import unittest

import simple_summarizer as simple


class FakeGateway:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate_json(self, _prompt, schema, media_assets=None):
        self.calls += 1
        self.asserted_schema = schema
        return self.responses.pop(0)


class SimpleSummarizerTests(unittest.TestCase):
    def test_projection_keeps_corrections_but_not_all_learning_records(self):
        learning = [
            {
                "record_kind": "translation", "topic": f"词汇 {index}",
                "user_original": f"word {index}",
                "assistant_revision": f"释义 {index}"
            }
            for index in range(20)
        ]
        learning.append({
            "record_kind": "correction", "topic": "form → from",
            "user_original": "form", "assistant_revision": "from"
        })
        result = {
            "overall_summary": "英语学习。",
            "conversation": {},
            "current_state": {},
            "topics": [],
            "memory_items": [],
            "typed_records": {"learning": learning},
            "media": []
        }
        projection = simple.build_simple_projection(result, [
            {"role": "User", "content": "form"},
            {"role": "AI", "content": "应为 from"}
        ])
        typed = projection["typed_records"]
        self.assertEqual(typed["learning_count"], 21)
        self.assertEqual(len(typed["corrections"]), 1)
        self.assertLessEqual(len(typed["representative_learning"]), 8)

    def test_validation_rejects_lists_and_unsupported_numbers(self):
        projection = {"known": "原文只有 50"}
        errors = simple.validate_simple_overview(
            "- 结果是 99。", projection, 100
        )
        self.assertTrue(any("列表" in error for error in errors))
        self.assertTrue(any("99" in error for error in errors))

    def test_generation_retries_after_overlong_output(self):
        gateway = FakeGateway([
            {"overview": "甲" * 300},
            {"overview": "用户提出问题，上一 AI 已回答。"}
        ])
        result = {
            "overall_summary": "用户提出问题。",
            "conversation": {},
            "current_state": {},
            "topics": [],
            "memory_items": [],
            "typed_records": {},
            "media": []
        }
        overview = simple.generate_simple_overview(
            result,
            [
                {"role": "User", "content": "问题"},
                {"role": "AI", "content": "回答"}
            ],
            gateway
        )
        self.assertEqual(gateway.calls, 2)
        self.assertEqual(overview, "用户提出问题，上一 AI 已回答。")

    def test_markdown_contains_only_overview_section(self):
        result = {
            "provider": "gemini", "model": "gemini-test",
            "source": "sample.md",
            "conversation": {
                "message_count": 8, "chunk_count": 1,
                "conversation_types": ["programming", "media_analysis"]
            }
        }
        metadata = simple.build_simple_metadata(result)
        rendered = simple.render_simple_markdown("已经完成。", metadata)
        self.assertIn("- 后端：gemini", rendered)
        self.assertIn("- 模型：gemini-test", rendered)
        self.assertIn("- 来源：sample.md", rendered)
        self.assertIn("- 消息数：8", rendered)
        self.assertIn("- 分块数：1", rendered)
        self.assertIn("- 对话类型：编程任务、媒体分析", rendered)
        self.assertTrue(rendered.endswith("# 总览\n\n已经完成。\n"))
        self.assertEqual(rendered.count("#"), 1)

        overview, saved = simple.parse_simple_markdown(rendered)
        self.assertEqual(overview, "已经完成。")
        self.assertEqual(saved, {
            "provider": "gemini", "model": "gemini-test"
        })

    def test_non_programming_assistant_suggestion_is_not_pending(self):
        result = {
            "overall_summary": "AI 已提供缓存清理建议。",
            "conversation": {"programming_mode": "none"},
            "current_state": {
                "pending": [{
                    "content": "用户是否执行清理",
                    "source": "assistant", "status": "unresolved"
                }],
                "next_step": {
                    "content": "用户执行清理",
                    "source": "inferred", "status": "suggested"
                }
            },
            "topics": [], "memory_items": [],
            "typed_records": {}, "media": []
        }
        projection = simple.build_simple_projection(result, [
            {"role": "User", "content": "可以删吗"},
            {"role": "AI", "content": "可以，但先退出程序。"}
        ])
        self.assertEqual(projection["current_state"]["pending"], [])
        self.assertEqual(projection["current_state"]["next_step"], {})

    def test_validation_rejects_false_adoption_pending(self):
        projection = {"current_state": {"pending": []}}
        errors = simple.validate_simple_overview(
            "AI 已纠正拼写，用户尚未确认是否采纳。", projection, 100
        )
        self.assertTrue(any("采纳待办" in error for error in errors))

    def test_normalization_removes_courtesy_waiting_tail(self):
        normalized = simple.normalize_simple_overview(
            "AI 已完成概念讲解，目前等待用户反馈或继续提问。"
        )
        self.assertEqual(normalized, "AI 已完成概念讲解。")

        normalized = simple.normalize_simple_overview(
            "目前所有问答均已完成，处于就绪状态，可随时接收新指令。"
        )
        self.assertEqual(normalized, "目前所有问答均已完成。")

        normalized = simple.normalize_simple_overview(
            "目前所有需求均已回答，处于就绪等待新要求的状态。"
        )
        self.assertEqual(normalized, "目前所有需求均已回答。")

        normalized = simple.normalize_simple_overview(
            "AI 已完成解答，当前无未决任务，可直接继续 Python 进阶学习。"
        )
        self.assertEqual(normalized, "AI 已完成解答，当前无未决任务。")

    def test_repair_removes_false_pending_and_downgrades_stability(self):
        repaired = simple.repair_simple_overview(
            "AI 预测数月稳定在500MB至1GB。目前建议已输出，"
            "尚待用户实际清理和验证。",
            {
                "current_state": {"pending": []},
                "evidence": "几个月约 500MB 至 1GB"
            }
        )
        self.assertEqual(repaired, "AI 预测几个月后约为500MB至1GB。")

    def test_repair_keeps_real_programming_pending(self):
        repaired = simple.repair_simple_overview(
            "AI 已交付补丁，尚待用户在本地验证。",
            {"current_state": {"pending": [{"content": "本地验证"}]}}
        )
        self.assertIn("尚待用户在本地验证", repaired)

    def test_long_language_overview_rejects_word_enumeration(self):
        projection = {
            "current_state": {"pending": []},
            "typed_records": {"learning_count": 100}
        }
        errors = simple.validate_simple_overview(
            "用户学习了英语词汇，涉及 slow、module、figure、category、hub 等。",
            projection,
            200
        )
        self.assertTrue(any("枚举" in error for error in errors))

        errors = simple.validate_simple_overview(
            "用户最近查询了数字“1”的释义与用法。",
            projection,
            200
        )
        self.assertTrue(any("单个词汇" in error for error in errors))

    def test_long_language_projection_omits_low_value_latest_query(self):
        learning = [
            {"record_kind": "translation", "topic": f"词汇 {index}"}
            for index in range(31)
        ]
        result = {
            "overall_summary": "用户进行了大量英语学习。",
            "conversation": {},
            "current_state": {
                "current_activity": {"content": "查询数字 1 的释义"},
                "last_user_intent": "查询数字 1 的释义"
            },
            "topics": [
                {
                    "title": "谚语学习", "summary": "具体谚语解释",
                    "memory_ids": ["L001"]
                },
                {
                    "title": "用电估算", "summary": "每月约 50 度",
                    "memory_ids": ["C001"]
                }
            ],
            "memory_items": [
                {"memory_id": "L001", "memory_type": "learning_point"},
                {"memory_id": "C001", "memory_type": "calculation"}
            ],
            "typed_records": {"learning": learning}, "media": []
        }
        projection = simple.build_simple_projection(result, [
            {"role": "User", "content": "1"},
            {"role": "AI", "content": "one 的释义"}
        ])
        self.assertEqual(projection["current_state"]["current_activity"], {})
        self.assertIsNone(projection["current_state"]["last_user_intent"])
        self.assertEqual([item["title"] for item in projection["topics"]], ["用电估算"])
        self.assertEqual(projection["typed_records"]["corrections"], [])

    def test_long_language_overview_rejects_individual_learning_topics(self):
        projection = {
            "current_state": {"pending": []},
            "typed_records": {"learning_count": 100}
        }
        errors = simple.validate_simple_overview(
            "用户探讨了英语谚语和计算机术语 bytecode，并涉及部分短语纠错。",
            projection,
            200
        )
        self.assertTrue(any("学习条目" in error for error in errors))

    def test_validation_rejects_false_user_completion(self):
        projection = {
            "current_state": {
                "pending": [],
                "completed": [{
                    "content": "AI 已完成申请文书润色",
                    "source": "assistant", "status": "delivered"
                }]
            },
            "typed_records": {"learning_count": 0},
            "topics": []
        }
        errors = simple.validate_simple_overview(
            "用户已完成多道申请文书润色。", projection, 200
        )
        self.assertTrue(any("交付物" in error for error in errors))

    def test_validation_requires_a_number_for_estimates(self):
        projection = {
            "current_state": {"pending": []},
            "typed_records": {"learning_count": 0},
            "topics": [{
                "summary": "AI 预测几个月约 500MB 至 1GB。"
            }]
        }
        errors = simple.validate_simple_overview(
            "AI 已提供缓存回涨规律预测。", projection, 200
        )
        self.assertTrue(any("核心数值" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
