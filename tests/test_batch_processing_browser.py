"""Actual Chromium + local routes; no user profiles, accounts or remote API."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from gui.batch_processing import BatchProcessingQueue, BatchPlan, ItemPlan
from gui.service import launch_browser_context


@unittest.skipUnless(os.environ.get("AI_MEMORY_BROWSER_SMOKE") == "1", "opt-in local Chromium check")
class BatchProcessingBrowserTests(unittest.TestCase):
    def test_real_profile_can_pause_switch_batch_and_resume_without_recapturing(self):
        from gui.batch_capture import capture_links
        identifiers = [f"33333333-3333-3333-3333-{index:012d}" for index in range(5)]
        links = [f"https://chatgpt.com/c/{value}" for value in identifiers]
        calls, launches = [], []
        async def launch(*args, **options):
            options.update(headless=True, start_minimized=False, viewport={"width": 900, "height": 600})
            context, channel = await launch_browser_context(*args, **options)
            launches.append(context)
            if len(launches) == 1:
                await context.add_cookies([dict(name="resume_fixture", value="authenticated", domain="chatgpt.com",
                                               path="/", secure=True, httpOnly=True, expires=time.time()+3600)])
            async def route(request_route):
                request = request_route.request
                path = urlparse(request.url).path
                if path == "/api/auth/session":
                    await request_route.fulfill(json={"accessToken": "fixture"})
                elif path.startswith("/backend-api/conversation/"):
                    self.assertIn("resume_fixture=authenticated", request.headers.get("cookie", ""))
                    identifier = path.rsplit("/", 1)[-1]
                    calls.append(identifier)
                    await request_route.fulfill(json={"conversation_id": identifier, "current_node": "answer",
                        "mapping": {key: {"id": key, "parent": parent, "message": {
                            "id": key, "author": {"role": role}, "recipient": "all", "metadata": {},
                            "content": {"content_type": "text", "parts": [identifier]}}}
                            for key, parent, role in (("question", None, "user"), ("answer", "question", "assistant"))}})
                else:
                    await request_route.fulfill(content_type="text/html", body="<p>local resume fixture</p>")
            await context.route("**/*", route)
            return context, channel
        async def run(root):
            profile = root / "isolated-profile"
            first = await capture_links(links[:4], root / "first", concurrency=2,
                                        browser_profile_root=profile, claim_item=lambda index: index <= 2)
            self.assertEqual([row["status"] for row in first], ["completed", "completed", "queued", "queued"])
            original = Path(first[0]["saved_files"][0]).read_bytes()
            second = await capture_links(links[4:], root / "second", concurrency=1, browser_profile_root=profile)
            self.assertEqual(second[0]["status"], "completed")
            resumed = await capture_links(links[:4], root / "first", concurrency=2, browser_profile_root=profile, resume=True)
            self.assertTrue(all(row["status"] == "completed" for row in resumed))
            self.assertEqual(Path(resumed[0]["saved_files"][0]).read_bytes(), original)
            await capture_links(links[:4], root / "first", concurrency=2, browser_profile_root=profile, resume=True)
        with tempfile.TemporaryDirectory() as temporary, patch("gui.batch_capture.launch_browser_context", launch):
            asyncio.run(run(Path(temporary)))
        self.assertEqual(len(launches), 3)
        self.assertEqual(sorted(calls), sorted(identifiers))

    def test_real_one_two_three_page_queues_overlap_summary_and_keep_item_identities(self):
        for concurrency in (1, 2, 3):
            with self.subTest(concurrency=concurrency):
                self.run_queue(concurrency)

    def run_queue(self, concurrency):
        identifiers = [f"22222222-2222-2222-2222-{index:012d}" for index in range(1, 5)]
        links = [f"https://chatgpt.com/c/{value}" for value in identifiers]
        release = threading.Event()
        stats = dict(launches=0, peak=0, closed=False)
        summaries = []
        histories = []
        async def launch(*args, **options):
            stats["launches"] += 1
            options.update(viewport={"width": 900, "height": 600})
            context, channel = await launch_browser_context(*args, **options)
            await context.add_cookies([dict(name="batch_fixture", value="logged-in", domain="chatgpt.com",
                                           path="/", secure=True, httpOnly=True)])
            barrier = asyncio.Event()
            seen = set()
            async def route(request_route):
                request = request_route.request
                path = urlparse(request.url).path
                if path == "/api/auth/session":
                    await request_route.fulfill(json={"accessToken": "fixture-token"})
                elif path.startswith("/backend-api/conversation/"):
                    identifier = path.rsplit("/", 1)[-1]
                    self.assertIn(identifier, identifiers)
                    self.assertIn("batch_fixture=logged-in", request.headers.get("cookie", ""))
                    seen.add(identifier)
                    if len(seen) >= concurrency:
                        barrier.set()
                    await asyncio.wait_for(barrier.wait(), 5)
                    await request_route.fulfill(json={"conversation_id": identifier, "current_node": "answer",
                        "mapping": {key: {"id": key, "parent": parent, "message": {
                            "id": key, "author": {"role": role}, "recipient": "all", "metadata": {},
                            "content": {"content_type": "text", "parts": [f"{role}: {identifier}"]}}}
                            for key, parent, role in (("question", None, "user"), ("answer", "question", "assistant"))}})
                else:
                    await request_route.fulfill(content_type="text/html", body="<p>local batch fixture</p>")
            await context.route("**/*", route)
            def opened(_page):
                stats["peak"] = max(stats["peak"], len(context.pages))
            context.on("page", opened)
            context.on("close", lambda *_: stats.update(closed=True))
            stats["peak"] = len(context.pages)
            return context, channel

        def summary(messages, modes, output, *, output_filename, **kwargs):
            self.assertTrue(release.wait(45), "test must unblock summaries after verifying capture overlap")
            summaries.append((messages, dict(modes), kwargs["source_platform"]))
            path = Path(output) / Path(output_filename).stem / output_filename
            path.write_text(messages[0]["content"], encoding="utf-8")
            return SimpleNamespace(saved_files=[path], summary_result=None)

        modes = (("raw", "simple"), ("normal",), ("detailed",), ("raw",))
        value = BatchPlan("links", tuple(ItemPlan(link, selected) for link, selected in zip(links, modes)), concurrency)
        with tempfile.TemporaryDirectory() as temporary, patch("gui.batch_capture.launch_browser_context", launch), \
                patch("gui.batch_processing.generate_output_bundle", summary):
            root = Path(temporary)
            queue = BatchProcessingQueue(on_item_done=lambda *args: histories.append(args))
            try:
                queue.add(value, output_parent=root, runtime_dir=root / "runtime", api_keys={"custom": "private-fixture-key"})
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    view = queue.snapshot()[0]
                    if stats["closed"]:
                        break
                    time.sleep(.03)
                self.assertTrue(stats["closed"], queue.snapshot())
                view = queue.snapshot()[0]
                self.assertEqual([item["status"] for item in view["items"]].count("completed"), 1, view)
                self.assertTrue(all(item["output_dir"] for item in view["items"]), view)
                self.assertTrue(queue.has_work, "API must still be processing while all capture slots are already done")
                self.assertEqual(stats["launches"], 1)
                self.assertEqual(stats["peak"], concurrency)
                release.set()
                deadline = time.monotonic() + 10
                while queue.has_work and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertFalse(queue.has_work, queue.snapshot())
                view = queue.snapshot()[0]
                self.assertEqual(view["status"], "completed", view)
                self.assertEqual(len(histories), 4)
                self.assertEqual(len(summaries), 3)
                for item, identifier, selected in zip(view["items"], identifiers, modes):
                    target = Path(item["output_dir"])
                    payload = json.loads((target / "result.json").read_text(encoding="utf-8"))
                    self.assertEqual(len(payload["messages"]), 2)
                    self.assertTrue(all(identifier in message["content"] for message in payload["messages"]))
                    self.assertEqual((target / "export.md").exists(), "raw" in selected)
                    self.assertTrue(all(Path(filename).is_file() for filename in item["saved_files"]))
                self.assertTrue(all(platform == "ChatGPT" for _messages, _modes, platform in summaries))
                for path in root.rglob("*.json"):
                    self.assertNotIn("private-fixture-key", path.read_text(encoding="utf-8"))
            finally:
                release.set()
                queue.close()
                self.assertTrue(queue.wait(15))


if __name__ == "__main__":
    unittest.main()
