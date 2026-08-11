"""豆包页面消息解析。"""

import re

import markdownify


DISPLAY_NAME = "豆包"
WAIT_SELECTOR = ".message-item"


def parse_messages(soup, image_map=None):
    """解析豆包消息；页面不属于豆包时返回 None。"""
    if image_map is None:
        image_map = {}

    for script_or_style in soup(['script', 'style', 'noscript', 'button']):
        script_or_style.decompose()

    message_items = soup.find_all('div', class_='message-item')
    if not message_items:
        return None

    parsed_messages = []
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
            file_cards = msg.find_all(
                class_=re.compile(r'file|attachment|doc', re.I)
            )
            for card in file_cards:
                card_text = card.get_text(strip=True)
                match = re.search(
                    r'[\w\-"\u4e00-\u9fa5\“\”]+\.'
                    r'(?:docx|doc|pdf|txt|xlsx|xls|pptx|ppt|zip|rar|csv)',
                    card_text,
                    re.IGNORECASE
                )
                if match:
                    user_parts.append(
                        f"📎 **[上传文档]** `{match.group(0)}`"
                    )

            text = msg.get_text(separator='\n', strip=True)
            clean_lines = [
                line.strip()
                for line in text.split('\n')
                if len(line.strip()) > 0
                and line.strip() not in [
                    "复制", "重新生成", "点赞", "踩", "分享", "已采纳",
                    "查看更多", "编辑", "朗读", "Word", "PDF", "文档"
                ]
            ]
            if clean_lines:
                user_parts.append('\n'.join(clean_lines))

            seen = set()
            ordered_parts = []
            for item in user_parts:
                if item not in seen:
                    seen.add(item)
                    ordered_parts.append(item)

            final_text = (
                "\n\n".join(ordered_parts)
                if ordered_parts
                else '\n'.join(clean_lines)
            )
            if final_text:
                parsed_messages.append({
                    'role': 'User',
                    'content': final_text
                })
        else:
            md_text = markdownify.markdownify(
                str(msg),
                heading_style="ATX"
            ).strip()
            if md_text:
                parsed_messages.append({'role': 'AI', 'content': md_text})

    return parsed_messages
