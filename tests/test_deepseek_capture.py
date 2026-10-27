"""DeepSeek source identity, literal inputs and original-image recovery."""
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from bs4 import BeautifulSoup
from PIL import Image
from scripts.providers import deepseek, deepseek_source as source
from gui.service import generate_raw_markdown

SESSION = "11111111-1111-1111-1111-111111111111"
FILE1 = "file-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
FILE2 = "file-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def file(file_id=FILE1):
    return dict(id=file_id, file_name="image.jpg", file_size=99, status="SUCCESS", is_image=False)


def message(body, files=None):
    parts = ([dict(type="FILE", files=files)] if files else []) + [dict(type="REQUEST", content=body)]
    return dict(message_id=1, parent_id=None, role="USER", fragments=parts)


def html(messages):
    nodes = ''.join(f'<div data-virtual-list-item-key="{m["message_id"]}"><div class="ds-message">'
                    + ('<div class="ds-think-content">正在思考</div>' if m['role'] == 'ASSISTANT' else 'UI text')
                    + '</div></div>' for m in messages)
    return '<html><body>' + nodes + source.embed_source(dict(target=SESSION, share=False, messages=messages)) + '</body></html>'


class DeepSeekSourceTests(unittest.TestCase):
    def test_answer_keeps_code_diagram_and_clickable_citations_without_hidden_ui(self):
        msg = dict(message_id=2, role='ASSISTANT', fragments=[
            dict(type='RESPONSE', content='```mermaid\nflowchart TD\n    A --> B\n```\n')])
        source_html = source.embed_source(dict(target=SESSION,share=False,messages=[msg]))
        soup = BeautifulSoup('<div data-virtual-list-item-key="2"><div class="ds-message">'
                             '<div class="ds-assistant-message-main-content">'
                             '<pre><code>x = "[citation:1]"  \n</code></pre>'
                             '<svg id="mermaid-svg-0"><text>flattened diagram UI</text></svg>'
                             '<p>结论<a href="https://example.org/source"><span class="ds-markdown-cite">'
                             '<span style="opacity: 0">-</span>1</span></a></p></div>'
                             '</div></div>'+source_html, 'html.parser')
        output = deepseek.parse_messages(soup)[0]['content']
        self.assertIn('x = "[citation:1]"  \n```', output)
        self.assertIn('```mermaid\nflowchart TD\n    A --> B\n```', output)
        self.assertIn('[1](https://example.org/source)', output)
        self.assertNotIn('flattened diagram UI', output)
        self.assertNotIn('[-1]', output)

    def test_math_keeps_list_and_quote_context_and_literal_backslashes(self):
        node=BeautifulSoup('<div><p>literal \\\\ and <em>emphasis</em></p>'
            '<ul><li><p>公式：</p><span role="math" data-math-source="a+b" style="display:block"></span>'
            '<p>后续说明</p></li><li>第二项</li></ul>'
            '<blockquote><span role="math" data-math-source="x" style="display:block"></span></blockquote></div>','html.parser').div
        output=deepseek._node_to_markdown(node,{})
        self.assertIn('literal \\\\\\\\',output)
        self.assertIn('  $\\displaystyle a+b$',output)
        self.assertIn('> $\\displaystyle x$',output)
        self.assertIn('<em>emphasis</em>',output)

    def test_current_branch_follows_parent_ids_instead_of_longest_or_sorted_cache(self):
        messages = [dict(message_id=i, parent_id=p) for i,p in [(1,None),(2,1),(3,2),(4,3),(5,2),(6,5)]]
        data = dict(chat_session=dict(id=SESSION, current_message_id=6), chat_messages=messages)
        self.assertEqual([m['message_id'] for m in source.current_branch(data, SESSION)], [1,2,5,6])
        with self.assertRaises(source.SourceError):
            source.current_branch(data, 'wrong-session')
        messages[-1]['parent_id'] = 999
        with self.assertRaises(source.SourceError):
            source.current_branch(data, SESSION)
        messages[-1]['parent_id'] = 6
        with self.assertRaises(source.SourceError):
            source.current_branch(data, SESSION)
        with self.assertRaises(source.SourceError):
            source.current_branch(dict(chat_session=data['chat_session'], chat_messages=[], cache_control='MERGE'), SESSION)

    def test_nested_display_math_keeps_matrix_row_breaks_and_comment_semantics(self):
        from html import escape
        latex='\\begin{pmatrix}\n1 & 2 \\\\ % row comment\n3 & 4\n\\end{pmatrix}'
        node=BeautifulSoup('<div><ul><li><p>矩阵：</p><span role="math" style="display:block" data-math-source="'+escape(latex,quote=True)+'"></span><p>正文继续</p></li></ul>'
                           '<pre><code>$$\nliteral \\\\ matrix\n$$</code></pre></div>','html.parser').div
        output=deepseek._node_to_markdown(node,{})
        self.assertIn('$\\displaystyle \\begin{pmatrix} 1 & 2 \\\\  3 & 4 \\end{pmatrix}$',output)
        self.assertNotIn('% row comment',output)
        self.assertIn('正文继续',output)
        self.assertIn('```\n$$\nliteral \\\\ matrix\n$$\n```',output)

    def test_literal_markdown_indentation_blanks_and_ui_words_survive_actual_saved_export(self):
        body = '# 输入\n\n1. 步骤\n    - 子项\n\n```python\ndef f():\n    return 1\n```\n\n复制\n\n</script>\n'
        parsed = deepseek.parse_messages(BeautifulSoup(html([message(body)]), 'html.parser'))
        self.assertEqual(parsed[0]['content'], body)
        self.assertEqual(parsed[0]['source_id'], 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'export.md'
            generate_raw_markdown(parsed, path)
            saved = path.read_bytes().decode('utf-8').replace('\r\n','\n')
        self.assertIn(body, saved)
        self.assertNotIn('\r\r\n', saved)

    def test_thinking_without_output_never_becomes_a_user_question(self):
        messages = [message('问题'), dict(message_id=2, parent_id=1, role='ASSISTANT', status='FINISHED', fragments=[])]
        parsed = deepseek.parse_messages(BeautifulSoup(html(messages), 'html.parser'))
        self.assertEqual([m['role'] for m in parsed], ['User','AI'])
        self.assertEqual(parsed[-1]['content'], '')
        self.assertEqual(parsed[-1]['reasoning'], '正在思考')

    def test_same_filename_never_borrows_another_files_local_path(self):
        f1,f2 = file(),file(FILE2)
        counts = source.name_counts(dict(messages=[message('', [f1,f2])]))
        self.assertIsNone(source.file_href(f2, {'image.jpg':'./wrong.jpg'}, counts))
        assets = {'https://files.deepseeksvc.com/api/file?file_id='+FILE2[5:]+'&state=private':'./second.png'}
        self.assertEqual(source.file_href(f2, assets, counts), './second.png')
        parsed = deepseek.parse_messages(BeautifulSoup(html([message('说明', [f1,f2])]), 'html.parser'), assets)
        self.assertIn('![image.jpg](./second.png)', parsed[0]['content'])
        self.assertEqual(parsed[0]['content'].count('原文件未能下载'), 1)

    def test_filename_brackets_do_not_break_the_attachment_label(self):
        attachment=dict(id=FILE1,file_name='[.txt',file_size=10,is_image=False)
        parsed=deepseek.parse_messages(BeautifulSoup(html([message('比对',[attachment])]),'html.parser'),
                                       {'deepseek-file:'+FILE1:'./documents/a.txt'})
        self.assertIn('[📄 \\[.txt](./documents/a.txt)',parsed[0]['content'])

    def test_collapsed_input_fallback_does_not_strip_indentation(self):
        soup=BeautifulSoup('<div data-virtual-list-item-key="1"><div class="ds-message"><div class="ds-collapsible-text"><span>a\n\n    b\n</span></div></div></div>', 'html.parser')
        self.assertEqual(deepseek.parse_messages(soup)[0]['content'], 'a\n\n    b\n')


class DeepSeekOriginalImageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.images=Path(self.tmp.name)/'images'
        image=Image.new('RGB',(2,2),'red');buffer=io.BytesIO();image.save(buffer,format='PNG');self.body=buffer.getvalue()

    def page(self, status=200):
        body=self.body
        async def metadata(_script, path):
            return dict(status=200,data=dict(code=0,data=dict(biz_code=0,biz_data=dict(files=[dict(
                id=FILE1,file_name='image.jpg',file_size=len(body)+100,status='SUCCESS',
                signed_path='/file?file_id='+FILE1[5:]+'&state=private-signature')]))))
        response=SimpleNamespace(status=status,body=AsyncMock(return_value=body))
        return SimpleNamespace(url='https://chat.deepseek.com/a/chat/s/'+SESSION,evaluate=AsyncMock(side_effect=metadata),
                               context=SimpleNamespace(request=SimpleNamespace(get=AsyncMock(return_value=response))))

    async def test_image_file_card_downloads_as_real_image_with_verified_id(self):
        page=self.page();warnings=[]
        mapping=await source.download_missing_images(page,html([message('说明',[file()])]),self.images,'./images',{},warnings)
        path=Path(self.tmp.name)/mapping['deepseek-file:'+FILE1].removeprefix('./')
        self.assertEqual(path.read_bytes(),self.body)
        self.assertEqual(path.suffix,'.png')
        self.assertEqual(warnings,[])
        self.assertIn('&ty=p',page.context.request.get.call_args.args[0])

    async def test_deleted_original_is_warned_without_signature_or_fake_file(self):
        page=self.page(status=404);warnings=[]
        mapping=await source.download_missing_images(page,html([message('说明',[file()])]),self.images,'./images',{},warnings)
        self.assertEqual(mapping,{})
        self.assertFalse(self.images.exists())
        self.assertIn('HTTP 404',warnings[0])
        self.assertNotIn('private-signature',warnings[0])

    async def test_existing_verified_image_is_reused_without_an_extra_download(self):
        page=self.page();warnings=[]
        ref='https://files.deepseeksvc.com/api/file?file_id='+FILE1[5:]
        mapping=await source.download_missing_images(page,html([message('说明',[file()])]),self.images,'./images',{ref:'./images/existing.webp'},warnings)
        self.assertEqual(mapping['deepseek-file:'+FILE1],'./images/existing.webp')
        page.evaluate.assert_not_called()
        page.context.request.get.assert_not_called()


if __name__ == '__main__':unittest.main()
