"""Opt-in, bounded compatibility probes; acceptance never proves reasoning effect.

Only parameter-specific validation errors are treated as capability evidence.
Generated model text and successful invalid-sentinel requests are deliberately
ignored. This module is never called by passive metadata discovery or saving.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import queue
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener

from scripts.reasoning_capabilities import (
    ReasoningCapability, _NoRedirect, _canonical_endpoint, budget_levels,
    capability_identity,
)


MAX_PROBE_REQUESTS = 8
MAX_PROBE_SECONDS = 40
PROBE_REQUEST_TIMEOUT = 5
PROBE_OUTPUT_TOKENS = 128
_MAX_RESPONSE_BYTES = 65_536
_SENTINEL = "__capability_probe_invalid__"
_ENUM_MARKER = re.compile(
    r"\b(?:(?:supported|allowed|valid|permitted)\s+(?:values?|options?)\s*(?:are|is|include)?\s*[:=]?"
    r"|(?:must|should)\s+be\s+(?:one\s+of\s*)?|(?:expected|enum)\s*[:=])",
    re.I,
)
_VALUE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")


@dataclass(frozen=True)
class ProbeResult:
    capability: ReasoningCapability
    message: str
    request_count: int = 0
    status: str = "unknown"


@dataclass(frozen=True)
class _Response:
    status: int
    data: object


class _ProbeStopped(Exception):
    def __init__(self, status):
        self.status = status


def _field_key(value):
    """Normalize camel/snake case and Pydantic location arrays, not leaf guesses."""
    if isinstance(value, (list, tuple)):
        value = ".".join(str(part) for part in value if str(part) not in {"body", "request"})
    return re.sub(r"[^a-z0-9.]", "", str(value).lower())


def _matches_field(value, parameter):
    key, wanted = _field_key(value), _field_key(parameter)
    if key == wanted:
        return True
    # Native Gemini sometimes omits generationConfig in field violations.
    return parameter.startswith("generationConfig.") and key == _field_key(parameter.split(".", 1)[1])


def _mentions_field(message, parameter):
    aliases = [parameter, re.sub(r"(?<!^)(?=[A-Z])", "_", parameter).lower()]
    if parameter.startswith("generationConfig."):
        aliases.extend(alias.split(".", 1)[1] for alias in tuple(aliases))
    return any(re.search(r"(?<![A-Za-z0-9_])" + re.escape(alias) + r"(?![A-Za-z0-9_])",
                         message, re.I) for alias in aliases)


def _error_nodes(data, parameter):
    """Yield only errors explicitly tied to this exact request parameter."""
    if not isinstance(data, (dict, list)):
        return
    pending = [(data, False)]
    visited = 0
    while pending and visited < 256:
        value, inherited = pending.pop(0)
        visited += 1
        if isinstance(value, list):
            pending.extend((item, inherited) for item in value[:64] if isinstance(item, (dict, list)))
            continue
        if not isinstance(value, dict):
            continue
        fields = [value.get(key) for key in ("param", "parameter", "field", "loc", "path") if key in value]
        # An error for another parameter must not inherit a parent's scope.
        scoped = any(_matches_field(field, parameter) for field in fields) if fields else inherited
        message = value.get("message", value.get("msg", value.get("description", "")))
        if isinstance(message, str) and not fields:
            # Exact full path/key only; a generic 'type' is not thinking.type.
            scoped = scoped or _mentions_field(message, parameter)
        if scoped:
            yield value
        pending.extend((item, scoped) for key, item in value.items()
                       if key not in {"input", "request", "payload", "choices", "candidates"}
                       and isinstance(item, (dict, list)))


def _tokens(value, api_key=""):
    if isinstance(value, str):
        value = re.findall(r"['\"]([A-Za-z][A-Za-z0-9_-]{0,63})['\"]", value)
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 32:
        return ()
    result = []
    for item in value:
        if (not isinstance(item, str) or not _VALUE.fullmatch(item) or item == "auto"
                or item == _SENTINEL or api_key and api_key in item):
            return ()
        if item not in result:
            result.append(item)
    return tuple(result)


def _enum_values(node, api_key):
    for key in ("enum", "allowed_values", "supported_values", "permitted_values", "expected"):
        values = _tokens(node.get(key), api_key)
        if values:
            return values
    context = node.get("ctx")
    if isinstance(context, dict):
        for key in ("expected", "enum", "allowed_values", "permitted"):
            values = _tokens(context.get(key), api_key)
            if values:
                return values
    for key in ("message", "msg", "description"):
        message = node.get(key)
        if not isinstance(message, str):
            continue
        match = _ENUM_MARKER.search(message)
        if not match:
            continue
        tail = message[match.end():].strip()
        if tail.startswith("[") and "]" in tail:
            tail = tail[:tail.index("]") + 1]
        else:
            tail = re.split(r"[.;\n]", tail, maxsplit=1)[0]
        values = _tokens(tail, api_key)
        if values:
            return values
        # Also accept plain low, medium, high; never extract arbitrary prose.
        plain = re.sub(r"\s+(?:or|and)\s+", ",", tail, flags=re.I)
        plain = plain.strip("[] ():")
        pieces = tuple(part.strip() for part in plain.split(","))
        if len(pieces) > 1:
            values = _tokens(pieces, api_key)
            if values:
                return values
    return ()


def _budget_range(nodes):
    minimum, maximum = None, None
    for node in nodes:
        scopes = [node]
        if isinstance(node.get("ctx"), dict):
            scopes.append(node["ctx"])
        for scope in scopes:
            for key in ("minimum", "min", "ge", "gte", "min_value"):
                value = scope.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    minimum = value if minimum is None else max(minimum, value)
            for key in ("maximum", "max", "le", "lte", "max_value"):
                value = scope.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    maximum = value if maximum is None else min(maximum, value)
        message = " ".join(str(node.get(key, "")) for key in ("message", "msg", "description"))
        match = re.search(r"(?:between|range\s*[:=]?)\s*(\d+)\s*(?:and|to|[-,])\s*(\d+)", message, re.I)
        if match:
            minimum, maximum = int(match[1]), int(match[2])
    if (minimum is not None and maximum is not None and 0 <= minimum <= maximum <= 1_000_000
            and maximum > 0):
        return minimum, maximum
    return None


def _evidence(data, parameter, kind, api_key):
    nodes = list(_error_nodes(data, parameter))
    if not nodes:
        return None
    if kind == "budget":
        bounds = _budget_range(nodes)
        if bounds is None:
            return None
        return ReasoningCapability("budget", budget_levels(*bounds), "probe_error", note=
                                   "错误响应声明的预算范围；刻度由应用划分，未确认实际生效",
                                   parameter=parameter, budget_min=bounds[0], budget_max=bounds[1])
    for node in nodes:
        values = _enum_values(node, api_key)
        if not values:
            continue
        try:
            if kind == "toggle":
                if set(values) <= {"enabled", "disabled"}:
                    values = tuple("none" if value == "disabled" else "enabled" for value in values)
                elif set(value.lower() for value in values) <= {"true", "false"}:
                    values = tuple("enabled" if value.lower() == "true" else "none" for value in values)
                else:
                    continue
            return ReasoningCapability(kind, values, "probe_error", note=
                                       "错误响应声明的档位；参数接受情况不代表实际生效", parameter=parameter)
        except (TypeError, ValueError):
            continue
    if parameter == "enable_thinking":
        # A typed boolean validator proves a recognized field, but not its effects.
        for node in nodes:
            kind_text = str(node.get("type", ""))
            message = " ".join(str(node.get(key, "")) for key in ("message", "msg", "description"))
            if re.search(r"bool(?:ean)?", kind_text + " " + message, re.I):
                return ReasoningCapability("toggle", ("none", "enabled"), "probe_accepted", note=
                                           "仅列出经请求接受的开关值；未确认实际生效", parameter=parameter)
    return None


def _set_path(payload, parameter, value):
    parts = parameter.split(".")
    target = payload
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def _wire_value(kind, parameter, level):
    if kind == "budget":
        return 0 if level == "none" else int(level)
    if kind == "toggle":
        return ("disabled" if level == "none" else "enabled") if parameter == "thinking.type" else level == "enabled"
    return level


def _request_payload(protocol, model, parameter, value, *, coupled=False, token_field="max_tokens"):
    if protocol == "gemini":
        payload = {"contents": [{"role": "user", "parts": [{"text": "Reply with OK."}]}],
                   "generationConfig": {"maxOutputTokens": PROBE_OUTPUT_TOKENS}}
    else:
        payload = {"model": model, "messages": [{"role": "user", "content": "Reply with OK."}],
                   token_field: PROBE_OUTPUT_TOKENS, "stream": False}
    if parameter == "thinking.budget_tokens" and value == 0 or coupled and value == "none":
        payload["thinking"] = {"type": "disabled"}
        return payload
    if parameter == "thinking.budget_tokens" or coupled:
        payload["thinking"] = {"type": "enabled"}
    if parameter == "generationConfig.thinkingConfig.thinkingLevel" and value == "none":
        parameter, value = "generationConfig.thinkingConfig.thinkingBudget", 0
    _set_path(payload, parameter, value)
    return payload


def _target(url, protocol, model):
    base = _canonical_endpoint(url, protocol)
    if protocol == "gemini":
        if not urlsplit(base).path:
            base += "/v1beta"
        return base + "/models/" + quote(model.removeprefix("models/"), safe="") + ":generateContent"
    return base + "/chat/completions"


def _read_response(stream, deadline, cancel_event):
    """Limit bytes and elapsed time even when a server trickles its response."""
    parts, size = [], 0
    reader = getattr(stream, "read1", None) or stream.read
    while size <= _MAX_RESPONSE_BYTES:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or cancel_event is not None and cancel_event.is_set():
            raise TimeoutError("probe response deadline")
        # urllib's socket timeout normally resets per read. Lower it to the
        # remaining absolute budget before each bounded socket operation.
        try:
            stream.fp.raw._sock.settimeout(min(PROBE_REQUEST_TIMEOUT, remaining))
        except (AttributeError, OSError):
            pass
        chunk = reader(min(8192, _MAX_RESPONSE_BYTES + 1 - size))
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise ValueError("Invalid response bytes")
        parts.append(chunk)
        size += len(chunk)
    return b"".join(parts)


def _perform_request(opener, target, protocol, api_key, payload, timeout, cancel_event=None):
    deadline = time.monotonic() + timeout
    request = Request(target, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    if api_key:
        request.add_unredirected_header("X-Goog-Api-Key" if protocol == "gemini" else "Authorization",
                                       api_key if protocol == "gemini" else "Bearer " + api_key)
    try:
        with opener.open(request, timeout=timeout) as response:
            # Generated response text is irrelevant; cap it before decoding.
            raw = _read_response(response, deadline, cancel_event)
            if len(raw) > _MAX_RESPONSE_BYTES:
                return _Response(0, None)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError):
                return _Response(0, None)
            # An HTTP 200 error wrapper is not evidence of accepted generation.
            if not isinstance(data, dict) or "error" in data:
                return _Response(0, None)
            items = data.get("candidates" if protocol == "gemini" else "choices")
            if not isinstance(items, list) or not items or not isinstance(items[0], dict):
                return _Response(0, None)
            return _Response(200, None)
    except HTTPError as error:
        try:
            raw = _read_response(error, deadline, cancel_event)
            data = json.loads(raw.decode("utf-8")) if len(raw) <= _MAX_RESPONSE_BYTES else None
        except (ValueError, OSError, UnicodeError, AttributeError):
            data = None
        finally:
            error.close()
        return _Response(error.code, data)
    except (OSError, ValueError, TypeError):
        return _Response(0, None)


class _Session:
    def __init__(self, target, protocol, model, api_key, cancel_event):
        self.target, self.protocol, self.model, self.api_key = target, protocol, model, api_key
        self.cancel_event = cancel_event
        self.deadline = time.monotonic() + MAX_PROBE_SECONDS
        self.request_count = 0
        self.opener = build_opener(_NoRedirect())
        self.token_field = "max_tokens"

    def check(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise _ProbeStopped("cancelled")
        if self.request_count >= MAX_PROBE_REQUESTS or time.monotonic() >= self.deadline:
            raise _ProbeStopped("limit")

    def request(self, parameter, value, *, coupled=False):
        self.check()
        payload = _request_payload(self.protocol, self.model, parameter, value,
                                   coupled=coupled, token_field=self.token_field)
        remaining = self.deadline - time.monotonic()
        timeout = min(PROBE_REQUEST_TIMEOUT, remaining)
        outbox = queue.Queue(maxsize=1)
        self.request_count += 1

        def run():
            try:
                result = _perform_request(self.opener, self.target, self.protocol, self.api_key, payload,
                                          timeout, self.cancel_event)
            except Exception:
                result = _Response(0, None)
            outbox.put(result)

        # The caller's deadline and cancellation also bound slow trickle responses.
        threading.Thread(target=run, daemon=True).start()
        request_deadline = min(self.deadline, time.monotonic() + PROBE_REQUEST_TIMEOUT)
        while True:
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise _ProbeStopped("cancelled")
            remaining = request_deadline - time.monotonic()
            if remaining <= 0:
                raise _ProbeStopped("unavailable")
            try:
                result = outbox.get(timeout=min(0.1, remaining))
                break
            except queue.Empty:
                continue
        if result.status in {401, 403}:
            raise _ProbeStopped("auth_error")
        if result.status == 429:
            raise _ProbeStopped("rate_limited")
        if result.status == 0 or result.status >= 500 or 300 <= result.status < 400:
            raise _ProbeStopped("unavailable")
        # Some OpenAI-compatible services have retired max_tokens. Retry once,
        # only on an exact token-field error, within the shared request budget.
        if self.token_field == "max_tokens" and result.status in {400, 422} and self.protocol == "openai":
            nodes = list(_error_nodes(result.data, "max_tokens"))
            if any("max_completion_tokens" in str(node.get("message", node.get("msg", ""))) for node in nodes):
                self.token_field = "max_completion_tokens"
                return self.request(parameter, value, coupled=coupled)
        return result


def probe_reasoning_capability(url, protocol, model, api_key="", *, cache=None, cancel_event=None):
    """Probe only when explicitly requested; at most eight small generation calls.

    Error declarations describe the current API, model and credential scope.
    Successful generation only establishes parameter acceptance, never effect.
    """
    protocol, model, api_key = str(protocol).strip().lower(), str(model).strip(), str(api_key).strip()
    try:
        identity = capability_identity(url, protocol, model, api_key)
        target = _target(url, protocol, model)
    except (TypeError, ValueError):
        return ProbeResult(ReasoningCapability(), "请填写有效的 API 地址、协议和模型 ID。", status="invalid")
    session = _Session(target, protocol, model, api_key, cancel_event)
    candidates = (("generationConfig.thinkingConfig.thinkingLevel", "gemini"),
                  ("generationConfig.thinkingConfig.thinkingBudget", "budget")) if protocol == "gemini" else (
                      ("reasoning_effort", "effort"), ("reasoning.effort", "effort"),
                      ("thinking.type", "toggle"), ("thinking_budget", "budget"),
                      ("thinking.budget_tokens", "budget"), ("enable_thinking", "toggle"))
    ambiguous = False
    try:
        for parameter, kind in candidates:
            response = session.request(parameter, -2_147_483_648 if kind == "budget" else _SENTINEL)
            coupled = False
            if response.status == 200:
                ambiguous = True
                continue
            if response.status not in {400, 422}:
                continue
            # DeepSeek-style effort may be validated only with thinking enabled.
            if parameter == "reasoning_effort":
                nodes = list(_error_nodes(response.data, parameter))
                if any(re.search(r"thinking.{0,50}(?:enabled|enable)",
                                 str(node.get("message", node.get("msg", ""))), re.I) for node in nodes):
                    coupled = True
                    response = session.request(parameter, _SENTINEL, coupled=True)
            capability = _evidence(response.data, parameter, kind, api_key)
            if capability is None:
                continue
            if coupled:
                capability = ReasoningCapability("deepseek", capability.levels, capability.source,
                                                  note=capability.note, parameter=parameter)
            accepted, rejected = [], []
            exhausted = False
            for level in capability.levels:
                if kind == "budget" and level.isdecimal() and int(level) >= PROBE_OUTPUT_TOKENS:
                    # Do not buy a large thinking budget just to test an enum.
                    # Native Gemini/Anthropic also share the small output cap.
                    exhausted = True
                    continue
                try:
                    reply = session.request(parameter, _wire_value(kind, parameter, level), coupled=coupled)
                except _ProbeStopped as stop:
                    if stop.status in {"limit", "unavailable"}:
                        exhausted = True
                        break
                    raise
                if reply.status == 200:
                    accepted.append(level)
                elif reply.status in {400, 422}:
                    # An unrelated validation failure cannot disprove this level.
                    if list(_error_nodes(reply.data, parameter)):
                        rejected.append(level)
                    else:
                        exhausted = True
                        break
            levels = tuple(level for level in capability.levels if level not in rejected)
            # Boolean type evidence needs accepted values; no enum was declared.
            if capability.source == "probe_accepted":
                levels = tuple(accepted)
            if not levels:
                continue
            if capability.kind == "budget" and rejected:
                # Rejected budget ticks invalidate the advertised range: retain
                # only individually accepted values with no range claim.
                levels = tuple(accepted)
                if not levels:
                    continue
                capability = ReasoningCapability("budget", levels, "probe_accepted", note=
                                                  "仅列出经请求接受的预算值；未确认实际生效", parameter=parameter)
            else:
                capability = ReasoningCapability(
                    capability.kind, levels, capability.source, note=capability.note,
                    parameter=capability.parameter, budget_min=capability.budget_min,
                    budget_max=capability.budget_max)
            if cancel_event is not None and cancel_event.is_set():
                raise _ProbeStopped("cancelled")
            if cache is not None:
                cache.put(identity, capability)
            qualifier = "部分档位未逐一测试；" if exhausted else ""
            return ProbeResult(capability, qualifier + "已识别参数与档位；请求被接受仍不能证明思考参数实际生效。",
                               session.request_count, "found")
    except _ProbeStopped as stop:
        messages = {
            "cancelled": "检测已取消，未应用结果。", "auth_error": "接口拒绝访问，请检查 API KEY 和模型权限。",
            "rate_limited": "接口触发限流或额度限制，已停止检测。",
            "unavailable": "检测遇到网络、服务或重定向问题，已停止；可稍后重试。",
            "limit": "已达到检测请求或时间上限，仍未取得可靠的档位信息。",
        }
        return ProbeResult(ReasoningCapability(), messages[stop.status], session.request_count, stop.status)
    message = ("接口接受了无效测试值，可能忽略参数；无法确认有效档位，请使用自动或手动配置。" if ambiguous else
               "接口未返回可靠的档位或预算规范，请使用自动或按服务商文档手动配置。")
    return ProbeResult(ReasoningCapability(), message, session.request_count)
