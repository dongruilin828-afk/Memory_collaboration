"""DeepSeek 页面采集与消息解析。"""

import re

import markdownify
from bs4 import BeautifulSoup
from rich.console import Console
from . import deepseek_source


DISPLAY_NAME = "DeepSeek"
WAIT_SELECTOR = "[data-virtual-list-item-key] .ds-message"
HOSTS = ("chat.deepseek.com",)

console = Console()


def _replace_math_with_placeholders(node):
    """用唯一 LaTeX 源替换 KaTeX 多层 DOM，避免导出公式重复。"""
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

    for math in list(node.select('[role="math"][data-math-source]')):
        style = str(math.get("style") or "").replace(" ", "").lower()
        replace(
            math,
            math.get("data-math-source"),
            math.select_one(".katex-display") is not None
            or "display:block" in style,
        )

    for annotation in list(
        node.select('annotation[encoding="application/x-tex"]')
    ):
        katex = annotation.find_parent(class_="katex")
        if katex is None:
            continue
        display = katex.find_parent(class_="katex-display")
        replace(display or katex, annotation.get_text(), display is not None)

    return replacements


class _DeepSeekMarkdownConverter(markdownify.MarkdownConverter):
    def process_text(self, el, parent_tags=None):
        if 'pre' in (parent_tags or set()):
            return str(el)
        return super().process_text(el, parent_tags)

    def convert_pre(self, el, text, parent_tags):
        code = el.find('code')
        value = (code or el).get_text()
        fence = '`' * max(3, 1 + max((len(m[0]) for m in re.finditer(r'`+', value)), default=0))
        language = el.get('data-deepseek-language', '')
        return '\n\n' + fence + language + '\n' + value + ('' if value.endswith('\n') else '\n') + fence + '\n\n'

    def convert_br(self, el, text, parent_tags):
        return '<br>' if 'table' in parent_tags else super().convert_br(el, text, parent_tags)

    def convert_strong(self, el, text, parent_tags):
        return '<strong>' + text + '</strong>'

    convert_b = convert_strong

    def convert_em(self, el, text, parent_tags):
        return '<em>' + text + '</em>'

    convert_i = convert_em

    def convert_ul(self, el, text, parent_tags):
        result = super().convert_ul(el, text, parent_tags)
        if el.find_parent(['ul', 'ol']) is None:
            result += '\n\n<!-- DeepSeek list boundary -->\n\n'
        return result

    convert_ol = convert_ul


def _node_to_markdown(node, image_map, original=None):
    """将 DeepSeek 消息节点转换为保留公式和本地图片的 Markdown。"""
    content = BeautifulSoup(str(node), "html.parser")
    root = content.find()
    for removable in root.select(
        "script, style, noscript, button, .md-code-block-banner-wrap"
    ):
        removable.decompose()
    for hidden in root.select('.ds-markdown-cite span[style]'):
        if re.search(r'opacity\s*:\s*0(?:\D|$)', hidden.get('style', '')):
            hidden.decompose()
    for marker in root.find_all("span"):
        if marker.parent is None or marker.attrs is None:
            continue
        style = str(marker.get("style") or "").replace(" ", "").lower()
        hidden_dash = marker.find(
            "span",
            style=lambda value: value
            and "opacity:0" in value.replace(" ", "").lower(),
            string="-",
        )
        if (
            marker.find_parent("a") is None
            and "cursor:pointer" in style
            and hidden_dash is not None
            and marker.find("svg") is not None
        ):
            previous = marker.previous_sibling
            if isinstance(previous, str) and previous.endswith("-"):
                previous.replace_with(previous[:-1])
            marker.decompose()
    # A rendered Mermaid SVG does not contain its editable diagram source.
    diagrams = []
    if original:
        for part in original.get('fragments', []):
            if part.get('type') == 'RESPONSE':
                diagrams.extend(re.finditer(r'(?ms)^ {0,3}(`{3,}|~{3,})mermaid[^\n]*\n(.*?)^ {0,3}\1[ \t]*(?:\n|$)', part.get('content', '')))
    for svg, diagram in zip(root.select('svg[id^="mermaid"]'), diagrams):
        pre = content.new_tag('pre', attrs={'data-deepseek-language': 'mermaid'})
        code = content.new_tag('code'); code.string = diagram[2]; pre.append(code)
        svg.replace_with(pre)
    for img in root.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src in image_map:
            img["src"] = image_map[src]

    replacements = _replace_math_with_placeholders(root)
    text = _DeepSeekMarkdownConverter(heading_style="ATX", escape_misc=True).convert(str(root)).strip()
    for token, latex in replacements.items():
        def restore(match):
            if not latex.startswith('\n\n$$'):
                return latex
            before = text[text.rfind('\n', 0, match.start()) + 1:match.start()]
            leading = re.match(r'([ \t]*(?:>[ \t]*)*)([ \t]*)(?:([-+*]|\d+\.)[ \t]+)?', before)
            prefix = leading[1] + leading[2]
            if leading[3]:
                prefix += ' ' * (len(leading[0]) - len(prefix))
            if prefix:
                # Some Markdown readers do not parse indented/quoted $$ blocks.
                # Keep the container intact and use its supported inline delimiter
                # with display-style TeX; matrix row breaks (\\) stay literal.
                body = latex.strip()[2:-2].strip()
                body = re.sub(r'(?m)(^|[^\\])((?:\\\\)*)%[^\n]*', r'\1\2', body).replace('\n', ' ')
                return '$\\displaystyle ' + body + '$'
            return '\n\n' + '\n'.join(prefix + line for line in latex.strip('\n').split('\n')) + '\n\n' + prefix
        text = re.sub(re.escape(token), restore, text)
    return text


async def collect_html(page):
    """逐屏收集 DeepSeek 虚拟列表中的消息，避免超长分享对话丢失。"""
    item_selector = "[data-virtual-list-item-key]"
    if await page.locator(f"{item_selector} .ds-message").count() == 0:
        return None

    source = None
    source_error = ""
    try:
        source = await deepseek_source.read_conversation(page)
    except Exception as error:
        source_error = str(error) if isinstance(error, deepseek_source.SourceError) else type(error).__name__
        console.print(f"[dim]DeepSeek 原站消息核验暂不可用：{source_error}[/dim]")

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
        for _ in range(max(500, 20 * len(source["messages"])) if source else 500):
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

            step = max(int(metrics["clientHeight"] * 0.5), 100)
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
            source_html = ""
            if source:
                expected = [str(m["message_id"]) for m in source["messages"]]
                missing = set(expected) - set(captured)
                if missing:
                    source_error = f"当前分支仍有 {len(missing)} 条消息未在页面中采集，不能宣称完整。"
                ordered_items = [captured[key] for key in expected if key in captured]
                source_html = deepseek_source.embed_source(source)
                console.print(f"[dim]已核对 DeepSeek 当前分支：{len(ordered_items)}/{len(expected)} 条消息。[/dim]")
            if source_error:
                from html import escape
                source_html += '<meta name="deepseek-source-error" content="' + escape(source_error, quote=True) + '">'
            console.print(
                f"[dim]已从 DeepSeek 虚拟列表中收集 "
                f"{len(ordered_items)} 条消息。[/dim]"
            )
            item_html = "\n".join(item["html"] for item in ordered_items)
            return f"<!DOCTYPE html><html><body>{item_html}{source_html}</body></html>"

    except Exception as e:
        console.print(
            f"[dim]提示: DeepSeek 虚拟列表收集失败，将使用当前页面快照: {e}[/dim]"
        )
    finally:
        if scroll_container is not None:
            await scroll_container.dispose()

    return None


def parse_messages(soup, image_map=None):
    """解析 DeepSeek 分享页；页面不属于 DeepSeek 时返回 None。"""
    if soup.select_one(WAIT_SELECTOR) is None:
        return None
    if image_map is None:
        image_map = {}

    parsed_messages = []
    source = deepseek_source.source_from_soup(soup)
    source_messages = {str(m["message_id"]): m for m in source["messages"]} if source else {}
    name_counts = deepseek_source.name_counts(source or {})
    ignored_ui_text = {
        "复制", "重新生成", "编辑", "分享", "下载", "点赞", "踩"
    }
    attachment_name_pattern = re.compile(
        r'^[^\\/:*?"<>|\n]+\.(?:png|jpe?g|webp|gif|bmp|svg|pdf|docx?|'
        r'xlsx?|pptx?|txt|csv|md|rtf|zip|rar)$',
        re.IGNORECASE
    )
    attachment_size_pattern = re.compile(
        r'^(?:PNG|JPE?G|WEBP|GIF|BMP|SVG|PDF|DOCX?|XLSX?|PPTX?|TXT|CSV|MD|RTF|ZIP|RAR)'
        r'\s+\d+(?:\.\d+)?\s*(?:B|KB|MB|GB)$',
        re.IGNORECASE
    )

    for item in soup.select('[data-virtual-list-item-key]'):
        original = source_messages.get(item.get('data-virtual-list-item-key'))
        if source and original is None:
            continue
        message_node = item.select_one('.ds-message')
        if message_node is None:
            continue

        answer_node = item.select_one('.ds-assistant-message-main-content')
        if answer_node is not None:
            md_text = _node_to_markdown(answer_node, image_map, original)
            if md_text or (original and original.get("role") == "ASSISTANT") or item.select_one('.ds-think-content'):
                message = {'role': 'AI', 'content': md_text}
                if original:
                    message['source_id'] = original['message_id']
                thinking_node = item.select_one('.ds-think-content')
                if thinking_node is not None:
                    reasoning = _node_to_markdown(thinking_node, image_map)
                    if reasoning:
                        message['reasoning'] = reasoning
                parsed_messages.append(message)
            continue

        if (original and original.get("role") == "ASSISTANT") or item.select_one('.ds-think-content'):
            thinking = item.select_one('.ds-think-content')
            message = {'role': 'AI', 'content': ''}
            if original:
                message['source_id'] = original['message_id']
            if thinking is not None:
                message['reasoning'] = _node_to_markdown(thinking, image_map)
            parsed_messages.append(message)
            continue

        if original and original.get("role") == "USER":
            parts = []
            for fragment in original.get("fragments", []):
                if isinstance(fragment.get("content"), str):
                    parts.append(fragment["content"])
                for file in fragment.get("files", []):
                    name = file.get("file_name") or "附件"
                    label = re.sub(r'([\\\[\]*_`])', r'\\\1', name)
                    href = deepseek_source.file_href(file, image_map, name_counts)
                    if deepseek_source.is_image(file):
                        parts.append(f'![{label}]({href})' if href else f'🖼️ **[用户上传图片]** `{name}`（DeepSeek 原文件未能下载）')
                    else:
                        label = label.replace(r'\[', '&#91;').replace(r'\]', '&#93;')
                        parts.append(f'[📄 {label}]({href})' if href else f'📎 **[上传文件]** `{name}`（原文件未能下载）')
            parsed_messages.append({'role': 'User', 'content': '\n\n'.join(parts), 'source_id': original['message_id']})
            continue

        user_soup = BeautifulSoup(str(message_node), 'html.parser')
        user_message = user_soup.select_one('.ds-message')
        user_parts = []
        # The visible input is plain Markdown in a pre-wrapped span. Its blank
        # lines and indentation are content, not UI whitespace.
        input_node = user_message.select_one('.ds-collapsible-text')
        input_text = None
        if input_node is not None:
            for br in input_node.find_all('br'):
                br.replace_with('\n')
            input_text = input_node.get_text(separator='', strip=False)
            input_node.decompose()

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
            for line in user_message.get_text(
                separator='\n',
                strip=True
            ).split('\n')
            if line.strip()
        ]
        clean_lines = []
        index = 0
        while index < len(raw_lines):
            line = raw_lines[index]
            next_line = (
                raw_lines[index + 1]
                if index + 1 < len(raw_lines)
                else ''
            )
            if (
                attachment_name_pattern.match(line)
                and attachment_size_pattern.match(next_line)
            ):
                local_href = image_map.get(line.lower())
                if local_href:
                    user_parts.append(
                        f'[📄 {line}]({local_href})（{next_line}）'
                    )
                else:
                    user_parts.append(
                        f'📎 **[上传文件]** `{line}`（{next_line}）'
                    )
                index += 2
                continue
            if line not in ignored_ui_text:
                clean_lines.append(line)
            index += 1

        if input_text is not None:
            user_parts.append(input_text)
        elif clean_lines:
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
