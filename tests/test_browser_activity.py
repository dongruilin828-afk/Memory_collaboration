"""Only real UI is leased; no-lock callers and concurrent network work stay free."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from scripts.browser_activity import active_rendering


class BrowserActivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_leases_do_not_overlap_and_activate_the_owner(self):
        lock=asyncio.Lock();events=[]
        pages=[SimpleNamespace(_aimemory_render_lock=lock,bring_to_front=AsyncMock()) for _ in range(3)]
        async def use(index):
            async with active_rendering(pages[index]):
                events.append(('start',index))
                await asyncio.sleep(.01)
                events.append(('end',index))
        await asyncio.gather(*(use(index) for index in range(3)))
        self.assertEqual([event[0] for event in events],['start','end']*3)
        for page in pages:page.bring_to_front.assert_awaited_once()
        self.assertFalse(lock.locked())

    async def test_nested_collection_and_cancellation_release_the_lease(self):
        lock=asyncio.Lock();page=SimpleNamespace(_aimemory_render_lock=lock,bring_to_front=AsyncMock())
        entered=asyncio.Event()
        async def use():
            async with active_rendering(page):
                async with active_rendering(page):entered.set()
                await asyncio.Event().wait()
        task=asyncio.create_task(use())
        await asyncio.wait_for(entered.wait(),1);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(lock.locked())
        async with active_rendering(page):pass
        self.assertEqual(page.bring_to_front.await_count,2)

    async def test_single_link_callers_are_not_activated(self):
        page=SimpleNamespace(bring_to_front=AsyncMock())
        async with active_rendering(page):pass
        page.bring_to_front.assert_not_awaited()
