"""集中定义项目目录，避免入口移动后产生路径漂移。"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
TESTS_DIR = PROJECT_ROOT / "tests"
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
