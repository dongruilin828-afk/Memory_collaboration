"""Gemini human verification must retain the verified target document."""
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
from gui.batch_login import BatchLoginCoordinator

URL = 'https://gemini.google.com/app/0123456789abcdef'
CONVERSATION = '''<user-query><div class="query-text">请记录验证标识。</div></user-query>
<model-response><message-content><p>已记录验证标识。</p></message-content></model-response>'''
CHALLENGE = '<form id="captcha-form">请完成人机验证</form>'


class GeminiLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_gemini_navigation_waits_until_current_verification_finishes(self):
        from scripts.browser_activity import active_rendering
        lock, entered, release = asyncio.Lock(), asyncio.Event(), asyncio.Event()
        owner = SimpleNamespace(_aimemory_render_lock=lock, bring_to_front=AsyncMock())
        page = SimpleNamespace(url=URL, _aimemory_render_lock=lock,
            bring_to_front=AsyncMock(), goto=AsyncMock())
        async def verifying():
            async with active_rendering(owner):
                entered.set()
                await release.wait()
        task = asyncio.create_task(verifying())
        await entered.wait()
        navigating = asyncio.create_task(service.goto_with_retry_gui(page, URL))
        await asyncio.sleep(0)
        page.goto.assert_not_awaited()
        release.set()
        await asyncio.wait_for(asyncio.gather(task, navigating), 2)
        page.goto.assert_awaited_once()

    async def test_shared_authorization_does_not_reload_an_already_readable_target(self):
        from tests.test_batch_login import Context
        context = Context(1)
        page = context.pages[0]
        page.url, page.goto = URL, AsyncMock()
        coordinator = BatchLoginCoordinator([page], AsyncMock())
        coordinator._epochs['gemini'] = 1
        self.assertTrue(await coordinator.authorize(page, URL, AsyncMock(return_value=True)))
        page.goto.assert_not_awaited()
        coordinator.callback.assert_not_awaited()

    async def test_readable_public_content_does_not_prompt_for_optional_sign_in_control(self):
        page, confirm = self.page(URL.replace('/app/','/share/')), AsyncMock()
        with patch.object(service, '_gemini_shows_login', AsyncMock(return_value=True)) as login:
            self.assertTrue(await service._ensure_gemini_conversation_access(page,page.url,confirm,
                ready=AsyncMock(return_value=True)))
        confirm.assert_not_awaited()
        login.assert_not_awaited()

    async def test_verification_prompt_is_classified_and_logged_without_account_or_url(self):
        from tests.test_batch_login import Context
        page = Context(1).pages[0]
        page.url = URL
        captured, logs = [], []
        pending = True
        async def callback(owner, _url):
            nonlocal pending
            captured.append(owner._aimemory_login_reason)
            pending = False
            return True
        async def verification(_page):
            return pending
        coordinator = BatchLoginCoordinator([page], callback)
        with patch.object(service, '_page_has_human_verification', verification), \
             patch('gui.batch_login._set_browser_window_state', AsyncMock()):
            self.assertTrue(await coordinator.authorize(page, URL, AsyncMock(side_effect=[False, False, True]), logger=logs.append))
        self.assertEqual(captured, ['verification'])
        self.assertTrue(any('人工确认开始：真人验证' in line for line in logs))
        self.assertTrue(any('授权恢复结束' in line and '1 次' in line for line in logs))
        self.assertFalse(any(URL in line for line in logs))

    def page(self, url=URL):
        empty = SimpleNamespace(count=AsyncMock(return_value=0))
        return SimpleNamespace(url=url, wait_for_timeout=AsyncMock(),
            locator=lambda *_: empty, get_by_role=lambda *_, **__: empty)

    async def test_verified_target_is_not_reloaded_and_gem_redirect_is_same_target(self):
        for current in (URL, 'https://gemini.google.com/gem/abcdefgh/0123456789abcdef'):
            page = self.page(current)
            confirm, ready = AsyncMock(return_value=True), AsyncMock(return_value=True)
            with patch.object(service, '_gemini_verification_pending', AsyncMock(return_value=False)), \
                 patch.object(service, 'goto_with_retry_gui', AsyncMock()) as goto:
                self.assertTrue(await service._ensure_gemini_conversation_access(page, URL, confirm, ready=ready))
            goto.assert_not_awaited()
            confirm.assert_not_awaited()

    async def test_pending_challenge_reprompts_without_navigation_and_is_bounded(self):
        for success in (True, False):
            page, prompts = self.page(), []
            async def confirm():
                prompts.append(1)
                return True
            async def pending(_page):
                return not success or len(prompts) < 2
            with patch.object(service, '_page_has_human_verification', pending), \
                 patch.object(service, 'goto_with_retry_gui', AsyncMock()) as goto:
                self.assertEqual(await service._ensure_gemini_conversation_access(
                    page, URL, confirm, ready=AsyncMock(return_value=True)), success)
            self.assertEqual(len(prompts), 2 if success else 3)
            goto.assert_not_awaited()

    async def test_wrong_conversation_is_navigated_and_not_accepted_as_target(self):
        page = self.page('https://gemini.google.com/app/fedcba9876543210')
        ready = AsyncMock(return_value=True)
        with patch.object(service, '_gemini_verification_pending', AsyncMock(return_value=False)), \
             patch.object(service, 'goto_with_retry_gui', AsyncMock()) as goto:
            with self.assertRaisesRegex(RuntimeError, '正文未就绪'):
                await service._ensure_gemini_conversation_access(
                    page, URL, AsyncMock(return_value=True), ready=ready)
        self.assertEqual(goto.await_count, 1)
        ready.assert_not_awaited()

    async def test_skip_and_cancel_do_not_navigate_or_accept(self):
        with patch.object(service, 'goto_with_retry_gui', AsyncMock()) as goto:
            self.assertFalse(await service._ensure_gemini_conversation_access(
                self.page(), URL, AsyncMock(return_value=False), force=True))
            with self.assertRaises(asyncio.CancelledError):
                await service._ensure_gemini_conversation_access(
                    self.page(), URL, AsyncMock(side_effect=asyncio.CancelledError()), force=True)
        goto.assert_not_awaited()

    async def test_verification_followed_by_missing_dom_only_waits_and_reloads_once(self):
        for recover in (True, False):
            page, pending, readable, reasons = self.page(), True, False, []
            async def verification(_page):
                return pending
            async def confirm():
                nonlocal pending
                reasons.append(page._aimemory_login_reason)
                pending = False
                return True
            async def check():
                return readable
            async def reload(*_args, **_options):
                nonlocal readable
                readable = recover
            with patch.object(service, '_page_has_human_verification', verification), \
                 patch.object(service, 'goto_with_retry_gui', AsyncMock(side_effect=reload)) as goto:
                if recover:
                    self.assertTrue(await service._ensure_gemini_conversation_access(page, URL, confirm, ready=check))
                else:
                    with self.assertRaisesRegex(RuntimeError, '正文未就绪'):
                        await service._ensure_gemini_conversation_access(page, URL, confirm, ready=check)
                    self.assertEqual(page._aimemory_login_reason, 'loading')
            self.assertEqual(reasons, ['verification'])
            goto.assert_awaited_once()

    async def test_cancel_during_automatic_wait_releases_lease_without_login_prompt(self):
        from tests.test_batch_login import Context
        page = Context(1).pages[0]
        page.url = URL
        entered = asyncio.Event()
        async def wait(_milliseconds):
            entered.set()
            await asyncio.Event().wait()
        page.wait_for_timeout = wait
        callback = AsyncMock()
        coordinator = BatchLoginCoordinator([page], callback)
        with patch('gui.batch_login._set_browser_window_state', AsyncMock()):
            task = asyncio.create_task(coordinator.authorize(page, URL, AsyncMock(return_value=False)))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        callback.assert_not_awaited()
        self.assertFalse(coordinator._lock.locked())


@unittest.skipUnless(os.getenv('AI_MEMORY_BROWSER_SMOKE') == '1', 'opt-in real Chromium fixtures')
class GeminiLoginBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_reuse_blank_does_not_ask_permission_or_login_before_automatic_recovery(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(headless=True)
            try:
                context=await browser.new_context()
                page=await context.new_page()
                visits=[]
                async def route(request_route):
                    visits.append(request_route.request.url)
                    await request_route.fulfill(body=CONVERSATION if len(visits)>=3 else '<main>会话加载中</main>',
                        content_type='text/html; charset=utf-8')
                await context.route('**/*', route)
                async def ready(owner,_url):
                    return bool(await owner.locator('user-query').count())
                permission,login=Mock(return_value=True),Mock()
                with tempfile.TemporaryDirectory() as temporary, \
                     patch.object(service,'launch_browser_context',AsyncMock(return_value=(context,'fixture'))), \
                     patch.object(service,'_close_browser_context_safely',AsyncMock()), \
                     patch.object(service,'_set_browser_window_state',AsyncMock()), \
                     patch.object(service,'_page_has_conversation_content',ready), \
                     patch.object(service,'reset_platform_login',AsyncMock()) as reset:
                    result=await service.fetch_chat_pipeline(URL,login_ready_event=asyncio.Event(),
                        login_required_callback=login,login_confirmation_callback=permission,
                        image_output_dir=Path(temporary)/'images',document_output_dir=Path(temporary)/'documents')
                self.assertIsNone(result.error)
                self.assertEqual(len(result.messages),2)
                permission.assert_not_called();login.assert_not_called();reset.assert_not_awaited()
                self.assertEqual(len(visits),3)
                output=os.getenv('AI_MEMORY_LOGIN_RESULTS')
                if output:
                    service.generate_raw_markdown(result.messages,Path(output)/'单链接空白自动恢复_抓取.md')
                    (Path(output)/'单链接空白自动恢复_恢复记录.json').write_text(json.dumps(dict(
                        messages=result.messages,login_prompts=0,permission_prompts=0,navigations=len(visits)),
                        ensure_ascii=False,indent=2),encoding='utf-8')
            finally:
                await browser.close()

    async def test_blank_page_after_verification_recovers_without_second_login_prompt(self):
        await self.run_blank_recovery('验证后空白自动恢复', challenge=True)

    async def test_already_signed_in_blank_page_recovers_without_any_prompt(self):
        await self.run_blank_recovery('已有登录正文延迟恢复', challenge=False)

    async def test_persistent_blank_after_verification_reports_loading_without_login_prompt(self):
        await self.run_blank_recovery('验证后持续空白', challenge=True, recover=False)

    async def run_blank_recovery(self, name, *, challenge, recover=True):
        from playwright.async_api import async_playwright
        blank = '<div id="account">已登录账号</div><button>Switch account</button><main>正在加载会话</main>'
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context(viewport={'width':1920,'height':10800})
                page = await context.new_page()
                navigations, prompts, logs = [], [], []
                async def route(request_route):
                    navigations.append(request_route.request.url)
                    body = (CHALLENGE if challenge else blank) if len(navigations)==1 else (CONVERSATION if recover else blank)
                    await request_route.fulfill(body=body, content_type='text/html; charset=utf-8')
                await context.route('**/*', route)
                await page.goto(URL)
                async def confirm(owner, _target):
                    prompts.append(owner._aimemory_login_reason)
                    await owner.set_content(blank)
                    return True
                async def ready():
                    return bool(await page.locator('user-query, message-content').count())
                coordinator=BatchLoginCoordinator([page],confirm)
                page._aimemory_render_lock=coordinator._lock
                with patch('gui.batch_login._set_browser_window_state', AsyncMock()):
                    if recover:
                        self.assertTrue(await coordinator.authorize(page,URL,ready,logger=logs.append))
                    else:
                        with self.assertRaisesRegex(RuntimeError,'正文未就绪'):
                            await coordinator.authorize(page,URL,ready,logger=logs.append)
                        self.assertEqual(page._aimemory_login_reason,'loading')
                self.assertEqual(prompts,['verification'] if challenge else [])
                self.assertEqual(len(navigations),2,'初始加载后只自动重载一次')
                self.assertFalse(any('人工确认开始：账号登录' in line for line in logs))
                self.assertFalse(coordinator._lock.locked())
                self.assertEqual(page.viewport_size,{'width':1920,'height':10800})
                output=os.getenv('AI_MEMORY_LOGIN_RESULTS')
                if output:
                    destination=Path(output)
                    record=dict(recovered=recover,prompts=prompts,navigations=len(navigations),logs=logs)
                    if recover:
                        from bs4 import BeautifulSoup
                        from scripts.providers import gemini
                        messages=gemini.parse_messages(BeautifulSoup(await page.content(),'html.parser'))
                        self.assertEqual(len(messages),2)
                        service.generate_raw_markdown(messages,destination/f'{name}_抓取.md')
                        record['messages']=messages
                    (destination/f'{name}_恢复记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            finally:
                await browser.close()

    async def test_explicit_login_control_still_requests_login_once(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(headless=True)
            try:
                page=await browser.new_page()
                await page.route('**/*', lambda route: route.fulfill(body='<button>Sign in</button>',content_type='text/html'))
                await page.goto(URL)
                reasons=[]
                async def confirm():
                    reasons.append(page._aimemory_login_reason)
                    await page.set_content(CONVERSATION)
                    return True
                async def ready():
                    return bool(await page.locator('user-query').count())
                self.assertTrue(await service._ensure_gemini_conversation_access(page,URL,confirm,ready=ready))
                self.assertEqual(reasons,['login'])
            finally:
                await browser.close()

    async def test_short_redirect_uses_actual_share_identity_without_reloading_verified_page(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False)
            try:
                page = await browser.new_page()
                short, canonical = 'https://share.gemini.google/short-code', URL.replace('/app/', '/share/')
                visits = []
                async def route(request_route):
                    visits.append(request_route.request.url)
                    await request_route.fulfill(body=CONVERSATION, content_type='text/html; charset=utf-8')
                await page.route('**/*', route)
                native_goto = page.goto
                async def navigate(url, **options):
                    # Model the redirect landing without allowing a 302 chain
                    # to leave Playwright's intercepted first request.
                    return await native_goto(canonical if url == short else url, **options)
                page.goto = navigate
                await service.goto_with_retry_gui(page, short)
                before = list(visits)
                self.assertTrue(service._gemini_target_is_current(page, short))
                self.assertTrue(await service._ensure_gemini_conversation_access(page, short, AsyncMock(return_value=True)))
                self.assertEqual(visits, before)
                self.assertFalse(service._gemini_target_is_current(page, 'https://share.gemini.google/other-code'))
            finally:
                await browser.close()

    async def test_resting_page_retries_boundedly_without_requesting_login(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False)
            try:
                page = await browser.new_page()
                visits = 0
                always_resting = False
                async def route(request_route):
                    await request_route.fulfill(body=(CONVERSATION if '/app/' in request_route.request.url
                        else '<h1>Gemini 休整中</h1>'), content_type='text/html; charset=utf-8')
                await page.route('**/*', route)
                native_goto = page.goto
                async def navigate(url, **options):
                    nonlocal visits
                    if url == URL:
                        visits += 1
                        if visits == 1 or always_resting:
                            url = 'https://gemini.google.com/unavailable'
                    return await native_goto(url, **options)
                page.goto = navigate
                await service.goto_with_retry_gui(page, URL)
                self.assertEqual(visits, 2)
                self.assertTrue(await service._page_has_conversation_content(page, URL))
                always_resting, visits = True, 0
                with self.assertRaisesRegex(RuntimeError, '休整中'):
                    await service.goto_with_retry_gui(page, URL)
                self.assertEqual(visits, 3)
            finally:
                await browser.close()

    async def test_login_button_regex_runs_in_real_browser_on_error_and_login_pages(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False)
            try:
                page = await browser.new_page()
                await page.route('**/*', lambda route: route.fulfill(body='<main>加载失败</main>'))
                public = URL.replace('/app/', '/share/')
                await page.goto(public)
                self.assertFalse(await service._page_requires_login(page, public))
                for role, html in [('button', '<button>登录/注册</button>'), ('link', '<a href="/login">Sign in</a>')]:
                    await page.set_content(html)
                    self.assertTrue(await service._page_requires_login(page, public), role)
                await page.goto('https://accounts.google.com/ServiceLogin')
                self.assertFalse(await service._page_has_human_verification(page))
                self.assertTrue(await service._gemini_verification_pending(page))
            finally:
                await browser.close()

    async def test_visible_challenge_blocks_stale_messages_but_invisible_recaptcha_does_not(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False)
            try:
                page = await browser.new_page()
                await page.route('**/*', lambda route: route.fulfill(body='fixture'))
                await page.goto(URL)
                await page.set_content(CONVERSATION + '<iframe src="https://www.google.com/recaptcha/enterprise/anchor?size=invisible"></iframe>')
                self.assertTrue(await service._page_has_conversation_content(page, URL))
                await page.set_content(CONVERSATION + CHALLENGE)
                self.assertFalse(await service._page_has_conversation_content(page, URL))
                await page.set_content(CONVERSATION + '<iframe src="https://www.google.com/recaptcha/api2/bframe" style="display:none"></iframe>')
                self.assertTrue(await service._page_has_conversation_content(page, URL))
            finally:
                await browser.close()

    async def test_batch_keeps_verified_document_and_restores_capture_viewport(self):
        await self.run_capture('批量原页验证', batch=True)

    async def test_single_reprompts_if_first_confirmation_still_has_challenge(self):
        await self.run_capture('单链接再次验证', repeat=True)

    async def test_single_home_redirect_navigates_target_then_recovers_new_challenge(self):
        await self.run_capture('单链接首页跳转再次验证', home=True)

    async def run_capture(self, name, *, batch=False, repeat=False, home=False):
        from playwright.async_api import async_playwright
        with tempfile.TemporaryDirectory() as temporary:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=False)
                context = await browser.new_context(viewport={'width': 1920, 'height': 10800})
                page = await context.new_page()
                visits, prompts, notifications = [], [], []
                async def route(request_route):
                    if request_route.request.url == URL:
                        visits.append(URL)
                    body = '<main>Gemini 首页</main>' if request_route.request.url.endswith('/app') else CHALLENGE
                    await request_route.fulfill(body=body, content_type='text/html; charset=utf-8')
                await context.route('**/*', route)
                event = asyncio.Event()
                verification_requests = []

                async def complete(owner, _target):
                    prompts.append(owner.url)
                    if len(prompts) == 1 and home:
                        await owner.goto('https://gemini.google.com/app')
                    elif len(prompts) == 1 and repeat:
                        await owner.set_content(CHALLENGE)
                    else:
                        await owner.set_content(CONVERSATION)
                    return True

                def notify():
                    notifications.append(event.is_set())
                    async def reply():
                        await complete(page, URL)
                        event.set()
                    asyncio.create_task(reply())

                def verify():
                    verification_requests.append(True)
                    notify()

                options = dict(image_output_dir=Path(temporary)/'images',
                               document_output_dir=Path(temporary)/'documents')
                with patch.object(service, '_set_browser_window_state', AsyncMock()):
                    if batch:
                        coordinator = BatchLoginCoordinator([page], complete)
                        result = await service.fetch_chat_pipeline(URL, shared_page=page,
                            authorize_login=coordinator.authorize, **options)
                        self.assertEqual(page.viewport_size, {'width': 1920, 'height': 10800})
                        self.assertFalse(coordinator._lock.locked())
                        self.assertEqual(page.url, URL)
                    else:
                        with patch.object(service, 'launch_browser_context', AsyncMock(return_value=(context, 'fixture'))):
                            result = await service.fetch_chat_pipeline(URL, need_login=True,
                                login_ready_event=event, login_required_callback=notify,
                                verification_required_callback=verify, **options)
                        self.assertFalse(any(notifications), '每次弹窗前必须清空上次确认事件')
                        self.assertEqual(len(verification_requests), len(prompts))
                self.assertIsNone(result.error)
                self.assertEqual([m['content'] for m in result.messages], ['请记录验证标识。', '已记录验证标识。'])
                self.assertEqual(len(prompts), 2 if repeat or home else 1)
                self.assertEqual(len(visits), 2 if home else 1, '成功验证后不能刷新目标页')
                output = os.getenv('AI_MEMORY_LOGIN_RESULTS')
                if output:
                    destination = Path(output)
                    service.generate_raw_markdown(result.messages, destination/f'{name}_抓取.md')
                    (destination/f'{name}_记录.json').write_text(json.dumps(dict(
                        result=asdict(result), target_navigations=len(visits), prompts=len(prompts),
                        confirmation_event_states=notifications), ensure_ascii=False, indent=2), encoding='utf-8')
                await browser.close()


if __name__ == '__main__':
    unittest.main()
