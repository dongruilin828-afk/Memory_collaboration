"""豆包页面消息解析。"""

import base64
import re
from collections import Counter
from urllib.parse import unquote

import markdownify
from bs4 import BeautifulSoup


DISPLAY_NAME = "豆包"
SHARE_MESSAGE_SELECTOR = ".message-item"
DIRECT_LIST_SELECTOR = "div[class*='message-list-']"
DIRECT_MESSAGE_SELECTOR = "div.my-0.w-full.mx-auto"
WAIT_SELECTOR = f"{SHARE_MESSAGE_SELECTOR}, {DIRECT_LIST_SELECTOR}"
HOSTS = ("doubao.com", "www.doubao.com")
_GENERATED_IMAGE_RE = re.compile(r"(/rc_gen_image/[^?~]+)~tplv-[^?]+")
_DECORATIVE_IMAGES = (
    '[data-testid="doc_card"] img, [class*="video-header-"] img, '
    'img[alt="Asset cover"], [data-assembly-preview-card][data-office-artifact-status] img'
)


def decorative_image_sources(soup):
    sources = set()
    for image in soup.select(_DECORATIVE_IMAGES):
        for key in ("src", "data-src"):
            if image.get(key):
                sources.add(image[key])
        sources.update(item.strip().split()[0] for item in str(image.get("srcset") or "").split(",") if item.strip())
    return sources


def prefer_original_generated_images(sources, preferred_sources=()):
    """同一豆包生成图同时出现缩略图和原图时只保留原图。"""
    preferred_sources = set(preferred_sources)
    preferred_keys = {
        match.group(1) for src in preferred_sources
        if (match := _GENERATED_IMAGE_RE.search(str(src)))
    }
    sources = [src for src in sources if not (
        (match := _GENERATED_IMAGE_RE.search(str(src)))
        and match.group(1) in preferred_keys and src not in preferred_sources
    )]
    matches = [(src, _GENERATED_IMAGE_RE.search(str(src))) for src in sources]
    def quality(source):
        path = str(source).split("?", 1)[0].lower()
        if "-image_pre_watermark_" in path or "-cgen_" in path:
            return 2
        if "-downsize_watermark_" in path or "-cthumb_" in path:
            return 1
        return 0

    best_quality = {}
    for src, match in matches:
        if match:
            key = match.group(1)
            best_quality[key] = max(best_quality.get(key, 0), quality(src))
    return [
        src for src, match in matches
        if not match or quality(src) >= best_quality[match.group(1)]
    ]


async def _scroll_messages(page, messages, message_count):
    index = 0
    stable_rounds = 0
    while index < 600 and stable_rounds < 6:
        message_count = max(message_count, await messages.count())
        if index >= message_count:
            try:
                await messages.last.evaluate(
                    """element => {
                        let scroller = element.parentElement;
                        while (scroller && !(
                            /^(auto|scroll|overlay)$/.test(getComputedStyle(scroller).overflowY)
                            && scroller.scrollHeight > scroller.clientHeight + 8
                        ))
                            scroller = scroller.parentElement;
                        if (scroller) scroller.scrollTop = scroller.scrollHeight;
                        else window.scrollTo(0, document.body.scrollHeight);
                    }"""
                )
            except Exception:
                pass
            await page.wait_for_timeout(900)
            updated_count = await messages.count()
            stable_rounds = stable_rounds + 1 if updated_count <= message_count else 0
            continue
        try:
            message = messages.nth(index)
            await message.scroll_into_view_if_needed(timeout=3000)
            # 豆包在消息进入视野后异步挂载 picture/img；短暂停留可避免
            # 长对话滚动过快时图片节点尚未生成就读取页面快照。
            await page.wait_for_timeout(120)
            if await message.locator('[class*="image-box-grid-item-"]').count() and not await message.locator('img[src^="http"]').count():
                try:
                    await message.locator('img[src^="http"]').first.wait_for(
                        state="attached", timeout=3000
                    )
                except Exception:
                    pass
        except Exception:
            pass
        index += 1
    await page.wait_for_timeout(700)
    for _ in range(20):
        expand = page.locator('[data-testid="message_expand_all_button"]').first
        if not await expand.count():
            break
        try:
            await expand.click(timeout=3000)
            await page.wait_for_timeout(150)
        except Exception:
            break


async def collect_html(page):
    """仅收集当前豆包会话，兼容分享页与账号内 `/chat/` 页面。"""
    share_messages = page.locator(SHARE_MESSAGE_SELECTOR)
    try:
        share_count = await share_messages.count()
    except Exception:
        return None
    if share_count:
        await _scroll_messages(page, share_messages, share_count)
        return await page.content()

    try:
        lists = page.locator(DIRECT_LIST_SELECTOR)
        list_stats = await lists.evaluate_all(
            """elements => elements.map((element, index) => {
                const messages = Array.from(
                    element.querySelectorAll('div.my-0.w-full.mx-auto')
                ).filter(wrapper => wrapper.querySelector(
                    'div.flex.flex-row.w-full'
                ));
                return {
                    index,
                    count: messages.length,
                    textLength: messages.reduce(
                        (total, message) => total + (message.innerText || '').length,
                        0
                    )
                };
            })"""
        )
    except Exception:
        return None
    usable_lists = [item for item in list_stats if item.get("count", 0) > 0]
    if not usable_lists:
        return None
    selected = max(
        usable_lists,
        key=lambda item: (item.get("count", 0), item.get("textLength", 0)),
    )
    direct_messages = lists.nth(selected["index"]).locator(
        DIRECT_MESSAGE_SELECTOR
    )
    scroller = lists.nth(selected["index"]).locator(
        '[class*="v_list_scroller-"]'
    ).first
    try:
        await scroller.hover(timeout=3000)
    except Exception:
        pass
    fragment_by_key = {}
    ordered_keys = []
    unchanged_rounds = 0
    first_fragment = None
    pending_indices = []
    last_at_top = False
    for _ in range(400):
        pending_indices = await direct_messages.evaluate_all(
            """elements => elements.flatMap((wrapper, index) => {
                const content = wrapper.querySelector('[data-testid="message_content"]');
                return content && !(content.innerText || '').trim()
                    && !content.querySelector('img, picture, iframe, [data-testid="attachment_file_item"]')
                    ? [index] : [];
            })"""
        )
        for pending_index in pending_indices:
            try:
                await direct_messages.nth(pending_index).scroll_into_view_if_needed(
                    timeout=3000
                )
                await page.wait_for_timeout(250)
            except Exception:
                pass
        current_fragments = await direct_messages.evaluate_all(
            """elements => elements.map((wrapper, index) => {
                const roleRows = Array.from(wrapper.querySelectorAll(
                    'div.flex.flex-row.w-full'
                ));
                if (!roleRows.length) return null;
                const isUser = roleRows.some(row => row.classList.contains('justify-end'));
                const content = wrapper.querySelector('[data-testid="message_content"]');
                const hasContent = Boolean(content && (
                    (content.innerText || '').trim()
                    || content.querySelector('img, picture, iframe, [data-testid="attachment_file_item"]')
                ));
                if (!hasContent) return null;
                const clone = wrapper.cloneNode(true);
                clone.classList.add('message-item');
                clone.setAttribute('data-doubao-role', isUser ? 'user' : 'assistant');
                const message = wrapper.querySelector('[data-message-id]');
                return {
                    index,
                    key: message?.getAttribute('data-message-id') || clone.outerHTML,
                    html: clone.outerHTML
                };
            }).filter(Boolean)"""
        )
        for item in current_fragments:
            if item["key"] in fragment_by_key:
                if 'alt="生成图表"' in fragment_by_key[item["key"]]:
                    item["html"] = fragment_by_key[item["key"]]
                continue
            try:
                message = direct_messages.nth(item["index"])
                previews = message.locator(
                    'iframe[src*="html_preview"]'
                )
                if not await previews.count():
                    continue
                await message.scroll_into_view_if_needed(timeout=3000)
                preview_images = []
                for preview_index in range(await previews.count()):
                    image = await previews.nth(preview_index).screenshot(type="png")
                    preview_images.append(
                        "data:image/png;base64," + base64.b64encode(image).decode("ascii")
                    )
                if preview_images:
                    fragment = BeautifulSoup(item["html"], "html.parser")
                    for iframe, image_src in zip(fragment.find_all("iframe"), preview_images):
                        iframe.replace_with(fragment.new_tag("img", src=image_src, alt="生成图表"))
                    item["html"] = str(fragment)
            except Exception:
                continue
        current_keys = [item["key"] for item in current_fragments]
        new_keys = [key for key in current_keys if key not in fragment_by_key]
        if new_keys:
            ordered_keys = new_keys + ordered_keys
        for item in current_fragments:
            fragment_by_key[item["key"]] = item["html"]

        current_first = current_keys[0] if current_keys else None
        unchanged_rounds = (
            unchanged_rounds + 1
            if not new_keys and current_first == first_fragment else 0
        )
        if not current_fragments:
            await page.wait_for_timeout(700)
            continue
        if (
            last_at_top
            and unchanged_rounds >= 20
        ):
            break
        first_fragment = current_first
        try:
            step = await scroller.evaluate(
                "element => Math.max(300, element.clientHeight * 0.8)"
            )
            await page.mouse.wheel(0, -step)
            at_top = await scroller.evaluate("element => element.scrollTop < 1")
            last_at_top = at_top
        except Exception:
            break
        await page.wait_for_timeout(700 if at_top else 50)

    if not ordered_keys:
        return None
    return (
        "<!DOCTYPE html><html><body>"
        + "\n".join(fragment_by_key[key] for key in ordered_keys)
        + f'<div data-doubao-pending-messages="{len(pending_indices)}"></div>'
        + "</body></html>"
    )


def _is_empty_svg_placeholder(img) -> bool:
    """只识别豆包懒加载产生的空 SVG，不误删含实际图形的 SVG。"""
    src = str(img.get("src") or "")
    if not src.lower().startswith("data:image/svg+xml,"):
        return False
    try:
        svg = unquote(src.split(",", 1)[1]).strip()
    except (IndexError, ValueError):
        return False
    return bool(re.fullmatch(
        r"<svg\b[^>]*(?:/\s*>|>\s*</svg\s*>)",
        svg,
        flags=re.IGNORECASE | re.DOTALL,
    ))


def _remove_assistant_image_artifacts(msg) -> None:
    """移除豆包 AI 消息中的空占位图、生成图缩略图和重复界面图标。"""
    for picture in msg.find_all("picture"):
        image = picture.find("img")
        source = picture.find("source")
        if image and source:
            original = source.get("src") or source.get("data-src") or (source.get("srcset") or "").split(" ", 1)[0]
            if original and original.startswith(("http://", "https://")):
                image["src"] = original
            for duplicate in picture.find_all("source"):
                duplicate.decompose()
    images = list(msg.find_all("img"))
    kept_sources = set(prefer_original_generated_images([
        img.get("src") or img.get("data-src") for img in images
    ]))
    for img in images:
        src = str(img.get("src") or img.get("data-src") or "")
        if src not in kept_sources:
            img.decompose()
            continue
        src = str(img.get("src") or img.get("data-src") or "")
        alt = str(img.get("alt") or "").strip().lower()
        if (
            _is_empty_svg_placeholder(img)
            or alt == "asset cover"
            or "doc-canvas-card-fallback" in src.lower()
        ):
            img.decompose()

    images = list(msg.find_all("img"))
    reference_counts = Counter(
        str(img.get("src") or img.get("data-src") or "")
        for img in images
        if img.get("src") or img.get("data-src")
    )
    for img in images:
        classes = set(img.get("class") or ())
        reference = str(img.get("src") or img.get("data-src") or "")
        if "img-z0eKj1" in classes and reference_counts[reference] > 1:
            img.decompose()


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
    document_title_counts = Counter(
        ' '.join(title.get_text(' ', strip=True).split()).lower()
        for card in soup.find_all('div', class_=re.compile(r'^product-card-'))
        if '创建时间' in card.get_text(' ', strip=True)
        and (title := card.find('div', class_=re.compile(r'^card-content-info-title-text-')))
    )
    previous_user_attachment_only = False
    for msg in message_items:
        for decoration in msg.select(_DECORATIVE_IMAGES):
            decoration.decompose()
        for chrome in msg.select(
            'time, [data-testid="message_action_bar"], '
            '[data-testid="message_expand_all_button"], [data-testid="suggest_message_item"]'
        ):
            chrome.decompose()
        classes = msg.get('class', [])
        declared_role = str(msg.get('data-doubao-role') or '').lower()
        is_user = declared_role == 'user' or (
            not declared_role and 'justify-end' in classes
        )

        if not is_user:
            _remove_assistant_image_artifacts(msg)
            # 分享页在已结束的生成图配文后补“...”，原会话没有此尾缀。
            # 仅清理该段落，保留普通正文、代码与私有会话中的省略号。
            if not declared_role and msg.select_one('[class*="image-box-grid-"]'):
                for paragraph in msg.select('[class*="paragraph-"]'):
                    if paragraph.find_parent(['pre', 'code']):
                        continue
                    last = paragraph.contents[-1] if paragraph.contents else None
                    if isinstance(last, str):
                        cleaned = re.sub(r'(?<=[。！？!?])\.{3}\s*$', '', str(last))
                        if cleaned != str(last):
                            last.replace_with(cleaned)
            for thought_header in msg.select('[class*="thinking-title"]'):
                thought_header.decompose()
            for search_status in msg.select('[data-plugin-identifier*="search_query_result_block"] [data-copy-ignore]'):
                search_status.decompose()

        # 只把成功下载的真实图片替换为本地路径。豆包文档卡片还会
        # 内嵌 Asset cover/base64/fallback 装饰图，不能当成用户上传图片。
        for img in msg.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if src in image_map:
                img["src"] = image_map[src]

        if is_user:
            user_parts = []
            attached_names = set()
            local_image_paths = set(image_map.values())
            for img in msg.find_all("img"):
                src = img.get("src") or img.get("data-src")
                alt = (img.get("alt") or "").strip().lower()
                is_document_cover = (
                    alt == "asset cover"
                    or "doc-canvas-card-fallback" in (src or "")
                    or (src or "").startswith("data:image/")
                )
                if is_document_cover:
                    continue
                if src in local_image_paths:
                    user_parts.append(f"![用户图片]({src})")
                elif (src or "").startswith(("http://", "https://")):
                    user_parts.append(f"![用户图片]({src})")

            # 识别真实的 HTML 文件卡片（非全文正则）
            file_cards = msg.find_all(
                class_=re.compile(r'file|attachment|doc', re.I)
            )
            for card in file_cards:
                card_text = card.get_text(separator='\n', strip=True)
                match = re.search(
                    r'[^\\/:*?"<>|\n]{1,180}\.'
                    r'(?:docx|doc|pdf|txt|md|rtf|xlsx|xls|pptx|ppt|zip|rar|csv)'
                    r'(?![A-Za-z0-9_])',
                    card_text,
                    re.IGNORECASE
                )
                if match:
                    filename = match.group(0)
                    attached_names.add(filename.lower())
                    local_href = image_map.get(filename.lower())
                    if local_href:
                        user_parts.append(
                            f"[📄 {filename}]({local_href})"
                        )
                    else:
                        user_parts.append(
                            f"📎 **[上传文档]** `{filename}`"
                        )

            text = msg.get_text(separator='\n', strip=True)

            clean_lines = [
                line.strip()
                for line in text.split('\n')
                if len(line.strip()) > 0
                and line.strip().lower() not in attached_names
                and line.strip() not in [
                    "复制", "点赞", "踩", "分享", "已采纳",
                    "查看更多", "编辑", "朗读", "Word", "PDF", "文档"
                ]
                and not any(
                    "上传文档" in part and line.strip().lower() in part.lower()
                    for part in user_parts
                )
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
                if previous_user_attachment_only and parsed_messages and parsed_messages[-1]["role"] == "User":
                    parsed_messages[-1]["content"] += "\n\n" + final_text
                else:
                    parsed_messages.append({'role': 'User', 'content': final_text})
                previous_user_attachment_only = bool(user_parts) and not clean_lines
        else:
            message_node = msg if msg.get("data-message-id") else msg.find(attrs={"data-message-id": True})
            message_id = str(message_node.get("data-message-id") or "") if message_node else ""
            missing_generated_images = sum(
                not item.find(['img', 'video'])
                and not item.find(class_=re.compile(r'block-video-'))
                for item in msg.select('[class*="image-box-grid-item-"]')
            )
            video_links = []
            for block in msg.select('[class*="block-video-"]'):
                cover = block.select_one('img[class*="cover-"]')
                reference = cover.get('src', '') if cover else ''
                local_href = image_map.get(f'doubao-video:{reference}')
                video_links.append(
                    f'[🎬 下载视频]({local_href})' if local_href
                    else '🎬 **[视频]**（原视频未能下载）'
                )
                block.decompose()
            ai_document_links = []
            document_href = image_map.get(f"doubao-ai-doc-message:{message_id}")
            if document_href:
                ai_document_links.append(
                    f"[📄 查看 AI 生成文档完整正文]({document_href})"
                )
                for card in msg.select('[data-assembly-preview-card][data-office-artifact-status]'):
                    card.decompose()
            for card in msg.find_all(
                "div", class_=re.compile(r"^product-card-")
            ):
                if "创建时间" not in card.get_text(" ", strip=True):
                    continue
                title_node = card.find(
                    "div",
                    class_=re.compile(r"^card-content-info-title-text-"),
                )
                title = " ".join(
                    (
                        title_node.get_text(" ", strip=True)
                        if title_node else ""
                    ).split()
                )
                local_href = (
                    image_map.get(title.lower())
                    if title and document_title_counts[title.lower()] == 1 else None
                )
                if local_href and local_href not in "\n".join(ai_document_links):
                    link = f"[📄 查看 AI 生成文档：{title}]({local_href})"
                    if link not in ai_document_links:
                        ai_document_links.append(link)
                if document_href or local_href:
                    card.decompose()
                elif title:
                    ai_document_links.append(
                        f'📄 **[AI生成文档未下载]** `{title}.md`（未能下载完整正文）'
                    )
                    card.decompose()
            md_text = markdownify.markdownify(
                str(msg),
                heading_style="ATX"
            ).strip()
            if video_links:
                md_text = "\n\n".join([md_text, *video_links]).strip()
            if missing_generated_images:
                md_text = "\n\n".join([
                    md_text,
                    *(['🖼️ **[图片]**（网页中的原图片已失效或未能加载）']
                      * missing_generated_images),
                ]).strip()
            if ai_document_links:
                md_text = "\n\n".join([
                    md_text,
                    *ai_document_links,
                ]).strip()
            if md_text:
                parsed_messages.append({'role': 'AI', 'content': md_text})

    for key, local_href in image_map.items():
        if not isinstance(key, str) or not key.lower().startswith("doubao-ai-doc:"):
            continue
        title = key.split(":", 1)[1]
        if any(local_href in item["content"] for item in parsed_messages):
            continue
        target = next((
            item for item in reversed(parsed_messages)
            if item["role"] == "AI" and title.lower() in item["content"].lower()
        ), None)
        if target is None:
            target = next((
                item for item in reversed(parsed_messages) if item["role"] == "AI"
            ), None)
        if target is not None:
            target["content"] += (
                f"\n\n[📄 查看 AI 生成文档：{title}]({local_href})"
            )

    return parsed_messages
