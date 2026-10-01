"""Gemini 复制会话附件恢复：核对消息身份，保留用户正文和回答。"""
import asyncio
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from bs4 import BeautifulSoup
from gui.service import (
    _extract_gemini_document_card_candidates,
    _recover_gemini_copied_attachments,
    _restore_gemini_copied_file_cards,
    _gemini_document_card_download,
    _download_image_candidates,
    DocumentCandidate,
)

SOURCE_URL = 'https://gemini.google.com/app/source12345678'
COPY_URL = 'https://gemini.google.com/app/copied12345678'

def user(request, conversation, query, filename, video=False, blocked=False):
    metadata = base64.b64encode(f'[["r_{request}","c_{conversation}"]]'.encode()).decode()
    label = '无法查看或下载共享对话中的文件' if blocked else ('以灯箱形式显示上传的视频' if video else filename)
    card = (f'<user-query-file-preview><button aria-label="{label}" jslog="BardVeMetadataKey:{metadata}">'
            + (f'<img src="https://drive-thirdparty.googleusercontent.com/type/video/mp4">' if video else '<img src="https://drive-thirdparty.googleusercontent.com/type/application/pdf">')
            + f'<div class="filename-label">{filename.rsplit(".", 1)[0]}</div></button></user-query-file-preview>')
    return f'<user-query>{card}<div class="query-text"><span class="cdk-visually-hidden">你说 {query}</span><p>{query}</p></div></user-query>'

def fixtures():
    copied = user('document123', 'copied12345678', '阅读这个文件', 'report.pdf', blocked=True)
    copied += '<message-content>copied answer</message-content>'
    copied += user('video123', 'copied12345678', '讲解这个视频', 'clip.mp4', video=True, blocked=True)
    original = user('document123', 'source12345678', '阅读这个文件', 'report.pdf')
    original += '<message-content>original answer</message-content>'
    original += user('video123', 'source12345678', '讲解这个视频', 'clip.mp4', video=True)
    return copied, original

class GeminiCopiedAttachmentTests(unittest.TestCase):
    def test_verified_file_cards_restore_without_changing_answers(self):
        copied, original = fixtures()
        restored = _restore_gemini_copied_file_cards(copied, original, SOURCE_URL)
        self.assertTrue(restored)
        self.assertIn('copied answer', restored)
        self.assertNotIn('original answer', restored)
        before = BeautifulSoup(copied, 'html.parser')
        after = BeautifulSoup(restored, 'html.parser')
        self.assertEqual([str(n) for n in before.select('.query-text')], [str(n) for n in after.select('.query-text')])
        self.assertEqual(len(_extract_gemini_document_card_candidates(restored, SOURCE_URL)), 2)
        self.assertNotIn('无法查看或下载', restored)

    def test_wrong_request_query_filename_type_and_missing_file_rejected(self):
        copied, original = fixtures()
        for wrong in (
            user('other123', 'source12345678', '阅读这个文件', 'report.pdf'),
            original.replace('阅读这个文件', '另一条提问'),
            original.replace('report', 'different'),
            original.replace('以灯箱形式显示上传的视频', '无法查看或下载共享对话中的文件'),
            original.replace('type/video/mp4', 'type/application/pdf').replace('以灯箱形式显示上传的视频', 'file.pdf'),
            original + original,
        ):
            with self.subTest(wrong=wrong[:80]):
                self.assertEqual(_restore_gemini_copied_file_cards(copied, wrong, SOURCE_URL), '')

    def test_search_uses_visible_query_and_verifies_source(self):
        copied, original = fixtures()
        copied = copied.replace("阅读这个文件", "你有能力阅读这个文件吗？请分析")
        original = original.replace("阅读这个文件", "你有能力阅读这个文件吗？请分析")
        click, fill, wait = AsyncMock(), AsyncMock(), AsyncMock()
        selectors = {
            '[data-test-id="search-chats-button"] a': SimpleNamespace(click=click),
            'input[data-test-id="search-input"]': SimpleNamespace(fill=fill),
            '.search-results-header, .no-results': SimpleNamespace(first=SimpleNamespace(wait_for=wait)),
            'search-snippet a[href]': SimpleNamespace(evaluate_all=AsyncMock(return_value=['https://evil.example/app/source12345678', '/app/source12345678'])),
        }
        page = SimpleNamespace(url=SOURCE_URL, locator=MagicMock(side_effect=lambda selector: selectors[selector]))
        with patch('gui.service.goto_with_retry_gui', new=AsyncMock()) as goto, patch(
            'gui.service._page_has_conversation_content', new=AsyncMock(return_value=True)
        ), patch('gui.service.collect_virtualized_html', new=AsyncMock(return_value=original)):
            url, restored = asyncio.run(_recover_gemini_copied_attachments(page, copied, COPY_URL))
        self.assertEqual(url, SOURCE_URL)
        self.assertTrue(restored)
        fill.assert_awaited_once_with('你有能力阅读这个文件吗', timeout=5000)
        goto.assert_awaited_once_with(page, SOURCE_URL, attempts=1, logger=None)

    def test_failed_search_returns_to_requested_conversation(self):
        copied, original = fixtures()
        page = SimpleNamespace(locator=MagicMock(return_value=SimpleNamespace(click=AsyncMock(side_effect=TimeoutError))))
        with patch('gui.service.goto_with_retry_gui', new=AsyncMock()) as goto, patch('gui.service.collect_virtualized_html', new=AsyncMock()):
            self.assertEqual(asyncio.run(_recover_gemini_copied_attachments(page, copied, COPY_URL)), ('', copied))
        self.assertEqual(goto.await_count, 2)
        self.assertTrue(all(call.args == (page, COPY_URL) for call in goto.await_args_list))

    def test_transient_search_failure_retries(self):
        copied, original = fixtures()
        copied = copied.replace('阅读这个文件', '你有能力阅读这个文件吗？请分析')
        original = original.replace('阅读这个文件', '你有能力阅读这个文件吗？请分析')
        fill = AsyncMock()
        selectors = {
            '[data-test-id="search-chats-button"] a': SimpleNamespace(click=AsyncMock(side_effect=[TimeoutError, None])),
            'input[data-test-id="search-input"]': SimpleNamespace(fill=fill),
            '.search-results-header, .no-results': SimpleNamespace(first=SimpleNamespace(wait_for=AsyncMock())),
            'search-snippet a[href]': SimpleNamespace(evaluate_all=AsyncMock(return_value=['/app/source12345678'])),
        }
        page = SimpleNamespace(url=SOURCE_URL, locator=MagicMock(side_effect=lambda selector: selectors[selector]))
        with patch('gui.service.goto_with_retry_gui', new=AsyncMock()) as goto, patch(
            'gui.service._page_has_conversation_content', new=AsyncMock(return_value=True)
        ), patch('gui.service.collect_virtualized_html', new=AsyncMock(return_value=original)):
            url, restored = asyncio.run(_recover_gemini_copied_attachments(page, copied, COPY_URL))
        self.assertEqual(url, SOURCE_URL)
        self.assertTrue(restored)
        self.assertEqual(goto.await_count, 2)
        self.assertEqual(fill.await_args.args[0], '你有能力阅读这个文件吗？请分析')

    def test_failed_search_and_navigation_keep_read_content(self):
        copied, original = fixtures()
        page = SimpleNamespace(locator=MagicMock(return_value=SimpleNamespace(click=AsyncMock(side_effect=TimeoutError))))
        with patch('gui.service.goto_with_retry_gui', new=AsyncMock(side_effect=TimeoutError)), patch('gui.service.collect_virtualized_html', new=AsyncMock()):
            self.assertEqual(asyncio.run(_recover_gemini_copied_attachments(page, copied, COPY_URL)), ('', copied))

    def test_unblocked_conversation_does_not_search(self):
        copied, original = fixtures()
        page = SimpleNamespace(locator=MagicMock())
        self.assertEqual(asyncio.run(_recover_gemini_copied_attachments(page, original, SOURCE_URL)), ('', original))
        page.locator.assert_not_called()

    def test_download_returns_to_candidate_conversation(self):
        missing = SimpleNamespace(count=AsyncMock(return_value=0))
        card = SimpleNamespace(locator=MagicMock(return_value=SimpleNamespace(first=missing)))
        cards = SimpleNamespace(filter=MagicMock(return_value=SimpleNamespace(first=card)), get_by_role=MagicMock(return_value=SimpleNamespace(first=missing)))
        page = SimpleNamespace(url=COPY_URL, locator=MagicMock(return_value=cards))
        candidate = DocumentCandidate('gemini-card:missing.pdf', SOURCE_URL, 'missing.pdf')
        with patch('gui.service.goto_with_retry_gui', new=AsyncMock()) as goto, patch('gui.service.collect_virtualized_html', new=AsyncMock()) as collect:
            with self.assertRaises(FileNotFoundError):
                asyncio.run(_gemini_document_card_download(page, candidate, 1000))
        goto.assert_awaited_once_with(page, SOURCE_URL, attempts=1)
        collect.assert_awaited_once_with(page)

    def test_search_binds_redirected_gem_source(self):
        copied, original = fixtures()
        actual_url = 'https://gemini.google.com/gem/gem123/source12345678'
        selectors = {
            '[data-test-id="search-chats-button"] a': SimpleNamespace(click=AsyncMock()),
            'input[data-test-id="search-input"]': SimpleNamespace(fill=AsyncMock()),
            '.search-results-header, .no-results': SimpleNamespace(first=SimpleNamespace(wait_for=AsyncMock())),
            'search-snippet a[href]': SimpleNamespace(evaluate_all=AsyncMock(return_value=['/app/source12345678'])),
        }
        page = SimpleNamespace(url=actual_url, locator=MagicMock(side_effect=lambda selector: selectors[selector]))
        with patch('gui.service.goto_with_retry_gui', new=AsyncMock()), patch(
            'gui.service._page_has_conversation_content', new=AsyncMock(return_value=True)
        ), patch('gui.service.collect_virtualized_html', new=AsyncMock(return_value=original)):
            url, restored = asyncio.run(_recover_gemini_copied_attachments(page, copied, COPY_URL))
        self.assertEqual(url, actual_url)
        candidates = _extract_gemini_document_card_candidates(restored, url)
        self.assertTrue(candidates)
        self.assertTrue(all(candidate.url == actual_url for candidate in candidates))

    def test_matching_gem_source_does_not_navigate_away(self):
        actual_url = 'https://gemini.google.com/gem/gem123/source12345678'
        missing = SimpleNamespace(count=AsyncMock(return_value=0))
        card = SimpleNamespace(locator=MagicMock(return_value=SimpleNamespace(first=missing)))
        cards = SimpleNamespace(filter=MagicMock(return_value=SimpleNamespace(first=card)), get_by_role=MagicMock(return_value=SimpleNamespace(first=missing)))
        page = SimpleNamespace(url=actual_url, locator=MagicMock(return_value=cards))
        candidate = DocumentCandidate('gemini-card:missing.pdf', actual_url, 'missing.pdf')
        with patch('gui.service.goto_with_retry_gui', new=AsyncMock()) as goto, patch('gui.service.collect_virtualized_html', new=AsyncMock()) as collect:
            with self.assertRaises(FileNotFoundError):
                asyncio.run(_gemini_document_card_download(page, candidate, 1000))
        goto.assert_not_awaited()
        collect.assert_not_awaited()

    def test_copied_image_uses_native_original_and_upgrades_cached_preview(self):
        source = 'https://lh3.googleusercontent.com/gg/example'
        body = b'\x89PNG\r\n\x1a\noriginal'
        wrapper = SimpleNamespace(screenshot=AsyncMock(return_value=body), evaluate=AsyncMock())
        page = SimpleNamespace(evaluate=AsyncMock(return_value='original-image'), locator=MagicMock(return_value=wrapper))
        with tempfile.TemporaryDirectory() as directory, patch('gui.service._authenticated_page_get', new=AsyncMock()) as get:
            target = Path(directory)
            cached = target / f'img_1_{hashlib.md5(source.encode()).hexdigest()[:8]}.png'
            cached.write_bytes(b'\x89PNG\r\n\x1a\npreview')
            mapping = asyncio.run(_download_image_candidates(page, [source], target, './images', prefer_original=True))
            self.assertEqual(mapping[source], './images/' + cached.name)
            self.assertEqual(cached.read_bytes(), body)
            self.assertEqual(len(list(target.iterdir())), 1)
        get.assert_not_awaited()
        self.assertIn("'=s0'", page.evaluate.await_args.args[0])
        self.assertIn('image.naturalWidth', page.evaluate.await_args.args[0])
        wrapper.evaluate.assert_awaited_once_with('node => node.remove()')

if __name__ == '__main__':
    unittest.main()
