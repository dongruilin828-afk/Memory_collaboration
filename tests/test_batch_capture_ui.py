"""First-stage batch entry keeps normal settings and uses the UI queue."""

import tempfile
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
                    dialog.deiconify()
                    width, height = dialog.minsize()
                    dialog.geometry(f"{width}x{height}")
                    dialog.update()
                    self.assertGreaterEqual(dialog.start_button.winfo_width(), dialog.start_button.winfo_reqwidth())
                    self.assertLessEqual(dialog.start_button.winfo_rootx() + dialog.start_button.winfo_width(),
                                         dialog.winfo_rootx() + dialog.winfo_width())
                    self.assertLessEqual(dialog.close_button.winfo_rooty() + dialog.close_button.winfo_height(),
                                         dialog.winfo_rooty() + dialog.winfo_height())
                    dialog.start_or_stop()
                    self.assertTrue(dialog.running)
                    self.assertEqual(dialog.links.cget("state"), "disabled")
                    self.assertEqual(len(start.call_args.args[0]), 2)
                    dialog.close()
                    stop.assert_called_once()
                    dialog.finish("已停止")
                    self.assertFalse(dialog.winfo_exists())
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
                options["progress"](1, 1, "抓取完成")
                record = dict(index=1, status="completed", platform="DeepSeek", warnings=[],
                              elapsed_seconds=1.25, saved_files=[str(output/"001/export.md")], output_dir=str(output/"001"))
                options["on_result"](record)
                return [record]

            with patch("gui.app.filedialog.askdirectory", return_value=temporary), patch("gui.batch_capture.capture_links", capture):
                self.assertTrue(app._start_batch_capture(["https://chat.deepseek.com/share/test"], dialog))
                self.assertTrue(finished.wait(5))
            app._on_task_finished.assert_called_once()
            app._add_history_record.assert_called_once()
            history = app._add_history_record.call_args.args[0]
            self.assertEqual(history["fetch_seconds"], 1.25)
            self.assertEqual(history["generation_seconds"], 0)
            self.assertIn("完成 1/1", dialog.finish.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
