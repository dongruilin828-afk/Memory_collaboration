"""对已抓取的 Gemini 结果运行三种总结，并与 Gemini_Right 对照。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.credential_store import WindowsCredentialStore
from gui.service import generate_output_bundle
from scripts.gemini_summarizer import load_exported_markdown


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def asset_hashes(root: Path, folder: str) -> list[str]:
    target = root / folder
    return sorted(sha256(path) for path in target.glob("*") if path.is_file())


def normalized_markdown(text: str) -> str:
    text = re.sub(r"(?<=\]\()[^)]*(images|documents)/[^)]+", r"\1/ASSET", text)
    text = re.sub(r"```(?:text)?\s*", "", text)
    text = text.replace("```", "")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def broken_local_links(markdown: Path) -> list[str]:
    refs = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", markdown.read_text(encoding="utf-8"))
    broken = []
    for ref in refs:
        ref = ref.split(" ", 1)[0].strip("<>")
        if ref.startswith(("http://", "https://", "#")):
            continue
        if "/" not in ref and "\\" not in ref and not Path(ref).suffix:
            continue
        if not (markdown.parent / ref).resolve().is_file():
            broken.append(ref)
    return broken


def matching_case(root: Path, number: str) -> Path | None:
    matches = sorted(path for path in root.glob(f"{number}*") if path.is_dir())
    return matches[0] if matches else None


def summarize_cases(output: Path, keys: dict[str, str]) -> dict[str, dict]:
    statuses = {}
    cache = output / "_summary_cache"
    for case in sorted(path for path in output.glob("*_capture") if path.is_dir()):
        export = case / "export.md"
        if not export.is_file():
            statuses[case.name] = {"status": "跳过", "error": "缺少 export.md"}
            continue
        summary_dir = case / "summaries"
        expected_summaries = [
            summary_dir / "AI_memory_summary.md",
            summary_dir / "AI_memory_simple.md",
            summary_dir / "AI_memory_detailed_summary.md",
        ]
        if all(path.is_file() for path in expected_summaries):
            statuses[case.name] = {
                "status": "成功",
                "files": [path.relative_to(case).as_posix() for path in expected_summaries],
                "log": ["三种总结文件已存在，跳过重复生成。"],
            }
            continue
        logs = []
        try:
            messages = load_exported_markdown(export)
            bundle = generate_output_bundle(
                messages,
                {"raw": False, "normal": True, "simple": True, "detailed": True},
                summary_dir,
                output_filename="AI_memory.md",
                api_keys=keys,
                result_cache_dir=cache,
                source_platform="Gemini",
                source_name=export.name,
                source_dir=case,
                progress=lambda message, name=case.name: (logs.append(message), print(f"[{name}] {message}", flush=True)),
            )
            statuses[case.name] = {
                "status": "成功",
                "files": [path.resolve().relative_to(case.resolve()).as_posix() for path in bundle.saved_files],
                "log": logs,
            }
        except Exception as error:
            statuses[case.name] = {
                "status": "失败",
                "error": f"{type(error).__name__}: {error}",
                "log": logs,
            }
        (output / "summary_status.json").write_text(
            json.dumps(statuses, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return statuses


def compare_cases(output: Path, right: Path, summary_status: dict[str, dict]) -> list[dict]:
    rows = []
    for index in range(1, 23):
        number = f"{index:02d}"
        actual = matching_case(output, number)
        expected = matching_case(right, number)
        row = {"case": number, "actual": actual.name if actual else None, "expected": expected.name if expected else None}
        if not actual or not expected:
            row["issue"] = "缺少本轮结果" if not actual else "缺少正确答案"
            rows.append(row)
            continue
        actual_md, expected_md = actual / "export.md", expected / "export.md"
        if not actual_md.is_file() or not expected_md.is_file():
            row["issue"] = "缺少 export.md"
            rows.append(row)
            continue
        actual_text = actual_md.read_text(encoding="utf-8")
        expected_text = expected_md.read_text(encoding="utf-8")
        result_path = actual / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
        row.update(
            messages=len(result.get("messages") or []),
            error=result.get("error"),
            warnings=result.get("warnings") or [],
            markdown_exact=actual_text == expected_text,
            text_equivalent=normalized_markdown(actual_text) == normalized_markdown(expected_text),
            images_equal=asset_hashes(actual, "images") == asset_hashes(expected, "images"),
            documents_equal=asset_hashes(actual, "documents") == asset_hashes(expected, "documents"),
            actual_images=len(asset_hashes(actual, "images")),
            expected_images=len(asset_hashes(expected, "images")),
            actual_documents=len(asset_hashes(actual, "documents")),
            expected_documents=len(asset_hashes(expected, "documents")),
            broken_links=broken_local_links(actual_md),
            summaries=summary_status.get(actual.name, {}).get("status", "未运行"),
            summary_error=summary_status.get(actual.name, {}).get("error"),
        )
        issues = []
        if row["error"]:
            issues.append(f"抓取错误：{row['error']}")
        if row["warnings"]:
            issues.append("抓取警告：" + "；".join(row["warnings"]))
        if not row["text_equivalent"]:
            issues.append("正文与正确答案不一致")
        if not row["images_equal"]:
            issues.append("图片集合不一致")
        if not row["documents_equal"]:
            issues.append("文档集合不一致")
        if row["broken_links"]:
            issues.append(f"存在 {len(row['broken_links'])} 个失效本地引用")
        if row["summaries"] != "成功":
            issues.append("三种总结失败")
        row["issue"] = "；".join(issues) or "无"
        rows.append(row)
    return rows


def write_report(output: Path, rows: list[dict]) -> None:
    ok = sum(row.get("issue") == "无" for row in rows)
    lines = [
        "# Gemini 全量抓取与三种总结验证报告", "",
        f"- 测试条目：{len(rows)}", f"- 无问题：{ok}", f"- 有问题：{len(rows) - ok}",
        "- 三种总结：普通版、极简版、详细版", "",
        "| 编号 | 消息 | 图片 本轮/正确 | 文档 本轮/正确 | Markdown 完全一致 | 正文等价 | 三种总结 | 问题 |",
        "| --- | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['case']} | {row.get('messages', '-')} | "
            f"{row.get('actual_images', '-')}/{row.get('expected_images', '-')} | "
            f"{row.get('actual_documents', '-')}/{row.get('expected_documents', '-')} | "
            f"{'是' if row.get('markdown_exact') else '否'} | "
            f"{'是' if row.get('text_equivalent') else '否'} | "
            f"{row.get('summaries', '-')} | {row.get('issue', '未知')} |"
        )
    (output / "Gemini全量验证报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output / "comparison.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    args = parser.parse_args()
    keys = WindowsCredentialStore().load_api_keys()
    statuses = summarize_cases(args.output, keys)
    rows = compare_cases(args.output, args.right, statuses)
    write_report(args.output, rows)
    print(f"完成：{sum(row['issue'] == '无' for row in rows)}/{len(rows)} 项无问题")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
