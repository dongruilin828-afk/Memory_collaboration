"""Doubao generated slides: message-bound discovery and native PPTX download."""
import hashlib
import io
import json
import re
import time
import zipfile
from pathlib import Path
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

SLIDES_SELECTOR = '[data-testid="slides-product-card"], [data-office-artifact-resource-type="9"]'
SLIDES_TITLE_SELECTOR = '[class*="card-title-text-"], [class*="card-content-info-title-text-"], [class^="title-"]'


def slide_entries(decoded_html, base_url):
    entries = []
    message_markers = list(re.finditer(r'"message_id"\s*:\s*"?(\d+)', decoded_html))
    for match in re.finditer(r'"artifact_block"\s*:\s*\{', decoded_html):
        try:
            block, _ = json.JSONDecoder().raw_decode(decoded_html[match.end()-1:])
        except ValueError:
            continue
        if not isinstance(block, dict) or block.get('resource_type') != 9:
            continue
        resource = str(block.get('artifact_topic') or block.get('resource_id') or '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', resource):
            continue
        previous = [m.group(1) for m in message_markers if m.start() < match.start()]
        entries.append({'title':str(block.get('title') or 'AI生成演示文稿'),
            'message_id':previous[-1] if previous else '', 'resource_id':resource,
            'conversation_id':str(block.get('conversation_id') or '')})
    soup = BeautifulSoup(decoded_html, 'html.parser')
    for card in soup.select(SLIDES_SELECTOR):
        parent = card.find_parent(attrs={'data-message-id':True})
        message_id = str(parent.get('data-message-id') or '') if parent else ''
        if message_id and any(e['message_id']==message_id for e in entries):
            continue
        title = card.select_one(SLIDES_TITLE_SELECTOR)
        conversation = re.fullmatch(r'/chat/(\d+)',urlparse(base_url).path)
        entries.append({'title':title.get_text(' ',strip=True) if title else 'AI生成演示文稿',
            'message_id':message_id,'resource_id':'',
            'conversation_id':conversation.group(1) if conversation else ''})
    return list({(e['message_id'],e['resource_id']):e for e in entries}.values())[:32]


def valid_pptx(body):
    if not body or not body.startswith(b'PK'):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            names = archive.namelist()
            return '[Content_Types].xml' in names and any(
                re.fullmatch(r'ppt/slides/slide\d+[.]xml',name) for name in names)
    except (ValueError,zipfile.BadZipFile):
        return False


async def save_slides(page, entries, directory, prefix, warnings, logger=None, reveal=None):
    mapping = {}
    for entry in entries:
        title, message_id, resource = (entry[k] for k in ('title','message_id','resource_id'))
        frame = None
        stage = '定位卡片'
        try:
            # A private editor can retain a previous resource in its warm iframe.
            if any('/partner/ccm-slides-v3/' in str(f.url) for f in page.frames):
                conversation = entry.get('conversation_id', '')
                if re.fullmatch(r'\d+',conversation):
                    await page.goto(f'https://www.doubao.com/chat/{conversation}',wait_until='domcontentloaded',timeout=20000)
                else:
                    await page.reload(wait_until='domcontentloaded',timeout=20000)
                await page.locator('[data-message-id]').first.wait_for(state='attached',timeout=15000)
            scope = page.locator(f'[data-message-id="{message_id}"]') if message_id else page
            card = scope.locator(SLIDES_SELECTOR).first
            if not await card.count() and reveal and message_id:
                await reveal(page,message_id,title)
            if not await card.count():
                raise ValueError('slides card not loaded')
            await card.scroll_into_view_if_needed(timeout=5000)
            await card.click(timeout=5000)
            stage = '等待对应编辑器'
            deadline = time.monotonic()+20
            while time.monotonic()<deadline:
                for candidate in page.frames:
                    parsed = urlparse(str(candidate.url))
                    match = re.fullmatch(r'/partner/ccm-slides-v3/([A-Za-z0-9_-]{8,128})',parsed.path)
                    if parsed.hostname in {'doubao.com','www.doubao.com'} and match and (
                        not resource or resource==match.group(1)):
                        frame = candidate
                        resource = match.group(1)
                        break
                if frame:
                    break
                await page.wait_for_timeout(250)
            if frame is None:
                raise ValueError('matching slides editor not opened')
            body = b''
            for attempt in range(2):
                try:
                    stage = '打开下载菜单'
                    pptx = frame.get_by_role('menuitem',name='PPTX',exact=True)
                    if not await pptx.is_visible():
                        await frame.get_by_role('button',name='下载',exact=True).click(timeout=15000)
                    async with page.expect_download(timeout=30000) as event:
                        stage = '点击PPTX'
                        await pptx.click(timeout=5000)
                        stage = '等待下载文件'
                    download = await event.value
                    path = await download.path()
                    body = Path(path).read_bytes() if path else b''
                    if len(body)<=50*1024*1024 and valid_pptx(body):
                        break
                    body = b''
                except Exception:
                    if attempt:
                        raise
                    await page.wait_for_timeout(800)
            if not body:
                raise ValueError('native PPTX download is not a complete presentation')
            directory = Path(directory)
            directory.mkdir(parents=True,exist_ok=True)
            stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]','_',title).rstrip(' .')[:150] or 'AI生成演示文稿'
            target = directory/(stem+'.pptx')
            if target.exists() and target.read_bytes()!=body:
                target = target.with_name(stem+'_'+hashlib.sha256((resource+message_id).encode()).hexdigest()[:8]+'.pptx')
            if not target.exists():
                target.write_bytes(body)
            local = prefix+'/'+quote(target.name,safe='')
            mapping['doubao-ai-slides-message:'+message_id] = local
            mapping['doubao-ai-slides-resource:'+resource] = local
            if logger:
                logger('已下载豆包生成演示文稿：'+target.name)
        except Exception as error:
            if logger:
                logger(f'豆包PPT导出阶段 {stage}：{str(error)[:1800]}')
            reason = str(error) if type(error) is ValueError else str(error).splitlines()[0][:160]
            reason = stage + '：' + reason
            warnings.append(f'豆包AI生成演示文稿未下载：{title}.pptx（{reason}）；已保留卡片名称与缺失提醒。')
        finally:
            if frame:
                try:
                    await page.keyboard.press('Escape')
                except Exception:
                    pass
    return mapping
