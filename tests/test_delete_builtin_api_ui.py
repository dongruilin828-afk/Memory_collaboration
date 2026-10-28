"""Built-in API deletion and restoration use only isolated credential records."""

import queue
import threading
import tkinter as tk
import unittest
from unittest.mock import patch

from gui.app import AIMemoryGUI
from gui.credential_store import CredentialStoreError, WindowsCredentialStore
from tests import test_gui_layout as layouts
from tests.test_custom_api import settings
from tests.test_gui_api_keys import FakeCredentialBackend


BUILTINS = ("gemini", "siliconflow", "deepseek")


class DeleteBuiltinAPIUITests(unittest.TestCase):
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
        self.store.save_api_keys({provider: provider + "-placeholder" for provider in BUILTINS})
        self.store.save_custom_api(settings(), "custom-placeholder")
        self.store.save_provider_order(["custom", "siliconflow", "gemini", "deepseek"])
        self.settings_store = layouts._SettingsStore()
        self.addCleanup(self.settings_store.scratch.cleanup)
        self.addCleanup(self.close_root)
        self.build_app()

    def close_root(self):
        self.root.update_idletasks()
        self.root.destroy()
        self.assertEqual(self.errors, [])

    def build_app(self):
        with patch("gui.app.WindowsCredentialStore", return_value=self.store), \
                patch("gui.app.WindowsAppSettingsStore", return_value=self.settings_store):
            self.app = AIMemoryGUI(self.root)
        self.app._show_page(3)
        self.root.update()
        self.page = self.app.page_frames[3]

    def reopen(self):
        self.root.destroy()
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0)
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.build_app()

    def delete(self, provider, answer=True):
        with patch("gui.app.messagebox.askyesno", return_value=answer) as confirm:
            self.page.api_delete_buttons[provider].invoke()
        return confirm

    def restore(self, answer=True):
        with patch("gui.app.messagebox.askyesno", return_value=answer) as confirm:
            self.page.restore_builtin_api_button.invoke()
        return confirm

    def test_every_builtin_has_a_delete_button_and_cancel_preserves_it(self):
        self.assertEqual(set(self.page.api_delete_buttons), {*BUILTINS, "custom"})
        before = dict(self.backend.passwords)
        for provider in BUILTINS:
            with self.subTest(provider=provider):
                button = self.page.api_delete_buttons[provider]
                self.assertEqual(button.cget("text"), "删除")
                row = self.page.api_row_refs[provider]
                confirm = self.delete(provider, answer=False)
                confirm.assert_called_once()
                self.assertIs(confirm.call_args.kwargs["parent"], self.root)
                self.assertEqual(self.backend.passwords, before)
                self.assertIs(self.page.api_row_refs[provider], row)
                self.assertTrue(row.winfo_exists())
        self.assertFalse(self.page.restore_builtin_api_button.winfo_manager())

    def test_each_deleted_builtin_stays_removed_after_save_and_reopen(self):
        for provider in BUILTINS:
            with self.subTest(provider=provider):
                row = self.page.api_row_refs[provider]
                self.delete(provider)
                self.root.update()
                self.assertFalse(row.winfo_exists())
                for collection in (self.page.api_row_refs, self.page.api_key_vars,
                                   self.page.api_test_buttons, self.page.api_delete_buttons,
                                   self.page.api_name_labels):
                    self.assertNotIn(provider, collection)
                self.assertNotIn(provider, self.page.ordered_providers)
                self.assertNotIn(provider, self.store.load_api_keys())
                self.page.api_save_button.invoke()
                self.reopen()
                self.assertNotIn(provider, self.page.api_row_refs)
                self.assertIn("custom", self.page.api_row_refs)
                self.assertEqual(self.store.load_api_keys()["custom"], "custom-placeholder")
        self.assertEqual(set(self.page.api_row_refs), {"custom"})
        self.assertTrue(self.page.restore_builtin_api_button.winfo_ismapped())

    def test_builtin_without_a_saved_key_can_be_deleted(self):
        self.store.save_api_keys({"siliconflow": "siliconflow-placeholder", "deepseek": "deepseek-placeholder"})
        self.reopen()
        self.assertEqual(self.page.api_key_vars["gemini"].get(), "")
        self.delete("gemini")
        self.reopen()
        self.assertNotIn("gemini", self.page.api_row_refs)
        self.assertIn("gemini", self.store.load_deleted_builtin_apis())

    def test_delete_failure_retains_row_and_safe_notice(self):
        before = dict(self.backend.passwords)
        row = self.page.api_row_refs["deepseek"]
        with patch.object(self.store, "delete_builtin_api", side_effect=CredentialStoreError("无法删除内置 API，请重试。")):
            self.delete("deepseek")
        self.root.update()
        self.assertEqual(self.backend.passwords, before)
        self.assertIs(self.page.api_row_refs["deepseek"], row)
        self.assertIn("无法删除", self.page.api_notice_var.get())
        self.assertNotIn("deepseek-placeholder", self.page.api_notice_var.get())

    def test_late_connection_result_is_ignored_after_builtin_deletion(self):
        callbacks = queue.Queue()
        self.app._post_ui = callbacks.put
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def connection(*_args):
            started.set()
            release.wait(3)
            return "连接成功 · old-model · 200"

        with patch("scripts.gemini_summarizer.test_api_connection", side_effect=connection):
            self.page.api_test_buttons["gemini"].invoke()
            self.assertTrue(started.wait(2))
            self.delete("gemini")
            notice = self.page.api_notice_var.get()
            release.set()
            callbacks.get(timeout=3)()
        self.assertEqual(self.page.api_notice_var.get(), notice)
        self.assertNotIn("gemini", self.page.api_row_refs)

    def test_restore_all_readds_empty_rows_without_old_keys_or_custom_changes(self):
        custom = dict(self.store.load_custom_apis()["custom"])
        for provider in BUILTINS:
            self.delete(provider)
        self.root.update()
        button = self.page.restore_builtin_api_button
        self.assertEqual(getattr(button, "_text", None) or button.cget("text"), "恢复内置 API")
        self.assertTrue(button.winfo_ismapped())
        before = dict(self.backend.passwords)
        self.restore(answer=False)
        self.assertEqual(self.backend.passwords, before)
        self.assertEqual(set(self.page.api_row_refs), {"custom"})
        self.restore()
        self.root.update()
        self.assertEqual(set(self.page.api_row_refs), {*BUILTINS, "custom"})
        for provider in BUILTINS:
            self.assertEqual(self.page.api_key_vars[provider].get(), "")
            self.assertIn(provider, self.page.api_delete_buttons)
            self.assertNotIn(provider, self.store.load_api_keys())
        self.assertEqual(self.store.load_custom_apis(), {"custom": custom})
        self.assertEqual(self.page.ordered_providers[0], "custom")
        self.assertFalse(button.winfo_manager())
        self.page.api_save_button.invoke()
        self.reopen()
        self.assertEqual(set(self.page.api_row_refs), {*BUILTINS, "custom"})
        self.assertEqual(self.store.load_api_keys(), {"custom": "custom-placeholder"})

    def test_restore_failure_keeps_ui_and_stored_hidden_set_consistent(self):
        for provider in BUILTINS:
            self.delete(provider)
        restore = self.store.restore_builtin_api
        attempts = []

        def fail_second(provider):
            attempts.append(provider)
            if len(attempts) == 2:
                raise CredentialStoreError("无法恢复内置 API，请重试。")
            restore(provider)

        with patch.object(self.store, "restore_builtin_api", side_effect=fail_second):
            self.restore()
        self.root.update()
        hidden = set(self.store.load_deleted_builtin_apis())
        self.assertEqual(set(self.page.api_row_refs), (set(BUILTINS) - hidden) | {"custom"})
        self.assertTrue(self.page.restore_builtin_api_button.winfo_ismapped())
        self.assertIn("无法恢复", self.page.api_notice_var.get())
        self.assertEqual(self.store.load_api_keys(), {"custom": "custom-placeholder"})

    def test_empty_api_list_can_be_saved_reopened_and_restored(self):
        for provider in (*BUILTINS, "custom"):
            self.delete(provider)
        self.root.update()
        self.assertEqual(self.page.api_row_refs, {})
        self.assertEqual(self.page.ordered_providers, [])
        self.assertTrue(self.page.restore_builtin_api_button.winfo_ismapped())
        self.page.api_save_button.invoke()
        self.reopen()
        self.assertEqual(self.page.api_row_refs, {})
        self.assertEqual(self.store.load_api_keys(), {})
        self.restore()
        self.root.update()
        self.assertEqual(set(self.page.api_row_refs), set(BUILTINS))
        self.assertEqual(self.store.load_api_keys(), {})
        self.assertEqual(self.store.load_custom_apis(), {})

    def test_restore_and_delete_buttons_fit_at_high_dpi_and_minimum_width(self):
        self.delete("gemini")
        self.root.tk.call("tk", "scaling", 8 / 3)
        self.app._apply_responsive_scale(force=True)
        self.root.geometry(f"{self.app.minimum_window_width}x720")
        layouts.GUIResponsiveGeometryTests()._settle_resize(self.root, self.app)
        restore = self.page.restore_builtin_api_button
        self.assertTrue(restore.winfo_ismapped())
        self.assertGreaterEqual(restore.winfo_width(), restore.winfo_reqwidth())
        self.assertLessEqual(restore.winfo_x() + restore.winfo_width(), restore.master.winfo_width())
        for provider in ("siliconflow", "deepseek", "custom"):
            row = self.page.api_row_refs[provider]
            button = self.page.api_delete_buttons[provider]
            self.assertTrue(button.winfo_ismapped())
            self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
            self.assertLessEqual(button.winfo_x() + button.winfo_width(), row.winfo_width())


if __name__ == "__main__":
    unittest.main()
