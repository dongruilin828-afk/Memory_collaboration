"""AI 记忆总结协同管理工具 - Argon 极简扁平桌面端主控制器。

架构分层：
- ``gui.theme``：设计系统令牌（色彩、字体层级、文案常量、平台智能识别、几何与图标辅助）
- ``gui.widgets``：自绘 Canvas/Frame 复合控件库（胶囊控制台、毛玻璃侧栏、平滑进度条、卡片与提示组件）
- ``gui.app``：主界面编排、响应式几何引擎、前后端异步任务桥接与模态交互流

保留所有原有功能与对外契约（公开方法名、属性名、回调签名与测试导出符号完全兼容）。
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import subprocess
import sys
import threading
import time
import warnings
import uuid
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

from gui.credential_store import CredentialStoreError, WindowsCredentialStore, is_custom_provider
from gui.history_store import HistoryStore, HistoryStoreError
from gui.run_logging import GenerationRunLog

warnings.filterwarnings("ignore", category=SyntaxWarning, module=r"^gui\.service$")
from gui.service import (
    MODE_FILENAME_SUFFIXES,
    build_document_asset_directory,
    build_image_asset_directory,
    build_output_paths,
    default_output_filename,
    fetch_chat_pipeline,
    generate_output_bundle,
    normalize_markdown_filename,
    requires_authenticated_browser,
)
from gui.settings_store import (
    AppSettings,
    SettingsStoreError,
    WindowsAppSettingsStore,
    default_app_settings,
)
from gui.theme import (
    AUTH_NOT_REQUIRED_LABEL,
    AUTH_REUSE_LABEL,
    COLOR_ACCENT,
    COLOR_ACCENT_BG,
    COLOR_ACCENT_BLUE,
    COLOR_BG_APP,
    COLOR_BORDER,
    COLOR_BORDER_FOCUS,
    COLOR_CARD,
    COLOR_DANGER,
    COLOR_DRAG_HIGHLIGHT,
    COLOR_GENERATION_ACCENT,
    COLOR_GENERATION_ACCENT_BG,
    COLOR_HOVER,
    COLOR_OMNIBOX_BG,
    COLOR_OMNIBOX_SURFACE,
    COLOR_SIDEBAR,
    COLOR_SIDEBAR_DIVIDER,
    COLOR_SUCCESS,
    COLOR_TEXT_DISABLED,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_TOPIC_DIALOG_BG,
    DIRECT_SUMMARY_FILE_TYPES,
    DIRECT_SUMMARY_MAX_BYTES,
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_FAMILY,
    FONT_H2,
    FONT_HERO,
    FONT_SIDEBAR_TITLE,
    FONT_SMALL,
    FONT_SMALL_BOLD,
    FONT_TINY,
    FONT_TITLE,
    GENERATE_BUTTON_LABEL,
    GENERATION_SOURCE_LABELS,
    REGENERATE_BUTTON_LABEL,
    SETTINGS_SECTION_PADX,
    SETTINGS_PANEL_PADX,
    SETTINGS_PAGE_PADX,
    _logo_png_path,
    _navigation_icon_path,
    _round_rectangle,
)
from gui.ui_dispatch import UIDispatcher, bind_visible_modal
from gui.widgets import (
    FlatButton,
    FlatEntryBox,
    FlatProgressBar,
    GenerationChoiceCard,
    GenerationSegmentOption,
    GlassCapsulePanel,
    GlassNavigationItem,
    HorizontalFileList,
    HistoryTaskCard,
    HoverTooltip,
    MinimalScrollbar,
    SettingsSegmentedTabs,
    StackedLayersIcon,
    SummaryTopicCard,
)


# ==================== 输出目标询问与直接总结工具函数 ====================


def _format_fetch_warnings(warnings: list[str]) -> str:
    """把抓取警告整理为任务完成后的用户提示。"""
    return "文件已正常生成，但抓取存在以下情况：\n\n" + "\n".join(
        f"• {warning}" for warning in warnings
    )


def _prompt_output_target(
    parent: tk.Misc,
    modes: dict[str, bool],
    settings: AppSettings,
    suggested_name: str | None = None,
) -> tuple[Path, str] | None:
    """询问结果名称；生成时会在所选位置创建同名结果文件夹。"""
    suggested_name = suggested_name or default_output_filename(modes)
    if settings.default_results_dir is not None:
        chosen_name = simpledialog.askstring(
            "设置保存名称",
            "请输入本次结果文件夹的名称：",
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
            "请选择保存位置并设置结果名称"
            if sum(bool(value) for value in modes.values()) == 1
            else "请选择保存位置并设置结果名称（文件将自动添加模式后缀）"
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


# ==================== 主 GUI 控制器 ====================


class AIMemoryGUI:
    """AI 记忆总结协同管理工具主界面（Argon 极简扁平侧栏版）。

    保留所有公开方法签名与属性名以兼容测试与服务层契约。
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self._responsive_after_id = None
        self._responsive_window_size = None
        self._resize_in_progress = False
        self._responsive_target_size = None
        self._responsive_scale = 1.0
        self._responsive_fonts_initialized = False
        self._scrollregion_after_id = None
        self._minimum_layout_after_id = None
        self._scrollregion = None
        self._gradient_item_id = None
        self._content_max_width = 1280
        self._responsive_layout_initialized = False
        self.layout_requires_wider_screen = False
        self._cancel_api_reorder_animation = None
        self._notice_after_id = None
        self._completed_badge_after_id = None
        self._history_viewport_after_id = None
        self._history_slots = []
        self._history_slots_ready = False

        root.title("AI 记忆总结协同管理工具")
        root.geometry("1040x680")
        root.minsize(820, 560)
        root.configure(bg=COLOR_BG_APP)
        self._window_icon = tk.PhotoImage(file=str(_logo_png_path(64)))
        root.iconphoto(True, self._window_icon)

        self.is_running = False
        self._generation_cancel_event = threading.Event()
        self._generation_completed = False
        self._generation_progress_reset = False
        self.selected_summary_file: Path | None = None
        self._generation_url_available = False
        self._generation_sources_formed = False
        self.credential_store = WindowsCredentialStore()
        self.settings_store = WindowsAppSettingsStore()
        try:
            self.app_settings = self.settings_store.load()
        except (SettingsStoreError, Exception):
            self.app_settings = default_app_settings()

        self.history_store = HistoryStore(self.app_settings.history_file)
        try:
            self.history_records = self.history_store.load()
        except HistoryStoreError:
            self.history_records = []

        self._settings_dialog = None
        self._api_key_dialog = None
        self._settings_load_error = None

        self._build_ui()
        self._refresh_history_list()
        self._update_generate_button_state()
        self._ui_dispatcher = UIDispatcher(root)
        self._post_ui = self._ui_dispatcher.post

    # ---------------- UI 构建 ----------------

    def _build_ui(self):
        top = tk.Frame(self.root, bg=COLOR_BG_APP)
        top.pack(fill=tk.BOTH, expand=True)

        # ===== 左侧任务栏（白底 + 图标导航） =====
        sidebar = tk.Frame(
            top, bg=COLOR_SIDEBAR, width=1,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
        )
        self.sidebar = sidebar
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # Logo + 标题
        header = tk.Frame(sidebar, bg=COLOR_SIDEBAR, padx=12, pady=24)
        header.pack(fill=tk.X)
        self._sidebar_header = header
        logo_row = tk.Frame(header, bg=COLOR_SIDEBAR)
        logo_row.pack(fill=tk.X)
        StackedLayersIcon(
            logo_row, width=40, height=40, bg=COLOR_SIDEBAR,
        ).pack(side=tk.LEFT)
        self.sidebar_title_label = tk.Label(
            logo_row, text="AI 记忆协同管理", font=FONT_SIDEBAR_TITLE,
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_SIDEBAR, anchor="w",
        )
        self.sidebar_title_label.pack(side=tk.LEFT, padx=(4, 0))

        tk.Frame(
            sidebar, bg=COLOR_SIDEBAR_DIVIDER, height=1,
        ).pack(fill=tk.X, padx=12, pady=(16, 10))

        # 主导航（图标 + 居中标题）
        nav = tk.Frame(sidebar, bg=COLOR_SIDEBAR, padx=8, pady=4)
        nav.pack(fill=tk.BOTH, expand=True)
        self._sidebar_navigation = nav

        self._nav_steps = [
            ("💬", "首页"),
            ("📑", "生成"),
            ("🕒", "历史"),
            ("⚙️", "设置"),
        ]
        self._nav_items: list[GlassNavigationItem] = []
        for idx, (icon, title) in enumerate(self._nav_steps):
            item = GlassNavigationItem(nav, icon, title)
            item.pack(fill=tk.X, pady=3)
            self._nav_items.append(item)
            item.bind("<Button-1>", lambda _e, i=idx: self._show_page(i))

        # 保留 api_key_button 契约：指向设置导航项（测试依赖此属性存在）
        self.api_key_button = self._nav_items[-1]

        # 底部：版本信息
        footer = tk.Frame(sidebar, bg=COLOR_SIDEBAR, padx=12, pady=12)
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        self._sidebar_footer = footer
        tk.Frame(
            footer, bg=COLOR_SIDEBAR_DIVIDER, height=1,
        ).pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            footer, text="AI 记忆协同管理 v1.0", font=FONT_TINY,
            fg=COLOR_TEXT_MUTED, bg=COLOR_SIDEBAR, anchor="w",
        ).pack(fill=tk.X)

        # ===== 右侧主内容区 =====
        main = tk.Frame(top, bg=COLOR_BG_APP)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.bg_canvas = tk.Canvas(
            main, highlightthickness=0, bg=COLOR_BG_APP,
        )
        self.bg_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.custom_scrollbar = MinimalScrollbar(
            main, target_canvas=self.bg_canvas, width=6,
        )
        self.custom_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=20)
        self.bg_canvas.config(yscrollcommand=self._on_canvas_scroll)

        self.main_content = tk.Frame(self.bg_canvas, bg=COLOR_BG_APP)
        self.canvas_window_id = self.bg_canvas.create_window(
            0, 0, window=self.main_content, anchor="nw",
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
        self.root.bind("<Return>", self._on_generate_shortcut, add="+")
        self.root.bind("<KP_Enter>", self._on_generate_shortcut, add="+")
        for idx in range(4):
            self.root.bind(
                f"<Control-Key-{idx + 1}>",
                lambda _e, page_idx=idx: self._show_page(page_idx),
                add="+",
            )
        # The toplevel's normal bind tag also receives every descendant's
        # Configure event. A private tag observes only the actual window.
        geometry_tag = f"WindowGeometry{id(self)}"
        self.root.bindtags((geometry_tag, *self.root.bindtags()))
        self.root.bind_class(geometry_tag, "<Configure>", self._on_root_configure)
        self.root.bind("<Destroy>", self._cancel_pending_ui_callbacks, add="+")
        self.root.after_idle(self._initialize_responsive_layout)

    def _cancel_pending_ui_callbacks(self, event):
        if event.widget is not self.root:
            return
        pending = [
            self._responsive_after_id,
            self._scrollregion_after_id,
            self._minimum_layout_after_id,
            self._notice_after_id,
            self._completed_badge_after_id,
            self._history_viewport_after_id,
        ]
        if self.page_frames:
            animation = getattr(self.page_frames[3], "api_animation", {})
            pending.append(animation.get("after_id"))
        pending.extend(item._animation_id for item in self._nav_items)
        for after_id in pending:
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass

    def _initialize_responsive_layout(self):
        if not self.root.winfo_exists():
            return
        self._apply_responsive_scale(force=True)

    def _update_sidebar_width(self):
        title_width = self._sidebar_header.winfo_reqwidth()
        footer_width = self._sidebar_footer.winfo_reqwidth()
        nav_right = max(
            (
                (item.bbox("content") or (0, 0, 0, 0))[2]
                for item in self._nav_items
            ),
            default=0,
        )
        nav_width = nav_right + 2 * int(self._sidebar_navigation.cget("padx")) + 2
        self.sidebar.configure(width=max(210, title_width, footer_width, nav_width))

    def _schedule_responsive_minimums(self):
        if self._minimum_layout_after_id is None:
            self._minimum_layout_after_id = self.root.after_idle(
                self._refresh_responsive_minimums,
            )

    def _refresh_responsive_minimums(self):
        self._minimum_layout_after_id = None
        if not self.root.winfo_exists() or self.root.state() in {"iconic", "withdrawn"}:
            return

        left_width = max(
            self._generation_mode_panel.winfo_reqwidth(),
            self._generation_auth_panel.winfo_reqwidth(),
        )
        right_width = self._generation_task_panel.winfo_reqwidth()
        self._generation_workspace.grid_columnconfigure(
            0, weight=3, minsize=left_width,
        )
        self._generation_workspace.grid_columnconfigure(
            1, weight=1, minsize=right_width,
        )
        self._generation_right_column.configure(width=right_width)
        self._update_sidebar_width()
        self.root.update_idletasks()

        settings_page = self.page_frames[3]
        api_rows = getattr(settings_page, "api_row_refs", {})
        # Include page, section, panel/border and API-page padding; placed rows
        # do not contribute their requested width to their ancestors.
        api_width = (max(row.winfo_reqwidth() for row in api_rows.values())
                     + 2 * (24 + SETTINGS_SECTION_PADX + SETTINGS_PANEL_PADX
                            + 1 + SETTINGS_PAGE_PADX)) if api_rows else 0
        if api_rows and not settings_page._drag_state["active"]:
            settings_page._layout_api_rows()
        required_content_width = max(self._generation_section.winfo_reqwidth() + 104, api_width)
        self._content_max_width = max(1280, required_content_width)
        chrome_width = self.custom_scrollbar.winfo_reqwidth() + 4
        min_width = max(
            880,
            self.sidebar.winfo_width() + chrome_width
            + required_content_width + 16,
        )
        screen_width = self.root.winfo_screenwidth()
        available_width = max(1, screen_width - 32)
        self.layout_requires_wider_screen = min_width > available_width
        self.minimum_window_width = min_width
        current_width = self.root.winfo_width()
        if current_width < min_width:
            self._responsive_target_size = (min_width, max(560, self.root.winfo_height()))
        if self.root.minsize() != (min_width, 560):
            self.root.minsize(min_width, 560)

        if not self._responsive_layout_initialized:
            target_width = max(current_width, min_width + 48)
            if min_width <= available_width:
                target_width = min(target_width, available_width)
            target_height = max(680, self.root.winfo_height())
            self._responsive_target_size = (target_width, target_height)
            self.root.geometry(f"{target_width}x{target_height}")
            self._responsive_layout_initialized = True
        elif current_width < min_width:
            self._responsive_target_size = (min_width, max(560, self.root.winfo_height()))
            self.root.geometry(
                f"{min_width}x{max(560, self.root.winfo_height())}",
            )
        self._schedule_scrollregion()

    def _on_root_configure(self, event):
        if event.widget is not self.root:
            return
        if self.root.state() in {"iconic", "withdrawn"}:
            self._responsive_window_size = None
            return
        size = (event.width, event.height)
        if size == self._responsive_window_size:
            return
        self._responsive_window_size = size
        self._resize_in_progress = True
        # Batch scroll extents while Configure updates visible geometry directly.
        self._schedule_scrollregion()
        if self._responsive_after_id is not None:
            self.root.after_cancel(self._responsive_after_id)
        if size == self._responsive_target_size:
            self._responsive_target_size = None
            self._responsive_after_id = self.root.after(1, self._apply_responsive_scale)
            return
        self._responsive_after_id = self.root.after(140, self._apply_responsive_scale)

    def _apply_responsive_scale(self, force=False):
        if self._responsive_after_id is not None:
            self.root.after_cancel(self._responsive_after_id)
        self._responsive_after_id = None
        self._resize_in_progress = False
        if self.root.state() in {"iconic", "withdrawn"}:
            return
        width = self.root.winfo_width()
        if width <= 1:
            return
        # Tk already scales fonts for the display DPI. Window resizing changes
        # layout space, not the font size of every widget (including hidden pages).
        scale = 1.0
        if (self._responsive_fonts_initialized
                and abs(scale - self._responsive_scale) < 0.01 and not force):
            if not self._responsive_layout_initialized:
                self._schedule_responsive_minimums()
            self._schedule_scrollregion()
            return
        self._responsive_scale = scale

        def visit(widget):
            if widget is not self.sidebar_title_label:
                resize = getattr(widget, "set_responsive_scale", None)
                if resize:
                    resize(scale)
                else:
                    try:
                        font = getattr(widget, "_responsive_font", None)
                        if font is None:
                            font_spec = widget.cget("font")
                            if not font_spec:
                                raise tk.TclError
                            font = tkfont.Font(master=widget, font=font_spec)
                            base_font_size = abs(int(font.actual("size")))
                            # Custom controls may expose a font for measurement
                            # without accepting configure(font=...). Only keep
                            # the resize state after configuration succeeds.
                            widget.configure(font=font)
                            widget._responsive_font = font
                            widget._responsive_base_font_size = base_font_size
                            widget._responsive_font_size = base_font_size
                        minimum = getattr(widget, "_responsive_min_font_size", 7)
                        maximum = getattr(widget, "_responsive_max_font_size", 22)
                        font_size = max(
                            minimum,
                            min(maximum, round(widget._responsive_base_font_size * scale)),
                        )
                        if font_size != widget._responsive_font_size:
                            font.configure(size=font_size)
                            widget._responsive_font_size = font_size
                    except (tk.TclError, TypeError, ValueError):
                        pass
            for child in widget.winfo_children():
                visit(child)

        visit(self.root)
        self._responsive_fonts_initialized = True
        self._update_sidebar_width()
        self._schedule_responsive_minimums()
        self._schedule_scrollregion()

    def _show_page(self, idx: int):
        """切换分层页面：隐藏全部，仅显示指定页；同步侧栏高亮。"""
        if not (0 <= idx < len(self.page_frames)):
            return
        if self._current_page == 3 and idx != 3 and self._cancel_api_reorder_animation:
            self._cancel_api_reorder_animation()
        self._current_page = idx
        for i, page in enumerate(self.page_frames):
            if i == idx:
                page.pack(fill=tk.BOTH, expand=True, padx=24, pady=24)
                page.lift()
            else:
                page.pack_forget()
        for i, item in enumerate(self._nav_items):
            item.set_active(i == idx)
        self.bg_canvas.yview_moveto(0)
        self._schedule_history_viewport()
        self._schedule_scrollregion()

    def _focus_home_input(self):
        """首页布局就绪后允许直接输入，同时避免切页后抢走焦点。"""
        if self._current_page == 0 and self.capsule_entry.entry.winfo_viewable():
            self.capsule_entry.entry.focus_set()

    def _refresh_scrollregion(self):
        self._scrollregion_after_id = None
        if self.root.state() in {"iconic", "withdrawn"}:
            return
        canvas_width = self.bg_canvas.winfo_width()
        self._draw_vibrant_gradient(canvas_width, self.bg_canvas.winfo_height())
        self._fit_content_to_canvas(canvas_width, self.bg_canvas.winfo_height())
        bb = self.bg_canvas.bbox("all")
        if bb and bb != self._scrollregion:
            self._scrollregion = bb
            self.bg_canvas.configure(scrollregion=bb)

    def _fit_content_to_canvas(self, canvas_width, canvas_height):
        """Apply cheap geometry immediately, including in Windows' resize loop."""
        content_width = min(canvas_width, self._content_max_width)
        content_height = max(
            canvas_height, self.main_content.winfo_reqheight(),
        )
        current_height = int(float(self.bg_canvas.itemcget(
            self.canvas_window_id, "height",
        )))
        current_width = int(float(self.bg_canvas.itemcget(
            self.canvas_window_id, "width",
        )))
        content_x = max(0, (canvas_width - content_width) // 2)
        if self.bg_canvas.coords(self.canvas_window_id) != [content_x, 0]:
            self.bg_canvas.coords(
                self.canvas_window_id, content_x, 0,
            )
        if current_width != content_width or current_height != content_height:
            self.bg_canvas.itemconfig(
                self.canvas_window_id,
                width=content_width, height=content_height,
            )

    def _schedule_scrollregion(self):
        if self._scrollregion_after_id is None:
            self._scrollregion_after_id = self.root.after(
                16, self._refresh_scrollregion,
            )

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
        StackedLayersIcon(
            welcome, width=64, height=64, bg=COLOR_BG_APP,
        ).pack()
        self.home_title_label = tk.Label(
            welcome, text="AI 记忆协同管理", font=FONT_HERO,
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP,
        )
        self.home_title_label._responsive_min_font_size = 24
        self.home_title_label._responsive_max_font_size = 30
        self.home_title_label.pack(pady=(12, 4))
        self.home_subtitle_label = tk.Label(
            welcome, text="让对话更连续，让知识可复用",
            font=(FONT_FAMILY, 14), fg=COLOR_TEXT_MUTED, bg=COLOR_BG_APP,
        )
        self.home_subtitle_label._responsive_min_font_size = 13
        self.home_subtitle_label._responsive_max_font_size = 15
        self.home_subtitle_label.pack()

        # ===== 统一 Omnibox 卡片（居中） =====
        omnibox = GlassCapsulePanel(center, bg_parent=COLOR_BG_APP)
        omnibox.pack(fill=tk.X, padx=52, pady=(28, 0))
        self._omnibox = omnibox
        omnibox_body = omnibox.content

        # 文件胶囊区（默认隐藏，文件附加后显示）
        self.selected_file_row = tk.Frame(omnibox_body, bg=COLOR_OMNIBOX_SURFACE)
        self.selected_file_row.pack(fill=tk.X, pady=(0, 10))
        self.selected_file_row.pack_forget()
        self.selected_file_name_var = tk.StringVar(value="")
        file_capsule = tk.Frame(
            self.selected_file_row, bg="#FFFFFF",
            padx=10, pady=4,
            highlightthickness=1, highlightbackground="#DDD6FE",
        )
        file_capsule.pack(side=tk.LEFT, fill=tk.X, expand=True)
        selected_file_name = tk.Label(
            file_capsule, textvariable=self.selected_file_name_var,
            font=(FONT_FAMILY, 11), fg=COLOR_TEXT_PRIMARY, bg="#FFFFFF",
            anchor="w", width=56,
        )
        selected_file_name._responsive_min_font_size = 11
        selected_file_name._responsive_max_font_size = 12
        self.selected_file_label = selected_file_name
        self._selected_file_tooltip = HoverTooltip(selected_file_name, "")
        self.clear_file_button = tk.Button(
            file_capsule, text="✕",
            command=self._clear_summary_file,
            font=(FONT_FAMILY, 11, "bold"), bg="#FFFFFF", fg=COLOR_DANGER,
            activebackground="#FEF2F2", activeforeground=COLOR_DANGER,
            relief=tk.FLAT, bd=0, cursor="hand2",
            padx=4, pady=0,
        )
        self.clear_file_button._responsive_min_font_size = 10
        self.clear_file_button._responsive_max_font_size = 12
        self.clear_file_button.pack(side=tk.RIGHT, padx=(6, 0))
        selected_file_name.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 自适应文本输入区
        self.capsule_entry = FlatEntryBox(
            omnibox_body, on_change=self._on_url_changed,
            bg_parent=COLOR_OMNIBOX_SURFACE,
            placeholder="粘贴或拖拽文件/链接",
        )
        self.capsule_entry.pack(fill=tk.X)
        self.capsule_entry.entry.bind("<Return>", self._on_omnibox_send)
        self.capsule_entry.entry.bind(
            "<Map>", lambda _event: self.root.after_idle(self._focus_home_input),
        )

        # ===== 底部微型工具栏 =====
        toolbar = tk.Frame(omnibox_body, bg=COLOR_OMNIBOX_SURFACE)
        toolbar.pack(fill=tk.X, pady=(2, 0))

        # 左下角：添加文件 + 粘贴链接
        toolbar_left = tk.Frame(toolbar, bg=COLOR_OMNIBOX_SURFACE)
        toolbar_left.pack(side=tk.LEFT)
        self._omnibox_toolbar_left = toolbar_left

        icon_pixels = 12 * float(self.root.tk.call("tk", "scaling"))
        icon_size = min((24, 32, 48), key=lambda size: abs(size - icon_pixels))
        self._attachment_icon = tk.PhotoImage(
            file=str(_navigation_icon_path("paperclip-outline", icon_size)),
        )
        self.file_select_button = tk.Button(
            toolbar_left, text=" 添加文件",
            image=self._attachment_icon, compound=tk.LEFT,
            command=self._choose_summary_file,
            font=(FONT_FAMILY, 12), bg=COLOR_OMNIBOX_SURFACE, fg="#4B5563",
            activebackground=COLOR_OMNIBOX_SURFACE, activeforeground="#1E293B",
            relief=tk.FLAT, bd=0, cursor="hand2",
            padx=8, pady=4,
        )
        self.file_select_button._responsive_min_font_size = 11
        self.file_select_button._responsive_max_font_size = 13
        self.file_select_button.pack(side=tk.LEFT, padx=(0, 16))

        self.paste_link_button = tk.Button(
            toolbar_left, text="🔗 粘贴链接",
            command=self._paste_clipboard_to_entry,
            font=(FONT_FAMILY, 12), bg=COLOR_OMNIBOX_SURFACE, fg="#4B5563",
            activebackground=COLOR_OMNIBOX_SURFACE, activeforeground="#1E293B",
            relief=tk.FLAT, bd=0, cursor="hand2",
            padx=8, pady=4,
        )
        self.paste_link_button._responsive_min_font_size = 11
        self.paste_link_button._responsive_max_font_size = 13
        self.paste_link_button.pack(side=tk.LEFT)

        # 右下角：发送按钮
        toolbar_right = tk.Frame(toolbar, bg=COLOR_OMNIBOX_SURFACE)
        toolbar_right.pack(side=tk.RIGHT)

        self.btn_send = tk.Button(
            toolbar_right, text="→",
            command=self._on_omnibox_send,
            font=(FONT_FAMILY, 22, "bold"), bg=COLOR_OMNIBOX_SURFACE,
            fg="#FFFFFF",
            activebackground=COLOR_OMNIBOX_SURFACE, activeforeground=COLOR_ACCENT_BLUE,
            relief=tk.FLAT, bd=0, cursor="arrow",
            width=4, pady=0, highlightthickness=0,
        )
        self.btn_send._responsive_min_font_size = 20
        self.btn_send._responsive_max_font_size = 25
        self.btn_send.pack(side=tk.RIGHT)
        self.btn_send.bind("<Enter>", self._on_send_hover)
        self.btn_send.bind("<Leave>", self._on_send_leave)
        self._update_send_button_state()

        # 配置拖拽到整个 Omnibox
        self._configure_file_drop()

        self.batch_capture_button = tk.Button(
            center, text="批量抓取多个链接", command=self._show_batch_capture_dialog,
            font=(FONT_FAMILY, 11), bg=COLOR_BG_APP, fg=COLOR_ACCENT_BLUE,
            activebackground=COLOR_BG_APP, relief=tk.FLAT, cursor="hand2", pady=8,
        )
        self.batch_capture_button.pack(pady=(8, 0))

        # 底部呼吸留白
        spacer = tk.Frame(center, bg=COLOR_BG_APP, height=80)
        spacer.pack(fill=tk.BOTH, expand=True)

    def _show_batch_capture_dialog(self):
        if self.is_running:
            messagebox.showinfo("任务正在运行", "请等待当前任务完成或停止后再开始批量抓取。", parent=self.root)
            return
        previous = getattr(self, "_batch_capture_dialog", None)
        if previous is not None and previous.winfo_exists():
            previous.lift()
            return
        from gui.batch_capture_dialog import BatchCaptureDialog
        self._batch_capture_dialog = BatchCaptureDialog(
            self.root, on_start=self._start_batch_capture,
            on_stop=lambda: self._generation_cancel_event.set(),
            initial_text=self.capsule_entry.get_text().strip(),
        )

    def _start_batch_capture(self, links, dialog, *, concurrency=3):
        if self.is_running:
            return False
        from datetime import datetime
        from uuid import uuid4
        from gui.batch_capture import capture_links

        current = self.app_settings
        settings = AppSettings(Path(current.runtime_data_dir), current.default_results_dir)
        parent = filedialog.askdirectory(
            parent=dialog, title="选择批量结果保存位置",
            initialdir=str(settings.default_results_dir or Path.home()),
        )
        if not parent:
            return False
        output = Path(parent) / f"批量抓取_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:6]}"
        self._generation_cancel_event = cancel_event = threading.Event()
        self.is_running = True
        self._set_inputs_locked(True)
        self._update_generate_button_state()

        def progress(index, total, message):
            self._post_ui(lambda text=f"[{index}/{total}] {message}": dialog.show_progress(text))

        def completed(record):
            if record["status"] != "completed":
                return
            elapsed = record["elapsed_seconds"]
            wait = record.get("wait_seconds", 0.0)
            history = dict(
                title=f"批量抓取 {record['index']:03d} · {record['platform']}",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), succeeded=True,
                program_seconds=max(0.0, elapsed - wait), fetch_seconds=max(0.0, elapsed - wait), generation_seconds=0.0,
                wait_seconds=wait, total_seconds=elapsed, file_count=len(record["saved_files"]),
                saved_files=record["saved_files"], output_dir=record["output_dir"],
            )
            self._post_ui(lambda: self._add_history_record(history))

        def run():
            try:
                records = asyncio.run(capture_links(
                    links, output, browser_profile_root=settings.browser_profile_dir,
                    concurrency=concurrency,
                    cancel_event=cancel_event, progress=progress, on_result=completed,
                    authorize_login=lambda page, url: self._await_batch_login(dialog, url),
                ))
                success = sum(record["status"] == "completed" for record in records)
                warnings = sum(bool(record["warnings"]) for record in records)
                failed = sum(record["status"] == "failed" for record in records)
                result = f"完成 {success}/{len(records)} 项，失败 {failed} 项，含警告 {warnings} 项。结果：{output}"
            except asyncio.CancelledError:
                result = f"已停止。已完成结果与各项状态保存在：{output}"
            except Exception as error:
                reason = (str(error).splitlines() or [type(error).__name__])[0]
                result = f"批量抓取失败：{reason}。详情和结果目录：{output}"
            self._post_ui(self._on_task_finished)
            self._post_ui(lambda: dialog.finish(result))

        threading.Thread(target=run, daemon=True).start()
        return True

    async def _await_batch_login(self, batch_dialog, url):
        loop = asyncio.get_running_loop()
        answered = loop.create_future()
        window = {"dialog": None}

        def reply(accepted):
            if answered.done() or loop.is_closed():
                return
            def complete():
                if not answered.done():
                    answered.set_result(accepted)
            try:
                loop.call_soon_threadsafe(complete)
            except RuntimeError:
                if not loop.is_closed():
                    raise

        def show():
            if not answered.done() and batch_dialog.winfo_exists():
                window["dialog"] = batch_dialog.request_login(url, reply)
            elif not answered.done():
                reply(False)

        def close():
            child = window["dialog"]
            if child is not None and child.winfo_exists():
                child.destroy()
            if batch_dialog.winfo_exists() and batch_dialog.winfo_viewable():
                batch_dialog.grab_set()

        self._post_ui(show, visible=True)
        try:
            return await answered
        finally:
            self._post_ui(close)

    def _on_omnibox_send(self, _event=None):
        """Omnibox 发送按钮：有链接或文件时进入生成配置页。"""
        if getattr(self, "_current_page", 0) == 1:
            return self._on_generate_shortcut(_event)
        url = self.capsule_entry.get_text().strip()
        has_file = self.selected_summary_file is not None
        if url or has_file:
            self._show_page(1)
        return "break"

    def _on_generate_shortcut(self, _event=None):
        """在生成配置页按 Enter 时触发当前可用的生成操作。"""
        if getattr(self, "_current_page", 0) != 1:
            return None
        if getattr(self, "is_running", False):
            return "break"
        button = getattr(self, "btn_generate", None)
        if button is not None and not getattr(button, "_enabled", True):
            return "break"
        self._on_start_generate()
        return "break"

    def _update_send_button_state(self):
        """根据输入内容更新发送按钮激活状态。"""
        url = self.capsule_entry.get_text() if hasattr(self, "capsule_entry") else ""
        has_file = getattr(self, "selected_summary_file", None) is not None
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
        """生成页：模式网格、任务摘要与统一执行栏。"""
        page = self.page_frames[1]
        page.configure(bg=COLOR_BG_APP)

        section = tk.Frame(page, bg=COLOR_BG_APP)
        section.pack(fill=tk.BOTH, expand=True, padx=28, pady=(16, 20))
        self._generation_section = section

        heading = tk.Frame(section, bg=COLOR_BG_APP)
        heading.pack(fill=tk.X, pady=(0, 14))
        heading_copy = tk.Frame(heading, bg=COLOR_BG_APP)
        heading_copy.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            heading_copy, text="生成记忆总结", font=(FONT_FAMILY, 20, "bold"),
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP, anchor="w",
        ).pack(fill=tk.X)
        self.generation_ready_badge = tk.Label(
            heading, text="  ●  待完善配置  ", font=FONT_SMALL_BOLD,
            fg=COLOR_TEXT_MUTED, bg=COLOR_ACCENT_BG, padx=8, pady=6,
        )
        self.generation_ready_badge.pack(side=tk.RIGHT, anchor="n", pady=2)

        workspace = tk.Frame(section, bg=COLOR_BG_APP)
        workspace.pack(fill=tk.X)
        self._generation_workspace = workspace
        card_width = 184
        workspace.grid_columnconfigure(0, weight=3, minsize=0)
        workspace.grid_columnconfigure(1, weight=1, minsize=0)
        workspace.grid_rowconfigure(0, weight=1)

        left_column = tk.Frame(workspace, bg=COLOR_BG_APP)
        left_column.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self._generation_left_column = left_column
        right_column = tk.Frame(workspace, bg=COLOR_BG_APP, width=210)
        right_column.grid(row=0, column=1, sticky="nsew")
        right_column.grid_propagate(False)
        self._generation_right_column = right_column

        mode_panel = tk.Frame(
            left_column, bg=COLOR_CARD, padx=0, pady=0,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
        )
        self._generation_mode_panel = mode_panel
        mode_panel.pack(fill=tk.X)
        mode_header = tk.Frame(
            mode_panel, bg="#F8FAFC", padx=20, pady=14,
        )
        mode_header.pack(fill=tk.X)
        self._generation_mode_title_label = tk.Label(
            mode_header, text="选择生成模式", font=FONT_TITLE,
            fg=COLOR_TEXT_PRIMARY, bg="#F8FAFC",
        )
        self._generation_mode_title_label._responsive_min_font_size = 16
        self._generation_mode_title_label._responsive_max_font_size = 20
        self._generation_mode_title_label.pack(side=tk.LEFT)
        self.generation_selection_var = tk.StringVar(value="已选 1 项")
        tk.Label(
            mode_header, textvariable=self.generation_selection_var,
            font=FONT_SMALL_BOLD, fg="#4F46E5", bg="#EEF2FF",
            padx=10, pady=2,
        ).pack(side=tk.RIGHT)

        tk.Frame(mode_panel, bg=COLOR_BORDER, height=1).pack(fill=tk.X)
        mode_grid = tk.Frame(mode_panel, bg=COLOR_CARD, padx=20)
        mode_grid.pack(fill=tk.X)
        mode_grid.grid_columnconfigure(0, weight=1)

        cards = (
            ("card_raw", "仅抓取对话", "保留原始问答，不调用 API。", "", False),
            ("card_normal", "结构化总结", "默认方式，支持选择不同话题重要程度", "", True),
            ("card_simple", "极简化总结", "压缩为一段极短的总览，快速掌握关键信息", "", False),
            ("card_detailed", "细节化总结", "保留更多细节信息", "", False),
        )
        for index, card_data in enumerate(cards):
            attr, title, subtitle, badge, checked = card_data
            card = GenerationChoiceCard(
                mode_grid, title=title, subtitle=subtitle,
                badge_text=badge,
                initial_checked=checked, on_toggle=self._on_mode_toggled,
                width=card_width, height=58,
                show_separator=index < len(cards) - 1,
            )
            card.grid(row=index, column=0, sticky="nsew")
            setattr(self, attr, card)

        auth_panel = tk.Frame(
            left_column, bg=COLOR_CARD, padx=12, pady=10,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
        )
        self._generation_auth_panel = auth_panel
        auth_panel.pack(fill=tk.X, pady=(12, 0))
        auth_copy = tk.Frame(auth_panel, bg=COLOR_CARD)
        auth_copy.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            auth_copy, text="访问方式", font=FONT_BODY_BOLD,
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD, anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            auth_copy, text="受限页面可切换为独立浏览器授权",
            font=FONT_TINY, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w",
        ).pack(fill=tk.X, pady=(3, 0))
        auth_switch = tk.Frame(auth_panel, bg="#F1F3F7", padx=2, pady=3)
        auth_switch.pack(side=tk.RIGHT)
        self.card_no_login = GenerationSegmentOption(
            auth_switch, text=AUTH_REUSE_LABEL, initial_checked=True,
            on_toggle=self._on_auth_toggled, width=94,
        )
        self.card_no_login.pack(side=tk.LEFT)
        self.card_need_login = GenerationSegmentOption(
            auth_switch, text="授权登录", initial_checked=False,
            on_toggle=self._on_auth_toggled, width=94,
        )
        self.card_need_login.pack(side=tk.LEFT)

        task_panel = tk.Frame(
            right_column, bg=COLOR_CARD, padx=15, pady=14,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
        )
        task_panel.pack(fill=tk.BOTH, expand=True)
        self._generation_task_panel = task_panel
        self._generation_task_title_label = tk.Label(
            task_panel, text="本次任务", font=(FONT_FAMILY, 12, "bold"),
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD, anchor="w",
        )
        self._generation_task_title_label._responsive_min_font_size = 11
        self._generation_task_title_label._responsive_max_font_size = 13
        self._generation_task_title_label.pack(fill=tk.X)
        source_box = tk.Frame(
            task_panel, bg="#F8FAFC", padx=11, pady=10,
            highlightthickness=1, highlightbackground="#E2E8F0",
        )
        source_box.pack(fill=tk.X, pady=(12, 12))
        self._generation_source_title_label = tk.Label(
            source_box, text="内容来源", font=FONT_BODY_BOLD,
            fg=COLOR_TEXT_PRIMARY, bg="#F8FAFC", anchor="center",
            justify=tk.CENTER,
        )
        self._generation_source_title_label._responsive_min_font_size = 10
        self._generation_source_title_label._responsive_max_font_size = 12
        self._generation_source_title_label.pack(fill=tk.X)
        source_switch = tk.Frame(source_box, bg="#F8FAFC")
        source_switch.pack(fill=tk.X, pady=(6, 0))
        self.card_source_url = GenerationSegmentOption(
            source_switch, text=GENERATION_SOURCE_LABELS["url"],
            initial_checked=False, on_toggle=self._on_generation_source_toggled,
            width=70, regular_font=FONT_BODY, bold_font=FONT_BODY_BOLD,
            min_font_size=9, max_font_size=12,
        )
        self.card_source_file = GenerationSegmentOption(
            source_switch, text=GENERATION_SOURCE_LABELS["file"],
            initial_checked=False, on_toggle=self._on_generation_source_toggled,
            width=70, regular_font=FONT_BODY, bold_font=FONT_BODY_BOLD,
            min_font_size=9, max_font_size=12,
        )

        self.generation_output_var = tk.StringVar(value="1 个 Markdown")
        self.generation_modes_var = tk.StringVar(value="结构化总结")
        self.generation_auth_var = tk.StringVar(value=AUTH_REUSE_LABEL)
        for label_text, value_var in (
            ("输出文件", self.generation_output_var),
            ("生成模式", self.generation_modes_var),
            ("访问方式", self.generation_auth_var),
        ):
            row = tk.Frame(task_panel, bg=COLOR_CARD)
            row.pack(fill=tk.X, pady=8)
            tk.Label(
                row, text=label_text, font=FONT_SMALL,
                fg=COLOR_TEXT_MUTED, bg=COLOR_CARD,
            ).pack(side=tk.LEFT)
            tk.Label(
                row, textvariable=value_var, font=FONT_SMALL_BOLD,
                fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD,
            ).pack(side=tk.RIGHT)

        run_panel = tk.Frame(
            section, bg=COLOR_GENERATION_ACCENT_BG, padx=16, pady=13,
            highlightthickness=1, highlightbackground="#DDD6FE",
        )
        run_panel.pack(fill=tk.X, pady=(14, 0))
        self._generation_run_panel = run_panel
        run_row = tk.Frame(run_panel, bg=COLOR_GENERATION_ACCENT_BG)
        run_row.pack(fill=tk.X)
        run_row.columnconfigure(1, weight=1)
        self._generation_run_row = run_row
        run_icon = tk.Canvas(
            run_row, width=20, height=20, bg=COLOR_GENERATION_ACCENT_BG,
            highlightthickness=0, bd=0,
        )
        _round_rectangle(
            run_icon, 1, 1, 19, 19, radius=6,
            fill="#EEF2FF", outline="#C7D2FE", width=1,
        )
        run_icon.create_oval(
            7, 7, 13, 13, fill=COLOR_GENERATION_ACCENT, outline="",
        )
        run_icon.grid(row=0, column=0, padx=(0, 10))
        status_copy = tk.Frame(run_row, bg=COLOR_GENERATION_ACCENT_BG)
        status_copy.grid(row=0, column=1, sticky="ew")
        self._generation_status_copy = status_copy
        self.status_var = tk.StringVar(value="所有配置已完成")
        self.status_label = tk.Label(
            status_copy, width=1,
            font=FONT_SMALL_BOLD, fg=COLOR_TEXT_PRIMARY,
            bg=COLOR_GENERATION_ACCENT_BG, anchor="w",
        )
        self.status_label.pack(fill=tk.X)
        self._generation_status_tooltip = HoverTooltip(self.status_label, self.status_var.get())

        def fit_status(_event=None):
            from scripts.api_config import middle_ellipsis
            message = self.status_var.get()
            self._generation_status_tooltip._text = message
            # Keep logs intact while the single-line display stays inside the
            # flexible text column. A long message must not resize the action.
            display = " ".join(message.splitlines())
            font = tkfont.Font(font=self.status_label.cget("font"))
            inset = sum(self.status_label.winfo_pixels(self.status_label.cget(option))
                        for option in ("padx", "borderwidth", "highlightthickness"))
            self.status_label.configure(text=middle_ellipsis(
                display, max(0, self.status_label.winfo_width() - 2 * inset), font.measure))

        status_trace = self.status_var.trace_add("write", lambda *_args: fit_status())
        self.status_label.bind("<Configure>", fit_status)
        self.status_label.bind(
            "<Destroy>", lambda _event: self.status_var.trace_remove("write", status_trace), add="+")
        fit_status()
        self.percent_var = tk.StringVar(value="")
        tk.Label(
            status_copy, textvariable=self.percent_var,
            font=FONT_TINY, fg=COLOR_TEXT_MUTED,
            bg=COLOR_GENERATION_ACCENT_BG, anchor="w", width=1,
        ).pack(fill=tk.X, pady=(3, 0))
        self.btn_generate = FlatButton(
            run_row, text=GENERATE_BUTTON_LABEL,
            command=self._on_start_generate,
            variant="accent", width=174, height=44,
            bg_parent=COLOR_GENERATION_ACCENT_BG,
        )
        self.btn_generate.grid(row=0, column=2, padx=(12, 0), sticky="e")
        self.progress_bar = FlatProgressBar(
            run_panel, height=5,
            bg_parent=COLOR_GENERATION_ACCENT_BG,
            fill_color=COLOR_GENERATION_ACCENT,
        )
        self.progress_bar.pack(fill=tk.X, pady=(10, 0))
        self.done_badge = tk.Label(
            run_panel, text="✓ 生成完成", font=FONT_SMALL_BOLD,
            fg=COLOR_SUCCESS, bg=COLOR_GENERATION_ACCENT_BG, anchor="w",
        )
        self._refresh_generation_sources()

    # ---------------- 历史页 ----------------

    def _build_history_section(self):
        """历史页：任务卡片列表 + 6 指标看板 + 定位跳转与记录管理。"""
        page = self.page_frames[2]
        page.configure(bg=COLOR_BG_APP)

        section = tk.Frame(page, bg=COLOR_BG_APP)
        section.pack(fill=tk.BOTH, expand=True, padx=80, pady=(24, 24))

        header_bar = tk.Frame(section, bg=COLOR_BG_APP)
        header_bar.pack(fill=tk.X)
        title_box = tk.Frame(header_bar, bg=COLOR_BG_APP)
        title_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            title_box, text="历史", font=(FONT_FAMILY, 18, "bold"),
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP, anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            title_box, text="查看历次任务的耗时统计与已生成文件",
            font=FONT_SMALL, fg=COLOR_TEXT_SECONDARY, bg=COLOR_BG_APP,
            anchor="w",
        ).pack(fill=tk.X, pady=(4, 0))

        header_actions = tk.Frame(header_bar, bg=COLOR_BG_APP)
        header_actions.pack(side=tk.RIGHT, anchor="center")
        self.history_count_var = tk.StringVar(value="")
        self.history_count_badge = tk.Label(
            header_actions, textvariable=self.history_count_var,
            font=FONT_SMALL_BOLD, fg="#4F46E5", bg="#EEF2FF",
            padx=12, pady=4,
        )
        self.history_count_badge.pack(side=tk.LEFT)

        tk.Frame(section, bg=COLOR_BG_APP, height=16).pack(fill=tk.X)

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

    def _add_history_record(self, record: dict):
        """任务完成后追加一条历史记录并刷新列表。"""
        self.history_records.insert(0, record)
        try:
            self.history_store.save(self.history_records)
        except HistoryStoreError as error:
            messagebox.showwarning(
                "历史记录保存失败",
                str(error),
                parent=self.root,
            )
        self._refresh_history_list()

    def _refresh_history_list(self):
        """重建历史卡片列表。"""
        if self._history_viewport_after_id is not None:
            self.root.after_cancel(self._history_viewport_after_id)
            self._history_viewport_after_id = None
        self._history_slots = []
        self._history_slots_ready = False
        for child in self.history_list_frame.winfo_children():
            child.destroy()

        count = len(self.history_records)
        if hasattr(self, "history_count_var"):
            self.history_count_var.set(f"共 {count} 条记录" if count else "0 条记录")

        if not self.history_records:
            self.history_empty_label = tk.Label(
                self.history_list_frame,
                text="暂无历史记录\n完成一次生成后，任务记录将在此显示",
                font=FONT_BODY, fg=COLOR_TEXT_MUTED, bg=COLOR_BG_APP,
                justify="center",
            )
            self.history_empty_label.pack(pady=(60, 0))
            self._apply_responsive_scale(force=True)
            return

        for record in self.history_records:
            slot = tk.Frame(self.history_list_frame, bg=COLOR_BG_APP)
            slot.pack(fill=tk.X)
            card = self._build_history_card(slot, record)
            self._history_slots.append((slot, card))
        self._apply_responsive_scale(force=True)
        self._schedule_history_viewport()

    def _on_canvas_scroll(self, first, last):
        self.custom_scrollbar.set_range(first, last)
        self._schedule_history_viewport()

    def _schedule_history_viewport(self):
        if self._history_slots and self._history_viewport_after_id is None:
            self._history_viewport_after_id = self.root.after(
                16, self._refresh_history_viewport,
            )

    def _refresh_history_viewport(self):
        """Keep offscreen history cards out of Tk's resize/layout/paint work."""
        self._history_viewport_after_id = None
        if not self._history_slots:
            return
        if not self._history_slots_ready:
            for slot, card in self._history_slots:
                slot.configure(height=card.winfo_reqheight() + 14)
                slot.pack_propagate(False)
            self._history_slots_ready = True
        list_y = (
            self.history_list_frame.winfo_rooty() - self.main_content.winfo_rooty()
        )
        top = self.bg_canvas.canvasy(0) - list_y
        bottom = top + self.bg_canvas.winfo_height()
        row_y = 0
        for slot, card in self._history_slots:
            row_height = int(slot.cget("height"))
            visible = (
                self._current_page == 2
                and row_y + row_height >= top - 160
                and row_y <= bottom + 160
            )
            if visible and not card.winfo_manager():
                card.pack(fill=tk.X, pady=7)
            elif not visible and card.winfo_manager():
                card.pack_forget()
            row_y += row_height

    def _build_history_card(self, parent: tk.Frame, record: dict):
        """Keep the static history dashboard on a single drawing surface."""
        card = HistoryTaskCard(parent, record, self._open_in_explorer)
        card.pack(fill=tk.X, pady=7)
        return card

    def _open_in_explorer(self, dir_path: str):
        """在系统文件管理器中打开目录。"""
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
        if self._gradient_item_id is None:
            self._gradient_item_id = self.bg_canvas.create_rectangle(
                0, 0, w, h, fill=COLOR_BG_APP, outline="", tags="gradient_bg",
            )
            self.bg_canvas.tag_lower(self._gradient_item_id)
        else:
            self.bg_canvas.coords(self._gradient_item_id, 0, 0, w, h)

    def _on_canvas_configure(self, event):
        # Native window resizing may delay timers. Fit the embedded frame in
        # this event; defer scroll extents and fonts, not the visible layout.
        self._fit_content_to_canvas(event.width, event.height)
        self._schedule_scrollregion()
        self._schedule_history_viewport()

    def _on_content_configure(self, _event):
        self._schedule_scrollregion()

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
                return "break"
            except tk.TclError:
                pass

        def on_pixelscroll(event):
            try:
                delta = getattr(event, "delta", 0)
                if delta == 0:
                    return
                self._smooth_scroll(-delta)
                return "break"
            except tk.TclError:
                pass

        self.root.bind_all("<MouseWheel>", on_wheel, add="+")
        try:
            self.root.bind_all("<PixelScroll>", on_pixelscroll, add="+")
        except tk.TclError:
            pass

    def _smooth_scroll(self, delta_px: int):
        """像素级平滑滚动：通过 yview_moveto 精确设置视口位置（兼容 Tk 8.6）。"""
        bb = self._scrollregion or self.bg_canvas.bbox("all")
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
        if getattr(self, "_generation_completed", False):
            self._reset_generation_for_new_input()
        self.selected_summary_file = Path(selected_path).resolve()
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
        tooltip = getattr(self, "_selected_file_tooltip", None)
        if tooltip:
            tooltip._text = str(self.selected_summary_file)
        self.file_select_button.config(text=" 重新添加")
        self.selected_file_row.pack(
            fill=tk.X, pady=(0, 8), before=self.capsule_entry,
        )
        self._refresh_generation_sources()
        self._update_send_button_state()
        self._update_generate_button_state()

    def _configure_file_drop(self):
        if not _HAS_DND:
            return
        try:
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
        tooltip = getattr(self, "_selected_file_tooltip", None)
        if tooltip:
            tooltip._text = ""
        self.selected_file_row.pack_forget()
        self.file_select_button.config(text=" 添加文件")
        self._refresh_generation_sources()
        self._update_send_button_state()
        self._update_generate_button_state()

    # ---------------- 模式与登录切换 ----------------

    def _refresh_generation_sources(self):
        if getattr(self, "is_running", False):
            return
        has_url = bool(self.capsule_entry.get_text().strip())
        has_file = self.selected_summary_file is not None
        url_became_available = (
            has_url and not getattr(self, "_generation_url_available", False)
        )
        first_dual_source = (
            has_url and has_file
            and not getattr(self, "_generation_sources_formed", False)
        )
        source = getattr(self, "generation_source", None)
        if source == "url" and not has_url:
            source = None
        elif source == "file" and not has_file:
            source = None
        if source is None:
            source = "url" if has_url else "file" if has_file else None
        elif first_dual_source and url_became_available and source == "file":
            source = "url"
        self.generation_source = source
        self._generation_url_available = has_url
        self._generation_sources_formed = (
            getattr(self, "_generation_sources_formed", False)
            or has_url and has_file
        )

        if source == "file" and self.card_raw.checked:
            self.card_raw.set_checked(False)
        source_options = (
            (self.card_source_url, "url", has_url),
            (self.card_source_file, "file", has_file),
        )
        for option, _key, _available in source_options:
            if option.winfo_manager() != "pack":
                option.pack(side=tk.LEFT, expand=True)
        for option, key, available in source_options:
            option.set_checked(source == key)
            option.set_disabled(self.is_running or not available)
        self.card_raw.set_disabled(self.is_running or source == "file")
        for attr in ("card_no_login", "card_need_login"):
            option = getattr(self, attr, None)
            if option is not None:
                option.set_disabled(self.is_running or source == "file")
        self._refresh_generation_summary()

    def _on_generation_source_toggled(self, selected_option):
        if getattr(self, "is_running", False):
            return
        self.generation_source = (
            "url" if selected_option is self.card_source_url else "file"
        )
        self._refresh_generation_sources()
        self._update_generate_button_state()

    def _refresh_generation_summary(self):
        """Keep the generation-page summary aligned with current choices."""
        mode_cards = (
            (getattr(self, "card_raw", None), "原始对话"),
            (getattr(self, "card_normal", None), "结构化总结"),
            (getattr(self, "card_simple", None), "极简化总结"),
            (getattr(self, "card_detailed", None), "细节化总结"),
        )
        selected_modes = [
            label for card, label in mode_cards
            if card is not None and getattr(card, "checked", False)
        ]
        selected_count = len(selected_modes)
        if hasattr(self, "generation_selection_var"):
            self.generation_selection_var.set(f"已选 {selected_count} 项")
        if hasattr(self, "generation_output_var"):
            self.generation_output_var.set(f"{selected_count} 个 Markdown")
        if hasattr(self, "generation_modes_var"):
            if not selected_modes:
                summary = "尚未选择"
            elif len(selected_modes) <= 2:
                summary = " / ".join(selected_modes)
            else:
                summary = f"{selected_modes[0]}等 {selected_count} 项"
            self.generation_modes_var.set(summary)
        if hasattr(self, "generation_auth_var"):
            need_login = getattr(
                getattr(self, "card_need_login", None), "checked", False,
            )
            source = getattr(self, "generation_source", None)
            if source == "file":
                auth_label = AUTH_NOT_REQUIRED_LABEL
            elif source == "url":
                auth_label = "授权登录" if need_login else AUTH_REUSE_LABEL
            else:
                auth_label = "未选择内容"
            self.generation_auth_var.set(auth_label)

    def _on_mode_toggled(self, _card=None):
        self._refresh_generation_summary()
        self._update_generate_button_state()

    def _on_auth_toggled(self, selected_card):
        if selected_card == self.card_no_login:
            self.card_need_login.set_checked(False)
        else:
            self.card_no_login.set_checked(False)
        self._refresh_generation_summary()
        self._update_generate_button_state()

    # ---------------- 输入锁定 ----------------

    def _set_inputs_locked(self, locked: bool):
        source = getattr(self, "generation_source", None)
        self.card_raw.set_disabled(locked or source == "file")
        self.card_normal.set_disabled(locked)
        self.card_simple.set_disabled(locked)
        self.card_detailed.set_disabled(locked)
        self.card_no_login.set_disabled(locked or source == "file")
        self.card_need_login.set_disabled(locked or source == "file")
        has_url = bool(
            self.capsule_entry.get_text().strip()
            if hasattr(self.capsule_entry, "get_text") else False
        )
        for attr, available in (
            ("card_source_url", has_url),
            ("card_source_file", getattr(self, "selected_summary_file", None) is not None),
        ):
            option = getattr(self, attr, None)
            if option is not None:
                option.set_disabled(locked or not available)
        try:
            self.api_key_button.config(state="normal", cursor="hand2")
        except tk.TclError:
            self.api_key_button.config(cursor="hand2")

    # ---------------- URL 变更检测 ----------------

    def _reset_generation_for_new_input(self):
        if getattr(self, "is_running", False):
            return
        if not getattr(self, "_generation_completed", False):
            return
        self._generation_completed = False
        self._generation_progress_reset = True
        self.progress_bar.reset()
        if getattr(self, "_completed_badge_after_id", None) is not None:
            try:
                self.root.after_cancel(self._completed_badge_after_id)
            except tk.TclError:
                pass
            self._completed_badge_after_id = None
        self.done_badge.pack_forget()

    def _on_url_changed(self):
        """URL 变更：发送按钮状态 + 私有链接检测 + 登录策略自动调整。"""
        if hasattr(self, "_update_send_button_state"):
            self._update_send_button_state()
        if getattr(self, "is_running", False):
            return
        if getattr(self, "_generation_completed", False):
            self._reset_generation_for_new_input()
        url = self.capsule_entry.get_text()
        is_private = requires_authenticated_browser(url)
        self._url_is_private = is_private
        if is_private and hasattr(self, "card_no_login"):
            self.card_need_login.set_checked(False)
            self.card_no_login.set_checked(True)
            self.status_var.set("账号内对话链接，将复用登录状态。")
        if hasattr(self, "card_source_url"):
            self._refresh_generation_sources()
        else:
            self._refresh_generation_summary()
        self._update_generate_button_state()

    # ---------------- 按钮状态 ----------------

    def _update_generate_button_state(self):
        completed = getattr(self, "_generation_completed", False)
        self.btn_generate._text = (
            REGENERATE_BUTTON_LABEL if completed else GENERATE_BUTTON_LABEL
        )
        if getattr(self, "is_running", False):
            stopping = self._generation_cancelled()
            self.btn_generate._text = "正在停止…" if stopping else "停止生成"
            self.btn_generate.set_enabled(not stopping)
            if hasattr(self, "generation_ready_badge"):
                self.generation_ready_badge.config(
                    text="  ●  停止中  " if stopping else "  ●  生成中  ", fg=COLOR_ACCENT_BLUE,
                    bg=COLOR_ACCENT_BG,
                )
            return
        has_mode = any([
            self.card_raw.checked, self.card_normal.checked,
            self.card_simple.checked, self.card_detailed.checked,
        ])
        source = getattr(self, "generation_source", None)
        has_url = bool(self.capsule_entry.get_text().strip())
        has_file = getattr(self, "selected_summary_file", None) is not None
        has_source = (source == "url" and has_url) or (
            source == "file" and has_file
        )
        has_auth = source == "file" or (
            self.card_no_login.checked or self.card_need_login.checked
        )
        if source == "file":
            has_mode = any([
                self.card_normal.checked,
                self.card_simple.checked,
                self.card_detailed.checked,
            ])
        configuration_complete = has_source and has_mode and has_auth

        if hasattr(self, "generation_ready_badge"):
            if configuration_complete:
                badge_text, badge_color, badge_bg = "已就绪", COLOR_SUCCESS, "#F1FAF6"
            else:
                missing = []
                if not has_source:
                    missing.append("内容来源")
                if not has_mode:
                    missing.append("生成模式")
                if source == "url" and not has_auth:
                    missing.append("访问方式")
                badge_text = f"待设置{'、'.join(missing)}"
                badge_color, badge_bg = COLOR_TEXT_MUTED, COLOR_ACCENT_BG
            self.generation_ready_badge.config(
                text=f"  ●  {badge_text}  ", fg=badge_color, bg=badge_bg,
            )

        if hasattr(self, "status_var") and not completed:
            self.status_var.set(
                "所有配置已完成" if configuration_complete else "配置未完全"
            )
        if hasattr(self, "percent_var") and not completed:
            missing_items = []
            if not has_source:
                missing_items.append("内容来源")
            if not has_mode:
                missing_items.append("生成模式")
            if source == "url" and not has_auth:
                missing_items.append("访问方式")
            self.percent_var.set(
                "0%" if getattr(self, "_generation_progress_reset", False)
                else (
                    "可以开始生成"
                    if configuration_complete
                    else f"还需设置：{'、'.join(missing_items)}"
                )
            )
        self.btn_generate.set_enabled(configuration_complete)
        if hasattr(self, "_update_send_button_state"):
            self._update_send_button_state()

    # ---------------- 完成徽章 ----------------

    def _show_completed_badge(self, duration_sec: int = 5):
        if getattr(self, "_completed_badge_after_id", None) is not None:
            try:
                self.root.after_cancel(self._completed_badge_after_id)
            except tk.TclError:
                pass
            self._completed_badge_after_id = None
        self.done_badge.pack(anchor="w", pady=(8, 0))

        def _hide():
            self._completed_badge_after_id = None
            try:
                self.done_badge.pack_forget()
            except tk.TclError:
                pass

        self._completed_badge_after_id = self.root.after(
            duration_sec * 1000, _hide,
        )

    # ---------------- 开始生成 / 直接总结 ----------------

    def _generation_cancelled(self):
        event = getattr(self, "_generation_cancel_event", None)
        return event is not None and event.is_set()

    def _check_generation_cancelled(self):
        if self._generation_cancelled():
            # CancelledError bypasses backend retry/fallback handlers.
            raise asyncio.CancelledError()

    def _wait_for_generation_event(self, event):
        while not event.wait(0.1):
            self._check_generation_cancelled()
            if self._ui_dispatcher.closed.is_set():
                raise RuntimeError("界面已关闭，无法继续等待用户操作。")
        self._check_generation_cancelled()

    def _post_generation_ui(self, callback, *, visible=False):
        cancel_event = getattr(self, "_generation_cancel_event", None)

        def apply():
            if cancel_event is None or not cancel_event.is_set():
                callback()

        self._post_ui(apply, visible=visible)

    def _on_stop_generate(self):
        if not self.is_running or self._generation_cancelled():
            return
        self._generation_cancel_event.set()
        self.progress_bar.reset()
        self.percent_var.set("0%")
        self.status_var.set("正在停止生成，请等待当前操作退出...")
        self._update_generate_button_state()

    async def _fetch_with_cancellation(self, fetch_coro):
        """One cancellation source; await browser/driver cleanup before returning."""
        task = asyncio.create_task(fetch_coro)
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=0.05)
            if not done and self._generation_cancelled():
                task.cancel()
                break
        return await task

    def _on_start_generate(self):
        if getattr(self, "is_running", False):
            self._on_stop_generate()
            return
        if getattr(self, "generation_source", None) == "file":
            self._on_direct_summary()
            return
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
        custom_api = None
        needs_summary = any(
            modes.get(name) for name in ("normal", "simple", "detailed")
        )
        if needs_summary:
            try:
                api_keys = self.credential_store.load_api_keys()
                if any(is_custom_provider(key) for key in api_keys):
                    custom_api = self.credential_store.load_custom_apis()
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

        self._generation_cancel_event = threading.Event()
        self.is_running = True
        self._generation_progress_reset = False
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
                self._post_ui(self._on_task_finished)
                self._post_ui(lambda error=str(e), detail=err_detail: [
                    self.status_var.set(f"❌ 线程崩溃: {error}"),
                    self.percent_var.set("0%"),
                    messagebox.showerror("生成线程崩溃", f"{error}\n\n{detail}", parent=self.root),
                ], visible=True)

        thread = threading.Thread(
            target=_safe_run,
            args=(
                url, need_login, modes, save_dir_path,
                output_filename, api_keys, settings,
            ),
            **({"kwargs": {"custom_api": custom_api}} if custom_api else {}),
            daemon=True,
        )
        thread.start()

    def _on_direct_summary(self):
        if getattr(self, "is_running", False):
            return
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
                "提示", "请至少勾选普通版、极简版或细节版之一。",
            )
            return

        try:
            _load_direct_summary_file(source_path)
            api_keys = self.credential_store.load_api_keys()
            custom_api = self.credential_store.load_custom_apis() if any(is_custom_provider(key) for key in api_keys) else None
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

        self._generation_cancel_event = threading.Event()
        self.is_running = True
        self._generation_progress_reset = False
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
                "",
                False,
                modes,
                save_dir_path,
                output_filename,
                dict(api_keys),
                settings,
                Path(source_path).resolve(),
            ),
            **({"kwargs": {"custom_api": custom_api}} if custom_api else {}),
            daemon=True,
        ).start()

    # ---------------- 登录确认弹窗与原站链接补充弹窗 ----------------

    def _confirm_login_required(self) -> bool:
        """在打开浏览器前征求用户同意。"""
        answered = threading.Event()
        result = {"confirmed": False}

        def ask():
            try:
                result["confirmed"] = messagebox.askyesno(
                    "需要登录或切换账号",
                    "当前登录状态无法读取目标会话。可能尚未登录、登录了其他账号，"
                    "或当前账号无权访问。是否打开浏览器登录或切换账号？",
                    parent=self.root,
                )
            finally:
                answered.set()

        self._post_generation_ui(ask, visible=True)
        self._wait_for_generation_event(answered)
        return result["confirmed"]

    def _request_attachment_web_link(self, missing_names: list[str] | None = None) -> str | None:
        """附件下载失败时，请用户提供可访问原文件的会话网页链接。"""
        answered = threading.Event()
        result: dict[str, str | None] = {"url": None}
        detail = (
            "、".join(missing_names[:5])
            + (f" 等共 {len(missing_names)} 个" if len(missing_names) > 5 else "")
            if missing_names else "附件"
        )
        missing_types = "、".join(sorted({
            Path(name).suffix.lower().lstrip(".") or "无扩展名"
            for name in missing_names or []
        })) or "未知"

        def ask():
            dialog = tk.Toplevel(self.root)
            dialog.title("请提供原始会话网页链接")
            dialog.geometry("560x300")
            dialog.resizable(False, False)
            dialog.transient(self.root)
            bind_visible_modal(dialog)
            dialog.configure(bg=COLOR_BG_APP)

            tk.Label(
                dialog,
                text=(
                    f"以下原文件无法从分享页下载：{detail}。\n"
                    f"未下载类型：{missing_types}。\n"
                    "请粘贴包含这些附件且您能访问的原始会话网页链接，程序将重试；"
                    "未能下载的附件会在导出中标明。"
                ),
                font=FONT_BODY,
                fg=COLOR_TEXT_PRIMARY,
                bg=COLOR_BG_APP,
                justify="left",
                wraplength=510,
            ).pack(padx=24, pady=(24, 14), anchor="w")

            url_var = tk.StringVar()
            entry = ttk.Entry(dialog, textvariable=url_var)
            entry.pack(fill="x", padx=24)
            countdown = ttk.Label(dialog, text="15 秒后自动跳过")
            countdown.pack(pady=(12, 8))
            buttons = ttk.Frame(dialog)
            buttons.pack()
            timer: dict[str, str | None] = {"id": None}

            def finish(url: str | None = None):
                if answered.is_set():
                    return
                if timer["id"] is not None:
                    dialog.after_cancel(timer["id"])
                result["url"] = url
                dialog.destroy()
                answered.set()

            def valid_url() -> str | None:
                url = url_var.get().strip()
                try:
                    parsed = urlparse(url)
                except ValueError:
                    return None
                return url if parsed.scheme in {"http", "https"} and parsed.netloc else None

            confirm = ttk.Button(
                buttons,
                text="确定",
                state="disabled",
                command=lambda: finish(valid_url()),
            )
            confirm.pack(side="left", padx=6)
            ttk.Button(buttons, text="跳过", command=finish).pack(side="left", padx=6)

            def update_confirm(*_args):
                confirm.configure(state="normal" if valid_url() else "disabled")

            def tick(seconds: int):
                if seconds <= 0:
                    finish()
                    return
                countdown.configure(text=f"{seconds} 秒后自动跳过")
                timer["id"] = dialog.after(1000, tick, seconds - 1)

            url_var.trace_add("write", update_confirm)
            dialog.bind("<Return>", lambda _event: finish(valid_url()) if valid_url() else None)
            dialog.protocol("WM_DELETE_WINDOW", finish)
            entry.focus_set()
            tick(15)

        def show_dialog():
            try:
                ask()
            except Exception:
                answered.set()
                raise

        self._post_generation_ui(show_dialog, visible=True)
        self._wait_for_generation_event(answered)
        return result["url"]

    def _show_login_dialog(
        self, loop: asyncio.AbstractEventLoop, login_event: asyncio.Event,
    ):
        dialog = tk.Toplevel(self.root)
        dialog.title("授权登录确认")
        dialog.geometry("480x230")
        dialog.resizable(False, False)
        dialog.configure(bg=COLOR_TOPIC_DIALOG_BG)
        dialog.transient(self.root)
        bind_visible_modal(dialog)

        x = self.root.winfo_x() + (self.root.winfo_width() - 480) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 230) // 2
        dialog.geometry(f"+{x}+{y}")

        content = tk.Frame(dialog, bg=COLOR_BG_APP, padx=28, pady=22)
        content.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            content, text="⚠️ 在生成结束前请勿关闭浏览器！",
            font=FONT_H2, fg=COLOR_DANGER, bg=COLOR_BG_APP, anchor="w",
            wraplength=420,
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(
            content,
            text=(
                "系统已为您打开浏览器窗口。\n"
                "请登录或切换到有权访问目标会话的 AI 账号，确认目标会话内容"
                "已经显示后，再点击下方按钮继续生成。"
            ),
            font=FONT_BODY, fg=COLOR_TEXT_SECONDARY, bg=COLOR_BG_APP,
            justify=tk.LEFT, anchor="w", wraplength=420,
        ).pack(anchor="w", pady=(0, 16))

        done_called = {"flag": False}

        def on_login_done(_event=None):
            if done_called["flag"]:
                return
            done_called["flag"] = True
            loop.call_soon_threadsafe(login_event.set)
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_login_done)
        dialog.bind("<Return>", on_login_done)

        FlatButton(
            content, text="已确认会话可访问，继续生成",
            command=on_login_done,
            variant="accent", width=200, height=40,
            bg_parent=COLOR_BG_APP,
        ).pack(anchor="center")

    # ---------------- 主题选择弹窗 ----------------

    def _show_summary_topic_dialog(self, available_topics, on_done):
        dialog = tk.Toplevel(self.root)
        dialog.title("选择重点主题")
        dialog.resizable(False, False)
        dialog.configure(bg=COLOR_BG_APP)
        dialog.transient(self.root)
        bind_visible_modal(dialog)

        height = min(690, 300 + 104 * min(len(available_topics), 4))
        width = 680
        x = self.root.winfo_x() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - height) // 2
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        content = tk.Frame(
            dialog, bg=COLOR_TOPIC_DIALOG_BG, padx=36, pady=30,
        )
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(3, weight=1)

        tk.Label(
            content, text="哪些主题值得重点展开？",
            font=(FONT_FAMILY, 20, "bold"), fg=COLOR_TEXT_PRIMARY,
            bg=COLOR_TOPIC_DIALOG_BG, anchor="w",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            content,
            text=(
                "所有主题摘要都会保留。选中的主题将在文末进一步展开关键记忆，"
                "方便你快速回看最重要的内容。"
            ),
            font=FONT_BODY, fg=COLOR_TEXT_MUTED, bg=COLOR_TOPIC_DIALOG_BG,
            wraplength=600, justify=tk.LEFT, anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(8, 22))

        list_header = tk.Frame(content, bg=COLOR_TOPIC_DIALOG_BG)
        list_header.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        selection_var = tk.StringVar(master=dialog)
        tk.Label(
            list_header, textvariable=selection_var,
            font=FONT_SMALL_BOLD, fg=COLOR_TEXT_SECONDARY,
            bg=COLOR_TOPIC_DIALOG_BG,
        ).pack(side=tk.LEFT)

        choices_shell = tk.Frame(content, bg=COLOR_TOPIC_DIALOG_BG)
        choices_shell.grid(row=3, column=0, sticky="nsew")
        choices_canvas = tk.Canvas(
            choices_shell, bg=COLOR_TOPIC_DIALOG_BG, highlightthickness=0,
            height=1,
        )
        choices_scrollbar = MinimalScrollbar(
            choices_shell, target_canvas=choices_canvas, width=7,
        )
        choices_canvas.configure(yscrollcommand=choices_scrollbar.set_range)
        choices_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        choices_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        choices = tk.Frame(choices_canvas, bg=COLOR_TOPIC_DIALOG_BG)
        choices_window = choices_canvas.create_window(
            0, 0, window=choices, anchor="nw",
        )
        choices.bind(
            "<Configure>",
            lambda _e: choices_canvas.configure(
                scrollregion=choices_canvas.bbox("all")
            ),
        )
        choices_canvas.bind(
            "<Configure>",
            lambda e: choices_canvas.itemconfig(choices_window, width=e.width),
        )
        dialog.bind(
            "<MouseWheel>",
            lambda e: choices_canvas.yview_scroll(
                -int(e.delta / 120), "units",
            ),
        )

        cards = {}

        def refresh_selection_status(_card=None):
            selected_count = sum(card.checked for card in cards.values())
            selection_var.set(f"已选 {selected_count} 项，共 {len(available_topics)} 项")
            clear_button.configure(
                fg=COLOR_GENERATION_ACCENT if selected_count else COLOR_TEXT_DISABLED,
                cursor="hand2" if selected_count else "arrow",
            )

        def set_all(checked: bool):
            for card in cards.values():
                card.set_checked(checked)
            refresh_selection_status()

        actions = tk.Frame(list_header, bg=COLOR_TOPIC_DIALOG_BG)
        actions.pack(side=tk.RIGHT)
        clear_button = tk.Label(
            actions, text="清空", font=FONT_SMALL_BOLD,
            fg=COLOR_TEXT_DISABLED, bg=COLOR_TOPIC_DIALOG_BG,
            padx=8, cursor="arrow",
        )
        clear_button.pack(side=tk.RIGHT)
        clear_button.bind(
            "<Button-1>",
            lambda _event: set_all(False) if any(
                card.checked for card in cards.values()
            ) else None,
        )
        select_all_button = tk.Label(
            actions, text="全选", font=FONT_SMALL_BOLD,
            fg=COLOR_GENERATION_ACCENT, bg=COLOR_TOPIC_DIALOG_BG,
            padx=8, cursor="hand2",
        )
        select_all_button.pack(side=tk.RIGHT)
        select_all_button.bind("<Button-1>", lambda _event: set_all(True))

        for index, topic in enumerate(available_topics, start=1):
            topic_id = topic["topic_id"]
            summary_text = str(topic.get("summary") or "该主题暂无摘要。")
            card = SummaryTopicCard(
                choices, index=index, title=str(topic["title"]),
                summary=summary_text, on_toggle=refresh_selection_status,
                width=578,
            )
            card.pack(fill=tk.X, pady=(0, 10))
            cards[topic_id] = card

        refresh_selection_status()

        completed = False

        def finish(use_checked: bool):
            nonlocal completed
            if completed:
                return
            completed = True
            selected = tuple(
                topic["topic_id"] for topic in available_topics
                if use_checked and cards[topic["topic_id"]].checked
            )
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()
            on_done(selected)

        footer = tk.Frame(content, bg=COLOR_TOPIC_DIALOG_BG)
        footer.grid(row=4, column=0, sticky="ew")
        tk.Frame(footer, bg=COLOR_BORDER, height=1).pack(
            fill=tk.X, pady=(16, 14),
        )
        button_row = tk.Frame(footer, bg=COLOR_TOPIC_DIALOG_BG)
        button_row.pack(fill=tk.X)
        action_group = tk.Frame(button_row, bg=COLOR_TOPIC_DIALOG_BG)
        action_group.pack(side=tk.RIGHT)
        FlatButton(
            action_group, text="暂不选择", command=lambda: finish(False),
            variant="topic-secondary", width=132, height=44,
            bg_parent=COLOR_TOPIC_DIALOG_BG,
        ).pack(side=tk.LEFT, padx=(0, 12))
        FlatButton(
            action_group, text="确认并继续生成",
            command=lambda: finish(True),
            variant="topic-primary", width=196, height=44,
            bg_parent=COLOR_TOPIC_DIALOG_BG,
        ).pack(side=tk.LEFT)

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

        self._post_generation_ui(show_dialog, visible=True)
        selection_started = time.perf_counter()
        self._wait_for_generation_event(selection_ready)
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
        custom_api: dict | None = None,
    ):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        task_started = time.perf_counter()
        run_succeeded = False
        direct_summary = source_path is not None
        fetch_warnings: list[str] = []
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
        output_paths = build_output_paths(save_dir, modes, output_filename)
        result_dir = output_paths["output_dir"]

        login_event = asyncio.Event()

        def update_progress(val: float, msg: str, *, from_fetch=False):
            if self._generation_cancelled():
                if from_fetch:
                    # Fetch logging may run from a browser cleanup finally block.
                    return
                self._check_generation_cancelled()
            run_log.event(
                "progress", msg,
                ui_progress=round(float(val), 3),
            )
            percent_str = f"{int(val * 100)}%"
            self._post_generation_ui(lambda: [
                self.progress_bar.set_progress(val),
                self.status_var.set(msg),
                self.percent_var.set(percent_str),
            ])

        try:
            self._check_generation_cancelled()
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
                asset_owner = output_paths["asset_markdown"].name
                image_output_dir = build_image_asset_directory(
                    result_dir,
                    asset_owner,
                )
                document_output_dir = build_document_asset_directory(
                    result_dir,
                    asset_owner,
                )
                fetch_coro = (
                    fetch_chat_pipeline(
                        url=url,
                        need_login=need_login,
                        login_ready_event=login_event,
                        login_required_callback=(
                            lambda: self._post_generation_ui(
                                lambda: self._show_login_dialog(loop, login_event),
                                visible=True,
                            )
                        ),
                        login_confirmation_callback=(
                            self._confirm_login_required
                        ),
                        attachment_web_link_callback=(
                            self._request_attachment_web_link
                        ),
                        logger=lambda m: update_progress(0.28, m, from_fetch=True),
                        image_output_dir=image_output_dir,
                        image_reference_base=result_dir,
                        document_output_dir=document_output_dir,
                        document_reference_base=result_dir,
                        browser_profile_root=app_settings.browser_profile_dir,
                        debug_html_file=app_settings.debug_html_file,
                    )
                )
                fetch_res = loop.run_until_complete(self._fetch_with_cancellation(fetch_coro))
                self._check_generation_cancelled()
                fetch_seconds = time.perf_counter() - fetch_started
                login_wait_seconds = max(0.0, fetch_res.user_wait_seconds)
                fetch_active_seconds = max(
                    0.0, fetch_seconds - login_wait_seconds,
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
                fetch_warnings = fetch_res.warnings
                for warning in fetch_warnings:
                    run_log.event("fetch_warning", warning)
                if fetch_res.error or not fetch_res.messages:
                    err = fetch_res.error or "未能提取到有效对话内容。"
                    self._post_generation_ui(
                        lambda: messagebox.showerror("生成失败", err, parent=self.root),
                        visible=True,
                    )
                    return

                messages = fetch_res.messages
                if fetch_warnings:
                    warning_text = _format_fetch_warnings(fetch_warnings)
                    self._post_generation_ui(
                        lambda text=warning_text: messagebox.showwarning(
                            "抓取完成，但部分附件未下载", text, parent=self.root,
                        ),
                        visible=True,
                    )
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
                    result, update_progress, run_log,
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
                **({"custom_api": custom_api} if custom_api else {}),
                result_cache_dir=app_settings.summary_cache_dir,
                source_platform=(
                    "deepseek"
                    if (
                        not direct_summary
                        and urlparse(url).hostname == "chat.deepseek.com"
                    )
                    else (
                        "doubao"
                        if not direct_summary and urlparse(url).hostname
                        in {"doubao.com", "www.doubao.com"}
                        else (
                            "ChatGPT"
                            if not direct_summary
                            and urlparse(url).hostname in {"chatgpt.com", "chat.openai.com"}
                            and urlparse(url).path.startswith(("/c/", "/share/"))
                            else None
                        )
                    )
                ),
                source_name=source_name,
                source_dir=source_dir,
                topic_selector=(
                    select_summary_topics
                    if modes.get("normal") or modes.get("detailed")
                    else None
                ),
                progress=lambda message: update_progress(0.72, message),
                cancel_check=self._check_generation_cancelled,
                cancel_event=getattr(self, "_generation_cancel_event", None),
            )
            self._check_generation_cancelled()
            generation_seconds = (
                time.perf_counter() - generation_started - selection_wait_seconds
            )
            saved_files = [str(path.resolve()) for path in bundle.saved_files]
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

            total_seconds = time.perf_counter() - task_started
            program_seconds = fetch_active_seconds + generation_seconds
            wait_seconds = login_wait_seconds + selection_wait_seconds
            update_progress(
                1.0,
                (
                    f"{'直接总结' if direct_summary else '生成'}完成 · "
                    f"共 {len(saved_files)} 个文件 · "
                    f"总计 {total_seconds:.1f} 秒。可在历史记录中查看。"
                ) if saved_files else "所有任务生成完成！",
            )
            self._post_generation_ui(lambda: self._show_completed_badge(5))
            from datetime import datetime as _dt
            history_record = {
                "title": (
                    source_path.name
                    if direct_summary and source_path is not None
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
                "output_dir": str(result_dir.resolve()),
            }
            self._post_generation_ui(
                lambda r=history_record: self._add_history_record(r)
            )
            run_succeeded = True
            self._post_generation_ui(
                lambda: setattr(self, "_generation_completed", True)
            )

        except asyncio.CancelledError:
            run_log.event("run_cancelled", "用户停止生成")
            self._post_ui(lambda: self.status_var.set("已停止生成"))
        except Exception as e:
            if self._generation_cancelled():
                run_log.event("run_cancelled", "用户停止生成")
                self._post_ui(lambda: self.status_var.set("已停止生成"))
                return
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
            self._post_generation_ui(
                lambda: messagebox.showerror("处理失败", f"生成失败：{err_msg}", parent=self.root),
                visible=True,
            )

        finally:
            run_log.event(
                "run_finished",
                succeeded=run_succeeded,
                total_seconds=round(time.perf_counter() - task_started, 3),
            )
            run_log.close()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            self._post_ui(self._on_task_finished)

    def _on_task_finished(self):
        self.is_running = False
        self._set_inputs_locked(False)
        self._refresh_generation_sources()
        self._update_generate_button_state()

    # ---------------- 设置页与旧版入口兼容 ----------------

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
        section.pack(fill=tk.BOTH, expand=True, padx=SETTINGS_SECTION_PADX, pady=16)

        tk.Label(
            section, text="设置", font=FONT_TITLE,
            fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP, anchor="w",
        ).pack(fill=tk.X, pady=(0, 12))

        panel = tk.Frame(
            section, bg=COLOR_CARD, padx=SETTINGS_PANEL_PADX, pady=16,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_BORDER, takefocus=False,
        )
        panel.pack(fill=tk.BOTH, expand=True)

        tabs = SettingsSegmentedTabs(
            panel, command=lambda key: show_page(key), bg_parent=COLOR_CARD,
        )
        tabs.pack(fill=tk.X, pady=(0, 10))
        page_host = tk.Frame(panel, bg=COLOR_CARD)
        page_host.pack(fill=tk.BOTH, expand=True)
        api_page = tk.Frame(page_host, bg=COLOR_CARD, padx=SETTINGS_PAGE_PADX, pady=12)
        data_page = tk.Frame(page_host, bg=COLOR_CARD, padx=SETTINGS_PAGE_PADX, pady=12)
        api_page.pack(fill=tk.BOTH, expand=True)
        active_settings_page = {"key": "api"}

        try:
            existing_keys = self.credential_store.load_api_keys()
            provider_order = list(self.credential_store.load_provider_order())
            custom_api_settings = getattr(self.credential_store, "load_custom_apis", lambda: {})()
            deleted_builtin_apis = set(getattr(self.credential_store, "load_deleted_builtin_apis", lambda: ())())
            key_load_error = None
        except CredentialStoreError as error:
            existing_keys = {}
            provider_order = ["gemini", "siliconflow", "deepseek"]
            custom_api_settings = {}
            deleted_builtin_apis = set()
            key_load_error = str(error)

        notice_var = tk.StringVar(value="")
        notice_slot = tk.Frame(api_page, bg=COLOR_CARD, height=42)
        notice_slot.pack(fill=tk.X, pady=(0, 8))
        notice_label = tk.Label(
            notice_slot, textvariable=notice_var,
            font=FONT_SMALL, fg=COLOR_DANGER, bg=COLOR_CARD, anchor="w", width=1,
        )
        notice_label.pack(fill=tk.X)
        from scripts.api_config import middle_ellipsis
        notice_label.configure(textvariable="", wraplength=0)
        notice_tooltip = HoverTooltip(notice_label, "")

        def fit_notice(_event=None):
            text = notice_var.get()
            notice_label.configure(text=middle_ellipsis(text, max(1, notice_label.winfo_width() - 4),
                                   tkfont.Font(font=notice_label.cget("font")).measure))
            notice_tooltip._text = text

        notice_var.trace_add("write", lambda *_args: fit_notice())
        notice_label.bind("<Configure>", fit_notice)

        def show_notice(message: str, duration_ms: int = 3500):
            if self._notice_after_id is not None:
                try:
                    self.root.after_cancel(self._notice_after_id)
                except tk.TclError:
                    pass
                self._notice_after_id = None
            is_success = message.startswith(("已", "连接成功"))
            notice_label.configure(
                fg=COLOR_SUCCESS if is_success else COLOR_DANGER,
            )
            notice_var.set(message)
            if duration_ms > 0:
                def clear_notice():
                    self._notice_after_id = None
                    notice_var.set("")

                self._notice_after_id = self.root.after(
                    duration_ms, clear_notice,
                )

        page.show_notice = show_notice
        page.api_notice_var = notice_var
        page.api_notice_label = notice_label

        # ----- API KEY 行 -----
        builtin_providers = {
            "gemini": "Google Gemini",
            "siliconflow": "SiliconFlow",
            "deepseek": "DeepSeek",
        }
        providers = {key: name for key, name in builtin_providers.items() if key not in deleted_builtin_apis}

        providers.update({key: value["name"] for key, value in custom_api_settings.items()})

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
        api_rows_frame.pack_propagate(False)

        api_key_vars: dict[str, tk.StringVar] = {}
        api_test_buttons = {}
        api_delete_buttons = {}
        api_row_refs: dict[str, tk.Frame] = {}
        drag_state = {
            "active": False, "src": None, "tgt": None,
            "start_order": None, "preview_order": None,
            "start_y": None, "start_x": None, "offset_y": 0,
            "inside": False, "moved": False,
        }
        animation = {"after_id": None, "token": 0}
        row_height, row_gap = 34, 8

        def _layout_api_rows(animate=False, order=None, dragged=None):
            nonlocal row_height
            delete_width = max((button.winfo_reqwidth() for button in api_delete_buttons.values()), default=0)
            for row in api_row_refs.values():
                row.columnconfigure(5, minsize=delete_width)
            row_height = max(34, max((row.winfo_reqheight() for row in api_row_refs.values()), default=0))
            if animation["after_id"] is not None:
                try:
                    self.root.after_cancel(animation["after_id"])
                except tk.TclError:
                    pass
                animation["after_id"] = None
            animation["token"] += 1
            token = animation["token"]
            row_order = ordered_providers if order is None else order
            starts = {
                provider: api_row_refs[provider].winfo_y()
                for provider in row_order
            }
            step = row_height + row_gap
            api_rows_frame.configure(
                height=max(1, len(row_order) * step - row_gap),
            )

            def place(progress):
                eased = 1 - (1 - progress) ** 3
                for index, provider in enumerate(row_order):
                    if provider == dragged:
                        continue
                    target_y = index * step
                    start_y = starts[provider]
                    y = round(start_y + (target_y - start_y) * eased)
                    api_row_refs[provider].place(
                        x=0, y=y, relwidth=1, height=row_height,
                    )

            if not animate or all(
                starts[provider] == index * step
                for index, provider in enumerate(row_order)
                if provider != dragged
            ):
                place(1)
                return

            started = time.perf_counter()

            def tick():
                if token != animation["token"]:
                    return
                progress = min(1, (time.perf_counter() - started) / 0.16)
                place(progress)
                if progress < 1:
                    animation["after_id"] = self.root.after(16, tick)
                else:
                    animation["after_id"] = None

            tick()

        def _reset_drag_state():
            drag_state.update({
                "active": False, "src": None, "tgt": None,
                "start_order": None, "preview_order": None,
                "start_y": None, "start_x": None, "offset_y": 0,
                "inside": False, "moved": False,
            })

        def _cancel_api_drag(animate=False):
            if not drag_state["active"] and animation["after_id"] is None:
                return
            _reset_drag_state()
            _layout_api_rows(animate=animate)

        def _cancel_api_reorder_animation():
            _cancel_api_drag(animate=False)

        self._cancel_api_reorder_animation = _cancel_api_reorder_animation

        api_name_labels = {}

        def _add_api_row(provider):
            row = tk.Frame(api_rows_frame, bg=COLOR_CARD)
            row.columnconfigure(2, weight=1)
            api_row_refs[provider] = row

            handle = tk.Label(
                row, text="\u2630", font=FONT_BODY,
                fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, cursor="hand2",
                padx=8,
            )
            handle.grid(row=0, column=0)
            handle.bind(
                "<ButtonPress-1>",
                lambda event, key=provider: _drag_start(event, key),
            )
            handle.bind("<B1-Motion>", lambda event: _drag_motion(event))
            handle.bind("<ButtonRelease-1>", lambda event: _drag_end(event))
            HoverTooltip(handle, "拖动以调整兜底顺序")

            name_label = tk.Label(
                row, text=providers[provider],
                font=FONT_BODY_BOLD, fg=COLOR_TEXT_PRIMARY,
                bg=COLOR_CARD, width=14, anchor="w",
            )
            name_label.grid(row=0, column=1, padx=(0, 6), sticky="w")
            api_name_labels[provider] = name_label
            if is_custom_provider(provider):
                from scripts.api_config import middle_ellipsis
                def fit_name(event=None):
                    name_label.configure(text=middle_ellipsis(
                        providers[provider], max(1, name_label.winfo_width() - 4),
                        tkfont.Font(font=name_label.cget("font")).measure))
                name_label.configure(cursor="hand2", takefocus=True)
                name_label.bind("<Configure>", fit_name)
                name_label.bind("<Button-1>", lambda _event: _edit_custom_api(provider))
                name_label.bind("<Return>", lambda _event: _edit_custom_api(provider))
                name_label.bind("<space>", lambda _event: _edit_custom_api(provider))
                name_label.api_tooltip = HoverTooltip(name_label, providers[provider] + "（单击编辑）")

            entry_var = tk.StringVar(value=existing_keys.get(provider, ""))
            key_entry = tk.Entry(
                row, textvariable=entry_var, show="*",
                font=FONT_BODY, fg=COLOR_TEXT_PRIMARY,
                bg=COLOR_BG_APP, relief=tk.FLAT, width=12,
                insertbackground=COLOR_TEXT_PRIMARY,
                highlightthickness=1,
                highlightbackground=COLOR_BORDER,
                highlightcolor=COLOR_BORDER_FOCUS,
            )
            key_entry.grid(row=0, column=2, sticky="ew", ipady=4, padx=2)
            api_key_vars[provider] = entry_var

            def _toggle_key_mask(ent=key_entry, btn_ref=None):
                showing = ent.cget("show") == ""
                ent.configure(show="*" if showing else "")
                if btn_ref is not None:
                    btn_ref.configure(text="👁" if showing else "🙈")

            eye_btn = tk.Button(
                row, text="👁", font=FONT_SMALL,
                bg=COLOR_CARD, fg=COLOR_TEXT_MUTED,
                activebackground=COLOR_HOVER, activeforeground=COLOR_TEXT_PRIMARY,
                relief=tk.FLAT, bd=0, cursor="hand2", padx=6, pady=0,
            )
            eye_btn.configure(command=lambda e=key_entry, b=eye_btn: _toggle_key_mask(e, b))
            eye_btn.grid(row=0, column=4, padx=(2, 0))
            HoverTooltip(eye_btn, "显示 / 隐藏 API Key")
            test_button = tk.Button(
                row, text="测试", font=FONT_SMALL,
                bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, relief=tk.FLAT,
                cursor="hand2", command=lambda key=provider: _test_api(key),
            )
            test_button.grid(row=0, column=3, padx=(4, 0))
            api_test_buttons[provider] = test_button
            delete_button = tk.Button(
                row, text="删除", font=FONT_SMALL, bg=COLOR_CARD, fg=COLOR_DANGER,
                activebackground=COLOR_HOVER, activeforeground=COLOR_DANGER,
                relief=tk.FLAT, bd=0, cursor="hand2", padx=6, pady=0,
                command=lambda key=provider: _delete_api(key),
            )
            delete_button.grid(row=0, column=5, padx=(4, 0))
            HoverTooltip(delete_button, "删除此 API 及已保存的 KEY")
            api_delete_buttons[provider] = delete_button
            if provider == "gemini":
                HoverTooltip(test_button, "使用 Gemini 3.8 Flash 发送一条简短测试请求")

        def _drag_start(_event, provider):
            if provider not in ordered_providers:
                return
            _layout_api_rows()
            row = api_row_refs[provider]
            pointer_y = getattr(_event, "y_root", row.winfo_rooty() + row_height // 2)
            pointer_x = getattr(_event, "x_root", row.winfo_rootx() + 12)
            drag_state["active"] = True
            drag_state["src"] = provider
            drag_state["tgt"] = provider
            drag_state["start_order"] = list(ordered_providers)
            drag_state["preview_order"] = list(ordered_providers)
            drag_state["start_y"] = pointer_y
            drag_state["start_x"] = pointer_x
            drag_state["offset_y"] = max(
                0, min(row_height, pointer_y - row.winfo_rooty()),
            )
            drag_state["inside"] = True
            drag_state["moved"] = False
            row.lift()

        def _drag_motion(event):
            if not drag_state["active"]:
                return
            src = drag_state["src"]
            pointer_y = event.y_root
            pointer_x = getattr(
                event, "x_root",
                api_rows_frame.winfo_rootx() + api_rows_frame.winfo_width() // 2,
            )
            if (
                abs(pointer_y - drag_state["start_y"]) >= 4
                or abs(pointer_x - drag_state["start_x"]) >= 4
            ):
                drag_state["moved"] = True

            list_top = api_rows_frame.winfo_rooty()
            list_left = api_rows_frame.winfo_rootx()
            list_bottom = list_top + api_rows_frame.winfo_height()
            list_right = list_left + api_rows_frame.winfo_width()
            list_height = len(ordered_providers) * (row_height + row_gap) - row_gap
            row = api_row_refs[src]
            dragged_top = max(
                0,
                min(
                    list_height - row_height,
                    pointer_y - list_top - drag_state["offset_y"],
                ),
            )
            row.place(x=0, y=dragged_top, relwidth=1, height=row_height)
            row.lift()

            inside = (
                list_left <= pointer_x <= list_right
                and list_top <= pointer_y <= list_bottom
            )
            drag_state["inside"] = inside
            start_order = drag_state["start_order"]
            if inside:
                others = [provider for provider in start_order if provider != src]
                pointer_offset = dragged_top + row_height / 2
                src_index = start_order.index(src)
                slot = 0
                for index, provider in enumerate(start_order):
                    if provider == src:
                        continue
                    threshold = index * (row_height + row_gap) + row_height / 2
                    if index == 0 and src_index > 0:
                        threshold += row_gap
                    elif index == len(start_order) - 1 and src_index < index:
                        threshold -= row_gap
                    slot += pointer_offset >= threshold
                preview = others[:slot] + [src] + others[slot:]
                drag_state["tgt"] = (
                    preview[min(slot + 1, len(preview) - 1)]
                    if slot < len(others) else preview[-1]
                )
            else:
                preview = list(start_order)
                drag_state["tgt"] = None

            if preview != drag_state["preview_order"]:
                drag_state["preview_order"] = preview
                _layout_api_rows(
                    animate=True, order=preview, dragged=src,
                )
                row.lift()

        def _drag_end(event):
            if not drag_state["active"]:
                return
            if event is not None:
                _drag_motion(event)
            start_order = drag_state["start_order"]
            preview_order = drag_state["preview_order"]
            commit = (
                drag_state["inside"] and drag_state["moved"]
                and preview_order != start_order
            )
            if commit:
                ordered_providers[:] = preview_order
            _reset_drag_state()
            _layout_api_rows(animate=True)

        page.api_row_refs = api_row_refs
        page.api_key_vars = api_key_vars
        page.api_test_buttons = api_test_buttons
        page.api_delete_buttons = api_delete_buttons
        page.ordered_providers = ordered_providers
        page.api_rows_frame = api_rows_frame
        page.api_animation = animation
        page._drag_start = _drag_start
        page._drag_motion = _drag_motion
        page._drag_end = _drag_end
        page._layout_api_rows = _layout_api_rows
        page._drag_state = drag_state
        for provider in providers:
            _add_api_row(provider)
        page.api_name_labels = api_name_labels
        _layout_api_rows()

        api_hint = tk.Label(
            api_page,
            text="上下拖动 ☰ 调整调用顺序，失败后依次回退；Gemini 仅使用 3.8 Flash。密钥存入 Windows 凭据管理器。",
            font=FONT_TINY, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w",
            justify=tk.LEFT,
        )
        api_hint.pack(fill=tk.X, pady=(2, 4))
        api_hint.bind("<Configure>", lambda e: api_hint.configure(wraplength=max(200, e.width)))

        def _test_api(provider):
            from scripts.gemini_summarizer import (
                SummaryConfig, DEFAULT_MODEL, SILICONFLOW_DEFAULT_MODEL,
                DEEPSEEK_DEFAULT_MODEL, custom_summary_config, test_api_connection,
            )
            key = api_key_vars[provider].get().strip()
            if not key:
                show_notice("请先填写 API KEY；测试会发送一条简短请求。", 5000)
                return
            try:
                if is_custom_provider(provider):
                    tested_settings = dict(custom_api_settings[provider])
                    config = custom_summary_config(tested_settings)
                else:
                    config = SummaryConfig(provider=provider, model={
                        "gemini": DEFAULT_MODEL, "siliconflow": SILICONFLOW_DEFAULT_MODEL,
                        "deepseek": DEEPSEEK_DEFAULT_MODEL,
                    }[provider], thinking_level="low")
            except ValueError as error:
                show_notice(str(error), 5000)
                return
            button = api_test_buttons[provider]
            button.configure(state="disabled")
            show_notice("正在发送测试请求…", 0)

            def finish(text):
                if (api_page.winfo_exists() and provider in api_key_vars
                        and api_test_buttons.get(provider) is button and button.winfo_exists()):
                    button.configure(state="normal")
                    if api_key_vars[provider].get().strip() != key or (
                        is_custom_provider(provider) and tested_settings != custom_api_settings.get(provider)
                    ):
                        show_notice("配置或 KEY 已更改，请重新测试当前配置。", 5000)
                    else:
                        show_notice(text, 8000)

            def run():
                try:
                    text = test_api_connection(config, key)
                except RuntimeError as error:
                    text = str(error)
                self._post_ui(lambda: finish(text))
            threading.Thread(target=run, daemon=True).start()

        def _delete_api(profile_id):
            if profile_id not in providers:
                return
            if key_load_error:
                show_notice("原有配置未能读取，已阻止删除；请重启程序后重试。", 5000)
                return
            _cancel_api_reorder_animation()
            name = providers[profile_id]
            custom = is_custom_provider(profile_id)
            detail = ("将同时移除此 API 的配置和已保存的 KEY。" if custom else
                      "将从列表移除此内置 API，并清除已保存的 KEY。之后可通过“恢复内置 API”重新添加。")
            if not messagebox.askyesno(
                "删除 API", f"确定删除“{name}”？\n{detail}",
                parent=self.root, icon="warning", default="no",
            ):
                return
            try:
                if custom:
                    self.credential_store.delete_custom_api(profile_id)
                else:
                    self.credential_store.delete_builtin_api(profile_id)
            except CredentialStoreError as error:
                show_notice(str(error), 5000)
                return
            current_dialog = getattr(page, "custom_api_dialog", None)
            if (current_dialog is not None and current_dialog.winfo_exists()
                    and getattr(current_dialog, "api_profile_id", None) == profile_id):
                current_dialog.close()
            api_key_vars.pop(profile_id).set("")
            existing_keys.pop(profile_id, None)
            custom_api_settings.pop(profile_id, None)
            providers.pop(profile_id)
            ordered_providers[:] = [provider for provider in ordered_providers if provider != profile_id]
            api_test_buttons.pop(profile_id)
            api_delete_buttons.pop(profile_id)
            api_name_labels.pop(profile_id)
            api_row_refs.pop(profile_id).destroy()
            if not custom:
                deleted_builtin_apis.add(profile_id)
                _update_builtin_restore_button()
            _layout_api_rows(animate=True)
            self._apply_responsive_scale(force=True)
            show_notice(f"已删除“{name}”及其已保存的 KEY", 4000)

        page.delete_api = _delete_api
        page.delete_custom_api = _delete_api

        def _edit_custom_api(profile_id=None):
            from gui.custom_api_dialog import CustomAPIDialog
            current_dialog = getattr(page, "custom_api_dialog", None)
            if current_dialog is not None and current_dialog.winfo_exists():
                current_dialog.deiconify()
                current_dialog.lift()
                current_dialog.editor.entries["name"].focus_set()
                return current_dialog
            _cancel_api_reorder_animation()
            adding = profile_id is None
            profile_id = profile_id or "custom_" + uuid.uuid4().hex
            was_priority = not adding and bool(ordered_providers) and ordered_providers[0] == profile_id

            def saved(values, key, priority):
                self.credential_store.save_custom_api(values, key, profile_id)
                custom_api_settings[profile_id] = dict(values)
                providers[profile_id] = values["name"]
                if adding and profile_id not in api_row_refs:
                    existing_keys[profile_id] = key
                    ordered_providers.append(profile_id)
                    _add_api_row(profile_id)
                api_key_vars[profile_id].set(key)
                api_name_labels[profile_id].api_tooltip._text = values["name"] + "（单击编辑）"
                api_name_labels[profile_id].event_generate("<Configure>")
                if priority:
                    ordered_providers.remove(profile_id)
                    ordered_providers.insert(0, profile_id)
                elif was_priority and len(ordered_providers) > 1:
                    ordered_providers.remove(profile_id)
                    ordered_providers.append(profile_id)
                self.credential_store.save_provider_order(ordered_providers)
                _layout_api_rows(animate=True)
                self._apply_responsive_scale(force=True)
                show_notice("已安全保存自定义 API", 3000)

            def closed():
                page.custom_api_dialog = None
                page.custom_api_editor = None

            dialog = CustomAPIDialog(
                self.root, dict(custom_api_settings.get(profile_id, {})),
                api_key_vars[profile_id].get() if not adding else "",
                self._post_ui, saved, on_close=closed,
                capability_cache_path=self.app_settings.log_dir / "reasoning_capabilities.json",
                priority=was_priority,
                priority_locked=was_priority and len(ordered_providers) == 1,
            )
            dialog.api_profile_id = profile_id
            page.custom_api_dialog = dialog
            page.custom_api_editor = dialog.editor
            return dialog

        page.edit_custom_api = _edit_custom_api
        page.custom_api_settings = custom_api_settings
        page.custom_api_button = FlatButton(
            api_page, text="添加自定义 API", command=_edit_custom_api,
            width=160, height=46, bg_parent=COLOR_CARD,
        )
        page.custom_api_button.pack(side=tk.LEFT, pady=(8, 0))

        def _update_builtin_restore_button():
            if deleted_builtin_apis:
                page.restore_builtin_api_button.pack(before=page.custom_api_button, anchor="w", pady=(0, 6))
            else:
                page.restore_builtin_api_button.pack_forget()

        def _restore_builtin_apis():
            if not deleted_builtin_apis or key_load_error:
                return
            names = "、".join(name for key, name in builtin_providers.items() if key in deleted_builtin_apis)
            if not messagebox.askyesno(
                "恢复内置 API", f"恢复 {names}？\n恢复后需要重新填写 KEY。", parent=self.root, default="no",
            ):
                return
            _cancel_api_reorder_animation()
            error_text = None
            for provider, name in builtin_providers.items():
                if provider not in deleted_builtin_apis:
                    continue
                try:
                    self.credential_store.restore_builtin_api(provider)
                except CredentialStoreError as error:
                    error_text = str(error)
                    break
                deleted_builtin_apis.remove(provider)
                providers[provider] = name
                existing_keys.pop(provider, None)
                ordered_providers.append(provider)
                _add_api_row(provider)
            _update_builtin_restore_button()
            _layout_api_rows(animate=True)
            self._apply_responsive_scale(force=True)
            show_notice(error_text or "已恢复内置 API，请重新填写 KEY 后安全保存。", 5000)

        page.restore_builtin_api_button = tk.Button(
            api_page, text="恢复内置 API", font=FONT_SMALL, command=_restore_builtin_apis,
            fg=COLOR_GENERATION_ACCENT, bg=COLOR_CARD, activebackground=COLOR_HOVER,
            activeforeground=COLOR_GENERATION_ACCENT, relief=tk.FLAT, bd=0, cursor="hand2", padx=0,
        )
        _update_builtin_restore_button()

        def _save_api_keys():
            _cancel_api_drag(animate=False)
            if key_load_error:
                show_notice("原有 KEY 未能读取，已阻止覆盖保存；请重启程序后重试。", 5000)
                return
            keys = {
                provider: var.get() for provider, var in api_key_vars.items()
            }
            try:
                self.credential_store.save_api_keys(keys)
                self.credential_store.save_provider_order(ordered_providers)
                show_notice("已安全保存", 2000)
            except CredentialStoreError as error:
                show_notice(str(error), 5000)

        save_button = FlatButton(
            api_page, text="安全保存", command=_save_api_keys,
            variant="settings-save", icon_text="\uEA18",
            width=148, height=46, bg_parent=COLOR_CARD,
        )
        save_button.pack(side=tk.RIGHT, pady=(8, 0))
        page.api_save_button = save_button

        if key_load_error:
            show_notice(key_load_error, 5000)

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
                self.history_store = HistoryStore(self.app_settings.history_file)
                self.history_store.save(self.history_records)
                runtime_var.set(str(self.app_settings.runtime_data_dir))
                results_var.set(
                    str(self.app_settings.default_results_dir or "")
                )
                show_notice("已保存数据位置", 2000)
            except (SettingsStoreError, HistoryStoreError) as error:
                show_notice(str(error), 5000)
            except Exception:
                show_notice("保存失败，请检查目录权限", 4000)

        def _make_dir_row(parent, label, var, title):
            row = tk.Frame(
                parent, bg="#F8FAFC", padx=14, pady=12,
                highlightthickness=1, highlightbackground="#E2E8F0",
            )
            row.pack(fill=tk.X, pady=7)
            tk.Label(
                row, text=label, font=FONT_BODY_BOLD,
                fg=COLOR_TEXT_PRIMARY, bg="#F8FAFC",
                width=12, anchor="w",
            ).pack(side=tk.LEFT)
            entry = tk.Entry(
                row, textvariable=var, font=FONT_BODY,
                fg=COLOR_TEXT_PRIMARY, bg="#FFFFFF",
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=COLOR_BORDER,
                highlightcolor=COLOR_BORDER_FOCUS,
            )
            entry.pack(
                side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=6,
            )
            path_tooltip = HoverTooltip(entry, var.get())
            var.trace_add(
                "write", lambda *_args, tip=path_tooltip, value=var: setattr(
                    tip, "_text", value.get(),
                ),
            )
            tk.Button(
                row, text="浏览", cursor="hand2",
                command=lambda: _pick_dir(var, title),
                font=FONT_SMALL, relief=tk.FLAT,
                bg="#FFFFFF", fg=COLOR_TEXT_PRIMARY,
                activebackground="#EEF2FF", activeforeground=COLOR_ACCENT,
                highlightthickness=1, highlightbackground=COLOR_BORDER,
                padx=12, pady=4,
            ).pack(side=tk.LEFT, padx=(4, 4))
            tk.Button(
                row, text="清除", cursor="hand2",
                command=lambda: var.set(""),
                font=FONT_SMALL, relief=tk.FLAT,
                bg="#FFFFFF", fg=COLOR_TEXT_SECONDARY,
                activebackground="#FEF2F2", activeforeground=COLOR_DANGER,
                highlightthickness=1, highlightbackground=COLOR_BORDER,
                padx=12, pady=4,
            ).pack(side=tk.LEFT, padx=2)
            return row

        _make_dir_row(
            data_page, "运行数据目录", runtime_var,
            "选择运行数据目录",
        )
        _make_dir_row(
            data_page, "结果默认目录", results_var,
            "选择结果默认目录",
        )

        footer = tk.Frame(data_page, bg=COLOR_CARD)
        footer.pack(fill=tk.X, pady=(16, 0))
        save_button = tk.Button(
            footer, text="保存", command=_save_data_settings,
            font=FONT_BODY_BOLD, bg=COLOR_GENERATION_ACCENT, fg="#FFFFFF",
            activebackground="#5B3FD9", activeforeground="#FFFFFF",
            relief=tk.FLAT, padx=20, pady=8, cursor="hand2",
        )
        reset_button = tk.Button(
            footer, text="恢复默认", cursor="hand2",
            command=lambda: (
                runtime_var.set(str(default_app_settings().runtime_data_dir)),
                results_var.set(""),
            ),
            font=FONT_BODY, bg="#F8FAFC", fg=COLOR_TEXT_PRIMARY,
            activebackground="#EEF2FF", relief=tk.FLAT,
            highlightthickness=1, highlightbackground=COLOR_BORDER,
            padx=18, pady=8,
        )
        save_button.pack(side=tk.RIGHT)
        reset_button.pack(side=tk.RIGHT, padx=(0, 8))
        data_page.footer = footer
        data_page.save_button = save_button
        data_page.reset_button = reset_button
        data_page.runtime_var = runtime_var
        data_page.results_var = results_var
        page.data_page = data_page
        page.settings_tabs = tabs

        # ----- 页面切换方法（兼容外部调用） -----
        def show_page(page_key: str):
            pages = {"api": api_page, "data": data_page}
            if page_key not in pages:
                return
            dialog = getattr(page, "custom_api_dialog", None)
            if dialog is not None and dialog.winfo_exists():
                dialog.close()
            if page_key != active_settings_page["key"]:
                if active_settings_page["key"] == "api":
                    _cancel_api_reorder_animation()
                pages[active_settings_page["key"]].pack_forget()
                pages[page_key].pack(fill=tk.BOTH, expand=True)
                active_settings_page["key"] = page_key
            tabs.select(page_key)

        page.show_page = show_page


def main() -> None:
    """启动 AI 记忆总结协同管理工具。"""
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    AIMemoryGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
