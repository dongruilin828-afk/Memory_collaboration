"""Generation cancellation must stop work and suppress queued success UI."""

import asyncio
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui.app import AIMemoryGUI
from gui.service import FetchResult
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


if __name__ == "__main__":
    unittest.main()
