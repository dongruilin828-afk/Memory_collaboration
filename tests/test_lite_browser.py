"""轻量版浏览器选择与回退测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gui.service import (
    BROWSER_MODE_ENV,
    browser_channel_candidates,
    launch_browser_context,
)


class FakeChromium:
    def __init__(self, failures=()):
        self.failures = set(failures)
        self.calls = []

    async def launch_persistent_context(self, **kwargs):
        self.calls.append(kwargs)
        channel = kwargs["channel"]
        if channel in self.failures:
            raise RuntimeError(f"sensitive failure from {channel}")
        return object()


class FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium


class LiteBrowserSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def _launch(self, chromium, mode):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {BROWSER_MODE_ENV: mode}):
                return await launch_browser_context(
                    FakePlaywright(chromium),
                    headless=True,
                    viewport={"width": 1280, "height": 720},
                    no_viewport=False,
                    profile_root=Path(temp_dir),
                )

    def test_full_variant_still_uses_only_bundled_chromium(self):
        with patch.dict(os.environ, {BROWSER_MODE_ENV: "full"}):
            self.assertEqual(browser_channel_candidates(), ("chromium",))

    def test_lite_variant_declares_edge_then_chrome(self):
        with patch.dict(os.environ, {BROWSER_MODE_ENV: "lite"}):
            self.assertEqual(
                browser_channel_candidates(),
                ("msedge", "chrome"),
            )

    async def test_lite_prefers_edge(self):
        chromium = FakeChromium()
        _context, channel = await self._launch(chromium, "lite")

        self.assertEqual(channel, "msedge")
        self.assertEqual(
            [call["channel"] for call in chromium.calls],
            ["msedge"],
        )
        self.assertTrue(
            chromium.calls[0]["user_data_dir"].endswith("msedge")
        )

    async def test_lite_falls_back_to_chrome(self):
        chromium = FakeChromium(failures={"msedge"})
        _context, channel = await self._launch(chromium, "lite")

        self.assertEqual(channel, "chrome")
        self.assertEqual(
            [call["channel"] for call in chromium.calls],
            ["msedge", "chrome"],
        )
        self.assertTrue(
            chromium.calls[1]["user_data_dir"].endswith("chrome")
        )

    async def test_lite_reports_full_download_without_leaking_errors(self):
        chromium = FakeChromium(failures={"msedge", "chrome"})
        with self.assertRaisesRegex(
            RuntimeError,
            "请下载安装其中一个浏览器，或下载全量版",
        ) as raised:
            await self._launch(chromium, "lite")

        self.assertNotIn("sensitive failure", str(raised.exception))
