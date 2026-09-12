"""AI 记忆总结协同管理工具 - 极简扁平侧栏版。

视觉系统：
- 纯白主底 + 240px 深色侧边任务栏
- 黑色主色调，单一蓝色 #0066FF 作为强调
- 6-8px 圆角克制风格，类 Notion/Linear
- 侧栏分步骤导航：输入 → 配置 → 生成 → 输出

保留所有原有功能与对外契约（公开方法名、属性名、回调签名不变）。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    from tkinterdnd2 import DND_FILES, DND_TEXT, TkinterDnD
    _HAS_DND = True
except ImportError:
    DND_FILES = ""
    DND_TEXT = ""
    TkinterDnD = None
    _HAS_DND = False
from gui.credential_store import CredentialStoreError, WindowsCredentialStore
from gui.settings_store import (
    AppSettings,
    SettingsStoreError,
    WindowsAppSettingsStore,
    default_app_settings,
)

from gui.run_logging import GenerationRunLog
from gui.service import (
    MODE_FILENAME_SUFFIXES,
    build_document_asset_directory,
    build_image_asset_directory,
    default_output_filename,
    fetch_chat_pipeline,
    generate_output_bundle,
    normalize_markdown_filename,
    requires_authenticated_browser,
)


# ==================== 调色板 ====================
COLOR_BG_APP = "#F8FAFD"
COLOR_SIDEBAR = "#FFFFFF"
COLOR_CARD = "#FFFFFF"
COLOR_BORDER = "#E3E8EF"
COLOR_BORDER_FOCUS = "#1A73E8"
COLOR_TEXT_PRIMARY = "#1E1F20"
COLOR_TEXT_SECONDARY = "#3C4043"
COLOR_TEXT_MUTED = "#5F6368"
COLOR_ACCENT = "#1E1F20"
COLOR_ACCENT_BLUE = "#1A73E8"
COLOR_ACCENT_BG = "#F0F4F9"
COLOR_SUCCESS = "#0F9D58"
COLOR_WARNING = "#F59E0B"
COLOR_DANGER = "#EA4335"
COLOR_HOVER = "#F0F4F9"
COLOR_DISABLED = "#E3E8EF"
COLOR_TEXT_DISABLED = "#9AA0A6"
COLOR_SIDEBAR_TEXT = "#5F6368"
COLOR_SIDEBAR_ACTIVE = "#1E1F20"
COLOR_SIDEBAR_ACTIVE_BG = "#F0F4F9"
COLOR_SIDEBAR_DIVIDER = "#E3E8EF"
COLOR_OMNIBOX_BG = "#F0F4F9"
COLOR_OMNIBOX_BG_FOCUS = "#FFFFFF"
COLOR_DRAG_HIGHLIGHT = "#EFF6FF"
COLOR_DRAG_NORMAL = "#F0F4F9"

FONT_FAMILY = "Microsoft YaHei UI"
FONT_TITLE = (FONT_FAMILY, 18, "bold")
FONT_H2 = (FONT_FAMILY, 14, "bold")
FONT_BODY = (FONT_FAMILY, 10)
FONT_BODY_BOLD = (FONT_FAMILY, 10, "bold")
FONT_SMALL = (FONT_FAMILY, 9)
FONT_SMALL_BOLD = (FONT_FAMILY, 9, "bold")
FONT_TINY = (FONT_FAMILY, 8)
FONT_HERO = (FONT_FAMILY, 24, "bold")
FONT_SIDEBAR_TITLE = (FONT_FAMILY, 12, "bold")
FONT_SIDEBAR_ITEM = (FONT_FAMILY, 10)
FONT_SIDEBAR_STEP = (FONT_FAMILY, 9, "bold")


# ==================== 输出目标询问与直接总结工具函数 ====================

def _prompt_output_target(
    parent: tk.Misc,
    modes: dict[str, bool],
    settings: AppSettings,
    suggested_name: str | None = None,
) -> tuple[Path, str] | None:
    """按设置询问输出目标；配置默认目录时只询问文件名。"""
    suggested_name = suggested_name or default_output_filename(modes)
    if settings.default_results_dir is not None:
        chosen_name = simpledialog.askstring(
            "设置保存名称",
            "请输入本次结果的保存名称：",
            initialvalue=suggested_name,
            parent=parent,
        )
        if not chosen_name or not chosen_name.strip():
            return None
        return (
            Path(settings.default_results_dir).resolve(),
            normalize_markdown_filename(chosen_name),
        )

    save_file = filedialog.asksaveasfilename(
        parent=parent,
        title=(
            "请选择保存位置并设置文件名"
            if sum(bool(value) for value in modes.values()) == 1
            else "请选择保存位置并设置共同文件名（将自动添加模式后缀）"
        ),
        initialdir=str(Path(settings.runtime_data_dir) / "results" / "summary"),
        initialfile=suggested_name,
        defaultextension=".md",
        filetypes=[("Markdown 文件", "*.md")],
    )
    if not save_file:
        return None
    selected_path = Path(save_file).resolve()
    return selected_path.parent, normalize_markdown_filename(selected_path.name)


DIRECT_SUMMARY_FILE_TYPES = {".md", ".txt"}
DIRECT_SUMMARY_MAX_BYTES = 10 * 1024 * 1024


def _load_direct_summary_file(path: Path) -> list[dict[str, str]]:
    """校验并读取可直接总结的本项目对话导出文件。"""
    path = Path(path).resolve()
    if path.suffix.lower() not in DIRECT_SUMMARY_FILE_TYPES:
        raise ValueError("仅支持 UTF-8 编码的 Markdown 或文本文件（.md/.txt）。")
    if not path.is_file():
        raise ValueError("所选文件不存在或已被移动。")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("所选文件为空。")
    if size > DIRECT_SUMMARY_MAX_BYTES:
        raise ValueError("所选文件超过 10 MiB 限制。")

    from scripts.gemini_summarizer import load_exported_markdown

    try:
        return load_exported_markdown(path)
    except UnicodeDecodeError as error:
        raise ValueError("所选文件不是有效的 UTF-8 文本。") from error


def _direct_summary_output_filename(
    source_path: Path,
    modes: dict[str, bool],
) -> str:
    """按原文件名生成直接总结的默认名称。"""
    stem = Path(source_path).stem.strip() or "AI_memory"
    enabled = [
        mode for mode in ("normal", "simple", "detailed")
        if modes.get(mode)
    ]
    if len(enabled) == 1:
        stem += MODE_FILENAME_SUFFIXES[enabled[0]]
    return f"{stem}.md"


# ==================== 通用绘制工具 ====================

def _round_rectangle(canvas: tk.Canvas, x1, y1, x2, y2, r=6, **kwargs):
    """在 Canvas 上绘制圆角矩形（极简扁平风格的卡片底）。"""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    if r <= 0:
        return canvas.create_rectangle(x1, y1, x2, y2, **kwargs)
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2,
        x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def _logo_png_path(size: int, variant: str = "neutral") -> Path:
    return (
        _PROJECT_ROOT / "gui" / "assets" / "logo"
        / variant / f"icon-{size}.png"
    )


def _navigation_icon_path(name: str, size: int = 24) -> Path:
    return _PROJECT_ROOT / "gui" / "assets" / "icons" / f"{name}-{size}.png"


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
            (16, 32, 64, 128, 256, 512, 1024),
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
    """纤细极简滚动条（深灰底、黑指示条、悬停加深）。"""

    def __init__(
        self,
        master,
        target_canvas: tk.Canvas,
        width: int = 6,
        **kwargs
    ):
        super().__init__(
            master, width=width, highlightthickness=0,
            bg=COLOR_BG_APP, **kwargs
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
        color = "#0A0A0A" if self._hover else "#525252"
        self._thumb_id = self.create_rectangle(
            1, thumb_y, self._width - 1, thumb_y + thumb_h,
            fill=color, outline="", tags="thumb"
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
                self._drag_start_first + delta)
        )
        self.target.yview_moveto(new_first)

    def _on_release(self, _event):
        self._drag_start_y = 0


# ==================== 极简扁平按钮 ====================

class FlatButton(tk.Canvas):
    """扁平按钮：黑底白字主按钮 / 描边次按钮 / 禁用灰底。"""

    def __init__(
        self,
        master,
        text: str,
        command: callable = None,
        variant: str = "primary",
        width: int = 220,
        height: int = 44,
        bg_parent: str = COLOR_BG_APP,
        **kwargs
    ):
        super().__init__(
            master, width=width, height=height,
            highlightthickness=0, bg=bg_parent, **kwargs
        )
        self._text = text
        self._command = command
        self._variant = variant
        self._width = width
        self._height = height
        self._enabled = True
        self._hover = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.redraw()

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        self.redraw()

    def _on_enter(self, _event=None):
        self._hover = True
        self.redraw()

    def _on_leave(self, _event=None):
        self._hover = False
        self.redraw()

    def _on_click(self, _event=None):
        if self._enabled and self._command:
            self._command()

    def redraw(self):
        self.delete("all")
        w, h = self._width, self._height
        if not self._enabled:
            bg, fg = COLOR_DISABLED, COLOR_TEXT_DISABLED
            outline = ""
        elif self._variant == "primary":
            bg = "#0A0A0A" if not self._hover else "#262626"
            fg = "#FFFFFF"
            outline = ""
        elif self._variant == "secondary":
            bg = COLOR_HOVER if self._hover else COLOR_CARD
            fg = COLOR_TEXT_PRIMARY
            outline = COLOR_BORDER
        else:
            bg = COLOR_HOVER if self._hover else self._bg_parent
            fg = COLOR_TEXT_PRIMARY
            outline = COLOR_BORDER
        _round_rectangle(
            self, 1, 1, w - 1, h - 1, r=6,
            fill=bg, outline=outline, width=1
        )
        self.create_text(
            w // 2, h // 2, text=self._text,
            fill=fg, font=FONT_BODY_BOLD
        )


# ==================== 极简扁平选择卡片 ====================

class FlatSelectCard(tk.Canvas):
    """扁平选择卡片：白底灰描边、悬停浅灰底、选中黑边 + 黑色对勾。

    支持 set_disabled / set_checked / _on_click 行为契约。
    """

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
        **kwargs
    ):
        super().__init__(
            master, width=width, height=height,
            highlightthickness=0, bg=bg_parent, **kwargs
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
            fill=bg, outline=outline, width=outline_w
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
            fill=indicator_fill, outline=indicator_color, width=1
        )
        if self._checked:
            self.create_line(
                ix + 3, iy + 7, ix + 6, iy + 10, ix + 11, iy + 4,
                fill="#FFFFFF", width=2, smooth=True
            )
        title_color = (
            COLOR_TEXT_DISABLED if self._disabled else COLOR_TEXT_PRIMARY
        )
        self.create_text(
            ix + isz + 10, iy + 2, text=self._title,
            fill=title_color, font=FONT_BODY_BOLD, anchor="nw"
        )
        sub_color = (
            COLOR_TEXT_DISABLED if self._disabled else COLOR_TEXT_SECONDARY
        )
        self.create_text(
            ix + isz + 10, iy + 22, text=self._subtitle,
            fill=sub_color, font=FONT_TINY, anchor="nw",
            width=w - ix - isz - 24
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
                fill=badge_bg, outline=""
            )
            self.create_text(
                bx + badge_w // 2, by + 9, text=self._badge,
                fill=(
                    COLOR_ACCENT
                    if self._checked and not self._disabled
                    else COLOR_TEXT_SECONDARY
                ),
                font=FONT_TINY
            )


# ==================== 极简扁平进度条 ====================

class FlatProgressBar(tk.Canvas):
    """扁平进度条：灰底 + 黑色填充，平滑动画。"""

    def __init__(
        self,
        master,
        height: int = 6,
        bg_parent: str = COLOR_BG_APP,
        **kwargs
    ):
        super().__init__(
            master, height=height, highlightthickness=0,
            bg=bg_parent, **kwargs
        )
        self._height = height
        self._value = 0.0
        self._target = 0.0
        self._anim_id = None
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_progress(self, val: float):
        self._target = max(0.0, min(1.0, float(val)))
        if self._anim_id is None:
            self._animate_step()

    def reset(self):
        self._target = 0.0
        self._value = 0.0
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None
        self.redraw()

    def _animate_step(self):
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
            self, 0, 0, w, h, r=h // 2,
            fill=COLOR_BORDER, outline=""
        )
        if self._value > 0:
            fw = max(h, int(w * self._value))
            _round_rectangle(
                self, 0, 0, fw, h, r=h // 2,
                fill=COLOR_TEXT_PRIMARY, outline=""
            )


# ==================== 对话输入胶囊 ====================

# Omnibox 的控件层无法像 Web CSS 一样透明，因此使用这层浅紫蓝作为
# 渐变中心色；真正的渐变由 GlassCapsulePanel 的 Canvas 绘制在整个面板上。
COLOR_OMNIBOX_SURFACE = "#EEF1FF"

class GlassCapsulePanel(tk.Canvas):
    """带全幅渐变、高光边框与弥散阴影的对话输入控制台。

    Tk 不支持 CSS ``backdrop-filter``，因此用分层色块模拟半透明玻璃的
    深浅变化；交互层仍是普通 Tk 控件，保证拖拽、键盘与辅助功能正常工作。
    """

    def __init__(self, master, bg_parent: str = COLOR_BG_APP, **kwargs):
        # 选中文件时会额外显示一行文件胶囊，预留高度避免内容被 Canvas 裁切。
        super().__init__(master, height=172, highlightthickness=0,
                         bg=bg_parent, **kwargs)
        self._bg_parent = bg_parent
        self._dragging = False
        self.content = tk.Frame(self, bg=COLOR_OMNIBOX_SURFACE, padx=20, pady=16)
        self._content_window = self.create_window(
            16, 12, window=self.content, anchor="nw"
        )
        self.bind("<Configure>", self._on_resize)
        self.redraw()

    def _on_resize(self, event):
        self.itemconfigure(
            self._content_window,
            width=max(1, event.width - 32),
            height=max(1, event.height - 24),
        )
        self.redraw()

    def set_drop_highlight(self, highlighted: bool):
        self._dragging = bool(highlighted)
        self.redraw()

    def redraw(self):
        self.delete("glass")
        w, h = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        # 三层柔影 + 覆盖整个控制台的蓝紫暖色渐变。
        _round_rectangle(self, 12, 10, w - 4, h - 1, r=24,
                         fill="#E5EAF2", outline="", tags="glass")
        _round_rectangle(self, 8, 6, w - 8, h - 7, r=24,
                         fill="#EEF2F8", outline="", tags="glass")
        fill = "#E6F0FF" if self._dragging else "#EEF1FF"
        outline = COLOR_ACCENT_BLUE if self._dragging else "#FFFFFF"
        _round_rectangle(self, 8, 4, w - 8, h - 9, r=24,
                         fill=fill, outline=outline,
                         width=2 if self._dragging else 1, tags="glass")
        # Tk 没有原生渐变填充，逐行混色让整块控制台（而非仅顶部）呈现渐变。
        stops = ((0.0, (224, 238, 255)), (0.54, (239, 232, 255)),
                 (1.0, (255, 237, 226)))
        for y in range(5, max(6, h - 8)):
            position = (y - 5) / max(1, h - 13)
            for index, (start, start_rgb) in enumerate(stops[:-1]):
                end, end_rgb = stops[index + 1]
                if start <= position <= end:
                    progress = (position - start) / (end - start)
                    rgb = tuple(round(a + (b - a) * progress)
                                for a, b in zip(start_rgb, end_rgb))
                    self.create_line(9, y, w - 9, y,
                                     fill="#{:02X}{:02X}{:02X}".format(*rgb),
                                     tags="glass")
                    break
        # 重新绘制内层描边，使渐变在圆角内完整收口。
        _round_rectangle(self, 8, 4, w - 8, h - 9, r=24,
                         fill="", outline=outline,
                         width=2 if self._dragging else 1, tags="glass")
        self.tag_lower("glass")


# ==================== 极简扁平输入框 ====================

class FlatEntryBox(tk.Canvas):
    """胶囊内的白色输入框，带 12px 圆角和蓝色焦点光晕。"""

    def __init__(
        self,
        master,
        on_change: callable = None,
        bg_parent: str = COLOR_BG_APP,
        placeholder: str = "",
        **kwargs
    ):
        super().__init__(
            master, height=48, highlightthickness=0,
            bg=bg_parent, **kwargs
        )
        self._bg_parent = bg_parent
        self._on_change = on_change
        self._locked = False
        self._focused = False
        self._placeholder = placeholder

        inner = tk.Frame(self, bg="#FFFFFF", padx=14, pady=10)
        self.window_id = self.create_window(0, 0, window=inner, anchor="nw")
        self.var = tk.StringVar()
        self.entry = tk.Entry(
            inner, textvariable=self.var, font=FONT_BODY,
            bg="#FFFFFF", fg=COLOR_TEXT_PRIMARY,
            insertbackground=COLOR_TEXT_PRIMARY,
            relief=tk.FLAT, bd=0, highlightthickness=0
        )
        self.entry.pack(fill=tk.BOTH, expand=True)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.entry.bind("<KeyRelease>", self._on_keyrelease)
        self.entry.bind("<<Paste>>", lambda _e: self.after(10, self._paste_clipboard))
        self.bind("<Configure>", self._on_resize)
        self.var.trace_add("write", self._on_var_change)
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
        if self._on_change:
            self._on_change()

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
        # 外圈是桌面端对 ``focus box-shadow`` 的近似实现。
        if self._focused:
            _round_rectangle(
                self, 0, 0, w, 48, r=13, fill="#DCEBFF", outline="",
                tags="frame"
            )
        outline = COLOR_ACCENT_BLUE if self._focused else "#DCE2EB"
        outline_w = 1.5 if self._focused else 1
        _round_rectangle(
            self, 2, 2, w - 2, 46, r=12,
            fill="#FFFFFF", outline=outline, width=outline_w, tags="frame"
        )
        self.tag_lower("frame")
        # placeholder：未聚焦且为空时显示浅灰提示
        self.delete("placeholder")
        if (
            self._placeholder
            and not self._focused
            and not self._locked
            and not self.var.get()
        ):
            self.create_text(
                18, 24, text=self._placeholder,
                font=(FONT_FAMILY, 10), fill="#9CA3AF",
                anchor="w", tags="placeholder",
            )


# ==================== 侧栏毛玻璃导航项 ====================

class GlassNavigationItem(tk.Canvas):
    """Gemini 风格的侧栏激活卡片，使用 Canvas 模拟渐变和柔光过渡。"""

    _CARD_MARGIN = 2
    _CARD_RADIUS = 16

    def __init__(self, master, icon: str, title: str, description: str, **kwargs):
        super().__init__(
            master, height=68, highlightthickness=0, bd=0,
            bg=COLOR_SIDEBAR, cursor="hand2", **kwargs,
        )
        self._icon = icon
        self._title = title
        self._description = description
        icon_asset = {
            "对话": "chat-outline",
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
        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.redraw()

    def set_active(self, active: bool):
        """绑定页面 active 状态，并以约 250ms 的缓动完成状态切换。"""
        self._active = bool(active)
        self._target_progress = 1.0 if self._active else 0.0
        if self._animation_id is None:
            self._animate()

    def _on_enter(self, _event):
        self._hovered = True
        self.redraw()

    def _on_leave(self, _event):
        self._hovered = False
        self.redraw()

    def _animate(self):
        # 16ms 一帧、缓入缓出，等效 CSS 的 0.25s cubic-bezier 过渡。
        delta = self._target_progress - self._progress
        if abs(delta) < 0.02:
            self._progress = self._target_progress
            self._animation_id = None
        else:
            self._progress += delta * 0.23
            self._animation_id = self.after(16, self._animate)
        self.redraw()

    @staticmethod
    def _mix(start: tuple[int, int, int], end: tuple[int, int, int], amount: float):
        return tuple(round(a + (b - a) * amount) for a, b in zip(start, end))

    def redraw(self):
        self.delete("all")
        width, height = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        progress = self._progress
        left, top = self._CARD_MARGIN, self._CARD_MARGIN
        right, bottom = width - self._CARD_MARGIN, height - self._CARD_MARGIN

        if progress > 0.01:
            # 0 4px 16px 蓝色柔光与 0 2px 4px 中性阴影的 Tk 等效层。
            shadow = self._mix((255, 255, 255), (222, 234, 251), progress)
            _round_rectangle(self, left + 1, top + 4, right - 1, bottom,
                             r=self._CARD_RADIUS, fill="#%02X%02X%02X" % shadow,
                             outline="", tags="card")
            # 以逐行混色描绘冰蓝 -> 靛紫 -> 暖橙粉的弥散渐变。
            stops = ((191, 219, 254), (224, 231, 255), (254, 215, 170))
            for y in range(top, bottom + 1):
                ratio = (y - top) / max(1, bottom - top)
                if ratio < 0.55:
                    color = self._mix(stops[0], stops[1], ratio / 0.55)
                else:
                    color = self._mix(stops[1], stops[2], (ratio - 0.55) / 0.45)
                # 以白底混合模拟 rgba(…, 0.5–0.7)，并让渐变随 active 渐入。
                color = self._mix((255, 255, 255), color, progress * 0.7)
                # 圆角区域按圆弧收缩，避免渐变在边角变成方形。
                edge = min(y - top, bottom - y)
                inset = 0
                if edge < self._CARD_RADIUS:
                    inset = self._CARD_RADIUS - int(
                        max(0, self._CARD_RADIUS ** 2 - (self._CARD_RADIUS - edge) ** 2) ** 0.5
                    )
                self.create_line(left + inset, y, right - inset, y,
                                 fill="#%02X%02X%02X" % color, tags="card")
            _round_rectangle(
                self, left, top, right, bottom, r=self._CARD_RADIUS,
                fill="", outline="#FFFFFF", width=1, tags="card",
            )
        elif self._hovered:
            _round_rectangle(self, left, top, right, bottom, r=self._CARD_RADIUS,
                             fill="#F7F9FC", outline="", tags="card")

        icon_color = "#1E293B" if (self._active or self._hovered) else COLOR_TEXT_SECONDARY
        if self._navigation_icon_image is not None:
            self.create_image(
                27, 34, image=self._navigation_icon_image,
                anchor=tk.CENTER, tags="content",
            )
        else:
            self.create_text(27, 34, text=self._icon, font=(FONT_FAMILY, 14),
                             fill=icon_color, anchor="center", tags="content")
        self.create_text(52, 27, text=self._title, font=(FONT_FAMILY, 10, "bold"),
                         fill="#0F172A", anchor="w", tags="content")
        self.create_text(52, 45, text=self._description, font=(FONT_FAMILY, 8),
                         fill="#475569", anchor="w", tags="content")


# ==================== 悬停提示 ====================

class HoverTooltip:
    """350ms 悬停后弹出无边框深色提示。"""

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 350):
        self._widget = widget
        self._text = text
        self._delay = delay_ms
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, _event=None):
        self._hide()
        self._after_id = self._widget.after(self._delay, self._show)

    def _show(self):
        if self._tip or not self._widget.winfo_exists():
            return
        x = self._widget.winfo_rootx() + 16
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 6
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.geometry(f"+{x}+{y}")
        tk.Label(
            self._tip, text=self._text, bg="#0A0A0A", fg="#FFFFFF",
            font=FONT_TINY, padx=8, pady=4
        ).pack()

    def _hide(self, _event=None):
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


# ==================== 主 GUI ====================

class AIMemoryGUI:
    """AI 记忆总结协同管理工具主界面（极简扁平侧栏版）。

    保留所有公开方法签名与属性名以兼容测试与服务层契约。
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("AI 记忆总结协同管理工具")
        root.geometry("960x680")
        root.minsize(820, 560)
        root.configure(bg=COLOR_BG_APP)
        self._window_icon = tk.PhotoImage(file=str(_logo_png_path(64)))
        root.iconphoto(True, self._window_icon)

        self.is_running = False
        self.selected_summary_file: Path | None = None
        self.credential_store = WindowsCredentialStore()
        self.settings_store = WindowsAppSettingsStore()
        try:
            self.app_settings = self.settings_store.load()
        except (SettingsStoreError, Exception):
            self.app_settings = default_app_settings()

        self._settings_dialog = None
        self._api_key_dialog = None
        self._settings_load_error = None

        self._build_ui()
        self._update_generate_button_state()

    # ---------------- UI 构建 ----------------

    def _build_ui(self):
        top = tk.Frame(self.root, bg=COLOR_BG_APP)
        top.pack(fill=tk.BOTH, expand=True)

        # ===== 左侧任务栏（白底 + 图标导航） =====
        sidebar = tk.Frame(
            top, bg=COLOR_SIDEBAR, width=200,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
        )
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # Logo + 标题
        header = tk.Frame(sidebar, bg=COLOR_SIDEBAR, padx=20, pady=24)
        header.pack(fill=tk.X)
        logo_row = tk.Frame(header, bg=COLOR_SIDEBAR)
        logo_row.pack(fill=tk.X)
        # 使用统一的灰色堆叠层图标，替换旧的黑色方块标识。
        StackedLayersIcon(
            logo_row, width=32, height=32, bg=COLOR_SIDEBAR,
        ).pack(side=tk.LEFT)
        tk.Label(
            logo_row, text="AI 记忆协同管理", font=FONT_SIDEBAR_TITLE,
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_SIDEBAR, anchor="w",
        ).pack(side=tk.LEFT, padx=(4, 0))

        tk.Frame(
            sidebar, bg=COLOR_SIDEBAR_DIVIDER, height=1
        ).pack(fill=tk.X, padx=20, pady=(16, 10))

        # 步骤导航（图标 + 标题 + 副标题）
        nav = tk.Frame(sidebar, bg=COLOR_SIDEBAR, padx=10, pady=4)
        nav.pack(fill=tk.BOTH, expand=True)

        self._nav_steps = [
            ("💬", "对话", "链接 + 文件合一输入"),
            ("📑", "生成", "模式与流水线"),
            ("🕒", "历史", "查看任务记录"),
            ("⚙️", "设置", "API KEY / 数据位置"),
        ]
        self._nav_items: list[GlassNavigationItem] = []
        for idx, (icon, title, desc) in enumerate(self._nav_steps):
            item = GlassNavigationItem(nav, icon, title, desc)
            # nav 自身保留 10px 内边距，让卡片距侧栏两侧自然留白。
            item.pack(fill=tk.X, pady=3)
            self._nav_items.append(item)
            # Canvas 作为完整的可点击卡片，点击任意位置均切换页面。
            item.bind("<Button-1>", lambda _e, i=idx: self._show_page(i))

        # 保留 api_key_button 契约：指向设置导航项（测试依赖此属性存在）
        self.api_key_button = self._nav_items[-1]

        # 底部：版本信息（设置已并入侧栏导航项）
        footer = tk.Frame(sidebar, bg=COLOR_SIDEBAR, padx=16, pady=12)
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Frame(
            footer, bg=COLOR_SIDEBAR_DIVIDER, height=1
        ).pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            footer, text="AI 记忆协同管理 v1.0", font=FONT_TINY,
            fg=COLOR_TEXT_MUTED, bg=COLOR_SIDEBAR, anchor="w",
        ).pack(fill=tk.X)

        # ===== 右侧主内容区 =====
        main = tk.Frame(top, bg=COLOR_BG_APP)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.bg_canvas = tk.Canvas(
            main, highlightthickness=0, bg=COLOR_BG_APP
        )
        self.bg_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.custom_scrollbar = MinimalScrollbar(
            main, target_canvas=self.bg_canvas, width=6
        )
        self.custom_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=20)
        self.bg_canvas.config(yscrollcommand=self.custom_scrollbar.set_range)

        self.main_content = tk.Frame(self.bg_canvas, bg=COLOR_BG_APP)
        self.canvas_window_id = self.bg_canvas.create_window(
            0, 0, window=self.main_content, anchor="nw"
        )

        self.bg_canvas.bind("<Configure>", self._on_canvas_configure)
        self.main_content.bind("<Configure>", self._on_content_configure)
        self._bind_mousewheel()

        # ===== 分层页面：每次仅显示一页（含设置页内嵌） =====
        self.page_frames: list[tk.Frame] = []
        self._current_page = 0
        for _ in range(len(self._nav_steps)):
            page = tk.Frame(self.main_content, bg=COLOR_BG_APP)
            self.page_frames.append(page)

        # 保留 sheet_frame 指向首帧以维持既有契约
        self.sheet_frame = self.page_frames[0]

        self._build_input_section()        # 对话页（统一 Omnibox）
        self._build_generation_section()   # 生成页
        self._build_history_section()      # 历史页
        self._build_settings_section()     # 设置页（内嵌）

        self._show_page(0)

    def _show_page(self, idx: int):
        """切换分层页面：隐藏全部，仅显示指定页；同步侧栏高亮。"""
        if not (0 <= idx < len(self.page_frames)):
            return
        self._current_page = idx
        for i, page in enumerate(self.page_frames):
            if i == idx:
                page.pack(fill=tk.BOTH, expand=True, padx=24, pady=24)
                page.lift()
            else:
                page.pack_forget()
        for i, item in enumerate(self._nav_items):
            item.set_active(i == idx)
        self.bg_canvas.update_idletasks()
        self._on_canvas_configure(None)
        # 强制更新 scrollregion 确保滚动生效
        bb = self.bg_canvas.bbox("all")
        if bb:
            self.bg_canvas.configure(scrollregion=bb)
        # 延迟再更新一次，确保内容完全布局后 scrollregion 正确
        self.bg_canvas.after(50, self._refresh_scrollregion)
        # 为新显示的页面子控件绑定滚轮（递归）
        self._bind_wheel_recursive(self.page_frames[idx])

    def _refresh_scrollregion(self):
        """延迟回调：内容布局完成后重新计算 scrollregion。"""
        self.bg_canvas.update_idletasks()
        bb = self.bg_canvas.bbox("all")
        if bb:
            self.bg_canvas.configure(scrollregion=bb)

    def _bind_wheel_recursive(self, widget):
        """递归为控件及其所有子控件绑定滚轮事件。"""
        def on_wheel(event):
            try:
                raw = event.delta
                if raw == 0:
                    return
                px = max(1, min(40, abs(raw) // 4))
                direction = px if raw < 0 else -px
                self._smooth_scroll(direction)
                return "break"
            except tk.TclError:
                pass

        try:
            widget.bind("<MouseWheel>", on_wheel)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._bind_wheel_recursive(child)

    # ---------------- 对话页：统一 Omnibox ----------------

    def _build_input_section(self):
        """对话页：统一 Omnibox（链接 + 文件拖拽 + 胶囊 + 工具栏 + 发送按钮）。"""
        page = self.page_frames[0]
        page.configure(bg=COLOR_BG_APP)

        center = tk.Frame(page, bg=COLOR_BG_APP)
        center.pack(fill=tk.BOTH, expand=True)

        # ===== 品牌视觉中枢（居中，上方弹性留白） =====
        spacer_top = tk.Frame(center, bg=COLOR_BG_APP)
        spacer_top.pack(fill=tk.BOTH, expand=True)

        welcome = tk.Frame(center, bg=COLOR_BG_APP)
        welcome.pack(pady=(0, 8))
        # 使用同一品牌图标，替换旧的蓝色四角星标识。
        StackedLayersIcon(
            welcome, width=64, height=64, bg=COLOR_BG_APP,
        ).pack()
        tk.Label(
            welcome, text="AI 记忆协同管理", font=FONT_HERO,
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP,
        ).pack(pady=(12, 4))
        tk.Label(
            welcome, text="让对话更连续，让知识可复用",
            font=FONT_SMALL, fg=COLOR_TEXT_MUTED, bg=COLOR_BG_APP,
        ).pack()

        # ===== 统一 Omnibox 卡片（居中，最大宽度 ~720px） =====
        omnibox = GlassCapsulePanel(center, bg_parent=COLOR_BG_APP)
        omnibox.pack(fill=tk.X, padx=72, pady=(28, 0))
        self._omnibox = omnibox
        omnibox_body = omnibox.content

        # 文件胶囊区（默认隐藏，文件附加后显示）
        self.selected_file_row = tk.Frame(omnibox_body, bg=COLOR_OMNIBOX_SURFACE)
        self.selected_file_row.pack(fill=tk.X, pady=(0, 8))
        self.selected_file_row.pack_forget()
        self.selected_file_name_var = tk.StringVar(value="")
        file_capsule = tk.Frame(
            self.selected_file_row, bg="#EAF2FF",
            padx=10, pady=4,
        )
        file_capsule.pack(side=tk.LEFT)
        tk.Label(
            file_capsule, textvariable=self.selected_file_name_var,
            font=FONT_SMALL, fg=COLOR_TEXT_PRIMARY, bg="#EAF2FF",
            anchor="w",
        ).pack(side=tk.LEFT)
        self.clear_file_button = tk.Button(
            file_capsule, text="✕",
            command=self._clear_summary_file,
            font=FONT_SMALL_BOLD, bg="#EAF2FF", fg=COLOR_DANGER,
            activebackground="#EAF2FF", activeforeground=COLOR_DANGER,
            relief=tk.FLAT, bd=0, cursor="hand2",
            padx=4, pady=0
        )
        self.clear_file_button.pack(side=tk.LEFT, padx=(6, 0))

        # 自适应文本输入区
        self.capsule_entry = FlatEntryBox(
            omnibox_body, on_change=self._on_url_changed,
            bg_parent=COLOR_OMNIBOX_SURFACE,
            placeholder="粘贴或拖拽文件/链接",
        )
        self.capsule_entry.pack(fill=tk.X)

        # ===== 底部微型工具栏 =====
        toolbar = tk.Frame(omnibox_body, bg=COLOR_OMNIBOX_SURFACE)
        toolbar.pack(fill=tk.X, pady=(12, 0))

        # 左下角：添加文件 + 粘贴链接
        toolbar_left = tk.Frame(toolbar, bg=COLOR_OMNIBOX_SURFACE)
        toolbar_left.pack(side=tk.LEFT)

        self.file_select_button = tk.Button(
            toolbar_left, text="📎 添加文件",
            command=self._choose_summary_file,
            font=(FONT_FAMILY, 9), bg=COLOR_OMNIBOX_SURFACE, fg="#4B5563",
            activebackground=COLOR_OMNIBOX_SURFACE, activeforeground="#1E293B",
            relief=tk.FLAT, bd=0, cursor="hand2",
            padx=8, pady=4
        )
        self.file_select_button.pack(side=tk.LEFT, padx=(0, 16))

        btn_paste = tk.Button(
            toolbar_left, text="🔗 粘贴链接",
            command=self._paste_clipboard_to_entry,
            font=(FONT_FAMILY, 9), bg=COLOR_OMNIBOX_SURFACE, fg="#4B5563",
            activebackground=COLOR_OMNIBOX_SURFACE, activeforeground="#1E293B",
            relief=tk.FLAT, bd=0, cursor="hand2",
            padx=8, pady=4
        )
        btn_paste.pack(side=tk.LEFT)

        # 右下角：直接总结 + 发送按钮
        toolbar_right = tk.Frame(toolbar, bg=COLOR_OMNIBOX_SURFACE)
        toolbar_right.pack(side=tk.RIGHT)

        self.btn_direct = FlatButton(
            toolbar_right, text="📝 直接总结此文件",
            command=self._on_direct_summary,
            variant="secondary", width=160, height=32, bg_parent=COLOR_OMNIBOX_SURFACE
        )
        # 默认隐藏（仅文件附加时显示）
        self.btn_direct.pack(side=tk.RIGHT, padx=(4, 0))
        self.btn_direct.pack_forget()

        self.btn_send = tk.Button(
            toolbar_right, text="→",
            command=self._on_omnibox_send,
            font=(FONT_FAMILY, 15, "bold"), bg=COLOR_OMNIBOX_SURFACE,
            fg="#FFFFFF",
            activebackground=COLOR_OMNIBOX_SURFACE, activeforeground=COLOR_ACCENT_BLUE,
            relief=tk.FLAT, bd=0, cursor="arrow",
            width=3, pady=2, highlightthickness=0,
        )
        self.btn_send.pack(side=tk.RIGHT)
        self.btn_send.bind("<Enter>", self._on_send_hover)
        self.btn_send.bind("<Leave>", self._on_send_leave)
        self._update_send_button_state()

        # 配置拖拽到整个 Omnibox
        self._configure_file_drop()

        # 底部呼吸留白（替代原示例问题区，保持居中纯净感）
        spacer = tk.Frame(center, bg=COLOR_BG_APP, height=80)
        spacer.pack(fill=tk.BOTH, expand=True)

    def _on_omnibox_send(self):
        """Omnibox 发送按钮：检测链接或文件，分流到生成页或直接总结。"""
        url = self.capsule_entry.get_text()
        has_file = bool(getattr(self, "_selected_summary_file", None))
        if has_file and not url:
            self._on_direct_summary()
        elif url:
            self._show_page(1)

    def _update_send_button_state(self):
        """根据输入内容更新发送按钮激活状态。"""
        url = self.capsule_entry.get_text() if hasattr(self, "capsule_entry") else ""
        has_file = bool(getattr(self, "_selected_summary_file", None))
        active = bool(url.strip()) or has_file
        if active:
            self.btn_send.config(
                bg=COLOR_OMNIBOX_SURFACE, fg=COLOR_ACCENT_BLUE,
                activebackground=COLOR_OMNIBOX_SURFACE,
                cursor="hand2",
            )
        else:
            self.btn_send.config(
                bg=COLOR_OMNIBOX_SURFACE, fg="#B8C0CB",
                cursor="arrow",
            )
        # 文件附加时显示"直接总结"按钮
        if has_file:
            self.btn_direct.pack(side=tk.RIGHT, padx=(4, 0))
        else:
            self.btn_direct.pack_forget()

    def _on_send_hover(self, _event=None):
        """用字符位移模拟无边框箭头按钮的 hover 微动效。"""
        if self.btn_send.cget("cursor") == "hand2":
            self.btn_send.config(text="  →", fg="#1E293B")

    def _on_send_leave(self, _event=None):
        self.btn_send.config(text="→")
        if self.btn_send.cget("cursor") == "hand2":
            self.btn_send.config(fg=COLOR_ACCENT_BLUE)

    def _paste_clipboard_to_entry(self):
        try:
            text = self.root.clipboard_get()
            self.capsule_entry.var.set(text.strip())
            self._on_url_changed()
        except tk.TclError:
            pass

    # ---------------- 生成页（合并配置 + 生成） ----------------

    def _build_generation_section(self):
        """生成页：模式选择 + 登录策略 + 进度 + 生成按钮。"""
        page = self.page_frames[1]
        page.configure(bg=COLOR_BG_APP)

        section = tk.Frame(page, bg=COLOR_BG_APP)
        section.pack(fill=tk.BOTH, expand=True, padx=80, pady=(24, 24))

        tk.Label(
            section, text="生成", font=(FONT_FAMILY, 18, "bold"),
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP, anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            section, text="选择合适的模式，开始生成你的记忆总结",
            font=FONT_SMALL, fg=COLOR_TEXT_SECONDARY, bg=COLOR_BG_APP,
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 16))

        # 模式卡片列表（纵向堆叠）
        self.card_raw = FlatSelectCard(
            section, title="仅抓取对话",
            subtitle="raw 原始问答 / 不调用总结 API",
            badge_text="", initial_checked=False,
            on_toggle=self._on_mode_toggled, theme_color=COLOR_ACCENT,
            bg_parent=COLOR_BG_APP, width=640, height=72,
        )
        self.card_raw.configure(bg=COLOR_BG_APP)
        self.card_raw.pack(fill=tk.X, pady=4)

        self.card_normal = FlatSelectCard(
            section, title="结构化总结",
            subtitle="整理为结构化多级总结，支持自定义大纲",
            badge_text="推荐", initial_checked=True,
            on_toggle=self._on_mode_toggled, theme_color=COLOR_ACCENT,
            bg_parent=COLOR_BG_APP, width=640, height=72,
        )
        self.card_normal.configure(bg=COLOR_BG_APP)
        self.card_normal.pack(fill=tk.X, pady=4)

        self.card_simple = FlatSelectCard(
            section, title="高保真总览",
            subtitle="单段落高保真总览，保留关键信息",
            badge_text="", initial_checked=False,
            on_toggle=self._on_mode_toggled, theme_color=COLOR_ACCENT,
            bg_parent=COLOR_BG_APP, width=640, height=72,
        )
        self.card_simple.configure(bg=COLOR_BG_APP)
        self.card_simple.pack(fill=tk.X, pady=4)

        self.card_detailed = FlatSelectCard(
            section, title="细节要点",
            subtitle="提取核心要点、事实与数据引用",
            badge_text="", initial_checked=False,
            on_toggle=self._on_mode_toggled, theme_color=COLOR_ACCENT,
            bg_parent=COLOR_BG_APP, width=640, height=72,
        )
        self.card_detailed.configure(bg=COLOR_BG_APP)
        self.card_detailed.pack(fill=tk.X, pady=4)

        # 登录策略
        tk.Label(
            section, text="登录策略", font=FONT_BODY_BOLD,
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP, anchor="w",
        ).pack(fill=tk.X, pady=(20, 4))
        tk.Label(
            section, text="选择用于访问受限内容的方式",
            font=FONT_SMALL, fg=COLOR_TEXT_SECONDARY, bg=COLOR_BG_APP,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 8))

        self.card_no_login = FlatSelectCard(
            section, title="复用会话",
            subtitle="使用当前会话进行操作，适用于临时任务",
            is_radio=True, initial_checked=True,
            on_toggle=self._on_auth_toggled, theme_color=COLOR_ACCENT,
            bg_parent=COLOR_BG_APP, width=640, height=64, badge_text=""
        )
        self.card_no_login.configure(bg=COLOR_BG_APP)
        self.card_no_login.pack(fill=tk.X, pady=4)

        self.card_need_login = FlatSelectCard(
            section, title="授权登录",
            subtitle="系统呼出独立隔离浏览器，手动完成首次登录",
            is_radio=True, initial_checked=False,
            on_toggle=self._on_auth_toggled, theme_color=COLOR_ACCENT,
            bg_parent=COLOR_BG_APP, width=640, height=64, badge_text=""
        )
        self.card_need_login.configure(bg=COLOR_BG_APP)
        self.card_need_login.pack(fill=tk.X, pady=4)

        # 状态 + 进度卡
        progress_card = tk.Frame(
            section, bg=COLOR_CARD, padx=24, pady=18,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
        )
        progress_card.pack(fill=tk.X, pady=(20, 16))

        status_row = tk.Frame(progress_card, bg=COLOR_CARD)
        status_row.pack(fill=tk.X, pady=(0, 10))
        self.status_var = tk.StringVar(value="准备就绪")
        tk.Label(
            status_row, textvariable=self.status_var,
            font=FONT_SMALL, fg=COLOR_TEXT_SECONDARY, bg=COLOR_CARD,
            anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.percent_var = tk.StringVar(value="")
        tk.Label(
            status_row, textvariable=self.percent_var,
            font=FONT_SMALL_BOLD, fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD,
            anchor="e",
        ).pack(side=tk.RIGHT)

        self.progress_bar = FlatProgressBar(
            progress_card, height=6, bg_parent=COLOR_CARD
        )
        self.progress_bar.pack(fill=tk.X)

        # 操作按钮
        action_row = tk.Frame(section, bg=COLOR_BG_APP)
        action_row.pack(fill=tk.X, pady=(12, 0))
        self.btn_generate = FlatButton(
            action_row, text="🚀 开始生成",
            command=self._on_start_generate,
            variant="primary", width=180, height=44, bg_parent=COLOR_BG_APP
        )
        self.btn_generate.pack(side=tk.LEFT, padx=(0, 12))

        self.done_badge = tk.Label(
            section, text="✓ 生成完成", font=FONT_BODY_BOLD,
            fg=COLOR_SUCCESS, bg=COLOR_BG_APP, anchor="w"
        )

    # ---------------- 历史页 ----------------

    def _build_history_section(self):
        """历史页：任务卡片列表 + 5 指标看板 + 定位跳转。"""
        page = self.page_frames[2]
        page.configure(bg=COLOR_BG_APP)

        section = tk.Frame(page, bg=COLOR_BG_APP)
        section.pack(fill=tk.BOTH, expand=True, padx=80, pady=(24, 24))

        tk.Label(
            section, text="历史", font=(FONT_FAMILY, 18, "bold"),
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP, anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            section, text="查看历次任务的耗时统计与已生成文件",
            font=FONT_SMALL, fg=COLOR_TEXT_SECONDARY, bg=COLOR_BG_APP,
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 20))

        # 历史列表容器（滚动）
        self.history_list_frame = tk.Frame(section, bg=COLOR_BG_APP)
        self.history_list_frame.pack(fill=tk.BOTH, expand=True)

        # 空状态提示
        self.history_empty_label = tk.Label(
            self.history_list_frame,
            text="暂无历史记录\n完成一次生成后，任务记录将在此显示",
            font=FONT_BODY, fg=COLOR_TEXT_MUTED, bg=COLOR_BG_APP,
            justify="center",
        )
        self.history_empty_label.pack(pady=(60, 0))

        # 存储历史记录（内存中，任务完成后追加）
        self.history_records: list[dict] = []

    def _add_history_record(self, record: dict):
        """任务完成后追加一条历史记录并刷新列表。"""
        self.history_records.insert(0, record)
        self._refresh_history_list()

    def _refresh_history_list(self):
        """重建历史卡片列表。"""
        # 清空现有内容（保留 empty_label 引用）
        for child in self.history_list_frame.winfo_children():
            child.destroy()

        if not self.history_records:
            self.history_empty_label = tk.Label(
                self.history_list_frame,
                text="暂无历史记录\n完成一次生成后，任务记录将在此显示",
                font=FONT_BODY, fg=COLOR_TEXT_MUTED, bg=COLOR_BG_APP,
                justify="center",
            )
            self.history_empty_label.pack(pady=(60, 0))
            return

        for record in self.history_records:
            self._build_history_card(self.history_list_frame, record)

    def _build_history_card(self, parent: tk.Frame, record: dict):
        """构建单条历史任务卡片。"""
        card = tk.Frame(
            parent, bg=COLOR_CARD, padx=20, pady=16,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
        )
        card.pack(fill=tk.X, pady=6)

        # 标题行：状态 + 文件名
        header = tk.Frame(card, bg=COLOR_CARD)
        header.pack(fill=tk.X)
        status_icon = "✓" if record.get("succeeded") else "✗"
        status_color = COLOR_SUCCESS if record.get("succeeded") else COLOR_DANGER
        tk.Label(
            header, text=status_icon, font=FONT_BODY_BOLD,
            fg=status_color, bg=COLOR_CARD,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(
            header, text=record.get("title", "未命名任务"),
            font=FONT_BODY_BOLD, fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD,
            anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            header, text=record.get("timestamp", ""),
            font=FONT_TINY, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD,
        ).pack(side=tk.RIGHT)

        # 5 指标看板（2×2 + 总计）
        metrics_frame = tk.Frame(card, bg=COLOR_CARD)
        metrics_frame.pack(fill=tk.X, pady=(10, 0))
        metrics_frame.grid_columnconfigure(0, weight=1, uniform="m")
        metrics_frame.grid_columnconfigure(1, weight=1, uniform="m")
        metrics_frame.grid_columnconfigure(2, weight=1, uniform="m")

        metrics = [
            ("程序处理", record.get("program_seconds", 0)),
            ("抓取/读取", record.get("fetch_seconds", 0)),
            ("总结", record.get("generation_seconds", 0)),
            ("人工等待", record.get("wait_seconds", 0)),
            ("总计", record.get("total_seconds", 0)),
            ("文件数", record.get("file_count", 0)),
        ]
        for idx, (label, value) in enumerate(metrics):
            row, col = divmod(idx, 3)
            cell = tk.Frame(metrics_frame, bg=COLOR_CARD)
            cell.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            tk.Label(
                cell, text=label, font=FONT_TINY,
                fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w",
            ).pack(fill=tk.X)
            tk.Label(
                cell, text=f"{value:.1f}s" if isinstance(value, float) else str(value),
                font=FONT_BODY_BOLD, fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD,
                anchor="w",
            ).pack(fill=tk.X)

        # 文件列表 + 打开文件夹按钮
        files = record.get("saved_files", [])
        if files:
            files_row = tk.Frame(card, bg=COLOR_CARD)
            files_row.pack(fill=tk.X, pady=(10, 0))
            tk.Label(
                files_row, text="📁 " + "、".join(files),
                font=FONT_TINY, fg=COLOR_TEXT_SECONDARY, bg=COLOR_CARD,
                anchor="w", wraplength=500, justify="left",
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)

            output_dir = record.get("output_dir")
            if output_dir:
                tk.Button(
                    files_row, text="📂 打开文件夹",
                    command=lambda d=output_dir: self._open_in_explorer(d),
                    font=FONT_TINY, bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY,
                    activebackground=COLOR_HOVER,
                    activeforeground=COLOR_TEXT_PRIMARY,
                    relief=tk.FLAT, bd=0, cursor="hand2",
                    highlightthickness=1, highlightbackground=COLOR_BORDER,
                    padx=10, pady=4,
                ).pack(side=tk.RIGHT)

    def _open_in_explorer(self, dir_path: str):
        """在系统文件管理器中打开目录。"""
        import subprocess
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", dir_path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", dir_path])
            else:
                subprocess.Popen(["xdg-open", dir_path])
        except Exception:
            pass

    # ---------------- 画布响应式 ----------------

    def _draw_vibrant_gradient(self, w: int, h: int):
        """保留契约：极简风使用纯色底，不绘制多段渐变。"""
        self.bg_canvas.delete("gradient_bg")
        self.bg_canvas.create_rectangle(
            0, 0, w, h, fill=COLOR_BG_APP, outline="", tags="gradient_bg"
        )
        self.bg_canvas.tag_lower("gradient_bg")

    def _on_canvas_configure(self, event):
        if event is None:
            self.bg_canvas.update_idletasks()
            w = self.bg_canvas.winfo_width()
            h = self.bg_canvas.winfo_height()
        else:
            w = event.width
            h = event.height
        self.bg_canvas.itemconfig(self.canvas_window_id, width=w)
        self._draw_vibrant_gradient(w, h)

    def _on_content_configure(self, _event):
        """内容尺寸变化时，用 bbox('all') 精确更新 scrollregion。"""
        self.bg_canvas.update_idletasks()
        bb = self.bg_canvas.bbox("all")
        if bb:
            self.bg_canvas.configure(scrollregion=bb)

    def _bind_mousewheel(self):
        """绑定滚轮 + 触控板双指滚动，yview_moveto 实现像素级丝滑（兼容 Tk 8.6）。"""
        def on_wheel(event):
            try:
                raw = event.delta
                if raw == 0:
                    return
                px = max(1, min(40, abs(raw) // 4))
                direction = px if raw < 0 else -px
                self._smooth_scroll(direction)
            except tk.TclError:
                pass

        def on_pixelscroll(event):
            try:
                delta = getattr(event, "delta", 0)
                if delta == 0:
                    return
                self._smooth_scroll(-delta)
            except tk.TclError:
                pass

        self.bg_canvas.bind("<MouseWheel>", on_wheel)
        self.root.bind_all("<MouseWheel>", on_wheel, add="+")
        try:
            self.bg_canvas.bind("<PixelScroll>", on_pixelscroll)
            self.root.bind_all("<PixelScroll>", on_pixelscroll, add="+")
        except tk.TclError:
            pass
        for child in self.bg_canvas.winfo_children():
            try:
                child.bind("<MouseWheel>", on_wheel)
            except tk.TclError:
                pass

    def _smooth_scroll(self, delta_px: int):
        """像素级平滑滚动：通过 yview_moveto 精确设置视口位置（兼容 Tk 8.6）。"""
        self.bg_canvas.update_idletasks()
        bb = self.bg_canvas.bbox("all")
        if not bb:
            return
        total_h = bb[3] - bb[1]
        view_h = self.bg_canvas.winfo_height()
        if total_h <= view_h:
            return
        current_top = self.bg_canvas.canvasy(0)
        new_top = current_top + delta_px
        max_top = total_h - view_h
        new_top = max(0, min(max_top, new_top))
        self.bg_canvas.yview_moveto(new_top / total_h)

    # ---------------- 文件选取与拖拽 ----------------

    def _choose_summary_file(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="选取对话文件",
            filetypes=[
                ("Markdown 或文本", "*.md *.txt"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self._select_summary_file(Path(path))

    def _select_summary_file(self, selected_path: Path):
        self.selected_summary_file = Path(selected_path).resolve()
        # 文件胶囊显示文件名 + 大小
        try:
            size = self.selected_summary_file.stat().st_size
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KiB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MiB"
            label = f"📄 {self.selected_summary_file.name} · {size_str} (UTF-8)"
        except OSError:
            label = f"📄 {self.selected_summary_file.name}"
        self.selected_file_name_var.set(label)
        self.selected_file_row.pack(fill=tk.X, pady=(0, 8))
        self._update_send_button_state()
        self._update_generate_button_state()

    def _configure_file_drop(self):
        if not _HAS_DND:
            return
        try:
            # 整个 Omnibox 作为拖拽响应区
            self._omnibox.drop_target_register(DND_FILES, DND_TEXT)
            self._omnibox.dnd_bind("<<DropEnter>>", self._on_file_drag_enter)
            self._omnibox.dnd_bind("<<DropLeave>>", self._on_file_drag_leave)
            self._omnibox.dnd_bind("<<Drop>>", self._on_file_drop)
        except (AttributeError, tk.TclError):
            pass

    def _set_file_drop_highlight(self, highlighted: bool):
        """拖拽高亮：Omnibox 描边变蓝 + 背景淡化。"""
        if not hasattr(self, "_omnibox"):
            return
        if isinstance(self._omnibox, GlassCapsulePanel):
            self._omnibox.set_drop_highlight(highlighted)
            return
        self._omnibox.config(
            bg=COLOR_DRAG_HIGHLIGHT if highlighted else COLOR_OMNIBOX_BG,
            highlightbackground=COLOR_ACCENT_BLUE if highlighted else COLOR_BORDER,
            highlightthickness=2 if highlighted else 1,
        )

    def _on_file_drag_enter(self, event):
        self._set_file_drop_highlight(True)

    def _on_file_drag_leave(self, _event):
        self._set_file_drop_highlight(False)

    def _on_file_drop(self, event):
        self._set_file_drop_highlight(False)
        try:
            files = self.root.tk.splitlist(event.data)
        except AttributeError:
            files = (event.data,)
        if files:
            dropped = str(files[0]).strip()
            candidate = Path(dropped)
            if candidate.is_file():
                self._select_summary_file(candidate)
            elif dropped.startswith(("http://", "https://")):
                self.capsule_entry.set_text(dropped)
                self._on_url_changed()
            else:
                messagebox.showwarning("提示", "请拖入对话文件或有效的分享链接。")
        return getattr(event, "action", "copy")

    def _clear_summary_file(self):
        self.selected_summary_file = None
        self.selected_file_name_var.set("")
        self.selected_file_row.pack_forget()
        self._update_send_button_state()
        self._update_generate_button_state()

    # ---------------- 模式与登录切换 ----------------

    def _on_mode_toggled(self, _card=None):
        self._update_generate_button_state()

    def _on_auth_toggled(self, selected_card):
        if selected_card == self.card_no_login:
            self.card_need_login.set_checked(False)
        else:
            self.card_no_login.set_checked(False)
        self._update_generate_button_state()

    # ---------------- 输入锁定 ----------------

    def _set_inputs_locked(self, locked: bool):
        self.capsule_entry.set_locked(locked)
        self.card_raw.set_disabled(locked)
        self.card_normal.set_disabled(locked)
        self.card_simple.set_disabled(locked)
        self.card_detailed.set_disabled(locked)
        self.card_no_login.set_disabled(locked)
        self.card_need_login.set_disabled(locked)
        self.file_select_button.config(
            state="disabled" if locked else "normal",
            cursor="arrow" if locked else "hand2",
        )
        self.clear_file_button.config(
            state="disabled" if locked else "normal",
            cursor="arrow" if locked else "hand2",
        )
        # 设置按钮始终可用（测试契约 test_generation_lock_keeps_settings_button_enabled）
        try:
            self.api_key_button.config(state="normal", cursor="hand2")
        except tk.TclError:
            # tk.Frame 不支持 state 选项，仅设置 cursor
            self.api_key_button.config(cursor="hand2")

    # ---------------- URL 变更检测 ----------------

    def _on_url_changed(self):
        """URL 变更：发送按钮状态 + 私有链接检测 + 登录策略自动调整。"""
        if hasattr(self, "_update_send_button_state"):
            self._update_send_button_state()
        url = self.capsule_entry.get_text()
        try:
            host = urlparse(url).netloc.lower()
            path = urlparse(url).path.lower()
        except Exception:
            host, path = "", ""
        is_private = (
            ("chatgpt.com" in host or "chat.openai.com" in host)
            and "/c/" in path
        ) or (
            "chat.deepseek.com" in host and "/a/chat/s/" in path
        )
        self._url_is_private = is_private
        if is_private and hasattr(self, "card_no_login"):
            self.card_need_login.set_checked(False)
            self.card_no_login.set_checked(True)
            self.status_var.set("账号内对话链接，将复用已保存的登录状态。")
        self._update_generate_button_state()

    # ---------------- 按钮状态 ----------------

    def _update_generate_button_state(self):
        if self.is_running:
            self.btn_generate.set_enabled(False)
            self.btn_direct.set_enabled(False)
            return
        has_mode = any([
            self.card_raw.checked, self.card_normal.checked,
            self.card_simple.checked, self.card_detailed.checked
        ])
        has_auth = self.card_no_login.checked or self.card_need_login.checked
        # 按钮始终可点击（URL/文件校验在 _on_start_generate 中拦截）
        self.btn_generate.set_enabled(True)
        if hasattr(self, "_update_send_button_state"):
            self._update_send_button_state()

        has_summary_mode = any([
            self.card_normal.checked,
            self.card_simple.checked,
            self.card_detailed.checked
        ])
        self.btn_direct.set_enabled(bool(
            self.selected_summary_file is not None and has_summary_mode
        ))

    # ---------------- 完成徽章 ----------------

    def _show_completed_badge(self, duration_sec: int = 5):
        self.done_badge.pack(anchor="w", pady=(8, 0))
        self.root.after(
            duration_sec * 1000,
            lambda: self.done_badge.pack_forget()
        )

    # ---------------- 开始生成 / 直接总结 ----------------

    def _on_start_generate(self):
        url = self.capsule_entry.get_text()
        if not url:
            messagebox.showwarning("提示", "请输入有效的 AI 分享链接。")
            return

        need_login = self.card_need_login.checked
        modes = {
            "raw": self.card_raw.checked,
            "normal": self.card_normal.checked,
            "simple": self.card_simple.checked,
            "detailed": self.card_detailed.checked,
        }

        if not any(modes.values()):
            messagebox.showwarning("提示", "请至少勾选一个生成模式。")
            return

        api_keys: dict[str, str] = {}
        needs_summary = any(
            modes.get(name) for name in ("normal", "simple", "detailed")
        )
        if needs_summary:
            try:
                api_keys = self.credential_store.load_api_keys()
            except CredentialStoreError:
                self._show_api_key_settings(require_key=True)
                return
            if not api_keys:
                self._show_api_key_settings(require_key=True)
                return

        api_keys = dict(api_keys)
        current_settings = getattr(self, "app_settings", default_app_settings())
        settings = AppSettings(
            runtime_data_dir=Path(current_settings.runtime_data_dir),
            default_results_dir=(
                Path(current_settings.default_results_dir)
                if current_settings.default_results_dir is not None
                else None
            ),
        )
        output_target = _prompt_output_target(
            getattr(self, "root", None), modes, settings,
        )
        if output_target is None:
            return
        save_dir_path, output_filename = output_target

        self.is_running = True
        self.done_badge.pack_forget()
        self._set_inputs_locked(True)
        self._update_generate_button_state()
        self.progress_bar.reset()
        self.progress_bar.set_progress(0.06)
        self.status_var.set("正在启动后台引擎...")
        self.percent_var.set("6%")

        def _safe_run(*args, **kwargs):
            try:
                self._run_generation_task(*args, **kwargs)
            except Exception as e:
                import traceback
                err_detail = traceback.format_exc()
                print(f"[Generation] FATAL: {e}\n{err_detail}", flush=True)
                self.root.after(0, lambda: [
                    self.status_var.set(f"❌ 线程崩溃: {e}"),
                    self.percent_var.set("0%"),
                    messagebox.showerror("生成线程崩溃", f"{e}\n\n{err_detail}")
                ])

        thread = threading.Thread(
            target=_safe_run,
            args=(
                url, need_login, modes, save_dir_path,
                output_filename, api_keys, settings,
            ),
            daemon=True
        )
        thread.start()

    def _on_direct_summary(self):
        source_path = getattr(self, "selected_summary_file", None)
        if source_path is None:
            messagebox.showwarning("提示", "请先选取要直接总结的对话文件。")
            return

        modes = {
            "raw": False,
            "normal": self.card_normal.checked,
            "simple": self.card_simple.checked,
            "detailed": self.card_detailed.checked,
        }
        if not any(modes.values()):
            messagebox.showwarning(
                "提示", "请至少勾选普通版、极简版或细节版之一。"
            )
            return

        try:
            _load_direct_summary_file(source_path)
            api_keys = self.credential_store.load_api_keys()
        except CredentialStoreError:
            self._show_api_key_settings(require_key=True)
            return
        except Exception as error:
            messagebox.showerror("无法读取文件", str(error))
            return
        if not api_keys:
            self._show_api_key_settings(require_key=True)
            return

        current_settings = getattr(self, "app_settings", default_app_settings())
        settings = AppSettings(
            runtime_data_dir=Path(current_settings.runtime_data_dir),
            default_results_dir=(
                Path(current_settings.default_results_dir)
                if current_settings.default_results_dir is not None
                else None
            ),
        )
        output_target = _prompt_output_target(
            getattr(self, "root", None), modes, settings,
            suggested_name=_direct_summary_output_filename(source_path, modes),
        )
        if output_target is None:
            return
        save_dir_path, output_filename = output_target

        self.is_running = True
        self.done_badge.pack_forget()
        self._set_inputs_locked(True)
        self._update_generate_button_state()
        self.progress_bar.reset()
        self.progress_bar.set_progress(0.06)
        self.status_var.set("正在读取所选对话文件...")
        self.percent_var.set("6%")

        threading.Thread(
            target=self._run_generation_task,
            args=(
                "", False, modes, save_dir_path,
                output_filename, api_keys, settings, Path(source_path),
            ),
            daemon=True
        ).start()

    # ---------------- 登录确认弹窗 ----------------

    def _show_login_dialog(
        self, loop: asyncio.AbstractEventLoop, login_event: asyncio.Event
    ):
        dialog = tk.Toplevel(self.root)
        dialog.title("授权登录确认")
        dialog.geometry("480x230")
        dialog.resizable(False, False)
        dialog.configure(bg=COLOR_BG_APP)
        dialog.transient(self.root)
        dialog.grab_set()

        x = self.root.winfo_x() + (self.root.winfo_width() - 480) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 230) // 2
        dialog.geometry(f"+{x}+{y}")

        content = tk.Frame(dialog, bg=COLOR_BG_APP, padx=28, pady=22)
        content.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            content, text="⚠️ 在生成结束前请勿关闭浏览器！",
            font=FONT_H2, fg=COLOR_DANGER, bg=COLOR_BG_APP, anchor="w"
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(
            content,
            text=(
                "系统已为您打开浏览器窗口。\n"
                "请在弹出的浏览器中登录您的 AI 账号，"
                "登录成功后点击下方按钮继续生成。"
            ),
            font=FONT_BODY, fg=COLOR_TEXT_SECONDARY, bg=COLOR_BG_APP,
            justify=tk.LEFT, anchor="w"
        ).pack(anchor="w", pady=(0, 16))

        def on_login_done():
            loop.call_soon_threadsafe(login_event.set)
            dialog.destroy()

        FlatButton(
            content, text="已登录完毕，继续生成",
            command=on_login_done,
            variant="primary", width=200, height=40,
            bg_parent=COLOR_BG_APP
        ).pack(anchor="center")

    # ---------------- 主题选择弹窗 ----------------

    def _show_summary_topic_dialog(self, available_topics, on_done):
        dialog = tk.Toplevel(self.root)
        dialog.title("选择重点主题")
        dialog.resizable(False, False)
        dialog.configure(bg=COLOR_BG_APP)
        dialog.transient(self.root)
        dialog.grab_set()

        height = min(650, 270 + 78 * min(len(available_topics), 5))
        width = 610
        x = self.root.winfo_x() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - height) // 2
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        content = tk.Frame(dialog, bg=COLOR_BG_APP, padx=28, pady=22)
        content.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            content, text="主题已经分好，请选择需要详细展示的主题",
            font=FONT_H2, fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP, anchor="w"
        ).pack(anchor="w")
        tk.Label(
            content,
            text=(
                "所有主题摘要都会完整保留；勾选只表示该主题更重要，"
                "并在摘要后展开它的关键记忆和相关结构化记录。"
            ),
            font=FONT_SMALL, fg=COLOR_TEXT_SECONDARY, bg=COLOR_BG_APP,
            wraplength=550, justify=tk.LEFT, anchor="w"
        ).pack(anchor="w", pady=(5, 14))

        choices_shell = tk.Frame(content, bg=COLOR_BG_APP)
        choices_shell.pack(fill=tk.BOTH, expand=True)
        choices_canvas = tk.Canvas(
            choices_shell, bg=COLOR_BG_APP, highlightthickness=0,
            height=min(390, max(90, 76 * len(available_topics)))
        )
        choices_scrollbar = ttk.Scrollbar(
            choices_shell, orient=tk.VERTICAL,
            command=choices_canvas.yview
        )
        choices_canvas.configure(yscrollcommand=choices_scrollbar.set)
        choices_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        choices_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        choices = tk.Frame(choices_canvas, bg=COLOR_BG_APP)
        choices_window = choices_canvas.create_window(
            0, 0, window=choices, anchor="nw"
        )
        choices.bind(
            "<Configure>",
            lambda _e: choices_canvas.configure(
                scrollregion=choices_canvas.bbox("all")
            )
        )
        choices_canvas.bind(
            "<Configure>",
            lambda e: choices_canvas.itemconfig(choices_window, width=e.width)
        )
        dialog.bind(
            "<MouseWheel>",
            lambda e: choices_canvas.yview_scroll(
                -int(e.delta / 120), "units"
            )
        )

        variables = {}
        for index, topic in enumerate(available_topics, start=1):
            topic_id = topic["topic_id"]
            row = tk.Frame(
                choices, bg=COLOR_CARD,
                highlightthickness=1, highlightbackground=COLOR_BORDER,
                padx=12, pady=8
            )
            row.pack(fill=tk.X, pady=4)
            variable = tk.BooleanVar(master=dialog, value=False)
            variables[topic_id] = variable
            tk.Checkbutton(
                row, text=f"{index}. {topic['title']}",
                variable=variable,
                font=FONT_BODY_BOLD, fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD,
                activebackground=COLOR_CARD, selectcolor=COLOR_ACCENT_BG,
                cursor="hand2", anchor="w"
            ).pack(fill=tk.X)
            tk.Label(
                row,
                text=str(topic.get("summary") or "该主题暂无摘要。")[:180],
                font=FONT_TINY, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD,
                anchor="w", justify=tk.LEFT, wraplength=500
            ).pack(fill=tk.X, padx=(24, 0), pady=(1, 0))

        tk.Label(
            content,
            text=(
                "未勾选主题不会消失；媒体与附件说明始终保留，"
                "详细版的细节记忆也始终保留。"
            ),
            font=FONT_TINY, fg=COLOR_ACCENT, bg=COLOR_BG_APP, anchor="w"
        ).pack(anchor="w", pady=(12, 8))

        completed = False

        def finish(use_checked: bool):
            nonlocal completed
            if completed:
                return
            completed = True
            selected = tuple(
                topic["topic_id"] for topic in available_topics
                if use_checked and variables[topic["topic_id"]].get()
            )
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()
            on_done(selected)

        button_row = tk.Frame(content, bg=COLOR_BG_APP)
        button_row.pack(fill=tk.X, pady=(2, 0))
        tk.Button(
            button_row, text="不额外展开", command=lambda: finish(False),
            font=FONT_SMALL, bg=COLOR_HOVER, fg=COLOR_TEXT_SECONDARY,
            activebackground=COLOR_BORDER, relief=tk.FLAT,
            padx=16, pady=7, cursor="hand2"
        ).pack(side=tk.LEFT)
        tk.Button(
            button_row, text="确认重点主题并继续",
            command=lambda: finish(True),
            font=FONT_BODY_BOLD, bg=COLOR_TEXT_PRIMARY, fg="#FFFFFF",
            activebackground="#262626", activeforeground="#FFFFFF",
            relief=tk.FLAT, padx=18, pady=8, cursor="hand2"
        ).pack(side=tk.RIGHT)

        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        dialog.bind("<Escape>", lambda _e: finish(False))
        dialog.bind("<Return>", lambda _e: finish(True))

    # ---------------- 主题选择调度 ----------------

    def _select_summary_topics(
        self,
        result,
        update_progress,
        run_log: GenerationRunLog,
    ) -> tuple[tuple[str, ...], float]:
        from scripts.gemini_summarizer import available_summary_topics

        available = available_summary_topics(result)
        if not available:
            update_progress(
                0.80,
                "主题分类完成，本次没有需要单独选择的历史主题。",
            )
            return (), 0.0

        update_progress(
            0.80, "主题分类完成，请在弹出的窗口中勾选重要主题...",
        )
        run_log.event("topic_selection_started", topic_count=len(available))
        selection_ready = threading.Event()
        selection_holder = {"topics": ()}

        def on_selected(topics):
            selection_holder["topics"] = tuple(topics)
            selection_ready.set()

        def show_dialog():
            try:
                self._show_summary_topic_dialog(available, on_selected)
            except Exception:
                on_selected(())

        self.root.after(0, show_dialog)
        selection_started = time.perf_counter()
        selection_ready.wait()
        wait_seconds = time.perf_counter() - selection_started
        selected = selection_holder["topics"]
        run_log.event(
            "topic_selection_completed",
            selected_count=len(selected),
            wait_seconds=round(wait_seconds, 3),
        )
        update_progress(
            0.84,
            (
                f"已选择 {len(selected)} 个重点主题，正在写入结果..."
                if selected
                else "未选择重点主题，正在写入完整主题摘要..."
            ),
        )
        return selected, wait_seconds

    # ---------------- 后台流水线 ----------------

    def _run_generation_task(
        self,
        url: str,
        need_login: bool,
        modes: dict[str, bool],
        save_dir: Path,
        output_filename: str,
        api_keys: dict[str, str],
        app_settings: AppSettings,
        source_path: Path | None = None,
    ):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        task_started = time.perf_counter()
        run_succeeded = False
        direct_summary = source_path is not None
        if direct_summary:
            source_path = Path(source_path).resolve()
            metadata = {
                "input_file_name": source_path.name,
                "input_file_fingerprint": hashlib.sha256(
                    str(source_path).encode("utf-8")
                ).hexdigest()[:12],
                "direct_summary": True,
            }
        else:
            metadata = {
                "link_host": urlparse(url).netloc.lower(),
                "link_fingerprint": hashlib.sha256(
                    url.encode("utf-8")
                ).hexdigest()[:12],
                "need_login": need_login,
            }
        metadata.update({
            "modes": [key for key, enabled in modes.items() if enabled],
            "output_filename": output_filename,
        })
        run_log = GenerationRunLog(
            app_settings.log_dir, metadata=metadata,
        )

        login_event = asyncio.Event()

        def update_progress(val: float, msg: str):
            run_log.event(
                "progress", msg,
                ui_progress=round(float(val), 3),
            )
            percent_str = f"{int(val * 100)}%"
            self.root.after(0, lambda: [
                self.progress_bar.set_progress(val),
                self.status_var.set(msg),
                self.percent_var.set(percent_str)
            ])

        try:
            fetch_started = time.perf_counter()
            source_name = None
            source_dir = None
            if direct_summary:
                update_progress(0.15, "正在读取所选对话文件...")
                messages = _load_direct_summary_file(source_path)
                fetch_seconds = time.perf_counter() - fetch_started
                fetch_active_seconds = fetch_seconds
                login_wait_seconds = 0.0
                source_name = source_path.name
                source_dir = source_path.parent
                run_log.event(
                    "file_loaded", "本地对话文件读取完成",
                    elapsed_seconds=round(fetch_seconds, 3),
                    message_count=len(messages),
                )
                update_progress(
                    0.42,
                    f"成功读取 {len(messages)} 条对话消息，正在准备总结...",
                )
            else:
                update_progress(0.15, "正在加载分享页并解析动态列表...")
                image_output_dir = build_image_asset_directory(
                    save_dir, output_filename,
                )
                document_output_dir = build_document_asset_directory(
                    save_dir, output_filename,
                )
                fetch_res = loop.run_until_complete(
                    fetch_chat_pipeline(
                        url=url,
                        need_login=need_login,
                        login_ready_event=login_event,
                        login_required_callback=(
                            lambda: self.root.after(
                                0,
                                lambda: self._show_login_dialog(loop, login_event)
                            )
                        ),
                        logger=lambda m: update_progress(0.28, m),
                        image_output_dir=image_output_dir,
                        image_reference_base=save_dir,
                        document_output_dir=document_output_dir,
                        document_reference_base=save_dir,
                        browser_profile_root=app_settings.browser_profile_dir,
                        debug_html_file=app_settings.debug_html_file,
                    )
                )
                fetch_seconds = time.perf_counter() - fetch_started
                login_wait_seconds = max(0.0, fetch_res.user_wait_seconds)
                fetch_active_seconds = max(
                    0.0, fetch_seconds - login_wait_seconds
                )
                run_log.event(
                    "fetch_completed" if not fetch_res.error else "fetch_failed",
                    fetch_res.error or "抓取完成",
                    elapsed_seconds=round(fetch_seconds, 3),
                    active_seconds=round(fetch_active_seconds, 3),
                    login_wait_seconds=round(login_wait_seconds, 3),
                    message_count=len(fetch_res.messages),
                    downloaded_images=len(fetch_res.image_map),
                )
                for warning in fetch_res.warnings:
                    run_log.event("fetch_warning", warning)
                if fetch_res.error or not fetch_res.messages:
                    err = fetch_res.error or "未能提取到有效对话内容。"
                    self.root.after(
                        0, lambda: messagebox.showerror("生成失败", err)
                    )
                    return

                messages = fetch_res.messages
                login_wait_detail = (
                    f"，等待登录 {login_wait_seconds:.1f} 秒"
                    if login_wait_seconds >= 0.1 else ""
                )
                update_progress(
                    0.42,
                    f"成功提取 {len(messages)} 条对话交互"
                    f"（实际抓取 {fetch_active_seconds:.1f} 秒"
                    f"{login_wait_detail}），正在按要求生成文件...",
                )

            selection_wait_seconds = 0.0

            def select_summary_topics(result):
                nonlocal selection_wait_seconds
                selected, wait_seconds = self._select_summary_topics(
                    result, update_progress, run_log
                )
                selection_wait_seconds += wait_seconds
                return selected

            update_progress(0.56, "正在连接总结后端并准备生成文件...")
            generation_started = time.perf_counter()
            bundle = generate_output_bundle(
                messages=messages,
                modes=modes,
                save_dir=save_dir,
                output_filename=output_filename,
                project_dir=app_settings.runtime_data_dir,
                api_keys=api_keys,
                result_cache_dir=app_settings.summary_cache_dir,
                source_platform=(
                    "deepseek"
                    if (
                        not direct_summary
                        and urlparse(url).hostname == "chat.deepseek.com"
                    )
                    else None
                ),
                source_name=source_name,
                source_dir=source_dir,
                topic_selector=(
                    select_summary_topics
                    if modes.get("normal") or modes.get("detailed")
                    else None
                ),
                progress=lambda message: update_progress(0.72, message),
            )
            generation_seconds = (
                time.perf_counter() - generation_started - selection_wait_seconds
            )
            saved_files = [path.name for path in bundle.saved_files]
            processing = (
                (bundle.summary_result or {}).get("processing", {})
                if isinstance(bundle.summary_result, dict) else {}
            )
            for warning in processing.get("warnings", []):
                run_log.event("generation_warning", warning)
            run_log.event(
                "generation_completed",
                fetch_seconds=round(fetch_seconds, 3),
                fetch_active_seconds=round(fetch_active_seconds, 3),
                login_wait_seconds=round(login_wait_seconds, 3),
                generation_seconds=round(generation_seconds, 3),
                selection_wait_seconds=round(selection_wait_seconds, 3),
                cache_hit=processing.get("cache_hit"),
                stage_timings=processing.get("timings_seconds", {}),
                saved_files=saved_files,
            )

            file_list_str = "、".join(saved_files)
            total_seconds = time.perf_counter() - task_started
            program_seconds = fetch_active_seconds + generation_seconds
            wait_seconds = login_wait_seconds + selection_wait_seconds
            wait_parts = []
            if login_wait_seconds >= 0.1:
                wait_parts.append(f"登录 {login_wait_seconds:.1f}")
            if selection_wait_seconds >= 0.1:
                wait_parts.append(f"选题 {selection_wait_seconds:.1f}")
            wait_text = (
                f"；人工等待 {wait_seconds:.1f} 秒"
                f"（{'/'.join(wait_parts)}）"
                if wait_parts else ""
            )
            update_progress(
                1.0,
                (
                    f"{'直接总结' if direct_summary else '所有任务生成'}完成"
                    f"（程序处理 {program_seconds:.1f} 秒："
                    f"{'读取' if direct_summary else '抓取'} "
                    f"{fetch_active_seconds:.1f}/"
                    f"总结 {generation_seconds:.1f}"
                    f"{wait_text}；总计 {total_seconds:.1f} 秒）："
                    f"{file_list_str}"
                ) if file_list_str else "所有任务生成完成！",
            )
            self.root.after(0, lambda: self._show_completed_badge(5))
            # 追加历史记录
            from datetime import datetime as _dt
            history_record = {
                "title": (
                    Path(self._selected_summary_file).name
                    if direct_summary and self._selected_summary_file
                    else (source_name or "链接总结")
                ),
                "timestamp": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                "succeeded": True,
                "program_seconds": program_seconds,
                "fetch_seconds": fetch_active_seconds,
                "generation_seconds": generation_seconds,
                "wait_seconds": wait_seconds,
                "total_seconds": total_seconds,
                "file_count": len(saved_files),
                "saved_files": saved_files,
                "output_dir": str(source_dir) if source_dir else "",
            }
            self.root.after(
                0, lambda r=history_record: self._add_history_record(r)
            )
            run_succeeded = True

        except Exception as e:
            err_msg = "处理失败，请检查网络、额度和模型配置。"
            try:
                from scripts.gemini_summarizer import safe_error_message
                err_msg = safe_error_message(e, tuple(api_keys.values()))
            except Exception:
                pass
            run_log.event(
                "run_error", err_msg, error_type=type(e).__name__,
            )
            update_progress(0.0, f"❌ 处理发生错误: {err_msg}")
            self.root.after(
                0,
                lambda: messagebox.showerror("处理失败", f"生成失败：{err_msg}")
            )

        finally:
            run_log.event(
                "run_finished",
                succeeded=run_succeeded,
                total_seconds=round(time.perf_counter() - task_started, 3),
            )
            run_log.close()
            loop.close()
            self.root.after(0, self._on_task_finished)

    def _on_task_finished(self):
        self.is_running = False
        self._set_inputs_locked(False)
        self._update_generate_button_state()

    # ---------------- 设置弹窗（保留旧版 API KEY 兼容入口） ----------------

    def _show_legacy_api_key_settings(self, require_key: bool = False):
        self._show_settings(initial_page="api", require_key=require_key)

    def _show_api_key_settings(self, require_key: bool = False):
        self._show_settings(initial_page="api", require_key=require_key)

    def _show_settings(
        self,
        initial_page: str = "api",
        require_key: bool = False,
    ):
        """切换到内嵌设置页（不再弹窗）。"""
        settings_page = self.page_frames[3]
        # 兼容旧契约：_settings_dialog / _api_key_dialog 指向设置页
        self._settings_dialog = settings_page
        self._api_key_dialog = settings_page
        if hasattr(settings_page, "show_page"):
            settings_page.show_page(
                "api" if require_key else initial_page
            )
        if require_key and hasattr(settings_page, "show_notice"):
            settings_page.show_notice("请先配置 API KEY")
        self._show_page(3)

    def _build_settings_section(self):
        """设置页：内嵌在主内容区（API KEY + 数据位置）。"""
        page = self.page_frames[3]
        page.configure(bg=COLOR_BG_APP)

        section = tk.Frame(page, bg=COLOR_BG_APP)
        section.pack(fill=tk.BOTH, expand=True, padx=80, pady=(24, 24))

        tk.Label(
            section, text="设置", font=FONT_TITLE,
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP, anchor="w",
        ).pack(fill=tk.X, pady=(0, 16))

        panel = tk.Frame(
            section, bg=COLOR_CARD, padx=24, pady=18,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
        )
        panel.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(panel)
        notebook.pack(fill=tk.BOTH, expand=True)
        api_page = tk.Frame(notebook, bg=COLOR_CARD, padx=18, pady=14)
        data_page = tk.Frame(notebook, bg=COLOR_CARD, padx=18, pady=14)
        notebook.add(api_page, text="API KEY 设置")
        notebook.add(data_page, text="数据保存位置")

        try:
            existing_keys = self.credential_store.load_api_keys()
            provider_order = list(self.credential_store.load_provider_order())
            key_load_error = None
        except CredentialStoreError as error:
            existing_keys = {}
            provider_order = ["gemini", "siliconflow", "deepseek"]
            key_load_error = str(error)

        notice_var = tk.StringVar(value="")
        notice_slot = tk.Frame(api_page, bg=COLOR_CARD, height=42)
        notice_slot.pack(fill=tk.X, pady=(0, 8))
        notice_label = tk.Label(
            notice_slot, textvariable=notice_var,
            font=FONT_SMALL, fg=COLOR_DANGER, bg=COLOR_CARD, anchor="w"
        )
        notice_label.pack(anchor="w")

        def show_notice(message: str, duration_ms: int = 3500):
            notice_var.set(message)
            if duration_ms > 0:
                self.root.after(duration_ms, lambda: notice_var.set(""))

        page.show_notice = show_notice

        # ----- API KEY 行 -----
        providers = {
            "gemini": "Google Gemini",
            "siliconflow": "SiliconFlow",
            "deepseek": "DeepSeek",
        }

        ordered_providers = [
            provider for provider in provider_order
            if provider in providers
        ]
        ordered_providers.extend(
            provider for provider in providers
            if provider not in ordered_providers
        )

        api_rows_frame = tk.Frame(api_page, bg=COLOR_CARD)
        api_rows_frame.pack(fill=tk.X, pady=(0, 8))

        api_key_vars: dict[str, tk.StringVar] = {}
        api_row_refs: list[tk.Frame] = []
        drag_state = {"active": False, "src": -1, "tgt": -1}

        def _render_api_rows():
            for row in api_row_refs:
                row.destroy()
            api_row_refs.clear()
            api_key_vars.clear()

            for idx, provider in enumerate(ordered_providers):
                row = tk.Frame(api_rows_frame, bg=COLOR_CARD)
                row.pack(fill=tk.X, pady=3)
                api_row_refs.append(row)

                handle = tk.Label(
                    row, text="\u2630", font=FONT_BODY,
                    fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, cursor="hand2",
                    padx=8,
                )
                handle.pack(side=tk.LEFT)
                handle.bind(
                    "<ButtonPress-1>",
                    lambda event, i=idx: _drag_start(event, i),
                )
                handle.bind(
                    "<B1-Motion>", lambda event: _drag_motion(event)
                )
                handle.bind(
                    "<ButtonRelease-1>",
                    lambda event: _drag_end(event),
                )
                HoverTooltip(handle, "拖动以调整兜底顺序")

                tk.Label(
                    row, text=providers[provider],
                    font=FONT_BODY_BOLD, fg=COLOR_TEXT_PRIMARY,
                    bg=COLOR_CARD, width=14, anchor="w",
                ).pack(side=tk.LEFT, padx=(0, 6))

                entry_var = tk.StringVar(
                    value=existing_keys.get(provider, "")
                )
                entry = tk.Entry(
                    row, textvariable=entry_var, show="*",
                    font=FONT_BODY, fg=COLOR_TEXT_PRIMARY,
                    bg=COLOR_BG_APP, relief=tk.FLAT, width=24,
                    insertbackground=COLOR_TEXT_PRIMARY,
                    highlightthickness=1,
                    highlightbackground=COLOR_BORDER,
                    highlightcolor=COLOR_BORDER_FOCUS,
                )
                entry.pack(
                    side=tk.LEFT, fill=tk.X, expand=True,
                    ipady=4, padx=2,
                )
                api_key_vars[provider] = entry_var

        def _drag_start(_event, idx):
            drag_state["active"] = True
            drag_state["src"] = idx
            drag_state["tgt"] = idx

        def _drag_motion(event):
            if not drag_state["active"]:
                return
            mouse_y = event.y_root
            for idx, row in enumerate(api_row_refs):
                top = row.winfo_rooty()
                bottom = top + row.winfo_reqheight()
                if top <= mouse_y <= bottom:
                    drag_state["tgt"] = idx
                    return

        def _drag_end(_event):
            if not drag_state["active"]:
                return
            src = drag_state["src"]
            tgt = drag_state["tgt"]
            if (
                0 <= src < len(ordered_providers)
                and 0 <= tgt < len(ordered_providers)
                and src != tgt
            ):
                item = ordered_providers.pop(src)
                ordered_providers.insert(tgt, item)
                _render_api_rows()
            drag_state["active"] = False
            drag_state["src"] = -1
            drag_state["tgt"] = -1

        def _save_api_keys():
            keys = {
                provider: var.get() for provider, var in api_key_vars.items()
            }
            try:
                self.credential_store.save_api_keys(keys)
                self.credential_store.save_provider_order(ordered_providers)
                show_notice("已安全保存", 2000)
            except CredentialStoreError as error:
                show_notice(str(error), 5000)

        save_button = tk.Button(
            api_page, text="\U0001F512 安全保存", command=_save_api_keys,
            font=FONT_BODY_BOLD, bg=COLOR_TEXT_PRIMARY, fg="#FFFFFF",
            activebackground="#262626", activeforeground="#FFFFFF",
            relief=tk.FLAT, padx=18, pady=8, cursor="hand2",
        )
        save_button.pack(side=tk.RIGHT, pady=(8, 0))

        if key_load_error:
            show_notice(key_load_error, 5000)

        _render_api_rows()

        # ----- 数据保存位置页 -----
        runtime_var = tk.StringVar(
            value=str(self.app_settings.runtime_data_dir)
        )
        results_var = tk.StringVar(
            value=str(self.app_settings.default_results_dir or "")
        )

        def _pick_dir(var: tk.StringVar, title: str):
            initial = var.get().strip()
            try:
                initial_dir = (
                    initial if initial and Path(initial).exists() else None
                )
            except Exception:
                initial_dir = None
            new_dir = filedialog.askdirectory(
                title=title, initialdir=initial_dir,
            )
            if new_dir:
                var.set(new_dir)

        def _save_data_settings():
            try:
                runtime_value = runtime_var.get().strip()
                results_value = results_var.get().strip()
                if not runtime_value:
                    show_notice("运行数据目录不能为空", 4000)
                    return
                runtime_dir = Path(runtime_value)
                results_dir = (
                    Path(results_value) if results_value else None
                )
                new_settings = AppSettings(runtime_dir, results_dir)
                self.app_settings = self.settings_store.save(new_settings)
                runtime_var.set(str(self.app_settings.runtime_data_dir))
                results_var.set(
                    str(self.app_settings.default_results_dir or "")
                )
                show_notice("已保存数据位置", 2000)
            except SettingsStoreError as error:
                show_notice(str(error), 5000)
            except Exception:
                show_notice("保存失败，请检查目录权限", 4000)

        def _make_dir_row(parent, label, var, title, with_reset=False):
            row = tk.Frame(parent, bg=COLOR_CARD)
            row.pack(fill=tk.X, pady=6)
            tk.Label(
                row, text=label, font=FONT_BODY_BOLD,
                fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD,
                width=12, anchor="w",
            ).pack(side=tk.LEFT)
            entry = tk.Entry(
                row, textvariable=var, font=FONT_BODY,
                fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP,
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=COLOR_BORDER,
                highlightcolor=COLOR_BORDER_FOCUS,
            )
            entry.pack(
                side=tk.LEFT, fill=tk.X, expand=True, ipady=4, padx=4,
            )
            tk.Button(
                row, text="浏览", cursor="hand2",
                command=lambda: _pick_dir(var, title),
                font=FONT_SMALL, relief=tk.FLAT,
                bg=COLOR_HOVER, fg=COLOR_TEXT_PRIMARY,
                activebackground=COLOR_BORDER,
                padx=10, pady=4,
            ).pack(side=tk.LEFT, padx=2)
            if with_reset:
                tk.Button(
                    row, text="恢复默认", cursor="hand2",
                    command=lambda: var.set(
                        str(default_app_settings().runtime_data_dir)
                    ),
                    font=FONT_SMALL, relief=tk.FLAT,
                    bg=COLOR_HOVER, fg=COLOR_TEXT_PRIMARY,
                    activebackground=COLOR_BORDER,
                    padx=10, pady=4,
                ).pack(side=tk.LEFT, padx=2)
            tk.Button(
                row, text="清除", cursor="hand2",
                command=lambda: var.set(""),
                font=FONT_SMALL, relief=tk.FLAT,
                bg=COLOR_HOVER, fg=COLOR_TEXT_PRIMARY,
                activebackground=COLOR_BORDER,
                padx=10, pady=4,
            ).pack(side=tk.LEFT, padx=2)
            return row

        _make_dir_row(
            data_page, "运行数据目录", runtime_var,
            "选择运行数据目录", with_reset=True,
        )
        _make_dir_row(
            data_page, "结果默认目录", results_var,
            "选择结果默认目录",
        )

        tk.Button(
            data_page, text="保存", command=_save_data_settings,
            font=FONT_BODY_BOLD, bg=COLOR_TEXT_PRIMARY, fg="#FFFFFF",
            activebackground="#262626", activeforeground="#FFFFFF",
            relief=tk.FLAT, padx=18, pady=8, cursor="hand2",
        ).pack(side=tk.RIGHT, pady=(12, 0))

        # ----- 页面切换方法（兼容外部调用） -----
        def show_page(page_key: str):
            if page_key == "api":
                notebook.select(api_page)
            elif page_key == "data":
                notebook.select(data_page)

        page.show_page = show_page


def main() -> None:
    """启动 AI 记忆总结协同管理工具。"""
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    AIMemoryGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
