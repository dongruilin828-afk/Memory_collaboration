"""Presentation of verified source text, without changing code or prose content."""
from __future__ import annotations

import ast
import re


def map_prose(text, transform):
    """Leave fenced and inline code literal, including unfinished code fences."""
    blocks = re.compile(r"(?m)^ {0,3}(`{3,}|~{3,})[^\n]*\n")
    inline = re.compile(r"(?<!`)(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)")

    def prose(part):
        pieces, start = [], 0
        for match in inline.finditer(part):
            pieces.extend((transform(part[start:match.start()]), match[0]))
            start = match.end()
        return "".join([*pieces, transform(part[start:])])

    pieces, position = [], 0
    while opening := blocks.search(text, position):
        pieces.append(prose(text[position:opening.start()]))
        marker = opening[1]
        closing = re.compile(r"(?m)^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*(?:\n|$)").search(text, opening.end())
        end = closing.end() if closing else len(text)
        pieces.append(text[opening.start():end])
        position = end
    pieces.append(prose(text[position:]))
    return "".join(pieces)


def strip_receiver_followups(text: str, metadata: dict) -> str:
    """Remove only a synthetic appendix identified by receiver-followup metadata."""
    labels = [r.get("matched_text") for r in metadata.get("content_references") or []
              if r.get("type") == "followup_a" and
              str(r.get("source") or "").startswith("receiver_followups") and r.get("matched_text")]
    if not labels:
        return text

    def remove(part):
        # Require the complete ordered recommendation list at the end. A genuine
        # earlier 'if you want' paragraph or the same words in code stay intact.
        items = r"[ \t]*\n".join(r"[ \t]*[-*+] " + re.escape(label) for label in labels)
        section = re.compile(r"\n\n(?:---+|\*\*\*+|___+)[ \t]*\n\n[^\n]{1,120}[:：][ \t]*\n\n" + items + r"[ \t\r\n]*\Z")
        return section.sub("", part)

    return map_prose(text, remove)


def fence_user_python(text: str) -> str:
    """Protect a confidently identified pasted Python program, not arbitrary prose.

    Parsing is syntax-only; never execute user code. Preserve an adjacent natural
    language request outside the fence, including CJK text valid as a Python name.
    """
    if re.search(r"(?m)^ {0,3}(?:`{3,}|~{3,})", text):
        return text
    if not re.match(r"\s*(?:import |from \w|def |class |#)", text):
        return text
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return text
    substantive = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    if len(substantive) < 2:
        return text
    code_end = len(text)
    if tree.body:
        last = tree.body[-1]
        if (isinstance(last, ast.Expr) and isinstance(last.value, ast.Name)
            and re.search(r"代码|程序|脚本|帮我|请问|解释|评价|分析", last.value.id)
            and len(last.value.id) >= 5):
            code_end = sum(len(line) for line in text.splitlines(keepends=True)[:last.lineno - 1])
    code, suffix = text[:code_end], text[code_end:]
    longest = max((len(m[0]) for m in re.finditer(r"`+", code)), default=0)
    fence = "`" * max(3, longest + 1)
    return fence + "python\n" + code + ("" if code.endswith("\n") else "\n") + fence + ("\n\n" + suffix if suffix else "")


def prepare_markdown(text: str, *, user=False) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if user:
        text = fence_user_python(text)

    def math(part):
        def display(match):
            prefix = part[part.rfind("\n", 0, match.start()) + 1:match.start()]
            if re.fullmatch(r"[ \t]*(?:>[ \t]*)+", prefix):
                # Keep quote prefixes on every line, especially the closing delimiter.
                if "\n" in match[1]:
                    return "$$" + match[1] + "$$"
                return "$$\n" + prefix + match[1].strip() + "\n" + prefix + "$$"
            return "$$\n" + match[1].strip() + "\n$$"

        part = re.sub(r"(?<!\\)\\\[([\s\S]*?)(?<!\\)\\\]",
                      display, part)
        return re.sub(r"(?<!\\)\\\(([^\n]*?)(?<!\\)\\\)",
                      lambda m: "$" + m[1].strip() + "$", part)

    return map_prose(text, math)
