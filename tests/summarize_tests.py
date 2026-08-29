"""批量总结 tests.txt 对应的现有 results/export，不重新抓取网页。"""

from __future__ import annotations

import argparse
import json
import os
import time
import sys
from pathlib import Path

from rich.console import Console

from scripts.gemini_summarizer import (
    SCHEMA_VERSION,
    SummaryConfig,
    create_gateway,
    default_summary_paths,
    load_exported_markdown,
    messages_fingerprint,
    renormalize_result,
    safe_error_message,
    summarize_conversation,
    write_summary_outputs,
)
from scripts.project_paths import (
    EXPORT_DIR,
    PROJECT_ROOT,
    SUMMARY_DETAILED_DIR,
    SUMMARY_DIR,
)
from .run_tests import clean_filename, read_tests


PROJECT_DIR = PROJECT_ROOT
RESULTS_DIR = EXPORT_DIR
DETAILED_SUMMARY_DIR = SUMMARY_DETAILED_DIR
console = Console()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "调用已配置模型批量总结 tests.txt 对应的现有 results/export，"
            "不重新打开浏览器。"
        )
    )
    parser.add_argument(
        "--provider",
        choices=("gemini", "siliconflow", "deepseek"),
        help="总结后端；默认读取 SUMMARY_PROVIDER 或使用 Gemini"
    )
    parser.add_argument(
        "--model",
        help="临时覆盖总结模型"
    )
    parser.add_argument(
        "--render-existing",
        action="store_true",
        help="不调用 API；重新规范化已有结果、生成两种 Markdown 并刷新报告"
    )
    parser.add_argument(
        "--include-details",
        action="store_true",
        help="在每份 Markdown 末尾附加精简的细节记忆；默认不附加"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="跳过已有同模型完整结果，仅续跑缺失或未完成任务"
    )
    return parser


def expected_result_files() -> list[Path]:
    return [
        RESULTS_DIR / f"{clean_filename(title)}.md"
        for title, _link in read_tests()
    ]


def valid_conversation(messages: list[dict[str, str]]) -> bool:
    roles = {message.get("role") for message in messages}
    return "User" in roles and "AI" in roles


def write_report(
    rows: list[tuple[str, str, str]],
    include_details: bool = False,
    model: str = "",
    provider: str = ""
) -> Path:
    output_dir = DETAILED_SUMMARY_DIR if include_details else SUMMARY_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "批量总结报告.md"
    lines = [
        "# 批量总结报告",
        "",
        f"- 本次请求后端：{provider or '未记录'}",
        f"- 本次请求模型：{model or '未记录'}",
        "- 各文件实际模型：以对应结果 JSON 与 Markdown 页眉为准；"
        "使用其他免费模型补跑时，报告行会单独注明。",
        "- 报告性质：仅记录批处理执行状态，不代表语义内容已经人工验收。",
        "",
        "| 原始结果 | 状态 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, status, detail in rows:
        lines.append(f"| {name} | {status} | {detail} |")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    args = build_argument_parser().parse_args()
    config = SummaryConfig.from_env(
        model_override=args.model,
        provider_override=args.provider
    )
    gateway = None if args.render_existing else create_gateway(config)
    result_files = expected_result_files()
    rows: list[tuple[str, str, str]] = []
    success_count = 0
    skipped_count = 0
    failure_count = 0
    request_interval = max(
        0,
        int(os.getenv("GEMINI_BATCH_INTERVAL_SECONDS", "15"))
    )
    previous_api_task = False

    output_dir = (
        DETAILED_SUMMARY_DIR if args.include_details else SUMMARY_DIR
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    for cache_path in output_dir.glob("*_progress.tmp"):
        # 当前缓存名由输出 JSON 决定（*_result_progress.tmp），模型与 schema
        # 已写入指纹。这里只清理旧版把模型名放进文件名的遗留缓存。
        if not cache_path.name.endswith("_result_progress.tmp"):
            try:
                cache_path.unlink()
            except OSError:
                pass

    console.print(
        f"共发现 {len(result_files)} 个测试任务，使用 "
        f"{config.provider}/{config.model}。",
        style="bold cyan"
    )
    for index, input_path in enumerate(result_files, start=1):
        console.print(
            f"\n[{index}/{len(result_files)}] {input_path.name}",
            style="bold"
        )
        if not input_path.is_file():
            skipped_count += 1
            rows.append((input_path.name, "跳过", "results/export 中没有该文件"))
            console.print("跳过：结果文件不存在。", style="yellow")
            continue

        try:
            messages = load_exported_markdown(input_path)
            if not valid_conversation(messages):
                skipped_count += 1
                rows.append((
                    input_path.name,
                    "跳过",
                    "未同时提取到用户消息和 AI 回答"
                ))
                console.print(
                    "跳过：未同时提取到用户消息和 AI 回答。",
                    style="yellow"
                )
                continue

            json_path, markdown_path = default_summary_paths(
                PROJECT_DIR,
                input_path.name,
                include_details=args.include_details
            )
            if args.render_existing:
                normal_json_path, normal_markdown_path = default_summary_paths(
                    PROJECT_DIR, input_path.name, include_details=False
                )
                try:
                    existing = json.loads(
                        normal_json_path.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    existing = {}
                if (
                    existing.get("schema_version") != SCHEMA_VERSION
                    or existing.get("conversation", {}).get(
                        "source_fingerprint"
                    ) != messages_fingerprint(messages)
                ):
                    skipped_count += 1
                    rows.append((
                        input_path.name, "跳过", "没有同 schema、同原文的现有结果"
                    ))
                    continue
                existing = renormalize_result(existing, messages=messages)
                write_summary_outputs(
                    existing, normal_json_path, normal_markdown_path,
                    include_details=False
                )
                detailed_json_path, detailed_markdown_path = default_summary_paths(
                    PROJECT_DIR, input_path.name, include_details=True
                )
                write_summary_outputs(
                    existing, detailed_json_path, detailed_markdown_path,
                    include_details=True
                )
                for existing_path in (json_path, detailed_json_path):
                    try:
                        existing_path.with_name(
                            existing_path.stem + "_progress.tmp"
                        ).unlink()
                    except FileNotFoundError:
                        pass
                success_count += 1
                rows.append((
                    input_path.name, "成功",
                    f"零 API 刷新（{existing.get('model', '未记录')}）"
                ))
                continue
            if args.include_details:
                normal_json_path, _normal_markdown_path = default_summary_paths(
                    PROJECT_DIR, input_path.name, include_details=False
                )
                try:
                    normal_result = json.loads(
                        normal_json_path.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    normal_result = {}
                if (
                    normal_result.get("model")
                    and normal_result.get("schema_version") == SCHEMA_VERSION
                    and normal_result.get("conversation", {}).get(
                        "source_fingerprint"
                    ) == messages_fingerprint(messages)
                ):
                    normal_result = renormalize_result(
                        normal_result, messages=messages
                    )
                    normal_json_path, normal_markdown_path = (
                        default_summary_paths(
                            PROJECT_DIR,
                            input_path.name,
                            include_details=False
                        )
                    )
                    write_summary_outputs(
                        normal_result,
                        normal_json_path,
                        normal_markdown_path,
                        include_details=False
                    )
                    write_summary_outputs(
                        normal_result,
                        json_path,
                        markdown_path,
                        include_details=True
                    )
                    try:
                        json_path.with_name(
                            json_path.stem + "_progress.tmp"
                        ).unlink()
                    except FileNotFoundError:
                        pass
                    success_count += 1
                    rows.append((
                        input_path.name,
                        "成功",
                        f"复用普通版语义结果（{normal_result['model']}）；"
                        f"{markdown_path.name}；"
                        f"{json_path.name}"
                    ))
                    console.print(
                        "已复用普通版语义结果，仅生成带细节展示。",
                        style="green"
                    )
                    continue
            if args.resume and json_path.is_file() and markdown_path.is_file():
                try:
                    existing = json.loads(
                        json_path.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    existing = {}
                if (
                    existing.get("model") == config.model
                    and existing.get("provider", "gemini") == config.provider
                    and existing.get("schema_version") == SCHEMA_VERSION
                ):
                    skipped_count += 1
                    rows.append((
                        input_path.name,
                        "跳过",
                        f"已存在同模型完整结果：{markdown_path.name}"
                    ))
                    console.print(
                        "跳过：已存在同模型完整结果。",
                        style="green"
                    )
                    continue

            if previous_api_task and request_interval:
                console.print(
                    f"为免费层级主动等待 {request_interval} 秒...",
                    style="dim"
                )
                time.sleep(request_interval)
            summarize_conversation(
                messages=messages,
                project_dir=PROJECT_DIR,
                source_dir=input_path.parent,
                source_name=input_path.name,
                config=config,
                gateway=gateway,
                include_details=args.include_details,
                progress=lambda message: console.print(message, style="dim")
            )
            success_count += 1
            previous_api_task = True
            rows.append((
                input_path.name,
                "成功",
                f"{markdown_path.name}；{json_path.name}"
            ))
        except Exception as error:
            previous_api_task = True
            failure_count += 1
            message = safe_error_message(error).replace("|", "\\|")
            rows.append((input_path.name, "失败", message))
            console.print(f"失败：{message}", style="bold red")

    if args.render_existing:
        report_path = write_report(
            rows, include_details=False, model="零 API", provider="零 API"
        )
        write_report(
            rows, include_details=True, model="零 API", provider="零 API"
        )
    else:
        report_path = write_report(
            rows,
            include_details=args.include_details,
            model=config.model,
            provider=config.provider
        )
    console.print(
        f"\n批量总结完成：成功 {success_count}，跳过 {skipped_count}，"
        f"失败 {failure_count}。",
        style="bold green" if failure_count == 0 else "bold yellow"
    )
    console.print(f"报告：{report_path}")
    return 1 if failure_count else 0


if __name__ == "__main__":
    sys.exit(main())
