"""Capture links with one logged-in browser and a bounded capture queue."""

import argparse
import asyncio
import json
from pathlib import Path

from gui.batch_capture import capture_links
from scripts.project_paths import BROWSER_USER_DATA_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--links", type=Path, required=True, help="UTF-8 text file, one HTTPS conversation URL per line")
    parser.add_argument("--output", type=Path, required=True, help="New or empty result directory")
    parser.add_argument("--profile", type=Path, default=BROWSER_USER_DATA_DIR, help="Existing automation login profile")
    args = parser.parse_args()
    try:
        records = asyncio.run(capture_links(
            args.links.read_text(encoding="utf-8-sig").splitlines(), args.output,
            browser_profile_root=args.profile,
            progress=lambda index, total, message: print(f"[{index}/{total}] {message}", flush=True),
        ))
    except KeyboardInterrupt:
        print("已停止；已完成和未完成项见结果目录的 manifest.json。")
        return 130
    except Exception as error:
        print(f"批量抓取失败：{error}")
        return 1
    print(json.dumps({state: sum(item["status"] == state for item in records)
                      for state in ("completed", "failed", "cancelled")}, ensure_ascii=False))
    return int(any(item["status"] != "completed" or item["warnings"] for item in records))


if __name__ == "__main__":
    raise SystemExit(main())
