"""Task continuity, role-safe excerpts and isolated literal OCR."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
from scripts import doubao_summary as rules, gemini_summarizer as summary
from scripts.doubao_media import _read_diagram, DIAGRAM_OCR_MODEL, MediaGateway
from scripts.summary_grounding import _plain


class TaskTopicsTests(unittest.TestCase):
    def conversation(self):
        users = ['生成一张英文招新流程图，保留报名和面试步骤', '去掉图中的16：9', '将比例改为9：16', '重新生成', '重新生成']
        return [m for text in users for m in ({'role':'User','content':text}, {'role':'AI','content':'将生成4张英文图。'})]

    def topics(self, messages):
        return [{'title':'初始需求：英文招新流程图' if i==0 else ('用户要求' if m['role']=='User' else 'AI 交付'),
                 'summary':'阶段说明'+str(i), 'memory_ids':['M'+str(i+1)], 'source_message_ids':[i+1]}
                for i,m in enumerate(messages)]

    def test_continuous_edits_merge_all_voices_without_losing_memories_or_constraints(self):
        messages = self.conversation()
        result = {'topics':self.topics(messages)}
        rules.merge_continuation_topics(result,messages)
        self.assertEqual(len(result['topics']),1)
        topic=result['topics'][0]
        self.assertEqual(topic['memory_ids'],['M'+str(i) for i in range(1,11)])
        self.assertEqual(topic['source_message_ids'],list(range(1,11)))
        self.assertIn('9：16',topic['summary'])
        self.assertIn('2次',topic['summary'])
        for evidence in topic['source_review']['evidence']:
            self.assertIn(evidence['quote'],_plain(messages[evidence['message_id']-1]['content']))
        before=copy.deepcopy(result)
        rules.repair_topic_roles(result,messages)
        rules.merge_continuation_topics(result,messages)
        self.assertEqual(result,before)

    def test_a_new_explicit_task_and_multi_intent_root_are_not_merged(self):
        messages=self.conversation()+[{'role':'User','content':'解释量子纠缠'}, {'role':'AI','content':'另一项解释'}]
        result={'topics':self.topics(messages)}
        rules.merge_continuation_topics(result,messages)
        self.assertEqual(len(result['topics']),3)
        self.assertNotIn(11,result['topics'][0]['source_message_ids'])
        messages=[{'role':'User','content':'画一张流程图，另外解释算法复杂度'}, {'role':'AI','content':'两个独立问题的回答'},
                  {'role':'User','content':'继续'}, {'role':'AI','content':'继续回答'}]
        result={'topics':self.topics(messages)}
        rules.merge_continuation_topics(result,messages)
        self.assertEqual(len(result['topics']),4)

    def test_an_already_single_model_topic_preserves_every_followup(self):
        messages=self.conversation()
        result={'topics':[{'title':'英文流程图','summary':'模型只给一个主题','memory_ids':['M1'],
                           'source_message_ids':list(range(1,len(messages)+1))}]}
        rules.merge_continuation_topics(result,messages)
        self.assertEqual(result['topics'][0]['task_user_message_ids'],[1,3,5,7,9])
        self.assertIn('2次',result['topics'][0]['summary'])

    def test_user_claim_evidence_budget_does_not_get_filled_by_adjacent_ai_replies(self):
        messages=[m for _ in range(5) for m in ({'role':'User','content':'重新生成'},
                    {'role':'AI','content':'我将重新生成4张9:16比例流程图。'*100})]
        item={'content':'用户连续五次回复重新生成','source':'user','message_ids':[1,3,5,7,9]}
        evidence=rules._review_evidence(item,messages,[])
        self.assertEqual({e['message_id'] for e in evidence},{1,3,5,7,9})
        self.assertEqual({e['source'] for e in evidence},{'user'})

    def review(self,title,answer_source,answer_evidence):
        messages=[{'role':'User','content':'重新生成'}, {'role':'AI','content':'我将重新生成4张9:16英文图。'}]
        result={'topics':[{'title':title,'summary':'候选','source_message_ids':[1,2],'memory_ids':[]}],
                'current_state':{'completed':[],'pending':[],'next_step':{}},'media':[]}
        gateway=Mock()
        gateway.generate_json.return_value={'items':[{'key':'topic0','decision':'keep','content':'候选',
            'source':answer_source,'status':'answered','evidence_ids':[answer_evidence]}]}
        rules.review_summary(result,messages,gateway)
        return result['topics'][0]

    def test_user_title_fallback_does_not_borrow_assistant_words(self):
        for title in ('用户第二次要求重新生成','用户要求AI重新生成'):
            topic=self.review(title,'assistant','S2P1')
            self.assertIn('用户原文',topic['summary'])
            self.assertNotIn('我将',topic['summary'])
            self.assertEqual({e['source'] for e in topic['source_review']['evidence']},{'user'})

    def test_assistant_title_fallback_does_not_borrow_user_words(self):
        topic=self.review('AI 首次交付','user','S1P1')
        self.assertIn('AI原文',topic['summary'])
        self.assertEqual({e['source'] for e in topic['source_review']['evidence']},{'assistant'})

    def test_saved_wrong_role_excerpt_is_repaired_with_original_evidence_retained(self):
        messages=[{'role':'User','content':'重新生成'}, {'role':'AI','content':'我将生成4张图'}]
        topic={'title':'用户第三次要求重新生成','summary':'我将生成4张图','source_message_ids':[1,2],
               'source_review':{'version':2,'evidence':[{'source':'assistant','message_id':2,'quote':'我将生成4张图'}]}}
        result={'topics':[topic]}
        rules.repair_topic_roles(result,messages)
        self.assertIn('用户原文',topic['summary'])
        self.assertNotIn('我将生成',topic['summary'])
        self.assertEqual(topic['topic_role_repair']['original_summary'],'我将生成4张图')

    def test_english_visual_design_is_not_split_into_language_memory_fragments(self):
        messages=[{'role':'User','content':'生成一张英文招新流程图'}, {'role':'AI','content':'提供招新流程图'}]
        memories=[{'memory_id':'M'+str(i),'topic':'小节'+str(i),'content':'设计细节'+str(i),
                   'source':'assistant','memory_type':'action','message_ids':[2]} for i in range(20)]
        topic={'title':'英文招新流程图','summary':'设计任务','memory_ids':[m['memory_id'] for m in memories],
               'source_message_ids':[1,2]}
        result=summary._normalize_topic_assignments([topic],memories,2,messages=messages,source_platform='豆包')
        self.assertEqual(len(result),1)
        self.assertEqual(len(result[0]['memory_ids']),20)
        self.assertEqual(result[0]['title'],'英文招新流程图')


class LiteralReaderTests(unittest.TestCase):
    def row(self, **changes):
        row={'text_lines':['Filld our weroonwork form','Add our rewechat work account'],
             'small_labels':['SpranAno','Alto','Aoto','Toner','Bass'],
             'unreadable_fragments':[], 'source_anomalies':['Filld','应为正确拼写',"a pesition 疑似 a position 拼写错误"]}
        row.update(changes)
        return row

    def run_reader(self, row):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'diagram.png';Image.new('RGB',(120,300),'white').save(path)
        asset=summary.MediaAsset('M1',2,'image','流程图','./diagram.png',local_path=path,mime_type='image/png')
        gateway=summary.SiliconFlowGateway(summary.SummaryConfig(provider='siliconflow',model='Qwen/Qwen3-8B'),api_key='test')
        payloads=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_):return False
            def read(self):return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(row)}}]}).encode()
        def request(req, timeout):
            payloads.append(json.loads(req.data));return Response()
        with patch.object(summary,'urlopen',side_effect=request):
            result=_read_diagram(asset,gateway,Path(temp.name))
            gateway.generate_json('原有普通图片',{'type':'object'},[asset])
            gateway.generate_json('原有文字',{'type':'object'})
        return result,payloads,gateway

    def test_legible_misspellings_are_literal_and_other_requests_keep_old_models(self):
        result,payloads,gateway=self.run_reader(self.row())
        self.assertEqual(result['status'],'described')
        self.assertIn('rewechat',result['description'])
        self.assertIn('Filld',result['description'])
        self.assertNotIn('应为正确拼写',result['description'])
        self.assertNotIn('疑似 a position',result['description'])
        self.assertTrue(all(t in result['description'] for t in ('SpranAno','Alto','Aoto','Toner','Bass')))
        self.assertEqual([p['model'] for p in payloads],[DIAGRAM_OCR_MODEL,summary.SILICONFLOW_VISION_MODEL,'Qwen/Qwen3-8B'])
        self.assertFalse(payloads[0]['enable_thinking'])
        self.assertEqual(payloads[1]['messages'][0]['content'],summary.SYSTEM_INSTRUCTION)
        self.assertFalse(hasattr(gateway,'_doubao_visual_model'))
        self.assertNotIn('visible_watermarks',result)

    def test_unreadable_core_is_still_unclear_and_local_views_do_not_add_steps(self):
        result,payloads,_=self.run_reader(self.row(text_lines=['3. Piclk out','[无法辨认]'],
                         unreadable_fragments=['右侧节点被裁切']))
        self.assertEqual(result['status'],'unclear')
        self.assertIn('Piclk',result['description'])
        self.assertIn('右侧节点被裁切',result['description'])
        self.assertEqual(len(payloads),6)

    def test_literal_reader_does_not_erase_the_existing_visible_watermark(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'image.png';Image.new('RGB',(10,10),'white').save(path)
            asset=summary.MediaAsset('M1',2,'image','图','./image.png',local_path=path,mime_type='image/png')
            vision=Mock();vision.generate_json.return_value={'items':[{'media_id':'M1','description':'流程图',
                'status':'described','visible_watermarks':['AI生成']}]}
            with patch('scripts.doubao_media._read_diagram',return_value={'status':'described','description':'逐字内容'}):
                result=MediaGateway(Mock(),vision,summary.SummaryConfig()).generate_json('读取',summary.MEDIA_SCHEMA,[asset])
            self.assertEqual(result['items'][0]['visible_watermarks'],['AI生成'])
            self.assertIn('【可见标注：AI生成】',result['items'][0]['description'])

    def test_small_flowchart_keeps_overview_and_watermark_without_fine_ocr(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'image.png';Image.new('RGB',(235,418),'white').save(path)
            asset=summary.MediaAsset('M1',2,'image','图','./image.png',local_path=path,mime_type='image/png')
            vision=Mock();vision.generate_json.return_value={'items':[{'media_id':'M1','description':'招新流程图',
                'status':'described','visible_watermarks':['AI生成']}]}
            with patch('scripts.doubao_media._read_diagram') as reader:
                result=MediaGateway(Mock(),vision,summary.SummaryConfig()).generate_json('读取',summary.MEDIA_SCHEMA,[asset])
            reader.assert_not_called()
            self.assertEqual(result['items'][0]['status'],'unclear')
            self.assertIn('235×418',result['items'][0]['description'])
            self.assertIn('不能视为精确转录',result['items'][0]['description'])
            self.assertIn('招新流程图',result['items'][0]['description'])
            self.assertIn('【可见标注：AI生成】',result['items'][0]['description'])

    def test_failed_local_read_cannot_discard_the_successful_literal_full_image(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'image.png';Image.new('RGB',(120,300),'white').save(path)
            asset=summary.MediaAsset('M1',2,'image','图','./image.png',local_path=path,mime_type='image/png')
            gateway=summary.SiliconFlowGateway(summary.SummaryConfig(provider='siliconflow'),api_key='test')
            def respond(_self,prompt,schema,media_assets):
                if media_assets[0].media_id.endswith('L1'):
                    raise summary.GeminiSummaryError('局部请求失败')
                return self.row(text_lines=['a pesition'],unreadable_fragments=['右侧裁切'])
            with patch.object(summary.SiliconFlowGateway,'generate_json',autospec=True,side_effect=respond), \
                 patch('scripts.doubao_media._read_diagram_legacy') as legacy:
                result=_read_diagram(asset,gateway,Path(temp))
            legacy.assert_not_called()
            self.assertIn('全图原字形：a pesition',result['description'])
            self.assertIn('局部1读取未完成',result['description'])
            self.assertEqual(result['status'],'unclear')

    def test_large_anomalous_image_uses_all_regions_even_if_full_read_claims_success(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'image.png';Image.new('RGB',(1300,2400),'white').save(path)
            asset=summary.MediaAsset('M1',2,'image','图','./image.png',local_path=path,mime_type='image/png')
            gateway=summary.SiliconFlowGateway(summary.SummaryConfig(provider='siliconflow'),api_key='test')
            def respond(_self,prompt,schema,media_assets):
                local='L' in media_assets[0].media_id
                return self.row(text_lines=['Add our rewechat work account' if local else 'Add our rewecchat work account'],
                                source_anomalies=['rewechat' if local else 'rewecchat'])
            with patch.object(summary.SiliconFlowGateway,'generate_json',autospec=True,side_effect=respond) as reader:
                result=_read_diagram(asset,gateway,Path(temp))
            self.assertEqual(reader.call_count,4)
            self.assertIn('Add our rewechat work account',result['description'])
            self.assertIn('全图原字形：Add our rewecchat work account',result['description'])
            self.assertIn('不能认定为精确转录',result['description'])
            self.assertNotIn('仍无法辨认的位置',result['description'])
            self.assertIn('分歧不等于原图不可辨认',result['description'])
            self.assertEqual(result['status'],'unclear')

    def test_partial_full_read_keeps_correct_fragments_when_regions_disagree(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'image.png';Image.new('RGB',(1300,2400),'white').save(path)
            asset=summary.MediaAsset('M1',2,'image','图','./image.png',local_path=path,mime_type='image/png')
            gateway=summary.SiliconFlowGateway(summary.SummaryConfig(provider='siliconflow'),api_key='test')
            def respond(_self,prompt,schema,media_assets):
                local='L' in media_assets[0].media_id
                return self.row(text_lines=['a position' if local else 'a pesition'],
                                unreadable_fragments=[] if local else ['右侧遮挡'])
            with patch.object(summary.SiliconFlowGateway,'generate_json',autospec=True,side_effect=respond):
                result=_read_diagram(asset,gateway,Path(temp))
            self.assertIn('全图原字形：a pesition',result['description'])
            self.assertEqual(result['status'],'unclear')


if __name__=='__main__':unittest.main()
