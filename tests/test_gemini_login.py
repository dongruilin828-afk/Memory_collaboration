"""Gemini human verification must retain the verified target document."""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from gui import service
from gui.batch_login import BatchLoginCoordinator

URL = 'https://gemini.google.com/app/0123456789abcdef'
CONVERSATION = '''<user-query><div class="query-text">请记录验证标识。</div></user-query>
<model-response><message-content><p>已记录验证标识。</p></message-content></model-response>'''
CHALLENGE = '<form id="captcha-form">请完成人机验证</form>'


class GeminiLoginTests(unittest.IsolatedAsyncioTestCase):
    def page(self, url=URL):
        return SimpleNamespace(url=url, wait_for_timeout=AsyncMock())

    async def test_verified_target_is_not_reloaded_and_gem_redirect_is_same_target(self):
        for current in (URL, 'https://gemini.google.com/gem/abcdefgh/0123456789abcdef'):
            page = self.page(current)
            confirm, ready = AsyncMock(return_value=True), AsyncMock(return_value=True)
            with patch.object(service, '_gemini_verification_pending', AsyncMock(return_value=False)), \
                 patch.object(service, 'goto_with_retry_gui', AsyncMock()) as goto:
                self.assertTrue(await service._ensure_gemini_conversation_access(page, URL, confirm, ready=ready))
            goto.assert_not_awaited()
            confirm.assert_awaited_once()

    async def test_pending_challenge_reprompts_without_navigation_and_is_bounded(self):
        for success in (True, False):
            page, prompts = self.page(), []
            async def confirm():
                prompts.append(1)
                return True
            async def pending(_page):
                return not success or len(prompts) < 2
            with patch.object(service, '_gemini_verification_pending', pending), \
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
            self.assertFalse(await service._ensure_gemini_conversation_access(
                page, URL, AsyncMock(return_value=True), ready=ready))
        self.assertEqual(goto.await_count, 3)
        ready.assert_not_awaited()

    async def test_skip_and_cancel_do_not_navigate_or_accept(self):
        with patch.object(service, 'goto_with_retry_gui', AsyncMock()) as goto:
            self.assertFalse(await service._ensure_gemini_conversation_access(
                self.page(), URL, AsyncMock(return_value=False)))
            with self.assertRaises(asyncio.CancelledError):
                await service._ensure_gemini_conversation_access(
                    self.page(), URL, AsyncMock(side_effect=asyncio.CancelledError()))
        goto.assert_not_awaited()


@unittest.skipUnless(os.getenv('AI_MEMORY_BROWSER_SMOKE') == '1', 'opt-in real Chromium fixtures')
class GeminiLoginBrowserTests(unittest.IsolatedAsyncioTestCase):
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
                                login_ready_event=event, login_required_callback=notify, **options)
                        self.assertFalse(any(notifications), '每次弹窗前必须清空上次确认事件')
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
