"""Tk geometry and responsive behavior regressions for the desktop GUI."""

from __future__ import annotations

import time
import tempfile
import tkinter as tk
import tkinter.font as tkfont
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gui.app import (
    AIMemoryGUI,
    COLOR_GENERATION_ACCENT,
    COLOR_TEXT_PRIMARY,
    FlatButton,
    HorizontalFileList,
    SummaryTopicCard,
)
from gui.settings_store import AppSettings, default_app_settings
from gui.widgets import GenerationChoiceCard, GlassNavigationItem


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
        self.scratch = tempfile.TemporaryDirectory()

    def load(self):
        return AppSettings(runtime_data_dir=Path(self.scratch.name))

    def save(self, settings):
        self.saved.append(settings)
        return settings


class TargetedAppearanceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def test_mode_description_wraps_without_losing_text_and_unwraps(self):
        subtitle = "默认方式，支持选择不同话题重要程度"
        for scaling in (1.0, 1.5, 2.0):
            with self.subTest(tk_scaling=scaling):
                self.root.tk.call("tk", "scaling", scaling)
                card = GenerationChoiceCard(
                    self.root, title="结构化总结", subtitle=subtitle,
                )
                card.pack(fill=tk.X)
                card.set_responsive_scale(1.0)
                title_space = card._title_font.measure(card._title) + 70
                narrow = title_space + card._subtitle_font.measure(subtitle) // 2 + 12
                wide = title_space + card._subtitle_font.measure(subtitle) + 20
                for width, wrapped in ((narrow, True), (wide, False), (narrow, True)):
                    self.root.geometry(f"{width}x300")
                    self.root.update()
                    items = [item for item in card.find_all()
                             if card.type(item) == "text"
                             and card.itemcget(item, "font") == str(card._subtitle_font)]
                    self.assertEqual(len(items), 1)
                    item = items[0]
                    self.assertEqual(card.itemcget(item, "text"), subtitle)
                    bounds = card.bbox(item)
                    line_height = card._subtitle_font.metrics("linespace")
                    if wrapped:
                        self.assertGreater(bounds[3] - bounds[1], line_height)
                        self.assertLessEqual(bounds[3] - bounds[1], 2 * line_height + 4)
                    else:
                        self.assertLessEqual(bounds[3] - bounds[1], line_height + 4)
                    self.assertGreaterEqual(bounds[1], 0)
                    self.assertLessEqual(bounds[3], card.winfo_height())
                    self.assertLessEqual(bounds[2], card.winfo_width() - 28)
                card.set_disabled(True)
                card._on_click()
                self.assertFalse(card.checked)
                card.set_disabled(False)
                card._on_click()
                self.assertTrue(card.checked)
                card.destroy()

    def test_sidebar_active_fill_is_gradient_without_accent_bar(self):
        self.root.geometry("240x100")
        item = GlassNavigationItem(self.root, "", "首页")
        item.pack(fill=tk.X)
        self.root.update()
        inactive_title_color = item.itemcget(item.find_withtag("title")[0], "fill")
        item._active = True
        item._progress = 1.0
        item.redraw()
        gradient = item.find_withtag("active_gradient")
        self.assertGreater(len(gradient), 10)
        self.assertEqual(set(item.find_withtag("card")), set(gradient))
        self.assertNotEqual(item.itemcget(gradient[0], "fill"),
                            item.itemcget(gradient[-1], "fill"))
        self.assertGreater(item.coords(gradient[0])[0],
                           item.coords(gradient[len(gradient) // 2])[0])
        self.assertEqual(item.itemcget(item.find_withtag("title")[0], "fill"),
                         inactive_title_color)


class SummaryTopicCardTests(unittest.TestCase):
    def test_card_toggles_and_expands_for_long_summary(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        try:
            root.withdraw()
            toggles = []
            card = SummaryTopicCard(
                root,
                index=1,
                title="一个需要重点展开的主题",
                summary="这是一段较长的主题摘要。" * 40,
                on_toggle=lambda item: toggles.append(item.checked),
                width=420,
            )
            card.pack()
            root.update_idletasks()

            self.assertFalse(card.checked)
            self.assertGreater(card.winfo_reqheight(), 88)
            card._toggle()
            self.assertTrue(card.checked)
            self.assertEqual(toggles, [True])
            indicator_items = card.find_withtag("selection_indicator")
            self.assertEqual(len(indicator_items), 3)
            self.assertEqual(
                [card.type(item) for item in indicator_items],
                ["polygon", "line", "line"],
            )
        finally:
            root.destroy()

    def test_topic_dialog_keeps_action_buttons_visible(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        try:
            root.attributes("-alpha", 0.0)
            root.geometry("1000x700+0+0")
            root.tk.call("tk", "scaling", 1.5)
            root.update_idletasks()
            app = object.__new__(AIMemoryGUI)
            app.root = root
            app._show_summary_topic_dialog(
                [
                    {
                        "topic_id": f"topic_{index}",
                        "title": f"第 {index} 个需要重点展开的主题",
                        "summary": "这是一段主题摘要。" * 3,
                    }
                    for index in range(1, 7)
                ],
                lambda _selected: None,
            )
            root.update()
            dialog = next(
                child for child in root.winfo_children()
                if isinstance(child, tk.Toplevel)
            )

            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)

            buttons = [
                widget for widget in descendants(dialog)
                if isinstance(widget, FlatButton)
            ]
            self.assertEqual(
                [button._text for button in buttons],
                ["暂不选择", "确认并继续生成"],
            )
            self.assertEqual(
                [button._variant for button in buttons],
                ["topic-secondary", "topic-primary"],
            )
            self.assertEqual(
                [(button._base_width, button._base_height) for button in buttons],
                [(132, 44), (196, 44)],
            )
            self.assertEqual(buttons[1].cget("bg"), COLOR_GENERATION_ACCENT)
            self.assertTrue(all(button.winfo_ismapped() for button in buttons))
            dialog_bottom = dialog.winfo_rooty() + dialog.winfo_height()
            self.assertTrue(all(
                button.winfo_rooty() + button.winfo_height() <= dialog_bottom
                for button in buttons
            ))
            canvas = next(
                widget for widget in descendants(dialog)
                if isinstance(widget, tk.Canvas)
                and not isinstance(widget, FlatButton)
            )
            self.assertLessEqual(
                canvas.winfo_rooty() + canvas.winfo_height(),
                min(button.winfo_rooty() for button in buttons),
            )
            dialog.grab_release()
            dialog.destroy()
        finally:
            root.destroy()


class GUIResponsiveGeometryTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.default_settings = AppSettings(Path(scratch.name) / "default-runtime")
        # 恢复默认后保存会写历史；不能让布局测试覆盖真实项目的历史文件。
        default_settings = patch(
            "gui.app.default_app_settings", return_value=self.default_settings,
        )
        default_settings.start()
        self.addCleanup(default_settings.stop)

    def test_continuous_resize_defers_font_work_until_drag_stops(self):
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        try:
            with (
                patch("gui.app.WindowsCredentialStore", return_value=_CredentialStore()),
                patch("gui.app.WindowsAppSettingsStore", return_value=_SettingsStore()),
            ):
                app = AIMemoryGUI(root)
            self._settle_resize(root, app)
            with patch.object(app, "_apply_responsive_scale") as scale:
                for width in (1100, 1120, 1140, 1160):
                    app._on_root_configure(SimpleNamespace(
                        widget=root, width=width, height=680,
                    ))
                    self._flush(root, 60)
                    scale.assert_not_called()
                self._flush(root, 180)
                scale.assert_called_once()
        finally:
            root.destroy()

    def test_unchanged_font_scale_does_not_recalculate_window_minimum(self):
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        try:
            with (
                patch("gui.app.WindowsCredentialStore", return_value=_CredentialStore()),
                patch("gui.app.WindowsAppSettingsStore", return_value=_SettingsStore()),
            ):
                app = AIMemoryGUI(root)
            self._flush(root, 300)
            with patch.object(app, "_schedule_responsive_minimums") as minimum:
                for _ in range(20):
                    app._apply_responsive_scale()
                minimum.assert_not_called()
        finally:
            root.destroy()

    def test_content_tracks_window_while_font_scaling_is_deferred(self):
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        try:
            with (
                patch("gui.app.WindowsCredentialStore", return_value=_CredentialStore()),
                patch("gui.app.WindowsAppSettingsStore", return_value=_SettingsStore()),
            ):
                app = AIMemoryGUI(root)
            self._settle_resize(root, app)
            initial_width = root.winfo_width()
            initial_height = root.winfo_height()
            # Keep sending real geometry changes faster than the font debounce.
            for page in range(4):
                app._show_page(page)
                self._settle_resize(root, app)
                with patch.object(app, "_apply_responsive_scale") as scale:
                    for delta in (24, 48, 72, 96):
                        root.geometry(
                            f"{initial_width + delta}x{initial_height + delta}"
                        )
                        self._flush(root, 35)
                        self.assertTrue(app._resize_in_progress)
                        self.assertEqual(
                            app.main_content.winfo_width(),
                            min(app.bg_canvas.winfo_width(), app._content_max_width),
                            "content width must follow the window during dragging",
                        )
                        self.assertGreaterEqual(
                            app.main_content.winfo_height(),
                            app.bg_canvas.winfo_height(),
                        )
                        scale.assert_not_called()
                root.geometry(f"{initial_width}x{initial_height}")
                self._settle_resize(root, app)
        finally:
            root.destroy()

    def test_capped_content_recenters_without_changing_its_dimensions(self):
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        try:
            with (
                patch("gui.app.WindowsCredentialStore", return_value=_CredentialStore()),
                patch("gui.app.WindowsAppSettingsStore", return_value=_SettingsStore()),
            ):
                app = AIMemoryGUI(root)
            self._settle_resize(root, app)
            app._content_max_width = 400
            app._refresh_scrollregion()
            self._flush(root)
            # Simulate a stale position while the content dimensions stay valid.
            app.bg_canvas.coords(app.canvas_window_id, 0, 0)
            app._refresh_scrollregion()
            self.assertEqual(
                app.bg_canvas.coords(app.canvas_window_id),
                [float((app.bg_canvas.winfo_width() - 400) // 2), 0.0],
            )
        finally:
            root.destroy()

    def test_history_only_lays_out_cards_near_the_viewport(self):
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        try:
            with (
                patch("gui.app.WindowsCredentialStore", return_value=_CredentialStore()),
                patch("gui.app.WindowsAppSettingsStore", return_value=_SettingsStore()),
            ):
                app = AIMemoryGUI(root)
            app.history_records = [
                {"title": f"记录 {index}", "saved_files": [f"result{index}.md"]}
                for index in range(60)
            ]
            app._refresh_history_list()
            app._show_page(2)
            self._settle_resize(root, app)
            cards = [card for _slot, card in app._history_slots]
            self.assertTrue(cards[0].winfo_manager())
            self.assertLess(sum(bool(card.winfo_manager()) for card in cards), 8)
            total_height = app.main_content.winfo_reqheight()
            app.bg_canvas.yview_moveto(1.0)
            self._flush(root, 100)
            self.assertFalse(cards[0].winfo_manager())
            self.assertTrue(cards[-1].winfo_manager())
            self.assertLess(sum(bool(card.winfo_manager()) for card in cards), 8)
            self.assertEqual(total_height, app.main_content.winfo_reqheight())
            # Native child Configure events must not reach the window handler.
            with patch.object(app, "_schedule_responsive_minimums") as minimum:
                for width in (1100, 1280, 1400, 1150):
                    root.geometry(f"{width}x680")
                    self._settle_resize(root, app)
                minimum.assert_not_called()
            app._show_page(0)
            self._flush(root)
            self.assertFalse(any(card.winfo_manager() for card in cards))
        finally:
            root.destroy()

    def test_repeated_minimize_restore_and_page_switch_keeps_ui_responsive(self):
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        errors, received = [], []
        root.report_callback_exception = lambda *error: errors.append(error)
        try:
            with (
                patch("gui.app.WindowsCredentialStore", return_value=_CredentialStore()),
                patch("gui.app.WindowsAppSettingsStore", return_value=_SettingsStore()),
            ):
                app = AIMemoryGUI(root)
            self._flush(root)
            for index in range(3):
                root.iconify()
                self._flush(root)
                self.assertEqual(root.state(), "iconic")
                app._post_ui(lambda value=index: received.append(value))
                app._post_ui(lambda value=index: received.append(f"visible-{value}"), visible=True)
                self._flush(root)
                self.assertIn(index, received)
                self.assertNotIn(f"visible-{index}", received)
                root.deiconify()
                self._flush(root)
                app._show_page((index + 1) % 4)
                self._flush(root)
                self.assertIn(f"visible-{index}", received)
                self.assertTrue(root.winfo_viewable())
                self.assertEqual(app._current_page, (index + 1) % 4)
            self.assertEqual(errors, [])
        finally:
            root.destroy()

    def test_history_file_list_scrolls_horizontally_only_when_needed(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        try:
            root.attributes("-alpha", 0.0)
            root.geometry("360x120+0+0")
            file_list = HorizontalFileList(
                root,
                text="📁 " + "、".join(f"very-long-output-{index}.md" for index in range(12)),
                tooltip_text="output files",
            )
            file_list.pack(fill=tk.X, padx=20, pady=20)
            self._flush(root)

            self.assertTrue(file_list.scrollbar.winfo_ismapped())
            self.assertLess(file_list.canvas.xview()[1], 1.0)
            initial_xview = file_list.canvas.xview()
            file_list._on_horizontal_wheel(SimpleNamespace(delta=-120, num=0))
            self._flush(root)
            self.assertGreater(file_list.canvas.xview()[0], initial_xview[0])

            file_list.destroy()
            short_file_list = HorizontalFileList(
                root,
                text="📁 summary.md",
                tooltip_text="summary.md",
            )
            short_file_list.pack(fill=tk.X, padx=20, pady=20)
            self._flush(root)
            self.assertFalse(short_file_list.scrollbar.winfo_ismapped())
        finally:
            root.destroy()

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
                    self._settle_resize(root, app)

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
                    entry = app.capsule_entry.entry
                    self.assertTrue(entry.bind("<Return>"))
                    entry.focus_force()
                    self._flush(root)
                    app.capsule_entry.set_text("https://example.com/share")
                    entry.event_generate("<Return>")
                    self._flush(root)
                    self.assertEqual(app._current_page, 1)

                    app._show_page(0)
                    app.capsule_entry.set_text("")
                    self._flush(root)
                    entry.focus_force()
                    self._flush(root)
                    entry.event_generate("<Return>")
                    self._flush(root)
                    self.assertEqual(app._current_page, 0)

                    app._select_summary_file(Path("dialog.md"))
                    self._flush(root)
                    entry.focus_force()
                    self._flush(root)
                    entry.event_generate("<Return>")
                    self._flush(root)
                    self.assertEqual(app._current_page, 1)
                    app._clear_summary_file()
                    app._show_page(0)

                    brand_font = tkfont.Font(
                        root=root, font=app.sidebar_title_label.cget("font"),
                    )
                    self.assertEqual(int(brand_font.actual("size")), 12)
                    self._assert_home_controls(root, app)
                    for nav_item in app._nav_items:
                        bounds = nav_item.bbox("content")
                        self.assertIsNotNone(bounds)
                        self.assertLessEqual(bounds[2], nav_item.winfo_width())
                        title_bounds = nav_item.bbox("title")
                        self.assertAlmostEqual(
                            (title_bounds[0] + title_bounds[2]) / 2,
                            nav_item.winfo_width() / 2,
                            delta=1,
                        )
                        self.assertEqual(
                            sum(nav_item.type(item) == "text"
                                for item in nav_item.find_all()),
                            1,
                            "sidebar navigation should contain only its centered title",
                        )
                        self.assertGreaterEqual(
                            int(nav_item._title_font.actual("size")), 12,
                        )
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
                        # 字体更新有意延后到用户停止拖动之后。
                        self._settle_resize(root, app)
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
                    self.assertEqual(max(sizes), min(sizes),
                                     "window resizing must not zoom every font")
                    self.assertEqual(root.tk.getint(app.status_label.cget("wraplength")), 0)

                    app._select_summary_file(
                        Path("C:/very/long/input") / ("long-name" * 16 + ".md"),
                    )
                    self.assertEqual(
                        app._selected_file_tooltip._text,
                        str(app.selected_summary_file),
                    )
                    self.assertEqual(root.tk.getint(app.selected_file_label.cget("width")), 56)
                    self.assertEqual(self._font_size(root, app.selected_file_label), 11)
                    capsule = app.selected_file_label.master
                    self.assertEqual(root.tk.getint(capsule.cget("padx")), 10)
                    self.assertEqual(root.tk.getint(capsule.cget("pady")), 4)
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
                    settings_tabs = settings_page.settings_tabs
                    settings_tabs.event_generate(
                        "<Button-1>",
                        x=settings_tabs._widths()[0] + 6,
                        y=settings_tabs._height // 2,
                    )
                    self._flush(root)
                    self.assertEqual(settings_tabs.selected_key, "data")
                    self.assertFalse(settings_tabs._focused)
                    self.assertEqual(
                        settings_tabs.master.cget("highlightbackground"),
                        settings_tabs.master.cget("highlightcolor"),
                    )
                    self.assertEqual(settings_page.data_page.winfo_manager(), "pack")
                    settings_tabs._move_selection(-1)
                    self._flush(root)
                    self.assertEqual(settings_tabs.selected_key, "api")
                    self.assertTrue(settings_tabs._focused)
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
                        str(self.default_settings.runtime_data_dir),
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
            {(0, 0), (1, 0), (2, 0), (3, 0)},
        )
        for card in cards:
            for item in card.find_all():
                if card.type(item) == "text":
                    bounds = card.bbox(item)
                    self.assertGreaterEqual(bounds[0], 0)
                    self.assertGreaterEqual(bounds[1], 0)
                    self.assertLessEqual(
                        bounds[2], card.winfo_width(),
                        f"{card._title}: {card.itemcget(item, 'text')!r} {bounds}",
                    )
                    self.assertLessEqual(
                        bounds[3], card.winfo_height(),
                        f"{card._title}: {card.itemcget(item, 'text')!r} {bounds}",
                    )
        left, right = app._generation_left_column, app._generation_right_column
        mode_panel = app._generation_mode_panel
        card_top = min(card.winfo_y() for card in cards)
        card_bottom = max(
            card.winfo_y() + card.winfo_height() for card in cards
        )
        self.assertGreater(mode_panel.winfo_height(), card_bottom - card_top)
        self.assertLess(
            mode_panel.winfo_height(), left.winfo_height(),
            "mode panel should keep its natural height instead of filling the column",
        )
        mode_title = app._generation_mode_title_label
        self.assertGreater(
            self._font_size(root, mode_title),
            int(app.card_raw._title_font.actual("size")),
            "mode-panel heading should remain stronger than mode-card titles",
        )
        mode_title_font = tkfont.Font(root=root, font=mode_title.cget("font"))
        self.assertLessEqual(
            mode_title_font.measure(mode_title.cget("text")), mode_title.winfo_width(),
            "mode-panel heading is clipped",
        )
        mode_count = mode_title.master.winfo_children()[1]
        self.assertLessEqual(
            mode_title.winfo_rootx() + mode_title.winfo_width(),
            mode_count.winfo_rootx(),
            "mode-panel heading overlaps the selected count",
        )
        self.assertGreaterEqual(
            self._font_size(root, app._generation_task_title_label), 11,
        )
        source_title = app._generation_source_title_label
        self.assertEqual(source_title.cget("fg"), COLOR_TEXT_PRIMARY)
        self.assertEqual(source_title.cget("anchor"), "center")
        self.assertGreaterEqual(self._font_size(root, source_title), 10)
        source_font = tkfont.Font(root=root, font=source_title.cget("font"))
        self.assertLessEqual(
            source_font.measure(source_title.cget("text")), source_title.winfo_width(),
            "source heading is clipped",
        )
        source_switch = app.card_source_url.master
        source_options = (app.card_source_url, app.card_source_file)
        self.assertTrue(all(option.winfo_ismapped() for option in source_options))
        self.assertTrue(all(option._disabled for option in source_options))
        self.assertTrue(all(option._regular_font.actual("size") >= 9
                            for option in source_options))
        option_left = min(option.winfo_rootx() for option in source_options)
        option_right = max(
            option.winfo_rootx() + option.winfo_width()
            for option in source_options
        )
        switch_left = source_switch.winfo_rootx()
        switch_right = switch_left + source_switch.winfo_width()
        self.assertGreaterEqual(option_left, switch_left)
        self.assertLessEqual(option_right, switch_right)
        self.assertAlmostEqual(
            (option_left + option_right) / 2,
            (switch_left + switch_right) / 2,
            delta=3,
            msg="source options should remain centered in their gray container",
        )
        self.assertEqual(
            int(app._generation_workspace.grid_columnconfigure(0)["weight"]), 3,
        )
        self.assertEqual(
            int(app._generation_workspace.grid_columnconfigure(1)["weight"]), 1,
        )
        self.assertGreaterEqual(
            right.winfo_rootx(), left.winfo_rootx() + left.winfo_width(),
        )
        self.assertEqual(left.winfo_rooty(), right.winfo_rooty())
        self.assertGreaterEqual(
            app._generation_task_panel.winfo_rootx(), right.winfo_rootx(),
        )
        self.assertEqual(
            app._generation_task_panel.winfo_rooty(), left.winfo_rooty(),
        )
        self.assertEqual(
            app._generation_task_panel.winfo_rooty()
            + app._generation_task_panel.winfo_height(),
            left.winfo_rooty() + left.winfo_height(),
            "task panel should match the height of the left-side content",
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
        content_bottom = max(
            app._generation_auth_panel.winfo_rooty()
            + app._generation_auth_panel.winfo_height(),
            app._generation_task_panel.winfo_rooty()
            + app._generation_task_panel.winfo_height(),
        )
        run_gap = app._generation_run_panel.winfo_rooty() - content_bottom
        self.assertGreaterEqual(run_gap, -2)
        self.assertLessEqual(run_gap, 24, "run panel should follow the content closely")
        canvas_left = app.bg_canvas.winfo_rootx()
        canvas_right = canvas_left + app.bg_canvas.winfo_width()
        for widget in (
            app.card_raw, app.card_normal, app.card_simple, app.card_detailed,
            app._generation_mode_panel, app._generation_auth_panel,
            right, app._generation_task_panel,
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
        self.assertGreaterEqual(self._font_size(root, app.home_title_label), 24)
        self.assertGreaterEqual(self._font_size(root, app.home_subtitle_label), 13)
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
        self.assertGreaterEqual(self._font_size(root, app.btn_send), 20)
        self.assertEqual(
            int(app._omnibox.content.cget("pady")), 0,
            "home input panel should not add unused space below its controls",
        )
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
        for _ in range(3):
            entries["gemini"].focus_force()
            self._flush(root)
            if root.focus_get() is entries["gemini"]:
                break
        focus_before = root.focus_get()
        self.assertIs(focus_before, entries["gemini"], "test window did not acquire initial focus")

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

        siliconflow = "siliconflow"
        self.assertEqual(order[1], siliconflow)
        list_top = page.api_rows_frame.winfo_rooty()
        list_bottom = list_top + page.api_rows_frame.winfo_height()
        list_left = page.api_rows_frame.winfo_rootx()
        list_center_x = list_left + page.api_rows_frame.winfo_width() // 2
        page._drag_start(None, siliconflow)
        page._drag_motion(SimpleNamespace(
            y_root=list_top + 1,
            x_root=list_center_x,
        ))
        self.assertEqual(
            page._drag_state["preview_order"],
            [siliconflow, order[0], order[2]],
            "the middle provider should be droppable above the top row",
        )
        page._drag_end(SimpleNamespace(
            y_root=list_top + 1,
            x_root=list_center_x,
        ))
        self.assertEqual(page.ordered_providers[0], siliconflow)

        page._drag_start(None, siliconflow)
        page._drag_motion(SimpleNamespace(
            y_root=list_top + 59,
            x_root=list_center_x,
        ))
        page._drag_end(SimpleNamespace(
            y_root=list_top + 59,
            x_root=list_center_x,
        ))
        self.assertEqual(page.ordered_providers[1], siliconflow)
        page._drag_start(None, siliconflow)
        page._drag_motion(SimpleNamespace(
            y_root=list_bottom - 1,
            x_root=list_center_x,
        ))
        self.assertEqual(
            page._drag_state["preview_order"][-1], siliconflow,
            "the middle provider should be droppable below the bottom row",
        )
        page._drag_end(SimpleNamespace(
            y_root=list_bottom - 1,
            x_root=list_center_x,
        ))
        self.assertEqual(page.ordered_providers[-1], siliconflow)
        page._drag_start(None, siliconflow)
        page._drag_motion(SimpleNamespace(
            y_root=list_top + 50,
            x_root=list_center_x,
        ))
        page._drag_end(SimpleNamespace(
            y_root=list_top + 50,
            x_root=list_center_x,
        ))
        self.assertEqual(page.ordered_providers, order)
        self._flush(root)
        order = list(page.ordered_providers)

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

    def _settle_resize(self, root, app):
        deadline = time.perf_counter() + 3
        stable = 0
        while time.perf_counter() < deadline:
            self._flush(root, 80)
            pending = (
                app._responsive_after_id, app._minimum_layout_after_id,
                app._scrollregion_after_id,
            )
            if not any(item is not None for item in pending) and not app._resize_in_progress:
                stable += 1
                if stable == 2:
                    return
            else:
                stable = 0
        self.fail("resize layout did not settle")

    @staticmethod
    def _flush(root, duration_ms=65):
        root.update_idletasks()
        root.after(duration_ms, root.quit)
        root.mainloop()
        root.update_idletasks()


if __name__ == "__main__":
    unittest.main()
