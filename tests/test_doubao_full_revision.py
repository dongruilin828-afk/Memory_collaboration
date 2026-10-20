"""Batch35 failures and neighboring valid inputs, without browser/API calls."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from bs4 import BeautifulSoup
from PIL import Image
from scripts import gemini_summarizer as summary
from scripts.providers import doubao
from scripts import doubao_summary as rules
from scripts.doubao_media import _read_diagram, _read_native_chart, MediaGateway, prepare_csv, _verified_ocr_line
from scripts.summary_grounding import apply_latest_turn_grounding, render_grounded_overview


class CaptureTests(unittest.TestCase):
    def parse(self, body):
        return doubao.parse_messages(BeautifulSoup('<div class="message-item">'+body+'</div>', 'html.parser'), {})[0]['content']

    def test_signed_cgen_is_accepted_without_modifying_signature(self):
        url = 'https://p26-flow-imagex-sign.byteimg.com/rc_gen_image/id.jpeg~tplv-x-cgen_lwm3.png?signature=abc&expires=123'
        self.assertEqual(doubao.original_generated_image_sources(json.dumps({'url': url})), [url])
        thumb = url.replace('cgen_lwm3', 'cthumb_lwm3')
        self.assertEqual(doubao.prefer_original_generated_images([thumb, url]), [url])
        original = url.replace('cgen_lwm3', 'image_pre_watermark_1')
        self.assertEqual(doubao.prefer_original_generated_images([thumb, url, original]), [original])

    def test_chart_tabs_removed_but_same_words_in_prose_and_code_survive(self):
        body = '<p>正文解释预览与查看代码。</p><pre>print("查看代码")</pre>'
        body += '<div class="semi-tabs"><div role="tablist"><div role="tab">预览</div><div role="tab">查看代码</div></div><img alt="生成图表" src="chart.png"></div>'
        body += '<div class="semi-tabs"><div role="tablist">真实资料目录</div></div>'
        content = self.parse(body)
        self.assertEqual(content.count('预览'), 1)
        self.assertEqual(content.count('查看代码'), 2)
        self.assertIn('chart.png', content)
        self.assertIn('真实资料目录', content)

    def test_upsell_arrow_and_link_are_removed_locally(self):
        content = self.parse('<p>正文里提到电脑版体验更深入的文件解读。</p><a href="https://www.doubao.com/magic/eco/runtime/a">电脑版体验更深入的文件解读 →</a>')
        self.assertNotIn('/magic/eco/', content)
        self.assertNotIn('→', content)
        self.assertIn('正文里提到电脑版体验', content)

    def test_native_code_after_card_is_not_falsely_unread(self):
        content = self.parse('<div><div data-testid="code-bar">已生成代码</div></div><div><pre><code>print(123)</code></pre></div>')
        self.assertNotIn('代码正文未读取', content)
        self.assertIn('print(123)', content)

    def test_lazy_share_payload_restores_the_same_original_code(self):
        soup = BeautifulSoup('<div class="message-item" data-message-id="200"><div data-testid="code-bar">已生成代码</div></div>', 'html.parser')
        script = soup.new_tag('script')
        script['data-fn-name'] = 'r'
        script['data-fn-args'] = json.dumps(['thread_(token)/page', 'shareInfo',
            {'data': {'message_list': [{'message_id':'200', 'content':json.dumps({'text':'```python\nprint(123)\n```'})}]}}])
        soup.append(script)
        content = doubao.parse_messages(soup, {})[0]['content']
        self.assertIn('print(123)', content)
        self.assertNotIn('代码正文未读取', content)

    def test_one_native_block_does_not_hide_a_different_missing_card(self):
        content = self.parse('<div data-testid="code-bar">第一份代码</div><div data-testid="code-bar">第二份代码</div><pre>print(123)</pre>')
        self.assertEqual(content.count('代码正文未读取'), 1)
        self.assertIn('print(123)', content)

    def test_failed_chart_still_removes_only_its_tabs_and_reaches_warning_collector(self):
        content = self.parse('<div class="semi-tabs"><div role="tablist">预览 查看代码</div>'
                             '<div class="diagramContent-x">🖼️ [图表未保存]（网页图表未能加载）</div></div>')
        self.assertNotIn('预览', content)
        from gui.service import _clean_attachment_display
        warnings = []
        _clean_attachment_display([{'role':'AI','content':content}], warnings)
        self.assertTrue(any('图片' in warning for warning in warnings))


class ChartFrameTests(unittest.IsolatedAsyncioTestCase):
    async def test_outer_preview_follows_the_nested_chart_frame(self):
        leaf = Mock()
        empty_child = Mock()
        empty_child.first.count = AsyncMock(return_value=0)
        canvas = Mock()
        canvas.first.wait_for = AsyncMock()
        leaf.locator.side_effect = lambda selector: empty_child if selector == 'iframe' else canvas
        child = Mock()
        child.count = AsyncMock(return_value=1)
        child.element_handle = AsyncMock(return_value=child)
        child.content_frame = AsyncMock(return_value=leaf)
        outer = Mock()
        outer.locator.return_value.first = child
        handle = Mock()
        handle.content_frame = AsyncMock(return_value=outer)
        preview = AsyncMock()
        preview.element_handle.return_value = handle
        preview.screenshot.return_value = b'png'
        previews = Mock()
        previews.count = AsyncMock(return_value=1)
        previews.nth.return_value = preview
        message = Mock()
        message.locator.return_value = previews
        html = await doubao._preview_html(message, '<div><iframe src="https://x/html_preview/"></iframe></div>')
        self.assertIn('data:image/png;base64,', html)
        self.assertIn('生成图表', html)
        canvas.first.wait_for.assert_awaited_once()


class SummaryTests(unittest.TestCase):
    def messages(self):
        return [{'role': 'User', 'content': '图片'}, {'role': 'AI', 'content': '原AI分析NumPy导入失败。'},
                {'role': 'User', 'content': '新图片'}, {'role': 'AI', 'content': '新图片的回答。'}]

    def test_missing_ai_image_does_not_poison_next_user_turn(self):
        topics = [{'title': '新图', 'summary': '用户上传新图片，AI已回答。', 'source_message_ids': [3,4]}]
        assets = [{'media_id': 'M1', 'message_index': 2, 'kind': 'image', 'can_reverify': False}]
        result = summary._qualify_unavailable_media_topics(topics, assets, messages=self.messages(), source_platform='豆包')
        self.assertNotIn('media_access_note', result[0])
        self.assertNotIn('不可重新验证', result[0]['summary'])

    def test_mixed_media_warning_identifies_only_the_missing_resource(self):
        topics = [{'title': '图表', 'summary': '四张图', 'source_message_ids': [1,2]}]
        media = [{'media_id': 'M1', 'message_index': 2, 'kind': 'image', 'can_reverify': False},
                 {'media_id': 'M2', 'message_index': 2, 'kind': 'image', 'can_reverify': True}]
        rules.qualify_media_topics(topics, media, self.messages())
        self.assertIn('仅附件M1', topics[0]['media_access_note'])
        self.assertEqual(topics[0]['summary'], '四张图')

    def test_valid_ids_do_not_validate_a_visual_caption_as_historical_speech(self):
        media = {'media_id': 'M1', 'message_index': 1, 'source_role': 'user', 'can_reverify': True,
                 'access_status': 'available_local', 'assistant_bindings': [{'user_message_id': 1,
                 'assistant_message_ids': [2], 'assistant_conclusion': '截图代码x=[1,2,3]', 'conclusion_status': 'suggested'}]}
        result = {'media': [media]}
        rules.reconcile_media_bindings(result, self.messages())
        binding = media['assistant_bindings'][0]
        self.assertNotIn('x=', binding['assistant_conclusion'])
        self.assertEqual(binding['reply_evidence'][0]['quote'], self.messages()[1]['content'])
        before = copy.deepcopy(result)
        rules.reconcile_media_bindings(result, self.messages())
        self.assertEqual(result, before)

    def test_numeric_user_choice_stays_a_user_event(self):
        messages = [{'role': 'User', 'content': '生成图片'}, {'role': 'AI', 'content': '1. 风景 / 自然\n2. 动漫'},
                    {'role': 'User', 'content': '1'}, {'role': 'AI', 'content': '已提供图片。'}]
        claim = {'content': '用户选择生成自然风景图', 'source': 'user', 'status': 'delivered', 'message_ids': [3]}
        result = {'current_state': {'completed': [claim], 'pending': [], 'next_step': {}}}
        rules.reconcile_state(result, messages)
        self.assertEqual((claim['source'], claim['status'], claim['message_ids']), ('user','confirmed',[3]))
        result['current_state'].update(last_user_message_id=3, last_user_turn_answered=True,
            next_step={'content':'无法确定“1”的具体指向', 'source':'user', 'status':'uncertain','message_ids':[3]})
        rules.reconcile_state(result, messages)
        self.assertEqual(result['current_state']['next_step']['content'], '无明确待办事项')
        self.assertIn('风景', claim['selection_evidence']['option_text'])
        claim.update(content='用户选择宇宙飞船', source='user', status='delivered', message_ids=[3])
        rules.reconcile_state(result, messages)
        self.assertNotIn('宇宙飞船', claim['content'])
        claim.update(source='assistant', status='answered', message_ids=[4])
        rules.reconcile_state(result, messages)
        self.assertEqual((claim['source'], claim['status'], claim['message_ids']), ('user','confirmed',[3]))

    def test_latest_delivered_answer_is_not_a_next_step(self):
        result = {'current_state': {'last_user_message_id': 3, 'last_user_turn_answered': True, 'pending': [],
                  'next_step': {'content': 'AI提供新图片分析', 'source': 'assistant', 'status': 'delivered', 'message_ids': [4]}}}
        rules.reconcile_state(result, self.messages())
        self.assertEqual(result['current_state']['next_step']['content'], '无明确待办事项')
        result['current_state']['next_step'] = {'content': 'AI提供了错误分析', 'source':'assistant', 'status':'suggested', 'message_ids':[4]}
        rules.reconcile_state(result, self.messages())
        self.assertEqual(result['current_state']['next_step']['content'], '无明确待办事项')

    def test_topic_coverage_is_by_turn_not_every_document_paragraph(self):
        memories = [{'memory_id': 'M'+str(i), 'topic': '内部章节'+str(i), 'content': '章节细节', 'message_ids': [2]} for i in range(100)]
        topics = [{'title': '文件分析', 'summary': '分析文件', 'source_message_ids': [1,2], 'memory_ids': ['M0']}]*2
        result = rules.reconcile_topics(topics, memories, self.messages())
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]['memory_ids']), 100)
        self.assertEqual(result[0]['source_message_ids'], [1,2])
        reviewed = rules.reconcile_topics([{'title':'已核对主题','summary':'原AI分析','source_message_ids':[2]}], [], self.messages())
        self.assertEqual(reviewed[0]['source_message_ids'], [1,2])

    def test_partial_chunk_gap_does_not_override_full_original_answer(self):
        bad = {'content': '截至本批末尾，未见AI回应。', 'message_ids': [1,2]}
        real = {'content': 'AI尚未执行建议的环境修复。', 'message_ids': [2]}
        payload = {'memory_items': [bad, real]}
        rules.discard_partial_state(payload, self.messages())
        self.assertEqual(payload['memory_items'], [real])
        self.assertEqual(payload['doubao_discarded_partial_state'], [bad])

    def test_unrelated_english_term_is_replaced_by_actual_excerpt(self):
        messages = [{'role':'User','content':'daytime前用什么介词'}, {'role':'AI','content':'in the daytime 或 during the daytime'}]
        item = {'content':'press作为介词不用于daytime前', 'source':'assistant', 'message_ids':[2]}
        rules.guard_memory_terms({'memory_items':[item]}, messages)
        self.assertNotIn('press', item['content'])
        self.assertIn('during the daytime', item['content'])

    def test_watermark_fact_is_separate_from_the_historical_promise(self):
        asset = {'media_id':'M1','message_index':2,'can_reverify':True,'description':'图片【可见标注：AI生成】'}
        result = {'media':[asset], 'processing':{'doubao_state_verification':{}}, 'current_state':{}}
        grounded = {'user_message_id':1, 'user_text':'去掉AI生成水印', 'assistant_message_ids':[2], 'assistant_summary':'已提供无水印图片'}
        # A nonempty verification marker denotes the Doubao pipeline.
        result['processing']['doubao_state_verification'] = {'version':1}
        apply_latest_turn_grounding(result, grounded)
        text = render_grounded_overview(grounded)
        self.assertNotIn('已提供无水印', text)
        self.assertIn('上一 AI 回复：表示将处理', text)
        self.assertIn('附件核对：', text)

    def test_normal_summary_uses_generated_boundaries_not_quoted_headings(self):
        item = {'memory_id':'C001M001','topic':'测试','content':'细节','source':'assistant','status':'answered',
                'message_ids':[2], 'evidence_quote':'开头\n## 原文内的二级标题\n后续原文'}
        result = {'model':'test','source':'x.md','conversation':{'message_count':2,'chunk_count':1},
                  'current_state':{},'topics':[],'memory_items':[item],'query_index':[],'typed_records':{},
                  'media':[],'processing':{'doubao_state_verification':{'version':1}}}
        normal = summary.render_summary_markdown(result)
        self.assertNotIn('原文内的二级标题', normal)
        self.assertNotIn('C001M001', normal)
        self.assertIn('媒体与附件说明', normal)
        detailed = summary.render_summary_markdown(result, include_details=True)
        self.assertIn('细节', detailed)

    def test_source_review_cannot_accept_an_unknown_evidence_id(self):
        result = {'current_state':{'completed':[],'pending':[],'next_step':{}}, 'media':[],
                  'topics':[{'title':'导入错误','summary':'虚构结论','source_message_ids':[1,2],'memory_ids':[]}]}
        gateway = Mock()
        gateway.generate_json.return_value = {'items':[{'key':'topic0','decision':'keep','content':'虚构结论',
            'source':'assistant','status':'answered','evidence_ids':['S999P1']}]}
        rules.review_summary(result, self.messages(), gateway)
        topic = result['topics'][0]
        self.assertIn('原文摘录', topic['summary'])
        self.assertNotIn('虚构结论', topic['summary'])

    def test_diagram_regions_are_read_separately_without_inventing_step_totals(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'diagram.png'
            Image.new('RGB',(100,400),'white').save(path)
            asset = summary.MediaAsset('M1',1,'image','流程图',str(path),local_path=path,mime_type='image/png')
            gateway = Mock()
            gateway.generate_json.return_value = {'text_lines':['节点'+str(i) for i in range(7)],
                                                   'small_labels':['A','B','C','D','E'], 'uncertain':False}
            result = _read_diagram(asset, gateway, Path(temp))
            self.assertIn('不据错乱编号推断步骤总数', result['description'])
            self.assertIn('A、B、C、D、E', result['description'])
            self.assertEqual(gateway.generate_json.call_count, 4)
            self.assertTrue(all(len(c.kwargs['media_assets']) == 1 for c in gateway.generate_json.call_args_list))


class OutputBudgetTests(unittest.TestCase):
    def gateway(self, provider='deepseek'):
        return summary.SiliconFlowGateway(summary.SummaryConfig(provider=provider,
            model='deepseek-flash' if provider=='deepseek' else 'Qwen/Qwen3-8B', retries=2),
            api_key='test-key', sleep=lambda _: None)

    def respond(self, responses, payloads):
        values = iter(responses)
        class Response:
            def __init__(self, value): self.value = value
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return json.dumps({'choices':[self.value]}).encode()
        def request(req, timeout):
            payloads.append(json.loads(req.data))
            return Response(next(values))
        return patch.object(summary, 'urlopen', side_effect=request)

    def choice(self, reason, content):
        return {'finish_reason':reason,'message':{'content':content},'usage':{}}

    def test_doubao_retries_truncated_json_with_bounded_budget_and_same_request(self):
        base = self.gateway()
        progress = Mock()
        scoped = rules.prepare_text_gateway(base, progress)
        payloads = []
        with self.respond([self.choice('length','{"partial":true}'),
                           self.choice('stop','{"complete":true}')], payloads):
            self.assertEqual(scoped.generate_json('原文JSON', {'type':'object'}), {'complete':True})
        self.assertEqual([p['max_tokens'] for p in payloads], [16384,32768])
        self.assertEqual({k:v for k,v in payloads[0].items() if k!='max_tokens'},
                         {k:v for k,v in payloads[1].items() if k!='max_tokens'})
        self.assertEqual(base._doubao_output_limit, 0)
        self.assertEqual(base.config.max_output_tokens, 16384)
        self.assertEqual(len(scoped._doubao_output_events), 1)
        progress.assert_called_once()

    def test_doubao_stops_at_budget_cap_and_does_not_accept_partial_object(self):
        scoped = rules.prepare_text_gateway(self.gateway(), Mock())
        payloads = []
        with self.respond([self.choice('length','{"partial":true}')]*2, payloads):
            with self.assertRaisesRegex(summary.SummaryOutputTruncatedError, '32768'):
                scoped.generate_json('JSON', {'type':'object'})
        self.assertEqual([p['max_tokens'] for p in payloads], [16384,32768])

    def test_other_platform_gateway_keeps_previous_output_budget_behavior(self):
        base = self.gateway()
        payloads = []
        with self.respond([self.choice('length','{"ok":true}')], payloads):
            self.assertEqual(base.generate_json('JSON', {'type':'object'}), {'ok':True})
        self.assertEqual([p['max_tokens'] for p in payloads], [16384])

    def test_siliconflow_gateway_is_not_changed_by_doubao_budget_recovery(self):
        base = self.gateway(provider='siliconflow')
        self.assertIs(rules.prepare_text_gateway(base, Mock()), base)
        self.assertEqual(base._doubao_output_limit, 0)

    def test_malformed_json_without_length_does_not_raise_budget(self):
        scoped = rules.prepare_text_gateway(self.gateway(), Mock())
        payloads = []
        with self.respond([self.choice('stop','{bad'),self.choice('stop','{"ok":true}')], payloads):
            self.assertEqual(scoped.generate_json('JSON', {'type':'object'}), {'ok':True})
        self.assertEqual([p['max_tokens'] for p in payloads], [16384,16384])


class UnclearDiagramTests(unittest.TestCase):
    def test_independent_words_cannot_be_spliced_into_an_invented_line(self):
        self.assertEqual(_verified_ocr_line('1. Add our a position',
            ['1. Fill out form\n2. Add our a position']), ('',False))
        self.assertEqual(_verified_ocr_line('Toner',['Toners']), ('',False))
        self.assertEqual(_verified_ocr_line('Add our wechat work account',
            ['Add our wechat\nwork account']), ('Add our wechat work account',True))

    def test_uncertain_landscape_is_rechecked_and_unconfirmed_fifth_step_is_withheld(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'flow.png';Image.new('RGB',(400,120),'white').save(path)
            asset=summary.MediaAsset('M007',1,'image','图',str(path),local_path=path,mime_type='image/png')
            gateway=Mock()
            gateway.generate_json.side_effect=[
                {'text_lines':['1. Fill out form','5. Invented step','7. Meet new friends!'],'small_labels':[],'uncertain':True},
                {'text_lines':['1. Fill out form'],'small_labels':[],'uncertain':False},
                {'text_lines':['3. Pick out a position'],'small_labels':[],'uncertain':False},
                {'text_lines':['7. Meet new friends!'],'small_labels':[],'uncertain':False}]
            result=_read_diagram(asset,gateway,Path(temp))
            self.assertEqual(result['status'],'unclear')
            self.assertIn('1. Fill out form',result['description'])
            self.assertIn('7. Meet new friends!',result['description'])
            self.assertNotIn('Invented step',result['description'])
            self.assertIn('未补写猜测词或步骤',result['description'])
            self.assertEqual(gateway.generate_json.call_count,4)

    def test_successful_landscape_keeps_previous_single_read_path(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'flow.png';Image.new('RGB',(400,120),'white').save(path)
            asset=summary.MediaAsset('M007',1,'image','图',str(path),local_path=path,mime_type='image/png')
            gateway=Mock();gateway.generate_json.return_value={'text_lines':['原字形'],'small_labels':['Toner'],'uncertain':False}
            result=_read_diagram(asset,gateway,Path(temp))
            self.assertEqual(result['status'],'described')
            self.assertIn('Toner',result['description'])
            gateway.generate_json.assert_called_once()

    def test_automatic_retry_does_not_replace_diagram_reading_with_a_generic_caption(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'flow.png';Image.new('RGB',(1000,1000),'white').save(path)
            asset=summary.MediaAsset('M007',1,'image','图',str(path),local_path=path,mime_type='image/png')
            vision=Mock();vision.generate_json.side_effect=[
                {'items':[{'media_id':'M007','description':'流程图','status':'described'}]},
                {'items':[{'media_id':'M007','description':'包含8个步骤','status':'described'}]}]
            adapter=MediaGateway(Mock(),vision,summary.SummaryConfig())
            with patch('scripts.doubao_media._read_diagram',return_value={'status':'unclear','description':'逐字未能确认'}) as reader:
                for _ in range(2):
                    result=adapter.generate_json('核对',summary.MEDIA_SCHEMA,[asset])
                    self.assertEqual(result['items'][0]['description'],'逐字未能确认')
            self.assertEqual(reader.call_count,2)


class CsvTests(unittest.TestCase):
    def prepare(self, text, config=None, encoding='utf-8-sig', role='user'):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'table.csv'
            path.write_bytes(text.encode(encoding))
            asset=summary.MediaAsset('M002',3,'document','table.csv','./table.csv',local_path=path,source_role=role)
            prepare_csv(asset,config or summary.SummaryConfig())
            return asset

    def test_units_remain_with_their_literal_column_and_missing_units_are_not_inferred(self):
        asset=self.prepare('时间/h,距中心0cm,温度/℃\n0.5,2.5499,25\n')
        self.assertEqual(asset.status,'described')
        self.assertIn('["时间/h", "距中心0cm", "温度/℃"]',asset.description)
        self.assertIn('2.5499',asset.description)
        self.assertIn('没有明确标出的数值单位不推断',asset.description)
        self.assertNotIn('湿度',asset.description)
        self.assertNotIn('单位：cm',asset.description)

    def test_quoted_commas_and_multiline_cells_are_not_split_into_extra_fields(self):
        asset=self.prepare('name,note,value\n"a,b","two\nlines",1\n')
        self.assertIn('共1条记录',asset.description)
        self.assertIn('"a,b", "two\\nlines", "1"',asset.description)

    def test_limit_stops_at_whole_record_and_does_not_publish_partial_values(self):
        config=summary.SummaryConfig(text_attachment_chars=8)
        asset=self.prepare('x,y\n1,2\n12345,999\n',config)
        self.assertEqual(asset.extracted_text,'x,y\n1,2\n')
        self.assertIn('不代表全文',asset.description)
        self.assertNotIn('12345',asset.description)

    def test_empty_csv_and_utf16_csv_are_explicit_without_model_guesses(self):
        self.assertIn('共0条记录',self.prepare('').description)
        asset=self.prepare('距离/cm,力/N\n2,4\n',encoding='utf-16',role='assistant')
        self.assertIn('AI回答附带CSV',asset.description)
        self.assertIn('距离/cm',asset.description)

    def test_other_platforms_keep_the_existing_model_compression_path(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'data.csv').write_text('x/cm,y\n1,2\n',encoding='utf-8')
            messages=[{'role':'User','content':'[data.csv](./data.csv)'}]
            for platform in ('doubao','豆包','chatgpt','gemini',None):
                asset=summary.discover_media(messages,folder,folder,summary.SummaryConfig(),platform)[0]
                self.assertEqual(asset.status,'described' if platform in ('doubao','豆包') else 'ready')

    def test_stale_csv_description_and_dependent_chunks_cannot_overwrite_fresh_fields(self):
        from tests.test_gemini_summarizer import FakeGateway
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'data.csv').write_bytes('时间/h,距中心0cm\n0.5,2.5499\n'.encode())
            messages=[{'role':'User','content':'[data.csv](./data.csv)'}]
            config=summary.SummaryConfig(provider='deepseek');output=folder/'result.json'
            summary._save_summary_cache(summary._summary_cache_path(output),{
                'fingerprint':summary._summary_fingerprint(messages,config,'doubao'),
                'media':[{'media_id':'M001','reference':'./data.csv','status':'described','description':'湿度单位：cm'}],
                'chunks':{'1':{'title':'错误旧分块'}}})
            gateway=FakeGateway()
            with patch('scripts.doubao_summary.review_summary'):
                result=summary.summarize_conversation(messages,folder,config=config,gateway=gateway,
                    source_platform='doubao',output_json=output,output_markdown=folder/'summary.md',progress=lambda _:None)
            self.assertIn('程序独立读取',result['media'][0]['description'])
            self.assertNotIn('湿度单位：cm',result['media'][0]['description'])
            self.assertTrue(any(schema is summary.CHUNK_SCHEMA for schema,prompt in gateway.prompts))


class NativeChartTests(unittest.TestCase):
    def row(self, **changes):
        return dict(is_chart=True, title='径向分布', x_axis='距离(cm)', y_axis='含水量',
            legend_present=True, legend_labels=['t='+str(i/2)+'h' for i in range(1,7)],
            watermark_present=False, watermark_text='', description='', uncertain=False, **changes)

    def asset(self, path=None):
        return summary.MediaAsset('M004', 8, 'image', '生成图表', './chart.png',
                                  local_path=path or Path('chart.png'), mime_type='image/png')

    def test_six_literal_legend_labels_survive_without_optional_watermark_guess(self):
        gateway = Mock()
        row = self.row()
        row['watermark_text'] = 'AI生成'
        gateway.generate_json.return_value = row
        result = _read_native_chart(self.asset(), gateway)
        self.assertIn('图例（6项）', result['description'])
        self.assertIn('t=2.5h', result['description'])
        self.assertEqual(result['visible_watermarks'], [])
        self.assertNotIn('AI生成', result['description'])

    def test_real_watermark_is_preserved(self):
        gateway = Mock()
        row = self.row()
        row.update(watermark_present=True, watermark_text='AI生成')
        gateway.generate_json.return_value = row
        result = _read_native_chart(self.asset(), gateway)
        self.assertEqual(result['visible_watermarks'], ['AI生成'])
        self.assertIn('【可见标注：AI生成】', result['description'])

    def test_absent_legend_ignores_filler_array_and_unreadable_present_legend_is_unclear(self):
        gateway = Mock()
        row = self.row()
        row.update(legend_present=False, legend_labels=['', '', '猜测'])
        gateway.generate_json.return_value = row
        result = _read_native_chart(self.asset(), gateway)
        self.assertIn('不推测曲线数量', result['description'])
        self.assertNotIn('猜测', result['description'])
        row.update(legend_present=True, legend_labels=[])
        self.assertEqual(_read_native_chart(self.asset(), gateway)['status'], 'unclear')

    def test_empty_nonchart_and_unreadable_watermark_cannot_be_described_successfully(self):
        gateway = Mock()
        row = self.row()
        row.update(is_chart=False, watermark_present=True)
        gateway.generate_json.return_value = row
        result = _read_native_chart(self.asset(), gateway)
        self.assertEqual(result['status'], 'unclear')
        self.assertIn('保留原图', result['description'])

    def test_native_chart_uses_its_own_visual_request_and_leaves_shared_gateway_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'chart.png'
            Image.new('RGB', (10,10), 'white').save(path)
            gateway = summary.SiliconFlowGateway(summary.SummaryConfig(provider='siliconflow'), api_key='test')
            payloads = []
            class Response:
                def __enter__(self): return self
                def __exit__(self, *_): return False
                def read(inner):
                    return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(self.row())}}]}).encode()
            def request(req, timeout):
                payloads.append(json.loads(req.data))
                return Response()
            with patch.object(summary, 'urlopen', side_effect=request):
                _read_native_chart(self.asset(path), gateway)
                gateway.generate_json('原有提示', {'type':'object'}, media_assets=[self.asset(path)])
            self.assertIn('独立图像读取器', payloads[0]['messages'][0]['content'])
            self.assertEqual(payloads[1]['messages'][0]['content'], summary.SYSTEM_INSTRUCTION)
            self.assertEqual(len(payloads[0]['messages'][1]['content']), 2)
            self.assertIn('M004（生成图表）', payloads[1]['messages'][1]['content'][1]['text'])
            self.assertFalse(hasattr(gateway, '_doubao_visual_instruction'))

    def test_native_reader_result_is_not_compressed_or_leaked_into_other_image_prompts(self):
        native, ordinary = self.asset(), self.asset()
        ordinary.media_id, ordinary.label = 'M005', '普通图片'
        text, vision = Mock(), Mock()
        vision.generate_json.return_value = {'items':[{'media_id':'M005','description':'真实主体',
            'status':'described','visible_watermarks':[]}]}
        verified = {'media_id':'M004','description':'独立图例核对','status':'described','visible_watermarks':[]}
        with patch('scripts.doubao_media._read_native_chart', return_value=verified) as reader:
            result = MediaGateway(text, vision, summary.SummaryConfig()).generate_json('识别', summary.MEDIA_SCHEMA, [native, ordinary])
        reader.assert_called_once_with(native, vision)
        self.assertIn(verified, result['items'])
        self.assertNotIn('独立图例核对', vision.generate_json.call_args.args[0])


class ImageReferenceTests(unittest.TestCase):
    def sample(self, raw='附上图片 ![图](./images/a.png)', described='风景图', available=True):
        messages = [{'role':'User','content':'重新生成'}, {'role':'AI','content':raw}]
        result = {'current_state':{'completed':[{'content':'AI附图片占位','message_ids':[2]}], 'pending':[]},
            'latest_turn_grounding':{'assistant_summary':'AI附图片占位','assistant_message_ids':[2],
                'user_message_id':1,'user_text':'重新生成'},
            'media':[{'media_id':'M1','kind':'image','message_index':2,'can_reverify':available,
                      'description':described}],
            'topics':[{'summary':'AI附图片占位','source_message_ids':[1,2]}],
            'memory_items':[{'content':'AI附图片占位','message_ids':[2]}], 'processing':{}}
        return result, messages

    def test_saved_image_is_a_reference_in_overview_state_topic_and_detail(self):
        result, messages = self.sample()
        rules.guard_image_references(result, messages)
        self.assertEqual(result['latest_turn_grounding']['assistant_summary'], 'AI附图片引用')
        self.assertEqual(result['current_state']['reached_stage']['content'], 'AI附图片引用')
        self.assertEqual(result['current_state']['completed'][0]['content'], 'AI附图片引用')
        self.assertEqual(result['topics'][0]['summary'], 'AI附图片引用')
        self.assertEqual(result['memory_items'][0]['content'], 'AI附图片引用')
        self.assertEqual(len(result['processing']['doubao_image_reference_verification']), 4)
        rules.guard_image_references(result, messages)
        self.assertEqual(len(result['processing']['doubao_image_reference_verification']), 4)

    def test_literal_placeholder_and_real_placeholder_image_are_preserved(self):
        for raw, description in [('这是一张占位图片 ![图](./images/a.png)','风景图'),
                                 ('附上图片 ![图](./images/a.png)','实际是一张灰色占位图片')]:
            result, messages = self.sample(raw=raw, described=description)
            rules.guard_image_references(result, messages)
            self.assertEqual(result['latest_turn_grounding']['assistant_summary'], 'AI附图片占位')

    def test_no_local_resource_does_not_claim_saved_images(self):
        result, messages = self.sample(available=False)
        rules.guard_image_references(result, messages)
        self.assertEqual(result['latest_turn_grounding']['assistant_summary'], 'AI附图片占位')

    def test_negative_placeholder_statement_is_not_reversed(self):
        result, messages = self.sample()
        result['latest_turn_grounding']['assistant_summary'] = '这些不是图片占位'
        rules.guard_image_references(result, messages)
        self.assertEqual(result['latest_turn_grounding']['assistant_summary'], '这些不是图片占位')


if __name__ == '__main__':
    unittest.main()
