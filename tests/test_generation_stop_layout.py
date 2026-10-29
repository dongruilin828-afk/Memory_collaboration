"""Long progress messages cannot shrink or hide generation action buttons."""

import tkinter as tk
import tkinter.font as tkfont
import unittest
from unittest.mock import patch

from gui.app import AIMemoryGUI
from gui.theme import GENERATE_BUTTON_LABEL, REGENERATE_BUTTON_LABEL
from scripts.api_config import middle_ellipsis
from tests import test_gui_layout as layouts


SCREENSHOT_MESSAGE = "图片资产处理完成：发现 1 个引用，去重并过滤装饰图后 1 个，成功下载或复用 1 个，耗时 0.0 秒。"
MESSAGES = (SCREENSHOT_MESSAGE, SCREENSHOT_MESSAGE * 2,
            "正在整理图片与文档：" + "非常长的附件名称_" * 100 + "，处理完成。")


class ProgressEllipsisTests(unittest.TestCase):
    def test_large_status_fits_without_excessive_font_measurements(self):
        measured = []
        def measure(text):
            measured.append(len(text))
            return len(text)
        text = "正在处理" + "图" * 100000 + "完成"
        displayed = middle_ellipsis(text, 32, measure)
        self.assertLessEqual(len(displayed), 32)
        self.assertTrue(displayed.startswith("正在处理"))
        self.assertTrue(displayed.endswith("完成"))
        self.assertLess(len(measured), 25)

    def test_tiny_space_does_not_draw_an_overflowing_ellipsis(self):
        self.assertEqual(middle_ellipsis("很长的状态", 0, len), "")
        self.assertEqual(middle_ellipsis("很长的状态", 1, len), "…")


class GenerationStopLayoutTests(unittest.TestCase):
    def setUp(self):
        self.root = None
        self.settings = None
        self.errors = []
        self.addCleanup(self.close_app)

    def make_app(self, scaling=4 / 3):
        self.close_app()
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.attributes("-alpha", 0)
        self.root.tk.call("tk", "scaling", scaling)
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.root.tk.call("set", "::stop_layout_errors", "")
        self.root.tk.call("proc", "bgerror", "message", "lappend ::stop_layout_errors $message")
        self.settings = layouts._SettingsStore()
        with patch("gui.app.WindowsCredentialStore", return_value=layouts._CredentialStore()), \
                patch("gui.app.WindowsAppSettingsStore", return_value=self.settings):
            self.app = AIMemoryGUI(self.root)
        self.app._show_page(1)
        self.root.geometry("1100x760")
        layouts.GUIResponsiveGeometryTests()._settle_resize(self.root, self.app)

    def close_app(self):
        if self.root is not None:
            self.root.destroy()
            self.root.tk.call("update")
            self.assertEqual(self.root.tk.splitlist(self.root.tk.call("set", "::stop_layout_errors")), ())
            self.root = None
        if self.settings is not None:
            self.settings.scratch.cleanup()
            self.settings = None
        self.assertEqual(self.errors, [])

    def state(self, name):
        self.app.is_running = name in {"running", "stopping"}
        self.app._generation_completed = name == "completed"
        self.app._generation_cancel_event.clear()
        if name == "stopping":
            self.app._generation_cancel_event.set()
        self.app._update_generate_button_state()
        expected = {"running": "停止生成", "stopping": "正在停止…",
                    "completed": REGENERATE_BUTTON_LABEL, "idle": GENERATE_BUTTON_LABEL}[name]
        self.assertEqual(self.app.btn_generate._text, expected)

    def test_status_padding_uses_tk_pixel_distances(self):
        self.make_app()
        self.app.status_label.configure(padx="2p", borderwidth="1p", highlightthickness="1p")
        self.app.status_var.set(SCREENSHOT_MESSAGE)
        self.root.update_idletasks()
        self.assertEqual(self.errors, [])
        self.assertTrue(self.app.status_label.cget("text"))

    def assert_layout(self, raw):
        self.root.update_idletasks()
        button = self.app.btn_generate
        row = self.app._generation_run_row
        status = self.app.status_label
        self.assertTrue(button.winfo_ismapped())
        self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
        self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight())
        self.assertGreaterEqual(button.winfo_x(), 0)
        self.assertGreaterEqual(button.winfo_y(), 0)
        self.assertLessEqual(button.winfo_x() + button.winfo_width(), row.winfo_width())
        self.assertLessEqual(button.winfo_y() + button.winfo_height(), row.winfo_height())
        self.assertGreaterEqual(button.winfo_rootx(), self.app.bg_canvas.winfo_rootx())
        self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                             self.app.bg_canvas.winfo_rootx() + self.app.bg_canvas.winfo_width())
        self.assertLessEqual(status.winfo_rootx() + status.winfo_width(), button.winfo_rootx())
        for item in button.find_all():
            if button.type(item) == "text":
                left, top, right, bottom = button.bbox(item)
                self.assertGreaterEqual(left, 0)
                self.assertGreaterEqual(top, 0)
                self.assertLessEqual(right, button.winfo_width())
                self.assertLessEqual(bottom, button.winfo_height())
        self.assertEqual(self.app.status_var.get(), raw)
        self.assertEqual(self.app._generation_status_tooltip._text, raw)
        displayed = status.cget("text")
        self.assertLessEqual(tkfont.Font(font=status.cget("font")).measure(displayed), status.winfo_width())
        self.assertEqual(status.winfo_pixels(status.cget("wraplength")), 0)

    def test_long_messages_preserve_stop_and_other_actions_across_dpi_and_widths(self):
        for scaling in (1, 4 / 3, 2, 8 / 3):
            self.make_app(scaling)
            for width in (self.app.minimum_window_width, 1100, 1600):
                self.root.geometry(f"{width}x760")
                layouts.GUIResponsiveGeometryTests()._settle_resize(self.root, self.app)
                for state in ("running", "stopping", "completed", "idle"):
                    self.state(state)
                    for message in MESSAGES:
                        with self.subTest(scaling=scaling, width=width, state=state, chars=len(message)):
                            self.app.status_var.set(message)
                            self.app.percent_var.set("28%")
                            self.assert_layout(message)

    def test_long_message_does_not_increase_the_window_minimum(self):
        self.make_app()
        self.state("running")
        before_minimum = self.root.minsize()
        before_width = self.root.winfo_width()
        self.app.status_var.set(MESSAGES[-1])
        layouts.GUIResponsiveGeometryTests()._settle_resize(self.root, self.app)
        self.assertEqual(self.root.minsize(), before_minimum)
        self.assertEqual(self.root.winfo_width(), before_width)
        self.assert_layout(MESSAGES[-1])

    def test_rapid_progress_and_resize_keep_the_latest_message_and_button(self):
        self.make_app()
        self.state("running")
        for index in range(18):
            message = f"{index}：" + MESSAGES[index % len(MESSAGES)]
            self.app.status_var.set(message)
            self.root.geometry(f"{1100 + (index % 3) * 120}x760")
            self.root.update()
        layouts.GUIResponsiveGeometryTests()._settle_resize(self.root, self.app)
        self.assert_layout(message)

    def test_pending_progress_layout_is_safe_when_window_closes(self):
        self.make_app()
        self.state("running")
        for index in range(10):
            self.app.status_var.set(f"{index}：" + MESSAGES[-1])
        self.close_app()

    def test_visible_stop_button_still_requests_cancellation(self):
        self.make_app()
        self.state("running")
        self.app.status_var.set(SCREENSHOT_MESSAGE)
        self.assert_layout(SCREENSHOT_MESSAGE)
        self.app.btn_generate.invoke()
        self.assertTrue(self.app._generation_cancel_event.is_set())
        self.assertEqual(self.app.btn_generate._text, "正在停止…")
        self.assertFalse(self.app.btn_generate._enabled)
        self.assert_layout(self.app.status_var.get())


if __name__ == "__main__":
    unittest.main()
