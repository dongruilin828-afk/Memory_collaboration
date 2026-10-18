"""ChatGPT historical claims must match the file, turn and actual action."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from scripts import gemini_summarizer as summary
from scripts.chatgpt_history import (
    HISTORY_SCHEMA, REVIEW_SCHEMA, HistoryEvidenceError, build_evidence,
    generate_chunk, review_records, validate_memories,
)


def asset(media_id="M001", message_index=1, name="data.csv"):
    return SimpleNamespace(media_id=media_id, message_index=message_index, label=name,
        reference="./documents/"+name, kind="document", source_role="user",
        status="described", description="该CSV包含时间和湿度数据，数值非空。")


def memory(turn=1, ids=None, media_ids=None, source="assistant", text="AI确认收到CSV并提供分析选项。", quote="我可以分析CSV", kind="message", ref="2"):
    return {"topic": "附件处理", "memory_type": "fact", "content": text, "source": source,
            "status": "delivered" if source=="assistant" else "confirmed", "message_ids": ids or [2],
            "evidence_quote": quote, "turn_user_id": turn, "media_ids": ["M001"] if media_ids is None else media_ids,
            "evidence": [{"kind": kind, "id": ref, "quote": quote}]}


def chunk_fixture(messages):
    """A truthful non-attachment fixture for the existing end-to-end bundle test."""
    from tests.test_gemini_summarizer import FakeGateway
    payload = FakeGateway().generate_json("", summary.CHUNK_SCHEMA)
    for key, value in list(payload.items()):
        if isinstance(value, list):
            payload[key] = []
    payload.update(title="新表格", summary="用户上传新表格，AI指出数值为空。", conversation_types=["document_analysis"],
                   current_progress={"current_activity": "上传新表格", "reached_stage": "AI指出数值为空", "completed_actions": [],
                                     "suggested_but_unconfirmed": [], "unresolved": [], "last_user_intent": "上传新表格", "message_ids": [3,4]})
    payload["memory_items"] = [memory(turn=3, ids=[4], media_ids=[], text="AI指出新表格数值为空。", quote="新表格数值为空。", ref="4")]
    return payload


def approve(prompt):
    import json
    records = json.loads(prompt.split("\nREVIEW_INPUT\n",1)[1])["claims"]
    return {"checks": [{"key": key, "verdict": "supported", "reason": ""} for key in records]}


class ChatGPTHistoryTests(unittest.TestCase):
    def setUp(self):
        self.messages = [{"role":"User","content":"[data.csv](./documents/data.csv)"},
            {"role":"AI","content":"我收到CSV了，我可以分析CSV，你可以告诉我需求。"},
            {"role":"User","content":"[data.xlsx](./documents/data.xlsx)"},
            {"role":"AI","content":"Excel数值单元格为空，无法计算。"}]
        self.assets = [asset(),asset("M002",3,"data.xlsx")]
        self.evidence = build_evidence(self.messages,self.assets)

    def test_csv_and_excel_have_distinct_turns_and_resources(self):
        self.assertEqual(self.evidence["messages"]["2"]["turn_user_id"],1)
        self.assertEqual(self.evidence["messages"]["4"]["turn_user_id"],3)
        self.assertEqual(self.evidence["attachments"]["M001"]["extension"],".csv")
        self.assertEqual(self.evidence["attachments"]["M002"]["extension"],".xlsx")

    def test_csv_cannot_borrow_excel_reply(self):
        item=memory(turn=3,ids=[4],text="CSV数值为空。",quote="Excel数值单元格为空",ref="4")
        with self.assertRaises(HistoryEvidenceError):
            validate_memories({"memory_items":[item]},self.evidence,{1,2,3,4})

    def test_wrong_turn_or_wrong_literal_quote_is_rejected(self):
        for item in (memory(ids=[4],ref="4",quote="Excel数值单元格为空"),memory(quote="我已经分析CSV")):
            with self.subTest(item=item),self.assertRaises(HistoryEvidenceError):
                validate_memories({"memory_items":[item]},self.evidence,{1,2,3,4})

    def test_structural_retry_receives_all_bad_record_indices(self):
        with self.assertRaises(HistoryEvidenceError) as caught:
            validate_memories({"memory_items":[memory(quote="不存在A"),memory(quote="不存在B")]},self.evidence,{1,2,3,4})
        self.assertIn("memory_items[0]",str(caught.exception))
        self.assertIn("memory_items[1]",str(caught.exception))

    def test_quote_can_omit_markdown_but_cannot_invent_an_ellipsis(self):
        messages=[self.messages[0],{"role":"AI","content":"**我可以分析CSV**，`但还未分析`。"}]
        evidence=build_evidence(messages,self.assets[:1])
        validate_memories({"memory_items":[memory(quote="我可以分析CSV，但还未分析")]},evidence,{1,2})
        with self.assertRaises(HistoryEvidenceError):
            validate_memories({"memory_items":[memory(quote="我可以分析CSV...但还未分析")]},evidence,{1,2})

    def test_future_attachments_are_not_available_to_earlier_chunks(self):
        from scripts.chatgpt_history import evidence_context
        context=evidence_context(self.evidence,{1,2})
        self.assertNotIn('M002',context['attachment_context_not_historical_speech'])
        with self.assertRaises(HistoryEvidenceError):
            validate_memories({'memory_items':[memory(media_ids=['M002'])]},self.evidence,{1,2})

    def test_program_reading_is_not_user_or_ai_speech(self):
        for source in ("user","assistant"):
            item=memory(ids=[1],source=source,kind="attachment",ref="M001",quote="数值非空")
            with self.subTest(source=source),self.assertRaises(HistoryEvidenceError):
                validate_memories({"memory_items":[item]},self.evidence,{1,2,3,4})
        item=memory(ids=[1],source="attachment",kind="attachment",ref="M001",quote="数值非空",text="CSV中存在数值。")
        validate_memories({"memory_items":[item]},self.evidence,{1,2,3,4})

    def test_attachment_anchor_is_derived_only_from_its_known_resource(self):
        from scripts.chatgpt_history import bind_attachment_anchors
        item=memory(source="attachment",kind="attachment",ref="M001",quote="数值非空")
        item["message_ids"]=[]
        payload={"memory_items":[item]}
        bind_attachment_anchors(payload,self.evidence,{1,2})
        self.assertEqual(item["message_ids"],[1])
        validate_memories(payload,self.evidence,{1,2})
        for field,value in (("turn_user_id",3),("media_ids",["M002"]),("media_ids",["unknown"])):
            changed=copy.deepcopy(item)
            changed.update(message_ids=[])
            changed[field]=value
            bind_attachment_anchors({"memory_items":[changed]},self.evidence,{1,2})
            self.assertEqual(changed["message_ids"],[])

    def test_later_explicit_reference_can_analyze_earlier_file(self):
        messages=copy.deepcopy(self.messages)
        messages[2]={"role":"User","content":"请分析之前的data.csv"}
        messages[3]={"role":"AI","content":"data.csv的均值是10。"}
        evidence=build_evidence(messages,[self.assets[0]])
        validate_memories({"memory_items":[memory(turn=3,ids=[4],quote="均值是10",ref="4",text="AI计算CSV均值为10。") ]},evidence,{1,2,3,4})

    def test_same_filename_old_versions_are_not_guessed(self):
        messages=self.messages+[{"role":"User","content":"分析data.csv"},{"role":"AI","content":"均值是10。"}]
        evidence=build_evidence(messages,[asset(),asset("M002",3,"data.csv")])
        item=memory(turn=5,ids=[6],ref="6",quote="均值是10",text="AI计算均值为10。")
        with self.assertRaises(HistoryEvidenceError):
            validate_memories({"memory_items":[item]},evidence,set(range(1,7)))

    def test_explicit_unique_short_document_title_can_reference_old_file(self):
        messages=[{"role":"User","content":"上传2025年奖学金评定细则-公示版.pdf"},
                  {"role":"AI","content":"已读。"},
                  {"role":"User","content":"上传申请表.docx"},
                  {"role":"AI","content":"结合《奖学金评定细则》核对申请表，合计应为31分。"}]
        old=asset(name="2025年奖学金评定细则-公示版.pdf")
        item=memory(turn=3,ids=[4],ref="4",quote="结合《奖学金评定细则》核对申请表",text="AI结合旧细则检查申请表。")
        validate_memories({"memory_items":[item]},build_evidence(messages,[old]),{1,2,3,4})
        other=asset("M002",1,"2026年奖学金评定细则-新版.pdf")
        with self.assertRaises(HistoryEvidenceError):
            validate_memories({"memory_items":[item]},build_evidence(messages,[old,other]),{1,2,3,4})

    def test_reviewer_rejection_and_missing_checks_are_enforced(self):
        payload={"memory_items":[memory(text="AI已分析CSV。") ]}
        for response in ({"checks":[]},{"checks":[{"key":"memory_items[0]","verdict":"unsupported","reason":"仅提供未来分析选项"}]}):
            gateway=Mock()
            gateway.generate_json.return_value=response
            with self.subTest(response=response),self.assertRaises(HistoryEvidenceError):
                review_records(payload,self.evidence,gateway)

    def test_receipt_is_not_analysis_but_actual_reading_remains_valid(self):
        messages=[{"role":"User","content":"上传细则.pdf"},{"role":"AI","content":"我已经读取PDF，其中包括参评条件。"},
                  {"role":"User","content":"上传交接.md"},{"role":"AI","content":"已读完交接文档，主要说明开发规范。"}]
        evidence=build_evidence(messages,[])
        payload={"memory_items":[memory(media_ids=[],quote="已经读取PDF",text="AI已读取PDF并概括参评条件。"),
                   memory(turn=3,ids=[4],media_ids=[],ref="4",quote="已读完交接文档",text="AI已读并概括开发规范。") ]}
        validate_memories(payload,evidence,{1,2,3,4})
        gateway=Mock()
        gateway.generate_json.side_effect=lambda prompt,schema: approve(prompt)
        review_records(payload,evidence,gateway)

    def test_generation_retries_but_never_accepts_an_unchecked_chunk(self):
        payload={"title":"CSV","summary":"AI已分析CSV。","memory_items":[memory(text="AI已分析CSV。") ]}
        gateway=Mock()
        def respond(prompt,schema):
            if schema is HISTORY_SCHEMA:
                return copy.deepcopy(payload)
            response=approve(prompt)
            for check in response["checks"]:
                check.update(verdict="unsupported",reason="原文仅表示可以分析")
            return response
        gateway.generate_json.side_effect=respond
        with self.assertRaises(HistoryEvidenceError):
            generate_chunk("原始请求",gateway,self.evidence,{1,2,3,4})
        self.assertEqual(sum(c.args[1] is HISTORY_SCHEMA for c in gateway.generate_json.call_args_list),2)
        prompts=[c.args[0] for c in gateway.generate_json.call_args_list if c.args[1] is HISTORY_SCHEMA]
        self.assertIn('"content": "AI已分析CSV。"',prompts[1])
        self.assertIn("前次返回的JSON",prompts[1])

    def test_final_topic_and_completed_claims_are_both_reviewed(self):
        payload={"memory_items":[memory()],"topics":[{"summary":"CSV数据缺失。"}],"current_state":{"completed":[{"content":"AI已分析CSV"}],"next_step":{"content":"未明确"}}}
        gateway=Mock()
        gateway.generate_json.side_effect=lambda prompt,schema: approve(prompt)
        review_records(payload,self.evidence,gateway,final=True)
        prompt=gateway.generate_json.call_args.args[0]
        self.assertIn('"topics[0]"',prompt)
        self.assertIn('"current_state.completed[0]"',prompt)
        self.assertIn('"memory_items[0]"',prompt)

    def test_normalization_keeps_the_reviewed_speaker_and_evidence(self):
        from scripts.chatgpt_history import attach_memory_evidence
        original=memory()
        normalized=copy.deepcopy(original)
        normalized.update(memory_id="C001M001",source="user",message_ids=[1],content="错误归因")
        payload={"memory_items":[normalized]}
        attach_memory_evidence(payload,{"memory_items":[original]})
        for key in ("content","source","status","message_ids","evidence_quote"):
            self.assertEqual(normalized[key],original[key])
        self.assertEqual(normalized["history_evidence"]["turn_user_id"],1)

    def test_completed_cache_does_not_rewrite_checked_history(self):
        messages=[{"role":"User","content":"这份文件里有数值吗？"},{"role":"AI","content":"有数值。"}]
        result={"processing":{"history_verification":{"version":1}},
                "conversation":{"source_fingerprint":summary.messages_fingerprint(messages)},
                "memory_items":[{"source":"user","status":"confirmed","memory_type":"fact",
                                 "message_ids":[1],"content":"用户询问文件是否包含数值。"}]}
        original=copy.deepcopy(result)
        actual=summary.renormalize_result(result,messages=messages,source_platform="ChatGPT")
        for key,value in original["memory_items"][0].items():
            self.assertEqual(actual["memory_items"][0][key],value)

    def test_grounding_schema_does_not_mutate_other_providers(self):
        properties=summary.CHUNK_SCHEMA['properties']['memory_items']['items']['properties']
        self.assertNotIn('media_ids',properties)
        self.assertIn('media_ids',HISTORY_SCHEMA['properties']['memory_items']['items']['properties'])


if __name__=="__main__":
    unittest.main()
