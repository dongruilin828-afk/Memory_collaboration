"""Argon 前端视觉设计系统（Theme Tokens、几何绘制与平台识别辅助）。

统一管理全界面调色板、字体阶梯、间距圆角、图标资源路径与 TTK 样式，
避免魔法颜色散落，确保高 DPI 缩放与跨页面视觉规范一致。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk
from urllib.parse import urlparse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ==================== 核心调色板 (Argon Design System) ====================
COLOR_BG_APP = "#F8FAFD"
COLOR_SIDEBAR = "#FFFFFF"
COLOR_CARD = "#FFFFFF"
COLOR_CARD_SUBTLE = "#F8FAFC"
COLOR_BORDER = "#E3E8EF"
COLOR_BORDER_SUBTLE = "#EDF2F7"
COLOR_BORDER_FOCUS = "#1A73E8"

COLOR_TEXT_PRIMARY = "#1E1F20"
COLOR_TEXT_SECONDARY = "#3C4043"
COLOR_TEXT_MUTED = "#5F6368"
COLOR_TEXT_DISABLED = "#9AA0A6"

COLOR_ACCENT = "#1E1F20"
COLOR_ACCENT_BLUE = "#1A73E8"
COLOR_ACCENT_BG = "#F0F4F9"

COLOR_SUCCESS = "#0F9D58"
COLOR_SUCCESS_BG = "#ECFDF5"
COLOR_WARNING = "#F59E0B"
COLOR_WARNING_BG = "#FFFBEB"
COLOR_DANGER = "#EA4335"
COLOR_DANGER_BG = "#FEF2F2"

COLOR_HOVER = "#F0F4F9"
COLOR_DISABLED = "#E3E8EF"

COLOR_SIDEBAR_TEXT = "#5F6368"
COLOR_SIDEBAR_ACTIVE = "#1E1F20"
COLOR_SIDEBAR_ACTIVE_BG = "#F0F4F9"
COLOR_SIDEBAR_DIVIDER = "#E3E8EF"

COLOR_OMNIBOX_BG = "#F0F4F9"
COLOR_OMNIBOX_BG_FOCUS = "#FFFFFF"
COLOR_OMNIBOX_SURFACE = "#F1ECFF"
COLOR_OMNIBOX_BORDER = "#C9B8F7"
COLOR_DRAG_HIGHLIGHT = "#EFF6FF"
COLOR_DRAG_NORMAL = "#F0F4F9"

COLOR_GENERATION_ACCENT = "#6F55E8"
COLOR_GENERATION_ACCENT_HOVER = "#5F43D2"
COLOR_GENERATION_ACCENT_BG = "#F4F1FF"
COLOR_GENERATION_BORDER = "#DED7FA"

COLOR_TOPIC_DIALOG_BG = "#F6F7FB"
COLOR_TOPIC_CARD_SELECTED = "#F5F3FF"
COLOR_TOPIC_CARD_HOVER = "#FAFAFC"
COLOR_TOPIC_CONTROL = "#ECEFF4"


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

SUPPORTED_PLATFORMS_HINT = (
    "支持 ChatGPT · Codex · DeepSeek · 豆包 · Gemini · Kimi · 通义千问 · Grok"
)


# ==================== 平台智能识别 ====================
_PLATFORM_BADGES: tuple[tuple[tuple[str, ...], str, str, str], ...] = (
    (("chat.deepseek.com", "deepseek.com"), "DeepSeek", "#1D4ED8", "#EFF6FF"),
    (("doubao.com", "www.doubao.com"), "豆包 Doubao", "#0369A1", "#F0F9FF"),
    (("gemini.google.com", "share.gemini.google"), "Google Gemini", "#4F46E5", "#EEF2FF"),
    (("kimi.com", "www.kimi.com", "kimi.moonshot.cn"), "Kimi", "#0F766E", "#F0FDFA"),
    (("qianwen.com", "www.qianwen.com", "qianwen.my.cn", "tongyi.aliyun.com"), "通义千问", "#6D28D9", "#F5F3FF"),
    (("grok.com", "www.grok.com", "x.com"), "Grok", "#1E293B", "#F1F5F9"),
)


def detect_platform_badge(url: str) -> tuple[str, str, str] | None:
    """根据输入 URL 识别目标 AI 平台，返回 (平台显示名, 前景色, 背景色)。"""
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if host in {"chatgpt.com", "chat.openai.com"}:
        if path.startswith("/s/cx_") or "/codex/" in path:
            return ("OpenAI Codex", "#7C3AED", "#F5F3FF")
        return ("ChatGPT", "#047857", "#ECFDF5")
    for hosts, label, fg, bg in _PLATFORM_BADGES:
        if host in hosts or any(host.endswith("." + h) for h in hosts):
            return (label, fg, bg)
    return ("网页链接", COLOR_TEXT_SECONDARY, COLOR_ACCENT_BG)


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


def configure_argon_ttk_style(master: tk.Misc | None = None) -> ttk.Style | None:
    """配置统一的 TTK 控件主题样式，使模态窗中的 ttk 控件与自绘扁平风格协调。"""
    if master is not None and not isinstance(master, tk.Misc):
        return None
    try:
        style = ttk.Style(master)
        style.configure(
            "TFrame",
            background=COLOR_TOPIC_DIALOG_BG,
        )
        style.configure(
            "TLabel",
            background=COLOR_TOPIC_DIALOG_BG,
            foreground=COLOR_TEXT_SECONDARY,
            font=FONT_SMALL,
        )
        style.configure(
            "TButton",
            font=FONT_BODY_BOLD,
            padding=(12, 6),
        )
        style.configure(
            "TEntry",
            padding=(8, 6),
        )
        return style
    except Exception:
        return None
