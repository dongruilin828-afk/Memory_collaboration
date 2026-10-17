"""豆包全量抓取及三种总结的人工验收入口。"""
import argparse
import asyncio
import hashlib
import json
import re
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.credential_store import WindowsCredentialStore
from gui import service
from gui.service import fetch_chat_pipeline, generate_output_bundle, generate_raw_markdown

ROOT = Path(__file__).resolve().parents[1]
TEXT = Path(__file__).with_name("tests.txt").read_text(encoding="utf-8-sig")
SECTION = re.split(r"豆包：", TEXT, maxsplit=1)[1].split("DeepSeek：", 1)[0]
CASES = re.findall(r"https://www\.doubao\.com/(?:thread|chat)/\S+", SECTION)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture-only", action="store_true")
    mode.add_argument("--summary-only", action="store_true")
    parser.add_argument("--preferred-provider", choices=("siliconflow", "deepseek"),
                        help="仅本次总结优先使用的已配置后端")
    parser.add_argument("--profile", type=Path, default=ROOT / ".browser_user_data")
    parser.add_argument("--reuse", type=Path, help="按 URL 复用旧批次中无错误、无警告的抓取")
    parser.add_argument("--resume", action="store_true", help="继续原批次，保留成功项，重试失败及有警告项")
    parser.add_argument("--cases", nargs="+", type=int)
    parser.add_argument("--force-cases", nargs="+", type=int, default=[], help="即使旧结果成功也重新抓取指定编号")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--login-signal", type=Path)
    parser.add_argument("--case-timeout", type=int, default=300)
    parser.add_argument("--cdp-port", type=int, help="仅增加本机调试端口，便于观察当前测试浏览器")
    parser.add_argument("--attach-cdp-port", type=int, help="连接用户保持打开的项目 Chromium 验证私有会话")
    parser.add_argument("--attachment-retry-link", help="指定编号的附件下载失败时使用原始会话链接重试")
    parser.add_argument("--attachment-retry-case", type=int, default=15,
                        help="指定 --attachment-retry-link 对应的测试编号")
    parser.add_argument("--retry-paired-attachments", action="store_true", help="分享页附件失败时尝试测试列表中紧随其后的对应私有会话")
    parser.add_argument("--skip-documents-for-recovery", action="store_true", help="仅为失败项补抓正文，跳过会阻塞的文档请求")
    args = parser.parse_args()
    if args.skip_documents_for_recovery:
        async def skip_documents(*_args, **_kwargs):
            return {}

        async def skip_ai_documents(*_args, **_kwargs):
            return {}, 0

        service._download_document_candidates = skip_documents
        service._save_doubao_ai_documents = skip_ai_documents
    if args.cdp_port:
        original_context_launcher = service.launch_browser_context

        async def diagnostic_context_launcher(playwright, **options):
            original_launch = playwright.chromium.launch_persistent_context

            async def launch_with_port(*positional, **launch_options):
                launch_options["args"] = [*launch_options.get("args", []),
                                          f"--remote-debugging-port={args.cdp_port}",
                                          "--remote-debugging-address=127.0.0.1"]
                return await original_launch(*positional, **launch_options)

            playwright.chromium.launch_persistent_context = launch_with_port
            try:
                return await original_context_launcher(playwright, **options)
            finally:
                playwright.chromium.launch_persistent_context = original_launch

        service.launch_browser_context = diagnostic_context_launcher

    original_context_launcher = service.launch_browser_context
    original_context_closer = service._close_browser_context_safely
    attached_contexts = set()

    async def hybrid_context(playwright, **options):
        profile = Path(options.get("profile_root") or args.profile).resolve()
        if profile != args.profile.resolve():
            return await original_context_launcher(playwright, **options)
        browser = await playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{args.attach_cdp_port}"
        )
        context = browser.contexts[0]
        attached_contexts.add(context)
        return context, "chromium"

    async def close_hybrid_context(context, warnings, logger=None):
        if context in attached_contexts:
            return None
        return await original_context_closer(context, warnings, logger)

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not CASES:
        parser.error("tests/tests.txt 中未找到豆包链接")
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig")) if manifest_path.exists() else []
    if args.capture_only and manifest and not args.resume:
        parser.error(f"结果目录已有 manifest.json，为避免覆盖请使用新的目录：{output}")

    if args.capture_only:
        previous = {item["url"]: item for item in manifest} if args.resume else {}
        if args.reuse:
            previous = {item["url"]: item for item in json.loads(
                (args.reuse / "manifest.json").read_text(encoding="utf-8")
            )}
        metadata = {
            "urls": CASES,
            "url_count": len(CASES),
            "profile": str(args.profile.resolve()),
            "headed": args.headed,
            "reuse": str(args.reuse.resolve()) if args.reuse else None,
            "resume": args.resume,
            "case_timeout_seconds": args.case_timeout,
            "cdp_port": args.cdp_port,
            "skip_documents_for_recovery": args.skip_documents_for_recovery,
            "source_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in ("tests/tests.txt", "gui/service.py", "scripts/providers/doubao.py",
                             "scripts/gemini_summarizer.py", "scripts/simple_summarizer.py")
            },
        }
        (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        for index, url in enumerate(CASES, 1):
            if args.cases and index not in args.cases:
                continue
            case = f"{index:02d}"
            target = output / case
            old = previous.get(url)
            if index not in args.force_cases and old and old.get("messages") and not any(old.get(key) for key in ("error", "exception", "warnings")):
                source = (args.reuse or output) / old["case"]
                if source.resolve() != target.resolve():
                    shutil.copytree(source, target)
                record = dict(old, case=case)
                if args.reuse:
                    record.update(reused_from=str(source.resolve()), original_case=old["case"])
                manifest = [item for item in manifest if item["url"] != url] + [record]
                manifest.sort(key=lambda item: int(item["case"]))
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"[{case}] 复用已成功抓取：{url}", flush=True)
                continue
            archive = None
            if target.exists():
                if not args.resume:
                    parser.error(f"结果目录已存在：{target}")
                archive = target / f"capture_before_retry_{time.time_ns()}"
                archive.mkdir()
                for path in list(target.iterdir()):
                    if path == archive or path.name.startswith("capture_before_retry_"):
                        continue
                    if not path.resolve().is_relative_to(output) or not archive.resolve().is_relative_to(output):
                        raise RuntimeError("归档路径超出结果目录")
                    path.rename(archive / path.name)
            target.mkdir(exist_ok=True)
            started = time.perf_counter()
            record = {"case": case, "url": url, "browser_mode": "headed" if args.headed else "headless",
                      "case_timeout_seconds": args.case_timeout}
            if archive:
                record["previous_capture"] = archive.relative_to(output).as_posix()
            with (target / "run.log").open("w", encoding="utf-8") as log:
                login_ready = asyncio.Event()

                def logger(message):
                    log.write(message + "\n")
                    log.flush()
                    print(f"[{case}] {message}", flush=True)

                def login_required():
                    logger("需要登录时，请在弹出的浏览器完成登录，然后回到终端按 Enter。")

                    async def wait_for_enter():
                        if args.login_signal:
                            stamp = args.login_signal.stat().st_mtime_ns if args.login_signal.exists() else 0
                            while not args.login_signal.exists() or args.login_signal.stat().st_mtime_ns <= stamp:
                                await asyncio.sleep(1)
                        else:
                            await asyncio.to_thread(input, "登录完成后按 Enter 继续：")
                        login_ready.set()

                    asyncio.create_task(wait_for_enter())

                try:
                    if args.attach_cdp_port:
                        service.launch_browser_context = hybrid_context
                        service._close_browser_context_safely = close_hybrid_context
                    else:
                        service.launch_browser_context = original_context_launcher
                        service._close_browser_context_safely = original_context_closer
                    def attachment_link(names=None):
                        logger("附件重试类型：" + "、".join(names or []))
                        if index == args.attachment_retry_case and args.attachment_retry_link:
                            return args.attachment_retry_link
                        if args.retry_paired_attachments and index in (9, 11, 13, 15):
                            return CASES[index]
                        return None
                    result = await asyncio.wait_for(fetch_chat_pipeline(
                        url,
                        need_login=args.headed,
                        login_ready_event=login_ready,
                        login_required_callback=login_required,
                        login_confirmation_callback=lambda: True,
                        attachment_web_link_callback=(
                            attachment_link
                            if (index == args.attachment_retry_case and args.attachment_retry_link)
                            or (args.retry_paired_attachments and index in (9, 11, 13, 15))
                            else None
                        ),
                        logger=logger,
                        image_output_dir=target / "images",
                        image_reference_base=target,
                        document_output_dir=target / "documents",
                        document_reference_base=target,
                        browser_profile_root=args.profile.resolve(),
                    ), timeout=args.case_timeout)
                    payload = asdict(result)
                    if args.skip_documents_for_recovery:
                        note = "测试补抓跳过了会阻塞的文档请求；文档正文及附件未验证。"
                        result.warnings.append(note)
                        payload["warnings"] = list(result.warnings)
                    (target / "snapshot.html").write_text(payload.pop("html") or "", encoding="utf-8")
                    payload.update(url=url, elapsed=time.perf_counter() - started)
                    payload["files"] = {
                        path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                        for folder in ("images", "documents")
                        for path in (target / folder).glob("*")
                        if path.is_file()
                    }
                    (target / "result.json").write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    record.update(
                        messages=len(result.messages),
                        images=len(set(result.image_map.values())),
                        documents=len(set(result.document_map.values())),
                        error=result.error,
                        warnings=result.warnings,
                    )
                    if not result.messages:
                        raise RuntimeError(result.error or "未抓取到消息")
                    generate_raw_markdown(result.messages, target / "export.md")
                    logger(
                        f"抓取完成：{len(result.messages)} 条消息，"
                        f"{record['images']} 张图片，{record['documents']} 个文档；"
                        f"错误 {result.error}；警告 {result.warnings}"
                    )
                except Exception as error:
                    detail = f"单项抓取超过测试时限 {args.case_timeout} 秒，已中断" if isinstance(error, asyncio.TimeoutError) else str(error)
                    record["exception"] = f"{type(error).__name__}: {detail}"
                    (target / "error.txt").write_text(record["exception"], encoding="utf-8")
                    logger(f"异常：{record['exception']}")
                finally:
                    service.launch_browser_context = original_context_launcher
                    service._close_browser_context_safely = original_context_closer
            record["elapsed"] = time.perf_counter() - started
            manifest = [item for item in manifest if item["url"] != url] + [record]
            manifest.sort(key=lambda item: int(item["case"]))
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    keys = {provider: secret for provider, secret in WindowsCredentialStore().load_api_keys().items()
            if provider in {"siliconflow", "deepseek"}}
    if args.preferred_provider:
        if not keys.get(args.preferred_provider):
            parser.error(f"未配置 {args.preferred_provider} API KEY")
        keys = {args.preferred_provider: keys[args.preferred_provider],
                **{provider: secret for provider, secret in keys.items()
                   if provider != args.preferred_provider}}
    status_suffix = "_" + "-".join(map(str, args.cases)) if args.cases else ""
    summary_manifest_path = output / f"summary_manifest{status_suffix}.json"
    for record in manifest:
        case = record["case"]
        if args.cases and int(case) not in args.cases:
            continue
        target = output / case
        expected = ("AI_memory_summary.md", "AI_memory_simple.md", "AI_memory_detailed_summary.md")
        if all((target / name).is_file() and (target / name).stat().st_size for name in expected):
            record["summary_status"] = "existing"
            print(f"[{case}] 三种总结已存在，保留。", flush=True)
            continue
        payload_path = target / "result.json"
        if not payload_path.is_file():
            print(f"[{case}] 缺少 result.json，跳过总结。", flush=True)
            record["summary_status"] = "missing_capture"
            continue
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        messages = payload.get("messages") or []
        if not messages:
            print(f"[{case}] 没有可总结的消息，跳过。", flush=True)
            record["summary_status"] = "no_messages"
            continue
        with (target / "summary.log").open("w", encoding="utf-8") as log:
            def logger(message):
                log.write(message + "\n")
                log.flush()
                print(f"[{case}] {message}", flush=True)

            try:
                bundle = await asyncio.to_thread(
                    generate_output_bundle,
                    messages,
                    {"raw": False, "normal": True, "simple": True, "detailed": True},
                    target,
                    project_dir=ROOT,
                    api_keys=keys,
                    result_cache_dir=output / "summary_cache",
                    source_platform="豆包",
                    source_name="export.md",
                    source_dir=target,
                    progress=logger,
                )
                summary_files = [path for path in bundle.saved_files if path != target / "export.md"]
                missing = [name for name in ("AI_memory_summary.md", "AI_memory_simple.md", "AI_memory_detailed_summary.md")
                           if not any(path.name == name for path in summary_files)]
                if missing:
                    raise RuntimeError("缺少总结输出：" + ", ".join(missing))
                record.update(summaries=[path.relative_to(target).as_posix() for path in summary_files], summary_status="generated")
                logger("三种总结均已生成。")
            except Exception as error:
                from scripts.gemini_summarizer import safe_error_message
                message = safe_error_message(error)
                record.update(summary_status="failed", summary_error=message)
                (target / "summary_error.txt").write_text(
                    message, encoding="utf-8"
                )
                logger(f"总结异常：{message}")
        summary_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
