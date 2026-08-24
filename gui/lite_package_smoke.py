"""轻量版冻结程序的离线发布自检。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from keyring.backends.Windows import WinVaultKeyring
from playwright.async_api import async_playwright

from gui.service import generate_raw_markdown, launch_browser_context
from scripts.gemini_summarizer import (
    SummaryConfig,
    _render_programming_records,
    create_gateway,
)
from scripts.project_paths import IS_FROZEN, PROJECT_ROOT


async def _check_system_browser() -> dict[str, str]:
    with tempfile.TemporaryDirectory(
        prefix="ai-memory-lite-smoke-"
    ) as profile_dir:
        async with async_playwright() as playwright:
            context, channel = await launch_browser_context(
                playwright,
                headless=True,
                viewport={"width": 1280, "height": 720},
                no_viewport=False,
                profile_root=Path(profile_dir),
            )
            try:
                page = (
                    context.pages[0]
                    if context.pages
                    else await context.new_page()
                )
                await page.set_content(
                    "<title>AI Memory lite package smoke</title>"
                )
                title = await page.title()
                version = context.browser.version if context.browser else ""
            finally:
                await context.close()
    if title != "AI Memory lite package smoke":
        raise RuntimeError("系统浏览器未通过页面渲染检查")
    return {
        "channel": channel,
        "version": version,
    }


def run_lite_package_smoke_test(report_path: Path) -> int:
    report: dict[str, Any] = {
        "ok": False,
        "variant": "lite",
        "frozen": IS_FROZEN,
        "browser_mode": os.getenv("AI_MEMORY_BROWSER_MODE", ""),
        "project_root": str(PROJECT_ROOT),
        "bundle_root": str(Path(getattr(sys, "_MEIPASS", "")).resolve()),
    }
    try:
        if not IS_FROZEN:
            raise RuntimeError("该检查必须从打包后的轻量版 EXE 运行")
        if os.getenv("AI_MEMORY_BROWSER_MODE") != "lite":
            raise RuntimeError("轻量版浏览器模式未生效")

        backend = WinVaultKeyring()
        backend.get_password(
            "AI Memory Summary Lite Package Smoke",
            "nonexistent-read-only-probe",
        )
        report["credential_backend"] = type(backend).__name__
        report["credential_read_probe"] = "ok"

        gateway = create_gateway(
            SummaryConfig(provider="gemini", retries=1),
            api_key="package-smoke-placeholder-not-a-real-key",
        )
        report["summary_gateway"] = type(gateway).__name__

        lines: list[str] = []
        _render_programming_records(lines, [{
            "topic": "轻量版发布自检",
            "code_state": "",
            "bug_or_issue": "",
            "assistant_diagnosis": "",
            "constraints": [],
            "implemented_changes": [],
            "proposed_changes": ["验证系统浏览器"],
            "pending_validation": [],
            "message_ids": [1, 2, 3],
            "implementation_status": "confirmed_by_user",
        }])
        rendered = "\n".join(lines)
        if (
            "已实施修改：无用户确认" in rendered
            or "建议的修改：无" in rendered
        ):
            raise RuntimeError("编程记录字段一致性检查失败")
        report["programming_consistency"] = "ok"

        with tempfile.TemporaryDirectory(
            prefix="ai-memory-lite-output-smoke-"
        ) as temp_dir:
            output = Path(temp_dir) / "raw.md"
            generate_raw_markdown(
                [{"role": "User", "content": "轻量版离线发布自检"}],
                output,
            )
            if "轻量版离线发布自检" not in output.read_text(
                encoding="utf-8"
            ):
                raise RuntimeError("本地导出写入检查失败")
        report["local_export"] = "ok"
        report["browser"] = asyncio.run(_check_system_browser())
        report["ok"] = True
        exit_code = 0
    except Exception as error:
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
        exit_code = 1
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return exit_code
