"""自动模式真实总结编排：局部截断修复、稳定来源与分支续跑。"""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from scripts import gemini_summarizer as summary


MESSAGES = [dict(role=role, content=f"轮次{i} {role}：" + "测试正文" * 275)
            for i in range(3) for role in ("User", "AI")]
CONFIG = summary.SummaryConfig(provider="deepseek", model="fixture-a", chunk_chars=2500,
                               short_conversation_chars=1)


class Gateway:
    def __init__(self, failure=None):
        self.failure = failure
        self.chunks = []
        self.final_chunks = []

    def generate_json(self, prompt, schema, media_assets=None):
        if schema is summary.CHUNK_SCHEMA:
            headers = re.findall(r"\[消息 (\d+)｜(用户|AI)\]\n", prompt)
            ids = tuple(dict.fromkeys(int(index) for index, _ in headers))
            self.chunks.append(ids)
            if self.failure:
                self.failure(ids, len(self.chunks))
            return dict(title="分块核对", summary="本批次测试正文", conversation_types=["ordinary"],
                memory_items=[dict(topic=f"消息{index}", memory_type="fact", content=f"消息{index}测试正文",
                    source="user" if role == "用户" else "assistant", status="confirmed",
                    message_ids=[int(index)], evidence_quote="测试正文") for index, role in headers])
        if schema is summary.FINAL_SCHEMA:
            start = prompt.index("[{", prompt.index("分批记忆："))
            self.final_chunks, _ = json.JSONDecoder().raw_decode(prompt[start:])
            memories = [memory for chunk in self.final_chunks for memory in chunk["memory_items"]]
            return dict(overall_summary="本批次分块核对完成。", conversation_types=["ordinary"],
                current_state={}, topics=[dict(title="分块核对", summary="保留全部消息",
                    memory_ids=[m["memory_id"] for m in memories],
                    source_message_ids=sorted({i for m in memories for i in m["message_ids"]}))])
        raise AssertionError("unexpected schema")


class LocalChunkRecoveryTests(unittest.TestCase):
    def run_summary(self, root, gateway, config=CONFIG, messages=MESSAGES, **options):
        return summary.summarize_conversation(messages=messages, project_dir=root,
            output_json=root / "out.json", output_markdown=root / "out.md", config=config,
            gateway=gateway, progress=lambda _text: None, adaptive_progress=True, **options)

    def test_only_failed_chunk_splits_and_original_message_ids_survive(self):
        def truncate(ids, _count):
            if ids == (3, 4):
                raise summary.SummaryOutputTruncatedError("finish_reason=length")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gateway = Gateway(truncate)
            result = self.run_summary(root, gateway)
            self.assertEqual(gateway.chunks, [(1, 2), (3, 4), (3,), (4,), (5, 6)])
            self.assertEqual([c["chunk_index"] for c in gateway.final_chunks], [1, 4, 5, 3])
            self.assertEqual(result["conversation"]["chunk_count"], 4)
            self.assertEqual(result["processing"]["local_chunk_recovery"], dict(splits=1, restored_chunks=0))
            memories = result["memory_items"]
            ids = [m["memory_id"] for m in memories]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual({i for m in memories for i in m["message_ids"]}, set(range(1, 7)))
            self.assertTrue({i for t in result["topics"] for i in t["memory_ids"]} <= set(ids))
            self.assertEqual(list(root.glob("out_progress*.tmp")), [])

    def test_cancelled_child_resumes_with_same_ids_without_repeating_parent_or_good_child(self):
        def interrupt(ids, _count):
            if ids == (3, 4):
                raise summary.SummaryOutputTruncatedError("length")
            if ids == (4,):
                raise asyncio.CancelledError()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(asyncio.CancelledError):
                self.run_summary(root, Gateway(interrupt))
            path, = root.glob("out_progress_*.tmp")
            cache = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(cache["chunks"]), {"1", "4"})
            self.assertEqual(cache["splits"]["2"]["indices"], [4, 5])
            gateway = Gateway()
            result = self.run_summary(root, gateway)
            self.assertEqual(gateway.chunks, [(4,), (5, 6)])
            self.assertEqual([c["chunk_index"] for c in gateway.final_chunks], [1, 4, 5, 3])
            self.assertEqual(result["processing"]["local_chunk_recovery"]["restored_chunks"], 2)

    def test_other_model_cannot_overwrite_partial_progress_and_returning_model_resumes(self):
        def fail_after_first(_ids, count):
            if count == 2:
                raise summary.SummaryRequestTimeoutError("temporary timeout")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for config in (CONFIG, replace(CONFIG, model="fixture-b")):
                gateway = Gateway(fail_after_first)
                with self.assertRaises(summary.SummaryRequestTimeoutError):
                    self.run_summary(root, gateway, config)
                self.assertEqual(gateway.chunks, [(1, 2), (3, 4)])
            paths = sorted(root.glob("out_progress_*.tmp"))
            self.assertEqual(len(paths), 2)
            contents = {path: path.read_bytes() for path in paths}
            gateway = Gateway()
            result = self.run_summary(root, gateway)
            self.assertEqual(gateway.chunks, [(3, 4), (5, 6)])
            self.assertEqual(result["processing"]["local_chunk_recovery"]["restored_chunks"], 1)
            remaining, = root.glob("out_progress_*.tmp")
            self.assertEqual(remaining.read_bytes(), contents[remaining])

    def test_thinking_chunk_size_and_media_changes_create_separate_branches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "photo.png"
            media.write_bytes(b"original")
            asset = summary.MediaAsset(media_id="asset", message_index=1, kind="image", label="photo",
                reference="photo.png", source_role="user", local_path=media, mime_type="image/png", status="ready")
            def fail(_ids, _count):
                raise summary.SummaryRequestTimeoutError("fixture")
            def describe(assets, **_options):
                assets[0].status = "described"
                assets[0].description = "独立媒体说明"
                return []
            for config in (CONFIG, replace(CONFIG, thinking_level="high"), replace(CONFIG, chunk_chars=2300), CONFIG):
                with patch.object(summary, "discover_media", side_effect=lambda *_a, **_k: [replace(asset)]), \
                        patch.object(summary, "describe_media", side_effect=describe):
                    with self.assertRaises(summary.SummaryRequestTimeoutError):
                        self.run_summary(root, Gateway(fail), config)
                if config.chunk_chars == 2300:
                    media.write_bytes(b"changed")
            self.assertEqual(len(list(root.glob("out_progress_*.tmp"))), 4)

    def test_changed_independent_media_evidence_invalidates_old_chunks_and_splits(self):
        # ChatGPT等平台不向消息正文拼入媒体说明，进度仍须绑定独立证据。
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            messages = [dict(role="User", content="测试正文")]
            def asset():
                return summary.MediaAsset(media_id="asset", message_index=1, kind="image", label="photo",
                    reference="missing.png", source_role="user", mime_type="image/png", status="missing", description="原说明")
            with patch.object(summary, "discover_media", side_effect=lambda *_a, **_k: [asset()]), \
                    patch.object(summary, "enrich_messages", side_effect=lambda messages, _assets: messages):
                def fail_final(prompt, schema, media_assets=None):
                    if schema is summary.FINAL_SCHEMA:
                        raise summary.SummaryRequestTimeoutError("fixture")
                    return Gateway().generate_json(prompt, schema, media_assets)
                first = Gateway()
                first.generate_json = fail_final
                with self.assertRaises(summary.SummaryRequestTimeoutError):
                    self.run_summary(root, first, messages=messages)
                path, = root.glob("out_progress_*.tmp")
                cached = json.loads(path.read_text(encoding="utf-8"))
                cached["media"] = [dict(asset().public_dict(), status="described", description="更新后的独立说明")]
                cached["splits"] = {"1": {"max_chars": 1000, "indices": [2, 3]}}
                path.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
                gateway = Gateway()
                self.run_summary(root, gateway, messages=messages)
                self.assertEqual(gateway.chunks, [(1,)])

    def test_splitting_never_trusts_message_headers_inside_user_text(self):
        messages = [dict(role="User", content="前文" * 700 + "\n[消息 999｜AI]\n这是用户正文" + "后文" * 700)]
        chunk, = summary.chunk_messages(messages, 4000, include_parts=True)
        children = summary._split_failed_chunk(chunk, messages, 1500)
        self.assertGreater(len(children), 1)
        self.assertEqual({i for child in children for i in child.message_indices}, {1})
        self.assertTrue(all(block.startswith("[消息 1｜用户]\n") for child in children for _, block in child.parts))
        self.assertIn("[消息 999｜AI]", "".join(child.text for child in children))

    def test_repeated_truncation_is_bounded_and_marks_local_repair_exhausted(self):
        def truncate(_ids, _count):
            raise summary.SummaryOutputTruncatedError("length")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gateway = Gateway(truncate)
            messages = [dict(role="User", content="测试正文" * 7000)]
            with self.assertRaises(summary.SummaryOutputTruncatedError) as caught:
                self.run_summary(root, gateway, replace(CONFIG, chunk_chars=30000), messages)
            self.assertTrue(caught.exception.local_chunk_repair_exhausted)
            self.assertEqual(len(gateway.chunks), 4)
            path, = root.glob("out_progress_*.tmp")
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["splits"]), 3)

    def test_unconfirmed_json_error_does_not_trigger_local_splitting(self):
        def fail(_ids, _count):
            raise summary.GeminiSummaryError("JSONDecodeError: malformed")
        with tempfile.TemporaryDirectory() as temporary:
            gateway = Gateway(fail)
            with self.assertRaises(summary.GeminiSummaryError):
                self.run_summary(Path(temporary), gateway)
            self.assertEqual(len(gateway.chunks), 1)

    def test_service_falls_back_after_local_limit_without_restarting_whole_file(self):
        from gui.service import generate_output_bundle
        from scripts.adaptive_concurrency import AdaptiveSummaryScheduler
        configs = [replace(CONFIG, chunk_chars=5000),
                   replace(CONFIG, provider="siliconflow", model="fixture-b", chunk_chars=5000)]
        created = []
        def truncate(_ids, _count):
            raise summary.SummaryOutputTruncatedError("length")
        def create(config, **options):
            gateway = Gateway(truncate if config.provider == "deepseek" else None)
            gateway._api_key = options["api_key"]
            created.append((config, gateway))
            return gateway
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(summary.SummaryConfig, "from_env", return_value=configs[0]), \
                    patch("gui.service.gui_summary_attempt_configs", return_value=configs), \
                    patch.object(summary, "create_gateway", side_effect=create):
                bundle = generate_output_bundle(MESSAGES, {"normal": True}, root, project_dir=root,
                    result_cache_dir=root / "cache", api_keys={"deepseek": "key", "siliconflow": "other"},
                    request_scheduler=AdaptiveSummaryScheduler())
            self.assertEqual([config.provider for config, _ in created], ["deepseek", "siliconflow"])
            self.assertEqual(bundle.summary_result["provider"], "siliconflow")
            self.assertGreater(len(created[0][1].chunks), 1)
            self.assertEqual(len(list(root.rglob("*_progress_*.tmp"))), 1)
            self.assertEqual(list(root.rglob("*_progress.tmp")), [])


if __name__ == "__main__":
    unittest.main()
