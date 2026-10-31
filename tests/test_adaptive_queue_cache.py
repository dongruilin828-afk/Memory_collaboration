"""Regression scenarios from the 36-file batch; no external API calls."""
import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from gui.batch_processing import BatchPlan, ItemPlan, BatchProcessingQueue
from gui.service import generate_output_bundle, generate_raw_markdown, gui_summary_attempt_configs
from scripts import gemini_summarizer as summary
from scripts.adaptive_concurrency import AdaptiveSummaryScheduler, APIDeferred, SummaryBudgetExceeded
from tests.test_adaptive_concurrency import Clock
from tests.test_gemini_summarizer import FakeGateway


MESSAGES = [{"role":"User", "content":"请解决报错"}, {"role":"AI", "content":"建议增加 try-except"}]


class QueueCacheTests(unittest.TestCase):
    def setUp(self):
        self.config = summary.SummaryConfig(provider="deepseek", model=summary.DEEPSEEK_DEFAULT_MODEL)

    def wait_queue(self, queue, timeout=8):
        deadline = time.monotonic()+timeout
        while queue.has_work and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertFalse(queue.has_work, queue.snapshot())

    def test_requeue_preserves_progress_and_topic_choice_without_marking_failure(self):
        calls, choices, completed = [], [], []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/"input.txt"
            source.write_text("fixture", encoding="utf-8")
            queue = BatchProcessingQueue(select_topics=lambda *_: choices.append(1) or ("T001",),
                on_item_done=lambda _view,item: completed.append(item["status"]))
            def generate(*_args, **options):
                calls.append(options["request_scheduler"].context.budget)
                self.assertEqual(options["topic_selector"]({"topics":[{"id":"T001"}]}), ("T001",))
                if len(calls)==1:
                    raise APIDeferred(retry_after=.01)
                return SimpleNamespace(saved_files=[], summary_result=None)
            try:
                with patch("gui.batch_processing.generate_output_bundle", generate):
                    queue.add(BatchPlan("files", (ItemPlan(str(source), ("normal",)),)),
                        output_parent=root, runtime_dir=root, api_keys={"deepseek":"key"})
                    self.wait_queue(queue)
                view = queue.snapshot()[0]
                self.assertEqual((len(calls),len(choices)), (2,1))
                self.assertIs(calls[0],calls[1])
                self.assertEqual(view["failed"],0)
                self.assertTrue(all(pool["assigned"]==0 for pool in view["auto_status"]["pools"]))
            finally:
                queue.close()
                self.assertTrue(queue.wait(3))
            self.assertEqual(completed,["completed"])

    def test_waiting_does_not_penalize_api_or_bypass_server_cooldown(self):
        clock = Clock()
        scheduler = AdaptiveSummaryScheduler(clock=clock)
        with self.assertRaises(HTTPError), scheduler.request(self.config,"key","test"):
            raise HTTPError("fixture",429,"limited",{"Retry-After":"600"},None)
        with patch.object(scheduler.condition,"wait",side_effect=lambda *_:clock.advance(4)):
            with self.assertRaises(APIDeferred), scheduler.request(self.config,"key","test"):
                self.fail("sent during cooldown")
        pool = next(iter(scheduler.pools.values()))
        self.assertEqual(pool.faults,0)
        self.assertEqual(scheduler.snapshot()["request_count"],1)
        self.assertGreater(pool.cooldown,clock())

    def test_intermittent_transport_faults_trigger_recovery_despite_intervening_success(self):
        clock = Clock()
        scheduler = AdaptiveSummaryScheduler(clock=clock)
        for failed in (True, False, True):
            clock.advance(5)
            try:
                with scheduler.request(self.config,"key","test"):
                    clock.advance()
                    if failed:
                        raise TimeoutError("fixture")
            except TimeoutError:
                pass
        pool = next(iter(scheduler.pools.values()))
        self.assertTrue(pool.recovering)
        self.assertEqual(pool.cooldown-clock(),2)

    def test_lower_throughput_pauses_growth_until_comparable_window_recovers(self):
        clock=Clock()
        scheduler=AdaptiveSummaryScheduler(clock=clock)
        def success(count):
            for _ in range(count):
                clock.advance()
                with scheduler.request(self.config,"key","same size"):
                    clock.advance()
        success(4)
        self.assertEqual(scheduler.capacity(),2)
        clock.advance(100)
        success(2)
        self.assertEqual(scheduler.capacity(),2)
        success(2)
        self.assertEqual(scheduler.capacity(),3)

    def test_dynamic_fallback_skips_cooling_candidate(self):
        scheduler = AdaptiveSummaryScheduler()
        keys = {"deepseek":"first","siliconflow":"second","gemini":"third"}
        configs = gui_summary_attempt_configs(self.config,keys)
        for config in configs:
            key,_ = scheduler.register(config.api_profile_id or config.provider,config,keys[config.provider])
            if config.provider=="siliconflow":
                scheduler.pools[key].cooldown=time.monotonic()+600
        seen=[]
        def generate(**options):
            seen.append(options["config"].provider)
            if len(seen)==1:
                raise summary.GeminiSummaryError("fixture failure")
            options["output_json"].write_text("{}",encoding="utf-8")
            options["output_markdown"].write_text("fixture",encoding="utf-8")
            return {"processing":{}}
        with tempfile.TemporaryDirectory() as temporary, patch.object(summary.SummaryConfig,"from_env",return_value=self.config), \
                patch.object(summary,"create_gateway",side_effect=lambda config,**_:SimpleNamespace(_api_key=keys[config.provider])), \
                patch.object(summary,"summarize_conversation",side_effect=generate):
            generate_output_bundle(MESSAGES,{"normal":True},Path(temporary),api_keys=keys,request_scheduler=scheduler,
                result_cache_dir=Path(temporary)/"cache")
        self.assertEqual(seen,["deepseek","gemini"])

    def test_completed_cache_is_found_before_trying_a_different_selected_api(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root/"cache"
            cached_config=gui_summary_attempt_configs(self.config,{"deepseek":"key"})[0]
            summary.summarize_conversation(MESSAGES,root,config=cached_config,gateway=FakeGateway(),
                output_json=root/"seed.json",output_markdown=root/"seed.md",result_cache_dir=cache,progress=lambda _:None)
            created=[]
            def create(config,**_):
                created.append(config.provider)
                return SimpleNamespace(_api_key="key")
            with patch.object(summary.SummaryConfig,"from_env",return_value=self.config), patch.object(summary,"create_gateway",side_effect=create):
                bundle=generate_output_bundle(MESSAGES,{"normal":True},root,output_filename="result.md",project_dir=root,
                    api_keys={"siliconflow":"other","deepseek":"key"},result_cache_dir=cache,
                    request_scheduler=AdaptiveSummaryScheduler())
            self.assertEqual(created,["deepseek"])
            self.assertTrue(bundle.summary_result["processing"]["cache_hit"])

    def test_simultaneous_duplicates_share_structured_result_and_keep_separate_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            source=root/"input.md"
            generate_raw_markdown(MESSAGES,source)
            calls=[]
            def create(config,**options):
                gateway=FakeGateway()
                gateway._api_key=options["api_key"]
                original=gateway.generate_json
                def generate(*args,**kwargs):
                    calls.append(args[1])
                    time.sleep(.08)
                    return original(*args,**kwargs)
                gateway.generate_json=generate
                return gateway
            choices=[]
            queue=BatchProcessingQueue(select_topics=lambda _batch,index,*_:choices.append(index) or ())
            try:
                with patch.object(summary.SummaryConfig,"from_env",return_value=self.config),patch.object(summary,"create_gateway",side_effect=create):
                    queue.add(BatchPlan("files",tuple(ItemPlan(str(source),("normal",)) for _ in range(2))),
                        output_parent=root,runtime_dir=root,api_keys={"deepseek":"key","siliconflow":"other"})
                    self.wait_queue(queue)
                view=queue.snapshot()[0]
                self.assertEqual(view["failed"],0)
                self.assertEqual(len(calls),2)
                self.assertEqual(sorted(choices),[1,2])
                self.assertEqual(len({item["output_dir"] for item in view["items"]}),2)
                trace=(Path(view["output_dir"])/"request_trace.jsonl").read_text(encoding="utf-8")
                self.assertIn('"event": "duplicate_wait"',trace)
            finally:
                queue.close()
                self.assertTrue(queue.wait(3))

    def test_full_fingerprint_separates_different_attachment_bytes_and_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name,content in (("a","版本甲"),("b","版本乙")):
                (root/name).mkdir()
                (root/name/"note.txt").write_text(content,encoding="utf-8")
            messages=[{"role":"User","content":"请总结[附件](note.txt)"}]
            assets=summary.discover_media(messages,root,root/"a",self.config)
            self.assertEqual(len(assets),1)
            fingerprint=lambda directory,config:summary.completed_summary_fingerprint(messages,config,root,root/directory,None)
            self.assertNotEqual(fingerprint("a",self.config),fingerprint("b",self.config))
            self.assertNotEqual(fingerprint("a",self.config),fingerprint("a",summary.replace(self.config,thinking_level="minimal")))

    def test_only_failed_requests_consume_budget_across_providers(self):
        clock=Clock()
        scheduler=AdaptiveSummaryScheduler(clock=clock)
        config=summary.replace(self.config,request_timeout_seconds=2)
        scheduler.register("deepseek",config,"key")
        reservation=scheduler.reserve(["deepseek"])
        budget={"spent":0,"waited":0}
        with scheduler.file(1,reservation,budget):
            for _ in range(5):
                with scheduler.request(config,"key","successful progress"):
                    clock.advance(1.5)
            clock.advance(100)  # User interaction is outside request slots.
            other=summary.replace(config,provider="siliconflow")
            for candidate,key in ((config,"key"),(other,"other")):
                with self.assertRaises(TimeoutError),scheduler.request(candidate,key,"failure") as ticket:
                    self.assertEqual(ticket["timeout"],2)
                    clock.advance(2)
                    raise TimeoutError("fixture")
            with self.assertRaises(SummaryBudgetExceeded),scheduler.request(other,"other","fourth"):
                self.fail("budget bypassed on fallback")
        scheduler.release(reservation)
        self.assertEqual(budget["spent"],11.5)
        self.assertEqual(budget["failed_seconds"],4)
        self.assertEqual(scheduler.snapshot()["active_requests"],0)

    def test_async_request_timeout_cancels_transport_and_releases_permit(self):
        scheduler=AdaptiveSummaryScheduler()
        scheduler.register("deepseek",self.config,"key")
        reservation=scheduler.reserve(["deepseek"])
        cleaned=[]
        async def slow(_request):
            try:
                await asyncio.sleep(1)
            finally:
                cleaned.append(True)
        gateway=summary.SiliconFlowGateway(summary.replace(self.config,retries=1,request_timeout_seconds=.03),api_key="key",
            request_scheduler=scheduler,cancel_event=threading.Event())
        with scheduler.file(1,reservation,{"spent":0,"waited":0,"limit":.03}),patch.object(gateway,"_request_async",slow):
            with self.assertRaises(summary.SummaryRequestTimeoutError):
                gateway.generate_json("test",{})
        self.assertEqual(cleaned,[True])
        self.assertEqual(scheduler.snapshot()["active_requests"],0)
        self.assertEqual(sum(pool.faults for pool in scheduler.pools.values()),1)
        scheduler.release(reservation)

    def test_truncation_metadata_is_numeric_only_and_not_retried_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace=Path(temporary)/"trace.jsonl"
            scheduler=AdaptiveSummaryScheduler(trace_path=trace)
            response=MagicMock()
            response.__enter__.return_value.read.return_value=json.dumps({"choices":[{"finish_reason":"length","message":{"content":"private response"}}],
                "usage":{"total_tokens":123,"completion_tokens":100,"private":"secret-value"}}).encode()
            gateway=summary.SiliconFlowGateway(self.config,api_key="secret-key",request_scheduler=scheduler)
            with patch.object(summary,"urlopen",return_value=response) as http:
                with self.assertRaises(summary.SummaryOutputTruncatedError):
                    gateway.generate_json("private prompt",{})
            self.assertEqual(http.call_count,1)
            text=trace.read_text(encoding="utf-8")
            self.assertNotIn("private",text)
            self.assertNotIn("secret",text)
            end=json.loads(text.splitlines()[-1])
            self.assertEqual(end["finish_reason"],"length")
            self.assertEqual(end["usage"],{"total_tokens":123,"completion_tokens":100})

    def test_chunk_repair_is_once_per_api_and_default_manual_path_is_unchanged(self):
        for automatic in (False,True):
            with self.subTest(automatic=automatic),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)
                seen=[]
                def generate(**options):
                    config=options["config"]
                    seen.append((config.provider,config.chunk_chars))
                    if config.provider=="deepseek":
                        raise summary.GeminiSummaryError("fixture JSONDecodeError")
                    options["output_json"].write_text("{}",encoding="utf-8")
                    options["output_markdown"].write_text("fixture",encoding="utf-8")
                    return {"processing":{}}
                with patch.object(summary.SummaryConfig,"from_env",return_value=self.config), \
                        patch.object(summary,"create_gateway",side_effect=lambda _config,**_:SimpleNamespace(_api_key="key")), \
                        patch.object(summary,"summarize_conversation",side_effect=generate):
                    generate_output_bundle([{"role":"User","content":"长文本"*3000}],{"normal":True},root,project_dir=root,
                        api_keys={"deepseek":"key","siliconflow":"other"},result_cache_dir=root/"cache",
                        request_scheduler=AdaptiveSummaryScheduler() if automatic else None)
                self.assertEqual(sum(provider=="deepseek" for provider,_ in seen),2 if automatic else 1)
                if automatic:
                    self.assertLess(seen[1][1],seen[0][1])

    def test_repaired_chunk_size_survives_a_local_deferral(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            source=root/"input.txt"
            source.write_text("长文本"*3000,encoding="utf-8")
            seen=[]
            def generate(**options):
                seen.append(options["config"].chunk_chars)
                if len(seen)==1:
                    raise summary.GeminiSummaryError("fixture JSONDecodeError")
                if len(seen)==2:
                    raise APIDeferred(retry_after=.01)
                options["output_json"].write_text("{}",encoding="utf-8")
                options["output_markdown"].write_text("fixture",encoding="utf-8")
                return {"processing":{}}
            queue=BatchProcessingQueue()
            try:
                with patch.object(summary.SummaryConfig,"from_env",return_value=self.config), \
                        patch.object(summary,"create_gateway",side_effect=lambda _config,**_:SimpleNamespace(_api_key="key")), \
                        patch.object(summary,"summarize_conversation",side_effect=generate):
                    queue.add(BatchPlan("files",(ItemPlan(str(source),("normal",)),)),
                        output_parent=root,runtime_dir=root,api_keys={"deepseek":"key"})
                    self.wait_queue(queue)
                self.assertEqual(len(seen),3)
                self.assertLess(seen[1],seen[0])
                self.assertEqual(seen[1],seen[2])
                self.assertEqual(queue.snapshot()[0]["failed"],0)
            finally:
                queue.close()
                self.assertTrue(queue.wait(3))

    def test_cancelled_owner_releases_duplicate_claim(self):
        scheduler=AdaptiveSummaryScheduler()
        scheduler.register("deepseek",self.config,"key")
        reservation=scheduler.reserve(["deepseek"])
        with self.assertRaises(asyncio.CancelledError),scheduler.file(1,reservation):
            scheduler.claim(["fingerprint"])
            raise asyncio.CancelledError()
        with scheduler.file(2,reservation):
            scheduler.claim(["fingerprint"])
        scheduler.release(reservation)
        self.assertEqual(scheduler.flights,{})

    def test_auto_media_timeout_preserves_failure_state_and_stops_before_text_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/"note.txt").write_text("实际附件内容",encoding="utf-8")
            gateway=FakeGateway()
            gateway._request_scheduler=AdaptiveSummaryScheduler()
            calls=[]
            def timeout(_prompt,schema,media_assets=None):
                calls.append(schema)
                raise summary.SummaryRequestTimeoutError("fixture")
            gateway.generate_json=timeout
            with self.assertRaises(summary.SummaryRequestTimeoutError):
                summary.summarize_conversation([{"role":"User","content":"请总结[附件](note.txt)"}],root,
                    config=self.config,gateway=gateway,output_json=root/"out.json",output_markdown=root/"out.md",progress=lambda _:None)
            self.assertEqual(calls,[summary.MEDIA_SCHEMA])
            progress=json.loads((root/"out_progress.tmp").read_text(encoding="utf-8"))
            self.assertEqual(progress["media"][0]["status"],"analysis_failed")


if __name__=="__main__":
    unittest.main()
