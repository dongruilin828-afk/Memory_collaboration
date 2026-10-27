"""Cancelling requests must close their clients before another run can start."""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from scripts import gemini_summarizer as summary


class SummaryCancellationTests(unittest.TestCase):
    def run_worker(self, gateway):
        outcome = []

        def request():
            try:
                outcome.append(gateway.generate_json("test", {"type": "object"}))
            except BaseException as error:
                outcome.append(error)

        worker = threading.Thread(target=request, daemon=True)
        worker.start()
        return worker, outcome

    def test_openai_compatible_cancellation_closes_transport_before_restart(self):
        for provider in ("deepseek", "siliconflow", "custom"):
            with self.subTest(provider=provider):
                entered, request_cleaned, client_closed = (
                    threading.Event(), threading.Event(), threading.Event(),
                )
                cancel = threading.Event()
                calls = []

                class Transport(httpx.AsyncBaseTransport):
                    async def handle_async_request(self, request):
                        calls.append(request)
                        entered.set()
                        try:
                            await asyncio.Event().wait()
                        finally:
                            # Exposes a second cancellation interrupting cleanup.
                            await asyncio.sleep(0.03)
                            request_cleaned.set()

                    async def aclose(self):
                        await asyncio.sleep(0.03)
                        client_closed.set()

                original_client = httpx.AsyncClient
                config = summary.SummaryConfig(
                    provider=provider, api_base="https://example.test/v1", retries=3,
                )
                gateway = summary.create_gateway(config, api_key="placeholder", cancel_event=cancel)
                with patch.object(httpx, "AsyncClient", side_effect=lambda **kwargs: original_client(
                    transport=Transport(), **kwargs,
                )):
                    worker, outcome = self.run_worker(gateway)
                    try:
                        self.assertTrue(entered.wait(3))
                        cancel.set()
                        worker.join(3)
                        self.assertFalse(worker.is_alive())
                        self.assertIsInstance(outcome[0], asyncio.CancelledError)
                        self.assertTrue(request_cleaned.is_set())
                        self.assertTrue(client_closed.is_set())
                        self.assertEqual(len(calls), 1)
                    finally:
                        cancel.set()
                        worker.join(3)

                def response(request):
                    return httpx.Response(200, json={
                        "choices": [{"message": {"content": '{"ok": true}'}}],
                    })

                fresh = summary.create_gateway(config, api_key="placeholder", cancel_event=threading.Event())
                with patch.object(httpx, "AsyncClient", side_effect=lambda **kwargs: original_client(
                    transport=httpx.MockTransport(response), **kwargs,
                )):
                    self.assertEqual(fresh.generate_json("test", {}), {"ok": True})

    def test_gemini_cancellation_closes_both_sdk_clients_before_restart(self):
        from google import genai

        entered, cleaned, async_closed, sync_closed = (
            threading.Event(), threading.Event(), threading.Event(), threading.Event(),
        )
        cancel = threading.Event()
        calls = []
        options = []
        success = [False]

        class AsyncClient:
            def __init__(self):
                self.models = self

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                await asyncio.sleep(0.03)
                async_closed.set()

            async def generate_content(self, **kwargs):
                calls.append(kwargs)
                if success[0]:
                    return SimpleNamespace(text='{"ok": true}')
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    await asyncio.sleep(0.03)
                    cleaned.set()

        def client(**kwargs):
            options.append(kwargs["http_options"])
            return SimpleNamespace(aio=AsyncClient(), close=sync_closed.set)

        with patch.object(genai, "Client", side_effect=client):
            gateway = summary.create_gateway(
                summary.SummaryConfig(retries=3), api_key="placeholder", cancel_event=cancel,
            )
            worker, outcome = self.run_worker(gateway)
            try:
                self.assertTrue(entered.wait(3))
                cancel.set()
                worker.join(3)
                self.assertFalse(worker.is_alive())
                self.assertIsInstance(outcome[0], asyncio.CancelledError)
                self.assertTrue(cleaned.is_set())
                self.assertTrue(async_closed.is_set())
                self.assertTrue(sync_closed.is_set())
                self.assertEqual(len(calls), 1)
                self.assertEqual(options[0].retry_options.attempts, 1)
            finally:
                cancel.set()
                worker.join(3)
            success[0] = True
            fresh = summary.create_gateway(
                summary.SummaryConfig(), api_key="placeholder", cancel_event=threading.Event(),
            )
            self.assertEqual(fresh.generate_json("test", {}), {"ok": True})

    def test_stop_interrupts_rate_limit_wait_without_another_attempt(self):
        class CancelEvent(threading.Event):
            def __init__(self):
                super().__init__()
                self.waiting = threading.Event()

            def wait(self, timeout=None):
                self.waiting.set()
                return super().wait(timeout)

        class RateLimitError(RuntimeError):
            code = 429

        for provider in ("gemini", "deepseek"):
            with self.subTest(provider=provider):
                cancel = CancelEvent()
                config = summary.SummaryConfig(provider=provider, retries=3, rate_limit_wait_seconds=65)
                gateway = summary.create_gateway(config, api_key="placeholder", cancel_event=cancel)
                calls = []

                async def fail(*_args):
                    calls.append(True)
                    raise RateLimitError()

                attribute = "_generate_async" if provider == "gemini" else "_request_async"
                with patch.object(gateway, attribute, side_effect=fail):
                    worker, outcome = self.run_worker(gateway)
                    try:
                        self.assertTrue(cancel.waiting.wait(3))
                        cancel.set()
                        worker.join(3)
                        self.assertFalse(worker.is_alive())
                        self.assertIsInstance(outcome[0], asyncio.CancelledError)
                        self.assertEqual(len(calls), 1)
                    finally:
                        cancel.set()
                        worker.join(3)

    def test_async_http_errors_preserve_status_redaction_and_no_auth_retry(self):
        client = httpx.AsyncClient
        calls = []

        def fail(request):
            calls.append(request)
            return httpx.Response(401, json={"error": {"message": "Invalid placeholder-secret"}})

        gateway = summary.create_gateway(
            summary.SummaryConfig(provider="deepseek", retries=3),
            api_key="placeholder-secret", cancel_event=threading.Event(),
        )
        with patch.object(httpx, "AsyncClient", side_effect=lambda **kwargs: client(
            transport=httpx.MockTransport(fail), **kwargs,
        )):
            with self.assertRaises(summary.GeminiSummaryError) as raised:
                gateway.generate_json("test", {})
        self.assertNotIn("placeholder-secret", str(raised.exception))
        self.assertEqual(gateway._last_status_code, 401)
        self.assertEqual(len(calls), 1)

    def test_custom_redirect_does_not_forward_credentials_even_on_same_origin(self):
        client = httpx.AsyncClient
        for destination in ("https://example.test/redirect", "https://other.test/redirect"):
            with self.subTest(destination=destination):
                calls = []

                def response(request):
                    calls.append(request)
                    if len(calls) == 1:
                        return httpx.Response(302, headers={"location": destination})
                    return httpx.Response(200, json={
                        "choices": [{"message": {"content": '{"ok": true}'}}],
                    })

                gateway = summary.create_gateway(summary.SummaryConfig(
                    provider="custom", api_base="https://example.test/v1",
                ), api_key="placeholder-secret", cancel_event=threading.Event())
                with patch.object(httpx, "AsyncClient", side_effect=lambda **kwargs: client(
                    transport=httpx.MockTransport(response), **kwargs,
                )):
                    self.assertEqual(gateway.generate_json("test", {}), {"ok": True})
                self.assertEqual(calls[0].headers.get("authorization"), "Bearer placeholder-secret")
                self.assertIsNone(calls[1].headers.get("authorization"))

    def test_async_timeouts_keep_recoverable_timeout_message_and_redact_key(self):
        for provider in ("gemini", "deepseek"):
            with self.subTest(provider=provider):
                gateway = summary.create_gateway(summary.SummaryConfig(
                    provider=provider, retries=1, request_timeout_seconds=37,
                ), api_key="placeholder-secret", cancel_event=threading.Event())

                async def timeout(*_args):
                    raise httpx.ReadTimeout("placeholder-secret")

                attribute = "_generate_async" if provider == "gemini" else "_request_async"
                with patch.object(gateway, attribute, side_effect=timeout):
                    with self.assertRaises(summary.SummaryRequestTimeoutError) as raised:
                        gateway.generate_json("test", {})
                self.assertIn("37 秒", str(raised.exception))
                self.assertNotIn("placeholder-secret", str(raised.exception))

    def test_hanging_local_http_connection_disconnects_and_immediately_restarts(self):
        for protocol in ("openai", "gemini"):
            with self.subTest(protocol=protocol):
                self._check_hanging_connection(protocol)

    def _check_hanging_connection(self, protocol):
        entered, disconnected = threading.Event(), threading.Event()
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                calls.append(self.path)
                if len(calls) == 1:
                    entered.set()
                    self.connection.settimeout(3)
                    if self.connection.recv(1) == b"":
                        disconnected.set()
                    return
                result = (
                    {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}], "role": "model"}, "finishReason": "STOP"}]}
                    if protocol == "gemini"
                    else {"choices": [{"message": {"content": '{"ok": true}'}}]}
                )
                body = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        cancel = threading.Event()
        config = summary.SummaryConfig(
            provider="custom", api_protocol=protocol, retries=3,
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
        )
        gateway = summary.create_gateway(config, api_key="placeholder", cancel_event=cancel)
        worker, outcome = self.run_worker(gateway)
        try:
            self.assertTrue(entered.wait(3))
            cancel.set()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertIsInstance(outcome[0], asyncio.CancelledError)
            self.assertTrue(disconnected.wait(3))
            self.assertEqual(len(calls), 1)
            fresh = summary.create_gateway(config, api_key="placeholder", cancel_event=threading.Event())
            self.assertEqual(fresh.generate_json("test", {}), {"ok": True})
            self.assertEqual(calls, [calls[0], calls[0]])
        finally:
            cancel.set()
            worker.join(3)
            server.shutdown()
            server.server_close()
            serving.join(3)


if __name__ == "__main__":
    unittest.main()
