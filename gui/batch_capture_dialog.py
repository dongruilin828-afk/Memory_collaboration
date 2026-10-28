"""Small first-stage batch entry, without changing single-link generation settings."""

import tkinter as tk
from tkinter import ttk

from gui.batch_capture import validate_capture_links
from gui.theme import COLOR_BG_APP, COLOR_CARD, COLOR_TEXT_PRIMARY, COLOR_TEXT_MUTED, COLOR_DANGER, COLOR_ACCENT_BLUE, FONT_BODY, FONT_H2
from gui.ui_dispatch import bind_visible_modal


class BatchCaptureDialog(tk.Toplevel):
    def __init__(self, parent, *, on_start, on_stop, initial_text=""):
        super().__init__(parent)
        self.title("批量抓取")
        self.configure(bg=COLOR_BG_APP)
        self.transient(parent)
        self.on_start, self.on_stop = on_start, on_stop
        self.running = False
        self.close_when_done = False
        body = tk.Frame(self, bg=COLOR_BG_APP, padx=24, pady=20)
        body.pack(fill=tk.BOTH, expand=True)
        tk.Label(body, text="批量抓取链接", font=FONT_H2, fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP).pack(anchor="w")
        self.hint = tk.Label(body, text="每行一个链接 · 最多两个标签页同时抓取 · 复用登录状态 · 仅导出原始对话及附件",
                             font=FONT_BODY, fg=COLOR_TEXT_MUTED, bg=COLOR_BG_APP, anchor="w", justify="left")
        self.hint.pack(fill=tk.X, pady=(8, 12))
        entry_row = tk.Frame(body, bg=COLOR_CARD)
        entry_row.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(entry_row, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.links = tk.Text(entry_row, width=64, height=12, wrap="char", font=FONT_BODY,
                             undo=True, yscrollcommand=scrollbar.set)
        self.links.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.configure(command=self.links.yview)
        self.links.insert("1.0", initial_text)
        self.status = tk.Label(body, text="请先通过单链接功能完成所需平台的登录。", font=FONT_BODY,
                               fg=COLOR_TEXT_MUTED, bg=COLOR_BG_APP, anchor="w", justify="left")
        self.status.pack(fill=tk.X, pady=(12, 8))
        buttons = tk.Frame(body, bg=COLOR_BG_APP)
        buttons.pack(fill=tk.X)
        self.start_button = tk.Button(buttons, text="开始批量抓取", command=self.start_or_stop,
                                      font=FONT_BODY, bg=COLOR_ACCENT_BLUE, fg="white", padx=16, pady=8)
        self.start_button.pack(side=tk.RIGHT)
        self.close_button = tk.Button(buttons, text="关闭", command=self.close, font=FONT_BODY, padx=16, pady=8)
        self.close_button.pack(side=tk.RIGHT, padx=(0, 12))
        body.bind("<Configure>", lambda event: [label.configure(wraplength=max(1, event.width - 48))
                                                for label in (self.hint, self.status)])
        self.update_idletasks()
        self.minsize(max(520, buttons.winfo_reqwidth() + 48), self.winfo_reqheight())
        self.protocol("WM_DELETE_WINDOW", self.close)
        bind_visible_modal(self)
        self.grab_set()
        self.links.focus_set()
        self.bind("<Destroy>", self._destroyed, add="+")

    def start_or_stop(self):
        if self.running:
            self.on_stop()
            self.start_button.configure(state="disabled", text="正在停止…")
            return
        try:
            links = validate_capture_links(self.links.get("1.0", "end" ).splitlines())
        except ValueError as error:
            self.status.configure(text=str(error), fg=COLOR_DANGER)
            return
        if self.on_start(links, self):
            self.running = True
            self.links.configure(state="disabled")
            self.start_button.configure(text="停止抓取")
            self.status.configure(text="正在启动共享浏览器…", fg=COLOR_TEXT_MUTED)

    def show_progress(self, text):
        self.status.configure(text=text, fg=COLOR_TEXT_MUTED)

    def finish(self, text):
        self.running = False
        self.links.configure(state="normal")
        self.start_button.configure(state="normal", text="开始批量抓取")
        self.status.configure(text=text)
        if self.close_when_done:
            self.destroy()

    def close(self):
        if self.running:
            self.close_when_done = True
            self.on_stop()
            self.start_button.configure(state="disabled", text="正在停止…")
            self.status.configure(text="正在释放标签页，完成后关闭。")
        else:
            self.destroy()

    def _destroyed(self, event):
        if event.widget is self and self.running:
            self.on_stop()
