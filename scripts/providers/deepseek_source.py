"""Read DeepSeek's own history/share data, scoped to the requested branch."""
from urllib.parse import urlsplit, parse_qs
import json
import re


class SourceError(RuntimeError):
    pass


async def request_json(page, path):
    if urlsplit(str(page.url)).hostname != "chat.deepseek.com" or not path.startswith("/api/v0/"):
        raise SourceError("DeepSeek 源数据请求不属于当前原站。")
    response = await page.evaluate("""async path => {
        const value = JSON.parse(localStorage.getItem('userToken') || 'null');
        const token = typeof value === 'string' ? value : value?.value;
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 30000);
        try {
            const r = await fetch(path, {credentials: 'include', cache: 'no-store',
                headers: token ? {Authorization: 'Bearer ' + token} : {}, signal: controller.signal});
            const text = await r.text();
            let data = null;
            try {data = JSON.parse(text);} catch {}
            return {status: r.status, data};
        } finally {clearTimeout(timer);}
    }""", path)
    payload = response.get("data") or {}
    data = payload.get("data") or {}
    if response.get("status") != 200 or payload.get("code") != 0 or data.get("biz_code") != 0:
        business_code = data.get("biz_code")
        detail = f"，业务码 {business_code}" if isinstance(business_code, int) else ""
        raise SourceError(f'DeepSeek 源数据读取失败（HTTP {response.get("status", "")}{detail}）。')
    return data.get("biz_data") or {}


def current_branch(data, session_id):
    session = data.get("chat_session") or {}
    if session.get("id") != session_id:
        raise SourceError("DeepSeek 返回的会话身份与请求不一致。")
    messages = data.get("chat_messages")
    if not isinstance(messages, list) or not messages:
        raise SourceError("DeepSeek 完整源消息为空，不能把缓存增量当作完整会话。")
    by_id = {m["message_id"]: m for m in messages}
    if len(by_id) != len(messages):
        raise SourceError("DeepSeek 源消息 ID 重复。")
    result, seen = [], set()
    node = session.get("current_message_id")
    while node is not None:
        if node in seen or node not in by_id:
            raise SourceError("DeepSeek 当前分支的父节点不完整或形成循环。")
        seen.add(node)
        message = by_id[node]
        result.append(message)
        node = message.get("parent_id")
    if not result:
        raise SourceError("DeepSeek 未提供当前分支节点。")
    return list(reversed(result))


async def read_conversation(page):
    path = urlsplit(str(page.url)).path
    private = re.fullmatch(r"/a/chat/s/([0-9a-fA-F-]{36})/?", path)
    share = re.fullmatch(r"/share/([A-Za-z0-9]+)/?", path)
    if private:
        target = private[1]
        # Omitting cache_version/cache_reset_at requests full history, not MERGE deltas.
        data = await request_json(page, "/api/v0/chat/history_messages?chat_session_id=" + target)
        messages = current_branch(data, target)
    elif share:
        target = share[1]
        data = await request_json(page, "/api/v0/share/content?share_id=" + target)
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            raise SourceError("DeepSeek 分享源消息为空。")
        if len({m["message_id"] for m in messages}) != len(messages):
            raise SourceError("DeepSeek 分享源消息 ID 重复。")
    else:
        raise SourceError("无法确认当前 DeepSeek 会话入口。")
    return {"target": target, "share": bool(share), "messages": messages}


def embed_source(source):
    messages = []
    for message in source["messages"]:
        item = {k: message.get(k) for k in ("message_id", "parent_id", "role", "status")}
        if message.get("role") == "USER":
            item["fragments"] = []
            for fragment in message.get("fragments") or []:
                part = {"type": fragment.get("type")}
                if "content" in fragment:
                    part["content"] = fragment["content"]
                if "files" in fragment:
                    part["files"] = [{k: f.get(k) for k in
                                      ("id", "file_name", "file_size", "is_image", "status")}
                                     for f in fragment["files"]]
                item["fragments"].append(part)
        else:
            item["fragments"] = [{"type": "RESPONSE", "content": part.get("content", "")}
                                 for part in message.get("fragments") or [] if part.get("type") == "RESPONSE"]
        messages.append(item)
    payload = json.dumps({**source, "messages": messages}, ensure_ascii=False).replace("<", "\\u003c")
    return '<script type="application/json" data-deepseek-source="true">' + payload + '</script>'


def source_from_soup(soup):
    node = soup.select_one('script[data-deepseek-source="true"]')
    if node is None:
        return None
    try:
        return json.loads(node.string or "")
    except (ValueError, TypeError):
        return None


def files(source):
    return [file for message in source.get("messages", []) if message.get("role") == "USER"
            for fragment in message.get("fragments", []) for file in fragment.get("files", [])]


def file_href(file, asset_map, name_counts=None):
    file_id = file.get("id") or ""
    if asset_map.get("deepseek-file:" + file_id):
        return asset_map["deepseek-file:" + file_id]
    raw_id = file_id.removeprefix("file-")
    for reference, local in asset_map.items():
        if parse_qs(urlsplit(reference).query).get("file_id") == [raw_id]:
            return local
    name = (file.get("file_name") or "").lower()
    if name_counts is None or name_counts.get(name, 0) == 1:
        return asset_map.get(name)
    return None


def is_image(file):
    return bool(file.get("is_image")) or bool(re.search(r"\.(?:jpe?g|png|webp|gif|bmp|avif)$", file.get("file_name") or "", re.I))


def name_counts(source):
    from collections import Counter
    return Counter(name for name, _ in {((f.get("file_name") or "").lower(), f.get("id")) for f in files(source)})


async def download_missing_images(page, html, images_dir, prefix, asset_map, warnings, max_bytes=40*1024*1024):
    """Recover FILE-fragment images by their own ID; never borrow another message's file."""
    from bs4 import BeautifulSoup
    import hashlib
    import io
    from urllib.parse import quote
    from PIL import Image
    soup = BeautifulSoup(html, "html.parser")
    source = source_from_soup(soup)
    if not source:
        return {}
    counts = name_counts(source)
    resolved = {}
    for message in source["messages"]:
        images = [f for part in message.get("fragments", []) for f in part.get("files", []) if is_image(f)]
        node = soup.select_one(f'[data-virtual-list-item-key="{message["message_id"]}"]')
        dom_images = node.select("img") if node else []
        for file in images:
            file_id, name = file.get("id") or "", file.get("file_name") or "图片"
            if not re.fullmatch(r"file-[0-9a-fA-F-]{36}", file_id):
                continue
            local = file_href(file, {**asset_map, **resolved}, counts)
            if not local and len(images) == len(dom_images) == 1:
                local = asset_map.get(dom_images[0].get("src") or dom_images[0].get("data-src"))
            if local:
                resolved["deepseek-file:" + file_id] = local
                continue
            try:
                data = await request_json(page, "/api/v0/file/fetch_files?file_ids=" + quote(file_id, safe=""))
                matches = [f for f in data.get("files", []) if f.get("id") == file_id and f.get("file_name") == name]
                if len(matches) != 1 or matches[0].get("status") != "SUCCESS":
                    raise SourceError("原站未返回同一文件的可用元数据")
                meta = matches[0]
                signed = str(meta.get("signed_path") or "")
                if not signed:
                    raise SourceError("原站未返回图片下载地址")
                url = "https://files.deepseeksvc.com/api/" + signed.lstrip("/")
                parsed = urlsplit(url)
                size = meta.get("file_size")
                if (parsed.path != "/api/file" or parse_qs(parsed.query).get("file_id") != [file_id[5:]]
                        or not isinstance(size, int) or not 0 < size <= max_bytes):
                    raise SourceError("原图地址或大小未通过身份校验")
                # DeepSeek serves the full-size image as p; r is for documents
                # and returns 400 even for healthy images. t is only a thumbnail.
                if re.search(r"[?&]ty=", url):
                    url = re.sub(r'([?&])ty=[^&]*', r'\1ty=p', url)
                else:
                    url += "&ty=p"
                response = await page.context.request.get(url, timeout=30000)
                if response.status != 200:
                    raise SourceError(f"原文件 HTTP {response.status}")
                body = await response.body()
                if not 0 < len(body) <= max_bytes:
                    raise SourceError("图片响应大小不在允许范围内")
                with Image.open(io.BytesIO(body)) as image:
                    extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp", "AVIF": ".avif"}.get(image.format)
                    image.verify()
                if not extension:
                    raise SourceError("原文件不是支持的图片")
                images_dir.mkdir(parents=True, exist_ok=True)
                target = images_dir / ("deepseek_" + file_id[5:] + "_" + hashlib.sha256(body).hexdigest()[:8] + extension)
                target.write_bytes(body)
                resolved["deepseek-file:" + file_id] = prefix + "/" + quote(target.name, safe="")
            except Exception as error:
                # Only our fixed diagnostic messages can include file names; no signed URLs.
                reason = str(error) if isinstance(error, SourceError) else type(error).__name__
                warnings.append(f"DeepSeek 图片 {name} 未取得原文件（{reason}）。")
    return resolved
