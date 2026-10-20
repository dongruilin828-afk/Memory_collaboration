"""Same-turn answer proof and all-slide visual reading, isolated to Doubao."""
import copy
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import gemini_summarizer as summary
from scripts.doubao_summary import repair_answer_bindings, reconcile_bindings, reconcile_state
from scripts.doubao_media import MediaGateway, prepare_pptx, pptx_images


class AnswerProofTests(unittest.TestCase):
    def payload(self):
        return {'memory_items': [{'content': '接受状态是q2', 'source': 'user', 'status': 'delivered',
                                 'message_ids': [1], 'evidence_quote': '接受状态是q2'}]}

    def test_paraphrase_uses_real_answer_fragment_and_survives_normalization(self):
        messages = [{'role': 'User', 'content': '翻译并完成'},
                    {'role': 'AI', 'content': r'最终 $F=\{q_2\}$，q2 是接受状态。'}]
        payload = self.payload()
        gateway = Mock()
        gateway.generate_json.return_value = {'items': [{'claim_id': 'C1', 'supported': True, 'evidence_ids': ['A2Q1']}]}
        repair_answer_bindings(payload, messages, gateway)
        memory = payload['memory_items'][0]
        self.assertEqual(memory['source'], 'assistant')
        self.assertEqual(memory['status'], 'answered')
        self.assertEqual(memory['message_ids'], [2])
        self.assertEqual(memory['evidence_quote'], messages[1]['content'])
        self.assertEqual(memory['answer_binding']['original']['original_message_ids'], [1])
        before = copy.deepcopy(memory)
        summary._reconcile_source_status(memory, messages)
        reconcile_bindings(payload, messages)
        self.assertEqual(before, memory)

    def test_wrong_turn_unknown_duplicate_and_partial_proof_stay_uncertain(self):
        messages = [{'role': 'User', 'content': '问题'}, {'role': 'AI', 'content': '本轮没有答案'},
                    {'role': 'User', 'content': '新问题'}, {'role': 'AI', 'content': 'q2 是接受状态'}]
        for entries in [
            [{'claim_id': 'C1', 'supported': True, 'evidence_ids': ['A4Q1']}],
            [{'claim_id': 'C1', 'supported': True, 'evidence_ids': ['不存在']}],
            [{'claim_id': 'C1', 'supported': False, 'evidence_ids': ['A2Q1']}],
            [{'claim_id': 'C1', 'supported': True, 'evidence_ids': ['A2Q1']}] * 2,
        ]:
            with self.subTest(entries=entries):
                payload = self.payload()
                gateway = Mock()
                gateway.generate_json.return_value = {'items': entries}
                repair_answer_bindings(payload, messages, gateway)
                self.assertEqual(payload['memory_items'][0]['source'], 'inferred')
                self.assertEqual(payload['memory_items'][0]['status'], 'uncertain')
                self.assertNotIn('A4Q1', gateway.generate_json.call_args.args[0])

    def test_more_than_four_real_fragments_are_not_arbitrarily_rejected(self):
        messages = [{'role': 'User', 'content': '问题'}, {'role': 'AI', 'content': '真实回答' * 400}]
        payload = self.payload()
        gateway = Mock()
        gateway.generate_json.return_value = {'items': [{'claim_id': 'C1', 'supported': True,
                                                       'evidence_ids': [f'A2Q{i}' for i in range(1, 6)]}]}
        repair_answer_bindings(payload, messages, gateway)
        self.assertEqual(payload['memory_items'][0]['source'], 'assistant')
        self.assertEqual(len(payload['memory_items'][0]['answer_binding']['evidence']), 5)

    def test_withheld_completion_recovers_as_ai_answer_never_user_execution(self):
        messages = [{'role': 'User', 'content': '翻译并完成'}, {'role': 'AI', 'content': '解答为42。'}]
        payload = {'current_state': {'completed': [{'content': '解答为42', 'source': 'user',
                    'status': 'delivered', 'message_ids': [1]}], 'pending': [], 'next_step': {}}}
        reconcile_state(payload, messages)
        gateway = Mock()
        gateway.generate_json.return_value = {'items': [{'claim_id': 'C1', 'supported': True, 'evidence_ids': ['A2Q1']}]}
        repair_answer_bindings(payload, messages, gateway)
        reconcile_state(payload, messages)
        claim = payload['current_state']['completed'][0]
        self.assertEqual((claim['source'], claim['status'], claim['message_ids']), ('assistant', 'answered', [2]))
        self.assertFalse(payload['processing']['unverified_completed_claims'])

    def test_ai_claim_of_user_execution_stays_attributed_and_all_evidence_is_rendered(self):
        messages = [{'role': 'User', 'content': '部署方法'}, {'role': 'AI', 'content': '用户已完成部署。'}]
        payload = self.payload()
        payload['memory_items'][0].update(content='用户已完成部署', evidence_quote='未知改写')
        gateway = Mock()
        gateway.generate_json.return_value = {'items': [{'claim_id': 'C1', 'supported': True, 'evidence_ids': ['A2Q1']}]}
        repair_answer_bindings(payload, messages, gateway)
        item = payload['memory_items'][0]
        self.assertTrue(item['content'].startswith('AI曾声称：'))
        self.assertEqual(item['status'], 'answered')
        item['answer_binding']['evidence'].append({'message_id': 2, 'quote': '补充原文'})
        rendered = '\n'.join(summary._memory_evidence_lines(item))
        self.assertEqual(rendered.count('原文证据（AI 消息 2）'), 2)
        self.assertIn('补充原文', rendered)
        self.assertIn('```text', rendered)
        detail_lines = []
        summary._render_detail_memory(detail_lines, payload)
        self.assertIn('### 回答来源复核依据', detail_lines)
        self.assertIn('补充原文', '\n'.join(detail_lines))
        self.assertEqual(summary._memory_evidence_lines({'evidence_quote': '原路径'}), ['  - 原文证据：原路径'])


class SlidesProofTests(unittest.TestCase):
    def test_all_40_pages_use_individual_visual_ids_not_sampling(self):
        text, vision = Mock(), Mock()
        def identify(prompt, schema, media_assets=None):
            self.assertEqual(len(media_assets), 1)
            self.assertNotIn('visible_watermarks', schema['properties']['items']['items']['properties'])
            view = media_assets[0]
            return {'items': [{'media_id': view.media_id, 'status': 'described',
                    'description': '图片与布局内容' + view.label}]}
        vision.generate_json.side_effect = identify
        asset = summary.MediaAsset('M001', 1, 'document', 'PPT', 'deck.pptx',
                    extracted_text='[PPTX 共40页；完整文本层]\n' + '\n'.join(f'[幻灯片{i}]\n标题{i}' for i in range(1, 41)))
        views = [summary.MediaAsset('old', 1, 'image', f'第{i}/40页', f'{i}.png') for i in range(1, 41)]
        with patch('scripts.doubao_media.pptx_images', return_value=views):
            result = MediaGateway(text, vision, summary.SummaryConfig()).generate_json('', summary.MEDIA_SCHEMA, [asset])
        item = result['items'][0]
        self.assertEqual(item['status'], 'described')
        self.assertEqual(vision.generate_json.call_count, 40)
        self.assertIn('第40/40页', item['description'])
        self.assertIn('文字层补充', item['description'])
        text.generate_json.assert_not_called()

    def test_render_failure_explicitly_keeps_only_text_as_unclear(self):
        asset = summary.MediaAsset('M001', 1, 'document', 'PPT', 'deck.pptx',
                                  extracted_text='[PPTX 共1页；完整文本层]\n[幻灯片1]\n文字')
        with patch('scripts.doubao_media.pptx_images', side_effect=RuntimeError('no renderer')):
            result = MediaGateway(Mock(), Mock(), summary.SummaryConfig()).generate_json('', summary.MEDIA_SCHEMA, [asset])
        self.assertEqual(result['items'][0]['status'], 'unclear')
        self.assertIn('PPT视觉未完成', result['items'][0]['description'])
        self.assertIn('文字', result['items'][0]['description'])

    def test_declared_slide_order_is_used_instead_of_archive_filename_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'a.pptx'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('ppt/presentation.xml', '<p:presentation xmlns:p="p" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId r:id="b"/><p:sldId r:id="a"/></p:sldIdLst><p:ext><p:sldId id="unrelated-extension"/></p:ext></p:presentation>')
                archive.writestr('ppt/_rels/presentation.xml.rels', '<Relationships><Relationship Id="a" Target="/ppt/slides/slide1.xml"/><Relationship Id="b" Target="slides/slide2.xml"/></Relationships>')
                archive.writestr('ppt/slides/slide1.xml', '<root xmlns:a="a"><a:t>后页</a:t></root>')
                archive.writestr('ppt/slides/slide2.xml', '<root xmlns:a="a"><a:t>前页</a:t></root>')
            asset = summary.MediaAsset('M001', 1, 'document', 'PPT', str(path), local_path=path)
            prepare_pptx(asset, summary.SummaryConfig())
            self.assertIn('[幻灯片1]\n前页\n[幻灯片2]\n后页', asset.extracted_text)


if __name__ == '__main__':
    unittest.main()
