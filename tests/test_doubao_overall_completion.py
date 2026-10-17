"""豆包总览：删除礼貌性等待状态时不能留下缺少宾语的句子。"""
import copy
import unittest

from scripts import gemini_summarizer as summary


class DoubaoOverallCompletionTests(unittest.TestCase):
    state = {"last_user_turn_answered": True, "breakpoint_status": "complete"}

    def test_remove_whole_waiting_clause_only_for_doubao(self):
        for prefix in ("对话断点在", "当前对话断点停留在", "断点在"):
            for waiting in ("等待用户确认文档", "等待用户后续反馈", "等待新任务"):
                text = f"AI已展示论文全文，{prefix}{waiting}。"
                with self.subTest(prefix=prefix, waiting=waiting):
                    for platform in ("豆包", "doubao"):
                        self.assertEqual(summary._sanitize_overall_completion(
                            text, self.state, source_platform=platform,
                        ), "AI已展示论文全文。")
                    for platform in (None, "gemini", "chatgpt", "deepseek"):
                        self.assertEqual(summary._sanitize_overall_completion(
                            text, self.state, source_platform=platform,
                        ), summary._sanitize_overall_completion(text, self.state))

    def test_preserve_facts_and_genuine_unresolved_state(self):
        for text in (
            "AI已展示论文全文。用户尚未确认该版本是否满足要求。",
            "对话断点在第三章建模修改，AI已提供新文档。",
        ):
            self.assertEqual(summary._sanitize_overall_completion(
                text, self.state, source_platform="豆包",
            ), text)
        text = "对话断点在等待用户确认参数，之后才能生成文档。"
        self.assertEqual(summary._sanitize_overall_completion(
            text, {"last_user_turn_answered": False, "breakpoint_status": "waiting_user"},
            source_platform="豆包",
        ), text)

    def test_fresh_normalization_and_renormalization_share_scoped_fix(self):
        messages = [
            {"role": "User", "content": "请展示论文全文"},
            {"role": "AI", "content": "已展示论文全文并提供文档。"},
        ]
        raw = {"overall_summary": "AI已展示论文全文，对话断点在等待用户确认文档。",
               "current_state": copy.deepcopy(self.state), "topics": []}
        normalized = summary._normalize_final_summary(
            copy.deepcopy(raw), [], messages, [], source_platform="豆包",
        )
        self.assertEqual(normalized["overall_summary"], "AI已展示论文全文。")
        result = {**raw, "conversation": {"message_count": 2}, "memory_items": [],
                  "typed_records": {}, "media": []}
        normalized = summary.renormalize_result(
            copy.deepcopy(result), messages, source_platform="豆包",
        )
        self.assertEqual(normalized["overall_summary"], "AI已展示论文全文。")
        self.assertTrue(summary.renormalize_result(
            copy.deepcopy(result), messages,
        )["overall_summary"].endswith("对话断点在。"))


if __name__ == "__main__":
    unittest.main()
