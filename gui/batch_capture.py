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


def system_proxy_options():
    """Batch Chromium must explicitly reuse the enabled Windows manual proxy."""
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            if not winreg.QueryValueEx(key, "ProxyEnable")[0]:
                return None
            value = str(winreg.QueryValueEx(key, "ProxyServer")[0]).strip()
            try:
                bypass = str(winreg.QueryValueEx(key, "ProxyOverride")[0])
            except FileNotFoundError:
                bypass = ""
    except OSError:
        return None
    if "=" in value:
        servers = dict(part.strip().split("=", 1) for part in value.split(";") if "=" in part)
        value = servers.get("https") or servers.get("http") or ""
        if not value and servers.get("socks"):
            value = "socks5://" + servers["socks"]
    if not value:
        return None
    server = value if "://" in value else "http://" + value
    try:
        parsed = urlparse(server)
        if parsed.scheme not in {"http", "https", "socks4", "socks5"} or not parsed.hostname or not parsed.port or parsed.username or parsed.password:
            return None
    except ValueError:
        return None
    return {"server": server, "bypass": ",".join(filter(None,
            ["localhost", "127.0.0.1", "[::1]", *bypass.split(";")]))}


async def capture_links(
    links: Sequence[str],
    output_dir: Path,
    *,
    concurrency: int | None = None,
    browser_profile_root: Path = BROWSER_USER_DATA_DIR,
    cancel_event=None,
    progress: Callable[[int, int, str], None] = lambda *_: None,
    on_result: Callable[[dict], None] = lambda _: None,
    authorize_login=None,
    save_raw: Sequence[bool] | None = None,
    resume: bool = False,
    claim_item: Callable[[int], bool] | None = None,
) -> list[dict]:
    """Save links independently in one context with at most three capture pages.

    The output directory must be empty. This entry point never calls a summary API
    or copies credentials. The GUI can await human login; CLI failures stay per link.
    Native login windows may temporarily add pages during human authorization.
    """
    links = validate_capture_links(links)
    if save_raw is not None and (
        len(save_raw) != len(links) or any(type(value) is not bool for value in save_raw)
    ):
        raise ValueError("原始对话输出选择须与链接逐项对应。")
    raw_outputs = tuple(save_raw) if save_raw is not None else (True,) * len(links)
    # Snapshot per batch: changing a later batch's choice cannot resize this one.
    concurrency = MAX_CAPTURE_TABS if concurrency is None else concurrency
    if type(concurrency) is not int or not 1 <= concurrency <= 3:
        raise ValueError("抓取并发数必须是 1～3 的整数。")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    previous = None
    if any(output_dir.iterdir()):
        if not resume:
            raise ValueError("批量结果目录必须为空，避免覆盖以前的抓取。")
        try:
            saved_input = json.loads((output_dir / "input.json").read_text(encoding="utf-8"))
            previous = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            if (saved_input["links"] != links or saved_input["concurrency"] != concurrency
                    or saved_input.get("raw_outputs", [True] * len(links)) != list(raw_outputs)
                    or len(previous["items"]) != len(links)):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("已保存的批次进度与当前输入不符，无法继续。") from None
    started = time.perf_counter()
    records = []
    for index, link in enumerate(links, 1):
        platform = provider_for_url(link).DISPLAY_NAME
        target = output_dir / f"{index:03d}_{platform}"
        target.mkdir(exist_ok=resume)
        records.append(dict(index=index, url=link, platform=platform, output_dir=str(target),
                            status="queued", error=None, warnings=[], saved_files=[]))
        if previous is not None:
            old = previous["items"][index - 1]
            if (old.get("index") != index or old.get("url") != link
                    or Path(old.get("output_dir", "")).resolve() != target
                    or old.get("status") not in {"queued", "completed", "failed", "cancelled"}):
                raise ValueError("已保存的条目进度不匹配，无法继续。")
            records[-1] = old
    _write_json(output_dir / "input.json", {
        "links": links, "sha256": hashlib.sha256("\n".join(links).encode("utf-8")).hexdigest(),
        "concurrency": concurrency, "mode": "raw", "authentication": "reuse",
        **({"raw_outputs": list(raw_outputs)} if save_raw is not None else {}),
    })
    batch_warnings = []
    batch_error = None
    cancelled = False
    paused = False
    prior_elapsed = float(previous.get("elapsed_seconds", 0)) if previous else 0

    def save_manifest():
        _write_json(output_dir / "manifest.json", {
            "concurrency": concurrency, "elapsed_seconds": round(prior_elapsed + time.perf_counter() - started, 3),
            "paused": paused,
            "warnings": batch_warnings, "error": batch_error, "items": records,
        })

    def stopped():
        return cancel_event is not None and cancel_event.is_set()

    save_manifest()
    if all(record["status"] != "queued" for record in records):
        return records
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
                proxy = system_proxy_options()
                context, _channel = await launch_browser_context(
                    playwright, headless=False, viewport={"width": 1920, "height": 10800},
                    no_viewport=False, start_minimized=True, profile_root=Path(browser_profile_root),
                    **({"proxy": proxy} if proxy else {}),
                )
                # Headed Chromium can exit when its last tab closes. Keep fixed
                # worker pages alive until the entire batch finishes.
                from gui.batch_login import BatchLoginCoordinator
                pages = list(context.pages)
                pending_records = [record for record in records if record["status"] == "queued"]
                count = min(concurrency, len(pending_records))
                while len(pages) < count:
                    pages.append(await context.new_page())
                for page in pages[count:]:
                    await page.close()
                pages = pages[:count]
                render_lock = asyncio.Lock()
                for page in pages:
                    page._aimemory_render_lock = render_lock
                    await page.add_init_script(f"({_SAME_TAB_SCRIPT})()")
                login = BatchLoginCoordinator(pages, authorize_login, render_lock=render_lock)
                pending = iter(pending_records)

                async def worker(page):
                    nonlocal paused
                    for record in pending:
                        if stopped():
                            raise asyncio.CancelledError()
                        if claim_item is not None and not claim_item(record["index"]):
                            paused = True
                            break
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
                                    saved = []
                                    if raw_outputs[record["index"] - 1]:
                                        export = generate_raw_markdown(result.messages, target / "export.md")
                                        saved.append(str(export.resolve()))
                                    record.update(status="completed", saved_files=saved)
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
                if paused and record["status"] == "queued" and not (stopped() or cancelled or batch_error):
                    continue
                record["status"] = "cancelled" if stopped() or cancelled else "failed"
                record["error"] = "用户停止批量抓取。" if stopped() or cancelled else batch_error
            if record["status"] == "completed":
                record["warnings"].extend(f"批次清理：{warning}" for warning in batch_warnings)
        save_manifest()
    return records
