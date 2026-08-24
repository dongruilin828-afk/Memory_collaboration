"""让冻结后的 Playwright 只使用分发包内置浏览器。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


bundle_root = Path(getattr(sys, "_MEIPASS", Path.cwd())).resolve()
browser_root = bundle_root / "playwright-browsers"
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_root)
os.environ["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] = "1"
os.environ["AI_MEMORY_BROWSER_MODE"] = "full"
