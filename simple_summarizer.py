"""把既有结构化总结压缩成只含一个总览段落的极简版。"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from gemini_summarizer import DEFAULT_PROVIDER, TYPE_LABELS, SummaryGateway


SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"}
    },
    "required": ["overview"]
}


class SimpleSummaryValidationError(RuntimeError):
    """模型生成的极简总览不满足可读性或忠实度约束。"""


def simple_char_limit(message_count: int) -> int:
    if message_count <= 6:
        return 220
    if message_count <= 30:
        return 360
    if message_count <= 100:
        return 460
    return 620


def _compact(value: Any, max_chars: int = 800) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    boundaries = [
        match.end() for match in re.finditer(r"[。！？!?；;]", text)
        if match.end() <= max_chars
    ]
    if boundaries:
        return text[:boundaries[-1]].strip()
    return text


def _claim_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: value.get(key)
        for key in ("content", "source", "status", "message_ids")
        if value.get(key) not in (None, "", [])
    }


def _record_projection(record: dict[str, Any]) -> dict[str, Any]:
    omitted = {
        "message_range", "evidence_quote", "source_chunk",
        "numeric_fidelity", "media_id", "adoption_status"
    }
    return {
        key: value for key, value in record.items()
        if key not in omitted and value not in (None, "", [])
    }


def _selected_source_messages(
    messages: list[dict[str, str]], result: dict[str, Any]
) -> list[dict[str, Any]]:
    message_count = len(messages)
    language_heavy = (
        len(result.get("typed_records", {}).get("learning", [])) > 30
    )
    if message_count <= 30:
        selected_ids = set(range(1, message_count + 1))
    else:
        selected_ids = set()
        if not language_heavy:
            selected_ids.update(range(1, min(5, message_count + 1)))
            selected_ids.update(
                range(max(1, message_count - 11), message_count + 1)
            )
        typed = result.get("typed_records", {})
        for group in ("calculations", "programming", "decisions", "source_text_issues"):
            for record in typed.get(group, []):
                selected_ids.update(
                    value for value in record.get("message_ids", [])
                    if isinstance(value, int)
                )
        state = result.get("current_state", {})
        if not language_heavy:
            for key in ("current_activity", "reached_stage", "next_step"):
                selected_ids.update(
                    value for value in state.get(key, {}).get("message_ids", [])
                    if isinstance(value, int)
                )
            for key in ("completed", "pending"):
                for claim in state.get(key, []):
                    selected_ids.update(
                        value for value in claim.get("message_ids", [])
                        if isinstance(value, int)
                    )
    return [
        {
            "message_id": message_id,
            "role": messages[message_id - 1].get("role"),
            "content": _compact(messages[message_id - 1].get("content"), 1200)
        }
        for message_id in sorted(selected_ids)
        if 1 <= message_id <= message_count
    ]


def build_simple_projection(
    result: dict[str, Any], messages: list[dict[str, str]]
) -> dict[str, Any]:
    """只保留生成单段总览所需的信息，避免把详细版再原样塞给模型。"""
    typed = result.get("typed_records", {})
    learning = [
        record for record in typed.get("learning", [])
        if isinstance(record, dict)
    ]
    language_heavy = len(learning) > 30
    learning_memory_ids = {
        str(item.get("memory_id"))
        for item in result.get("memory_items", [])
        if isinstance(item, dict)
        and item.get("memory_type") == "learning_point"
        and item.get("memory_id")
    }
    corrections = [
        _record_projection(record) for record in learning
        if record.get("record_kind") == "correction"
    ][:20]
    representatives = learning[:4]
    if len(learning) > 8:
        representatives += learning[-4:]
    elif len(learning) > 4:
        representatives += learning[4:]
    representative_records = []
    seen_learning: set[str] = set()
    for record in ([] if len(learning) > 30 else representatives):
        key = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if key not in seen_learning:
            representative_records.append(_record_projection(record))
            seen_learning.add(key)

    priority_types = {
        "user_condition", "decision", "action", "verification",
        "open_question", "correction", "code_state"
    }
    key_memories = [
        _record_projection(item)
        for item in result.get("memory_items", [])
        if isinstance(item, dict) and item.get("memory_type") in priority_types
    ]
    if len(key_memories) > 24:
        key_memories = key_memories[:12] + key_memories[-12:]

    state = result.get("current_state", {})
    programming_task = (
        result.get("conversation", {}).get("programming_mode") == "task"
    )
    meaningful_pending = [
        item for item in state.get("pending", [])
        if isinstance(item, dict)
        and (
            programming_task
            or (
                item.get("source") == "user"
                and item.get("status") == "unresolved"
            )
        )
    ]
    next_step = state.get("next_step")
    if not programming_task and (
        not isinstance(next_step, dict)
        or next_step.get("source") != "user"
        or next_step.get("status") != "unresolved"
    ):
        next_step = {}
    return {
        "source": result.get("source"),
        "message_count": len(messages),
        "existing_overall_summary": result.get("overall_summary", ""),
        "conversation": result.get("conversation", {}),
        "current_state": {
            "current_activity": (
                {} if language_heavy
                else _claim_projection(state.get("current_activity"))
            ),
            "reached_stage": _claim_projection(state.get("reached_stage")),
            "completed": [
                _claim_projection(item) for item in state.get("completed", [])
                if isinstance(item, dict)
            ],
            "pending": [
                _claim_projection(item) for item in meaningful_pending
            ],
            "next_step": _claim_projection(next_step),
            "last_user_intent": (
                None if language_heavy else state.get("last_user_intent")
            ),
            "breakpoint_status": state.get("breakpoint_status")
        },
        "topics": [
            {
                "title": topic.get("title"),
                "summary": topic.get("summary"),
                "source_message_ids": topic.get("source_message_ids", [])
            }
            for topic in result.get("topics", [])
            if isinstance(topic, dict)
            and not (
                language_heavy
                and topic.get("memory_ids")
                and all(
                    str(memory_id) in learning_memory_ids
                    for memory_id in topic.get("memory_ids", [])
                )
            )
        ],
        "key_memories": key_memories,
        "typed_records": {
            "programming": [
                _record_projection(item)
                for item in typed.get("programming", [])
                if isinstance(item, dict)
            ],
            "calculations": [
                _record_projection(item)
                for item in typed.get("calculations", [])
                if isinstance(item, dict)
            ],
            "decisions": [
                _record_projection(item)
                for item in typed.get("decisions", [])
                if isinstance(item, dict)
            ],
            "source_text_issues": [
                _record_projection(item)
                for item in typed.get("source_text_issues", [])
                if isinstance(item, dict)
            ],
            "learning_count": len(learning),
            "learning_kinds": dict(Counter(
                str(item.get("record_kind") or "unknown") for item in learning
            )),
            "corrections": [] if language_heavy else corrections,
            "representative_learning": representative_records
        },
        "media": [
            {
                "kind": item.get("kind"),
                "label": item.get("label"),
                "description": item.get("description"),
                "can_reverify": item.get("can_reverify")
            }
            for item in result.get("media", [])
            if isinstance(item, dict)
        ],
        "selected_source_messages": _selected_source_messages(messages, result)
    }


def build_simple_prompt(projection: dict[str, Any], max_chars: int) -> str:
    return f"""你正在生成一份供下一个 AI 直接接手历史任务的“极简记忆”。

只输出 JSON 对象中的 overview。overview 必须满足：
1. 只写一个连贯的中文总览段落，不要标题、列表、编号、Markdown、来源消息号或质量检查说明。
2. 最多 {max_chars} 个字符，并在完整句子处结束；在不影响续接的前提下越短越好。
3. 合并所有真正有续接价值的信息：用户目标、明确条件或选择、上一 AI 已完成的关键工作或结论，以及确实仍未解决的事项。
4. 普通寒暄、AI 结尾的邀请式追问、开发期媒体说明、重复解释和大量普通词汇逐项列表全部省略。
5. 严格区分用户行为与上一 AI 的回答/建议。没有用户原文证据时，不得声称用户已经采纳、执行、确认、掌握或完成。
6. 编程对话必须区分“AI 提供方案”“用户尝试运行”“最终修复已验证”；不能把建议写成已实施。
7. 已回答的问题不要制造成待办。只有会影响继续任务的真实未解决事项才写进总览。
8. 数字、专名、计算结果和图片/文档结论必须来自输入；不可访问的媒体只能写成历史 AI 判断，不能升级为本轮已验证事实。
9. 超长学习对话只概括整体学习范围和其他非学习类独立主题；不要写任何单个普通词汇、短语、谚语、术语或随机举例。
10. 不要把普通翻译或纠错写成“用户尚未确认采纳”；不要用“等待用户继续提问”“可承接/接收新指令”之类的客套话收尾。
11. 保留“可能、大概率、约”等不确定性，不得擅自强化为“稳定、必然、确定”。
12. 用户限定条件下已有明确数值预测或估算时，至少保留最终核心范围或阈值。

以下是已经过普通版归一化的结构化记忆及必要原文证据：
{json.dumps(projection, ensure_ascii=False)}
"""


def normalize_simple_overview(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^#{1,6}\s*(?:极简)?总览\s*", "", text)
    text = re.sub(r"^[-*+]\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(
        r"(?:，|。)?(?:目前)?(?:正在)?等待用户(?:反馈|继续提问|后续提问)"
        r"[^。]*[。]?$",
        "",
        text
    ).strip()
    text = re.sub(
        r"(?:，|。)?后续可直接承接用户的?新(?:指令|问题|任务)[。]?$",
        "",
        text
    ).strip()
    text = re.sub(
        r"[，,]?(?:处于)?就绪状态(?:，?可随时(?:接收|承接)[^。]*)?[。]?$",
        "",
        text
    ).strip()
    text = re.sub(
        r"[，,]?(?:处于)?就绪等待(?:用户)?(?:新)?(?:要求|指令|问题|任务)的?状态[。]?$",
        "",
        text
    ).strip()
    text = re.sub(
        r"[，,]?(?:后续)?可直接继续[^。]*(?:学习|提问|讨论|任务)[。]?$",
        "",
        text
    ).strip()
    if text and text[-1] not in "。！？!?":
        text += "。"
    return text


def validate_simple_overview(
    overview: str, projection: dict[str, Any], max_chars: int
) -> list[str]:
    errors: list[str] = []
    if not overview:
        return ["总览为空"]
    if len(overview) > max_chars:
        errors.append(f"超过 {max_chars} 字符限制")
    if re.search(r"(?:^|\n)\s*(?:#{1,6}|[-*+]\s|\d+[.)、])", overview):
        errors.append("包含标题或列表")
    if "\n" in overview:
        errors.append("不是单一段落")
    source_text = json.dumps(projection, ensure_ascii=False)
    unsupported_numbers = sorted({
        number for number in re.findall(
            r"(?<![A-Za-z])\d+(?:[.~-]\d+)?%?", overview
        )
        if number not in source_text
    })
    if unsupported_numbers:
        errors.append("出现输入中不存在的数字：" + "、".join(unsupported_numbers))
    if overview.count("`") % 2:
        errors.append("反引号未闭合")
    if overview.count("“") != overview.count("”"):
        errors.append("中文双引号未闭合")
    pending = projection.get("current_state", {}).get("pending", [])
    if not pending and re.search(r"(?:尚待|等待)用户", overview):
        errors.append("把已回答对话制造成待用户处理")
    if re.search(r"(?:可随时|后续可).{0,8}(?:接收|承接).{0,8}(?:指令|问题|任务)", overview):
        errors.append("包含无续接价值的客套收尾")
    if re.search(r"就绪等待.{0,8}(?:要求|指令|问题|任务)", overview):
        errors.append("包含无续接价值的等待收尾")
    if re.search(r"(?:后续)?可直接继续[^。]*(?:学习|提问|讨论|任务)", overview):
        errors.append("包含无续接价值的继续收尾")
    completion = re.search(
        r"用户(?:已经|已)完成.{0,60}(润色|撰写|修改|诊断|代码|方案)",
        overview
    )
    if completion:
        deliverable = completion.group(1)
        user_completion_evidence = any(
            isinstance(item, dict)
            and item.get("source") == "user"
            and item.get("status") in {"confirmed", "executed", "verified"}
            and deliverable in str(item.get("content") or "")
            and re.search(
                r"(?:完成|已经|已(?:经)?(?:润色|撰写|修改|执行|采用|验证))",
                str(item.get("content") or "")
            )
            for item in projection.get("current_state", {}).get("completed", [])
        )
        if not user_completion_evidence:
            errors.append("把上一 AI 的交付物误写成用户已完成")
    if re.search(
        r"用户.{0,8}(?:尚未|未)确认.{0,8}(?:采纳|采用)", overview
    ):
        errors.append("把普通回答或纠错制造成采纳待办")
    for strengthened in ("稳定", "必然", "肯定", "确定会"):
        if strengthened in overview and strengthened not in source_text:
            errors.append(f"擅自强化不确定结论：{strengthened}")
    if projection.get("typed_records", {}).get("learning_count", 0) > 30:
        if re.search(
            r"(?:探讨|查询|讲解|解释).{0,60}(?:谚语|术语|单词|词汇|短语)",
            overview
        ) or re.search(r"(?:部分|若干).{0,6}(?:词汇|短语|纠错)", overview):
            errors.append("超长学习对话保留了单个或笼统的学习条目")
        if re.search(
            r"(?:查询|讲解|学习|解释).{0,20}[‘'\"“][^’'\"”]{1,24}[’'\"”]"
            r".{0,12}(?:释义|含义|用法)",
            overview
        ):
            errors.append("超长学习对话保留了低价值的单个词汇查询")
        for match in re.finditer(r"(?:涉及|包括)([^。]+)", overview):
            enumeration = match.group(1)
            if len(re.findall(r"[、,，]", enumeration)) >= 3:
                errors.append("超长学习对话枚举了普通词汇")
                break
    estimate_numbers: set[str] = set()
    for topic in projection.get("topics", []):
        summary = str(topic.get("summary") or "")
        if re.search(r"(?:预测|估算|推算)", summary):
            estimate_numbers.update(re.findall(r"\d+(?:\.\d+)?", summary))
    if estimate_numbers and not any(
        number in overview for number in estimate_numbers
    ):
        errors.append("遗漏了数值预测或估算主题的核心数值")
    return errors


def repair_simple_overview(
    overview: str, projection: dict[str, Any]
) -> str:
    """依据结构化状态修复已有极简文本，不凭空补写新事实。"""
    text = normalize_simple_overview(overview)
    if not projection.get("current_state", {}).get("pending"):
        text = re.sub(
            r"(?:目前)?[^。]*(?:尚待|等待)用户[^。]*[。]?$",
            "",
            text
        ).strip()
    text = re.sub(
        r"[（(]用户(?:尚未|未)确认是否?(?:采纳|采用)[）)]",
        "",
        text
    )
    text = re.sub(
        r"，?用户(?:尚未|未)确认是否?(?:采纳|采用)[^。]*",
        "",
        text
    )
    source_text = json.dumps(projection, ensure_ascii=False)
    if "稳定" not in source_text:
        text = re.sub(r"(?:数月|几个月)稳定在", "几个月后约为", text)
        text = text.replace("稳定在", "约为")
    return normalize_simple_overview(text)


def generate_simple_overview(
    result: dict[str, Any],
    messages: list[dict[str, str]],
    gateway: SummaryGateway
) -> str:
    projection = build_simple_projection(result, messages)
    max_chars = simple_char_limit(len(messages))
    prompt = build_simple_prompt(projection, max_chars)
    last_errors: list[str] = []
    for attempt in range(2):
        if attempt:
            prompt += (
                "\n\n上一次输出未通过程序检查：" + "；".join(last_errors)
                + "。请重新生成，不要解释。"
            )
        response = gateway.generate_json(prompt, SIMPLE_SCHEMA)
        overview = normalize_simple_overview(response.get("overview"))
        last_errors = validate_simple_overview(
            overview, projection, max_chars
        )
        if not last_errors:
            return overview
    raise SimpleSummaryValidationError("；".join(last_errors))


def build_simple_metadata(
    result: dict[str, Any],
    provider: str | None = None,
    model: str | None = None
) -> dict[str, str]:
    conversation = result.get("conversation", {})
    type_names = [
        TYPE_LABELS.get(value, str(value))
        for value in conversation.get("conversation_types", [])
    ]
    return {
        "provider": str(provider or result.get("provider") or DEFAULT_PROVIDER),
        "model": str(model or result.get("model") or "未记录"),
        "source": str(result.get("source") or "未记录"),
        "message_count": str(conversation.get("message_count", "未记录")),
        "chunk_count": str(conversation.get("chunk_count", "未记录")),
        "conversation_types": "、".join(type_names) or "未识别"
    }


def parse_simple_markdown(value: str) -> tuple[str, dict[str, str]]:
    match = re.search(r"(?m)^# 总览\s*$", value)
    if match:
        prefix = value[:match.start()]
        overview = value[match.end():].strip()
    else:
        prefix = ""
        overview = value.strip()
    labels = {
        "后端": "provider",
        "模型": "model"
    }
    metadata: dict[str, str] = {}
    for label, key in labels.items():
        item = re.search(
            rf"(?m)^-\s*{re.escape(label)}：\s*(.+?)\s*$", prefix
        )
        if item:
            metadata[key] = item.group(1).strip()
    return overview, metadata


def render_simple_markdown(
    overview: str, metadata: dict[str, str]
) -> str:
    lines = [
        f"- 后端：{metadata['provider']}",
        f"- 模型：{metadata['model']}",
        f"- 来源：{metadata['source']}",
        f"- 消息数：{metadata['message_count']}",
        f"- 分块数：{metadata['chunk_count']}",
        f"- 对话类型：{metadata['conversation_types']}",
        "",
        "# 总览",
        "",
        normalize_simple_overview(overview),
        ""
    ]
    return "\n".join(lines)


def write_simple_markdown(
    path: Path, overview: str, metadata: dict[str, str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(
        render_simple_markdown(overview, metadata), encoding="utf-8"
    )
    temp_path.replace(path)
