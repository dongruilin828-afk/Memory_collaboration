"""Custom summary endpoint settings; API keys are kept out of runtime configs."""
from urllib.parse import urlsplit, urlunsplit


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
    levels = {"auto", "none", "minimal", "low", "medium", "high", "xhigh"}
    if thinking not in levels or (protocol == "gemini" and thinking not in {"auto", "low", "medium", "high"}):
        raise ValueError("所选思考强度不适用于当前协议。")
    json_mode = str(values.get("json_mode") or "json_object")
    if json_mode not in {"json_object", "json_schema", "prompt"}:
        raise ValueError("请选择有效的 JSON 输出方式。")
    try:
        tokens = int(values.get("max_output_tokens", 16384))
        timeout = int(values.get("request_timeout_seconds", 180))
    except (ValueError, TypeError):
        raise ValueError("输出上限和超时须为整数。") from None
    if not 128 <= tokens <= 1_000_000 or not 5 <= timeout <= 600:
        raise ValueError("输出上限须为 128–1000000；超时须为 5–600 秒。")
    return dict(name=name, url=url, model=model, protocol=protocol,
                thinking_level=thinking, json_mode=json_mode,
                max_output_tokens=tokens, request_timeout_seconds=timeout)
