"""人工审查后 Gemini 复测；调用实际抓取流水线，每例新建目录以保留旧结果。"""
import argparse
import asyncio
import hashlib
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui.service import fetch_chat_pipeline, generate_raw_markdown

CASES = {
    "01": "https://share.gemini.google/pjqqn6qvUB6M",
    "02": "https://gemini.google.com/app/9aa52a89087a7fdc",
    "09": "https://share.gemini.google/YHIhw3SCWFZ7",
    "13": "https://share.gemini.google/N3NeBQVhFWIT",
    "14": "https://gemini.google.com/gem/801fad40429f/058c89ea8d4f09b5",
    "15": "https://share.gemini.google/YINsLdHDRoWg",
    "16": "https://gemini.google.com/gem/801fad40429f/bf49992eb84f9bb3",
}

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--suffix", default="fixed")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for case in args.cases:
        target = args.output / f"{case}_{args.suffix}"
        target.mkdir(exist_ok=False)
        started = time.perf_counter()
        with (target / "run.log").open("w", encoding="utf-8") as log:
            def logger(message):
                log.write(message + "\n")
                log.flush()
                print(f"[{case}] {message}", flush=True)
            logger(f"开始 {CASES[case]}")
            try:
                result = await fetch_chat_pipeline(
                    CASES[case], logger=logger,
                    image_output_dir=target / "images", image_reference_base=target,
                    document_output_dir=target / "documents", document_reference_base=target,
                    browser_profile_root=Path(__file__).resolve().parents[1] / ".browser_user_data",
                )
                payload = asdict(result)
                (target / "snapshot.html").write_text(payload.pop("html") or "", encoding="utf-8")
                payload.update(url=CASES[case], elapsed=time.perf_counter() - started)
                payload["files"] = {
                    path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for folder in ("images", "documents") for path in (target / folder).glob("*")
                    if path.is_file()
                }
                (target / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                if result.messages:
                    generate_raw_markdown(result.messages, target / "export.md")
                logger(f"结束：{len(result.messages)} 条消息；{len(set(result.image_map.values()))} 张图片；{len(set(result.document_map.values()))} 个文档；错误 {result.error}；警告 {result.warnings}")
            except Exception as error:
                logger(f"异常：{type(error).__name__}: {error}")
                (target / "error.txt").write_text(str(error), encoding="utf-8")

if __name__ == "__main__":
    asyncio.run(main())
