"""Argon 前端自定义 Canvas/Frame 复合控件库。

所有控件均遵循统一的设计系统令牌（gui.theme），并在 <Destroy> 生命周期中
自动清理挂起的 Tcl after 定时器，杜绝窗口切换或销毁时的孤儿回调异常。
"""

from __future__ import annotations

import math
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from gui.theme import (
    COLOR_ACCENT,
    COLOR_ACCENT_BG,
    COLOR_ACCENT_BLUE,
    COLOR_BG_APP,
    COLOR_BORDER,
    COLOR_BORDER_FOCUS,
    COLOR_BORDER_SUBTLE,
    COLOR_CARD,
    COLOR_DISABLED,
    COLOR_GENERATION_ACCENT,
    COLOR_GENERATION_ACCENT_HOVER,
    COLOR_HOVER,
    COLOR_OMNIBOX_BORDER,
    COLOR_OMNIBOX_SURFACE,
    COLOR_SIDEBAR,
    COLOR_TEXT_DISABLED,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_TOPIC_CARD_HOVER,
    COLOR_TOPIC_CARD_SELECTED,
    COLOR_TOPIC_CONTROL,
    COLOR_TOPIC_DIALOG_BG,
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_FAMILY,
    FONT_H2,
    FONT_SIDEBAR_ITEM,
    FONT_SMALL,
    FONT_SMALL_BOLD,
    FONT_TINY,
    _logo_png_path,
    _mix_color,
    _navigation_icon_path,
    _round_rectangle,
    _scaled_font_size,
)


class StackedLayersIcon(tk.Canvas):
    """显示正式版分层记忆 Logo 的透明 PNG 资源。"""

    def __init__(self, master, width: int, height: int, bg: str, **kwargs):
        super().__init__(
            master, width=width, height=height, bg=bg,
            highlightthickness=0, bd=0, **kwargs,
        )
        self._icon_width = width
        self._icon_height = height
        requested_size = min(width, height)
        self._asset_size = min(
            (16, 32, 40, 64, 128, 256, 512, 1024),
            key=lambda size: abs(size - requested_size),
        )
        self._image = tk.PhotoImage(
            file=str(_logo_png_path(self._asset_size))
        )
        self._draw()

    def _draw(self):
        self.delete("icon")
        self.create_image(
            self._icon_width / 2,
            self._icon_height / 2,
            image=self._image,
            anchor=tk.CENTER,
            tags="icon",
        )


# ==================== 极简扁平滚动条 ====================

class MinimalScrollbar(tk.Canvas):
    """纤细圆角胶囊滚动条（按需显现、悬停加深）。"""

    def __init__(
        self,
        master,
        target_canvas: tk.Canvas,
        width: int = 6,
        **kwargs,
    ):
        super().__init__(
            master, width=width, highlightthickness=0,
            bg=COLOR_BG_APP, **kwargs,
        )
        self.target = target_canvas
        self._width = width
        self._thumb_id = None
        self._drag_start_y = 0
        self._drag_start_first = 0.0
        self._first = 0.0
        self._last = 1.0
        self._hover = False
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set_range(self, first: str, last: str):
        try:
            f = float(first)
            l = float(last)
        except (TypeError, ValueError):
            return
        self._first, self._last = f, l
        self.redraw()

    def _set_hover(self, hover: bool):
        self._hover = hover
        self.redraw()

    def redraw(self):
        self.delete("thumb")
        h = max(self.winfo_height(), 1)
        span = max(0.0, self._last - self._first)
        if span >= 1.0:
            return
        thumb_h = max(28, int(h * span))
        thumb_y = int(h * self._first)
        color = "#475569" if self._hover else "#CBD5E1"
        self._thumb_id = _round_rectangle(
            self, 1, thumb_y, self._width - 1, thumb_y + thumb_h,
            r=(self._width - 2) / 2,
            fill=color, outline="", tags="thumb",
        )

    def _on_click(self, event):
        self._drag_start_y = event.y
        self._drag_start_first = self._first

    def _on_drag(self, event):
        h = max(self.winfo_height(), 1)
        delta = (event.y - self._drag_start_y) / h
        new_first = max(
            0.0,
            min(1.0 - (self._last - self._first),
                self._drag_start_first + delta),
        )
        self.target.yview_moveto(new_first)

    def _on_release(self, _event):
        self._drag_start_y = 0


# ==================== 极简扁平按钮 ====================

class FlatButton(tk.Canvas):
    """扁平圆角按钮：支持主按钮、紫调强调按钮、设置渐变保存按钮及次要描边按钮。"""

    def __init__(
        self,
        master,
        text: str,
        command: callable = None,
        variant: str = "primary",
        width: int = 220,
        height: int = 44,
        icon_text: str = "",
        bg_parent: str = COLOR_BG_APP,
        **kwargs,
    ):
        super().__init__(
            master, width=width, height=height,
            highlightthickness=0, bg=bg_parent, **kwargs,
        )
        self._text = text
        self._command = command
        self._variant = variant
        self._base_width = width
        self._base_height = height
        self._width = width
        self._height = height
        self._bg_parent = bg_parent
        self._font = tkfont.Font(master=self, font=FONT_BODY_BOLD)
        self._icon_text = icon_text
        self._icon_font = (
            tkfont.Font(master=self, font=("Segoe MDL2 Assets", 12))
            if icon_text else None
        )
        self._enabled = True
        self._hover = False
        self._focused = False
        self._suppress_focus_ring = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.configure(takefocus=True, cursor="hand2")
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Return>", self._on_key_activate)
        self.bind("<space>", self._on_key_activate)
        self.redraw()

    def set_responsive_scale(self, scale: float):
        self._font.configure(size=_scaled_font_size(self._font, scale, 9, 11))
        if self._icon_font:
            self._icon_font.configure(
                size=_scaled_font_size(self._icon_font, scale, 11, 13)
            )
        icon_width = (
            self._icon_font.measure(self._icon_text) + 8
            if self._icon_font else 0
        )
        self._width = max(
            round(self._base_width * scale),
            self._font.measure(self._text) + icon_width + 32,
        )
        self._height = max(
            round(self._base_height * scale), self._font.metrics("linespace") + 16,
        )
        self.configure(width=self._width, height=self._height)
        self.redraw()

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        self.configure(cursor="hand2" if self._enabled else "arrow")
        self.redraw()

    def _on_enter(self, _event=None):
        self._hover = True
        self.redraw()

    def _on_leave(self, _event=None):
        self._hover = False
        self.redraw()

    def _on_focus_in(self, _event=None):
        self._focused = not self._suppress_focus_ring
        self.redraw()

    def _on_focus_out(self, _event=None):
        self._focused = False
        self._suppress_focus_ring = False
        self.redraw()

    def _on_key_activate(self, _event=None):
        self._suppress_focus_ring = False
        self._focused = True
        self.redraw()
        self.invoke()
        return "break"

    def _on_click(self, _event=None):
        self._suppress_focus_ring = True
        self.focus_set()
        self._focused = False
        self.redraw()
        if self._enabled and self._command:
            self._command()

    def invoke(self):
        if self._enabled and self._command:
            return self._command()
        return None

    def redraw(self):
        self.delete("all")
        if self._variant == "settings-save":
            self._draw_settings_save_button()
            return
        if self._variant == "topic-primary":
            self.configure(
                bg=COLOR_GENERATION_ACCENT if self._enabled else COLOR_DISABLED,
            )
            bg = (
                COLOR_GENERATION_ACCENT_HOVER
                if (self._hover and self._enabled)
                else (COLOR_GENERATION_ACCENT if self._enabled else COLOR_DISABLED)
            )
            fg = "#FFFFFF" if self._enabled else COLOR_TEXT_DISABLED
            _round_rectangle(
                self, 1, 1, self._width - 2, self._height - 2, r=10,
                fill=bg, outline=bg, width=1,
            )
            if self._focused and self._enabled:
                _round_rectangle(
                    self, 3, 3, self._width - 4, self._height - 4, r=8,
                    fill="", outline="#FFFFFF", width=1.5,
                )
            self.create_text(
                self._width // 2, self._height // 2,
                text=self._text, fill=fg, font=self._font,
            )
            return
        if self._variant == "topic-secondary":
            self.configure(bg=self._bg_parent)
            bg = "#EAECEF" if self._hover else COLOR_CARD
            outline = "#BEC6D2" if self._hover else "#D0D6E0"
            _round_rectangle(
                self, 1, 1, self._width - 2, self._height - 2, r=10,
                fill=bg, outline=outline, width=1,
            )
            if self._focused and self._enabled:
                _round_rectangle(
                    self, 3, 3, self._width - 4, self._height - 4, r=8,
                    fill="", outline=COLOR_GENERATION_ACCENT, width=2,
                )
            self.create_text(
                self._width // 2, self._height // 2,
                text=self._text, fill=COLOR_TEXT_SECONDARY, font=self._font,
            )
            return
        self.configure(bg=self._bg_parent)
        if not self._enabled:
            bg = COLOR_DISABLED
            fg = COLOR_TEXT_DISABLED
            outline = COLOR_DISABLED
        elif self._variant == "primary":
            bg = "#262626" if self._hover else COLOR_ACCENT
            fg = "#FFFFFF"
            outline = bg
        elif self._variant == "accent":
            bg = (
                COLOR_GENERATION_ACCENT_HOVER
                if self._hover else COLOR_GENERATION_ACCENT
            )
            fg = "#FFFFFF"
            outline = bg
        else:
            bg = COLOR_HOVER if self._hover else COLOR_CARD
            fg = COLOR_TEXT_PRIMARY
            outline = COLOR_BORDER

        _round_rectangle(
            self, 1, 1, self._width - 2, self._height - 2, r=10,
            fill=bg, outline=outline, width=1,
        )
        self.create_text(
            self._width // 2, self._height // 2,
            text=self._text, fill=fg, font=self._font,
        )

    def _draw_settings_save_button(self):
        self.configure(bg=self._bg_parent)
        radius = min(12, max(8, (self._height - 6) // 2))
        if not self._enabled:
            _round_rectangle(
                self, 2, 2, self._width - 2, self._height - 3, r=radius,
                fill=COLOR_DISABLED, outline=COLOR_DISABLED, width=1,
            )
            fg = COLOR_TEXT_DISABLED
        else:
            fill_color = (
                COLOR_GENERATION_ACCENT_HOVER
                if self._hover else COLOR_GENERATION_ACCENT
            )
            _round_rectangle(
                self, 2, 2, self._width - 2, self._height - 3, r=radius,
                fill=fill_color, outline=fill_color, width=1,
            )
            if self._focused:
                _round_rectangle(
                    self, 4, 4, self._width - 4, self._height - 5, r=max(6, radius - 2),
                    fill="", outline="#FFFFFF", width=1.5,
                )
            fg = "#FFFFFF"

        center_y = (self._height - 1) / 2
        if self._icon_font:
            icon_w = self._icon_font.measure(self._icon_text)
            text_w = self._font.measure(self._text)
            gap = 8
            start_x = (self._width - (icon_w + gap + text_w)) / 2
            self.create_text(
                start_x, center_y, text=self._icon_text,
                fill=fg, font=self._icon_font, anchor="w",
            )
            self.create_text(
                start_x + icon_w + gap, center_y, text=self._text,
                fill=fg, font=self._font, anchor="w",
            )
        else:
            self.create_text(
                self._width / 2, center_y, text=self._text,
                fill=fg, font=self._font,
            )


# ==================== 设置页分段切换栏 ====================

class SettingsSegmentedTabs(tk.Canvas):
    """设置页顶部的胶囊分段切换器（统一 Argon 靛紫视觉语言）。"""

    def __init__(
        self,
        master,
        command: callable,
        bg_parent: str = COLOR_CARD,
        **kwargs,
    ):
        self._items = (
            ("api", "API KEY 设置"),
            ("data", "数据保存位置"),
        )
        self._command = command
        self._bg_parent = bg_parent
        self._selected = "api"
        self._hover_key = None
        self._focused = False
        self._suppress_focus_ring = False
        self._font = tkfont.Font(master=master, font=FONT_BODY_BOLD)
        self._height = 46
        self._width = 500
        super().__init__(
            master, width=self._width, height=self._height,
            bg=bg_parent, highlightthickness=0, bd=0,
            takefocus=True, cursor="hand2", **kwargs,
        )
        self.bind("<Configure>", self._on_configure)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Left>", lambda _event: self._move_selection(-1))
        self.bind("<Right>", lambda _event: self._move_selection(1))
        self.bind("<Return>", self._activate_focused)
        self.bind("<space>", self._activate_focused)
        self.redraw()

    @property
    def selected_key(self) -> str:
        return self._selected

    def set_responsive_scale(self, scale: float):
        self._font.configure(size=_scaled_font_size(self._font, scale, 9, 12))
        self._height = max(42, round(46 * scale))
        self.configure(height=self._height)
        self.redraw()

    def select(self, key: str, invoke: bool = False):
        if key not in dict(self._items):
            return
        self._selected = key
        self.redraw()
        if invoke and self._command:
            self._command(key)

    def _widths(self) -> list[int]:
        return [
            max(122, self._font.measure(label) + 34)
            for _key, label in self._items
        ]

    def _hit_test(self, x: int) -> str | None:
        widths = self._widths()
        if x < widths[0] + 5:
            return "api"
        if x < sum(widths) + 12:
            return "data"
        return None

    def _on_configure(self, event):
        if event.width > 1 and event.width != self._width:
            self._width = event.width
            self.redraw()

    def _on_motion(self, event):
        key = self._hit_test(event.x)
        if key != self._hover_key:
            self._hover_key = key
            self.configure(cursor="hand2" if key else "arrow")
            self.redraw()

    def _on_leave(self, _event=None):
        if self._hover_key is not None:
            self._hover_key = None
            self.redraw()

    def _on_click(self, event):
        key = self._hit_test(event.x)
        if key:
            self._suppress_focus_ring = True
            self.focus_set()
            self._focused = False
            self.select(key, invoke=True)

    def _on_focus_in(self, _event=None):
        self._focused = not self._suppress_focus_ring
        self.redraw()

    def _on_focus_out(self, _event=None):
        self._focused = False
        self._suppress_focus_ring = False
        self.redraw()

    def _move_selection(self, step: int):
        keys = [key for key, _label in self._items]
        idx = (keys.index(self._selected) + step) % len(keys)
        self._suppress_focus_ring = False
        self._focused = True
        self.select(keys[idx], invoke=True)
        return "break"

    def _activate_focused(self, _event=None):
        self._suppress_focus_ring = False
        self._focused = True
        if self._command:
            self._command(self._selected)
        return "break"

    def redraw(self):
        self.delete("all")
        seg_widths = self._widths()
        width = max(self._width, sum(seg_widths) + 18)
        height = self._height
        _round_rectangle(
            self, 1, 1, width - 1, height - 1, r=12,
            fill="#F1F5F9", outline="#E2E8F0", width=1,
        )
        if self._focused:
            _round_rectangle(
                self, 2, 2, width - 2, height - 2, r=11,
                fill="", outline=COLOR_GENERATION_ACCENT, width=1.5,
            )

        cursor_x = 5
        for (key, label), seg_w in zip(self._items, seg_widths):
            x1, y1 = cursor_x, 5
            x2, y2 = cursor_x + seg_w, height - 5
            if key == self._selected:
                _round_rectangle(
                    self, x1, y1, x2, y2, r=9,
                    fill=COLOR_GENERATION_ACCENT,
                    outline=COLOR_GENERATION_ACCENT, width=1,
                )
                fg = "#FFFFFF"
            elif key == self._hover_key:
                _round_rectangle(
                    self, x1, y1, x2, y2, r=9,
                    fill="#E2E8F0", outline="", width=0,
                )
                fg = COLOR_TEXT_PRIMARY
            else:
                fg = COLOR_TEXT_SECONDARY

            self.create_text(
                (x1 + x2) / 2, (y1 + y2) / 2,
                text=label, fill=fg, font=self._font,
            )
            cursor_x = x2 + 6


# ==================== 扁平选择卡片 ====================

class FlatSelectCard(tk.Canvas):
    """可勾选/单选的扁平卡片（保留对外兼容契约）。"""

    def __init__(
        self,
        master,
        title: str,
        subtitle: str,
        badge_text: str = "",
        initial_checked: bool = False,
        on_toggle: callable = None,
        width: int = 200,
        height: int = 86,
        accent_color: str = COLOR_ACCENT,
        selected_bg: str = "#FAFAFA",
        hover_border: str = "#A3A3A3",
        badge_bg: str = COLOR_ACCENT_BG,
        badge_fg: str = COLOR_ACCENT_BLUE,
        **kwargs,
    ):
        super().__init__(
            master, width=width, height=height,
            highlightthickness=0, bg=COLOR_CARD,
            cursor="hand2", **kwargs,
        )
        self._title = title
        self._subtitle = subtitle
        self._badge = badge_text
        self.checked = initial_checked
        self._on_toggle = on_toggle
        self._width = width
        self._height = height
        self._hover = False
        self._disabled = False
        self._accent_color = accent_color
        self._selected_bg = selected_bg
        self._hover_border = hover_border
        self._badge_bg = badge_bg
        self._badge_fg = badge_fg
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Configure>", self._on_resize)
        self.redraw()

    def _on_resize(self, event):
        if event.width > 1 and event.width != self._width:
            self._width = event.width
            self.redraw()

    def set_disabled(self, disabled: bool):
        self._disabled = bool(disabled)
        self.config(cursor="arrow" if self._disabled else "hand2")
        self.redraw()

    def set_checked(self, val: bool):
        self.checked = bool(val)
        self.redraw()

    def _on_enter(self, _e=None):
        if not self._disabled:
            self._hover = True
            self.redraw()

    def _on_leave(self, _e=None):
        self._hover = False
        self.redraw()

    def _on_click(self, _e=None):
        if self._disabled:
            return
        self.checked = not self.checked
        self.redraw()
        if self._on_toggle:
            self._on_toggle(self)

    def redraw(self):
        self.delete("all")
        w, h = self._width, self._height

        if self._disabled:
            bg = "#FAFAFA"
            border = COLOR_BORDER
            bw = 1
        elif self.checked:
            bg = self._selected_bg
            border = self._accent_color
            bw = 2
        elif self._hover:
            bg = COLOR_CARD
            border = self._hover_border
            bw = 1
        else:
            bg = COLOR_CARD
            border = COLOR_BORDER
            bw = 1

        _round_rectangle(
            self, 2, 2, w - 2, h - 2, r=8,
            fill=bg, outline=border, width=bw,
        )

        box_x, box_y = 16, 20
        if self.checked and not self._disabled:
            _round_rectangle(
                self, box_x, box_y, box_x + 16, box_y + 16, r=4,
                fill=self._accent_color, outline=self._accent_color,
            )
            self.create_line(
                box_x + 3, box_y + 8, box_x + 7, box_y + 12,
                fill="#FFFFFF", width=2,
            )
            self.create_line(
                box_x + 7, box_y + 12, box_x + 13, box_y + 4,
                fill="#FFFFFF", width=2,
            )
        else:
            _round_rectangle(
                self, box_x, box_y, box_x + 16, box_y + 16, r=4,
                fill=COLOR_CARD, outline=COLOR_BORDER, width=1,
            )

        title_color = (
            COLOR_TEXT_DISABLED if self._disabled else COLOR_TEXT_PRIMARY
        )
        sub_color = (
            COLOR_TEXT_DISABLED if self._disabled else COLOR_TEXT_SECONDARY
        )
        self.create_text(
            42, 20, text=self._title, fill=title_color,
            font=FONT_BODY_BOLD, anchor="nw",
        )
        self.create_text(
            42, 44, text=self._subtitle, fill=sub_color,
            font=FONT_SMALL, anchor="nw", width=w - 56,
        )

        if self._badge:
            badge_w = len(self._badge) * 10 + 14
            bx1 = w - badge_w - 12
            by1 = 16
            _round_rectangle(
                self, bx1, by1, bx1 + badge_w, by1 + 20, r=4,
                fill=self._badge_bg, outline="",
            )
            self.create_text(
                bx1 + badge_w // 2, by1 + 10,
                text=self._badge, fill=self._badge_fg,
                font=FONT_TINY,
            )


class SummaryTopicCard(tk.Canvas):
    """重点主题选择弹窗中的自适应高度主题卡片。"""

    def __init__(
        self,
        master,
        index: int,
        title: str,
        summary: str,
        on_toggle: callable = None,
        width: int = 580,
        **kwargs,
    ):
        super().__init__(
            master,
            width=width,
            height=96,
            highlightthickness=0,
            bg=COLOR_TOPIC_DIALOG_BG,
            cursor="hand2",
            takefocus=True,
            **kwargs,
        )
        self._index = index
        self._title = title
        self._summary = summary
        self._on_toggle = on_toggle
        self._width = width
        self._height = 96
        self._checked = False
        self._hover = False
        self._focused = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._toggle)
        self.bind("<FocusIn>", self._on_focus)
        self.bind("<FocusOut>", self._on_blur)
        self.bind("<Return>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<Configure>", self._on_resize)
        self.redraw()

    @property
    def checked(self) -> bool:
        return self._checked

    def set_checked(self, checked: bool, notify: bool = False):
        changed = self._checked != bool(checked)
        self._checked = bool(checked)
        self.redraw()
        if changed and notify and self._on_toggle:
            self._on_toggle(self)

    def _on_enter(self, _event=None):
        self._hover = True
        self.redraw()

    def _on_leave(self, _event=None):
        self._hover = False
        self.redraw()

    def _on_focus(self, _event=None):
        self._focused = True
        self.redraw()

    def _on_blur(self, _event=None):
        self._focused = False
        self.redraw()

    def _on_resize(self, event):
        if event.width > 1 and event.width != self._width:
            self._width = event.width
            self.redraw()

    def _toggle(self, _event=None):
        self.focus_set()
        self.set_checked(not self._checked, notify=True)
        return "break"

    def redraw(self):
        self.delete("all")
        width = self._width
        if self._checked:
            background = COLOR_TOPIC_CARD_SELECTED
            outline = "#CEC6F7"
        elif self._hover:
            background = COLOR_TOPIC_CARD_HOVER
            outline = "#CDD3DE"
        else:
            background = COLOR_CARD
            outline = COLOR_BORDER

        _round_rectangle(
            self, 2, 2, width - 4, self._height - 4, r=10,
            fill=background, outline=outline,
            width=1,
        )
        if self._checked:
            _round_rectangle(
                self, 2, 12, 6, self._height - 14, r=2,
                fill=COLOR_GENERATION_ACCENT, outline="",
            )
        if self._focused and not self._checked:
            _round_rectangle(
                self, 5, 5, width - 7, self._height - 8, r=9,
                fill="", outline="#8C78E8", width=2,
            )

        self.create_text(
            24, 23, text=f"{self._index:02d}",
            fill=(COLOR_GENERATION_ACCENT if self._checked else COLOR_TEXT_MUTED),
            font=FONT_SMALL_BOLD, anchor="nw",
        )

        check_x = width - 31
        check_y = 30
        indicator_fill = (
            COLOR_GENERATION_ACCENT if self._checked else COLOR_TOPIC_CONTROL
        )
        indicator_outline = (
            COLOR_GENERATION_ACCENT if self._checked else "#C9CFD9"
        )
        _round_rectangle(
            self, check_x - 10, check_y - 10, check_x + 10, check_y + 10,
            r=5,
            fill=indicator_fill, outline=indicator_outline, width=1,
            tags=("selection_indicator",),
        )
        if self._checked:
            self.create_line(
                check_x - 5, check_y, check_x - 1, check_y + 4,
                fill="#FFFFFF", width=2, capstyle=tk.ROUND,
                tags=("selection_indicator",),
            )
            self.create_line(
                check_x - 1, check_y + 4, check_x + 6, check_y - 5,
                fill="#FFFFFF", width=2, capstyle=tk.ROUND,
                tags=("selection_indicator",),
            )

        text_width = width - 112
        title_id = self.create_text(
            58, 18, text=self._title, fill=COLOR_TEXT_PRIMARY,
            font=FONT_BODY_BOLD, anchor="nw", width=text_width,
        )
        title_bbox = self.bbox(title_id)
        summary_y = (title_bbox[3] if title_bbox else 34) + 7
        summary_id = self.create_text(
            58, summary_y, text=self._summary, fill=COLOR_TEXT_MUTED,
            font=FONT_BODY, anchor="nw", width=text_width,
        )
        summary_bbox = self.bbox(summary_id)
        desired_height = max(96, (summary_bbox[3] if summary_bbox else 72) + 20)
        if desired_height != self._height:
            self._height = desired_height
            self.configure(height=desired_height)
            self.redraw()


# ==================== 极简扁平进度条 ====================

class FlatProgressBar(tk.Canvas):
    """扁平进度条：柔和紫底轨道 + 主题填充，带 60fps 缓动过渡与销毁清理。"""

    def __init__(
        self,
        master,
        height: int = 6,
        bg_parent: str = COLOR_BG_APP,
        fill_color: str = COLOR_TEXT_PRIMARY,
        **kwargs,
    ):
        super().__init__(
            master, height=height, highlightthickness=0,
            bg=bg_parent, **kwargs,
        )
        self._height = height
        self._fill_color = fill_color
        self._value = 0.0
        self._target = 0.0
        self._anim_id = None
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _on_destroy(self, _event=None):
        if self._anim_id is not None:
            try:
                self.after_cancel(self._anim_id)
            except tk.TclError:
                pass
            self._anim_id = None

    def set_progress(self, val: float):
        self._target = max(0.0, min(1.0, float(val)))
        if self._anim_id is None and self.winfo_exists():
            self._animate_step()

    def reset(self):
        self._target = 0.0
        self._value = 0.0
        if self._anim_id:
            try:
                self.after_cancel(self._anim_id)
            except tk.TclError:
                pass
            self._anim_id = None
        self.redraw()

    def _animate_step(self):
        if not self.winfo_exists():
            self._anim_id = None
            return
        diff = self._target - self._value
        if abs(diff) < 0.002:
            self._value = self._target
            self._anim_id = None
        else:
            self._value += diff * 0.3
            self._anim_id = self.after(16, self._animate_step)
        self.redraw()

    def redraw(self):
        self.delete("all")
        w = max(self.winfo_width(), 1)
        h = self._height
        _round_rectangle(
            self, 0, 0, w, h, r=h / 2,
            fill="#E4DDFB", outline="",
        )
        if self._value > 0:
            fw = max(h, int(w * self._value))
            _round_rectangle(
                self, 0, 0, fw, h, r=h / 2,
                fill=self._fill_color, outline="",
            )


class GenerationChoiceCard(tk.Canvas):
    """生成页响应式模式卡片（内联推荐徽章，选中态柔光高亮）。"""

    def __init__(
        self, master, title: str, subtitle: str,
        badge_text: str = "", initial_checked: bool = False,
        on_toggle: callable = None, width: int = 200,
        height: int = 58, show_separator: bool = True, **kwargs,
    ):
        super().__init__(
            master, width=width, height=height, bg=COLOR_CARD,
            highlightthickness=0, cursor="hand2", **kwargs,
        )
        self._title = title
        self._subtitle = subtitle
        self._badge = badge_text
        self._show_separator = show_separator
        self._checked = bool(initial_checked)
        self.checked = self._checked
        self._disabled = False
        self._hover = False
        self._on_toggle = on_toggle
        self._base_width = width
        self._base_height = height
        self._title_font = tkfont.Font(master=self, font=FONT_H2)
        self._subtitle_font = tkfont.Font(master=self, font=FONT_BODY)
        self._badge_font = tkfont.Font(
            root=self, family=FONT_FAMILY, size=8, weight="bold",
        )
        self._row_height = height
        self._height = height
        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def set_responsive_scale(self, scale: float):
        self._title_font.configure(
            size=_scaled_font_size(self._title_font, scale, 13, 17),
        )
        self._subtitle_font.configure(
            size=_scaled_font_size(self._subtitle_font, scale, 9, 12),
        )
        self._badge_font.configure(
            size=_scaled_font_size(self._badge_font, scale, 8, 9),
        )
        self._row_height = max(54, min(70, round(self._base_height * scale)))
        self._height = self._row_height
        self.configure(height=self._height)
        self.redraw()

    @staticmethod
    def _ellipsize(text: str, font: tkfont.Font, max_width: int) -> str:
        if max_width <= 0:
            return ""
        if font.measure(text) <= max_width:
            return text
        ellipsis = "…"
        available = max_width - font.measure(ellipsis)
        if available <= 0:
            return ellipsis
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if font.measure(text[:middle]) <= available:
                low = middle
            else:
                high = middle - 1
        return text[:low].rstrip() + ellipsis

    def set_disabled(self, disabled: bool):
        self._disabled = bool(disabled)
        self.configure(cursor="arrow" if disabled else "hand2")
        self.redraw()

    def set_checked(self, value: bool):
        self._checked = bool(value)
        self.checked = self._checked
        self.redraw()

    def _on_enter(self, _event=None):
        self._hover = True
        self.redraw()

    def _on_leave(self, _event=None):
        self._hover = False
        self.redraw()

    def _on_click(self, _event=None):
        if self._disabled:
            return
        self.set_checked(not self._checked)
        if self._on_toggle:
            self._on_toggle(self)

    def redraw(self):
        self.delete("all")
        width = self.winfo_width()
        if width <= 1:
            return
        height = self._height
        if self._disabled:
            background = "#F8FAFC"
            title_color = COLOR_TEXT_DISABLED
        elif self._checked:
            background = "#FAF8FF" if not self._hover else "#F5F2FF"
            title_color = COLOR_TEXT_PRIMARY
        elif self._hover:
            background = "#F8FAFC"
            title_color = COLOR_TEXT_PRIMARY
        else:
            background = COLOR_CARD
            title_color = COLOR_TEXT_PRIMARY

        self.create_rectangle(0, 0, width, height, fill=background, outline="")
        content_y = height / 2
        title_x = 8
        self.create_text(
            title_x, content_y, text=self._title, fill=title_color,
            font=self._title_font, anchor="w",
        )
        cursor_x = title_x + self._title_font.measure(self._title) + 12

        if self._badge:
            badge_width = self._badge_font.measure(self._badge) + 14
            badge_width += badge_width % 2
            badge_top = content_y - 10
            badge_bottom = content_y + 10
            _round_rectangle(
                self, cursor_x, badge_top, cursor_x + badge_width, badge_bottom, r=6,
                fill=("#CBD5E1" if self._disabled else COLOR_GENERATION_ACCENT),
                outline="",
            )
            self.create_text(
                cursor_x + badge_width / 2, content_y,
                text=self._badge,
                fill="#FFFFFF", font=self._badge_font, anchor="center",
            )
            cursor_x += badge_width + 12
        else:
            cursor_x += 6

        indicator_size = 20
        indicator_x = width - indicator_size - 8
        indicator_y = (height - indicator_size) / 2
        subtitle_item = self.create_text(
            cursor_x, content_y, text=self._subtitle,
            fill=(COLOR_TEXT_DISABLED if self._disabled else COLOR_TEXT_MUTED),
            font=self._subtitle_font, anchor="w",
            width=max(1, int(indicator_x - cursor_x - 16)), justify=tk.LEFT,
        )
        bounds = self.bbox(subtitle_item)
        required_height = max(
            self._row_height, self._title_font.metrics("linespace") + 16,
            bounds[3] - bounds[1] + 16,
        )
        if height != required_height:
            self._height = required_height
            self.configure(height=required_height)
            self.redraw()
            return
        _round_rectangle(
            self, indicator_x, indicator_y,
            indicator_x + indicator_size, indicator_y + indicator_size, r=6,
            fill=(COLOR_GENERATION_ACCENT if self._checked else COLOR_CARD),
            outline=(COLOR_GENERATION_ACCENT if self._checked else "#CBD5E1"),
        )
        if self._checked:
            self.create_line(
                indicator_x + 5, indicator_y + 10,
                indicator_x + 8.5, indicator_y + 13.5,
                indicator_x + 15, indicator_y + 6.5,
                fill="#FFFFFF", width=2,
                capstyle=tk.ROUND, joinstyle=tk.ROUND,
            )
        if self._show_separator:
            self.create_line(
                8, height - 1, width - 8, height - 1,
                fill=COLOR_BORDER_SUBTLE, width=1,
            )


class GenerationSegmentOption(tk.Canvas):
    """生成页分段单选按钮。"""

    def __init__(
        self, master, text: str, initial_checked: bool = False,
        on_toggle: callable = None, width: int = 142, height: int = 38,
        regular_font=FONT_SMALL, bold_font=FONT_SMALL_BOLD,
        min_font_size: int = 8, max_font_size: int = 10,
        **kwargs,
    ):
        super().__init__(
            master, width=width, height=height, bg="#F1F5F9",
            highlightthickness=0, cursor="hand2", **kwargs,
        )
        self._text = text
        self._checked = bool(initial_checked)
        self.checked = self._checked
        self._disabled = False
        self._hover = False
        self._on_toggle = on_toggle
        self._base_width = width
        self._regular_font = tkfont.Font(master=self, font=regular_font)
        self._bold_font = tkfont.Font(master=self, font=bold_font)
        self._min_font_size = min_font_size
        self._max_font_size = max_font_size
        self._width = max(width, self._bold_font.measure(text) + 24)
        self._height = height
        self.configure(width=self._width)
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self.bind("<Button-1>", self._on_click)
        self.redraw()

    def set_responsive_scale(self, scale: float):
        for font in (self._regular_font, self._bold_font):
            font.configure(size=_scaled_font_size(
                font, scale, self._min_font_size, self._max_font_size,
            ))
        self._width = max(
            self._base_width, self._bold_font.measure(self._text) + 24,
        )
        self.configure(width=self._width)
        self.redraw()

    def _set_hover(self, value: bool):
        self._hover = value
        self.redraw()

    def set_disabled(self, disabled: bool):
        self._disabled = bool(disabled)
        self.configure(cursor="arrow" if disabled else "hand2")
        self.redraw()

    def set_checked(self, value: bool):
        self._checked = bool(value)
        self.checked = self._checked
        self.redraw()

    def _on_click(self, _event=None):
        if self._disabled or self._checked:
            return
        self.set_checked(True)
        if self._on_toggle:
            self._on_toggle(self)

    def redraw(self):
        self.delete("all")
        if self._disabled:
            background = "#F8FAFC"
            foreground = COLOR_TEXT_DISABLED
            outline = COLOR_BORDER
        elif self._checked:
            background = COLOR_CARD
            foreground = COLOR_GENERATION_ACCENT
            outline = "#DDD6FE"
        elif self._hover:
            background = "#E2E8F0"
            foreground = COLOR_TEXT_PRIMARY
            outline = ""
        else:
            background = "#F1F5F9"
            foreground = COLOR_TEXT_MUTED
            outline = ""
        _round_rectangle(
            self, 1, 1, self._width - 1, self._height - 1, r=9,
            fill=background, outline=outline, width=1,
        )
        self.create_text(
            self._width // 2, self._height // 2,
            text=self._text, fill=foreground,
            font=self._bold_font if self._checked else self._regular_font,
        )


# ==================== 对话输入胶囊 ====================

class GlassCapsulePanel(tk.Canvas):
    """带柔和紫调填充与圆角描边的对话输入控制台。"""

    _PANEL_RADIUS = 28

    def __init__(self, master, bg_parent: str = COLOR_BG_APP, **kwargs):
        super().__init__(master, highlightthickness=0, bg=bg_parent, **kwargs)
        self._bg_parent = bg_parent
        self._dragging = False
        self.content = tk.Frame(self, bg=COLOR_OMNIBOX_SURFACE, padx=22, pady=0)
        self._content_window = self.create_window(
            16, 22, window=self.content, anchor="nw",
        )
        self.content.bind("<Configure>", self._fit_height)
        self.bind("<Configure>", self._on_resize)
        self._fit_height()
        self.redraw()

    def _on_resize(self, event):
        width = max(1, event.width - 32)
        current_width = int(float(self.itemcget(self._content_window, "width")))
        if current_width != width:
            self.itemconfigure(self._content_window, width=width)
        self.redraw()

    def _fit_height(self, _event=None):
        height = self.content.winfo_reqheight() + 36
        if self.winfo_reqheight() != height:
            self.configure(height=height)

    def set_drop_highlight(self, highlighted: bool):
        self._dragging = bool(highlighted)
        self.redraw()

    def redraw(self):
        self.delete("glass")
        w, h = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        fill = "#EDE5FF" if self._dragging else COLOR_OMNIBOX_SURFACE
        outline = (
            COLOR_GENERATION_ACCENT if self._dragging else COLOR_OMNIBOX_BORDER
        )
        _round_rectangle(
            self, 8, 4, w - 8, h - 9, r=self._PANEL_RADIUS,
            fill=fill, outline=outline,
            width=2 if self._dragging else 1, tags="glass",
        )
        self.tag_lower("glass")


# ==================== 极简扁平输入框 ====================

class FlatEntryBox(tk.Canvas):
    """胶囊内的白色圆角输入框，带可见占位提示、焦点柔光圈与右键快捷菜单。"""

    def __init__(
        self,
        master,
        on_change: callable = None,
        bg_parent: str = COLOR_BG_APP,
        placeholder: str = "",
        **kwargs,
    ):
        super().__init__(
            master, height=58, highlightthickness=0,
            bg=bg_parent, **kwargs,
        )
        self._bg_parent = bg_parent
        self._on_change = on_change
        self._locked = False
        self._focused = False
        self._placeholder = placeholder
        self._placeholder_font = tkfont.Font(
            master=self, font=(FONT_FAMILY, 13),
        )

        self._inner = tk.Frame(self, bg="#FFFFFF", padx=8, pady=5)
        self.window_id = self.create_window(14, 8, window=self._inner, anchor="nw")
        self.var = tk.StringVar()
        self.entry = tk.Entry(
            self._inner, textvariable=self.var, font=(FONT_FAMILY, 13),
            bg="#FFFFFF", fg=COLOR_TEXT_PRIMARY,
            insertbackground=COLOR_GENERATION_ACCENT,
            relief=tk.FLAT, bd=0, highlightthickness=0,
        )
        self.entry._responsive_min_font_size = 12
        self.entry._responsive_max_font_size = 15
        self.entry.pack(fill=tk.BOTH, expand=True)

        self._placeholder_label = tk.Label(
            self._inner,
            text=self._placeholder,
            font=self._placeholder_font,
            fg="#94A3B8",
            bg="#FFFFFF",
            anchor="w",
            cursor="xterm",
        )
        self._placeholder_label._responsive_min_font_size = 12
        self._placeholder_label._responsive_max_font_size = 15
        self._placeholder_label.bind(
            "<Button-1>", lambda _e: self.entry.focus_set(),
        )

        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.entry.bind("<KeyRelease>", self._on_keyrelease)
        self.entry.bind("<<Paste>>", lambda _e: self.after(10, self._paste_clipboard))
        self.entry.bind("<Button-3>", self._show_context_menu)
        self._placeholder_label.bind("<Button-3>", self._show_context_menu)
        self.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self.bind("<Configure>", self._on_resize)
        self.var.trace_add("write", self._on_var_change)
        self.redraw()

    def _show_context_menu(self, event):
        if self._locked:
            return
        menu = tk.Menu(self, tearoff=0, font=FONT_SMALL)
        menu.add_command(label="粘贴", command=self._paste_clipboard)
        if self.var.get():
            menu.add_command(
                label="复制",
                command=lambda: (
                    self.winfo_toplevel().clipboard_clear(),
                    self.winfo_toplevel().clipboard_append(self.var.get()),
                ),
            )
            menu.add_separator()
            menu.add_command(label="清空输入", command=lambda: self.set_text(""))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def set_responsive_scale(self, scale: float):
        self._placeholder_font.configure(
            size=_scaled_font_size(self._placeholder_font, scale, 12, 15),
        )
        self.redraw()

    def _on_resize(self, event):
        self.configure(width=event.width)
        self.coords(self.window_id, 14, 8)
        self.itemconfig(
            self.window_id,
            width=max(1, event.width - 28),
            height=42,
        )
        self.redraw()

    def _on_focus_in(self, _event):
        self._focused = True
        self.redraw()

    def _on_focus_out(self, _event):
        self._focused = False
        self.redraw()

    def _on_keyrelease(self, _event):
        self.redraw()

    def _on_var_change(self, *_args):
        self.redraw()
        if self._on_change:
            self._on_change()

    def _paste_clipboard(self):
        try:
            text = self.winfo_toplevel().clipboard_get()
            self.var.set(text.strip())
        except tk.TclError:
            pass

    def get_text(self) -> str:
        return self.var.get().strip()

    def set_text(self, text: str):
        self.var.set(text)
        self.redraw()

    def set_locked(self, locked: bool):
        self._locked = bool(locked)
        self.entry.config(state="disabled" if self._locked else "normal")
        self.redraw()

    def redraw(self):
        self.delete("frame")
        w = max(self.winfo_width(), 1)
        if self._focused:
            _round_rectangle(
                self, 0, 0, w, 58, r=16, fill="#E0E7FF", outline="",
                tags="frame",
            )
        outline = COLOR_GENERATION_ACCENT if self._focused else "#D8D0F5"
        outline_w = 1.5 if self._focused else 1
        _round_rectangle(
            self, 2, 2, w - 2, 56, r=14,
            fill="#FFFFFF", outline=outline, width=outline_w, tags="frame",
        )
        self.tag_lower("frame")
        self.delete("placeholder")
        show_placeholder = (
            bool(self._placeholder)
            and not self._focused
            and not self._locked
            and not self.var.get()
        )
        if show_placeholder:
            self._placeholder_label.place(x=2, rely=0.5, anchor="w")
        else:
            self._placeholder_label.place_forget()


# ==================== 侧栏毛玻璃导航项 ====================

class GlassNavigationItem(tk.Canvas):
    """Argon 侧栏激活卡片：柔和薰衣草渐变 + 居中标题。"""

    _CARD_MARGIN = 3
    _CARD_RADIUS = 14

    def __init__(self, master, icon: str, title: str, **kwargs):
        super().__init__(
            master, height=68, highlightthickness=0, bd=0,
            bg=COLOR_SIDEBAR, cursor="hand2", **kwargs,
        )
        self._icon = icon
        self._title = title
        icon_asset = {
            "首页": "chat-outline",
            "生成": "document-outline",
            "历史": "history-clock",
        }.get(title)
        self._navigation_icon_image = (
            tk.PhotoImage(file=str(_navigation_icon_path(icon_asset)))
            if icon_asset
            else None
        )
        self._active = False
        self._progress = 0.0
        self._target_progress = 0.0
        self._animation_id = None
        self._hovered = False
        self._title_font = tkfont.Font(master=self, font=FONT_SIDEBAR_ITEM)
        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.redraw()

    def _on_destroy(self, _event=None):
        if self._animation_id is not None:
            try:
                self.after_cancel(self._animation_id)
            except tk.TclError:
                pass
            self._animation_id = None

    def set_responsive_scale(self, scale: float):
        self._title_font.configure(
            size=_scaled_font_size(self._title_font, scale, 12, 15),
        )
        self.redraw()

    def set_active(self, active: bool):
        active = bool(active)
        target = 1.0 if active else 0.0
        if self._active == active and self._target_progress == target:
            return
        self._active = active
        self._target_progress = target
        if self._animation_id is None and self.winfo_exists():
            self._animate()

    def _on_enter(self, _event):
        self._hovered = True
        self.redraw()

    def _on_leave(self, _event):
        self._hovered = False
        self.redraw()

    def _animate(self):
        if not self.winfo_exists():
            self._animation_id = None
            return
        delta = self._target_progress - self._progress
        if abs(delta) < 0.02:
            self._progress = self._target_progress
            self._animation_id = None
        else:
            self._progress += delta * 0.25
            self._animation_id = self.after(16, self._animate)
        self.redraw()

    @staticmethod
    def _mix(start: tuple[int, int, int], end: tuple[int, int, int], amount: float):
        return tuple(round(a + (b - a) * amount) for a, b in zip(start, end))

    def _draw_settings_gear(self, color: str):
        center_x, center_y = 27, 34
        points = []
        tooth_step = math.tau / 8
        for tooth in range(8):
            center = -math.pi / 2 + tooth * tooth_step
            for offset, radius in (
                (-tooth_step / 2, 7.5), (-tooth_step * 0.28, 7.5),
                (-tooth_step * 0.28, 10.2), (tooth_step * 0.28, 10.2),
                (tooth_step * 0.28, 7.5), (tooth_step / 2, 7.5),
            ):
                angle = center + offset
                points.extend((
                    center_x + radius * math.cos(angle),
                    center_y + radius * math.sin(angle),
                ))
        points.extend(points[:2])
        self.create_line(
            *points, fill=color, width=1.7, joinstyle=tk.ROUND,
            capstyle=tk.ROUND, tags="content",
        )
        self.create_oval(
            center_x - 3.6, center_y - 3.6, center_x + 3.6, center_y + 3.6,
            outline=color, width=1.7, tags="content",
        )

    def redraw(self):
        self.delete("all")
        width, height = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        progress = self._progress
        left, top = self._CARD_MARGIN, self._CARD_MARGIN
        right, bottom = width - self._CARD_MARGIN, height - self._CARD_MARGIN

        if progress > 0.01:
            radius = min(self._CARD_RADIUS, (right - left) / 2, (bottom - top) / 2)
            for y in range(int(top), int(bottom)):
                edge_distance = min(y + 0.5 - top, bottom - y - 0.5)
                inset = (radius - math.sqrt(radius ** 2 - (radius - edge_distance) ** 2)
                         if edge_distance < radius else 0)
                color = self._mix(
                    (233, 225, 255), (196, 177, 252),
                    (y - top) / max(1, bottom - top - 1),
                )
                fill_rgb = self._mix((255, 255, 255), color, progress)
                self.create_line(
                    left + inset, y + 0.5, right - inset, y + 0.5,
                    fill="#%02X%02X%02X" % fill_rgb, width=1,
                    tags=("card", "active_gradient"),
                )
        elif self._hovered:
            _round_rectangle(
                self, left, top, right, bottom, r=self._CARD_RADIUS,
                fill="#F8FAFC", outline="", tags="card",
            )

        icon_color = (
            "#1E293B" if self._active or self._hovered else "#5F6672"
        )
        if self._navigation_icon_image is not None:
            self.create_image(
                27, 34, image=self._navigation_icon_image,
                anchor=tk.CENTER, tags="content",
            )
        elif self._title == "设置":
            self._draw_settings_gear(icon_color)
        else:
            self.create_text(
                27, 34, text=self._icon, font=(FONT_FAMILY, 14),
                fill=icon_color, anchor="center", tags="content",
            )

        title_color = "#0F172A"
        self.create_text(
            width / 2, height / 2, text=self._title, font=self._title_font,
            fill=title_color, anchor="center", tags=("content", "title"),
        )


# ==================== 悬停提示 ====================

class HoverTooltip:
    """350ms 悬停后弹出无边框深色提示，组件销毁时自动清理定时器。"""

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 350):
        self._widget = widget
        self._text = text
        self._delay = delay_ms
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._hide()
        if self._text and self._widget.winfo_exists():
            self._after_id = self._widget.after(self._delay, self._show)

    def _show(self):
        self._after_id = None
        if self._tip or not self._text or not self._widget.winfo_exists():
            return
        screen_width = self._widget.winfo_screenwidth()
        screen_height = self._widget.winfo_screenheight()
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        tk.Label(
            self._tip, text=self._text, bg="#0F172A", fg="#F8FAFC",
            font=FONT_TINY, padx=10, pady=5,
            wraplength=max(240, screen_width - 32), justify=tk.LEFT,
        ).pack()
        self._tip.update_idletasks()
        x = min(
            max(8, self._widget.winfo_rootx() + 16),
            screen_width - self._tip.winfo_width() - 8,
        )
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 6
        if y + self._tip.winfo_height() > screen_height:
            y = max(8, self._widget.winfo_rooty() - self._tip.winfo_height() - 6)
        self._tip.geometry(f"+{x}+{y}")

    def _hide(self, _event=None):
        if self._after_id:
            try:
                self._widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if self._tip:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


class HistoryTaskCard(tk.Canvas):
    """Draw the static dashboard in one surface instead of dozens of HWNDs."""

    def __init__(self, master, record, on_open):
        super().__init__(
            master, bg=COLOR_CARD, highlightthickness=1,
            highlightbackground=COLOR_BORDER, borderwidth=0,
        )
        self.record = record
        self._small = tkfont.Font(root=self, font=FONT_TINY)
        self._bold = tkfont.Font(root=self, font=FONT_BODY_BOLD)
        self._header_height = max(
            self._small.metrics("linespace") + 4, self._bold.metrics("linespace"),
        )
        self._cell_height = (
            self._small.metrics("linespace") + self._bold.metrics("linespace") + 18
        )
        self._metrics_top = 18 + self._header_height + 16
        self._files_top = self._metrics_top + 2 * (self._cell_height + 8) + 8
        self._files_window = None
        if record.get("saved_files"):
            row = tk.Frame(self, bg=COLOR_CARD)
            files = record["saved_files"]
            HorizontalFileList(
                row, text="📁 " + "、".join(Path(file).name for file in files),
                tooltip_text="、".join(map(str, files)),
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)
            if record.get("output_dir"):
                button = tk.Button(
                    row, text="📂 打开文件夹",
                    command=lambda: on_open(record["output_dir"]),
                    font=FONT_TINY, bg="#F8FAFC", fg=COLOR_TEXT_SECONDARY,
                    activebackground="#EEF2FF", activeforeground=COLOR_ACCENT,
                    relief=tk.FLAT, bd=0, cursor="hand2",
                    highlightthickness=1, highlightbackground=COLOR_BORDER,
                    padx=12, pady=5,
                )
                button.pack(side=tk.RIGHT, padx=(10, 0))
                HoverTooltip(button, str(record["output_dir"]))
            self._files_window = self.create_window(
                22, self._files_top, anchor="nw", window=row,
                height=max(36, self._small.metrics("linespace") + 14),
            )
        bottom = (
            self._files_top + max(36, self._small.metrics("linespace") + 14)
            if self._files_window else self._files_top - 8
        )
        self.configure(height=bottom + 18)
        self._last_width = None
        self.bind("<Configure>", self._on_resize)
        HoverTooltip(self, str(record.get("title", "未命名任务")))

    def _on_resize(self, event):
        if event.width == self._last_width:
            return
        self._last_width = event.width
        self.delete("dashboard")
        width = event.width
        succeeded = bool(self.record.get("succeeded"))
        status = "✓ 成功" if succeeded else "✗ 失败"
        status_width = self._small.measure(status) + 16
        header_y = 18 + self._header_height / 2
        self.create_rectangle(
            22, 18, 22 + status_width, 18 + self._header_height,
            fill="#ECFDF5" if succeeded else "#FEF2F2", outline="",
            tags="dashboard",
        )
        self.create_text(
            30, header_y, text=status, font=self._small, anchor="w",
            fill="#059669" if succeeded else "#DC2626", tags="dashboard",
        )
        timestamp = str(self.record.get("timestamp", ""))
        self.create_text(
            width - 22, header_y, text=timestamp, font=self._small,
            anchor="e", fill=COLOR_TEXT_MUTED, tags="dashboard",
        )
        title_x = 32 + status_width
        title = GenerationChoiceCard._ellipsize(
            str(self.record.get("title", "未命名任务")), self._bold,
            width - 34 - self._small.measure(timestamp) - title_x,
        )
        self.create_text(
            title_x, header_y, text=title, font=self._bold, anchor="w",
            fill=COLOR_TEXT_PRIMARY, tags="dashboard",
        )
        fields = (
            ("程序处理", "program_seconds"), ("抓取/读取", "fetch_seconds"),
            ("总结", "generation_seconds"), ("人工等待", "wait_seconds"),
            ("总计", "total_seconds"), ("文件数", "file_count"),
        )
        cell_width = max(1, (width - 44) / 3)
        for index, (label, key) in enumerate(fields):
            row, col = divmod(index, 3)
            x = 26 + col * cell_width
            y = self._metrics_top + row * (self._cell_height + 8)
            self.create_rectangle(
                x, y, x + cell_width - 8, y + self._cell_height,
                fill="#F8FAFC", outline="#EEF2F6", tags="dashboard",
            )
            self.create_text(
                x + 10, y + 7, text=label, font=self._small, anchor="nw",
                fill=COLOR_TEXT_MUTED, tags="dashboard",
            )
            value = self.record.get(key, 0)
            self.create_text(
                x + 10, y + 9 + self._small.metrics("linespace"),
                text=f"{value:.1f}s" if isinstance(value, float) else str(value),
                font=self._bold, anchor="nw", fill=COLOR_TEXT_PRIMARY,
                tags="dashboard",
            )
        if self._files_window:
            self.itemconfigure(self._files_window, width=max(1, width - 44))


class HorizontalFileList(tk.Frame):
    """单行文件列表，内容溢出时自动展开水平滚动条并支持 Shift+滚轮。"""

    def __init__(self, master, text: str, tooltip_text: str):
        super().__init__(master, bg=COLOR_CARD)
        self.canvas = tk.Canvas(
            self,
            height=22,
            bg=COLOR_CARD,
            highlightthickness=0,
            borderwidth=0,
            xscrollincrement=16,
        )
        self.scrollbar = tk.Scrollbar(
            self,
            orient=tk.HORIZONTAL,
            command=self.canvas.xview,
            width=8,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            elementborderwidth=0,
            background=COLOR_BORDER,
            activebackground=COLOR_TEXT_MUTED,
            troughcolor=COLOR_CARD,
        )
        self.canvas.configure(xscrollcommand=self.scrollbar.set)
        self.canvas.pack(fill=tk.X, expand=True)
        self._text_id = self.canvas.create_text(
            0, 2,
            text=text,
            font=FONT_TINY,
            fill=COLOR_TEXT_SECONDARY,
            anchor="nw",
        )
        self.canvas.bind("<Configure>", self._sync_scrollbar, add="+")
        self.canvas.bind("<Shift-MouseWheel>", self._on_horizontal_wheel)
        self.canvas.bind("<Shift-Button-4>", self._on_horizontal_wheel)
        self.canvas.bind("<Shift-Button-5>", self._on_horizontal_wheel)
        HoverTooltip(self.canvas, tooltip_text)
        self.after_idle(self._sync_scrollbar)

    def _sync_scrollbar(self, _event=None):
        bounds = self.canvas.bbox(self._text_id)
        if not bounds:
            return
        self.canvas.configure(scrollregion=(0, 0, bounds[2], bounds[3]))
        overflowing = bounds[2] > self.canvas.winfo_width()
        if overflowing and not self.scrollbar.winfo_manager():
            self.scrollbar.pack(fill=tk.X, pady=(2, 0))
        elif not overflowing and self.scrollbar.winfo_manager():
            self.scrollbar.pack_forget()
            self.canvas.xview_moveto(0)

    def _on_horizontal_wheel(self, event):
        delta = getattr(event, "delta", 0)
        if delta:
            direction = -3 if delta > 0 else 3
        else:
            direction = -3 if getattr(event, "num", 0) == 4 else 3
        self.canvas.xview_scroll(direction, "units")
        return "break"
