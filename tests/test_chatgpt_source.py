"""Regression cases for wrong conversations, virtualized text and file ownership."""
import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from gui.chatgpt_capture import capture_conversation, read_asset, save_asset, rich_markdown, rendered_messages
from scripts.providers.chatgpt_source import Message
from bs4 import BeautifulSoup
from scripts.providers import chatgpt
from scripts.providers.chatgpt_source import Asset, SourceError, resolve_citations, source_messages
from scripts.providers.chatgpt_markdown import prepare_markdown


CID = "12345678-1234-1234-1234-123456789abc"
URL = f"https://chatgpt.com/c/{CID}"


def node(key, role, text="", parent=None, **metadata):
    return {"id": key, "parent": parent, "message": {
        "id": key, "author": {"role": role}, "recipient": "all",
        "content": {"content_type": "text", "parts": [text]}, "metadata": metadata}}


def payload(*nodes):
    return {"conversation_id": CID, "current_node": nodes[-1]["id"],
            "mapping": {n["id"]: n for n in nodes}}


class ChatGPTSourceTests(unittest.TestCase):
    def test_grouped_citation_keeps_primary_and_all_supporting_websites(self):
        marker = "\ue200cite\ue202turn1view0\ue202turn1view1\ue201"
        primary = {"title": "Primary", "url": "https://example.com/main"}
        second = {"title": "Second [source]", "url": "https://example.org/second"}
        third = {"url": "https://example.net/third"}
        metadata = [{"content_references": [{"type": "grouped_webpages", "matched_text": marker,
            "items": [{**primary, "thumbnail_url": "https://images.openai.com/icon",
                "supporting_websites": [second, third, second, {"url": "javascript:alert(1)"}]}]}],
            "search_result_groups": [{"entries": [{"url": "https://example.org/unused"}]}]}]
        expected = ("Answer [Primary](https://example.com/main) "
            "[Second &#91;source&#93;](https://example.org/second) [example.net](https://example.net/third).")
        result = resolve_citations("Answer " + marker + ".", metadata, {})
        self.assertEqual(result, expected)
        self.assertEqual(prepare_markdown(result), expected)

    def test_grouped_citation_without_supporting_sites_is_unchanged(self):
        marker = "\ue200cite\ue202turn1view0\ue201"
        for extra in ({}, {"supporting_websites": None}, {"supporting_websites": []}):
            metadata = [{"content_references": [{"type": "grouped_webpages", "matched_text": marker,
                "items": [{"title": "Primary", "url": "https://example.com/main", **extra}]}]}]
            text = "  First line\n\n```python\n    x = 1\n```\n" + marker
            self.assertEqual(resolve_citations(text, metadata, {}),
                text.replace(marker, "[Primary](https://example.com/main)"))

    def test_supporting_title_punctuation_is_literal_not_math_or_code(self):
        marker = "\ue200cite\ue202turn1view0\ue201"
        metadata = [{"content_references": [{"type": "grouped_webpages", "matched_text": marker,
            "items": [{"url": "https://example.com/main", "supporting_websites": [
                {"url": "https://example.org/removed", "title": "[Removed]"},
                {"url": "https://example.org/cost", "title": "$5 *price* `code` <tag>"}]}]}]}]
        result = prepare_markdown(resolve_citations(marker, metadata, {}))
        self.assertIn("[&#91;Removed&#93;](https://example.org/removed)", result)
        self.assertIn("[&#36;5 &#42;price&#42; &#96;code&#96; &lt;tag&gt;]", result)
        self.assertNotIn("$$", result)

    def test_primary_citation_title_brackets_cannot_turn_into_math(self):
        marker = "\ue200cite\ue202turn3view1\ue201"
        item = {"url": "https://example.com/removed", "title": "[ Removed by moderator ] : r/codex"}
        meta = {"content_references": [{"type": "grouped_webpages", "matched_text": marker, "items": [item]}]}
        text = prepare_markdown(resolve_citations("Answer " + marker, [meta], {}))
        self.assertEqual(text, "Answer [&#91; Removed by moderator &#93; : r/codex](https://example.com/removed)")
        row = Message("a", "AI", ["a"], "", rich=True, metadata=[{
            "model_dil_v2": {"appData": {"opGenui": {"componentResults": {
                "cite": {"status": "resolved", "componentName": "Cite", "state": {"items": [item]}}
            }}}}}])
        rich = prepare_markdown(rich_markdown(row, {"a": '<div class="markdown"><p>Answer</p></div>'}, {}))
        self.assertIn("[&#91; Removed by moderator &#93; : r/codex](https://example.com/removed)", rich)
        self.assertNotIn("$$", rich)

    def test_private_project_login_and_document_response_routes_are_separate(self):
        from gui.service import requires_authenticated_browser, _is_document_content_response
        project = f"https://chatgpt.com/g/g-p-project/c/{CID}"
        self.assertTrue(requires_authenticated_browser(project))
        self.assertFalse(requires_authenticated_browser(f"https://chatgpt.com/share/{CID}"))
        self.assertFalse(_is_document_content_response(project))
        self.assertFalse(_is_document_content_response(f"https://chatgpt.com/backend-api/conversation/{CID}"))
        self.assertTrue(_is_document_content_response("https://chatgpt.com/backend-api/files/download/file_test"))
        self.assertTrue(_is_document_content_response("https://chatgpt.com/backend-api/estuary/content?id=file_test"))

    def test_zero_width_citation_footnote_never_replaces_spaces_or_code(self):
        text = "words with spaces\n\n```python\n    x = 1\n```"
        metadata = [{"content_references": [{"type": "sources_footnote", "matched_text": " ", "start_idx": 10, "end_idx": 10}]}]
        self.assertEqual(resolve_citations(text, metadata, {}), text)

    def test_interactive_formula_and_map_require_identity_matched_dom(self):
        for kind in ("map", "client_defined_widget", "dil", "image_group"):
            data = payload(node("a", "assistant", "widget", content_references=[{"type": kind}]))
            self.assertTrue(source_messages(data, URL)[0].rich)

    def test_reject_wrong_conversation_even_if_it_has_more_messages(self):
        data = payload(node("a", "user", "unrelated"))
        data["conversation_id"] = "wrong"
        with self.assertRaises(SourceError):
            source_messages(data, URL)

    def test_only_active_branch_and_no_internal_messages(self):
        data = payload(node("root", "system", "secret"), node("u", "user", "question", "root"),
                       node("old", "assistant", "old answer", "u"), node("new", "assistant", "new answer", "u"))
        self.assertEqual([m.text for m in source_messages(data, URL)], ["question", "new answer"])

    def test_incomplete_or_cyclic_branch_is_not_success(self):
        for parent in ("missing", "u"):
            with self.subTest(parent=parent), self.assertRaises(SourceError):
                source_messages(payload(node("u", "user", "text", parent)), URL)

    def test_long_user_input_indentation_and_language_fence_preserved(self):
        text = "\n\n  nested\n\n" + "log line\n" * 4000 + "    final line  \n"
        code = "```python\nimport math\n\nx = 10\nprint(math.sqrt(x))\n```"
        rows = source_messages(payload(node("u", "user", text), node("a", "assistant", code, "u")), URL)
        self.assertEqual([r.text for r in rows], [text, code])

    def test_combine_same_exchange_but_keep_distinct_identical_task_replies(self):
        data = payload(node("u", "user", "Q"),
                       node("a", "assistant", "first", "u", turn_exchange_id="turn1"),
                       node("b", "assistant", "second", "a", turn_exchange_id="turn1"),
                       node("c", "assistant", "task created", "b", turn_exchange_id="turn2"),
                       node("d", "assistant", "task created", "c", turn_exchange_id="turn3"))
        self.assertEqual([m.text for m in source_messages(data, URL)],
                         ["Q", "first\n\nsecond", "task created", "task created"])

    def test_all_generated_images_stay_with_their_reply(self):
        first = node("g1", "tool", parent="u")
        first["message"]["content"] = {"content_type": "multimodal_text", "parts": [
            {"content_type": "image_asset_pointer", "asset_pointer": "sediment://file_one", "metadata": {"dalle": {"prompt": "private drawing prompt"}}}]}
        # Empty metadata containers do not identify generation; real metadata is nonempty.
        second = node("g2", "tool", parent="g1")
        second["message"]["content"] = {"parts": [{"content_type": "image_asset_pointer",
            "asset_pointer": "sediment://file_two", "metadata": {"generation": {"id": "g"}}}]}
        rows = source_messages(payload(node("u", "user", "draw"), first, second,
                                       node("empty", "assistant", "", "g2")), URL)
        self.assertEqual(len(rows), 2)
        self.assertEqual([a.key for a in rows[1].assets], ["file_one", "file_two"])
        self.assertEqual(rows[1].text, "")

    def test_zip_and_markdown_keep_identity_with_repeated_filenames(self):
        rows = source_messages(payload(
            node("u1", "user", "first", attachments=[{"id": "file_zip", "name": "logs.zip"}, {"id": "file_md1", "name": "notes.md"}]),
            node("u2", "user", "second", "u1", attachments=[{"id": "file_md2", "name": "notes.md"}]),
        ), URL)
        self.assertEqual([a.key for a in rows[0].assets], ["file_zip", "file_md1"])
        self.assertEqual([a.key for a in rows[1].assets], ["file_md2"])

    def test_generated_file_is_not_confused_with_user_upload_or_code_example(self):
        rows = source_messages(payload(node("u", "user", "Q", attachments=[{"id": "file_doc", "name": "report.docx"}]),
            node("a", "assistant", "[report](sandbox:/mnt/data/report.docx)\n\n```md\n[sample](sandbox:/mnt/data/example.txt)\n```", "u")), URL)
        self.assertEqual(len(rows[1].assets), 1)
        self.assertNotEqual(rows[0].assets[0].key, rows[1].assets[0].key)
        self.assertIn("message_id=a", rows[1].assets[0].endpoint)

    def test_share_generated_file_uses_server_declared_backing_conversation(self):
        data = payload(node("a", "assistant", "[report](sandbox:/mnt/data/report.docx)"))
        backing = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        data["backing_conversation_id"] = backing
        row = source_messages(data, f"https://chatgpt.com/share/{CID}")[0]
        self.assertIn(f"/conversation/{backing}/interpreter/download", row.assets[0].endpoint)
        self.assertIn(f"shared_conversation_id={CID}", row.assets[0].endpoint)

    def test_content_hash_dedup_and_same_name_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = {}; root = Path(temp)
            a = Asset("file1", "../same.md", "document", "/endpoint")
            first = save_asset(b"first", a, root, "./docs", cache)
            second = save_asset(b"second", a, root, "./docs", cache)
            again = save_asset(b"first", a, root, "./docs", cache)
            self.assertNotEqual(first, second)
            self.assertEqual(first, again)
            self.assertEqual(len(list(root.iterdir())), 2)
            self.assertTrue(all(f.parent == root for f in root.iterdir()))


class ChatGPTCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_widget_placeholder_does_not_block_verified_conversation(self):
        placeholder = "正在生成 无人机飞越群山湖泊"
        for kinds, identifier, visible, succeeds in (
            (("client_defined_widget",), "answer", placeholder, True),
            (("client_defined_widget",), "answer", "", False),
            (("client_defined_widget",), "other", placeholder, False),
            (("map",), "answer", placeholder, False),
            (("client_defined_widget", "map"), "answer", placeholder, False),
        ):
            with self.subTest(kinds=kinds, identifier=identifier, visible=visible):
                page = AsyncMock()
                page.url = URL
                scroll = AsyncMock()
                scroll.evaluate.return_value = True
                page.evaluate_handle.return_value = scroll
                async def evaluate(script, arg):
                    if "id=>" in script:
                        return True
                    return [{"ids": [identifier], "text": visible,
                             "html": '<div class="markdown"><span class="sr-only">hidden label</span>'
                                     '<div data-markdown-copy="exclude" aria-hidden="true">' + visible + '</div></div>'}]
                page.evaluate.side_effect = evaluate
                data = payload(node("question", "user", "生成动画"),
                    node("answer", "assistant", "widget implementation\n" * 400, "question",
                         content_references=[{"type": kind} for kind in kinds]))
                options = dict(images_dir=Path("unused"), image_prefix="./images",
                               documents_dir=Path("unused"), document_prefix="./docs")
                if succeeds:
                    result = await capture_conversation(page, URL, data, **options)
                    self.assertEqual([m["role"] for m in result["messages"]], ["User", "AI"])
                    self.assertEqual(result["messages"][-1]["content"], "（交互组件暂未导出）")
                    self.assertNotIn("hidden label", result["html"])
                    self.assertNotIn("widget implementation", result["html"])
                    self.assertTrue(any("交互组件导出未完成" in w for w in result["warnings"]))
                else:
                    with self.assertRaises(SourceError):
                        await capture_conversation(page, URL, data, **options)

    async def test_windows_source_newlines_survive_snapshot_and_markdown_file_roundtrip(self):
        from gui.service import generate_raw_markdown
        text = "  first\r\n\r\n    nested code\r\n"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = await capture_conversation(None, URL, payload(node("u", "user", text)),
                images_dir=root, image_prefix="./images", documents_dir=root, document_prefix="./docs")
            content = result["messages"][0]["content"]
            self.assertEqual(content, "  first\n\n    nested code\n")
            snapshot = root / "snapshot.html"
            snapshot.write_text(result["html"], encoding="utf-8")
            reparsed = chatgpt.parse_messages(BeautifulSoup(snapshot.read_text(encoding="utf-8"), "html.parser"))
            self.assertEqual(reparsed[0]["content"], content)
            output = root / "export.md"
            generate_raw_markdown(result["messages"], output)
            self.assertIn(content, output.read_text(encoding="utf-8"))
            self.assertNotIn(b"\r\r\n", output.read_bytes())

    async def test_reverse_list_accepts_exact_message_but_rejects_shared_exchange(self):
        for identifier, succeeds in (("answer", True), ("exchange", False), ("other", False)):
            with self.subTest(identifier=identifier):
                page = AsyncMock()
                page.url = URL
                scroll = AsyncMock()
                scroll.evaluate.return_value = True
                page.evaluate_handle.return_value = scroll
                async def evaluate(script, arg):
                    if "at_first" in script or "id=>" in script:
                        return True
                    return [{"ids": [identifier], "text": "A complete visible answer.",
                             "html": '<div class="markdown">A complete visible answer.</div>'}]
                page.evaluate.side_effect = evaluate
                rows = [Message("question", "User", ["question", "exchange"], "Q"),
                        Message("answer", "AI", ["answer", "exchange"], "A complete visible answer.",
                                exchange_id="exchange", rich=True)]
                if succeeds:
                    result = await rendered_messages(page, URL, rows)
                    self.assertIn("answer", result)
                else:
                    with self.assertRaises(SourceError):
                        await rendered_messages(page, URL, rows)
                self.assertTrue(any(call.args == ('(e,reverse)=>e.scrollTop=reverse?-e.scrollHeight:0', True)
                                    for call in scroll.evaluate.await_args_list))

    async def test_visible_process_note_retained_without_internal_tool_instruction(self):
        progress = node("progress", "assistant", "I will compare the files.", "u")
        progress["message"]["channel"] = "commentary"
        hidden = node("internal", "assistant", "internal tool instruction", "progress")
        hidden["message"].update(channel="commentary", recipient="python")
        data = payload(node("u", "user", "compare"), progress, hidden, node("a", "assistant", "Final result", "internal"))
        with tempfile.TemporaryDirectory() as temp:
            result = await capture_conversation(None, URL, data, images_dir=Path(temp), image_prefix="./images",
                                                 documents_dir=Path(temp), document_prefix="./docs")
        self.assertEqual(result["messages"][1]["content"], "I will compare the files.\n\nFinal result")
        self.assertIn("progress", result["messages"][1]["source_ids"])
        self.assertNotIn("internal", result["messages"][1]["source_ids"])

    async def test_empty_markdown_is_a_valid_file(self):
        page = AsyncMock()
        page.evaluate.return_value = {"status":200,"body":"","content_type":"text/markdown"}
        body, mime = await read_asset(page, Asset("file_empty", "empty.md", "document", "/backend-api/files/download/file_empty"))
        self.assertEqual((body,mime), (b"", "text/markdown"))
        page.evaluate.assert_awaited_once()

    async def test_cli_reuses_verified_capture_without_a_second_browser(self):
        from gui.service import FetchResult
        from scripts.parser import fetch_chat_content
        with patch("gui.service.fetch_chat_pipeline", new=AsyncMock(return_value=FetchResult(
            html="verified", messages=[], image_map={"image":"./image.png"}, document_map={"doc":"./doc.md"}))) as fetch:
            result = await fetch_chat_content(URL)
        self.assertEqual(result, ("verified", {"image":"./image.png", "doc":"./doc.md"}))
        fetch.assert_awaited_once()

    def test_verified_snapshot_round_trip_keeps_markdown_and_indentation(self):
        markup = '<section data-message-author-role="user"><pre data-source-markdown="true">  code\n\n    nested  </pre></section>'
        self.assertEqual(chatgpt.parse_messages(BeautifulSoup(markup, "html.parser"))[0]["content"], "  code\n\n    nested  ")

    def test_rich_code_language_and_diagram_survive_without_copy_toolbar(self):
        fragment = '''<div data-message-author-role="assistant"><div class="markdown">
        <div data-markdown-copy="code-block"><header>Python 运行</header><pre><code class="language-python">x = 1\n    y = 2</code></pre></div>
        <svg role="img"><text>axis</text><script>bad()</script></svg></div></div>'''
        text = rich_markdown(Message("a", "AI", ["a"], "", rich=True), {"a": fragment}, {})
        self.assertIn("```python\nx = 1\n    y = 2", text)
        self.assertNotIn("运行", text)
        self.assertIn("data:image/svg+xml;base64,", text)

    def test_map_controls_removed_but_place_names_and_prose_preserved(self):
        fragment = '''<div class="markdown"><div class="mapboxgl-map">
        <div class="mapboxgl-marker"><span>Example cafe</span></div>
        <div class="mapboxgl-touch-pan-blocker">Use two fingers to move the map</div>
        <div class="mapboxgl-scroll-zoom-blocker">Use ctrl + scroll to zoom the map</div>
        <div class="mapboxgl-control-container">Zoom out</div></div><p>Visible answer.</p></div>'''
        text = rich_markdown(Message("a", "AI", ["a"], "", rich=True), {"a": fragment}, {})
        self.assertIn("Example cafe", text)
        self.assertIn("Visible answer.", text)
        self.assertNotIn("Use two fingers", text)
        self.assertNotIn("Use ctrl", text)
        self.assertNotIn("Zoom out", text)

    def test_rich_citation_destinations_preserved_without_unused_search_results(self):
        row = Message("a", "AI", ["a"], "", rich=True, metadata=[{
            "search_result_groups": [{"entries": [
                {"url": "https://example.com/source?utm_source=chatgpt.com", "title": "Original source"},
                {"url": "https://example.com/unused", "title": "Unused search result"}]}],
            "genui_components": [{"type": "cite", "safe_urls": [
                {"url": "https://example.com/source"},
                {"url": "https://example.com/source?id=2"},
                {"url": "https://images.openai.com/static-rsc-1/icon"}]}]}])
        text = rich_markdown(row, {"a": '<div class="markdown"><p>Visible answer. example.com +1</p></div>'}, {})
        self.assertIn("[Original source](https://example.com/source)", text)
        self.assertIn("https://example.com/source?id=2", text)
        self.assertNotIn("/unused", text)
        self.assertNotIn("static-rsc", text)
        row.metadata = [{"model_dil_v2": {"appData": {"opGenui": {"componentResults": {
            "resolved-cite": {"status": "resolved", "componentName": "Cite", "state": {
                "items": [{"url": "https://example.com/private-source", "title": "Private-view citation",
                           "thumbnail_url": "https://images.openai.com/icon"}]}}
        }}}}}]
        text = rich_markdown(row, {"a": '<div class="markdown"><p>Visible answer.</p></div>'}, {})
        self.assertIn("[Private-view citation](https://example.com/private-source)", text)
        self.assertNotIn("images.openai.com", text)

    def test_rich_reply_keeps_current_citation_supporting_sites_only(self):
        marker = "\ue200cite\ue202turn1view0\ue201"
        item = {"url": "https://example.com/main", "supporting_websites": [
            {"url": "https://example.org/extra", "title": "[Extra]"}]}
        row = Message("a", "AI", ["a"], "Answer " + marker, rich=True, metadata=[{
            "content_references": [
                {"type": "grouped_webpages", "matched_text": marker, "items": [item]},
                {"type": "grouped_webpages", "matched_text": "\ue200cite\ue202unused\ue201", "items": [{
                    "supporting_websites": [{"url": "https://example.org/unused", "title": "Unused"}]}]}]}])
        dom = '<div class="markdown"><p>Answer <a href="https://example.com/main">Primary</a></p></div>'
        text = prepare_markdown(rich_markdown(row, {"a": dom}, {}))
        self.assertIn("[Primary](https://example.com/main)", text)
        self.assertIn("[&#91;Extra&#93;](https://example.org/extra)", text)
        self.assertNotIn("example.org/unused", text)
        row.metadata[0]["content_references"][0]["items"][0]["supporting_websites"].append(
            {"url": "https://example.com/main", "title": "Primary"})
        self.assertEqual(prepare_markdown(rich_markdown(row, {"a": dom}, {})), text)
        row.metadata[0]["content_references"][0]["items"][0]["supporting_websites"].append(
            {"url": "https://example.com/mai", "title": "Distinct URL prefix"})
        self.assertIn("[Distinct URL prefix](https://example.com/mai)", rich_markdown(row, {"a": dom}, {}))

    async def test_export_has_every_file_link_in_exact_owner_and_no_ui_text(self):
        data = payload(node("u1", "user", "  text\n\n    code  ", attachments=[{"id": "file_a", "name": "a.md"}]),
                       node("a1", "assistant", "```python\nx = 1\n```", "u1"),
                       node("u2", "user", "second", "a1", attachments=[{"id": "file_b", "name": "b.zip"}]))
        async def download(page, asset):
            return asset.key.encode(), "application/octet-stream"
        with tempfile.TemporaryDirectory() as temp, patch("gui.chatgpt_capture.read_asset", side_effect=download):
            result = await capture_conversation(None, URL, data, images_dir=Path(temp)/"images", image_prefix="./images",
                                                 documents_dir=Path(temp)/"docs", document_prefix="./docs")
        self.assertIn("a.md", result["messages"][0]["content"])
        self.assertNotIn("a.md", result["messages"][2]["content"])
        self.assertIn("b.zip", result["messages"][2]["content"])
        self.assertTrue(result["messages"][0]["content"].endswith("  text\n\n    code  "))
        self.assertEqual(result["messages"][1]["content"], "```python\nx = 1\n```")
        self.assertFalse(result["warnings"])

    async def test_failed_zip_has_explicit_message_and_warning(self):
        data = payload(node("u", "user", "Q", attachments=[{"id": "file_zip", "name": "archive.zip"}]))
        with tempfile.TemporaryDirectory() as temp, patch("gui.chatgpt_capture.read_asset", side_effect=SourceError("HTTP 403")):
            result = await capture_conversation(None, URL, data, images_dir=Path(temp), image_prefix="./images",
                                                 documents_dir=Path(temp), document_prefix="./docs")
        self.assertIn("附件未下载", result["messages"][0]["content"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertFalse(result["document_map"])

    async def test_asset_auth_failure_is_propagated_without_changing_capture_shape(self):
        data = payload(node("u", "user", "Q", attachments=[{"id": "file_zip", "name": "archive.zip"}]))
        error = SourceError("HTTP 401")
        error.auth_required = True
        authorization = []
        with tempfile.TemporaryDirectory() as temp, patch("gui.chatgpt_capture.read_asset", side_effect=error):
            result = await capture_conversation(None, URL, data, images_dir=Path(temp), image_prefix="./images",
                documents_dir=Path(temp), document_prefix="./docs", authorization_required=authorization)
        self.assertEqual(authorization, [True])
        self.assertNotIn('authorization_required', result)
        self.assertTrue(result['warnings'])


if __name__ == "__main__":
    unittest.main()
