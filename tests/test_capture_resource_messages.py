"""Shared attachment presentation and missing-image warning regressions."""

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from gui.service import _clean_attachment_display


class CaptureResourceMessageTests(unittest.TestCase):
    def test_attachment_names_are_not_repeated_after_links_for_any_provider(self):
        for platform in ("ChatGPT", "DeepSeek", "豆包", "Gemini", "Kimi", "千问", "Grok", "Codex"):
            with self.subTest(platform=platform):
                messages = [{"role": "User", "content":
                    "[📄 a.pdf](./files/a.pdf)\n\n[📄 b #1.docx](./files/b%20%231.docx)\n\na.pdf\nb #1.docx\n\n请比较 a.pdf 和 b #1.docx。"}]
                _clean_attachment_display(messages, [])
                self.assertNotIn("\na.pdf\n", messages[0]["content"])
                self.assertNotIn("\nb #1.docx\n", messages[0]["content"])
                self.assertIn("请比较 a.pdf 和 b #1.docx。", messages[0]["content"])

    def test_code_and_later_filename_mentions_are_preserved(self):
        content = "[📄 report.pdf](./files/report.pdf)\n\n```text\nreport.pdf\n~~~\n```\n\n请解释：\nreport.pdf"
        messages = [{"role": "User", "content": content}]
        _clean_attachment_display(messages, [])
        self.assertEqual(messages[0]["content"], content)

    def test_missing_image_markers_feed_existing_gui_warning_list(self):
        messages = [{"role": "AI", "content":
            "🖼️ **[图片]**（网页中的原图片已失效或未能加载）\n\n"
            "🖼️ **[用户上传图片]**（DeepSeek 分享页原图已失效或加载失败）"}]
        warnings = []
        _clean_attachment_display(messages, warnings)
        _clean_attachment_display(messages, warnings)
        self.assertEqual(len(warnings), 1)
        self.assertIn("2 张图片", warnings[0])

    def test_only_doubao_retries_invalid_long_json_with_smaller_chunks(self):
        from gui.service import generate_output_bundle
        from scripts.gemini_summarizer import (
            GeminiSummaryError, SummaryConfig, _summary_cache_path,
            _summary_fingerprint, _save_summary_cache,
        )
        messages = [{"role": "User", "content": "内容" * 15000}]
        config = SummaryConfig(provider="deepseek", model="deepseek-v4-pro")
        media = [{"media_id": "M001", "reference": "./image.png", "status": "described"}]
        for platform in ("doubao", "豆包", "deepseek", "Gemini", "kimi", "qwen", "grok", "codex", None):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                calls = []

                def summarize(**kwargs):
                    calls.append(kwargs["config"].chunk_chars)
                    path = _summary_cache_path(kwargs["output_json"])
                    if len(calls) == 1:
                        _save_summary_cache(path, {
                            "fingerprint": _summary_fingerprint(messages, config, platform),
                            "media": media, "chunks": {"1": {"old": True}},
                        })
                        raise GeminiSummaryError("API 连续两次调用失败（JSONDecodeError）")
                    cached = json.loads(path.read_text(encoding="utf-8"))
                    self.assertEqual(kwargs["config"].thinking_level, "minimal")
                    self.assertEqual(cached["media"], media)
                    self.assertEqual(cached["chunks"], {})
                    self.assertEqual(cached["fingerprint"], _summary_fingerprint(messages, kwargs["config"], platform))
                    kwargs["output_json"].write_text("{}", encoding="utf-8")
                    kwargs["output_markdown"].write_text("summary", encoding="utf-8")
                    return {"typed_records": {}}

                with patch("scripts.gemini_summarizer.summarize_conversation", side_effect=summarize):
                    if platform in {"doubao", "豆包"}:
                        generate_output_bundle(messages, {"normal": True}, Path(directory), config=config, gateway=object(), source_platform=platform, progress=lambda _: None)
                        self.assertEqual(calls, [24000, 12000])
                    else:
                        with self.assertRaises(GeminiSummaryError):
                            generate_output_bundle(messages, {"normal": True}, Path(directory), config=config, gateway=object(), source_platform=platform, progress=lambda _: None)
                        self.assertEqual(calls, [24000])


if __name__ == "__main__":
    unittest.main()
