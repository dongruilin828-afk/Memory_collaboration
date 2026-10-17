"""Execute the production authentication probe against local Chromium routes.

All requests are fulfilled in memory; no login token or conversation is read.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gui.service import _chatgpt_session_is_authenticated
from playwright.async_api import async_playwright


async def verify(output):
    records = []
    url = "https://chatgpt.com/c/offline-auth-fixture"
    cases = [
        ("session_rejected", 401, {}, 200, False),
        ("token_absent", 200, {}, 200, False),
        ("conversation_forbidden", 200, {"accessToken": "offline-test-token"}, 403, False),
        ("conversation_authorized", 200, {"accessToken": "offline-test-token"}, 200, True),
        ("alternate_token_key", 200, {"access_token": "offline-test-token"}, 200, True),
    ]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for name, session_status, session, detail_status, expected in cases:
                context = await browser.new_context()
                requests = []

                async def route_request(route):
                    path = route.request.url.removeprefix("https://chatgpt.com")
                    requests.append(path)
                    if path == "/api/auth/session":
                        await route.fulfill(status=session_status, json=session)
                    elif path == "/backend-api/conversation/offline-auth-fixture":
                        assert route.request.headers.get("authorization") == "Bearer offline-test-token"
                        await route.fulfill(status=detail_status, json={})
                    elif path == "/c/offline-auth-fixture":
                        await route.fulfill(content_type="text/html", body="<html>fixture</html>")
                    else:
                        await route.abort()

                await context.route("**/*", route_request)
                page = await context.new_page()
                await page.goto(url)
                actual = await _chatgpt_session_is_authenticated(page, url)
                records.append({"case": name, "expected": expected, "actual": actual,
                                "requests": requests, "passed": actual == expected})
                await context.close()
        finally:
            await browser.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    assert all(row["passed"] for row in records), records
    print(f"Chromium authentication fixtures passed: {len(records)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    asyncio.run(verify(parser.parse_args().output))
