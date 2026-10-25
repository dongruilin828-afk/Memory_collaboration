"""Capture one verified ChatGPT branch and bind every file to its source message."""
from __future__ import annotations

import base64
import hashlib
import html
import io
import ipaddress
import re
import zipfile
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlparse

from bs4 import BeautifulSoup
from PIL import Image

from scripts.providers import chatgpt
from scripts.providers.chatgpt_markdown import prepare_markdown
from scripts.providers.chatgpt_source import (
    Asset, Message, SourceError, conversation_target, markdown_label,
    resolve_citations, source_messages, supporting_citation_links, citation_label,
)


async def read_asset(page, asset: Asset) -> tuple[bytes, str]:
    """Download through the authorized browser; session tokens never leave JS."""
    external = asset.endpoint.startswith(("https://", "blob:"))
    if asset.endpoint.startswith("https://"):
        host = urlparse(asset.endpoint).hostname or ""
        try:
            blocked = not ipaddress.ip_address(host).is_global
        except ValueError:
            blocked = not host or host.lower() == "localhost" or host.lower().endswith((".local", ".localhost"))
        if blocked:
            raise SourceError("图片地址不是公开网站资源。")
    result = {}
    for attempt in range(3):
        try:
            result = await page.evaluate("""async ({endpoint,maxBytes,attempt}) => {
              let phase='session';
              try {
                const target=new URL(endpoint,location.href);
                const backend=target.origin===location.origin && target.pathname.startsWith('/backend-api/');
                if(!backend && target.protocol!=='https:' && !(target.protocol==='blob:' && target.origin===location.origin))
                    return {error:'invalid_endpoint'};
                let token;
                if(backend)try{
                    const r=await fetch('/api/auth/session',{credentials:'include',signal:AbortSignal.timeout(15000)});
                    if(r.ok){const s=await r.json();token=s.accessToken||s.access_token;}
                }catch{}
                const opts=()=>({cache:attempt?'no-store':'default',
                    credentials:backend?'include':'omit',signal:AbortSignal.timeout(60000),
                    ...(token?{headers:{Authorization:'Bearer '+token}}:{})});
                const file=target.pathname.match(/^\\/backend-api\\/files\\/download\\/([^/]+)$/);
                // The account's file route and the public-share file route have
                // different download grants. With an authenticated session try
                // the account route first, then the public grant for shared-only files.
                if(token && attempt!==1)target.searchParams.delete('shared_conversation_id');
                if(file){
                    phase='prepare';
                    const prepared=await fetch('/backend-api/files/'+file[1]+'/simple'+target.search,opts());
                    await prepared.arrayBuffer();
                }
                phase='metadata';
                let r=await fetch(target.href,opts());
                if(!r.ok)return {status:r.status};
                if((r.headers.get('content-type')||'').includes('application/json')){
                    const data=await r.json();
                    const link=data.download_url||data.downloadUrl||data.url||data.data?.download_url||data.data?.url;
                    if(!link)return {error:'missing_download_url'};
                    const download=new URL(link,location.href);
                    if(download.protocol!=='https:')return {error:'invalid_download_url'};
                    const options=opts();
                    if(download.origin!==location.origin){
                        delete options.headers;
                        // The signed CDN URL authorizes this request itself.
                        // Credentials would reject its wildcard CORS response.
                        options.credentials='omit';
                    }
                    phase='download';
                    r=await fetch(download.href,options);
                    if(!r.ok)return {status:r.status};
                }
                if(Number(r.headers.get('content-length')||0)>maxBytes)return {error:'size_limit'};
                phase='body';
                const reader=r.body.getReader(),chunks=[];let total=0;
                while(true){
                    const {value,done}=await reader.read();if(done)break;
                    total+=value.length;
                    if(total>maxBytes){await reader.cancel();return {error:'size_limit'};}
                    chunks.push(value);
                }
                let binary='';
                for(const chunk of chunks)for(let i=0;i<chunk.length;i+=32768)
                    binary+=String.fromCharCode(...chunk.subarray(i,i+32768));
                return {status:r.status,body:btoa(binary),content_type:r.headers.get('content-type')||''};
              }catch(error){return {error:'browser_'+phase,error_type:error.name};}
            }""", {"endpoint": asset.endpoint, "maxBytes": 250 * 1024 * 1024, "attempt": attempt})
            if result.get("status") == 200 and "body" in result:
                body = base64.b64decode(result["body"])
                mime = result.get("content_type", "").split(";", 1)[0].lower()
                if mime in {"text/html", "application/json"} and not asset.name.lower().endswith((".html", ".htm", ".json")):
                    raise ValueError("unexpected_response_type")
                if asset.kind == "image":
                    with Image.open(io.BytesIO(body)) as image:
                        image.verify()
                elif asset.name.lower().endswith(".docx"):
                    with zipfile.ZipFile(io.BytesIO(body)) as document:
                        if not {"[Content_Types].xml", "word/document.xml"} <= set(document.namelist()):
                            raise zipfile.BadZipFile("Missing DOCX parts")
                return body, mime
        except Exception as error:
            result = {"error": "DOCX 文件不完整或格式无效" if isinstance(error, zipfile.BadZipFile)
                      else "network_or_invalid_file", "error_type": type(error).__name__}
        if external and asset.endpoint.startswith("https://") and result.get("error", "").startswith("browser_"):
            # Public article/product images often omit CORS headers. The normal
            # browser request context can still retrieve them without bearer headers.
            try:
                response = await page.request.get(asset.endpoint, timeout=30000)
                if response.status == 200:
                    body = await response.body()
                    if len(body) <= 32 * 1024 * 1024:
                        with Image.open(io.BytesIO(body)) as image:
                            image.verify()
                        return body, response.headers.get("content-type", "")
            except Exception:
                pass
        if (result.get("status") in {404, 410} and "shared_conversation_id=" not in asset.endpoint) or result.get("error") == "size_limit":
            break
        if attempt < 2:
            await page.wait_for_timeout(1500)
    raise SourceError(f"原文件未能下载（{result.get('error') or 'HTTP ' + str(result.get('status', 0))}）。")


def save_asset(body: bytes, asset: Asset, directory: Path, prefix: str,
               cache: dict[tuple[str, str], str]) -> str:
    digest = hashlib.sha256(body).hexdigest()
    key = (asset.kind, digest)
    if key in cache:
        return cache[key]
    directory.mkdir(parents=True, exist_ok=True)
    if asset.kind == "image":
        with Image.open(io.BytesIO(body)) as image:
            suffix = {"JPEG": "jpg", "TIFF": "tiff"}.get(image.format, (image.format or "png").lower())
        filename = f"img_{digest[:16]}.{suffix}"
    else:
        filename = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", asset.name).strip(" .") or "attachment"
        filename = filename[:180]
        if re.fullmatch(r"(?i)(?:con|prn|aux|nul|com\d|lpt\d)(?:\..*)?", filename):
            filename = "_" + filename
    path = directory / filename
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        filename = f"{path.stem}_{digest[:16]}{path.suffix}"
        path = directory / filename
    path.write_bytes(body)
    reference = f"{prefix.rstrip('/')}/{quote(filename)}"
    cache[key] = reference
    return reference


def _is_deferred_widget(message: Message) -> bool:
    kinds = {ref.get("type") for meta in message.metadata
             for ref in meta.get("content_references") or []}
    return kinds & {"map", "client_defined_widget", "dil", "image_group"} == {"client_defined_widget"}


async def rendered_messages(page, url: str, messages: list[Message]) -> dict[str, str]:
    """Collect only requested rich-message IDs; reject unrelated or empty DOM."""
    # A user turn and its answer can share an exchange ID. Only message/node
    # identities may authorize a DOM fragment to replace the answer's source.
    wanted = {identifier for m in messages if m.rich for identifier in m.ids
              if identifier != m.exchange_id or identifier == m.id}
    if not wanted:
        return {}
    selector = '[data-chatgpt-search-unit-key], [data-message-author-role], [data-chatgpt-search-message-ids]'
    captured: dict[str, str] = {}
    scores: dict[str, int] = {}
    def ready(message):
        # Deferred widgets expose a short status, not their implementation text.
        minimum = 1 if _is_deferred_widget(message) else min(50, max(1, len(message.text) // 4))
        return any(scores.get(identifier, 0) >= minimum for identifier in message.ids)

    for navigation in range(2):
        try:
            same_target = conversation_target(page.url) == conversation_target(url)
        except SourceError:
            same_target = False
        try:
            if navigation or not same_target:
                await page.goto(url.replace("http://", "https://"), wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_selector(selector, state="attached", timeout=30000)
            await page.wait_for_timeout(5000)
            scroll = await page.evaluate_handle("""selector => {
                let n=document.querySelector(selector);
                while(n){const s=getComputedStyle(n);
                    if(n.clientHeight>200&&n.scrollHeight>n.clientHeight+100&&/(auto|scroll)/.test(s.overflowY))return n;
                    n=n.parentElement;}
                return document.scrollingElement;
            }""", selector)
            reverse = await scroll.evaluate('''e=>{
                const before=e.scrollTop;e.scrollTop=1;const positive=e.scrollTop;
                e.scrollTop=-1;const negative=e.scrollTop;e.scrollTop=before;
                return positive===0&&negative<0;
            }''')
            # Private views also use reverse virtual lists. scrollTop=0 can be
            # the newest message, not the beginning of the conversation.
            for _ in range(60):
                await scroll.evaluate('(e,reverse)=>e.scrollTop=reverse?-e.scrollHeight:0', reverse)
                await page.wait_for_timeout(700)
                at_first = await page.evaluate('''id=>Array.from(document.querySelectorAll(
                    '[data-message-id],[data-chatgpt-search-message-ids],[data-chatgpt-selection-message-id]'
                )).some(n=>Array.from(n.attributes).some(a=>a.value.split(' ').includes(id)))''', messages[0].id)
                if at_first:
                    await page.wait_for_timeout(1500)
                    break
            stable = 0
            for _ in range(1200):
                await page.wait_for_timeout(350)
                rows = await page.evaluate(r"""selector => {
                    const nodes=Array.from(document.querySelectorAll(selector)),set=new Set(nodes);
                    return nodes.filter(n=>{
                        for(let p=n.parentElement;p;p=p.parentElement)if(set.has(p))return false;
                        return !!n.closest('main');
                    }).map(n=>({html:n.outerHTML,text:(n.querySelector(
                        '[data-markdown-text-style="assistant-message"],.markdown'
                    )||n).innerText,
                        ids:Array.from(new Set([n,...n.querySelectorAll('*')].flatMap(e=>
                            Array.from(e.attributes).filter(a=>/(message-id|message-ids|unit-key|turn-id)/.test(a.name))
                            .flatMap(a=>a.value.match(/[0-9a-f]{8}-[0-9a-f-]{27,}/g)||[]))))}));
                }""", selector)
                for row in rows:
                    score = len(re.sub(r"ChatGPT\s*(?:说|said|says)?[:：]?", "", row["text"], flags=re.I).strip())
                    for identifier in wanted.intersection(row["ids"]):
                        if score > scores.get(identifier, 0):
                            captured[identifier], scores[identifier] = row["html"], score
                if all(ready(m) for m in messages if m.rich):
                    break
                bottom = await scroll.evaluate("""(e,reverse)=>{
                    const before=e.scrollTop;e.scrollTop+=Math.max(400,e.clientHeight*.7);
                    return e.scrollTop>=(reverse?0:e.scrollHeight-e.clientHeight)-3 && e.scrollTop===before;
                }""", reverse)
                stable = stable + 1 if bottom else 0
                if stable >= 4:
                    break
            if all(ready(m) for m in messages if m.rich):
                return captured
        except Exception:
            pass
    missing = [m.id for m in messages if m.rich and not ready(m)]
    raise SourceError(f"有 {len(missing)} 条交互回复尚未完整渲染，已停止导出以避免遗漏。请稍后重试。")


def _citation_key(target: str) -> tuple[str, str, str]:
    url = urlparse(target)
    query = sorted((key, value) for key, value in parse_qsl(url.query, keep_blank_values=True)
                   if not key.lower().startswith("utm_") and key.lower() != "trk")
    return url.netloc.lower(), url.path.rstrip("/"), urlencode(query)


def rich_markdown(row: Message, rendered: dict[str, str], assets: dict[str, str]) -> str:
    fragments = list(dict.fromkeys(rendered[i] for i in row.ids if i in rendered))
    parsed = []
    for fragment in fragments:
        soup = BeautifulSoup(fragment, "html.parser")
        root = soup.find()
        root["data-message-author-role"] = "assistant"
        for node in soup.select(
            '[data-markdown-copy="exclude"], .sr-only, [aria-hidden="true"], '
            '.mapboxgl-control-container, .mapboxgl-touch-pan-blocker, .mapboxgl-scroll-zoom-blocker'
        ):
            node.decompose()
        for image in list(soup.find_all("img")):
            src = str(image.get("src") or "")
            if image.find_parent("a", attrs={"data-testid": "chatgpt-citation"}) or "favicon" in src.lower():
                image.decompose()
        # SVG diagrams remain portable. Icon SVGs have no meaningful text and
        # are excluded rather than exported as hundreds of broken attachments.
        for svg in list(soup.find_all("svg")):
            if svg.find("text") or svg.get("role") == "img":
                for unsafe in svg.find_all(["script", "foreignobject"]):
                    unsafe.decompose()
                for node in [svg, *svg.find_all(True)]:
                    for attr in list(node.attrs):
                        if attr.lower().startswith("on") or (
                            attr in {"href", "xlink:href"} and not str(node[attr]).startswith("#")
                        ):
                            del node[attr]
                image = soup.new_tag("img", alt="示意图")
                image["src"] = "data:image/svg+xml;base64," + base64.b64encode(str(svg).encode()).decode()
                svg.replace_with(image)
            else:
                svg.decompose()
        converted = chatgpt.parse_messages(soup, assets) or []
        text = "\n\n".join(m["content"] for m in converted if m["role"] == "AI")
        if text and text not in parsed:
            parsed.append(text)
    if not parsed and _is_deferred_widget(row):
        parsed.append("（交互组件暂未导出）")
    if not parsed:
        raise SourceError("交互回复未取得可见正文，已停止导出。")
    body = "\n\n".join(parsed)
    # GenUI citation popovers render only a domain and '+N'; their destinations
    # remain in the exact message's resolved components. Preserve these as a
    # source list without clicking the popover or guessing inline positions.
    cited, supporting = {}, {}
    for metadata in row.metadata:
        for ref in metadata.get("content_references") or []:
            marker = ref.get("matched_text") or ""
            if ref.get("type") != "grouped_webpages" or "\ue200" not in marker or marker not in row.text:
                continue
            for item in ref.get("items") or []:
                for target, link in supporting_citation_links(item):
                    if not re.search(r"\]\(" + re.escape(target) + r"\)", body):
                        supporting.setdefault(_citation_key(target), link)
        titles = {}
        dil = metadata.get("model_dil_v2") or {}
        components = (dil.get("appData") or {}).get("opGenui", {}).get("componentResults", {})
        for component in components.values():
            if component.get("status") != "resolved" or component.get("componentName") not in {"Cite", "Link"}:
                continue
            state = component.get("state") or {}
            items = state.get("items") or ([state] if state.get("url") else [])
            for item in items:
                target = item.get("url") or ""
                url = urlparse(target)
                if url.scheme in {"http", "https"} and url.hostname and target not in body:
                    cited.setdefault(_citation_key(target),
                                     (target, item.get("title") or url.hostname))
        for group in metadata.get("search_result_groups") or []:
            for entry in group.get("entries") or []:
                url = urlparse(entry.get("url") or "")
                titles[_citation_key(entry.get("url") or "")] = entry.get("title")
        for component in metadata.get("genui_components") or []:
            if component.get("type") != "cite":
                continue
            for item in component.get("safe_urls") or []:
                target = item.get("url") or ""
                url = urlparse(target)
                key = _citation_key(target)
                if (url.scheme not in {"http", "https"} or not url.hostname
                    or url.hostname == "images.openai.com"
                    or (key not in titles and re.search(r"\.(png|jpe?g|webp|gif|ico|svg)$", url.path, re.I))):
                    continue
                if target not in body:
                    cited.setdefault(key, (target, titles.get(key) or url.hostname))
    source_lines = [f"- [{citation_label(title)}]({target})" for target, title in cited.values()]
    source_lines.extend(f"- {link}" for key, link in supporting.items() if key not in cited)
    if source_lines:
        body += "\n\n引用来源：\n\n" + "\n".join(source_lines)
    return body


async def capture_conversation(page, url, payload, *, images_dir, image_prefix,
                               documents_dir, document_prefix, logger=None):
    rows = source_messages(payload, url)
    if logger:
        logger(f"已核验目标会话 ID，当前分支共 {len(rows)} 条可见消息。")
    rendered = await rendered_messages(page, url, rows)
    # Preserve meaningful web/product pictures inside rendered rich replies too;
    # these are separate from user uploads and generated file-service assets.
    for row in rows:
        if not row.rich:
            continue
        seen = set()
        for fragment in dict.fromkeys(rendered[i] for i in row.ids if i in rendered):
            soup = BeautifulSoup(fragment, "html.parser")
            for image in soup.find_all("img"):
                src = str(image.get("src") or image.get("data-src") or "")
                if (not src.startswith(("https://", "blob:")) or src in seen
                    or "favicon" in src.lower()
                    or image.find_parent("a", attrs={"data-testid": "chatgpt-citation"})
                    or image.get("aria-hidden") == "true"):
                    continue
                seen.add(src)
                row.assets.append(Asset("web:" + hashlib.sha256(src.encode()).hexdigest(),
                    image.get("alt") or "网页引用图片", "image", src, src))
    image_map, document_map, warnings, file_cache = {}, {}, [], {}
    for index, row in enumerate(rows, 1):
        kinds = {ref.get("type") for meta in row.metadata for ref in meta.get("content_references") or []}
        for kind, label in (("map", "地图"), ("client_defined_widget", "交互组件")):
            if kind in kinds:
                warnings.append(f"第 {index} 条消息的{label}导出未完成：当前仅保留可读静态内容。")
    references, failures = {}, {}
    assets = {a.key: a for row in rows for a in row.assets}
    for index, asset in enumerate(assets.values(), 1):
        try:
            body, _ = await read_asset(page, asset)
            is_image = asset.kind == "image"
            reference = save_asset(body, asset, images_dir if is_image else documents_dir,
                                   image_prefix if is_image else document_prefix, file_cache)
            references[asset.key] = reference
            if asset.source_reference:
                references[asset.source_reference] = reference
            target_map = image_map if is_image else document_map
            target_map[asset.key] = reference
            if asset.source_reference.startswith("sandbox:"):
                target_map[asset.source_reference] = reference
        except SourceError as error:
            failures[asset.key] = str(error)
            warnings.append(f"附件 {asset.name}（{asset.key}）未下载：{error}")
        if logger:
            logger(f"原会话附件 {index}/{len(assets)}：{'已保存' if asset.key in references else '未下载，已明确标记'}。")
    result, snapshots = [], []
    for row in rows:
        body = rich_markdown(row, rendered, references) if row.rich else resolve_citations(row.text, row.metadata, references)
        body = prepare_markdown(body, user=row.role == "User")
        attachments = []
        for asset in row.assets:
            reference = references.get(asset.key)
            label = markdown_label(asset.name)
            if asset.source_reference:
                if reference:
                    body = body.replace(asset.source_reference, reference)
                elif asset.kind == "image":
                    body = re.sub(r'!\[[^\]]*\]\(' + re.escape(asset.source_reference) + r'\)',
                                  lambda _: f"🖼️ **[引用图片未下载]** `{label}`", body)
                else:
                    body += f"\n\n📎 **[AI生成文件未下载]** `{label}`（原站未提供可用下载，请从原会话重试）"
            elif reference:
                attachments.append(f"![{label}]({reference})" if asset.kind == "image" else f"[📄 {label}]({reference})")
            else:
                kind = "图片" if asset.kind == "image" else "附件"
                attachments.append(f"📎 **[{kind}未下载]** `{label}`（请从原会话重试）")
        preface = [prepare_markdown(resolve_citations(p["text"], [p["metadata"]], references)) for p in row.commentary]
        content = "\n\n".join([*preface, *attachments, body] if body else [*preface, *attachments])
        # Windows text writers expand LF to CRLF. Normalize source CRLF once,
        # otherwise CRLF becomes CRCRLF and reading the export adds blank lines.
        # This changes only the newline encoding, never indentation or spacing.
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        exported_ids = list(dict.fromkeys([p["id"] for p in row.commentary] + row.ids))
        result.append({"role": row.role, "content": content, "source_id": row.id,
                       "source_ids": exported_ids})
        snapshots.append(f'<section data-message-author-role="{"user" if row.role == "User" else "assistant"}" '
                         f'data-message-id="{html.escape(row.id)}" data-chatgpt-search-message-ids="{html.escape(" ".join(exported_ids))}">'
                         f'<pre data-source-markdown="true">{html.escape(content)}</pre></section>')
    return {"html": '<main data-verified-chatgpt-conversation="' + html.escape(payload["conversation_id"]) + '">' + "\n".join(snapshots) + '</main>',
            "messages": result, "image_map": image_map, "document_map": document_map, "warnings": warnings}
