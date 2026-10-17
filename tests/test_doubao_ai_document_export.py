"""Regression test for Doubao online document Markdown downloads."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from gui.service import (
    _download_doubao_ai_document_markdown,
    _extract_doubao_ai_document_entries,
    _save_doubao_ai_documents,
)
from bs4 import BeautifulSoup
from scripts.providers import doubao


class _DownloadContext:
    def __init__(self, path: Path):
        self.value = asyncio.get_running_loop().create_future()
        self.value.set_result(SimpleNamespace(
            suggested_filename="document.md",
            path=AsyncMock(return_value=str(path)),
        ))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class DoubaoAIDocumentExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_retries_menu_action_in_same_document_page(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'document.md'
            file.write_text('# 完整导出\n\n文末内容',encoding='utf-8')
            page=MagicMock()
            page.get_by_role.return_value=SimpleNamespace(wait_for=AsyncMock(),click=AsyncMock())
            menu=SimpleNamespace(click=AsyncMock(side_effect=[TimeoutError(),None]))
            page.get_by_text.return_value=menu
            page.keyboard.press=AsyncMock()
            page.expect_download.side_effect=lambda **_kwargs:_DownloadContext(file)
            self.assertEqual(await _download_doubao_ai_document_markdown(page),file.read_bytes())
            self.assertEqual(menu.click.await_count,2)
            page.keyboard.press.assert_awaited_once_with('Escape')

    async def test_downloads_full_markdown_from_document_menu(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "document.md"
            file.write_text("# 在线文档\n\n完整正文\n", encoding="utf-8")
            page = MagicMock()
            page.get_by_role.return_value = SimpleNamespace(
                wait_for=AsyncMock(), click=AsyncMock()
            )
            page.get_by_text.return_value = SimpleNamespace(click=AsyncMock())
            page.expect_download.return_value = _DownloadContext(file)

            payload = await _download_doubao_ai_document_markdown(page)

            self.assertEqual(payload, file.read_bytes())
            page.get_by_role.assert_called_once_with(
                "button", name="下载", exact=True
            )
            page.get_by_text.assert_called_once_with("Markdown", exact=True)

    async def test_private_card_exports_complete_document_in_same_context(self):
        title = "在线研究文档"
        doc_url = "https://www.doubao.com/docx/document123"
        page = MagicMock()
        page.url = "https://www.doubao.com/chat/123"
        title_node = MagicMock()
        title_node.count = AsyncMock(return_value=1)
        title_node.first = title_node
        title_node.locator.return_value = title_node
        title_node.scroll_into_view_if_needed = AsyncMock()
        async def open_document(**_options):
            page.frames = [SimpleNamespace(
                url="https://www.doubao.com/partner/ccm-docx/docx/document123"
            )]
        title_node.click = AsyncMock(side_effect=open_document)
        page.get_by_text.return_value = title_node
        page.frames = []
        document_page = SimpleNamespace(
            url=doc_url, goto=AsyncMock(), close=AsyncMock(), is_closed=lambda: False
        )
        page.context.new_page = AsyncMock(return_value=document_page)
        page.keyboard.press = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        payload = "# 在线研究文档\n\n开头正文\n\n## 文末附录\n完整末尾\n".encode()

        with tempfile.TemporaryDirectory() as directory, patch(
            "gui.service._extract_doubao_ai_document_titles", return_value=[title]
        ), patch(
            "gui.service._extract_doubao_ai_document_entries", return_value=[]
        ), patch(
            "gui.service._download_doubao_ai_document_markdown",
            new=AsyncMock(return_value=payload),
        ) as download:
            warnings = []
            resolved, count = await _save_doubao_ai_documents(
                page, "", Path(directory), "./documents", warnings
            )
            self.assertEqual(count, 1)
            self.assertFalse(warnings)
            self.assertEqual((Path(directory) / f"{title}.md").read_bytes(), payload)
            self.assertIn(doc_url, resolved)
            download.assert_awaited_once_with(document_page)
            document_page.goto.assert_awaited_once_with(
                doc_url, wait_until="domcontentloaded", timeout=10000
            )
            document_page.close.assert_awaited_once()
            page.keyboard.press.assert_awaited_once_with("Escape")

    async def test_failed_full_export_does_not_save_visible_partial_text(self):
        page = MagicMock()
        page.url = "https://www.doubao.com/thread/share123"
        document_page = SimpleNamespace(
            url="https://www.doubao.com/docx/document123",
            goto=AsyncMock(), close=AsyncMock(), is_closed=lambda: False,
        )
        page.context.new_page = AsyncMock(return_value=document_page)
        with tempfile.TemporaryDirectory() as directory, patch(
            "gui.service._extract_doubao_ai_document_titles", return_value=[]
        ), patch(
            "gui.service._extract_doubao_ai_document_entries",
            return_value=[("研究文档", document_page.url, "123")],
        ), patch(
            "gui.service._download_doubao_ai_document_markdown",
            new=AsyncMock(return_value=b""),
        ), patch(
            "gui.service._read_doubao_ai_document_body",
            new=AsyncMock(return_value="仅已加载的开头"),
        ) as partial:
            warnings = []
            resolved, count = await _save_doubao_ai_documents(
                page, "", Path(directory), "./documents", warnings
            )
            self.assertEqual((resolved, count), ({}, 1))
            self.assertFalse(list(Path(directory).iterdir()))
            self.assertIn("未能下载完整正文", warnings[0])
            partial.assert_not_awaited()

    async def test_same_title_versions_are_saved_and_bound_to_distinct_messages(self):
        html = '''<script>
        {"message_id":"101","artifact_block":{"resource_id":"DocumentFirst","title":"同名报告","resource_type":10},"is_finish":true}
        {"message_id":"102","artifact_block":{"resource_id":"DocumentSecond","title":"同名报告","resource_type":10},"is_finish":true}
        </script>
        <div class="message-item"><div data-message-id="101">第一份文档已就绪</div></div>
        <div class="message-item"><div data-message-id="102">第二份文档已就绪</div></div>'''
        entries = _extract_doubao_ai_document_entries(html, "https://www.doubao.com/thread/share123")
        self.assertEqual([e[2] for e in entries], ["101", "102"])
        page = MagicMock()
        page.url = "https://www.doubao.com/thread/share123"
        document_page = MagicMock()
        async def goto(url, **_kwargs):
            document_page.url = url
        document_page.goto = AsyncMock(side_effect=goto)
        document_page.close = AsyncMock()
        document_page.is_closed.return_value = False
        page.context.new_page = AsyncMock(return_value=document_page)
        with tempfile.TemporaryDirectory() as directory, patch(
            "gui.service._download_doubao_ai_document_markdown",
            new=AsyncMock(side_effect=[b"# First\n\nVersion one", b"# Second\n\nVersion two"]),
        ):
            warnings = []
            mapping, count = await _save_doubao_ai_documents(
                page, html, Path(directory), "./documents", warnings
            )
            self.assertEqual(count, 2)
            self.assertFalse(warnings)
            first, second = (mapping[f"doubao-ai-doc-message:{i}"] for i in (101, 102))
            self.assertNotEqual(first, second)
            self.assertNotIn("同名报告", mapping)
            messages = doubao.parse_messages(BeautifulSoup(html, "html.parser"), mapping)
            self.assertIn(first, messages[0]["content"])
            self.assertNotIn(second, messages[0]["content"])
            self.assertIn(second, messages[1]["content"])
            self.assertNotIn(first, messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
