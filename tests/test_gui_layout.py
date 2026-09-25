"""Tk geometry and responsive behavior regressions for the desktop GUI."""

from __future__ import annotations

import time
import tkinter as tk
import tkinter.font as tkfont
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gui.app import AIMemoryGUI
from gui.settings_store import default_app_settings


class _CredentialStore:
    def __init__(self):
        self.saved_keys = None
        self.saved_order = None

    def load_api_keys(self):
        return {}

    def load_provider_order(self):
        return ("gemini", "siliconflow", "deepseek")

    def save_api_keys(self, keys):
        self.saved_keys = dict(keys)

    def save_provider_order(self, order):
        self.saved_order = list(order)


class _SettingsStore:
    def __init__(self):
        self.saved = []

    def load(self):
        return default_app_settings()

    def save(self, settings):
        self.saved.append(settings)
        return settings


class GUIResponsiveGeometryTests(unittest.TestCase):
    def test_same_window_resizes_without_drift_and_preserves_layout(self):
        for scaling in (1.0, 1.25, 1.5):
            with self.subTest(tk_scaling=scaling):
                try:
                    root = tk.Tk()
                except tk.TclError as error:
                    self.skipTest(f"Tk display unavailable: {error}")
                try:
                    root.attributes("-alpha", 0.0)
                    root.tk.call("tk", "scaling", scaling)
                    credentials = _CredentialStore()
                    settings = _SettingsStore()
                    with (
                        patch("gui.app.WindowsCredentialStore", return_value=credentials),
                        patch("gui.app.WindowsAppSettingsStore", return_value=settings),
                    ):
                        app = AIMemoryGUI(root)
                    self._flush(root)

                    minimum = app.minimum_window_width
                    available_width = root.winfo_screenwidth() - 32
                    self.assertGreaterEqual(minimum, 880)
                    self.assertFalse(
                        app.layout_requires_wider_screen,
                        f"compact layout still exceeds screen: {minimum}>{available_width}",
                    )
                    initial_width = root.winfo_width()
                    self.assertGreaterEqual(initial_width, minimum)
                    self.assertLessEqual(initial_width, available_width)
                    self.assertGreaterEqual(initial_width, min(minimum + 32, available_width))
                    self.assertGreaterEqual(app.sidebar.winfo_width(), 210)
                    self.assertLessEqual(app.sidebar.winfo_width(), 260)
                    brand_font = tkfont.Font(
                        root=root, font=app.sidebar_title_label.cget("font"),
                    )
                    self.assertEqual(int(brand_font.actual("size")), 12)
                    self._assert_home_controls(root, app)
                    for nav_item in app._nav_items:
                        bounds = nav_item.bbox("content")
                        self.assertIsNotNone(bounds)
                        self.assertLessEqual(bounds[2], nav_item.winfo_width())
                    self.assertLessEqual(
                        app.sidebar_title_label.winfo_rootx()
                        + app.sidebar_title_label.winfo_width(),
                        app.sidebar.winfo_rootx() + app.sidebar.winfo_width(),
                    )
                    logo_row = app.sidebar_title_label.master
                    self.assertIs(logo_row.winfo_children()[1], app.sidebar_title_label)
                    logo = logo_row.winfo_children()[0]
                    self.assertLess(
                        max(logo.winfo_rooty(), app.sidebar_title_label.winfo_rooty()),
                        min(
                            logo.winfo_rooty() + logo.winfo_height(),
                            app.sidebar_title_label.winfo_rooty()
                            + app.sidebar_title_label.winfo_height(),
                        ),
                    )

                    app._show_page(1)
                    default_width = max(minimum, 1040)
                    wide_width = min(1600, available_width)
                    widths = (
                        minimum, default_width, min(1280, available_width),
                        wide_width, default_width, wide_width, minimum,
                    )
                    sizes = []
                    observed_sizes = {}
                    for width in widths:
                        root.geometry(f"{width}x680")
                        self._flush(root)
                        self._assert_generation_geometry(root, app)
                        size = int(app.status_label._responsive_font.actual("size"))
                        sizes.append(size)
                        actual_width = root.winfo_width()
                        if actual_width in observed_sizes:
                            self.assertEqual(
                                size, observed_sizes[actual_width],
                                f"font drift at repeated width {actual_width}",
                            )
                        observed_sizes[actual_width] = size
                    self.assertGreaterEqual(max(sizes), min(sizes))
                    self.assertGreater(max(sizes), min(sizes))
                    self.assertEqual(root.tk.getint(app.status_label.cget("wraplength")), 0)

                    app._select_summary_file(
                        Path("C:/very/long/input") / ("long-name" * 16 + ".md"),
                    )
                    self.assertEqual(
                        app._selected_file_tooltip._text,
                        str(app.selected_summary_file),
                    )
                    self.assertEqual(root.tk.getint(app.selected_file_label.cget("width")), 56)
                    app._clear_summary_file()

                    switches = []
                    for page in (2, 3, 0, 1) * 4:
                        started = time.perf_counter()
                        app._show_page(page)
                        switches.append(time.perf_counter() - started)
                    self.assertLess(max(switches), 0.05)

                    app.history_records = [{
                        "title": "超长历史任务标题" * 18,
                        "timestamp": "2026-09-24 12:34",
                        "succeeded": True,
                        "program_seconds": 1.0,
                        "fetch_seconds": 2.0,
                        "generation_seconds": 3.0,
                        "wait_seconds": 0.0,
                        "total_seconds": 6.0,
                        "file_count": 1,
                        "saved_files": ["超长输出文件名" * 18 + ".md"],
                        "output_dir": "C:/very/long/output/path",
                    }]
                    app._refresh_history_list()
                    app._show_page(2)
                    self._flush(root)
                    self.assertGreaterEqual(
                        app.bg_canvas.bbox(app.canvas_window_id)[3]
                        - app.bg_canvas.bbox(app.canvas_window_id)[1],
                        app.bg_canvas.winfo_height(),
                    )

                    app._show_page(3)
                    settings_page = app.page_frames[3]
                    settings_page.show_page("api")
                    self._flush(root)
                    self._assert_api_reorder_preserves_inputs(root, app, credentials)

                    settings_page.show_page("data")
                    self._flush(root)
                    data_page = settings_page.data_page
                    data_page.runtime_var.set("C:/very/long/runtime/path/" * 10)
                    data_page.results_var.set("C:/very/long/results/path/" * 10)
                    self.assertEqual(data_page.reset_button.cget("text"), "恢复默认")
                    data_page.reset_button.invoke()
                    self.assertEqual(
                        data_page.runtime_var.get(),
                        str(default_app_settings().runtime_data_dir),
                    )
                    self.assertEqual(data_page.results_var.get(), "")
                    self.assertEqual(settings.saved, [], "reset must not persist")
                    self.assertLess(
                        data_page.reset_button.winfo_rootx(),
                        data_page.save_button.winfo_rootx(),
                    )
                    self.assertLessEqual(
                        data_page.save_button.winfo_rootx()
                        + data_page.save_button.winfo_width(),
                        data_page.footer.winfo_rootx() + data_page.footer.winfo_width(),
                    )
                    data_page.save_button.invoke()
                    self.assertEqual(len(settings.saved), 1)
                    self.assertIsNone(settings.saved[0].default_results_dir)
                finally:
                    root.destroy()

    def _assert_generation_geometry(self, root, app):
        cards = (app.card_raw, app.card_normal, app.card_simple, app.card_detailed)
        self.assertEqual(
            {(int(card.grid_info()["row"]), int(card.grid_info()["column"]))
             for card in cards},
            {(0, 0), (0, 1), (1, 0), (1, 1)},
        )
        for card in cards:
            for item in card.find_all():
                if card.type(item) == "text":
                    bounds = card.bbox(item)
                    self.assertGreaterEqual(bounds[0], 0)
                    self.assertLessEqual(
                        bounds[2], card.winfo_width(),
                        f"{card._title}: {card.itemcget(item, 'text')!r} {bounds}",
                    )
        left, right = app._generation_left_column, app._generation_right_column
        self.assertGreaterEqual(
            right.winfo_rootx(), left.winfo_rootx() + left.winfo_width(),
        )
        self.assertEqual(left.winfo_rooty(), right.winfo_rooty())
        self.assertGreaterEqual(
            app._generation_task_panel.winfo_rootx(), right.winfo_rootx(),
        )
        self.assertGreaterEqual(
            app._generation_tip_panel.winfo_rootx(), right.winfo_rootx(),
        )
        self.assertEqual(root.tk.getint(app._generation_tip_copy.cget("wraplength")), 0)
        tip_font = tkfont.Font(root=root, font=app._generation_tip_copy.cget("font"))
        self.assertLessEqual(
            tip_font.measure(app._generation_tip_copy.cget("text")),
            app._generation_tip_copy.winfo_width(),
        )
        for row in app._generation_task_panel.winfo_children():
            labels = [child for child in row.winfo_children()
                      if isinstance(child, tk.Label)]
            if len(labels) == 2:
                self.assertLessEqual(
                    labels[0].winfo_rootx() + labels[0].winfo_width(),
                    labels[1].winfo_rootx(),
                )
        auth_options = (app.card_no_login, app.card_need_login)
        self.assertIs(auth_options[0].master, auth_options[1].master)
        self.assertLessEqual(
            auth_options[0].winfo_rootx() + auth_options[0].winfo_width(),
            auth_options[1].winfo_rootx(),
        )
        self.assertLess(
            max(option.winfo_rooty() for option in auth_options),
            min(option.winfo_rooty() + option.winfo_height() for option in auth_options),
        )
        auth_caption = app._generation_auth_panel.winfo_children()[0].winfo_children()[1]
        caption_font = tkfont.Font(root=root, font=auth_caption.cget("font"))
        self.assertLessEqual(
            caption_font.measure(auth_caption.cget("text")),
            auth_caption.winfo_width(),
            "single-line access caption is clipped",
        )

        status = app._generation_status_copy
        button = app.btn_generate
        self.assertLessEqual(
            status.winfo_rootx() + status.winfo_width(), button.winfo_rootx(),
        )
        self.assertLess(
            max(status.winfo_rooty(), button.winfo_rooty()),
            min(
                status.winfo_rooty() + status.winfo_height(),
                button.winfo_rooty() + button.winfo_height(),
            ),
        )
        self.assertTrue(button.winfo_ismapped())
        canvas_left = app.bg_canvas.winfo_rootx()
        canvas_right = canvas_left + app.bg_canvas.winfo_width()
        for widget in (
            app.card_raw, app.card_normal, app.card_simple, app.card_detailed,
            app._generation_mode_panel, app._generation_auth_panel,
            right, app._generation_task_panel, app._generation_tip_panel,
            app._generation_run_panel, button,
        ):
            self.assertGreaterEqual(
                widget.winfo_rootx(), canvas_left,
                f"{widget} starts left of visible canvas",
            )
            self.assertLessEqual(
                widget.winfo_rootx() + widget.winfo_width(), canvas_right,
                f"{widget} is clipped by visible canvas",
            )
        heading_copy = app._generation_section.winfo_children()[0].winfo_children()[0]
        self.assertEqual(
            [child.cget("text") for child in heading_copy.winfo_children()
             if isinstance(child, tk.Label)],
            ["生成记忆总结"],
        )
        self.assertEqual(len(app.bg_canvas.find_withtag("gradient_bg")), 1)
        canvas_width = int(float(app.bg_canvas.itemcget(
            app.canvas_window_id, "width",
        )))
        self.assertEqual(
            canvas_width,
            min(app.bg_canvas.winfo_width(), app._content_max_width),
        )
        self.assertLessEqual(root.winfo_width(), 1600)

    def _assert_home_controls(self, root, app):
        for widget in (
            app.home_subtitle_label,
            app.file_select_button,
            app.paste_link_button,
            app.selected_file_label,
        ):
            self.assertGreaterEqual(
                self._font_size(root, widget), 11,
                f"{widget} is below the home-control minimum",
            )
        self.assertGreaterEqual(self._font_size(root, app.btn_send), 17)
        for button in (app.file_select_button, app.paste_link_button):
            self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
        subtitle_font = tkfont.Font(
            root=root, font=app.home_subtitle_label.cget("font"),
        )
        self.assertLessEqual(
            subtitle_font.measure(app.home_subtitle_label.cget("text")),
            app.home_subtitle_label.winfo_width(),
        )

    @staticmethod
    def _font_size(root, widget):
        font = getattr(widget, "_responsive_font", None)
        if font is None:
            font = tkfont.Font(root=root, font=widget.cget("font"))
        return int(font.actual("size"))

    def _assert_api_reorder_preserves_inputs(self, root, app, credentials):
        page = app.page_frames[3]
        rows = page.api_row_refs
        variables = page.api_key_vars
        order = list(page.ordered_providers)
        row_ids = {provider: id(row) for provider, row in rows.items()}
        variable_ids = {provider: id(var) for provider, var in variables.items()}
        entries = {
            provider: next(
                child for child in row.winfo_children()
                if isinstance(child, tk.Entry)
            )
            for provider, row in rows.items()
        }
        entry_ids = {provider: id(entry) for provider, entry in entries.items()}
        variables["gemini"].set("unsaved-key-value")
        entries["gemini"].focus_force()
        self._flush(root)
        focus_before = root.focus_get()

        first = order[0]
        page._drag_start(None, first)
        page._drag_end(None)
        self.assertEqual(page.ordered_providers, order, "same-row drop changed order")

        page._drag_start(None, first)
        page._drag_motion(SimpleNamespace(
            y_root=page.api_rows_frame.winfo_rooty() - 12,
            x_root=page.api_rows_frame.winfo_rootx() + page.api_rows_frame.winfo_width() // 2,
        ))
        page._drag_end(None)
        self.assertEqual(page.ordered_providers, order, "outside drop changed order")
        self.assertEqual(
            {provider: row.winfo_y() for provider, row in rows.items()},
            {provider: index * 42 for index, provider in enumerate(order)},
        )

        target = order[1]
        original_positions = {
            provider: row.winfo_y() for provider, row in rows.items()
        }
        list_left = page.api_rows_frame.winfo_rootx()
        list_center_x = list_left + page.api_rows_frame.winfo_width() // 2
        source_center_y = rows[first].winfo_rooty() + rows[first].winfo_height() // 2
        page._drag_start(None, first)
        page._drag_motion(SimpleNamespace(
            y_root=source_center_y + 6,
            x_root=list_center_x,
        ))
        self.assertEqual(
            page._drag_state["preview_order"], order,
            "a small movement within the source row changed the preview",
        )
        self.assertTrue(all(
            rows[provider].winfo_y() == original_positions[provider]
            for provider in order if provider != first
        ))

        target_center_y = (
            rows[target].winfo_rooty() + rows[target].winfo_height() // 2 + 1
        )
        page._drag_motion(SimpleNamespace(
            y_root=target_center_y,
            x_root=list_center_x,
        ))
        self.assertEqual(
            page._drag_state["preview_order"],
            [target, first, order[2]],
        )
        self._flush(root, duration_ms=40)
        self.assertEqual(rows[first].winfo_y(), 43)
        self.assertGreater(rows[target].winfo_y(), 0)
        self.assertLess(
            rows[target].winfo_y(), original_positions[target],
            "the adjacent row did not move through an intermediate frame",
        )
        self.assertEqual(page.ordered_providers, order)
        page._drag_end(SimpleNamespace(
            y_root=target_center_y,
            x_root=list_center_x,
        ))
        adjacent_order = [target, first, order[2]]
        self.assertEqual(page.ordered_providers, adjacent_order)
        self.assertEqual({key: id(row) for key, row in rows.items()}, row_ids)
        self.assertEqual({key: id(var) for key, var in variables.items()}, variable_ids)
        self.assertEqual({key: id(entry) for key, entry in entries.items()}, entry_ids)
        self.assertEqual(variables["gemini"].get(), "unsaved-key-value")
        self.assertIs(focus_before, entries["gemini"])
        self.assertIs(root.focus_get(), focus_before)

        order = list(page.ordered_providers)
        first = order[0]
        target = order[-1]
        original_positions = {
            provider: row.winfo_y() for provider, row in rows.items()
        }
        list_top = page.api_rows_frame.winfo_rooty()
        list_bottom = list_top + page.api_rows_frame.winfo_height()
        page._drag_start(None, first)
        page._drag_motion(SimpleNamespace(
            y_root=rows[target].winfo_rooty() + rows[target].winfo_height() // 2 + 1,
            x_root=list_center_x,
        ))
        self._flush(root)
        self.assertNotEqual(
            rows[first].winfo_y(), original_positions[first],
            "dragged row did not follow the pointer before release",
        )
        self.assertTrue(
            any(rows[p].winfo_y() != original_positions[p] for p in order if p != first),
            "neighbor rows did not move before release",
        )
        self.assertEqual(
            rows[first].winfo_y(),
            page.api_rows_frame.winfo_height() - rows[first].winfo_height(),
            "dragged row was not clamped to the list bounds",
        )
        self.assertEqual(
            page.ordered_providers, order,
            "preview must not commit provider order before release",
        )
        self.assertTrue(page._drag_state["active"])
        page._drag_end(None)
        self.assertEqual(page.ordered_providers, order[1:] + order[:1])

        app._show_page(2)
        self.assertIsNone(page.api_animation["after_id"])
        self._flush(root)
        self.assertEqual(
            {provider: rows[provider].winfo_y()
             for provider in page.ordered_providers},
            {provider: index * 42
             for index, provider in enumerate(page.ordered_providers)},
        )
        app._show_page(3)
        page.show_page("api")
        order = list(page.ordered_providers)
        first = order[0]
        page._drag_start(None, first)
        page._drag_motion(SimpleNamespace(
            y_root=list_bottom - 10, x_root=list_center_x,
        ))
        self._flush(root)
        self.assertEqual(page.ordered_providers, order)
        page.show_page("data")
        self._flush(root)
        self.assertEqual(page.ordered_providers, order)
        self.assertFalse(page._drag_state["active"])
        self.assertIsNone(page.api_animation["after_id"])
        page.show_page("api")

        page._drag_start(None, first)
        page._drag_motion(SimpleNamespace(
            y_root=list_bottom - 10, x_root=list_center_x,
        ))
        self._flush(root)
        app._show_page(2)
        self.assertEqual(page.ordered_providers, order)
        self.assertFalse(page._drag_state["active"])
        self.assertIsNone(page.api_animation["after_id"])
        app._show_page(3)
        page.show_page("api")
        page.api_save_button.invoke()
        self.assertEqual(credentials.saved_keys["gemini"], "unsaved-key-value")
        self.assertEqual(credentials.saved_order, page.ordered_providers)

    @staticmethod
    def _flush(root, duration_ms=65):
        root.update_idletasks()
        root.after(duration_ms, root.quit)
        root.mainloop()
        root.update_idletasks()


if __name__ == "__main__":
    unittest.main()
