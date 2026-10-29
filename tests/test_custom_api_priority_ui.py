"""Priority switches reflect persisted API order without using real credentials."""

import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gui.app import AIMemoryGUI
from gui.credential_store import WindowsCredentialStore
from tests import test_gui_layout as layouts
from tests.test_custom_api import settings
from tests.test_gui_api_keys import FakeCredentialBackend


SECOND = "custom_" + "a" * 32


class CustomAPIPriorityUITests(unittest.TestCase):
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
        self.store.save_custom_api(settings(), "first-placeholder")
        self.store.save_custom_api({**settings(), "name": "第二个接口", "model": "second-model"},
                                   "second-placeholder", SECOND)
        self.store.save_api_keys({"gemini": "builtin-placeholder"})
        self.store.save_provider_order(["gemini", "custom", SECOND, "siliconflow", "deepseek"])
        self.settings_store = layouts._SettingsStore()
        self.addCleanup(self.settings_store.scratch.cleanup)
        self.addCleanup(self.close_root)
        # Capability discovery is independent of priority; no API requests are
        # needed to validate reopening and editing these isolated profiles.
        discovery = patch("gui.custom_api_dialog.CustomAPIEditor._start_reasoning_discovery")
        discovery.start()
        self.addCleanup(discovery.stop)
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

    def reopen_app(self):
        self.root.destroy()
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0)
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.build_app()

    def editor(self, profile="custom"):
        dialog = self.page.edit_custom_api(profile)
        self.root.update()
        return dialog.editor

    def prefer(self, profile="custom"):
        editor = self.editor(profile)
        if not editor.priority_var.get():
            editor.priority_switch.invoke()
        editor.save()
        self.root.update()
        self.assertEqual(self.page.ordered_providers[0], profile)

    def test_priority_stays_on_after_save_reopen_and_application_restart(self):
        editor = self.editor()
        self.assertFalse(editor.priority_var.get())
        editor.priority_switch.invoke()
        self.assertTrue(editor.priority_var.get())
        editor.save()
        self.root.update()
        self.assertEqual(self.store.load_provider_order()[0], "custom")
        editor = self.editor()
        self.assertTrue(editor.priority_var.get())
        editor.close()
        self.reopen_app()
        self.assertTrue(self.editor().priority_var.get())

    def test_another_profile_taking_first_place_turns_previous_priority_off(self):
        self.prefer()
        self.prefer(SECOND)
        editor = self.editor()
        self.assertFalse(editor.priority_var.get())
        editor.close()
        self.assertTrue(self.editor(SECOND).priority_var.get())
        self.assertEqual(self.store.load_provider_order()[0], SECOND)

    def test_unchecking_current_first_moves_it_last_and_persists_off(self):
        self.prefer()
        before = list(self.page.ordered_providers)
        editor = self.editor()
        self.assertTrue(editor.priority_var.get())
        editor.priority_switch.invoke()
        self.assertFalse(editor.priority_var.get())
        editor.save()
        self.root.update()
        self.assertEqual(self.page.ordered_providers, [*before[1:], "custom"])
        self.assertEqual(self.store.load_provider_order()[-1], "custom")
        self.assertFalse(self.editor().priority_var.get())

    def test_dragging_a_profile_to_first_updates_reopened_priority_state(self):
        self.prefer()
        top = self.page.api_rows_frame.winfo_rooty()
        center = self.page.api_rows_frame.winfo_rootx() + self.page.api_rows_frame.winfo_width() // 2
        self.page._drag_start(None, SECOND)
        pointer = SimpleNamespace(y_root=top + 1, x_root=center)
        self.page._drag_motion(pointer)
        self.page._drag_end(pointer)
        self.assertEqual(self.page.ordered_providers[0], SECOND)
        self.page.api_save_button.invoke()
        editor = self.editor(SECOND)
        self.assertTrue(editor.priority_var.get())
        editor.close()
        self.assertFalse(self.editor().priority_var.get())

    def test_cancel_does_not_change_saved_priority_or_call_order(self):
        self.prefer()
        before = dict(self.backend.passwords)
        order = list(self.page.ordered_providers)
        editor = self.editor()
        editor.priority_switch.invoke()
        self.assertFalse(editor.priority_var.get())
        editor.cancel_button.invoke()
        self.root.update()
        self.assertEqual(self.backend.passwords, before)
        self.assertEqual(self.page.ordered_providers, order)
        self.assertTrue(self.editor().priority_var.get())

    def test_saving_an_unprioritized_profile_preserves_existing_order(self):
        before = list(self.page.ordered_providers)
        editor = self.editor(SECOND)
        self.assertFalse(editor.priority_var.get())
        editor.variables["name"].set("更新后的名称")
        editor.save()
        self.root.update()
        self.assertEqual(self.page.ordered_providers, before)
        self.assertEqual(self.store.load_provider_order(), tuple(before))
        self.assertFalse(self.editor(SECOND).priority_var.get())

    def test_new_profile_starts_with_priority_off(self):
        editor = self.editor(None)
        self.assertFalse(editor.priority_var.get())
        self.assertEqual(str(editor.priority_switch.cget("state")), "normal")

    def test_only_remaining_profile_is_first_and_priority_switch_is_locked(self):
        for provider in ("gemini", "siliconflow", "deepseek"):
            self.store.delete_builtin_api(provider)
        self.store.delete_custom_api(SECOND)
        self.reopen_app()
        self.assertEqual(self.page.ordered_providers, ["custom"])
        editor = self.editor()
        self.assertTrue(editor.priority_var.get())
        self.assertEqual(str(editor.priority_switch.cget("state")), "disabled")
        editor.priority_switch.invoke()
        self.assertTrue(editor.priority_var.get())
        editor.save()
        self.root.update()
        self.assertEqual(self.page.ordered_providers, ["custom"])
        self.assertTrue(self.editor().priority_var.get())


if __name__ == "__main__":
    unittest.main()
