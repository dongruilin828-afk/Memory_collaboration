"""窗口最小化和 UI 消息调度的线程回归测试。"""

import gc
import threading
import tkinter as tk
import unittest
from types import SimpleNamespace

from gui.ui_dispatch import UIDispatcher, bind_visible_modal


class FakeRoot:
    def __init__(self):
        self.owner = threading.get_ident()
        self.window_state = "normal"
        self.errors = []
        self.scheduled = []

    def check_thread(self):
        if threading.get_ident() != self.owner:
            raise AssertionError("Tk called from worker thread")

    def after(self, delay, callback):
        self.check_thread()
        self.scheduled.append(callback)
        return len(self.scheduled)

    def after_cancel(self, identifier):
        self.check_thread()

    def bind(self, *args, **kwargs):
        self.check_thread()

    def state(self):
        self.check_thread()
        return self.window_state

    def winfo_viewable(self):
        self.check_thread()
        return self.window_state == "normal"

    def report_callback_exception(self, *error):
        self.errors.append(error)


class UIDispatcherTests(unittest.TestCase):
    def setUp(self):
        # 前一项 Tk 测试的 Font/Variable 析构也必须在主线程执行。
        gc.collect()
        self.root = FakeRoot()
        self.dispatcher = UIDispatcher(self.root)
        self.addCleanup(self.dispatcher.close)

    def test_worker_progress_does_not_wait_for_tk_even_when_minimized(self):
        self.root.window_state = "iconic"
        received, errors = [], []

        def worker():
            try:
                for index in range(300):
                    self.dispatcher.post(lambda value=index: received.append(
                        (value, threading.get_ident())
                    ))
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive(), "抓取线程被 Tk 调度阻塞")
        self.assertEqual(errors, [])
        self.assertEqual(received, [])
        for _ in range(5):
            self.dispatcher._drain()
        self.assertEqual(received, [(i, self.root.owner) for i in range(300)])

    def test_hidden_modal_waits_for_restore_without_blocking_progress(self):
        for state in ("iconic", "withdrawn"):
            with self.subTest(state=state):
                calls = []
                self.root.window_state = state
                self.dispatcher.post(lambda: calls.append("dialog"), visible=True)
                self.dispatcher.post(lambda: calls.append("progress"))
                self.dispatcher._drain()
                self.assertEqual(calls, ["progress"])
                self.root.window_state = "normal"
                self.dispatcher._drain()
                self.dispatcher._drain()
                self.assertEqual(calls, ["progress", "dialog"])

    def test_callback_failure_does_not_stop_future_updates(self):
        calls = []
        self.dispatcher.post(lambda: 1 / 0)
        self.dispatcher.post(lambda: calls.append("next"))
        self.dispatcher._drain()
        self.assertEqual(calls, ["next"])
        self.assertEqual(len(self.root.errors), 1)
        self.assertIsNotNone(self.dispatcher._after_id)

    def test_close_releases_waiting_worker_and_discards_callbacks(self):
        errors = []

        def worker():
            try:
                self.dispatcher.wait(threading.Event())
            except RuntimeError as error:
                errors.append(str(error))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.dispatcher.close()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.dispatcher.post(lambda: self.fail("closed callback executed"))
        self.dispatcher._drain()

    def test_child_destroy_does_not_stop_dispatcher(self):
        self.dispatcher._on_destroy(SimpleNamespace(widget=object()))
        self.assertFalse(self.dispatcher.closed.is_set())

    def test_real_tk_restore_delivers_deferred_dialog(self):
        root = tk.Tk()
        root.withdraw()
        dispatcher = UIDispatcher(root)
        try:
            calls = []
            dispatcher.post(lambda: calls.append("dialog"), visible=True)
            dispatcher.post(lambda: calls.append("progress"))
            dispatcher._drain()
            self.assertEqual(calls, ["progress"])
            root.deiconify()
            root.update_idletasks()
            dispatcher._drain()
            self.assertEqual(calls, ["progress", "dialog"])
        finally:
            dispatcher.close()
            root.destroy()

    def test_modal_releases_grab_when_hidden_and_reacquires_on_restore(self):
        root = tk.Tk()
        dialog = tk.Toplevel(root)
        dialog.transient(root)
        bind_visible_modal(dialog)
        try:
            root.update()
            self.assertIs(root.grab_current(), dialog)
            dialog.withdraw()
            root.update()
            self.assertIsNone(root.grab_current())
            dialog.deiconify()
            root.update()
            self.assertIs(root.grab_current(), dialog)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
