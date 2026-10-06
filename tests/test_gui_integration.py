"""Offline checks for the merged frontend-to-backend task contract."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui.app import AIMemoryGUI
from gui.history_store import HistoryStore
from gui.service import FetchResult, build_output_paths
from gui.settings_store import AppSettings
from scripts.gemini_summarizer import write_summary_outputs


class MergedGenerationTests(unittest.TestCase):
    def test_platforms_and_modes_keep_assets_topics_warnings_and_history(self):
        urls = (
            "https://chatgpt.com/share/example",
            "https://chat.deepseek.com/share/example",
            "https://www.doubao.com/thread/example",
            "https://share.gemini.google/example",
            "https://www.kimi.com/share/example",
            "https://www.qianwen.com/share/example",
            "https://grok.com/share/example",
            "https://chatgpt.com/codex/tasks/example",
        )
        mode_sets = [
            {mode: True} for mode in ("raw", "normal", "simple", "detailed")
        ] + [{mode: True for mode in ("raw", "normal", "simple", "detailed")}]
        for url in urls:
            for modes in mode_sets:
                with self.subTest(url=url, modes=modes), tempfile.TemporaryDirectory() as temp:
                    self._check_task(Path(temp), url, modes)

    def _check_task(self, directory, url, modes):
        settings = AppSettings(directory / "runtime")
        save_dir = directory / "chosen output"
        paths = build_output_paths(save_dir, modes, "中文 result.md")
        app = object.__new__(AIMemoryGUI)
        app.root = SimpleNamespace(after=lambda _delay, callback: callback())
        app.progress_bar = Mock()
        app.status_var = Mock()
        app.percent_var = Mock()
        app.history_store = HistoryStore(settings.history_file)
        app.history_records = []
        app._refresh_history_list = Mock()
        app._show_completed_badge = Mock()
        app._on_task_finished = Mock()
        app._confirm_login_required = Mock(return_value=True)
        app._show_login_dialog = Mock()
        app._show_summary_topic_dialog = Mock(
            side_effect=lambda topics, on_done: on_done((topics[0]["topic_id"],))
        )
        messages = [
            {"role": "User", "content": "请总结对话"},
            {"role": "AI", "content": "![图片](./asset/image.png) [附件](./asset/document.pdf)"},
        ]
        result = {
            "conversation": {"message_count": 2, "chunk_count": 1},
            "model": "offline-model", "source": url,
            "overall_summary": messages[1]["content"],
            "typed_records": {},
            "topics": [{
                "topic_id": "topic_1", "title": "重点主题", "summary": "主题摘要",
                "memory_ids": [], "source_message_ids": [1, 2],
            }],
        }
        warning = "部分附件不可下载，正文已保留文件名。"

        async def fetch(**kwargs):
            self.assertEqual(kwargs["url"], url)
            self.assertIs(kwargs["login_confirmation_callback"], app._confirm_login_required)
            self.assertIsNotNone(kwargs["login_required_callback"])
            self.assertIsNotNone(kwargs["login_ready_event"])
            owner = paths["asset_markdown"].stem
            self.assertEqual(kwargs["image_output_dir"].name, owner + "_images")
            self.assertEqual(kwargs["document_output_dir"].name, owner + "_files")
            self.assertEqual(kwargs["image_reference_base"], save_dir)
            self.assertEqual(kwargs["document_reference_base"], save_dir)
            return FetchResult(
                html="", image_map={}, messages=messages, warnings=[warning]
            )

        def summarize(**kwargs):
            self.assertEqual(kwargs["messages"], messages)
            self.assertEqual(kwargs["source_dir"], save_dir.resolve())
            self.assertEqual(kwargs["result_cache_dir"], settings.summary_cache_dir.resolve())
            selected = ()
            if modes.get("normal") or modes.get("detailed"):
                selected = kwargs["topic_selector"](result)
                self.assertEqual(selected, ("topic_1",))
            else:
                self.assertIsNone(kwargs["topic_selector"])
            write_summary_outputs(
                result, kwargs["output_json"], kwargs["output_markdown"],
                include_details=kwargs["include_details"], selected_topics=selected,
            )
            return result

        with (
            patch("gui.app.fetch_chat_pipeline", side_effect=fetch),
            patch("scripts.gemini_summarizer.create_gateway", return_value=object()),
            patch("scripts.gemini_summarizer.summarize_conversation", side_effect=summarize) as summary,
            patch("scripts.simple_summarizer.generate_simple_overview", return_value="极简总览"),
            patch("gui.app.messagebox.showwarning") as showwarning,
            patch("gui.app.messagebox.showerror") as showerror,
        ):
            app._run_generation_task(
                url, False, modes, save_dir, "中文 result.md",
                {"gemini": "offline-placeholder"}, settings,
            )

        showerror.assert_not_called()
        showwarning.assert_called_once()
        self.assertIn(warning, showwarning.call_args.args[1])
        self.assertEqual(summary.call_count, 0 if modes == {"raw": True} else 1)
        self.assertEqual(
            app._show_summary_topic_dialog.call_count,
            int(bool(modes.get("normal") or modes.get("detailed"))),
        )
        expected = []
        for mode in ("raw", "normal", "detailed", "simple"):
            if modes.get(mode):
                expected.append(paths[mode + "_markdown"])
                if mode in ("normal", "detailed"):
                    expected.append(paths[mode + "_json"])
        records = app.history_store.load()
        self.assertEqual(records[0]["saved_files"], [str(path.resolve()) for path in expected])
        self.assertEqual(records[0]["output_dir"], str(save_dir.resolve()))
        self.assertEqual(records[0]["file_count"], len(expected))
        self.assertTrue(all(path.is_file() for path in expected))
        for mode in ("raw", "normal", "detailed"):
            if modes.get(mode):
                self.assertIn(
                    messages[1]["content"],
                    paths[mode + "_markdown"].read_text(encoding="utf-8"),
                )
        app._on_task_finished.assert_called_once()


if __name__ == "__main__":
    unittest.main()
