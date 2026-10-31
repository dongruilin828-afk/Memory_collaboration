"""Compact queue cards; keep widgets alive while progress changes."""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from pathlib import Path
from urllib.parse import urlparse

from gui.batch_processing import TERMINAL, MODE_LABELS
from gui.batch_processing_dialog import ScrollArea, trash_image
from gui.theme import (COLOR_BG_APP, COLOR_CARD, COLOR_BORDER, COLOR_TEXT_PRIMARY,
                       COLOR_TEXT_MUTED, COLOR_GENERATION_ACCENT as COLOR_ACCENT, COLOR_DANGER, COLOR_SUCCESS,
                       FONT_BODY, FONT_BODY_BOLD, FONT_SMALL)
from gui.widgets import HoverTooltip, FlatProgressBar
from scripts.api_config import middle_ellipsis

STATUS_LABELS = {"queued": "排队中", "running": "处理中", "completed": "已完成",
                 "paused": "已暂停", "failed": "有失败项", "cancelled": "已停止"}
ITEM_LABELS = {**STATUS_LABELS, "failed": "失败", "capturing": "抓取中", "ready": "等待总结", "summarizing": "总结中"}


def readable_error(error):
    value = str(error or "")
    if any(code in value for code in ("ERR_CONNECTION_TIMED_OUT", "ERR_TIMED_OUT", "Timeout", "超时")):
        return "网页连接超时。请检查网络和系统代理是否可用，再重新添加该链接。"
    if any(code in value for code in ("ERR_PROXY_CONNECTION_FAILED", "ERR_TUNNEL_CONNECTION_FAILED")):
        return "无法连接系统代理。请启动代理软件并确认代理设置，再重试。"
    if "ERR_NAME_NOT_RESOLVED" in value:
        return "无法解析网站地址。请检查链接、网络和 DNS 设置。"
    if any(code in value for code in ("ProcessSingleton", "exitCode=21", "already in use")):
        return "登录浏览器正被其他任务使用。请等待该任务结束后重试。"
    return (value.splitlines() or [""])[0]


class BatchQueuePanel(tk.Frame):
    def __init__(self, parent, *, on_edit, on_remove, on_move, on_open, on_layout=lambda: None, on_add=None):
        super().__init__(parent, bg=COLOR_BG_APP)
        self.on_edit, self.on_remove, self.on_move, self.on_open = on_edit, on_remove, on_move, on_open
        self.on_layout = on_layout
        self.cards = {}
        self.views = []
        self._drag = None
        self._drag_preview = None
        self._drag_target = None
        self._columns = 2
        self._order = []
        self._trash = trash_image(self)
        font = tkfont.Font(master=self, font=FONT_BODY)
        self.minimum_card_width = max(245, font.measure("999 个文件") + font.measure("有失败项") + 80)
        self.minimum_width = 2 * self.minimum_card_width + 12
        heading = tk.Frame(self, bg=COLOR_BG_APP)
        heading.pack(fill=tk.X, pady=(0, 10))
        tk.Label(heading, text="批次队列", font=FONT_BODY_BOLD,
                 fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_APP).pack(side=tk.LEFT)
        self.add_button = tk.Button(heading, text="添加批次", command=on_add, font=FONT_SMALL,
            fg=COLOR_ACCENT, bg=COLOR_BG_APP, activebackground=COLOR_BG_APP,
            relief=tk.FLAT, cursor="hand2", padx=12)
        self.add_button.pack(side=tk.LEFT, padx=(8, 0))
        self.count = tk.Label(heading, text="", font=FONT_SMALL, fg=COLOR_TEXT_MUTED, bg=COLOR_BG_APP)
        self.count.pack(side=tk.RIGHT)
        self.area = ScrollArea(self, height=170, bg=COLOR_BG_APP)
        self.area.canvas.configure(width=self.minimum_width)
        self.area.pack(fill=tk.BOTH, expand=True)
        self.area.canvas.bind("<Configure>", self._resized, add="+")

    def set_batches(self, views):
        if self._drag and not any(value["id"] == self._drag
                                  and value["status"] not in TERMINAL for value in views):
            self._clear_drag()
        if self._drag_target and not any(value["id"] == self._drag_target
                                        and value["status"] not in TERMINAL for value in views):
            self._drag_target = None
        self.views = sorted(views, key=lambda value: value["status"] in TERMINAL)
        current = {view["id"] for view in self.views}
        for key in list(self.cards):
            if key not in current:
                self.cards.pop(key)["frame"].destroy()
        for position, view in enumerate(self.views, 1):
            if view["id"] not in self.cards:
                self.cards[view["id"]] = self._make_card(view["id"])
            self._update_card(self.cards[view["id"]], view, position)
        self.count.configure(text=f"{sum(view['status'] not in TERMINAL for view in views)} 个待处理 · {sum(view['status'] in TERMINAL for view in views)} 个已结束")
        order = [view["id"] for view in self.views]
        if order != self._order:
            self._order = order
            self._layout()

    def _make_card(self, batch_id):
        frame = tk.Frame(self.area.content, bg=COLOR_CARD, padx=12, pady=12,
                         highlightthickness=1, highlightbackground=COLOR_BORDER)
        frame._batch_id = batch_id
        frame.columnconfigure(0, weight=1)
        title = tk.Label(frame, text="", font=FONT_BODY_BOLD, bg=COLOR_CARD,
                         fg=COLOR_TEXT_PRIMARY, anchor="w", width=1, cursor="fleur")
        title.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        status = tk.Label(frame, text="", font=FONT_SMALL, bg=COLOR_CARD, fg=COLOR_ACCENT)
        status.grid(row=0, column=1, sticky="e")
        preview = tk.Label(frame, text="", font=FONT_SMALL, bg=COLOR_CARD,
                           fg=COLOR_TEXT_MUTED, anchor="w", width=1)
        preview.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 7))
        tooltip = HoverTooltip(preview, "")
        progress = FlatProgressBar(frame, height=5, bg_parent=COLOR_CARD, fill_color=COLOR_ACCENT)
        progress.grid(row=2, column=0, columnspan=2, sticky="ew")
        footer = tk.Frame(frame, bg=COLOR_CARD)
        footer.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        counts = tk.Label(footer, text="", font=FONT_SMALL, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, width=1, anchor="w")
        counts.grid(row=0, column=0, sticky="ew")
        edit = tk.Button(footer, text="编辑", command=lambda: self._edit(batch_id),
            font=FONT_SMALL, bg=COLOR_CARD, fg=COLOR_ACCENT, relief=tk.FLAT, padx=5, cursor="hand2")
        edit.grid(row=0, column=1)
        remove = tk.Button(footer, text="删除", image=self._trash, compound=tk.NONE,
            command=lambda: self.on_remove(batch_id), bg=COLOR_CARD, relief=tk.FLAT,
            padx=6, pady=3, cursor="hand2")
        remove.grid(row=0, column=2, padx=(3, 0))
        remove_tip = HoverTooltip(remove, "")
        title.bind("<ButtonPress-1>", lambda event: self._drag_start(batch_id, event))
        title.bind("<B1-Motion>", self._drag_motion)
        title.bind("<ButtonRelease-1>", self._drag_end)
        title.bind("<Double-Button-1>", lambda _event: self._edit(batch_id))
        frame.bind("<Configure>", lambda _event: self._fit_preview(batch_id))
        self.area.bind_wheel(frame)
        return dict(frame=frame, title=title, status=status, preview=preview, tooltip=tooltip,
                    progress=progress, counts=counts, edit=edit, remove=remove, remove_tip=remove_tip,
                    view=None, preview_text="")

    def _update_card(self, card, view, position):
        card["view"] = view
        kind = "链接" if view["kind"] == "links" else "文件"
        card["title"].configure(text=f"{position} · {view['total']} 个{kind}")
        card["status"].configure(text="正在收尾" if view.get("finishing") else "交接中" if view.get("pausing") else "编辑中" if view.get("editing") else STATUS_LABELS[view["status"]],
            fg=COLOR_DANGER if view["failed"] else COLOR_SUCCESS if view["status"] == "completed" else COLOR_ACCENT)
        active = next((item for item in view["items"] if item["status"] in {"capturing", "summarizing"}), None)
        first = view["items"][0]["source"]
        limit = f"自动（{view['concurrency']}）" if "requested_concurrency" in view and view["requested_concurrency"] is None else str(view["concurrency"])
        if view.get("auto_status"):
            limit = f"自动（{view['summaries']} 项处理中 · 上限 {view['concurrency']}）"
        card["preview_text"] = f"{limit} 并发 · " + (f"第 {active['index']} 项 · {active['message']}" if active else
                                Path(first).name if view["kind"] == "files" else first)
        card["tooltip"]._text = "\n".join([first] + ([active["message"]] if active else [])
            + ([view["auto_status"]["reason"]] if view.get("auto_status") else [])
            + (["上次调整：" + view["auto_status"]["last_adjustment"]]
               if (view.get("auto_status") or {}).get("last_adjustment") else []))
        card["progress"].set_progress(view["done"] / max(1, view["total"]))
        detail = f"{view['done']} / {view['total']}"
        if view["failed"]:
            detail += f" · {view['failed']} 失败"
        elif view["warnings"]:
            detail += f" · {view['warnings']} 警告"
        card["counts"].configure(text=detail)
        card["edit"].configure(text="详情" if view["started"] or view["status"] in TERMINAL else "编辑")
        card["remove_tip"]._text = ("停止此批次" if view["started"] and view["status"] not in TERMINAL else
                                      "从队列移除，保留已生成的结果文件")
        self._fit_preview(view["id"])

    def _fit_preview(self, batch_id):
        card = self.cards.get(batch_id)
        if card:
            label = card["preview"]
            label.configure(text=middle_ellipsis(card["preview_text"], max(0, label.winfo_width() - 4),
                                                 tkfont.Font(master=label, font=label.cget("font")).measure))

    def _resized(self, event):
        columns = 3 if event.width >= 3 * self.minimum_card_width + 24 else 2
        if columns != self._columns:
            self._columns = columns
            self._layout()

    def _layout(self):
        for column in range(3):
            self.area.content.columnconfigure(column, weight=1 if column < self._columns else 0,
                                               minsize=self.minimum_card_width if column < self._columns else 0)
        for index, view in enumerate(self.views):
            frame = self.cards[view["id"]]["frame"]
            frame.grid(row=index // self._columns, column=index % self._columns, sticky="nsew",
                       padx=(0, 12 if index % self._columns < self._columns - 1 else 0), pady=(0, 12))
        self.update_idletasks()
        height = max((card["frame"].winfo_reqheight() for card in self.cards.values()), default=145)
        rows = min(2, (len(self.views) + self._columns - 1) // self._columns)
        self.area.canvas.configure(height=min(380, max(145, rows * (height + 12))))
        self.on_layout()

    def _edit(self, batch_id):
        view = self.cards[batch_id]["view"]
        if not view["started"] and view["status"] not in TERMINAL:
            self.on_edit(batch_id)
            return
        dialog = tk.Toplevel(self)
        dialog.title("批次详情")
        dialog.configure(bg=COLOR_CARD)
        dialog.geometry("820x500")
        dialog.minsize(620, 320)
        toolbar = tk.Frame(dialog, bg=COLOR_CARD, padx=16, pady=12)
        toolbar.pack(fill=tk.X)
        tk.Label(toolbar, text=f"{view['done']} / {view['total']} · {STATUS_LABELS[view['status']]}",
                 font=FONT_BODY_BOLD, bg=COLOR_CARD).pack(side=tk.LEFT)
        tk.Button(toolbar, text="打开结果", command=lambda: self.on_open(view["output_dir"]),
                  state="normal" if any(item["output_dir"] for item in view["items"]) else "disabled").pack(side=tk.RIGHT)
        text = tk.Text(dialog, wrap="word", font=FONT_BODY, bg=COLOR_CARD, relief=tk.FLAT, padx=16, pady=12)
        text.tag_configure("heading", font=FONT_BODY_BOLD, spacing1=14, spacing3=6)
        text.tag_configure("error", foreground=COLOR_DANGER, spacing1=6, spacing3=6)
        text.tag_configure("muted", foreground=COLOR_TEXT_MUTED, spacing3=5)
        text.tag_configure("technical", foreground=COLOR_TEXT_MUTED, elide=True)
        bar = ttk.Scrollbar(dialog, command=text.yview)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        text.configure(yscrollcommand=bar.set)
        text.pack(fill=tk.BOTH, expand=True)
        for item in view["items"]:
            modes = " / ".join(MODE_LABELS[mode] for mode in item["modes"])
            name = Path(item["source"]).name if view["kind"] == "files" else urlparse(item["source"]).hostname or "链接"
            text.insert("end", f"{item['index']:02d} · {name}　{ITEM_LABELS[item['status']]}\n", "heading")
            text.insert("end", item["source"] + "\n", "muted")
            text.insert("end", f"生成模式：{modes}\n")
            text.insert("end", f"抓取/读取 {item.get('fetch_seconds', 0):.1f} 秒　总结 {item.get('generation_seconds', 0):.1f} 秒　等待操作 {item.get('wait_seconds', 0):.1f} 秒\n", "muted")
            if item["error"]:
                text.insert("end", "失败原因：" + readable_error(item["error"]) + "\n", "error")
                text.insert("end", "技术详情：\n" + item["error"] + "\n", "technical")
            elif item["status"] == "completed":
                text.insert("end", f"已保存 {len(item.get('saved_files', []))} 个文件。\n")
            elif item.get("message"):
                text.insert("end", "当前进度：" + readable_error(item["message"]) + "\n")
            for message in item["warnings"]:
                text.insert("end", "提醒：" + readable_error(message) + "\n", "muted")
            if item.get("output_dir"):
                text.insert("end", "结果位置：" + item["output_dir"] + "\n", "muted")
            text.insert("end", "\n" + "─" * 36 + "\n", "muted")
        text.configure(state="disabled")
        technical = tk.BooleanVar(dialog)
        tk.Checkbutton(toolbar, text="显示技术详情", variable=technical, bg=COLOR_CARD,
            command=lambda: text.tag_configure("technical", elide=not technical.get())).pack(side=tk.RIGHT, padx=12)

    def _drag_start(self, batch_id, event):
        card = self.cards[batch_id]
        if card["view"]["status"] in TERMINAL:
            return
        self._drag = batch_id
        self._drag_target = None
        self._drag_origin = (getattr(event, "x_root", 0), getattr(event, "y_root", 0))
        card["frame"].configure(highlightbackground=COLOR_ACCENT)

    def _drag_motion(self, event):
        if self._drag:
            if self._drag_preview is None and abs(event.x_root - self._drag_origin[0]) + abs(event.y_root - self._drag_origin[1]) >= 6:
                self._drag_preview = tk.Frame(self, bg=COLOR_CARD, padx=12, pady=10,
                    highlightthickness=2, highlightbackground=COLOR_ACCENT)
                tk.Label(self._drag_preview, text=self.cards[self._drag]["title"].cget("text"),
                    font=FONT_BODY_BOLD, bg=COLOR_CARD, fg=COLOR_ACCENT).pack()
                self._drag_preview.lift()
            if self._drag_preview is not None:
                self._drag_preview.place(x=max(0, min(self.winfo_width() - 200, event.x_root - self.winfo_rootx() + 10)),
                    y=max(0, min(self.winfo_height() - 55, event.y_root - self.winfo_rooty() + 10)), width=200)
                self._drag_target = None
                for key, card in self.cards.items():
                    frame = card["frame"]
                    if key != self._drag and card["view"]["status"] not in TERMINAL and (
                        frame.winfo_rootx() <= event.x_root <= frame.winfo_rootx() + frame.winfo_width() and
                        frame.winfo_rooty() <= event.y_root <= frame.winfo_rooty() + frame.winfo_height()):
                        self._drag_target = key
                        break
                for key, card in self.cards.items():
                    card["frame"].configure(highlightbackground=COLOR_ACCENT if key in {self._drag, self._drag_target} else COLOR_BORDER,
                                            highlightthickness=2 if key == self._drag_target else 1)
            top = self.area.canvas.winfo_rooty()
            if event.y_root < top + 24:
                self.area.canvas.yview_scroll(-1, "units")
            elif event.y_root > top + self.area.canvas.winfo_height() - 24:
                self.area.canvas.yview_scroll(1, "units")

    def _drag_end(self, event):
        source, before = self._drag, self._drag_target
        self._clear_drag()
        if not self._pending_card(source):
            return
        if self._pending_card(before):
            self.on_move(source, before)
            return
        target = self.winfo_containing(event.x_root, event.y_root)
        while target is not None and not hasattr(target, "_batch_id"):
            target = getattr(target, "master", None)
        if target is not None and target._batch_id != source and self._pending_card(target._batch_id):
            self.on_move(source, target._batch_id)

    def _pending_card(self, batch_id):
        card = self.cards.get(batch_id)
        return card is not None and card["view"]["status"] not in TERMINAL

    def _clear_drag(self):
        self._drag = self._drag_target = None
        if self._drag_preview is not None:
            self._drag_preview.destroy()
            self._drag_preview = None
        for card in self.cards.values():
            card["frame"].configure(highlightbackground=COLOR_BORDER, highlightthickness=1)
