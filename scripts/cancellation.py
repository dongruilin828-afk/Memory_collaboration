"""Cooperative cancellation for a synchronous caller owning async requests."""

import asyncio
from contextlib import suppress
import time


def check_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError()


def wait_with_cancel(seconds, cancel_event, sleep=time.sleep):
    if cancel_event is None:
        sleep(seconds)
    elif cancel_event.wait(seconds):
        raise asyncio.CancelledError()


def run_cancellable_request(factory, cancel_event):
    """Cancel once, then let the request's async cleanup finish before returning."""
    check_cancelled(cancel_event)

    async def run():
        async def stopped():
            while not cancel_event.is_set():
                await asyncio.sleep(0.05)

        request = asyncio.create_task(factory())
        observer = asyncio.create_task(stopped())
        try:
            await asyncio.wait((request, observer), return_when=asyncio.FIRST_COMPLETED)
            if cancel_event.is_set() and not request.done():
                request.cancel()
            result = await request
            check_cancelled(cancel_event)
            return result
        finally:
            observer.cancel()
            with suppress(asyncio.CancelledError):
                await observer

    return asyncio.run(run())
