"""集中定义源码、运行数据与打包资源目录。"""

import os
import sys
from pathlib import Path


IS_FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE_ROOT = Path(
    getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
).resolve()
SOURCE_ROOT = BUNDLE_ROOT if IS_FROZEN else Path(__file__).resolve().parent.parent

if IS_FROZEN:
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA")
        or (Path.home() / "AppData" / "Local")
    )
    PROJECT_ROOT = local_app_data / "AI Memory Summary"
else:
    PROJECT_ROOT = SOURCE_ROOT

BUNDLED_BROWSERS_DIR = BUNDLE_ROOT / "playwright-browsers"
if IS_FROZEN and BUNDLED_BROWSERS_DIR.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BUNDLED_BROWSERS_DIR))

SCRIPTS_DIR = SOURCE_ROOT / "scripts"
TESTS_DIR = SOURCE_ROOT / "tests"
TESTS_FILE = TESTS_DIR / "tests.txt"

RESULTS_ROOT = PROJECT_ROOT / "results"
EXPORT_DIR = RESULTS_ROOT / "export"
EXPORT_RIGHT_DIR = RESULTS_ROOT / "export_right"
SUMMARY_DIR = RESULTS_ROOT / "summary"
SUMMARY_DETAILED_DIR = RESULTS_ROOT / "summary_detailed"
SUMMARY_SIMPLE_DIR = RESULTS_ROOT / "summary_simple"

IMAGES_DIR = PROJECT_ROOT / "images"
BROWSER_USER_DATA_DIR = PROJECT_ROOT / ".browser_user_data"
DEFAULT_EXPORT_FILE = PROJECT_ROOT / "AI_memory_export.md"
DEBUG_HTML_FILE = PROJECT_ROOT / "debug_last_fetch.html"
LOG_DIR = PROJECT_ROOT / "log"
