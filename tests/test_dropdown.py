"""Keyboard, modal and lifecycle behavior of the rounded dropdown popup."""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
import unittest
from unittest.mock import patch

from gui.dropdown import RoundedCombobox


class RoundedComboboxTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.root.attributes("-alpha", 0.0)
        self.root.geometry("400x300")
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.tk.call("set", "::dropdown_test_bgerrors", "")
        self.root.tk.call("proc", "bgerror", "message", "lappend ::dropdown_test_bgerrors $message")
        self.addCleanup(self._close_root)
        self.root.update()
        self.root.focus_force()
        self.root.update()

    def _close_root(self):
        self.root.update_idletasks()
        self.root.destroy()
        # Tcl binding errors bypass Tkinter's report_callback_exception hook.
        self.root.tk.call("update")
        self.assertEqual(tuple(self.root.tk.splitlist(self.root.tk.call("set", "::dropdown_test_bgerrors"))), ())
        self.assertEqual(self.errors, [])

    def combo(self, parent=None, **kwargs):
        options = dict(values=("自动", "低", "中", "高"), state="readonly")
        options.update(kwargs)
        combo = RoundedCombobox(parent or self.root, **options)
        combo.pack(fill=tk.X, padx=16, pady=16)
        combo.current(1)
        self.root.update()
        return combo

    def open(self, combo):
        combo.open_dropdown()
        self.root.update()
        popup = combo.popup
        self.assertIsNotNone(popup)
        self.assertTrue(popup.winfo_exists())
        popup.canvas.focus_force()
        self.root.update()
        return popup

    def key(self, widget, sequence):
        widget.event_generate(sequence)
        self.root.update()

    def _entry_and_combo(self, parent=None):
        owner = parent or self.root
        entry = tk.Entry(owner)
        entry.pack(fill=tk.X, padx=16, pady=16)
        combo = self.combo(owner)
        return entry, combo

    def _open_without_forcing_focus(self, combo):
        combo.open_dropdown()
        self.root.update()
        popup = combo.popup
        self.assertIsNotNone(popup)
        focus = self.root.focus_displayof()
        self.assertIsNotNone(focus)
        self.assertIs(focus.winfo_toplevel(), popup)
        return popup

    def _type_into_focused_entry(self, entry, character="x"):
        focus = self.root.focus_displayof()
        self.assertIs(focus, entry)
        focus.event_generate(f"<KeyPress-{character}>")
        focus.event_generate(f"<KeyRelease-{character}>")
        self.root.update()
        self.assertEqual(entry.get(), character)

    def _click_entry_and_type(self, entry):
        entry.event_generate("<ButtonPress-1>", x=10, y=8)
        entry.event_generate("<ButtonRelease-1>", x=10, y=8)
        self.root.update()
        self._type_into_focused_entry(entry)

    def test_choose_and_escape_leave_owner_entries_editable(self):
        for action in ("choose", "escape"):
            with self.subTest(action=action):
                entry, combo = self._entry_and_combo()
                popup = self._open_without_forcing_focus(combo)
                if action == "choose":
                    popup.choose(2)
                else:
                    popup._escape()
                self.root.update()
                self.assertIs(self.root.focus_displayof(), combo)
                self._click_entry_and_type(entry)
                combo.destroy()
                entry.destroy()

    def test_programmatic_close_preserves_keyboard_input_for_both_focus_options(self):
        for restore_focus in (False, True):
            with self.subTest(restore_focus=restore_focus):
                entry, combo = self._entry_and_combo()
                self._open_without_forcing_focus(combo)
                combo.close_dropdown(restore_focus=restore_focus)
                self.root.update()
                self.assertIs(self.root.focus_displayof(), combo)
                self._click_entry_and_type(entry)
                combo.destroy()
                entry.destroy()

    def test_outside_entry_click_dismisses_and_allows_immediate_typing(self):
        entry, combo = self._entry_and_combo()
        popup = self._open_without_forcing_focus(combo)
        x, y = entry.winfo_rootx() + 10, entry.winfo_rooty() + 8
        # Alpha-zero Windows fixtures are excluded from the native hit test.
        # Only that lookup is stubbed; focus and typing use the real Tk widgets.
        with patch.object(tk.Misc, "winfo_containing", return_value=entry):
            popup.canvas.event_generate(
                "<ButtonPress-1>", x=x - popup.winfo_rootx(), y=y - popup.winfo_rooty(),
                rootx=x, rooty=y,
            )
            self.root.update()
        self.assertIsNone(combo.popup)
        self._type_into_focused_entry(entry)

    def test_dismiss_does_not_steal_focus_or_grab_from_a_newer_modal(self):
        newer = tk.Toplevel(self.root)
        newer.attributes("-alpha", 0.0)
        other_entry = tk.Entry(newer)
        other_entry.pack()
        previous = tk.Toplevel(self.root)
        previous.attributes("-alpha", 0.0)
        previous.geometry("400x300")
        _, combo = self._entry_and_combo(previous)
        self.root.update()
        combo.focus_set()
        self.root.update()
        previous.grab_set()
        self._open_without_forcing_focus(combo)
        other_entry.focus_set()
        newer.grab_set()
        combo.close_dropdown(restore_focus=True)
        self.root.update()
        self.assertIs(self.root.focus_displayof(), other_entry)
        self.assertIs(self.root.grab_current(), newer)
        self._type_into_focused_entry(other_entry)

    def test_keyboard_navigation_commits_once_and_preserves_combobox_api(self):
        value = tk.StringVar(self.root)
        combo = self.combo(textvariable=value)
        self.assertIsInstance(combo, ttk.Combobox)
        selected = []
        combo.bind("<<ComboboxSelected>>", lambda _e: selected.append(combo.get()))
        popup = self.open(combo)
        self.assertEqual(popup.active_index, 1)
        self.key(popup.canvas, "<Down>")
        self.assertEqual(popup.active_index, 2)
        self.assertEqual(value.get(), "低")
        self.key(popup.canvas, "<Return>")
        self.assertEqual(combo.current(), 2)
        self.assertEqual(value.get(), "中")
        self.assertEqual(selected, ["中"])
        self.assertIsNone(combo.popup)
        self.assertEqual(self.errors, [])

    def test_escape_cancels_highlight_without_changing_value_or_closing_parent(self):
        combo = self.combo()
        selected = []
        combo.bind("<<ComboboxSelected>>", lambda _e: selected.append(combo.get()))
        popup = self.open(combo)
        self.key(popup.canvas, "<Down>")
        self.assertEqual(popup.active_index, 2)
        self.key(popup.canvas, "<Escape>")
        self.assertEqual(combo.get(), "低")
        self.assertEqual(selected, [])
        self.assertIsNone(combo.popup)
        self.assertTrue(self.root.winfo_viewable())

    def test_mouse_choice_commits_one_selected_event(self):
        combo = self.combo()
        selected = []
        combo.bind("<<ComboboxSelected>>", lambda _e: selected.append(combo.current()))
        popup = self.open(combo)
        popup.choose(3)
        self.root.update()
        self.assertEqual(combo.get(), "高")
        self.assertEqual(selected, [3])
        self.assertIsNone(combo.popup)

    def test_outside_click_routed_to_popup_canvas_dismisses_without_commit(self):
        combo = self.combo()
        selected = []
        combo.bind("<<ComboboxSelected>>", lambda _e: selected.append(combo.get()))
        popup = self.open(combo)
        popup.canvas.event_generate(
            "<ButtonPress-1>", x=-20, y=-20,
            rootx=popup.winfo_rootx() - 20, rooty=popup.winfo_rooty() - 20,
        )
        self.root.update()
        self.assertIsNone(combo.popup)
        self.assertEqual(combo.get(), "低")
        self.assertEqual(selected, [])
        self.assertIsNone(self.root.grab_current())

    def test_disabled_control_does_not_open_and_configuration_closes_old_popup(self):
        combo = self.combo()
        combo.configure(state="disabled")
        combo.open_dropdown()
        self.root.update()
        self.assertIsNone(combo.popup)
        combo.configure(state="readonly")
        popup = self.open(combo)
        combo.configure(values=("新选项一", "新选项二"))
        self.root.update()
        self.assertIsNone(combo.popup)
        self.assertFalse(popup.winfo_exists())
        popup = self.open(combo)
        combo.configure(state="disabled")
        self.root.update()
        self.assertIsNone(combo.popup)
        self.assertFalse(popup.winfo_exists())
        combo.state(["!disabled", "readonly"])
        popup = self.open(combo)
        combo.state(["disabled"])
        self.root.update()
        self.assertIsNone(combo.popup)
        self.assertFalse(popup.winfo_exists())
        self.assertEqual(self.errors, [])

    def test_popup_close_and_commit_restore_existing_modal_grab(self):
        modal = tk.Toplevel(self.root)
        modal.attributes("-alpha", 0.0)
        modal.geometry("400x300")
        combo = self.combo(modal)
        modal.grab_set()
        popup = self.open(combo)
        self.assertIs(self.root.grab_current(), popup)
        combo.close_dropdown(restore_focus=False)
        self.root.update()
        self.assertIs(self.root.grab_current(), modal)
        popup = self.open(combo)
        popup.choose(2)
        self.root.update()
        self.assertIs(self.root.grab_current(), modal)
        self.assertEqual(combo.get(), "中")
        self.assertEqual(self.errors, [])

    def test_parent_hide_and_destroy_remove_popup_and_leave_no_callbacks(self):
        host = tk.Toplevel(self.root)
        host.attributes("-alpha", 0.0)
        host.geometry("400x300")
        combo = self.combo(host)
        popup = self.open(combo)
        host.withdraw()
        self.root.update()
        self.assertIsNone(combo.popup)
        self.assertFalse(popup.winfo_exists())
        host.deiconify()
        self.root.update()
        popup = self.open(combo)
        popup_path = str(popup)
        host.destroy()
        self.root.update()
        self.assertFalse(self.root.tk.call("winfo", "exists", popup_path))
        self.assertIsNone(self.root.grab_current())
        self.assertEqual(self.errors, [])

    def test_opening_second_dropdown_replaces_first_and_preserves_modal_grab(self):
        modal = tk.Toplevel(self.root)
        modal.attributes("-alpha", 0.0)
        modal.geometry("400x300")
        first = self.combo(modal)
        second = self.combo(modal)
        modal.grab_set()
        first_popup = self.open(first)
        second_popup = self.open(second)
        self.assertIsNone(first.popup)
        self.assertFalse(first_popup.winfo_exists())
        self.assertIs(self.root.grab_current(), second_popup)
        second.close_dropdown()
        self.root.update()
        self.assertIs(self.root.grab_current(), modal)
        self.assertEqual(self.errors, [])

    def test_large_font_popup_fits_screen_when_opened_near_bottom(self):
        self.root.tk.call("tk", "scaling", 8 / 3)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"400x300+{max(0, screen_width - 420)}+{max(0, screen_height - 330)}")
        font = tkfont.Font(self.root, family="Microsoft YaHei UI", size=10)
        combo = self.combo(
            values=("auto", "none", "minimal", "low", "medium", "high", "xhigh"),
            font=font,
        )
        popup = self.open(combo)
        self.assertGreaterEqual(popup.row_height, font.metrics("linespace"))
        self.assertGreaterEqual(popup.winfo_rootx(), 0)
        self.assertGreaterEqual(popup.winfo_rooty(), 0)
        self.assertLessEqual(popup.winfo_rootx() + popup.winfo_width(), screen_width)
        self.assertLessEqual(popup.winfo_rooty() + popup.winfo_height(), screen_height)
        self.assertEqual(self.errors, [])

    def test_mouse_and_keyboard_open_only_custom_popup(self):
        combo = self.combo()
        native_posts = []
        trace_command = self.root.register(lambda *args: native_posts.append(args))
        self.root.tk.call("trace", "add", "execution", "ttk::combobox::Post", "enter", trace_command)
        try:
            combo.focus_force()
            self.root.update()
            self.key(combo, "<ButtonPress-1>")
            self.key(combo, "<ButtonRelease-1>")
            self.assertIsNotNone(combo.popup)
            combo.close_dropdown()
            self.root.update()
            for sequence in ("<Down>", "<space>", "<Alt-Down>"):
                with self.subTest(key=sequence):
                    combo.focus_force()
                    self.root.update()
                    self.key(combo, sequence)
                    self.assertIsNotNone(combo.popup)
                    combo.close_dropdown()
                    self.root.update()
            self.assertEqual(native_posts, [])
        finally:
            self.root.tk.call("trace", "remove", "execution", "ttk::combobox::Post", "enter", trace_command)
            self.root.deletecommand(trace_command)


if __name__ == "__main__":
    unittest.main()
