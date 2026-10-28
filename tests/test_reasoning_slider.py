"""Discrete reasoning slider behavior with the existing API parameter values."""

import tkinter as tk
import tkinter.font as tkfont
import unittest

from gui.reasoning_slider import ReasoningSlider
from gui.theme import FONT_BODY


class ReasoningSliderTests(unittest.TestCase):
    VALUES = ("auto", "none", "minimal", "low", "medium", "high", "xhigh")

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
                                   ("<Home>", "auto"), ("<Left>", "auto"),
                                   ("<Right>", "none"), ("<Right>", "minimal"),
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
        for x, expected in ((positions[2] + .2 * (positions[3] - positions[2]), "minimal"),
                            (positions[4] + .8 * (positions[5] - positions[4]), "high"),
                            (positions[0] - 20, "auto"), (positions[-1] + 20, "xhigh")):
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

    def test_protocol_choices_preserve_supported_values_and_reset_unsupported_to_auto(self):
        slider, variable = self.slider("high")
        native_choices = ("auto", "low", "medium", "high")
        slider.configure(values=native_choices)
        self.root.update()
        self.assertEqual(slider.values, native_choices)
        self.assertEqual(slider.get(), "high")
        slider.configure(values=self.VALUES)
        variable.set("xhigh")
        self.root.update()
        slider.configure(values=native_choices)
        self.root.update()
        self.assertEqual(slider.get(), "auto")
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
                self.assertEqual(slider.get(), "auto")

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
