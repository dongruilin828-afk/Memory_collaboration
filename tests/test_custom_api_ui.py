"""Settings/editor behaviour with isolated stores and no real API credentials."""
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gui.app import AIMemoryGUI
from gui.credential_store import WindowsCredentialStore
from gui.custom_api_dialog import CustomAPIEditor
from tests import test_custom_api as api_tests
from tests import test_gui_api_keys as old_tests
from tests import test_gui_layout as layouts


class CustomAPISnapshotTests(unittest.TestCase):
    def test_task_keeps_configuration_and_key_when_settings_are_edited(self):
        values = api_tests.settings()
        keys = {"custom": "original-key"}
        gui, _ = old_tests.GUIApiKeyRoutingTests._fake_gui(normal=True)
        gui.root = object()
        gui._run_generation_task = lambda *_args, **_kwargs: None
        gui._set_inputs_locked = lambda _locked: None
        gui._update_generate_button_state = lambda: None
        gui.done_badge = SimpleNamespace(pack_forget=lambda: None)
        gui.progress_bar = SimpleNamespace(reset=lambda: None, set_progress=lambda _v: None)
        gui.status_var = gui.percent_var = SimpleNamespace(set=lambda _v: None)
        gui.credential_store = SimpleNamespace(load_api_keys=lambda: keys, load_custom_apis=lambda: {"custom": dict(values)})
        captured = {}
        class Thread:
            def __init__(self, **kwargs):
                captured.update(kwargs)
            def start(self):
                pass
        with patch("gui.app.threading.Thread", Thread), \
                patch("gui.app._prompt_output_target", return_value=(Path("output"), "summary.md")):
            AIMemoryGUI._on_start_generate(gui)
        keys["custom"] = "changed-key"
        values["url"] = "https://changed.test/v1"
        self.assertEqual(captured["args"][5], {"custom": "original-key"})
        self.assertEqual(captured["kwargs"]["custom_api"]["custom"]["url"], "https://example.test/v1")


class CustomAPIUITests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.attributes("-alpha", 0.0)
        self.callbacks = queue.Queue()
        self.saved = []
        self.addCleanup(self._close_root)

    def _close_root(self):
        self.root.update_idletasks()
        self.root.destroy()

    def dialog(self):
        dialog = CustomAPIEditor(self.root, api_tests.settings(), "placeholder-key",
                                 self.callbacks.put, lambda *args: self.saved.append(args))
        dialog.pack(fill=tk.BOTH, expand=True)
        return dialog

    def test_cancel_discards_draft_save_normalizes_and_protocol_changes_choices(self):
        dialog = self.dialog()
        self.assertEqual(dialog.key_entry.cget("show"), "*")
        dialog.variables["name"].set("unsaved")
        dialog.destroy()
        self.assertEqual(self.saved, [])
        dialog = self.dialog()
        dialog.variables["url"].set("https://my.test/v1/chat/completions")
        dialog.variables["thinking_level"].set("xhigh")
        dialog.variables["protocol"].set("gemini")
        dialog._protocol_changed()
        self.assertEqual(dialog.variables["thinking_level"].get(), "auto")
        self.assertEqual(str(dialog.entries["json_mode"].cget("state")), "disabled")
        dialog.variables["protocol"].set("openai")
        dialog._protocol_changed()
        dialog.priority_var.set(True)
        dialog.save()
        self.assertEqual(self.saved[0][0]["url"], "https://my.test/v1")
        self.assertEqual(self.saved[0][1:], ("placeholder-key", True))

    def test_pending_test_ignores_duplicate_and_does_not_validate_edited_draft(self):
        dialog = self.dialog()
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def probe(*_args):
            started.set()
            release.wait(3)
            return "连接成功"
        with patch("gui.custom_api_dialog.test_api_connection", side_effect=probe) as call:
            dialog.test()
            self.assertTrue(started.wait(2))
            self.assertFalse(dialog.test_button._enabled)
            dialog.test()
            self.assertEqual(call.call_count, 1)
            dialog.variables["model"].set("edited-model")
            release.set()
            self.callbacks.get(timeout=3)()
        self.assertIn("配置已更改", dialog.status_var.get())
        self.assertTrue(dialog.test_button._enabled)
        self.assertEqual(self.saved, [])

    def test_test_completion_after_close_does_not_touch_destroyed_widgets(self):
        dialog = self.dialog()
        with patch("gui.custom_api_dialog.test_api_connection", return_value="连接成功"):
            dialog.test()
            callback = self.callbacks.get(timeout=3)
        dialog.destroy()
        callback()
        self.assertEqual(self.saved, [])

    def test_settings_editor_saves_to_vault_and_updates_real_priority(self):
        store = WindowsCredentialStore(old_tests.FakeCredentialBackend())
        settings_store = layouts._SettingsStore()
        self.addCleanup(settings_store.scratch.cleanup)
        with patch("gui.app.WindowsCredentialStore", return_value=store), \
                patch("gui.app.WindowsAppSettingsStore", return_value=settings_store):
            app = AIMemoryGUI(self.root)
        app._show_page(3)
        self.root.update_idletasks()
        page = app.page_frames[3]
        self.assertNotIn("custom", page.api_key_vars)
        windows_before = set(self.root.winfo_children())
        draft = page.edit_custom_api()
        self.root.update_idletasks()
        self.assertIs(draft.winfo_toplevel(), self.root)
        self.assertEqual(set(self.root.winfo_children()), windows_before)
        self.assertTrue(draft.winfo_ismapped())
        draft.variables["name"].set("discarded draft")
        draft.cancel_button._command()
        self.root.update_idletasks()
        self.assertIsNone(page.custom_api_editor)
        self.assertEqual(store.load_custom_apis(), {})
        self.assertTrue(page.custom_api_button.winfo_ismapped())
        dialog = page.edit_custom_api()
        for name, value in api_tests.settings().items():
            dialog.variables[name].set(value)
        dialog.key_var.set("new-placeholder-key")
        dialog.priority_var.set(True)
        dialog.save()
        profile_id = page.ordered_providers[0]
        self.assertTrue(profile_id.startswith("custom_"))
        self.assertEqual(store.load_provider_order()[0], profile_id)
        self.assertEqual(store.load_api_keys()[profile_id], "new-placeholder-key")
        page.edit_custom_api()
        page.show_page("data")
        layouts.GUIResponsiveGeometryTests._flush(self.root)
        self.assertIsNone(page.custom_api_editor)
        self.assertTrue(page.data_page.winfo_ismapped())
        page.show_page("api")
        layouts.GUIResponsiveGeometryTests._flush(self.root)
        self.assertTrue(page.custom_api_button.winfo_ismapped())
        self.assertEqual(page.api_key_vars[profile_id].get(), "new-placeholder-key")
        self.assertEqual(store.load_custom_apis()[profile_id]["model"], "my-model")
        self.root.update_idletasks()
        self.assertEqual(page.api_name_labels[profile_id].cget("text"), "我的接口")
        # Clicking the name edits this profile; adding creates a separate one.
        page.api_name_labels[profile_id].event_generate("<Button-1>")
        edited = page.custom_api_editor
        self.assertEqual(edited.variables["name"].get(), "我的接口")
        edited.variables["name"].set("renamed")
        edited.save()
        second = page.edit_custom_api()
        for name, value in api_tests.settings().items():
            second.variables[name].set(value)
        second.key_var.set("second-key")
        second.save()
        self.assertEqual(len(store.load_custom_apis()), 2)
        self.assertEqual(store.load_custom_apis()[profile_id]["name"], "renamed")
        self.assertEqual(store.load_api_keys()[profile_id], "new-placeholder-key")

    def test_failed_key_load_cannot_overwrite_existing_credentials(self):
        store = WindowsCredentialStore(old_tests.FakeCredentialBackend())
        settings_store = layouts._SettingsStore()
        self.addCleanup(settings_store.scratch.cleanup)
        with patch.object(store, "load_api_keys", side_effect=old_tests.CredentialStoreError("读取失败")), \
                patch("gui.app.WindowsCredentialStore", return_value=store), \
                patch("gui.app.WindowsAppSettingsStore", return_value=settings_store):
            app = AIMemoryGUI(self.root)
        with patch.object(store, "save_api_keys") as save:
            app.page_frames[3].api_save_button._command()
        save.assert_not_called()

    def test_settings_row_rejects_stale_success_after_key_edit(self):
        store = WindowsCredentialStore(old_tests.FakeCredentialBackend())
        store.save_api_keys({"gemini": "original-placeholder"})
        settings_store = layouts._SettingsStore()
        self.addCleanup(settings_store.scratch.cleanup)
        with patch("gui.app.WindowsCredentialStore", return_value=store), \
                patch("gui.app.WindowsAppSettingsStore", return_value=settings_store):
            app = AIMemoryGUI(self.root)
        page = app.page_frames[3]
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def probe(*_args):
            started.set()
            release.wait(3)
            return "连接成功"
        with patch("scripts.gemini_summarizer.test_api_connection", side_effect=probe):
            page.api_test_buttons["gemini"].invoke()
            self.assertTrue(started.wait(2))
            page.api_key_vars["gemini"].set("edited-placeholder")
            release.set()
            deadline = time.monotonic() + 3
            while "已更改" not in page.api_notice_var.get() and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.02)
        self.assertIn("已更改", page.api_notice_var.get())

    def test_result_uses_available_row_width_without_wrapping(self):
        store = WindowsCredentialStore(old_tests.FakeCredentialBackend())
        settings_store = layouts._SettingsStore()
        self.addCleanup(settings_store.scratch.cleanup)
        with patch("gui.app.WindowsCredentialStore", return_value=store), \
                patch("gui.app.WindowsAppSettingsStore", return_value=settings_store):
            app = AIMemoryGUI(self.root)
        app._show_page(3)
        self.root.update_idletasks()
        page = app.page_frames[3]
        with patch("scripts.gemini_summarizer.test_api_connection", return_value="连接成功 · Qwen/Qwen3-8B · 200"):
            page.api_key_vars["siliconflow"].set("placeholder")
            page.api_test_buttons["siliconflow"].invoke()
            deadline = time.monotonic() + 3
            while not page.api_notice_var.get().startswith("连接成功") and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.02)
        label = page.api_notice_label
        self.assertEqual(label.cget("text"), "连接成功 · Qwen/Qwen3-8B · 200")
        self.assertEqual(int(label.cget("wraplength")), 0)
        self.assertGreaterEqual(label.winfo_width(), page.api_rows_frame.winfo_width() - 4)
        self.assertLessEqual(tkfont.Font(font=label.cget("font")).measure(label.cget("text")), label.winfo_width())


class CustomAPIGeometryTests(unittest.TestCase):
    def test_fixed_controls_and_entry_fit_at_minimum_width_across_dpi(self):
        for scaling in (1.0, 4 / 3, 5 / 3, 2.0, 8 / 3):
            with self.subTest(tk_scaling=scaling):
                root = tk.Tk()
                root.attributes("-alpha", 0.0)
                root.tk.call("tk", "scaling", scaling)
                store = WindowsCredentialStore(old_tests.FakeCredentialBackend())
                store.save_custom_api({**api_tests.settings(), "name": "DeepSeek-很长的名称-WorkBuddy"}, "placeholder")
                settings_store = layouts._SettingsStore()
                try:
                    with patch("gui.app.WindowsCredentialStore", return_value=store), \
                            patch("gui.app.WindowsAppSettingsStore", return_value=settings_store):
                        app = AIMemoryGUI(root)
                    app._show_page(3)
                    settle = layouts.GUIResponsiveGeometryTests()._settle_resize
                    settle(root, app)
                    page = app.page_frames[3]
                    dialog = page.edit_custom_api()
                    settle(root, app)
                    self.assertIs(dialog.winfo_toplevel(), root)
                    for button in (dialog.cancel_button, dialog.test_button, dialog.save_button):
                        self.assertGreaterEqual(button.winfo_x(), 0)
                        self.assertLessEqual(
                            button.winfo_x() + button.winfo_width(), button.master.winfo_width(),
                        )
                    for name, value in api_tests.settings().items():
                        dialog.variables[name].set(value)
                    dialog.key_var.set("new-placeholder")
                    dialog.save()
                    settle(root, app)
                    self.assertEqual(len(page.api_row_refs), 5)
                    for width in (app.minimum_window_width, min(root.winfo_screenwidth() - 32, app.minimum_window_width + 220), app.minimum_window_width):
                        root.geometry(f"{width}x680")
                        settle(root, app)
                        for provider, row in page.api_row_refs.items():
                            self.assertEqual(page.api_test_buttons[provider].cget("text"), "测试")
                            for widget in row.grid_slaves():
                                self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth(), provider)
                                self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight(), provider)
                                self.assertGreaterEqual(widget.winfo_x(), 0, provider)
                                self.assertLessEqual(widget.winfo_x() + widget.winfo_width(), row.winfo_width(), provider)
                                self.assertLessEqual(widget.winfo_y() + widget.winfo_height(), row.winfo_height(), provider)
                finally:
                    root.update_idletasks()
                    root.destroy()
                    settings_store.scratch.cleanup()


if __name__ == "__main__":
    unittest.main()
