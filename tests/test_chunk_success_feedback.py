"""成功反馈只放宽后续未保存的拆分目标，使用真实输出预算及反馈轮次。"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts import gemini_summarizer as summary
from scripts.adaptive_concurrency import AdaptiveSummaryScheduler, APIDeferred, SummaryBudgetExceeded
from tests.test_local_chunk_recovery import CONFIG, MESSAGES, Gateway


HTTP_EVIDENCE = {}


class SuccessFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.config = replace(CONFIG, chunk_chars=20000, max_output_tokens=10000)
        self.scheduler = AdaptiveSummaryScheduler()
        self.key = "fixture-private-key"

    def learn(self, config=None):
        self.scheduler.record_chunk_split(config or self.config, self.key, None, 6200, 6, 3100)

    def observe(self, *, config=None, chars=3100, count=3, epoch="current", response="valid"):
        config = config or self.config
        if epoch == "current":
            epoch = self.scheduler.chunk_epoch(config, self.key, None, chars, count)
        if response == "valid":
            response = dict(finish_reason="stop", usage=dict(completion_tokens=1000), output_limit=config.max_output_tokens)
        self.scheduler.record_chunk_success(config, self.key, None, chars, count, epoch, response)

    def target(self, config=None):
        return self.scheduler.chunk_target(config or self.config, self.key, None, 6200, 6)

    def test_three_successes_grow_by_quarter_with_failure_margin_and_config_cap(self):
        self.learn()
        for _ in range(2):
            self.observe()
        self.assertEqual(self.target(), 3100)
        self.observe()
        self.assertEqual(self.target(), 3875)
        for _ in range(12):
            self.observe()
        self.assertEqual(self.target(), 4960)
        config = replace(self.config, chunk_chars=3500, model="capped")
        self.learn(config)
        for _ in range(3):
            self.observe(config=config)
        self.assertEqual(self.target(config), 3500)

    def test_success_without_failure_sample_does_not_create_a_policy(self):
        for _ in range(10):
            self.observe()
        self.assertEqual(self.scheduler.chunk_limits, {})

    def test_missing_invalid_high_usage_and_changed_budget_break_success_streak(self):
        invalid = [None, {}, dict(usage=None), dict(finish_reason="length"),
            dict(finish_reason="stop", usage=dict(completion_tokens=6100), output_limit=10000),
            dict(finish_reason="stop", usage=dict(completion_tokens=True), output_limit=10000),
            dict(finish_reason="stop", usage=dict(completion_tokens=-1), output_limit=10000),
            dict(finish_reason="stop", usage=dict(completion_tokens=1), output_limit=20000),
            dict(finish_reason="stop", usage=dict(completion_tokens=1), output_limit=10000,
                 request_config=replace(self.config, model="other-actual-model"))]
        for response in invalid:
            with self.subTest(response=response):
                self.scheduler = AdaptiveSummaryScheduler()
                self.learn()
                self.observe(); self.observe(); self.observe(response=response); self.observe()
                self.assertEqual(self.target(), 3100)
                self.observe(); self.observe()
                self.assertEqual(self.target(), 3875)

    def test_too_small_successful_tail_cannot_expand_full_chunks(self):
        self.learn()
        for _ in range(6):
            self.observe(chars=1500, count=1)
        self.assertEqual(self.target(), 3100)
        for _ in range(3):
            self.observe(response=dict(finish_reason="stop", usage=dict(completion_tokens=6000), output_limit=10000))
        self.assertEqual(self.target(), 3875)

    def test_projected_larger_output_keeps_quarter_budget_spare(self):
        self.learn()
        for _ in range(3):
            self.observe(chars=2200, count=2, response=dict(finish_reason="stop",
                usage=dict(completion_tokens=5000), output_limit=10000))
        self.assertEqual(self.target(), 3100)

    def test_google_includes_thoughts_and_requires_separate_usage(self):
        config = replace(self.config, provider="gemini")
        self.learn(config)
        for usage in (dict(completion_tokens=1000), dict(completion_tokens=5000, reasoning_tokens=2000)):
            for _ in range(3):
                self.observe(config=config, response=dict(finish_reason="stop", usage=usage, output_limit=10000))
            self.assertEqual(self.target(config), 3100)
        for _ in range(3):
            self.observe(config=config, response=dict(finish_reason="stop",
                usage=dict(completion_tokens=3000, reasoning_tokens=2000), output_limit=10000))
        self.assertEqual(self.target(config), 3875)

    def test_changed_model_thinking_or_budget_cannot_grow_original_policy(self):
        self.learn()
        for config in (replace(self.config, model="other"), replace(self.config, thinking_level="high"),
                       replace(self.config, max_output_tokens=20000)):
            for _ in range(6):
                self.observe(config=config)
        self.assertEqual(self.target(), 3100)

    def test_truncation_immediately_tightens_and_old_successes_are_ignored(self):
        self.learn()
        old_epoch = self.scheduler.chunk_epoch(self.config, self.key, None, 3100, 3)
        for _ in range(3):
            self.observe()
        self.scheduler.record_chunk_split(self.config, self.key, None, 5000, 4, 2500)
        for _ in range(6):
            self.observe(epoch=old_epoch)
        self.assertEqual(self.target(), 2500)
        self.observe(); self.observe()
        self.assertEqual(self.target(), 2500)
        self.observe()
        self.assertEqual(self.target(), 3125)

    def test_many_inflight_old_successes_only_allow_one_growth_step(self):
        self.learn()
        epoch = self.scheduler.chunk_epoch(self.config, self.key, None, 3100, 3)
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _i: self.observe(epoch=epoch), range(24)))
        self.assertEqual(self.target(), 3875)

    def prepared_gateway(self, scheduler, config):
        gateway = Gateway()
        gateway._request_scheduler = scheduler
        gateway._api_key = self.key
        original = gateway.generate_json
        def generate(prompt, schema, media_assets=None):
            data = original(prompt, schema, media_assets)
            if schema is summary.CHUNK_SCHEMA:
                scheduler.context.chunk_response = dict(finish_reason="stop", output_limit=config.max_output_tokens,
                    usage=dict(completion_tokens=1000))
            return data
        gateway.generate_json = generate
        return gateway

    def summarize(self, root, gateway, *, messages=MESSAGES, adaptive=True):
        return summary.summarize_conversation(messages, root, output_json=root / "out.json", output_markdown=root / "out.md",
            config=self.config, gateway=gateway, adaptive_progress=adaptive, progress=lambda _text: None)

    def test_semantic_failure_does_not_count_a_valid_json_response(self):
        self.learn(); self.observe(); self.observe()
        with tempfile.TemporaryDirectory() as temporary, patch.object(summary, "_normalize_chunk_summary", side_effect=ValueError("fixture")):
            with self.assertRaises(ValueError):
                self.summarize(Path(temporary), self.prepared_gateway(self.scheduler, self.config), messages=MESSAGES[:2])
        self.assertEqual(self.target(), 3100)
        self.observe()
        self.assertEqual(self.target(), 3100)

    def test_local_deferral_or_budget_stop_does_not_reset_other_successes(self):
        for error in (APIDeferred(), SummaryBudgetExceeded("fixture")):
            for stage in ("generation", "verification"):
                with self.subTest(error=type(error), stage=stage), tempfile.TemporaryDirectory() as temporary:
                    self.scheduler = AdaptiveSummaryScheduler()
                    self.learn(); self.observe(); self.observe()
                    gateway = self.prepared_gateway(self.scheduler, self.config)
                    if stage == "generation":
                        def defer(*_args, **_kwargs):
                            raise error
                        gateway.generate_json = defer
                    with patch.object(summary, "_normalize_chunk_summary", side_effect=error), self.assertRaises(type(error)):
                        self.summarize(Path(temporary), gateway, messages=MESSAGES[:2])
                    self.observe()
                    self.assertEqual(self.target(), 3875)

    def test_saved_tree_and_cached_successes_do_not_count_twice(self):
        self.scheduler.record_chunk_split(self.config, self.key, None, 7000, 6, 3500)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gateway = self.prepared_gateway(self.scheduler, self.config)
            original = gateway.generate_json
            def fail_final(prompt, schema, media_assets=None):
                if schema is summary.FINAL_SCHEMA:
                    raise summary.SummaryRequestTimeoutError("fixture")
                return original(prompt, schema, media_assets)
            gateway.generate_json = fail_final
            with self.assertRaises(summary.SummaryRequestTimeoutError):
                self.summarize(root, gateway)
            target = self.target()
            self.assertEqual(target, 4375)
            resumed = self.prepared_gateway(self.scheduler, self.config)
            with patch.object(self.scheduler, "record_chunk_success", wraps=self.scheduler.record_chunk_success) as feedback:
                result = self.summarize(root, resumed)
            self.assertEqual(feedback.call_count, 0)
            self.assertEqual(result["processing"]["local_chunk_recovery"]["restored_chunks"], 3)
            self.assertEqual([c["chunk_index"] for c in resumed.final_chunks], [2, 3, 4])
            self.assertEqual(self.target(), target)

    def test_default_entry_does_not_use_success_feedback(self):
        self.learn()
        with tempfile.TemporaryDirectory() as temporary, patch.object(self.scheduler, "record_chunk_success") as feedback:
            self.summarize(Path(temporary), self.prepared_gateway(self.scheduler, self.config), adaptive=False)
        self.assertEqual(feedback.call_count, 0)
        self.assertEqual(self.target(), 3100)

    def test_real_http_growth_reduces_requests_without_rewriting_saved_chunks(self):
        HTTP_EVIDENCE.clear()
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                schema = payload["response_format"]["json_schema"]["schema"]
                chunk = "memory_items" in schema["properties"]
                calls.append("chunk" if chunk else "global")
                response = Gateway().generate_json(payload["messages"][-1]["content"], summary.CHUNK_SCHEMA if chunk else summary.FINAL_SCHEMA)
                body = json.dumps(dict(choices=[dict(finish_reason="stop", message=dict(content=json.dumps(response)))],
                    usage=dict(prompt_tokens=100, completion_tokens=100, total_tokens=200))).encode()
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
                config = replace(self.config, provider="custom", api_base=f"http://127.0.0.1:{server.server_port}/v1",
                    api_profile_id="custom_"+"a"*32, json_mode="json_schema", retries=1, max_output_tokens=4096)
                for enabled in (False, True):
                    calls.clear()
                    scheduler = AdaptiveSummaryScheduler(trace_path=root / f"trace{enabled}.jsonl")
                    scheduler.record_chunk_split(config, self.key, None, 6200, 6, 3100)
                    counts, results = [], []
                    # 基线仅关闭成功回升，其他编排和真实HTTP传输保持一致。
                    with patch.object(scheduler, "record_chunk_success", wraps=scheduler.record_chunk_success if enabled else None):
                        for file in (1, 2):
                            before = len(calls)
                            result = summary.summarize_conversation((MESSAGES * 4)[:20], root,
                                output_json=root / f"out{enabled}_{file}.json", output_markdown=root / f"out{enabled}_{file}.md",
                                config=config, gateway=summary.create_gateway(config, api_key=self.key, request_scheduler=scheduler),
                                adaptive_progress=True, progress=lambda _text: None)
                            counts.append(len(calls)-before)
                            self.assertEqual({i for m in result["memory_items"] for i in m["message_ids"]}, set(range(1, 21)))
                            self.assertEqual(len(result["memory_items"]), len({m["memory_id"] for m in result["memory_items"]}))
                            results.append(dict(chunks=result["conversation"]["chunk_count"], sources_verified=True))
                    rows = [json.loads(line) for line in (root / f"trace{enabled}.jsonl").read_text(encoding="utf-8").splitlines()]
                    HTTP_EVIDENCE["enabled" if enabled else "baseline"] = dict(requests=len(calls), per_file_requests=counts,
                        results=results, trace=rows, final_status=scheduler.snapshot())
                self.assertEqual(HTTP_EVIDENCE["baseline"]["per_file_requests"], [10, 10])
                self.assertEqual(HTTP_EVIDENCE["enabled"]["per_file_requests"], [10, 6])
                self.assertTrue(any(row["event"] == "chunk_limit_relaxed" for row in HTTP_EVIDENCE["enabled"]["trace"]))
                self.assertEqual(HTTP_EVIDENCE["enabled"]["final_status"]["active_requests"], 0)
                self.assertNotIn(self.key, json.dumps(HTTP_EVIDENCE))
                self.assertNotIn("127.0.0.1", json.dumps(HTTP_EVIDENCE))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)


if __name__ == "__main__":
    unittest.main()
