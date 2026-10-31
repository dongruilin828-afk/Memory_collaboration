"""批内截断反馈只作用于同配置、相近密度的未完成分块。"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest

from scripts import gemini_summarizer as summary
from scripts.adaptive_concurrency import AdaptiveSummaryScheduler
from tests.test_local_chunk_recovery import CONFIG, MESSAGES, Gateway


HTTP_EVIDENCE = {}


class PredictiveChunkTests(unittest.TestCase):
    def gateway(self, scheduler, failure=None):
        gateway = Gateway(failure)
        gateway._request_scheduler = scheduler
        gateway._api_key = "fixture-private-key"
        return gateway

    def run_summary(self, root, gateway, messages=MESSAGES, *, adaptive=True):
        return summary.summarize_conversation(messages=messages, project_dir=root,
            output_json=root / "out.json", output_markdown=root / "out.md", config=CONFIG,
            gateway=gateway, progress=lambda _text: None, adaptive_progress=adaptive)

    def truncate_pairs(self, ids, _count):
        if len(ids) == 2:
            raise summary.SummaryOutputTruncatedError("length")

    def test_later_chunks_split_before_request_and_keep_source_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scheduler = AdaptiveSummaryScheduler(trace_path=root / "trace.jsonl")
            gateway = self.gateway(scheduler, self.truncate_pairs)
            result = self.run_summary(root, gateway)
            self.assertEqual(gateway.chunks, [(1, 2), (1,), (2,), (3,), (4,), (5,), (6,)])
            self.assertEqual(result["processing"]["local_chunk_recovery"],
                             dict(splits=3, restored_chunks=0, predictive_splits=2))
            self.assertEqual([sorted({i for memory in chunk["memory_items"] for i in memory["message_ids"]})
                              for chunk in gateway.final_chunks],
                             [[1], [2], [3], [4], [5], [6]])
            memories = result["memory_items"]
            self.assertEqual(len(memories), len({m["memory_id"] for m in memories}))
            self.assertEqual({i for m in memories for i in m["message_ids"]}, set(range(1, 7)))
            rows = [json.loads(line) for line in (root / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["event"] for r in rows], ["chunk_limit_learned", "chunk_preempted", "chunk_preempted"])
            trace = json.dumps(rows, ensure_ascii=False)
            self.assertNotIn("fixture-private-key", trace)
            self.assertNotIn("api.deepseek.com", trace)
            self.assertNotIn("测试正文", trace)

    def test_learning_applies_to_next_file_but_not_next_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scheduler = AdaptiveSummaryScheduler()
            first = self.gateway(scheduler, self.truncate_pairs)
            self.run_summary(root, first, MESSAGES[:2])
            second = self.gateway(scheduler, self.truncate_pairs)
            result = self.run_summary(root, second, MESSAGES[2:4])
            self.assertEqual(second.chunks, [(1,), (2,)])
            self.assertEqual(result["processing"]["local_chunk_recovery"]["predictive_splits"], 1)
            new_batch = self.gateway(AdaptiveSummaryScheduler())
            self.run_summary(root, new_batch, MESSAGES[4:])
            self.assertEqual(new_batch.chunks, [(1, 2)])

    def test_scope_isolated_by_endpoint_key_model_thinking_budget_protocol_and_platform(self):
        scheduler = AdaptiveSummaryScheduler()
        config = replace(CONFIG, provider="custom", api_base="https://private-endpoint.test/v1")
        scheduler.record_chunk_split(config, "key-a", None, 3000, 2, 1500)
        self.assertEqual(scheduler.chunk_target(config, "key-a", None, 3000, 2), 1500)
        for changed in (replace(config, model="other"), replace(config, thinking_level="high"),
                        replace(config, max_output_tokens=32768), replace(config, api_protocol="google"),
                        replace(config, json_mode="json_schema"), replace(config, reasoning_config={"mode": "high"}),
                        replace(config, api_base="https://other-endpoint.test/v1")):
            with self.subTest(config=changed):
                self.assertIsNone(scheduler.chunk_target(changed, "key-a", None, 3000, 2))
        self.assertIsNone(scheduler.chunk_target(config, "key-b", None, 3000, 2))
        self.assertIsNone(scheduler.chunk_target(config, "key-a", "doubao", 3000, 2))
        self.assertEqual(scheduler.chunk_target(replace(config, api_profile_id="duplicate"), "key-a", None, 3000, 2), 1500)

    def test_smaller_or_different_density_chunks_are_not_preempted(self):
        scheduler = AdaptiveSummaryScheduler()
        scheduler.record_chunk_split(CONFIG, "key", None, 3000, 2, 1500)
        self.assertIsNone(scheduler.chunk_target(CONFIG, "key", None, 2300, 2))
        self.assertEqual(scheduler.chunk_target(CONFIG, "key", None, 2400, 2), 1500)
        self.assertIsNone(scheduler.chunk_target(CONFIG, "key", None, 3000, 20))

    def test_parallel_feedback_cannot_relax_a_stricter_limit(self):
        scheduler = AdaptiveSummaryScheduler()
        def record(chars):
            scheduler.record_chunk_split(CONFIG, "key", None, chars, 2, chars // 2)
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(record, [2800 + index * 40 for index in range(10)] * 3))
        self.assertEqual(scheduler.chunk_target(CONFIG, "key", None, 3000, 2), 1400)
        self.assertEqual(len(scheduler.chunk_limits), 1)

    def test_cancelled_prediction_resumes_saved_tree_and_preserves_successful_chunks(self):
        def stop(ids, _count):
            if ids == (3, 4):
                raise summary.SummaryOutputTruncatedError("length")
            if ids == (4,):
                raise asyncio.CancelledError()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scheduler = AdaptiveSummaryScheduler()
            with self.assertRaises(asyncio.CancelledError):
                self.run_summary(root, self.gateway(scheduler, stop))
            path, = root.glob("out_progress_*.tmp")
            cache = json.loads(path.read_text(encoding="utf-8"))
            good = [cache["chunks"][key] for key in ("1", "4")]
            # 模拟另一个并发文件在中断期间提供了更严格的同档反馈。
            scheduler.record_chunk_split(CONFIG, "fixture-private-key", None, 1300, 1, 1000)
            resumed = self.gateway(scheduler)
            result = self.run_summary(root, resumed)
            self.assertNotIn((1, 2), resumed.chunks)
            self.assertNotIn((3,), resumed.chunks)
            for chunk in good:
                self.assertIn(chunk, resumed.final_chunks)
            self.assertEqual(result["processing"]["local_chunk_recovery"]["restored_chunks"], 2)

    def test_predictive_tree_survives_restart_without_in_memory_feedback(self):
        def stop(ids, _count):
            if ids == (3,):
                raise asyncio.CancelledError()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scheduler = AdaptiveSummaryScheduler()
            scheduler.record_chunk_split(CONFIG, "fixture-private-key", None, 2400, 2, 1200)
            with self.assertRaises(asyncio.CancelledError):
                self.run_summary(root, self.gateway(scheduler, stop))
            path, = root.glob("out_progress_*.tmp")
            cache = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(cache["splits"]["2"]["reason"], "feedback")
            gateway = self.gateway(AdaptiveSummaryScheduler())
            result = self.run_summary(root, gateway)
            self.assertEqual(gateway.chunks, [(3,), (4,), (5, 6)])
            self.assertEqual(result["processing"]["local_chunk_recovery"]["restored_chunks"], 2)

    def test_manual_entry_does_not_use_batch_feedback(self):
        with tempfile.TemporaryDirectory() as temporary:
            scheduler = AdaptiveSummaryScheduler()
            scheduler.record_chunk_split(CONFIG, "fixture-private-key", None, 2200, 2, 1100)
            gateway = self.gateway(scheduler)
            result = self.run_summary(Path(temporary), gateway, MESSAGES[:2], adaptive=False)
            self.assertEqual(gateway.chunks, [(1, 2)])
            self.assertNotIn("local_chunk_recovery", result["processing"])

    def test_other_errors_and_global_truncation_do_not_train_chunk_policy(self):
        for error in (summary.GeminiSummaryError("JSONDecodeError"), summary.SummaryRequestTimeoutError("timeout")):
            with self.subTest(error=type(error)), tempfile.TemporaryDirectory() as temporary:
                scheduler = AdaptiveSummaryScheduler()
                def fail(_ids, _count):
                    raise error
                with self.assertRaises(type(error)):
                    self.run_summary(Path(temporary), self.gateway(scheduler, fail))
                self.assertEqual(scheduler.chunk_limits, {})
        with tempfile.TemporaryDirectory() as temporary:
            scheduler = AdaptiveSummaryScheduler()
            gateway = self.gateway(scheduler)
            original = gateway.generate_json
            def fail_global(prompt, schema, media_assets=None):
                if schema is summary.FINAL_SCHEMA:
                    raise summary.SummaryOutputTruncatedError("global length")
                return original(prompt, schema, media_assets)
            gateway.generate_json = fail_global
            with self.assertRaises(summary.SummaryOutputTruncatedError):
                self.run_summary(Path(temporary), gateway)
            self.assertEqual(scheduler.chunk_limits, {})

    def test_failure_and_prediction_share_depth_limit(self):
        def truncate(_ids, _count):
            raise summary.SummaryOutputTruncatedError("length")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scheduler = AdaptiveSummaryScheduler()
            scheduler.record_chunk_split(CONFIG, "fixture-private-key", None, 2200, 2, 1100)
            with self.assertRaises(summary.SummaryOutputTruncatedError) as caught:
                self.run_summary(root, self.gateway(scheduler, truncate))
            self.assertTrue(caught.exception.local_chunk_repair_exhausted)
            path, = root.glob("out_progress_*.tmp")
            cache = json.loads(path.read_text(encoding="utf-8"))
            index, depth = 1, 0
            while str(index) in cache["splits"]:
                index = cache["splits"][str(index)]["indices"][0]
                depth += 1
            self.assertLessEqual(depth, 3)

    def test_real_http_gateway_learns_length_and_preempts_next_file(self):
        HTTP_EVIDENCE.clear()
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                prompt = payload["messages"][-1]["content"]
                schema = payload["response_format"]["json_schema"]["schema"]
                chunk = "memory_items" in schema["properties"]
                ids = [int(index) for index in re.findall(r"\[消息 (\d+)｜(?:用户|AI)\]\n", prompt)] if chunk else []
                truncated = not requests
                requests.append(dict(stage="chunk" if chunk else "global", message_ids=ids, truncated=truncated))
                response = {} if truncated else Gateway().generate_json(prompt, summary.CHUNK_SCHEMA if chunk else summary.FINAL_SCHEMA)
                body = json.dumps(dict(choices=[dict(finish_reason="length" if truncated else "stop",
                    message=dict(content=json.dumps(response, ensure_ascii=False)))],
                    usage=dict(prompt_tokens=1, completion_tokens=1, total_tokens=2)), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config = replace(CONFIG, provider="custom", api_base=f"http://127.0.0.1:{server.server_port}/v1",
                    api_profile_id="custom_"+"a"*32, json_mode="json_schema", retries=1)
                scheduler = AdaptiveSummaryScheduler(trace_path=root / "trace.jsonl")
                scheduler.register(config.api_profile_id, config, "fixture-private-key")
                results = []
                for file, messages in enumerate((MESSAGES[:2], MESSAGES[2:4]), 1):
                    reservation = scheduler.reserve([config.api_profile_id])
                    try:
                        with scheduler.file(file, reservation):
                            results.append(summary.summarize_conversation(messages=messages, project_dir=root,
                                output_json=root / f"out{file}.json", output_markdown=root / f"out{file}.md", config=config,
                                gateway=summary.create_gateway(config, api_key="fixture-private-key", request_scheduler=scheduler),
                                progress=lambda _text: None, adaptive_progress=True))
                    finally:
                        scheduler.release(reservation)
                rows = [json.loads(line) for line in (root / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(requests), 7)
                self.assertEqual(sum(row["truncated"] for row in requests), 1)
                self.assertEqual([row["message_ids"] for row in requests if row["stage"] == "chunk"], [[1, 2], [1], [2], [1], [2]])
                self.assertEqual(results[1]["processing"]["local_chunk_recovery"]["predictive_splits"], 1)
                self.assertEqual(sum(row["event"] == "request_end" and row.get("finish_reason") == "length" for row in rows), 1)
                self.assertEqual(scheduler.snapshot()["active_requests"], 0)
                self.assertEqual(scheduler.snapshot()["pools"][0]["assigned"], 0)
                HTTP_EVIDENCE.update(requests=requests, trace=rows, final_status=scheduler.snapshot(),
                    results=[r["processing"]["local_chunk_recovery"] for r in results])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)


if __name__ == "__main__":
    unittest.main()
