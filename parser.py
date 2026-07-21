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
        # 使用超高视口（10800px），强制 React 将所有虚拟滚动列表中的聊天记录同时渲染到 DOM 中
        page = await browser.new_page(viewport={'width': 1920, 'height': 10800})
        try:
            # 访问指定的 URL
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # 等待前端框架渲染对话数据
            console.print("[dim]正在等待动态内容渲染...[/dim]")
            try:
                # 兼容豆包 (.message-item) 和 ChatGPT ([data-message-author-role])
                await page.wait_for_selector(".message-item, [data-message-author-role]", state="attached", timeout=10000)
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
    
    import os
    import markdownify
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 无论成功与否，保留一份供调试的本地快照
    debug_filename = os.path.join(script_dir, "debug_last_fetch.html")
    with open(debug_filename, "w", encoding="utf-8") as f:
        f.write(html)
        
    soup = BeautifulSoup(html, 'html.parser')
    console.print("[bold green]✅ 页面加载完毕，正在解析对话内容...[/bold green]\n")
    
    parsed_messages = []
    
    # 1. 尝试使用 ChatGPT 解析逻辑
    chatgpt_messages = soup.find_all(attrs={"data-message-author-role": True})
    if chatgpt_messages:
        console.print("[dim]检测到 ChatGPT 分享链接格式，使用专用解析器...[/dim]")
        for msg in chatgpt_messages:
            role = msg.get("data-message-author-role")
            if role == "user":
                text = msg.get_text(separator='\n', strip=True)
                parsed_messages.append({'role': 'User', 'content': text})
            elif role == "assistant":
                # 修复 ChatGPT 嵌套 <pre> 导致 markdownify 生成多重/错误代码块的问题
                for pre in msg.find_all("pre"):
                    if "cm-content" not in pre.get('class', []):
                        inner_pre = pre.find("pre", class_="cm-content")
                        if inner_pre:
                            code_text = inner_pre.get_text()
                            # 构造一个干干净净的标准 <pre><code>，避免 markdownify 被复杂的嵌套标签搞晕
                            new_pre = soup.new_tag("pre")
                            new_code = soup.new_tag("code")
                            new_code.string = code_text
                            new_pre.append(new_code)
                            pre.replace_with(new_pre)
                md_text = markdownify.markdownify(str(msg), heading_style="ATX", strip=['img']).strip()
                parsed_messages.append({'role': 'AI', 'content': md_text})
                
    else:
        # 2. 尝试使用豆包解析逻辑
        for script_or_style in soup(['script', 'style', 'noscript', 'svg', 'button']):
            script_or_style.decompose()
            
        message_items = soup.find_all('div', class_='message-item')
        if message_items:
            console.print("[dim]检测到豆包分享链接格式，使用专用解析器...[/dim]")
            for msg in message_items:
                classes = msg.get('class', [])
                is_user = 'justify-end' in classes
                
                if is_user:
                    text = msg.get_text(separator='\n', strip=True)
                    clean_lines = [line.strip() for line in text.split('\n') if len(line.strip()) > 0 and line.strip() not in ["复制", "重新生成", "点赞", "踩", "分享", "已采纳", "查看更多", "编辑", "朗读"]]
                    if clean_lines:
                        parsed_messages.append({'role': 'User', 'content': '\n'.join(clean_lines)})
                else:
                    md_text = markdownify.markdownify(str(msg), heading_style="ATX", strip=['img']).strip()
                    if md_text:
                        parsed_messages.append({'role': 'AI', 'content': md_text})
        
        else:
            # 3. 降级方案
            console.print("[dim]未能找到标志性的对话类，启用降级提取模式...[/dim]")
            text_content = soup.get_text(separator='\n', strip=True)
            lines = text_content.split('\n')
            current_block = []
            is_user = True
            
            for line in lines:
                line = line.strip()
                if len(line) < 2 or line in ["复制", "重新生成", "点赞", "踩", "分享", "已采纳", "查看更多", "编辑", "朗读"]:
                    continue
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

    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 导出为 Markdown 文件
    export_filename = os.path.join(script_dir, "AI_memory_export.md")
    try:
        with open(export_filename, "w", encoding="utf-8") as f:
            f.write("# AI 对话记忆导出\n\n")
            for item in parsed_messages:
                if item['role'] == 'User':
                    f.write(f"---\n\n### 👤 用户\n\n{item['content']}\n\n")
                else:
                    f.write(f"---\n\n### 🤖 AI 回答\n\n{item['content']}\n\n")
        console.print(f"\n[bold green]🎉 对话记录已成功导出为 Markdown 文件: {export_filename}[/bold green]")
    except Exception as e:
        console.print(f"\n[bold red]保存 Markdown 文件时出错:[/bold red] {e}")

async def main():
    console.print(Panel.fit("[bold yellow]🚀 AI 记忆协同管理工具 - 对话提取与可视化工具 (V0.1)[/bold yellow]", border_style="green"))
    console.print("本程序使用 Playwright 抓取动态渲染的网页，并使用 Rich 在终端进行美化输出。\n")
    
    url = input("请输入 AI 的分享链接 (例如 https://...): ").strip()
    if not url:
        console.print("[bold red]链接不能为空，程序退出。[/bold red]")
        sys.exit(1)
        
    html = await fetch_chat_content(url)
    parse_and_display(html)
    
    console.print("\n[bold green]处理完成！[/bold green]")
    console.print("[dim]注意：这只是一个基础的文本提取版本。后续有更清晰的 DOM 结构后，可实现精准的用户与AI对话分离。[/dim]")

if __name__ == "__main__":
    asyncio.run(main())
