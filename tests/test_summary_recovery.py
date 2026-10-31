"""Failures recover automatically; normal long-running progress is never a retry cost."""
import asyncio
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from gui.batch_processing import BatchPlan, ItemPlan, BatchProcessingQueue
from gui.service import generate_raw_markdown
from scripts import gemini_summarizer as summary
from scripts.adaptive_concurrency import AdaptiveSummaryScheduler, SummaryBudgetExceeded
from tests.test_adaptive_concurrency import Clock
from tests.test_gemini_summarizer import FakeGateway
from tests.test_adaptive_queue_cache import MESSAGES


class RecoveryTests(unittest.TestCase):
    def wait_for(self, predicate, timeout=5):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertTrue(predicate())

    def test_four_successful_chunks_leave_full_timeout_for_global_synthesis(self):
        clock=Clock()
        scheduler=AdaptiveSummaryScheduler(clock=clock)
        config=summary.SummaryConfig(provider="deepseek",request_timeout_seconds=180)
        scheduler.register("deepseek",config,"key")
        reservation=scheduler.reserve(["deepseek"])
        budget={"spent":0,"waited":0}
        with scheduler.file(15,reservation,budget):
            for _ in range(4):
                with scheduler.request(config,"key","chunk"):
                    clock.advance(86.5)
            with scheduler.request(config,"key","global") as ticket:
                self.assertEqual(ticket["timeout"],180)
                clock.advance(100)
        self.assertEqual(budget["spent"],446)
        self.assertEqual(budget.get("failed_seconds",0),0)
        scheduler.release(reservation)

    def test_transient_failure_recovers_without_premature_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/"input.txt";source.write_text("fixture",encoding="utf-8")
            calls=[];done=[]
            queue=BatchProcessingQueue(on_item_done=lambda _view,item:done.append(item["status"]))
            def generate(batch,item):
                state=batch.budgets[item["index"]]
                calls.append(state)
                if len(calls)==1:
                    state.update(failed_seconds=360,failed_configs={"old"},timed_out_providers={"deepseek"},repairs={"deepseek":4000})
                    raise SummaryBudgetExceeded("temporary failure budget")
                self.assertEqual(state["failed_seconds"],0)
                self.assertNotIn("failed_configs",state)
                self.assertNotIn("timed_out_providers",state)
                self.assertEqual(state["repairs"],{"deepseek":4000})
                return []
            try:
                with patch("gui.batch_processing.AUTO_RETRY_DELAYS",(.01,.02)),patch.object(queue,"_generate",generate):
                    queue.add(BatchPlan("files",(ItemPlan(str(source),("normal",)),)),output_parent=root,runtime_dir=root,api_keys={"deepseek":"key"})
                    self.wait_for(lambda:not queue.has_work)
                view=queue.snapshot()[0]
                self.assertEqual(view["failed"],0)
                self.assertEqual(view["items"][0]["auto_retries"],1)
                self.assertEqual(len(calls),2)
                self.assertIsNone(view["items"][0]["error"])
            finally:
                queue.close();self.assertTrue(queue.wait(3))
            self.assertEqual(done,["completed"])

    def test_persistent_failure_is_bounded_and_manual_mode_keeps_its_contract(self):
        for automatic in (True,False):
            with self.subTest(automatic=automatic),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);source=root/"input.txt";source.write_text("fixture",encoding="utf-8")
                queue=BatchProcessingQueue()
                try:
                    with patch("gui.batch_processing.AUTO_RETRY_DELAYS",(.01,.02)),patch.object(queue,"_generate",side_effect=summary.GeminiSummaryError("temporary")) as generate:
                        queue.add(BatchPlan("files",(ItemPlan(str(source),("normal",)),),None if automatic else 1),
                            output_parent=root,runtime_dir=root,api_keys={"deepseek":"key"})
                        self.wait_for(lambda:not queue.has_work)
                    view=queue.snapshot()[0]
                    self.assertEqual(generate.call_count,3 if automatic else 1)
                    self.assertEqual(view["failed"],1)
                    if automatic:
                        self.assertIn("已自动重试2次",view["items"][0]["error"])
                finally:
                    queue.close();self.assertTrue(queue.wait(3))

    def test_cancelling_during_recovery_cooldown_stops_further_attempts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/"input.txt";source.write_text("fixture",encoding="utf-8")
            queue=BatchProcessingQueue()
            try:
                with patch.object(queue,"_generate",side_effect=summary.GeminiSummaryError("temporary")) as generate:
                    identifier=queue.add(BatchPlan("files",(ItemPlan(str(source),("normal",)),)),output_parent=root,runtime_dir=root,api_keys={"deepseek":"key"})
                    self.wait_for(lambda:queue.snapshot()[0]["items"][0].get("auto_retries")==1)
                    queue.cancel(identifier)
                    self.wait_for(lambda:not queue.has_work)
                    self.assertEqual(generate.call_count,1)
                self.assertEqual(queue.snapshot()[0]["items"][0]["status"],"cancelled")
            finally:
                queue.close();self.assertTrue(queue.wait(3))

    def test_disabled_credentials_are_not_blindly_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/"input.txt";source.write_text("fixture",encoding="utf-8")
            queue=BatchProcessingQueue();calls=[]
            def generate(batch,_item):
                calls.append(1)
                for pool in batch.scheduler.pools.values():pool.disabled=True
                raise summary.GeminiSummaryError("HTTP401")
            try:
                with patch.object(queue,"_generate",generate):
                    queue.add(BatchPlan("files",(ItemPlan(str(source),("normal",)),)),output_parent=root,runtime_dir=root,api_keys={"deepseek":"key"})
                    self.wait_for(lambda:not queue.has_work)
                self.assertEqual(calls,[1])
                self.assertEqual(queue.snapshot()[0]["failed"],1)
            finally:
                queue.close();self.assertTrue(queue.wait(3))

    def test_recovery_tasks_are_serialized_while_normal_tasks_can_overlap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/"input.txt";source.write_text("fixture",encoding="utf-8")
            queue=BatchProcessingQueue();barrier=threading.Barrier(2);active=peak=0;lock=threading.Lock()
            def generate(_batch,item):
                nonlocal active,peak
                if not item.get("auto_retries"):
                    barrier.wait(2)
                    raise summary.GeminiSummaryError("temporary")
                with lock:active+=1;peak=max(peak,active)
                time.sleep(.05)
                with lock:active-=1
                return []
            try:
                with patch("gui.batch_processing.AUTO_RETRY_DELAYS",(.01,.02)),patch.object(queue,"_generate",generate):
                    queue.add(BatchPlan("files",tuple(ItemPlan(str(source),("normal",)) for _ in range(2))),
                        output_parent=root,runtime_dir=root,api_keys={"deepseek":"key","siliconflow":"other"})
                    self.wait_for(lambda:not queue.has_work)
                self.assertEqual(queue.snapshot()[0]["failed"],0)
                self.assertEqual(peak,1)
            finally:
                queue.close();self.assertTrue(queue.wait(3))

    def test_retry_resumes_successful_chunks_instead_of_repeating_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/"input.md";generate_raw_markdown(MESSAGES,source)
            calls=[];globals_seen=[]
            def create(_config,**options):
                gateway=FakeGateway();gateway._api_key=options["api_key"];original=gateway.generate_json
                def generate(prompt,schema,media_assets=None):
                    calls.append(schema)
                    if schema is summary.FINAL_SCHEMA:
                        globals_seen.append(1)
                        if len(globals_seen)==1:raise summary.SummaryRequestTimeoutError("temporary global timeout")
                    return original(prompt,schema,media_assets)
                gateway.generate_json=generate
                return gateway
            queue=BatchProcessingQueue()
            try:
                with patch("gui.batch_processing.AUTO_RETRY_DELAYS",(.01,.02)),patch.object(summary,"create_gateway",side_effect=create):
                    queue.add(BatchPlan("files",(ItemPlan(str(source),("normal",)),)),output_parent=root,runtime_dir=root,api_keys={"deepseek":"key"})
                    self.wait_for(lambda:not queue.has_work)
                self.assertEqual(queue.snapshot()[0]["failed"],0)
                self.assertEqual(sum(schema is summary.CHUNK_SCHEMA for schema in calls),1)
                self.assertEqual(sum(schema is summary.FINAL_SCHEMA for schema in calls),2)
            finally:
                queue.close();self.assertTrue(queue.wait(3))

    def test_truncation_retry_reduces_chunk_again_in_a_new_recovery_round(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/"input.txt";source.write_text("长文本"*6000,encoding="utf-8")
            sizes=[]
            def generate(**options):
                sizes.append(options["config"].chunk_chars)
                if len(sizes)<4:raise summary.SummaryOutputTruncatedError("fixture length")
                options["output_json"].write_text("{}",encoding="utf-8");options["output_markdown"].write_text("fixture",encoding="utf-8")
                return {"processing":{}}
            queue=BatchProcessingQueue()
            try:
                with patch("gui.batch_processing.AUTO_RETRY_DELAYS",(.01,.02)), \
                        patch.object(summary,"create_gateway",side_effect=lambda *_args,**_options:FakeKeyGateway()), \
                        patch.object(summary,"summarize_conversation",side_effect=generate):
                    queue.add(BatchPlan("files",(ItemPlan(str(source),("normal",)),)),output_parent=root,runtime_dir=root,api_keys={"deepseek":"key"})
                    self.wait_for(lambda:not queue.has_work)
                self.assertEqual(queue.snapshot()[0]["failed"],0)
                self.assertEqual(len(sizes),4)
                self.assertEqual(sizes[1],sizes[2])
                self.assertLess(sizes[3],sizes[2])
            finally:
                queue.close();self.assertTrue(queue.wait(3))


class FakeKeyGateway:
    _api_key="key"


if __name__=="__main__":unittest.main()
