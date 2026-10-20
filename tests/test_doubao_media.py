import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfWriter

from scripts import gemini_summarizer as summary
from scripts.doubao_media import MediaGateway, pdf_images, prepare_pdf, _annotate_watermarks
from scripts.providers import doubao
from tests.test_gemini_summarizer import FakeGateway


class DoubaoMediaTests(unittest.TestCase):
    def test_similar_images_are_supplied_one_at_a_time_with_their_own_ids(self):
        images = [summary.MediaAsset(f"M{i:03}", i, "image", "相似截图", f"{i}.png") for i in (1, 2)]
        vision = Mock()
        def identify(prompt, schema, media_assets=None):
            self.assertEqual(len(media_assets), 1)
            asset = media_assets[0]
            self.assertIn(f"本次只核对附件{asset.media_id}", prompt)
            return {"items": [{"media_id": asset.media_id, "description": "独立内容" + asset.media_id,
                               "status": "described", "visible_watermarks": []}]}
        vision.generate_json.side_effect = identify
        result = MediaGateway(Mock(), vision, summary.SummaryConfig(provider="deepseek")).generate_json(
            "核对截图", summary.MEDIA_SCHEMA, images)
        self.assertEqual(vision.generate_json.call_count, 2)
        self.assertEqual([item['description'] for item in result['items']], ['独立内容M001', '独立内容M002'])

    def test_origin_and_absence_metadata_are_not_visible_labels(self):
        for raw, expected in [
            (["AI生成的文本内容，无可见水印或品牌标识"], []),
            (["AI生成的文本内容", "未见明显水印"], []),
            (["豆包AI生成", "无可见水印或品牌标识"], ["豆包AI生成"]),
            (["AI生成", "‘AI生成的文本内容’"], ["AI生成", "‘AI生成的文本内容’"]),
        ]:
            with self.subTest(raw=raw):
                item = {"description": "面向对象编程概念图", "visible_watermarks": raw}
                _annotate_watermarks(item)
                self.assertEqual(item["visible_watermarks"], expected)
                self.assertEqual("【可见标注：" in item["description"], bool(expected))

    def test_all_video_views_survive_parent_compression(self):
        views = [summary.MediaAsset("old", 1, "image", f"时间{i}秒", f"frame{i}.png") for i in range(3)]
        vision = Mock()
        vision.generate_json.side_effect = lambda prompt, schema, media_assets=None: {"items": [
            {"media_id": a.media_id, "description": "独立画面" + a.label, "status": "described", "visible_watermarks": []}
            for a in media_assets or []]}
        text = Mock()
        text.generate_json.return_value = {"items": [{"media_id": "M001", "description": "只描述开场", "status": "described"}]}
        asset = summary.MediaAsset("M001", 1, "video", "视频", "v.mp4", mime_type="video/mp4")
        with patch("scripts.doubao_media.video_images", return_value=views):
            result = MediaGateway(text, vision, summary.SummaryConfig(provider="deepseek", media_batch_size=2)).generate_json('父附件 M001; "extracted_document_text": "对照说明"', summary.MEDIA_SCHEMA, [asset])
        item = result["items"][0]
        self.assertEqual(item["status"], "described")
        for index in range(3):
            self.assertIn(f"独立画面时间{index}秒", item["description"])
        self.assertNotIn("只描述开场", item["description"])
        self.assertEqual(vision.generate_json.call_count, 2)
        text.generate_json.assert_called_once()

    def test_missing_video_view_is_not_promoted_to_success(self):
        views = [summary.MediaAsset("old", 1, "image", f"时间{i}秒", f"frame{i}.png") for i in range(2)]
        vision = Mock()
        vision.generate_json.side_effect = lambda prompt, schema, media_assets=None: {"items": [
            {"media_id": a.media_id, "description": "开场", "status": "described", "visible_watermarks": []}
            for a in media_assets or [] if a.media_id.endswith("001")]}
        text = Mock()
        text.generate_json.return_value = {"items": [{"media_id": "M001", "description": "正常", "status": "described"}]}
        asset = summary.MediaAsset("M001", 1, "video", "视频", "v.mp4", mime_type="video/mp4")
        with patch("scripts.doubao_media.video_images", return_value=views):
            result = MediaGateway(text, vision, summary.SummaryConfig(provider="deepseek", media_batch_size=2)).generate_json("父附件 M001", summary.MEDIA_SCHEMA, [asset])
        self.assertEqual(result["items"][0]["status"], "unclear")
        self.assertIn("未有效识别", result["items"][0]["description"])

    def test_scanned_pages_are_individual_and_empty_page_is_retained(self):
        views = [summary.MediaAsset("old", 1, "image", f"第{i}页", f"page{i}.png") for i in range(1, 4)]
        vision = Mock()
        def identify(prompt, schema, media_assets=None):
            self.assertEqual(len(media_assets), 1)
            self.assertNotIn("visible_watermarks", schema["properties"]["items"]["items"]["required"])
            a = media_assets[0]
            return {"items": [{"media_id": a.media_id, "description": "深色空页，无可见文字" if a.label == "第3页" else a.label + "独立内容", "status": "described", "visible_watermarks": ["附件文件名.pdf"]}]}
        vision.generate_json.side_effect = identify
        text = Mock()
        text.generate_json.return_value = {"items": [{"media_id": "M001", "description": "首页", "status": "described"}]}
        asset = summary.MediaAsset("M001", 1, "document", "扫描件", "s.pdf", mime_type="application/pdf")
        with patch("scripts.doubao_media.pdf_images", return_value=views):
            result = MediaGateway(text, vision, summary.SummaryConfig(provider="deepseek")).generate_json("父附件 M001", summary.MEDIA_SCHEMA, [asset])
        self.assertEqual(vision.generate_json.call_count, 3)
        self.assertEqual(result["items"][0]["status"], "described")
        self.assertIn("第2页独立内容", result["items"][0]["description"])
        self.assertIn("深色空页", result["items"][0]["description"])
        self.assertNotIn("【可见标注", result["items"][0]["description"])

    def test_text_documents_do_not_request_or_publish_watermark_fields(self):
        text, vision = Mock(), Mock()
        text.generate_json.return_value = {"items": [{"media_id": "M001", "description": "论文正文", "status": "described", "visible_watermarks": ["a.pdf"]}]}
        result = MediaGateway(text, vision, summary.SummaryConfig(provider="deepseek")).generate_json("文档正文", summary.MEDIA_SCHEMA, [])
        self.assertIs(text.generate_json.call_args.args[1], summary.MEDIA_SCHEMA)
        vision.generate_json.assert_not_called()
        self.assertNotIn("visible_watermarks", result["items"][0])
        self.assertEqual(result["items"][0]["description"], "论文正文")

    def test_mixed_image_and_text_document_only_annotates_image(self):
        text, vision = Mock(), Mock()
        vision.generate_json.return_value = {"items": [
            {"media_id": "M001", "description": "图片", "status": "described", "visible_watermarks": ["AI生成"]},
            {"media_id": "M002", "description": "文档正文", "status": "described", "visible_watermarks": ["a.pdf"]},
        ]}
        image = summary.MediaAsset("M001", 1, "image", "图片", "x.png", mime_type="image/png")
        result = MediaGateway(text, vision, summary.SummaryConfig(provider="deepseek")).generate_json("图片和已提取文档", summary.MEDIA_SCHEMA, [image])
        by_id = {item["media_id"]: item for item in result["items"]}
        self.assertIn("【可见标注：AI生成】", by_id["M001"]["description"])
        self.assertEqual(by_id["M002"]["description"], "文档正文")
        self.assertNotIn("visible_watermarks", by_id["M002"])

    def test_scanned_pdf_renders_every_page_instead_of_empty_document(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path = directory / "scan.pdf"
            writer = PdfWriter()
            for _ in range(3):
                writer.add_blank_page(width=200, height=200)
            writer.write(path)
            asset = summary.MediaAsset("M001", 1, "document", "scan.pdf", "scan.pdf", local_path=path)
            prepare_pdf(asset, summary.SummaryConfig())
            self.assertEqual(asset.status, "ready")
            self.assertEqual(asset.extracted_text, "")
            parts = pdf_images(asset, directory)
            self.assertEqual(len(parts), 3)
            self.assertTrue(all(p.local_path.read_bytes().startswith(b"\x89PNG") for p in parts))
            self.assertIn("3/3页", parts[-1].label)

    def test_pdf_unicode_replacement_is_explicit_and_encoded_safely(self):
        textpage = Mock()
        textpage.get_text_bounded.return_value = "主题与数学符号" * 10 + "\ud800"
        page = Mock()
        page.get_textpage.return_value = textpage
        document = Mock()
        document.__len__ = Mock(return_value=1)
        document.__getitem__ = Mock(return_value=page)
        context = Mock()
        context.__enter__ = Mock(return_value=document)
        context.__exit__ = Mock(return_value=False)
        asset = summary.MediaAsset("M001", 1, "document", "a.pdf", "a.pdf", local_path=Path("a.pdf"))
        with patch("pypdfium2.PdfDocument", return_value=context):
            prepare_pdf(asset, summary.SummaryConfig())
        self.assertIn("\ufffd", asset.extracted_text)
        asset.extracted_text.encode("utf-8")
        textpage.get_text_bounded.assert_called_once_with(errors="replace")

    def test_visual_requests_use_vision_backend_and_include_ids_and_watermarks(self):
        text = Mock()
        vision = Mock()
        vision.generate_json.return_value = {"items": [{"media_id": "M019", "description": "天鹅照片，图中未见水印或AI生成痕迹。", "status": "described", "visible_watermarks": ["AI生成"]}]}
        asset = summary.MediaAsset("M019", 6, "image", "生成图", "x.png", mime_type="image/png")
        result = MediaGateway(text, vision, summary.SummaryConfig(provider="deepseek")).generate_json("重新识别", summary.MEDIA_SCHEMA, [asset])
        text.generate_json.assert_not_called()
        self.assertIn('"media_id": "M019"', vision.generate_json.call_args.args[0])
        self.assertIn("AI生成", result["items"][0]["description"])
        self.assertNotIn("未见水印", result["items"][0]["description"])
        self.assertIn("visible_watermarks", vision.generate_json.call_args.args[1]["properties"]["items"]["items"]["required"])
        self.assertNotIn("visible_watermarks", summary.MEDIA_SCHEMA["properties"]["items"]["items"]["required"])

    def test_only_doubao_discovers_local_video(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "clip.mp4").write_bytes(b"video")
            messages = [{"role": "AI", "content": "[视频](./clip.mp4)"}]
            for platform in ("doubao", "豆包", "gemini", "deepseek", "kimi", None):
                assets = summary.discover_media(messages, directory, directory, summary.SummaryConfig(), platform)
                self.assertEqual([a.kind for a in assets], ["video"] if platform in {"doubao", "豆包"} else [])

    def test_unclear_cached_media_and_dependent_chunks_are_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in ("one.png", "two.png"):
                Image.new("RGB", (8, 8), "white").save(directory / name)
            messages = [{"role": "User", "content": "![一](./one.png) ![二](./two.png) 请去水印"}]
            config = summary.SummaryConfig(provider="deepseek")
            output = directory / "result.json"
            cache = summary._summary_cache_path(output)
            summary._save_summary_cache(cache, {"fingerprint": summary._summary_fingerprint(messages, config, "doubao"), "media": [
                {"media_id": "M001", "reference": "./one.png", "status": "described", "description": "有效旧说明"},
                {"media_id": "M002", "reference": "./two.png", "status": "unclear", "description": "未识别"},
            ], "chunks": {"1": {"title": "不应复用旧分块"}}})
            vision = Mock()
            vision.generate_json.return_value = {"items": [{"media_id": "M002", "description": "第二张图可读", "status": "described", "visible_watermarks": []}]}
            gateway = FakeGateway()
            # This test owns media/cache invalidation; final semantic review has
            # separate source-bound tests in test_doubao_full_revision.
            with patch('scripts.doubao_summary.review_summary'), patch('scripts.gemini_summarizer.enrich_messages',
                    side_effect=AssertionError('独立附件说明不可插入豆包原话')):
                result = summary.summarize_conversation(messages, directory, config=config, gateway=gateway,
                             media_gateway=vision, source_platform="doubao", output_json=output,
                             output_markdown=directory / "summary.md", progress=lambda _: None)
            self.assertEqual([a["status"] for a in result["media"]], ["described", "described"])
            self.assertEqual(vision.generate_json.call_count, 1)
            self.assertTrue(any(schema is summary.CHUNK_SCHEMA and "图片实际效果" in prompt for schema, prompt in gateway.prompts))

    def test_doubao_ui_nodes_are_removed_but_prose_and_real_images_remain(self):
        html = '''<div class="message-item"><div data-message-id="12">
        <div data-testid="doc_card"><img src="doc-icon.png"/><img src="doc-preview.png"/></div>
        <div class="video-header-x"><img src="video-icon.png"/></div>
        <div data-assembly-preview-card data-office-artifact-status="2"><span><img src="private-icon.png"/></span><img data-assembly-doc-image src="private-preview.png"/></div>
        <div data-plugin-identifier="search_query_result_block"><div data-copy-ignore>搜索10个关键词</div><p>正文讨论搜索策略。</p></div>
        <img src="https://example.org/real.png"/></div></div>'''
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(doubao.decorative_image_sources(soup), {"doc-icon.png", "doc-preview.png", "video-icon.png", "private-icon.png", "private-preview.png"})
        messages = doubao.parse_messages(soup, {})
        content = messages[0]["content"]
        self.assertNotIn("doc-icon", content)
        self.assertNotIn("video-icon", content)
        self.assertNotIn("private-preview", content)
        self.assertNotIn("搜索10个关键词", content)
        self.assertIn("正文讨论搜索策略", content)
        self.assertIn("real.png", content)


if __name__ == "__main__":
    unittest.main()
