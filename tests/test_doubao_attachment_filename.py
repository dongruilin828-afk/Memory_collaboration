"""Doubao attachment names must not be inferred from Python module imports."""

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bs4 import BeautifulSoup

from scripts.providers import doubao
from gui.service import (
    DocumentCandidate, _download_document_candidates,
    _doubao_document_groups, _inject_doubao_document_names,
    _doubao_unavailable_attachment_names, _clean_attachment_display,
)


class DoubaoAttachmentFilenameTests(unittest.TestCase):
    def test_python_module_is_not_an_uploaded_pdf(self):
        html = (
            '<div class="message-item justify-end" data-doubao-role="user">'
            '<div>from reportlab.pdfbase import pdfmetrics</div>'
            '</div>'
        )
        messages = doubao.parse_messages(BeautifulSoup(html, "html.parser"), {})
        self.assertEqual(len(messages), 1)
        self.assertIn("from reportlab.pdfbase", messages[0]["content"])
        self.assertNotIn("📎", messages[0]["content"])

    def test_real_pdf_card_is_preserved(self):
        html = (
            '<div class="message-item justify-end" data-doubao-role="user">'
            '<div class="attachment">report.pdf</div>'
            '</div>'
        )
        messages = doubao.parse_messages(BeautifulSoup(html, "html.parser"), {})
        self.assertIn("`report.pdf`", messages[0]["content"])

    def test_pdf_output_filename_in_code_is_not_an_uploaded_attachment(self):
        html = '<div class="message-item justify-end"><pre>pdf_filename = "智检未来_商业计划书.pdf"\ndoc = SimpleDocTemplate(pdf_filename)</pre></div>'
        message = doubao.parse_messages(BeautifulSoup(html, "html.parser"), {})[0]
        self.assertIn('pdf_filename = "智检未来_商业计划书.pdf"', message["content"])
        self.assertNotIn("上传文档", message["content"])

    def test_attachment_only_block_and_following_question_are_one_user_turn(self):
        html = '''<div class="message-item justify-end"><div class="attachment">report.pdf</div></div>
        <div class="message-item justify-end"><p>请分析这份文件。</p></div>
        <div class="message-item"><div class="group/thinking-title">已完成思考</div><p>答复</p><pre>已完成思考</pre></div>'''
        messages = doubao.parse_messages(BeautifulSoup(html, "html.parser"), {"report.pdf": "./documents/report.pdf"})
        self.assertEqual([m["role"] for m in messages], ["User", "AI"])
        self.assertEqual(messages[0]["content"].count("report.pdf"), 2)  # link label and URL
        self.assertIn("请分析这份文件。", messages[0]["content"])
        self.assertEqual(messages[1]["content"].count("已完成思考"), 1)

    def test_two_text_questions_are_not_merged(self):
        html = '<div class="message-item justify-end">问题一</div><div class="message-item justify-end">问题二</div>'
        self.assertEqual(len(doubao.parse_messages(BeautifulSoup(html, "html.parser"), {})), 2)

    def test_displayed_generated_image_versions_are_consistent(self):
        thumb1 = "https://example.com/rc_gen_image/one.jpeg~tplv-x-downsize_watermark_1.png"
        full1 = "https://example.com/rc_gen_image/one.jpeg~tplv-x-image_pre_watermark_1.png"
        thumb2 = "https://example.com/rc_gen_image/two.jpeg~tplv-x-downsize_watermark_1.png"
        self.assertEqual(doubao.prefer_original_generated_images(
            [full1, thumb1, thumb2], preferred_sources=[thumb1, thumb2]
        ), [thumb1, thumb2])
        self.assertEqual(doubao.prefer_original_generated_images([full1, thumb1, thumb2]), [full1, thumb2])

    def test_hidden_fifth_file_is_bound_to_its_original_message(self):
        payload = '''{"message_id":"101","file":{"name":"第五份文件.pdf","uri":"tos-cn-i-test/fifth.pdf"}}'''
        html = '<div class="message-item justify-end"><div data-message-id="101">前四个附件</div></div><div class="message-item justify-end"><div data-message-id="102">提问</div></div>'
        result = BeautifulSoup(_inject_doubao_document_names(html, _doubao_document_groups(payload)), "html.parser")
        self.assertIn("第五份文件.pdf", result.find(attrs={"data-message-id": "101"}).get_text())
        self.assertNotIn("第五份文件.pdf", result.find(attrs={"data-message-id": "102"}).get_text())

    def test_visible_filename_without_file_css_still_becomes_a_download_link(self):
        payload = '''{"message_id":"101","file":{"name":"工作交接极简版.md","uri":"tos-cn-i-test/note.md"}}'''
        html = '<div class="message-item justify-end"><div data-message-id="101"><span>工作交接极简版.md</span></div></div>'
        injected = _inject_doubao_document_names(html, _doubao_document_groups(payload))
        message = doubao.parse_messages(BeautifulSoup(injected, "html.parser"), {"工作交接极简版.md": "./documents/note.md"})[0]
        self.assertIn("[📄 工作交接极简版.md](./documents/note.md)", message["content"])
        self.assertNotIn("\n工作交接极简版.md", message["content"])

    def test_ai_netdisk_file_keeps_source_link_and_is_not_a_user_upload(self):
        href = "https://pan.baidu.com/s/example"
        payload = '{"message_id":"102","user_type":2,"content":"点击下载：[生成报告.pdf](' + href + ')"}'
        html = '<div class="message-item"><div data-message-id="102"><div data-testid="attachment_file_item"><span data-testid="message_nested_content_file_name">生成报告.pdf</span></div></div></div>'
        self.assertEqual(_doubao_unavailable_attachment_names(html, {}), [])
        injected = _inject_doubao_document_names(html, _doubao_document_groups(payload))
        messages = doubao.parse_messages(BeautifulSoup(injected, "html.parser"), {})
        warnings = []
        _clean_attachment_display(messages, warnings)
        self.assertIn(href, messages[0]["content"])
        self.assertIn("外部网盘文件未下载", messages[0]["content"])
        self.assertNotIn("上传文档", messages[0]["content"])
        self.assertEqual(len(warnings), 1)


class DoubaoFreshCredentialTests(unittest.IsolatedAsyncioTestCase):
    async def test_cdn_candidates_refresh_credentials_before_reading_stale_url(self):
        candidate = DocumentCandidate("tos-cn-i-test/report.pdf", "https://p6-flow-sign.byteimg.com/tos-cn-i-test/report.pdf?expired=1", "report.pdf")
        response = SimpleNamespace(ok=True, headers={"content-type": "application/pdf"}, body=AsyncMock(return_value=b"%PDF-1.7 real file"))
        page = SimpleNamespace(url="https://www.doubao.com/chat/123", request=SimpleNamespace(get=AsyncMock()))
        with tempfile.TemporaryDirectory() as directory, patch(
            "gui.service._doubao_document_api_get", new=AsyncMock(return_value=response)
        ) as refresh:
            mapping = await _download_document_candidates(page, [candidate], Path(directory), "./documents")
            self.assertIn("report.pdf", mapping)
            self.assertTrue((Path(directory) / "report.pdf").is_file())
            self.assertEqual(refresh.await_args.args[1].url, "https://www.doubao.com/alice/message/get_file_url")
            page.request.get.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
