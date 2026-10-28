"""Serialize human login; OAuth popups never borrow another capture's page."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from gui.service import _set_browser_window_state


class BatchLoginCoordinator:
    def __init__(self, pages, callback):
        self.pages = tuple(pages)
        self.callback = callback
        self._lock = asyncio.Lock()
        self._epochs = {}

    async def authorize(self, page, url, ready, *, force=False):
        """Confirm the exact target after human login, once per queued origin.

        OAuth may need an extra native login window: COOP can prevent named
        targets from reusing an unrelated worker tab. Only close this login's
        new pages, never a capture worker or the shared browser context.
        """
        if page not in self.pages:
            raise ValueError("不是本批次的工作标签页。")
        origin = urlparse(url).netloc.lower()
        epoch = self._epochs.get(origin, 0)
        async with self._lock:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if (not force or self._epochs.get(origin, 0) != epoch) and await ready():
                return True
            if self.callback is None:
                return False
            context = page.context
            existing = set(context.pages)
            opened = set()
            session = None
            script_id = None

            def new_page(child):
                opened.add(child)

            context.on("page", new_page)
            try:
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
                accepted = await self.callback(page, url)
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
                            if session is not None:
                                await session.detach()

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
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            confirmed = bool(await ready())
            if confirmed:
                self._epochs[origin] = self._epochs.get(origin, 0) + 1
            return confirmed
