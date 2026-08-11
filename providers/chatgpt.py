"""ChatGPT 页面采集与消息解析。"""

import re

import markdownify
from rich.console import Console


DISPLAY_NAME = "ChatGPT"
WAIT_SELECTOR = "[data-message-author-role]"

console = Console()


async def collect_html(page):
    """逐屏收集 ChatGPT 虚拟列表中的消息，避免长对话首尾丢失。"""
    role_selector = WAIT_SELECTOR
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


def parse_messages(soup, image_map=None):
    """解析 ChatGPT 消息；页面不属于 ChatGPT 时返回 None。"""
    if image_map is None:
        image_map = {}

    chatgpt_messages = soup.find_all(
        attrs={"data-message-author-role": True}
    )
    if not chatgpt_messages:
        return None

    parsed_messages = []
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
                if (
                    (href.startswith("http") or href.startswith("/"))
                    and any(
                        ext in link_text.lower()
                        for ext in [
                            '.doc', '.pdf', '.txt', '.xls', '.ppt',
                            '.zip', '.rar', '.csv'
                        ]
                    )
                ):
                    content_parts.append(f"[📄 {link_text}]({href})")

            # 识别真实的 HTML 文件卡片节点（非纯文本正则）
            file_cards = msg.find_all(
                class_=re.compile(r'file|attachment|document', re.I)
            )
            for card in file_cards:
                card_text = card.get_text(strip=True)
                if any(
                    ext in card_text.lower()
                    for ext in [
                        '.doc', '.pdf', '.txt', '.xls', '.ppt',
                        '.zip', '.rar', '.csv'
                    ]
                ):
                    # 提炼出真正文件名
                    match = re.search(
                        r'[\w\-"\u4e00-\u9fa5\“\”]+\.'
                        r'(?:docx|doc|pdf|txt|xlsx|xls|pptx|ppt|zip|rar|csv)',
                        card_text,
                        re.IGNORECASE
                    )
                    if match:
                        content_parts.append(
                            f"📎 **[上传文档]** `{match.group(0)}`"
                        )

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

            final_user_text = (
                "\n\n".join(ordered_parts) if ordered_parts else text
            )
            parsed_messages.append({
                'role': 'User',
                'content': final_user_text
            })

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

            md_text = markdownify.markdownify(
                str(msg),
                heading_style="ATX"
            ).strip()
            parsed_messages.append({'role': 'AI', 'content': md_text})

    return parsed_messages
