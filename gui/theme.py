"""Argon 前端视觉设计系统（Theme Tokens、精确圆角几何与样式辅助）。

统一管理全界面调色板、字体阶梯、间距圆角、图标资源路径与 TTK 样式，
避免魔法颜色散落，确保高 DPI 缩放与跨页面视觉规范一致。
"""

from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ==================== 核心调色板 (Argon Design System) ====================
COLOR_BG_APP = "#F8FAFD"
COLOR_SIDEBAR = "#FFFFFF"
COLOR_CARD = "#FFFFFF"
COLOR_CARD_SUBTLE = "#F8FAFC"
COLOR_BORDER = "#E2E8F0"
COLOR_BORDER_SUBTLE = "#EEF2F6"
COLOR_BORDER_FOCUS = "#6F55E8"

COLOR_TEXT_PRIMARY = "#1E1F20"
COLOR_TEXT_SECONDARY = "#3C4043"
COLOR_TEXT_MUTED = "#64748B"
COLOR_TEXT_DISABLED = "#94A3B8"

COLOR_ACCENT = "#1E1F20"
COLOR_ACCENT_BLUE = "#4F46E5"
COLOR_ACCENT_BG = "#F1F5F9"

COLOR_SUCCESS = "#0F9D58"
COLOR_SUCCESS_BG = "#ECFDF5"
COLOR_WARNING = "#F59E0B"
COLOR_WARNING_BG = "#FFFBEB"
COLOR_DANGER = "#EA4335"
COLOR_DANGER_BG = "#FEF2F2"

COLOR_HOVER = "#F1F5F9"
COLOR_DISABLED = "#E2E8F0"

COLOR_SIDEBAR_TEXT = "#64748B"
COLOR_SIDEBAR_ACTIVE = "#1E1F20"
COLOR_SIDEBAR_ACTIVE_BG = "#F5F3FF"
COLOR_SIDEBAR_DIVIDER = "#E2E8F0"

COLOR_OMNIBOX_BG = "#F0F4F9"
COLOR_OMNIBOX_BG_FOCUS = "#FFFFFF"
COLOR_OMNIBOX_SURFACE = "#F3EEFF"
COLOR_OMNIBOX_BORDER = "#C4B5FD"
COLOR_DRAG_HIGHLIGHT = "#EFF6FF"
COLOR_DRAG_NORMAL = "#F0F4F9"

COLOR_GENERATION_ACCENT = "#6F55E8"
COLOR_GENERATION_ACCENT_HOVER = "#5B42D6"
COLOR_GENERATION_ACCENT_BG = "#F5F3FF"
COLOR_GENERATION_BORDER = "#DDD6FE"

COLOR_TOPIC_DIALOG_BG = "#F6F7FB"
COLOR_TOPIC_CARD_SELECTED = "#F5F3FF"
COLOR_TOPIC_CARD_HOVER = "#FAFAFC"
COLOR_TOPIC_CONTROL = "#ECEFF4"

SETTINGS_SECTION_PADX = 48
SETTINGS_PANEL_PADX = 20
SETTINGS_PAGE_PADX = 14


# ==================== 字体阶梯 ====================
FONT_FAMILY = "Microsoft YaHei UI"
FONT_TITLE = (FONT_FAMILY, 18, "bold")
FONT_H2 = (FONT_FAMILY, 14, "bold")
FONT_BODY = (FONT_FAMILY, 10)
FONT_BODY_BOLD = (FONT_FAMILY, 10, "bold")
FONT_SMALL = (FONT_FAMILY, 9)
FONT_SMALL_BOLD = (FONT_FAMILY, 9, "bold")
FONT_TINY = (FONT_FAMILY, 8)
FONT_TINY_BOLD = (FONT_FAMILY, 8, "bold")
FONT_HERO = (FONT_FAMILY, 28, "bold")
FONT_SIDEBAR_TITLE = (FONT_FAMILY, 12, "bold")
FONT_SIDEBAR_ITEM = (FONT_FAMILY, 13, "bold")
FONT_SIDEBAR_STEP = (FONT_FAMILY, 9, "bold")


# ==================== 交互文案常量 ====================
GENERATION_SOURCE_LABELS = {
    "url": "当前对话",
    "file": "已选文件",
}
AUTH_REUSE_LABEL = "复用登录状态"
AUTH_NOT_REQUIRED_LABEL = "本地文件无需登录"
GENERATE_BUTTON_LABEL = "开始生成  →"
REGENERATE_BUTTON_LABEL = "重新生成  →"

DIRECT_SUMMARY_FILE_TYPES = {".md", ".txt"}
DIRECT_SUMMARY_MAX_BYTES = 10 * 1024 * 1024


# ==================== 资源路径与几何工具 ====================

def _logo_png_path(size: int, variant: str = "neutral") -> Path:
    return (
        _PROJECT_ROOT / "gui" / "assets" / "logo"
        / variant / f"icon-{size}.png"
    )


def _navigation_icon_path(name: str, size: int = 24) -> Path:
    return _PROJECT_ROOT / "gui" / "assets" / "icons" / f"{name}-{size}.png"


def _scaled_font_size(font: tkfont.Font, scale: float, low: int, high: int) -> int:
    """按窗口缩放系数计算受限字号，记录初始基准避免累计漂移。"""
    base = getattr(font, "_responsive_base_size", None)
    if base is None:
        base = abs(int(font.actual("size")))
        font._responsive_base_size = base
    return max(low, min(high, round(base * scale)))


def _mix_color(start: str, end: str, amount: float) -> str:
    """在两个十六进制颜色之间线性插值。"""
    amount = max(0.0, min(1.0, float(amount)))
    channels = (
        round(int(start[i:i + 2], 16) * (1.0 - amount)
              + int(end[i:i + 2], 16) * amount)
        for i in (1, 3, 5)
    )
    return "#" + "".join(f"{channel:02X}" for channel in channels)


def _round_rectangle(canvas: tk.Canvas, x1, y1, x2, y2, r=6, **kwargs):
    """在 Canvas 上绘制精确圆弧顶点的圆角矩形（返回单个 polygon 图元）。"""
    if "radius" in kwargs:
        r = kwargs.pop("radius")
    w = x2 - x1
    h = y2 - y1
    r = max(0.0, min(float(r), w / 2.0, h / 2.0))
    if r <= 0.5:
        return canvas.create_rectangle(x1, y1, x2, y2, **kwargs)
    steps = max(8, min(16, int(r)))
    points: list[float] = []
    corners = (
        (x2 - r, y1 + r, -math.pi / 2, 0.0),
        (x2 - r, y2 - r, 0.0, math.pi / 2),
        (x1 + r, y2 - r, math.pi / 2, math.pi),
        (x1 + r, y1 + r, math.pi, 1.5 * math.pi),
    )
    for cx, cy, start_angle, end_angle in corners:
        for i in range(steps + 1):
            angle = start_angle + (end_angle - start_angle) * (i / steps)
            points.append(cx + r * math.cos(angle))
            points.append(cy + r * math.sin(angle))
    kwargs.pop("smooth", None)
    return canvas.create_polygon(points, smooth=False, **kwargs)
