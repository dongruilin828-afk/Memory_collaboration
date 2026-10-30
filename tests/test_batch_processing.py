"""Queue isolation, stage overlap and input snapshots without live accounts."""
import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gui import batch_processing as batch


def plan(kind="links", count=2, modes=("raw",), concurrency=3):
    return batch.BatchPlan(kind, tuple(batch.ItemPlan(f"https://chatgpt.com/c/item{i}", modes)
                                      for i in range(count)), concurrency)


class BatchPlanTests(unittest.TestCase):
    def test_plain_text_keeps_indentation_and_exported_messages_keep_their_roles(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "file.md"
            text = "# title\n\n  - nested\n\n```python\n    value = 1\n```\n"
            path.write_text(text, encoding="utf-8")
            self.assertEqual(batch.load_input_messages(path), [{"role": "User", "content": text}])
            path.write_text("## 🔵 👤 用户提问\n\nquestion\n\n## 🟣 🤖 AI 回答\n\nanswer", encoding="utf-8")
            self.assertEqual(batch.load_input_messages(path), [dict(role="User", content="question"), dict(role="AI", content="answer")])

    def test_normalizes_http_and_validates_modes_and_concurrency(self):
        value = batch.BatchPlan("links", (batch.ItemPlan("http://chatgpt.com/c/one", ("detailed", "raw")),), 1).validate()
        self.assertEqual(value.items[0].source, "https://chatgpt.com/c/one")
        self.assertEqual(value.items[0].modes, ("raw", "detailed"))
        for concurrency in (0, 4, True, "2"):
            with self.subTest(concurrency=concurrency), self.assertRaises(ValueError):
                plan(concurrency=concurrency).validate()
        for modes in ((), ("unknown",)):
            with self.subTest(modes=modes), self.assertRaises(ValueError):
                plan(modes=modes).validate()

    def test_files_must_exist_and_do_not_offer_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "file.MD"
            path.write_text("hello", encoding="utf-8")
            valid = batch.BatchPlan("files", (batch.ItemPlan(str(path), ("normal",)),), 2)
            self.assertEqual(valid.validate().items[0].source, str(path.resolve()))
            for item in (batch.ItemPlan(str(path), ("raw",)), batch.ItemPlan(str(path.with_suffix('.pdf')), ("simple",))):
                with self.subTest(item=item), self.assertRaises(ValueError):
                    batch.BatchPlan("files", (item,), 1).validate()


class BatchQueueTests(unittest.TestCase):
    def test_file_auto_limit_and_selected_api_rotation(self):
        source = self.root / "auto.txt"
        source.write_text("正文", encoding="utf-8")
        value = batch.BatchPlan("files", tuple(batch.ItemPlan(str(source), ("simple",)) for _ in range(6)),
                                None, ("gemini", "deepseek"))
        active = peak = 0
        lock = threading.Lock()
        def generate(*args, **kwargs):
            nonlocal active, peak
            index = int(kwargs["output_filename"].split("_")[0])
            self.assertEqual(set(kwargs["api_keys"]), {"gemini", "deepseek"})
            self.assertEqual(next(iter(kwargs["api_keys"])), ("gemini", "deepseek")[(index-1) % 2])
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(.04)
                return self.summary(*args, **kwargs)
            finally:
                with lock:
                    active -= 1
        with patch.object(batch, "generate_output_bundle", generate):
            self.add(value, api_keys={"gemini": "a", "deepseek": "b", "siliconflow": "excluded"})
            self.wait_for(lambda: not self.queue.has_work)
        self.assertEqual(peak, 2)
        self.assertEqual(self.queue.snapshot()[0]["requested_concurrency"], None)
        self.assertEqual(self.queue.snapshot()[0]["done"], 6)

    def test_manual_file_limit_can_reach_ten(self):
        source = self.root / "ten.txt"
        source.write_text("正文", encoding="utf-8")
        value = batch.BatchPlan("files", tuple(batch.ItemPlan(str(source), ("simple",)) for _ in range(10)), 10)
        gate = threading.Barrier(10, timeout=4)
        def generate(*args, **kwargs):
            gate.wait()
            return self.summary(*args, **kwargs)
        with patch.object(batch, "generate_output_bundle", generate):
            self.add(value, api_keys={"gemini": "key"})
            self.wait_for(lambda: not self.queue.has_work)
        self.assertEqual(self.queue.snapshot()[0]["failed"], 0)
        self.assertEqual(len(self.histories), 10)
        with self.assertRaises(ValueError):
            plan(concurrency=10).validate()

    def test_reordering_running_summary_batch_drains_current_items_then_resumes(self):
        source = self.root / "work.txt"
        source.write_text("正文", encoding="utf-8")
        first_two = threading.Event()
        release = [threading.Event(), threading.Event(), threading.Event()]
        for event in release:
            self.addCleanup(event.set)
        calls, ids = [], {}
        lock = threading.Lock()
        def generate(current, item):
            with lock:
                calls.append((current.id, item["index"]))
                if len(calls) == 2:
                    first_two.set()
            if current.plan.concurrency == 2 and item["index"] <= 2:
                self.assertTrue(release[item["index"] - 1].wait(4))
            elif current.plan.concurrency == 1:
                ids["second_entered"] = True
                self.assertTrue(release[2].wait(4))
            return []
        with patch.object(self.queue, "_generate", generate):
            first = self.add(batch.BatchPlan("files", tuple(batch.ItemPlan(str(source), ("simple",)) for _ in range(4)), 2), api_keys={"gemini": "key"})
            self.assertTrue(first_two.wait(3))
            second = self.add(batch.BatchPlan("files", (batch.ItemPlan(str(source), ("simple",)),), 1), api_keys={"gemini": "key"})
            self.assertTrue(self.queue.move(first, second))
            release[0].set()
            time.sleep(.05)
            self.assertNotIn("second_entered", ids)
            release[1].set()
            self.wait_for(lambda: ids.get("second_entered"))
            self.assertEqual(sum(key == first for key, _ in calls), 2)
            self.assertEqual(next(view for view in self.queue.snapshot() if view["id"] == first)["status"], "paused")
            release[2].set()
            self.wait_for(lambda: not self.queue.has_work)
        self.assertEqual(sorted(index for key, index in calls if key == first), [1, 2, 3, 4])
        self.assertEqual(len(self.histories), 5)

    def test_link_preemption_resumes_existing_outputs_without_recapture(self):
        from gui import batch_capture as capture_module
        from gui.service import FetchResult
        from tests.test_batch_capture import Context, playwright
        first_two, second_entered = threading.Event(), threading.Event()
        release_first, release_second = threading.Event(), threading.Event()
        self.addCleanup(release_first.set)
        self.addCleanup(release_second.set)
        calls, contexts = [], []
        async def launch(*args, **kwargs):
            context = Context()
            contexts.append(context)
            return context, "chromium"
        async def fetch(url, **kwargs):
            calls.append(url)
            if url.endswith(("a0", "a1")):
                if len(calls) == 2:
                    first_two.set()
                await asyncio.to_thread(release_first.wait, 4)
            elif url.endswith("second"):
                second_entered.set()
                await asyncio.to_thread(release_second.wait, 4)
            return FetchResult(html="body", messages=[dict(role="User", content=url)], image_map={}, document_map={})
        links = tuple(batch.ItemPlan(f"https://chatgpt.com/c/a{i}", ("raw",)) for i in range(5))
        with patch.object(capture_module, "async_playwright", playwright), \
             patch.object(capture_module, "launch_browser_context", launch), \
             patch.object(capture_module, "fetch_chat_pipeline", fetch):
            first = self.add(batch.BatchPlan("links", links, 2))
            self.assertTrue(first_two.wait(3))
            second = self.add(batch.BatchPlan("links", (batch.ItemPlan("https://chatgpt.com/c/second", ("raw",)),), 1))
            self.assertTrue(self.queue.move(second, first))
            self.assertFalse(second_entered.is_set())
            release_first.set()
            self.assertTrue(second_entered.wait(3))
            paused = next(view for view in self.queue.snapshot() if view["id"] == first)
            self.assertEqual(paused["status"], "paused")
            self.assertEqual(paused["done"], 2)
            manifest = json.loads((Path(paused["output_dir"]) / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["paused"])
            original = Path(paused["items"][0]["saved_files"][0]).read_bytes()
            release_second.set()
            self.wait_for(lambda: not self.queue.has_work)
        self.assertEqual(len(calls), 6)
        self.assertEqual(len(set(calls)), 6)
        self.assertEqual(len(contexts), 3)
        self.assertTrue(all(context.closed for context in contexts))
        final = next(view for view in self.queue.snapshot() if view["id"] == first)
        self.assertEqual(final["done"], 5)
        self.assertEqual(Path(final["items"][0]["saved_files"][0]).read_bytes(), original)

    def test_priority_handoff_does_not_disable_overlap_for_later_independent_batches(self):
        self.queue.browser_lock.acquire()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def generate(current, item):
            entered.set()
            self.assertTrue(release.wait(4))
            return []
        with patch.object(batch, "capture_links", self.capture), patch.object(self.queue, "_generate", generate):
            first, second = self.add(plan(count=1)), self.add(plan(count=1))
            self.assertTrue(self.queue.move(first, second))
            self.queue.browser_lock.release()
            self.wait_for(lambda: not self.queue.has_work)
            path = self.root / "next-wave.txt"
            path.write_text("正文", encoding="utf-8")
            file_id = self.add(batch.BatchPlan("files", (batch.ItemPlan(str(path), ("simple",)),), 1), api_keys={"gemini": "key"})
            self.assertTrue(entered.wait(3))
            link_id = self.add(plan(count=1))
            self.wait_for(lambda: next(view for view in self.queue.snapshot() if view["id"] == link_id)["status"] == "completed")
            self.assertEqual(next(view for view in self.queue.snapshot() if view["id"] == file_id)["status"], "running")
            release.set()
            self.wait_for(lambda: not self.queue.has_work)

    def test_handoff_leaves_waiting_summaries_queued_instead_of_draining_the_entire_backlog(self):
        entered, urgent_entered = threading.Event(), threading.Event()
        release, urgent_release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        self.addCleanup(urgent_release.set)
        def generate(current, item):
            if current.plan.kind == "links" and item["index"] == 1:
                entered.set()
                self.assertTrue(release.wait(4))
            if current.plan.kind == "files":
                urgent_entered.set()
                self.assertTrue(urgent_release.wait(4))
            return []
        with patch.object(batch, "capture_links", self.capture), patch.object(self.queue, "_generate", generate):
            first = self.add(plan(count=3, modes=("simple",), concurrency=1), api_keys={"gemini": "key"})
            self.assertTrue(entered.wait(3))
            self.wait_for(lambda: not self.queue.capture_busy)
            path = self.root / "urgent.txt"
            path.write_text("正文", encoding="utf-8")
            urgent = self.add(batch.BatchPlan("files", (batch.ItemPlan(str(path), ("simple",)),), 1), api_keys={"gemini": "key"})
            self.assertTrue(self.queue.move(urgent, first))
            release.set()
            self.assertTrue(urgent_entered.wait(3))
            original = next(view for view in self.queue.snapshot() if view["id"] == first)
            self.assertEqual(original["done"], 1)
            self.assertEqual([item["status"] for item in original["items"]], ["completed", "ready", "ready"])
            self.assertEqual(original["status"], "paused")
            urgent_release.set()
            self.wait_for(lambda: not self.queue.has_work)

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.addCleanup(self.scratch.cleanup)
        self.histories = []
        self.queue = batch.BatchProcessingQueue(on_item_done=lambda *args: self.histories.append(args))
        self.addCleanup(self.close)

    def close(self):
        self.queue.close()
        self.assertTrue(self.queue.wait(5), "workers must release their resources")

    def add(self, value, **kwargs):
        return self.queue.add(value, output_parent=self.root, runtime_dir=self.root / "runtime", **kwargs)

    def wait_for(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        self.fail(f"Queue did not reach expected state: {self.queue.snapshot()}")

    def complete_record(self, root, index, source, save_raw=True):
        target = root / f"{index:03d}_ChatGPT"
        target.mkdir(parents=True)
        (target / "result.json").write_text(json.dumps({"messages": [{"role": "User", "content": source}]}), encoding="utf-8")
        saved = []
        if save_raw:
            path = target / "export.md"
            path.write_text(source, encoding="utf-8")
            saved.append(str(path))
        return dict(index=index, output_dir=str(target), status="completed", saved_files=saved,
                    error=None, warnings=[], elapsed_seconds=.05, wait_seconds=0)

    async def capture(self, links, root, **options):
        records = []
        for index, source in enumerate(links, 1):
            options["progress"](index, len(links), "reading")
            record = self.complete_record(root, index, source, options["save_raw"][index-1])
            records.append(record)
            options["on_result"](record)
        return records

    @staticmethod
    def summary(messages, modes, save_dir, *, output_filename, **kwargs):
        target = Path(save_dir) / Path(output_filename).stem / output_filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(messages[0]["content"], encoding="utf-8")
        return SimpleNamespace(saved_files=[target], summary_result=None)

    def test_raw_defaults_keep_independent_results_without_api(self):
        with patch.object(batch, "capture_links", self.capture):
            self.add(plan())
            self.wait_for(lambda: not self.queue.has_work)
        view = self.queue.snapshot()[0]
        self.assertEqual(view["status"], "completed")
        self.assertEqual(view["done"], 2)
        self.assertEqual(len(self.histories), 2)
        self.assertEqual([len(item["saved_files"]) for item in view["items"]], [1, 1])

    def test_summary_overlaps_next_capture_and_respects_each_raw_selection(self):
        entered, release, next_capture = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def summary(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return self.summary(*args, **kwargs)
        async def capture(links, root, **options):
            records = []
            for index, source in enumerate(links, 1):
                record = self.complete_record(root, index, source, options["save_raw"][index-1])
                options["on_result"](record)
                records.append(record)
                if index == 1:
                    self.assertTrue(entered.wait(2), "summary must start before capture finishes")
                else:
                    next_capture.set()
            return records
        value = batch.BatchPlan("links", (
            batch.ItemPlan("https://chatgpt.com/c/one", ("normal",)),
            batch.ItemPlan("https://chatgpt.com/c/two", ("raw", "simple"))), 2)
        with patch.object(batch, "capture_links", capture), patch.object(batch, "generate_output_bundle", summary):
            self.add(value, api_keys={"custom": "private-key"})
            self.assertTrue(next_capture.wait(2))
            self.assertTrue(self.queue.has_work)
            release.set()
            self.wait_for(lambda: not self.queue.has_work)
        items = self.queue.snapshot()[0]["items"]
        self.assertEqual([len(item["saved_files"]) for item in items], [1, 2])
        self.assertFalse((Path(items[0]["output_dir"]) / "export.md").exists())
        self.assertTrue((Path(items[1]["output_dir"]) / "export.md").exists())
        for path in self.root.rglob("*.json"):
            self.assertNotIn("private-key", path.read_text(encoding="utf-8"))

    def test_pending_batches_can_edit_move_delete_while_browser_is_occupied(self):
        self.queue.browser_lock.acquire()
        with patch.object(batch, "capture_links", self.capture):
            first = self.add(plan(count=1))
            second = self.add(plan(count=2))
            self.assertTrue(self.queue.move(second, first))
            self.queue.edit(second, plan(count=3, concurrency=1))
            self.queue.remove(first)
            snapshot = self.queue.snapshot()
            self.assertEqual([item["id"] for item in snapshot], [second])
            self.assertFalse(snapshot[0]["started"])
            self.assertEqual(snapshot[0]["total"], 3)
            self.assertEqual(snapshot[0]["concurrency"], 1)
            self.queue.browser_lock.release()
            self.wait_for(lambda: not self.queue.has_work)
        self.assertEqual(self.queue.snapshot()[0]["done"], 3)

    def test_existing_summary_does_not_hold_browser_lock_and_file_assets_use_source_directory(self):
        source = self.root / "conversation.md"
        source.write_text("# 用户\n\nhello\n\n# AI\n\nworld", encoding="utf-8")
        value = batch.BatchPlan("files", (batch.ItemPlan(str(source), ("simple",)),), 1)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def summary(*args, **kwargs):
            self.assertEqual(kwargs["source_dir"], source.parent)
            entered.set()
            self.assertTrue(release.wait(3))
            return self.summary(*args, **kwargs)
        with patch.object(batch, "generate_output_bundle", summary), patch.object(batch, "capture_links", self.capture):
            self.add(value, api_keys={"custom": "secret"})
            self.assertTrue(entered.wait(2))
            self.add(plan(count=1))
            self.wait_for(lambda: self.queue.snapshot()[1]["status"] == "completed")
            self.assertEqual(self.queue.snapshot()[0]["status"], "running")
            release.set()
            self.wait_for(lambda: not self.queue.has_work)

    def test_per_batch_summary_limit_failure_isolation_and_private_configuration_snapshot(self):
        source = self.root / "conversation.txt"
        source.write_text("hello", encoding="utf-8")
        value = batch.BatchPlan("files", tuple(batch.ItemPlan(str(source), ("simple",)) for _ in range(5)), 1)
        active, peak, calls = 0, 0, 0
        lock = threading.Lock()
        keys, custom = {"custom": "original-secret"}, {"custom": {"url": "https://original.test"}}
        def summary(*args, **kwargs):
            nonlocal active, peak, calls
            with lock:
                active += 1
                peak = max(peak, active)
                calls += 1
                index = calls
            try:
                self.assertEqual(kwargs["api_keys"]["custom"], "original-secret")
                self.assertEqual(kwargs["custom_api"]["custom"]["url"], "https://original.test")
                kwargs["progress"]("test progress original-secret")
                time.sleep(.02)
                if index == 1:
                    raise ValueError("unavailable")
                return self.summary(*args, **kwargs)
            finally:
                with lock:
                    active -= 1
        with patch.object(batch, "generate_output_bundle", summary):
            self.add(value, api_keys=keys, custom_api=custom)
            keys["custom"] = "changed"
            custom["custom"]["url"] = "https://changed.test"
            self.wait_for(lambda: not self.queue.has_work)
        self.assertEqual(peak, 1)
        self.assertEqual(calls, 5)
        view = self.queue.snapshot()[0]
        self.assertEqual(view["failed"], 1)
        self.assertEqual(view["done"], 5)
        self.assertEqual(len(self.histories), 5)
        self.assertEqual(sum(item["status"] == "failed" for _, item in self.histories), 1)
        for path in self.root.rglob("*"):
            if path.is_file() and path.suffix in {".json", ".log"}:
                self.assertNotIn("original-secret", path.read_text(encoding="utf-8"))

    def test_cancelled_queued_batches_never_start_and_started_plans_cannot_change(self):
        source = self.root / "file.txt"
        source.write_text("hello", encoding="utf-8")
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def summary(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            if kwargs["cancel_event"].is_set():
                raise asyncio.CancelledError()
            return self.summary(*args, **kwargs)
        with patch.object(batch, "generate_output_bundle", summary):
            first = self.add(batch.BatchPlan("files", (batch.ItemPlan(str(source), ("simple",)),), 1), api_keys={"custom": "secret"})
            self.assertTrue(entered.wait(2))
            with self.assertRaises(ValueError):
                self.queue.edit(first, plan(count=1))
            self.queue.browser_lock.acquire()
            pending = self.add(plan(count=1))
            self.queue.cancel(pending)
            self.queue.remove(pending)
            self.queue.browser_lock.release()
            self.queue.cancel(first)
            release.set()
            self.wait_for(lambda: not self.queue.has_work)
        self.assertEqual(self.queue.snapshot()[0]["status"], "cancelled")
        self.assertEqual(len(self.histories), 1)
        self.assertEqual(self.histories[0][1]["status"], "cancelled")

    def test_capture_startup_failures_are_recorded_once_per_item(self):
        async def fail(*args, **kwargs):
            raise RuntimeError("browser failed")
        with patch.object(batch, "capture_links", fail):
            self.add(plan(count=2))
            self.wait_for(lambda: not self.queue.has_work)
        self.assertEqual([item["status"] for _, item in self.histories], ["failed", "failed"])
        current = self.queue.batches[0]
        self.queue._finished(current, current.items[0])
        self.assertEqual(len(self.histories), 2)

    def test_edit_hold_does_not_start_old_plan_and_cancel_edit_resumes_original(self):
        order = []
        async def capture(links, root, **options):
            order.append(len(links))
            return await self.capture(links, root, **options)
        self.queue.browser_lock.acquire()
        with patch.object(batch, "capture_links", capture):
            first = self.add(plan(count=1))
            self.assertTrue(self.queue.hold(first))
            self.add(plan(count=2))
            self.queue.browser_lock.release()
            self.wait_for(lambda: self.queue.snapshot()[1]["status"] == "completed")
            self.assertFalse(self.queue.snapshot()[0]["started"])
            self.queue.resume(first)
            self.wait_for(lambda: not self.queue.has_work)
        self.assertEqual(order, [2, 1])

    def test_global_summary_pool_never_exceeds_three_across_multiple_batches(self):
        source = self.root / "file.txt"
        source.write_text("hello", encoding="utf-8")
        value = batch.BatchPlan("files", tuple(batch.ItemPlan(str(source), ("simple",)) for _ in range(6)), 3)
        active, peak = 0, 0
        lock = threading.Lock()
        def summary(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(.03)
                return self.summary(*args, **kwargs)
            finally:
                with lock:
                    active -= 1
        with patch.object(batch, "generate_output_bundle", summary):
            self.add(value, api_keys={"custom": "key"})
            self.add(value, api_keys={"custom": "key"})
            self.wait_for(lambda: not self.queue.has_work)
        self.assertEqual(peak, 3)
        self.assertEqual(sum(view["done"] for view in self.queue.snapshot()), 12)

    def test_later_batches_do_not_exceed_an_active_serial_summary_selection(self):
        source = self.root / "file.txt"
        source.write_text("hello", encoding="utf-8")
        value = batch.BatchPlan("files", tuple(batch.ItemPlan(str(source), ("simple",)) for _ in range(3)), 1)
        entered, release = threading.Event(), threading.Event()
        active, peak = 0, 0
        lock = threading.Lock()
        def summary(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                entered.set()
                self.assertTrue(release.wait(2))
                return self.summary(*args, **kwargs)
            finally:
                with lock:
                    active -= 1
        self.addCleanup(release.set)
        with patch.object(batch, "generate_output_bundle", summary):
            self.add(value, api_keys={"custom": "key"})
            self.assertTrue(entered.wait(2))
            self.add(value, api_keys={"custom": "key"})
            time.sleep(.05)
            self.assertFalse(self.queue.snapshot()[1]["started"])
            release.set()
            self.wait_for(lambda: not self.queue.has_work)
        self.assertEqual(peak, 1)


if __name__ == "__main__":
    unittest.main()
