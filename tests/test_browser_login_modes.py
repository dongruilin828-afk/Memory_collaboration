"""Explicit re-login and reuse defaults across single and concurrent capture."""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from gui import service
from gui.browser_login import platform_login_key, reset_platform_login
from gui.batch_login import BatchLoginCoordinator
from tests.test_batch_login import Context
from tests.test_gemini_login import CONVERSATION, CHALLENGE

PRIVATE = 'https://gemini.google.com/app/0123456789abcdef'
PUBLIC = 'https://gemini.google.com/share/0123456789abcdef'


class LoginModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_unreadable_public_page_without_auth_evidence_is_not_a_login_request(self):
        empty = SimpleNamespace(count=AsyncMock(return_value=0))
        page = SimpleNamespace(url=PUBLIC, locator=Mock(return_value=empty), get_by_role=Mock(return_value=empty))
        self.assertFalse(await service._page_requires_login(page, PUBLIC))
        self.assertTrue(await service._page_requires_login(page, PRIVATE))
    def test_platform_aliases_share_account_but_other_ai_does_not(self):
        for left, right in [('https://chatgpt.com/c/12345678', 'https://chat.openai.com/c/12345678'),
                            ('https://gemini.google.com/app/12345678', 'https://share.gemini.google/12345678'),
                            ('https://kimi.com/chat/12345678', 'https://kimi.moonshot.cn/chat/12345678')]:
            self.assertEqual(platform_login_key(left), platform_login_key(right))
        self.assertNotEqual(platform_login_key(PRIVATE), platform_login_key('https://chat.deepseek.com/a/chat/s/12345678'))

    async def test_reset_is_scoped_and_no_cookies_or_tokens_are_written(self):
        page = SimpleNamespace(url='https://chatgpt.com/', goto=AsyncMock())
        state = dict(cookies=[dict(domain='.chatgpt.com'), dict(domain='auth.openai.com'), dict(domain='chat.deepseek.com')],
                     origins=[dict(origin='https://chatgpt.com'), dict(origin='https://auth.openai.com'),
                              dict(origin='https://chat.deepseek.com')])
        session = SimpleNamespace(send=AsyncMock(), detach=AsyncMock())
        context = SimpleNamespace(pages=[page], storage_state=AsyncMock(return_value=state),
                                  clear_cookies=AsyncMock(), new_cdp_session=AsyncMock(return_value=session))
        await reset_platform_login(context, page, 'https://chatgpt.com/share/example')
        self.assertEqual({c.kwargs['domain'] for c in context.clear_cookies.await_args_list}, {'.chatgpt.com', 'auth.openai.com'})
        self.assertEqual({c.args[1]['origin'] for c in session.send.await_args_list}, {'https://chatgpt.com', 'https://auth.openai.com'})
        session.detach.assert_awaited_once()

    async def test_batch_alias_waiter_reuses_completed_login(self):
        context, logged_in = Context(2), False
        entered, release = asyncio.Event(), asyncio.Event()
        async def login(*_args):
            nonlocal logged_in
            entered.set()
            await release.wait()
            logged_in = True
            return True
        callback = AsyncMock(side_effect=login)
        coordinator = BatchLoginCoordinator(context.pages, callback)
        async def ready():
            return logged_in
        with patch('gui.batch_login._set_browser_window_state', AsyncMock()):
            first = asyncio.create_task(coordinator.authorize(context.pages[0], 'https://chatgpt.com/c/one', ready, force=True))
            await entered.wait()
            second = asyncio.create_task(coordinator.authorize(context.pages[1], 'https://chat.openai.com/c/two', ready, force=True))
            await asyncio.sleep(0)
            release.set()
            self.assertEqual(await asyncio.gather(first, second), [True, True])
        callback.assert_awaited_once()

    async def test_reuse_does_not_prompt_when_readable_but_reprompts_if_account_cannot_access(self):
        context = Context(1)
        callback = AsyncMock(return_value=True)
        coordinator = BatchLoginCoordinator(context.pages, callback)
        with patch('gui.batch_login._set_browser_window_state', AsyncMock()):
            self.assertTrue(await coordinator.authorize(context.pages[0], 'https://chatgpt.com/c/one', AsyncMock(return_value=True)))
            callback.assert_not_awaited()
            for suffix in ('two', 'three'):
                self.assertTrue(await coordinator.authorize(context.pages[0], 'https://chatgpt.com/c/'+suffix,
                    AsyncMock(side_effect=[False, True])))
        self.assertEqual(callback.await_count, 2)

    async def test_gemini_stale_tab_refreshes_once_after_other_worker_logs_in(self):
        context, logged_in = Context(2), False
        coordinator = None
        first, second = context.pages
        first.url, second.url = PRIVATE, PRIVATE.replace('0123456789abcdef', 'fedcba9876543210')
        first.readable = second.readable = False
        async def reload_second(url, **_options):
            second.url, second.readable = url, logged_in
        second.goto = AsyncMock(side_effect=reload_second)
        async def login(page, _url):
            nonlocal logged_in
            logged_in, page.readable = True, True
            return True
        callback = AsyncMock(side_effect=login)
        coordinator = BatchLoginCoordinator(context.pages, callback)
        async def ready(page):
            return page.readable
        with patch('gui.batch_login._set_browser_window_state', AsyncMock()):
            self.assertTrue(await coordinator.authorize(first, first.url, lambda: ready(first)))
            self.assertTrue(await coordinator.authorize(second, second.url, lambda: ready(second)))
        callback.assert_awaited_once()
        second.goto.assert_awaited_once()


@unittest.skipUnless(os.getenv('AI_MEMORY_BROWSER_SMOKE') == '1', 'opt-in real Chromium fixtures')
class LoginModeBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_stale_tabs_share_one_login_then_allow_reauth_after_expiry(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False)
            try:
                context = await browser.new_context(viewport={'width': 1200, 'height': 800})
                pages = [await context.new_page() for _ in range(3)]
                targets = [PRIVATE.replace('0123456789abcdef', f'{index:016x}') for index in range(1, 4)]
                async def route(request_route):
                    logged = 'batch_login=valid' in request_route.request.headers.get('cookie', '')
                    await request_route.fulfill(body=CONVERSATION if logged else CHALLENGE, content_type='text/html; charset=utf-8')
                await context.route('**/*', route)
                await asyncio.gather(*(page.goto(url) for page, url in zip(pages, targets)))
                prompts = []
                async def login(page, target):
                    prompts.append(target)
                    await context.add_cookies([dict(name='batch_login', value='valid', domain='gemini.google.com', path='/', secure=True)])
                    await page.set_content(CONVERSATION)
                    return True
                coordinator = BatchLoginCoordinator(pages, login)
                with patch('gui.batch_login._set_browser_window_state', AsyncMock()):
                    result = await asyncio.gather(*(coordinator.authorize(page, url,
                        lambda page=page, url=url: service._page_has_conversation_content(page, url)) for page, url in zip(pages, targets)))
                    self.assertEqual(result, [True]*3)
                    self.assertEqual(len(prompts), 1, '已有标签页应刷新复用新登录态')
                    await context.clear_cookies(domain='gemini.google.com')
                    await pages[0].goto(targets[0])
                    self.assertTrue(await coordinator.authorize(pages[0], targets[0],
                        lambda: service._page_has_conversation_content(pages[0], targets[0])))
                    self.assertEqual(len(prompts), 2, '登录过期后仍可重新授权')
                output = os.getenv('AI_MEMORY_LOGIN_RESULTS')
                if output:
                    (Path(output)/'并发共享登录记录.json').write_text(json.dumps(dict(
                        simultaneous_targets=3, initial_login_prompts=1, prompts_after_expiry=len(prompts),
                        accessible_targets=result), ensure_ascii=False, indent=2), encoding='utf-8')
            finally:
                await browser.close()

    async def test_single_public_anonymous_never_prompts(self):
        await self.capture('复用公开页匿名可读', public=True)

    async def test_single_public_reuses_saved_cookie_without_prompt(self):
        await self.capture('复用公开页已有登录', public=True, saved=True)

    async def test_single_private_reuses_saved_cookie_without_prompt(self):
        await self.capture('复用私有页已有登录', saved=True)

    async def test_explicit_public_login_starts_signed_out_even_if_anonymous_is_readable(self):
        await self.capture('授权公开页必须重新登录', public=True, saved=True, explicit=True)

    async def test_explicit_private_login_starts_signed_out(self):
        await self.capture('授权私有页必须重新登录', saved=True, explicit=True)

    async def test_expired_reuse_only_prompts_after_headed_probe_and_does_not_clear_state(self):
        await self.capture('复用过期后才请求登录')

    async def capture(self, name, *, public=False, saved=False, explicit=False):
        from playwright.async_api import async_playwright
        target = PUBLIC if public else PRIVATE
        with tempfile.TemporaryDirectory() as temporary:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=False)
                context = await browser.new_context(viewport={'width': 1200, 'height': 800})
                page = await context.new_page()
                visits, prompts, launch_options = [], [], []
                async def route(request_route):
                    if request_route.request.is_navigation_request():
                        visits.append('fixture=old' in request_route.request.headers.get('cookie', ''))
                    authenticated = 'fixture=' in request_route.request.headers.get('cookie', '')
                    body = CONVERSATION if public or authenticated else CHALLENGE
                    await request_route.fulfill(body=body, content_type='text/html; charset=utf-8')
                await context.route('**/*', route)
                if saved:
                    await context.add_cookies([dict(name='fixture', value='old', domain='gemini.google.com', path='/', secure=True)])
                    await page.goto(target)
                    await page.evaluate("localStorage.setItem('old-login','old')")
                    visits.clear()
                await context.add_cookies([dict(name='unrelated', value='keep', domain='chat.deepseek.com', path='/', secure=True)])
                event = asyncio.Event()
                permission = Mock(return_value=True)
                async def login():
                    cookie_names = [row['name'] for row in await context.cookies(target)]
                    prompts.append(dict(cookie_names=cookie_names, old_storage=await page.evaluate("localStorage.getItem('old-login')")))
                    if explicit:
                        self.assertNotIn('fixture', cookie_names)
                        self.assertIsNone(prompts[-1]['old_storage'])
                    await context.add_cookies([dict(name='fixture', value='new', domain='gemini.google.com', path='/', secure=True)])
                    await page.set_content(CONVERSATION)
                    event.set()
                def notify():
                    self.assertFalse(event.is_set())
                    asyncio.create_task(login())
                async def launch(*_args, **options):
                    launch_options.append(options)
                    return context, 'fixture'
                with patch.object(service, 'launch_browser_context', launch), \
                     patch.object(service, '_close_browser_context_safely', AsyncMock()), \
                     patch('gui.batch_login._set_browser_window_state', AsyncMock()), \
                     patch.object(service, '_set_browser_window_state', AsyncMock()):
                    result = await service.fetch_chat_pipeline(target, need_login=explicit,
                        login_ready_event=event, login_required_callback=notify, login_confirmation_callback=permission,
                        browser_profile_root=Path(temporary)/'profile', image_output_dir=Path(temporary)/'images',
                        document_output_dir=Path(temporary)/'documents')
                self.assertIsNone(result.error)
                self.assertEqual(len(result.messages), 2)
                expected_prompts = 1 if explicit or (not public and not saved) else 0
                self.assertEqual(len(prompts), expected_prompts)
                self.assertEqual(permission.call_count, 1 if not explicit and expected_prompts else 0)
                self.assertEqual([option['headless'] for option in launch_options],
                                 [False] if explicit else ([True, False] if expected_prompts else [True]))
                self.assertTrue(all(option['profile_root'] == Path(temporary)/'profile' for option in launch_options))
                if explicit:
                    self.assertFalse(any(visits), '首次导航前应清理旧 Cookie')
                elif saved:
                    self.assertTrue(all(visits), '复用模式应携带旧 Cookie')
                self.assertEqual([row['value'] for row in await context.cookies('https://chat.deepseek.com')], ['keep'])
                output = os.getenv('AI_MEMORY_LOGIN_RESULTS')
                if output:
                    destination = Path(output)
                    service.generate_raw_markdown(result.messages, destination/f'{name}_抓取.md')
                    (destination/f'{name}_记录.json').write_text(json.dumps(dict(result=asdict(result),
                        explicit_login=explicit, prompts=len(prompts), login_permission_prompts=permission.call_count,
                        navigation_used_old_session=visits, launches=[row['headless'] for row in launch_options]),
                        ensure_ascii=False, indent=2), encoding='utf-8')
                await browser.close()


if __name__ == '__main__':
    unittest.main()
