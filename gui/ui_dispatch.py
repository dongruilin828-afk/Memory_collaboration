"""后台线程只写队列；所有 Tk 调用均由界面线程执行。"""

from __future__ import annotations

import queue
import threading
import tkinter as tk


def bind_visible_modal(dialog):
    """隐藏的 transient 窗口不能继续持有输入抓取。"""
    def mapped(event):
        if event.widget is dialog and dialog.winfo_viewable():
            dialog.grab_set()

    def unmapped(event):
        if event.widget is dialog and dialog.grab_current() is dialog:
            dialog.grab_release()

    dialog.bind("<Map>", mapped, add="+")
    dialog.bind("<Unmap>", unmapped, add="+")


class UIDispatcher:
    def __init__(self, root, interval_ms=40):
        self.root = root
        self.interval_ms = interval_ms
        self.closed = threading.Event()
        self._queue = queue.SimpleQueue()
        self._deferred = []
        self._after_id = root.after(interval_ms, self._drain)
        root.bind("<Destroy>", self._on_destroy, add="+")

    def post(self, callback, *, visible=False):
        # 此方法运行在工作线程，不能调用 after/winfo 等任何 Tk API。
        if not self.closed.is_set():
            self._queue.put((callback, visible))

    def _drain(self):
        self._after_id = None
        if self.closed.is_set():
            return
        pending, self._deferred = self._deferred, []
        for _ in range(64):
            try:
                pending.append(self._queue.get_nowait())
            except queue.Empty:
                break
        try:
            for callback, visible in pending:
                if self.closed.is_set():
                    break
                if visible and (
                    self.root.state() in {"iconic", "withdrawn"}
                    or not self.root.winfo_viewable()
                ):
                    # 最小化期间不建立持有 grab 的隐藏模态窗口。
                    self._deferred.append((callback, visible))
                    continue
                try:
                    callback()
                except Exception as error:
                    self.root.report_callback_exception(
                        type(error), error, error.__traceback__,
                    )
        finally:
            if not self.closed.is_set():
                self._after_id = self.root.after(self.interval_ms, self._drain)

    def _on_destroy(self, event):
        if event.widget is self.root:
            self.close()

    def close(self):
        self.closed.set()
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self._deferred.clear()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def wait(self, event):
        """供后台等待用户选择；窗口销毁后不留下永久等待的线程。"""
        while not event.wait(0.2):
            if self.closed.is_set():
                raise RuntimeError("界面已关闭，无法继续等待用户操作。")
