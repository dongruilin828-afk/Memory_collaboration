"""Gemini 原生可展开代码面板：源码与输出需分别保留。"""
import unittest

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from gui.service import _parse_page_messages
from scripts.providers import gemini


def parse(html):
    provider, messages = _parse_page_messages(
        'https://gemini.google.com/app/example',
        BeautifulSoup('<message-content>' + html + '</message-content>', 'html.parser'), {})
    assert provider is gemini
    text = messages[0]['content']
    return text, [(t.info, t.content) for t in MarkdownIt().parse(text) if t.type == 'fence']


class GeminiCodeOutputTests(unittest.TestCase):
    def test_collapsed_panel_preserves_source_and_labeled_output_in_order(self):
        text, blocks = parse('''<p>先计算</p><code-block>
          <div style="display:none;height:0px">
            <div class="code-block-decoration"><span>Python</span><button>复制</button></div>
            <pre><code data-test-id="code-content">print(2 &lt; 3)</code></pre>
            <div>代码输出</div>
            <pre><code data-test-id="code-output-stdout-stderr">True
  保留缩进 &lt;tag&gt;
Traceback: example error</code></pre>
          </div></code-block><p>以上是结果</p>''')
        self.assertEqual(blocks, [('Python', 'print(2 < 3)\n'),
                                 ('text', 'True\n  保留缩进 <tag>\nTraceback: example error\n')])
        self.assertEqual(text.count('代码输出'), 1)
        self.assertLess(text.index('print('), text.index('代码输出'))
        self.assertLess(text.index('代码输出'), text.index('True'))
        self.assertLess(text.index('Traceback:'), text.index('以上是结果'))
        self.assertNotIn('复制', text)

    def test_multiple_panels_keep_repeated_output_without_borrowing_language(self):
        panel = '''<code-block><div class="code-header"><span>Python</span></div>
        <pre><code>print(1)</code></pre>
        <pre><code data-test-id="code-output-stdout-stderr">1</code></pre></code-block>'''
        text, blocks = parse(panel + '<p>再验证</p>' + panel)
        self.assertEqual(blocks, [('Python', 'print(1)\n'), ('text', '1\n')] * 2)
        self.assertEqual(text.count('代码输出'), 2)

    def test_additional_plain_pre_and_output_only_panel_are_preserved(self):
        text, blocks = parse('''<code-block><div class="code-header"><span>Python</span></div>
        <pre><code>print(7)</code></pre><pre>7</pre></code-block>
        <code-block><pre><code data-test-id="code-output-stdout-stderr">saved</code></pre></code-block>''')
        self.assertEqual(blocks, [('Python', 'print(7)\n'), ('', '7\n'), ('text', 'saved\n')])


if __name__ == '__main__':
    unittest.main()
