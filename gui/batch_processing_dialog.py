"""Batch plan editor: links/files, per-item modes and a bounded native table."""
from pathlib import Path
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk

from gui.batch_capture import validate_capture_links
from gui.batch_processing import BatchPlan, ItemPlan, MODES, MODE_LABELS
from gui.theme import (COLOR_BG_APP, COLOR_CARD, COLOR_BORDER, COLOR_TEXT_PRIMARY,
                       COLOR_TEXT_MUTED, COLOR_GENERATION_ACCENT as COLOR_ACCENT, COLOR_DANGER, FONT_BODY,
                       FONT_BODY_BOLD, FONT_H2)
from gui.ui_dispatch import clear_background_focus
from gui.widgets import HoverTooltip


class ScrollArea(tk.Frame):
    def __init__(self, parent, *, height=320, bg=COLOR_CARD):
        super().__init__(parent, bg=bg)
        bar = ttk.Scrollbar(self, orient=tk.VERTICAL)
        self.scrollbar = bar
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas = tk.Canvas(self, height=height, bg=bg, bd=0, highlightthickness=0,
                                yscrollcommand=bar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bar.configure(command=self.canvas.yview)
        self.content = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.window, width=event.width))
        self.content.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.bind_wheel(self)

    def bind_wheel(self, widget):
        if not isinstance(widget, tk.Text):
            widget.bind("<MouseWheel>", self._wheel)
        for child in widget.winfo_children():
            self.bind_wheel(child)

    def _wheel(self, event):
        if event.delta:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"


def trash_image(master):
    image = tk.PhotoImage(master=master, width=18, height=20)
    for rectangle in ((4, 5, 14, 6), (7, 2, 11, 3), (2, 4, 16, 5),
                      (4, 6, 5, 17), (13, 6, 14, 17), (5, 17, 13, 18),
                      (7, 8, 8, 15), (10, 8, 11, 15)):
        image.put(COLOR_DANGER, to=rectangle)
    return image


class BatchProcessingDialog(tk.Toplevel):
    def __init__(self, parent, *, on_submit, initial_text="", plan=None, draft=None, on_close=None):
        super().__init__(parent)
        self.withdraw()
        self.title("编辑批次" if plan else "批量处理")
        self.configure(bg=COLOR_BG_APP)
        self.on_submit = on_submit
        self.on_close = on_close
        self._submitted = False
        self.kind = tk.StringVar(self, value=plan.kind if plan else "links")
        self.concurrency = tk.IntVar(self, value=plan.concurrency if plan else 3)
        self.drafts = {"links": [], "files": []}
        if plan:
            self.drafts[plan.kind] = [dict(source=item.source, modes=set(item.modes)) for item in plan.items]
        if draft:
            self.kind.set(draft.get("kind", "links"))
            self.concurrency.set(draft.get("concurrency", 3))
            for key in self.drafts:
                self.drafts[key] = [dict(source=item["source"], modes=set(item["modes"])) for item in draft.get(key, [])]
        self.rows = []
        self._row_views = {"links": {}, "files": {}}
        self._header_kind = None
        self._rendered_stage = None
        self._rendering = False
        self._row_height = {}
        self._viewport_after = None
        self._font = tkfont.Font(master=self, font=FONT_BODY)
        self._bold_font = tkfont.Font(master=self, font=FONT_BODY_BOLD)
        self._row_traces = []
        self._append_after = None
        self.column_vars = {}
        self._trash = trash_image(self)
        body = tk.Frame(self, bg=COLOR_BG_APP, padx=22, pady=18)
        body.pack(fill=tk.BOTH, expand=True)
        self.heading = tk.Label(body, text="编辑批次" if plan else "批量处理", font=FONT_H2,
                                bg=COLOR_BG_APP, fg=COLOR_TEXT_PRIMARY)
        toolbar = tk.Frame(body, bg=COLOR_BG_APP)
        self.toolbar = toolbar
        toolbar.pack(fill=tk.X, pady=(0, 14))
        self.tabs = []
        for key, label in (("links", "对话链接"), ("files", "已有文件")):
            button = tk.Radiobutton(toolbar, text=label, value=key, variable=self.kind,
                command=self._render, indicatoron=False, font=self._bold_font,
                bg=COLOR_CARD, selectcolor=COLOR_ACCENT, fg=COLOR_TEXT_PRIMARY,
                activebackground=COLOR_CARD, relief=tk.FLAT, padx=18, pady=8,
                highlightthickness=1, highlightbackground=COLOR_BORDER)
            button.pack(side=tk.LEFT, padx=(0, 8))
            self.tabs.append(button)
        settings = tk.Frame(toolbar, bg=COLOR_BG_APP)
        settings.pack(side=tk.RIGHT)
        tk.Label(settings, text="并发数量", font=self._font, fg=COLOR_TEXT_PRIMARY,
                 bg=COLOR_BG_APP).pack(side=tk.LEFT, padx=(0, 10))
        self.concurrency_box = ttk.Combobox(settings, textvariable=self.concurrency,
                                          values=(1, 2, 3), width=3, state="readonly", font=self._font)
        self.concurrency_box.pack(side=tk.LEFT)
        self.file_controls = tk.Frame(body, bg=COLOR_BG_APP)
        self.add_files_button = self._button(self.file_controls, "添加文件", self.choose_files)
        self.add_files_button.pack(side=tk.LEFT, padx=(0, 10))
        self.add_folder_button = self._button(self.file_controls, "添加文件夹", self.choose_folder)
        self.add_folder_button.pack(side=tk.LEFT)

        self.input_panel = tk.Frame(body, bg=COLOR_CARD, padx=12, pady=12)
        self.links_text = tk.Text(self.input_panel, height=10, width=50, font=self._font,
                                  wrap="char", undo=True, bd=0, highlightthickness=1,
                                  highlightbackground=COLOR_BORDER)
        self.links_text.pack(fill=tk.BOTH, expand=True)
        self.links_text.insert("1.0", draft.get("input", initial_text) if draft else initial_text)
        self.input_actions = tk.Frame(self.input_panel, bg=COLOR_CARD)
        self.input_actions.pack(fill=tk.X, pady=(10, 0))
        self.identify_button = self._button(self.input_actions, "识别", self.identify, accent=True)
        self.identify_button.pack(side=tk.RIGHT)
        self.input_close = self._button(self.input_actions, "关闭", self.close)
        self.input_close.pack(side=tk.RIGHT, padx=(0, 10))
        self.links_text.bind("<Control-Return>", lambda _event: self.identify() or "break")

        self.table_header = tk.Frame(body, bg=COLOR_CARD, pady=8)
        self.area = ScrollArea(body, height=330)
        def scrolled(first, last):
            self.area.scrollbar.set(first, last)
            self._schedule_row_viewport()
        self.area.canvas.configure(yscrollcommand=scrolled)
        self.area.canvas.bind("<Configure>", lambda _event: self._schedule_row_viewport(), add="+")
        self.row_host = tk.Frame(self.area.content, bg=COLOR_CARD)
        self.row_host.pack(fill=tk.X)
        self.row_host.columnconfigure(0, weight=1)
        self.append_panel = tk.Frame(self.area.content, bg=COLOR_CARD, padx=8, pady=12)
        self.plus_button = self._button(self.append_panel, "+ 添加链接", self.show_append)
        self.plus_button.pack(anchor="w")
        self.append_text = tk.Text(self.append_panel, height=3, width=30, font=self._font,
                                   wrap="char", undo=True, highlightthickness=1, highlightbackground=COLOR_BORDER)
        self.append_actions = tk.Frame(self.append_panel, bg=COLOR_CARD)
        self.append_identify = self._button(self.append_actions, "识别", lambda: self.identify(append=True), accent=True)
        self.append_identify.pack(side=tk.RIGHT)
        self.append_cancel = self._button(self.append_actions, "取消", self.cancel_append)
        self.append_cancel.pack(side=tk.RIGHT, padx=(0, 10))
        self.append_text.bind("<Return>", self._append_return)
        self.append_text.bind("<Shift-Return>", lambda _event: None)

        self.notice = tk.Label(body, text="", font=self._font, bg=COLOR_BG_APP,
                               fg=COLOR_DANGER, anchor="w", justify="left", width=1)
        self.footer = tk.Frame(body, bg=COLOR_BG_APP)
        self.footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(14, 0))
        self.submit_button = self._button(self.footer, "保存批次" if plan else "添加批次", self.submit, accent=True)
        self.submit_button.pack(side=tk.RIGHT)
        self.close_button = self._button(self.footer, "关闭", self.close)
        self.close_button.pack(side=tk.RIGHT, padx=(0, 10))
        self.count_label = tk.Label(self.footer, text="", font=self._font,
                                    fg=COLOR_TEXT_MUTED, bg=COLOR_BG_APP)
        self.count_label.pack(side=tk.LEFT)
        self.notice.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        body.bind("<Configure>", lambda event: self.notice.configure(wraplength=max(1, event.width - 44)))
        self._render()
        if draft and draft.get("append"):
            self.show_append()
            self.append_text.insert("1.0", draft["append"])
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        self.bind("<Button-1>", clear_background_focus, add="+")
        self.bind("<Destroy>", self._destroyed, add="+")
        self.update_idletasks()
        width = max(self.minsize()[0], min(1020, self.winfo_screenwidth() - 60))
        height = min(max(570, self.winfo_reqheight()), self.winfo_screenheight() - 100)
        self.geometry(f"{width}x{height}")
        self.deiconify()
        self.links_text.focus_set() if not plan else self.submit_button.focus_set()

    def _button(self, parent, text, command, *, accent=False):
        return tk.Button(parent, text=text, command=command, font=self._font,
                         bg=COLOR_ACCENT if accent else COLOR_CARD,
                         fg="white" if accent else COLOR_TEXT_PRIMARY,
                         activebackground=COLOR_ACCENT if accent else COLOR_BG_APP,
                         activeforeground="white" if accent else COLOR_TEXT_PRIMARY,
                         relief=tk.FLAT, cursor="hand2", padx=14, pady=7, takefocus=True,
                         highlightthickness=1, highlightbackground=COLOR_BORDER)

    def identify(self, append=False):
        text = self.append_text if append else self.links_text
        links = []
        for line in text.get("1.0", "end").splitlines():
            try:
                links.extend(validate_capture_links([line]))
            except ValueError:
                continue
        if not links:
            if append:
                self.cancel_append()
            self.notice.configure(text="没有合法的对话链接。" if append else "请输入至少一个合法的对话链接。")
            return False
        self.drafts["links"].extend(dict(source=link, modes={"raw"}) for link in links)
        text.delete("1.0", "end")
        self.notice.configure(text="")
        self._render()
        self.cancel_append()
        self.area.canvas.yview_moveto(1)
        return True

    def _append_return(self, _event):
        self.identify(append=True)
        return "break"

    def show_append(self):
        if self._append_after is not None:
            self.after_cancel(self._append_after)
        self.plus_button.pack_forget()
        self.append_text.pack(fill=tk.X)
        self.append_actions.pack(fill=tk.X, pady=(8, 0))
        self.append_text.focus_set()
        def scroll():
            self._append_after = None
            self.area.canvas.yview_moveto(1)
        self._append_after = self.after_idle(scroll)

    def cancel_append(self):
        self.append_text.delete("1.0", "end")
        self.append_text.pack_forget()
        self.append_actions.pack_forget()
        self.plus_button.pack(anchor="w")

    def draft_state(self):
        return dict(kind=self.kind.get(), concurrency=self.concurrency.get(),
                    input=self.links_text.get("1.0", "end-1c"), append=self.append_text.get("1.0", "end-1c"),
                    **{key: [dict(source=row["source"], modes=list(row["modes"])) for row in rows]
                       for key, rows in self.drafts.items()})

    def close(self):
        if self.on_close:
            self.on_close(None if self._submitted else self.draft_state())
        self.destroy()

    def _destroyed(self, event):
        if event.widget is self:
            if self._append_after is not None:
                self.after_cancel(self._append_after)
            if self._viewport_after is not None:
                self.after_cancel(self._viewport_after)
            for variable, trace in self._row_traces:
                variable.trace_remove("write", trace)
            self._row_traces.clear()

    def choose_files(self):
        paths = filedialog.askopenfilenames(parent=self, title="添加已有文件",
                    filetypes=[("Markdown 和文本", "*.md *.txt"), ("所有文件", "*.*")])
        if paths:
            self.add_paths(paths)

    def choose_folder(self):
        folder = filedialog.askdirectory(parent=self, title="添加文件夹")
        if folder:
            paths = []
            for base, directories, files in os.walk(folder, followlinks=False):
                directories[:] = sorted(name for name in directories if not Path(base, name).is_symlink())
                paths.extend(Path(base, name) for name in sorted(files) if Path(name).suffix.lower() in {".md", ".txt"})
            if not paths:
                self.notice.configure(text="该文件夹中没有 .md 或 .txt 文件。")
            else:
                self.add_paths(paths)

    def add_paths(self, paths):
        existing = {os.path.normcase(row["source"]) for row in self.drafts["files"]}
        invalid = []
        for path in paths:
            resolved = str(Path(path).resolve())
            if Path(resolved).suffix.lower() not in {".md", ".txt"} or not Path(resolved).is_file():
                invalid.append(Path(resolved).name)
            elif os.path.normcase(resolved) not in existing:
                self.drafts["files"].append(dict(source=resolved, modes={"normal"}))
                existing.add(os.path.normcase(resolved))
        skipped = "、".join(name if len(name) <= 30 else name[:14] + "…" + name[-14:] for name in invalid[:3])
        self.notice.configure(text=(f"已跳过 {len(invalid)} 个不支持的文件：{skipped}" + ("…" if len(invalid) > 3 else "")) if invalid else "")
        self._render()

    def replace_file(self, index):
        path = filedialog.askopenfilename(parent=self, title="重新选择文件",
                    filetypes=[("Markdown 和文本", "*.md *.txt")])
        if path:
            self.drafts["files"][index]["source"] = str(Path(path).resolve())
            self._render()

    def move_row(self, index, offset):
        rows = self.drafts[self.kind.get()]
        other = index + offset
        if 0 <= other < len(rows):
            rows[index], rows[other] = rows[other], rows[index]
            self._render()

    def delete_row(self, index):
        del self.drafts[self.kind.get()][index]
        self._render()

    def clear(self):
        self.drafts[self.kind.get()].clear()
        self._render()

    def select_column(self, mode):
        selected = self.column_vars[mode].get()
        for row in self.drafts[self.kind.get()]:
            row["modes"].add(mode) if selected else row["modes"].discard(mode)
        for row in self.rows:
            row["checks"][mode].set(selected)

    def _mode_changed(self, draft, mode, variable):
        draft["modes"].add(mode) if variable.get() else draft["modes"].discard(mode)
        self._sync_columns()

    def _sync_columns(self):
        drafts = self.drafts[self.kind.get()]
        for mode, variable in self.column_vars.items():
            variable.set(bool(drafts) and all(mode in item["modes"] for item in drafts))

    def _render(self):
        if self._rendering:
            return
        self._rendering = True
        try:
            self._render_contents()
        finally:
            self._rendering = False

    def _schedule_row_viewport(self):
        if not self._rendering and len(self.drafts[self.kind.get()]) > 40 and self._viewport_after is None:
            def refresh():
                self._viewport_after = None
                self._render()
            self._viewport_after = self.after_idle(refresh)

    def _render_contents(self):
        kind = self.kind.get()
        drafts = self.drafts[kind]
        virtual = len(drafts) > 40
        stage = (kind, bool(drafts), virtual)
        if stage != self._rendered_stage:
            for widget in (self.file_controls, self.input_panel, self.table_header, self.area):
                widget.pack_forget()
            for key, views in self._row_views.items():
                if key != kind:
                    for view in views.values():
                        view["frame"].grid_remove()
                        view["frame"].place_forget()
            for key, button in zip(("links", "files"), self.tabs):
                button.configure(fg="white" if key == kind else COLOR_TEXT_PRIMARY)
            if kind == "files":
                self.file_controls.pack(fill=tk.X, pady=(0, 12))
            if kind == "links" and not drafts:
                self.input_panel.pack(fill=tk.BOTH, expand=True)
                self.footer.pack_forget()
            else:
                self.footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(14, 0))
                self.table_header.pack(fill=tk.X, padx=(0, self.area.scrollbar.winfo_reqwidth()))
                self.area.pack(fill=tk.BOTH, expand=True)
            self.append_panel.pack_forget()
            if kind == "links":
                self.append_panel.pack(fill=tk.X)
            self._rendered_stage = stage
        self.rows = []
        modes = MODES if kind == "links" else MODES[1:]
        if self._header_kind != kind:
            self._build_header(kind, modes)
        views = self._row_views[kind]
        if virtual and kind not in self._row_height:
            first = views.get(id(drafts[0]))
            if first is None:
                first = views[id(drafts[0])] = self._make_row(drafts[0], kind, modes)
            self.update_idletasks()
            self._row_height[kind] = first["frame"].winfo_reqheight()
        self.row_host.grid_propagate(not virtual)
        if virtual:
            height = self._row_height[kind]
            self.row_host.configure(height=height * len(drafts))
            top = max(0, self.area.canvas.canvasy(0) - self.row_host.winfo_y())
            first_index = min(len(drafts) - 1, max(0, int(top // height) - 2))
            last_index = min(len(drafts), int((top + max(330, self.area.canvas.winfo_height())) // height) + 3)
        else:
            first_index, last_index = 0, len(drafts)
        visible = list(enumerate(drafts))[first_index:last_index]
        current = {id(row) for _, row in visible}
        for key in list(views):
            if key not in current:
                view = views.pop(key)
                if view.get("trace"):
                    view["variable"].trace_remove("write", view["trace"])
                    self._row_traces.remove((view["variable"], view["trace"]))
                view["frame"].destroy()
        for index, draft in visible:
            view = views.get(id(draft))
            if view is None:
                view = views[id(draft)] = self._make_row(draft, kind, modes)
            moved = view["index"] != index
            if moved:
                view["index"] = index
                view["number"].configure(text=str(index + 1))
            frame = view["frame"]
            if virtual:
                if moved or frame.winfo_manager() != "place":
                    frame.grid_forget()
                    frame.place(x=0, y=index * height, relwidth=1, height=height)
            elif moved or frame.winfo_manager() != "grid":
                frame.place_forget()
                frame.grid(row=index, column=0, sticky="ew")
            for offset, button in view["arrows"]:
                enabled = 0 <= index + offset < len(drafts)
                if view["arrow_enabled"].get(offset) != enabled:
                    view["arrow_enabled"][offset] = enabled
                    button.configure(state="normal" if enabled else "disabled")
            view["tooltip"]._text = draft["source"]
            if kind == "files" and view["variable"].get() != draft["source"]:
                view["variable"].set(draft["source"])
                view["fit_name"]()
            self.rows.append(view)
        self._sync_columns()
        self.count_label.configure(text=f"{len(drafts)} 项" if drafts else "")
        self.submit_button.configure(state="normal" if drafts else "disabled")
        self._set_minimums(kind, drafts)

    def _build_header(self, kind, modes):
        self._header_kind = kind
        self.column_vars.clear()
        for widget in self.table_header.winfo_children():
            widget.destroy()
        for column in range(8):
            self.table_header.columnconfigure(column, minsize=0, weight=0)
        for column, title in ((0, "排序"), (1, "序号"), (2, "链接" if kind == "links" else "文件")):
            tk.Label(self.table_header, text=title, font=self._bold_font, bg=COLOR_CARD,
                     fg=COLOR_TEXT_MUTED, anchor="w" if column == 2 else "center").grid(row=0, column=column, sticky="ew")
        for column, mode in enumerate(modes, 3):
            variable = tk.BooleanVar(self)
            self.column_vars[mode] = variable
            check = tk.Checkbutton(self.table_header, text=MODE_LABELS[mode], variable=variable,
                command=lambda key=mode: self.select_column(key), font=self._font,
                bg=COLOR_CARD, activebackground=COLOR_CARD, fg=COLOR_TEXT_PRIMARY,
                highlightthickness=0)
            check.grid(row=0, column=column, sticky="w", padx=4)
            HoverTooltip(check, "全选/取消所有项目的" + MODE_LABELS[mode])
        clear_button = self._button(self.table_header, "清空", self.clear)
        clear_button.grid(row=0, column=3 + len(modes), padx=(4, 0))
        arrow_probe = tk.Button(self.table_header, text="↑", font=self._font, relief=tk.FLAT, padx=5, pady=4)
        # Native focus/border padding also scales; text width alone clips the
        # arrow column and shifts every checkbox at high display DPI.
        self._widths = [max(70, 2 * arrow_probe.winfo_reqwidth()), self._font.measure("序号") + 12, 240]
        arrow_probe.destroy()
        self._widths += [max(widget.winfo_reqwidth() for widget in self.table_header.grid_slaves(column=column)) + 8
                         for column in range(3, 4 + len(modes))]
        for column, width in enumerate(self._widths):
            self.table_header.columnconfigure(column, weight=1 if column == 2 else 0, minsize=width)

    def _make_row(self, draft, kind, modes):
        row = tk.Frame(self.row_host, bg=COLOR_CARD, pady=6)
        view = dict(frame=row, index=-1, arrow_enabled={})
        order = tk.Frame(row, bg=COLOR_CARD)
        order.grid(row=0, column=0)
        arrows = []
        for offset, text in ((-1, "↑"), (1, "↓")):
            button = tk.Button(order, text=text, font=self._font, bg=COLOR_CARD,
                fg=COLOR_TEXT_MUTED, relief=tk.FLAT, padx=5, pady=4, cursor="hand2",
                command=lambda step=offset: self.move_row(view["index"], step))
            button.pack(side=tk.LEFT)
            arrows.append((offset, button))
        number = tk.Label(row, bg=COLOR_CARD, font=self._font, fg=COLOR_TEXT_MUTED)
        number.grid(row=0, column=1)
        variable = tk.StringVar(self, value=draft["source"])
        if kind == "links":
            source = tk.Entry(row, textvariable=variable, font=self._font, width=1,
                              relief=tk.SOLID, bd=1, highlightthickness=0)
            trace = variable.trace_add("write", lambda *_args, value=variable, item=draft: item.update(source=value.get()))
            self._row_traces.append((variable, trace))
            view["trace"] = trace
        else:
            source = self._button(row, Path(draft["source"]).name, lambda: self.replace_file(view["index"]))
            source.configure(anchor="w", width=1, padx=8, font=self._font)
            def fit_name(_event=None, button=source):
                from scripts.api_config import middle_ellipsis
                button.configure(text=middle_ellipsis(Path(draft["source"]).name, max(0, button.winfo_width() - 20), self._font.measure))
            source.bind("<Configure>", fit_name)
            view["fit_name"] = fit_name
        source.grid(row=0, column=2, sticky="ew", ipady=7, padx=(4, 10))
        tooltip = HoverTooltip(source, draft["source"])
        checks = {}
        for column, mode in enumerate(modes, 3):
            value = tk.BooleanVar(self, value=mode in draft["modes"])
            check = tk.Checkbutton(row, variable=value, bg=COLOR_CARD,
                font=self._font,
                activebackground=COLOR_CARD, highlightthickness=0,
                command=lambda item=draft, key=mode, var=value: self._mode_changed(item, key, var))
            check.grid(row=0, column=column, sticky="w", padx=4)
            HoverTooltip(check, MODE_LABELS[mode])
            checks[mode] = value
        delete = tk.Button(row, text="删除", image=self._trash, compound=tk.NONE,
            command=lambda: self.delete_row(view["index"]), bg=COLOR_CARD, relief=tk.FLAT,
            activebackground=COLOR_BG_APP, padx=8, pady=5, cursor="hand2")
        delete.grid(row=0, column=3 + len(modes), padx=(4, 0))
        HoverTooltip(delete, "删除此项")
        for column, width in enumerate(self._widths):
            row.columnconfigure(column, weight=1 if column == 2 else 0, minsize=width)
        self.area.bind_wheel(row)
        view.update(source=source, variable=variable, checks=checks, delete=delete,
                    arrows=arrows, number=number, tooltip=tooltip)
        return view

    def _set_minimums(self, kind, drafts):
        widths = self._widths
        chrome_height = sum(widget.winfo_reqheight() for widget in
                            (self.toolbar, self.footer, self.notice)) + 74
        if kind == "files":
            chrome_height += self.file_controls.winfo_reqheight() + 12
        if drafts or kind == "files":
            chrome_height += self.table_header.winfo_reqheight()
        minimum_height = max(420, chrome_height + max(80, self._font.metrics("linespace") * 3))
        self.minsize(max(720, sum(widths) + 62, self.footer.winfo_reqwidth() + 44,
                         self.toolbar.winfo_reqwidth() + 44), minimum_height)

    def get_plan(self):
        return BatchPlan(self.kind.get(), tuple(ItemPlan(row["source"], tuple(mode for mode in MODES if mode in row["modes"]))
                                               for row in self.drafts[self.kind.get()]), self.concurrency.get()).validate()

    def submit(self):
        try:
            plan = self.get_plan()
            if self.on_submit(plan, self) is not False:
                self._submitted = True
                self.close()
        except (ValueError, OSError) as error:
            self.notice.configure(text=str(error))
