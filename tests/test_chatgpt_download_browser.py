"""Exercise the actual download JS in Chromium with local route fixtures only."""
import io
import unittest
import zipfile
from unittest.mock import AsyncMock, patch

from PIL import Image
from playwright.async_api import async_playwright

from gui.chatgpt_capture import read_asset
from scripts.providers.chatgpt_source import Asset, SourceError


APP = 'https://capture.example.test'
CDN = 'https://asset.example.test'


class ChatGPTDownloadBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.launch(headless=True)
        except Exception as error:
            await self.playwright.stop()
            if "Executable doesn't exist" in str(error):
                self.skipTest('Install Playwright Chromium to run browser download tests')
            raise
        self.context = await self.browser.new_context()
        await self.context.add_cookies([
            {'name': 'fixture_session', 'value': 'local-fixture', 'url': APP},
            {'name': 'fixture_cdn', 'value': 'must-not-be-sent', 'url': CDN,
             'sameSite': 'None', 'secure': True},
        ])
        self.page = await self.context.new_page()
        self.origin = CDN
        self.body, self.mime = b'# original attachment\n', 'text/markdown'
        self.download_bodies = []
        self.download_headers, self.metadata_headers = [], []
        await self.page.route('**/*', self.respond)
        await self.page.goto(APP)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def respond(self, route):
        url = route.request.url
        headers = route.request.headers
        if url in {APP, APP + '/'}:
            await route.fulfill(content_type='text/html', body='<html>fixture</html>')
        elif url == APP + '/api/auth/session':
            await route.fulfill(json={'accessToken': 'fixture-token'})
        elif url == APP + '/backend-api/files/file_fixture/simple':
            await route.fulfill(json={})
        elif url == APP + '/backend-api/files/download/file_fixture':
            self.metadata_headers.append(headers)
            await route.fulfill(json={'download_url': self.origin + '/signed/file'})
        elif url == self.origin + '/signed/file':
            self.download_headers.append(headers)
            # A normal signed CDN response allows CORS without browser credentials.
            body = self.download_bodies.pop(0) if self.download_bodies else self.body
            await route.fulfill(body=body, headers={
                'content-type': self.mime, 'access-control-allow-origin': '*',
            })
        else:
            await route.abort()

    async def download(self, kind, name):
        return await read_asset(self.page, Asset('file_fixture', name, kind,
            '/backend-api/files/download/file_fixture'))

    async def test_signed_cdn_document_needs_no_browser_credentials(self):
        self.assertEqual(await self.download('document', 'original.md'), (self.body, self.mime))
        self.assertEqual(len(self.download_headers), 1)
        self.assertNotIn('authorization', self.download_headers[0])
        self.assertNotIn('cookie', self.download_headers[0])

    async def test_signed_cdn_image_passes_real_image_validation(self):
        image = io.BytesIO()
        Image.new('RGB', (2, 2), 'blue').save(image, format='PNG')
        self.body, self.mime = image.getvalue(), 'image/png'
        self.assertEqual(await self.download('image', 'original.png'), (self.body, self.mime))

    async def test_same_origin_download_keeps_the_authorized_session(self):
        self.origin = APP
        self.assertEqual(await self.download('document', 'original.md'), (self.body, self.mime))
        for headers in self.metadata_headers + self.download_headers:
            self.assertEqual(headers.get('authorization'), 'Bearer fixture-token')
            self.assertIn('fixture_session=local-fixture', headers.get('cookie', ''))

    async def test_truncated_docx_retries_without_cache_and_returns_complete_file(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as package:
            package.writestr('[Content_Types].xml', '<Types/>')
            package.writestr('word/document.xml', '<document>Complete content</document>')
        self.body = data.getvalue()
        self.mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        self.download_bodies = [self.body[:80], self.body]
        await self.page.evaluate("""() => {
            const request = window.fetch.bind(window);
            window.downloadCacheModes = [];
            window.fetch = (url, options) => {
                if (String(url).includes('/signed/file')) window.downloadCacheModes.push(options.cache);
                return request(url, options);
            };
        }""")
        self.assertEqual(await self.download('document', 'original.docx'), (self.body, self.mime))
        self.assertEqual(len(self.download_headers), 2)
        self.assertEqual(await self.page.evaluate('window.downloadCacheModes'), ['default', 'no-store'])
        for headers in self.download_headers:
            self.assertNotIn('authorization', headers)
            self.assertNotIn('cookie', headers)

    async def test_invalid_docx_is_rejected_after_bounded_retries(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as package:
            package.writestr('unrelated.txt', 'Not a Word document')
        for body in (data.getvalue()[:80], data.getvalue()):
            with self.subTest(truncated=not zipfile.is_zipfile(io.BytesIO(body))):
                self.body = body
                self.mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                self.download_headers.clear()
                with self.assertRaisesRegex(SourceError, 'DOCX'):
                    await self.download('document', 'original.docx')
                self.assertEqual(len(self.download_headers), 3)

    async def test_auth_markers_exclude_cdn_denials_and_challenge_pages(self):
        for phase, origin, status, challenge, expected in (
            ('metadata', APP, 401, False, True),
            ('metadata', APP, 403, True, False),
            ('download', APP, 403, False, True),
            ('download', CDN, 403, False, False),
        ):
            with self.subTest(phase=phase, origin=origin, challenge=challenge):
                async def deny(route):
                    await route.fulfill(status=status, body='denied', headers={
                        'access-control-allow-origin': '*',
                        **({'cf-mitigated': 'challenge'} if challenge else {}),
                    })
                self.origin = origin
                target = APP + '/backend-api/files/download/file_fixture' if phase == 'metadata' else origin + '/signed/file'
                await self.page.route(target, deny)
                with patch.object(self.page, 'wait_for_timeout', new=AsyncMock()):
                    with self.assertRaises(SourceError) as caught:
                        await self.download('document', 'original.md')
                self.assertEqual(caught.exception.auth_required, expected)
                await self.page.unroute(target, deny)


if __name__ == '__main__':
    unittest.main()
