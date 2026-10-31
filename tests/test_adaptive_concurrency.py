"""Deterministic feedback, real thread admission, gateway retries and file dispatch."""
import asyncio
from contextlib import contextmanager
import io
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from scripts.adaptive_concurrency import AdaptiveSummaryScheduler, APIUnavailable, retry_seconds
from scripts import gemini_summarizer as summary
from gui.batch_processing import BatchPlan, ItemPlan, BatchProcessingQueue


class Clock:
    now = 100
    def __call__(self):
        return self.now
    def advance(self, amount=1):
        self.now += amount


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.scheduler = AdaptiveSummaryScheduler(clock=self.clock)
        self.config = summary.SummaryConfig(provider="deepseek", model="fixture", retries=2, thinking_level="auto")
        self.key, _ = self.scheduler.register("deepseek", self.config, "fixture-secret")

    def success(self, count=4, prompt="test"):
        for _ in range(count):
            self.clock.advance()
            with self.scheduler.request(self.config, "fixture-secret", prompt):
                self.clock.advance()

    def failure(self, code, headers=None):
        self.clock.advance(100)
        with self.assertRaises(HTTPError), self.scheduler.request(self.config, "fixture-secret", "test"):
            raise HTTPError("https://fixture.test", code, "fixture", headers or {}, io.BytesIO(b"{}"))

    def test_stable_requests_grow_one_api_to_ten_without_probes(self):
        self.assertEqual(self.scheduler.capacity(), 1)
        self.success()
        self.assertEqual(self.scheduler.capacity(), 2)
        self.success(80)
        self.assertEqual(self.scheduler.capacity(), 10)
        self.assertEqual(self.scheduler.snapshot()["active_requests"], 0)

    def test_duplicate_profiles_and_models_share_capacity(self):
        other = summary.replace(self.config, model="other", api_profile_id="duplicate")
        self.scheduler.register("duplicate", other, "fixture-secret")
        self.assertEqual(self.scheduler.capacity(), 1)
        first = self.scheduler.reserve(["deepseek", "duplicate"])
        second = self.scheduler.reserve(["duplicate", "deepseek"])
        self.assertEqual(first[1], second[1])
        self.scheduler.release(first)
        self.scheduler.release(second)
        self.assertEqual(self.scheduler.pools[self.key].assigned, 0)
        self.assertNotIn("fixture-secret", json.dumps(self.scheduler.snapshot()))

    def test_load_assignment_avoids_reserved_or_cooling_api(self):
        self.scheduler.register("gemini", summary.replace(self.config, provider="gemini"), "other")
        reserved = self.scheduler.reserve(["deepseek", "gemini"], 4)
        self.assertEqual(self.scheduler.reserve(["deepseek", "gemini"])[0], "gemini")
        self.scheduler.release(reserved)
        self.failure(429, {"Retry-After": "12.5"})
        self.assertEqual(self.scheduler.reserve(["deepseek", "gemini"])[0], "gemini")
        self.assertEqual(self.scheduler.snapshot()["cooling"], 1)
        self.assertAlmostEqual(retry_seconds(HTTPError("x",429,"x",{"Retry-After":"12.5"},None)), 12.5)

    def test_rate_limit_halves_capacity_and_cools_down(self):
        self.success(12)
        self.assertEqual(self.scheduler.capacity(), 4)
        self.failure(429, {"Retry-After": "12"})
        self.assertEqual(self.scheduler.capacity(), 0)
        self.clock.advance(13)
        self.assertEqual(self.scheduler.capacity(), 2)
        self.assertGreater(self.scheduler.pools[self.key].interval, .25)

    def test_content_failures_do_not_reduce_capacity(self):
        self.success()
        for code in (400, 422, 400):
            self.failure(code)
        self.clock.advance()
        with self.assertRaises(json.JSONDecodeError), self.scheduler.request(self.config, "fixture-secret", "test"):
            json.loads("invalid")
        self.assertEqual(self.scheduler.capacity(), 2)
        self.assertEqual(self.scheduler.pools[self.key].faults, 0)

    def test_permanent_errors_block_account_or_only_failed_model(self):
        for code in (401, 402, 403, 404):
            with self.subTest(code=code):
                self.setUp()
                other = summary.replace(self.config, model="other")
                self.scheduler.register("deepseek", other, "fixture-secret")
                self.failure(code)
                self.assertEqual(self.scheduler.capacity(), 0 if code in (401,402) else 1)
                with self.assertRaises(APIUnavailable), self.scheduler.request(self.config, "fixture-secret", "test"):
                    self.fail("disabled endpoint sent a request")

    def test_only_repeated_transport_failures_reduce_capacity(self):
        self.success(12)
        self.failure(503)
        self.assertEqual(self.scheduler.capacity(), 4)
        self.failure(503)
        self.clock.advance(3)
        self.assertEqual(self.scheduler.capacity(), 1)  # One recovery request first.
        self.success(1)
        self.assertEqual(self.scheduler.capacity(), 2)

    def test_large_or_different_model_request_is_not_compared_to_small_request(self):
        self.success()
        self.clock.advance()
        with self.scheduler.request(self.config, "fixture-secret", "large" * 5000):
            self.clock.advance(90)
        self.assertEqual(self.scheduler.capacity(), 2)
        self.assertEqual(self.scheduler.pools[self.key].stable, 3)

    def test_no_growth_when_queue_has_no_pending_files(self):
        self.scheduler.has_pending = lambda: False
        self.success(12)
        self.assertEqual(self.scheduler.capacity(), 1)

    def test_waiting_and_inflight_cancellation_release_permits(self):
        cancel, entered = threading.Event(), threading.Event()
        outcome = []
        def waiting():
            try:
                entered.set()
                with self.scheduler.request(self.config, "fixture-secret", "test", cancel):
                    self.fail("no capacity should be available")
            except BaseException as error:
                outcome.append(error)
        with self.scheduler.request(self.config, "fixture-secret", "test"):
            worker = threading.Thread(target=waiting)
            worker.start()
            self.assertTrue(entered.wait(1))
            cancel.set()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertIsInstance(outcome[0], asyncio.CancelledError)
        self.assertEqual(self.scheduler.snapshot()["active_requests"], 0)
        self.clock.advance(100)
        with self.assertRaises(asyncio.CancelledError), self.scheduler.request(self.config, "fixture-secret", "test"):
            raise asyncio.CancelledError()
        self.assertEqual(self.scheduler.snapshot()["active_requests"], 0)

    def test_cooling_wait_can_be_cancelled(self):
        self.failure(429, {"Retry-After":"600"})
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(asyncio.CancelledError), self.scheduler.request(self.config, "fixture-secret", "test", cancel):
            self.fail("cooling request was sent")

    def test_every_http_retry_gets_a_new_permit(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"{\\"ok\\":true}"}}]}'
        gateway = summary.SiliconFlowGateway(self.config, api_key="fixture-secret", request_scheduler=self.scheduler,
            sleep=lambda _: self.clock.advance(100))
        with patch.object(summary, "urlopen", side_effect=[HTTPError("x",429,"x",{"Retry-After":"5"},None), response]), \
                patch.object(self.scheduler, "request", wraps=self.scheduler.request) as admission:
            self.assertEqual(gateway.generate_json("test", {}), {"ok":True})
        self.assertEqual(admission.call_count, 2)
        self.assertEqual(self.scheduler.snapshot()["active_requests"], 0)

    def test_google_retry_gets_a_new_permit_and_keeps_structured_delay(self):
        config = summary.replace(self.config, provider="gemini")
        error = RuntimeError("fixture")
        error.code, error.details = 429, [{"retryDelay":"8s"}]
        with patch("google.genai.Client") as client:
            client.return_value.models.generate_content.side_effect = [error, SimpleNamespace(text='{"ok":true}')]
            gateway = summary.GeminiGateway(config, api_key="google-fixture", request_scheduler=self.scheduler,
                sleep=lambda _: self.clock.advance(100))
            with patch.object(self.scheduler, "request", wraps=self.scheduler.request) as admission:
                self.assertEqual(gateway.generate_json("test", {}), {"ok":True})
            self.assertEqual(admission.call_count, 2)

    def test_async_http_timeouts_reduce_capacity_after_two_real_attempts(self):
        import httpx
        self.success(12)
        gateway = summary.SiliconFlowGateway(self.config, api_key="fixture-secret", request_scheduler=self.scheduler,
            cancel_event=threading.Event())
        self.clock.advance(100)
        async def timeout(_request):
            raise httpx.ReadTimeout("fixture timeout")
        with patch.object(gateway,"_request_async",timeout), \
                patch.object(summary,"wait_with_cancel",side_effect=lambda *_: self.clock.advance(100)):
            with self.assertRaises(summary.SummaryRequestTimeoutError):
                gateway.generate_json("test",{})
        self.clock.advance(3)
        self.assertEqual(self.scheduler.capacity(),1)
        self.assertEqual(self.scheduler.snapshot()["active_requests"],0)

    def test_worker_survives_candidate_disappearing_between_wait_and_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            source=root/"input.txt"
            source.write_text("fixture",encoding="utf-8")
            queue=BatchProcessingQueue()
            original=queue._next_summary
            candidates, errors=[],[]
            def unstable():
                candidate=original()
                if candidate is not None:
                    candidates.append(candidate)
                    if len(candidates)==2:
                        return None
                return candidate
            try:
                with patch.object(queue,"_next_summary",unstable), patch.object(queue,"_generate",return_value=[]), \
                        patch.object(threading,"excepthook",side_effect=lambda error:errors.append(error)):
                    queue.add(BatchPlan("files",(ItemPlan(str(source),("simple",)),)),
                        output_parent=root,runtime_dir=root,api_keys={"deepseek":"key"})
                    deadline=time.monotonic()+3
                    while queue.has_work and time.monotonic()<deadline:
                        time.sleep(.01)
                    self.assertFalse(queue.has_work,queue.snapshot())
                    self.assertEqual(errors,[])
                    self.assertTrue(all(thread.is_alive() for thread in queue.threads))
            finally:
                queue.close()
                self.assertTrue(queue.wait(3))

    def test_queue_expands_one_api_and_manual_modes_do_not_inject_scheduler(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.txt"
            source.write_text("fixture", encoding="utf-8")
            for limit in (None, 2):
                queue = BatchProcessingQueue()
                observed = []
                def generate(*args, **options):
                    scheduler = options.get("request_scheduler")
                    observed.append(scheduler)
                    if scheduler:
                        self.clock.now = max(self.clock.now, time.monotonic() + 1000)
                        scheduler.clock = self.clock
                        for _ in range(4):
                            self.clock.advance(3)
                            with scheduler.request(self.config, "key", "test"):
                                self.clock.advance()
                    return SimpleNamespace(saved_files=[], summary_result=None)
                try:
                    with patch("gui.batch_processing.generate_output_bundle", generate):
                        queue.add(BatchPlan("files", tuple(ItemPlan(str(source),("simple",)) for _ in range(8)), limit),
                            output_parent=root, runtime_dir=root, api_keys={"deepseek":"key"})
                        deadline = time.monotonic() + 5
                        while queue.has_work and time.monotonic() < deadline:
                            time.sleep(.01)
                    self.assertFalse(queue.has_work, queue.snapshot())
                    self.assertEqual(queue.snapshot()[0]["failed"], 0)
                    self.assertTrue(all((item is not None) == (limit is None) for item in observed))
                    if limit is None:
                        self.assertGreater(queue.snapshot()[0]["concurrency"], 1)
                finally:
                    queue.close()
                    self.assertTrue(queue.wait(3))

    def test_cooling_file_does_not_stop_healthy_api_dispatch(self):
        reserved = self.scheduler.reserve(["deepseek"])
        self.assertEqual(self.scheduler.busy_files([reserved]), 1)
        self.failure(429)
        self.assertEqual(self.scheduler.busy_files([reserved]), 0)

    def test_twelve_endpoints_never_send_more_than_ten_requests_at_once(self):
        scheduler = AdaptiveSummaryScheduler()
        release, ten_entered = threading.Event(), threading.Event()
        lock = threading.Lock()
        active = peak = 0
        errors = []
        def run(index):
            nonlocal active, peak
            try:
                config = summary.replace(self.config, provider="custom", api_base=f"https://endpoint-{index}.test")
                with scheduler.request(config, "key", "test"):
                    with lock:
                        active += 1
                        peak = max(peak, active)
                        if active == 10:
                            ten_entered.set()
                    release.wait(3)
                    with lock:
                        active -= 1
            except BaseException as error:
                errors.append(error)
        workers = [threading.Thread(target=run, args=(index,)) for index in range(12)]
        try:
            for worker in workers:
                worker.start()
            self.assertTrue(ten_entered.wait(2))
            self.assertEqual(scheduler.snapshot()["active_requests"], 10)
        finally:
            release.set()
            for worker in workers:
                worker.join(3)
        self.assertEqual(errors, [])
        self.assertEqual(peak, 10)
        self.assertEqual(scheduler.snapshot()["active_requests"], 0)

    def test_service_fallback_uses_the_same_scheduler_and_skips_disabled_api(self):
        from gui.service import generate_output_bundle
        scheduler = AdaptiveSummaryScheduler()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"{\\"ok\\":true}"}}]}'
        calls = []
        def http(request, **_options):
            calls.append(request.full_url)
            if "deepseek" in request.full_url:
                raise HTTPError(request.full_url,401,"unauthorized",{},io.BytesIO(b'{}'))
            return response
        def summarize(**options):
            self.assertEqual(options["gateway"].generate_json("test", {}), {"ok":True})
            options["output_markdown"].write_text("fixture", encoding="utf-8")
            options["output_json"].write_text("{}", encoding="utf-8")
            return {"processing":{}}
        with tempfile.TemporaryDirectory() as temporary, patch.object(summary.SummaryConfig,"from_env",return_value=self.config), \
                patch.object(summary,"urlopen",side_effect=http), patch.object(summary,"summarize_conversation",side_effect=summarize):
            scheduler.register("deepseek", self.config, "first")
            reservation = scheduler.reserve(["deepseek"], 3)
            with scheduler.file(11, reservation):
                generate_output_bundle([dict(role="User",content="fixture")], {"normal":True}, Path(temporary),
                    api_keys={"deepseek":"first", "siliconflow":"second"}, request_scheduler=scheduler)
            self.assertEqual(reservation[0], "siliconflow")
            self.assertEqual([p.assigned for p in scheduler.pools.values()], [0, 3])
            scheduler.release(reservation)
            self.assertTrue(all(p.assigned == 0 for p in scheduler.pools.values()))
        self.assertEqual(len(calls), 2)
        self.assertEqual(scheduler.snapshot()["disabled"], 1)
        self.assertEqual(scheduler.snapshot()["active_requests"], 0)

    def test_topic_wait_allows_next_file_to_start_without_holding_api(self):
        entered, release, next_file = threading.Event(), threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.txt"
            source.write_text("fixture", encoding="utf-8")
            def choose(*_args):
                entered.set()
                self.assertTrue(release.wait(3))
                return ()
            queue = BatchProcessingQueue(select_topics=choose)
            def generate(*_args, **options):
                if options["output_filename"].startswith("001"):
                    options["topic_selector"]({})
                else:
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(options["request_scheduler"].snapshot()["active_requests"], 0)
                    next_file.set()
                return SimpleNamespace(saved_files=[], summary_result=None)
            try:
                with patch("gui.batch_processing.generate_output_bundle", generate):
                    queue.add(BatchPlan("files",tuple(ItemPlan(str(source),("normal",)) for _ in range(2))),
                        output_parent=root,runtime_dir=root,api_keys={"deepseek":"key"})
                    self.assertTrue(next_file.wait(2))
                    release.set()
                    deadline = time.monotonic() + 3
                    while queue.has_work and time.monotonic() < deadline:
                        time.sleep(.01)
                self.assertEqual(queue.snapshot()[0]["failed"],0)
            finally:
                release.set()
                queue.close()
                self.assertTrue(queue.wait(3))

    def test_two_successes_explore_capacity_but_failures_end_warmup(self):
        self.success(1)
        self.assertEqual(self.scheduler.capacity(), 1)
        self.success(1)
        self.assertEqual(self.scheduler.capacity(), 2)
        self.setUp()
        self.failure(422)
        self.success(2)
        self.assertEqual(self.scheduler.capacity(), 1)
        self.success(2)
        self.assertEqual(self.scheduler.capacity(), 2)

    def test_progressive_cooldown_then_one_real_recovery_request(self):
        self.success(12)
        for code, delay in ((503, 0), (503, 2), (503, 4), (503, 8), (503, 16), (503, 32), (503, 60), (503, 60)):
            self.failure(code)
            pool = self.scheduler.pools[self.key]
            self.assertEqual(max(0, pool.cooldown-self.clock()), delay)
        self.clock.advance(61)
        self.assertEqual(self.scheduler.capacity(), 1)
        self.assertEqual(self.scheduler.snapshot()["recovering"], 1)
        self.success(1)
        self.assertEqual(self.scheduler.snapshot()["recovering"], 0)
        self.assertEqual(self.scheduler.pools[self.key].faults, 0)

    def test_inflight_success_cannot_undo_newer_failures(self):
        self.success(12)
        with self.scheduler.request(self.config, "fixture-secret", "old request"):
            self.failure(503)
            self.failure(503)
        pool = self.scheduler.pools[self.key]
        self.assertTrue(pool.recovering)
        self.assertEqual(pool.faults, 2)
        self.assertEqual(pool.stable, 0)

    def test_recovery_only_admits_one_request_and_wait_can_be_cancelled(self):
        self.failure(503)
        self.failure(503)
        self.clock.advance(3)
        cancel, waiting = threading.Event(), threading.Event()
        outcomes = []
        def second():
            waiting.set()
            try:
                with self.scheduler.request(self.config, "fixture-secret", "test", cancel):
                    outcomes.append("unexpected request")
            except asyncio.CancelledError:
                outcomes.append("cancelled")
        with self.scheduler.request(self.config, "fixture-secret", "recovery"):
            worker = threading.Thread(target=second)
            worker.start()
            self.assertTrue(waiting.wait(1))
            cancel.set()
            worker.join(2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(outcomes, ["cancelled"])
        self.assertEqual(self.scheduler.snapshot()["active_requests"], 0)

    def test_fallback_moves_reservation_but_media_request_does_not(self):
        other = summary.replace(self.config, provider="siliconflow")
        other_key, _ = self.scheduler.register("siliconflow", other, "second-secret")
        reservation = self.scheduler.reserve(["deepseek"], 4)
        with self.scheduler.file(7, reservation):
            with self.scheduler.request(other, "second-secret", "media", media_assets=[object()]):
                self.clock.advance()
            self.assertEqual(self.scheduler.pools[self.key].assigned, 4)
            self.scheduler.use(other, "second-secret")
            self.assertEqual(reservation[0], "siliconflow")
            self.assertEqual(self.scheduler.pools[self.key].assigned, 0)
            self.assertEqual(self.scheduler.pools[other_key].assigned, 4)
            self.scheduler.use(other, "second-secret")
            self.assertEqual(self.scheduler.pools[other_key].assigned, 4)
        self.scheduler.release(reservation)
        self.assertEqual(self.scheduler.pools[other_key].assigned, 0)
        self.assertFalse(hasattr(self.scheduler.context, "file"))

    def test_trace_pairs_requests_with_files_and_hides_sensitive_data(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"request_trace.jsonl"
            self.scheduler.trace_path = path
            reservation = self.scheduler.reserve(["deepseek"])
            with self.scheduler.file(3, reservation):
                with self.scheduler.request(self.config, "fixture-secret", "private conversation", request_kind=("memory_items",)):
                    self.clock.advance(.125)
            self.scheduler.release(reservation)
            text = path.read_text(encoding="utf-8")
            for secret in ("fixture-secret", "private conversation", "https://", hashlib.sha256(b"fixture-secret").hexdigest()):
                self.assertNotIn(secret, text)
            events = [json.loads(line) for line in text.splitlines()]
            self.assertEqual([event["event"] for event in events], ["file_start", "request_start", "request_end", "file_end"])
            self.assertEqual({event["file"] for event in events}, {3})
            self.assertEqual(events[1]["request"], events[2]["request"])
            self.assertEqual(events[2]["seconds"], .125)
            self.assertEqual(events[2]["active_requests"], 0)
            self.assertEqual(self.scheduler.snapshot()["peak_requests"], 1)

    def test_trace_write_failure_preserves_request_and_exposes_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.scheduler.trace_path = Path(temporary)  # Opening a directory as a file fails.
            self.success(1)
            self.assertTrue(self.scheduler.snapshot()["trace_error"])
            self.assertEqual(self.scheduler.snapshot()["active_requests"], 0)

    def test_admission_defers_without_bypassing_retry_after(self):
        self.failure(429, {"Retry-After":"600"})
        with patch.object(self.scheduler.condition, "wait", side_effect=lambda *_: self.clock.advance(61)):
            with self.assertRaises(APIUnavailable), self.scheduler.request(self.config, "fixture-secret", "test"):
                self.fail("request sent during Retry-After")
        self.assertEqual(self.scheduler.snapshot()["active_requests"], 0)
        self.assertEqual(self.scheduler.snapshot()["cooling"], 1)

    def test_gateway_stops_after_repeated_transport_failure_only_in_auto_mode(self):
        for automatic, expected in ((True, 2), (False, 5)):
            with self.subTest(automatic=automatic):
                self.setUp()
                config = summary.replace(self.config, retries=5)
                gateway = summary.SiliconFlowGateway(config, api_key="fixture-secret", sleep=lambda _: self.clock.advance(100),
                    request_scheduler=self.scheduler if automatic else None)
                with patch.object(summary, "urlopen", side_effect=OSError("transport")) as http:
                    with self.assertRaises(summary.GeminiSummaryError):
                        gateway.generate_json("test", {})
                self.assertEqual(http.call_count, expected)

    def test_cumulative_retry_budget_avoids_another_full_timeout(self):
        gateway = summary.SiliconFlowGateway(self.config, api_key="fixture-secret", sleep=lambda _: None,
            request_scheduler=self.scheduler)
        started = time.monotonic()
        with patch.object(summary, "urlopen", side_effect=TimeoutError("fixture")) as http, \
                patch("scripts.adaptive_concurrency.time.monotonic", side_effect=[started, started+181]):
            with self.assertRaises(summary.SummaryRequestTimeoutError):
                gateway.generate_json("test", {})
        self.assertEqual(http.call_count, 1)

    def test_google_auto_stops_repeated_service_failures(self):
        config = summary.replace(self.config, provider="gemini", retries=5)
        error = RuntimeError("fixture")
        error.code = 503
        with patch("google.genai.Client") as client:
            client.return_value.models.generate_content.side_effect = error
            gateway = summary.GeminiGateway(config, api_key="google-fixture", request_scheduler=self.scheduler,
                sleep=lambda _: self.clock.advance(100))
            with self.assertRaises(summary.GeminiSummaryError):
                gateway.generate_json("test", {})
            self.assertEqual(client.return_value.models.generate_content.call_count, 2)
            self.assertEqual(self.scheduler.snapshot()["active_requests"], 0)

    def test_final_batch_state_records_zero_active_jobs_and_released_load(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/"input.txt"
            source.write_text("fixture", encoding="utf-8")
            finished = threading.Event()
            queue = BatchProcessingQueue(on_item_done=lambda *_: finished.set())
            try:
                with patch("gui.batch_processing.generate_output_bundle", return_value=SimpleNamespace(saved_files=[], summary_result=None)):
                    queue.add(BatchPlan("files", (ItemPlan(str(source), ("normal",)),)),
                        output_parent=root, runtime_dir=root, api_keys={"deepseek":"key"})
                    self.assertTrue(finished.wait(3))
                    view = queue.snapshot()[0]
                    saved = json.loads((Path(view["output_dir"])/"batch_state.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["summaries"], 0)
                self.assertEqual(saved["auto_status"]["active_requests"], 0)
                self.assertTrue(all(pool["assigned"] == 0 for pool in saved["auto_status"]["pools"]))
            finally:
                queue.close()
                self.assertTrue(queue.wait(3))


if __name__ == "__main__":
    unittest.main()
