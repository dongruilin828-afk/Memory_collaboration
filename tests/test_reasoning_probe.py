"""Opt-in detection uses field validation evidence, bounded calls and safe results."""

import io
import json
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from scripts import reasoning_probe as probe
from scripts.reasoning_capabilities import ReasoningCapabilityCache, capability_identity


URL = "https://relay.test/v1"
MODEL = "a-model-never-seen-before"
KEY = "private-test-key"


def error(data, status=400):
    return HTTPError(URL, status, "private error", {}, io.BytesIO(json.dumps(data).encode()))


def success(protocol="openai"):
    return io.BytesIO(json.dumps({"candidates" if protocol == "gemini" else "choices": [
        {"message": {"role": "assistant", "content": "I support all levels, even imaginary."}}]}).encode())


def invalid(parameter, values):
    return error({"error": {"param": parameter, "message": "Invalid value. Supported values are: "
                           + ", ".join(repr(value) for value in values)}})


class ReasoningProbeTests(unittest.TestCase):
    def run_probe(self, respond, protocol="openai", **kwargs):
        opener = Mock()
        def dispatch(request, timeout):
            self.assertLessEqual(timeout, probe.PROBE_REQUEST_TIMEOUT)
            self.assertEqual(request.get_method(), "POST")
            return respond(request, json.loads(request.data))
        opener.open.side_effect = dispatch
        with patch.object(probe, "build_opener", return_value=opener):
            result = probe.probe_reasoning_capability(URL, protocol, MODEL, KEY, **kwargs)
        self.assertLessEqual(result.request_count, probe.MAX_PROBE_REQUESTS)
        self.assertEqual(result.request_count, opener.open.call_count)
        for private in (KEY, MODEL, "private error"):
            self.assertNotIn(private, result.message)
            self.assertNotIn(private, result.capability.note)
        return result, opener

    def test_exact_error_declared_future_enum_and_cache_provenance(self):
        levels = ("tiny", "balanced", "extra_deep")
        cache = ReasoningCapabilityCache()
        def respond(request, payload):
            value = payload.get("reasoning_effort")
            if value == probe._SENTINEL:
                raise invalid("reasoning_effort", levels)
            self.assertIn(value, levels)
            self.assertEqual(payload["max_tokens"], 128)
            return success()
        result, opener = self.run_probe(respond, cache=cache)
        self.assertEqual(result.status, "found")
        self.assertEqual(result.capability.levels, levels)
        self.assertEqual(result.capability.parameter, "reasoning_effort")
        self.assertEqual(result.capability.source, "probe_error")
        self.assertEqual(result.request_count, 4)
        cached = cache.get(capability_identity(URL, "openai", MODEL, KEY))
        self.assertEqual(cached.evidence_source, "probe_error")
        self.assertIsNone(cache.get(capability_identity(URL, "openai", MODEL, "another-key")))
        request = opener.open.call_args_list[0].args[0]
        self.assertEqual(request.unredirected_hdrs["Authorization"], "Bearer " + KEY)
        self.assertNotIn("Authorization", request.headers)
        self.assertNotIn(KEY, request.full_url)
        self.assertNotIn(KEY, request.data.decode())

    def test_successful_invalid_values_never_prove_support_or_use_self_report(self):
        result, _ = self.run_probe(lambda *_: success())
        self.assertFalse(result.capability.known)
        self.assertEqual(result.request_count, 6)
        self.assertIn("忽略参数", result.message)

    def test_unrelated_validation_enum_is_not_a_reasoning_enum(self):
        def respond(*_):
            raise error({"error": {"param": "role", "message":
                                   "reasoning_effort request role should be 'user' or 'assistant'"}})
        result, _ = self.run_probe(respond)
        self.assertFalse(result.capability.known)

    def test_nested_effort_cannot_inherit_top_level_validation(self):
        def respond(request, payload):
            if "reasoning" in payload:
                self.assertIn(payload["reasoning"]["effort"], {probe._SENTINEL, "low", "high"})
                if payload["reasoning"]["effort"] == probe._SENTINEL:
                    raise invalid("reasoning.effort", ("low", "high"))
                return success()
            raise error({"error": {"param": "reasoning_effort", "message": "Unknown parameter"}})
        result, _ = self.run_probe(respond)
        self.assertEqual(result.capability.parameter, "reasoning.effort")
        self.assertEqual(result.capability.levels, ("low", "high"))
        self.assertEqual(result.request_count, 4)

    def test_pydantic_literal_error_context_is_parsed(self):
        def respond(request, payload):
            if payload.get("reasoning_effort") == probe._SENTINEL:
                raise error({"detail": [{"loc": ["body", "reasoning_effort"],
                                        "type": "literal_error", "input": probe._SENTINEL,
                                        "ctx": {"expected": "'low', 'high' or 'maximum'"},
                                        "msg": "Input should be 'low', 'high' or 'maximum'"}]}, 422)
            return success()
        result, _ = self.run_probe(respond)
        self.assertEqual(result.capability.levels, ("low", "high", "maximum"))

    def test_invalid_enum_tokens_and_reflected_key_cannot_be_persisted(self):
        for values in (("auto", "high"), ("high", KEY), ("high", "bad.value"), ("high", "")):
            with self.subTest(values=values):
                def respond(request, payload):
                    if "reasoning_effort" in payload:
                        raise invalid("reasoning_effort", values)
                    raise error({"error": {"message": "Unknown parameter"}})
                result, _ = self.run_probe(respond)
                self.assertFalse(result.capability.known)

    def test_rejected_declared_levels_are_removed(self):
        def respond(request, payload):
            value = payload.get("reasoning_effort")
            if value == probe._SENTINEL:
                raise invalid("reasoning_effort", ("low", "medium", "high"))
            if value == "medium":
                raise error({"error": {"param": "reasoning_effort", "message": "Value unavailable"}})
            return success()
        result, _ = self.run_probe(respond)
        self.assertEqual(result.capability.levels, ("low", "high"))

    def test_unrelated_failure_does_not_remove_declared_levels(self):
        def respond(request, payload):
            if payload.get("reasoning_effort") == probe._SENTINEL:
                raise invalid("reasoning_effort", ("low", "high"))
            raise error({"error": {"param": "messages", "message": "Invalid message"}})
        result, _ = self.run_probe(respond)
        self.assertEqual(result.capability.levels, ("low", "high"))
        self.assertIn("未逐一测试", result.message)

    def test_many_declared_levels_respect_request_limit(self):
        levels = tuple("depth" + str(index) for index in range(20))
        def respond(request, payload):
            if payload.get("reasoning_effort") == probe._SENTINEL:
                raise invalid("reasoning_effort", levels)
            return success()
        result, _ = self.run_probe(respond)
        self.assertEqual(result.request_count, 8)
        self.assertEqual(result.capability.levels, levels)
        self.assertEqual(result.capability.source, "probe_error")

    def test_budget_has_application_ticks_range_and_direct_wire_parameter(self):
        def respond(request, payload):
            if "thinking_budget" not in payload:
                raise error({"error": {"message": "Unsupported parameter"}})
            self.assertNotIn("enable_thinking", payload)
            if payload["thinking_budget"] < 0:
                raise error({"error": {"param": "thinking_budget", "minimum": 0, "maximum": 4096,
                                       "message": "Budget must be in range: 0 to 4096"}})
            self.assertGreaterEqual(payload["thinking_budget"], 0)
            self.assertLessEqual(payload["thinking_budget"], 4096)
            return success()
        result, _ = self.run_probe(respond)
        self.assertEqual(result.capability.kind, "budget")
        self.assertEqual(result.capability.budget_min, 0)
        self.assertEqual(result.capability.budget_max, 4096)
        self.assertIn("none", result.capability.levels)
        self.assertIn("应用", result.capability.note)

    def test_incomplete_or_invalid_budget_bounds_are_not_invented(self):
        for bounds in ({"minimum": 128}, {"maximum": 8192}, {"minimum": -1, "maximum": 8192},
                       {"minimum": 8192, "maximum": 1024}, {"minimum": 0, "maximum": 99999999}):
            with self.subTest(bounds=bounds):
                def respond(*_):
                    raise error({"error": {"param": "thinking_budget", **bounds, "message": "Invalid budget"}})
                result, _ = self.run_probe(respond)
                self.assertFalse(result.capability.known)

    def test_toggle_boolean_requires_field_type_evidence_and_accepted_values(self):
        def respond(request, payload):
            if "enable_thinking" not in payload:
                raise error({"error": {"message": "Unsupported parameter"}})
            if not isinstance(payload["enable_thinking"], bool):
                raise error({"detail": [{"loc": ["body", "enable_thinking"], "type": "bool_parsing",
                                         "msg": "Input should be a valid boolean"}]}, 422)
            return success()
        result, _ = self.run_probe(respond)
        self.assertEqual(result.capability.kind, "toggle")
        self.assertEqual(result.capability.source, "probe_accepted")
        self.assertEqual(result.capability.levels, ("none", "enabled"))
        self.assertEqual(result.request_count, 8)

    def test_thinking_type_enum_maps_disabled_enabled(self):
        def respond(request, payload):
            if "thinking" not in payload:
                raise error({"error": {"message": "Unsupported parameter"}})
            value = payload["thinking"]["type"]
            if value == probe._SENTINEL:
                raise invalid("thinking.type", ("disabled", "enabled"))
            return success()
        result, _ = self.run_probe(respond)
        self.assertEqual(result.capability.parameter, "thinking.type")
        self.assertEqual(result.capability.levels, ("none", "enabled"))

    def test_coupled_deepseek_thinking_is_enabled_only_when_required(self):
        def respond(request, payload):
            if "thinking" not in payload:
                raise error({"error": {"param": "reasoning_effort", "message":
                                       "reasoning_effort requires thinking to be enabled"}})
            self.assertEqual(payload["thinking"], {"type": "enabled"})
            if payload.get("reasoning_effort") == probe._SENTINEL:
                raise invalid("reasoning_effort", ("low", "future_deep"))
            return success()
        result, _ = self.run_probe(respond)
        self.assertEqual(result.capability.kind, "deepseek")
        self.assertEqual(result.capability.levels, ("low", "future_deep"))
        self.assertEqual(result.request_count, 4)

    def test_gemini_model_path_header_enum_and_no_auth_query(self):
        def respond(request, payload):
            self.assertEqual(request.full_url, URL + "/models/" + MODEL + ":generateContent")
            self.assertEqual(request.unredirected_hdrs["X-goog-api-key"], KEY)
            self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 128)
            value = payload["generationConfig"]["thinkingConfig"]["thinkingLevel"]
            if value == probe._SENTINEL:
                raise error({"error": {"details": [{"fieldViolations": [{
                    "field": "generation_config.thinking_config.thinking_level",
                    "description": "Allowed values: 'LOW', 'MEDIUM', 'HIGH'"}]}]}})
            return success("gemini")
        result, _ = self.run_probe(respond, "gemini")
        self.assertEqual(result.capability.kind, "gemini")
        self.assertEqual(result.capability.levels, ("LOW", "MEDIUM", "HIGH"))

    def test_native_gemini_root_endpoint_adds_v1beta_and_escapes_model(self):
        self.assertEqual(probe._target("https://native.test", "gemini", "models/a/b"),
                         "https://native.test/v1beta/models/a%2Fb:generateContent")

    def test_confirmation_none_payload_matches_gateway_wire_semantics(self):
        nested = probe._request_payload("openai", MODEL, "thinking.budget_tokens", 0)
        self.assertEqual(nested["thinking"], {"type": "disabled"})
        coupled = probe._request_payload("openai", MODEL, "reasoning_effort", "none", coupled=True)
        self.assertEqual(coupled["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", coupled)
        native = probe._request_payload("gemini", MODEL, "generationConfig.thinkingConfig.thinkingLevel", "none")
        self.assertEqual(native["generationConfig"]["thinkingConfig"], {"thinkingBudget": 0})

    def test_unsupported_max_tokens_retries_once_with_completion_limit(self):
        def respond(request, payload):
            if "max_tokens" in payload:
                raise error({"error": {"param": "max_tokens", "message":
                                       "max_tokens is unsupported; use max_completion_tokens instead"}})
            self.assertEqual(payload["max_completion_tokens"], 128)
            if payload.get("reasoning_effort") == probe._SENTINEL:
                raise invalid("reasoning_effort", ("low",))
            return success()
        result, _ = self.run_probe(respond)
        self.assertEqual(result.request_count, 3)
        self.assertEqual(result.capability.levels, ("low",))

    def test_auth_rate_limit_and_server_failures_stop_immediately_without_details(self):
        for status, expected in ((401, "auth_error"), (403, "auth_error"), (429, "rate_limited"),
                                 (500, "unavailable"), (302, "unavailable")):
            with self.subTest(status=status):
                def respond(*_):
                    raise error({"error": {"message": KEY + " " + MODEL}}, status)
                result, _ = self.run_probe(respond)
                self.assertEqual(result.status, expected)
                self.assertEqual(result.request_count, 1)
                self.assertFalse(result.capability.known)

    def test_non_json_oversized_and_http200_error_wrappers_are_not_success(self):
        for body in (b"<html>private error</html>", b"x" * 65_537, b'{"error":{"message":"oops"}}', b'{}'):
            with self.subTest(length=len(body)):
                result, _ = self.run_probe(lambda *_: io.BytesIO(body))
                self.assertEqual(result.status, "unavailable")
                self.assertFalse(result.capability.known)
                self.assertEqual(result.request_count, 1)

    def test_cancel_before_request_has_no_network_or_cache_effects(self):
        cancelled = threading.Event()
        cancelled.set()
        cache = Mock()
        result, opener = self.run_probe(lambda *_: self.fail("request after cancellation"),
                                        cache=cache, cancel_event=cancelled)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.request_count, 0)
        cache.put.assert_not_called()

    def test_cancel_during_request_prevents_more_calls(self):
        cancelled = threading.Event()
        def respond(*_):
            cancelled.set()
            return success()
        result, _ = self.run_probe(respond, cancel_event=cancelled)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.request_count, 1)

    def test_wall_deadline_and_response_reads_are_bounded(self):
        opener = Mock()
        raw = success()
        raw.read1 = Mock(wraps=raw.read1)
        opener.open.return_value = raw
        with patch.object(probe, "build_opener", return_value=opener):
            result = probe.probe_reasoning_capability(URL, "openai", MODEL, KEY)
        self.assertTrue(raw.read1.called)
        self.assertTrue(all(call.args[0] <= 8192 for call in raw.read1.call_args_list))
        # A stalled response cannot block caller beyond its per-request deadline.
        def slow(*_):
            time.sleep(0.15)
            return success()
        with patch.object(probe, "PROBE_REQUEST_TIMEOUT", 0.03):
            start = time.monotonic()
            result, _ = self.run_probe(slow)
            self.assertLess(time.monotonic() - start, 0.13)
        self.assertEqual(result.status, "unavailable")

    def test_response_reader_stops_trickles_on_deadline_and_cancellation(self):
        class Trickle:
            def __init__(self):
                self.calls = 0
            def read1(self, count):
                self.calls += 1
                time.sleep(0.01)
                return b"x"
        stream = Trickle()
        with self.assertRaises(TimeoutError):
            probe._read_response(stream, time.monotonic() + 0.025, None)
        self.assertLessEqual(stream.calls, 3)
        stopped = threading.Event()
        stopped.set()
        stream = Trickle()
        with self.assertRaises(TimeoutError):
            probe._read_response(stream, time.monotonic() + 10, stopped)
        self.assertEqual(stream.calls, 0)

    def test_bad_endpoint_and_protocol_are_rejected_before_network(self):
        for url, protocol in (("file:///secret", "openai"), ("https://u:p@relay.test/v1", "openai"),
                              (URL + "?key=private", "openai"), (URL, "other")):
            with self.subTest(url=url, protocol=protocol), patch.object(probe, "build_opener") as factory:
                result = probe.probe_reasoning_capability(url, protocol, MODEL, KEY)
                self.assertEqual(result.status, "invalid")
                factory.assert_not_called()

    def test_passive_discovery_never_imports_or_calls_probe(self):
        from scripts import reasoning_capabilities as capabilities
        with patch.object(capabilities, "_fetch_metadata", return_value=capabilities.ReasoningCapability()), \
                patch.object(probe, "probe_reasoning_capability") as active:
            capabilities.discover_capability(URL, "openai", MODEL, KEY)
        active.assert_not_called()


if __name__ == "__main__":
    unittest.main()
