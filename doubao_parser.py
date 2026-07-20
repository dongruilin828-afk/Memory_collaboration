import sys
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from rich.console import Console
from rich.panel import Panel

console = Console()

async def fetch_chat_content(url):
    console.print(f"[bold cyan]正在加载页面:[/bold cyan] {url}")
    async with async_playwright() as p:
        # 启动无头浏览器，使用系统自带的 Edge，避免下载内核失败
        browser = await p.chromium.launch(headless=True, channel="msedge")
        page = await browser.new_page()
        try:
            # 访问指定的 URL
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # 等待前端框架 (如 React/Vue) 渲染对话数据
            console.print("[dim]正在等待动态内容渲染...[/dim]")
            try:
                await page.wait_for_selector(".message-item", state="attached", timeout=10000)
            except Exception:
                console.print("[dim]提示: 等待动态节点超时，可能网页结构有所变化。[/dim]")
            await page.wait_for_timeout(3000) 
            
            # 获取渲染后的完整 HTML
            html = await page.content()
            return html
        except Exception as e:
            console.print(f"[bold red]加载页面时发生错误:[/bold red] {e}")
            return None
        finally:
            await browser.close()

def parse_and_display(html):
    if not html:
        return
    
    # 无论成功与否，保留一份供调试的本地快照
    with open("debug_last_fetch.html", "w", encoding="utf-8") as f:
        f.write(html)
        
    soup = BeautifulSoup(html, 'html.parser')
    console.print("[bold green]✅ 页面加载完毕，正在解析对话内容...[/bold green]\n")
    
    # 移除无用标签
    for script_or_style in soup(['script', 'style', 'noscript', 'svg', 'button']):
        script_or_style.decompose()

    # 精确提取：查找所有带有 message-item 类的聊天块
    message_items = soup.find_all('div', class_='message-item')
    
    parsed_messages = []
    if message_items:
        for msg in message_items:
            classes = msg.get('class', [])
            text = msg.get_text(separator='\n', strip=True)
            
            clean_lines = []
            for line in text.split('\n'):
                line = line.strip()
                if line not in ["复制", "重新生成", "点赞", "踩", "分享", "已采纳", "查看更多", "编辑", "朗读"] and len(line) > 0:
                    clean_lines.append(line)
            
            clean_text = '\n'.join(clean_lines)
            if not clean_text:
                continue
                
            is_user = 'justify-end' in classes
            parsed_messages.append({
                'role': 'User' if is_user else 'AI',
                'content': clean_text
            })
    else:
        # 降级方案：如果没有找到 message-item，尝试按块提取
        console.print("[dim]未能找到标志性的 message-item 类，启用降级提取模式...[/dim]")
        text_content = soup.get_text(separator='\n', strip=True)
        lines = text_content.split('\n')
        
        current_block = []
        is_user = True
        
        for line in lines:
            line = line.strip()
            if len(line) < 2 or line in ["复制", "重新生成", "点赞", "踩", "分享", "已采纳", "查看更多", "编辑", "朗读"]:
                continue
                
            # 简单的角色切换启发式（如果遇到常见的AI回答开头，或者固定句式）
            if line.startswith("回答") or line.startswith("好的") or line.startswith("字数") or line.endswith("字以内)"):
                 if current_block:
                     parsed_messages.append({'role': 'User' if is_user else 'AI', 'content': '\n'.join(current_block)})
                     current_block = []
                     is_user = not is_user
            current_block.append(line)
            
        if current_block:
            parsed_messages.append({'role': 'User' if is_user else 'AI', 'content': '\n'.join(current_block)})

    if not parsed_messages:
        console.print("[bold red]未能提取到有效对话内容。网页快照已保存到 debug_last_fetch.html，供排查。[/bold red]")
        return

    console.print(f"[dim]共提取到 {len(parsed_messages)} 条对话交互：[/dim]\n")
    
    for item in parsed_messages:
        if item['role'] == 'User':
            console.print(Panel(item['content'], title="[bold blue]👤 用户 / 提问[/bold blue]", border_style="blue", title_align="right"))
        else:
            console.print(Panel(item['content'], title="[bold magenta]🤖 豆包 / 回答[/bold magenta]", border_style="magenta", title_align="left"))

async def main():
    console.print(Panel.fit("[bold yellow]🚀 AI 记忆协同管理工具 - 对话提取与可视化工具 (V0.1)[/bold yellow]", border_style="green"))
    console.print("本程序使用 Playwright 抓取动态渲染的网页，并使用 Rich 在终端进行美化输出。\n")
    
    url = input("请输入豆包 (或其它AI) 的分享链接 (例如 https://...): ").strip()
    if not url:
        console.print("[bold red]链接不能为空，程序退出。[/bold red]")
        sys.exit(1)
        
    html = await fetch_chat_content(url)
    parse_and_display(html)
    
    console.print("\n[bold green]处理完成！[/bold green]")
    console.print("[dim]注意：这只是一个基础的文本提取版本。后续有更清晰的 DOM 结构后，可实现精准的用户与AI对话分离。[/dim]")

if __name__ == "__main__":
    asyncio.run(main())
