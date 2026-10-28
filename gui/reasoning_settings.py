"""Optional per-profile override for servers without capability metadata."""

import tkinter as tk
import tkinter.font as tkfont

from gui.dropdown import RoundedCombobox
from gui.theme import (
    COLOR_CARD, COLOR_BG_APP, COLOR_TEXT_PRIMARY, COLOR_TEXT_MUTED,
    COLOR_DANGER, FONT_H2, FONT_BODY, FONT_SMALL,
)
from gui.widgets import FlatButton, MinimalScrollbar
from scripts.reasoning_capabilities import ReasoningCapability


def capability_source_text(capability):
    source = capability.evidence_source if capability.source == "cache" else capability.source
    label = {"catalog": "官方模型配置", "metadata": "服务端声明", "schema": "服务端参数规范",
             "probe_error": "检测：接口校验声明", "probe_accepted": "检测：参数已接受",
             "manual": "手动指定", "unknown": "尚未识别"}.get(source, "尚未识别")
    if capability.source == "cache":
        label += "（缓存）"
    if source in {"probe_error", "probe_accepted"}:
        label += "；未确认思考实际生效"
    return label


class ReasoningSettingsDialog(tk.Toplevel):
    def __init__(self, parent, protocol, capability, on_apply, *, surface_factory,
                 on_probe=None, on_cancel_probe=None):
        super().__init__(parent)
        self.withdraw()
        self.title("思考档位设置")
        self.transient(parent)
        self.resizable(False, False)
        self.configure(bg=COLOR_CARD)
        self.attributes("-alpha", parent.attributes("-alpha"))
        self._parent = parent
        self._previous_grab = self.grab_current()
        self._on_apply = on_apply
        self._closed = False
        self._api_protocol = protocol
        self._on_probe = on_probe
        self._on_cancel_probe = on_cancel_probe
        self._probing = False
        self._original_capability = capability
        self.templates = ({"Gemini 原生强度": "gemini", "思考 Token 预算": "budget", "仅使用默认": "none"}
                          if protocol == "gemini" else
                          {"标准思考强度": "effort", "DeepSeek 原生控制": "deepseek",
                           "思考 Token 预算": "budget", "思考开关": "toggle", "仅使用默认": "none"})
        self.defaults = {
            "effort": "none, minimal, low, medium, high, xhigh",
            "deepseek": "none, low, high, max",
            "gemini": "low, medium, high",
            "budget": "none, 1024, 2048, 4096, 8192, 16384",
            "toggle": "none, enabled", "none": "",
        }
        actions = tk.Frame(self, bg=COLOR_CARD, padx=24, pady=16)
        actions.pack(side=tk.BOTTOM, fill=tk.X)
        body = tk.Frame(self, bg=COLOR_CARD)
        body.pack(fill=tk.BOTH, expand=True)
        self.scroll_canvas = tk.Canvas(body, bg=COLOR_CARD, highlightthickness=0, yscrollincrement=1)
        scroll = MinimalScrollbar(body, target_canvas=self.scroll_canvas, width=7)
        self.scroll_canvas.configure(yscrollcommand=scroll.set_range)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 3))
        self.scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        content = tk.Frame(self.scroll_canvas, bg=COLOR_CARD, padx=24, pady=20)
        self._content = content
        content_item = self.scroll_canvas.create_window((0, 0), window=content, anchor="nw")
        self.scroll_canvas.bind("<Configure>", lambda e: self.scroll_canvas.itemconfigure(content_item, width=e.width))
        content.bind("<Configure>", lambda _e: self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all")))
        tk.Label(content, text="思考档位设置", font=FONT_H2, bg=COLOR_CARD,
                 fg=COLOR_TEXT_PRIMARY, anchor="w").pack(fill=tk.X)
        self._label(content, "手动设置仅对当前 API 地址和模型生效；请按服务商文档填写。", pady=(8, 12))
        self.source_var = tk.StringVar(self, value="当前来源：" + capability_source_text(capability))
        self._label(content, "", textvariable=self.source_var, pady=(0, 12))
        self.range_var = tk.StringVar(self)
        self._label(content, "", textvariable=self.range_var, pady=(0, 8))
        current = next((name for name, kind in self.templates.items() if kind == capability.kind), next(iter(self.templates)))
        self.template_var = tk.StringVar(self, value=current)
        self.levels_var = tk.StringVar(self, value=", ".join(capability.levels) if capability.known else self.defaults[self.templates[current]])
        self._label(content, "参数类型", body=True, pady=(0, 6))
        surface = surface_factory(content)
        surface.pack(fill=tk.X, pady=(0, 14))
        self.template = RoundedCombobox(surface, textvariable=self.template_var,
                                        values=tuple(self.templates), state="readonly", font=FONT_BODY,
                                        width=1, style="CustomAPI.TCombobox")
        surface.attach(self.template)
        self.template.bind("<<ComboboxSelected>>", self._template_changed)
        self._label(content, "参数位置（按服务商文档选择）", body=True, pady=(0, 6))
        surface = surface_factory(content)
        surface.pack(fill=tk.X, pady=(0, 14))
        self.parameter_var = tk.StringVar(self)
        self.parameter = RoundedCombobox(surface, textvariable=self.parameter_var,
                                         values=(), state="readonly", font=FONT_BODY,
                                         width=1, style="CustomAPI.TCombobox")
        surface.attach(self.parameter)
        self._set_parameters(capability.parameter)
        self._label(content, "支持的原生参数值（英文逗号分隔）", body=True, pady=(0, 6))
        surface = surface_factory(content)
        surface.pack(fill=tk.X)
        self.levels_entry = tk.Entry(surface, textvariable=self.levels_var, font=FONT_BODY,
                                     bg=COLOR_BG_APP, fg=COLOR_TEXT_PRIMARY, relief=tk.FLAT,
                                     bd=0, highlightthickness=0, width=1)
        surface.attach(self.levels_entry)
        self._label(content, "自动使用服务商默认参数，无需加入上述档位。预算类型填写 Token 数值。", pady=(8, 12))
        self._set_range(capability)
        self._original_signature = self._signature()
        self._label(content, "兼容性检测最多发送 8 次短生成请求，可能计费；仅在点击后运行。"
                    "参数被接受不代表思考实际生效。", pady=(0, 12))
        self.error_var = tk.StringVar(self)
        error = tk.Label(content, textvariable=self.error_var, font=FONT_SMALL, width=1,
                         bg=COLOR_CARD, fg=COLOR_DANGER, anchor="w", justify=tk.LEFT)
        self.message_label = error
        error.pack(fill=tk.X, pady=(0, 10))
        error.bind("<Configure>", lambda e: error.configure(wraplength=max(1, e.width)))
        buttons = []
        for text, command, side, variant in (("应用", self.apply, tk.RIGHT, "accent"),
                                               ("取消", self.close, tk.RIGHT, "secondary"),
                                               ("重新识别", self.redetect, tk.LEFT, "secondary"),
                                               ("检测兼容性", self.probe, tk.LEFT, "secondary")):
            button = FlatButton(actions, text=text, command=command, variant=variant,
                                width=110 if text in {"重新识别", "检测兼容性"} else 80,
                                height=36, bg_parent=COLOR_CARD)
            button.set_responsive_scale(1)
            button.pack(side=side, padx=(0, 8) if text in {"取消", "重新识别"} else 0)
            buttons.append(button)
        self._buttons = buttons
        self.probe_button = buttons[-1]
        self.probe_button.set_enabled(on_probe is not None)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<Destroy>", self._destroyed, add="+")
        font = tkfont.Font(self, font=FONT_BODY)
        width = min(self.winfo_screenwidth() - 48, max(520, font.measure("支持的原生参数值（英文逗号分隔）") + 80,
                                                          sum(button.winfo_reqwidth() for button in buttons) + 72))
        self.geometry(f"{width}x{min(self.winfo_screenheight() - 96, 640)}")
        # Resolve width-dependent wrapping before choosing the bounded height.
        for _ in range(3):
            self.update_idletasks()
        height = min(self.winfo_screenheight() - 96, content.winfo_reqheight() + actions.winfo_reqheight())
        x = max(8, min(parent.winfo_rootx() + (parent.winfo_width() - width) // 2,
                        self.winfo_screenwidth() - width - 16))
        y = max(8, min(parent.winfo_rooty() + (parent.winfo_height() - height) // 2,
                        self.winfo_screenheight() - height - 64))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.grab_set()
        self.levels_entry.focus_set()
        def bind_scroll(widget):
            widget.bind("<MouseWheel>", lambda e: self.scroll_canvas.yview_scroll(-int(e.delta / 120) * 48, "units"), add="+")
            widget.bind("<Button-4>", lambda _e: self.scroll_canvas.yview_scroll(-48, "units"), add="+")
            widget.bind("<Button-5>", lambda _e: self.scroll_canvas.yview_scroll(48, "units"), add="+")
            for child in widget.winfo_children():
                bind_scroll(child)
        bind_scroll(content)

    def _label(self, parent, text, *, body=False, pady=0, textvariable=None):
        label = tk.Label(parent, text=text, font=FONT_BODY if body else FONT_SMALL,
                         fg=COLOR_TEXT_PRIMARY if body else COLOR_TEXT_MUTED,
                         bg=COLOR_CARD, anchor="w", justify=tk.LEFT, width=1,
                         textvariable=textvariable)
        label.pack(fill=tk.X, pady=pady)
        label.bind("<Configure>", lambda e: label.configure(wraplength=max(1, e.width)))

    def _template_changed(self, _event=None):
        self.levels_var.set(self.defaults[self.templates[self.template_var.get()]])
        self._set_parameters()
        self.range_var.set("")
        self.error_var.set("")

    def _set_parameters(self, current=""):
        kind = self.templates[self.template_var.get()]
        if self._api_protocol == "gemini":
            choices = {"gemini": ("generationConfig.thinkingConfig.thinkingLevel",),
                       "budget": ("generationConfig.thinkingConfig.thinkingBudget",)}.get(kind, ("默认",))
        else:
            choices = {"effort": ("reasoning_effort", "reasoning.effort"),
                       "deepseek": ("reasoning_effort",),
                       "budget": ("thinking_budget", "thinking.budget_tokens"),
                       "toggle": ("enable_thinking", "thinking.type")}.get(kind, ("默认",))
        self.parameter.configure(values=choices)
        self.parameter_var.set(current if current in choices else choices[0])

    def _set_range(self, capability):
        text = ""
        if capability.kind == "budget":
            text = "预算滑条为应用划分的刻度，单位为 Token。"
            if capability.budget_min is not None and capability.budget_max is not None:
                text += f"接口声明范围：{capability.budget_min}–{capability.budget_max}。"
        self.range_var.set(text)

    def _signature(self):
        return self.template_var.get(), self.parameter_var.get(), self.levels_var.get()

    def probe(self):
        if self._probing or self._on_probe is None:
            return
        self._probing = True
        self.template.configure(state="disabled")
        self.parameter.configure(state="disabled")
        self.levels_entry.configure(state="disabled")
        for button in self._buttons:
            if button is not self._buttons[1]:  # Keep Cancel available.
                button.set_enabled(False)
        self.error_var.set("正在检测参数兼容性…可取消；本次最多 8 次请求。")
        self.message_label.configure(fg=COLOR_TEXT_MUTED)
        self._on_probe(self)

    def finish_probe(self, capability, message):
        if self._closed:
            return
        self._probing = False
        self.template.configure(state="readonly")
        self.parameter.configure(state="readonly")
        self.levels_entry.configure(state="normal")
        for button in self._buttons:
            button.set_enabled(True)
        self.error_var.set(message)
        if not capability.known:
            return
        current = next((name for name, kind in self.templates.items() if kind == capability.kind), None)
        if current is None:
            return
        self.template_var.set(current)
        self.levels_var.set(", ".join(capability.levels))
        self._set_parameters(capability.parameter)
        self._set_range(capability)
        self.source_var.set("当前来源：" + capability_source_text(capability))
        self._original_capability = capability
        self._original_signature = self._signature()

    def apply(self):
        if self._probing:
            return
        try:
            levels = tuple(value.strip() for value in self.levels_var.get().replace("，", ",").split(",") if value.strip())
            if self._original_capability.known and self._signature() == self._original_signature:
                capability = self._original_capability
            else:
                parameter = self.parameter_var.get()
                capability = ReasoningCapability(
                    self.templates[self.template_var.get()], levels, "manual", note="手动指定的模型能力",
                    parameter="" if parameter == "默认" else parameter,
                )
        except (ValueError, KeyError):
            self.message_label.configure(fg=COLOR_DANGER)
            self.error_var.set("档位值不适用于所选参数类型，请按服务商文档检查。")
            return
        self._on_apply(capability)
        self.close()

    def redetect(self):
        self._on_apply(None)
        self.close()

    def close(self):
        if self.winfo_exists():
            self.destroy()

    def _destroyed(self, event):
        if event.widget is not self or self._closed:
            return
        self._closed = True
        if self._probing and self._on_cancel_probe is not None:
            self._on_cancel_probe()
        previous = self._previous_grab
        if previous is not None and previous.winfo_exists() and previous.winfo_viewable():
            previous.grab_set()
