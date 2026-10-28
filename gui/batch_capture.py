"""Three-worker authenticated capture queue; parsing stays in service.py."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from gui.service import (
    _close_browser_context_safely,
    fetch_chat_pipeline,
    generate_raw_markdown,
    launch_browser_context,
)
from scripts.project_paths import BROWSER_USER_DATA_DIR
from scripts.providers import provider_for_url


MAX_CAPTURE_TABS = 3

# Site download buttons can call window.open or use target=_blank. In batch
# pages only, keep these navigations in their owner tab (downloads stay downloads).
_SAME_TAB_SCRIPT = """() => {
    const nativeOpen = window.open.bind(window);
    window.open = (url, target, features) => {
        if (window.__aimemoryAllowLoginPopup)
            return nativeOpen(url, target, features);
        if (url) location.assign(url);
        return null;
    };
    document.addEventListener('click', event => {
        const link = event.target.closest?.('a[target]');
        if (!window.__aimemoryAllowLoginPopup && link
                && !['_self', '_parent', '_top'].includes(link.target.toLowerCase()))
            link.target = '_self';
    }, true);
}"""


def validate_capture_links(links: Sequence[str]) -> list[str]:
    if isinstance(links, (str, bytes)):
        raise ValueError("请提供链接列表，每行一个链接。")
    result = [str(link).strip() for link in links if str(link).strip()]
    if not result:
        raise ValueError("请至少添加一个链接。")
    for index, link in enumerate(result, 1):
        if link.startswith("http://"):
            link = "https://" + link[7:]
            result[index - 1] = link
        parsed = urlparse(link)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or any(char.isspace() for char in link) or provider_for_url(link) is None):
            raise ValueError(f"第 {index} 项不是受支持的 HTTPS 对话链接；批量暂不支持文件。")
    return result


def _write_json(path: Path, value) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def capture_links(
    links: Sequence[str],
    output_dir: Path,
    *,
    browser_profile_root: Path = BROWSER_USER_DATA_DIR,
    cancel_event=None,
    progress: Callable[[int, int, str], None] = lambda *_: None,
    on_result: Callable[[dict], None] = lambda _: None,
    authorize_login=None,
) -> list[dict]:
    """Save links independently in one context with at most three capture pages.

    The output directory must be empty. This entry point never calls a summary API
    or copies credentials. The GUI can await human login; CLI failures stay per link.
    Native login windows may temporarily add pages during human authorization.
    """
    links = validate_capture_links(links)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise ValueError("批量结果目录必须为空，避免覆盖以前的抓取。")
    started = time.perf_counter()
    records = []
    for index, link in enumerate(links, 1):
        platform = provider_for_url(link).DISPLAY_NAME
        target = output_dir / f"{index:03d}_{platform}"
        target.mkdir()
        records.append(dict(index=index, url=link, platform=platform, output_dir=str(target),
                            status="queued", error=None, warnings=[], saved_files=[]))
    _write_json(output_dir / "input.json", {
        "links": links, "sha256": hashlib.sha256("\n".join(links).encode("utf-8")).hexdigest(),
        "concurrency": MAX_CAPTURE_TABS, "mode": "raw", "authentication": "reuse",
    })
    batch_warnings = []
    batch_error = None
    cancelled = False

    def save_manifest():
        _write_json(output_dir / "manifest.json", {
            "concurrency": MAX_CAPTURE_TABS, "elapsed_seconds": round(time.perf_counter() - started, 3),
            "warnings": batch_warnings, "error": batch_error, "items": records,
        })

    def stopped():
        return cancel_event is not None and cancel_event.is_set()

    save_manifest()
    workers = []
    monitor = None
    context = None
    owner = asyncio.current_task()

    async def watch_stop():
        while not stopped():
            await asyncio.sleep(0.1)
        if not owner.done():
            owner.cancel()

    try:
        if stopped():
            raise asyncio.CancelledError()
        if cancel_event is not None:
            monitor = asyncio.create_task(watch_stop())
        async with async_playwright() as playwright:
            try:
                progress(0, len(links), "正在启动共享浏览器，复用已保存的登录状态…")
                context, _channel = await launch_browser_context(
                    playwright, headless=False, viewport={"width": 1920, "height": 10800},
                    no_viewport=False, start_minimized=True, profile_root=Path(browser_profile_root),
                )
                # Headed Chromium can exit when its last tab closes. Keep fixed
                # worker pages alive until the entire batch finishes.
                from gui.batch_login import BatchLoginCoordinator
                pages = list(context.pages)
                count = min(MAX_CAPTURE_TABS, len(links))
                while len(pages) < count:
                    pages.append(await context.new_page())
                for page in pages[count:]:
                    await page.close()
                pages = pages[:count]
                for page in pages:
                    await page.add_init_script(f"({_SAME_TAB_SCRIPT})()")
                login = BatchLoginCoordinator(pages, authorize_login)
                pending = iter(records)

                async def worker(page):
                    for record in pending:
                        if stopped():
                            raise asyncio.CancelledError()
                        target = Path(record["output_dir"])
                        record["status"] = "running"
                        item_started = time.perf_counter()
                        result = payload = None
                        with (target / "run.log").open("w", encoding="utf-8") as log:
                            def report(message):
                                log.write(str(message) + "\n")
                                log.flush()
                                progress(record["index"], len(links), str(message))

                            try:
                                result = await fetch_chat_pipeline(
                                    record["url"], shared_page=page, need_login=False,
                                    browser_profile_root=Path(browser_profile_root),
                                    image_output_dir=target / "images", image_reference_base=target,
                                    document_output_dir=target / "documents", document_reference_base=target,
                                    debug_html_file=target / "debug.html", logger=report,
                                    **({"authorize_login": login.authorize} if authorize_login is not None else {}),
                                )
                                payload = asdict(result)
                                (target / "snapshot.html").write_text(payload.pop("html") or "", encoding="utf-8", newline="")
                                payload.update(url=record["url"], files={
                                    path.relative_to(target).as_posix(): _file_hash(path)
                                    for folder in ("images", "documents")
                                    for path in (target / folder).glob("*") if path.is_file()
                                })
                                _write_json(target / "result.json", payload)
                                record.update(error=result.error, warnings=list(result.warnings),
                                              messages=len(result.messages), images=len(set(result.image_map.values())),
                                              documents=len(set(result.document_map.values())),
                                              wait_seconds=result.user_wait_seconds)
                                if result.error or not result.messages:
                                    record["status"] = "failed"
                                    record["error"] = result.error or "未能提取到有效对话内容。"
                                else:
                                    export = generate_raw_markdown(result.messages, target / "export.md")
                                    record.update(status="completed", saved_files=[str(export.resolve())])
                            except asyncio.CancelledError:
                                record["status"] = "cancelled"
                                raise
                            except Exception as error:
                                record.update(status="failed", error=f"{type(error).__name__}: {error}")
                            finally:
                                # Do not retain the last conversation while the next one loads.
                                result = payload = None
                                try:
                                    await page.goto("about:blank", wait_until="commit", timeout=10000)
                                except Exception:
                                    record["warnings"].append("标签页未能复位，请核对浏览器状态。")
                                finally:
                                    record["elapsed_seconds"] = round(time.perf_counter() - item_started, 3)
                                    save_manifest()
                                    on_result(dict(record))
                        progress(record["index"], len(links), {
                            "completed": "抓取完成", "failed": "抓取失败", "cancelled": "已停止",
                        }[record["status"]])

                workers = [asyncio.create_task(worker(page)) for page in pages]

                await asyncio.gather(*workers)
            finally:
                for task in workers:
                    if not task.done() and not task.cancelling():
                        task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                if context is not None:
                    await _close_browser_context_safely(context, batch_warnings)
    except asyncio.CancelledError:
        cancelled = True
        raise
    except Exception as error:
        batch_error = f"{type(error).__name__}: {error}"
        raise
    finally:
        if monitor is not None:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        for record in records:
            if record["status"] in {"queued", "running"}:
                record["status"] = "cancelled" if stopped() or cancelled else "failed"
                record["error"] = "用户停止批量抓取。" if stopped() or cancelled else batch_error
            if record["status"] == "completed":
                record["warnings"].extend(f"批次清理：{warning}" for warning in batch_warnings)
        save_manifest()
    return records
