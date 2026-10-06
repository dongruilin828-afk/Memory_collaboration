"""GUI task history persistence tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from gui.app import AIMemoryGUI

from gui.history_store import HistoryStore, HistoryStoreError
from gui.settings_store import AppSettings


class HistoryStoreTests(unittest.TestCase):
    def test_records_round_trip_with_unicode_and_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = AppSettings(Path(temp))
            store = HistoryStore(settings.history_file)
            records = [{
                "title": "课程总结.md",
                "timestamp": "2026-10-06 14:30:00",
                "succeeded": True,
                "total_seconds": 12.5,
                "saved_files": [Path("课程总结.md")],
            }]

            store.save(records)

            self.assertEqual(
                store.load(),
                [{
                    "title": "课程总结.md",
                    "timestamp": "2026-10-06 14:30:00",
                    "succeeded": True,
                    "total_seconds": 12.5,
                    "saved_files": ["课程总结.md"],
                }],
            )
            self.assertEqual(settings.history_file.parent, Path(temp))

    def test_gui_add_record_persists_before_refresh(self):
        app = object.__new__(AIMemoryGUI)
        app.root = None
        app.history_records = []
        app.history_store = Mock()
        app._refresh_history_list = Mock()
        record = {"title": "新任务"}

        app._add_history_record(record)

        self.assertEqual(app.history_records, [record])
        app.history_store.save.assert_called_once_with([record])
        app._refresh_history_list.assert_called_once_with()

    def test_missing_file_loads_as_empty_history(self):
        with tempfile.TemporaryDirectory() as temp:
            store = HistoryStore(Path(temp) / "task_history.json")
            self.assertEqual(store.load(), [])

    def test_invalid_file_raises_safe_error(self):
        with tempfile.TemporaryDirectory() as temp:
            history_file = Path(temp) / "task_history.json"
            history_file.write_text("not-json", encoding="utf-8")

            with self.assertRaisesRegex(HistoryStoreError, "无法读取"):
                HistoryStore(history_file).load()

    def test_save_replaces_previous_document(self):
        with tempfile.TemporaryDirectory() as temp:
            history_file = Path(temp) / "task_history.json"
            store = HistoryStore(history_file)
            store.save([{"title": "旧记录"}])
            store.save([{"title": "新记录"}])

            payload = json.loads(history_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(payload["records"], [{"title": "新记录"}])
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
