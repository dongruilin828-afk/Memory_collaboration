"""Identity-checked ChatGPT source messages, independent of virtualized DOM order."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlencode, urlparse


HOSTS = {"chatgpt.com", "chat.openai.com"}
UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
FILE_ID = re.compile(r"file[_-][A-Za-z0-9_-]+")
FENCE = re.compile(r"^(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$", re.M | re.S)
SANDBOX_LINK = re.compile(r"\[([^\]]+)\]\((sandbox:[^)]+)\)")


class SourceError(RuntimeError):
    """The requested conversation cannot be identified or read completely."""


def conversation_target(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in HOSTS:
        raise SourceError("不是 ChatGPT 会话链接。")
    match = re.fullmatch(rf"/share/({UUID})/?", parsed.path)
    if match:
        return "share", match[1].lower()
    match = re.fullmatch(rf"/(?:g/[^/]+/)?c/({UUID})/?", parsed.path)
    if match:
        return "conversation", match[1].lower()
    raise SourceError("ChatGPT 链接缺少有效会话 ID。")


def current_branch(payload: dict, url: str) -> list[dict]:
    _, expected = conversation_target(url)
    if str(payload.get("conversation_id") or "").lower() != expected:
        raise SourceError("原站返回的会话 ID 与请求不一致，已拒绝导出其它会话。")
    mapping = payload.get("mapping")
    node_id = payload.get("current_node")
    if not isinstance(mapping, dict) or not node_id:
        raise SourceError("原站未返回完整会话分支，无法确认消息完整性。")
    branch, seen = [], set()
    while node_id:
        if node_id in seen or node_id not in mapping:
            raise SourceError("原站会话分支缺失或循环，无法确认消息完整性。")
        seen.add(node_id)
        node = mapping[node_id]
        branch.append(node)
        node_id = node.get("parent")
    return list(reversed(branch))


async def read_conversation(page, url: str) -> dict:
    """Use only the exact authorized endpoint, never the longest cached conversation."""
    route, identifier = conversation_target(url)
    result = {}
    for attempt in range(3):
        try:
            result = await page.evaluate("""async endpoint => {
                if (!['chatgpt.com','chat.openai.com'].includes(location.hostname))
                    return {status: 0};
                const options={credentials:'include',signal:AbortSignal.timeout(45000)};
                try {
                    const r=await fetch('/api/auth/session',{credentials:'include',signal:AbortSignal.timeout(15000)});
                    if(r.ok){
                        const session=await r.json();
                        const token=session.accessToken||session.access_token;
                        if(token)options.headers={Authorization:'Bearer '+token};
                    }
                } catch {}
                const r=await fetch(endpoint,options);
                let data=null;try{data=await r.json();}catch{}
                return {status:r.status,data};
            }""", f"/backend-api/{route}/{identifier}")
            if result.get("status") == 200 and isinstance(result.get("data"), dict):
                current_branch(result["data"], url)
                return result["data"]
        except SourceError:
            raise
        except Exception:
            # Browser errors can contain session URLs; do not expose them.
            result = {"status": 0}
        if attempt < 2:
            await page.wait_for_timeout(1500)
            # Session hydration and challenge pages can temporarily return 403.
            # Retry normal navigation, then the *same* conversation endpoint;
            # never substitute another conversation from history or route cache.
            if result.get("status") in {0, 401, 403}:
                try:
                    destination = url.replace("http://", "https://") if attempt == 0 else "https://chatgpt.com/"
                    await page.goto(destination, wait_until="domcontentloaded", timeout=45000)
                    await page.wait_for_timeout(4000)
                except Exception:
                    pass
    raise SourceError(f"无法核验目标 ChatGPT 会话（HTTP {result.get('status', 0)}），请确认登录与访问权限后重试。")


@dataclass
class Asset:
    key: str
    name: str
    kind: str
    endpoint: str
    source_reference: str = ""


@dataclass
class Message:
    id: str
    role: str
    ids: list[str]
    text: str
    exchange_id: str = ""
    rich: bool = False
    assets: list[Asset] = field(default_factory=list)
    metadata: list[dict] = field(default_factory=list)
    commentary: list[dict] = field(default_factory=list)


def image_parts(value):
    if isinstance(value, dict):
        if value.get("content_type") == "image_asset_pointer":
            yield value
        else:
            for child in value.values():
                yield from image_parts(child)
    elif isinstance(value, list):
        for child in value:
            yield from image_parts(child)


def source_messages(payload: dict, url: str) -> list[Message]:
    route, identifier = conversation_target(url)
    backing_id = str(payload.get("backing_conversation_id") or "")
    file_conversation_id = backing_id if route == "share" and re.fullmatch(UUID, backing_id) else identifier
    query = "?" + urlencode({"shared_conversation_id": identifier}) if route == "share" else ""
    records: list[Message] = []
    gallery = None
    pending_commentary = []
    for node in current_branch(payload, url):
        message = node.get("message") or {}
        metadata = message.get("metadata") or {}
        if metadata.get("is_visually_hidden_from_conversation"):
            continue
        role = (message.get("author") or {}).get("role")
        content = message.get("content") or {}
        if (role == "assistant" and message.get("channel") == "commentary"
                and (message.get("recipient") or "all") == "all"):
            text = "\n".join(p for p in content.get("parts", []) if isinstance(p, str))
            if text:
                pending_commentary.append({"id": message.get("id") or node["id"], "text": text, "metadata": metadata})
            continue
        pictures = list(image_parts(content))
        generated = role == "tool" and any(
            (p.get("metadata") or {}).get("dalle") or (p.get("metadata") or {}).get("generation")
            for p in pictures
        )
        if role == "user":
            if pending_commentary:
                records.append(Message(pending_commentary[0]["id"], "AI", [p["id"] for p in pending_commentary],
                                       "\n\n".join(p["text"] for p in pending_commentary),
                                       metadata=[p["metadata"] for p in pending_commentary]))
                pending_commentary = []
            gallery = None
        elif not generated and not (
            role == "assistant" and (message.get("recipient") or "all") == "all"
            and message.get("channel") != "commentary"
            and content.get("content_type") in {"text", "code"}
        ):
            continue
        text = "\n".join(p for p in content.get("parts", []) if isinstance(p, str))
        if not text and content.get("content_type") in {"text", "code"}:
            text = content.get("text", "")
        if not generated and role == "assistant" and not text.strip() and gallery:
            continue
        mid = message.get("id") or node["id"]
        exchange = metadata.get("turn_exchange_id") or ""
        row = Message(mid, "User" if role == "user" else "AI",
                      list(dict.fromkeys(x for x in (mid, node.get("id"), exchange) if x)),
                      "" if generated else text, exchange,
                      bool(metadata.get("model_dil_v2") or metadata.get("genui_components") or any(
                          ref.get("type") in {"map", "client_defined_widget", "dil", "image_group"}
                          for ref in metadata.get("content_references") or [])),
                      metadata=[metadata])
        if row.role == "AI" and pending_commentary:
            row.commentary, pending_commentary = pending_commentary, []
        if role == "user" or generated:
            for picture in pictures:
                match = FILE_ID.search(picture.get("asset_pointer") or "")
                if match:
                    file_id = match[0]
                    row.assets.append(Asset(file_id, "已生成图像" if generated else "已上传的图片", "image",
                                            f"/backend-api/files/download/{quote(file_id, safe='')}{query}"))
            for attachment in metadata.get("attachments") or []:
                file_id = attachment.get("id") or attachment.get("file_id") or ""
                if not FILE_ID.fullmatch(file_id):
                    continue
                name = attachment.get("name") or attachment.get("filename") or attachment.get("file_name") or file_id
                is_image = str(attachment.get("mime_type") or "").startswith("image/")
                if any(a.key == file_id for a in row.assets):
                    continue
                row.assets.append(Asset(file_id, name, "image" if is_image else "document",
                                        f"/backend-api/files/download/{quote(file_id, safe='')}{query}"))
        if role == "assistant":
            for match in SANDBOX_LINK.finditer(FENCE.sub("", text)):
                sandbox = unquote(match[2])
                path = sandbox.removeprefix("sandbox:")
                params = {"message_id": mid, "sandbox_path": path}
                if route == "share":
                    params["shared_conversation_id"] = identifier
                row.assets.append(Asset(f"{mid}:{sandbox}", path.rsplit("/", 1)[-1], "document",
                    f"/backend-api/conversation/{file_conversation_id}/interpreter/download?{urlencode(params)}", match[2]))
        if generated and gallery is not None:
            gallery.ids = list(dict.fromkeys(gallery.ids + row.ids))
            gallery.assets.extend(row.assets)
            gallery.commentary.extend(row.commentary)
        else:
            records.append(row)
            if generated:
                gallery = row

    if pending_commentary:
        records.append(Message(pending_commentary[0]["id"], "AI", [p["id"] for p in pending_commentary],
                               "\n\n".join(p["text"] for p in pending_commentary),
                               metadata=[p["metadata"] for p in pending_commentary]))

    grouped: list[Message] = []
    for row in records:
        if (grouped and row.role == grouped[-1].role == "AI" and row.exchange_id
                and row.exchange_id == grouped[-1].exchange_id):
            previous = grouped[-1]
            previous.text = "\n\n".join(t for t in (previous.text, row.text) if t)
            previous.ids = list(dict.fromkeys(previous.ids + row.ids))
            previous.assets.extend(row.assets)
            previous.metadata.extend(row.metadata)
            previous.commentary.extend(row.commentary)
            previous.rich |= row.rich
        else:
            grouped.append(row)
    if not grouped:
        raise SourceError("目标会话未包含可导出的可见消息。")
    for row in grouped:
        row.assets = list({asset.key: asset for asset in row.assets}.values())
    return grouped


def markdown_label(text: str) -> str:
    return re.sub(r"([\\\[\]])", r"\\\1", text.replace("\n", " "))


def resolve_citations(text: str, metadata: list[dict], asset_map: dict[str, str]) -> str:
    """Keep citation destinations without downloading decorative favicons."""
    for meta in metadata:
        for ref in meta.get("content_references") or []:
            marker = ref.get("matched_text")
            # Footnotes can have matched_text=' ' with zero-width source ranges.
            # Replacing that globally would corrupt every space, including code.
            if not marker or "\ue200" not in marker or marker not in text:
                continue
            if ref.get("type") == "hidden":
                text = text.replace(marker, "")
                continue
            links = []
            if ref.get("type") == "file":
                name = ref.get("name") or "引用文件"
                target = asset_map.get(ref.get("id")) or ref.get("cloud_doc_url")
                links.append(f"[{markdown_label(name)}]({target})" if target else f"〔{name}〕")
            for item in ref.get("items") or []:
                target = item.get("url")
                if target and urlparse(target).scheme in {"http", "https"}:
                    links.append(f"[{markdown_label(item.get('title') or urlparse(target).hostname or '来源')}]({target})")
            if not links and ref.get("url"):
                target = ref["url"]
                if urlparse(target).scheme in {"http", "https"}:
                    links.append(f"[{markdown_label(ref.get('title') or '来源')}]({target})")
            text = text.replace(marker, " ".join(dict.fromkeys(links)) or (ref.get("alt") or "〔引用〕"))
    # The few legacy markers without metadata are explicit unresolved citations,
    # not broken image attachments or leaked internal control tokens.
    return re.sub(r"\ue200[^\ue201]*\ue201", "〔引用〕", text)
