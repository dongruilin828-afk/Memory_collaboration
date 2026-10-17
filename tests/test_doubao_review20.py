"""用户人工审查20：图片配文尾缀、同名在线文档与失败占位。"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bs4 import BeautifulSoup
from scripts.providers import doubao
from gui.service import _save_doubao_ai_documents


def card(message_id):
    return f'''<div class="message-item"><div data-message-id="{message_id}">
      <p>文档已就绪</p><div class="product-card-test">
      <div class="card-content-info-title-text-test">同名报告</div>
      <div>创建时间：06-27 20:25</div></div></div></div>'''


class Review20ParserTests(unittest.TestCase):
    def test_suggested_titles_are_not_exported_as_document_body(self):
        html = card(101)[:-6] + '<p>请保留这段正文。</p>' + '<div data-testid="suggest_message_item">同名报告</div>'*3 + '</div>'
        text = doubao.parse_messages(BeautifulSoup(html,'html.parser'), {'doubao-ai-doc-message:101':'./documents/first.md'})[0]['content']
        self.assertIn('请保留这段正文。',text)
        self.assertIn('./documents/first.md',text)
        self.assertNotIn('同名报告',text)

    def test_doubao_simple_ignores_section_numbers_but_keeps_real_prediction(self):
        from scripts.simple_summarizer import validate_simple_overview
        projection = {'topics':[{'summary':'论文第5.3节提出按预测分配储位。'}]}
        overview = '对话围绕论文修改与文档交付。'
        self.assertFalse(validate_simple_overview(overview,projection,200,source_platform='豆包'))
        self.assertIn('遗漏了数值预测或估算主题的核心数值',validate_simple_overview(overview,projection,200))
        projection['topics'][0]['summary']='论文第5.3节预测效率提升20%。'
        self.assertIn('遗漏了数值预测或估算主题的核心数值',validate_simple_overview(overview,projection,200,source_platform='豆包'))
        self.assertFalse(validate_simple_overview('预测效率提升20%。',projection,200,source_platform='豆包'))

    def test_only_share_generated_caption_sentence_suffix_is_removed(self):
        html = '''<div class="message-item"><div class="paragraph-test">我将去除标识。...</div>
          <pre>print("。...")</pre><div class="image-box-grid-test"><img src="https://a/image.png"></div></div>'''
        message = doubao.parse_messages(BeautifulSoup(html, 'html.parser'))[0]['content']
        self.assertIn('我将去除标识。\n', message)
        self.assertNotIn('我将去除标识。...', message)
        self.assertIn('print("。...")', message)
        for attrs, image in [('', ''), ('data-doubao-role="assistant"', '<div class="image-box-grid-test"></div>')]:
            with self.subTest(attrs=attrs, image=image):
                text = f'<div class="message-item" {attrs}><div class="paragraph-test">实际正文。...</div>{image}</div>'
                self.assertIn('实际正文。...', doubao.parse_messages(BeautifulSoup(text, 'html.parser'))[0]['content'])

    def test_same_title_missing_versions_never_reuse_first_file(self):
        messages = doubao.parse_messages(BeautifulSoup(''.join(card(n) for n in (101, 102, 103)), 'html.parser'), {
            'doubao-ai-doc-message:101': './documents/first.md',
            '同名报告': './documents/first.md',
        })
        self.assertIn('./documents/first.md', messages[0]['content'])
        for message in messages[1:]:
            self.assertIn('AI生成文档未下载', message['content'])
            self.assertIn('同名报告', message['content'])
            self.assertNotIn('./documents/first.md', message['content'])
            self.assertNotIn('创建时间', message['content'])


class Review20DocumentTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_url_failure_retries_own_card_without_crossing_resources(self):
        for navigation_error, wrong_resource in [(False,False),(True,False),(False,True)]:
            with self.subTest(navigation_error=navigation_error,wrong_resource=wrong_resource):
                page=MagicMock();page.url='https://www.doubao.com/chat/123';page.frames=[]
                scope=MagicMock();scope.count=AsyncMock(return_value=1)
                node=MagicMock();node.first=node;node.locator.return_value=node
                node.count=AsyncMock(return_value=1);node.scroll_into_view_if_needed=AsyncMock()
                async def click(**_kwargs):
                    page.frames=[SimpleNamespace(url='https://www.doubao.com/partner/ccm-docx/docx/'+('OtherDocument' if wrong_resource else 'ExpectedDocument'))]
                node.click=AsyncMock(side_effect=click)
                scope.get_by_text.return_value=node;page.locator.return_value=scope
                direct=SimpleNamespace(url='https://www.doubao.com/docx/ExpectedDocument',goto=AsyncMock(side_effect=TimeoutError() if navigation_error else None),close=AsyncMock(),is_closed=lambda:False)
                card_page=SimpleNamespace(url='https://www.doubao.com/docx/'+('OtherDocument' if wrong_resource else 'ExpectedDocument'),goto=AsyncMock(),close=AsyncMock(),is_closed=lambda:False)
                page.context.new_page=AsyncMock(side_effect=[direct,card_page])
                page.keyboard.press=AsyncMock();page.wait_for_timeout=AsyncMock()
                async def download(document_page):
                    return b'' if document_page is direct else b'# Complete recovered document'
                with tempfile.TemporaryDirectory() as directory,patch('gui.service._download_doubao_ai_document_markdown',new=AsyncMock(side_effect=download)):
                    warnings=[]
                    html=card(202).replace('同名报告','另一份报告')
                    mapping,count=await _save_doubao_ai_documents(page,html,Path(directory),'./documents',warnings,entries=[('同名报告',direct.url,'101'),('另一份报告',direct.url,'102')])
                    self.assertEqual(count,2)
                    if wrong_resource:
                        self.assertFalse(mapping);self.assertTrue(warnings)
                    else:
                        self.assertIn('doubao-ai-doc-message:101',mapping);self.assertFalse(warnings)
                    node.click.assert_awaited_once()
                    page.get_by_text.assert_not_called()

    async def test_private_missing_card_is_revealed_before_download(self):
        page = MagicMock()
        page.url = 'https://www.doubao.com/chat/123'
        scope = MagicMock()
        scope.count = AsyncMock(side_effect=[0, 1])
        title = MagicMock()
        title.first = title
        title.count = AsyncMock(return_value=1)
        title.scroll_into_view_if_needed = AsyncMock()
        async def open_document(**_options):
            page.frames = [SimpleNamespace(url='https://www.doubao.com/partner/ccm-docx/docx/document123')]
        title.click = AsyncMock(side_effect=open_document)
        title.locator.return_value = title
        scope.get_by_text.return_value = title
        page.locator.return_value = scope
        page.frames = []
        doc = SimpleNamespace(url='https://www.doubao.com/docx/document123', goto=AsyncMock(), close=AsyncMock(), is_closed=lambda: False)
        page.context.new_page = AsyncMock(return_value=doc)
        page.keyboard.press = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        with tempfile.TemporaryDirectory() as directory, patch(
            'gui.service._reveal_doubao_document_message', new=AsyncMock()
        ) as reveal, patch(
            'gui.service._download_doubao_ai_document_markdown', new=AsyncMock(return_value=b'# Complete\n\nEnd')
        ):
            warnings = []
            mapping, count = await _save_doubao_ai_documents(
                page, '', Path(directory), './documents', warnings, entries=[('同名报告', '', '102')])
            reveal.assert_awaited_once_with(page, '102', '同名报告')
            self.assertEqual(count, 1)
            self.assertIn('doubao-ai-doc-message:102', mapping)
            self.assertFalse(warnings)

    async def test_same_title_cards_clear_previous_editor_route(self):
        page = MagicMock()
        page.url = 'https://www.doubao.com/chat/123'
        page.frames = []
        async def reload(**_options):
            page.frames = []
        page.reload = AsyncMock(side_effect=reload)
        scope = MagicMock()
        scope.count = AsyncMock(return_value=1)
        scope.first = scope
        scope.wait_for = AsyncMock()
        page.locator.return_value = scope
        node = MagicMock()
        node.first = node
        node.locator.return_value = node
        node.count = AsyncMock(return_value=1)
        node.scroll_into_view_if_needed = AsyncMock()
        scope.get_by_text.return_value = node
        click_count = 0
        async def click(**_options):
            nonlocal click_count
            click_count += 1
            page.frames = [SimpleNamespace(url='https://www.doubao.com/partner/ccm-docx/docx/'+('FirstDocument' if click_count==1 else 'SecondDocument'))]
        node.click = AsyncMock(side_effect=click)
        doc = SimpleNamespace(url='', goto=AsyncMock(), close=AsyncMock(), is_closed=lambda:False)
        async def goto(url, **_options):
            doc.url = url
        doc.goto.side_effect = goto
        page.context.new_page = AsyncMock(return_value=doc)
        page.keyboard.press = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        async def download(document_page):
            return document_page.url.encode('utf-8')
        with tempfile.TemporaryDirectory() as directory, patch(
            'gui.service._download_doubao_ai_document_markdown', new=AsyncMock(side_effect=download)
        ):
            mapping, count = await _save_doubao_ai_documents(
                page, '', Path(directory), './documents', [],
                entries=[('同名报告','','101'),('同名报告','','102')])
            self.assertEqual(count,2)
            self.assertNotEqual(mapping['doubao-ai-doc-message:101'],mapping['doubao-ai-doc-message:102'])
            page.reload.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
