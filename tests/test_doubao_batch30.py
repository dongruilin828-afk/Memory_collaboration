"""Doubao batch 30: source fidelity and summary evidence regressions."""
import unittest
import io
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import copy
import json
from bs4 import BeautifulSoup
from scripts.providers import doubao
from scripts.doubao_artifacts import slide_entries, save_slides, valid_pptx
from scripts import gemini_summarizer as summary
from scripts.summary_grounding import ground_latest_turn, _quantity_errors
from scripts.simple_summarizer import generate_simple_overview
from scripts.doubao_summary import is_language_memory, reconcile_state, reconcile_bindings
from scripts.doubao_media import prepare_pptx, MediaGateway


def parse(html, mapping=None):
    return doubao.parse_messages(BeautifulSoup(html, 'html.parser'), mapping or {})


class CaptureFidelityTests(unittest.TestCase):
    def test_original_uses_site_signature_and_aliases_the_displayed_thumbnail(self):
        thumb='https://p3.byteimg.com/rc_gen_image/one.jpeg~tplv-x-downsize_watermark_1.png?sig=thumb'
        full='https://p3.byteimg.com/rc_gen_image/one.jpeg~tplv-x-image_pre_watermark_1.png?sig=original&x=2'
        sources=doubao.original_generated_image_sources('"'+full.replace('&','&amp;')+'"')
        self.assertEqual(sources,[full])
        selected=doubao.prefer_original_generated_images([thumb,*sources],preferred_sources=[thumb])
        self.assertEqual(selected,[full])
        mapping={full:'./images/full.png'}
        doubao.alias_generated_images(mapping,[thumb])
        self.assertEqual(mapping[thumb],'./images/full.png')

    def test_attachment_subtitle_is_removed_but_user_type_words_remain(self):
        for kind, suffix in [('PPT','pptx'),('PDF','pdf'),('Excel','xlsx'),('Word','docx')]:
            with self.subTest(kind=kind):
                html = f'''<div class="message-item justify-end"><div data-testid="attachment_file_item">
                  <div data-testid="message_nested_content_file_name" class="file-name">demo.{suffix}</div>
                  <div data-testid="message_nested_content_file_subtitle">{kind}</div></div>
                  <p>{kind}</p><p>请解释该文件。</p></div>'''
                message = parse(html,{f'demo.{suffix}':f'./documents/demo.{suffix}'})[0]['content']
                self.assertEqual(message.count(kind),1)
                self.assertIn(f'[📄 demo.{suffix}]',message)
                self.assertIn('请解释该文件。',message)

    def test_attachment_only_type_does_not_split_a_question(self):
        html = '''<div class="message-item justify-end"><div data-testid="attachment_file_item">
          <span class="file-name">demo.pptx</span><span data-testid="message_nested_content_file_subtitle">PPT</span>
          </div></div><div class="message-item justify-end">请解释。</div><div class="message-item">回答</div>'''
        messages = parse(html,{'demo.pptx':'./documents/demo.pptx'})
        self.assertEqual([m['role'] for m in messages],['User','AI'])
        self.assertNotIn('\nPPT',messages[0]['content'])

    def test_formula_uses_source_even_when_rendered_text_is_empty_or_reversed(self):
        html = r'''<div class="message-item"><p>磁场<span copy-text="\(B_0=\dfrac{E_0}{c}\)">B0=cE0</span>，
          纵坐标<span copy-text="E_y、B_z"></span>。</p>
          <div class="math-display" copy-text="\[\begin{matrix}a&amp;b\end{matrix}\]">ab</div></div>'''
        text = parse(html)[0]['content']
        self.assertIn(r'$B_0=\dfrac{E_0}{c}$',text)
        self.assertIn('$E_y、B_z$',text)
        self.assertIn('$$',text)
        self.assertNotIn('B0=cE0',text)

    def test_code_toolbar_is_not_body_but_language_and_indentation_survive(self):
        html = '''<div class="message-item"><div class="code-block-element-x">
          <div data-copy-ignore="true">python <span>运行</span></div>
          <pre class="language-python"><code>if True:\n    print("运行")\n</code></pre></div></div>'''
        text = parse(html)[0]['content']
        self.assertIn('```python',text)
        self.assertEqual(text.count('运行'),1)
        self.assertIn('    print("运行")',text)

    def test_generated_slides_has_file_link_or_missing_marker(self):
        html = '''<div class="message-item"><div data-message-id="123"><p>交付完成。</p>
          <div data-testid="slides-product-card"><div class="card-title-text-x">演示文稿</div>
          <span>创建时间：10-06</span></div></div></div>'''
        missing = parse(html)[0]['content']
        self.assertIn('AI生成文档未下载',missing)
        self.assertIn('演示文稿.pptx',missing)
        saved = parse(html,{'doubao-ai-slides-message:123':'./documents/slides.pptx'})[0]['content']
        self.assertIn('./documents/slides.pptx',saved)
        self.assertNotIn('创建时间',saved)

    def test_anonymous_slides_card_also_gets_a_missing_marker(self):
        html='''<div class="message-item"><div data-message-id="123">
          <div data-office-artifact-resource-type="9"><div class="title-x">报告</div>
          <div>创建时间：10-06</div></div></div></div>'''
        self.assertIn('报告.pptx',parse(html)[0]['content'])
        self.assertNotIn('创建时间',parse(html)[0]['content'])
        self.assertEqual(slide_entries(html,'https://www.doubao.com/chat/123')[0]['message_id'],'123')


class SlidesDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_download_requires_actual_presentation_and_message_scope(self):
        for valid in (True,False):
            with self.subTest(valid=valid),tempfile.TemporaryDirectory() as tmp:
                stream=io.BytesIO()
                with zipfile.ZipFile(stream,'w') as archive:
                    archive.writestr('[Content_Types].xml','<Types/>')
                    archive.writestr('ppt/slides/slide1.xml','<slide/>')
                body=stream.getvalue() if valid else b'<html>preview</html>'
                path=Path(tmp)/'native.download';path.write_bytes(body)
                page=MagicMock();page.url='https://www.doubao.com/chat/123';page.frames=[]
                node=MagicMock();node.first=node;node.locator.return_value=node
                node.count=AsyncMock(return_value=1);node.scroll_into_view_if_needed=AsyncMock()
                page.locator.return_value=node;page.keyboard.press=AsyncMock();page.wait_for_timeout=AsyncMock()
                frame=MagicMock();frame.url='https://www.doubao.com/partner/ccm-slides-v3/ExpectedToken123'
                button=MagicMock();button.is_visible=AsyncMock(return_value=False);button.click=AsyncMock()
                frame.get_by_text.return_value=button;frame.get_by_role.return_value=button
                async def open_card(**_):page.frames=[frame]
                node.click=AsyncMock(side_effect=open_card)
                download=SimpleNamespace(path=AsyncMock(return_value=str(path)))
                class Event:
                    async def __aenter__(self):return SimpleNamespace(value=AsyncMock(return_value=download)())
                    async def __aexit__(self,*_):return False
                page.expect_download.side_effect=lambda **_:Event()
                warnings=[]
                mapping=await save_slides(page,[{'title':'报告','message_id':'777','resource_id':'ExpectedToken123','conversation_id':'123'}],
                    Path(tmp)/'documents','./documents',warnings)
                if valid:
                    self.assertTrue(valid_pptx((Path(tmp)/'documents/报告.pptx').read_bytes()))
                    self.assertIn('doubao-ai-slides-message:777',mapping)
                    self.assertFalse(warnings)
                else:
                    self.assertFalse(mapping);self.assertTrue(warnings)
                page.locator.assert_called_with('[data-message-id="777"]')


class SummaryRegressionTests(unittest.TestCase):
    def test_presentation_quote_restored_to_unique_exact_source(self):
        messages=[{'role':'User','content':'如何调用'}, {'role':'AI','content':'调用 `read(a, b)` 后查看结果。'}]
        gateway=Mock()
        gateway.generate_json.return_value={'assistant_summary':'说明调用方法。','evidence':[{'message_id':2,'quote':'调用 read(a,b) 后查看结果'}]}
        grounded=ground_latest_turn(messages,gateway,source_platform='豆包')
        self.assertEqual(grounded['evidence'][0]['quote'],'调用 `read(a, b)` 后查看结果')
        self.assertEqual(grounded['verification']['attempts'],1)
        with self.assertRaises(ValueError):
            ground_latest_turn(messages,gateway,source_platform='ChatGPT')

    def test_source_fragment_id_restores_actual_text_without_model_copying_code(self):
        messages=[{'role':'User','content':'如何调用'}, {'role':'AI','content':'调用 `read(a, b)` 后查看结果。'}]
        gateway=Mock()
        gateway.generate_json.return_value={'assistant_summary':'说明调用方法。','evidence':[{'message_id':2,'quote':'A2Q1'}]}
        grounded=ground_latest_turn(messages,gateway,source_platform='豆包')
        self.assertEqual(grounded['assistant_summary'],'说明调用方法。')
        self.assertEqual(grounded['evidence'][0]['quote'],messages[1]['content'])
        self.assertEqual(grounded['verification']['method'],'indexed_source_quotes')

    def test_fragment_id_cannot_be_bound_to_another_answer(self):
        messages=[{'role':'User','content':'问题'}, {'role':'AI','content':'第一条回答'}, {'role':'AI','content':'第二条回答'}]
        gateway=Mock()
        gateway.generate_json.return_value={'assistant_summary':'说明两点。','evidence':[{'message_id':2,'quote':'A3Q1'},{'message_id':3,'quote':'A3Q1'}]}
        grounded=ground_latest_turn(messages,gateway,source_platform='豆包')
        self.assertEqual(grounded['verification']['method'],'exact_extract_fallback')
        self.assertEqual(grounded['evidence'][0]['quote'],'第一条回答')

    def test_rejected_quote_retry_explicitly_selects_real_fragment_ids(self):
        messages=[{'role':'User','content':'问题'},{'role':'AI','content':'完整的真实回答，不含省略。'}]
        gateway=Mock()
        gateway.generate_json.side_effect=[
            {'assistant_summary':'解释实际问题。','evidence':[{'message_id':2,'quote':'真实...回答'}]},
            {'assistant_summary':'解释实际问题。','evidence':[{'message_id':2,'quote':'A2Q1'}]},
        ]
        grounded=ground_latest_turn(messages,gateway,source_platform='豆包')
        prompt=gateway.generate_json.call_args.args[0]
        self.assertIn('本次quote只填下面的原文片段编号',prompt)
        self.assertIn('合法编号：A2Q1',prompt)
        self.assertEqual(grounded['verification']['attempts'],2)
        self.assertEqual(grounded['evidence'][0]['quote'],messages[1]['content'])

    def test_bad_quote_is_never_accepted_and_fallback_is_source_extract(self):
        messages=[{'role':'User','content':'新问题'},{'role':'AI','content':'这是准确的实际回复。'}]
        gateway=Mock()
        gateway.generate_json.return_value={'assistant_summary':'编造的回答','evidence':[{'message_id':2,'quote':'准确...回复'}]}
        grounded=ground_latest_turn(messages,gateway,source_platform='豆包')
        self.assertEqual(grounded['verification']['method'],'exact_extract_fallback')
        self.assertIn('准确...回复',gateway.generate_json.call_args.args[0])
        self.assertNotIn('编造的回答',grounded['assistant_summary'])
        self.assertIn(grounded['evidence'][0]['quote'],messages[1]['content'])

    def test_quantity_is_not_proved_by_an_unrelated_real_quote(self):
        raw='```text\n'+'\n\n'.join(f'Principle {chr(65+i)} is good.\n原则翻译。' for i in range(19))+'\n```'
        self.assertTrue(_quantity_errors('提供14条原则。',{2:raw}))
        self.assertFalse(_quantity_errors('提供19条原则。',{2:raw}))

    def test_extract_fallback_does_not_break_code_or_quote_delimiters(self):
        gateway=Mock()
        gateway.generate_json.return_value={'assistant_summary':'错误','evidence':[{'message_id':2,'quote':'编造'}]}
        messages=[{'role':'User','content':'说明代码'},{'role':'AI','content':'```python\nprint(“很长的文本'+('x'*200)+'”)\n```'}]
        grounded=ground_latest_turn(messages,gateway,source_platform='豆包')
        result={'conversation':{},'current_state':{},'topics':[],'latest_turn_grounding':grounded}
        self.assertIn('回复摘录',generate_simple_overview(result,messages,gateway,source_platform='豆包'))
        self.assertIn(grounded['evidence'][0]['quote'],messages[1]['content'].replace('\n',' '))

    def test_simple_current_turn_ignores_old_forecast(self):
        result={'conversation':{},'current_state':{},'topics':[{'summary':'预测20度用电量。','source_message_ids':[1,2]}],
                'latest_turn_grounding':{'user_message_id':3,'user_text':'indent','assistant_message_ids':[4],'assistant_summary':'解释缩进。'}}
        gateway=Mock()
        self.assertIn('解释缩进',generate_simple_overview(result,[],gateway,source_platform='豆包'))
        gateway.generate_json.assert_not_called()

    def test_language_membership_uses_actual_query(self):
        for query,kind,expected in [('你支持上传视频吗','user_condition',False),('阻力是速度三次方不是时间三次方','correction',False),
                                    ('vivo是什么意思','learning_point',True),('bytecode','learning_point',True)]:
            item={'memory_id':'m','memory_type':kind,'source':'user','topic':'用户询问','content':query,'message_ids':[1]}
            self.assertEqual(is_language_memory(item,[{'role':'User','content':query}]),expected)

    def test_topic_remainder_rebuilt_after_membership_changes(self):
        messages=[{'role':'User','content':'bytecode'},{'role':'AI','content':'字节码'},
                  {'role':'User','content':'解释缩进机制'},{'role':'AI','content':'缩进定义语句块'}]
        memories=[{'memory_id':'a','message_ids':[2],'memory_type':'learning_point','content':'bytecode是字节码'},
                  {'memory_id':'b','message_ids':[4],'memory_type':'learning_point','content':'缩进定义语句块'}]
        topics=[{'topic_id':'t1','title':'编程术语','summary':'bytecode和缩进','memory_ids':['a','b']},
                {'topic_id':'t2','title':'字节码','summary':'字节码','memory_ids':['a']}]
        result=summary._merge_language_learning_topics(topics,memories,messages,source_platform='豆包')
        remainder=next(t for t in result if t['memory_ids']==['b'])
        self.assertNotIn('bytecode',remainder['summary'])
        self.assertIn('缩进',remainder['summary'])

    def test_state_ledger_and_completed_old_next_step(self):
        result={'media':[{'media_id':'M001','message_index':2,'status':'described','can_reverify':True,'access_status':'available_local'}],
                'current_state':{'completed':[{'content':'AI曾描述图片，但该媒体已失效，无法重新验证。','message_ids':[2]}],
                   'last_user_message_id':3,'last_user_turn_answered':True,'pending':[],
                   'next_step':{'content':'已交付视频','source':'assistant','status':'delivered','message_ids':[2]}}}
        reconcile_state(result)
        self.assertNotIn('失效',result['current_state']['completed'][0]['content'])
        self.assertIn('可重新验证',result['current_state']['completed'][0]['content'])
        self.assertEqual(result['current_state']['next_step']['status'],'uncertain')
        result['current_state']['pending']=[{'content':'还需执行','source':'user','status':'unresolved','message_ids':[3]}]
        result['current_state']['next_step']={'content':'执行修复','source':'user','status':'unresolved','message_ids':[3]}
        reconcile_state(result)
        self.assertEqual(result['current_state']['next_step']['status'],'unresolved')

    def test_transient_batch_media_error_retries_each_asset_once(self):
        gateway=Mock()
        gateway.generate_json.side_effect=[summary.GeminiSummaryError('HTTP429'),
            {'items':[{'media_id':'M001','status':'described','description':'成功读到正文'}]}]
        asset=summary.MediaAsset('M001',1,'document','文件','a.txt',status='ready',extracted_text='正文')
        warnings=summary.describe_media([asset],gateway,summary.SummaryConfig(),lambda _:None,retry_failed=True)
        self.assertFalse(warnings);self.assertEqual(asset.status,'described')
        self.assertEqual(gateway.generate_json.call_count,2)

    def test_explicit_ai_delivery_is_bound_to_answers_and_courtesy_is_not_next_step(self):
        result={'media':[],'current_state':{'completed':[{'content':'AI已给出解答','source':'user','status':'delivered','message_ids':[1,3]}],
            'pending':[],'last_user_message_id':3,'last_user_turn_answered':True,
            'next_step':{'content':'是否需要我继续下一题','source':'assistant','status':'suggested','message_ids':[4]}}}
        messages=[{'role':'User','content':'问题一'},{'role':'AI','content':'解答一'},
                  {'role':'User','content':'问题二'},{'role':'AI','content':'解答二。是否需要我继续下一题'}]
        reconcile_state(result,messages)
        claim=result['current_state']['completed'][0]
        self.assertEqual(claim['source'],'assistant');self.assertEqual(claim['message_ids'],[2,4])
        self.assertEqual(result['current_state']['next_step']['content'],'无明确待办事项')

    def test_answer_wrongly_bound_to_user_uses_unique_real_quote(self):
        messages=[{'role':'User','content':'请计算'},{'role':'AI','content':'总分为31。'}]
        payload={'memory_items':[{'source':'user','status':'delivered','message_ids':[1],'evidence_quote':'总分为31','content':'总分为31'}]}
        reconcile_bindings(payload,messages)
        self.assertEqual(payload['memory_items'][0]['source'],'assistant')
        self.assertEqual(payload['memory_items'][0]['message_ids'],[2])

    def test_unverified_paraphrase_is_not_guessed_into_user_or_ai_fact(self):
        messages=[{'role':'User','content':'请计算'},{'role':'AI','content':'$L^2=\\{00,001\\}$'}]
        payload={'memory_items':[{'source':'user','status':'delivered','message_ids':[1],'evidence_quote':'L²={00,001}','content':'L²={00,001}'}]}
        reconcile_bindings(payload,messages)
        self.assertEqual(payload['memory_items'][0]['source'],'inferred')
        self.assertEqual(payload['memory_items'][0]['status'],'uncertain')
        self.assertEqual(payload['memory_items'][0]['content'],'L²={00,001}')

    def test_uncertain_binding_survives_role_reconciliation_during_rendering(self):
        messages=[{'role':'User','content':'请计算'},{'role':'AI','content':'实际回答'}]
        payload={'memory_items':[{'source':'user','status':'delivered','message_ids':[1],'evidence_quote':'改写过的片段'}]}
        reconcile_bindings(payload,messages)
        payload['memory_items'][0]=summary._reconcile_source_status(payload['memory_items'][0],messages)
        reconcile_bindings(payload,messages)
        self.assertEqual(payload['memory_items'][0]['source'],'inferred')
        self.assertEqual(payload['memory_items'][0]['status'],'uncertain')

    def test_user_delivery_requires_user_text_and_uncertain_completed_is_preserved_as_evidence(self):
        messages=[{'role':'User','content':'翻译并完成'},{'role':'AI','content':'已解答。'}]
        claim={'content':'计算题解答完成','source':'user','status':'delivered','message_ids':[1]}
        result={'current_state':{'completed':[claim],'pending':[],'next_step':{}}}
        reconcile_state(result,messages)
        self.assertEqual(result['current_state']['completed'],[])
        self.assertEqual(result['processing']['unverified_completed_claims'],[claim])
        actual=[{'role':'User','content':'我已完成部署'},{'role':'AI','content':'好的'}]
        payload={'memory_items':[{'source':'user','status':'delivered','message_ids':[1],'evidence_quote':'我已完成部署'}]}
        reconcile_bindings(payload,actual)
        self.assertEqual(payload['memory_items'][0]['source'],'user')

    def test_existing_fallback_display_is_repaired_by_core_normalization(self):
        from scripts.summary_grounding import repair_extract_display
        grounded={'assistant_summary':'坏的旧展示','evidence':[{'message_id':2,'quote':'代码 `open_file'}],
                  'verification':{'method':'exact_extract_fallback'}}
        repair_extract_display(grounded)
        self.assertNotIn('`',grounded['assistant_summary'])
        self.assertEqual(grounded['evidence'][0]['quote'],'代码 `open_file')

    def test_ai_claim_cannot_become_user_execution_confirmation(self):
        claim={'content':'用户已完成部署','source':'assistant','status':'delivered','message_ids':[2]}
        result={'current_state':{'completed':[claim],'pending':[],'next_step':{}}}
        reconcile_state(result,[{'role':'User','content':'请提供部署方法'},{'role':'AI','content':'部署方法如下'}])
        self.assertEqual(claim['source'],'assistant')
        self.assertEqual(claim['status'],'answered')
        self.assertTrue(claim['content'].startswith('AI曾声称'))

    def test_ppt_retains_each_page_text_as_explicit_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'slides.pptx'
            with zipfile.ZipFile(path,'w') as archive:
                for i in range(1,22):
                    archive.writestr(f'ppt/slides/slide{i}.xml',f'<root xmlns:a="a"><a:t>第{i}页独立正文，不是模板。</a:t></root>')
            asset=summary.MediaAsset('M001',1,'document','slides','slides.pptx',local_path=path)
            prepare_pptx(asset,summary.SummaryConfig())
            self.assertIn('[幻灯片21]',asset.extracted_text)
            text=Mock()
            def identify(prompt,schema,media_assets=None):
                data=json.loads(prompt.split('\n',1)[1])
                return {'items':[{'media_id':item['media_id'],'description':item['text'],'quote':item['text'],'status':'described'} for item in data]}
            text.generate_json.side_effect=identify
            with patch('scripts.doubao_media.pptx_images', side_effect=RuntimeError('no renderer')):
                result=MediaGateway(text,None,summary.SummaryConfig()).generate_json('',summary.MEDIA_SCHEMA,[asset])
            description=result['items'][0]['description']
            self.assertIn('第21页',description);self.assertIn('第11页',description)
            self.assertEqual(result['items'][0]['status'],'unclear')
            self.assertIn('PPT视觉未完成',description)
            text.generate_json.assert_not_called()


if __name__=='__main__':
    unittest.main()
