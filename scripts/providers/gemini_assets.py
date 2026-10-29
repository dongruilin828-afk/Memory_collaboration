"""Original document URLs from the owning page's Gemini history response.

Only the current request's attachment records are indexed. Accumulated context,
model output and arbitrary URLs in conversation text are deliberately ignored.
"""
import base64
import asyncio
import json
import re
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlsplit

from .gemini import VIDEO_EXTENSIONS


def _frames(text):
    if text.startswith(")]}'"):
        text = text.partition("\n")[2]
    decoder = json.JSONDecoder()
    while text.strip():
        text = text.lstrip()
        if text[0].isdigit():
            text = text.partition("\n")[2]
            continue
        try:
            value, end = decoder.raw_decode(text)
        except ValueError:
            return
        yield value
        text = text[end:]


def _at(value, *path):
    for index in path:
        if not isinstance(value, list) or len(value) <= index:
            return None
        value = value[index]
    return value


class DocumentIndex:
    def __init__(self):
        self._urls = {}
        self._session = None
        self._pending = {}
        self._tasks = set()

    def _task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def start(self, page):
        """Observe this page only, without intercepting or replaying requests."""
        try:
            self._session = await page.context.new_cdp_session(page)
            self._session.on("Network.responseReceived", self._received)
            self._session.on("Network.dataReceived", self._data)
            self._session.on("Network.loadingFinished", self._finished)
            self._session.on("Network.loadingFailed", self._finished)
            await self._session.send("Network.enable", {
                "maxResourceBufferSize": 32 * 1024 * 1024,
                "maxTotalBufferSize": 64 * 1024 * 1024,
            })
        except Exception:
            await self.close()

    def _received(self, params):
        response = params.get("response", {})
        parsed = urlsplit(response.get("url", ""))
        if (response.get("status") != 200
                or parsed.hostname != "gemini.google.com"
                or not parsed.path.endswith("/data/batchexecute")
                or "hNvQHb" not in parse_qs(parsed.query).get("rpcids", [""])[0].split(",")
                or len(self._pending) >= 4):
            return
        identifier = params["requestId"]
        state = dict(chunks=[], size=0, overflow=False, ending=False)
        self._pending[identifier] = state
        state["stream"] = self._task(self._stream(identifier))

    async def _stream(self, identifier):
        try:
            value = await asyncio.wait_for(self._session.send(
                "Network.streamResourceContent", {"requestId": identifier}), 10)
            return base64.b64decode(value["bufferedData"])
        except Exception:
            return None

    def _data(self, params):
        state = self._pending.get(params["requestId"])
        if state is None or state["overflow"] or not params.get("data"):
            return
        chunk = base64.b64decode(params["data"])
        state["size"] += len(chunk)
        if state["size"] > 32 * 1024 * 1024:
            state["overflow"] = True
            state["chunks"].clear()
        else:
            state["chunks"].append(chunk)

    def _finished(self, params):
        identifier = params["requestId"]
        state = self._pending.get(identifier)
        if state is not None and not state["ending"]:
            state["ending"] = True
            self._task(self._read(identifier, state))

    async def _read(self, identifier, state):
        try:
            buffered = await state["stream"]
            if state["overflow"]:
                return
            if buffered is not None:
                # Streaming also preserves complete frames before a site aborts
                # an XHR, when getResponseBody no longer has the resource.
                if len(buffered) + state["size"] > 32 * 1024 * 1024:
                    return
                body = buffered + b"".join(state["chunks"])
            else:
                value = await asyncio.wait_for(self._session.send(
                    "Network.getResponseBody", {"requestId": identifier}), 10)
                body = base64.b64decode(value["body"]) if value["base64Encoded"] else value["body"].encode()
            if len(body) <= 32 * 1024 * 1024:
                self.ingest(body.decode("utf-8", "replace"))
        except Exception:
            pass
        finally:
            self._pending.pop(identifier, None)

    async def drain(self):
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def close(self):
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        self._pending.clear()
        if self._session is not None:
            try:
                await self._session.detach()
            except Exception:
                pass
            self._session = None

    def ingest(self, text):
        # batchexecute frames contain typed wrb.fr records; do not recursively
        # search the payload (which also contains old context and user text).
        for frame in _frames(text):
            if not isinstance(frame, list):
                continue
            for record in frame:
                if (_at(record, 0) != "wrb.fr"
                        or _at(record, 1) != "hNvQHb"
                        or not isinstance(_at(record, 2), str)):
                    continue
                try:
                    entries = _at(json.loads(record[2]), 0)
                except ValueError:
                    continue
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    conversation, request = _at(entry, 0, 0), _at(entry, 0, 1)
                    if (not isinstance(conversation, str)
                            or not re.fullmatch(r"c_[0-9a-f]+", conversation)
                            or not isinstance(request, str)
                            or not re.fullmatch(r"r_[0-9a-f]+", request)):
                        continue
                    files = _at(entry, 2, 0, 4, 0, 3)
                    if not isinstance(files, list):
                        continue
                    for file in files:
                        name, url = _at(file, 2), _at(file, 7, 1)
                        if not isinstance(name, str) or not isinstance(url, str):
                            continue
                        parsed = urlsplit(url)
                        query = parse_qs(parsed.query)
                        if (parsed.scheme != "https"
                                or parsed.netloc != "contribution.usercontent.google.com"
                                or parsed.path != "/download"
                                or query.get("filename") != [name]
                                or len(query.get("c", [])) != 1
                                or not query["c"][0]):
                            continue
                        key = conversation, request, name
                        if key not in self._urls:
                            self._urls[key] = url
                        elif self._urls[key] != url:
                            # Same-name versions within one request are ambiguous.
                            self._urls[key] = None

    @staticmethod
    def _identity(reference, conversation_url):
        parsed = urlsplit(conversation_url)
        match = re.fullmatch(r"/(?:app/|gem/[^/]+/)([0-9a-f]+)(?:/)?", parsed.path)
        metadata = re.match(r"^gemini-card:([A-Za-z0-9_+/=-]{20,}):", reference)
        if parsed.hostname != "gemini.google.com" or not match or not metadata:
            return None
        try:
            value = json.loads(base64.b64decode(metadata[1] + "===").decode())
        except (ValueError, UnicodeDecodeError):
            return None
        request, conversation = _at(value, 0, 0), _at(value, 0, 1)
        if (not isinstance(request, str) or not re.fullmatch(r"r_[0-9a-f]+", request)
                or conversation != "c_" + match[1]):
            return None
        return conversation, request

    def lookup(self, reference, conversation_url, filename):
        identity = self._identity(reference, conversation_url)
        return self._urls.get((*identity, filename)) if identity else None

    def lookup_video(self, reference, conversation_url):
        """A generic video card is usable only with one video in that request."""
        identity = self._identity(reference, conversation_url)
        if identity is None:
            return None
        videos = [(name, url) for (conversation, request, name), url in self._urls.items()
                  if (conversation, request) == identity
                  and PurePosixPath(name).suffix.lower() in VIDEO_EXTENSIONS]
        return videos[0] if len(videos) == 1 and videos[0][1] else None
