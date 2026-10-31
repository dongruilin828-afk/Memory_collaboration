"""Serialize human login; OAuth popups never borrow another capture's page."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

from gui.browser_login import platform_login_key

from gui.service import (
    GEMINI_HOSTS, _ensure_gemini_conversation_access, _gemini_target_is_current,
    _gemini_verification_pending, _set_browser_window_state,
)
from scripts.browser_activity import active_rendering


LOGIN_VIEWPORT = {"width": 1200, "height": 800}


class BatchLoginCoordinator:
    def __init__(self, pages, callback, *, render_lock=None):
        self.pages = tuple(pages)
        self.callback = callback
        self._lock = render_lock if render_lock is not None else asyncio.Lock()
        self._epochs = {}
        self._page_epochs = {}

    async def authorize(self, page, url, ready, *, force=False, logger=None):
        """Confirm the exact target after human login, once per queued origin.

        OAuth may need an extra native login window: COOP can prevent named
        targets from reusing an unrelated worker tab. Only close this login's
        new pages, never a capture worker or the shared browser context.
        """
        if page not in self.pages:
            raise ValueError("不是本批次的工作标签页。")
        origin = platform_login_key(url)
        epoch = self._epochs.get(origin, 0)
        gemini = urlparse(url).hostname in GEMINI_HOSTS
        def report(message):
            if logger:
                logger(f"[{time.strftime('%H:%M:%S')}] {message}")
        async with active_rendering(page, self._lock):
            refreshed_login = self._page_epochs.get((page, origin), 0) < self._epochs.get(origin, 0)
            reuse_allowed = not force or self._epochs.get(origin, 0) != epoch
            if gemini and reuse_allowed and _gemini_target_is_current(page, url) and await ready():
                self._page_epochs[page, origin] = self._epochs.get(origin, 0)
                report('当前目标已可读，直接复用，未刷新页面、未请求人工确认。')
                return True
            # Tabs loaded before another worker logged in still show stale login
            # UI. Reload those once with the newly shared cookies, even Gemini.
            if not gemini or refreshed_login or (not _gemini_target_is_current(page, url)
                              and not await _gemini_verification_pending(page)):
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if (not force or self._epochs.get(origin, 0) != epoch) and await ready():
                self._page_epochs[page, origin] = self._epochs.get(origin, 0)
                report('已复用共享授权状态，目标可读，无需人工确认。')
                return True
            if self.callback is None:
                return False
            context = page.context
            existing = set(context.pages)
            opened = set()
            session = None
            script_id = None
            original_viewport = page.viewport_size
            prompts = 0

            async def prompt():
                nonlocal prompts
                prompts += 1
                verification = gemini and getattr(page, '_aimemory_login_reason', '') == 'verification'
                page._aimemory_login_reason = 'verification' if verification else 'login'
                report(f"人工确认开始：{'真人验证' if verification else '账号登录/切换'}；本轮第 {prompts} 次提示。")
                accepted = await self.callback(page, url)
                report(f"人工确认返回：{'继续检查页面' if accepted else '跳过此项'}。")
                return accepted

            def new_page(child):
                opened.add(child)

            context.on("page", new_page)
            try:
                # A 10800px capture viewport centers login forms off-screen.
                if original_viewport is not None:
                    await page.set_viewport_size(LOGIN_VIEWPORT)
                # Install before document scripts, including automatic OAuth
                # redirects; CDP permits removing it after this authorization.
                session = await context.new_cdp_session(page)
                await session.send('Page.enable')
                script_id = (await session.send('Page.addScriptToEvaluateOnNewDocument', {
                    'source': 'window.__aimemoryAllowLoginPopup = true;',
                }))['identifier']
                await page.evaluate("window.__aimemoryAllowLoginPopup = true;")
                await _set_browser_window_state(page, "maximized")
                await page.bring_to_front()
                accepted = (await _ensure_gemini_conversation_access(
                    page, url, prompt, ready=ready, logger=logger, force=force and not reuse_allowed,
                ) if gemini else await prompt())
            finally:
                async def cleanup():
                    try:
                        if script_id is not None:
                            await session.send('Page.removeScriptToEvaluateOnNewDocument', {'identifier': script_id})
                        await page.evaluate("window.__aimemoryAllowLoginPopup = false;")
                    finally:
                        try:
                            while True:
                                children = (opened | (set(context.pages) - existing)) - set(self.pages)
                                children = [child for child in children if not child.is_closed()]
                                if not children:
                                    break
                                await asyncio.gather(*(child.close() for child in children))
                        finally:
                            context.remove_listener("page", new_page)
                            try:
                                if session is not None:
                                    await session.detach()
                            finally:
                                if original_viewport is not None and not page.is_closed():
                                    await page.set_viewport_size(original_viewport)

                cleaning = asyncio.create_task(asyncio.wait_for(cleanup(), timeout=15))
                cancelled = False
                while not cleaning.done():
                    try:
                        await asyncio.shield(cleaning)
                    except asyncio.CancelledError:
                        cancelled = True
                cleaning.result()
                if cancelled:
                    raise asyncio.CancelledError()
            if not accepted:
                return False
            if not gemini:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            confirmed = accepted if gemini else bool(await ready())
            report(f"授权恢复结束：{'目标已可读' if confirmed else '目标仍不可读'}；人工提示 {prompts} 次。")
            if confirmed:
                self._epochs[origin] = self._epochs.get(origin, 0) + 1
                self._page_epochs[page, origin] = self._epochs[origin]
            return confirmed
