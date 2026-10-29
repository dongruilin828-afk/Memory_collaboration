"""Discover explicit reasoning controls without issuing generation requests.

Model-list responses usually omit effort enums. Missing metadata stays unknown;
the catalog is used only for documented models on their official API origins.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


_KINDS = {"unknown", "effort", "deepseek", "gemini", "budget", "toggle", "none"}
_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "enabled")
_PARAMETERS = {
    "effort": {"reasoning_effort", "reasoning.effort"},
    "deepseek": {"reasoning_effort"},
    "gemini": {"generationConfig.thinkingConfig.thinkingLevel"},
    "budget": {"thinking_budget", "thinking.budget_tokens", "generationConfig.thinkingConfig.thinkingBudget"},
    "toggle": {"thinking.type", "enable_thinking"},
}
_MAX_METADATA_BYTES = 1_048_576
_CATALOG_VERSION = 3


def _valid_levels(kind, values):
    if not isinstance(values, (tuple, list)) or len(values) > 32:
        raise ValueError("Invalid reasoning levels")
    result = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Reasoning levels must be strings")
        if kind == "budget":
            valid = value == "none" or bool(re.fullmatch(r"[1-9][0-9]{0,6}", value)) and int(value) <= 1_000_000
        elif kind == "toggle":
            valid = value in {"none", "enabled"}
        else:
            # New models can publish new native enum values; never interpret them
            # as executable paths, JSON, or automatic-mode sentinels.
            valid = bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value)) and value != "auto"
        if not valid:
            raise ValueError("Unsupported reasoning level")
        if value not in result:
            result.append(value)
    if kind in {"unknown", "none"}:
        if result:
            raise ValueError("This capability cannot contain manual levels")
    elif not result:
        raise ValueError("Manual reasoning controls need at least one level")
    if kind == "budget":
        result.sort(key=lambda item: -1 if item == "none" else int(item))
    elif all(value in _EFFORTS for value in result):
        result.sort(key=_EFFORTS.index)
    return tuple(result)


@dataclass(frozen=True)
class ReasoningCapability:
    kind: str = "unknown"
    levels: tuple[str, ...] = ()
    source: str = "unknown"
    default_level: str | None = None
    note: str = ""
    parameter: str = ""
    budget_min: int | None = None
    budget_max: int | None = None
    evidence_source: str = ""

    def __post_init__(self):
        if not isinstance(self.kind, str) or self.kind not in _KINDS:
            raise ValueError("Invalid reasoning capability kind")
        object.__setattr__(self, "levels", _valid_levels(self.kind, self.levels))
        if not isinstance(self.source, str) or len(self.source) > 32 or any(ord(c) < 32 for c in self.source):
            raise ValueError("Invalid capability source")
        if self.default_level is not None and self.default_level not in self.levels:
            raise ValueError("Default reasoning level is not supported")
        if not isinstance(self.note, str) or len(self.note) > 200 or any(ord(c) < 32 for c in self.note):
            raise ValueError("Invalid capability note")
        if not isinstance(self.parameter, str) or self.parameter and self.parameter not in _PARAMETERS.get(self.kind, set()):
            raise ValueError("Unsupported reasoning parameter")
        if not isinstance(self.evidence_source, str) or len(self.evidence_source) > 32 or any(ord(c) < 32 for c in self.evidence_source):
            raise ValueError("Invalid capability evidence source")
        bounds = (self.budget_min, self.budget_max)
        if any(value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                     or not 0 <= value <= 1_000_000) for value in bounds):
            raise ValueError("Invalid reasoning budget range")
        if any(value is not None for value in bounds):
            if self.kind != "budget" or None in bounds or self.budget_min > self.budget_max:
                raise ValueError("Invalid reasoning budget range")
            for level in self.levels:
                value = 0 if level == "none" else int(level)
                if not self.budget_min <= value <= self.budget_max:
                    raise ValueError("Reasoning budget is outside the declared range")

    @property
    def known(self):
        return self.kind != "unknown"

    def to_dict(self):
        return dict(kind=self.kind, levels=list(self.levels), source=self.source,
                    default_level=self.default_level, note=self.note, parameter=self.parameter,
                    budget_min=self.budget_min, budget_max=self.budget_max,
                    evidence_source=self.evidence_source)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("Invalid reasoning capability")
        return cls(kind=data.get("kind", "unknown"), levels=data.get("levels", ()),
                   source=data.get("source", "unknown"), default_level=data.get("default_level"),
                   note=data.get("note", ""), parameter=data.get("parameter", ""),
                   budget_min=data.get("budget_min"), budget_max=data.get("budget_max"),
                   evidence_source=data.get("evidence_source", ""))


def _canonical_endpoint(url, protocol):
    if not isinstance(url, str) or any(ord(c) < 32 for c in url):
        raise ValueError("Invalid API endpoint")
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Invalid API endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API endpoint cannot contain credentials or query parameters")
    scheme, host = parsed.scheme.lower(), parsed.hostname.lower()
    port = parsed.port
    if port == 0:
        raise ValueError("Invalid API port")
    if ":" in host:
        host = f"[{host}]"
    if port and port != (443 if scheme == "https" else 80):
        host += f":{port}"
    path = parsed.path.rstrip("/")
    if protocol == "openai" and path.endswith("/chat/completions"):
        path = path[:-17].rstrip("/")
    return urlunsplit((scheme, host, path, "", ""))


def capability_identity(url, protocol, model, api_key=""):
    protocol = str(protocol).strip().lower()
    if protocol not in {"openai", "gemini"}:
        raise ValueError("Invalid API protocol")
    model = str(model).strip()
    if not model or len(model) > 200 or any(ord(c) < 32 for c in model):
        raise ValueError("Invalid model ID")
    endpoint = _canonical_endpoint(url, protocol)
    scope = hashlib.sha256(str(api_key).encode("utf-8")).hexdigest()
    value = json.dumps([endpoint, protocol, model, scope], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def catalog_capability(url, protocol, model):
    try:
        endpoint = _canonical_endpoint(url, protocol)
    except (ValueError, TypeError):
        return ReasoningCapability()
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or parsed.port not in {None, 443}:
        return ReasoningCapability()
    host, path = parsed.hostname, parsed.path
    model = str(model).removeprefix("models/") if protocol == "gemini" else str(model)
    if protocol == "openai" and host == "api.openai.com" and path in {"", "/v1"}:
        native = ("low", "medium", "high", "xhigh", "max")
        always_on = {"gpt-6-astra", "gpt-6.1-sol"}
        optional = {"gpt-6-sol", "gpt-6-luna", "gpt-6.1-terra"}
        base = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model)
        if base in always_on | optional:
            levels = native if base in always_on else ("none", *native)
            return ReasoningCapability("effort", levels, "catalog", "medium", "官方模型配置")
    if protocol == "gemini" and host == "generativelanguage.googleapis.com" and path in {"", "/v1", "/v1beta"}:
        models = {
            "gemini-4-argon": (("low", "medium", "high"), "medium"),
            "gemini-3.8-flash": (("low", "medium", "high"), "medium"),
            "gemini-3.6-flash": (("minimal", "low", "medium", "high"), "medium"),
            "gemini-3.5-flash-lite": (("minimal", "low", "medium", "high"), "minimal"),
            "gemini-3.1-pro-preview": (("low", "medium", "high"), "high"),
            "gemini-3-flash-preview": (("minimal", "low", "medium", "high"), "high"),
            "gemini-3-pro-preview": (("low", "high"), "high"),
        }
        if model in models:
            levels, default = models[model]
            return ReasoningCapability("gemini", levels, "catalog", default, "官方模型配置")
    if protocol == "openai" and host == "api.deepseek.com" and path in {"", "/v1"}:
        if model in {"deepseek-flash", "deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4.1-flash-1017"}:
            return ReasoningCapability("deepseek", ("none", "low", "high", "max"), "catalog", "high", "官方模型配置")
    if protocol == "openai" and host in {"api.moonshot.cn", "api.moonshot.ai"} and path == "/v1":
        # https://platform.kimi.ai/docs/guide/use-reasoning-effort
        # K3 models always think and use top-level effort, not K2's thinking toggle.
        if model in {"kimi-k3", "kimi-k3.1-pro", "kimi-k3.1-pro-highspeed"}:
            return ReasoningCapability("effort", ("low", "high", "max"), "catalog", "max",
                                       "Kimi 官方原生档位；该模型不能关闭思考")
    if protocol == "openai" and host in {"api.siliconflow.cn", "api.siliconflow.com"} and path == "/v1":
        if model in {"deepseek-ai/DeepSeek-V4-Flash", "Pro/deepseek-ai/DeepSeek-V4",
                     "Pro/zai-org/GLM-5.2"}:
            return ReasoningCapability("effort", ("high", "max"), "catalog", "high", "平台原生强度档位")
        if model == "Qwen/Qwen3-8B":
            return ReasoningCapability("budget", ("none", "1024", "2048", "4096", "8192", "16384", "32768"),
                                       "catalog", None, "应用预算刻度，单位为 Token")
    return ReasoningCapability()


class ReasoningCapabilityCache:
    def __init__(self, path=None, ttl_seconds=86400):
        self.path = Path(path) if path is not None else None
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._lock = threading.RLock()
        self._entries = {}
        self._load()

    def _load(self):
        if self.path is None:
            return
        try:
            if self.path.stat().st_size > _MAX_METADATA_BYTES:
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != _CATALOG_VERSION or not isinstance(data.get("entries"), dict):
                return
            for key, item in list(data["entries"].items())[-256:]:
                if not re.fullmatch(r"[0-9a-f]{64}", key) or not isinstance(item, dict):
                    continue
                try:
                    capability = ReasoningCapability.from_dict(item["capability"])
                    timestamp = float(item["timestamp"])
                    if capability.known and math.isfinite(timestamp):
                        self._entries[key] = timestamp, capability
                except (KeyError, TypeError, ValueError):
                    continue
        except (OSError, ValueError, TypeError, AttributeError):
            return

    def get(self, identity):
        with self._lock:
            item = self._entries.get(identity)
            if item is None:
                return None
            timestamp, capability = item
            age = time.time() - timestamp
            if age < -60 or age >= self.ttl_seconds:
                self._entries.pop(identity, None)
                return None
            return replace(capability, source="cache", evidence_source=capability.evidence_source or capability.source)

    def put(self, identity, capability):
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ValueError("Invalid capability cache key")
        if not isinstance(capability, ReasoningCapability) or not capability.known:
            return
        with self._lock:
            self._entries[identity] = time.time(), capability
            if len(self._entries) > 256:
                oldest = min(self._entries, key=lambda key: self._entries[key][0])
                self._entries.pop(oldest)
            self._save()

    def forget(self, identity):
        """Remove one endpoint/model/key result after an explicit refresh."""
        with self._lock:
            if self._entries.pop(identity, None) is not None:
                self._save()

    def _save(self):
        if self.path is None:
            return
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {"version": _CATALOG_VERSION, "entries": {
                key: {"timestamp": timestamp, "capability": capability.to_dict()}
                for key, (timestamp, capability) in self._entries.items()}}
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             prefix=self.path.name + ".", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, ensure_ascii=False)
            os.replace(temporary, self.path)
            temporary = None
        except (OSError, TypeError, ValueError):
            pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _record_for_model(data, model):
    if not isinstance(data, dict):
        return None
    for field in ("data", "models"):
        if isinstance(data.get(field), list):
            return next((item for item in data[field] if isinstance(item, dict)
                         and item.get("id", item.get("name")) in (model, "models/" + model.removeprefix("models/"))), None)
    if isinstance(data.get("data"), dict):
        data = data["data"]
    identity = data.get("id", data.get("name"))
    if identity is not None and identity not in (model, "models/" + model.removeprefix("models/")):
        return None
    return data


def budget_levels(minimum, maximum, default=None):
    """Application ticks inside a declared numeric range, not native efforts."""
    if (isinstance(minimum, bool) or isinstance(maximum, bool)
            or not isinstance(minimum, int) or not isinstance(maximum, int)
            or not 0 <= minimum <= maximum <= 1_000_000):
        raise ValueError("Invalid reasoning budget range")
    values = {minimum, maximum}
    values.update(2 ** power for power in range(20) if minimum <= 2 ** power <= maximum)
    if isinstance(default, int) and not isinstance(default, bool) and minimum <= default <= maximum:
        values.add(default)
    return tuple("none" if value == 0 else str(value) for value in sorted(values))


def _compatible(capability, protocol):
    kinds = {"gemini", "budget", "none"} if protocol == "gemini" else {"effort", "deepseek", "budget", "toggle", "none"}
    if capability.kind not in kinds:
        return False
    if capability.parameter:
        native = capability.parameter.startswith("generationConfig.")
        if native != (protocol == "gemini"):
            return False
    return True


def _descriptor_capability(candidate, protocol):
    if not isinstance(candidate.get("levels", ()), (list, tuple)):
        return ReasoningCapability()
    descriptor = dict(candidate)
    descriptor["kind"] = descriptor.get("kind") or ("gemini" if protocol == "gemini" else "effort")
    descriptor["levels"] = [value for value in descriptor.get("levels", ()) if value != "auto"]
    descriptor["source"] = "metadata"
    descriptor["evidence_source"] = ""
    descriptor["note"] = "服务端明确声明的档位"
    if descriptor["kind"] == "budget":
        minimum = descriptor.get("budget_min", descriptor.get("minimum", descriptor.get("min_tokens")))
        maximum = descriptor.get("budget_max", descriptor.get("maximum", descriptor.get("max_tokens")))
        if minimum is not None or maximum is not None:
            descriptor["budget_min"], descriptor["budget_max"] = minimum, maximum
            default = descriptor.get("default_level")
            numeric_default = int(default) if isinstance(default, str) and default.isdecimal() else default
            if not descriptor["levels"]:
                descriptor["levels"] = budget_levels(minimum, maximum, numeric_default)
            descriptor["note"] = "服务端声明预算范围；滑条为应用划分的 Token 刻度"
        if descriptor.get("default_level") == "0":
            descriptor["default_level"] = "none"
        elif isinstance(descriptor.get("default_level"), int) and not isinstance(descriptor["default_level"], bool):
            descriptor["default_level"] = "none" if descriptor["default_level"] == 0 else str(descriptor["default_level"])
    if descriptor.get("default_level") == "auto":
        descriptor["default_level"] = None
    result = ReasoningCapability.from_dict(descriptor)
    return result if _compatible(result, protocol) else ReasoningCapability()


def _schema_node(schema, path):
    node = schema
    for part in path.split("."):
        node = _resolve_schema(node, schema)
        if not isinstance(node, dict):
            return None
        # JSON Schema uses properties; model-parameter maps often omit it.
        fields = node.get("properties", node)
        if not isinstance(fields, dict):
            return None
        if path in fields:
            return fields[path]
        node = fields.get(part)
    return node


def _resolve_schema(node, root):
    """Resolve bounded, local JSON Schema references without fetching URLs."""
    visited = set()
    for _ in range(8):
        if not isinstance(node, dict):
            return None
        reference = node.get("$ref")
        if reference is None:
            return node
        if not isinstance(reference, str) or not reference.startswith("#/") or reference in visited:
            return None
        visited.add(reference)
        target = root
        for part in reference[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                return None
            target = target[part]
        node = target
    return None


def _schema_allows_value(node, value):
    if not isinstance(node, dict):
        return True
    if "const" in node and node["const"] != value:
        return False
    if "enum" in node and (not isinstance(node["enum"], list) or value not in node["enum"]):
        return False
    return True


def _thinking_schema(schema):
    return (_resolve_schema(_schema_node(schema, "thinking"), schema),
            _resolve_schema(_schema_node(schema, "thinking.type"), schema))


def _schema_capability(record, model, protocol):
    """Interpret only schemas tied explicitly to the selected model."""
    schemas = [record.get(field) for field in
               ("parameters", "parameter_schema", "parameters_schema", "input_schema", "request_schema")]
    capabilities = record.get("capabilities")
    if isinstance(capabilities, dict):
        schemas.append(capabilities.get("parameters"))
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        model_node = _schema_node(schema, "model")
        explicit_model = record.get("id", record.get("name")) in (model, "models/" + model.removeprefix("models/"))
        scoped_schema = (isinstance(model_node, dict)
                         and (model_node.get("const") == model or model_node.get("enum") == [model]))
        if not explicit_model and not scoped_schema:
            continue
        if isinstance(model_node, dict) and ("const" in model_node or "enum" in model_node) and not scoped_schema:
            continue
        parameters = (("gemini", "generationConfig.thinkingConfig.thinkingLevel"),
                      ("budget", "generationConfig.thinkingConfig.thinkingBudget")) if protocol == "gemini" else (
                      ("effort", "reasoning_effort"), ("effort", "reasoning.effort"),
                      ("budget", "thinking_budget"), ("budget", "thinking.budget_tokens"),
                      ("toggle", "enable_thinking"), ("toggle", "thinking.type"))
        for kind, parameter in parameters:
            node = _resolve_schema(_schema_node(schema, parameter), schema)
            if not isinstance(node, dict):
                continue
            try:
                model_required = schema.get("required", [])
                if not isinstance(model_required, list):
                    continue
                if kind != "effort" and any(field in model_required for field in ("reasoning_effort", "reasoning")):
                    continue
                if kind == "effort" and "thinking_budget" in model_required:
                    continue
                if kind == "budget":
                    if node.get("type") != "integer":
                        continue
                    minimum, maximum = node.get("minimum"), node.get("maximum")
                    default = node.get("default")
                    if default is not None and (isinstance(default, bool) or not isinstance(default, int)):
                        continue
                    choices = node.get("enum")
                    if choices is not None:
                        if (not isinstance(choices, list) or not choices or len(choices) > 32
                                or any(type(value) is not int or not 0 <= value <= 1_000_000 for value in choices)):
                            continue
                        levels = tuple("none" if value == 0 else str(value) for value in choices)
                        if minimum is None and maximum is None:
                            minimum, maximum = min(choices), max(choices)
                        note = "当前模型参数规范声明的思考 Token 预算枚举"
                    else:
                        levels = budget_levels(minimum, maximum, default)
                        note = "模型参数规范声明预算范围；滑条为应用划分的 Token 刻度"
                    default = "none" if default == 0 else str(default) if default is not None else None
                    if parameter == "thinking.budget_tokens":
                        thinking_node, type_node = _thinking_schema(schema)
                        fields = thinking_node.get("properties", {}) if isinstance(thinking_node, dict) else {}
                        if (isinstance(thinking_node, dict) and thinking_node.get("additionalProperties") is False
                                and (not isinstance(fields, dict) or "type" not in fields)):
                            continue
                        if not _schema_allows_value(type_node, "enabled"):
                            continue
                        # Our disabled form omits budget_tokens; do not expose it
                        # when this model's schema requires a different shape.
                        required = thinking_node.get("required", []) if isinstance(thinking_node, dict) else []
                        if "budget_tokens" in required or not _schema_allows_value(type_node, "disabled"):
                            levels = tuple(value for value in levels if value != "none")
                            if default == "none":
                                default = None
                    result = ReasoningCapability(kind, levels, "schema", default,
                        note,
                        parameter=parameter, budget_min=minimum, budget_max=maximum)
                elif kind == "toggle":
                    if parameter == "enable_thinking" and node.get("type") == "boolean":
                        choices = node.get("enum", [False, True])
                        if not isinstance(choices, list) or not choices or any(type(value) is not bool for value in choices):
                            continue
                        levels = tuple("enabled" if value else "none" for value in choices)
                    elif parameter == "thinking.type" and isinstance(node.get("enum"), list):
                        thinking_node, _ = _thinking_schema(schema)
                        thinking_required = thinking_node.get("required", []) if isinstance(thinking_node, dict) else []
                        if not isinstance(thinking_required, list) or any(value != "type" for value in thinking_required):
                            continue
                        choices = node["enum"]
                        if not choices or any(value not in {"enabled", "disabled"} for value in choices):
                            continue
                        levels = tuple("none" if value == "disabled" else value for value in choices)
                    else:
                        continue
                    result = ReasoningCapability(kind, levels, "schema", note="当前模型参数规范声明的思考开关", parameter=parameter)
                else:
                    levels = node.get("enum")
                    if not isinstance(levels, list):
                        continue
                    levels = tuple(value for value in levels if value != "auto")
                    default = node.get("default") if node.get("default") != "auto" else None
                    wire_kind = kind
                    required = schema.get("required", [])
                    if kind == "effort" and isinstance(required, list) and "thinking" in required:
                        thinking_node, type_node = _thinking_schema(schema)
                        thinking_required = thinking_node.get("required", []) if isinstance(thinking_node, dict) else []
                        if (parameter != "reasoning_effort" or not isinstance(thinking_required, list)
                                or "type" not in thinking_required or any(value != "type" for value in thinking_required)
                                or not isinstance(type_node, dict) or not any(field in type_node for field in ("const", "enum"))
                                or not _schema_allows_value(type_node, "enabled")):
                            continue
                        wire_kind = "deepseek"
                        if "reasoning_effort" in required or not _schema_allows_value(type_node, "disabled"):
                            levels = tuple(value for value in levels if value != "none")
                            if default == "none":
                                default = None
                    result = ReasoningCapability(wire_kind, levels, "schema", default,
                        "当前模型参数规范声明的原生档位", parameter=parameter)
                if _compatible(result, protocol):
                    return result
            except (ValueError, TypeError):
                continue
    return ReasoningCapability()


def parse_metadata_capability(data, model, protocol):
    record = _record_for_model(data, model)
    if record is None:
        return ReasoningCapability()
    candidates = []
    capabilities = record.get("capabilities")
    if isinstance(capabilities, dict) and isinstance(capabilities.get("reasoning"), dict):
        candidates.append(capabilities["reasoning"])
    if isinstance(record.get("reasoning"), dict):
        candidates.append(record["reasoning"])
    for name, kind in (("supported_reasoning_efforts", "effort"), ("reasoning_efforts", "effort"),
                       ("supported_thinking_levels", "gemini")):
        if isinstance(record.get(name), list):
            candidates.append({"kind": kind, "levels": record[name], "default_level": record.get("default_reasoning_effort")})
    for candidate in candidates:
        try:
            result = _descriptor_capability(candidate, protocol)
            if result.known:
                return result
        except (TypeError, ValueError):
            continue
    return _schema_capability(record, model, protocol)


def _metadata_urls(url, protocol, model):
    base = _canonical_endpoint(url, protocol)
    if protocol == "gemini":
        parsed = urlsplit(base)
        if not parsed.path:
            base += "/v1beta"
        model = model.removeprefix("models/")
    return base + "/models/" + quote(model, safe=""), base + "/models"


def _fetch_metadata(url, protocol, model, api_key):
    opener = build_opener(_NoRedirect())
    for index, target in enumerate(_metadata_urls(url, protocol, model)):
        request = Request(target, headers={"Accept": "application/json"}, method="GET")
        if api_key:
            request.add_unredirected_header("X-Goog-Api-Key" if protocol == "gemini" else "Authorization",
                                           api_key if protocol == "gemini" else f"Bearer {api_key}")
        try:
            with opener.open(request, timeout=4) as response:
                body = response.read(_MAX_METADATA_BYTES + 1)
                if len(body) > _MAX_METADATA_BYTES:
                    return ReasoningCapability()
                data = json.loads(body.decode("utf-8"))
                capability = parse_metadata_capability(data, model, protocol)
                if capability.known or index:
                    return capability
                # Some gateways put richer capability records only in the list.
                # This is still read-only and the list parser requires exact IDs.
                continue
        except HTTPError as error:
            if index == 0 and error.code in {404, 405}:
                continue
            return ReasoningCapability()
        except (OSError, ValueError, TypeError, UnicodeError):
            return ReasoningCapability()
    return ReasoningCapability()


def discover_capability(url, protocol, model, api_key="", *, cache=None, force=False):
    protocol = str(protocol).strip().lower()
    model = str(model).strip()
    try:
        identity = capability_identity(url, protocol, model, api_key)
    except (TypeError, ValueError):
        return ReasoningCapability()
    if cache is not None and not force:
        cached = cache.get(identity)
        if cached is not None:
            return cached
    capability = _fetch_metadata(url, protocol, model, api_key)
    if not capability.known:
        capability = catalog_capability(url, protocol, model)
    if cache is not None and capability.known:
        cache.put(identity, capability)
    elif cache is not None and force:
        cache.forget(identity)
    return capability
