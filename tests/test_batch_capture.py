"""Batch isolation, scheduling, stop cleanup, and borrowed-page ownership."""

import asyncio
import json
import os
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from gui.batch_capture import capture_links, validate_capture_links
from gui.service import FetchResult, fetch_chat_pipeline
from scripts.providers.chatgpt_source import SourceError


LINKS = [f"https://chat.deepseek.com/share/{index}" for index in range(4)]


class Page:
    def __init__(self, context):
        self.context = context
        self.closed = False

    async def goto(self, url, **kwargs):
        self.url = url

    async def add_init_script(self, script):
        self.script = script

    async def close(self):
        self.closed = True
        self.context.pages.remove(self)


class Context:
    def __init__(self):
        self.pages = []
        self.peak = 0
        self.closed = False

    async def new_page(self):
        page = Page(self)
        self.pages.append(page)
        self.peak = max(self.peak, len(self.pages))
        return page

    async def close(self):
        self.closed = True
        for page in list(self.pages):
            await page.close()


@asynccontextmanager
async def playwright():
    yield object()


class BatchCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_image_auth_marks_same_origin_but_not_cdn_or_challenge(self):
        from gui.service import _download_image_candidates
        for origin, challenge, expected in (
            ('https://chat.deepseek.com', False, True),
            ('https://images.example.com', False, False),
            ('https://chat.deepseek.com', True, False),
        ):
            with self.subTest(origin=origin, challenge=challenge), tempfile.TemporaryDirectory() as temporary:
                page = MagicMock()
                page.url = 'https://chat.deepseek.com/c/exact'
                page.evaluate = AsyncMock(return_value=None)
                page.wait_for_timeout = AsyncMock()
                response = SimpleNamespace(ok=False, status=403, headers={'cf-mitigated': 'challenge'} if challenge else {})
                auth = []
                with patch('gui.service._authenticated_page_get', AsyncMock(return_value=response)), patch(
                    'gui.service.GUI_IMAGE_DOWNLOAD_ATTEMPTS', 1
                ):
                    await _download_image_candidates(page, [origin+'/fixture.png'], Path(temporary), './images',
                                                     authentication_required=auth, detect_login=True)
                self.assertEqual(bool(auth), expected)

    async def test_stop_during_browser_start_waits_for_startup_cleanup(self):
        entered, cleaned = asyncio.Event(), asyncio.Event()
        stop = threading.Event()

        async def launch(*_args, **_options):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.01)
                cleaned.set()

        with tempfile.TemporaryDirectory() as temporary, patch("gui.batch_capture.async_playwright", playwright), patch(
            "gui.batch_capture.launch_browser_context", launch
        ):
            task = asyncio.create_task(capture_links(LINKS, Path(temporary)/"results", cancel_event=stop))
            await entered.wait()
            stop.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            self.assertTrue(cleaned.is_set())

    async def test_three_pages_overlap_and_queue_preserves_identity_assets_and_failures(self):
        context = Context()
        first_three = asyncio.Event()
        seen, finished = [], []

        async def fetch(url, **options):
            seen.append(url)
            self.assertFalse(context.closed)
            self.assertFalse(options["need_login"])
            self.assertIs(options["shared_page"].context, context)
            self.assertLessEqual(len(context.pages), 3)
            if len(seen) == 3:
                first_three.set()
            await asyncio.wait_for(first_three.wait(), 2)
            if url == LINKS[1]:
                raise RuntimeError("one link failed")
            target = options["document_output_dir"]
            target.mkdir()
            (target / "same.txt").write_text(url, encoding="utf-8")
            await asyncio.sleep(0.01)
            return FetchResult(html=f"<p>{url}</p>", image_map={},
                               document_map={url: "./documents/same.txt"},
                               messages=[dict(role="User", content=f"{url}\n[附件](./documents/same.txt)")])

        launch = AsyncMock(return_value=(context, "chromium"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "results"
            with patch("gui.batch_capture.async_playwright", playwright), patch(
                "gui.batch_capture.launch_browser_context", launch
            ), patch("gui.batch_capture.fetch_chat_pipeline", side_effect=fetch):
                records = await capture_links(LINKS, root, on_result=finished.append)
            self.assertEqual(context.peak, 3)
            self.assertTrue(context.closed)
            self.assertEqual(context.pages, [])
            launch.assert_awaited_once()
            self.assertEqual(len(finished), 4)
            self.assertEqual([item["url"] for item in records], LINKS)
            self.assertEqual([item["status"] for item in records], ["completed", "failed", "completed", "completed"])
            for item in records:
                if item["status"] == "completed":
                    folder = Path(item["output_dir"])
                    self.assertEqual((folder / "documents/same.txt").read_text(encoding="utf-8"), item["url"])
                    self.assertIn(item["url"], (folder / "export.md").read_text(encoding="utf-8"))
                    self.assertIn("documents/same.txt", json.loads((folder / "result.json").read_text(encoding="utf-8"))["files"])
            self.assertEqual(json.loads((root / "manifest.json").read_text(encoding="utf-8"))["items"], records)

    async def test_stop_cancels_three_active_pages_and_keeps_queued_status(self):
        context = Context()
        stop = threading.Event()
        entered, cleaned = [], []

        async def fetch(url, **options):
            entered.append(url)
            if len(entered) == 3:
                stop.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.01)
                cleaned.append(url)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "results"
            with patch("gui.batch_capture.async_playwright", playwright), patch(
                "gui.batch_capture.launch_browser_context", AsyncMock(return_value=(context, "chromium"))
            ), patch("gui.batch_capture.fetch_chat_pipeline", side_effect=fetch):
                with self.assertRaises(asyncio.CancelledError):
                    await capture_links(LINKS, root, cancel_event=stop)
            self.assertEqual(len(entered), 3)
            self.assertEqual(sorted(cleaned), sorted(entered))
            self.assertTrue(context.closed)
            self.assertEqual(context.pages, [])
            records = json.loads((root / "manifest.json").read_text(encoding="utf-8"))["items"]
            self.assertTrue(all(record["status"] == "cancelled" for record in records))

    async def test_rejects_files_unsupported_urls_and_existing_outputs_before_launch(self):
        for links in (["C:/input.md"], ["https://example.org/chat"], [], LINKS[0], ["https://user:secret@chatgpt.com/c/id"]):
            with self.subTest(links=links), self.assertRaises(ValueError):
                validate_capture_links(links)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "export.md").write_text("keep", encoding="utf-8")
            with patch("gui.batch_capture.launch_browser_context") as launch:
                with self.assertRaises(ValueError):
                    await capture_links(LINKS, root)
                launch.assert_not_called()
            self.assertEqual((root / "export.md").read_text(encoding="utf-8"), "keep")

    async def test_stop_after_export_keeps_completed_record_and_notification(self):
        context = Context()
        page = await context.new_page()
        page.goto = AsyncMock(side_effect=asyncio.CancelledError())
        finished = []
        fetched = FetchResult(html="", image_map={}, messages=[dict(role="User", content="saved")])
        with tempfile.TemporaryDirectory() as temporary, patch("gui.batch_capture.async_playwright", playwright), patch(
            "gui.batch_capture.launch_browser_context", AsyncMock(return_value=(context, "chromium"))
        ), patch("gui.batch_capture.fetch_chat_pipeline", AsyncMock(return_value=fetched)):
            root = Path(temporary)/"results"
            with self.assertRaises(asyncio.CancelledError):
                await capture_links(LINKS[:1], root, on_result=finished.append)
            self.assertEqual(finished[0]["status"], "completed")
            self.assertIn("elapsed_seconds", finished[0])
            self.assertTrue(Path(finished[0]["saved_files"][0]).is_file())
            self.assertEqual(json.loads((root/"manifest.json").read_text(encoding="utf-8"))["items"][0]["status"], "completed")

    async def test_batch_cleanup_warning_remains_visible_without_losing_outputs(self):
        context = Context()

        async def close():
            await Context.close(context)
            raise RuntimeError("fixture cleanup warning")

        context.close = close
        fetched = FetchResult(html="", image_map={}, messages=[dict(role="User", content="saved")])
        with tempfile.TemporaryDirectory() as temporary, patch("gui.batch_capture.async_playwright", playwright), patch(
            "gui.batch_capture.launch_browser_context", AsyncMock(return_value=(context, "chromium"))
        ), patch("gui.batch_capture.fetch_chat_pipeline", AsyncMock(return_value=fetched)):
            records = await capture_links(LINKS[:1], Path(temporary)/"results")
            self.assertEqual(records[0]["status"], "completed")
            self.assertTrue(Path(records[0]["saved_files"][0]).is_file())
            self.assertIn("批次清理", records[0]["warnings"][0])

    async def test_borrowed_page_reuses_auth_without_creating_or_closing_browser(self):
        external_listener = lambda response: None
        listeners = {external_listener}
        page = SimpleNamespace(
            context=SimpleNamespace(clear_cookies=AsyncMock()),
            on=Mock(side_effect=lambda event, callback: listeners.add(callback)),
            remove_listener=Mock(side_effect=lambda event, callback: listeners.remove(callback)),
            wait_for_timeout=AsyncMock(),
        )
        url = "https://chatgpt.com/c/11111111-1111-1111-1111-111111111111"
        captured = dict(html="<p>actual</p>", messages=[dict(role="User", content="actual")],
                        image_map={}, document_map={}, warnings=[])
        with tempfile.TemporaryDirectory() as temporary, patch(
            "gui.service.async_playwright"
        ) as start, patch("gui.service.launch_browser_context") as launch, patch(
            "gui.service._close_browser_context_safely"
        ) as close, patch("gui.service.goto_with_retry_gui", AsyncMock()), patch(
            "gui.service.chatgpt_source.read_conversation", AsyncMock(return_value={"mapping": {"actual": 1}})
        ), patch("gui.chatgpt_capture.capture_conversation", AsyncMock(return_value=captured)):
            result = await fetch_chat_pipeline(url, shared_page=page,
                image_output_dir=Path(temporary)/"images", document_output_dir=Path(temporary)/"documents")
        self.assertEqual(result.messages, captured["messages"])
        start.assert_not_called()
        launch.assert_not_called()
        close.assert_not_called()
        page.context.clear_cookies.assert_not_awaited()
        self.assertEqual(page.on.call_count, 1)
        self.assertEqual(page.remove_listener.call_count, 1)
        self.assertEqual(listeners, {external_listener})

    async def test_expired_login_is_a_link_failure_without_interactive_login(self):
        page = SimpleNamespace(context=object(), on=Mock(), remove_listener=Mock(), wait_for_timeout=AsyncMock())
        with patch("gui.service.goto_with_retry_gui", AsyncMock()), patch(
            "gui.service.chatgpt_source.read_conversation", AsyncMock(side_effect=SourceError("login expired"))
        ):
            result = await fetch_chat_pipeline("https://chatgpt.com/c/11111111-1111-1111-1111-111111111111", shared_page=page)
        self.assertIn("登录状态", result.error)
        self.assertEqual(result.messages, [])

    async def test_expired_shared_login_awaits_authorization_and_rechecks_exact_source(self):
        page = SimpleNamespace(context=object(), on=Mock(), remove_listener=Mock(), wait_for_timeout=AsyncMock())
        url = 'https://chatgpt.com/c/11111111-1111-1111-1111-111111111111'
        captured = dict(html='', messages=[dict(role='User', content='actual')], image_map={}, document_map={}, warnings=[])
        reads = AsyncMock(side_effect=[SourceError('login expired'), {'mapping': {'actual': 1}}])
        async def authorize(actual_page, target, ready, **options):
            self.assertIs(actual_page, page)
            self.assertEqual(target, url)
            self.assertFalse(options['force'])
            return await ready()
        with patch('gui.service.goto_with_retry_gui', AsyncMock()), patch(
            'gui.service.chatgpt_source.read_conversation', reads
        ), patch('gui.chatgpt_capture.capture_conversation', AsyncMock(return_value=captured)):
            result = await fetch_chat_pipeline(url, shared_page=page, authorize_login=authorize)
        self.assertIsNone(result.error)
        self.assertEqual(result.messages, captured['messages'])
        self.assertEqual(reads.await_count, 2)

    async def test_shared_asset_auth_retries_capture_once_after_force_authorization(self):
        page = SimpleNamespace(context=object(), on=Mock(), remove_listener=Mock(), wait_for_timeout=AsyncMock())
        url = 'https://chatgpt.com/c/11111111-1111-1111-1111-111111111111'
        calls = []
        async def capture(_page, _url, _payload, **options):
            calls.append(options)
            if len(calls) == 1:
                options['authorization_required'].append(True)
            return dict(html='', messages=[dict(role='User', content='actual')], image_map={}, document_map={}, warnings=[])
        authorize = AsyncMock(return_value=True)
        with patch('gui.service.goto_with_retry_gui', AsyncMock()), patch(
            'gui.service.chatgpt_source.read_conversation', AsyncMock(return_value={'mapping': {'actual': 1}})
        ), patch('gui.chatgpt_capture.capture_conversation', capture):
            result = await fetch_chat_pipeline(url, shared_page=page, authorize_login=authorize)
        self.assertIsNone(result.error)
        self.assertEqual(len(calls), 2)
        authorize.assert_awaited_once()
        self.assertTrue(authorize.call_args.kwargs['force'])
        self.assertNotIn('authorization_required', calls[1])

    async def test_skipping_asset_authorization_marks_item_failed_instead_of_partial_success(self):
        page = SimpleNamespace(context=object(), on=Mock(), remove_listener=Mock(), wait_for_timeout=AsyncMock())
        url = 'https://chatgpt.com/c/11111111-1111-1111-1111-111111111111'
        async def capture(_page, _url, _payload, **options):
            options['authorization_required'].append(True)
            return dict(html='', messages=[dict(role='User', content='partial')], image_map={}, document_map={}, warnings=[])
        with patch('gui.service.goto_with_retry_gui', AsyncMock()), patch(
            'gui.service.chatgpt_source.read_conversation', AsyncMock(return_value={'mapping': {'actual': 1}})
        ), patch('gui.chatgpt_capture.capture_conversation', capture):
            result = await fetch_chat_pipeline(url, shared_page=page, authorize_login=AsyncMock(return_value=False))
        self.assertIn('已停止此项', result.error)
        self.assertEqual(result.messages, [])

    async def test_online_documents_use_own_page_and_restore_without_a_third_tab(self):
        from gui.service import _save_doubao_ai_documents
        original = "https://www.doubao.com/chat/12345678"
        page = SimpleNamespace(url=original, context=SimpleNamespace(new_page=AsyncMock()))

        async def goto(url, **_options):
            page.url = url

        page.goto = AsyncMock(side_effect=goto)
        with tempfile.TemporaryDirectory() as temporary, patch(
            "gui.service._extract_doubao_ai_document_titles", return_value=[]
        ), patch("gui.service._page_has_conversation_content", AsyncMock(return_value=True)), patch(
            "gui.service._download_doubao_ai_document_markdown", AsyncMock(side_effect=[b"first", b"second"])
        ):
            mapping, count = await _save_doubao_ai_documents(page, "", Path(temporary), "./documents", [],
                entries=[("one", "https://www.doubao.com/docx/document1", "1"),
                         ("two", "https://www.doubao.com/docx/document2", "2")], reuse_page=True)
            self.assertEqual(count, 2)
            self.assertEqual((Path(temporary)/"one.md").read_bytes(), b"first")
            self.assertEqual((Path(temporary)/"two.md").read_bytes(), b"second")
        page.context.new_page.assert_not_awaited()
        self.assertEqual(page.url, original)
        self.assertNotEqual(mapping["doubao-ai-doc-message:1"], mapping["doubao-ai-doc-message:2"])

    async def test_online_document_recovery_returns_to_original_card_in_shared_page(self):
        from gui.service import _save_doubao_ai_documents
        original = "https://www.doubao.com/chat/12345678"
        document = "https://www.doubao.com/docx/document123"
        page = MagicMock()
        page.url, page.frames = original, []
        page.context.new_page = AsyncMock()

        async def goto(url, **_options):
            page.url = url
            page.frames = []

        page.goto = AsyncMock(side_effect=goto)
        page.keyboard.press = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        card = MagicMock()
        card.count = AsyncMock(return_value=1)
        card.first = card
        card.locator.return_value = card
        card.get_by_text.return_value = card
        card.scroll_into_view_if_needed = AsyncMock()

        async def click(**_options):
            page.frames = [SimpleNamespace(url="https://www.doubao.com/partner/ccm-docx/docx/document123")]

        card.click = AsyncMock(side_effect=click)
        page.get_by_text.return_value = card
        page.locator.return_value = card
        with tempfile.TemporaryDirectory() as temporary, patch(
            "gui.service._extract_doubao_ai_document_titles", return_value=[]
        ), patch("gui.service._page_has_conversation_content", AsyncMock(return_value=True)), patch(
            "gui.service._download_doubao_ai_document_markdown", AsyncMock(side_effect=[b"", b"full document"])
        ):
            warnings = []
            mapping, _ = await _save_doubao_ai_documents(page, "", Path(temporary), "./documents", warnings,
                entries=[("report", document, "1")], reuse_page=True)
            self.assertFalse(warnings)
            self.assertEqual((Path(temporary)/"report.md").read_bytes(), b"full document")
            self.assertIn("doubao-ai-doc-message:1", mapping)
        page.context.new_page.assert_not_awaited()
        self.assertEqual(page.url, original)


@unittest.skipUnless(os.getenv("AI_MEMORY_BROWSER_SMOKE") == "1", "opt-in real Chromium check")
class BatchBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_three_tab_pipeline_reuses_cookie_and_keeps_four_conversations_separate(self):
        from gui.service import launch_browser_context
        from urllib.parse import urlparse

        ids = [f"11111111-1111-1111-1111-{index:012d}" for index in range(1, 5)]
        links = [f"https://chatgpt.com/c/{identifier}" for identifier in ids]
        first_three = asyncio.Event()
        requested = []
        observed = {"launches": 0, "peak": 0, "downloads": 0}

        async def route(request_route):
            request = request_route.request
            path = urlparse(request.url).path
            if path == "/api/auth/session":
                await request_route.fulfill(json={"accessToken": "fixture-token"})
            elif path == "/batch-download":
                observed["downloads"] += 1
                await request_route.fulfill(body=b"fixture attachment", headers={
                    "content-type": "application/octet-stream", "content-disposition": "attachment; filename=fixture.txt"})
            elif path.startswith("/backend-api/conversation/"):
                identifier = path.rsplit("/", 1)[-1]
                self.assertIn("batch_fixture=logged-in", request.headers.get("cookie", ""))
                self.assertEqual(request.headers.get("authorization"), "Bearer fixture-token")
                requested.append(identifier)
                if len(requested) >= 3:
                    first_three.set()
                await asyncio.wait_for(first_three.wait(), 5)
                await request_route.fulfill(json={"conversation_id": identifier, "current_node": "answer",
                    "mapping": {key: {"id": key, "parent": parent, "message": {
                        "id": key, "author": {"role": role}, "recipient": "all", "metadata": {},
                        "content": {"content_type": "text", "parts": [f"{role}: {identifier}"]}}}
                        for key, parent, role in [("question", None, "user"), ("answer", "question", "assistant")]}})
            else:
                await request_route.fulfill(content_type="text/html", body="""<html><body>fixture
                    <a id="download" href="/batch-download" target="_blank">download</a>
                    <button onclick="window.open('/batch-download')">popup download</button>
                    </body></html>""")

        async def fetch_with_download(url, **options):
            page = options["shared_page"]
            await page.goto(url, wait_until="domcontentloaded")
            async with page.expect_download() as downloading:
                if ids.index(url.rsplit("/", 1)[-1]) % 2:
                    await page.locator("#download").click()
                else:
                    await page.get_by_role("button", name="popup download").click()
            download = await downloading.value
            self.assertEqual(Path(await download.path()).read_bytes(), b"fixture attachment")
            return await fetch_chat_pipeline(url, **options)

        async def launch(*args, **options):
            observed["launches"] += 1
            options.update(headless=False, viewport={"width": 900, "height": 600}, start_minimized=True)
            context, channel = await launch_browser_context(*args, **options)
            await context.add_cookies([dict(name="batch_fixture", value="logged-in", domain="chatgpt.com",
                                           path="/", secure=True, httpOnly=True)])
            await context.route("**/*", route)

            def opened(_page):
                observed["peak"] = max(observed["peak"], len(context.pages))

            observed["peak"] = len(context.pages)
            context.on("page", opened)
            return context, channel

        with tempfile.TemporaryDirectory() as temporary, patch("gui.batch_capture.launch_browser_context", launch), patch(
            "gui.batch_capture.fetch_chat_pipeline", fetch_with_download
        ):
            records = await asyncio.wait_for(capture_links(links, Path(temporary)/"results",
                                                          browser_profile_root=Path(temporary)/"profile"), 45)
            self.assertEqual(observed, {"launches": 1, "peak": 3, "downloads": 4})
            self.assertTrue(first_three.is_set(), "three conversations must be in flight together")
            for identifier, record in zip(ids, records):
                self.assertEqual(record["status"], "completed", record)
                self.assertEqual(record["messages"], 2)
                markdown = Path(record["saved_files"][0]).read_text(encoding="utf-8")
                self.assertIn(identifier, markdown)
                self.assertTrue(all(other not in markdown for other in ids if other != identifier))


if __name__ == "__main__":
    unittest.main()
