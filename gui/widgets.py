"""Argon 前端自绘高复用组件库。

封装所有基于 Tkinter Canvas / Frame 的扁平与毛玻璃过渡控件，
内置高 DPI 响应式字号缩放、键盘无障碍焦点环以及销毁时定时器自动清理。
"""

from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont

from gui.theme import (
    COLOR_ACCENT,
    COLOR_ACCENT_BG,
    COLOR_ACCENT_BLUE,
    COLOR_BG_APP,
    COLOR_BORDER,
    COLOR_BORDER_FOCUS,
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


# ==================== 品牌分层图标 ====================

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
    """纤细极简滚动条（自动隐藏、圆润指示条、悬停加深）。"""

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
        if not self.winfo_exists():
            return
        self.delete("thumb")
        h = max(self.winfo_height(), 1)
        span = max(0.0, self._last - self._first)
        if span >= 1.0:
            return
        thumb_h = max(28, int(h * span))
        thumb_y = int(h * self._first)
        color = "#1E293B" if self._hover else "#94A3B8"
        self._thumb_id = _round_rectangle(
            self,
            1, thumb_y, self._width - 1, thumb_y + thumb_h,
            r=max(1, (self._width - 2) // 2),
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
            min(
                1.0 - (self._last - self._first),
                self._drag_start_first + delta,
            ),
        )
        self.target.yview_moveto(new_first)

    def _on_release(self, _event):
        self._drag_start_y = 0


# ==================== 极简扁平按钮 ====================

class FlatButton(tk.Canvas):
    """扁平/渐变按钮：支持主色、强调紫、次级描边、渐变保存及键盘无障碍激活。"""

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
            round(self._base_height * scale),
            self._font.metrics("linespace") + 16,
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

    @staticmethod
    def _mix_color(start: str, end: str, amount: float) -> str:
        return _mix_color(start, end, amount)

    def _draw_settings_gradient(self, width: int, height: int):
        _round_rectangle(
            self, 2, 3, width - 2, height - 2, r=12,
            fill="#DDE3EF", outline="",
        )
        x1, y1, x2, y2 = 2, 1, width - 2, height - 4
        radius = min(12, (y2 - y1) / 2)
        start, end = (
            ("#146FB3", "#5B4BC0") if self._hover
            else ("#0D5B99", "#49379F")
        )
        steps = max(1, width - 4)
        for step in range(steps):
            left = x1 + (x2 - x1) * step / steps
            right = x1 + (x2 - x1) * (step + 1) / steps
            center = (left + right) / 2
            edge_distance = min(center - x1, x2 - center)
            inset = (
                radius - (radius ** 2 - (radius - edge_distance) ** 2) ** 0.5
                if edge_distance < radius else 0
            )
            color = self._mix_color(start, end, step / max(1, steps - 1))
            self.create_rectangle(
                left, y1 + inset, right + 0.5, y2 - inset,
                fill=color, outline=color,
            )
        _round_rectangle(
            self, x1, y1, x2, y2, r=radius,
            fill="", outline="#FFFFFF", width=1,
        )
        if self._focused:
            _round_rectangle(
                self, 0, 0, width, height, r=13,
                fill="", outline="#8AB4F8", width=2,
            )

    def _draw_topic_primary_gradient(self, width: int, height: int):
        x1, y1, x2, y2 = 1, 1, width - 1, height - 1
        radius = min(9, (y2 - y1) / 2)
        start, end = (
            ("#7667E8", "#5F4DD3") if self._hover
            else ("#806FEA", "#6955DA")
        )
        steps = max(1, width - 4)
        for step in range(steps):
            left = x1 + (x2 - x1) * step / steps
            right = x1 + (x2 - x1) * (step + 1) / steps
            center = (left + right) / 2
            edge_distance = min(center - x1, x2 - center)
            inset = (
                radius - (radius ** 2 - (radius - edge_distance) ** 2) ** 0.5
                if edge_distance < radius else 0
            )
            color = self._mix_color(start, end, step / max(1, steps - 1))
            self.create_rectangle(
                left, y1 + inset, right + 0.5, y2 - inset,
                fill=color, outline=color,
            )
        _round_rectangle(
            self, x1, y1, x2, y2, r=radius,
            fill="", outline="#6552D3", width=1,
        )
        if self._focused:
            _round_rectangle(
                self, 2, 2, width - 2, height - 2, r=8,
                fill="", outline="#D9D3FF", width=1,
            )

    def redraw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        w, h = self._width, self._height
        self.configure(
            bg=(
                COLOR_GENERATION_ACCENT
                if self._variant == "topic-primary" and self._enabled
                else self._bg_parent
            )
        )
        if not self._enabled:
            bg, fg = COLOR_DISABLED, COLOR_TEXT_DISABLED
            outline = ""
        elif self._variant == "accent":
            bg = (
                COLOR_GENERATION_ACCENT_HOVER
                if self._hover else COLOR_GENERATION_ACCENT
            )
            fg = "#FFFFFF"
            outline = ""
        elif self._variant == "primary":
            bg = "#0A0A0A" if not self._hover else "#262626"
            fg = "#FFFFFF"
            outline = ""
        elif self._variant == "settings-save":
            bg = COLOR_ACCENT_BLUE
            fg = "#FFFFFF"
            outline = ""
        elif self._variant == "secondary":
            bg = COLOR_HOVER if self._hover else COLOR_CARD
            fg = COLOR_TEXT_PRIMARY
            outline = COLOR_BORDER
        elif self._variant == "topic-secondary":
            bg = "#F1EFFF" if self._hover else "#FFFFFF"
            fg = COLOR_GENERATION_ACCENT if self._hover else COLOR_TEXT_SECONDARY
            outline = "#BDB4F3" if self._hover else "#D9DCE6"
        elif self._variant == "topic-primary":
            bg = COLOR_GENERATION_ACCENT
            fg = "#FFFFFF"
            outline = ""
        elif self._variant == "ghost":
            bg = COLOR_HOVER if self._hover else self._bg_parent
            fg = COLOR_TEXT_SECONDARY
            outline = ""
        else:
            bg = COLOR_HOVER if self._hover else self._bg_parent
            fg = COLOR_TEXT_PRIMARY
            outline = COLOR_BORDER

        if self._variant == "settings-save" and self._enabled:
            self._draw_settings_gradient(w, h)
        elif self._variant == "topic-primary" and self._enabled:
            self._draw_topic_primary_gradient(w, h)
        else:
            _round_rectangle(
                self, 1, 1, w - 1, h - 1,
                r=(
                    12 if self._variant == "settings-save"
                    else 9 if self._variant.startswith("topic-")
                    else 8 if self._variant == "accent"
                    else 6
                ),
                fill=bg, outline=outline, width=1,
            )
            if self._focused:
                _round_rectangle(
                    self, 1, 1, w - 1, h - 1, r=6,
                    fill="", outline="#8C78E8", width=2,
                )

        if self._icon_text and self._icon_font:
            icon_width = self._icon_font.measure(self._icon_text)
            text_width = self._font.measure(self._text)
            start_x = (w - icon_width - 8 - text_width) / 2
            self.create_text(
                start_x + icon_width / 2, h / 2,
                text=self._icon_text, fill=fg, font=self._icon_font,
            )
            self.create_text(
                start_x + icon_width + 8 + text_width / 2, h / 2,
                text=self._text, fill=fg, font=self._font,
            )
        else:
            self.create_text(
                w // 2, h // 2, text=self._text,
                fill=fg, font=self._font,
            )


# ==================== 设置页圆角分段选项卡 ====================

class SettingsSegmentedTabs(tk.Canvas):
    """设置页的胶囊分段选项卡，支持鼠标点击与左右方向键切换。"""

    _OPTIONS = (("api", "API KEY 设置"), ("data", "数据保存位置"))

    def __init__(self, master, command=None, bg_parent=COLOR_CARD):
        super().__init__(
            master, height=42, highlightthickness=0, bg=bg_parent,
            takefocus=True, cursor="hand2",
        )
        self._command = command
        self._bg_parent = bg_parent
        self._selected_key = "api"
        self._base_height = 42
        self._height = self._base_height
        self._scale = 1.0
        self._font = tkfont.Font(master=self, font=FONT_BODY_BOLD)
        self._focused = False
        self._suppress_focus_ring = False
        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<Left>", lambda _event: self._move_selection(-1))
        self.bind("<Right>", lambda _event: self._move_selection(1))
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.redraw()

    @property
    def selected_key(self):
        return self._selected_key

    def set_responsive_scale(self, scale: float):
        self._scale = scale
        self._height = max(36, round(self._base_height * scale))
        self._font.configure(size=_scaled_font_size(self._font, scale, 9, 11))
        self.configure(height=self._height)
        self.redraw()

    def select(self, key: str):
        if key in dict(self._OPTIONS):
            self._selected_key = key
            self.redraw()

    def _widths(self):
        return [
            max(round(124 * self._scale), self._font.measure(label) + 32)
            for _key, label in self._OPTIONS
        ]

    def _activate(self, key: str):
        if key not in dict(self._OPTIONS) or key == self._selected_key:
            return
        self._selected_key = key
        self.redraw()
        if self._command:
            self._command(key)

    def _on_click(self, event):
        self._suppress_focus_ring = True
        self.focus_set()
        self._focused = False
        self.redraw()
        widths = self._widths()
        if event.x < widths[0] + 5:
            self._activate("api")
        elif event.x < sum(widths) + 10:
            self._activate("data")

    def _move_selection(self, direction: int):
        self._suppress_focus_ring = False
        self._focused = True
        keys = [key for key, _label in self._OPTIONS]
        self._activate(
            keys[(keys.index(self._selected_key) + direction) % len(keys)]
        )
        return "break"

    def _on_focus_in(self, _event=None):
        self._focused = not self._suppress_focus_ring
        self.redraw()

    def _on_focus_out(self, _event=None):
        self._focused = False
        self._suppress_focus_ring = False
        self.redraw()

    def redraw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        width = max(self.winfo_width(), 1)
        height = self._height
        _round_rectangle(
            self, 1, 1, width - 1, height - 1, r=height / 2,
            fill="#EDF1F5", outline=COLOR_BORDER, width=1,
        )
        widths = self._widths()
        positions = (4, 4 + widths[0] + 4)
        selected_index = 0 if self._selected_key == "api" else 1
        selected_x = positions[selected_index]
        _round_rectangle(
            self, selected_x, 3, selected_x + widths[selected_index],
            height - 3, r=(height - 6) / 2,
            fill="#0D5B99", outline="",
        )
        for index, (key, label) in enumerate(self._OPTIONS):
            self.create_text(
                positions[index] + widths[index] / 2, height / 2,
                text=label,
                fill=(
                    "#FFFFFF" if key == self._selected_key
                    else COLOR_TEXT_SECONDARY
                ),
                font=self._font,
            )
        if self._focused:
            _round_rectangle(
                self, 0, 0, width, height, r=height / 2,
                fill="", outline=COLOR_BORDER_FOCUS, width=1,
            )


# ==================== 极简扁平选择卡片（兼容契约） ====================

class FlatSelectCard(tk.Canvas):
    """扁平选择卡片：支持 set_disabled / set_checked / _on_click 契约。"""

    def __init__(
        self,
        master,
        title: str,
        subtitle: str,
        badge_text: str = "",
        is_radio: bool = False,
        initial_checked: bool = False,
        on_toggle: callable = None,
        theme_color: str = COLOR_ACCENT,
        bg_parent: str = COLOR_BG_APP,
        width: int = 220,
        height: int = 96,
        **kwargs,
    ):
        super().__init__(
            master, width=width, height=height,
            highlightthickness=0, bg=bg_parent, **kwargs,
        )
        self._title = title
        self._subtitle = subtitle
        self._badge = badge_text
        self._is_radio = is_radio
        self._checked = initial_checked
        self._disabled = False
        self._hover = False
        self._on_toggle = on_toggle
        self._theme = theme_color
        self._bg_parent = bg_parent
        self._width = width
        self._height = height
        self.checked = self._checked
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.redraw()

    def set_disabled(self, disabled: bool):
        self._disabled = bool(disabled)
        self.redraw()

    def set_checked(self, val: bool):
        self._checked = bool(val)
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
        if self._is_radio:
            if not self._checked:
                self.set_checked(True)
                if self._on_toggle:
                    self._on_toggle(self)
        else:
            self.set_checked(not self._checked)
            if self._on_toggle:
                self._on_toggle(self)

    def redraw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        w, h = self._width, self._height
        if self._checked and not self._disabled:
            bg = COLOR_ACCENT_BG
            outline = COLOR_TEXT_PRIMARY
            outline_w = 1.5
        elif self._hover and not self._disabled:
            bg = COLOR_HOVER
            outline = COLOR_BORDER
            outline_w = 1
        elif self._disabled:
            bg = "#FAFAFA"
            outline = COLOR_BORDER
            outline_w = 1
        else:
            bg = COLOR_CARD
            outline = COLOR_BORDER
            outline_w = 1
        _round_rectangle(
            self, 1, 1, w - 1, h - 1, r=6,
            fill=bg, outline=outline, width=outline_w,
        )
        indicator_color = (
            COLOR_TEXT_PRIMARY if self._checked else COLOR_BORDER
        )
        indicator_fill = (
            COLOR_TEXT_PRIMARY if self._checked else "#FFFFFF"
        )
        ix, iy, isz = 14, 14, 14
        _round_rectangle(
            self, ix, iy, ix + isz, iy + isz, r=2,
            fill=indicator_fill, outline=indicator_color, width=1,
        )
        if self._checked:
            self.create_line(
                ix + 3, iy + 7, ix + 6, iy + 10, ix + 11, iy + 4,
                fill="#FFFFFF", width=2, smooth=True,
            )
        title_color = (
            COLOR_TEXT_DISABLED if self._disabled else COLOR_TEXT_PRIMARY
        )
        self.create_text(
            ix + isz + 10, iy + 2, text=self._title,
            fill=title_color, font=FONT_BODY_BOLD, anchor="nw",
        )
        sub_color = (
            COLOR_TEXT_DISABLED if self._disabled else COLOR_TEXT_SECONDARY
        )
        self.create_text(
            ix + isz + 10, iy + 22, text=self._subtitle,
            fill=sub_color, font=FONT_TINY, anchor="nw",
            width=w - ix - isz - 24,
        )
        if self._badge and w >= 138 and h >= 48:
            badge_w = 8 + len(self._badge) * 6
            bx = w - 14 - badge_w
            by = 12
            badge_bg = (
                COLOR_ACCENT_BG
                if self._checked and not self._disabled
                else "#F5F5F5"
            )
            _round_rectangle(
                self, bx, by, bx + badge_w, by + 18, r=9,
                fill=badge_bg, outline="",
            )
            self.create_text(
                bx + badge_w // 2, by + 9, text=self._badge,
                fill=(
                    COLOR_ACCENT
                    if self._checked and not self._disabled
                    else COLOR_TEXT_SECONDARY
                ),
                font=FONT_TINY,
            )


# ==================== 重点主题选择卡片 ====================

class SummaryTopicCard(tk.Canvas):
    """用于重点主题弹窗的整卡可点击多选项（支持长文本自适应增高）。"""

    def __init__(
        self,
        master,
        index: int,
        title: str,
        summary: str,
        on_toggle: callable = None,
        width: int = 526,
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
        if not self.winfo_exists():
            return
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
            fill=background, outline=outline, width=1,
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

        text_width = max(80, width - 112)
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
    """扁平进度条：柔和轨道 + 强调色填充，平滑 60fps 插值动画。"""

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
        if self._anim_id is not None:
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
        if not self.winfo_exists():
            return
        self.delete("all")
        w = max(self.winfo_width(), 1)
        h = self._height
        _round_rectangle(
            self, 0, 0, w, h, r=h // 2,
            fill="#E0DAF7", outline="",
        )
        if self._value > 0:
            fw = max(h, int(w * self._value))
            _round_rectangle(
                self, 0, 0, fw, h, r=h // 2,
                fill=self._fill_color, outline="",
            )


# ==================== 生成页模式选择行卡片 ====================

class GenerationChoiceCard(tk.Canvas):
    """生成页专用的响应式模式选择行卡片。"""

    def __init__(
        self,
        master,
        title: str,
        subtitle: str,
        badge_text: str = "",
        initial_checked: bool = False,
        on_toggle: callable = None,
        width: int = 200,
        height: int = 58,
        show_separator: bool = True,
        **kwargs,
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
        self._height = max(54, min(70, round(self._base_height * scale)))
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
        end = len(text)
        while end > 0 and font.measure(text[:end]) > available:
            end -= 1
        return text[:end].rstrip() + ellipsis

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
        if not self.winfo_exists():
            return
        self.delete("all")
        width = max(self.winfo_width(), self._base_width)
        height = self._height
        if self._disabled:
            background = "#F8F9FB"
            title_color = COLOR_TEXT_DISABLED
        elif self._hover:
            background = "#F5F7FC"
            title_color = COLOR_TEXT_PRIMARY
        elif self._checked:
            background = "#FDFCFF"
            title_color = COLOR_TEXT_PRIMARY
        else:
            background = COLOR_CARD
            title_color = COLOR_TEXT_PRIMARY
        self.create_rectangle(0, 0, width, height, fill=background, outline="")
        content_y = height / 2 + (5 if self._badge else 0)
        title_x = 8
        self.create_text(
            title_x, content_y, text=self._title, fill=title_color,
            font=self._title_font, anchor="w",
        )
        copy_x = title_x + self._title_font.measure(self._title) + 18
        indicator_size = 20
        indicator_x = width - indicator_size - 8
        indicator_y = (height - indicator_size) / 2
        subtitle = self._ellipsize(
            self._subtitle, self._subtitle_font,
            int(indicator_x - copy_x - 16),
        )
        self.create_text(
            copy_x, content_y, text=subtitle,
            fill=(COLOR_TEXT_DISABLED if self._disabled else COLOR_TEXT_MUTED),
            font=self._subtitle_font, anchor="w",
        )
        _round_rectangle(
            self, indicator_x, indicator_y,
            indicator_x + indicator_size, indicator_y + indicator_size, r=6,
            fill=("#4F5FE7" if self._checked else COLOR_CARD),
            outline=("#4F5FE7" if self._checked else "#C9D1DC"),
        )
        if self._checked:
            self.create_line(
                indicator_x + 5, indicator_y + 10,
                indicator_x + 8.5, indicator_y + 13.5,
                indicator_x + 15, indicator_y + 6.5,
                fill="#FFFFFF", width=2,
                capstyle=tk.ROUND, joinstyle=tk.ROUND,
            )
        if self._badge:
            badge_width = self._badge_font.measure(self._badge) + 16
            badge_width += badge_width % 2
            badge_top = 2
            badge_bottom = 22
            _round_rectangle(
                self, 0, badge_top, badge_width, badge_bottom, r=8,
                fill=("#AAB1C0" if self._disabled else "#4658F5"),
                outline="",
            )
            self.create_text(
                badge_width / 2, (badge_top + badge_bottom) / 2,
                text=self._badge,
                fill="#FFFFFF", font=self._badge_font, anchor="center",
            )
        if self._show_separator:
            self.create_line(
                8, height - 1, width - 8, height - 1,
                fill=COLOR_BORDER, width=1,
            )


# ==================== 生成页分段单选胶囊 ====================

class GenerationSegmentOption(tk.Canvas):
    """生成页分段单选按钮（用于访问方式与内容来源切换）。"""

    def __init__(
        self,
        master,
        text: str,
        initial_checked: bool = False,
        on_toggle: callable = None,
        width: int = 142,
        height: int = 38,
        regular_font=FONT_SMALL,
        bold_font=FONT_SMALL_BOLD,
        min_font_size: int = 8,
        max_font_size: int = 10,
        **kwargs,
    ):
        super().__init__(
            master, width=width, height=height, bg="#F1F3F7",
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
        if not self.winfo_exists():
            return
        self.delete("all")
        if self._disabled:
            background = "#F8F9FB"
            foreground = COLOR_TEXT_DISABLED
            outline = COLOR_BORDER
        elif self._checked:
            background = COLOR_CARD
            foreground = COLOR_TEXT_PRIMARY
            outline = "#E1E4EA"
        elif self._hover:
            background = "#E9EBF1"
            foreground = COLOR_TEXT_PRIMARY
            outline = ""
        else:
            background = "#F1F3F7"
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


# ==================== 对话输入胶囊控制台 ====================

class GlassCapsulePanel(tk.Canvas):
    """带柔和薰衣草紫填充与圆角描边的对话输入控制台（Omnibox）。"""

    _PANEL_RADIUS = 32

    def __init__(self, master, bg_parent: str = COLOR_BG_APP, **kwargs):
        super().__init__(master, highlightthickness=0, bg=bg_parent, **kwargs)
        self._bg_parent = bg_parent
        self._dragging = False
        self.content = tk.Frame(self, bg=COLOR_OMNIBOX_SURFACE, padx=20, pady=0)
        self._content_window = self.create_window(
            16, 20, window=self.content, anchor="nw",
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
        height = self.content.winfo_reqheight() + 32
        if self.winfo_reqheight() != height:
            self.configure(height=height)

    def set_drop_highlight(self, highlighted: bool):
        self._dragging = bool(highlighted)
        self.redraw()

    def redraw(self):
        if not self.winfo_exists():
            return
        self.delete("glass")
        w, h = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        fill = "#EDE6FF" if self._dragging else COLOR_OMNIBOX_SURFACE
        outline = (
            COLOR_GENERATION_ACCENT if self._dragging else COLOR_OMNIBOX_BORDER
        )
        width_px = 2 if self._dragging else 1
        _round_rectangle(
            self, 8, 4, w - 8, h - 9, r=self._PANEL_RADIUS,
            fill=fill, outline=outline, width=width_px, tags="glass",
        )
        _round_rectangle(
            self, 8, 4, w - 8, h - 9, r=self._PANEL_RADIUS,
            fill="", outline=outline, width=width_px, tags="glass",
        )
        self.tag_lower("glass")


# ==================== 极简扁平输入框 ====================

class FlatEntryBox(tk.Canvas):
    """胶囊内的白色圆角输入框，带 12px 圆角、焦点光晕与右键快捷菜单。"""

    def __init__(
        self,
        master,
        on_change: callable = None,
        bg_parent: str = COLOR_BG_APP,
        placeholder: str = "",
        **kwargs,
    ):
        super().__init__(
            master, height=48, highlightthickness=0,
            bg=bg_parent, **kwargs,
        )
        self._bg_parent = bg_parent
        self._on_change = on_change
        self._locked = False
        self._focused = False
        self._placeholder = placeholder
        self._placeholder_font = tkfont.Font(
            master=self, font=(FONT_FAMILY, 10),
        )

        inner = tk.Frame(self, bg="#FFFFFF", padx=14, pady=10)
        self.window_id = self.create_window(0, 0, window=inner, anchor="nw")
        self.var = tk.StringVar()
        self.entry = tk.Entry(
            inner, textvariable=self.var, font=FONT_BODY,
            bg="#FFFFFF", fg=COLOR_TEXT_PRIMARY,
            insertbackground=COLOR_TEXT_PRIMARY,
            relief=tk.FLAT, bd=0, highlightthickness=0,
        )
        self.entry.pack(fill=tk.BOTH, expand=True)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.entry.bind("<KeyRelease>", self._on_keyrelease)
        self.entry.bind("<<Paste>>", lambda _e: self.after(10, self._paste_clipboard))
        self.entry.bind("<Button-3>", self._show_context_menu)
        self.bind("<Configure>", self._on_resize)
        self.var.trace_add("write", self._on_var_change)
        self._context_menu = None
        self.redraw()

    def _show_context_menu(self, event):
        if self._locked:
            return
        if self._context_menu is None:
            menu = tk.Menu(self.entry, tearoff=0, font=FONT_SMALL)
            menu.add_command(label="粘贴", command=self._paste_clipboard)
            menu.add_command(
                label="复制",
                command=lambda: self.entry.event_generate("<<Copy>>"),
            )
            menu.add_separator()
            menu.add_command(
                label="清空输入",
                command=lambda: self.set_text(""),
            )
            self._context_menu = menu
        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._context_menu.grab_release()

    def set_responsive_scale(self, scale: float):
        self._placeholder_font.configure(
            size=_scaled_font_size(self._placeholder_font, scale, 9, 11),
        )
        self.redraw()

    def _on_resize(self, event):
        self.configure(width=event.width)
        self.itemconfig(self.window_id, width=event.width, height=48)

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
        if not self.winfo_exists():
            return
        self.delete("frame")
        w = max(self.winfo_width(), 1)
        if self._focused:
            _round_rectangle(
                self, 0, 0, w, 48, r=13, fill="#DCEBFF", outline="",
                tags="frame",
            )
        outline = COLOR_ACCENT_BLUE if self._focused else "#DCE2EB"
        outline_w = 1.5 if self._focused else 1
        _round_rectangle(
            self, 2, 2, w - 2, 46, r=12,
            fill="#FFFFFF", outline=outline, width=outline_w, tags="frame",
        )
        self.tag_lower("frame")
        self.delete("placeholder")
        if (
            self._placeholder
            and not self._focused
            and not self._locked
            and not self.var.get()
        ):
            self.create_text(
                18, 24, text=self._placeholder,
                font=self._placeholder_font, fill="#9CA3AF",
                anchor="w", tags="placeholder",
            )


# ==================== 侧栏毛玻璃导航项 ====================

class GlassNavigationItem(tk.Canvas):
    """Argon 侧栏激活卡片，使用 Canvas 模拟薰衣草紫柔光渐变与平滑缓动。"""

    _CARD_MARGIN = 2
    _CARD_RADIUS = 16

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
        """绑定页面 active 状态，并以约 250ms 的缓动完成状态切换。"""
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
            self._progress += delta * 0.23
            self._animation_id = self.after(16, self._animate)
        self.redraw()

    @staticmethod
    def _mix(
        start: tuple[int, int, int],
        end: tuple[int, int, int],
        amount: float,
    ):
        return tuple(round(a + (b - a) * amount) for a, b in zip(start, end))

    def _draw_settings_gear(self, color: str):
        center_x, center_y = 27, 34
        points = []
        tooth_step = math.tau / 8
        for tooth in range(8):
            center = -math.pi / 2 + tooth * tooth_step
            for offset, radius in (
                (-tooth_step / 2, 8), (-tooth_step * 0.28, 8),
                (-tooth_step * 0.28, 11), (tooth_step * 0.28, 11),
                (tooth_step * 0.28, 8), (tooth_step / 2, 8),
            ):
                angle = center + offset
                points.extend((
                    center_x + radius * math.cos(angle),
                    center_y + radius * math.sin(angle),
                ))
        points.extend(points[:2])
        self.create_line(
            *points, fill=color, width=2, joinstyle=tk.ROUND,
            capstyle=tk.ROUND, tags="content",
        )
        self.create_oval(
            center_x - 4, center_y - 4, center_x + 4, center_y + 4,
            outline=color, width=2, tags="content",
        )

    def redraw(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        width, height = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        progress = self._progress
        left, top = self._CARD_MARGIN, self._CARD_MARGIN
        right, bottom = width - self._CARD_MARGIN, height - self._CARD_MARGIN

        if progress > 0.01:
            shadow = self._mix((255, 255, 255), (232, 222, 252), progress)
            _round_rectangle(
                self, left + 1, top + 4, right - 1, bottom,
                r=self._CARD_RADIUS, fill="#%02X%02X%02X" % shadow,
                outline="", tags="card",
            )
            stops = ((221, 214, 254), (196, 181, 253), (167, 139, 250))
            for y in range(top, bottom + 1):
                ratio = (y - top) / max(1, bottom - top)
                if ratio < 0.55:
                    color = self._mix(stops[0], stops[1], ratio / 0.55)
                else:
                    color = self._mix(stops[1], stops[2], (ratio - 0.55) / 0.45)
                color = self._mix((255, 255, 255), color, progress * 0.7)
                edge = min(y - top, bottom - y)
                inset = 0
                if edge < self._CARD_RADIUS:
                    inset = self._CARD_RADIUS - int(
                        max(
                            0,
                            self._CARD_RADIUS ** 2
                            - (self._CARD_RADIUS - edge) ** 2,
                        ) ** 0.5
                    )
                self.create_line(
                    left + inset, y, right - inset, y,
                    fill="#%02X%02X%02X" % color, tags="card",
                )
            _round_rectangle(
                self, left, top, right, bottom, r=self._CARD_RADIUS,
                fill="", outline="#FFFFFF", width=1, tags="card",
            )
        elif self._hovered:
            _round_rectangle(
                self, left, top, right, bottom, r=self._CARD_RADIUS,
                fill="#F7F9FC", outline="", tags="card",
            )

        icon_color = (
            "#1E293B" if (self._active or self._hovered)
            else COLOR_TEXT_SECONDARY
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
        self.create_text(
            width / 2, height / 2, text=self._title, font=self._title_font,
            fill="#0F172A", anchor="center", tags=("content", "title"),
        )


# ==================== 非模态悬停提示 ====================

class HoverTooltip:
    """350ms 悬停后弹出无边框深色浮层提示，自动规避屏幕边缘裁剪。"""

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 350):
        self._widget = widget
        self._text = text
        self._delay = delay_ms
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._hide()
        if not self._text or not self._widget.winfo_exists():
            return
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
            self._tip, text=self._text, bg="#0F172A", fg="#FFFFFF",
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
            y = max(
                8,
                self._widget.winfo_rooty() - self._tip.winfo_height() - 6,
            )
        self._tip.geometry(f"+{x}+{y}")

    def _hide(self, _event=None):
        if self._after_id is not None:
            try:
                self._widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


# ==================== 单行横向滚动文件列表 ====================

class HorizontalFileList(tk.Frame):
    """单行输出文件列表，仅在内容溢出时自动展开横向滚动条。"""

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
        if not self.canvas.winfo_exists():
            return
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
