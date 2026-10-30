"""First-stage batch entry keeps normal settings and uses the UI queue."""

import tempfile
import asyncio
import threading
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui.app import AIMemoryGUI
from gui.batch_capture_dialog import BatchCaptureDialog
from gui.settings_store import AppSettings


class BatchDialogTests(unittest.TestCase):
    def test_login_reply_from_ui_thread_wakes_worker_without_blocking_loop(self):
        app = object.__new__(AIMemoryGUI)
        ui = []
        app._post_ui = lambda callback, **_options: ui.append(callback)
        dialog = Mock()
        async def exercise():
            task = asyncio.create_task(app._await_batch_login(dialog, 'https://chatgpt.com/c/exact'))
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            ui.pop(0)()
            reply = dialog.request_login.call_args.args[1]
            sender = threading.Thread(target=reply, args=(True,))
            sender.start()
            sender.join()
            self.assertTrue(await asyncio.wait_for(task, 1))
            ui.pop(0)()
        asyncio.run(exercise())

    def test_login_buttons_complete_skip_stop_and_keep_visible_bounds(self):
        root = tk.Tk()
        root.attributes('-alpha', 0.0)
        try:
            for scale in (1.0, 1.5, 2.0):
                root.tk.call('tk', 'scaling', scale)
                stop, reply = Mock(), Mock()
                dialog = BatchCaptureDialog(root, on_start=Mock(), on_stop=stop)
                for text, accepted in (('已完成授权，继续', True), ('跳过此项', False), ('停止全部', None)):
                    login = dialog.request_login('https://chatgpt.com/c/exact', reply)
                    login.attributes('-alpha', 0.0)
                    width, height = login.minsize()
                    login.geometry(f'{width}x{height}')
                    login.update()
                    buttons = login.winfo_children()[0].winfo_children()[1].winfo_children()
                    for button in buttons:
                        self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
                        self.assertLessEqual(button.winfo_rootx()+button.winfo_width(), login.winfo_rootx()+login.winfo_width())
                    next(button for button in buttons if button.cget('text') == text).invoke()
                    if accepted is None:
                        stop.assert_called_once()
                        login.destroy()
                    else:
                        self.assertEqual(reply.call_args.args, (accepted,))
                dialog.destroy()
        finally:
            root.destroy()

    def test_late_login_reply_after_worker_loop_closed_is_ignored(self):
        app = object.__new__(AIMemoryGUI)
        ui = []
        app._post_ui = lambda callback, **_options: ui.append(callback)
        dialog = Mock()
        child = Mock()
        dialog.request_login.return_value = child
        async def exercise():
            task = asyncio.create_task(app._await_batch_login(dialog, 'https://chatgpt.com/c/exact'))
            await asyncio.sleep(0)
            ui.pop(0)()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(exercise())
        reply = dialog.request_login.call_args.args[1]
        reply(True)
        ui.pop(0)()
        child.destroy.assert_called_once()

    def test_validation_start_stop_and_minimum_geometry_at_different_scales(self):
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        root.update()
        try:
            for scale in (1.0, 1.5, 2.0):
                with self.subTest(scale=scale):
                    root.tk.call("tk", "scaling", scale)
                    start, stop = Mock(return_value=True), Mock()
                    dialog = BatchCaptureDialog(root, on_start=start, on_stop=stop, initial_text="C:/local.md")
                    dialog.attributes("-alpha", 0.0)
                    dialog.start_or_stop()
                    start.assert_not_called()
                    self.assertIn("不支持文件", dialog.status.cget("text"))
                    dialog.links.delete("1.0", "end")
                    dialog.links.insert("1.0", "https://chat.deepseek.com/share/first\nhttps://chatgpt.com/share/second")
                    self.assertEqual(dialog.concurrency_var.get(), 3)
                    dialog.concurrency_box.invoke("buttondown")
                    self.assertEqual(dialog.concurrency_var.get(), 2)
                    dialog.deiconify()
                    width, height = dialog.minsize()
                    dialog.geometry(f"{width}x{height}")
                    dialog.update()
                    self.assertGreaterEqual(dialog.start_button.winfo_width(), dialog.start_button.winfo_reqwidth())
                    self.assertLessEqual(dialog.start_button.winfo_rootx() + dialog.start_button.winfo_width(),
                                         dialog.winfo_rootx() + dialog.winfo_width())
                    self.assertLessEqual(dialog.close_button.winfo_rooty() + dialog.close_button.winfo_height(),
                                         dialog.winfo_rooty() + dialog.winfo_height())
                    self.assertGreaterEqual(dialog.concurrency_box.winfo_width(), dialog.concurrency_box.winfo_reqwidth())
                    self.assertLessEqual(dialog.concurrency_box.winfo_rootx() + dialog.concurrency_box.winfo_width(),
                                         dialog.winfo_rootx() + dialog.winfo_width())
                    dialog.start_or_stop()
                    self.assertTrue(dialog.running)
                    self.assertEqual(dialog.links.cget("state"), "disabled")
                    self.assertEqual(len(start.call_args.args[0]), 2)
                    self.assertEqual(start.call_args.kwargs["concurrency"], 2)
                    self.assertEqual(dialog.concurrency_box.cget("state"), "disabled")
                    dialog.concurrency_box.invoke("buttonup")
                    self.assertEqual(dialog.concurrency_var.get(), 2)
                    dialog.finish("已完成")
                    self.assertEqual(dialog.concurrency_box.cget("state"), "normal")
                    dialog.concurrency_var.set(9)
                    dialog.concurrency_box.invoke("buttonup")
                    dialog.start_or_stop()
                    self.assertEqual(start.call_args.kwargs["concurrency"], 10)
                    dialog.close()
                    stop.assert_called_once()
                    dialog.finish("已停止")
                    self.assertFalse(dialog.winfo_exists())
        finally:
            root.destroy()

    def test_capture_dialog_rejects_out_of_range_and_noninteger_limits(self):
        root = tk.Tk()
        root.attributes("-alpha", 0)
        try:
            start = Mock(return_value=True)
            dialog = BatchCaptureDialog(root, on_start=start, on_stop=Mock(), initial_text="https://chatgpt.com/c/ten")
            dialog.attributes("-alpha", 0)
            for value in ("0", "11", "2.5", ""):
                dialog.concurrency_box.delete(0, "end")
                dialog.concurrency_box.insert(0, value)
                dialog.start_or_stop()
                self.assertIn("1～10", dialog.status.cget("text"))
                self.assertFalse(dialog.running)
            start.assert_not_called()
            dialog.destroy()
        finally:
            root.destroy()

    def test_gui_batch_uses_snapshot_and_keeps_completed_items_in_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = object.__new__(AIMemoryGUI)
            app.is_running = False
            settings = AppSettings(Path(temporary)/"runtime", Path(temporary))
            app.app_settings = settings
            app._set_inputs_locked = Mock()
            app._update_generate_button_state = Mock()
            app._add_history_record = Mock()
            app._on_task_finished = Mock()
            app._post_ui = lambda callback, **_options: callback()
            finished = threading.Event()
            dialog = SimpleNamespace(show_progress=Mock(), finish=Mock(side_effect=lambda _: finished.set()))

            async def capture(links, output, **options):
                self.assertEqual(links, ["https://chat.deepseek.com/share/test"])
                self.assertEqual(options["browser_profile_root"], settings.browser_profile_dir)
                self.assertIs(options["cancel_event"], app._generation_cancel_event)
                self.assertEqual(options["concurrency"], 2)
                options["progress"](1, 1, "抓取完成")
                record = dict(index=1, status="completed", platform="DeepSeek", warnings=[],
                              elapsed_seconds=1.25, saved_files=[str(output/"001/export.md")], output_dir=str(output/"001"))
                options["on_result"](record)
                return [record]

            with patch("gui.app.filedialog.askdirectory", return_value=temporary), patch("gui.batch_capture.capture_links", capture):
                self.assertTrue(app._start_batch_capture(["https://chat.deepseek.com/share/test"], dialog, concurrency=2))
                self.assertTrue(finished.wait(5))
            app._on_task_finished.assert_called_once()
            app._add_history_record.assert_called_once()
            history = app._add_history_record.call_args.args[0]
            self.assertEqual(history["fetch_seconds"], 1.25)
            self.assertEqual(history["generation_seconds"], 0)
            self.assertIn("完成 1/1", dialog.finish.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
