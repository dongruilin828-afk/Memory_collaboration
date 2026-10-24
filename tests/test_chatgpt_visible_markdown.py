"""Human-review regressions: visible prose versus source-only UI metadata."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from scripts.providers.chatgpt_markdown import prepare_markdown, strip_receiver_followups
from scripts.providers.chatgpt_source import source_messages
from tests.test_chatgpt_source import URL, node, payload
from gui.chatgpt_capture import capture_conversation


class VisibleMarkdownTests(unittest.TestCase):
    def test_followup_appendix_requires_metadata_and_preserves_original_offer(self):
        original = "Answer.\n\n如果你愿意，我可以继续解释。"
        appendix = "\n\n---\n\n如果你愿意，我可以：\n\n- First suggestion\n- Second suggestion"
        meta = {"content_references": [{"type": "followup_a", "source": "receiver_followups_tailored",
                                        "matched_text": name} for name in ("First suggestion", "Second suggestion")]}
        self.assertEqual(strip_receiver_followups(original + appendix, meta), original)
        self.assertEqual(strip_receiver_followups(original + appendix, {}), original + appendix)
        example = "```md\n" + original + appendix + "\n```"
        self.assertEqual(strip_receiver_followups(example, meta), example)

    def test_thinking_preamble_not_exported_but_ordinary_commentary_kept(self):
        hidden = node("p", "assistant", "thinking preview", "u", is_thinking_preamble_message=True)
        hidden["message"]["channel"] = "commentary"
        visible = node("v", "assistant", "visible progress", "p")
        visible["message"]["channel"] = "commentary"
        rows = source_messages(payload(node("u", "user", "question"), hidden, visible,
                                       node("a", "assistant", "answer", "v")), URL)
        self.assertEqual(rows[1].text, "answer")
        self.assertEqual([p["text"] for p in rows[1].commentary], ["visible progress"])

    def test_latex_uses_renderable_delimiters_without_touching_code(self):
        text = r"Inline \(a_1+b^2\)" + "\n\n" + r"\[" + "\n" + r"64\times4=256\text{ bit}" + "\n" + r"\]"
        expected = "Inline $a_1+b^2$\n\n$$\n" + r"64\times4=256\text{ bit}" + "\n$$"
        self.assertEqual(prepare_markdown(text), expected)
        literals = ["```python\n" + text + "\n```", "````md\n```\n" + text + "\n```\n````",
                    "~~~text\n" + text + "\n~~~", r"Code `\(x\)` and ``\[y\]``", "```\n" + text]
        for literal in literals:
            self.assertEqual(prepare_markdown(literal), literal)
        self.assertEqual(prepare_markdown(expected), expected)

    def test_pasted_python_is_fenced_and_question_stays_outside(self):
        code = "import os\nimport sys\n\n# heading must remain a comment\ndef f():\n    return r'\\[x\\]'\n"
        result = prepare_markdown(code + "评价一下这段代码", user=True)
        self.assertEqual(result, "```python\n" + code + "```\n\n评价一下这段代码")
        self.assertEqual(prepare_markdown(result, user=True), result)
        self.assertEqual(prepare_markdown("Please explain import os", user=True), "Please explain import os")
        self.assertEqual(prepare_markdown("# Heading\n\nOrdinary prose", user=True), "# Heading\n\nOrdinary prose")

    def test_quoted_display_math_keeps_each_line_in_its_quote(self):
        for prefix in ("> ", "> > ", ">>", "  >\t> "):
            with self.subTest(prefix=prefix):
                source = prefix + r"\[" + "\n" + prefix + r"\alpha_i\ge0,\qquad \sum_i\alpha_i=1." + "\n" + prefix + r"\]"
                expected = source.replace(r"\[", "$$").replace(r"\]", "$$")
                self.assertEqual(prepare_markdown(source.replace("\n", "\r\n")), expected)
                self.assertEqual(prepare_markdown(expected), expected)
                self.assertEqual(prepare_markdown(prefix + r"\[x+y\]"),
                                 prefix + "$$\n" + prefix + "x+y\n" + prefix + "$$")

    def test_quoted_math_preserves_spacing_and_code_literals(self):
        source = "> \\[\n>     x + y\n>\t\\]\n\n[attachment](./paper.pdf)"
        expected = "> $$\n>     x + y\n>\t$$\n\n[attachment](./paper.pdf)"
        self.assertEqual(prepare_markdown(source), expected)
        for literal in ("> ```latex\n" + source + "\n> ```", "> `\\[x\\]`", "> \\[unclosed"):
            self.assertEqual(prepare_markdown(literal), literal)


class CapturePresentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_deferred_widgets_warn_without_losing_static_text(self):
        source = payload(node("u", "user", "question"), node("a", "assistant", "static answer", "u",
            content_references=[{"type": "map"}, {"type": "client_defined_widget"}]))
        with TemporaryDirectory() as folder, patch("gui.chatgpt_capture.rendered_messages", new=AsyncMock(return_value={})), \
                patch("gui.chatgpt_capture.rich_markdown", return_value="Static answer with \\(x^2\\)"):
            result = await capture_conversation(None, URL, source, images_dir=Path(folder), image_prefix="./images",
                documents_dir=Path(folder), document_prefix="./documents")
        self.assertEqual(result["messages"][-1]["content"], "Static answer with $x^2$")
        self.assertEqual(len(result["warnings"]), 2)
        self.assertTrue(all("第 2 条消息" in w and "未完成" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
