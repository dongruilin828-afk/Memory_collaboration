"""Editable batch plans; one browser queue and a separate bounded summary queue."""
from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlparse
import uuid

from gui.batch_capture import capture_links, validate_capture_links, _write_json
from gui.service import generate_output_bundle
from gui.theme import DIRECT_SUMMARY_FILE_TYPES, DIRECT_SUMMARY_MAX_BYTES

MODES = ("raw", "normal", "simple", "detailed")
MODE_LABELS = {"raw": "抓取", "normal": "总结", "simple": "极简", "detailed": "细节"}
TERMINAL = {"completed", "failed", "cancelled"}


def load_input_messages(path):
    path = Path(path).resolve()
    if path.suffix.lower() not in DIRECT_SUMMARY_FILE_TYPES:
        raise ValueError("仅支持 UTF-8 编码的 Markdown 或文本文件（.md/.txt）。")
    if not path.is_file():
        raise ValueError("所选文件不存在或已被移动。")
    if not 0 < path.stat().st_size <= DIRECT_SUMMARY_MAX_BYTES:
        raise ValueError("所选文件为空或超过 10 MiB 限制。")
    from scripts.gemini_summarizer import load_exported_markdown, GeminiSummaryError
    try:
        try:
            return load_exported_markdown(path)
        except GeminiSummaryError:
            text = path.read_text(encoding="utf-8-sig")
            if not text.strip():
                raise ValueError("所选文件没有可总结的正文。")
            return [{"role": "User", "content": text}]
    except UnicodeDecodeError as error:
        raise ValueError("所选文件不是有效的 UTF-8 文本。") from error


@dataclass(frozen=True)
class ItemPlan:
    source: str
    modes: tuple[str, ...]


@dataclass(frozen=True)
class BatchPlan:
    kind: str
    items: tuple[ItemPlan, ...]
    concurrency: int | None = None
    api_providers: tuple[str, ...] | None = None

    def validate(self):
        if self.kind not in {"links", "files"}:
            raise ValueError("请选择对话链接或已有文件。")
        cap = 3 if self.kind == "links" else 10
        if self.concurrency is not None and (type(self.concurrency) is not int or not 1 <= self.concurrency <= cap):
            raise ValueError(f"并发数量须为自动或 1～{cap}。")
        if self.api_providers is not None and (not self.api_providers or any(not isinstance(value, str) or not value for value in self.api_providers)):
            raise ValueError("请至少选择一个允许使用的 API。")
        if not self.items:
            raise ValueError("请至少添加一项。")
        sources = (validate_capture_links([item.source for item in self.items])
                   if self.kind == "links" else [str(Path(item.source).resolve()) for item in self.items])
        normalized = []
        for index, (source, item) in enumerate(zip(sources, self.items), 1):
            if not item.modes or any(mode not in MODES for mode in item.modes):
                raise ValueError(f"第 {index} 项请至少选择一种生成模式。")
            if self.kind == "files":
                path = Path(source)
                if "raw" in item.modes:
                    raise ValueError("已有文件不支持抓取模式。")
                if path.suffix.lower() not in DIRECT_SUMMARY_FILE_TYPES or not path.is_file():
                    raise ValueError(f"第 {index} 项须为存在的 .md 或 .txt 文件。")
                if not 0 < path.stat().st_size <= DIRECT_SUMMARY_MAX_BYTES:
                    raise ValueError(f"第 {index} 项为空或超过 10 MiB 限制。")
            normalized.append(ItemPlan(source, tuple(mode for mode in MODES if mode in item.modes)))
        return BatchPlan(self.kind, tuple(normalized), self.concurrency,
                         tuple(dict.fromkeys(self.api_providers)) if self.api_providers is not None else None)


@dataclass
class _Batch:
    id: str
    plan: BatchPlan
    output_dir: Path
    runtime_dir: Path
    api_keys: dict = field(repr=False)
    custom_api: dict = field(repr=False)
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    started: bool = False
    editing: bool = False
    capture_started: bool = False
    capture_done: bool = False
    capture_active: bool = False
    summaries: int = 0
    items: list = field(default_factory=list)
    reported: set = field(default_factory=set, repr=False)


class BatchProcessingQueue:
    """All state is protected by a condition; callbacks must marshal to the UI."""
    def __init__(self, *, browser_lock=None, on_change=lambda _: None,
                 on_item_done=lambda *_: None, authorize_login=None, select_topics=None):
        self.browser_lock = browser_lock or threading.Lock()
        self.on_change, self.on_item_done = on_change, on_item_done
        self.authorize_login, self.select_topics = authorize_login, select_topics
        self.condition = threading.Condition(threading.RLock())
        self.batches = []
        self.closed = False
        self.threads = []
        self.capture_busy = False
        self._last_progress = 0.0
        self._ordered = False
        self._drain_items = set()

    @staticmethod
    def _api_snapshot(plan, api_keys):
        keys = dict(api_keys or {})
        if plan.api_providers is not None:
            if any(provider not in keys or not keys[provider] for provider in plan.api_providers):
                raise ValueError("所选 API 已不可用，请重新选择。")
            keys = {provider: keys[provider] for provider in plan.api_providers}
        return keys

    @staticmethod
    def _limit(batch):
        if batch.plan.concurrency is not None:
            return batch.plan.concurrency
        return min(len(batch.items), 3 if batch.plan.kind == "links" else min(10, max(1, len(batch.api_keys))))

    def _draining(self):
        return {(batch.id, item["index"]) for batch in self.batches for item in batch.items
                if (batch.id, item["index"]) in self._drain_items and item["status"] not in TERMINAL}

    def _priority(self):
        return next((batch for batch in self.batches if not batch.cancel.is_set() and not batch.editing
                     and (batch.capture_active or any(item["status"] not in TERMINAL for item in batch.items))), None)

    def _can_start(self, batch):
        return (not self.closed and not batch.cancel.is_set() and not batch.editing
                and (not self._ordered or (not self._draining() and self._priority() is batch)))

    def _next_capture(self):
        return next((batch for batch in self.batches if batch.plan.kind == "links"
                     and not batch.capture_done and not batch.capture_active and self._can_start(batch)), None)

    def _claim_capture(self, batch, index):
        with self.condition:
            if not self._can_start(batch):
                return False
            batch.items[index - 1].update(status="capturing", message="正在抓取")
            self.condition.notify_all()
            return True

    @staticmethod
    def _items(plan):
        return [dict(index=i, source=item.source, modes=list(item.modes), status="queued",
                     message="", error=None, warnings=[], saved_files=[], output_dir=None,
                     fetch_seconds=0.0, generation_seconds=0.0, wait_seconds=0.0,
                     capture_wait_seconds=0.0, topic_wait_seconds=0.0,
                     elapsed_seconds=0.0)
                for i, item in enumerate(plan.items, 1)]

    def add(self, plan, *, output_parent, runtime_dir, api_keys=None, custom_api=None):
        plan = plan.validate()
        api_keys = self._api_snapshot(plan, api_keys)
        if any(mode != "raw" for item in plan.items for mode in item.modes) and not api_keys:
            raise ValueError("请先在设置中添加总结 API。")
        batch_id = uuid.uuid4().hex
        output = Path(output_parent).resolve() / f"批量处理_{datetime.now():%Y%m%d_%H%M%S}_{batch_id[:6]}"
        batch = _Batch(batch_id, plan, output, Path(runtime_dir).resolve(),
                       dict(api_keys or {}), copy.deepcopy(custom_api or {}))
        batch.items = self._items(plan)
        with self.condition:
            if self.closed:
                raise ValueError("程序正在关闭，不能添加批次。")
            if not self.has_work:
                self._ordered = False
                self._drain_items.clear()
            self.batches.append(batch)
            if not self.threads:
                for target in (self._capture_worker, *([self._summary_worker] * 10)):
                    thread = threading.Thread(target=target, daemon=True, name="batch-processing")
                    self.threads.append(thread)
                    thread.start()
            self.condition.notify_all()
        self._publish()
        return batch_id

    def _find(self, batch_id):
        return next((batch for batch in self.batches if batch.id == batch_id), None)

    def edit(self, batch_id, plan, *, api_keys=None, custom_api=None):
        plan = plan.validate()
        api_keys = self._api_snapshot(plan, api_keys)
        if any(mode != "raw" for item in plan.items for mode in item.modes) and not api_keys:
            raise ValueError("请先在设置中添加总结 API。")
        with self.condition:
            batch = self._find(batch_id)
            if batch is None or batch.started or batch.cancel.is_set():
                raise ValueError("该批次已经开始或已移除，不能更改。")
            batch.plan, batch.items = plan, self._items(plan)
            batch.api_keys, batch.custom_api = dict(api_keys or {}), copy.deepcopy(custom_api or {})
            self.condition.notify_all()
        self._publish()

    def move(self, batch_id, before_id):
        with self.condition:
            batch, before = self._find(batch_id), self._find(before_id)
            if (batch is None or batch.cancel.is_set() or before is None
                    or self._view(batch)["status"] in TERMINAL or self._view(before)["status"] in TERMINAL):
                return False
            if batch is not before:
                position = self.batches.index(before)
                self.batches.remove(batch)
                self.batches.insert(position, batch)
                self._ordered = True
                self._drain_items = {(current.id, item["index"]) for current in self.batches for item in current.items
                                     if item["status"] in {"capturing", "summarizing"}}
                self.condition.notify_all()
        self._publish()
        return True

    def hold(self, batch_id):
        with self.condition:
            batch = self._find(batch_id)
            if batch is None or batch.started or batch.editing or batch.cancel.is_set():
                return False
            batch.editing = True
        self._publish()
        return True

    def resume(self, batch_id):
        with self.condition:
            batch = self._find(batch_id)
            if batch is not None:
                batch.editing = False
                self.condition.notify_all()
        self._publish()

    def cancel(self, batch_id):
        with self.condition:
            batch = self._find(batch_id)
            if batch is None:
                return
            batch.cancel.set()
            for item in batch.items:
                if item["status"] in {"queued", "ready"}:
                    item.update(status="cancelled", message="已停止")
            self.condition.notify_all()
        self._publish(batch)

    def remove(self, batch_id):
        with self.condition:
            batch = self._find(batch_id)
            if batch is None:
                return
            if batch.started and self._view(batch)["status"] not in TERMINAL:
                raise ValueError("请先停止该批次，等待任务释放资源后再移除。")
            self.batches.remove(batch)
        self._publish()

    def close(self):
        with self.condition:
            self.closed = True
            for batch in self.batches:
                batch.cancel.set()
                for item in batch.items:
                    if item["status"] in {"queued", "ready"}:
                        item.update(status="cancelled", message="已停止")
            self.condition.notify_all()

    @property
    def has_work(self):
        with self.condition:
            return self.capture_busy or any(batch.summaries for batch in self.batches) or any(item["status"] not in TERMINAL
                                             for batch in self.batches for item in batch.items)

    def wait(self, timeout=30):
        deadline = time.monotonic() + timeout
        for thread in self.threads:
            thread.join(max(0, deadline - time.monotonic()))
        return not any(thread.is_alive() for thread in self.threads)

    def snapshot(self):
        with self.condition:
            return [self._view(batch) for batch in self.batches]

    def _view(self, batch):
        statuses = [item["status"] for item in batch.items]
        done = sum(status in TERMINAL for status in statuses)
        finishing = batch.capture_active and done == len(statuses)
        status = ("running" if batch.started else "queued") if done < len(statuses) or finishing else (
            "failed" if "failed" in statuses else "cancelled" if "cancelled" in statuses else "completed")
        if status == "running" and not finishing and self._ordered and self._priority() is not batch and not any(
                item["status"] in {"capturing", "summarizing"} for item in batch.items):
            status = "paused"
        return dict(id=batch.id, kind=batch.plan.kind, concurrency=self._limit(batch),
                    requested_concurrency=batch.plan.concurrency, api_providers=batch.plan.api_providers,
                    pausing=bool(batch.started and status not in TERMINAL and self._ordered
                                 and self._draining() and self._priority() is not batch),
                    output_dir=str(batch.output_dir), started=batch.started, editing=batch.editing, status=status,
                    finishing=finishing,
                    done=done, total=len(statuses), failed=statuses.count("failed"),
                    warnings=sum(bool(item["warnings"]) for item in batch.items),
                    items=copy.deepcopy(batch.items))

    def _publish(self, batch=None, *, progress=False):
        with self.condition:
            if batch is not None and batch.output_dir.is_dir() and not progress:
                try:
                    _write_json(batch.output_dir / "batch_state.json", self._view(batch))
                except OSError:
                    warning = "批次状态未能保存，请检查结果目录权限。"
                    for item in batch.items:
                        if warning not in item["warnings"]:
                            item["warnings"].append(warning)
            now = time.monotonic()
            if progress and now - self._last_progress < .12:
                return
            self._last_progress = now
            self.on_change(self.snapshot())

    def _update(self, batch, item, **values):
        with self.condition:
            item.update(values)
            self.condition.notify_all()
        self._publish(batch, progress=set(values) <= {"message"})

    def _finished(self, batch, item):
        self._publish(batch)
        with self.condition:
            if item["status"] not in TERMINAL or item["index"] in batch.reported:
                return
            batch.reported.add(item["index"])
            view, completed = self._view(batch), copy.deepcopy(item)
        self.on_item_done(view, completed)

    def _capture_worker(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self._next_capture() is not None)
                if self.closed:
                    return
            if not self.browser_lock.acquire(timeout=.1):
                continue
            batch = None
            try:
                with self.condition:
                    batch = self._next_capture()
                    if batch is None or self.closed:
                        continue
                    resuming = batch.capture_started
                    batch.started = batch.capture_started = batch.capture_active = self.capture_busy = True
                self._publish()
                records = asyncio.run(capture_links(
                    [item.source for item in batch.plan.items], batch.output_dir,
                    concurrency=self._limit(batch), browser_profile_root=batch.runtime_dir / ".browser_user_data",
                    resume=resuming, claim_item=lambda index: self._claim_capture(batch, index),
                    cancel_event=batch.cancel,
                    save_raw=["raw" in item.modes for item in batch.plan.items],
                    progress=lambda index, _total, message: self._capture_progress(batch, index, message),
                    on_result=lambda record: self._capture_result(batch, record),
                    authorize_login=(lambda page, url: self.authorize_login(batch.id, page, url, batch.cancel))
                    if self.authorize_login is not None else None,
                ))
                with self.condition:
                    for record in records:
                        item = batch.items[record["index"] - 1]
                        item["warnings"] = list(dict.fromkeys(item["warnings"] + record["warnings"]))
            except asyncio.CancelledError:
                self._capture_failed(batch, "已停止", "cancelled")
            except Exception as error:
                self._capture_failed(batch, self._safe_error(error, batch), "failed")
            finally:
                with self.condition:
                    self.capture_busy = False
                    if batch is not None:
                        batch.capture_active = False
                        batch.capture_done = not any(item["status"] in {"queued", "capturing"} for item in batch.items)
                    self.condition.notify_all()
                self.browser_lock.release()
                if batch is not None:
                    self._publish(batch)

    def _capture_progress(self, batch, index, message):
        if 1 <= index <= len(batch.items):
            item = batch.items[index - 1]
            with self.condition:
                if item["status"] not in {"queued", "capturing"}:
                    return
                if item["status"] == "queued":
                    item["status"] = "capturing"
            self._update(batch, item, message=str(message))

    def _capture_result(self, batch, record):
        item = batch.items[record["index"] - 1]
        status = record["status"]
        if status == "completed" and any(mode != "raw" for mode in item["modes"]):
            status = "cancelled" if batch.cancel.is_set() else "ready"
        self._update(batch, item, status=status, output_dir=record["output_dir"],
                     error=record.get("error"), warnings=list(record["warnings"]),
                     saved_files=list(record["saved_files"]),
                     fetch_seconds=record.get("elapsed_seconds", 0), wait_seconds=record.get("wait_seconds", 0),
                     capture_wait_seconds=record.get("wait_seconds", 0),
                     elapsed_seconds=record.get("elapsed_seconds", 0),
                     message="等待总结" if status == "ready" else "抓取完成" if status == "completed" else record.get("error") or "已停止")
        if status in TERMINAL:
            self._finished(batch, item)

    def _capture_failed(self, batch, message, status):
        if batch is None:
            return
        with self.condition:
            finished = []
            for item in batch.items:
                if item["status"] in {"queued", "capturing"}:
                    item.update(status=status, error=message, message=message)
                    finished.append(item)
            self.condition.notify_all()
        for item in finished:
            self._finished(batch, item)

    def _next_summary(self):
        # An active batch keeps its chosen limit; later batches must not add
        # extra API calls on top of a user's 1/2-worker selection.
        active = next((batch for batch in self.batches if batch.summaries), None)
        for batch in ([active] if active is not None else self.batches):
            if batch.cancel.is_set() or batch.editing or batch.summaries >= self._limit(batch):
                continue
            for item in batch.items:
                if item["status"] == "ready" or (batch.plan.kind == "files" and item["status"] == "queued"):
                    if self._ordered:
                        draining = self._draining()
                        if draining and (batch.id, item["index"]) not in draining:
                            continue
                        if not draining and not self._can_start(batch):
                            continue
                    return batch, item
        return None

    def _summary_worker(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self._next_summary() is not None)
                if self.closed:
                    return
                batch, item = self._next_summary()
                batch.started = True
                batch.summaries += 1
                item.update(status="summarizing", message="正在总结")
            started = time.perf_counter()
            try:
                self._publish()
                saved = self._generate(batch, item)
                self._update(batch, item, status="completed", message="已完成", saved_files=item["saved_files"] + saved)
            except asyncio.CancelledError:
                self._update(batch, item, status="cancelled", message="已停止")
            except Exception as error:
                message = self._safe_error(error, batch)
                self._update(batch, item, status="failed", message=message, error=message)
            finally:
                with self.condition:
                    seconds = time.perf_counter() - started
                    item["generation_seconds"] = max(0, seconds - item["topic_wait_seconds"])
                    item["wait_seconds"] = item["capture_wait_seconds"] + item["topic_wait_seconds"]
                    item["elapsed_seconds"] = item["fetch_seconds"] + seconds
                try:
                    self._finished(batch, item)
                finally:
                    with self.condition:
                        batch.summaries -= 1
                        self.condition.notify_all()

    def _generate(self, batch, item):
        self._check_cancel(batch)
        if batch.plan.kind == "files":
            source = Path(item["source"])
            messages = load_input_messages(source)
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", source.stem).strip(" .")[:60] or "file"
            target = batch.output_dir / f"{item['index']:03d}_{stem}"
            source_dir, source_name, platform = source.parent, source.name, None
        else:
            target = Path(item["output_dir"])
            messages = json.loads((target / "result.json").read_text(encoding="utf-8"))["messages"]
            source_dir, source_name = target, None
            host = urlparse(item["source"]).hostname
            platform = {"chat.deepseek.com": "deepseek", "doubao.com": "doubao", "www.doubao.com": "doubao",
                        "chatgpt.com": "ChatGPT", "chat.openai.com": "ChatGPT"}.get(host)
            if platform == "ChatGPT" and not urlparse(item["source"]).path.startswith(("/c/", "/share/")):
                platform = None
        target.mkdir(parents=True, exist_ok=True)
        self._update(batch, item, output_dir=str(target))
        modes = {mode: mode != "raw" and mode in item["modes"] for mode in MODES}
        def select_topics(result):
            started = time.perf_counter()
            try:
                return self.select_topics(batch.id, item["index"], result, batch.cancel)
            finally:
                with self.condition:
                    item["topic_wait_seconds"] += time.perf_counter() - started
        with (target / "summary.log").open("w", encoding="utf-8") as stream:
            def progress(message):
                self._check_cancel(batch)
                from scripts.gemini_summarizer import GeminiSummaryError, safe_error_message
                message = safe_error_message(GeminiSummaryError(str(message)), tuple(batch.api_keys.values()))
                stream.write(message + "\n")
                stream.flush()
                self._update(batch, item, message=str(message))
            keys = batch.api_keys
            if batch.plan.kind == "files" and keys:
                providers = list(keys)
                offset = (item["index"] - 1) % len(providers)
                keys = {key: keys[key] for key in providers[offset:] + providers[:offset]}
            bundle = generate_output_bundle(
                messages, modes, batch.output_dir, output_filename=target.name + ".md",
                project_dir=batch.runtime_dir, api_keys=keys,
                custom_api=batch.custom_api or None, result_cache_dir=batch.runtime_dir / "summary_results",
                source_platform=platform, source_name=source_name, source_dir=source_dir,
                topic_selector=select_topics
                if self.select_topics and (modes["normal"] or modes["detailed"]) else None,
                progress=progress, cancel_event=batch.cancel, cancel_check=lambda: self._check_cancel(batch),
            )
        self._check_cancel(batch)
        processing = (bundle.summary_result or {}).get("processing", {})
        with self.condition:
            item["warnings"] += processing.get("warnings", [])
        return [str(path.resolve()) for path in bundle.saved_files]

    @staticmethod
    def _check_cancel(batch):
        if batch.cancel.is_set():
            raise asyncio.CancelledError()

    @staticmethod
    def _safe_error(error, batch):
        from scripts.gemini_summarizer import safe_error_message, GeminiSummaryError
        if isinstance(error, FileNotFoundError):
            error = GeminiSummaryError("文件或结果目录不存在，请检查是否被移动。")
        elif isinstance(error, PermissionError):
            error = GeminiSummaryError("无法读取文件或写入结果目录，请检查访问权限。")
        elif isinstance(error, ValueError):
            error = GeminiSummaryError(str(error))
        return safe_error_message(error, tuple(batch.api_keys.values()) if batch else ())
