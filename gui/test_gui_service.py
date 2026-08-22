"""GUI 模块独立单元测试。

验证 GUI 辅助方法、状态机和逻辑约束，不依赖图形显示服务器。
"""

import asyncio
import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from bs4 import BeautifulSoup

from gui.service import (
    _download_image_candidates,
    build_image_asset_directory,
    build_markdown_asset_prefix,
    build_output_paths,
    default_output_filename,
    generate_output_bundle,
    generate_raw_markdown,
    gui_summary_config_candidates,
    normalize_markdown_filename,
    parse_fallback_messages_gui,
)
from scripts.gemini_summarizer import GeminiSummaryError, SummaryConfig


class GUIServiceTests(unittest.TestCase):
    def test_image_downloads_are_bounded_and_keep_success_order(self):
        class FakeResponse:
            def __init__(self, ok, payload):
                self.ok = ok
                self.payload = payload

            async def body(self):
                return self.payload

        class FakeRequest:
            def __init__(self):
                self.active = 0
                self.max_active = 0

            async def get(self, src, timeout):
                self.assert_timeout = timeout
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                try:
                    await asyncio.sleep(0.01)
                    return FakeResponse("fail" not in src, src.encode("utf-8"))
                finally:
                    self.active -= 1

        request = FakeRequest()
        page = SimpleNamespace(request=request)
        candidates = [
            "https://example.com/a.png",
            "https://example.com/fail.png",
            "https://example.com/b.jpg",
            "https://example.com/c.webp",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            image_map = asyncio.run(_download_image_candidates(
                page,
                candidates,
                Path(temp_dir),
                "./assets",
                concurrency=2,
            ))
            files = sorted(Path(temp_dir).iterdir())
            self.assertEqual(len(files), 3)
            self.assertEqual(
                [path.read_bytes() for path in files],
                [
                    b"https://example.com/a.png",
                    b"https://example.com/b.jpg",
                    b"https://example.com/c.webp",
                ],
            )

        self.assertEqual(request.max_active, 2)
        self.assertEqual(list(image_map), [
            "https://example.com/a.png",
            "https://example.com/b.jpg",
            "https://example.com/c.webp",
        ])
        self.assertTrue(image_map[candidates[0]].startswith("./assets/img_1_"))
        self.assertTrue(image_map[candidates[2]].startswith("./assets/img_2_"))
        self.assertTrue(image_map[candidates[3]].startswith("./assets/img_3_"))

    def test_image_asset_directory_sits_beside_markdown_outputs(self):
        base = Path("用户结果")
        asset_dir = build_image_asset_directory(base, "课程 总结.txt")
        self.assertEqual(asset_dir, base / "课程 总结_images")
        self.assertEqual(
            build_markdown_asset_prefix(asset_dir, base),
            "./%E8%AF%BE%E7%A8%8B%20%E6%80%BB%E7%BB%93_images",
        )

    def test_output_filename_defaults_and_md_normalization(self):
        self.assertEqual(
            default_output_filename({"normal": True}),
            "AI_memory_summary.md",
        )
        self.assertEqual(
            default_output_filename({"raw": True, "normal": True}),
            "AI_memory.md",
        )
        self.assertEqual(
            normalize_markdown_filename("我的总结.txt"),
            "我的总结.md",
        )
        self.assertEqual(
            normalize_markdown_filename("我的总结.MD"),
            "我的总结.md",
        )

    def test_custom_output_paths_for_single_and_multiple_modes(self):
        base = Path("output")
        single = build_output_paths(
            base,
            {"normal": True},
            "课程总结.txt",
        )
        self.assertEqual(single["normal_markdown"].name, "课程总结.md")
        self.assertEqual(single["normal_json"].name, "课程总结.json")

        multiple = build_output_paths(
            base,
            {
                "raw": True,
                "normal": True,
                "simple": True,
                "detailed": True,
            },
            "课程总结.md",
        )
        self.assertEqual(
            multiple["raw_markdown"].name,
            "课程总结_export.md",
        )
        self.assertEqual(
            multiple["normal_markdown"].name,
            "课程总结_summary.md",
        )
        self.assertEqual(
            multiple["normal_json"].name,
            "课程总结_result.json",
        )
        self.assertEqual(
            multiple["simple_markdown"].name,
            "课程总结_simple.md",
        )
        self.assertEqual(
            multiple["detailed_markdown"].name,
            "课程总结_detailed_summary.md",
        )
        self.assertEqual(
            multiple["detailed_json"].name,
            "课程总结_detailed_result.json",
        )

    def test_fallback_parser_works_consistently(self):
        html = "<div><p>用户输入问题</p><p>回答</p><p>这是AI的回复内容</p></div>"
        soup = BeautifulSoup(html, "html.parser")
        messages = parse_fallback_messages_gui(soup)
        self.assertTrue(len(messages) >= 1)

    def test_generate_raw_markdown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "output.md"
            messages = [
                {"role": "User", "content": "你好"},
                {"role": "AI", "content": "你好！有什么我可以帮你的？"}
            ]
            generate_raw_markdown(messages, target)
            self.assertTrue(target.is_file())
            content = target.read_text(encoding="utf-8")
            self.assertIn("# AI 对话记忆导出", content)
            self.assertIn("用户提问", content)
            self.assertIn("AI 回答", content)

    def test_normal_and_detailed_reuse_one_result_and_one_selection(self):
        messages = [
            {"role": "User", "content": "请解释这段代码"},
            {"role": "AI", "content": "这是一个示例解释。"},
        ]
        fake_result = {
            "typed_records": {"programming": [{"topic": "示例"}]},
            "topics": [{"title": "主题一", "summary": "摘要"}],
        }
        summarize_calls = []
        detailed_calls = []
        selector_calls = []

        def fake_summarize(**kwargs):
            summarize_calls.append(kwargs)
            selected = kwargs["section_selector"](fake_result)
            self.assertEqual(selected, ("programming",))
            kwargs["output_json"].write_text("{}", encoding="utf-8")
            kwargs["output_markdown"].write_text("normal", encoding="utf-8")
            return fake_result

        def fake_write(
            result, output_json, output_markdown,
            include_details=False, selected_sections=None,
            selected_topics=None
        ):
            detailed_calls.append({
                "result": result,
                "include_details": include_details,
                "selected_sections": tuple(selected_sections or ()),
                "selected_topics": tuple(selected_topics or ()),
            })
            output_json.write_text("{}", encoding="utf-8")
            output_markdown.write_text("detailed", encoding="utf-8")

        def selector(result):
            selector_calls.append(result)
            return ("programming",)

        fake_config = SimpleNamespace(provider="test", model="fake-model")
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "scripts.gemini_summarizer.create_gateway", return_value=object()
        ), patch(
            "scripts.gemini_summarizer.summarize_conversation",
            side_effect=fake_summarize,
        ), patch(
            "scripts.gemini_summarizer.write_summary_outputs",
            side_effect=fake_write,
        ):
            bundle = generate_output_bundle(
                messages,
                {"normal": True, "detailed": True, "simple": False},
                Path(temp_dir),
                section_selector=selector,
                config=fake_config,
            )

        self.assertEqual(len(summarize_calls), 1)
        self.assertEqual(selector_calls, [fake_result])
        self.assertEqual(bundle.selected_sections, ("programming",))
        self.assertEqual(len(detailed_calls), 1)
        self.assertTrue(detailed_calls[0]["include_details"])
        self.assertEqual(
            detailed_calls[0]["selected_sections"], ("programming",)
        )
        self.assertEqual(detailed_calls[0]["selected_topics"], ())
        self.assertEqual(
            [path.name for path in bundle.saved_files],
            [
                "AI_memory_summary.md",
                "AI_memory_result.json",
                "AI_memory_detailed_summary.md",
                "AI_memory_detailed_result.json",
            ],
        )

    def test_detailed_only_writes_no_unrequested_normal_files(self):
        messages = [
            {"role": "User", "content": "计算 1+1"},
            {"role": "AI", "content": "结果是 2。"},
        ]
        captured = {}

        def fake_summarize(**kwargs):
            captured.update(kwargs)
            kwargs["section_selector"]({
                "typed_records": {"calculations": [{"topic": "加法"}]}
            })
            kwargs["output_json"].write_text("{}", encoding="utf-8")
            kwargs["output_markdown"].write_text("detailed", encoding="utf-8")
            return {"typed_records": {}}

        fake_config = SimpleNamespace(provider="test", model="fake-model")
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "scripts.gemini_summarizer.create_gateway", return_value=object()
        ), patch(
            "scripts.gemini_summarizer.summarize_conversation",
            side_effect=fake_summarize,
        ):
            output_dir = Path(temp_dir)
            bundle = generate_output_bundle(
                messages,
                {"normal": False, "detailed": True, "simple": False},
                output_dir,
                section_selector=lambda _result: ("calculations",),
                config=fake_config,
            )
            self.assertFalse((output_dir / "AI_memory_summary.md").exists())
            self.assertFalse((output_dir / "AI_memory_result.json").exists())

        self.assertTrue(captured["include_details"])
        self.assertEqual(captured["source_dir"], output_dir.resolve())
        self.assertEqual(
            captured["source_name"],
            "AI_memory_export.md",
        )
        self.assertEqual(bundle.selected_sections, ("calculations",))
        self.assertEqual(
            [path.name for path in bundle.saved_files],
            ["AI_memory_detailed_summary.md", "AI_memory_detailed_result.json"],
        )

    def test_gui_topic_selection_is_reused_by_normal_and_detailed(self):
        messages = [
            {"role": "User", "content": "先讨论代码，再讨论部署"},
            {"role": "AI", "content": "已分别说明。"},
        ]
        fake_result = {
            "typed_records": {},
            "topics": [
                {
                    "topic_id": "topic_1",
                    "title": "代码实现",
                    "summary": "代码主题摘要",
                    "memory_ids": ["M1"],
                    "source_message_ids": [1, 2],
                },
                {
                    "topic_id": "topic_2",
                    "title": "部署流程",
                    "summary": "部署主题摘要",
                    "memory_ids": ["M2"],
                    "source_message_ids": [1, 2],
                },
            ],
        }
        detailed_calls = []

        def fake_summarize(**kwargs):
            self.assertIsNone(kwargs["section_selector"])
            selected = kwargs["topic_selector"](fake_result)
            self.assertEqual(selected, ("topic_2",))
            kwargs["output_json"].write_text("{}", encoding="utf-8")
            kwargs["output_markdown"].write_text("normal", encoding="utf-8")
            return fake_result

        def fake_write(
            _result, output_json, output_markdown,
            include_details=False, selected_sections=None,
            selected_topics=None
        ):
            detailed_calls.append({
                "include_details": include_details,
                "selected_sections": tuple(selected_sections or ()),
                "selected_topics": tuple(selected_topics or ()),
            })
            output_json.write_text("{}", encoding="utf-8")
            output_markdown.write_text("detailed", encoding="utf-8")

        fake_config = SimpleNamespace(provider="test", model="fake-model")
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "scripts.gemini_summarizer.create_gateway", return_value=object()
        ), patch(
            "scripts.gemini_summarizer.summarize_conversation",
            side_effect=fake_summarize,
        ), patch(
            "scripts.gemini_summarizer.write_summary_outputs",
            side_effect=fake_write,
        ):
            bundle = generate_output_bundle(
                messages,
                {"normal": True, "detailed": True, "simple": False},
                Path(temp_dir),
                topic_selector=lambda _result: ("topic_2",),
                config=fake_config,
            )

        self.assertEqual(bundle.selected_sections, ())
        self.assertEqual(bundle.selected_topics, ("topic_2",))
        self.assertEqual(len(detailed_calls), 1)
        self.assertTrue(detailed_calls[0]["include_details"])
        self.assertEqual(detailed_calls[0]["selected_sections"], ())
        self.assertEqual(detailed_calls[0]["selected_topics"], ("topic_2",))

    def test_gui_model_candidates_stay_within_the_same_provider(self):
        gemini = SummaryConfig(
            provider="gemini",
            model="gemini-3.5-flash",
            retries=3,
            rate_limit_wait_seconds=65,
        )
        gemini_candidates = gui_summary_config_candidates(gemini)
        self.assertEqual(
            [(item.provider, item.model) for item in gemini_candidates],
            [
                ("gemini", "gemini-3.5-flash"),
                ("gemini", "gemini-3.6-flash"),
                ("gemini", "gemini-3.5-flash-lite"),
            ],
        )
        self.assertTrue(all(item.retries == 1 for item in gemini_candidates))

        silicon = SummaryConfig(
            provider="siliconflow",
            model="Qwen/Qwen3.5-397B-A17B",
        )
        silicon_candidates = gui_summary_config_candidates(silicon)
        self.assertEqual(len(silicon_candidates), 1)
        self.assertEqual(silicon_candidates[0].provider, "siliconflow")

    def test_gui_falls_back_to_next_gemini_model_without_reprompting(self):
        messages = [
            {"role": "User", "content": "你好"},
            {"role": "AI", "content": "你好！"},
        ]
        base_config = SummaryConfig(
            provider="gemini",
            model="gemini-3.5-flash",
        )
        attempted_models = []
        selector_calls = []
        fake_result = {"typed_records": {}, "topics": []}

        def fake_summarize(**kwargs):
            model = kwargs["config"].model
            attempted_models.append(model)
            if model == "gemini-3.5-flash":
                raise GeminiSummaryError("模拟额度限制")
            selector_calls.append(kwargs["section_selector"](fake_result))
            kwargs["output_json"].write_text("{}", encoding="utf-8")
            kwargs["output_markdown"].write_text("normal", encoding="utf-8")
            return fake_result

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "scripts.gemini_summarizer.SummaryConfig.from_env",
            return_value=base_config,
        ), patch(
            "scripts.gemini_summarizer.create_gateway",
            side_effect=lambda config: config.model,
        ), patch(
            "scripts.gemini_summarizer.summarize_conversation",
            side_effect=fake_summarize,
        ):
            bundle = generate_output_bundle(
                messages,
                {"normal": True, "detailed": False, "simple": False},
                Path(temp_dir),
                section_selector=lambda _result: (),
            )

        self.assertEqual(
            attempted_models,
            ["gemini-3.5-flash", "gemini-3.6-flash"],
        )
        self.assertEqual(selector_calls, [()])
        self.assertEqual(bundle.summary_result, fake_result)


if __name__ == "__main__":
    unittest.main()
