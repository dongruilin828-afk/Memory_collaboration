"""Editor for one user-defined summary API, using the existing desktop theme."""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
import threading
from PIL import Image, ImageDraw, ImageTk

from gui.theme import (
    COLOR_BG_APP, COLOR_CARD, COLOR_BORDER, COLOR_BORDER_FOCUS,
    COLOR_GENERATION_ACCENT, COLOR_BORDER_SUBTLE,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_MUTED, COLOR_DANGER, COLOR_SUCCESS,
    FONT_BODY, FONT_BODY_BOLD, FONT_H2, FONT_SMALL, _round_rectangle,
)
from gui.widgets import FlatButton, MinimalScrollbar
from gui.dropdown import RoundedCombobox
from gui.reasoning_slider import ReasoningSlider
from gui.ui_dispatch import bind_visible_modal
from scripts.api_config import normalize_custom_api, middle_ellipsis
from scripts.gemini_summarizer import custom_summary_config, test_api_connection


class _InputSurface(tk.Canvas):
    """Antialiased rounded frame around a native editable control."""

    def __init__(self, parent):
        super().__init__(parent, bg=COLOR_CARD, highlightthickness=0,
                         bd=0, width=1, height=44, takefocus=False)
        self.control = None
        self._focused = False
        self._hover = False
        self._window = None
        self._background = self.create_image(0, 0, anchor="nw")
        self.bind("<Configure>", self._resize)
        self.bind("<Enter>", lambda _e: self._set_state(hover=True))
        self.bind("<Leave>", lambda _e: self._set_state(hover=False))
        self.bind("<Button-1>", self._focus_control)

    def attach(self, control):
        self.control = control
        if isinstance(control, RoundedCombobox):
            control.popup_anchor = self
            control.bind("<<DropdownOpened>>", lambda _e: self.redraw(), add="+")
            control.bind("<<DropdownClosed>>", lambda _e: self.redraw(), add="+")
        self._window = self.create_window(14, 22, anchor="w", window=control)
        control.bind("<Configure>", self._fit_height, add="+")
        control.bind("<FocusIn>", lambda _e: self._set_state(focused=True), add="+")
        control.bind("<FocusOut>", lambda _e: self._set_state(focused=False), add="+")
        control.bind("<Enter>", lambda _e: self._set_state(hover=True), add="+")
        control.bind("<Leave>", lambda _e: self._set_state(hover=False), add="+")
        self._fit_height()

    def _focus_control(self, _event=None):
        if self.control is not None:
            self.control.focus_set()
            if isinstance(self.control, RoundedCombobox):
                self.control.open_dropdown()

    def _fit_height(self, _event=None):
        height = max(44, self.control.winfo_reqheight() + 22)
        if int(self.cget("height")) != height:
            self.configure(height=height)

    def _set_state(self, *, focused=None, hover=None):
        previous = self._focused, self._hover
        if focused is not None:
            self._focused = focused
        if hover is not None:
            self._hover = hover
        if previous != (self._focused, self._hover):
            self.redraw()

    def _resize(self, event):
        if self._window is not None:
            slider = isinstance(self.control, ReasoningSlider)
            inset = 6 if slider else 14
            self.coords(self._window, inset, event.height / 2)
            self.itemconfigure(self._window, width=max(1, event.width - 2 * inset))
            if slider:
                self.itemconfigure(self._window, height=max(1, event.height - 8))
        self.redraw()

    def redraw(self):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 5 or height < 5:
            return
        disabled = self.control is not None and str(self.control.cget("state")) == "disabled"
        opened = isinstance(self.control, RoundedCombobox) and self.control.popup is not None
        focused = (self._focused or opened) and not disabled
        scale = 3
        bitmap = Image.new("RGB", (width * scale, height * scale), COLOR_CARD)
        draw = ImageDraw.Draw(bitmap)
        if focused:
            draw.rounded_rectangle((0, 0, width * scale - 1, height * scale - 1),
                                   radius=13 * scale, fill="#EDE9FE")
        border = COLOR_BORDER_FOCUS if focused else ("#B8C2D3" if self._hover and not disabled else COLOR_BORDER)
        draw.rounded_rectangle((2 * scale, 2 * scale, (width - 2) * scale, (height - 2) * scale),
                               radius=10 * scale, fill="#F1F5F9" if disabled else COLOR_BG_APP,
                               outline=border, width=scale)
        self._image = ImageTk.PhotoImage(bitmap.resize((width, height), Image.Resampling.LANCZOS), master=self)
        self.itemconfigure(self._background, image=self._image)


class _PrioritySwitch(tk.Checkbutton):
    """Native checkbutton semantics with a smooth pill and a visible focus ring."""

    def __init__(self, parent, variable):
        super().__init__(parent, text="优先使用此 API", variable=variable, indicatoron=False,
                         bg=COLOR_CARD, activebackground=COLOR_CARD, selectcolor=COLOR_CARD,
                         relief=tk.FLAT, offrelief=tk.FLAT, overrelief=tk.FLAT,
                         bd=0, highlightthickness=0, padx=0, pady=0, takefocus=True, cursor="hand2")
        self.variable = variable
        self._focused = False
        self._hover = False
        self._track_height = max(24, tkfont.Font(master=self, font=FONT_BODY).metrics("linespace") + 2)
        self._trace = variable.trace_add("write", lambda *_args: self._redraw())
        self.bind("<FocusIn>", lambda _e: self._set_state(focused=True))
        self.bind("<FocusOut>", lambda _e: self._set_state(focused=False))
        self.bind("<Enter>", lambda _e: self._set_state(hover=True))
        self.bind("<Leave>", lambda _e: self._set_state(hover=False))
        self.bind("<Return>", self._activate)
        self.bind("<Destroy>", self._dispose, add="+")
        self._redraw()

    def _activate(self, _event=None):
        self.invoke()
        return "break"

    def _set_state(self, *, focused=None, hover=None):
        if focused is not None:
            self._focused = focused
        if hover is not None:
            self._hover = hover
        self._redraw()

    def _redraw(self):
        height = self._track_height
        width = round(height * 1.8)
        scale = 3
        bitmap = Image.new("RGB", ((width + 8) * scale, (height + 8) * scale), COLOR_CARD)
        draw = ImageDraw.Draw(bitmap)
        if self._focused:
            draw.rounded_rectangle((0, 0, (width + 8) * scale - 1, (height + 8) * scale - 1),
                                   radius=(height / 2 + 4) * scale, fill="#EDE9FE")
        enabled = self.variable.get()
        color = ("#5B42D6" if self._hover else COLOR_GENERATION_ACCENT) if enabled else ("#B7C2D3" if self._hover else "#CBD5E1")
        draw.rounded_rectangle((4 * scale, 4 * scale, (width + 4) * scale, (height + 4) * scale),
                               radius=height * scale / 2, fill=color)
        left = width - height + 7 if enabled else 7
        draw.ellipse((left * scale, 7 * scale, (left + height - 6) * scale, (height + 1) * scale),
                     fill=COLOR_CARD)
        size = (width + 8, height + 8)
        self._image = ImageTk.PhotoImage(bitmap.resize(size, Image.Resampling.LANCZOS), master=self)
        self.configure(image=self._image)

    def _dispose(self, event):
        if event.widget is self:
            self.variable.trace_remove("write", self._trace)


class _FormCard(tk.Canvas):
    """Rounded card sized by its form contents, including wrapped labels."""

    def __init__(self, parent):
        super().__init__(parent, bg=COLOR_BG_APP, highlightthickness=0, width=1, height=32)
        self.body = tk.Frame(self, bg=COLOR_CARD)
        self._window = self.create_window(20, 16, anchor="nw", window=self.body)
        self.bind("<Configure>", self._resize)
        self.body.bind("<Configure>", self._fit_height)

    def _fit_height(self, _event=None):
        height = self.body.winfo_reqheight() + 32
        if height != int(self.cget("height")):
            self.configure(height=height)

    def _resize(self, event):
        self.itemconfigure(self._window, width=max(1, event.width - 40))
        self.delete("card")
        if event.width > 4:
            _round_rectangle(self, 1, 1, event.width - 1, event.height - 1, r=12,
                             fill=COLOR_CARD, outline=COLOR_BORDER_SUBTLE, tags="card")
            self.tag_lower("card")


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
        self._protocol_display = tk.StringVar(self)
        self.configure(bg=COLOR_CARD)
        self._configure_dropdown_style()
        header = tk.Frame(self, bg=COLOR_CARD)
        header.pack(fill=tk.X, padx=24, pady=(20, 18))
        title_block = tk.Frame(header, bg=COLOR_CARD)
        title_block.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(title_block, text="编辑自定义 API" if values else "添加自定义 API", font=FONT_H2,
                 fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
        subtitle = tk.Label(title_block, text="连接你的模型服务，按需调整生成参数。", font=FONT_SMALL,
                            fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w", justify=tk.LEFT, width=1)
        subtitle.pack(fill=tk.X, pady=(6, 0))
        subtitle.bind("<Configure>", lambda e: subtitle.configure(wraplength=max(1, e.width)))
        tk.Frame(self, bg=COLOR_BORDER_SUBTLE, height=1).pack(fill=tk.X)

        footer = tk.Frame(self, bg=COLOR_CARD)
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Frame(footer, bg=COLOR_BORDER, height=1).pack(fill=tk.X)
        actions = tk.Frame(footer, bg=COLOR_CARD)
        actions.pack(side=tk.BOTTOM, fill=tk.X, padx=24, pady=(14, 16))
        self.save_button = FlatButton(actions, text="保存配置", command=self.save,
                                      width=120, height=40, variant="accent", bg_parent=COLOR_CARD)
        self.save_button.pack(side=tk.RIGHT)
        self.test_button = FlatButton(actions, text="测试连接", command=self.test,
                                      width=112, height=40, variant="secondary", bg_parent=COLOR_CARD)
        self.test_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.cancel_button = FlatButton(actions, text="取消", command=self.close,
                                        width=80, height=40, variant="secondary", bg_parent=COLOR_CARD)
        self.cancel_button.pack(side=tk.LEFT)
        self.status_var = tk.StringVar(self)
        self.status_label = tk.Label(footer, font=FONT_SMALL, width=1,
                                     fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, justify=tk.LEFT, anchor="w")
        def fit_status(_event=None):
            message = self.status_var.get()
            if message and not self.status_label.winfo_manager():
                self.status_label.pack(before=actions, fill=tk.X, padx=18, pady=(8, 2))
            elif not message:
                self.status_label.pack_forget()
            self.status_label.configure(text=middle_ellipsis(
                message, max(1, self.status_label.winfo_width() - 4),
                tkfont.Font(font=self.status_label.cget("font")).measure))
        self.status_label.bind("<Configure>", fit_status)
        self.status_var.trace_add("write", lambda *_args: fit_status())

        body = tk.Frame(self, bg=COLOR_BG_APP)
        body.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(body, bg=COLOR_BG_APP, highlightthickness=0, yscrollincrement=1)
        self.scroll_canvas = canvas
        scroll = MinimalScrollbar(body, target_canvas=canvas, width=7)
        scroll.bind("<Button-1>", lambda _e: self._cancel_scroll_animation(), add="+")
        canvas.configure(yscrollcommand=scroll.set_range)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 3))
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        form = tk.Frame(canvas, bg=COLOR_BG_APP, padx=18, pady=18)
        item = canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
        form.bind("<Configure>", self._schedule_scrollregion)
        self.entries = {}
        self.input_surfaces = {}

        def wrapped_label(parent, text, *, color=COLOR_TEXT_MUTED, pady=(0, 8)):
            label = tk.Label(parent, text=text, font=FONT_SMALL, bg=COLOR_CARD,
                             fg=color, anchor="w", justify=tk.LEFT, width=1)
            label.pack(fill=tk.X, pady=pady)
            label.bind("<Configure>", lambda e: label.configure(wraplength=max(1, e.width)))
            return label

        def card(title):
            container = _FormCard(form)
            container.pack(fill=tk.X, pady=(0, 12))
            shell = container.body
            tk.Label(shell, text=title, font=FONT_BODY_BOLD, bg=COLOR_CARD,
                     fg=COLOR_TEXT_PRIMARY, anchor="w").pack(fill=tk.X, pady=(0, 16))
            return shell

        def field(parent, label, key, choices=None, hint=None):
            group = tk.Frame(parent, bg=COLOR_CARD)
            heading = tk.Frame(group, bg=COLOR_CARD) if key == "thinking_level" else group
            if heading is not group:
                heading.pack(fill=tk.X, pady=(0, 6))
            label_widget = tk.Label(heading, text=label, font=FONT_BODY, bg=COLOR_CARD,
                                    fg=COLOR_TEXT_PRIMARY, anchor="w")
            if heading is group:
                label_widget.pack(fill=tk.X, pady=(0, 6))
            else:
                label_widget.pack(side=tk.LEFT)
            surface = _InputSurface(group)
            surface.pack(fill=tk.X)
            if key == "thinking_level":
                widget = ReasoningSlider(surface, variable=self.variables[key], values=choices, font=FONT_BODY)
                tk.Label(heading, textvariable=widget.label_var, font=FONT_SMALL,
                         fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="e").pack(side=tk.RIGHT)
            elif choices:
                variable = self._protocol_display if key == "protocol" else self.variables[key]
                widget = RoundedCombobox(surface, textvariable=variable, values=choices,
                                      state="readonly", font=FONT_BODY, width=1,
                                      style="CustomAPI.TCombobox")
            else:
                widget = tk.Entry(surface, textvariable=self.variables[key], font=FONT_BODY,
                                  bg=COLOR_BG_APP, fg=COLOR_TEXT_PRIMARY,
                                  insertbackground=COLOR_GENERATION_ACCENT,
                                  selectbackground="#EDE9FE", selectforeground=COLOR_TEXT_PRIMARY,
                                  relief=tk.FLAT, bd=0, highlightthickness=0, width=1)
            surface.attach(widget)
            self.input_surfaces[key] = surface
            if hint:
                wrapped_label(group, hint, pady=(5, 0))
            self.entries[key] = widget
            return group

        def pair(parent, first, second):
            host = tk.Frame(parent, bg=COLOR_CARD)
            host.pack(fill=tk.X, pady=(0, 10))
            left, right = first(host), second(host)
            mode = [None]
            label_font = tkfont.Font(master=self, font=FONT_BODY)
            threshold = 2 * (label_font.measure("最大输出 Token") + 72)
            def layout(event):
                dual = event is not None and event.width >= threshold
                if dual == mode[0]:
                    return
                mode[0] = dual
                host.columnconfigure(0, weight=1, uniform="fields" if dual else "")
                host.columnconfigure(1, weight=1 if dual else 0, uniform="fields" if dual else "")
                left.grid(row=0, column=0, sticky="nsew", padx=(0, 8) if dual else 0)
                right.grid(row=0 if dual else 1, column=1 if dual else 0, sticky="nsew",
                           padx=(8, 0) if dual else 0, pady=0 if dual else (14, 0))
            host.bind("<Configure>", layout)
            layout(None)

        connection = card("连接设置")
        pair(connection,
             lambda host: field(host, "名称", "name"),
             lambda host: field(host, "接口协议", "protocol", ["OpenAI 兼容", "Gemini 原生"]))
        protocol = self.entries["protocol"]
        field(connection, "API 地址", "url").pack(fill=tk.X, pady=(0, 4))
        self.protocol_hint = wrapped_label(connection, "", pady=(0, 10))
        field(connection, "模型 ID", "model").pack(fill=tk.X, pady=(0, 10))

        credentials = card("密钥与调用偏好")
        key_group = tk.Frame(credentials, bg=COLOR_CARD)
        key_group.pack(fill=tk.X, pady=(0, 10))
        key_heading = tk.Frame(key_group, bg=COLOR_CARD)
        key_heading.pack(fill=tk.X, pady=(0, 4))
        tk.Label(key_heading, text="API 密钥", font=FONT_BODY, bg=COLOR_CARD,
                 fg=COLOR_TEXT_PRIMARY).pack(side=tk.LEFT)
        self.key_toggle = tk.Button(key_heading, text="显示", font=FONT_SMALL,
                                    fg=COLOR_GENERATION_ACCENT, activeforeground=COLOR_GENERATION_ACCENT,
                                    bg=COLOR_CARD, activebackground=COLOR_CARD, relief=tk.FLAT,
                                    bd=0, padx=4, pady=0, cursor="hand2", command=self._toggle_key)
        self.key_toggle.pack(side=tk.RIGHT)
        key_edge = _InputSurface(key_group)
        key_edge.pack(fill=tk.X)
        self.key_entry = tk.Entry(key_edge, textvariable=self.key_var, show="*", font=FONT_BODY,
                                  bg=COLOR_BG_APP, fg=COLOR_TEXT_PRIMARY, relief=tk.FLAT, bd=0,
                                  selectbackground="#EDE9FE", selectforeground=COLOR_TEXT_PRIMARY,
                                  highlightthickness=0, insertbackground=COLOR_GENERATION_ACCENT, width=1)
        key_edge.attach(self.key_entry)
        self.input_surfaces["api_key"] = key_edge
        preference = tk.Frame(credentials, bg=COLOR_CARD)
        preference.pack(fill=tk.X, pady=(8, 0))
        self.priority_switch = _PrioritySwitch(preference, self.priority_var)
        self.priority_switch.pack(side=tk.RIGHT, padx=(16, 0))
        preference_copy = tk.Frame(preference, bg=COLOR_CARD)
        preference_copy.pack(side=tk.LEFT, fill=tk.X, expand=True)
        priority_label = tk.Label(preference_copy, text="优先使用此 API", font=FONT_BODY,
                                  fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD, anchor="w", cursor="hand2")
        priority_label.pack(fill=tk.X)
        priority_label.bind("<Button-1>", lambda _e: self.priority_switch.invoke())
        wrapped_label(preference_copy, "启用后，优先调用此服务。", pady=(4, 0))

        advanced_card = _FormCard(form)
        advanced_card.pack(fill=tk.X, pady=(0, 2))
        advanced = advanced_card.body
        advanced_header = tk.Frame(advanced, bg=COLOR_CARD)
        advanced_header.pack(fill=tk.X)
        tk.Label(advanced_header, text="高级参数", font=FONT_BODY_BOLD,
                 fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD).pack(side=tk.LEFT)
        self.advanced_button = FlatButton(advanced_header, text="展开", command=self._toggle_advanced,
                                          variant="secondary", width=64, height=32, bg_parent=COLOR_CARD)
        self.advanced_button.pack(side=tk.RIGHT)
        wrapped_label(advanced, "思考强度、输出格式与请求限制", pady=(6, 0))
        self.advanced_body = tk.Frame(advanced, bg=COLOR_CARD)
        self._advanced_open = False
        wrapped_label(self.advanced_body, "按服务商要求调整；不确定时可保留默认值。", pady=(12, 14))
        pair(self.advanced_body,
             lambda host: field(host, "思考强度", "thinking_level", ["auto", "none", "minimal", "low", "medium", "high", "xhigh"]),
             lambda host: field(host, "JSON 输出", "json_mode", ["json_object", "json_schema", "prompt"]))
        pair(self.advanced_body,
             lambda host: field(host, "最大输出 Token", "max_output_tokens"),
             lambda host: field(host, "请求超时（秒）", "request_timeout_seconds"))
        protocol.bind("<<ComboboxSelected>>", self._select_protocol)
        self._protocol_changed()
        for button in (self.save_button, self.test_button, self.cancel_button, self.advanced_button):
            button.set_responsive_scale(1.0)

        def bind_interactions(widget):
            widget.bind("<Escape>", self._on_escape, add="+")
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

    def _configure_dropdown_style(self):
        style = ttk.Style(self)
        # Keep images alive for the interpreter, including when an editor is reopened.
        arrow_name = "CustomAPI.Combobox.menu.downarrow"
        if arrow_name not in style.element_names():
            arrows = []
            for background, color, opened in ((COLOR_BG_APP, COLOR_TEXT_MUTED, False),
                                               ("#F1F5F9", "#94A3B8", False),
                                               (COLOR_BG_APP, COLOR_GENERATION_ACCENT, True)):
                bitmap = Image.new("RGB", (54, 54), background)
                points = [(15, 30), (27, 18), (39, 30)] if opened else [(15, 21), (27, 33), (39, 21)]
                ImageDraw.Draw(bitmap).line(points,
                                            fill=color, width=5, joint="curve")
                arrows.append(ImageTk.PhotoImage(bitmap.resize((18, 18), Image.Resampling.LANCZOS), master=self))
            self._root()._custom_api_dropdown_images = arrows
            style.element_create(arrow_name, "image", arrows[0], ("disabled", arrows[1]),
                                 ("pressed", arrows[2]), sticky="")
        style.layout("CustomAPI.TCombobox", [
            ("Combobox.padding", {"sticky": "nswe", "children": [
                (arrow_name, {"side": "right", "sticky": "ns"}),
                ("Combobox.textarea", {"sticky": "nswe"}),
            ]}),
        ])
        style.configure("CustomAPI.TCombobox", padding=0, arrowsize=14, borderwidth=0, relief="flat",
                        fieldbackground=COLOR_BG_APP, background=COLOR_BG_APP,
                        foreground=COLOR_TEXT_PRIMARY, arrowcolor=COLOR_TEXT_MUTED,
                        bordercolor=COLOR_BORDER, lightcolor=COLOR_BORDER, darkcolor=COLOR_BORDER,
                        selectbackground=COLOR_BG_APP, selectforeground=COLOR_TEXT_PRIMARY)
        style.map("CustomAPI.TCombobox",
                  foreground=[("disabled", COLOR_TEXT_MUTED), ("!disabled", COLOR_TEXT_PRIMARY)],
                  fieldbackground=[("disabled", "#F1F5F9"), ("readonly", COLOR_BG_APP)],
                  selectforeground=[("disabled", COLOR_TEXT_MUTED), ("!disabled", COLOR_TEXT_PRIMARY)],
                  selectbackground=[("!disabled", COLOR_BG_APP)],
                  focusfill=[("readonly", "focus", COLOR_BG_APP)],
                  bordercolor=[("focus", COLOR_BORDER_FOCUS)])

    def _toggle_key(self):
        visible = bool(self.key_entry.cget("show"))
        self.key_entry.configure(show="" if visible else "*")
        self.key_toggle.configure(text="隐藏" if visible else "显示")

    def _toggle_advanced(self):
        self._advanced_open = not self._advanced_open
        if self._advanced_open:
            self.advanced_body.pack(fill=tk.X)
        else:
            self.advanced_body.pack_forget()
        self.advanced_button._text = "收起" if self._advanced_open else "展开"
        self.advanced_button.redraw()
        self._schedule_scrollregion()

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
        for entry in self.entries.values():
            if isinstance(entry, RoundedCombobox):
                entry.close_dropdown()
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

    def _on_escape(self, _event=None):
        self.close()
        return "break"

    def _protocol_changed(self):
        native = self.variables["protocol"].get() == "gemini"
        self._protocol_display.set("Gemini 原生" if native else "OpenAI 兼容")
        self.protocol_hint.configure(text=(
            "Gemini 原生接口，例如 https://generativelanguage.googleapis.com"
            if native else "OpenAI 兼容接口，例如 https://api.example.com/v1"
        ))
        choices = ["auto", "low", "medium", "high"] if native else ["auto", "none", "minimal", "low", "medium", "high", "xhigh"]
        self.entries["thinking_level"].configure(values=choices)
        if self.variables["thinking_level"].get() not in choices:
            self.variables["thinking_level"].set("auto")
        self.entries["json_mode"].configure(state="disabled" if native else "readonly")
        self.input_surfaces["json_mode"].redraw()

    def _select_protocol(self, _event=None):
        self.variables["protocol"].set(
            "gemini" if self._protocol_display.get() == "Gemini 原生" else "openai"
        )
        self._protocol_changed()

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


class CustomAPIDialog(tk.Toplevel):
    """Resizable modal window around the shared, scrollable API editor."""

    def __init__(self, parent, values, api_key, post_ui, on_save, on_close=None):
        super().__init__(parent)
        self.withdraw()
        self._parent = parent.winfo_toplevel()
        self._on_close = on_close
        self._closed = False
        self._show_after_id = None
        self.title("编辑自定义 API" if values else "添加自定义 API")
        self.configure(bg=COLOR_CARD)
        self.transient(self._parent)
        self.resizable(True, True)
        # Match the parent when it is intentionally transparent (e.g. UI tests).
        self.attributes("-alpha", self._parent.attributes("-alpha"))

        scale = float(self.tk.call("tk", "scaling")) / (96 / 72)
        available_width = max(1, self.winfo_screenwidth() - 48)
        available_height = max(1, self.winfo_screenheight() - 96)
        # Form spacing is in pixels; scale the text allowance rather than all whitespace.
        width = min(available_width, round(620 + 120 * scale))
        height = min(available_height, round(650 + 130 * scale))
        self.minsize(min(width, round(460 + 60 * scale)), min(height, round(360 + 80 * scale)))
        self.maxsize(available_width, available_height)
        x = self._parent.winfo_rootx() + (self._parent.winfo_width() - width) // 2
        y = self._parent.winfo_rooty() + (self._parent.winfo_height() - height) // 2
        x = max(16, min(x, self.winfo_screenwidth() - width - 16))
        y = max(16, min(y, self.winfo_screenheight() - height - 64))
        self.geometry(f"{width}x{height}+{x}+{y}")

        self.editor = CustomAPIEditor(self, values, api_key, post_ui, on_save, on_close=self.close)
        self.editor.pack(fill=tk.BOTH, expand=True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", self.editor._on_escape)
        self.bind("<Destroy>", self._on_destroy, add="+")
        bind_visible_modal(self)
        self._show_after_id = self.after_idle(self._show)

    def _show(self):
        self._show_after_id = None
        if not self._closed:
            self.deiconify()
            self.lift()
            self.editor.entries["name"].focus_set()

    def close(self):
        if self._closed:
            return
        if self.grab_current() is self:
            self.grab_release()
        self.destroy()

    def _on_destroy(self, event):
        if event.widget is not self or self._closed:
            return
        self._closed = True
        if self._show_after_id is not None:
            self.after_cancel(self._show_after_id)
            self._show_after_id = None
        if self._on_close:
            self._on_close()
