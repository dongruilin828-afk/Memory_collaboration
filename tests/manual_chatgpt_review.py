"""全量验证 tests.txt 中的 ChatGPT 抓取和三种总结。"""
import asyncio
import hashlib
import json
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.credential_store import WindowsCredentialStore
from gui.service import fetch_chat_pipeline, generate_output_bundle, generate_raw_markdown

ROOT = Path(__file__).resolve().parents[1]
TEXT = Path(__file__).with_name("tests.txt").read_text(encoding="utf-8-sig")
SECTION = re.split(r"ChatGPT：", TEXT, maxsplit=1, flags=re.IGNORECASE)[1].split("豆包：", 1)[0]
CASES = re.findall(r"https://chatgpt\.com/\S+", SECTION)


async def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", nargs="*", type=int)
    parser.add_argument("--skip-summary", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--attachment-web-link")
    parser.add_argument("--profile", type=Path, default=ROOT / ".browser_user_data")
    parser.add_argument("--need-login", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    api_keys = WindowsCredentialStore().load_api_keys()
    manifest_path = args.output / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if args.summary_only and manifest_path.exists()
        else []
    )
    selected = set(args.cases or range(1, len(CASES) + 1))

    for index, url in enumerate(CASES, 1):
        if index not in selected:
            continue
        case = f"{index:02d}"
        target = args.output / case
        target.mkdir(exist_ok=True)
        started = time.perf_counter()
        with (target / "run.log").open("w", encoding="utf-8") as log:
            def logger(message):
                log.write(message + "\n")
                log.flush()
                print(f"[{case}] {message}", flush=True)

            record = next(
                (item.copy() for item in manifest if item.get("case") == case),
                {"case": case, "url": url},
            )
            try:
                if args.summary_only:
                    payload = json.loads((target / "result.json").read_text(encoding="utf-8"))
                    messages = payload["messages"]
                    if not messages:
                        raise RuntimeError(payload.get("error") or "未抓取到消息")
                    bundle = generate_output_bundle(
                        messages,
                        {"raw": False, "normal": True, "simple": True, "detailed": True},
                        target,
                        project_dir=ROOT,
                        api_keys=api_keys,
                        result_cache_dir=args.output / "summary_cache",
                        source_platform="ChatGPT",
                        source_name="export.md",
                        source_dir=target,
                        progress=logger,
                    )
                    record.update(
                        messages=len(messages),
                        outputs=[path.relative_to(args.output).as_posix() for path in bundle.saved_files],
                        elapsed=time.perf_counter() - started,
                    )
                    logger(f"总结完成：{len(messages)} 条消息")
                    manifest = [item for item in manifest if item.get("case") != case]
                    manifest.append(record)
                    manifest.sort(key=lambda item: item["case"])
                    manifest_path.write_text(
                        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    continue

                login_ready = asyncio.Event()
                signal = args.output / "login_ready.signal"

                async def wait_for_login_signal():
                    while not signal.exists() or signal.stat().st_mtime < started:
                        await asyncio.sleep(1)
                    login_ready.set()

                asyncio.create_task(wait_for_login_signal())
                result = await fetch_chat_pipeline(
                    url,
                    need_login=args.need_login,
                    login_ready_event=login_ready,
                    login_required_callback=lambda: logger("请在浏览器中完成 ChatGPT 登录。"),
                    login_confirmation_callback=lambda: True,
                    attachment_web_link_callback=lambda: args.attachment_web_link,
                    logger=logger,
                    image_output_dir=target / "images",
                    image_reference_base=target,
                    document_output_dir=target / "documents",
                    document_reference_base=target,
                    browser_profile_root=args.profile.resolve(),
                )
                payload = asdict(result)
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
                if not args.skip_summary:
                    bundle = generate_output_bundle(
                        result.messages,
                        {"raw": False, "normal": True, "simple": True, "detailed": True},
                        target,
                        project_dir=ROOT,
                        api_keys=api_keys,
                        result_cache_dir=args.output / "summary_cache",
                        source_platform="ChatGPT",
                        source_name="export.md",
                        source_dir=target,
                        progress=logger,
                    )
                    record["outputs"] = [
                        path.relative_to(args.output).as_posix() for path in bundle.saved_files
                    ]
                logger(
                    f"完成：{record['messages']} 条消息，{record['images']} 张图片，"
                    f"{record['documents']} 个文档；错误 {result.error}；警告 {result.warnings}"
                )
            except Exception as error:
                record["exception"] = f"{type(error).__name__}: {error}"
                (target / "error.txt").write_text(record["exception"], encoding="utf-8")
                logger(f"异常：{record['exception']}")
            record["elapsed"] = time.perf_counter() - started
            manifest.append(record)
            (args.output / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )


if __name__ == "__main__":
    asyncio.run(main())
