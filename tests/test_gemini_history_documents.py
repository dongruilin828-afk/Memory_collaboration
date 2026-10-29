import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

from gui import service
from scripts.providers.gemini_assets import DocumentIndex


def reference(request="r_0123", conversation="c_abcd"):
    data = base64.b64encode(json.dumps([[request, conversation]]).encode()).decode()
    return "gemini-card:" + data + ":same.txt"


def file_record(name="same.txt", token="first"):
    return [None, 3, name, None, None, "opaque", None, [
        "https://drive.google.com/preview", "https://contribution.usercontent.google.com/download?c="
        + token + "&filename=" + quote(name), "https://drive.google.com/view"]]


def entry(request="r_0123", files=None, conversation="c_abcd", context=None):
    return [[conversation, request], [conversation, "r_9999"],
            [["question", None, None, None, [[None, None, None,
                files if files is not None else [file_record()], context or []]]]]]


def wire(entries, rpc="hNvQHb"):
    frame = json.dumps([["wrb.fr", rpc, json.dumps([entries])]])
    return ")]}'\n\n" + str(len(frame)) + "\n" + frame + "\n"


class HistoryIdentityTests(unittest.TestCase):
    def test_current_request_only_and_same_name_versions_remain_separate(self):
        index = DocumentIndex()
        index.ingest(wire([entry(), entry("r_4567", [file_record(token="second")])]))
        self.assertIn("c=first", index.lookup(reference(), "https://gemini.google.com/app/abcd", "same.txt"))
        self.assertIn("c=second", index.lookup(reference("r_4567"), "https://gemini.google.com/app/abcd", "same.txt"))
        self.assertIsNone(index.lookup(reference(), "https://gemini.google.com/app/aaaa", "same.txt"))
        self.assertIsNone(index.lookup(reference(), "https://gemini.google.com/share/abcd", "same.txt"))
        self.assertIsNone(index.lookup(reference(), "https://chatgpt.com/app/abcd", "same.txt"))

    def test_context_model_text_and_other_rpc_cannot_supply_a_file(self):
        row = entry(files=[], context=[file_record()])
        row.append(file_record())
        index = DocumentIndex()
        index.ingest(wire([row])); index.ingest(wire([entry()], rpc="different"))
        self.assertIsNone(index.lookup(reference(), "https://gemini.google.com/app/abcd", "same.txt"))

    def test_ambiguous_or_wrong_host_or_filename_are_not_used(self):
        for records in ([file_record(), file_record(token="second")],
                        [file_record(name="different.txt")]):
            index = DocumentIndex(); index.ingest(wire([entry(files=records)]))
            self.assertIsNone(index.lookup(reference(), "https://gemini.google.com/app/abcd", "same.txt"))
        bad = file_record(); bad[7][1] = bad[7][1].replace(".google.com", ".google.com.evil.test")
        index = DocumentIndex(); index.ingest(wire([entry(files=[bad])]))
        self.assertIsNone(index.lookup(reference(), "https://gemini.google.com/app/abcd", "same.txt"))

    def test_incomplete_and_malformed_data_fall_back(self):
        index = DocumentIndex()
        for value in ("not JSON", ")]}'\n1\n[]", wire([None, [], entry(files=[None, []])])):
            index.ingest(value)
        self.assertIsNone(index.lookup("gemini-card:filename", "https://gemini.google.com/app/abcd", "same.txt"))
        self.assertIsNone(index.lookup(reference([]), "https://gemini.google.com/app/abcd", "same.txt"))

    def test_generic_video_is_bound_to_unique_current_request_not_other_messages(self):
        index = DocumentIndex()
        index.ingest(wire([entry(files=[file_record("actual.mp4"), file_record("report.pptx")]),
                           entry("r_4567", [file_record("other.mp4")])]))
        video = index.lookup_video(reference(), "https://gemini.google.com/app/abcd")
        self.assertEqual(video[0], "actual.mp4")
        self.assertEqual(video[1], index.lookup(reference(), "https://gemini.google.com/app/abcd", "actual.mp4"))
        self.assertIsNone(index.lookup_video(reference(), "https://gemini.google.com/app/ffff"))

    def test_generic_video_rejects_multiple_or_ambiguous_attachments(self):
        for files in ([file_record("one.mp4"), file_record("two.webm")],
                      [file_record("one.mp4"), file_record("one.mp4", "different")],
                      [file_record("one.txt")]):
            index = DocumentIndex(); index.ingest(wire([entry(files=files)]))
            self.assertIsNone(index.lookup_video(reference(), "https://gemini.google.com/app/abcd"))


class HistoryDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_keeps_complete_frame_when_history_request_is_cancelled(self):
        text=wire([entry()]).encode();split=len(text)//2
        session=SimpleNamespace(send=AsyncMock(return_value={"bufferedData":base64.b64encode(text[:split]).decode()}),
                                detach=AsyncMock())
        index=DocumentIndex();index._session=session
        index._received(dict(requestId="one",response=dict(status=200,
            url="https://gemini.google.com/data/batchexecute?rpcids=hNvQHb")))
        index._data(dict(requestId="one",data=base64.b64encode(text[split:]).decode()))
        index._finished(dict(requestId="one",canceled=True))
        await index.drain()
        self.assertIsNotNone(index.lookup(reference(),"https://gemini.google.com/app/abcd","same.txt"))
        await index.close();session.detach.assert_awaited_once()

    async def test_unsupported_stream_uses_body_and_closes_collector(self):
        async def send(method,*args):
            if method=="Network.streamResourceContent":raise RuntimeError("unsupported")
            return dict(body=wire([entry()]),base64Encoded=False)
        index=DocumentIndex();index._session=SimpleNamespace(send=AsyncMock(side_effect=send),detach=AsyncMock())
        index._received(dict(requestId="one",response=dict(status=200,
            url="https://gemini.google.com/data/batchexecute?rpcids=hNvQHb")))
        index._finished(dict(requestId="one"));await index.drain()
        self.assertIsNotNone(index.lookup(reference(),"https://gemini.google.com/app/abcd","same.txt"))
        await index.close();self.assertFalse(index._pending)

    async def test_oversized_history_and_other_pages_cannot_add_records(self):
        index=DocumentIndex();index._session=SimpleNamespace(send=AsyncMock(return_value={"bufferedData":""}),detach=AsyncMock())
        index._received(dict(requestId="foreign",response=dict(status=200,
            url="https://other.test/data/batchexecute?rpcids=hNvQHb")))
        self.assertFalse(index._pending)
        index._received(dict(requestId="one",response=dict(status=200,
            url="https://gemini.google.com/data/batchexecute?rpcids=hNvQHb")))
        index._pending['one']['size']=32*1024*1024
        index._data(dict(requestId="one",data=base64.b64encode(b'x').decode()))
        index._finished(dict(requestId="one"));await index.drain()
        self.assertFalse(index._urls);await index.close()

    async def test_verified_original_avoids_viewer(self):
        index = DocumentIndex(); index.ingest(wire([entry()]))
        page = SimpleNamespace(_aimemory_gemini_documents=index, url="https://gemini.google.com/app/abcd")
        with patch.object(service, "_gemini_original_document_download", AsyncMock(return_value=(b"actual original", {}))) as get:
            body, _headers = await service._gemini_document_card_download(page,
                service.DocumentCandidate(reference(), page.url, "same.txt"), 5000)
        self.assertEqual(body, b"actual original")
        self.assertIn("c=first", get.await_args.args[1])
        self.assertEqual(get.await_args.args[2], "same.txt")

    async def test_bad_or_expired_download_retains_native_fallback(self):
        for error in (TimeoutError(), ValueError("wrong filename"), ValueError("empty body")):
            index = DocumentIndex(); index.ingest(wire([entry()]))
            page = SimpleNamespace(_aimemory_gemini_documents=index, url="https://gemini.google.com/app/abcd")
            with patch.object(service, "_gemini_original_document_download", AsyncMock(side_effect=error)), \
                 patch.object(service, "_gemini_download_open_card", AsyncMock(return_value=(b"native", {}))) as native:
                body, _headers = await service._gemini_document_card_download(page,
                    service.DocumentCandidate(reference(), page.url, "same.txt"), 5000)
            self.assertEqual(body, b"native"); native.assert_awaited_once()

    async def test_generic_video_uses_verified_real_name_and_ambiguity_falls_back(self):
        page = SimpleNamespace(url="https://gemini.google.com/app/abcd")
        for files, direct_expected in (([file_record("actual.mp4")], True),
                                       ([file_record("one.mp4"), file_record("two.mp4")], False)):
            index = DocumentIndex(); index.ingest(wire([entry(files=files)]))
            page._aimemory_gemini_documents = index
            with patch.object(service, "_gemini_original_document_download", AsyncMock(return_value=(b"original video", {}))) as direct, \
                 patch.object(service, "_gemini_download_open_card", AsyncMock(return_value=(b"native video", {}))) as native:
                body, _ = await service._gemini_document_card_download(page,
                    service.DocumentCandidate(reference(), page.url, "上传视频.mp4"), 5000)
            if direct_expected:
                self.assertEqual(body, b"original video")
                self.assertEqual(direct.await_args.args[2], "actual.mp4")
                native.assert_not_awaited()
            else:
                self.assertEqual(body, b"native video")
                direct.assert_not_awaited(); native.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
