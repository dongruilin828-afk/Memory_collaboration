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

async def collect_chatgpt_virtualized_html(page):
    """逐屏收集 ChatGPT 虚拟列表中的消息，避免长对话首尾丢失。"""
    role_selector = "[data-message-author-role]"
    if await page.locator(role_selector).count() == 0:
        return None

    scroll_container = None
    captured = {}
    discovery_index = 0

    try:
        scroll_container = await page.locator(role_selector).first.evaluate_handle(
            """element => {
                let current = element;
                while (current) {
                    const style = window.getComputedStyle(current);
                    const canScroll = current.scrollHeight > current.clientHeight + 1;
                    if (canScroll && /(auto|scroll)/.test(style.overflowY)) {
                        return current;
                    }
                    current = current.parentElement;
                }
                return document.scrollingElement || document.documentElement;
            }"""
        )

        scroll_top = 0
        for _ in range(100):
            await scroll_container.evaluate(
                "(element, top) => element.scrollTo(0, top)",
                scroll_top
            )
            await page.wait_for_timeout(700)

            visible_messages = await page.locator(role_selector).evaluate_all(
                """elements => elements.map(element => {
                    const turn = element.closest('[data-testid^="conversation-turn-"]');
                    const testId = turn ? turn.getAttribute('data-testid') || '' : '';
                    const turnMatch = testId.match(/(\\d+)$/);
                    const messageId = element.getAttribute('data-message-id') || '';
                    const role = element.getAttribute('data-message-author-role') || '';
                    const text = element.innerText || element.textContent || '';
                    return {
                        key: messageId || testId || `${role}:${text}`,
                        order: turnMatch ? Number(turnMatch[1]) : null,
                        html: element.outerHTML
                    };
                })"""
            )

            for message in visible_messages:
                key = message["key"]
                if key not in captured:
                    message["discovery_index"] = discovery_index
                    captured[key] = message
                    discovery_index += 1

            metrics = await scroll_container.evaluate(
                """element => ({
                    scrollHeight: element.scrollHeight,
                    clientHeight: element.clientHeight
                })"""
            )
            max_scroll_top = max(
                0,
                metrics["scrollHeight"] - metrics["clientHeight"]
            )
            if scroll_top >= max_scroll_top:
                break

            step = max(int(metrics["clientHeight"] * 0.5), 800)
            next_scroll_top = min(scroll_top + step, max_scroll_top)
            if next_scroll_top <= scroll_top:
                break
            scroll_top = next_scroll_top

        ordered_messages = sorted(
            captured.values(),
            key=lambda message: (
                message["order"] is None,
                message["order"]
                if message["order"] is not None
                else message["discovery_index"]
            )
        )

        if ordered_messages:
            console.print(
                f"[dim]已从 ChatGPT 虚拟列表中完整收集 "
                f"{len(ordered_messages)} 条消息。[/dim]"
            )
            message_html = "\n".join(
                message["html"] for message in ordered_messages
            )
            return f"<!DOCTYPE html><html><body>{message_html}</body></html>"

    except Exception as e:
        console.print(
            f"[dim]提示: ChatGPT 虚拟列表收集失败，将使用当前页面快照: {e}[/dim]"
        )
    finally:
        if scroll_container is not None:
            await scroll_container.dispose()

    return None

async def collect_deepseek_virtualized_html(page):
    """逐屏收集 DeepSeek 虚拟列表中的消息，避免超长分享对话丢失。"""
    item_selector = "[data-virtual-list-item-key]"
    if await page.locator(f"{item_selector} .ds-message").count() == 0:
        return None

    scroll_container = None
    captured = {}
    discovery_index = 0

    async def capture_visible_items():
        """收集当前已挂载的消息；DeepSeek 的虚拟列表挂载有短暂延迟。"""
        nonlocal discovery_index
        visible_items = await page.locator(item_selector).evaluate_all(
            """elements => elements
                .filter(element => element.querySelector('.ds-message'))
                .map(element => {
                    const rawKey = element.getAttribute(
                        'data-virtual-list-item-key'
                    ) || '';
                    const numericKey = Number(rawKey);
                    const imageScore = Array.from(
                        element.querySelectorAll('img')
                    ).filter(image => {
                        const src = image.getAttribute('src')
                            || image.getAttribute('data-src') || '';
                        return src && !src.startsWith('data:image/svg');
                    }).length;
                    return {
                        key: rawKey || element.innerText || element.outerHTML,
                        order: Number.isFinite(numericKey) ? numericKey : null,
                        image_score: imageScore,
                        html: element.outerHTML
                    };
                })"""
        )

        for item in visible_items:
            key = item["key"]
            existing = captured.get(key)
            if existing is None:
                item["discovery_index"] = discovery_index
                captured[key] = item
                discovery_index += 1
            elif (
                item["image_score"],
                len(item["html"])
            ) > (
                existing["image_score"],
                len(existing["html"])
            ):
                item["discovery_index"] = existing["discovery_index"]
                captured[key] = item

    try:
        scroll_container = await page.locator(
            f"{item_selector} .ds-message"
        ).first.evaluate_handle(
            """element => {
                let current = element;
                while (current) {
                    const style = window.getComputedStyle(current);
                    const canScroll = current.scrollHeight > current.clientHeight + 1;
                    if (canScroll && /(auto|scroll)/.test(style.overflowY)) {
                        return current;
                    }
                    current = current.parentElement;
                }
                return document.scrollingElement || document.documentElement;
            }"""
        )

        scroll_top = 0
        max_scroll_top = 0
        for _ in range(500):
            await scroll_container.evaluate(
                "(element, top) => element.scrollTo(0, top)",
                scroll_top
            )
            await page.wait_for_timeout(700)

            await capture_visible_items()
            await page.wait_for_timeout(500)
            await capture_visible_items()

            metrics = await scroll_container.evaluate(
                """element => ({
                    scrollHeight: element.scrollHeight,
                    clientHeight: element.clientHeight
                })"""
            )
            max_scroll_top = max(
                0,
                metrics["scrollHeight"] - metrics["clientHeight"]
            )
            if scroll_top >= max_scroll_top:
                break

            step = max(int(metrics["clientHeight"] * 0.5), 800)
            next_scroll_top = min(scroll_top + step, max_scroll_top)
            if next_scroll_top <= scroll_top:
                break
            scroll_top = next_scroll_top

        # 人工登录使用系统窗口尺寸。此时首次滚到顶部后，DeepSeek
        # 偶尔要过一小段时间才会挂载第一条消息。回访首尾边界并固定
        # 复采数次，既补齐首条，也避免尾条遇到相同的竞态。
        for boundary in (max_scroll_top, 0):
            await scroll_container.evaluate(
                "(element, top) => element.scrollTo(0, top)",
                boundary
            )
            for _ in range(4):
                await page.wait_for_timeout(500)
                await capture_visible_items()

        ordered_items = sorted(
            captured.values(),
            key=lambda item: (
                item["order"] is None,
                item["order"]
                if item["order"] is not None
                else item["discovery_index"]
            )
        )

        if ordered_items:
            console.print(
                f"[dim]已从 DeepSeek 虚拟列表中完整收集 "
                f"{len(ordered_items)} 条消息。[/dim]"
            )
            item_html = "\n".join(item["html"] for item in ordered_items)
            return f"<!DOCTYPE html><html><body>{item_html}</body></html>"

    except Exception as e:
        console.print(
            f"[dim]提示: DeepSeek 虚拟列表收集失败，将使用当前页面快照: {e}[/dim]"
        )
    finally:
        if scroll_container is not None:
            await scroll_container.dispose()

    return None

async def goto_with_retry(page, url, attempts=3):
    """加载分享页；网络偶发超时时自动重试，并明确显示进度。"""
    for attempt in range(1, attempts + 1):
        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=45000
            )
            return
        except Exception:
            if attempt >= attempts:
                raise
            console.print(
                f"[yellow]页面加载超时，正在进行第 {attempt + 1}/{attempts} 次尝试...[/yellow]"
            )
            await page.wait_for_timeout(2000 * attempt)

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
            await goto_with_retry(page, url)
            
            if need_login:
                console.print("\n[bold green]>>> 提示：请在弹出的浏览器界面中完成登录，完成后按【回车键 (Enter)】继续抓取... <<<[/bold green]")
                input()
                console.print("[dim]登录确认成功，继续抓取对话数据...[/dim]")
                await page.wait_for_timeout(2000)
            
            console.print("[dim]正在等待动态内容渲染...[/dim]")
            try:
                # 兼容豆包、ChatGPT 和 DeepSeek 的稳定消息节点
                await page.wait_for_selector(
                    ".message-item, [data-message-author-role], "
                    "[data-virtual-list-item-key] .ds-message",
                    state="attached",
                    timeout=15000
                )
            except Exception:
                console.print("[dim]提示: 等待动态节点超时，可能网页结构有所变化或需登录访问。[/dim]")
            await page.wait_for_timeout(4000)
            
            # ChatGPT 使用虚拟列表，长对话必须逐屏收集才能避免首尾消息丢失。
            html = await collect_chatgpt_virtualized_html(page)
            if html is None:
                html = await collect_deepseek_virtualized_html(page)
            if html is None:
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

def parse_deepseek_messages(soup, image_map=None):
    """解析 DeepSeek 分享页，只保留用户内容和 AI 最终回答。"""
    if image_map is None:
        image_map = {}

    parsed_messages = []
    ignored_ui_text = {
        "复制", "重新生成", "编辑", "分享", "下载", "点赞", "踩"
    }
    attachment_name_pattern = re.compile(
        r'^[^\\/:*?"<>|\n]+\.(?:png|jpe?g|webp|gif|bmp|svg|pdf|docx?|'
        r'xlsx?|pptx?|txt|csv|zip|rar)$',
        re.IGNORECASE
    )
    attachment_size_pattern = re.compile(
        r'^(?:PNG|JPE?G|WEBP|GIF|BMP|SVG|PDF|DOCX?|XLSX?|PPTX?|TXT|CSV|ZIP|RAR)'
        r'\s+\d+(?:\.\d+)?\s*(?:B|KB|MB|GB)$',
        re.IGNORECASE
    )

    for item in soup.select('[data-virtual-list-item-key]'):
        message_node = item.select_one('.ds-message')
        if message_node is None:
            continue

        answer_node = item.select_one('.ds-assistant-message-main-content')
        if answer_node is not None:
            answer_soup = BeautifulSoup(str(answer_node), 'html.parser')
            answer = answer_soup.select_one('.ds-assistant-message-main-content')

            # 去掉代码块工具栏中的“复制/下载”等界面文字，保留代码本体。
            for removable in answer.select(
                'script, style, noscript, button, .md-code-block-banner-wrap'
            ):
                removable.decompose()

            for img in answer.find_all('img'):
                src = img.get('src') or img.get('data-src')
                if src in image_map:
                    img['src'] = image_map[src]

            md_text = markdownify.markdownify(
                str(answer),
                heading_style='ATX'
            ).strip()
            if md_text:
                parsed_messages.append({'role': 'AI', 'content': md_text})
            continue

        user_soup = BeautifulSoup(str(message_node), 'html.parser')
        user_message = user_soup.select_one('.ds-message')
        user_parts = []

        # DeepSeek 的历史分享图片可能已经从文件服务失效。此时前端只
        # 留下一个带宽高样式和 tabindex 的错误占位组件，没有 img/src。
        media_placeholder = user_message.find(attrs={'tabindex': '0'})
        placeholder_style = (
            media_placeholder.get('style', '')
            if media_placeholder is not None
            else ''
        )
        has_failed_image_placeholder = (
            user_message.find('img') is None
            and 'width:' in placeholder_style
            and 'height:' in placeholder_style
        )

        for img in user_message.find_all('img'):
            src = img.get('src') or img.get('data-src')
            alt = img.get('alt', '用户上传图片')
            if src and not src.startswith('data:image/svg'):
                local_src = image_map.get(src, src)
                user_parts.append(f'![{alt}]({local_src})')

        for removable in user_message.select(
            'script, style, noscript, button, svg'
        ):
            removable.decompose()

        raw_lines = [
            line.strip()
            for line in user_message.get_text(separator='\n', strip=True).split('\n')
            if line.strip()
        ]
        clean_lines = []
        index = 0
        while index < len(raw_lines):
            line = raw_lines[index]
            next_line = raw_lines[index + 1] if index + 1 < len(raw_lines) else ''
            if (
                attachment_name_pattern.match(line)
                and attachment_size_pattern.match(next_line)
            ):
                user_parts.append(
                    f'📎 **[上传文件]** `{line}`（{next_line}）'
                )
                index += 2
                continue
            if line not in ignored_ui_text:
                clean_lines.append(line)
            index += 1

        if clean_lines:
            user_parts.append('\n'.join(clean_lines))

        if not user_parts and has_failed_image_placeholder:
            user_parts.append(
                '🖼️ **[用户上传图片]**'
                '（DeepSeek 分享页原图已失效或加载失败）'
            )

        seen = set()
        ordered_parts = []
        for part in user_parts:
            if part not in seen:
                seen.add(part)
                ordered_parts.append(part)

        final_text = '\n\n'.join(ordered_parts)
        if final_text:
            parsed_messages.append({'role': 'User', 'content': final_text})

    return parsed_messages

def parse_and_display(html, image_map=None):
    if not html:
        return False
    
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
    deepseek_messages = []
    if not chatgpt_messages:
        deepseek_messages = parse_deepseek_messages(soup, image_map)
        if deepseek_messages:
            console.print("[dim]检测到 DeepSeek 对话格式，使用专用解析器...[/dim]")
            parsed_messages.extend(deepseek_messages)

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
                
    elif not deepseek_messages:
        # 3. 尝试使用豆包解析逻辑
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
            # 4. 降级提取方案
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
        return False

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
                    f.write(
                        '\n<hr style="border: 0; border-top: 5px solid #2563EB; '
                        'margin: 48px 0 24px 0;">\n\n'
                        f"## 🔵 👤 用户提问\n\n{item['content']}\n\n"
                    )
                else:
                    f.write(
                        '\n<hr style="border: 0; border-top: 5px solid #9333EA; '
                        'margin: 48px 0 24px 0;">\n\n'
                        f"## 🟣 🤖 AI 回答\n\n{item['content']}\n\n"
                    )
        console.print(f"\n[bold green]🎉 对话记录已成功导出为 Markdown 文件: {export_filename}[/bold green]")
        if image_map:
            console.print(f"[dim]已成功下载并关联 {len(image_map)} 张图片到 ./images/ 目录。[/dim]")
        return True
    except Exception as e:
        console.print(f"\n[bold red]保存 Markdown 文件时出错:[/bold red] {e}")
        return False

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
    success = parse_and_display(html, image_map)
    if not success:
        console.print("\n[bold red]处理失败，未生成有效的导出文件。[/bold red]")
        sys.exit(1)
    
    console.print("\n[bold green]处理完成！[/bold green]")

if __name__ == "__main__":
    asyncio.run(main())
