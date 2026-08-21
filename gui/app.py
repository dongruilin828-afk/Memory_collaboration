"""AI 记忆总结图形用户界面 (GUI) 主程序 - 灵动胶囊自适应全比例版。

优化亮点：
1. 右侧平滑胶囊滚动条：在内容超出或滚动时，右侧呈现极简现代胶囊滚动指示条，实时展示滚动位置，支持鼠标拖拽与滚轮同步；
2. 全比例自适应放大：彻底解决窗口放大时底部留白/粉色断层问题，使所有组件与卡片随窗口缩放等比例自适应伸展并充满视窗；
3. 文案规范：“不登录”卡片说明已移除“或公开分享页”；
4. 完好保留前期全部好评功能：晨曦极光渐变背景、胶囊输入与一键粘贴、四大多彩模式卡片、两大登录卡片、平滑渐变进度条与生成安全锁定。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import threading
import time
from pathlib import Path

# 确保无论从项目根目录还是 gui 目录运行，均能正确解析项目模块
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from scripts.project_paths import DEFAULT_EXPORT_FILE, PROJECT_ROOT
from gui.service import fetch_chat_pipeline, generate_output_bundle


# ==================== 颜色计算与渐变工具 ====================

def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    hex_str = hex_str.lstrip("#")
    if len(hex_str) == 3:
        hex_str = "".join([c * 2 for c in hex_str])
    return int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    return f"#{r:02x}{g:02x}{b:02x}"


def interpolate_color(color1: str, color2: str, factor: float) -> str:
    """计算两种颜色之间的插值颜色 (0.0 ~ 1.0)"""
    r1, g1, b1 = hex_to_rgb(color1)
    r2, g2, b2 = hex_to_rgb(color2)
    factor = max(0.0, min(1.0, factor))
    r = r1 + (r2 - r1) * factor
    g = g1 + (g2 - g1) * factor
    b = b1 + (b2 - b1) * factor
    return rgb_to_hex(int(r), int(g), int(b))


def draw_pill(canvas: tk.Canvas, x1, y1, x2, y2, radius=None, **kwargs):
    """在 Canvas 上绘制精细平滑的胶囊/超大圆角矩形 (Pill Shape)"""
    w = abs(x2 - x1)
    h = abs(y2 - y1)
    if radius is None:
        radius = min(w, h) / 2.0
    else:
        radius = min(radius, w / 2.0, h / 2.0)

    r = radius
    points = [
        x1 + r, y1,
        x1 + r, y1,
        x2 - r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


# ==================== 右侧现代胶囊滚动指示器 ====================

class CapsuleScrollbar(tk.Canvas):
    """现代极简胶囊滚动条（支持拖拽、指示与悬停动画）"""
    def __init__(
        self,
        master,
        target_canvas: tk.Canvas,
        width: int = 10,
        bg_parent: str = "#EEF2FF",
        thumb_color: str = "#94A3B8",
        thumb_hover: str = "#6366F1",
        **kwargs
    ):
        super().__init__(
            master,
            width=width,
            highlightthickness=0,
            bg=bg_parent,
            cursor="hand2",
            **kwargs
        )
        self.target_canvas = target_canvas
        self.bar_width = width
        self.bg_parent = bg_parent
        self.thumb_color = thumb_color
        self.thumb_hover = thumb_hover
        self.is_dragging = False
        self.top_fraction = 0.0
        self.bottom_fraction = 1.0

        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda e: self.redraw(hover=True))
        self.bind("<Leave>", lambda e: self.redraw(hover=False))
        self.bind("<Configure>", lambda e: self.redraw())

    def set_range(self, first: str, last: str):
        try:
            self.top_fraction = float(first)
            self.bottom_fraction = float(last)
            self.redraw()
        except Exception:
            pass

    def redraw(self, hover: bool = False):
        self.delete("all")
        w = self.winfo_width() or self.bar_width
        h = self.winfo_height()
        if h <= 20:
            return

        # 如果内容完全在视窗内无需滚动，保持极简隐形
        if (self.bottom_fraction - self.top_fraction) >= 0.999:
            return

        # 1. 绘制滑道底槽
        r = w / 2.0
        draw_pill(self, 2, 4, w - 2, h - 4, radius=r - 2, fill="#E2E8F0", outline="")

        # 2. 绘制滑块胶囊
        y1 = max(4, int(h * self.top_fraction))
        y2 = min(h - 4, max(y1 + 28, int(h * self.bottom_fraction)))
        col = self.thumb_hover if (self.is_dragging or hover) else self.thumb_color
        draw_pill(self, 1, y1, w - 1, y2, radius=r - 1, fill=col, outline="")

    def _on_click(self, event):
        h = self.winfo_height()
        if h <= 0:
            return
        self.is_dragging = True
        fraction = max(0.0, min(1.0, (event.y - 14) / float(h)))
        self.target_canvas.yview_moveto(fraction)
        self.redraw(hover=True)

    def _on_drag(self, event):
        h = self.winfo_height()
        if h <= 0:
            return
        fraction = max(0.0, min(1.0, (event.y - 14) / float(h)))
        self.target_canvas.yview_moveto(fraction)
        self.redraw(hover=True)

    def _on_release(self, event):
        self.is_dragging = False
        self.redraw(hover=False)


# ==================== 渐变胶囊按钮组件 ====================

class GradientPillButton(tk.Canvas):
    """支持渐变色、悬停光泽与状态锁定的胶囊按钮"""
    def __init__(
        self,
        master,
        text: str,
        command: callable = None,
        color_start: str = "#2563EB",
        color_end: str = "#7C3AED",
        hover_start: str = "#3B82F6",
        hover_end: str = "#8B5CF6",
        disabled_bg: str = "#CBD5E1",
        disabled_fg: str = "#64748B",
        width: int = 240,
        height: int = 48,
        font=("Microsoft YaHei", 12, "bold"),
        bg_parent: str = "#EEF2FF",
        **kwargs
    ):
        super().__init__(
            master,
            width=width,
            height=height,
            highlightthickness=0,
            bg=bg_parent,
            cursor="hand2",
            **kwargs
        )
        self.text = text
        self.command = command
        self.color_start = color_start
        self.color_end = color_end
        self.hover_start = hover_start
        self.hover_end = hover_end
        self.disabled_bg = disabled_bg
        self.disabled_fg = disabled_fg
        self.btn_width = width
        self.btn_height = height
        self.btn_font = font
        self.bg_parent = bg_parent

        self.is_hovered = False
        self.is_enabled = True

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Configure>", lambda e: self.redraw())
        self.redraw()

    def set_enabled(self, enabled: bool):
        self.is_enabled = enabled
        self.config(cursor="hand2" if enabled else "arrow")
        self.redraw()

    def _on_enter(self, event=None):
        if self.is_enabled:
            self.is_hovered = True
            self.redraw()

    def _on_leave(self, event=None):
        if self.is_enabled:
            self.is_hovered = False
            self.redraw()

    def _on_click(self, event=None):
        if self.is_enabled and self.command:
            self.command()

    def redraw(self):
        self.delete("all")
        w = self.winfo_width() or self.btn_width
        h = self.winfo_height() or self.btn_height
        r = h / 2.0

        if not self.is_enabled:
            draw_pill(self, 2, 2, w - 2, h - 2, radius=r - 2, fill=self.disabled_bg, outline="#94A3B8", width=1)
            self.create_text(
                w / 2, h / 2,
                text=self.text,
                font=self.btn_font,
                fill=self.disabled_fg
            )
            return

        c1 = self.hover_start if self.is_hovered else self.color_start
        c2 = self.hover_end if self.is_hovered else self.color_end

        steps = 36
        for i in range(steps):
            factor = i / float(steps - 1)
            band_color = interpolate_color(c1, c2, factor)
            x_start = 2 + (w - 4) * (i / steps)
            x_end = 2 + (w - 4) * ((i + 1) / steps)
            self.create_rectangle(x_start, 2, x_end, h - 2, fill=band_color, outline=band_color)

        draw_pill(self, 2, 2, w - 2, h - 2, radius=r - 2, fill="", outline="#FFFFFF", width=1.5)

        self.create_text(
            w / 2, h / 2 + 1,
            text=self.text,
            font=self.btn_font,
            fill="#1E1B4B" if self.is_hovered else "#312E81"
        )
        self.create_text(
            w / 2, h / 2,
            text=self.text,
            font=self.btn_font,
            fill="#FFFFFF"
        )


# ==================== 极美胶囊卡片选择组件 ====================

class CapsuleSelectCard(tk.Canvas):
    """完全圆滑的胶囊/大圆角主题卡片（全比例自适应响应）"""
    def __init__(
        self,
        master,
        title: str,
        subtitle: str,
        badge_text: str = "",
        is_radio: bool = False,
        initial_checked: bool = False,
        on_toggle: callable = None,
        theme_color: str = "#2563EB",
        theme_bg_light: str = "#EFF6FF",
        theme_border: str = "#93C5FD",
        width: int = 175,
        height: int = 94,
        radius: int = 20,
        bg_parent: str = "#EEF2FF",
        **kwargs
    ):
        super().__init__(
            master,
            width=width,
            height=height,
            bg=bg_parent,
            highlightthickness=0,
            cursor="hand2",
            **kwargs
        )
        self.title = title
        self.subtitle = subtitle
        self.badge_text = badge_text
        self.is_radio = is_radio
        self.checked = initial_checked
        self.on_toggle = on_toggle
        self.theme_color = theme_color
        self.theme_bg_light = theme_bg_light
        self.theme_border = theme_border
        self.card_w = width
        self.card_h = height
        self.radius = radius
        self.bg_parent = bg_parent
        self.disabled = False
        self.is_hovered = False

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Configure>", lambda e: self.redraw())
        self.redraw()

    def set_disabled(self, disabled: bool):
        self.disabled = disabled
        self.config(cursor="arrow" if disabled else "hand2")
        self.redraw()

    def _on_enter(self, event=None):
        if not self.disabled:
            self.is_hovered = True
            self.redraw()

    def _on_leave(self, event=None):
        if not self.disabled:
            self.is_hovered = False
            self.redraw()

    def _on_click(self, event=None):
        if self.disabled:
            return
        if self.is_radio:
            if not self.checked:
                self.checked = True
                self.redraw()
                if self.on_toggle:
                    self.on_toggle(self)
        else:
            self.checked = not self.checked
            self.redraw()
            if self.on_toggle:
                self.on_toggle(self)

    def set_checked(self, val: bool):
        self.checked = val
        self.redraw()

    def redraw(self):
        self.delete("all")
        w = self.winfo_width() or self.card_w
        h = self.winfo_height() or self.card_h
        r = min(self.radius, h / 2.0, w / 4.0)

        if self.disabled:
            bg_fill = "#F1F5F9"
            border_col = "#E2E8F0"
            border_w = 1
            icon_col = "#CBD5E1"
            title_col = "#94A3B8"
            sub_col = "#CBD5E1"
            badge_bg = "#E2E8F0"
            badge_fg = "#94A3B8"
        elif self.checked:
            bg_fill = self.theme_bg_light
            border_col = self.theme_color
            border_w = 2.0
            icon_col = self.theme_color
            title_col = "#0F172A"
            sub_col = "#334155"
            badge_bg = self.theme_color
            badge_fg = "#FFFFFF"
        else:
            bg_fill = "#FFFFFF"
            border_col = self.theme_border if self.is_hovered else "#CBD5E1"
            border_w = 1.6 if self.is_hovered else 1.0
            icon_col = "#94A3B8"
            title_col = "#334155"
            sub_col = "#64748B"
            badge_bg = "#F1F5F9"
            badge_fg = "#64748B"

        pad = 2
        draw_pill(
            self,
            pad, pad, w - pad, h - pad,
            radius=r,
            fill=bg_fill,
            outline=border_col,
            width=border_w
        )

        ind_x, ind_y = 18, 20
        if self.is_radio:
            rad = 7
            self.create_oval(
                ind_x - rad, ind_y - rad, ind_x + rad, ind_y + rad,
                outline=icon_col, width=2,
                fill=self.theme_color if self.checked and not self.disabled else bg_fill
            )
            if self.checked and not self.disabled:
                self.create_oval(
                    ind_x - 3, ind_y - 3, ind_x + 3, ind_y + 3,
                    fill="#FFFFFF", outline=""
                )
        else:
            rad = 7
            draw_pill(
                self,
                ind_x - rad, ind_y - rad, ind_x + rad, ind_y + rad,
                radius=4,
                fill=self.theme_color if self.checked and not self.disabled else bg_fill,
                outline=icon_col,
                width=2
            )
            if self.checked and not self.disabled:
                self.create_line(
                    ind_x - 3.5, ind_y, ind_x - 1, ind_y + 3, ind_x + 4, ind_y - 3,
                    fill="#FFFFFF", width=2.0, capstyle=tk.ROUND
                )

        self.create_text(
            32, 20,
            text=self.title,
            font=("Microsoft YaHei", 10, "bold"),
            fill=title_col,
            anchor="w"
        )

        if self.badge_text:
            bw = len(self.badge_text) * 11 + 12
            bx2 = w - 14
            bx1 = bx2 - bw
            by1, by2 = 11, 26
            draw_pill(self, bx1, by1, bx2, by2, radius=7, fill=badge_bg, outline="")
            self.create_text(
                (bx1 + bx2) / 2, (by1 + by2) / 2,
                text=self.badge_text,
                font=("Microsoft YaHei", 8, "bold"),
                fill=badge_fg
            )

        self.create_text(
            18, 42,
            text=self.subtitle,
            font=("Microsoft YaHei", 8),
            fill=sub_col,
            anchor="nw",
            width=w - 32
        )


# ==================== 渐变平滑胶囊进度条 ====================

class CapsuleProgressBar(tk.Canvas):
    """现代纯渐变平滑胶囊进度条"""
    def __init__(self, master, height=12, bg_parent="#EEF2FF", **kwargs):
        super().__init__(
            master,
            height=height,
            bg=bg_parent,
            highlightthickness=0,
            **kwargs
        )
        self.bar_height = height
        self.progress = 0.0
        self.target_progress = 0.0
        self.bind("<Configure>", lambda e: self.redraw())

    def set_progress(self, val: float):
        self.target_progress = max(self.progress, min(1.0, float(val)))
        self._animate_step()

    def _animate_step(self):
        if self.progress < self.target_progress:
            step = max(0.015, (self.target_progress - self.progress) * 0.3)
            self.progress = min(self.target_progress, self.progress + step)
            self.redraw()
            if self.progress < self.target_progress:
                self.after(16, self._animate_step)
        else:
            self.redraw()

    def reset(self):
        self.progress = 0.0
        self.target_progress = 0.0
        self.redraw()

    def redraw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.bar_height
        if w <= 10:
            return

        r = h / 2.0
        draw_pill(self, 0, 0, w, h, radius=r, fill="#CBD5E1", outline="")

        fill_w = int(w * self.progress)
        if fill_w >= h:
            steps = max(10, int(fill_w / 6))
            c_start = "#3B82F6"
            c_end = "#8B5CF6"
            for i in range(steps):
                f = i / float(steps - 1)
                color = interpolate_color(c_start, c_end, f)
                x_s = fill_w * (i / steps)
                x_e = fill_w * ((i + 1) / steps)
                self.create_rectangle(x_s, 0, x_e, h, fill=color, outline=color)
            draw_pill(self, 0, 0, fill_w, h, radius=r, fill="", outline="#FFFFFF", width=0.5)
        elif fill_w > 0:
            self.create_oval(0, 0, h, h, fill="#3B82F6", outline="")


# ==================== 大圆滑胶囊输入框容器 ====================

class CapsuleEntryBox(tk.Canvas):
    """完全圆滑的胶囊输入框（自适应宽度扩展）"""
    def __init__(self, master, on_change: callable = None, bg_parent: str = "#EEF2FF", **kwargs):
        super().__init__(master, height=48, bg=bg_parent, highlightthickness=0, **kwargs)
        self.on_change = on_change
        self.bg_parent = bg_parent

        self.inner_frame = tk.Frame(self, bg="#FFFFFF")
        self.window_id = self.create_window(0, 0, window=self.inner_frame, anchor="nw")

        self.url_entry = tk.Entry(
            self.inner_frame,
            font=("Microsoft YaHei", 10),
            bg="#FFFFFF",
            fg="#0F172A",
            relief=tk.FLAT,
            insertbackground="#2563EB"
        )
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(16, 8), ipady=3)
        if self.on_change:
            self.url_entry.bind("<KeyRelease>", lambda e: self.on_change())

        self.paste_btn = tk.Button(
            self.inner_frame,
            text="📋 粘贴链接",
            font=("Microsoft YaHei", 9, "bold"),
            bg="#EFF6FF",
            fg="#2563EB",
            activebackground="#DBEAFE",
            activeforeground="#1D4ED8",
            relief=tk.FLAT,
            padx=14,
            pady=4,
            cursor="hand2",
            command=self._paste_clipboard
        )
        self.paste_btn.pack(side=tk.RIGHT, padx=(0, 8))

        self.bind("<Configure>", self._on_resize)

    def _paste_clipboard(self):
        try:
            text = self.winfo_toplevel().clipboard_get()
            if text:
                self.url_entry.delete(0, tk.END)
                self.url_entry.insert(0, text.strip())
                if self.on_change:
                    self.on_change()
        except Exception:
            pass

    def get_text(self) -> str:
        return self.url_entry.get().strip()

    def set_locked(self, locked: bool):
        state = tk.DISABLED if locked else tk.NORMAL
        self.url_entry.config(state=state)
        self.paste_btn.config(state=state, cursor="arrow" if locked else "hand2")

    def _on_resize(self, event):
        w = event.width
        h = 48
        self.delete("pill_bg")
        draw_pill(self, 2, 2, w - 2, h - 2, radius=22, fill="#FFFFFF", outline="#93C5FD", width=1.8, tags="pill_bg")
        self.tag_lower("pill_bg")
        self.coords(self.window_id, 10, 6)
        self.inner_frame.config(width=w - 20, height=36)
        self.inner_frame.pack_propagate(False)


# ==================== 主窗口与交互逻辑 ====================

class AIMemoryGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AI 记忆总结协同管理工具")
        # 紧凑初始尺寸，支持自由等比例缩放
        self.root.geometry("880x660")
        self.root.minsize(780, 520)
        self.root.configure(bg="#E0E7FF")

        self.is_running = False
        self._build_ui()
        self._bind_mousewheel()
        self._update_generate_button_state()

    def _build_ui(self):
        # 整体主容器
        root_container = tk.Frame(self.root, bg="#E0E7FF")
        root_container.pack(fill=tk.BOTH, expand=True)

        # 1. 主可滚动渐变画布
        self.bg_canvas = tk.Canvas(root_container, highlightthickness=0, bg="#E0E7FF")
        self.bg_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 2. 右侧现代胶囊滚动指示条
        self.custom_scrollbar = CapsuleScrollbar(
            root_container,
            target_canvas=self.bg_canvas,
            width=10,
            bg_parent="#E0E7FF"
        )
        self.custom_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.bg_canvas.config(yscrollcommand=self.custom_scrollbar.set_range)

        # 3. 挂载主内容框架（全比例等比拉伸）
        self.main_content = tk.Frame(self.bg_canvas, bg="#E0E7FF")
        self.canvas_window_id = self.bg_canvas.create_window(0, 0, window=self.main_content, anchor="nw")

        self.bg_canvas.bind("<Configure>", self._on_canvas_configure)
        self.main_content.bind("<Configure>", self._on_content_configure)

        # 主卡片白底胶囊外框（fill=BOTH, expand=True 全自适应拉伸）
        self.sheet_frame = tk.Frame(self.main_content, bg="#EEF2FF", padx=28, pady=18)
        self.sheet_frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=14)

        # 头部主标题区
        header_frame = tk.Frame(self.sheet_frame, bg="#EEF2FF")
        header_frame.pack(fill=tk.X, pady=(0, 10))

        title_lbl = tk.Label(
            header_frame,
            text="AI 记忆总结",
            font=("Microsoft YaHei", 22, "bold"),
            foreground="#1E1B4B",
            bg="#EEF2FF"
        )
        title_lbl.pack(anchor="center")

        sub_chip_frame = tk.Frame(header_frame, bg="#EEF2FF")
        sub_chip_frame.pack(anchor="center", pady=(4, 0))

        sub_desc = tk.Label(
            sub_chip_frame,
            text="✨ 多平台对话提取 · 多模态深度提炼 · 极简/深度可续接记忆协同",
            font=("Microsoft YaHei", 9),
            foreground="#4338CA",
            bg="#E0E7FF",
            padx=14,
            pady=3
        )
        sub_desc.pack(anchor="center")

        # 分享链接板块（胶囊输入框）
        url_section = tk.Frame(self.sheet_frame, bg="#EEF2FF")
        url_section.pack(fill=tk.X, pady=(0, 10))

        url_label = tk.Label(
            url_section,
            text="🔗 分享链接",
            font=("Microsoft YaHei", 10, "bold"),
            foreground="#1E293B",
            bg="#EEF2FF"
        )
        url_label.pack(anchor="w", pady=(0, 4))

        self.capsule_entry = CapsuleEntryBox(
            url_section,
            on_change=self._update_generate_button_state,
            bg_parent="#EEF2FF"
        )
        self.capsule_entry.pack(fill=tk.X)

        # 导出模式（4 大彩色胶囊卡片）
        mode_section = tk.Frame(self.sheet_frame, bg="#EEF2FF")
        mode_section.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        mode_header = tk.Label(
            mode_section,
            text="🏷️ 导出模式（支持勾选一个或多个）",
            font=("Microsoft YaHei", 10, "bold"),
            foreground="#1E293B",
            bg="#EEF2FF"
        )
        mode_header.pack(anchor="w", pady=(0, 5))

        mode_grid = tk.Frame(mode_section, bg="#EEF2FF")
        mode_grid.pack(fill=tk.BOTH, expand=True)
        for i in range(4):
            mode_grid.columnconfigure(i, weight=1, uniform="mode_col")
        mode_grid.rowconfigure(0, weight=1)

        # 模式 1：raw 原始对话（暖金琥珀）
        self.card_raw = CapsuleSelectCard(
            mode_grid,
            title="仅抓取对话",
            subtitle="raw 原始问答\n不调用总结 API",
            badge_text="raw",
            is_radio=False,
            initial_checked=False,
            on_toggle=lambda c: self._on_mode_toggled(),
            theme_color="#D97706",
            theme_bg_light="#FFFBEB",
            theme_border="#FDE68A",
            bg_parent="#EEF2FF",
            height=94,
            radius=18
        )
        self.card_raw.grid(row=0, column=0, padx=5, sticky="nsew")

        # 模式 2：普通版（极光科技蓝）
        self.card_normal = CapsuleSelectCard(
            mode_grid,
            title="普通版",
            subtitle="生成分层总结\n结构化与标准摘要",
            badge_text="推荐",
            is_radio=False,
            initial_checked=True,
            on_toggle=lambda c: self._on_mode_toggled(),
            theme_color="#2563EB",
            theme_bg_light="#EFF6FF",
            theme_border="#BFDBFE",
            bg_parent="#EEF2FF",
            height=94,
            radius=18
        )
        self.card_normal.grid(row=0, column=1, padx=5, sticky="nsew")

        # 模式 3：极简版（清爽薄荷青）
        self.card_simple = CapsuleSelectCard(
            mode_grid,
            title="极简版",
            subtitle="单段落高保真总览\n去冗余极短提炼",
            badge_text="极短",
            is_radio=False,
            initial_checked=False,
            on_toggle=lambda c: self._on_mode_toggled(),
            theme_color="#0D9488",
            theme_bg_light="#F0FDFA",
            theme_border="#99F6E4",
            bg_parent="#EEF2FF",
            height=94,
            radius=18
        )
        self.card_simple.grid(row=0, column=2, padx=5, sticky="nsew")

        # 模式 4：细节版（梦幻暮光紫）
        self.card_detailed = CapsuleSelectCard(
            mode_grid,
            title="细节版",
            subtitle="总结包含细节记忆\n附带高价值要点",
            badge_text="精细",
            is_radio=False,
            initial_checked=False,
            on_toggle=lambda c: self._on_mode_toggled(),
            theme_color="#7C3AED",
            theme_bg_light="#FAF5FF",
            theme_border="#DDD6FE",
            bg_parent="#EEF2FF",
            height=94,
            radius=18
        )
        self.card_detailed.grid(row=0, column=3, padx=5, sticky="nsew")

        # 登录选项（2 大圆角胶囊卡片）
        auth_section = tk.Frame(self.sheet_frame, bg="#EEF2FF")
        auth_section.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        auth_header = tk.Label(
            auth_section,
            text="🔐 登录选项（单选）",
            font=("Microsoft YaHei", 10, "bold"),
            foreground="#1E293B",
            bg="#EEF2FF"
        )
        auth_header.pack(anchor="w", pady=(0, 5))

        auth_grid = tk.Frame(auth_section, bg="#EEF2FF")
        auth_grid.pack(fill=tk.BOTH, expand=True)
        auth_grid.columnconfigure(0, weight=1, uniform="auth_col")
        auth_grid.columnconfigure(1, weight=1, uniform="auth_col")
        auth_grid.rowconfigure(0, weight=1)

        # 不登录（已去掉“或公开分享页”）
        self.card_no_login = CapsuleSelectCard(
            auth_grid,
            title="不登录",
            subtitle="已登录过该 AI，则不必重复登录",
            badge_text="默认",
            is_radio=True,
            initial_checked=True,
            on_toggle=self._on_auth_toggled,
            theme_color="#EA580C",
            theme_bg_light="#FFF7ED",
            theme_border="#FED7AA",
            bg_parent="#EEF2FF",
            height=80,
            radius=18
        )
        self.card_no_login.grid(row=0, column=0, padx=5, sticky="nsew")

        # 授权登录
        self.card_need_login = CapsuleSelectCard(
            auth_grid,
            title="授权登录",
            subtitle="首次总结该 AI 建议登录，将自动弹出独立浏览器",
            badge_text="首次建议",
            is_radio=True,
            initial_checked=False,
            on_toggle=self._on_auth_toggled,
            theme_color="#0284C7",
            theme_bg_light="#F0F9FF",
            theme_border="#BAE6FD",
            bg_parent="#EEF2FF",
            height=80,
            radius=18
        )
        self.card_need_login.grid(row=0, column=1, padx=5, sticky="nsew")

        # 进度反馈区（胶囊进度条与步骤提示）
        status_box = tk.Frame(self.sheet_frame, bg="#EEF2FF")
        status_box.pack(fill=tk.X, pady=(2, 4))

        self.status_var = tk.StringVar(value="准备就绪")
        self.status_lbl = tk.Label(
            status_box,
            textvariable=self.status_var,
            font=("Microsoft YaHei", 9),
            foreground="#475569",
            bg="#EEF2FF",
            anchor="w"
        )
        self.status_lbl.pack(side=tk.LEFT)

        self.percent_var = tk.StringVar(value="")
        self.percent_lbl = tk.Label(
            status_box,
            textvariable=self.percent_var,
            font=("Microsoft YaHei", 9, "bold"),
            foreground="#2563EB",
            bg="#EEF2FF",
            anchor="e"
        )
        self.percent_lbl.pack(side=tk.RIGHT)

        self.progress_bar = CapsuleProgressBar(self.sheet_frame, height=12, bg_parent="#EEF2FF")
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))

        # 开始生成按钮与完成徽章区
        action_box = tk.Frame(self.sheet_frame, bg="#EEF2FF")
        action_box.pack(fill=tk.X, pady=(0, 6))

        self.btn_generate = GradientPillButton(
            action_box,
            text="🚀 开始生成",
            command=self._on_start_generate,
            width=240,
            height=48,
            font=("Microsoft YaHei", 12, "bold"),
            bg_parent="#EEF2FF"
        )
        self.btn_generate.pack(anchor="center")

        self.done_badge = tk.Label(
            action_box,
            text="🎉 生成已全部完成！文件已成功保存。",
            font=("Microsoft YaHei", 10, "bold"),
            foreground="#15803D",
            bg="#DCFCE7",
            padx=20,
            pady=5,
            relief=tk.FLAT
        )

    def _draw_vibrant_gradient(self, w: int, h: int):
        """绘制极光晨曦渐变色"""
        self.bg_canvas.delete("gradient_bg")
        c1 = "#C7D2FE"
        c2 = "#E9D5FF"
        c3 = "#FCE7F3"
        steps = 60
        half = steps // 2
        for i in range(steps):
            if i < half:
                f = i / float(half)
                col = interpolate_color(c1, c2, f)
            else:
                f = (i - half) / float(steps - half - 1)
                col = interpolate_color(c2, c3, f)
            y_s = h * (i / steps)
            y_e = h * ((i + 1) / steps)
            self.bg_canvas.create_rectangle(0, y_s, w, y_e, fill=col, outline=col, tags="gradient_bg")
        self.bg_canvas.tag_lower("gradient_bg")

    def _on_canvas_configure(self, event):
        w = event.width
        h = event.height
        if w > 10 and h > 10:
            req_h = self.main_content.winfo_reqheight()
            total_h = max(h, req_h)
            self._draw_vibrant_gradient(w, total_h)
            # 让 main_content 高度充满整个视窗，彻底杜绝下方粉色空隙断层
            self.bg_canvas.itemconfig(self.canvas_window_id, width=w, height=total_h)

    def _on_content_configure(self, event):
        # 动态更新滚轮滚动区域
        self.bg_canvas.configure(scrollregion=self.bg_canvas.bbox("all"))

    def _bind_mousewheel(self):
        """全局绑定鼠标滚轮，低分屏或缩小窗口时自由滚动并联动右侧滚动条"""
        def _on_mousewheel(event):
            can_h = self.bg_canvas.winfo_height()
            req_h = self.main_content.winfo_reqheight()
            if req_h > can_h:
                delta = -1 * int(event.delta / 120)
                self.bg_canvas.yview_scroll(delta, "units")

        self.root.bind_all("<MouseWheel>", _on_mousewheel)

    def _on_mode_toggled(self):
        self._update_generate_button_state()

    def _on_auth_toggled(self, selected_card):
        if selected_card == self.card_no_login:
            self.card_need_login.set_checked(False)
        else:
            self.card_no_login.set_checked(False)
        self._update_generate_button_state()

    def _set_inputs_locked(self, locked: bool):
        """生成过程中锁定所有输入与选项卡片"""
        self.capsule_entry.set_locked(locked)
        self.card_raw.set_disabled(locked)
        self.card_normal.set_disabled(locked)
        self.card_simple.set_disabled(locked)
        self.card_detailed.set_disabled(locked)
        self.card_no_login.set_disabled(locked)
        self.card_need_login.set_disabled(locked)

    def _update_generate_button_state(self):
        if self.is_running:
            self.btn_generate.set_enabled(False)
            return

        has_mode = any([
            self.card_raw.checked,
            self.card_normal.checked,
            self.card_simple.checked,
            self.card_detailed.checked
        ])
        has_auth = self.card_no_login.checked or self.card_need_login.checked
        has_url = len(self.capsule_entry.get_text()) > 0

        self.btn_generate.set_enabled(bool(has_mode and has_auth and has_url))

    def _show_completed_badge(self, duration_sec: int = 5):
        self.done_badge.pack(anchor="center", pady=(8, 0))
        def hide():
            time.sleep(duration_sec)
            self.root.after(0, lambda: self.done_badge.pack_forget())
        threading.Thread(target=hide, daemon=True).start()

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

        # 选择保存目录
        save_directory = filedialog.askdirectory(
            title="请选择生成结果的保存目录",
            initialdir=str(PROJECT_ROOT / "results" / "summary")
        )
        if not save_directory:
            return  # 用户取消选择

        save_dir_path = Path(save_directory).resolve()

        # 锁定界面输入并启动任务
        self.is_running = True
        self.done_badge.pack_forget()
        self._set_inputs_locked(True)
        self._update_generate_button_state()
        self.progress_bar.reset()
        self.progress_bar.set_progress(0.06)
        self.status_var.set("正在启动后台引擎...")
        self.percent_var.set("6%")

        thread = threading.Thread(
            target=self._run_generation_task,
            args=(url, need_login, modes, save_dir_path),
            daemon=True
        )
        thread.start()

    def _show_login_dialog(self, loop: asyncio.AbstractEventLoop, login_event: asyncio.Event):
        """弹出登录提示对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title("授权登录确认")
        dialog.geometry("480x230")
        dialog.resizable(False, False)
        dialog.configure(bg="#FFFFFF")
        dialog.transient(self.root)
        dialog.grab_set()

        x = self.root.winfo_x() + (self.root.winfo_width() - 480) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 230) // 2
        dialog.geometry(f"+{x}+{y}")

        content_frame = tk.Frame(dialog, bg="#FFFFFF", padx=28, pady=22)
        content_frame.pack(fill=tk.BOTH, expand=True)

        warn_title = tk.Label(
            content_frame,
            text="⚠️ 在生成结束前请勿关闭浏览器！",
            font=("Microsoft YaHei", 12, "bold"),
            foreground="#DC2626",
            bg="#FFFFFF"
        )
        warn_title.pack(anchor="w", pady=(0, 8))

        msg_body = tk.Label(
            content_frame,
            text="系统已为您打开浏览器窗口。\n请在弹出的浏览器中登录您的 AI 账号，登录成功后点击下方按钮继续生成。",
            font=("Microsoft YaHei", 10),
            foreground="#334155",
            bg="#FFFFFF",
            justify=tk.LEFT
        )
        msg_body.pack(anchor="w", pady=(0, 16))

        def on_login_done():
            loop.call_soon_threadsafe(login_event.set)
            dialog.destroy()

        btn_done = tk.Button(
            content_frame,
            text="已登录完毕，继续生成",
            font=("Microsoft YaHei", 11, "bold"),
            bg="#16A34A",
            fg="#FFFFFF",
            activebackground="#15803D",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=20,
            pady=8,
            cursor="hand2",
            command=on_login_done
        )
        btn_done.pack(anchor="center")

    def _show_summary_section_dialog(self, available_sections, on_done):
        """在主题综合完成后，让用户选择普通/详细版的重点展开板块。"""
        from scripts.gemini_summarizer import SUMMARY_SECTION_LABELS

        descriptions = {
            "programming": "代码学习、项目实现、调试与验证过程",
            "learning": "词汇、翻译、表达与语言纠错",
            "calculations": "用户条件、AI 假设与分阶段计算结果",
            "decisions": "明确选项、用户选择及当前状态",
            "context_references": "影响理解的短消息与上下文指代",
            "progressions": "同一主题中条件和结论的递进变化",
            "source_text_issues": "会实质影响理解的原文问题与推断修正",
        }

        dialog = tk.Toplevel(self.root)
        dialog.title("选择重点板块")
        dialog.resizable(False, False)
        dialog.configure(bg="#F8FAFC")
        dialog.transient(self.root)
        dialog.grab_set()

        height = min(620, 245 + 62 * len(available_sections))
        width = 570
        x = self.root.winfo_x() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - height) // 2
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        content = tk.Frame(dialog, bg="#F8FAFC", padx=28, pady=22)
        content.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            content,
            text="主题已经分好，请选择你认为重要的板块",
            font=("Microsoft YaHei", 14, "bold"),
            foreground="#1E1B4B",
            bg="#F8FAFC",
        ).pack(anchor="w")
        tk.Label(
            content,
            text=(
                "勾选只会在完整的“分主题摘要”之后展开对应记录；"
                "不会删减或改写任何主题。"
            ),
            font=("Microsoft YaHei", 9),
            foreground="#475569",
            bg="#F8FAFC",
            wraplength=510,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(5, 14))

        choices = tk.Frame(content, bg="#F8FAFC")
        choices.pack(fill=tk.BOTH, expand=True)
        variables = {}
        for key in available_sections:
            row = tk.Frame(
                choices,
                bg="#FFFFFF",
                highlightthickness=1,
                highlightbackground="#CBD5E1",
                padx=12,
                pady=7,
            )
            row.pack(fill=tk.X, pady=4)
            variable = tk.BooleanVar(master=dialog, value=False)
            variables[key] = variable
            checkbox = tk.Checkbutton(
                row,
                text=SUMMARY_SECTION_LABELS[key],
                variable=variable,
                font=("Microsoft YaHei", 10, "bold"),
                foreground="#1E293B",
                bg="#FFFFFF",
                activebackground="#FFFFFF",
                selectcolor="#EEF2FF",
                cursor="hand2",
                anchor="w",
            )
            checkbox.pack(fill=tk.X)
            tk.Label(
                row,
                text=descriptions.get(key, "展开该类结构化记录"),
                font=("Microsoft YaHei", 8),
                foreground="#64748B",
                bg="#FFFFFF",
                anchor="w",
            ).pack(fill=tk.X, padx=(24, 0), pady=(1, 0))

        tk.Label(
            content,
            text="媒体与附件说明始终保留；详细版的细节记忆也始终保留。",
            font=("Microsoft YaHei", 8),
            foreground="#7C3AED",
            bg="#F8FAFC",
        ).pack(anchor="w", pady=(12, 8))

        completed = False

        def finish(use_checked: bool):
            nonlocal completed
            if completed:
                return
            completed = True
            selected = tuple(
                key for key in available_sections
                if use_checked and variables[key].get()
            )
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()
            on_done(selected)

        button_row = tk.Frame(content, bg="#F8FAFC")
        button_row.pack(fill=tk.X, pady=(2, 0))
        tk.Button(
            button_row,
            text="全部不展开",
            command=lambda: finish(False),
            font=("Microsoft YaHei", 9),
            bg="#E2E8F0",
            fg="#334155",
            activebackground="#CBD5E1",
            relief=tk.FLAT,
            padx=16,
            pady=7,
            cursor="hand2",
        ).pack(side=tk.LEFT)
        tk.Button(
            button_row,
            text="确认重点板块并继续",
            command=lambda: finish(True),
            font=("Microsoft YaHei", 10, "bold"),
            bg="#4F46E5",
            fg="#FFFFFF",
            activebackground="#4338CA",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=18,
            pady=8,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        dialog.bind("<Escape>", lambda _event: finish(False))
        dialog.bind("<Return>", lambda _event: finish(True))
        dialog.focus_force()

    def _run_generation_task(
        self,
        url: str,
        need_login: bool,
        modes: dict[str, bool],
        save_dir: Path
    ):
        """后台异步流水线调用与平滑进度控制"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        login_event = asyncio.Event()

        def update_progress(val: float, msg: str):
            percent_str = f"{int(val * 100)}%"
            self.root.after(0, lambda: [
                self.progress_bar.set_progress(val),
                self.status_var.set(msg),
                self.percent_var.set(percent_str)
            ])

        if need_login:
            self.root.after(0, lambda: self._show_login_dialog(loop, login_event))

        try:
            update_progress(0.15, "正在加载分享页并解析动态列表...")

            # 1. 抓取网页内容
            fetch_res = loop.run_until_complete(
                fetch_chat_pipeline(
                    url=url,
                    need_login=need_login,
                    login_ready_event=login_event if need_login else None,
                    logger=lambda m: update_progress(0.28, m)
                )
            )

            if fetch_res.error or not fetch_res.messages:
                err = fetch_res.error or "未能提取到有效对话内容。"
                self.root.after(0, lambda: messagebox.showerror("生成失败", err))
                return

            messages = fetch_res.messages
            update_progress(0.42, f"成功提取 {len(messages)} 条对话交互，正在按要求生成文件...")

            def select_summary_sections(result):
                from scripts.gemini_summarizer import available_summary_sections

                available = available_summary_sections(result)
                if not available:
                    update_progress(
                        0.80,
                        "主题分类完成，本次没有额外可展开的分类板块。",
                    )
                    return ()

                update_progress(
                    0.80,
                    "主题分类完成，请在弹出的窗口中勾选重要板块...",
                )
                selection_ready = threading.Event()
                selection_holder = {"sections": ()}

                def on_selected(sections):
                    selection_holder["sections"] = tuple(sections)
                    selection_ready.set()

                def show_dialog():
                    try:
                        self._show_summary_section_dialog(
                            available, on_selected
                        )
                    except Exception:
                        on_selected(())

                self.root.after(0, show_dialog)
                selection_ready.wait()
                selected = selection_holder["sections"]
                update_progress(
                    0.84,
                    (
                        f"已选择 {len(selected)} 个重点板块，正在写入结果..."
                        if selected
                        else "未选择额外板块，正在写入完整主题摘要..."
                    ),
                )
                return selected

            update_progress(0.56, "正在连接总结后端并准备生成文件...")
            bundle = generate_output_bundle(
                messages=messages,
                modes=modes,
                save_dir=save_dir,
                project_dir=PROJECT_ROOT,
                section_selector=(
                    select_summary_sections
                    if modes.get("normal") or modes.get("detailed")
                    else None
                ),
                progress=lambda message: update_progress(0.72, message),
            )
            saved_files = [path.name for path in bundle.saved_files]

            # 4. 完成进度 100%
            file_list_str = "、".join(saved_files)
            update_progress(
                1.0,
                f"所有任务生成完成：{file_list_str}" if file_list_str
                else "所有任务生成完成！",
            )
            self.root.after(0, lambda: self._show_completed_badge(5))

        except Exception as e:
            err_msg = str(e)
            try:
                from scripts.gemini_summarizer import safe_error_message
                err_msg = safe_error_message(e)
            except Exception:
                pass
            update_progress(0.0, f"❌ 处理发生错误: {err_msg}")
            self.root.after(0, lambda: messagebox.showerror("处理失败", f"生成失败：{err_msg}"))

        finally:
            loop.close()
            self.root.after(0, self._on_task_finished)

    def _on_task_finished(self):
        self.is_running = False
        self._set_inputs_locked(False)
        self._update_generate_button_state()


def main():
    root = tk.Tk()
    app = AIMemoryGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
