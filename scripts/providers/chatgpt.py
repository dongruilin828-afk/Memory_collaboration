"""ChatGPT 页面采集与消息解析。"""

import re

import markdownify
from rich.console import Console


DISPLAY_NAME = "ChatGPT"
WAIT_SELECTOR = (
    "[data-message-author-role], "
    "[data-chatgpt-search-unit-key$=':user'], "
    "[data-chatgpt-search-unit-key$=':assistant']"
)
HOSTS = ("chatgpt.com", "chat.openai.com")

console = Console()

SCROLL_PRIMARY_SETTLE_MS = 400
SCROLL_SECONDARY_SETTLE_MS = 150
BOUNDARY_SETTLE_MS = 350
BOUNDARY_CAPTURE_ROUNDS = 3
TOP_PRELOAD_SETTLE_MS = 800
TOP_PRELOAD_STABLE_ROUNDS = 10
TOP_PRELOAD_NO_GROWTH_ROUNDS = 20
TOP_PRELOAD_SAFETY_ROUNDS = 2000
SCROLL_BOTTOM_STABLE_ROUNDS = 10
SCROLL_NO_GROWTH_ROUNDS = 100
SCROLL_SAFETY_ROUNDS = 5000


def _prefer_snapshot(candidate, existing):
    """仅在文本或图片更完整且另一维不退步时替换消息快照。"""
    candidate_text = int(candidate.get("text_length") or 0)
    existing_text = int(existing.get("text_length") or 0)
    candidate_images = int(candidate.get("image_score") or 0)
    existing_images = int(existing.get("image_score") or 0)
    if existing_text == 0 and candidate_text > 0:
        return True
    return (
        candidate_text > existing_text
        and candidate_images >= existing_images
    ) or (
        candidate_images > existing_images
        and candidate_text >= existing_text
    )


def _sort_captured_messages(captured, route_message_ids):
    """优先按路由中的稳定消息 ID 排序，缺失时退回页面观察顺序。"""
    route_order = {}
    for index, route_message in enumerate(route_message_ids or []):
        ids = route_message if isinstance(route_message, list) else [route_message]
        route_order.update((message_id, index) for message_id in ids if message_id)

    def route_index(message):
        ids = message.get("ids") or [message["key"]]
        return min((route_order[id_] for id_ in ids if id_ in route_order), default=None)

    if route_order:
        matched = [message for message in captured.values() if route_index(message) is not None]
        if matched:
            ordered = sorted(matched, key=route_index)
            for message in sorted(
                (
                    message for message in captured.values()
                    if route_index(message) is None
                ),
                key=lambda message: message["discovery_index"],
            ):
                next_discovered = next((
                    candidate for candidate in matched
                    if candidate["discovery_index"] > message["discovery_index"]
                ), None)
                if next_discovered is None:
                    ordered.append(message)
                else:
                    ordered.insert(ordered.index(next_discovered), message)
            return ordered
    return sorted(
        captured.values(),
        key=lambda message: (
            message["order"] is None,
            message["order"]
            if message["order"] is not None
            else message["discovery_index"],
        ),
    )


def _collapse_nested_markdown_fences(text):
    """将 ChatGPT 偶发生成的双层 Markdown 代码围栏折叠为单层。"""
    fence = chr(96) * 3
    lines = text.splitlines(keepends=True)
    cleaned = []
    index = 0

    def is_fence(line):
        return line.strip().startswith(fence)

    while index < len(lines):
        # markdownify 偶尔产生“围栏 / 围栏 / 正文 / 围栏 / 围栏”。
        # 只折叠这一完整、对称的双层结构，不碰普通代码块。
        if (
            index + 1 < len(lines)
            and is_fence(lines[index])
            and is_fence(lines[index + 1])
        ):
            closing_index = index + 2
            while closing_index + 1 < len(lines):
                if (
                    is_fence(lines[closing_index])
                    and is_fence(lines[closing_index + 1])
                ):
                    cleaned.extend(lines[index + 1:closing_index + 1])
                    index = closing_index + 2
                    break
                closing_index += 1
            else:
                cleaned.append(lines[index])
                index += 1
            continue

        cleaned.append(lines[index])
        index += 1

    return "".join(cleaned)


def _replace_math_with_placeholders(message):
    """提取 ChatGPT 公式源并以占位符保护，避免 Markdown 转换破坏 LaTeX。"""
    replacements = {}
    counter = 0

    def replace(target, latex, display):
        nonlocal counter
        latex = str(latex or "").strip()
        if not latex:
            return
        token = f"AIMEMORYMATHPLACEHOLDER{counter:04d}Z"
        counter += 1
        replacements[token] = (
            f"\n\n$$\n{latex}\n$$\n\n" if display else f"${latex}$"
        )
        target.replace_with(token)

    # 当前 ChatGPT 把绝大多数公式源放在外层 role=math 节点中。
    for node in list(message.select('[role="math"][data-math-source]')):
        style = str(node.get("style") or "").replace(" ", "").lower()
        display = (
            node.select_one(".katex-display") is not None
            or "display:block" in style
        )
        replace(node, node.get("data-math-source"), display)

    # 兼容仍使用标准 KaTeX MathML annotation 的旧式公式节点。
    for annotation in list(
        message.select('annotation[encoding="application/x-tex"]')
    ):
        katex = annotation.find_parent(class_="katex")
        if katex is None:
            continue
        display_container = katex.find_parent(class_="katex-display")
        replace(
            display_container or katex,
            annotation.get_text(),
            display_container is not None,
        )

    return replacements


def _restore_math_placeholders(text, replacements):
    for token, latex in replacements.items():
        text = text.replace(token, latex)
    return text


async def collect_html(page):
    """逐屏收集 ChatGPT 虚拟列表中的消息，避免长对话首尾丢失。"""
    role_selector = (
        f'{WAIT_SELECTOR}, '
        '[data-testid^="conversation-turn-"][data-turn="assistant"]'
        ':not(:has([data-message-author-role]))'
    )
    if await page.locator(role_selector).count() == 0:
        return None

    scroll_container = None
    captured = {}
    discovery_index = 0

    async def capture_visible_messages():
        """复采当前消息；保留文本和真实图片均不退步的较完整快照。"""
        nonlocal discovery_index
        visible_messages = await page.locator(role_selector).evaluate_all(
            """elements => elements.map(element => {
                const turn = element.closest(
                    '[data-testid^="conversation-turn-"]'
                );
                const testId = turn
                    ? turn.getAttribute('data-testid') || ''
                    : '';
                const searchKey = element.getAttribute(
                    'data-chatgpt-search-unit-key'
                ) || '';
                const turnMatch = testId.match(/(\\d+)$/)
                    || searchKey.match(/^fallback-turn-(\\d+):/);
                const selectionNode = element.matches(
                    '[data-chatgpt-selection-message-id]'
                ) ? element : element.querySelector(
                    '[data-chatgpt-selection-message-id]'
                );
                const searchMessageIds = element.getAttribute(
                    'data-chatgpt-search-message-ids'
                ) || '';
                const messageId =
                    element.getAttribute('data-message-id')
                    || (turn && turn.getAttribute('data-message-id'))
                    || (turn && turn.querySelector('[data-message-id]')
                        && turn.querySelector('[data-message-id]')
                            .getAttribute('data-message-id'))
                    || (selectionNode && selectionNode.getAttribute(
                        'data-chatgpt-selection-message-id'
                    ))
                    || searchMessageIds.trim().split(/\s+/)[0]
                    || '';
                const stableIds = Array.from(new Set([
                    messageId,
                    turn && turn.getAttribute('data-turn-id'),
                    turn && turn.getAttribute('data-turn-id-container'),
                ].filter(Boolean)));
                const role = element.getAttribute('data-message-author-role')
                    || (turn ? turn.getAttribute('data-turn') : '')
                    || (searchKey.match(/:(user|assistant)$/) || [])[1]
                    || '';
                const text =
                    element.innerText || element.textContent || '';
                const stableText = (element.textContent || text)
                    .replace(/\s+/g, ' ').trim();
                const imageScore = Array.from(
                    element.querySelectorAll('img')
                ).filter(image => {
                    const src = image.getAttribute('src')
                        || image.getAttribute('data-src') || '';
                    return src && !src.startsWith('data:image/svg');
                }).length;
                // fallback-turn-* 是会被虚拟列表重复利用的槽位，不是消息 ID。
                const stableKey = messageId || role + ':' + stableText;
                return {
                    key: stableKey,
                    ids: stableIds,
                    boundary_key: stableKey,
                    order: turnMatch ? Number(turnMatch[1]) : null,
                    text_length: text.length,
                    image_score: imageScore,
                    html: (() => {
                        const snapshot = (turn || element).cloneNode(true);
                        if (!snapshot.hasAttribute('data-message-author-role')) {
                            snapshot.setAttribute('data-message-author-role', role);
                        }
                        return snapshot.outerHTML;
                    })()
                };
            })"""
        )

        for message in visible_messages:
            key = message["key"]
            existing = captured.get(key)
            if existing is None:
                message["discovery_index"] = discovery_index
                captured[key] = message
                discovery_index += 1
            elif _prefer_snapshot(message, existing):
                observed_orders = [
                    order for order in (
                        existing.get("order"), message.get("order")
                    )
                    if order is not None
                ]
                if observed_orders:
                    message["order"] = min(observed_orders)
                message["discovery_index"] = existing["discovery_index"]
                captured[key] = message
            elif message.get("order") is not None:
                existing_order = existing.get("order")
                if existing_order is None or message["order"] < existing_order:
                    existing["order"] = message["order"]

        return [message["boundary_key"] for message in visible_messages]

    try:
        scroll_container = await page.locator(role_selector).first.evaluate_handle(
            """element => {
                const messageSelector = [
                    '[data-message-author-role]',
                    '[data-chatgpt-search-unit-key$=":user"]',
                    '[data-chatgpt-search-unit-key$=":assistant"]'
                ].join(',');
                const candidates = [];
                let current = element;
                while (current) {
                    const style = window.getComputedStyle(current);
                    const canScroll = current.scrollHeight > current.clientHeight + 1;
                    if (canScroll && /(auto|scroll)/.test(style.overflowY)) {
                        candidates.push(current);
                    }
                    current = current.parentElement;
                }
                return candidates.sort((left, right) =>
                    right.querySelectorAll(messageSelector).length
                    - left.querySelectorAll(messageSelector).length
                    || (right.scrollHeight - right.clientHeight)
                    - (left.scrollHeight - left.clientHeight)
                )[0] || document.scrollingElement || document.documentElement;
            }"""
        )

        is_reverse = await scroll_container.evaluate(
            """element => {
                const initial = element.scrollTop;
                element.scrollTo(0, 1);
                const positive = element.scrollTop;
                element.scrollTo(0, -1);
                const negative = element.scrollTop;
                element.scrollTo(0, initial);
                return positive === 0 && negative < 0;
            }"""
        )

        # ChatGPT 到达顶部后会异步补挂更早消息，并让既有 turn 编号整体后移。
        # 虚拟列表高度会因节点换页反复变化，只以消息数连续稳定判断加载完成。
        previous_state = None
        stable_rounds = 0
        previous_capture_count = len(captured)
        no_growth_rounds = 0
        for _ in range(TOP_PRELOAD_SAFETY_ROUNDS):
            # 反向虚拟列表以负 scrollTop 表示更早消息；普通列表顶部仍为 0。
            await scroll_container.evaluate(
                """(element, reverse) => element.scrollTo(
                    0, reverse ? -element.scrollHeight : Math.min(240, element.scrollHeight)
                )""",
                is_reverse,
            )
            await page.wait_for_timeout(100)
            if not is_reverse:
                await scroll_container.evaluate(
                    "element => element.scrollTo(0, 0)"
                )
            await page.wait_for_timeout(TOP_PRELOAD_SETTLE_MS)
            visible_keys = await capture_visible_messages()
            state = tuple(visible_keys[:2])
            if state == previous_state:
                stable_rounds += 1
            else:
                stable_rounds = 0
            previous_state = state
            capture_count = len(captured)
            if capture_count == previous_capture_count:
                no_growth_rounds += 1
            else:
                no_growth_rounds = 0
                previous_capture_count = capture_count
            if (
                stable_rounds >= TOP_PRELOAD_STABLE_ROUNDS
                or no_growth_rounds >= TOP_PRELOAD_NO_GROWTH_ROUNDS
            ):
                break

        # 保留预热阶段已经出现过的历史消息。ChatGPT 的虚拟列表在顶部
        # 补挂旧消息后，正式向下遍历时不一定会再次挂载每一个中间节点。
        # capture_visible_messages 会持续更新同一 message-id 的最终 turn 顺序。
        initial_metrics = await scroll_container.evaluate(
            """element => ({
                scrollTop: element.scrollTop,
                scrollHeight: element.scrollHeight,
                clientHeight: element.clientHeight
            })"""
        )
        scroll_top = int(initial_metrics["scrollTop"])
        max_scroll_top = 0
        previous_bottom_state = None
        bottom_stable_rounds = 0
        previous_bottom_capture_count = len(captured)
        bottom_no_growth_rounds = 0
        for _ in range(SCROLL_SAFETY_ROUNDS):
            await scroll_container.evaluate(
                "(element, top) => element.scrollTo(0, top)",
                scroll_top
            )
            await page.wait_for_timeout(SCROLL_PRIMARY_SETTLE_MS)

            await capture_visible_messages()
            await page.wait_for_timeout(SCROLL_SECONDARY_SETTLE_MS)
            visible_keys = await capture_visible_messages()

            capture_count = len(captured)
            if capture_count == previous_bottom_capture_count:
                bottom_no_growth_rounds += 1
            else:
                bottom_no_growth_rounds = 0
                previous_bottom_capture_count = capture_count
            if bottom_no_growth_rounds >= SCROLL_NO_GROWTH_ROUNDS:
                break

            metrics = await scroll_container.evaluate(
                """element => ({
                    scrollTop: element.scrollTop,
                    scrollHeight: element.scrollHeight,
                    clientHeight: element.clientHeight
                })"""
            )
            max_scroll_top = max(
                0,
                metrics["scrollHeight"] - metrics["clientHeight"]
            )
            current_top = int(metrics["scrollTop"])
            at_bottom = current_top >= -1 if is_reverse else current_top >= max_scroll_top - 1
            if at_bottom:
                bottom_state = tuple(visible_keys[-2:])
                if bottom_state == previous_bottom_state:
                    bottom_stable_rounds += 1
                else:
                    bottom_stable_rounds = 0
                previous_bottom_state = bottom_state
                if bottom_stable_rounds >= SCROLL_BOTTOM_STABLE_ROUNDS:
                    break
                scroll_top = 0 if is_reverse else max_scroll_top
                continue

            previous_bottom_state = None
            bottom_stable_rounds = 0
            step = max(int(metrics["clientHeight"] * 0.5), 800)
            scroll_top = (
                min(current_top + step, 0)
                if is_reverse
                else min(current_top + step, max_scroll_top)
            )

        # 首尾媒体均可能延迟挂载；回访边界并只接受图片更完整的快照。
        boundaries = (0, -max_scroll_top) if is_reverse else (max_scroll_top, 0)
        for boundary in boundaries:
            await scroll_container.evaluate(
                "(element, top) => element.scrollTo(0, top)",
                boundary
            )
            for _ in range(BOUNDARY_CAPTURE_ROUNDS):
                await page.wait_for_timeout(BOUNDARY_SETTLE_MS)
                await capture_visible_messages()

        captured_ids = list({
            id_
            for message in captured.values()
            for id_ in (message.get("ids") or [message["key"]])
        })
        route_message_ids = await page.evaluate(
            """(capturedIds) => {
                const root = window.__reactRouterDataRouter?.state?.loaderData;
                const captured = new Set(capturedIds);
                const seen = new WeakSet();
                let longest = [];
                let bestMatches = -1;
                function keep(candidate) {
                    const messages = candidate
                        .map(item => ({
                            message: item?.message,
                            nodeId: item?.id || '',
                        }))
                        .filter(item => item.message?.id);
                    const matches = messages.filter(item =>
                        captured.has(item.message.id) || captured.has(item.nodeId)
                    ).length;
                    if (matches < bestMatches
                        || (matches === bestMatches
                            && messages.length <= longest.length)) return;
                    bestMatches = matches;
                    longest = messages.map(({message, nodeId}) =>
                        Array.from(new Set([
                            message.id, nodeId,
                        ].filter(Boolean)))
                    );
                }
                function find(value) {
                    if (!value || typeof value !== 'object' || seen.has(value)) return;
                    seen.add(value);
                    if (Array.isArray(value)) {
                        for (const item of value) find(item);
                        return;
                    }
                    if (Array.isArray(value.linear_conversation)) {
                        keep(value.linear_conversation);
                    }
                    if (value.mapping && typeof value.mapping === 'object') {
                        const branch = [];
                        let nodeId = value.current_node;
                        while (nodeId && value.mapping[nodeId]) {
                            const node = value.mapping[nodeId];
                            branch.push({...node, id: node?.id || nodeId});
                            nodeId = node.parent;
                        }
                        keep(branch.length ? branch.reverse() : Object.entries(
                            value.mapping
                        ).map(([id, node]) => ({
                            ...node, id: node?.id || id,
                        })));
                    }
                    for (const item of Object.values(value)) find(item);
                }
                find(root);
                return longest;
            }""",
            captured_ids,
        )
        ordered_messages = _sort_captured_messages(
            captured, route_message_ids
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

    for message in soup.select("[data-chatgpt-search-unit-key]"):
        match = re.search(
            r":(user|assistant)$",
            message.get("data-chatgpt-search-unit-key", ""),
        )
        if match and not message.get("data-message-author-role"):
            message["data-message-author-role"] = match.group(1)

    chatgpt_messages = [
        message for message in soup.find_all(
            attrs={"data-message-author-role": True}
        )
        if message.find_parent(attrs={"data-message-author-role": True}) is None
    ]
    if not chatgpt_messages:
        return None

    parsed_messages = []
    for msg in chatgpt_messages:
        role = msg.get("data-message-author-role")
        math_replacements = _replace_math_with_placeholders(msg)
        if role == "user":
            for excluded in msg.select(
                '[data-markdown-copy="exclude"], [aria-hidden="true"], '
                '.sr-only, .cdk-visually-hidden'
            ):
                excluded.decompose()
            content_parts = []
            message_container = msg.find_parent(
                attrs={"data-testid": re.compile(r"^conversation-turn-")}
            ) or msg
            seen_document_names = set()
            # 提取用户发送的所有图片 (精准映射本地路径)
            for img in msg.find_all("img"):
                src = img.get("src") or img.get("data-src")
                alt = img.get("alt", "用户上传图片")
                if src and not src.startswith("data:image/svg"):
                    local_src = image_map.get(src, src)
                    content_parts.append(f"![{alt}]({local_src})")

            # 精准检查显示的文件卡片或下载链接（排除纯文本里的误触发）
            for a in message_container.find_all("a", href=True):
                href = a["href"]
                link_text = a.get_text(strip=True) or "附件文件"
                if (
                    (href.startswith("http") or href.startswith("/"))
                    and any(
                        ext in link_text.lower()
                        for ext in [
                            '.doc', '.pdf', '.txt', '.xls', '.ppt',
                            '.zip', '.rar', '.csv', '.md', '.rtf',
                            '.mp4', '.mov', '.webm', '.m4v', '.avi', '.mkv'
                        ]
                    )
                ):
                    local_href = image_map.get(
                        href, image_map.get(link_text.lower(), href)
                    )
                    content_parts.append(
                        f"[📄 {link_text}]({local_href})"
                    )
                    seen_document_names.add(link_text.lower())

            # 识别真实的 HTML 文件卡片节点（非纯文本正则）
            file_cards = list(message_container.find_all(
                class_=re.compile(r'file|attachment|document', re.I)
            ))
            # ChatGPT 当前版文件卡片的标题节点不再带 file/attachment 类名。
            # 仅补充平台稳定使用的真实标题节点，避免扫描普通消息文本。
            for title in message_container.select("div.truncate.font-semibold"):
                if title not in file_cards:
                    file_cards.append(title)
            for card in file_cards:
                card_text = card.get_text(strip=True)
                if any(
                    ext in card_text.lower()
                    for ext in [
                        '.doc', '.pdf', '.txt', '.xls', '.ppt',
                        '.zip', '.rar', '.csv', '.md', '.rtf',
                        '.mp4', '.mov', '.webm', '.m4v', '.avi', '.mkv'
                    ]
                ):
                    # 提炼出真正文件名
                    match = re.search(
                        r'[\w\-()"\u4e00-\u9fa5\“\”]+\.'
                        r'(?:docx|doc|pdf|txt|md|rtf|xlsx|xls|pptx|ppt|zip|rar|csv|mp4|mov|webm|m4v|avi|mkv)',
                        card_text,
                        re.IGNORECASE
                    )
                    if match:
                        filename = match.group(0)
                        if filename.lower() in seen_document_names:
                            continue
                        seen_document_names.add(filename.lower())
                        local_href = image_map.get(filename.lower())
                        if local_href:
                            content_parts.append(
                                f"[📄 {filename}]({local_href})"
                            )
                        else:
                            content_parts.append(
                                f"📎 **[上传文档]** `{filename}`"
                            )



            text = msg.get_text(separator='\n', strip=True)
            if any(part.startswith("![") for part in content_parts):
                text = '\n'.join(
                    line for line in text.splitlines()
                    if line.strip() != '已上传图片'
                ).strip()
            text_lines = {line.strip().lower() for line in text.splitlines()}
            for filename, local_href in image_map.items():
                lowered = str(filename).lower()
                if (
                    "/" not in lowered
                    and "\\" not in lowered
                    and lowered in text_lines
                    and re.search(
                        r'\.(?:docx?|pdf|txt|md|rtf|xlsx?|pptx?|csv|mp4|mov|webm|m4v|avi|mkv)$',
                        lowered,
                    )
                    and lowered not in seen_document_names
                ):
                    content_parts.append(f"[📄 {filename}]({local_href})")
                    seen_document_names.add(lowered)
            if seen_document_names:
                text = '\n'.join(
                    line for line in text.splitlines()
                    if line.strip() != '上传文件'
                    and line.strip().lower() not in seen_document_names
                ).strip()
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
            final_user_text = _restore_math_placeholders(
                final_user_text, math_replacements
            )
            parsed_messages.append({
                'role': 'User',
                'content': final_user_text
            })

        elif role == "assistant":
            content = msg.select_one(
                ".markdown, [data-markdown-text-style='assistant-message']"
            )
            if content is None and msg.find(
                ["p", "pre", "ol", "ul", "table", "blockquote", "img"]
            ):
                content = msg
            if content is None:
                continue

            # ChatGPT 新版代码块把“纯文本”等工具栏和代码并列放置。
            for block in list(content.select("[data-markdown-copy='code-block']")):
                code = block.find("code")
                if code is None:
                    continue
                new_pre = soup.new_tag("pre")
                new_code = soup.new_tag("code")
                new_code.string = code.get_text()
                new_pre.append(new_code)
                block.replace_with(new_pre)

            # 引用卡片图标不是消息图片，仅保留外层引用链接。
            for img in list(content.select("a[data-testid='chatgpt-citation'] img")):
                img.decompose()

            # 替换本地图片路径，并移除生成图的重复展示节点。
            seen_image_sources = set()
            for img in list(content.find_all("img")):
                src = img.get("src") or img.get("data-src")
                if src in seen_image_sources:
                    img.decompose()
                    continue
                seen_image_sources.add(src)
                if src in image_map:
                    img["src"] = image_map[src]

            # 修复 ChatGPT 嵌套 <pre> 导致 markdownify 生成多重/错误代码块的问题
            for pre in content.find_all("pre"):
                inner_pre = pre.find("pre")
                if inner_pre:
                    code_text = inner_pre.get_text()
                    # 构造标准 <pre><code> 避免嵌套冲突；不依赖易变化的类名
                    new_pre = soup.new_tag("pre")
                    new_code = soup.new_tag("code")
                    new_code.string = code_text
                    new_pre.append(new_code)
                    pre.replace_with(new_pre)

            md_text = markdownify.markdownify(
                str(content),
                heading_style="ATX"
            ).strip()
            md_text = _collapse_nested_markdown_fences(md_text)
            md_text = _restore_math_placeholders(md_text, math_replacements)
            if md_text:
                parsed_messages.append({'role': 'AI', 'content': md_text})

    return parsed_messages
