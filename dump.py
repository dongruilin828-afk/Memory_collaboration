import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel='msedge')
        page = await browser.new_page()
        await page.goto('https://www.doubao.com/thread/x6a706cbf05c6889690a5b1aa9838ef84', wait_until='networkidle')
        await page.wait_for_timeout(3000)
        html = await page.content()
        with open('dump.html', 'w', encoding='utf-8') as f:
            f.write(html)
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
