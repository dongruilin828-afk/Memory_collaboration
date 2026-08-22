"""GUI 单次生成任务的即时结构化日志。"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


_SECRET_PATTERN = re.compile(
    r"(?:AIza[A-Za-z0-9_-]{20,}|Bearer\s+[^\s,;]+|"
    r"(?:api[_-]?key|authorization)\s*[:=]\s*[^\s,;]+)",
    re.IGNORECASE,
)


def _safe_value(value: Any, key: str = "") -> Any:
    lowered_key = key.lower()
    if any(marker in lowered_key for marker in ("api_key", "token", "authorization")):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(k): _safe_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return _SECRET_PATTERN.sub("<redacted>", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


class GenerationRunLog:
    """逐行写入并立即刷新；日志失败绝不影响生成主流程。"""

    def __init__(self, log_dir: Path, metadata: Mapping[str, Any]):
        self.started = time.perf_counter()
        self.path: Path | None = None
        self._handle = None
        self._lock = threading.Lock()
        try:
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            self.path = log_dir / f"gui_run_{stamp}_{os.getpid()}.jsonl"
            self._handle = self.path.open("a", encoding="utf-8", buffering=1)
        except OSError:
            self.path = None
            self._handle = None
        self.event("run_started", metadata=dict(metadata))

    def event(self, event: str, message: str = "", **details: Any) -> None:
        if self._handle is None:
            return
        record: dict[str, Any] = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "elapsed_seconds": round(time.perf_counter() - self.started, 3),
            "event": str(event),
        }
        if message:
            record["message"] = _safe_value(message)
        if details:
            record["details"] = _safe_value(details)
        try:
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            with self._lock:
                self._handle.write(line + "\n")
                self._handle.flush()
        except (OSError, ValueError):
            self.close()

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.close()
        except OSError:
            pass
