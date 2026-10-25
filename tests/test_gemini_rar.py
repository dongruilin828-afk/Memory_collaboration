"""Gemini RAR 原文件保存回归；不解压、不执行归档内容。"""
import asyncio
import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bs4 import BeautifulSoup
from gui import service
from scripts.providers import gemini

URL = 'https://gemini.google.com/app/0123456789abcdef'
META = base64.b64encode(b'[["r_attachment", "c_conversation"]]').decode()


def card(label='文献.rar', *, blocked=False, metadata=META):
    aria = '无法查看或下载共享对话中的文件' if blocked else label
    return (f'<user-query><user-query-file-preview><button aria-label="{aria}" '
            f'jslog="BardVeMetadataKey:{metadata}"><div class="filename-label">文献</div>'
            '<div class="extension-label">RAR</div></button></user-query-file-preview>'
            '<div class="query-text">检查文献</div></user-query>')


class GeminiRarTests(unittest.TestCase):
    def test_candidate_keeps_card_identity_and_does_not_enable_shared_card(self):
        candidates = service._extract_gemini_document_card_candidates(card(), URL)
        self.assertEqual([c.filename for c in candidates], ['文献.rar'])
        self.assertEqual(candidates[0].reference, f'gemini-card:{META}:文献.rar')
        self.assertFalse(service._extract_gemini_document_card_candidates(card(blocked=True), URL))
        self.assertFalse(service._extract_gemini_document_card_candidates(card(), 'https://share.gemini.google/demo'))
        self.assertNotIn('.rar', service.DOCUMENT_EXTENSIONS)
        self.assertNotIn('.rar', service.CHATGPT_ATTACHMENT_EXTENSIONS)
        # 通用 URL 提取不得因 Gemini 新类型而改变其他平台原来的过滤行为。
        for url in ('https://chatgpt.com/c/demo', 'https://www.doubao.com/chat/12345678', 'https://chat.deepseek.com/a/chat/demo'):
            self.assertFalse(service._extract_document_candidates('<a href="https://example.com/report.rar">文献.rar</a>', url))

    def test_rar4_and_rar5_saved_byte_for_byte_and_linked_by_metadata(self):
        candidate = service.DocumentCandidate(f'gemini-card:{META}:文献.rar', URL, '文献.rar')
        for signature in (b'Rar!\x1a\x07\x00', b'Rar!\x1a\x07\x01\x00'):
            body = signature + b'test payload'
            with self.subTest(signature=signature), tempfile.TemporaryDirectory() as directory, patch(
                'gui.service._gemini_document_card_download', new=AsyncMock(return_value=(body, {}))
            ):
                mapping = asyncio.run(service._download_document_candidates(SimpleNamespace(), [candidate], Path(directory), './documents'))
                self.assertIn(candidate.reference, mapping)
                self.assertEqual((Path(directory) / '文献.rar').read_bytes(), body)
                messages = gemini.parse_messages(BeautifulSoup(card(), 'html.parser'), mapping)
                self.assertIn(f'[文献.rar]({mapping[candidate.reference]})', messages[0]['content'])
                self.assertNotIn('未提供下载', messages[0]['content'])
                # 分享卡和原会话使用相同 metadata，不能靠全局文件名猜绑定。
                shared = gemini.parse_messages(BeautifulSoup(card(blocked=True), 'html.parser'), mapping)
                self.assertIn(mapping[candidate.reference], shared[0]['content'])

    def test_error_body_empty_body_and_oversize_are_not_saved_as_rar(self):
        candidate = service.DocumentCandidate(f'gemini-card:{META}:文献.rar', URL, '文献.rar')
        for body in (b'<html>login</html>', b'', b'Rar!\x1a\x07\x01\x00' + b'x' * 32):
            with self.subTest(body=body[:12]), tempfile.TemporaryDirectory() as directory, patch(
                'gui.service._gemini_document_card_download', new=AsyncMock(return_value=(body, {}))
            ), patch('gui.service.GUI_DOCUMENT_MAX_BYTES', 24):
                warnings = []
                failures = {}
                mapping = asyncio.run(service._download_document_candidates(
                    SimpleNamespace(), [candidate], Path(directory), './documents',
                    warning_collector=warnings, failure_collector=failures))
                self.assertFalse(mapping)
                self.assertFalse(list(Path(directory).iterdir()))
                self.assertTrue(warnings)
                self.assertIn(candidate, failures)

    def test_cached_error_response_is_also_rejected(self):
        candidate = service.DocumentCandidate(f'gemini-card:{META}:文献.rar', URL, '文献.rar')
        with tempfile.TemporaryDirectory() as directory:
            warnings = []
            mapping = asyncio.run(service._download_document_candidates(
                SimpleNamespace(), [candidate], Path(directory), './documents',
                captured_documents={candidate.reference: (b'<html>error</html>', {})},
                warning_collector=warnings))
            self.assertFalse(mapping)
            self.assertTrue(warnings)


if __name__ == '__main__':
    unittest.main()
