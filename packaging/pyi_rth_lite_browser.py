"""配置冻结后的轻量版只调用用户已安装的系统浏览器。"""

from __future__ import annotations

import os


os.environ["AI_MEMORY_BROWSER_MODE"] = "lite"
os.environ["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] = "1"
os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
