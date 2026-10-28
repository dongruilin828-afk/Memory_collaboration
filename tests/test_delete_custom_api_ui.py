"""Custom API deletion uses isolated vault records and never real credentials."""

import queue
import threading
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gui.app import AIMemoryGUI
from gui.credential_store import CredentialStoreError, WindowsCredentialStore
from tests.test_custom_api import settings
from tests.test_gui_api_keys import FakeCredentialBackend
from tests import test_gui_layout as layouts


SECOND = "custom_" + "a" * 32


class DeleteCustomAPIUITests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.attributes("-alpha", 0)
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.backend = FakeCredentialBackend()
        self.store = WindowsCredentialStore(self.backend)
        self.store.save_custom_api(settings(), "legacy-placeholder")
        self.store.save_custom_api({**settings(), "name": "第二个接口", "model": "second-model"},
                                   "second-placeholder", SECOND)
        self.store.save_api_keys({"gemini": "builtin-placeholder"})
        self.store.save_provider_order([SECOND, "custom", "gemini", "siliconflow", "deepseek"])
        self.settings_store = layouts._SettingsStore()
        self.addCleanup(self.settings_store.scratch.cleanup)
        self.addCleanup(self.close_root)
        self.app = self.build_app()
        self.page = self.app.page_frames[3]

    def close_root(self):
        self.root.update_idletasks()
        self.root.destroy()
        self.assertEqual(self.errors, [])

    def build_app(self):
        with patch("gui.app.WindowsCredentialStore", return_value=self.store), \
                patch("gui.app.WindowsAppSettingsStore", return_value=self.settings_store):
            app = AIMemoryGUI(self.root)
        app._show_page(3)
        self.root.update()
        return app

    def confirm_delete(self, profile="custom", answer=True):
        with patch("gui.app.messagebox.askyesno", return_value=answer) as confirm:
            self.page.api_delete_buttons[profile].invoke()
        return confirm

    def test_cancel_preserves_the_profile_key_and_row(self):
        before = dict(self.backend.passwords)
        row = self.page.api_row_refs["custom"]
        confirm = self.confirm_delete(answer=False)
        confirm.assert_called_once()
        self.assertIn("我的接口", str(confirm.call_args))
        self.assertIs(confirm.call_args.kwargs["parent"], self.root)
        self.assertEqual(self.backend.passwords, before)
        self.assertIs(self.page.api_row_refs["custom"], row)
        self.assertTrue(row.winfo_exists())

    def test_confirmed_deletion_removes_configuration_and_key_and_cannot_resurrect(self):
        self.assertEqual(set(self.page.api_delete_buttons), set(self.page.api_row_refs))
        self.assertEqual(self.page.api_delete_buttons["custom"].cget("text"), "删除")
        before_second = dict(self.store.load_custom_apis()[SECOND])
        row = self.page.api_row_refs["custom"]
        self.confirm_delete()
        self.root.update()
        self.assertFalse(row.winfo_exists())
        for collection in (self.page.api_row_refs, self.page.api_key_vars,
                           self.page.api_test_buttons, self.page.api_delete_buttons,
                           self.page.api_name_labels, self.page.custom_api_settings):
            self.assertNotIn("custom", collection)
        self.assertNotIn("custom", self.page.ordered_providers)
        self.assertEqual(self.store.load_custom_apis(), {SECOND: before_second})
        self.assertEqual(self.store.load_api_keys(), {SECOND: "second-placeholder", "gemini": "builtin-placeholder"})
        self.page.api_save_button.invoke()
        self.assertNotIn("custom", self.store.load_api_keys())
        self.root.destroy()
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0)
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.app = self.build_app()
        self.page = self.app.page_frames[3]
        self.assertNotIn("custom", self.page.api_row_refs)
        self.assertIn(SECOND, self.page.api_delete_buttons)
        self.assertEqual(set(self.page.api_row_refs), {SECOND, "gemini", "siliconflow", "deepseek"})

    def test_store_failure_keeps_the_row_and_shows_safe_error(self):
        before = dict(self.backend.passwords)
        row = self.page.api_row_refs[SECOND]
        with patch.object(self.store, "delete_custom_api", side_effect=CredentialStoreError("无法删除自定义 API。")):
            self.confirm_delete(SECOND)
        self.root.update()
        self.assertEqual(self.backend.passwords, before)
        self.assertTrue(row.winfo_exists())
        self.assertIn(SECOND, self.page.api_key_vars)
        self.assertIn("无法删除", self.page.api_notice_var.get())
        self.assertNotIn("second-placeholder", self.page.api_notice_var.get())

    def test_pending_connection_result_is_ignored_after_profile_deletion(self):
        callbacks = queue.Queue()
        self.app._post_ui = callbacks.put
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def connection(*_args):
            started.set()
            release.wait(3)
            return "连接成功 · deleted-model · 200"

        with patch("scripts.gemini_summarizer.test_api_connection", side_effect=connection):
            self.page.api_test_buttons[SECOND].invoke()
            self.assertTrue(started.wait(2))
            self.confirm_delete(SECOND)
            notice = self.page.api_notice_var.get()
            release.set()
            callbacks.get(timeout=3)()
        self.assertEqual(self.page.api_notice_var.get(), notice)
        self.assertNotIn(SECOND, self.page.api_row_refs)

    def test_deleting_a_dragged_row_clears_stale_reorder_state(self):
        row = self.page.api_row_refs[SECOND]
        self.page._drag_start(SimpleNamespace(x_root=row.winfo_rootx() + 10,
                                              y_root=row.winfo_rooty() + 10), SECOND)
        self.assertTrue(self.page._drag_state["active"])
        self.confirm_delete(SECOND)
        layouts.GUIResponsiveGeometryTests._flush(self.root, 250)
        self.assertFalse(self.page._drag_state["active"])
        self.assertNotIn(SECOND, self.page.ordered_providers)
        self.assertNotIn(SECOND, self.page.api_row_refs)

    def test_delete_buttons_fit_rows_at_high_dpi_and_minimum_width(self):
        self.root.tk.call("tk", "scaling", 8 / 3)
        self.app._apply_responsive_scale(force=True)
        self.root.geometry(f"{self.app.minimum_window_width}x720")
        layouts.GUIResponsiveGeometryTests()._settle_resize(self.root, self.app)
        for profile in ("custom", SECOND):
            button = self.page.api_delete_buttons[profile]
            row = self.page.api_row_refs[profile]
            self.assertTrue(button.winfo_ismapped())
            self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
            self.assertLessEqual(button.winfo_x() + button.winfo_width(), row.winfo_width())
            for widget in row.grid_slaves():
                self.assertGreaterEqual(widget.winfo_x(), 0)
                self.assertLessEqual(widget.winfo_x() + widget.winfo_width(), row.winfo_width())


if __name__ == "__main__":
    unittest.main()
