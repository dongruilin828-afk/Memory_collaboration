import sys
import os
import asyncio
import hashlib
import re
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from rich.console import Console
from rich.panel import Panel
import markdownify

console = Console()

async def fetch_chat_content(url, need_login=False):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    user_data_dir = os.path.join(script_dir, ".browser_user_data")
    images_dir = os.path.join(script_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    headless = not need_login
    if need_login:
        console.print("[bold yellow]正在启动浏览器供您登录账号...[/bold yellow]")
        console.print("[dim]请在弹出的浏览器中登录您的 AI 账号。[/dim]")

    console.print(f"[bold cyan]正在加载页面:[/bold cyan] {url}")
    
    # 无头抓取模式下使用大视口以渲染虚拟列表
    viewport_config = None if need_login else {'width': 1920, 'height': 10800}
    
    async with async_playwright() as p:
        # 使用持久化上下文保存/读取登录 Cookie 及 Session
        # 配合反自动化伪装参数，绕过 Google / OpenAI 的 "此浏览器或应用可能不安全" 拦截
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            channel="msedge",
            viewport=viewport_config,
            no_viewport=need_login,
            ignore_default_args=["--enable-automation"],
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-service-autorun"
            ]
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        try:
            # 使用 domcontentloaded 替代 networkidle，防止 ChatGPT 私有对话长连接导致 45 秒超时
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            
            if need_login:
                console.print("\n[bold green]>>> 提示：请在弹出的浏览器界面中完成登录，完成后按【回车键 (Enter)】继续抓取... <<<[/bold green]")
                input()
                console.print("[dim]登录确认成功，继续抓取对话数据...[/dim]")
                await page.wait_for_timeout(2000)
            
            console.print("[dim]正在等待动态内容渲染...[/dim]")
            try:
                # 兼容豆包 (.message-item) 和 ChatGPT ([data-message-author-role])
                await page.wait_for_selector(".message-item, [data-message-author-role]", state="attached", timeout=15000)
            except Exception:
                console.print("[dim]提示: 等待动态节点超时，可能网页结构有所变化或需登录访问。[/dim]")
            await page.wait_for_timeout(4000)
            
            # 获取完整 HTML
            html = await page.content()
            soup_pre = BeautifulSoup(html, "html.parser")
            
            # 自动提取并本地化保存网页中的所有真实图片 (支持 src, data-src, srcset)
            image_map = {}
            img_index = 1
            console.print("[dim]正在检查并下载页面中的图片资产...[/dim]")
            
            for img in soup_pre.find_all(["img", "source"]):
                src_candidates = [img.get("src"), img.get("data-src")]
                srcset = img.get("srcset")
                if srcset:
                    # 提取 srcset 中的图片 URL
                    for item in srcset.split(","):
                        parts = item.strip().split()
                        if parts:
                            src_candidates.append(parts[0])
                
                for src in src_candidates:
                    if src and src.startswith("http") and not src.startswith("data:image/svg") and src not in image_map:
                        url_hash = hashlib.md5(src.encode('utf-8')).hexdigest()[:8]
                        ext = "png"
                        if ".jpg" in src.lower() or ".jpeg" in src.lower():
                            ext = "jpg"
                        elif ".webp" in src.lower():
                            ext = "webp"
                        
                        filename = f"img_{img_index}_{url_hash}.{ext}"
                        filepath = os.path.join(images_dir, filename)
                        
                        if not os.path.exists(filepath):
                            try:
                                res = await page.request.get(src, timeout=10000)
                                if res.ok:
                                    with open(filepath, "wb") as f_img:
                                        f_img.write(await res.body())
                                    image_map[src] = f"../images/{filename}"
                                    img_index += 1
                            except Exception:
                                pass
                        else:
                            image_map[src] = f"../images/{filename}"

            return html, image_map
        except Exception as e:
            console.print(f"[bold red]加载页面时发生错误:[/bold red] {e}")
            return None, {}
        finally:
            await context.close()

def parse_and_display(html, image_map=None):
    if not html:
        return
    
    if image_map is None:
        image_map = {}
        
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 保留一份供调试的本地快照
    debug_filename = os.path.join(script_dir, "debug_last_fetch.html")
    with open(debug_filename, "w", encoding="utf-8") as f:
        f.write(html)
        
    soup = BeautifulSoup(html, 'html.parser')
    console.print("[bold green]✅ 页面加载完毕，正在解析对话内容...[/bold green]\n")
    
    parsed_messages = []
    
    # 1. 尝试使用 ChatGPT 解析逻辑
    chatgpt_messages = soup.find_all(attrs={"data-message-author-role": True})
    if chatgpt_messages:
        console.print("[dim]检测到 ChatGPT 对话格式，使用专用解析器...[/dim]")
        for msg in chatgpt_messages:
            role = msg.get("data-message-author-role")
            if role == "user":
                content_parts = []
                # 提取用户发送的所有图片 (精准映射本地路径)
                for img in msg.find_all("img"):
                    src = img.get("src") or img.get("data-src")
                    alt = img.get("alt", "用户上传图片")
                    if src and not src.startswith("data:image/svg"):
                        local_src = image_map.get(src, src)
                        content_parts.append(f"![{alt}]({local_src})")
                
                # 精准检查显示的文件卡片或下载链接（排除纯文本里的误触发）
                for a in msg.find_all("a", href=True):
                    href = a["href"]
                    link_text = a.get_text(strip=True) or "附件文件"
                    if (href.startswith("http") or href.startswith("/")) and any(ext in link_text.lower() for ext in ['.doc', '.pdf', '.txt', '.xls', '.ppt', '.zip', '.rar', '.csv']):
                        content_parts.append(f"[📄 {link_text}]({href})")

                # 识别真实的 HTML 文件卡片节点（非纯文本正则）
                file_cards = msg.find_all(class_=re.compile(r'file|attachment|document', re.I))
                for card in file_cards:
                    card_text = card.get_text(strip=True)
                    if any(ext in card_text.lower() for ext in ['.doc', '.pdf', '.txt', '.xls', '.ppt', '.zip', '.rar', '.csv']):
                        # 提炼出真正文件名
                        match = re.search(r'[\w\-\"\u4e00-\u9fa5\“\”]+\.(?:docx|doc|pdf|txt|xlsx|xls|pptx|ppt|zip|rar|csv)', card_text, re.IGNORECASE)
                        if match:
                            content_parts.append(f"📎 **[上传文档]** `{match.group(0)}`")

                text = msg.get_text(separator='\n', strip=True)
                if text:
                    content_parts.append(text)
                
                # 顺序去重但保留多个不同图片
                seen = set()
                ordered_parts = []
                for item in content_parts:
                    if item not in seen:
                        seen.add(item)
                        ordered_parts.append(item)

                final_user_text = "\n\n".join(ordered_parts) if ordered_parts else text
                parsed_messages.append({'role': 'User', 'content': final_user_text})

            elif role == "assistant":
                # 替换本地图片路径
                for img in msg.find_all("img"):
                    src = img.get("src") or img.get("data-src")
                    if src in image_map:
                        img["src"] = image_map[src]

                # 修复 ChatGPT 嵌套 <pre> 导致 markdownify 生成多重/错误代码块的问题
                for pre in msg.find_all("pre"):
                    if "cm-content" not in pre.get('class', []):
                        inner_pre = pre.find("pre", class_="cm-content")
                        if inner_pre:
                            code_text = inner_pre.get_text()
                            # 构造标准 <pre><code> 避免嵌套冲突
                            new_pre = soup.new_tag("pre")
                            new_code = soup.new_tag("code")
                            new_code.string = code_text
                            new_pre.append(new_code)
                            pre.replace_with(new_pre)

                md_text = markdownify.markdownify(str(msg), heading_style="ATX").strip()
                parsed_messages.append({'role': 'AI', 'content': md_text})
                
    else:
        # 2. 尝试使用豆包解析逻辑
        for script_or_style in soup(['script', 'style', 'noscript', 'button']):
            script_or_style.decompose()
            
        message_items = soup.find_all('div', class_='message-item')
        if message_items:
            console.print("[dim]检测到豆包对话格式，使用专用解析器...[/dim]")
            for msg in message_items:
                classes = msg.get('class', [])
                is_user = 'justify-end' in classes
                
                # 替换本地图片路径
                for img in msg.find_all("img"):
                    src = img.get("src") or img.get("data-src")
                    if src in image_map:
                        img["src"] = image_map[src]

                if is_user:
                    user_parts = []
                    # 关键修复：支持提取豆包用户上传的图片！
                    for img in msg.find_all("img"):
                        src = img.get("src") or img.get("data-src")
                        if src and not src.startswith("data:image/svg"):
                            local_src = image_map.get(src, src)
                            user_parts.append(f"![用户图片]({local_src})")

                    # 识别真实的 HTML 文件卡片（非全文正则）
                    file_cards = msg.find_all(class_=re.compile(r'file|attachment|doc', re.I))
                    for card in file_cards:
                        card_text = card.get_text(strip=True)
                        match = re.search(r'[\w\-\"\u4e00-\u9fa5\“\”]+\.(?:docx|doc|pdf|txt|xlsx|xls|pptx|ppt|zip|rar|csv)', card_text, re.IGNORECASE)
                        if match:
                            user_parts.append(f"📎 **[上传文档]** `{match.group(0)}`")

                    text = msg.get_text(separator='\n', strip=True)
                    clean_lines = [line.strip() for line in text.split('\n') if len(line.strip()) > 0 and line.strip() not in ["复制", "重新生成", "点赞", "踩", "分享", "已采纳", "查看更多", "编辑", "朗读", "Word", "PDF", "文档"]]
                    if clean_lines:
                        user_parts.append('\n'.join(clean_lines))
                    
                    seen = set()
                    ordered_parts = []
                    for item in user_parts:
                        if item not in seen:
                            seen.add(item)
                            ordered_parts.append(item)

                    final_text = "\n\n".join(ordered_parts) if ordered_parts else '\n'.join(clean_lines)
                    if final_text:
                        parsed_messages.append({'role': 'User', 'content': final_text})
                else:
                    md_text = markdownify.markdownify(str(msg), heading_style="ATX").strip()
                    if md_text:
                        parsed_messages.append({'role': 'AI', 'content': md_text})
        
        else:
            # 3. 降级提取方案
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
            console.print(Panel(item['content'], title="[bold magenta]🤖 AI / 回答[/bold magenta]", border_style="magenta", title_align="left"))

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
        if image_map:
            console.print(f"[dim]已成功下载并关联 {len(image_map)} 张图片到 ../images/ 目录。[/dim]")
    except Exception as e:
        console.print(f"\n[bold red]保存 Markdown 文件时出错:[/bold red] {e}")

async def main():
    console.print(Panel.fit("[bold yellow]🚀 AI 记忆协同管理工具 - 对话提取与可视化工具 (V0.2)[/bold yellow]", border_style="green"))
    console.print("本程序使用 Playwright + 登录凭证保存技术，支持抓取带图片/附件的完整对话。\n")
    
    console.print("[bold cyan]请选择模式:[/bold cyan]")
    console.print("  [1] 直接抓取 (推荐，自动使用已保存的登录凭证)")
    console.print("  [2] 弹出浏览器登录账号 (首次使用/需要更新登录状态时选此项)")
    
    mode = input("\n请选择模式 (1 或 2，默认 1): ").strip()
    need_login = (mode == "2")
    
    url = input("请输入 AI 的对话/分享链接 (例如 https://...): ").strip()
    if not url:
        console.print("[bold red]链接不能为空，程序退出。[/bold red]")
        sys.exit(1)
        
    html, image_map = await fetch_chat_content(url, need_login=need_login)
    parse_and_display(html, image_map)
    
    console.print("\n[bold green]处理完成！[/bold green]")

if __name__ == "__main__":
    asyncio.run(main())
