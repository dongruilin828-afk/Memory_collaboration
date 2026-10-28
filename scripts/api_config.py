"""Custom summary endpoint settings; API keys are kept out of runtime configs."""
import re
from urllib.parse import urlsplit, urlunsplit
import math


def middle_ellipsis(text, width, measure):
    if measure(text) <= width:
        return text
    for count in range(len(text) - 1, 0, -1):
        head = (count + 1) // 2
        tail = count // 2
        shortened = text[:head] + "…" + (text[-tail:] if tail else "")
        if measure(shortened) <= width:
            return shortened
    return "…"


def normalize_custom_api(values):
    name = str(values.get("name") or "自定义 API").strip()
    model = str(values.get("model") or "").strip()
    protocol = str(values.get("protocol") or "openai").strip()
    url = str(values.get("url") or "").strip().rstrip("/")
    if any(ord(c) < 32 for c in url):
        raise ValueError("API URL 不能包含换行或控制字符。")
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in {"https", "http"} and parsed.hostname and parsed.port != 0
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("请填写完整的 HTTP 或 HTTPS API URL。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API URL 不应包含账号、密码、查询参数或片段；密钥请填在 KEY 中。")
    if protocol not in {"openai", "gemini"}:
        raise ValueError("请选择 OpenAI 兼容或 Gemini 原生协议。")
    if protocol == "openai" and parsed.path.endswith("/chat/completions"):
        url = urlunsplit(parsed._replace(path=parsed.path[:-17])).rstrip("/")
    if not model or len(model) > 200 or any(ord(c) < 32 for c in model):
        raise ValueError("请填写有效的模型 ID。")
    if not name or len(name) > 60 or any(ord(c) < 32 for c in name):
        raise ValueError("名称须为 1–60 个可见字符。")
    thinking = str(values.get("thinking_level") or "auto").strip()
    reasoning_config = None
    if values.get("reasoning_config") is not None:
        from scripts.reasoning_capabilities import ReasoningCapability, capability_identity
        snapshot = values["reasoning_config"]
        if not isinstance(snapshot, dict):
            raise ValueError("思考设置的能力信息无效，请重新识别。")
        capability = ReasoningCapability.from_dict(snapshot)
        identity = capability_identity(url, protocol, model)
        if snapshot.get("identity") != identity:
            raise ValueError("API 地址、协议或模型已更改，请重新识别思考设置。")
        if ((protocol == "gemini" and capability.kind in {"effort", "deepseek", "toggle"})
                or (protocol == "openai" and capability.kind == "gemini")
                or (capability.parameter and
                    (capability.parameter.startswith("generationConfig.") != (protocol == "gemini")))):
            raise ValueError("思考参数格式不适用于当前接口协议。")
        if thinking != "auto" and thinking not in capability.levels:
            raise ValueError("所选思考强度不在当前模型支持的档位中。")
        if "override" in snapshot and not isinstance(snapshot["override"], bool):
            raise ValueError("思考设置的覆盖标记无效。")
        reasoning_config = {**capability.to_dict(), "identity": identity,
                            "override": snapshot.get("override", False)}
        if "observed_at" in snapshot:
            timestamp = snapshot["observed_at"]
            if type(timestamp) not in {int, float} or not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError("思考设置的识别时间无效，请重新识别。")
            reasoning_config["observed_at"] = timestamp
        if "scope" in snapshot:
            scope = snapshot["scope"]
            if not isinstance(scope, str) or not re.fullmatch(r"[0-9a-f]{64}", scope):
                raise ValueError("思考设置的密钥作用域无效，请重新识别。")
            reasoning_config["scope"] = scope
    else:
        # Saved profiles predating capability discovery retain their wire values.
        levels = {"auto", "none", "minimal", "low", "medium", "high", "xhigh"}
        if thinking not in levels or (protocol == "gemini" and thinking not in {"auto", "low", "medium", "high"}):
            raise ValueError("所选思考强度不适用于当前协议。")
    json_mode = str(values.get("json_mode") or "json_object")
    if json_mode not in {"json_object", "json_schema", "prompt"}:
        raise ValueError("请选择有效的 JSON 输出方式。")
    token_value = values.get("max_output_tokens", 16384)
    unlimited = token_value is None or (
        isinstance(token_value, str) and token_value.strip().lower() in {"无限制", "unlimited", "none", "∞"}
    )
    try:
        if not unlimited and (isinstance(token_value, bool) or not re.fullmatch(r"[0-9]+", str(token_value).strip())):
            raise ValueError
        tokens = None if unlimited else int(token_value)
        timeout = int(values.get("request_timeout_seconds", 180))
    except (ValueError, TypeError):
        raise ValueError("输出上限须为整数或“无限制”；超时须为整数。") from None
    if (tokens is not None and not 128 <= tokens <= 1_000_000) or not 5 <= timeout <= 600:
        raise ValueError("输出上限须为 128–1000000 或“无限制”；超时须为 5–600 秒。")
    if (reasoning_config is not None and protocol == "gemini"
            and reasoning_config["kind"] == "budget" and thinking.isdecimal()
            and tokens is not None and int(thinking) >= tokens):
        raise ValueError("Gemini 思考预算须小于输出上限，为回答保留空间。")
    normalized = dict(name=name, url=url, model=model, protocol=protocol,
                      thinking_level=thinking, json_mode=json_mode,
                      max_output_tokens=tokens, request_timeout_seconds=timeout)
    if reasoning_config is not None:
        normalized["reasoning_config"] = reasoning_config
    return normalized
