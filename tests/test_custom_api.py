"""Custom endpoint routing, real local HTTP requests, and secret persistence."""
import json
import os
import tempfile
import threading
import unittest
from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gui.credential_store import WindowsCredentialStore, CredentialStoreError
from gui.service import gui_summary_attempt_configs, generate_output_bundle
from scripts import gemini_summarizer as summary
from scripts.api_config import normalize_custom_api
from tests import test_gui_api_keys as old_tests


def settings():
    return dict(name="我的接口", url="https://example.test/v1", model="my-model",
                protocol="openai", thinking_level="high")


class CustomAPISettingsTests(unittest.TestCase):
    def test_url_and_model_validation_keeps_credentials_out_of_config(self):
        values = settings()
        values.update(url="https://example.test/v1/chat/completions", api_key="secret")
        config = summary.custom_summary_config(values)
        self.assertEqual(config.api_base, "https://example.test/v1")
        self.assertNotIn("secret", json.dumps(asdict(config)))
        for url in ["file:///tmp/key", "ftp://host/v1", "host/v1", "https://u:p@host/v1",
                    "https://host/v1?key=secret", "https://host/v1#fragment", "https://host\n/v1"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_custom_api({**values, "url": url})
        for values in [{**values, "model": ""}, {**values, "request_timeout_seconds": "bad"},
                       {**values, "max_output_tokens": 0}, {**values, "protocol": "gemini", "thinking_level": "none"}]:
            with self.assertRaises(ValueError):
                normalize_custom_api(values)

    def test_credential_record_roundtrip_disable_and_failed_update(self):
        backend = old_tests.FakeCredentialBackend()
        store = WindowsCredentialStore(backend)
        store.save_custom_api(settings(), "private-custom-key")
        self.assertNotIn("api_key", store.load_custom_api())
        store.save_api_keys({"gemini": "builtin-key"})
        store.save_provider_order(["custom", "gemini"])
        self.assertEqual(list(store.load_api_keys()), ["custom", "gemini"])
        self.assertEqual(store.load_api_keys()["custom"], "private-custom-key")
        before = dict(backend.passwords)
        with patch.object(backend, "set_password", side_effect=RuntimeError("new-secret")):
            with self.assertRaises(CredentialStoreError) as raised:
                store.save_custom_api({**settings(), "url": "https://other.test/v1"}, "new-secret")
        self.assertNotIn("new-secret", str(raised.exception))
        self.assertEqual(backend.passwords, before)
        store.save_api_keys({"gemini": "builtin-key", "custom": ""})
        self.assertNotIn("custom", store.load_api_keys())
        self.assertEqual(store.load_custom_api()["url"], "https://example.test/v1")

    def test_custom_priority_and_fallback_isolate_endpoint_and_limits(self):
        custom = {**settings(), "max_output_tokens": 200000, "request_timeout_seconds": 19}
        candidates = gui_summary_attempt_configs(summary.SummaryConfig(),
            {"custom": "c", "gemini": "g"}, custom)
        self.assertEqual([(c.provider, c.model) for c in candidates],
                         [("custom", "my-model"), ("gemini", "gemini-3.8-flash")])
        self.assertEqual(candidates[0].api_base, "https://example.test/v1")
        self.assertEqual(candidates[0].request_timeout_seconds, 19)
        self.assertEqual(candidates[1].api_base, "")
        self.assertEqual(candidates[1].max_output_tokens, summary.DEFAULT_MAX_OUTPUT_TOKENS)

    def test_real_summary_entry_uses_custom_configuration_and_key(self):
        created = []
        def create(config, api_key=None):
            created.append((config, api_key))
            return object()
        with tempfile.TemporaryDirectory() as directory, patch.object(summary, "create_gateway", side_effect=create), \
                patch.object(summary, "summarize_conversation", side_effect=old_tests.GUIApiKeyRoutingTests._write_success):
            bundle = generate_output_bundle(
                [{"role": "User", "content": "question"}, {"role": "AI", "content": "answer"}],
                {"normal": True}, Path(directory), api_keys={"custom": "correct-secret"},
                custom_api=settings(),
            )
        self.assertTrue(bundle.saved_files)
        config, key = created[0]
        self.assertEqual(key, "correct-secret")
        self.assertEqual(config.provider, "custom")
        self.assertEqual((config.api_name, config.model, config.thinking_level), ("我的接口", "my-model", "high"))

    def test_native_protocol_and_38_legacy_thinking_are_sent_to_sdk(self):
        from google import genai
        calls = {}
        def generate(**kwargs):
            calls.update(kwargs)
            return SimpleNamespace(text='{"ok": true}')
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        values = {**settings(), "protocol": "gemini", "thinking_level": "low",
                  "url": "https://native.example.test", "model": summary.DEFAULT_MODEL}
        config = replace(summary.custom_summary_config(values), thinking_level="minimal")
        with patch.object(genai, "Client", return_value=client) as factory:
            gateway = summary.create_gateway(config, api_key="native-placeholder")
            self.assertEqual(gateway.generate_json("test", {"type": "object"}), {"ok": True})
        self.assertEqual(factory.call_args.kwargs["http_options"].base_url, "https://native.example.test")
        self.assertEqual(calls["model"], "gemini-3.8-flash")
        self.assertEqual(calls["config"].thinking_config.thinking_level.value.lower(), "low")

    def test_retired_environment_model_is_migrated(self):
        for model in ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.7-flash"]:
            with patch.dict(os.environ, {"SUMMARY_PROVIDER": "gemini", "SUMMARY_MODEL": model}, clear=True):
                self.assertEqual(summary.SummaryConfig.from_env().model, "gemini-3.8-flash")

    def test_custom_native_never_uses_builtin_environment_key(self):
        config = summary.custom_summary_config({**settings(), "protocol": "gemini"})
        with patch.dict(os.environ, {"GEMINI_API_KEY": "builtin-secret"}), self.assertRaises(summary.GeminiSummaryError):
            summary.create_gateway(config)

    def test_actual_gemini_sdk_preserves_json_schema_wire_keys(self):
        import httpx
        from google import genai
        from google.genai import types
        requests = []
        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"candidates": [{"content": {
                "role": "model", "parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}]})
        client = genai.Client(api_key="placeholder", http_options=types.HttpOptions(
            base_url="https://native.example.test", httpx_client=httpx.Client(transport=httpx.MockTransport(respond))))
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "additionalProperties": False}
        try:
            with patch.object(genai, "Client", return_value=client):
                gateway = summary.GeminiGateway(summary.SummaryConfig(retries=1), api_key="placeholder")
            self.assertEqual(gateway.generate_json("test", schema), {"ok": True})
        finally:
            client.close()
        self.assertEqual(requests[0]["generationConfig"]["responseJsonSchema"], schema)
        self.assertNotIn("responseSchema", requests[0]["generationConfig"])

    def test_native_error_detail_redacts_the_supplied_secret(self):
        from google import genai
        class Rejected(Exception):
            code = 400
            status = "INVALID_ARGUMENT"
            message = "bad parameter with private-placeholder-key"
        client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **_k: (_ for _ in ()).throw(Rejected())))
        with patch.object(genai, "Client", return_value=client):
            gateway = summary.GeminiGateway(summary.SummaryConfig(retries=1), api_key="private-placeholder-key")
        with self.assertRaises(summary.GeminiSummaryError) as raised:
            gateway.generate_json("test", {"type": "object"})
        self.assertIn("bad parameter", str(raised.exception))
        self.assertNotIn("private-placeholder-key", str(raised.exception))


class CustomAPIHTTPTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.status = 200
        self.redirect = False
        self.response = {"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}]}
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append((self.path, dict(self.headers), payload))
                if owner.redirect:
                    self.send_response(302)
                    self.send_header("Location", f"http://localhost:{owner.server.server_port}/sink")
                    self.end_headers()
                    return
                self.send_response(owner.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(owner.response).encode())
            def do_GET(self):
                owner.requests.append((self.path, dict(self.headers), None))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(owner.response).encode())
            def log_message(self, *_args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.values = {**settings(), "url": f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions"}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def test_connection_uses_real_post_auth_model_and_json_modes(self):
        for mode in ["json_object", "json_schema", "prompt"]:
            config = summary.custom_summary_config({**self.values, "json_mode": mode})
            message = summary.test_api_connection(config, "placeholder-secret")
            path, headers, payload = self.requests[-1]
            self.assertEqual(path, "/v1/chat/completions")
            self.assertEqual(headers["Authorization"], "Bearer placeholder-secret")
            self.assertEqual(payload["model"], "my-model")
            self.assertEqual(payload["reasoning_effort"], "high")
            self.assertLess(len(payload["messages"][0]["content"]), 100)
            self.assertTrue(message.startswith("连接成功"))
            if mode == "prompt":
                self.assertNotIn("response_format", payload)
            else:
                self.assertEqual(payload["response_format"]["type"], mode)
        config = summary.custom_summary_config({**self.values, "thinking_level": "auto"})
        summary.test_api_connection(config, "placeholder-secret")
        self.assertNotIn("reasoning_effort", self.requests[-1][2])

    def test_redirect_never_forwards_the_custom_authorization(self):
        self.redirect = True
        summary.test_api_connection(summary.custom_summary_config(self.values), "placeholder-secret")
        self.assertEqual(self.requests[-1][0], "/sink")
        self.assertNotIn("Authorization", self.requests[-1][1])

    def test_bad_auth_wrong_json_and_truncation_cannot_pass_connection(self):
        config = summary.custom_summary_config(self.values)
        self.status = 401
        self.response = {"error": {"message": "invalid placeholder-secret"}}
        with self.assertRaises(summary.GeminiSummaryError) as raised:
            summary.test_api_connection(config, "placeholder-secret")
        self.assertNotIn("placeholder-secret", str(raised.exception))
        self.assertIn("401", str(raised.exception))
        self.status = 200
        for content, finish in [('{}', 'stop'), ('{"ok": true}', 'length'), ('not json', 'stop')]:
            self.response = {"choices": [{"message": {"content": content}, "finish_reason": finish}]}
            with self.assertRaises(summary.GeminiSummaryError):
                summary.test_api_connection(config, "placeholder-secret")


if __name__ == "__main__":
    unittest.main()
