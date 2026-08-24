"""AI 记忆总结工具轻量版入口。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ["AI_MEMORY_BROWSER_MODE"] = "lite"


def main() -> None:
    if "--package-smoke-report" in sys.argv:
        option_index = sys.argv.index("--package-smoke-report")
        try:
            report_path = Path(sys.argv[option_index + 1]).resolve()
        except IndexError:
            raise SystemExit("--package-smoke-report 后必须提供报告路径")
        from gui.lite_package_smoke import run_lite_package_smoke_test

        raise SystemExit(run_lite_package_smoke_test(report_path))

    from gui.app import main as run_gui

    run_gui()


if __name__ == "__main__":
    main()
