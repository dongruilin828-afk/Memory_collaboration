"""Human login is serialized, cancellable, and owns only its OAuth windows."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from gui.batch_login import BatchLoginCoordinator


class Context:
    def __init__(self, count):
        self.pages = []
        self.handlers = {}
        for _ in range(count):
            Page(self)

    def on(self, event, callback):
        self.handlers.setdefault(event, set()).add(callback)

    def remove_listener(self, event, callback):
        self.handlers.setdefault(event, set()).discard(callback)

    def popup(self):
        child = Page(self)
        for callback in tuple(self.handlers.get('page', ())):
            callback(child)
        return child

    async def new_cdp_session(self, page):
        async def send(method, _params=None):
            if method != 'Page.enable':
                page.init_allowed = method.startswith('Page.addScript')
            return {'identifier': 'fixture'}
        return SimpleNamespace(send=send, detach=AsyncMock())


class Page:
    def __init__(self, context):
        self.context = context
        context.pages.append(self)
        self.url = 'about:blank'
        self.allowed = False
        self.init_allowed = False
        self.closed = False
        self.viewport_size = {'width': 1920, 'height': 10800}
        self.viewports = []
        self.handlers = {}
        self.bring_to_front = AsyncMock()
        self.wait_for_timeout = AsyncMock()

    def locator(self, _selector):
        return SimpleNamespace(count=AsyncMock(return_value=0))

    def get_by_role(self, *_args, **_options):
        return SimpleNamespace(count=AsyncMock(return_value=0))

    async def set_viewport_size(self, viewport):
        self.viewport_size = dict(viewport)
        self.viewports.append(dict(viewport))

    async def goto(self, url, **_options):
        self.url = url
        self.allowed = self.init_allowed
        for callback in tuple(self.handlers.get('domcontentloaded', ())):
            callback()
        await asyncio.sleep(0)

    async def evaluate(self, script):
        self.allowed = '= true' in script

    def on(self, event, callback):
        self.handlers.setdefault(event, set()).add(callback)

    def remove_listener(self, event, callback):
        self.handlers.setdefault(event, set()).discard(callback)

    def is_closed(self):
        return self.closed

    async def close(self):
        self.closed = True
        self.context.pages.remove(self)


class BatchLoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch('gui.batch_login._set_browser_window_state', new_callable=AsyncMock))

    async def test_human_viewport_restores_after_accept_skip_error_or_cancel(self):
        for outcome in ('accept', 'skip', 'error', 'cancel'):
            with self.subTest(outcome=outcome):
                context = Context(2)
                owner, other = context.pages
                original = dict(owner.viewport_size)
                entered = asyncio.Event()

                async def login(page, _url):
                    self.assertEqual(page.viewport_size, {'width': 1200, 'height': 800})
                    self.assertEqual(other.viewport_size, original)
                    entered.set()
                    if outcome == 'cancel':
                        await asyncio.Event().wait()
                    if outcome == 'error':
                        raise RuntimeError('login fixture failed')
                    return outcome == 'accept'

                coordinator = BatchLoginCoordinator(context.pages, login)
                task = asyncio.create_task(coordinator.authorize(
                    owner, 'https://chatgpt.com/c/exact', AsyncMock(side_effect=[False, True])))
                if outcome == 'cancel':
                    # Surface callback assertion failures without hanging the test.
                    waiting = asyncio.create_task(entered.wait())
                    await asyncio.wait({task, waiting}, return_when=asyncio.FIRST_COMPLETED)
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
                    if not task.done():
                        task.cancel()
                if outcome in ('error', 'cancel'):
                    with self.assertRaises(RuntimeError if outcome == 'error' else asyncio.CancelledError):
                        await task
                else:
                    self.assertEqual(await task, outcome == 'accept')
                self.assertEqual(owner.viewport_size, original)
                self.assertEqual(owner.viewports[-1], original)
                self.assertEqual(other.viewports, [])
                self.assertFalse(coordinator._lock.locked())

    async def test_native_window_viewport_does_not_enable_emulation_for_login(self):
        context = Context(1)
        owner = context.pages[0]
        owner.viewport_size = None
        coordinator = BatchLoginCoordinator([owner], AsyncMock(return_value=True))
        self.assertTrue(await coordinator.authorize(
            owner, 'https://chatgpt.com/c/exact', AsyncMock(side_effect=[False, True])))
        self.assertIsNone(owner.viewport_size)
        self.assertEqual(owner.viewports, [])

    async def test_same_origin_waiters_recheck_and_do_not_steal_worker_page(self):
        context = Context(3)
        pages = list(context.pages)
        logged_in = False
        entered, release = asyncio.Event(), asyncio.Event()

        async def login(page, _url):
            nonlocal logged_in
            self.assertTrue(page.allowed)
            child = context.popup()
            entered.set()
            await release.wait()
            logged_in = True
            return True

        callback = AsyncMock(side_effect=login)
        coordinator = BatchLoginCoordinator(pages, callback)
        first = asyncio.create_task(coordinator.authorize(pages[0], 'https://chatgpt.com/c/one', lambda: ready()))
        async def ready():
            return logged_in
        await entered.wait()
        second = asyncio.create_task(coordinator.authorize(pages[1], 'https://chatgpt.com/c/two', ready))
        third = asyncio.create_task(coordinator.authorize(pages[2], 'https://chatgpt.com/c/three', ready))
        await asyncio.sleep(0)
        self.assertEqual(pages[1].url, 'about:blank')
        release.set()
        self.assertEqual(await asyncio.gather(first, second, third), [True, True, True])
        callback.assert_awaited_once()
        self.assertEqual(context.pages, pages)
        self.assertEqual([p.url.rsplit('/', 1)[-1] for p in pages], ['one', 'two', 'three'])
        self.assertFalse(any(p.allowed or p.closed for p in pages))
        self.assertFalse(context.handlers['page'])

    async def test_force_prompts_despite_readable_body_then_reuses_login_epoch(self):
        context = Context(2)
        entered, release = asyncio.Event(), asyncio.Event()
        async def login(*_args):
            entered.set()
            await release.wait()
            return True
        callback = AsyncMock(side_effect=login)
        coordinator = BatchLoginCoordinator(context.pages, callback)
        ready = AsyncMock(return_value=True)
        first = asyncio.create_task(coordinator.authorize(context.pages[0], 'https://gemini.google.com/app/one', ready, force=True))
        await entered.wait()
        second = asyncio.create_task(coordinator.authorize(context.pages[1], 'https://gemini.google.com/app/two', ready, force=True))
        await asyncio.sleep(0)
        release.set()
        self.assertEqual(await asyncio.gather(first, second), [True, True])
        callback.assert_awaited_once()

    async def test_skip_or_cancel_closes_only_new_windows_and_releases_lock(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                context = Context(2)
                pages = list(context.pages)
                unrelated = Page(context)
                entered = asyncio.Event()
                async def login(*_args):
                    context.popup()
                    entered.set()
                    if cancel:
                        await asyncio.Event().wait()
                    return False
                coordinator = BatchLoginCoordinator(pages, login)
                task = asyncio.create_task(coordinator.authorize(pages[0], 'https://chatgpt.com/c/one', AsyncMock(return_value=False)))
                await entered.wait()
                if cancel:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                else:
                    self.assertFalse(await task)
                self.assertEqual(context.pages, pages + [unrelated])
                self.assertFalse(pages[0].allowed)
                self.assertFalse(coordinator._lock.locked())
                self.assertFalse(context.handlers['page'])

    async def test_cancel_waiter_does_not_cancel_current_login(self):
        context = Context(2)
        entered, release = asyncio.Event(), asyncio.Event()
        async def login(*_args):
            entered.set()
            await release.wait()
            return False
        coordinator = BatchLoginCoordinator(context.pages, login)
        first = asyncio.create_task(coordinator.authorize(context.pages[0], 'https://chatgpt.com/c/one', AsyncMock(return_value=False)))
        await entered.wait()
        second = asyncio.create_task(coordinator.authorize(context.pages[1], 'https://chatgpt.com/c/two', AsyncMock(return_value=False)))
        await asyncio.sleep(0)
        second.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await second
        self.assertFalse(first.done())
        release.set()
        self.assertFalse(await first)

    async def test_navigation_keeps_popup_enabled_only_during_login(self):
        context = Context(1)
        owner = context.pages[0]
        async def login(page, _url):
            await page.goto('https://chatgpt.com/auth/login')
            self.assertTrue(page.allowed)
            return True
        coordinator = BatchLoginCoordinator([owner], login)
        self.assertTrue(await coordinator.authorize(owner, 'https://chatgpt.com/c/one', AsyncMock(side_effect=[False, True])))
        self.assertFalse(owner.allowed)
        self.assertFalse(owner.init_allowed)


@unittest.skipUnless(os.getenv('AI_MEMORY_BROWSER_SMOKE') == '1', 'opt-in real Chromium check')
class BatchOAuthBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_coop_oauth_keeps_native_opener_and_restores_original_target(self):
        from playwright.async_api import async_playwright
        from gui.batch_capture import _SAME_TAB_SCRIPT
        from gui.service import launch_browser_context
        from urllib.parse import urlparse

        async def route(request_route):
            path = urlparse(request_route.request.url).path
            body = '''<button id="login" onclick="window.open('/oauth','_blank')">login</button>
              <script>window.addEventListener('message',e=>window.authorized=e.data==='done')</script>'''
            if path == '/oauth':
                body = '''<button id="complete" onclick="document.cookie='fixture=logged-in;path=/;Secure';
                  window.opener.postMessage('done','*');window.close()">complete</button>'''
            elif path == '/login-auto':
                body = '<script>window.open("/oauth", "_blank")</script>'
            body = '<style>body{margin:0;min-height:100vh;display:grid;place-items:center}</style>' + body
            await request_route.fulfill(content_type='text/html', body=body,
                                        headers={'cross-origin-opener-policy': 'same-origin'})

        with tempfile.TemporaryDirectory() as temporary, patch('gui.batch_login._set_browser_window_state', new_callable=AsyncMock):
            async with async_playwright() as playwright:
                context, _ = await launch_browser_context(playwright, headless=False,
                    viewport={'width': 1200, 'height': 800}, no_viewport=False,
                    start_minimized=True, profile_root=Path(temporary)/'profile')
                try:
                    await context.route('**/*', route)
                    owner = context.pages[0]
                    other = await context.new_page()
                    capture_viewport = {'width': 1920, 'height': 10800}
                    await owner.set_viewport_size(capture_viewport)
                    await other.set_viewport_size(capture_viewport)
                    await other.goto('https://other.test/work')
                    await owner.add_init_script(f'({_SAME_TAB_SCRIPT})()')
                    prompts = []
                    async def callback(page, _url):
                        prompts.append(page)
                        self.assertEqual(page.viewport_size, {'width': 1200, 'height': 800})
                        self.assertEqual(other.viewport_size, capture_viewport)
                        button = await page.locator('#login').bounding_box()
                        self.assertGreaterEqual(button['y'], 0)
                        self.assertLess(button['y'] + button['height'], 800)
                        async with page.expect_popup(timeout=5000) as opening:
                            await page.goto('https://owner.test/login-auto')
                        child = await opening.value
                        await child.wait_for_load_state('domcontentloaded')
                        self.assertEqual(child.viewport_size, {'width': 1200, 'height': 800})
                        button = await child.locator('#complete').bounding_box()
                        self.assertLess(button['y'] + button['height'], 800)
                        await child.locator('#complete').click()
                        await page.wait_for_function("document.cookie.includes('fixture=logged-in')")
                        return True
                    coordinator = BatchLoginCoordinator([owner, other], callback)
                    async def ready():
                        return 'fixture=logged-in' in await owner.evaluate('document.cookie')
                    url = 'https://owner.test/c/exact-target'
                    self.assertTrue(await coordinator.authorize(owner, url, ready))
                    self.assertEqual(owner.url, url)
                    self.assertEqual(owner.viewport_size, capture_viewport)
                    self.assertFalse(await owner.evaluate('!!window.__aimemoryAllowLoginPopup'))
                    self.assertEqual(other.url, 'https://other.test/work')
                    self.assertEqual(context.pages, [owner, other])
                    self.assertEqual(len(prompts), 1)
                finally:
                    await context.close()


if __name__ == '__main__':
    unittest.main()
