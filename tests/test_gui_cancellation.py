"""Generation cancellation must stop work and suppress queued success UI."""

import asyncio
import os
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui.app import AIMemoryGUI
from gui.service import FetchResult, _close_browser_context_safely, generate_output_bundle
from gui.settings_store import AppSettings


class GenerationCancellationTests(unittest.TestCase):
    def make_app(self):
        app = object.__new__(AIMemoryGUI)
        app.is_running = True
        app._generation_cancel_event = threading.Event()
        app.btn_generate = Mock()
        app.status_var = Mock()
        app.percent_var = Mock()
        app.progress_bar = Mock()
        app._on_task_finished = Mock()
        app._show_completed_badge = Mock()
        app._add_history_record = Mock()
        app._confirm_login_required = Mock()
        app._request_attachment_web_link = Mock()
        callbacks = queue.SimpleQueue()
        app._post_ui = lambda callback, **kwargs: callbacks.put(callback)
        return app, callbacks

    def drain(self, callbacks):
        while not callbacks.empty():
            callbacks.get_nowait()()

    def test_running_button_requests_stop_and_rejects_repeated_clicks(self):
        app, callbacks = self.make_app()
        app._update_generate_button_state()
        self.assertEqual(app.btn_generate._text, "停止生成")
        app.btn_generate.set_enabled.assert_called_with(True)
        app._on_start_generate()
        self.assertTrue(app._generation_cancel_event.is_set())
        app.progress_bar.reset.assert_called_once()
        app.percent_var.set.assert_called_with("0%")
        self.assertEqual(app.btn_generate._text, "正在停止…")
        app.btn_generate.set_enabled.assert_called_with(False)
        app.status_var.reset_mock()
        app._on_start_generate()
        app.status_var.set.assert_not_called()

    def test_stop_cancels_fetch_and_runs_cleanup_without_generating_outputs(self):
        app, callbacks = self.make_app()
        entered, cleaned = threading.Event(), threading.Event()

        async def fetch(**kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / "output") as temp:
            with patch("gui.app.fetch_chat_pipeline", side_effect=fetch), patch(
                "gui.app.generate_output_bundle"
            ) as generate, patch("gui.app.messagebox.showerror") as error:
                worker = threading.Thread(target=app._run_generation_task, args=(
                    "https://example.com/share", False, {"raw": True},
                    Path(temp), "cancelled.md", {}, AppSettings(Path(temp) / "runtime"),
                ), daemon=True)
                worker.start()
                try:
                    self.assertTrue(entered.wait(3))
                    app._on_start_generate()
                    worker.join(3)
                    self.assertFalse(worker.is_alive())
                    self.assertTrue(cleaned.is_set())
                    self.drain(callbacks)
                    generate.assert_not_called()
                    error.assert_not_called()
                    app._show_completed_badge.assert_not_called()
                    app._add_history_record.assert_not_called()
                    app._on_task_finished.assert_called_once()
                    app.status_var.set.assert_called_with("已停止生成")
                finally:
                    app._on_stop_generate()
                    worker.join(3)

    def test_stop_during_sync_generation_checks_before_following_steps(self):
        app, callbacks = self.make_app()
        entered, release = threading.Event(), threading.Event()

        async def fetch(**kwargs):
            return FetchResult(html="", image_map={}, messages=[
                {"role": "User", "content": "test"},
            ])

        def generate(**kwargs):
            self.assertIs(kwargs["cancel_event"], app._generation_cancel_event)
            entered.set()
            release.wait(3)
            kwargs["cancel_check"]()
            self.fail("Cancelled generation continued")

        with tempfile.TemporaryDirectory(dir=Path.cwd() / "output") as temp:
            with patch("gui.app.fetch_chat_pipeline", side_effect=fetch), patch(
                "gui.app.generate_output_bundle", side_effect=generate,
            ), patch("gui.app.messagebox.showerror") as error:
                worker = threading.Thread(target=app._run_generation_task, args=(
                    "https://example.com/share", False, {"normal": True},
                    Path(temp), "cancelled.md", {}, AppSettings(Path(temp) / "runtime"),
                ), daemon=True)
                worker.start()
                try:
                    self.assertTrue(entered.wait(3))
                    app._on_start_generate()
                    release.set()
                    worker.join(3)
                    self.assertFalse(worker.is_alive())
                    self.drain(callbacks)
                    error.assert_not_called()
                    app._show_completed_badge.assert_not_called()
                    app._add_history_record.assert_not_called()
                    app._on_task_finished.assert_called_once()
                    app.status_var.set.assert_called_with("已停止生成")
                finally:
                    release.set()
                    worker.join(3)

    def test_cancel_releases_user_wait_and_suppresses_deferred_dialog(self):
        app, callbacks = self.make_app()
        app._ui_dispatcher = SimpleNamespace(closed=threading.Event())
        dialog = Mock()
        app._post_generation_ui(dialog, visible=True)
        app._on_stop_generate()
        self.drain(callbacks)
        dialog.assert_not_called()
        with self.assertRaises(asyncio.CancelledError):
            app._wait_for_generation_event(threading.Event())

    def test_cleanup_logging_cannot_cancel_close_a_second_time(self):
        app, callbacks = self.make_app()
        entered, closing, cleaned, release = (threading.Event() for _ in range(4))

        async def fetch(**kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closing.set()
                # A cleanup log after Stop used to raise a second CancelledError.
                kwargs["logger"]("正在关闭浏览器")
                while not release.is_set():
                    await asyncio.sleep(0.01)
                cleaned.set()

        with tempfile.TemporaryDirectory(dir=Path.cwd() / "output") as temp:
            with patch("gui.app.fetch_chat_pipeline", side_effect=fetch):
                worker = threading.Thread(target=app._run_generation_task, args=(
                    "https://example.com/share", False, {"raw": True}, Path(temp),
                    "stopped.md", {}, AppSettings(Path(temp) / "runtime"),
                ), daemon=True)
                worker.start()
                try:
                    self.assertTrue(entered.wait(3))
                    app._on_stop_generate()
                    self.assertTrue(closing.wait(3))
                    self.drain(callbacks)
                    app._on_task_finished.assert_not_called()
                    app._on_stop_generate()
                    release.set()
                    worker.join(3)
                    self.assertFalse(worker.is_alive())
                    self.assertTrue(cleaned.is_set())
                    self.drain(callbacks)
                    app._on_task_finished.assert_called_once()
                finally:
                    release.set()
                    worker.join(3)

    def test_stop_while_browser_is_already_closing_waits_for_close(self):
        async def scenario():
            closing, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

            class Context:
                async def close(self):
                    closing.set()
                    await release.wait()
                    closed.set()

            task = asyncio.create_task(_close_browser_context_safely(Context(), []))
            await closing.wait()
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(closed.is_set())

        asyncio.run(scenario())

    def test_cancel_event_reaches_media_and_text_and_prevents_provider_fallback(self):
        from scripts.gemini_summarizer import SummaryRequestTimeoutError

        for platform in (None, "doubao"):
            with self.subTest(platform=platform):
                cancel = threading.Event()
                gateways = []

                def create(config, api_key=None, cancel_event=None):
                    self.assertIs(cancel_event, cancel)
                    gateway = SimpleNamespace(cancel_event=cancel_event)
                    gateways.append(gateway)
                    return gateway

                def summarize(**kwargs):
                    self.assertIs(kwargs["gateway"].cancel_event, cancel)
                    cancel.set()
                    # A timeout racing a stop must not initiate a fallback call.
                    raise SummaryRequestTimeoutError("offline timeout")

                with tempfile.TemporaryDirectory(dir=Path.cwd() / "output") as temp:
                    with patch("scripts.gemini_summarizer.create_gateway", side_effect=create), patch(
                        "scripts.gemini_summarizer.summarize_conversation", side_effect=summarize,
                    ):
                        with self.assertRaises(asyncio.CancelledError):
                            generate_output_bundle(
                                [{"role": "User", "content": "test"}], {"normal": True},
                                Path(temp), api_keys={"deepseek": "test", "siliconflow": "test"},
                                source_platform=platform, cancel_event=cancel,
                            )
                self.assertEqual(len(gateways), 2 if platform == "doubao" else 1)

    @unittest.skipUnless(os.getenv("AI_MEMORY_BROWSER_SMOKE") == "1", "opt-in real browser check")
    def test_stop_then_immediately_reopen_real_persistent_browser(self):
        from playwright.async_api import async_playwright

        app, callbacks = self.make_app()
        entered, closed = threading.Event(), threading.Event()
        attempts = []

        with tempfile.TemporaryDirectory(dir=Path.cwd() / "output") as temp:
            profile = Path(temp) / "browser-profile"

            async def fetch(**kwargs):
                async with async_playwright() as playwright:
                    options = {} if Path(playwright.chromium.executable_path).exists() else {"channel": "msedge"}
                    context = await playwright.chromium.launch_persistent_context(
                        str(profile), headless=True, **options,
                    )
                    try:
                        page = await context.new_page()
                        await page.goto("about:blank")
                        await page.set_content("<p>offline cancellation check</p>")
                        attempts.append(await page.locator("p").inner_text())
                        entered.set()
                        if len(attempts) == 1:
                            await asyncio.Event().wait()
                        return FetchResult(html="", image_map={}, messages=[
                            {"role": "User", "content": "offline cancellation check"},
                        ])
                    finally:
                        kwargs["logger"]("关闭离线测试浏览器")
                        await _close_browser_context_safely(context, [], kwargs["logger"])
                        closed.set()

            args = ("https://example.com/share", False, {"raw": True}, Path(temp),
                    "browser-check.md", {}, AppSettings(Path(temp) / "runtime"))
            with patch("gui.app.fetch_chat_pipeline", side_effect=fetch), patch(
                "gui.app.messagebox.showerror"
            ) as error:
                worker = threading.Thread(target=app._run_generation_task, args=args, daemon=True)
                worker.start()
                try:
                    self.assertTrue(entered.wait(15))
                    app._on_stop_generate()
                    worker.join(15)
                    self.assertFalse(worker.is_alive())
                    self.assertTrue(closed.is_set())
                    self.drain(callbacks)
                    app._add_history_record.assert_not_called()
                    app._generation_cancel_event = threading.Event()
                    # Reuse the exact profile as soon as cancellation finishes.
                    app._run_generation_task(*args)
                    self.drain(callbacks)
                    self.assertEqual(len(attempts), 2)
                    app._add_history_record.assert_called_once()
                    error.assert_not_called()
                finally:
                    app._on_stop_generate()
                    worker.join(15)


if __name__ == "__main__":
    unittest.main()
