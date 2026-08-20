"""批量生成只含一个总览段落的极简版总结。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

from rich.console import Console

from gemini_summarizer import (
    SCHEMA_VERSION,
    SummaryConfig,
    create_gateway,
    load_exported_markdown,
    messages_fingerprint,
    safe_error_message,
)
from run_tests import clean_filename, read_tests
from simple_summarizer import (
    SimpleSummaryValidationError,
    build_simple_metadata,
    build_simple_projection,
    generate_simple_overview,
    parse_simple_markdown,
    repair_simple_overview,
    simple_char_limit,
    validate_simple_overview,
    write_simple_markdown,
)


PROJECT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_DIR / "results"
SUMMARY_DIR = PROJECT_DIR / "summary"
SIMPLE_DIR = PROJECT_DIR / "summary_simple"
console = Console()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="复用普通版结构化结果，生成只含总览的极简版总结。"
    )
    parser.add_argument("--provider", choices=("gemini", "siliconflow"))
    parser.add_argument("--model")
    parser.add_argument(
        "--resume", action="store_true", help="跳过已经存在的极简版文件"
    )
    parser.add_argument(
        "--repair-existing",
        action="store_true",
        help="零 API：依据普通版结构化状态重新规范化已有极简文本"
    )
    parser.add_argument(
        "--only",
        action="append",
        help="只运行指定名称；可重复使用，名称可省略 .md 或 _simple.md"
    )
    return parser


def model_candidates(base: SummaryConfig) -> list[SummaryConfig]:
    candidates = [base]
    for model in (
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite"
    ):
        candidate = replace(base, provider="gemini", model=model)
        if (candidate.provider, candidate.model) not in {
            (item.provider, item.model) for item in candidates
        }:
            candidates.append(candidate)
    if os.getenv("Silicon_API_KEY") or os.getenv("SILICONFLOW_API_KEY"):
        candidates.append(replace(
            base,
            provider="siliconflow",
            model=os.getenv(
                "SUMMARY_SIMPLE_SILICON_MODEL",
                "Qwen/Qwen3.5-397B-A17B"
            )
        ))
    return candidates


def main() -> int:
    args = build_argument_parser().parse_args()
    base_config = SummaryConfig.from_env(
        provider_override=args.provider,
        model_override=args.model
    )
    candidates = model_candidates(base_config)
    gateways = {}
    unavailable: set[tuple[str, str]] = set()
    SIMPLE_DIR.mkdir(parents=True, exist_ok=True)
    success = skipped = failed = 0
    last_api_time = 0.0
    interval = max(
        0, int(os.getenv("GEMINI_BATCH_INTERVAL_SECONDS", "15"))
    )

    tasks = [
        (clean_filename(title), RESULTS_DIR / f"{clean_filename(title)}.md")
        for title, _link in read_tests()
    ]
    if args.only:
        requested = {
            Path(value).stem.removesuffix("_simple") for value in args.only
        }
        tasks = [item for item in tasks if item[0] in requested]
    console.print(f"共发现 {len(tasks)} 个任务。", style="bold cyan")
    for index, (name, input_path) in enumerate(tasks, start=1):
        output_path = SIMPLE_DIR / f"{name}_simple.md"
        console.print(f"\n[{index}/{len(tasks)}] {input_path.name}", style="bold")
        if args.resume and output_path.is_file():
            skipped += 1
            console.print("跳过：极简版已存在。", style="green")
            continue
        if not input_path.is_file():
            skipped += 1
            console.print("跳过：原始结果不存在。", style="yellow")
            continue
        try:
            messages = load_exported_markdown(input_path)
        except Exception as error:
            skipped += 1
            console.print(
                f"跳过：{safe_error_message(error)}", style="yellow"
            )
            continue
        if {item.get("role") for item in messages} != {"User", "AI"}:
            skipped += 1
            console.print("跳过：未同时提取到用户消息和 AI 回答。", style="yellow")
            continue
        normal_path = SUMMARY_DIR / f"{name}_result.json"
        try:
            result = json.loads(normal_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            failed += 1
            console.print("失败：缺少有效普通版 JSON。", style="bold red")
            continue
        if (
            result.get("schema_version") != SCHEMA_VERSION
            or result.get("conversation", {}).get("source_fingerprint")
            != messages_fingerprint(messages)
        ):
            failed += 1
            console.print(
                "失败：普通版 JSON 与当前原文或 schema 不匹配。",
                style="bold red"
            )
            continue

        if args.repair_existing:
            if not output_path.is_file():
                failed += 1
                console.print("失败：没有可修复的现有极简版。", style="bold red")
                continue
            raw_text = output_path.read_text(encoding="utf-8")
            raw_overview, saved_metadata = parse_simple_markdown(raw_text)
            projection = build_simple_projection(result, messages)
            overview = repair_simple_overview(raw_overview, projection)
            errors = validate_simple_overview(
                overview, projection, simple_char_limit(len(messages))
            )
            if errors:
                failed += 1
                console.print(
                    "失败：零 API 修复后仍未通过校验：" + "；".join(errors),
                    style="bold red"
                )
                continue
            metadata = build_simple_metadata(
                result,
                provider=saved_metadata.get("provider"),
                model=saved_metadata.get("model")
            )
            write_simple_markdown(output_path, overview, metadata)
            success += 1
            console.print(f"已零 API 刷新：{output_path.name}", style="green")
            continue

        completed = False
        validation_failed = False
        for config in candidates:
            key = (config.provider, config.model)
            if key in unavailable:
                continue
            try:
                if last_api_time and interval:
                    wait = interval - (time.monotonic() - last_api_time)
                    if wait > 0:
                        console.print(
                            f"免费层级等待 {int(wait + 0.999)} 秒...", style="dim"
                        )
                        time.sleep(wait)
                gateway = gateways.get(key)
                if gateway is None:
                    gateway = create_gateway(config)
                    gateways[key] = gateway
                console.print(
                    f"尝试 {config.provider}/{config.model}", style="dim"
                )
                overview = generate_simple_overview(result, messages, gateway)
                last_api_time = time.monotonic()
                metadata = build_simple_metadata(
                    result, provider=config.provider, model=config.model
                )
                write_simple_markdown(output_path, overview, metadata)
                console.print(f"已保存：{output_path.name}", style="green")
                success += 1
                completed = True
                break
            except SimpleSummaryValidationError as error:
                last_api_time = time.monotonic()
                validation_failed = True
                console.print(
                    f"该模型输出未通过极简校验：{error}", style="yellow"
                )
            except Exception as error:
                last_api_time = time.monotonic()
                unavailable.add(key)
                console.print(
                    f"{config.provider}/{config.model} 不可用："
                    f"{safe_error_message(error)}",
                    style="yellow"
                )
        if not completed:
            failed += 1
            detail = "所有模型均未通过校验" if validation_failed else "所有模型均不可用"
            console.print(f"失败：{detail}。", style="bold red")

    console.print(
        f"\n极简总结完成：成功 {success}，跳过 {skipped}，失败 {failed}。",
        style="bold green" if not failed else "bold yellow"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
