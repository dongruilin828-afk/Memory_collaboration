import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gui.run_logging import GenerationRunLog
from gui.service import generate_output_bundle, gui_summary_config_candidates
from scripts import gemini_summarizer as summary


class GenerationRunLogTests(unittest.TestCase):
    def test_jsonl_log_flushes_events_timings_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            run_log = GenerationRunLog(
                Path(temp),
                {"modes": ["normal"], "api_key": "secret-value"},
            )
            path = run_log.path
            self.assertIsNotNone(path)
            run_log.event(
                "generation_completed",
                "完成",
                stage_timings={"chunk_extraction": 1.25},
            )
            lines_before_close = path.read_text(encoding="utf-8").splitlines()
            run_log.close()

        records = [json.loads(line) for line in lines_before_close]
        self.assertEqual(records[0]["event"], "run_started")
        self.assertEqual(records[1]["event"], "generation_completed")
        self.assertIn("elapsed_seconds", records[1])
        self.assertEqual(
            records[1]["details"]["stage_timings"]["chunk_extraction"],
            1.25,
        )
        self.assertNotIn("secret-value", "\n".join(lines_before_close))

    def test_gui_timeout_does_not_repeat_across_fallback_models(self):
        base_config = summary.SummaryConfig(
            provider="gemini",
            model="gemini-3.5-flash",
            request_timeout_seconds=180,
        )
        candidates = gui_summary_config_candidates(base_config)
        self.assertTrue(all(
            item.request_timeout_seconds == 120 for item in candidates
        ))
        created_models = []

        def fake_create_gateway(config):
            created_models.append(config.model)
            return object()

        def fake_summarize(**_kwargs):
            raise summary.SummaryRequestTimeoutError("模拟请求超时")

        with tempfile.TemporaryDirectory() as temp, patch(
            "scripts.gemini_summarizer.SummaryConfig.from_env",
            return_value=base_config,
        ), patch(
            "scripts.gemini_summarizer.create_gateway",
            side_effect=fake_create_gateway,
        ), patch(
            "scripts.gemini_summarizer.summarize_conversation",
            side_effect=fake_summarize,
        ):
            with self.assertRaises(summary.SummaryRequestTimeoutError):
                generate_output_bundle(
                    messages=[
                        {"role": "User", "content": "测试"},
                        {"role": "AI", "content": "回答"},
                    ],
                    modes={"normal": True},
                    save_dir=Path(temp),
                )

        self.assertEqual(created_models, ["gemini-3.5-flash"])


if __name__ == "__main__":
    unittest.main()
