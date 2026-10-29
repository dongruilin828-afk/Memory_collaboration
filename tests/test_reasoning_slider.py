"""Discrete reasoning slider behavior with the existing API parameter values."""

import tkinter as tk
import tkinter.font as tkfont
import unittest

from gui.reasoning_slider import AutoReasoningButton, ReasoningSlider
from gui.theme import FONT_BODY


class ReasoningSliderTests(unittest.TestCase):
    VALUES = ("none", "minimal", "low", "medium", "high", "xhigh")

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.root.attributes("-alpha", 0.0)
        self.root.geometry("600x200")
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root.tk.call("set", "::reasoning_slider_bgerrors", "")
        self.root.tk.call("proc", "bgerror", "message", "lappend ::reasoning_slider_bgerrors $message")
        self.addCleanup(self._close_root)
        self.root.update()

    def _close_root(self):
        self.root.update_idletasks()
        self.root.destroy()
        self.root.tk.call("update")
        self.assertEqual(tuple(self.root.tk.splitlist(self.root.tk.call("set", "::reasoning_slider_bgerrors"))), ())
        self.assertEqual(self.errors, [])

    def slider(self, value="medium"):
        variable = tk.StringVar(self.root, value=value)
        slider = ReasoningSlider(self.root, variable=variable, values=self.VALUES, font=FONT_BODY)
        slider.pack(fill=tk.X, padx=16, pady=16)
        self.root.update()
        return slider, variable

    def key(self, slider, sequence):
        slider.focus_force()
        self.root.update()
        slider.event_generate(sequence)
        self.root.update()

    def click_value(self, slider, index):
        x = round(slider._positions()[index])
        y = slider.winfo_height() // 2
        slider.event_generate("<ButtonPress-1>", x=x, y=y)
        slider.event_generate("<ButtonRelease-1>", x=x, y=y)
        self.root.update()

    def test_clicks_preserve_all_existing_parameter_values_and_show_chinese_labels(self):
        slider, variable = self.slider()
        self.assertIsInstance(slider, tk.Canvas)
        self.assertEqual(slider.values, self.VALUES)
        self.assertEqual(tuple(self.root.tk.splitlist(slider.cget("values"))), self.VALUES)
        self.assertEqual(
            tkfont.Font(self.root, font=slider.cget("font")).metrics("linespace"),
            tkfont.Font(self.root, font=FONT_BODY).metrics("linespace"),
        )
        for index, value in enumerate(self.VALUES):
            with self.subTest(value=value):
                self.click_value(slider, index)
                self.assertEqual(variable.get(), value)
                self.assertEqual(slider.get(), value)
                self.assertRegex(slider.label_var.get(), "[\u4e00-\u9fff]")
                self.assertNotIn(value, slider.label_var.get())

    def test_keyboard_steps_and_bounds_use_exact_values(self):
        slider, variable = self.slider("medium")
        for sequence, expected in (("<Right>", "high"), ("<Right>", "xhigh"),
                                   ("<Right>", "xhigh"), ("<Left>", "high"),
                                   ("<Home>", "none"), ("<Left>", "none"),
                                   ("<Right>", "minimal"), ("<Right>", "low"),
                                   ("<End>", "xhigh")):
            with self.subTest(key=sequence, value=expected):
                self.key(slider, sequence)
                self.assertEqual(variable.get(), expected)

    def test_drag_snaps_to_nearest_step_without_fractional_storage(self):
        slider, variable = self.slider("auto")
        writes = []
        variable.trace_add("write", lambda *_args: writes.append(variable.get()))
        positions = slider._positions()
        y = slider.winfo_height() // 2
        slider.event_generate("<ButtonPress-1>", x=round(positions[0]), y=y)
        for x, expected in ((positions[1] + .2 * (positions[2] - positions[1]), "minimal"),
                            (positions[3] + .8 * (positions[4] - positions[3]), "high"),
                            (positions[0] - 20, "none"), (positions[-1] + 20, "xhigh")):
            with self.subTest(pointer_x=x):
                slider.event_generate("<B1-Motion>", x=round(x), y=y)
                self.root.update()
                self.assertEqual(slider.get(), expected)
        slider.event_generate("<ButtonRelease-1>", x=round(positions[-1]), y=y)
        self.root.update()
        self.assertTrue(writes)
        self.assertTrue(all(value in self.VALUES for value in writes), writes)

    def test_legacy_values_survive_construction_resize_and_focus_without_writes(self):
        for legacy in ("none", "minimal"):
            with self.subTest(value=legacy):
                slider, variable = self.slider(legacy)
                self.assertEqual(variable.get(), legacy)
                writes = []
                variable.trace_add("write", lambda *_args: writes.append(variable.get()))
                for width in (360, 820, 600):
                    self.root.geometry(f"{width}x200")
                    slider.focus_force()
                    self.root.update()
                    positions = slider._positions()
                    self.assertEqual(len(positions), len(self.VALUES))
                    self.assertEqual(tuple(positions), tuple(sorted(positions)))
                    self.assertEqual(slider.get(), legacy)
                self.assertEqual(writes, [])
                slider.destroy()
                self.root.update()

    def test_protocol_choices_do_not_silently_rewrite_saved_values(self):
        slider, variable = self.slider("high")
        native_choices = ("low", "medium", "high")
        slider.configure(values=native_choices)
        self.root.update()
        self.assertEqual(slider.values, native_choices)
        self.assertEqual(slider.get(), "high")
        slider.configure(values=self.VALUES)
        variable.set("xhigh")
        self.root.update()
        slider.configure(values=native_choices)
        self.root.update()
        self.assertEqual(slider.get(), "xhigh")
        for legacy in ("none", "minimal"):
            with self.subTest(value=legacy):
                slider.configure(values=self.VALUES)
                variable.set(legacy)
                self.root.update()
                slider.configure(values=self.VALUES)
                self.root.update()
                self.assertEqual(slider.get(), legacy)
                slider.configure(values=native_choices)
                self.root.update()
                self.assertEqual(slider.get(), legacy)

    def test_unknown_capability_is_gray_and_cannot_be_adjusted(self):
        variable = tk.StringVar(self.root, value="auto")
        slider = ReasoningSlider(self.root, variable=variable, values=())
        slider.pack(fill=tk.X)
        self.root.update()
        self.assertEqual(slider.values, ())
        self.assertEqual(str(slider.cget("state")), "disabled")
        self.assertEqual(str(slider.cget("cursor")), "arrow")
        slider._select(0)
        slider._step(1)
        slider.event_generate("<ButtonPress-1>", x=100, y=10)
        slider.event_generate("<B1-Motion>", x=300, y=10)
        self.key(slider, "<End>")
        self.assertEqual(variable.get(), "auto")
        self.assertFalse(slider._focused)

    def test_disabled_known_slider_does_not_change_value_or_keep_drag_active(self):
        slider, variable = self.slider("medium")
        self.click_value(slider, 3)
        slider.configure(state="disabled")
        self.root.update()
        slider.event_generate("<ButtonPress-1>", x=slider.winfo_width(), y=10)
        slider._step(1)
        slider._select(0)
        self.assertEqual(variable.get(), "medium")
        self.assertFalse(slider._dragging)
        slider.configure(state="normal")
        self.root.update()
        self.click_value(slider, len(slider.values) - 1)
        self.assertEqual(variable.get(), "xhigh")

    def test_auto_button_uses_default_and_manual_interaction_removes_highlight(self):
        slider, variable = self.slider("medium")
        button = AutoReasoningButton(self.root, variable=variable)
        button.pack()
        self.root.update()
        self.assertFalse(button.selected)
        button.invoke()
        self.assertTrue(button.selected)
        self.assertEqual(slider.get(), "auto")
        self.assertNotIn("auto", slider.values)
        self.assertEqual(str(slider.cget("state")), "normal")
        self.assertEqual(slider.label_var.get(), "默认")
        self.key(slider, "<Right>")
        self.assertEqual(slider.get(), slider.values[0])
        self.assertFalse(button.selected)

    def test_capability_update_and_single_level_stay_usable_without_selecting_default(self):
        variable = tk.StringVar(self.root, value="auto")
        slider = ReasoningSlider(self.root, variable=variable, values=())
        slider.pack(fill=tk.X)
        slider.configure(values=("auto", "high"), default_level="high", state="normal")
        self.root.update()
        self.assertEqual(slider.values, ("high",))
        self.assertEqual(slider.get(), "auto")
        self.assertEqual(slider._positions(), (slider.winfo_width() / 2,))
        self.click_value(slider, 0)
        self.assertEqual(slider.get(), "high")

    def test_extra_native_levels_and_budget_values_have_labels(self):
        slider, variable = self.slider("auto")
        slider.configure(values=("none", "enabled", "max", "ultra", "4096"))
        for index, value in enumerate(slider.values):
            self.click_value(slider, index)
            self.assertEqual(variable.get(), value)
            self.assertTrue(slider.label_var.get())
        self.assertEqual(slider.label_var.get(), "4096 Token")

    def test_auto_button_fits_existing_heading_and_cleans_variable_trace(self):
        for scaling in (1, 4 / 3, 2, 8 / 3):
            self.root.tk.call("tk", "scaling", scaling)
            variable = tk.StringVar(self.root, value="auto")
            traces = variable.trace_info()
            button = AutoReasoningButton(self.root, variable=variable)
            heading = tk.Label(self.root, text="思考强度", font=FONT_BODY)
            self.root.update_idletasks()
            self.assertLessEqual(button.winfo_reqheight(), heading.winfo_reqheight())
            button.destroy()
            heading.destroy()
            self.assertEqual(variable.trace_info(), traces)
            variable.set("high")

    def test_external_variable_updates_refresh_label_and_remain_exact(self):
        slider, variable = self.slider("auto")
        original_label = slider.label_var.get()
        variable.set("high")
        self.root.update()
        self.assertEqual(slider.get(), "high")
        self.assertNotEqual(slider.label_var.get(), original_label)
        self.assertRegex(slider.label_var.get(), "[\u4e00-\u9fff]")

    def test_destroy_removes_only_its_trace_and_keeps_variable_usable(self):
        variable = tk.StringVar(self.root, value="minimal")
        external_writes = []
        variable.trace_add("write", lambda *_args: external_writes.append(variable.get()))
        initial_traces = variable.trace_info()
        slider = ReasoningSlider(self.root, variable=variable, values=self.VALUES, font=FONT_BODY)
        slider.pack(fill=tk.X)
        self.root.update()
        self.assertGreater(len(variable.trace_info()), len(initial_traces))
        slider.destroy()
        self.root.update()
        self.assertEqual(variable.trace_info(), initial_traces)
        variable.set("high")
        self.root.update()
        self.assertEqual(external_writes[-1], "high")


if __name__ == "__main__":
    unittest.main()
