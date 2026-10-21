"""Latest-turn grounding and Doubao document page-count regressions."""
import copy
import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path
from tests.test_gemini_summarizer import FakeGateway

from scripts import gemini_summarizer as summary
from scripts.simple_summarizer import generate_simple_overview, validate_simple_overview
from scripts.summary_grounding import ANSWER_SCHEMA, ground_latest_turn, render_grounded_overview


class LatestTurnTests(unittest.TestCase):
    def test_scoped_progress_caches_do_not_collide(self):
        messages = [{"role": "User", "content": "相同输入"}]
        config = summary.SummaryConfig()
        self.assertNotEqual(summary._summary_fingerprint(messages, config, "ChatGPT"),
                            summary._summary_fingerprint(messages, config, "deepseek"))
        self.assertNotEqual(summary._summary_fingerprint(messages, config, "ChatGPT"),
                            summary._summary_fingerprint(messages, config, "doubao"))

    def test_each_answer_after_last_user_requires_evidence(self):
        gateway = Mock()
        gateway.generate_json.return_value = {"assistant_summary": "已完成回复和文档。", "evidence": [{"message_id": 2, "quote": "已回复"}]}
        with self.assertRaises(ValueError):
            ground_latest_turn([{"role": "User", "content": "请提供文档"}, {"role": "AI", "content": "已回复"},
                               {"role": "AI", "content": "文档已就绪"}], gateway)

    def test_live_pipeline_overrides_stale_overview_and_isolates_cache(self):
        messages = [{"role": "User", "content": "检查申请表"}, {"role": "AI", "content": "总分应为31。"},
                    {"role": "User", "content": "上传新表格"}, {"role": "AI", "content": "新表格数值为空。"}]

        class Gateway(FakeGateway):
            def generate_json(self, prompt, schema, media_assets=None):
                from scripts.chatgpt_history import HISTORY_SCHEMA, REVIEW_SCHEMA
                from tests.test_chatgpt_history import chunk_fixture, approve
                if schema is HISTORY_SCHEMA:
                    return chunk_fixture(messages)
                if schema is REVIEW_SCHEMA:
                    return approve(prompt)
                if schema is ANSWER_SCHEMA:
                    return {"assistant_summary": "指出新表格数值为空。", "evidence": [{"message_id": 4, "quote": "新表格数值为空"}]}
                return super().generate_json(prompt, schema, media_assets)

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            first = summary.summarize_conversation(messages, directory, gateway=Gateway(), source_platform="ChatGPT",
                result_cache_dir=directory/'cache', output_json=directory/'first.json', output_markdown=directory/'first.md', progress=lambda _: None)
            self.assertIn("新表格", first["overall_summary"])
            self.assertNotIn("申请表", first["overall_summary"])
            self.assertEqual(first["current_state"]["current_activity"]["message_ids"], [3])
            self.assertEqual(first["current_state"]["reached_stage"]["message_ids"], [4])
            self.assertIn("数值为空", first["current_state"]["reached_stage"]["content"])
            second = summary.summarize_conversation(messages, directory, gateway=Gateway(), source_platform="ChatGPT",
                result_cache_dir=directory/'cache', output_json=directory/'second.json', output_markdown=directory/'second.md', progress=lambda _: None)
            self.assertTrue(second["processing"]["cache_hit"])
            self.assertEqual(first["overall_summary"], second["overall_summary"])
            renormalized = summary.renormalize_result(copy.deepcopy(first), messages, source_platform="ChatGPT")
            self.assertEqual(first["overall_summary"], renormalized["overall_summary"])
            self.assertEqual(renormalized["current_state"]["reached_stage"]["message_ids"], [4])
            other = summary.summarize_conversation(messages, directory, gateway=Gateway(), source_platform="gemini",
                result_cache_dir=directory/'cache', output_json=directory/'other.json', output_markdown=directory/'other.md', progress=lambda _: None)
            self.assertFalse(other["processing"]["cache_hit"])
            self.assertNotIn("latest_turn_grounding", other)
            from gui.service import generate_output_bundle
            bundle_dir = directory/'bundle'
            bundle = generate_output_bundle(messages, {"normal": True, "detailed": True, "simple": True}, bundle_dir,
                                   config=summary.SummaryConfig(), gateway=Gateway(), source_platform="ChatGPT")
            simple_path = next(path for path in bundle.saved_files if path.name == 'AI_memory_simple.md')
            self.assertEqual(simple_path.parent.parent, bundle_dir)
            simple = simple_path.read_text(encoding='utf-8')
            self.assertIn("新表格", simple)
            self.assertIn("数值为空", simple)

    def test_document_page_count_does_not_become_a_prediction(self):
        projection = {"topics": [{"summary": "该文件为494页系统论课程讲义，涵盖系统建模、系统预测和评价。"}]}
        text = "用户修改论文，AI已提供新文档。"
        self.assertEqual(validate_simple_overview(text, projection, 460, source_platform="豆包"), [])
        self.assertIn("遗漏了数值预测或估算主题的核心数值", validate_simple_overview(text, projection, 460))

    def test_real_forecasts_are_still_required(self):
        for text in ("教材共494页，预测效率提升20%。", "预测将打印494页。", "按用户条件估算，每周约30~50元。"):
            with self.subTest(text=text):
                errors = validate_simple_overview("AI已完成说明。", {"topics": [{"summary": text}]}, 460, source_platform="豆包")
                self.assertIn("遗漏了数值预测或估算主题的核心数值", errors)

    def test_unrelated_document_counts_do_not_leak_across_prediction_clauses(self):
        projection = {"topics": [{"summary": "该课程共12章，文件为494页，涵盖系统预测和评价。"}]}
        self.assertEqual(validate_simple_overview("用户修改论文，AI已提供文档。", projection, 460, source_platform="豆包"), [])

    def test_ai_choice_is_not_inserted_into_user_request(self):
        messages = [{"role": "User", "content": "将3.3节重新生成，不用DHR架构，基于合适内容展示全文。"},
                    {"role": "AI", "content": "采用排队论建立模型，已展示全文。"},
                    {"role": "AI", "content": "已转为可编辑文档。"}]
        gateway = Mock()
        gateway.generate_json.return_value = {
            "assistant_summary": "采用排队论建立模型，展示全文并转为可编辑文档。",
            "evidence": [{"message_id": 2, "quote": "采用排队论建立模型"}, {"message_id": 3, "quote": "已转为可编辑文档"}],
        }
        grounded = ground_latest_turn(messages, gateway)
        text = render_grounded_overview(grounded)
        self.assertNotIn("排队论", grounded["user_text"])
        self.assertIn("排队论", text)
        self.assertIn("上一 AI 回复", text)
        self.assertEqual(grounded["assistant_message_ids"], [2, 3])

    def test_upload_only_latest_turn_does_not_use_previous_topic(self):
        messages = [{"role": "User", "content": "分析奖学金申请表"}, {"role": "AI", "content": "应为31分。"},
                    {"role": "User", "content": "[数据.xlsx](./documents/data.xlsx)\n\n电子表格"},
                    {"role": "AI", "content": "表头存在，具体数值单元格是空的，无法计算。"}]
        gateway = Mock()
        gateway.generate_json.return_value = {"assistant_summary": "指出表格数值单元格为空，无法计算。", "evidence": [{"message_id": 4, "quote": "具体数值单元格是空的"}]}
        grounded = ground_latest_turn(messages, gateway)
        text = render_grounded_overview(grounded)
        self.assertIn("数据.xlsx", text)
        self.assertNotIn("用户要求分析", text)
        self.assertNotIn("奖学金", text)
        self.assertNotIn("./documents", text)
        self.assertIn("为空", text)
        result = {"latest_turn_grounding": grounded, "conversation": {}, "topics": [], "current_state": {}}
        gateway.generate_json.reset_mock()
        simple = generate_simple_overview(result, messages, gateway, source_platform="ChatGPT")
        self.assertIn("数据.xlsx", simple)
        self.assertIn("为空", simple)
        gateway.generate_json.assert_not_called()

    def test_wrong_message_or_fabricated_quote_is_rejected(self):
        messages = [{"role": "User", "content": "新问题"}, {"role": "AI", "content": "真实回答"}]
        for evidence in ([{"message_id": 1, "quote": "新问题"}], [{"message_id": 2, "quote": "编造内容"}]):
            with self.subTest(evidence=evidence):
                gateway = Mock()
                gateway.generate_json.return_value = {"assistant_summary": "给出解释。", "evidence": evidence}
                with self.assertRaises(ValueError):
                    ground_latest_turn(messages, gateway)
                self.assertEqual(gateway.generate_json.call_count, 2)

    def test_user_choice_in_ai_summary_is_rejected(self):
        gateway = Mock()
        gateway.generate_json.return_value = {"assistant_summary": "用户指定排队论，已完成。", "evidence": [{"message_id": 2, "quote": "已完成"}]}
        with self.assertRaises(ValueError):
            ground_latest_turn([{"role": "User", "content": "换合适方案"}, {"role": "AI", "content": "已完成"}], gateway)

    def test_unanswered_user_does_not_create_ai_result(self):
        gateway = Mock()
        grounded = ground_latest_turn([{"role": "User", "content": "请检查结果"}], gateway)
        self.assertIn("尚无后续 AI 回答", render_grounded_overview(grounded))
        gateway.generate_json.assert_not_called()

    def test_other_platform_simple_path_is_unchanged(self):
        gateway = Mock()
        gateway.generate_json.return_value = {"overview": "AI已完成说明。"}
        result = {"latest_turn_grounding": {"user_text": "不应采用", "assistant_summary": "不应采用"}, "topics": []}
        for platform in (None, "gemini", "deepseek", "kimi", "grok", "qwen", "codex"):
            with self.subTest(platform=platform):
                self.assertEqual(generate_simple_overview(copy.deepcopy(result), [], gateway, source_platform=platform), "AI已完成说明。")


if __name__ == "__main__":
    unittest.main()
