"""全量验证 tests.txt 中的 DeepSeek 抓取和三种总结。"""
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
SECTION = TEXT.split("deepseek：", 1)[1].split("Gemini：", 1)[0]
CASES = re.findall(r"https://chat\.deepseek\.com/\S+", SECTION)


async def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", nargs="*", type=int)
    parser.add_argument("--skip-summary", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    api_keys = WindowsCredentialStore().load_api_keys()
    manifest = []
    selected = set(args.cases or range(1, len(CASES) + 1))

    for index, url in enumerate(CASES, 1):
        if index not in selected:
            continue
        case = f"{index:02d}"
        target = args.output / case
        target.mkdir()
        started = time.perf_counter()
        with (target / "run.log").open("w", encoding="utf-8") as log:
            def logger(message):
                log.write(message + "\n")
                log.flush()
                print(f"[{case}] {message}", flush=True)

            record = {"case": case, "url": url}
            try:
                result = await fetch_chat_pipeline(
                    url,
                    logger=logger,
                    image_output_dir=target / "images",
                    image_reference_base=target,
                    document_output_dir=target / "documents",
                    document_reference_base=target,
                    browser_profile_root=ROOT / ".browser_user_data",
                )
                payload = asdict(result)
                (target / "snapshot.html").write_text(
                    payload.pop("html") or "", encoding="utf-8"
                )
                payload.update(url=url, elapsed=time.perf_counter() - started)
                payload["files"] = {
                    path.relative_to(target).as_posix(): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for folder in ("images", "documents")
                    for path in (target / folder).glob("*")
                    if path.is_file()
                }
                (target / "result.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
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
                        source_platform="DeepSeek",
                        source_name="export.md",
                        source_dir=target,
                        progress=logger,
                    )
                    record["outputs"] = [
                        path.relative_to(args.output).as_posix()
                        for path in bundle.saved_files
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
