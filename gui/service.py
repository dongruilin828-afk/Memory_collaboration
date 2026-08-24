"""GUI 业务桥接服务模块。

纯新增模块，负责连接图形界面与底层的抓取、总结和文件保存流水线。
不修改任何原有模块，纯组合调用现有能力。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Collection, Mapping, Optional
from urllib.parse import quote, urlparse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from scripts.markdown_exporter import display_and_export
from scripts.project_paths import (
    BROWSER_USER_DATA_DIR,
    DEBUG_HTML_FILE,
    DEFAULT_EXPORT_FILE,
    IMAGES_DIR,
    PROJECT_ROOT,
)
from scripts.providers import WAIT_SELECTOR, collect_virtualized_html, parse_messages


SAVE_DEBUG_SNAPSHOT = os.getenv("AI_MEMORY_SAVE_DEBUG_HTML", "").strip() == "1"
BROWSER_MODE_ENV = "AI_MEMORY_BROWSER_MODE"
LITE_BROWSER_CHANNELS = ("msedge", "chrome")
BROWSER_CHANNEL_LABELS = {
    "chromium": "内置 Chromium",
    "msedge": "Microsoft Edge",
    "chrome": "Google Chrome",
}


def browser_channel_candidates() -> tuple[str, ...]:
    """返回当前发布变体允许使用的浏览器通道。"""
    mode = os.getenv(BROWSER_MODE_ENV, "full").strip().lower()
    return LITE_BROWSER_CHANNELS if mode == "lite" else ("chromium",)


def _browser_profile_directory(
    channel: str,
    profile_root: Optional[Path] = None,
) -> Path:
    root = Path(profile_root or BROWSER_USER_DATA_DIR).resolve()
    if browser_channel_candidates() == LITE_BROWSER_CHANNELS:
        return root / channel
    return root


async def launch_browser_context(
    playwright: Any,
    *,
    headless: bool,
    viewport: Optional[dict[str, int]],
    no_viewport: bool,
    logger: Optional[Callable[[str], None]] = None,
    profile_root: Optional[Path] = None,
) -> tuple[Any, str]:
    """启动当前变体的浏览器；轻量版按 Edge、Chrome 顺序回退。"""
    channels = browser_channel_candidates()
    last_error: Optional[BaseException] = None
    for index, channel in enumerate(channels):
        try:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(
                    _browser_profile_directory(channel, profile_root)
                ),
                headless=headless,
                channel=channel,
                viewport=viewport,
                no_viewport=no_viewport,
                ignore_default_args=["--enable-automation"],
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-service-autorun",
                ],
            )
            if logger:
                logger(f"正在使用 {BROWSER_CHANNEL_LABELS[channel]}。")
            return context, channel
        except Exception as error:
            last_error = error
            if logger and index + 1 < len(channels):
                next_channel = channels[index + 1]
                logger(
                    f"未能启动 {BROWSER_CHANNEL_LABELS[channel]}，"
                    f"正在尝试 {BROWSER_CHANNEL_LABELS[next_channel]}..."
                )

    if channels == LITE_BROWSER_CHANNELS:
        raise RuntimeError(
            "未检测到可用的 Microsoft Edge 或 Google Chrome，"
            "请下载安装其中一个浏览器，或下载全量版。"
        ) from None
    if last_error is not None:
        raise last_error
    raise RuntimeError("未能启动浏览器。")


@dataclass
class FetchResult:
    html: Optional[str]
    image_map: dict[str, str]
    messages: list[dict[str, str]]
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    user_wait_seconds: float = 0.0


@dataclass
class GenerationBundle:
    """一次 GUI 生成任务实际落盘的文件与展示选择。"""

    saved_files: list[Path]
    selected_sections: tuple[str, ...] = ()
    selected_topics: tuple[str, ...] = ()
    summary_result: Optional[dict[str, Any]] = None


DEFAULT_MODE_MARKDOWN_FILENAMES = {
    "raw": "AI_memory_export.md",
    "normal": "AI_memory_summary.md",
    "simple": "AI_memory_simple.md",
    "detailed": "AI_memory_detailed_summary.md",
}

MODE_FILENAME_SUFFIXES = {
    "raw": "_export",
    "normal": "_summary",
    "simple": "_simple",
    "detailed": "_detailed_summary",
}

GUI_IMAGE_DOWNLOAD_CONCURRENCY = 4
GUI_IMAGE_DOWNLOAD_ATTEMPTS = 2
GUI_IMAGE_DOWNLOAD_TIMEOUT_MS = 10000
GUI_REQUEST_TIMEOUT_SECONDS = 120
SILICONFLOW_FREE_SUMMARY_MODELS = (
    "Qwen/Qwen3-8B",
)


def default_output_filename(modes: Mapping[str, bool]) -> str:
    """返回保存对话框应展示的默认 Markdown 文件名。"""
    enabled_modes = [
        mode for mode in DEFAULT_MODE_MARKDOWN_FILENAMES
        if modes.get(mode)
    ]
    if len(enabled_modes) == 1:
        return DEFAULT_MODE_MARKDOWN_FILENAMES[enabled_modes[0]]
    return "AI_memory.md"


def default_summary_result_cache_dir(
    runtime_data_dir: Optional[Path] = None,
) -> Path:
    """返回 GUI 私有的本机完成结果缓存目录。"""
    if runtime_data_dir is not None:
        return Path(runtime_data_dir).resolve() / "summary_results"
    base = os.getenv("LOCALAPPDATA") or os.getenv("XDG_CACHE_HOME")
    if base:
        return Path(base) / "AI Memory Summary" / "summary_results"
    return Path.home() / ".cache" / "ai-memory-summary" / "summary_results"


def normalize_markdown_filename(filename: str) -> str:
    """只保留文件名，并将任意扩展名强制规范为小写 ``.md``。"""
    safe_name = Path(str(filename).strip()).name
    if not safe_name:
        raise ValueError("文件名不能为空。")
    path = Path(safe_name)
    if path.suffix:
        path = path.with_suffix(".md")
    else:
        path = Path(f"{safe_name}.md")
    return path.name


def build_image_asset_directory(
    save_dir: Path,
    output_filename: str,
) -> Path:
    """返回与本次 Markdown 主文件配套的便携图片目录。"""
    normalized = normalize_markdown_filename(output_filename)
    return Path(save_dir) / f"{Path(normalized).stem}_images"


def build_markdown_asset_prefix(
    asset_dir: Path,
    markdown_dir: Path,
) -> str:
    """构造相对于 Markdown 所在目录、可安全包含中文和空格的 URL 路径。"""
    relative_dir = Path(
        os.path.relpath(Path(asset_dir).resolve(), Path(markdown_dir).resolve())
    ).as_posix()
    encoded_dir = quote(relative_dir, safe="/-_.~")
    return encoded_dir if encoded_dir.startswith(".") else f"./{encoded_dir}"


def build_output_paths(
    save_dir: Path,
    modes: Mapping[str, bool],
    output_filename: Optional[str] = None,
) -> dict[str, Path]:
    """计算各模式的输出路径；未指定名称时完全沿用旧命名规则。"""
    save_dir = Path(save_dir)
    enabled_modes = [
        mode for mode in DEFAULT_MODE_MARKDOWN_FILENAMES
        if modes.get(mode)
    ]
    markdown_names = dict(DEFAULT_MODE_MARKDOWN_FILENAMES)

    if output_filename is not None:
        normalized = normalize_markdown_filename(output_filename)
        stem = Path(normalized).stem
        if len(enabled_modes) == 1:
            markdown_names[enabled_modes[0]] = normalized
        else:
            for mode in enabled_modes:
                markdown_names[mode] = (
                    f"{stem}{MODE_FILENAME_SUFFIXES[mode]}.md"
                )

    def json_name(mode: str, legacy_name: str) -> str:
        if output_filename is None:
            return legacy_name
        markdown_path = Path(markdown_names[mode])
        if len(enabled_modes) == 1:
            return markdown_path.with_suffix(".json").name
        stem = Path(normalize_markdown_filename(output_filename)).stem
        suffix = "_result" if mode == "normal" else "_detailed_result"
        return f"{stem}{suffix}.json"

    return {
        "raw_markdown": save_dir / markdown_names["raw"],
        "normal_json": save_dir / json_name(
            "normal", "AI_memory_result.json"
        ),
        "normal_markdown": save_dir / markdown_names["normal"],
        "detailed_json": save_dir / json_name(
            "detailed", "AI_memory_detailed_result.json"
        ),
        "detailed_markdown": save_dir / markdown_names["detailed"],
        "simple_markdown": save_dir / markdown_names["simple"],
        "intermediate_json": save_dir / ".gui_intermediate_result.json",
        "intermediate_markdown": save_dir / ".gui_intermediate_summary.md",
    }


def gui_summary_config_candidates(base_config: Any) -> list[Any]:
    """构造同一提供商内的 GUI 快速回退链，避免额度等待像界面卡死。"""
    candidates: list[Any] = []

    def append(candidate: Any) -> None:
        key = (candidate.provider, candidate.model)
        if key not in {
            (item.provider, item.model) for item in candidates
        }:
            candidates.append(replace(
                candidate,
                retries=1,
                rate_limit_wait_seconds=min(
                    int(candidate.rate_limit_wait_seconds), 5
                ),
                request_timeout_seconds=min(
                    int(candidate.request_timeout_seconds),
                    GUI_REQUEST_TIMEOUT_SECONDS,
                ),
            ))

    append(base_config)
    if base_config.provider == "gemini":
        append(replace(base_config, model="gemini-3.6-flash"))
        append(replace(base_config, model="gemini-3.5-flash-lite"))
    elif base_config.provider == "siliconflow":
        for model in SILICONFLOW_FREE_SUMMARY_MODELS:
            append(replace(base_config, model=model))
    return candidates


def resolve_gui_summary_config(
    base_config: Any,
    api_keys: Mapping[str, str],
) -> Any:
    """按已配置的用户密钥选择提供商，不改变该提供商的模型回退链。"""
    normalized = {
        provider: str(api_keys.get(provider) or "").strip()
        for provider in ("gemini", "siliconflow")
        if str(api_keys.get(provider) or "").strip()
    }
    if not normalized:
        from scripts.gemini_summarizer import GeminiSummaryError
        raise GeminiSummaryError("请先配置API KEY。")

    preferred_provider = (
        base_config.provider
        if base_config.provider in normalized
        else (
            "gemini" if "gemini" in normalized else "siliconflow"
        )
    )
    if preferred_provider == base_config.provider:
        return base_config

    from scripts.gemini_summarizer import (
        DEFAULT_MODEL,
        SILICONFLOW_DEFAULT_MODEL,
    )
    model = (
        SILICONFLOW_DEFAULT_MODEL
        if preferred_provider == "siliconflow"
        else DEFAULT_MODEL
    )
    return replace(base_config, provider=preferred_provider, model=model)


async def goto_with_retry_gui(page, url: str, attempts: int = 3, logger: Optional[Callable[[str], None]] = None):
    for attempt in range(1, attempts + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            return
        except Exception as e:
            if attempt >= attempts:
                raise
            if logger:
                logger(f"页面加载超时，正在进行第 {attempt + 1}/{attempts} 次尝试...")
            await page.wait_for_timeout(2000 * attempt)


def parse_fallback_messages_gui(soup: BeautifulSoup) -> list[dict[str, str]]:
    text_content = soup.get_text(separator="\n", strip=True)
    lines = text_content.split("\n")
    parsed_messages = []
    current_block = []
    is_user = True

    ignored_text = [
        "复制", "重新生成", "点赞", "踩", "分享",
        "已采纳", "查看更多", "编辑", "朗读"
    ]
    for line in lines:
        line = line.strip()
        if len(line) < 2 or line in ignored_text:
            continue
        if (
            line.startswith("回答")
            or line.startswith("好的")
            or line.startswith("字数")
            or line.endswith("字以内)")
        ):
            if current_block:
                parsed_messages.append({
                    "role": "User" if is_user else "AI",
                    "content": "\n".join(current_block)
                })
                current_block = []
                is_user = not is_user
        current_block.append(line)

    if current_block:
        parsed_messages.append({
            "role": "User" if is_user else "AI",
            "content": "\n".join(current_block)
        })

    return parsed_messages


def _image_extension(src: str) -> str:
    lowered = src.lower()
    if ".jpg" in lowered or ".jpeg" in lowered:
        return "jpg"
    if ".webp" in lowered:
        return "webp"
    return "png"


def _is_decorative_image_candidate(src: str) -> bool:
    """识别 ChatGPT 引用卡片使用的 Google favicon，避免下载无关图标。"""
    parsed = urlparse(src)
    return (
        parsed.netloc.lower() in {"google.com", "www.google.com"}
        and parsed.path.rstrip("/").lower() == "/s2/favicons"
    )


def _ordered_image_sources(candidates: list[str]) -> list[str]:
    """按 DOM 首次出现顺序去重，并排除确定无语义的装饰图片。"""
    return list(dict.fromkeys(
        src for src in candidates
        if src and not _is_decorative_image_candidate(src)
    ))


def _image_file_index(path: Path) -> int:
    match = re.match(r"img_(\d+)_", path.name)
    return int(match.group(1)) if match else 0


def _existing_image_for_source(images_dir: Path, src: str) -> Optional[Path]:
    """按 URL 哈希寻找此前已成功下载的同一资源，不依赖旧顺序编号。"""
    url_hash = hashlib.md5(src.encode("utf-8")).hexdigest()[:8]
    extension = _image_extension(src)
    matches = sorted(
        images_dir.glob(f"img_*_{url_hash}.{extension}"),
        key=lambda path: (_image_file_index(path), path.name),
    ) if images_dir.is_dir() else []
    for path in matches:
        try:
            if path.is_file() and path.stat().st_size > 0:
                return path
        except OSError:
            continue
    return None


async def _download_image_candidates(
    page: Any,
    candidates: list[str],
    images_dir: Path,
    image_reference_prefix: str,
    concurrency: int = GUI_IMAGE_DOWNLOAD_CONCURRENCY,
    warning_collector: Optional[list[str]] = None,
) -> dict[str, str]:
    """复用已有文件并受限并发下载唯一真实图片，稳定保持 DOM 顺序。"""
    images_dir = Path(images_dir)
    ordered_sources = _ordered_image_sources(candidates)
    resolved_references: dict[str, str] = {}
    pending_sources: list[str] = []
    for src in ordered_sources:
        existing = _existing_image_for_source(images_dir, src)
        if existing is None:
            pending_sources.append(src)
        else:
            resolved_references[src] = (
                f"{image_reference_prefix}/{existing.name}"
            )

    limit = max(1, min(int(concurrency), 8))
    semaphore = asyncio.Semaphore(limit)

    async def download(
        src: str,
    ) -> tuple[str, Optional[bytes], Optional[str]]:
        failure_reason: Optional[str] = None
        for _attempt in range(GUI_IMAGE_DOWNLOAD_ATTEMPTS):
            try:
                async with semaphore:
                    response = await page.request.get(
                        src, timeout=GUI_IMAGE_DOWNLOAD_TIMEOUT_MS
                    )
                    if response.ok:
                        body = await response.body()
                        if body:
                            return src, body, None
                        failure_reason = "empty_body"
                    else:
                        status = getattr(response, "status", None)
                        failure_reason = (
                            f"http_{status}" if status else "http_error"
                        )
            except Exception as error:
                failure_reason = type(error).__name__
                continue
        return src, None, failure_reason or "unknown_error"

    download_results = await asyncio.gather(*(
        download(src) for src in pending_sources
    ))
    downloaded = {
        src: body for src, body, _reason in download_results
    }
    failed_reasons = [
        reason for _src, body, reason in download_results
        if body is None and reason
    ]
    if failed_reasons and warning_collector is not None:
        reason_counts: dict[str, int] = {}
        for reason in failed_reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        reason_summary = "、".join(
            f"{reason}×{count}"
            for reason, count in sorted(reason_counts.items())
        )
        warning_collector.append(
            f"{len(failed_reasons)} 个真实图片资源下载失败"
            f"（{reason_summary}）；对话文字抓取继续保留。"
        )
    existing_indices = [
        _image_file_index(path)
        for path in images_dir.glob("img_*")
    ] if images_dir.is_dir() else []
    img_index = max(existing_indices, default=0) + 1
    for src in ordered_sources:
        if src in resolved_references:
            continue
        body = downloaded.get(src)
        if body is None:
            continue
        url_hash = hashlib.md5(src.encode("utf-8")).hexdigest()[:8]
        filename = f"img_{img_index}_{url_hash}.{_image_extension(src)}"
        images_dir.mkdir(parents=True, exist_ok=True)
        (images_dir / filename).write_bytes(body)
        resolved_references[src] = f"{image_reference_prefix}/{filename}"
        img_index += 1
    return {
        src: resolved_references[src]
        for src in ordered_sources
        if src in resolved_references
    }


async def _close_browser_context_safely(
    context: Any,
    warnings: list[str],
    logger: Optional[Callable[[str], None]] = None,
) -> None:
    """关闭浏览器；驱动已断开时保留此前结果并记录清理警告。"""
    try:
        await context.close()
    except Exception as error:
        warning = f"浏览器清理异常（已保留此前抓取结果）：{error}"
        if warning not in warnings:
            warnings.append(warning)
        if logger:
            try:
                logger(warning)
            except Exception:
                pass


async def fetch_chat_pipeline(
    url: str,
    need_login: bool = False,
    login_ready_event: Optional[asyncio.Event] = None,
    logger: Optional[Callable[[str], None]] = None,
    image_output_dir: Optional[Path] = None,
    image_reference_base: Optional[Path] = None,
    image_download_concurrency: int = GUI_IMAGE_DOWNLOAD_CONCURRENCY,
    browser_profile_root: Optional[Path] = None,
    debug_html_file: Optional[Path] = None,
) -> FetchResult:
    """异步抓取并提取网页中的对话和图片。"""
    fetch_warnings: list[str] = []
    completed_result: Optional[FetchResult] = None
    user_wait_seconds = 0.0
    if image_output_dir is None:
        resolved_images_dir = Path(IMAGES_DIR).resolve()
        image_reference_prefix = "./images"
    else:
        resolved_images_dir = Path(image_output_dir).resolve()
        reference_base = Path(
            image_reference_base or resolved_images_dir.parent
        ).resolve()
        image_reference_prefix = build_markdown_asset_prefix(
            resolved_images_dir,
            reference_base,
        )
    headless = not need_login
    viewport_config = None if need_login else {
        "width": 1920,
        "height": 10800
    }

    if logger:
        if need_login:
            logger("正在启动浏览器供您登录 AI 账号...")
        else:
            logger("正在启动无头浏览器加载分享页...")

    try:
        async with async_playwright() as playwright:
            context, _browser_channel = await launch_browser_context(
                playwright,
                headless=headless,
                viewport=viewport_config,
                no_viewport=need_login,
                logger=logger,
                profile_root=browser_profile_root,
            )
            page = context.pages[0] if context.pages else await context.new_page()

            try:
                if logger:
                    host = urlparse(url).netloc.lower() or "AI"
                    logger(f"正在加载 {host} 分享页...")
                await goto_with_retry_gui(page, url, logger=logger)

                if need_login:
                    if logger:
                        logger("请在弹出的浏览器中完成登录，并在提示框中点击【登录完毕】...")
                    if login_ready_event:
                        login_wait_started = time.perf_counter()
                        await login_ready_event.wait()
                        user_wait_seconds += (
                            time.perf_counter() - login_wait_started
                        )
                    if logger:
                        logger("登录确认完毕，正在继续抓取对话数据...")
                    await page.wait_for_timeout(2000)

                if logger:
                    logger("正在等待动态内容渲染...")
                try:
                    await page.wait_for_selector(
                        WAIT_SELECTOR,
                        state="attached",
                        timeout=15000
                    )
                except Exception:
                    if logger:
                        logger("等待动态节点超时，可能网页结构有所变化或需登录访问。")
                await page.wait_for_timeout(2000)

                html = await collect_virtualized_html(page)
                if html is None:
                    html = await page.content()

                soup_pre = BeautifulSoup(html, "html.parser")
                image_candidates: list[str] = []
                if logger:
                    logger("正在检查并下载页面中的图片资产...")

                for img in soup_pre.find_all(["img", "source"]):
                    src_candidates = [img.get("src"), img.get("data-src")]
                    srcset = img.get("srcset")
                    if srcset:
                        for item in srcset.split(","):
                            parts = item.strip().split()
                            if parts:
                                src_candidates.append(parts[0])

                    for src in src_candidates:
                        if not (
                            src
                            and src.startswith("http")
                            and not src.startswith("data:image/svg")
                        ):
                            continue
                        image_candidates.append(src)

                download_started = time.perf_counter()
                image_map = await _download_image_candidates(
                    page,
                    image_candidates,
                    resolved_images_dir,
                    image_reference_prefix,
                    image_download_concurrency,
                    fetch_warnings,
                )
                if logger:
                    usable_sources = _ordered_image_sources(image_candidates)
                    logger(
                        f"图片资产处理完成：发现 {len(image_candidates)} 个引用，"
                        f"去重并过滤装饰图后 {len(usable_sources)} 个，"
                        f"成功下载或复用 {len(image_map)} 个，耗时 "
                        f"{time.perf_counter() - download_started:.1f} 秒。"
                    )

                snapshot_saved = False
                if SAVE_DEBUG_SNAPSHOT:
                    try:
                        snapshot_path = Path(
                            debug_html_file or DEBUG_HTML_FILE
                        ).resolve()
                        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(
                            snapshot_path, "w", encoding="utf-8"
                        ) as output:
                            output.write(html)
                        snapshot_saved = True
                    except Exception:
                        pass

                soup = BeautifulSoup(html, "html.parser")
                provider, parsed_messages = parse_messages(soup, image_map)
                if provider is not None:
                    if logger:
                        logger(f"检测到 {provider.DISPLAY_NAME} 对话格式，使用专用解析器。")
                else:
                    if logger:
                        logger("未识别出平台标志性类名，使用降级解析。")
                    parsed_messages = parse_fallback_messages_gui(soup)

                if not parsed_messages:
                    completed_result = FetchResult(
                        html=html,
                        image_map=image_map,
                        messages=[],
                        error=(
                            "未能提取到有效对话内容。"
                            + (
                                "调试快照已保存到本地。"
                                if snapshot_saved else ""
                            )
                        ),
                        warnings=fetch_warnings,
                        user_wait_seconds=user_wait_seconds,
                    )
                    return completed_result

                completed_result = FetchResult(
                    html=html,
                    image_map=image_map,
                    messages=parsed_messages,
                    warnings=fetch_warnings,
                    user_wait_seconds=user_wait_seconds,
                )
                return completed_result

            finally:
                await _close_browser_context_safely(
                    context, fetch_warnings, logger
                )

    except Exception as e:
        if completed_result is not None:
            warning = (
                "Playwright 驱动退出异常（已保留此前抓取结果）："
                f"{e}"
            )
            if warning not in fetch_warnings:
                fetch_warnings.append(warning)
            if logger:
                try:
                    logger(warning)
                except Exception:
                    pass
            return completed_result
        return FetchResult(
            html=None,
            image_map={},
            messages=[],
            error=re.sub(r"https?://[^\s)\]]+", "<分享链接>", str(e)),
            warnings=fetch_warnings,
            user_wait_seconds=user_wait_seconds,
        )


def generate_raw_markdown(messages: list[dict[str, str]], target_path: Path) -> Path:
    """生成原始对话 Markdown 并保存到目标路径。"""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as file:
        file.write("# AI 对话记忆导出\n\n")
        for item in messages:
            if item["role"] == "User":
                file.write(
                    '\n<hr style="border: 0; border-top: 5px solid #2563EB; '
                    'margin: 48px 0 24px 0;">\n\n'
                    f"## 🔵 👤 用户提问\n\n{item['content']}\n\n"
                )
            else:
                file.write(
                    '\n<hr style="border: 0; border-top: 5px solid #9333EA; '
                    'margin: 48px 0 24px 0;">\n\n'
                    f"## 🟣 🤖 AI 回答\n\n{item['content']}\n\n"
                )
    return target_path


def generate_output_bundle(
    messages: list[dict[str, str]],
    modes: Mapping[str, bool],
    save_dir: Path,
    *,
    output_filename: Optional[str] = None,
    project_dir: Path = PROJECT_ROOT,
    section_selector: Optional[
        Callable[[dict[str, Any]], Collection[str] | str]
    ] = None,
    topic_selector: Optional[
        Callable[[dict[str, Any]], Collection[str] | str]
    ] = None,
    progress: Callable[[str], None] = lambda _message: None,
    config: Any = None,
    gateway: Any = None,
    api_keys: Optional[Mapping[str, str]] = None,
    result_cache_dir: Optional[Path] = None,
) -> GenerationBundle:
    """按 GUI 模式生成文件，并让普通/详细版复用同一份语义结果。

    选择器会在后端已经完成主题与分类综合、尚未写出 Markdown 时调用。
    GUI 使用 ``topic_selector`` 选择具体主题；旧的 ``section_selector`` 继续
    兼容命令行式分类选择。普通版和详细版复用同一选择结果；极简版和仅抓取
    模式不会触发选择。
    """
    if not messages:
        raise ValueError("没有可生成的对话消息。")
    if not any(bool(value) for value in modes.values()):
        raise ValueError("至少需要选择一种生成模式。")

    save_dir = Path(save_dir).resolve()
    save_dir.mkdir(parents=True, exist_ok=True)
    output_paths = build_output_paths(save_dir, modes, output_filename)
    saved_files: list[Path] = []

    if modes.get("raw"):
        raw_path = generate_raw_markdown(
            messages, output_paths["raw_markdown"]
        )
        saved_files.append(raw_path)
        progress(f"已生成 raw 对话文件：{raw_path.name}")

    needs_summary = any(
        modes.get(key) for key in ("normal", "simple", "detailed")
    )
    if not needs_summary:
        return GenerationBundle(saved_files=saved_files)

    from scripts.gemini_summarizer import (
        SUMMARY_SECTION_LABELS,
        SummaryConfig,
        create_gateway,
        normalize_summary_sections,
        normalize_summary_topics,
        summarize_conversation,
        write_summary_outputs,
    )

    config_was_provided = config is not None
    gateway_was_provided = gateway is not None
    config = config or SummaryConfig.from_env()
    user_api_keys = (
        None
        if api_keys is None
        else {
            provider: str(api_keys.get(provider) or "").strip()
            for provider in ("gemini", "siliconflow")
            if str(api_keys.get(provider) or "").strip()
        }
    )
    if user_api_keys is not None:
        config = resolve_gui_summary_config(config, user_api_keys)
    selected_sections: tuple[str, ...] = ()
    selected_topics: tuple[str, ...] = ()

    def capture_selection(result: dict[str, Any]) -> tuple[str, ...]:
        nonlocal selected_sections
        raw_selection: Collection[str] | str = ()
        if section_selector is not None:
            raw_selection = section_selector(result)
        normalized = normalize_summary_sections(raw_selection)
        selected_sections = tuple(
            key for key in SUMMARY_SECTION_LABELS if key in normalized
        )
        return selected_sections

    def capture_topic_selection(result: dict[str, Any]) -> tuple[str, ...]:
        nonlocal selected_topics
        raw_selection: Collection[str] | str = ()
        if topic_selector is not None:
            raw_selection = topic_selector(result)
        selected_topics = normalize_summary_topics(result, raw_selection)
        return selected_topics

    has_selectable_output = bool(modes.get("normal") or modes.get("detailed"))
    section_callback = (
        capture_selection
        if has_selectable_output and section_selector is not None
        else None
    )
    topic_callback = (
        capture_topic_selection
        if has_selectable_output and topic_selector is not None
        else None
    )

    if modes.get("normal"):
        primary_json = output_paths["normal_json"]
        primary_markdown = output_paths["normal_markdown"]
        primary_includes_details = False
        intermediate_only = False
    elif modes.get("detailed"):
        primary_json = output_paths["detailed_json"]
        primary_markdown = output_paths["detailed_markdown"]
        primary_includes_details = True
        intermediate_only = False
    else:
        # 极简版仍需先生成完整语义结果，但不应额外留下普通版 Markdown。
        primary_json = output_paths["intermediate_json"]
        primary_markdown = output_paths["intermediate_markdown"]
        primary_includes_details = False
        intermediate_only = True

    if gateway_was_provided:
        attempts = [(config, gateway)]
    else:
        candidate_configs = (
            [config] if config_was_provided
            else gui_summary_config_candidates(config)
        )
        attempts = [(candidate, None) for candidate in candidate_configs]

    from scripts.gemini_summarizer import (
        GeminiSummaryError,
        SummaryRequestTimeoutError,
        safe_error_message,
    )

    base_result = None
    last_error: Optional[BaseException] = None
    for attempt_index, (candidate_config, candidate_gateway) in enumerate(
        attempts, start=1
    ):
        if candidate_gateway is None:
            if user_api_keys is None:
                candidate_gateway = create_gateway(candidate_config)
            else:
                candidate_gateway = create_gateway(
                    candidate_config,
                    api_key=user_api_keys[candidate_config.provider],
                )
        progress(
            f"正在调用 {candidate_config.provider}/{candidate_config.model} "
            "生成结构化分层总结..."
        )
        try:
            base_result = summarize_conversation(
                messages=messages,
                project_dir=Path(project_dir).resolve(),
                source_dir=save_dir,
                source_name=output_paths["raw_markdown"].name,
                output_json=primary_json,
                output_markdown=primary_markdown,
                config=candidate_config,
                gateway=candidate_gateway,
                progress=progress,
                include_details=primary_includes_details,
                selected_sections=(),
                section_selector=section_callback,
                selected_topics=(),
                topic_selector=topic_callback,
                result_cache_dir=(
                    Path(result_cache_dir).resolve()
                    if result_cache_dir is not None
                    else default_summary_result_cache_dir()
                ),
            )
            config = candidate_config
            gateway = candidate_gateway
            break
        except SummaryRequestTimeoutError:
            # 网络层超时通常会同时影响同一提供商的其他模型；继续回退只会让
            # GUI 再无反馈地等待数分钟。进度缓存会保留，直接提示重试更可靠。
            raise
        except GeminiSummaryError as error:
            last_error = error
            if attempt_index >= len(attempts):
                raise
            next_config = attempts[attempt_index][0]
            safe_message = safe_error_message(
                error,
                tuple(user_api_keys.values()) if user_api_keys else (),
            )
            progress(
                f"当前模型不可用（{safe_message}），"
                f"正在切换到 {next_config.provider}/{next_config.model}..."
            )

    if base_result is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("总结后端未返回结果。")

    if modes.get("normal"):
        saved_files.extend([primary_markdown, primary_json])

    if modes.get("detailed"):
        if primary_includes_details:
            detailed_json = primary_json
            detailed_markdown = primary_markdown
        else:
            detailed_json = output_paths["detailed_json"]
            detailed_markdown = output_paths["detailed_markdown"]
            write_summary_outputs(
                base_result,
                detailed_json,
                detailed_markdown,
                include_details=True,
                selected_sections=selected_sections,
                selected_topics=selected_topics,
            )
        saved_files.extend([detailed_markdown, detailed_json])

    if modes.get("simple"):
        from scripts.simple_summarizer import (
            build_simple_metadata,
            generate_simple_overview,
            write_simple_markdown,
        )

        progress("正在生成极简版总览...")
        simple_overview = generate_simple_overview(
            base_result, messages, gateway
        )
        simple_meta = build_simple_metadata(
            base_result,
            provider=config.provider,
            model=config.model,
        )
        simple_markdown = output_paths["simple_markdown"]
        write_simple_markdown(simple_markdown, simple_overview, simple_meta)
        saved_files.append(simple_markdown)

    if intermediate_only:
        for intermediate_path in (primary_json, primary_markdown):
            try:
                intermediate_path.unlink()
            except FileNotFoundError:
                pass

    return GenerationBundle(
        saved_files=saved_files,
        selected_sections=selected_sections,
        selected_topics=selected_topics,
        summary_result=base_result,
    )
