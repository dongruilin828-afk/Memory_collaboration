"""Editor for one user-defined summary API, using the existing desktop theme."""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
import threading

from gui.theme import (
    COLOR_BG_APP, COLOR_CARD, COLOR_BORDER, COLOR_BORDER_FOCUS,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_MUTED, COLOR_DANGER, COLOR_SUCCESS,
    FONT_BODY, FONT_H2, FONT_SMALL,
)
from gui.widgets import FlatButton
from scripts.api_config import normalize_custom_api, middle_ellipsis
from scripts.gemini_summarizer import custom_summary_config, test_api_connection


class CustomAPIEditor(tk.Frame):
    def __init__(self, parent, values, api_key, post_ui, on_save, on_close=None):
        super().__init__(parent)
        self.configure(bg=COLOR_BG_APP)
        self._on_close = on_close
        self._post_ui = post_ui
        self._on_save = on_save
        self._testing = False
        self._scroll_after_id = None
        self._scrollregion_after_id = None
        self._scrollregion = None
        self._scroll_target = None
        defaults = dict(name="自定义 API", url="", model="", protocol="openai",
                        thinking_level="auto", json_mode="json_object",
                        max_output_tokens=16384, request_timeout_seconds=180)
        defaults.update(values)
        self.variables = {key: tk.StringVar(self, value=str(value)) for key, value in defaults.items()}
        self.key_var = tk.StringVar(self, value=api_key)
        self.priority_var = tk.BooleanVar(self, value=False)
        tk.Label(self, text="自定义总结 API", font=FONT_H2,
                 fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP).pack(anchor="w", padx=16, pady=(16, 4))
        subtitle = tk.Label(self, text="配置保存到本机 Windows 凭据管理器；测试只发送一条简短请求。",
                            font=FONT_SMALL, fg=COLOR_TEXT_MUTED, bg=COLOR_BG_APP,
                            anchor="w", justify=tk.LEFT, width=1)
        subtitle.pack(fill=tk.X, padx=16, pady=(0, 10))
        subtitle.bind("<Configure>", lambda e: subtitle.configure(wraplength=max(1, e.width)))
        actions = tk.Frame(self, bg=COLOR_BG_APP)
        actions.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=(8, 12))
        self.save_button = FlatButton(actions, text="保存配置", command=self.save,
                                      width=120, height=40, variant="accent", bg_parent=COLOR_BG_APP)
        self.save_button.pack(side=tk.RIGHT)
        self.test_button = FlatButton(actions, text="测试", command=self.test,
                                      width=120, height=40, bg_parent=COLOR_BG_APP)
        self.test_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.cancel_button = FlatButton(actions, text="取消", command=self.close,
                                        width=96, height=40, bg_parent=COLOR_BG_APP)
        self.cancel_button.pack(side=tk.LEFT)
        self.status_var = tk.StringVar(self)
        self.status_label = tk.Label(self, font=FONT_SMALL, width=1,
                                     fg=COLOR_TEXT_MUTED, bg=COLOR_BG_APP, justify=tk.LEFT, anchor="w")
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=6)
        def fit_status(_event=None):
            self.status_label.configure(text=middle_ellipsis(
                self.status_var.get(), max(1, self.status_label.winfo_width() - 4),
                tkfont.Font(font=self.status_label.cget("font")).measure))
        self.status_label.bind("<Configure>", fit_status)
        self.status_var.trace_add("write", lambda *_args: fit_status())
        body = tk.Frame(self, bg=COLOR_BG_APP)
        body.pack(fill=tk.BOTH, expand=True, padx=16)
        canvas = tk.Canvas(body, bg=COLOR_CARD, highlightthickness=0, yscrollincrement=1)
        self.scroll_canvas = canvas
        scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self._scroll_command)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        form = tk.Frame(canvas, bg=COLOR_CARD, padx=16, pady=12)
        item = canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
        form.bind("<Configure>", self._schedule_scrollregion)
        form.columnconfigure(1, weight=1)
        self.entries = {}

        def field(row, label, key, choices=None):
            tk.Label(form, text=label, font=FONT_BODY, bg=COLOR_CARD,
                     fg=COLOR_TEXT_PRIMARY, anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=8)
            if choices:
                widget = ttk.Combobox(form, textvariable=self.variables[key], values=choices,
                                      state="readonly", font=FONT_BODY, width=20)
            else:
                widget = tk.Entry(form, textvariable=self.variables[key], font=FONT_BODY,
                                  bg=COLOR_BG_APP, fg=COLOR_TEXT_PRIMARY, relief=tk.FLAT,
                                  highlightthickness=1, highlightbackground=COLOR_BORDER,
                                  highlightcolor=COLOR_BORDER_FOCUS, width=20)
            widget.grid(row=row, column=1, sticky="ew", pady=8, ipady=5)
            self.entries[key] = widget
            return widget

        field(0, "名称", "name")
        protocol = field(1, "协议", "protocol", ["openai", "gemini"])
        field(2, "API URL", "url")
        field(3, "模型 ID", "model")
        tk.Label(form, text="API KEY", font=FONT_BODY, bg=COLOR_CARD,
                 fg=COLOR_TEXT_PRIMARY).grid(row=4, column=0, sticky="w", pady=8)
        key_host = tk.Frame(form, bg=COLOR_CARD)
        key_host.grid(row=4, column=1, sticky="ew", pady=8)
        self.key_entry = tk.Entry(key_host, textvariable=self.key_var, show="*", font=FONT_BODY,
                                  bg=COLOR_BG_APP, relief=tk.FLAT, highlightthickness=1,
                                  highlightbackground=COLOR_BORDER, highlightcolor=COLOR_BORDER_FOCUS, width=16)
        self.key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        tk.Button(key_host, text="显示/隐藏", font=FONT_SMALL, relief=tk.FLAT, bg=COLOR_CARD,
                  command=lambda: self.key_entry.configure(show="*" if not self.key_entry.cget("show") else ""))\
            .pack(side=tk.RIGHT, padx=(6, 0))
        field(5, "思考强度", "thinking_level", ["auto", "none", "minimal", "low", "medium", "high", "xhigh"])
        field(6, "JSON 输出", "json_mode", ["json_object", "json_schema", "prompt"])
        field(7, "最大输出 token", "max_output_tokens")
        field(8, "请求超时（秒）", "request_timeout_seconds")
        tk.Checkbutton(form, text="优先使用此 API（移到调用顺序首位）", variable=self.priority_var,
                       font=FONT_BODY, bg=COLOR_CARD, anchor="w").grid(row=9, column=0, columnspan=2, sticky="w", pady=8)
        hint = tk.Label(form, text="openai：Chat Completions 兼容接口，例如 https://example.com/v1\n"
                        "gemini：Google 原生接口，例如 https://generativelanguage.googleapis.com\n"
                        "auto：不发送思考参数；prompt：仅用提示词约束 JSON，供不支持结构化输出的接口使用。\n"
                        "建议使用 HTTPS；HTTP 会明文传输 KEY，仅用于可信本机或内网。",
                        justify=tk.LEFT, anchor="w", bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, font=FONT_SMALL)
        hint.grid(row=10, column=0, columnspan=2, sticky="ew", pady=8)
        hint.bind("<Configure>", lambda e: hint.configure(wraplength=max(200, e.width)))
        protocol.bind("<<ComboboxSelected>>", lambda _e: self._protocol_changed())
        self._protocol_changed()

        def bind_interactions(widget):
            widget.bind("<Escape>", lambda _e: self.close())
            widget.bind("<MouseWheel>", self._on_mousewheel)
            widget.bind("<Button-4>", lambda _e: self._scroll_pixels(-48))
            widget.bind("<Button-5>", lambda _e: self._scroll_pixels(48))
            try:
                widget.bind("<PixelScroll>", self._on_pixelscroll)
            except tk.TclError:
                pass
            for child in widget.winfo_children():
                bind_interactions(child)

        bind_interactions(self)
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _schedule_scrollregion(self, _event=None):
        if self._scrollregion_after_id is None:
            self._scrollregion_after_id = self.after_idle(self._refresh_scrollregion)

    def _refresh_scrollregion(self):
        self._scrollregion_after_id = None
        bounds = self.scroll_canvas.bbox("all")
        if bounds:
            if bounds != self._scrollregion:
                self._scrollregion = bounds
                self.scroll_canvas.configure(scrollregion=bounds)
            if self._scroll_target is not None:
                self._scroll_target = min(self._scroll_target, self._scroll_limit(bounds))

    def _scroll_limit(self, bounds):
        return max(0, bounds[3] - bounds[1] - self.scroll_canvas.winfo_height())

    def _on_mousewheel(self, event):
        # Retain high resolution wheel deltas instead of reducing them to a sign.
        return self._scroll_pixels(-float(event.delta) * 48 / 120)

    def _on_pixelscroll(self, event):
        return self._scroll_pixels(-float(event.delta))

    def _scroll_pixels(self, delta):
        if not delta:
            return "break"
        bounds = self.scroll_canvas.bbox("all")
        if not bounds or self._scroll_limit(bounds) == 0:
            return "break"
        current = self.scroll_canvas.canvasy(0) - bounds[1]
        target = current if self._scroll_target is None else self._scroll_target
        if abs(target - current) >= 2 and (target - current) * delta < 0:
            target = current
        self._scroll_target = max(0, min(self._scroll_limit(bounds), target + delta))
        if self._scroll_after_id is None:
            self._scroll_after_id = self.after(16, self._animate_scroll)
        return "break"

    def _animate_scroll(self):
        self._scroll_after_id = None
        bounds = self.scroll_canvas.bbox("all")
        if not bounds or self._scroll_target is None:
            return
        target = max(0, min(self._scroll_limit(bounds), self._scroll_target))
        current = self.scroll_canvas.canvasy(0) - bounds[1]
        distance = target - current
        finished = abs(distance) < 2
        position = target if finished else current + distance * 0.35
        self.scroll_canvas.yview_moveto(position / max(1, bounds[3] - bounds[1]))
        # Retain the fractional target so small trackpad deltas accumulate.
        self._scroll_target = target
        if not finished:
            self._scroll_after_id = self.after(16, self._animate_scroll)

    def _scroll_command(self, *args):
        self._cancel_scroll_animation()
        self.scroll_canvas.yview(*args)

    def _cancel_scroll_animation(self):
        if self._scroll_after_id is not None:
            self.after_cancel(self._scroll_after_id)
            self._scroll_after_id = None
        self._scroll_target = None

    def _on_destroy(self, event):
        if event.widget is not self:
            return
        self._cancel_scroll_animation()
        if self._scrollregion_after_id is not None:
            self.after_cancel(self._scrollregion_after_id)
            self._scrollregion_after_id = None

    def close(self):
        self.destroy()
        if self._on_close:
            self._on_close()

    def _protocol_changed(self):
        native = self.variables["protocol"].get() == "gemini"
        choices = ["auto", "low", "medium", "high"] if native else ["auto", "none", "minimal", "low", "medium", "high", "xhigh"]
        self.entries["thinking_level"].configure(values=choices)
        if self.variables["thinking_level"].get() not in choices:
            self.variables["thinking_level"].set("auto")
        self.entries["json_mode"].configure(state="disabled" if native else "readonly")

    def _values(self):
        return {key: value.get() for key, value in self.variables.items()}

    def _status(self, text, success=False):
        self.status_var.set(text)
        self.status_label.configure(fg=COLOR_SUCCESS if success else COLOR_DANGER)

    def save(self):
        try:
            values = normalize_custom_api(self._values())
            self._on_save(values, self.key_var.get().strip(), self.priority_var.get())
        except (ValueError, RuntimeError) as error:
            self._status(str(error))
            return
        self.close()

    def test(self):
        if self._testing:
            return
        try:
            values = self._values()
            config = custom_summary_config(values)
            key = self.key_var.get().strip()
            if not key:
                raise ValueError("请填写 API KEY 后测试连接。")
        except ValueError as error:
            self._status(str(error))
            return
        self._testing = True
        self.test_button.set_enabled(False)
        self.status_var.set("正在发送测试请求…")

        def finish(text, success):
            if not self.winfo_exists():
                return
            self._testing = False
            self.test_button.set_enabled(True)
            if values != self._values() or key != self.key_var.get().strip():
                self._status("配置已更改，请重新测试当前配置。")
            else:
                self._status(text, success)

        def run():
            try:
                text, success = test_api_connection(config, key), True
            except RuntimeError as error:
                text, success = str(error), False
            self._post_ui(lambda: finish(text, success))
        threading.Thread(target=run, daemon=True).start()
