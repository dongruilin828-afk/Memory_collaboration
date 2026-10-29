"""Real Chromium fixtures: collect/download without animation-frame stability."""
import asyncio
import base64
import json
import io
import os
from pathlib import Path
import tempfile
import time
import unittest

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw
from playwright.async_api import async_playwright
from unittest.mock import AsyncMock, patch
from gui import service
from gui.service import DocumentCandidate, _gemini_document_card_download
from scripts.providers import gemini
from scripts.providers.gemini_assets import DocumentIndex
from tests.test_gemini_history_documents import entry, file_record, reference, wire


@unittest.skipUnless(os.getenv('AI_MEMORY_BROWSER_SMOKE') == '1', 'opt-in real Chromium fixtures')
class GeminiBackgroundBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=False)
        self.context = await self.browser.new_context(viewport={'width': 800, 'height': 400})
        self.page = await self.context.new_page()
        self.page_errors = []
        self.page.on('pageerror', lambda error: self.page_errors.append(str(error)))
        self.body = ''
        async def route(request_route):
            if '/file/' in request_route.request.url:
                identifier = request_route.request.url.rsplit('/', 1)[-1]
                await request_route.fulfill(body=('original '+identifier).encode(), headers={
                    'content-type': 'application/octet-stream', 'content-disposition': f'attachment; filename="{identifier}"'})
            else:
                await request_route.fulfill(body=self.body, content_type='text/html; charset=utf-8')
        await self.context.route('**/*', route)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def test_collect_preserves_lazy_messages_and_skips_nested_hidden_scroll_waits(self):
        self.body = '''<style>user-query,model-response{display:block;min-height:220px}</style>
          <user-query id="u0"><div class="query-text">question 0</div></user-query>
          <model-response id="outer0"><message-content id="a0">answer 0</message-content></model-response>
          <user-query id="u1"><div class="query-text">question 1</div></user-query>
          <model-response id="outer1"><message-content id="a1">answer 1</message-content></model-response>
          <model-response id="hidden" style="display:none"><message-content></message-content></model-response>
          <script>
            window.requestAnimationFrame=()=>0;
            window.scrolled=[];
            const nativeScroll=Element.prototype.scrollIntoView;
            Element.prototype.scrollIntoView=function(options){window.scrolled.push(this.id);nativeScroll.call(this,options)};
            window.addEventListener('scroll',()=>setTimeout(()=>{
              const div=document.createElement('div');
              div.innerHTML='<user-query id="earlier"><div class="query-text">earlier question</div></user-query>'+
                  '<model-response><message-content id="earlier-a">earlier answer</message-content></model-response>';
              document.body.prepend(div);
            },20),{once:true});
          </script>'''
        await self.page.goto('https://gemini.google.com/app/fixture')
        other = await self.context.new_page()
        await other.goto('https://other.test/blank')
        started = time.perf_counter()
        result = await asyncio.wait_for(gemini.collect_html(self.page), 8)
        self.assertLess(time.perf_counter()-started, 8)
        messages = gemini.parse_messages(BeautifulSoup(result, 'html.parser'))
        self.assertEqual([m['content'] for m in messages], [
            'earlier question','earlier answer','question 0','answer 0','question 1','answer 1'])
        scrolled = await self.page.evaluate('window.scrolled')
        self.assertNotIn('outer0', scrolled)
        self.assertNotIn('outer1', scrolled)
        self.assertNotIn('hidden', scrolled)

    async def test_native_download_retains_metadata_identity_and_waits_until_enabled(self):
        metadata = {i:base64.b64encode(f'[["file_{i}","conversation_fixture"]]'.encode()).decode() for i in ('one','two')}
        self.body = ''.join(f'''<user-query-file-preview><button aria-label="report.txt"
          jslog="BardVeMetadataKey:{metadata[i]}" onclick="openFile('{i}')">report.txt</button></user-query-file-preview>'''
          for i in metadata) + '''<div role="dialog" style="display:none">
          <button aria-label="下载" disabled onclick="if(!event.isTrusted)throw new Error('native download requires trusted input');location.assign('/file/'+window.selected+'.txt')">download</button>
          <button aria-label="关闭" onclick="this.parentElement.style.display='none'">close</button></div>
          <script>window.requestAnimationFrame=()=>0;
            window.openFile=id=>{window.selected=id;document.querySelector('[role=dialog]').style.display='block';
              setTimeout(()=>document.querySelector('[aria-label=下载]').disabled=false,150)};
          </script>'''
        url = 'https://gemini.google.com/app/fixture'
        await self.page.goto(url)
        self.assertEqual(await self.page.evaluate('typeof window.openFile'), 'function', self.page_errors)
        other = await self.context.new_page()
        await other.goto('https://other.test/blank')
        try:
            body, headers = await asyncio.wait_for(_gemini_document_card_download(self.page,
                DocumentCandidate('gemini-card:'+metadata['two']+':report.txt', url, 'report.txt'), 5000), 20)
        except Exception:
            print('FIXTURE_DIAGNOSTICS', self.page_errors, await self.page.evaluate("""() => ({selected:window.selected,
                labels:Array.from(document.querySelectorAll('[aria-label]')).map(n=>n.getAttribute('aria-label')),
                display:document.querySelector('[role=dialog]')?.style.display})"""))
            raise
        self.assertEqual(body, b'original two.txt')
        self.assertIn('two.txt', headers['content-disposition'])
        self.assertFalse(await self.page.locator('[role=dialog]').is_visible())

    async def test_three_native_viewers_activate_only_their_owner_and_keep_files_separate(self):
        key=base64.b64encode(b'[["file_bound","conversation_fixture"]]').decode()
        self.body=f'''<user-query-file-preview><button aria-label="report.txt" jslog="BardVeMetadataKey:{key}"
          onclick="if(document.visibilityState!=='visible')throw new Error('inactive owner');document.querySelector('[role=dialog]').style.display='block'">report.txt</button></user-query-file-preview>
          <div role="dialog" style="display:none"><button aria-label="下载"
          onclick="if(!event.isTrusted)throw new Error('untrusted');location.assign('/file/'+location.pathname.split('/').pop()+'.txt')">download</button>
          <button aria-label="关闭" onclick="this.parentElement.style.display='none'">close</button></div>'''
        pages=[self.page,await self.context.new_page(),await self.context.new_page()]
        lock=asyncio.Lock()
        for index,page in enumerate(pages):
            await page.goto(f'https://gemini.google.com/app/owner{index}')
            page._aimemory_render_lock=lock
            page.bring_to_front=AsyncMock(wraps=page.bring_to_front)
        results=await asyncio.wait_for(asyncio.gather(*(
            _gemini_document_card_download(page,DocumentCandidate('gemini-card:'+key+':report.txt',page.url,'report.txt'),5000)
            for page in pages)),30)
        self.assertEqual([row[0] for row in results],[f'original owner{index}.txt'.encode() for index in range(3)])
        self.assertEqual(len(self.context.pages),3)
        self.assertFalse(lock.locked())
        for page in pages:page.bring_to_front.assert_awaited_once()

    async def test_history_original_download_skips_preview_and_keeps_owner_page(self):
        row=entry();row[2][0][0]='long history '*200000
        history=wire([row])
        await self.context.route('**/data/batchexecute?rpcids=hNvQHb',
            lambda route: route.fulfill(body=history,content_type='text/plain; charset=utf-8'))
        await self.context.route('https://contribution.usercontent.google.com/download?*',
            lambda route: route.fulfill(body=b'actual original file',headers={
                'content-type':'application/octet-stream','content-disposition':'attachment; filename="same.txt"'}))
        await self.page.goto('https://gemini.google.com/app/abcd')
        index=DocumentIndex();self.page._aimemory_gemini_documents=index
        await index.start(self.page)
        try:
            await self.page.evaluate("async()=>{await(await fetch('/data/batchexecute?rpcids=hNvQHb')).text()}")
            for _ in range(100):
                await index.drain()
                if index.lookup(reference(),self.page.url,'same.txt'):break
                await asyncio.sleep(0.05)
            self.assertIsNotNone(index.lookup(reference(),self.page.url,'same.txt'))
            body,_=await _gemini_document_card_download(self.page,
                DocumentCandidate(reference(),self.page.url,'same.txt'),10000)
            self.assertEqual(body,b'actual original file')
            self.assertEqual(self.page.url,'https://gemini.google.com/app/abcd')
            self.assertEqual(len(self.context.pages),1)
            self.assertEqual(await self.page.locator('[role=dialog]').count(),0)
        finally:
            await index.close()
        self.assertFalse(index._pending)
        self.assertFalse(index._tasks)

    async def test_original_download_rejects_wrong_name_empty_and_oversized_files(self):
        await self.page.goto('https://gemini.google.com/app/abcd')
        for body,name,maximum in ((b'actual','wrong.txt',100),(b'','same.txt',100),(b'xx','same.txt',1)):
            async def file_response(route):
                await route.fulfill(body=body,headers={
                    'content-type':'application/octet-stream','content-disposition':f'attachment; filename="{name}"'})
            await self.context.route('https://contribution.usercontent.google.com/download?*',file_response)
            with patch.object(service,'GUI_DOCUMENT_MAX_BYTES',maximum):
                with self.assertRaises(ValueError):
                    await service._gemini_original_document_download(self.page,
                        'https://contribution.usercontent.google.com/download?c=fixture&filename=same.txt','same.txt',10000)
            await self.context.unroute('https://contribution.usercontent.google.com/download?*')

    async def test_generic_video_download_keeps_identity_and_rejects_html_or_oversize(self):
        await self.page.goto('https://gemini.google.com/app/abcd')
        index = DocumentIndex(); index.ingest(wire([entry(files=[file_record('actual.mp4')])]))
        self.page._aimemory_gemini_documents = index
        self.page._aimemory_render_lock = asyncio.Lock()
        other = await self.context.new_page(); await other.goto('https://other.test/blank')
        actual_video = b'\x00\x00\x00\x18ftypmp42' + b'video payload' * 20
        for body, maximum, valid in ((actual_video, len(actual_video), True),
                                      (b'<html>login page</html>', 100, False),
                                      (actual_video, len(actual_video) - 1, False)):
            async def file_response(route):
                await route.fulfill(body=body, headers={
                    'content-type': 'application/octet-stream',
                    'content-disposition': 'attachment; filename="actual.mp4"'})
            await self.context.route('https://contribution.usercontent.google.com/download?*', file_response)
            with patch.object(service, 'GUI_VIDEO_MAX_BYTES', maximum), \
                 patch.object(service, 'GUI_DOCUMENT_MAX_BYTES', 1), \
                 patch.object(service, '_gemini_download_open_card', AsyncMock(return_value=(b'native fallback', {}))) as native:
                captured, headers = await _gemini_document_card_download(self.page,
                    DocumentCandidate(reference(), self.page.url, '上传视频.mp4'), 10000)
            self.assertEqual(captured, actual_video if valid else b'native fallback')
            if valid:
                self.assertIn('actual.mp4', headers['content-disposition'])
                native.assert_not_awaited()
            else:
                native.assert_awaited_once()
            self.assertEqual(self.page.url, 'https://gemini.google.com/app/abcd')
            self.assertEqual(len(self.context.pages), 2)
            await self.context.unroute('https://contribution.usercontent.google.com/download?*')

    async def test_background_gemini_image_fallback_leases_page_and_preserves_full_pixels(self):
        src='https://lh3.googleusercontent.com/gg/fixture=s512'
        picture=Image.new('RGB',(160,100),(192,32,16))
        ImageDraw.Draw(picture).rectangle((0,50,159,99),fill=(16,64,192))
        stream=io.BytesIO();picture.save(stream,format='PNG');png=stream.getvalue()
        async def image_response(route):
            if route.request.resource_type=='image':
                await route.fulfill(body=png,content_type='image/png')
            else:
                await route.fulfill(status=403,body='not available')
        await self.context.route('https://lh3.googleusercontent.com/**',image_response)
        self.body=f'''<style>img[data-test-id="video-thumbnail"]{{clip-path:inset(50% 0 0 0)!important}}</style>
            <img data-test-id="video-thumbnail" _ngcontent-fixture src="{src}">'''
        await self.page.goto('https://gemini.google.com/app/abcd')
        other=await self.context.new_page();await other.goto('https://other.test/blank')
        self.page._aimemory_render_lock=asyncio.Lock()
        self.page.bring_to_front=AsyncMock(wraps=self.page.bring_to_front)
        with tempfile.TemporaryDirectory() as temporary:
            for original in (False,True):
                await other.bring_to_front()
                with patch.object(service,'_authenticated_page_get',AsyncMock(side_effect=RuntimeError('no direct bytes'))), \
                     patch.object(service,'GUI_IMAGE_DOWNLOAD_ATTEMPTS',1):
                    output=Path(temporary)/str(original)
                    mapping=await asyncio.wait_for(service._download_image_candidates(
                        self.page,[src],output,'./images',prefer_original=original),20)
                self.assertIn(src,mapping)
                with Image.open(output/Path(mapping[src]).name) as actual:
                    self.assertEqual(actual.size,picture.size)
                    self.assertEqual(actual.convert('RGB').getpixel((80,25)),(192,32,16))
                    self.assertEqual(actual.convert('RGB').getpixel((80,75)),(16,64,192))
        self.assertGreaterEqual(self.page.bring_to_front.await_count,2)
        self.assertFalse(self.page._aimemory_render_lock.locked())


if __name__ == '__main__':
    unittest.main()
