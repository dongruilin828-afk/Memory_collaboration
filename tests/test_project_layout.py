import unittest
from pathlib import Path

from scripts.gemini_summarizer import default_summary_paths
from scripts.project_paths import (
    EXPORT_DIR,
    EXPORT_RIGHT_DIR,
    PROJECT_ROOT,
    RESULTS_ROOT,
    SCRIPTS_DIR,
    SUMMARY_DETAILED_DIR,
    SUMMARY_DIR,
    SUMMARY_SIMPLE_DIR,
    TESTS_DIR,
    TESTS_FILE,
)
from tests.run_tests import read_tests


class ProjectLayoutTests(unittest.TestCase):
    def test_central_paths_match_the_reorganized_layout(self):
        expected_root = Path(__file__).resolve().parent.parent
        self.assertEqual(PROJECT_ROOT, expected_root)
        self.assertEqual(SCRIPTS_DIR, expected_root / "scripts")
        self.assertEqual(TESTS_DIR, expected_root / "tests")
        self.assertEqual(TESTS_FILE, TESTS_DIR / "tests.txt")
        self.assertEqual(RESULTS_ROOT, expected_root / "results")
        self.assertEqual(EXPORT_DIR, RESULTS_ROOT / "export")
        self.assertEqual(EXPORT_RIGHT_DIR, RESULTS_ROOT / "export_right")
        self.assertEqual(SUMMARY_DIR, RESULTS_ROOT / "summary")
        self.assertEqual(
            SUMMARY_DETAILED_DIR, RESULTS_ROOT / "summary_detailed"
        )
        self.assertEqual(SUMMARY_SIMPLE_DIR, RESULTS_ROOT / "summary_simple")

    def test_batch_runner_reads_the_moved_tests_file(self):
        tasks = read_tests()
        self.assertTrue(tasks)
        self.assertTrue(all(link.startswith("https://") for _title, link in tasks))

    def test_default_summary_paths_stay_under_results(self):
        normal_json, normal_markdown = default_summary_paths(
            PROJECT_ROOT, "示例.md"
        )
        detailed_json, detailed_markdown = default_summary_paths(
            PROJECT_ROOT, "示例.md", include_details=True
        )
        self.assertEqual(normal_json.parent, SUMMARY_DIR)
        self.assertEqual(normal_markdown.parent, SUMMARY_DIR)
        self.assertEqual(detailed_json.parent, SUMMARY_DETAILED_DIR)
        self.assertEqual(detailed_markdown.parent, SUMMARY_DETAILED_DIR)


if __name__ == "__main__":
    unittest.main()
