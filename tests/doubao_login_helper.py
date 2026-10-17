"""Keep the project's Chromium profile open while its owner signs in to Doubao."""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui.service import launch_browser_context


async def main():
    target_url = "https://www.doubao.com/chat/38441607137483266?channel=xiazais"
    print("正在启动项目专用 Chromium...", flush=True)
    async with async_playwright() as playwright:
        original_launch = playwright.chromium.launch_persistent_context

        async def launch_with_cdp(*args, **options):
            options["args"] = [
                *options.get("args", []),
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=9277",
            ]
            return await original_launch(*args, **options)

        playwright.chromium.launch_persistent_context = launch_with_cdp
        context, _ = await launch_browser_context(
            playwright,
            headless=False,
            viewport=None,
            no_viewport=True,
            profile_root=Path(__file__).resolve().parents[1] / ".browser_user_data",
        )
        playwright.chromium.launch_persistent_context = original_launch
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            print("Chromium 已启动，正在打开豆包会话...", flush=True)
            try:
                await page.goto(
                    target_url, wait_until="domcontentloaded", timeout=15000
                )
            except Exception as error:
                print(f"打开会话暂时失败：{type(error).__name__}", flush=True)
                try:
                    await page.goto(
                        "https://www.doubao.com/",
                        wait_until="domcontentloaded", timeout=15000,
                    )
                except Exception:
                    pass
            verified = False
            while not verified:
                print("请在此 Chromium 中完成登录；准备好后回到终端按 Enter，脚本会核验历史会话。", flush=True)
                await asyncio.to_thread(input)
                for _ in range(3):
                    try:
                        await page.goto(
                            target_url, wait_until="domcontentloaded", timeout=15000
                        )
                    except Exception as error:
                        print(f"重新打开会话失败：{type(error).__name__}", flush=True)
                        continue
                    try:
                        await page.locator(
                            "div[class*='message-list-'] [data-message-id]"
                        ).first.wait_for(state="attached", timeout=12000)
                    except Exception:
                        await page.wait_for_timeout(1500)
                        continue
                    print("历史会话可访问，登录状态已保存：", page.url, flush=True)
                    verified = True
                    break
                if verified:
                    break
                print("仍未读到目标历史会话，当前页面：", page.url, flush=True)
            print("请保持 Chromium 和此 PowerShell 窗口打开，待我完成私有会话核对后通知你关闭。", flush=True)
            await asyncio.to_thread(input, "收到关闭通知后，按 Enter 结束：")
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
