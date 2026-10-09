"""GUI 模块独立单元测试。

验证 GUI 辅助方法、状态机和逻辑约束，不依赖图形显示服务器。
"""

import asyncio
import hashlib
import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from bs4 import BeautifulSoup

from gui.service import (
    _authenticated_page_get,
    _capture_document_content_response,
    _close_browser_context_safely,
    _collect_response_assets,
    _document_download_url_from_payload,
    _document_response_cache_keys,
    _deepseek_document_card_get,
    _download_document_candidates,
    _download_image_candidates,
    _extract_chatgpt_document_card_candidates,
    _extract_chatgpt_shared_image_sources,
    _extract_deepseek_document_card_candidates,
    _extract_document_candidates,
    _extract_gemini_document_card_candidates,
    _gemini_document_card_download,
    _extract_grok_document_card_candidates,
    _grok_document_card_download,
    _gemini_private_conversation_url,
    _enrich_gemini_shared_user_content,
    _extract_doubao_ai_document_resources,
    _extract_doubao_ai_document_titles,
    _inject_chatgpt_attachment_names,
    _inject_chatgpt_message_images,
    _inject_chatgpt_shared_images,
    _mark_unavailable_assets,
    _chatgpt_message_asset_groups,
    _is_decorative_image_candidate,
    _merge_chatgpt_rehydrate_html,
    _normalize_doubao_ai_document_text,
    _page_has_conversation_content,
    _parse_page_messages,
    _rehydrate_chatgpt_conversation,
    _recover_chatgpt_shared_video_assets,
    _repair_downloaded_text_mojibake,
    _set_browser_window_state,
    DocumentCandidate,
    build_document_asset_directory,
    build_image_asset_directory,
    build_image_asset_prefix,
    build_markdown_asset_prefix,
    build_output_paths,
    default_output_filename,
    default_summary_result_cache_dir,
    generate_output_bundle,
    generate_raw_markdown,
    gui_summary_config_candidates,
    launch_browser_context,
    normalize_markdown_filename,
    parse_fallback_messages_gui,
    requires_authenticated_browser,
)
from scripts.gemini_summarizer import GeminiSummaryError, SummaryConfig


class GUIServiceTests(unittest.TestCase):
    def test_gemini_blob_image_is_downloaded(self):
        body = b"\x89PNG\r\n\x1a\ncontent"
        page = SimpleNamespace(
            evaluate=AsyncMock(return_value=(
                "data:;base64,iVBORw0KGgpjb250ZW50"
            )),
            locator=MagicMock(),
        )
        page.request = SimpleNamespace(get=AsyncMock(side_effect=ValueError))
        with tempfile.TemporaryDirectory() as temp_dir:
            mapping = asyncio.run(_download_image_candidates(
                page,
                ["blob:https://gemini.google.com/generated"],
                Path(temp_dir),
                "./images",
            ))
            self.assertEqual(len(mapping), 1)
            saved = Path(temp_dir) / Path(next(iter(mapping.values()))).name
            self.assertEqual(saved.read_bytes(), body)

    def test_image_extension_uses_downloaded_bytes(self):
        body = b"\xff\xd8\xffcontent"
        page = SimpleNamespace(
            evaluate=AsyncMock(return_value="data:;base64,/9j/Y29udGVudA=="),
            locator=MagicMock(),
        )
        page.request = SimpleNamespace(get=AsyncMock(side_effect=ValueError))
        with tempfile.TemporaryDirectory() as temp_dir:
            mapping = asyncio.run(_download_image_candidates(
                page,
                ["blob:https://example.com/wrong.png"],
                Path(temp_dir),
                "./images",
            ))
            saved = Path(temp_dir) / Path(next(iter(mapping.values()))).name
            self.assertEqual(saved.suffix, ".jpg")
            self.assertEqual(saved.read_bytes(), body)

    def test_background_browser_starts_offscreen(self):
        launcher = AsyncMock(return_value=(object(), "chromium"))
        playwright = SimpleNamespace(
            chromium=SimpleNamespace(launch_persistent_context=launcher)
        )
        with patch("gui.service.browser_channel_candidates", return_value=("chromium",)):
            asyncio.run(launch_browser_context(
                playwright,
                headless=False,
                viewport=None,
                no_viewport=True,
                start_minimized=True,
            ))
        args = launcher.await_args.kwargs["args"]
        self.assertIn("--start-minimized", args)
        self.assertIn("--window-position=-32000,-32000", args)

    def test_maximize_restores_offscreen_browser_first(self):
        session = SimpleNamespace(
            send=AsyncMock(side_effect=[{"windowId": 7}, None, None]),
            detach=AsyncMock(),
        )
        page = SimpleNamespace(
            context=SimpleNamespace(new_cdp_session=AsyncMock(return_value=session))
        )
        asyncio.run(_set_browser_window_state(page, "maximized"))
        self.assertEqual(
            session.send.await_args_list[1].args,
            ("Browser.setWindowBounds", {
                "windowId": 7,
                "bounds": {
                    "windowState": "normal",
                    "left": 0,
                    "top": 0,
                    "width": 1200,
                    "height": 800,
                },
            }),
        )
        self.assertEqual(
            session.send.await_args_list[2].args,
            ("Browser.setWindowBounds", {
                "windowId": 7,
                "bounds": {"windowState": "maximized"},
            }),
        )

    def test_grok_share_document_cards(self):
        html = '''
        <button aria-label="打开附件">report.pdf</button>
        <button aria-label="打开附件"><img src="preview-image">image.png</button>
        <button aria-label="打开附件">result.xlsx</button>
        '''
        candidates = _extract_grok_document_card_candidates(
            html, "https://grok.com/share/example"
        )
        self.assertEqual(
            [candidate.filename for candidate in candidates],
            ["report.pdf", "result.xlsx"],
        )

    def test_grok_card_accepts_browser_download(self):
        class FakeDownload:
            async def path(self):
                return downloaded_path

        class FakeCard:
            async def click(self, timeout):
                page.listeners["download"](FakeDownload())

        class FakeLocator:
            def filter(self, **_kwargs):
                return self

            @property
            def first(self):
                return FakeCard()

        class FakeKeyboard:
            press = AsyncMock()

        class FakePage:
            def __init__(self):
                self.listeners = {}
                self.keyboard = FakeKeyboard()

            def locator(self, _selector):
                return FakeLocator()

            def on(self, event, callback):
                self.listeners[event] = callback

            def remove_listener(self, event, _callback):
                self.listeners.pop(event)

        with tempfile.TemporaryDirectory() as temp_dir:
            downloaded_path = Path(temp_dir) / "result.xlsx"
            downloaded_path.write_bytes(b"xlsx")
            page = FakePage()
            body, headers = asyncio.run(_grok_document_card_download(
                page,
                DocumentCandidate(
                    "grok-card:result.xlsx",
                    "https://grok.com/share/example",
                    "result.xlsx",
                ),
                1000,
            ))
        self.assertEqual(body, b"xlsx")
        self.assertIn("result.xlsx", headers["content-disposition"])
        page.keyboard.press.assert_awaited_once_with("Escape")

    def test_gemini_document_download_retries_once(self):
        page = SimpleNamespace(
            keyboard=SimpleNamespace(press=AsyncMock()),
            wait_for_timeout=AsyncMock(),
        )
        candidate = DocumentCandidate(
            "gemini-card:data.csv",
            "https://gemini.google.com/app/example",
            "data.csv",
        )
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "gui.service._gemini_document_card_download",
            new=AsyncMock(side_effect=[TimeoutError, (b"a,b\n1,2\n", {})]),
        ) as download:
            mapping = asyncio.run(_download_document_candidates(
                page,
                [candidate],
                Path(temp_dir),
                "./result_files",
            ))
        self.assertEqual(download.await_count, 2)
        page.keyboard.press.assert_awaited_once_with("Escape")
        page.wait_for_timeout.assert_awaited_once_with(1000)
        self.assertEqual(mapping[candidate.reference], "./result_files/data.csv")

    def test_gemini_video_uses_browser_download_and_rejects_error_pages(self):
        import base64
        body = b'\x00\x00\x00\x20ftypisom' + b'video data'
        for content_type, payload_body, accepted in (
            ('video/mp4', body, True),
            ('text/html', b'<html>not available</html>', False),
            ('application/octet-stream', b'<html>not available</html>', False),
        ):
            with self.subTest(content_type=content_type):
                button = SimpleNamespace(count=AsyncMock(return_value=1),
                                         is_enabled=AsyncMock(return_value=True), click=AsyncMock())
                card = SimpleNamespace(locator=MagicMock(return_value=SimpleNamespace(first=button)))
                cards = SimpleNamespace(filter=MagicMock(return_value=SimpleNamespace(first=card)))
                source = 'https://contribution.usercontent.google.com/download?filename=recording%20test.mp4'
                video = SimpleNamespace(wait_for=AsyncMock(), evaluate=AsyncMock(return_value=source))
                close = SimpleNamespace(count=AsyncMock(return_value=0))
                dialog = SimpleNamespace(locator=MagicMock(return_value=SimpleNamespace(first=close)))
                page = SimpleNamespace(
                    locator=MagicMock(side_effect=lambda selector: {
                        'user-query-file-preview': cards,
                        '[role="dialog"] video': SimpleNamespace(first=video),
                        '[role="dialog"]': SimpleNamespace(first=dialog),
                    }[selector]),
                    keyboard=SimpleNamespace(press=AsyncMock()),
                    evaluate=AsyncMock(return_value={
                        'data': base64.b64encode(payload_body).decode(),
                        'headers': {'content-type': content_type},
                    }),
                )
                candidate = DocumentCandidate('gemini-card:recording.mp4',
                                              'https://gemini.google.com/app/example', 'recording.mp4')
                if accepted:
                    downloaded, headers = asyncio.run(_gemini_document_card_download(page, candidate, 1000))
                    self.assertEqual(downloaded, body)
                    self.assertIn('recording%20test.mp4', headers['content-disposition'])
                    self.assertEqual(page.evaluate.await_args.args[1]['url'], source)
                else:
                    with self.assertRaises(ValueError):
                        asyncio.run(_gemini_document_card_download(page, candidate, 1000))
                page.keyboard.press.assert_awaited_once_with('Escape')

    def test_gemini_video_saved_with_real_download_filename(self):
        candidate = DocumentCandidate('gemini-card:' + 'A' * 24 + ':上传视频.mp4',
                                      'https://gemini.google.com/app/example', '上传视频.mp4')
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            'gui.service._gemini_document_card_download',
            new=AsyncMock(return_value=(b'\x00\x00\x00\x20ftypisomvideo', {
                'content-type': 'video/mp4',
                'content-disposition': "attachment; filename*=UTF-8''real%20name.mp4",
            })),
        ):
            mapping = asyncio.run(_download_document_candidates(
                SimpleNamespace(), [candidate], Path(temp_dir), './documents',
            ))
            self.assertEqual(mapping[candidate.reference], './documents/real%20name.mp4')
            self.assertTrue((Path(temp_dir) / 'real name.mp4').is_file())

    def test_gemini_same_name_versions_save_separately(self):
        first = DocumentCandidate(
            'gemini-card:' + 'A' * 24 + ':same.py',
            'https://gemini.google.com/app/example', 'same.py',
        )
        second = DocumentCandidate(
            'gemini-card:' + 'B' * 24 + ':same.py',
            'https://gemini.google.com/app/example', 'same.py',
        )
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            'gui.service._gemini_document_card_download',
            new=AsyncMock(side_effect=[(b'first', {}), (b'second', {})]),
        ):
            mapping = asyncio.run(_download_document_candidates(
                SimpleNamespace(), [first, second], Path(temp_dir),
                './documents',
            ))
            first_path = Path(temp_dir) / Path(mapping[first.reference]).name
            second_path = Path(temp_dir) / Path(mapping[second.reference]).name
            self.assertNotEqual(first_path, second_path)
            self.assertEqual(first_path.read_bytes(), b'first')
            self.assertEqual(second_path.read_bytes(), b'second')

    def test_gemini_share_metadata_and_document_cards(self):
        metadata = "[[\"r_file12345678\",\"c_058650b27dade1e6\"]]"
        import base64
        encoded = base64.b64encode(metadata.encode()).decode()
        html = f'''
        <user-query-file-preview><button aria-label="无法查看或下载共享对话中的文件"
          jslog="191296;BardVeMetadataKey:{encoded}">
          <div class="filename-label">报告</div><div class="extension-label">PDF</div>
        </button></user-query-file-preview>
        <user-query-file-preview><button aria-label="无法查看或下载共享对话中的文件">
          <img alt="text/markdown"><div class="filename-label">notes</div>
        </button></user-query-file-preview>
        '''
        self.assertEqual(
            _gemini_private_conversation_url(html),
            "https://gemini.google.com/app/058650b27dade1e6",
        )
        candidates = _extract_gemini_document_card_candidates(
            html, "https://gemini.google.com/share/example"
        )
        self.assertEqual(candidates, [])
        # 页面即使跳到原始会话，旧共享页 HTML 也不能生成可点击候选。
        self.assertEqual(
            _extract_gemini_document_card_candidates(
                html, "https://gemini.google.com/app/058650b27dade1e6"
            ),
            [],
        )

    def test_gemini_share_recovers_images_by_request_id_and_keeps_snapshot(self):
        import base64
        def user(request, text, images=(), document=False):
            metadata = base64.b64encode(
                f'[["r_{request}","c_conversation123"]]'.encode()
            ).decode()
            cards = ''.join(
                f'<user-query-file-preview><button aria-label="图片"><img src="{src}"></button></user-query-file-preview>'
                for src in images
            )
            if document:
                cards += '<user-query-file-preview><button aria-label="无法查看或下载"><img src="https://gstatic.com/file.png"><div class="filename-label">keep.pdf</div></button></user-query-file-preview>'
            return f'<user-query><button jslog="BardVeMetadataKey:{metadata}"></button>{cards}<div class="query-text">{text}</div></user-query>'
        shared = (user('first', 'short', document=True)
                  + '<message-content>shared answer</message-content>'
                  + user('second', 'second'))
        private = (user('second', 'second', ['https://lh3.googleusercontent.com/gg/three'])
                   + user('first', 'short complete', ['https://lh3.googleusercontent.com/gg/one', 'https://lh3.googleusercontent.com/gg/two'])
                   + user('later', 'must not export', ['https://lh3.googleusercontent.com/gg/later']))
        enriched = BeautifulSoup(_enrich_gemini_shared_user_content(shared, private), 'html.parser')
        users = enriched.find_all('user-query')
        self.assertEqual(len(users), 2)
        self.assertEqual([img['src'] for img in users[0].find_all('img')], [
            'https://lh3.googleusercontent.com/gg/one',
            'https://lh3.googleusercontent.com/gg/two',
            'https://gstatic.com/file.png',
        ])
        self.assertEqual(users[0].select_one('.query-text').get_text(), 'short complete')
        self.assertIn('keep.pdf', str(enriched))
        self.assertIn('shared answer', str(enriched))
        self.assertNotIn('must not export', str(enriched))
        self.assertEqual(_gemini_private_conversation_url(shared), 'https://gemini.google.com/app/conversation123')

    def test_gemini_enrichment_reuses_complete_downloaded_image_cards(self):
        import base64
        metadata = base64.b64encode(b'[["r_request123", "c_conversation123"]]').decode()
        shared = f'<user-query><button jslog="BardVeMetadataKey:{metadata}"></button><user-query-file-preview><button aria-label="图片"><img src="https://lh3.googleusercontent.com/gg/cached"></button></user-query-file-preview><div class="query-text">same</div></user-query>'
        private = shared.replace('/gg/cached', '/gg/fresh')
        result = _enrich_gemini_shared_user_content(shared, private, {'https://lh3.googleusercontent.com/gg/cached': './images/cached.png'})
        self.assertIn('/gg/cached', result)
        self.assertNotIn('/gg/fresh', result)
        # A failed initial download must still recover the fresh private source.
        result = _enrich_gemini_shared_user_content(shared, private, {})
        self.assertIn('/gg/fresh', result)
        self.assertNotIn('/gg/cached', result)

    def test_gemini_missing_document_card_fails_fast(self):
        missing = SimpleNamespace(count=AsyncMock(return_value=0))
        card = SimpleNamespace(locator=MagicMock(return_value=SimpleNamespace(first=missing)))
        cards = SimpleNamespace(
            filter=MagicMock(return_value=SimpleNamespace(first=card)),
            get_by_role=MagicMock(return_value=SimpleNamespace(first=missing)),
        )
        page = SimpleNamespace(locator=MagicMock(return_value=cards))
        candidate = DocumentCandidate(
            "gemini-card:missing.pdf",
            "https://gemini.google.com/app/058650b27dade1e6",
            "missing.pdf",
        )
        with self.assertRaises(FileNotFoundError):
            asyncio.run(_gemini_document_card_download(page, candidate, 1000))
        cards.get_by_role.assert_called_once_with(
            "button", name="missing.pdf", exact=True
        )

    def test_image_downloads_are_bounded_and_keep_success_order(self):
        class FakeResponse:
            def __init__(self, ok, payload):
                self.ok = ok
                self.payload = payload
                self.headers = {}

            async def body(self):
                return self.payload

        class FakeRequest:
            def __init__(self):
                self.active = 0
                self.max_active = 0

            async def get(self, src, timeout):
                self.assert_timeout = timeout
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                try:
                    await asyncio.sleep(0.01)
                    if src.endswith(".jpg"):
                        payload = b"\xff\xd8\xff" + src.encode("utf-8")
                    elif src.endswith(".webp"):
                        payload = b"RIFF\x00\x00\x00\x00WEBP" + src.encode("utf-8")
                    else:
                        payload = b"\x89PNG\r\n\x1a\n" + src.encode("utf-8")
                    return FakeResponse("fail" not in src, payload)
                finally:
                    self.active -= 1

        request = FakeRequest()
        page = SimpleNamespace(request=request)
        candidates = [
            "https://example.com/a.png",
            "https://example.com/fail.png",
            "https://example.com/b.jpg",
            "https://example.com/c.webp",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            image_map = asyncio.run(_download_image_candidates(
                page,
                candidates,
                Path(temp_dir),
                "./assets",
                concurrency=2,
            ))
            files = sorted(Path(temp_dir).iterdir())
            self.assertEqual(len(files), 3)
            self.assertEqual(
                [path.read_bytes() for path in files],
                [
                    b"\x89PNG\r\n\x1a\nhttps://example.com/a.png",
                    b"\xff\xd8\xffhttps://example.com/b.jpg",
                    b"RIFF\x00\x00\x00\x00WEBPhttps://example.com/c.webp",
                ],
            )

        self.assertEqual(request.max_active, 2)
        self.assertEqual(list(image_map), [
            "https://example.com/a.png",
            "https://example.com/b.jpg",
            "https://example.com/c.webp",
        ])
        self.assertTrue(image_map[candidates[0]].startswith("./assets/img_1_"))
        self.assertTrue(image_map[candidates[2]].startswith("./assets/img_2_"))
        self.assertTrue(image_map[candidates[3]].startswith("./assets/img_3_"))

    def test_image_download_saves_embedded_png_data_url(self):
        source = "data:image/png;base64,iVBORw0KGgpyZWFs"
        with tempfile.TemporaryDirectory() as temp_dir:
            image_map = asyncio.run(_download_image_candidates(
                SimpleNamespace(),
                [source],
                Path(temp_dir),
                "./assets",
            ))
            saved = Path(temp_dir) / Path(image_map[source]).name
            self.assertTrue(saved.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_image_download_falls_back_to_page_fetch_after_http_failure(self):
        class FakeResponse:
            ok = False
            status = 403
            headers = {}

        class FakeRequest:
            async def get(self, src, timeout):
                return FakeResponse()

        class FakePage:
            request = FakeRequest()

            def __init__(self):
                self.fetches = []

            async def evaluate(self, script, src):
                self.fetches.append(src)
                return "data:;base64,iVBORw0KGgpyZWFs"

        source = "https://example.com/protected.png"
        page = FakePage()
        with tempfile.TemporaryDirectory() as temp_dir:
            image_map = asyncio.run(_download_image_candidates(
                page,
                [source],
                Path(temp_dir),
                "./assets",
            ))
            saved = Path(temp_dir) / Path(image_map[source]).name
            self.assertTrue(saved.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

        self.assertEqual(page.fetches, [source])

    def test_unloaded_gemini_image_still_uses_network_download(self):
        source = "https://lh3.googleusercontent.com/gg/example"

        class FakeResponse:
            ok = True
            headers = {"content-type": "image/png"}

            async def body(self):
                return b"\x89PNG\r\n\x1a\nreal"

        class FakeImage:
            async def get_attribute(self, name):
                return source if name == "src" else None

            async def scroll_into_view_if_needed(self, timeout):
                return None

            async def evaluate(self, script):
                return False if "new Promise" in script else [0, 0]

        class FakeImages:
            async def count(self):
                return 1

            def nth(self, index):
                return FakeImage()

        class FakeRequest:
            async def get(self, src, timeout):
                return FakeResponse()

        class FakePage:
            request = FakeRequest()

            def locator(self, selector):
                return FakeImages()

        with tempfile.TemporaryDirectory() as temp_dir:
            image_map = asyncio.run(_download_image_candidates(
                FakePage(), [source], Path(temp_dir), "./images",
            ))
            saved = Path(temp_dir) / Path(image_map[source]).name
            self.assertEqual(saved.read_bytes(), b"\x89PNG\r\n\x1a\nreal")

    def test_gemini_fallback_exports_full_decoded_image_without_lightbox(self):
        source = "https://lh3.googleusercontent.com/gg/example"

        class FakeResponse:
            ok = False
            status = 403
            headers = {}

        class FakeRequest:
            async def get(self, src, timeout):
                return FakeResponse()

        class FakeImage:
            async def get_attribute(self, name):
                return source if name == "src" else None

            async def is_visible(self):
                return True

            async def scroll_into_view_if_needed(self, timeout):
                return None

            async def evaluate(self, script):
                if "trae-gemini-full-image" in script:
                    return "full-image"
                if "currentSrc" in script:
                    return [None, source, None]
                if "new Promise" in script:
                    return True
                return [640, 480]

            async def screenshot(self, **kwargs):
                return b"\x89PNG\r\n\x1a\nrendered"

        class FakeImages:
            async def count(self):
                return 1

            def nth(self, index):
                return FakeImage()

        class FakePage:
            request = FakeRequest()

            async def evaluate(self, script, src):
                raise TimeoutError

            def locator(self, selector):
                return FakeImage() if selector.startswith("#") else FakeImages()

        with tempfile.TemporaryDirectory() as temp_dir:
            image_map = asyncio.run(_download_image_candidates(
                FakePage(), [source], Path(temp_dir), "./images"
            ))
            saved = Path(temp_dir) / Path(image_map[source]).name
            self.assertEqual(saved.read_bytes(), b"\x89PNG\r\n\x1a\nrendered")

    def test_concurrent_gemini_screenshots_never_overlap(self):
        sources = ['https://lh3.googleusercontent.com/gg/one', 'https://lh3.googleusercontent.com/gg/two']
        active = set()
        class Image:
            def __init__(self, source):
                self.source = source
            async def get_attribute(self, name):
                return self.source if name == 'src' else None
            async def scroll_into_view_if_needed(self, **kwargs):
                self.assert_no_overlay()
            def assert_no_overlay(self):
                if active:
                    raise AssertionError('another screenshot is still visible')
            async def evaluate(self, script):
                if 'trae-gemini-full-image' in script:
                    self.assert_no_overlay()
                    active.add(self.source)
                    await asyncio.sleep(0.01)
                    return str(sources.index(self.source))
                if 'currentSrc' in script:
                    return [self.source, self.source, None]
                if 'new Promise' in script:
                    return True
                if 'remove()' in script:
                    active.remove(self.source)
                    return None
                return [640, 480]
            async def screenshot(self, **kwargs):
                await asyncio.sleep(0.01)
                if active != {self.source}:
                    raise AssertionError('overlapping screenshots captured the wrong image')
                return b'\x89PNG\r\n\x1a\n' + self.source.encode()
        class Images:
            async def count(self):
                return len(sources)
            def nth(self, index):
                return Image(sources[index])
        class Page:
            request = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(ok=False,status=403)))
            async def evaluate(self, *args):
                return None
            def locator(self, selector):
                return Image(sources[int(selector[1:])]) if selector.startswith('#') else Images()
        warnings = []
        with tempfile.TemporaryDirectory() as temp_dir:
            mapping = asyncio.run(_download_image_candidates(Page(), sources, Path(temp_dir), './images', warning_collector=warnings))
            self.assertEqual(len(mapping), 2)
            for source in sources:
                self.assertEqual((Path(temp_dir)/Path(mapping[source]).name).read_bytes(), b'\x89PNG\r\n\x1a\n' + source.encode())
        self.assertEqual(warnings, [])
        self.assertEqual(active, set())

    def test_existing_image_directory_stays_concurrent_and_deduplicated(self):
        class FakeResponse:
            def __init__(self, ok, payload):
                self.ok = ok
                self.payload = payload
                self.headers = {}

            async def body(self):
                return self.payload

        class FakeRequest:
            def __init__(self):
                self.active = 0
                self.max_active = 0
                self.calls = {}

            async def get(self, src, timeout):
                self.calls[src] = self.calls.get(src, 0) + 1
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                try:
                    await asyncio.sleep(0.01)
                    payload = b"\xff\xd8\xff" + src.encode("utf-8")
                    return FakeResponse("fail" not in src, payload)
                finally:
                    self.active -= 1

        existing = "https://example.com/already.png"
        failing = "https://example.com/fail.png"
        fresh = "https://example.com/new.jpg"
        favicon = (
            "https://www.google.com/s2/favicons?"
            "domain=https://www.reddit.com&sz=128"
        )
        request = FakeRequest()
        page = SimpleNamespace(request=request)
        warnings = []
        failures = {existing: "old_error"}
        with tempfile.TemporaryDirectory() as temp_dir:
            images_dir = Path(temp_dir)
            digest = hashlib.md5(existing.encode("utf-8")).hexdigest()[:8]
            existing_file = images_dir / f"img_7_{digest}.png"
            existing_file.write_bytes(b"\x89PNG\r\n\x1a\nexisting")
            image_map = asyncio.run(_download_image_candidates(
                page,
                [existing, failing, failing, failing, favicon, fresh],
                images_dir,
                "./assets",
                concurrency=2,
                warning_collector=warnings,
                failure_collector=failures,
            ))

            self.assertEqual(
                existing_file.read_bytes(), b"\x89PNG\r\n\x1a\nexisting"
            )
            self.assertEqual(len(list(images_dir.iterdir())), 2)

        self.assertEqual(request.calls.get(existing, 0), 0)
        self.assertEqual(request.calls.get(failing), 2)
        self.assertEqual(request.calls.get(fresh), 1)
        self.assertEqual(request.calls.get(favicon, 0), 0)
        self.assertEqual(request.max_active, 2)
        self.assertEqual(len(warnings), 1)
        self.assertIn("1 个真实图片资源下载失败", warnings[0])
        self.assertEqual(set(failures), {failing})
        self.assertEqual(list(image_map), [existing, fresh])
        self.assertEqual(image_map[existing], f"./assets/{existing_file.name}")
        self.assertTrue(image_map[fresh].startswith("./assets/img_8_"))

    def test_unavailable_assets_keep_names_in_messages(self):
        image_url = "https://example.com/photo.png"
        document = DocumentCandidate(
            "document-card", "https://example.com/report.pdf", "report.pdf"
        )
        messages = [{
            "role": "AI",
            "content": (
                f"![分析图]({image_url})\n"
                f"[下载报告]({document.url})\n"
                "report.pdf\n"
                "📎 **[上传文件]** `notes.docx`"
            ),
        }]
        _mark_unavailable_assets(
            messages,
            {image_url: "http_403"},
            {document: "http_403"},
        )
        content = messages[0]["content"]
        self.assertIn("🖼️ **[图片]** `分析图`（原图片未能下载）", content)
        self.assertEqual(
            content.count("📎 **[上传文档]** `report.pdf`（原文件未能下载）"),
            2,
        )
        self.assertIn("📎 **[上传文件]** `notes.docx`（原文件未能下载）", content)

    def test_image_download_follows_signed_metadata_and_skips_stale_json(self):
        source = "https://chatgpt.com/backend-api/files/download/file_image"
        signed = "https://example.com/signed.png"

        class FakeResponse:
            def __init__(self, body, content_type):
                self.ok = True
                self.status = 200
                self.payload = body
                self.headers = {"content-type": content_type}

            async def body(self):
                return self.payload

            async def json(self):
                return {"download_url": signed}

        class FakeRequest:
            def __init__(self):
                self.calls = []

            async def get(self, src, timeout):
                self.calls.append(src)
                if src == source:
                    return FakeResponse(b'{"status":"success"}', "application/json")
                return FakeResponse(b"\x89PNG\r\n\x1a\nreal", "image/png")

        request = FakeRequest()
        with tempfile.TemporaryDirectory() as temp_dir:
            images_dir = Path(temp_dir)
            digest = hashlib.md5(source.encode("utf-8")).hexdigest()[:8]
            stale = images_dir / f"img_1_{digest}.png"
            stale.write_bytes(b'{"status":"success"}')
            image_map = asyncio.run(_download_image_candidates(
                SimpleNamespace(request=request),
                [source],
                images_dir,
                "./assets",
            ))
            saved = images_dir / Path(image_map[source]).name
            self.assertEqual(saved.read_bytes(), b"\x89PNG\r\n\x1a\nreal")
            self.assertNotEqual(saved, stale)

        self.assertEqual(request.calls, [source, signed])

    def test_image_download_retries_owned_chatgpt_file_without_share_scope(self):
        share_id = "6aa95199-4040-83e8-b16a-4be411338d94"
        source = (
            "https://chatgpt.com/backend-api/files/download/file_image"
            f"?shared_conversation_id={share_id}"
        )
        private_source = (
            "https://chatgpt.com/backend-api/files/download/file_image"
            "?post_id=&inline=false&download_intent=false"
        )

        class FakeResponse:
            ok = True
            status = 200

            def __init__(self, payload, content_type):
                self.payload = payload
                self.headers = {"content-type": content_type}

            async def body(self):
                return self.payload

            async def json(self):
                return {"error_code": "safety_check_failed"}

        class FakeRequest:
            def __init__(self):
                self.calls = []

            async def get(self, src, timeout):
                self.calls.append(src)
                if src == source:
                    return FakeResponse(b"{}", "application/json")
                if src == private_source:
                    response = FakeResponse(b"{}", "application/json")
                    response.json = lambda: asyncio.sleep(
                        0, result={"download_url": "https://example.com/signed.png"}
                    )
                    return response
                return FakeResponse(b"\x89PNG\r\n\x1a\nreal", "image/png")

        request = FakeRequest()
        with tempfile.TemporaryDirectory() as temp_dir:
            image_map = asyncio.run(_download_image_candidates(
                SimpleNamespace(request=request),
                [source],
                Path(temp_dir),
                "./assets",
            ))
            saved = Path(temp_dir) / Path(image_map[source]).name
            self.assertEqual(saved.read_bytes(), b"\x89PNG\r\n\x1a\nreal")

        self.assertEqual(
            request.calls,
            [source, private_source, "https://example.com/signed.png"],
        )

    def test_image_download_reports_chatgpt_login_requirement(self):
        share_id = "6aa93ca3-11c0-83e8-9c36-afa39378a735"
        source = (
            "https://chatgpt.com/backend-api/files/download/file_image"
            f"?shared_conversation_id={share_id}"
        )

        class FakeResponse:
            def __init__(self, ok, status, payload):
                self.ok = ok
                self.status = status
                self.payload = payload
                self.headers = {"content-type": "application/json"}

            async def json(self):
                return self.payload

        class FakeRequest:
            async def get(self, src, timeout):
                if "shared_conversation_id" in src:
                    return FakeResponse(
                        True, 200, {"error_code": "safety_check_failed"}
                    )
                return FakeResponse(False, 403, {"detail": "Forbidden"})

        authentication_required = []
        warnings = []
        with tempfile.TemporaryDirectory() as temp_dir:
            image_map = asyncio.run(_download_image_candidates(
                SimpleNamespace(request=FakeRequest()),
                [source],
                Path(temp_dir),
                "./assets",
                warning_collector=warnings,
                authentication_required=authentication_required,
            ))

        self.assertEqual(image_map, {})
        self.assertEqual(authentication_required, [True])
        self.assertIn("http_403", warnings[0])

    def test_browser_cleanup_failure_becomes_warning(self):
        class BrokenContext:
            async def close(self):
                raise RuntimeError(
                    "Connection closed while reading from the driver"
                )

        warnings = []
        messages = []
        asyncio.run(_close_browser_context_safely(
            BrokenContext(), warnings, messages.append
        ))

        self.assertEqual(len(warnings), 1)
        self.assertIn("浏览器清理异常", warnings[0])
        self.assertEqual(messages, warnings)

    def test_browser_cleanup_timeout_becomes_warning(self):
        class HangingContext:
            async def close(self):
                await asyncio.Event().wait()

        observed_timeouts = []

        async def timeout_immediately(awaitable, timeout):
            awaitable.close()
            observed_timeouts.append(timeout)
            raise asyncio.TimeoutError

        warnings = []
        with patch(
            "gui.service.asyncio.wait_for",
            new=timeout_immediately,
        ):
            asyncio.run(_close_browser_context_safely(
                HangingContext(), warnings
            ))

        self.assertEqual(observed_timeouts, [10])
        self.assertEqual(len(warnings), 1)
        self.assertIn("浏览器清理异常", warnings[0])

    def test_image_asset_directory_sits_beside_markdown_outputs(self):
        base = Path("用户结果")
        asset_dir = build_image_asset_directory(base, "课程 总结.txt")
        self.assertEqual(asset_dir, base / "课程 总结_images")
        self.assertEqual(
            build_markdown_asset_prefix(asset_dir, base),
            "./%E8%AF%BE%E7%A8%8B%20%E6%80%BB%E7%BB%93_images",
        )
        absolute_base = Path.cwd() / "用户结果"
        self.assertEqual(
            build_markdown_asset_prefix(
                absolute_base / "课程 总结_images",
                absolute_base,
            ),
            "./%E8%AF%BE%E7%A8%8B%20%E6%80%BB%E7%BB%93_images",
        )
        self.assertEqual(
            build_image_asset_prefix(asset_dir),
            asset_dir.resolve().as_uri(),
        )

    def test_custom_runtime_directory_owns_summary_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime-data"
            self.assertEqual(
                default_summary_result_cache_dir(runtime_dir),
                runtime_dir.resolve() / "summary_results",
            )

    def test_output_filename_defaults_and_md_normalization(self):
        self.assertEqual(
            default_output_filename({"normal": True}),
            "AI_memory_summary.md",
        )
        self.assertEqual(
            default_output_filename({"raw": True, "normal": True}),
            "AI_memory.md",
        )
        self.assertEqual(
            normalize_markdown_filename("我的总结.txt"),
            "我的总结.md",
        )
        self.assertEqual(
            normalize_markdown_filename("我的总结.MD"),
            "我的总结.md",
        )

    def test_custom_output_paths_for_single_and_multiple_modes(self):
        base = Path("output")
        single = build_output_paths(
            base,
            {"normal": True},
            "课程总结.txt",
        )
        self.assertEqual(single["asset_markdown"].name, "课程总结.md")
        self.assertEqual(single["normal_markdown"].name, "课程总结.md")
        self.assertEqual(single["normal_json"].name, "课程总结.json")

        multiple = build_output_paths(
            base,
            {
                "raw": True,
                "normal": True,
                "simple": True,
                "detailed": True,
            },
            "课程总结.md",
        )
        self.assertEqual(
            multiple["asset_markdown"].name,
            "课程总结_export.md",
        )
        self.assertEqual(
            build_image_asset_directory(
                base, multiple["asset_markdown"].name
            ),
            base / "课程总结_export_images",
        )
        self.assertEqual(
            multiple["raw_markdown"].name,
            "课程总结_export.md",
        )
        self.assertEqual(
            multiple["normal_markdown"].name,
            "课程总结_summary.md",
        )
        self.assertEqual(
            multiple["normal_json"].name,
            "课程总结_result.json",
        )
        self.assertEqual(
            multiple["simple_markdown"].name,
            "课程总结_simple.md",
        )
        self.assertEqual(
            multiple["detailed_markdown"].name,
            "课程总结_detailed_summary.md",
        )
        self.assertEqual(
            multiple["detailed_json"].name,
            "课程总结_detailed_result.json",
        )

    def test_fallback_parser_works_consistently(self):
        html = "<div><p>用户输入问题</p><p>回答</p><p>这是AI的回复内容</p></div>"
        soup = BeautifulSoup(html, "html.parser")
        messages = parse_fallback_messages_gui(soup)
        self.assertTrue(len(messages) >= 1)

    def test_doubao_shell_is_not_parsed_as_conversation(self):
        soup = BeautifulSoup(
            "<html><title>豆包 - 你的 AI 智能助手</title></html>",
            "html.parser",
        )
        provider, messages = _parse_page_messages(
            "https://www.doubao.com/thread/example",
            soup,
            {},
        )
        self.assertIsNone(provider)
        self.assertIsNone(messages)

    def test_chatgpt_error_shell_is_not_fallback_parsed(self):
        soup = BeautifulSoup(
            "<html><body><h1>Something went wrong</h1><p>Try again</p></body></html>",
            "html.parser",
        )
        provider, messages = _parse_page_messages(
            "https://chatgpt.com/c/example", soup, {}
        )
        self.assertIsNone(provider)
        self.assertIsNone(messages)

    def test_chatgpt_rehydrate_keeps_full_body_when_same_nodes_turn_empty(self):
        before = (
            '<div data-message-author-role="user"><p>问题</p></div>'
            '<div data-message-author-role="assistant">'
            '<div class="markdown"><p>完整回答</p></div></div>'
        )
        after = (
            '<div data-message-author-role="user"><p>问题</p></div>'
            '<div data-message-author-role="assistant">'
            '<h5 class="sr-only">ChatGPT 说：</h5><div>来源</div></div>'
        )
        merged = _merge_chatgpt_rehydrate_html(before, after)
        self.assertIn("完整回答", merged)
        self.assertNotIn("ChatGPT 说", merged)
        self.assertNotIn("来源", merged)

    def test_chatgpt_current_share_turn_is_conversation_content(self):
        class Locator:
            async def count(self):
                return 1

        class Page:
            url = "https://chatgpt.com/share/example"
            selector = ""

            async def wait_for_selector(self, selector, state, timeout):
                self.selector = selector

            def locator(self, selector):
                self.selector = selector
                return Locator()

        page = Page()
        ready = asyncio.run(_page_has_conversation_content(
            page,
            "https://chatgpt.com/share/example",
        ))
        self.assertTrue(ready)
        self.assertIn("data-chatgpt-search-unit-key", page.selector)

    def test_doubao_home_message_item_is_not_conversation_content(self):
        class Locator:
            async def count(self):
                return 0

        class Page:
            url = "https://www.doubao.com/"
            selector = ""

            async def wait_for_selector(self, selector, state, timeout):
                self.selector = selector

            def locator(self, selector):
                self.selector = selector
                return Locator()

        page = Page()
        ready = asyncio.run(_page_has_conversation_content(
            page,
            "https://www.doubao.com/chat/38441607137483266",
        ))
        self.assertFalse(ready)
        self.assertNotIn(".message-item", page.selector)

    def test_generate_raw_markdown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "output.md"
            messages = [
                {
                    "role": "User",
                    "content": "![截图](./output_images/截图.png)\n\n"
                    "📎 [资料](./output_files/中文 资料.pdf)",
                },
                {"role": "AI", "content": "你好！有什么我可以帮你的？"},
            ]
            generate_raw_markdown(messages, target)
            self.assertTrue(target.is_file())
            content = target.read_text(encoding="utf-8")
            self.assertIn("# AI 对话记忆导出", content)
            self.assertIn("用户提问", content)
            self.assertIn("AI 回答", content)
            self.assertIn("![截图](./output_images/截图.png)", content)
            self.assertIn("[资料](./output_files/中文 资料.pdf)", content)

    def test_normal_and_detailed_reuse_one_result_and_one_selection(self):
        messages = [
            {"role": "User", "content": "请解释这段代码"},
            {"role": "AI", "content": "这是一个示例解释。"},
        ]
        fake_result = {
            "typed_records": {"programming": [{"topic": "示例"}]},
            "topics": [{"title": "主题一", "summary": "摘要"}],
        }
        summarize_calls = []
        detailed_calls = []
        selector_calls = []

        def fake_summarize(**kwargs):
            summarize_calls.append(kwargs)
            selected = kwargs["section_selector"](fake_result)
            self.assertEqual(selected, ("programming",))
            kwargs["output_json"].write_text("{}", encoding="utf-8")
            kwargs["output_markdown"].write_text("normal", encoding="utf-8")
            return fake_result

        def fake_write(
            result, output_json, output_markdown,
            include_details=False, selected_sections=None,
            selected_topics=None
        ):
            detailed_calls.append({
                "result": result,
                "include_details": include_details,
                "selected_sections": tuple(selected_sections or ()),
                "selected_topics": tuple(selected_topics or ()),
            })
            output_json.write_text("{}", encoding="utf-8")
            output_markdown.write_text("detailed", encoding="utf-8")

        def selector(result):
            selector_calls.append(result)
            return ("programming",)

        fake_config = SimpleNamespace(provider="test", model="fake-model")
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "scripts.gemini_summarizer.create_gateway", return_value=object()
        ), patch(
            "scripts.gemini_summarizer.summarize_conversation",
            side_effect=fake_summarize,
        ), patch(
            "scripts.gemini_summarizer.write_summary_outputs",
            side_effect=fake_write,
        ):
            bundle = generate_output_bundle(
                messages,
                {"normal": True, "detailed": True, "simple": False},
                Path(temp_dir),
                section_selector=selector,
                config=fake_config,
            )

        self.assertEqual(len(summarize_calls), 1)
        self.assertEqual(selector_calls, [fake_result])
        self.assertEqual(bundle.selected_sections, ("programming",))
        self.assertEqual(len(detailed_calls), 1)
        self.assertTrue(detailed_calls[0]["include_details"])
        self.assertEqual(
            detailed_calls[0]["selected_sections"], ("programming",)
        )
        self.assertEqual(detailed_calls[0]["selected_topics"], ())
        self.assertEqual(
            [path.name for path in bundle.saved_files],
            [
                "AI_memory_summary.md",
                "AI_memory_result.json",
                "AI_memory_detailed_summary.md",
                "AI_memory_detailed_result.json",
            ],
        )

    def test_detailed_only_writes_no_unrequested_normal_files(self):
        messages = [
            {"role": "User", "content": "计算 1+1"},
            {"role": "AI", "content": "结果是 2。"},
        ]
        captured = {}

        def fake_summarize(**kwargs):
            captured.update(kwargs)
            kwargs["section_selector"]({
                "typed_records": {"calculations": [{"topic": "加法"}]}
            })
            kwargs["output_json"].write_text("{}", encoding="utf-8")
            kwargs["output_markdown"].write_text("detailed", encoding="utf-8")
            return {"typed_records": {}}

        fake_config = SimpleNamespace(provider="test", model="fake-model")
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "scripts.gemini_summarizer.create_gateway", return_value=object()
        ), patch(
            "scripts.gemini_summarizer.summarize_conversation",
            side_effect=fake_summarize,
        ):
            output_dir = Path(temp_dir)
            bundle = generate_output_bundle(
                messages,
                {"normal": False, "detailed": True, "simple": False},
                output_dir,
                section_selector=lambda _result: ("calculations",),
                config=fake_config,
                source_name="原始对话.md",
                source_dir=output_dir / "input",
            )
            self.assertFalse((output_dir / "AI_memory_summary.md").exists())
            self.assertFalse((output_dir / "AI_memory_result.json").exists())

        self.assertTrue(captured["include_details"])
        self.assertEqual(
            captured["source_dir"], (output_dir / "input").resolve()
        )
        self.assertEqual(
            captured["source_name"],
            "原始对话.md",
        )
        self.assertEqual(bundle.selected_sections, ("calculations",))
        self.assertEqual(
            [path.name for path in bundle.saved_files],
            ["AI_memory_detailed_summary.md", "AI_memory_detailed_result.json"],
        )

    def test_gui_topic_selection_is_reused_by_normal_and_detailed(self):
        messages = [
            {"role": "User", "content": "先讨论代码，再讨论部署"},
            {"role": "AI", "content": "已分别说明。"},
        ]
        fake_result = {
            "typed_records": {},
            "topics": [
                {
                    "topic_id": "topic_1",
                    "title": "代码实现",
                    "summary": "代码主题摘要",
                    "memory_ids": ["M1"],
                    "source_message_ids": [1, 2],
                },
                {
                    "topic_id": "topic_2",
                    "title": "部署流程",
                    "summary": "部署主题摘要",
                    "memory_ids": ["M2"],
                    "source_message_ids": [1, 2],
                },
            ],
        }
        detailed_calls = []

        def fake_summarize(**kwargs):
            self.assertIsNone(kwargs["section_selector"])
            selected = kwargs["topic_selector"](fake_result)
            self.assertEqual(selected, ("topic_2",))
            kwargs["output_json"].write_text("{}", encoding="utf-8")
            kwargs["output_markdown"].write_text("normal", encoding="utf-8")
            return fake_result

        def fake_write(
            _result, output_json, output_markdown,
            include_details=False, selected_sections=None,
            selected_topics=None
        ):
            detailed_calls.append({
                "include_details": include_details,
                "selected_sections": tuple(selected_sections or ()),
                "selected_topics": tuple(selected_topics or ()),
            })
            output_json.write_text("{}", encoding="utf-8")
            output_markdown.write_text("detailed", encoding="utf-8")

        fake_config = SimpleNamespace(provider="test", model="fake-model")
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "scripts.gemini_summarizer.create_gateway", return_value=object()
        ), patch(
            "scripts.gemini_summarizer.summarize_conversation",
            side_effect=fake_summarize,
        ), patch(
            "scripts.gemini_summarizer.write_summary_outputs",
            side_effect=fake_write,
        ):
            bundle = generate_output_bundle(
                messages,
                {"normal": True, "detailed": True, "simple": False},
                Path(temp_dir),
                topic_selector=lambda _result: ("topic_2",),
                config=fake_config,
            )

        self.assertEqual(bundle.selected_sections, ())
        self.assertEqual(bundle.selected_topics, ("topic_2",))
        self.assertEqual(len(detailed_calls), 1)
        self.assertTrue(detailed_calls[0]["include_details"])
        self.assertEqual(detailed_calls[0]["selected_sections"], ())
        self.assertEqual(detailed_calls[0]["selected_topics"], ("topic_2",))

    def test_gui_model_candidates_stay_within_the_same_provider(self):
        gemini = SummaryConfig(
            provider="gemini",
            model="gemini-3.5-flash",
            retries=3,
            rate_limit_wait_seconds=65,
        )
        gemini_candidates = gui_summary_config_candidates(gemini)
        self.assertEqual(
            [(item.provider, item.model) for item in gemini_candidates],
            [
                ("gemini", "gemini-3.5-flash"),
                ("gemini", "gemini-3.6-flash"),
                ("gemini", "gemini-3.5-flash-lite"),
            ],
        )
        self.assertTrue(all(item.retries == 2 for item in gemini_candidates))

        silicon = SummaryConfig(
            provider="siliconflow",
            model="Qwen/Qwen3-8B",
        )
        silicon_candidates = gui_summary_config_candidates(silicon)
        self.assertEqual(
            [(item.provider, item.model) for item in silicon_candidates],
            [("siliconflow", "Qwen/Qwen3-8B")],
        )
        self.assertTrue(
            all(item.retries == 2 for item in silicon_candidates)
        )

    def test_gui_falls_back_to_next_gemini_model_without_reprompting(self):
        messages = [
            {"role": "User", "content": "你好"},
            {"role": "AI", "content": "你好！"},
        ]
        base_config = SummaryConfig(
            provider="gemini",
            model="gemini-3.5-flash",
        )
        attempted_models = []
        selector_calls = []
        fake_result = {"typed_records": {}, "topics": []}

        def fake_summarize(**kwargs):
            model = kwargs["config"].model
            attempted_models.append(model)
            if model == "gemini-3.5-flash":
                raise GeminiSummaryError("模拟额度限制")
            selector_calls.append(kwargs["section_selector"](fake_result))
            kwargs["output_json"].write_text("{}", encoding="utf-8")
            kwargs["output_markdown"].write_text("normal", encoding="utf-8")
            return fake_result

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "scripts.gemini_summarizer.SummaryConfig.from_env",
            return_value=base_config,
        ), patch(
            "scripts.gemini_summarizer.create_gateway",
            side_effect=lambda config: config.model,
        ), patch(
            "scripts.gemini_summarizer.summarize_conversation",
            side_effect=fake_summarize,
        ):
            bundle = generate_output_bundle(
                messages,
                {"normal": True, "detailed": False, "simple": False},
                Path(temp_dir),
                section_selector=lambda _result: (),
            )

        self.assertEqual(
            attempted_models,
            ["gemini-3.5-flash", "gemini-3.6-flash"],
        )
        self.assertEqual(selector_calls, [()])
        self.assertEqual(bundle.summary_result, fake_result)


    def test_private_conversation_urls_require_authenticated_browser(self):
        self.assertTrue(requires_authenticated_browser(
            "https://chatgpt.com/c/11111111-2222-3333-4444-555555555555"
        ))
        self.assertTrue(requires_authenticated_browser(
            "https://chat.deepseek.com/a/chat/s/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        ))
        self.assertFalse(requires_authenticated_browser(
            "https://chatgpt.com/share/6a60329f-c73c-83ee-a272-ea3768b04ab5"
        ))
        self.assertFalse(requires_authenticated_browser(
            "https://chat.deepseek.com/share/xxv4e99bimvt1p0uo2"
        ))

    def test_document_candidates_download_beside_markdown(self):
        class FakeResponse:
            ok = True
            status = 200
            headers = {
                "content-type": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                "content-disposition": "filename*=UTF-8''%E6%8A%A5%E5%91%8A.docx",
            }

            async def body(self):
                return b"PK\x03\x04fake-docx"

        class FakeRequest:
            def __init__(self):
                self.urls = []

            async def get(self, url, timeout):
                self.urls.append((url, timeout))
                return FakeResponse()

        page = SimpleNamespace(request=FakeRequest())
        html = (
            '<div data-testid="conversation-turn-1">'
            '<a href="/backend-api/files/download?id=secret" '
            'download="报告.docx">报告.docx</a></div>'
        )
        candidates = _extract_document_candidates(
            html, "https://chatgpt.com/c/conversation-id"
        )
        self.assertEqual(len(candidates), 1)
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "result_files"
            mapping = asyncio.run(_download_document_candidates(
                page,
                candidates,
                output_dir,
                "./result_files",
            ))
            saved = list(output_dir.iterdir())
            self.assertEqual([path.name for path in saved], ["报告.docx"])
            self.assertEqual(saved[0].read_bytes(), b"PK\x03\x04fake-docx")
            self.assertEqual(mapping["报告.docx"], "./result_files/%E6%8A%A5%E5%91%8A.docx")
            self.assertNotIn("secret", " ".join(mapping.values()))

    def test_document_link_encodes_spaces_and_markdown_delimiters(self):
        from urllib.parse import unquote, quote
        filename = '新建 文本文档 (1)#%.txt'
        response = SimpleNamespace(ok=True, headers={'content-type': 'text/plain'}, body=AsyncMock(return_value=b'original file content'))
        page = SimpleNamespace(request=SimpleNamespace(get=AsyncMock(return_value=response)))
        candidate = DocumentCandidate('file_ref', 'https://example.com/file', filename)
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / 'documents'
            mapping = asyncio.run(_download_document_candidates(page, [candidate], folder, './documents'))
            reference = mapping[candidate.reference]
            self.assertEqual(reference, './documents/' + quote(filename, safe=''))
            self.assertEqual((Path(temp_dir) / unquote(reference)).read_bytes(), b'original file content')
            self.assertEqual([path.name for path in folder.iterdir()], [filename])

    def test_chatgpt_document_retries_without_share_scope(self):
        share_id = "6aa93ca3-11c0-83e8-9c36-afa39378a735"
        source = (
            "https://chatgpt.com/backend-api/files/download/file_csv"
            f"?shared_conversation_id={share_id}"
        )
        private_source = (
            "https://chatgpt.com/backend-api/files/download/file_csv"
            "?post_id=&inline=false&download_intent=false"
        )

        class FakeResponse:
            ok = True
            status = 200

            def __init__(self, payload, content_type):
                self.payload = payload
                self.headers = {"content-type": content_type}

            async def body(self):
                return self.payload

            async def json(self):
                return {"error_code": "safety_check_failed"}

        class FakeRequest:
            def __init__(self):
                self.calls = []

            async def get(self, url, timeout):
                self.calls.append(url)
                if url == source:
                    return FakeResponse(b"{}", "application/json")
                return FakeResponse(b"a,b\n1,2\n", "text/csv")

        request = FakeRequest()
        candidate = DocumentCandidate("file_csv", source, "data.csv")
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "result_files"
            mapping = asyncio.run(_download_document_candidates(
                SimpleNamespace(request=request),
                [candidate],
                output_dir,
                "./result_files",
                conversation_url=f"https://chatgpt.com/share/{share_id}",
            ))
            self.assertEqual((output_dir / "data.csv").read_bytes(), b"a,b\n1,2\n")

        self.assertEqual(request.calls, [source, private_source])
        self.assertEqual(mapping["data.csv"], "./result_files/data.csv")

    def test_document_candidates_reject_local_and_credential_urls(self):
        html = (
            '<a href="http://127.0.0.1/private.pdf">private.pdf</a>'
            '<a href="http://192.168.1.10/report.docx">report.docx</a>'
            '<a href="https://user:password@example.com/secret.pdf">'
            'secret.pdf</a>'
        )
        self.assertEqual(
            _extract_document_candidates(html, "https://chatgpt.com/c/example"),
            [],
        )

    def test_chatgpt_embedded_document_metadata_becomes_session_download(self):
        html = (
            '<script>self.__next_f.push([1,"'
            r'"file","name","课堂材料.docx",'
            r'"file_test1234567890abcdef",'
            r'"source","my_files","library_file_id"'
            '"])</script>'
        )
        candidates = _extract_document_candidates(
            html,
            "https://chatgpt.com/c/conversation-id",
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].filename, "课堂材料.docx")
        self.assertEqual(
            candidates[0].url,
            "https://chatgpt.com/backend-api/files/download/"
            "file_test1234567890abcdef",
        )

        shared = _extract_document_candidates(
            html,
            "https://chatgpt.com/share/6a60329f-c73c-83ee-a272-ea3768b04ab5",
        )
        self.assertEqual(
            shared[0].url,
            "https://chatgpt.com/backend-api/files/download/"
            "file_test1234567890abcdef"
            "?shared_conversation_id=6a60329f-c73c-83ee-a272-ea3768b04ab5",
        )

    def test_authorized_platform_responses_produce_downloadable_documents(self):
        chatgpt_documents = []
        chatgpt_images = set()
        _collect_response_assets(
            {
                "messages": [{
                    "metadata": {
                        "attachments": [
                            {
                                "id": "file_document123456",
                                "name": "课堂材料.md",
                                "mime_type": "text/markdown",
                            },
                            {
                                "id": "file_image123456",
                                "name": "课堂图片.png",
                                "mime_type": "image/png",
                            },
                        ]
                    }
                }]
            },
            "https://chatgpt.com/c/conversation-id",
            chatgpt_documents,
            chatgpt_images,
        )
        self.assertEqual(chatgpt_documents, [DocumentCandidate(
            "file_document123456",
            "https://chatgpt.com/backend-api/files/download/file_document123456",
            "课堂材料.md",
        )])
        self.assertEqual(chatgpt_images, {
            "https://chatgpt.com/backend-api/files/download/file_image123456"
        })

        assistant_documents = []
        _collect_response_assets(
            {"messages": [{
                "author": {"role": "assistant"},
                "metadata": {"attachments": [{
                    "id": "file_citation123456",
                    "name": "tools.md",
                    "mime_type": "text/markdown",
                }]},
            }]},
            "https://chatgpt.com/c/conversation-id",
            assistant_documents,
            set(),
        )
        self.assertEqual(assistant_documents, [])

        video_documents = []
        _collect_response_assets(
            {"attachments": [{
                "id": "file_video123456",
                "name": "测试视频.mp4",
                "mime_type": "video/mp4",
            }]},
            "https://chatgpt.com/c/conversation-id",
            video_documents,
            set(),
        )
        self.assertEqual(video_documents, [DocumentCandidate(
            "file_video123456",
            "https://chatgpt.com/backend-api/files/download/file_video123456",
            "测试视频.mp4",
        )])

        shared_documents = []
        _collect_response_assets(
            {
                "attachments": [{
                    "id": "file_document123456",
                    "name": "课堂材料.md",
                }]
            },
            "https://chatgpt.com/share/6a60329f-c73c-83ee-a272-ea3768b04ab5",
            shared_documents,
            set(),
        )
        self.assertEqual(shared_documents, [DocumentCandidate(
            "file_document123456",
            "https://chatgpt.com/backend-api/files/download/file_document123456"
            "?shared_conversation_id=6a60329f-c73c-83ee-a272-ea3768b04ab5",
            "课堂材料.md",
        )])

        deepseek_documents = []
        _collect_response_assets(
            {
                "files": [{
                    "status": "SUCCESS",
                    "file_name": "资料.md",
                    "signed_path": "/file?file_id=fake&state=signed",
                }]
            },
            "https://chat.deepseek.com/share/example",
            deepseek_documents,
            set(),
        )
        self.assertEqual(len(deepseek_documents), 1)
        self.assertEqual(deepseek_documents[0].url,
            "https://files.deepseeksvc.com/api/file?"
            "file_id=fake&state=signed&ty=r",
        )

        grok_documents = []
        grok_images = set()
        _collect_response_assets(
            {"fileAttachmentsMetadata": [{
                "fileName": "result.xlsx",
                "fileMimeType": (
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                "fileUri": "users/user-id/asset-id/content",
            }]},
            "https://grok.com/c/conversation-id",
            grok_documents,
            grok_images,
        )
        self.assertEqual(grok_documents, [DocumentCandidate(
            "users/user-id/asset-id/content",
            "https://assets.grok.com/users/user-id/asset-id/content",
            "result.xlsx",
        )])

    def test_successful_chatgpt_document_response_is_reused_without_retry(self):
        class FakeResponse:
            status = 200
            url = (
                "https://chatgpt.com/backend-api/estuary/content?"
                "id=file_document123456&sig=authorized"
            )
            headers = {
                "content-type": "text/markdown; charset=utf-8"
            }

            async def body(self):
                return b"# captured document"

        cache = {}
        asyncio.run(_capture_document_content_response(
            FakeResponse(), cache
        ))
        self.assertIn("file_document123456", cache)
        candidate = DocumentCandidate(
            "file_document123456",
            "https://chatgpt.com/backend-api/files/download/"
            "file_document123456",
            "captured.md",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "result_files"
            mapping = asyncio.run(_download_document_candidates(
                SimpleNamespace(),
                [candidate],
                output_dir,
                "./result_files",
                captured_documents=cache,
            ))
            saved = output_dir / "captured.md"
            self.assertEqual(saved.read_bytes(), b"# captured document")
            self.assertIn("captured.md", mapping)

    def test_chatgpt_video_uses_video_size_limit(self):
        body = b"v" * (25 * 1024 * 1024 + 1)
        downloaded = SimpleNamespace(
            ok=True,
            status=200,
            headers={
                "content-type": "video/mp4",
                "content-length": str(len(body)),
            },
            body=AsyncMock(return_value=body),
        )
        candidate = DocumentCandidate(
            "file_video123456",
            "https://chatgpt.com/backend-api/files/download/file_video123456",
            "测试视频.mp4",
        )
        with patch(
            "gui.service._authenticated_page_get",
            new=AsyncMock(return_value=downloaded),
        ), tempfile.TemporaryDirectory() as temp_dir:
            mapping = asyncio.run(_download_document_candidates(
                SimpleNamespace(),
                [candidate],
                Path(temp_dir),
                "./documents",
            ))
            self.assertEqual(mapping["测试视频.mp4"], "./documents/%E6%B5%8B%E8%AF%95%E8%A7%86%E9%A2%91.mp4")
            self.assertEqual((Path(temp_dir) / "测试视频.mp4").stat().st_size, len(body))

    def test_chatgpt_direct_download_retries_rate_limit(self):
        rate_limited = SimpleNamespace(ok=False, status=429, headers={})
        downloaded = SimpleNamespace(
            ok=True,
            status=200,
            headers={"content-type": "text/markdown"},
            body=AsyncMock(return_value=b"# document"),
        )
        page = SimpleNamespace(wait_for_timeout=AsyncMock())
        candidate = DocumentCandidate(
            "file_document123456",
            "https://chatgpt.com/backend-api/files/download/file_document123456",
            "document.md",
        )
        with patch(
            "gui.service._authenticated_page_get",
            new=AsyncMock(side_effect=[rate_limited, downloaded]),
        ) as request, tempfile.TemporaryDirectory() as temp_dir:
            mapping = asyncio.run(_download_document_candidates(
                page,
                [candidate],
                Path(temp_dir),
                "./documents",
            ))
        self.assertEqual(request.await_count, 2)
        self.assertEqual(
            request.await_args_list[0].args[1],
            "https://chatgpt.com/backend-api/files/download/file_document123456",
        )
        page.wait_for_timeout.assert_awaited_once_with(1500)
        self.assertEqual(mapping["document.md"], "./documents/document.md")

    def test_chatgpt_only_real_file_title_nodes_become_click_candidates(self):
        html = """
        <div data-message-author-role="user">
          <p>开头的代码提到 report.pdf，但它只是正文。</p>
          <span class="truncate font-semibold">课堂材料.docx</span>
      <div class="truncate font-semibold">测试视频.mp4</div>
        </div>
        <div data-message-author-role="assistant">
          <div class="truncate font-semibold">引用资料.md</div>
        </div>
        """
        candidates = _extract_chatgpt_document_card_candidates(
            html,
            "https://chatgpt.com/c/conversation-id",
        )
        self.assertEqual(
            [candidate.filename for candidate in candidates],
            ["课堂材料.docx", "测试视频.mp4"],
        )
        self.assertTrue(candidates[0].reference.startswith("chatgpt-card:"))

    def test_chatgpt_assistant_document_citations_are_not_attachments(self):
        html = """
        <div data-message-author-role="user">
          <a href="https://files.example.com/课堂材料.docx">课堂材料.docx</a>
        </div>
        <div data-message-author-role="assistant">
          <a data-testid="chatgpt-citation"
             href="https://github.com/example/repo/blob/main/tools.md">
            tools.md
          </a>
        </div>
        """
        chatgpt_candidates = _extract_document_candidates(
            html,
            "https://chatgpt.com/c/conversation-id",
        )
        self.assertEqual(
            [candidate.filename for candidate in chatgpt_candidates],
            ["课堂材料.docx"],
        )
        self.assertEqual(
            len(_extract_document_candidates(html, "https://example.com/chat")),
            2,
        )

    def test_deepseek_private_file_cards_become_click_candidates(self):
        html = """
        <div data-virtual-list-item-key="1">
          <div class="ds-message">
            <div>mddd.md</div><div>MD 19.49KB</div>
            <div>普通正文.pdf 不是文件卡片</div>
          </div>
        </div>
        """
        candidates = _extract_deepseek_document_card_candidates(
            html,
            "https://chat.deepseek.com/a/chat/s/conversation-id",
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].filename, "mddd.md")
        self.assertTrue(candidates[0].reference.startswith("deepseek-card:"))

    def test_deepseek_site_icon_is_decorative(self):
        self.assertTrue(_is_decorative_image_candidate(
            "https://cdn.deepseek.com/site-icons/csair.com"
        ))
        self.assertTrue(_is_decorative_image_candidate(
            "https://t0.gstatic.com/faviconV2?url=https%3A%2F%2Fnumpy.org"
        ))
        self.assertFalse(_is_decorative_image_candidate(
            "https://cdn.deepseek.com/content/answer.webp"
        ))

    def test_deepseek_document_card_uses_react_signed_path(self):
        signed_path = "/file?file_id=xlsx-id&state=signed"
        name = MagicMock()
        name.evaluate = AsyncMock(return_value=signed_path)
        message = MagicMock()
        message.get_by_text.return_value.first = name
        page = MagicMock()
        page.locator.return_value.filter.return_value = message
        candidate = DocumentCandidate(
            "deepseek-card:result1.xlsx",
            "https://chat.deepseek.com/a/chat/s/example",
            "result1.xlsx",
        )

        with patch(
            "gui.service._scroll_to_deepseek_file_card",
            new=AsyncMock(return_value=True),
        ), patch(
            "gui.service._authenticated_page_get",
            new=AsyncMock(return_value="response"),
        ) as request:
            response = asyncio.run(_deepseek_document_card_get(
                page, candidate, 20000
            ))

        self.assertEqual(response, "response")
        name.evaluate.assert_awaited_once()
        self.assertEqual(name.evaluate.await_args.args[1], "result1.xlsx")
        request.assert_awaited_once_with(
            page,
            "https://files.deepseeksvc.com/api/file?"
            "file_id=xlsx-id&state=signed&ty=r",
            20000,
        )

    def test_deepseek_card_falls_back_after_expired_direct_url(self):
        direct = DocumentCandidate(
            "/file?file_id=old&state=expired",
            "https://files.deepseeksvc.com/api/file?file_id=old&state=expired&ty=r",
            "result1.xlsx",
        )
        card = DocumentCandidate(
            "deepseek-card:result1.xlsx",
            "https://chat.deepseek.com/share/example",
            "result1.xlsx",
        )
        expired = SimpleNamespace(ok=False, status=404, headers={})
        fresh = SimpleNamespace(
            ok=True,
            status=200,
            headers={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            body=AsyncMock(return_value=b"PK\x03\x04xlsx"),
        )
        warnings = []
        with patch(
            "gui.service._authenticated_page_get",
            new=AsyncMock(return_value=expired),
        ), patch(
            "gui.service._deepseek_document_card_get",
            new=AsyncMock(return_value=fresh),
        ):
            with tempfile.TemporaryDirectory() as temp_dir:
                mapping = asyncio.run(_download_document_candidates(
                    SimpleNamespace(),
                    [direct, card],
                    Path(temp_dir),
                    "./documents",
                    warning_collector=warnings,
                ))
                self.assertEqual(
                    (Path(temp_dir) / "result1.xlsx").read_bytes(),
                    b"PK\x03\x04xlsx",
                )
        self.assertEqual(warnings, [])
        self.assertEqual(mapping[direct.url], "./documents/result1.xlsx")
        self.assertEqual(mapping[card.reference], "./documents/result1.xlsx")

    def test_deepseek_duplicate_candidates_report_one_failed_file(self):
        direct = DocumentCandidate(
            "/file?file_id=old&state=expired",
            "https://files.deepseeksvc.com/api/file?file_id=old&state=expired&ty=r",
            "result1.xlsx",
        )
        card = DocumentCandidate(
            "deepseek-card:result1.xlsx",
            "https://chat.deepseek.com/share/example",
            "result1.xlsx",
        )
        expired = SimpleNamespace(ok=False, status=404, headers={})
        warnings = []
        failures = {}
        authentication_required = []
        with patch(
            "gui.service._authenticated_page_get",
            new=AsyncMock(return_value=expired),
        ), patch(
            "gui.service._deepseek_document_card_get",
            new=AsyncMock(return_value=expired),
        ):
            with tempfile.TemporaryDirectory() as temp_dir:
                mapping = asyncio.run(_download_document_candidates(
                    SimpleNamespace(),
                    [direct, card],
                    Path(temp_dir),
                    "./documents",
                    warning_collector=warnings,
                    conversation_url="https://chat.deepseek.com/share/example",
                    failure_collector=failures,
                    authentication_required=authentication_required,
                ))
        self.assertEqual(mapping, {})
        self.assertEqual(authentication_required, [True])
        self.assertEqual(warnings, [
            "1 个文档附件未能保存到本地（http_404×1）；对话文字抓取继续保留。"
        ])
        self.assertEqual(len(failures), 1)

    def test_document_403_requests_login_but_regular_404_does_not(self):
        forbidden = SimpleNamespace(ok=False, status=403, headers={})
        missing = SimpleNamespace(ok=False, status=404, headers={})
        candidate = DocumentCandidate(
            "file", "https://example.com/report.xlsx", "report.xlsx"
        )
        for response, expected in ((forbidden, [True]), (missing, [])):
            authentication_required = []
            with patch(
                "gui.service._authenticated_page_get",
                new=AsyncMock(return_value=response),
            ), tempfile.TemporaryDirectory() as temp_dir:
                asyncio.run(_download_document_candidates(
                    SimpleNamespace(),
                    [candidate],
                    Path(temp_dir),
                    "./documents",
                    authentication_required=authentication_required,
                ))
            self.assertEqual(authentication_required, expected)

    def test_deepseek_response_cache_does_not_collide_on_shared_path(self):
        first = _document_response_cache_keys(
            "https://files.deepseeksvc.com/api/file?file_id=first&state=one"
        )
        second = _document_response_cache_keys(
            "https://files.deepseeksvc.com/api/file?file_id=second&state=two"
        )
        self.assertEqual(first, (
            "https://files.deepseeksvc.com/api/file?file_id=first&state=one",
        ))
        self.assertTrue(set(first).isdisjoint(second))

    def test_deepseek_image_body_is_not_saved_as_document(self):
        response = SimpleNamespace(
            ok=True,
            headers={"content-type": "image/webp"},
            body=AsyncMock(return_value=b"RIFF\x00\x00\x00\x00WEBPpayload"),
        )
        page = SimpleNamespace()
        candidate = DocumentCandidate(
            "/file?file_id=fake&state=signed",
            "https://files.deepseeksvc.com/api/file?file_id=fake&state=signed&ty=r",
            "report.pdf",
        )
        warnings = []
        with patch(
            "gui.service._authenticated_page_get",
            new=AsyncMock(return_value=response),
        ):
            with tempfile.TemporaryDirectory() as temp_dir:
                mapping = asyncio.run(_download_document_candidates(
                    page,
                    [candidate],
                    Path(temp_dir),
                    "./documents",
                    warning_collector=warnings,
                ))
                self.assertEqual(mapping, {})
                self.assertFalse((Path(temp_dir) / "report.pdf").exists())
        self.assertTrue(any("not_a_document" in warning for warning in warnings))

    def test_doubao_response_metadata_produces_authorized_candidate(self):
        documents = []
        _collect_response_assets(
            {
                "content": {
                    "file": {
                        "name": "课堂材料.docx",
                        "uri": "tos-cn-i-test/folder/material.docx",
                    }
                }
            },
            "https://www.doubao.com/chat/conversation-id",
            documents,
            set(),
        )
        self.assertEqual(len(documents), 1)
        self.assertEqual(
            documents[0].url,
            "https://www.doubao.com/alice/message/get_file_url",
        )
        self.assertEqual(
            documents[0].reference,
            "tos-cn-i-test/folder/material.docx",
        )

    def test_doubao_share_embedded_state_produces_document_candidate(self):
        html = (
            '&amp;quot;file&amp;quot;:{'
            '&amp;quot;name&amp;quot;:&amp;quot;课堂材料.docx&amp;quot;,'
            '&amp;quot;uri&amp;quot;:'
            '&amp;quot;tos-cn-i-test/folder/material.docx&amp;quot;,'
            '&amp;quot;url&amp;quot;:'
            '&amp;quot;https://example.com/material.docx?signature=test&amp;quot;}'
        )
        candidates = _extract_document_candidates(
            html,
            "https://www.doubao.com/thread/example",
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].filename, "课堂材料.docx")
        self.assertEqual(
            candidates[0].reference,
            "tos-cn-i-test/folder/material.docx",
        )
        self.assertEqual(
            candidates[0].url,
            "https://example.com/material.docx?signature=test",
        )

    def test_doubao_share_decodes_unicode_escaped_document_uri(self):
        html = (
            r'\"name\":\"课堂材料.docx\",'
            r'\"uri\":\"tos-cn-i-test\u002Ffolder\u002Fmaterial.docx\"'
        )
        candidates = _extract_document_candidates(
            html,
            "https://www.doubao.com/thread/example",
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0].reference,
            "tos-cn-i-test/folder/material.docx",
        )

    def test_only_real_doubao_ai_document_cards_produce_titles(self):
        html = """
        <div class="message-item">
          <div class="product-card-real123">
            <div class="card-content-info-title-text-real123">在线报告</div>
            <div>创建时间：07-08 10:06</div>
          </div>
          <div class="product-card-other123">
            <div class="card-content-info-title-text-other123">其他产品</div>
          </div>
          <p>普通正文标题：创建时间与在线报告</p>
        </div>
        """
        self.assertEqual(
            _extract_doubao_ai_document_titles(
                html, "https://www.doubao.com/thread/example"
            ),
            ["在线报告"],
        )
        self.assertEqual(
            _extract_doubao_ai_document_titles(
                html, "https://example.com/thread/example"
            ),
            [],
        )

    def test_doubao_share_state_produces_ai_document_resource(self):
        html = r'''\"artifact_block\":{\"resource_id\":\"DocResource123\",\"title\":\"在线报告\",\"resource_type\":10},\"is_finish\":true'''
        self.assertEqual(
            _extract_doubao_ai_document_resources(
                html, "https://www.doubao.com/thread/example"
            ),
            {
                "在线报告": (
                    "https://www.doubao.com/docx/DocResource123"
                )
            },
        )

    def test_doubao_ai_document_pages_are_deduplicated_and_cleaned(self):
        self.assertEqual(
            _normalize_doubao_ai_document_text([
                "第一段\u200b\n\n\n第二段",
                "第一段\u200b\n\n\n第二段",
                "第三段\ufeff",
            ]),
            "第一段\n\n第二段\n\n第三段",
        )

    def test_doubao_document_candidate_downloads_original_file(self):
        class FakeResponse:
            ok = True
            status = 200
            headers = {
                "content-type": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                )
            }

            async def body(self):
                return b"PK\x03\x04real-docx"

        class FakeRequest:
            async def get(self, url, timeout):
                self.url = url
                self.timeout = timeout
                return FakeResponse()

        class FakePage:
            url = "https://www.doubao.com/thread/example"

            def __init__(self):
                self.request = FakeRequest()
                self.evaluation_argument = None

            async def evaluate(self, _script, argument):
                self.evaluation_argument = argument
                return {
                    "data": {
                        "file_urls": [{
                            "main_url": (
                                "https://p9-flow-sign.byteimg.com/"
                                "tos-cn-i-test/folder/material.docx"
                            )
                        }]
                    }
                }

        page = FakePage()
        candidate = DocumentCandidate(
            "tos-cn-i-test/folder/material.docx",
            "https://www.doubao.com/alice/message/get_file_url",
            "课堂材料.docx",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "result_files"
            mapping = asyncio.run(_download_document_candidates(
                page,
                [candidate],
                output_dir,
                "./result_files",
            ))
            saved = list(output_dir.iterdir())
            self.assertEqual([path.name for path in saved], ["课堂材料.docx"])
            self.assertEqual(saved[0].read_bytes(), b"PK\x03\x04real-docx")
            self.assertIn("课堂材料.docx", mapping)
        self.assertEqual(
            page.evaluation_argument["uri"],
            "tos-cn-i-test/folder/material.docx",
        )

    def test_text_attachment_mojibake_is_repaired_only_when_reversible(self):
        original = "# AI 对话记忆导出\n\n## 用户提问\n你好"
        mojibake = original.encode("utf-8").decode("latin-1").encode("utf-8")
        self.assertEqual(
            _repair_downloaded_text_mojibake(
                mojibake,
                "课堂材料.md",
                "text/markdown",
            ).decode("utf-8"),
            original,
        )
        normal = "正常中文和 English".encode("utf-8")
        self.assertEqual(
            _repair_downloaded_text_mojibake(normal, "课堂材料.md"),
            normal,
        )

    def test_chatgpt_rehydrate_switches_home_then_returns_original(self):
        class FakePage:
            def __init__(self):
                self.visited = []
                self.waited = []

            async def goto(self, url, **_kwargs):
                self.visited.append(url)

            async def wait_for_timeout(self, milliseconds):
                self.waited.append(milliseconds)

        page = FakePage()
        url = "https://chatgpt.com/c/conversation-id"
        with patch("gui.service._set_browser_window_state") as set_state:
            asyncio.run(_rehydrate_chatgpt_conversation(page, url))
        self.assertEqual(page.visited, ["https://chatgpt.com/", url])
        self.assertTrue(set_state.await_count >= 3)
        self.assertTrue(all(
            call.args[1] == "minimized" for call in set_state.await_args_list
        ))

    def test_chatgpt_download_credential_accepts_only_safe_public_url(self):
        self.assertEqual(
            _document_download_url_from_payload({
                "download_url": "https://chatgpt.com/backend-api/estuary/content?id=fake"
            }),
            "https://chatgpt.com/backend-api/estuary/content?id=fake",
        )
        self.assertEqual(
            _document_download_url_from_payload({
                "download_url": "http://127.0.0.1/private.docx"
            }),
            "",
        )

    def test_chatgpt_file_token_stays_in_same_origin_page_request(self):
        class ResponseInfo:
            def __init__(self):
                self.value = asyncio.sleep(0, result=SimpleNamespace(ok=True))

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

        class FakePage:
            url = "https://chatgpt.com/c/conversation-id"

            def __init__(self):
                self.request = SimpleNamespace(get=None)
                self.evaluation = None

            def expect_response(self, *_args, **_kwargs):
                return ResponseInfo()

            async def evaluate(self, script, argument):
                self.evaluation = (script, argument)

        page = FakePage()
        result = asyncio.run(_authenticated_page_get(
            page,
            "https://chatgpt.com/backend-api/files/download/file_fake",
            1000,
        ))
        script, argument = page.evaluation
        self.assertTrue(result.ok)
        self.assertEqual(argument, {
            "resource": (
                "https://chatgpt.com/backend-api/files/download/file_fake"
            ),
            "prepare": (
                "https://chatgpt.com/backend-api/files/file_fake/simple"
            ),
        })
        self.assertIn("/api/auth/session", script)
        self.assertNotIn("token", argument)

    def test_grok_asset_uses_page_fetch_across_origins(self):
        class ResponseInfo:
            value = asyncio.sleep(0, result=SimpleNamespace(ok=True))

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

        class FakePage:
            url = "https://grok.com/c/conversation-id"

            def __init__(self):
                self.request = SimpleNamespace(get=AsyncMock())
                self.argument = None

            def expect_response(self, *_args, **_kwargs):
                return ResponseInfo()

            async def evaluate(self, _script, argument):
                self.argument = argument

        page = FakePage()
        url = "https://assets.grok.com/users/user-id/asset-id/content"
        result = asyncio.run(_authenticated_page_get(page, url, 1000))
        self.assertTrue(result.ok)
        self.assertEqual(page.argument, {"resource": url, "prepare": None})
        page.request.get.assert_not_awaited()

    def test_chatgpt_share_placeholder_uses_matching_embedded_image(self):
        share_id = "6a5ed6e7-bd38-83ee-936d-571f7594a63e"
        source_html = (
            "sediment://file_older?shared_conversation_id=" + share_id
            + " sediment://file_newer?shared_conversation_id=" + share_id
            + " sediment://file_wrong?shared_conversation_id="
            + "00000000-0000-0000-0000-000000000000"
        )
        sources = _extract_chatgpt_shared_image_sources(
            source_html,
            f"https://chatgpt.com/share/{share_id}",
        )
        self.assertEqual(sources, [
            "https://chatgpt.com/backend-api/files/download/file_newer"
            f"?shared_conversation_id={share_id}",
            "https://chatgpt.com/backend-api/files/download/file_older"
            f"?shared_conversation_id={share_id}"
        ])

        html = (
            '<div data-testid="conversation-turn-1">'
            '<span>已上传图片</span>'
            '<div data-message-author-role="user">他说的对吗</div>'
            '</div>'
        )
        injected = _inject_chatgpt_shared_images(html, sources)
        image = BeautifulSoup(injected, "html.parser").find("img")
        self.assertEqual(image["src"], sources[0])
        self.assertEqual(image["alt"], "已上传的图片")

    def test_chatgpt_runtime_assets_keep_message_and_multi_image_order(self):
        share_id = "6a5ed6e7-bd38-83ee-936d-571f7594a63e"

        class FakePage:
            def __init__(self):
                self.script = ""

            async def evaluate(self, script):
                self.script = script
                return [
                    {
                        "images": [
                            "sediment://file_first?shared_conversation_id="
                            + share_id,
                            "sediment://file_second?shared_conversation_id="
                            + share_id,
                        ],
                        "attachments": [],
                    },
                    {
                        "images": [
                            "sediment://file_video_frame_one",
                            "sediment://file_video_frame_two",
                        ],
                        "attachments": [
                            {
                                "id": "file_document",
                                "name": "课堂材料.docx",
                            },
                            {
                                "id": "file_video",
                                "name": "测试视频.mp4",
                            },
                        ],
                    },
                ]

        page = FakePage()
        image_groups, document_groups = asyncio.run(
            _chatgpt_message_asset_groups(
                page, f"https://chatgpt.com/share/{share_id}"
            )
        )
        self.assertIn("value.mapping", page.script)
        html = (
            '<div data-message-author-role="user">第一问</div>'
            '<div data-message-author-role="user">第二问</div>'
        )
        result = _inject_chatgpt_message_images(html, image_groups)
        messages = BeautifulSoup(result, "html.parser").find_all(
            attrs={"data-message-author-role": "user"}
        )
        self.assertEqual(
            [image["src"] for image in messages[0].find_all("img")],
            image_groups[0],
        )
        self.assertEqual(
            len(messages[1].find_all("img")), 2
        )
        self.assertEqual(
            [candidate.filename for candidate in document_groups[1]],
            ["课堂材料.docx", "测试视频.mp4"],
        )

    def test_chatgpt_shared_video_recovers_private_attachment_without_runtime_groups(self):
        share_id = "6ac64d05-b08c-83e9-82f6-ecb01f142770"
        video = DocumentCandidate(
            "file_private_video",
            "https://chatgpt.com/backend-api/files/download/file_private_video",
            "测试视频.mp4",
        )
        page = SimpleNamespace(
            evaluate=AsyncMock(return_value=[[{
                "id": "file_private_video",
                "name": "测试视频.mp4",
            }]]),
        )
        images, documents = asyncio.run(
            _recover_chatgpt_shared_video_assets(
                page,
                f"https://chatgpt.com/share/{share_id}",
                '<div data-message-author-role="user">'
                '测试视频.mp4 文件 这个视频讲了什么</div>',
                [],
                [],
            )
        )
        self.assertEqual(images, [[]])
        self.assertEqual(documents, [[video]])
        self.assertEqual(page.evaluate.await_args.args[1], "这个视频讲了什么")

    def test_chatgpt_placeholder_gets_real_metadata_filename(self):
        html = (
            '<div data-message-author-role="user">上传文件</div>'
        )
        result = _inject_chatgpt_attachment_names(
            html,
            [DocumentCandidate(
                "file_fake",
                "https://chatgpt.com/backend-api/files/download/file_fake",
                "课堂材料.docx",
            )],
        )
        self.assertIn("课堂材料.docx", result)
        self.assertIn("api-attachment-name", result)

    def test_chatgpt_document_name_stays_with_its_user_message(self):
        document = DocumentCandidate(
            "file_fake",
            "https://chatgpt.com/backend-api/files/download/file_fake",
            "课堂材料.docx",
        )
        html = (
            '<div data-message-author-role="user">第一问</div>'
            '<div data-message-author-role="user">上传文件\n第二问</div>'
        )
        result = _inject_chatgpt_attachment_names(
            html, [document], [[], [document]]
        )
        messages = BeautifulSoup(result, "html.parser").find_all(
            attrs={"data-message-author-role": "user"}
        )
        self.assertNotIn("课堂材料.docx", messages[0].get_text())
        self.assertIn("课堂材料.docx", messages[1].get_text())

    def test_chatgpt_visible_attachment_name_still_gets_download_marker(self):
        document = DocumentCandidate(
            "file_fake",
            "https://chatgpt.com/backend-api/files/download/file_fake",
            "课堂材料.docx",
        )
        html = (
            '<div data-message-author-role="user">'
            '<div class="truncate font-semibold">课堂材料.docx</div>'
            '</div>'
        )
        result = _inject_chatgpt_attachment_names(
            html, [document], [[document]]
        )
        self.assertIn("api-attachment-name", result)
        _, messages = _parse_page_messages(
            "https://chatgpt.com/c/conversation-id",
            BeautifulSoup(result, "html.parser"),
            {"课堂材料.docx": "./documents/material.docx"},
        )
        self.assertIn(
            "[📄 课堂材料.docx](./documents/material.docx)",
            messages[0]["content"],
        )

    def test_chatgpt_show_more_control_is_not_exported(self):
        html = (
            '<div data-message-author-role="user">完整问题'
            '<span aria-hidden="true">…</span>'
            '<button data-markdown-copy="exclude">'
            '<span>显示更多</span></button></div>'
        )
        _, messages = _parse_page_messages(
            "https://chatgpt.com/c/conversation-id",
            BeautifulSoup(html, "html.parser"),
            {},
        )
        self.assertEqual(messages[0]["content"], "完整问题")

    def test_chatgpt_plain_attachment_name_uses_downloaded_file(self):
        html = (
            '<div data-message-author-role="user">'
            'problem2_moisture.csv<br>电子表格'
            '</div>'
        )
        _, messages = _parse_page_messages(
            "https://chatgpt.com/c/conversation-id",
            BeautifulSoup(html, "html.parser"),
            {"problem2_moisture.csv": "./documents/problem2_moisture.csv"},
        )
        self.assertEqual(
            messages[0]["content"],
            "[📄 problem2_moisture.csv](./documents/problem2_moisture.csv)"
            "\n\n电子表格",
        )

    def test_chatgpt_plain_video_name_uses_downloaded_file(self):
        html = (
            '<div data-message-author-role="user">'
            '测试视频.mp4<br>文件<br>这个视频讲了什么'
            '</div>'
        )
        _, messages = _parse_page_messages(
            "https://chatgpt.com/c/conversation-id",
            BeautifulSoup(html, "html.parser"),
            {"测试视频.mp4": "./documents/video.mp4"},
        )
        self.assertEqual(
            messages[0]["content"],
            "[📄 测试视频.mp4](./documents/video.mp4)\n\n文件\n这个视频讲了什么",
        )

    def test_document_asset_directory_uses_output_stem(self):
        self.assertEqual(
            build_document_asset_directory(Path("D:/output"), "课程 总结.md"),
            Path("D:/output/课程 总结_files"),
        )
if __name__ == "__main__":
    unittest.main()
