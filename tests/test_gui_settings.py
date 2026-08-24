"""GUI 数据位置设置与目录路由测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gui.app import _prompt_output_target
from gui.settings_store import (
    DEFAULT_RESULTS_VALUE,
    RUNTIME_DATA_VALUE,
    AppSettings,
    SettingsStoreError,
    WindowsAppSettingsStore,
    default_app_settings,
    normalize_directory,
)


class MemorySettingsStore(WindowsAppSettingsStore):
    def __init__(self, values=None):
        self.values = dict(values or {})

    def _read_values(self):
        return dict(self.values)

    def _write_values(self, values):
        self.values = dict(values)


class GUISettingsStoreTests(unittest.TestCase):
    def test_empty_store_uses_existing_runtime_default_and_no_result_default(self):
        settings = MemorySettingsStore().load()
        self.assertEqual(settings, default_app_settings())
        self.assertIsNone(settings.default_results_dir)

    def test_paths_round_trip_and_are_created(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            runtime = base / "runtime"
            results = base / "results"
            store = MemorySettingsStore()
            saved = store.save(AppSettings(runtime, results))

            self.assertTrue(runtime.is_dir())
            self.assertTrue(results.is_dir())
            self.assertEqual(saved.runtime_data_dir, runtime.resolve())
            self.assertEqual(saved.default_results_dir, results.resolve())
            self.assertEqual(store.load(), saved)
            self.assertEqual(store.values[RUNTIME_DATA_VALUE], str(runtime.resolve()))
            self.assertEqual(store.values[DEFAULT_RESULTS_VALUE], str(results.resolve()))
            self.assertFalse(any(runtime.glob(".ai-memory-write-test-*")))
            self.assertFalse(any(results.glob(".ai-memory-write-test-*")))

            self.assertEqual(saved.browser_profile_dir, runtime / ".browser_user_data")
            self.assertEqual(saved.log_dir, runtime / "log")
            self.assertEqual(saved.summary_cache_dir, runtime / "summary_results")
            self.assertEqual(
                saved.debug_html_file,
                runtime / "debug_last_fetch.html",
            )

    def test_clearing_result_default_keeps_runtime_location(self):
        with tempfile.TemporaryDirectory() as temp:
            store = MemorySettingsStore()
            saved = store.save(AppSettings(Path(temp), None))
            self.assertEqual(saved.runtime_data_dir, Path(temp).resolve())
            self.assertIsNone(saved.default_results_dir)
            self.assertEqual(store.values[DEFAULT_RESULTS_VALUE], "")

    def test_relative_paths_are_rejected(self):
        self.assertIsNone(normalize_directory("relative/path"))
        with self.assertRaisesRegex(SettingsStoreError, "绝对路径"):
            MemorySettingsStore().save(AppSettings(Path("relative/path")))

    def test_configured_result_directory_only_prompts_for_name(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "gui.app.simpledialog.askstring",
            return_value="课程总结.txt",
        ) as name_dialog, patch(
            "gui.app.filedialog.asksaveasfilename",
        ) as file_dialog:
            settings = AppSettings(Path(temp) / "runtime", Path(temp) / "results")
            target = _prompt_output_target(
                None,
                {"normal": True, "raw": False},
                settings,
            )

        self.assertEqual(
            target,
            ((Path(temp) / "results").resolve(), "课程总结.md"),
        )
        name_dialog.assert_called_once()
        file_dialog.assert_not_called()

    def test_unset_result_directory_keeps_combined_location_dialog(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "gui.app.filedialog.asksaveasfilename",
            return_value=str(Path(temp) / "手动位置" / "报告.md"),
        ) as file_dialog, patch(
            "gui.app.simpledialog.askstring",
        ) as name_dialog:
            settings = AppSettings(Path(temp) / "runtime", None)
            target = _prompt_output_target(
                None,
                {"normal": True, "raw": False},
                settings,
            )

        self.assertEqual(
            target,
            ((Path(temp) / "手动位置").resolve(), "报告.md"),
        )
        file_dialog.assert_called_once()
        name_dialog.assert_not_called()

    def test_name_prompt_cancel_stops_generation_target_selection(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "gui.app.simpledialog.askstring",
            return_value="",
        ):
            settings = AppSettings(Path(temp), Path(temp))
            self.assertIsNone(_prompt_output_target(None, {"raw": True}, settings))


if __name__ == "__main__":
    unittest.main()
