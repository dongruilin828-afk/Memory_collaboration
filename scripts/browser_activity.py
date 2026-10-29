"""Lease the real active tab for batch operations that need rendered UI."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


@asynccontextmanager
async def active_rendering(page, lock=None):
    if lock is None:
        lock = vars(page).get("_aimemory_render_lock")
    if lock is None or getattr(lock, "_aimemory_owner", None) is asyncio.current_task():
        yield
        return
    async with lock:
        lock._aimemory_owner = asyncio.current_task()
        try:
            # Emulated focus does not prevent the real background tab's 1 FPS cap.
            await page.bring_to_front()
            yield
        finally:
            lock._aimemory_owner = None
