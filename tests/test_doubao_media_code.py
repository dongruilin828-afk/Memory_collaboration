"""Doubao reply ledger and generated-code source recovery."""
import copy
import json
import unittest
from bs4 import BeautifulSoup

from scripts.doubao_summary import reconcile_media_bindings
from scripts.providers import doubao


def media(number=1, available=True):
    return {'media_id': 'M001', 'message_index': number, 'source_role': 'user',
            'status': 'described' if available else 'unavailable', 'can_reverify': available,
            'access_status': 'available_local' if available else 'unavailable',
            'assistant_bindings': [{'user_message_id': number, 'assistant_message_ids': [],
               'assistant_conclusion': '程序独立识别的图片内容', 'conclusion_status': 'unavailable'}]}


class MediaLedgerTests(unittest.TestCase):
    def test_available_images_bind_to_actual_answer_without_resource_failure(self):
        messages = [{'role': 'User', 'content': '图片1'}, {'role': 'AI', 'content': '第一题解答'},
                    {'role': 'User', 'content': '图片2'}, {'role': 'AI', 'content': '第二题解答'},
                    {'role': 'User', 'content': '图片3'}, {'role': 'AI', 'content': '第三题解答'}]
        result = {'media': [media(i) for i in (1, 3, 5)]}
        reconcile_media_bindings(result, messages)
        for asset, answer in zip(result['media'], (2, 4, 6)):
            binding = asset['assistant_bindings'][0]
            self.assertEqual(binding['assistant_message_ids'], [answer])
            self.assertEqual(binding['conclusion_status'], 'uncertain')
            self.assertEqual(binding['reply_evidence'][0]['quote'], messages[answer-1]['content'])
            self.assertNotIn('程序独立识别', binding['assistant_conclusion'])
            self.assertEqual(asset['status'], 'described')
        before = copy.deepcopy(result)
        reconcile_media_bindings(result, messages)
        self.assertEqual(before, result)

    def test_multiple_uploads_followup_and_no_cross_turn_guess(self):
        messages = [{'role': 'User', 'content': '上传'}, {'role': 'User', 'content': '请分析'},
                    {'role': 'AI', 'content': '收到文件，尚未分析'}, {'role': 'AI', 'content': '请补充信息'},
                    {'role': 'User', 'content': '新问题'}, {'role': 'AI', 'content': '下一轮回答'}]
        result = {'media': [media(), media()]}
        for asset in result['media']:
            asset['assistant_bindings'][0]['assistant_message_ids'] = [6]
        reconcile_media_bindings(result, messages)
        for asset in result['media']:
            binding = asset['assistant_bindings'][0]
            self.assertEqual(binding['assistant_message_ids'], [3, 4])
            self.assertIn('不等于 AI 已分析', binding['assistant_conclusion'])

    def test_no_reply_has_no_false_unavailable_conclusion(self):
        result = {'media': [media()]}
        reconcile_media_bindings(result, [{'role': 'User', 'content': '图片'}])
        self.assertEqual(result['media'][0]['assistant_bindings'], [])
        self.assertEqual(result['media'][0]['reply_binding_verification']['status'], 'no_ai_reply')
        self.assertEqual(result['media'][0]['access_status'], 'available_local')

    def test_empty_ai_reply_does_not_attach_a_later_turn(self):
        result = {'media': [media()]}
        reconcile_media_bindings(result, [{'role': 'User', 'content': '图片'}, {'role': 'AI', 'content': ''},
                                          {'role': 'User', 'content': '新问题'}, {'role': 'AI', 'content': '新回答'}])
        self.assertEqual(result['media'][0]['assistant_bindings'], [])

    def test_expired_file_stays_unavailable_but_historical_reply_is_preserved(self):
        result = {'media': [media(available=False)]}
        reconcile_media_bindings(result, [{'role': 'User', 'content': '图片'}, {'role': 'AI', 'content': '当时的回答'}])
        binding = result['media'][0]['assistant_bindings'][0]
        self.assertEqual(binding['assistant_message_ids'], [2])
        self.assertEqual(binding['conclusion_status'], 'unavailable')
        self.assertIn('不能重新验证', binding['assistant_conclusion'])

    def test_legacy_binding_gets_original_reply_and_assistant_media_is_unchanged(self):
        asset = media()
        asset['assistant_bindings'] = [{'user_message_id': 1, 'assistant_message_ids': [2],
                                        'assistant_conclusion': 'AI确认收到文件', 'conclusion_status': 'uncertain'}]
        other = media(2)
        other['source_role'] = 'assistant'
        result = {'media': [asset, other]}
        before = copy.deepcopy(result)
        reconcile_media_bindings(result, [{'role': 'User', 'content': '图片'}, {'role': 'AI', 'content': '收到'}])
        binding = result['media'][0]['assistant_bindings'][0]
        self.assertEqual(binding['reply_evidence'], [{'message_id': 2, 'quote': '收到'}])
        self.assertIn('原AI回复摘录', binding['assistant_conclusion'])
        self.assertEqual(before['media'][1], result['media'][1])
        revised = copy.deepcopy(result)
        reconcile_media_bindings(result, [{'role': 'User', 'content': '图片'}, {'role': 'AI', 'content': '收到'}])
        self.assertEqual(revised, result)


def source_page(markdown, body, source_id='200', message_id='200', extra=None):
    soup = BeautifulSoup(f'<div class="message-item" data-message-id="{message_id}">{body}</div>', 'html.parser')
    messages = [{'message_id': source_id, 'content': json.dumps({'text': markdown}, ensure_ascii=False)}]
    messages.extend(extra or [])
    args = ['thread_(token)/page', [{'key': 'shareInfo', 'routerDataFnArgs': [json.dumps({'data': {'message_list': messages}}, ensure_ascii=False)]}]]
    script = soup.new_tag('script')
    script['data-fn-args'] = json.dumps(args, ensure_ascii=False)
    soup.append(script)
    return soup


BAR = '<div><div data-testid="code-bar">已生成代码</div></div>'


class CodeRecoveryTests(unittest.TestCase):
    def test_original_message_restores_code_language_spacing_and_escapes(self):
        code = 'if ready:\n    print("中文\\n", r"C:\\temp\\a.py")\n'
        soup = source_page('```python\n' + code + '```', '<p>回答</p>' + BAR)
        text = doubao.parse_messages(soup)[0]['content']
        self.assertIn('```python\n' + code + '```', text)
        self.assertNotIn('已生成代码', text)
        self.assertNotIn('代码正文未读取', text)

    def test_two_identical_controls_receive_different_blocks_by_identity(self):
        soup = source_page('```python\nfirst()\n```\n```js\nsecond();\n```', BAR + BAR)
        text = doubao.parse_messages(soup)[0]['content']
        self.assertEqual(text.count('first()'), 1)
        self.assertEqual(text.count('second();'), 1)
        self.assertIn('```js', text)

    def test_wrong_message_or_conflicting_version_never_borrows_code(self):
        extra = [{'message_id': '200', 'content': json.dumps({'text': '```\nwrong()\n```'})}]
        for soup in (source_page('```\nsecret()\n```', BAR, source_id='201'),
                     source_page('```\nsecret()\n```', BAR, extra=extra)):
            with self.subTest():
                text = doubao.parse_messages(soup)[0]['content']
                self.assertIn('[代码正文未读取]', text)
                self.assertNotIn('secret()', text)
                self.assertNotIn('wrong()', text)

    def test_mixed_native_and_collapsed_code_must_match_original_order(self):
        markdown = '```\nfirst()\n```\n```\nsecond()\n```'
        html = '<pre><code>first()\n</code></pre>' + BAR
        text = doubao.parse_messages(source_page(markdown, html))[0]['content']
        self.assertIn('second()', text)
        mismatch = doubao.parse_messages(source_page(markdown, html.replace('first()', 'different()')))[0]['content']
        self.assertIn('[代码正文未读取]', mismatch)
        self.assertNotIn('second()', mismatch)

    def test_open_card_does_not_duplicate_native_code(self):
        html = '<div><div data-testid="code-bar">已生成代码</div><pre><code>first()\n</code></pre></div>'
        text = doubao.parse_messages(source_page('```\nfirst()\n```', html))[0]['content']
        self.assertEqual(text.count('first()'), 1)
        self.assertNotIn('已生成代码', text)

    def test_long_fence_keeps_short_fence_inside_code(self):
        code = 'before\n```\nafter\n'
        self.assertEqual(doubao._fenced_code_blocks('````text\n' + code + '`````'), [('text', code)])
        result = doubao.parse_messages(source_page('````text\n' + code + '`````', BAR))[0]['content']
        self.assertEqual(doubao._fenced_code_blocks(result), [('text', code)])


if __name__ == '__main__':
    unittest.main()
