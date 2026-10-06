"""GUI task history persistence."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Iterable, Mapping


HISTORY_SCHEMA_VERSION = 1


class HistoryStoreError(RuntimeError):
    """Raised when task history cannot be loaded or saved."""


class HistoryStore:
    """Persist GUI task history as a small versioned JSON document."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> list[dict]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise HistoryStoreError("无法读取历史记录文件。") from error

        if not isinstance(payload, dict):
            raise HistoryStoreError("历史记录文件格式无效。")
        records = payload.get("records")
        if not isinstance(records, list):
            raise HistoryStoreError("历史记录文件格式无效。")
        return [dict(record) for record in records if isinstance(record, dict)]

    def save(self, records: Iterable[Mapping]) -> None:
        payload = {
            "version": HISTORY_SCHEMA_VERSION,
            "records": [dict(record) for record in records],
        }
        temporary_path = self.path.with_name(
            f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(temporary_path, self.path)
        except (OSError, TypeError, ValueError) as error:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise HistoryStoreError("无法保存历史记录文件。") from error
