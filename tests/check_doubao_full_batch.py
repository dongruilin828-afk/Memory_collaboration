"""Check every Doubao URL and its capture/summary outputs; never call an API."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.gemini_summarizer import messages_fingerprint

SOURCES = (
    "tests/tests.txt", "tests/manual_doubao_review.py", "gui/app.py", "gui/service.py",
    "scripts/providers/doubao.py", "scripts/gemini_summarizer.py",
    "scripts/simple_summarizer.py", "scripts/doubao_media.py", "scripts/summary_grounding.py",
)


def inventory():
    text = (ROOT / "tests/tests.txt").read_text(encoding="utf-8-sig")
    section = text.split("豆包：", 1)[1].split("DeepSeek：", 1)[0]
    urls = re.findall(r"https?://[^\s<>]+", section)
    if not urls or any(urlsplit(u).hostname != "www.doubao.com" for u in urls):
        raise ValueError("豆包清单为空或包含非豆包网址")
    from tests.manual_doubao_review import CASES
    if CASES != urls or len(set(urls)) != len(urls):
        raise ValueError("运行脚本的 URL 覆盖与原清单不一致，或清单中有重复网址")
    return [{"case": f"{i:02d}", "kind": "分享" if "/thread/" in u else "网页", "url": u}
            for i, u in enumerate(urls, 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true", help="冻结清单和代码指纹，不抓取、不总结")
    args = parser.parse_args()
    output = args.output.resolve()
    cases = inventory()
    fingerprints = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}
    frozen_path = output / "batch_inventory.json"
    if args.prepare:
        if output.exists():
            parser.error(f"准备新批次时目录必须尚不存在：{output}")
        output.mkdir(parents=True)
        frozen_path.write_text(json.dumps({"cases": cases, "source_sha256": fingerprints}, ensure_ascii=False, indent=2), encoding="utf-8")
        rows = ["# 豆包本批测试清单", "", "| 编号 | 入口 | 链接 |", "| --- | --- | --- |"]
        rows += [f"| {c['case']} | {c['kind']} | {c['url']} |" for c in cases]
        (output / "测试清单.md").write_text("\n".join(rows)+"\n", encoding="utf-8")
        print(f"本批清单：{len(cases)} 条，分享 {sum(c['kind']=='分享' for c in cases)} 条，网页 {sum(c['kind']=='网页' for c in cases)} 条。")
        print(f"结果目录：{output}")
        return
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig")) if manifest_path.is_file() else []
    rows = []
    for case in cases:
        target = output / case["case"]
        matches = [r for r in manifest if r.get("url") == case["url"]]
        errors, warnings = [], []
        if len(matches) != 1 or matches[0].get("case") != case["case"]:
            errors.append("清单记录缺失、重复或编号错误")
        elif matches[0].get("error") or matches[0].get("exception"):
            errors.append(matches[0].get("exception") or matches[0]["error"])
        if matches:
            warnings.extend(matches[0].get("warnings") or [])
        expected = ("export.md", "result.json", "snapshot.html", "AI_memory_summary.md",
                    "AI_memory_simple.md", "AI_memory_detailed_summary.md",
                    "AI_memory_result.json", "AI_memory_detailed_result.json")
        missing = [name for name in expected if not (target/name).is_file() or not (target/name).stat().st_size]
        if missing:
            errors.append("缺少产物："+"、".join(missing))
        try:
            captured = json.loads((target / "result.json").read_text(encoding="utf-8"))
            if not captured.get("messages"):
                errors.append("抓取消息为空")
            if captured.get("url") != case["url"]:
                errors.append("抓取结果 URL 与编号不一致")
            if not missing:
                summary = json.loads((target / "AI_memory_result.json").read_text(encoding="utf-8"))
                detailed = json.loads((target / "AI_memory_detailed_result.json").read_text(encoding="utf-8"))
                if summary != detailed:
                    errors.append("普通和详细结构化结果不一致")
                if summary.get("conversation", {}).get("source_fingerprint") != messages_fingerprint(captured["messages"]):
                    errors.append("总结来源指纹与本批抓取不符")
                warnings.extend(summary.get("processing", {}).get("warnings") or [])
                warnings.extend(f"媒体 {m.get('media_id')}：{m.get('status')}"
                                for m in summary.get("media", []) if m.get("status") != "described")
        except (OSError, ValueError, KeyError) as error:
            errors.append(f"产物读取失败：{type(error).__name__}")
        rows.append({**case, "errors": errors, "warnings": list(dict.fromkeys(warnings))})
    changed = [name for name, digest in fingerprints.items() if frozen["source_sha256"].get(name) != digest]
    complete = not changed and frozen["cases"] == cases and len(manifest) == len(cases) and not any(r["errors"] for r in rows)
    report = {"expected_links": len(cases), "manifest_records": len(manifest),
              "file_outputs_complete": complete, "source_files_changed": changed,
              "warning_cases": [r["case"] for r in rows if r["warnings"]], "cases": rows,
              "note": "仅核对链接覆盖、产物与来源，不代替网页内容及总结事实审查。"}
    (output / "coverage_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"应测试 {len(cases)} 条；记录 {len(manifest)} 条；产物与来源齐全：{complete}；有提醒 {len(report['warning_cases'])} 项。")
    for row in rows:
        if row["errors"]:
            print(f"[{row['case']}] "+"；".join(row["errors"]))
    print(f"检查文件：{output / 'coverage_check.json'}")
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
