"""对已有 AI 对话 Markdown 执行 Gemini 分层总结。"""

import argparse
import sys
from pathlib import Path

from rich.console import Console

from .gemini_summarizer import (
    GeminiSummaryError,
    SummaryConfig,
    load_exported_markdown,
    safe_error_message,
    summarize_conversation,
)
from .project_paths import PROJECT_ROOT


console = Console()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用已配置模型对导出的 AI 对话进行多模态分层总结。"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="AI_memory_export.md",
        help="待总结的 Markdown，默认 AI_memory_export.md"
    )
    parser.add_argument(
        "--provider",
        choices=("gemini", "siliconflow"),
        help="总结后端；默认读取 SUMMARY_PROVIDER 或使用 Gemini"
    )
    parser.add_argument(
        "--model",
        help="临时覆盖总结模型"
    )
    parser.add_argument(
        "--json-output",
        help="结构化 JSON 输出路径；默认保存到 results/summary/源文件名_result.json"
    )
    parser.add_argument(
        "--markdown-output",
        help="可读 Markdown 输出路径；默认保存到 results/summary/源文件名_summary.md"
    )
    parser.add_argument(
        "--include-details",
        action="store_true",
        help="在 Markdown 末尾附加精简的细节记忆；默认不附加"
    )
    return parser


def _resolve_from_project(project_dir: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_dir / path


def main() -> int:
    args = build_argument_parser().parse_args()
    project_dir = PROJECT_ROOT
    input_path = _resolve_from_project(project_dir, args.input).resolve()

    try:
        if not input_path.is_file():
            raise GeminiSummaryError(
                f"找不到输入文件：{input_path}"
            )

        messages = load_exported_markdown(input_path)
        config = SummaryConfig.from_env(
            model_override=args.model,
            provider_override=args.provider
        )
        console.print(
            f"已读取 {len(messages)} 条消息，准备调用 "
            f"{config.provider}/{config.model}。",
            style="cyan"
        )
        summarize_conversation(
            messages=messages,
            project_dir=project_dir,
            source_dir=input_path.parent,
            source_name=input_path.name,
            output_json=(
                _resolve_from_project(project_dir, args.json_output)
                if args.json_output else None
            ),
            output_markdown=(
                _resolve_from_project(project_dir, args.markdown_output)
                if args.markdown_output else None
            ),
            config=config,
            include_details=args.include_details,
            progress=lambda message: console.print(
                message, style="dim"
            )
        )
        console.print("分层总结完成。", style="bold green")
        return 0
    except Exception as error:
        console.print(
            f"总结失败：{safe_error_message(error)}",
            style="bold red"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
