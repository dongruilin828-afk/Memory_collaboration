"""Explicit model metadata, provider-specific catalog, and safe capability cache."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

from scripts import reasoning_capabilities as reasoning


class ReasoningCapabilityTests(unittest.TestCase):
    def test_kimi_official_k3_models_have_native_efforts_and_default_max(self):
        for host in ("api.moonshot.cn", "api.moonshot.ai"):
            for model in ("kimi-k3", "kimi-k3.1-pro", "kimi-k3.1-pro-highspeed"):
                with self.subTest(host=host, model=model):
                    capability = reasoning.catalog_capability(f"https://{host}/v1", "openai", model)
                    self.assertEqual(capability.kind, "effort")
                    self.assertEqual(capability.levels, ("low", "high", "max"))
                    self.assertEqual(capability.default_level, "max")
                    self.assertNotIn("none", capability.levels)
        for url, protocol, model in (
            ("https://api.moonshot.cn.example.test/v1", "openai", "kimi-k3.1-pro"),
            ("https://proxy.test/v1", "openai", "kimi-k3.1-pro"),
            ("https://api.moonshot.cn/coding/v1", "openai", "kimi-k3.1-pro"),
            ("https://api.moonshot.cn/v1", "gemini", "kimi-k3.1-pro"),
            ("https://api.moonshot.cn/v1", "openai", "kimi-unknown"),
            ("https://api.moonshot.cn/v1", "openai", "kimi-k2.5"),
        ):
            with self.subTest(url=url, model=model, protocol=protocol):
                self.assertFalse(reasoning.catalog_capability(url, protocol, model).known)

    def test_descriptor_roundtrip_preserves_native_levels_and_ignores_outer_wire_fields(self):
        wire = dict(kind="effort", levels=["high", "low", "high", "max"], source="manual",
                    default_level="high", note="测试", identity="profile-hash", override=True)
        capability = reasoning.ReasoningCapability.from_dict(wire)
        self.assertTrue(capability.known)
        self.assertEqual(capability.levels, ("low", "high", "max"))
        self.assertEqual(reasoning.ReasoningCapability.from_dict(capability.to_dict()), capability)
        self.assertNotIn("identity", capability.to_dict())
        self.assertNotIn("override", capability.to_dict())

    def test_invalid_or_automatic_native_levels_cannot_be_injected(self):
        descriptors = [
            dict(kind="effort", levels=["auto", "low"]),
            dict(kind="effort", levels=["unsafe value"]),
            dict(kind="effort", levels="low"),
            dict(kind="effort", levels=[]),
            dict(kind="arbitrary", levels=["low"]),
            dict(kind=["effort"], levels=["low"]),
            dict(kind="unknown", levels=["high"]),
            dict(kind="none", levels=["none"]),
            dict(kind="effort", levels=["low"], default_level="high"),
            dict(kind="budget", levels=["-1"]),
            dict(kind="budget", levels=["0"]),
            dict(kind="budget", levels=["1000001"]),
            dict(kind="budget", levels=["1.5"]),
            dict(kind="toggle", levels=["high"]),
            dict(kind="gemini", levels=["auto"]),
        ]
        for descriptor in descriptors:
            with self.subTest(descriptor=descriptor), self.assertRaises(ValueError):
                reasoning.ReasoningCapability.from_dict(descriptor)

    def test_budget_and_toggle_levels_are_native_controls(self):
        budget = reasoning.ReasoningCapability("budget", ("4096", "none", "1024"), "manual")
        self.assertEqual(budget.levels, ("none", "1024", "4096"))
        toggle = reasoning.ReasoningCapability("toggle", ("enabled", "none"), "manual")
        self.assertEqual(toggle.levels, ("none", "enabled"))
        self.assertTrue(reasoning.ReasoningCapability("none").known)
        self.assertFalse(reasoning.ReasoningCapability().known)

    def test_identity_normalizes_origin_and_completion_suffix_without_merging_scopes(self):
        identity = reasoning.capability_identity("https://API.Example.test:443/V1/chat/completions/", "openai", "Model-A", "key")
        self.assertEqual(identity, reasoning.capability_identity("https://api.example.test/V1", "openai", "Model-A", "key"))
        for url, protocol, model, key in (
            ("https://api.example.test/v1", "openai", "Model-A", "key"),
            ("https://api.example.test:8443/V1", "openai", "Model-A", "key"),
            ("https://api.example.test/V1", "gemini", "Model-A", "key"),
            ("https://api.example.test/V1", "openai", "model-a", "key"),
            ("https://api.example.test/V1", "openai", "Model-A", "second-key"),
        ):
            self.assertNotEqual(identity, reasoning.capability_identity(url, protocol, model, key))
        self.assertRegex(identity, r"^[0-9a-f]{64}$")

    def test_identity_rejects_credentials_queries_fragments_and_control_characters(self):
        for url in ("file:///tmp/model", "https://name:secret@example.test/v1",
                    "https://example.test/v1?key=secret", "https://example.test/v1#fragment",
                    "https://example.test\n/v1", "https://example.test:0/v1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                reasoning.capability_identity(url, "openai", "model")

    def test_official_catalog_is_model_and_endpoint_specific(self):
        openai = reasoning.catalog_capability("https://api.openai.com/v1", "openai", "gpt-6-astra")
        self.assertEqual(openai.levels, ("low", "medium", "high", "xhigh", "max"))
        optional = reasoning.catalog_capability("https://api.openai.com/v1", "openai", "gpt-6.1-terra")
        self.assertIn("none", optional.levels)
        gemini = reasoning.catalog_capability("https://generativelanguage.googleapis.com", "gemini", "models/gemini-3.8-flash")
        self.assertEqual(gemini.levels, ("low", "medium", "high"))
        lite = reasoning.catalog_capability("https://generativelanguage.googleapis.com/v1beta", "gemini", "gemini-3.5-flash-lite")
        self.assertIn("minimal", lite.levels)
        self.assertEqual(lite.default_level, "minimal")
        official = reasoning.catalog_capability("https://api.deepseek.com/v1", "openai", "deepseek-flash")
        hosted = reasoning.catalog_capability("https://api.siliconflow.cn/v1", "openai", "deepseek-ai/DeepSeek-V4-Flash")
        self.assertEqual(official.kind, "deepseek")
        self.assertIn("low", official.levels)
        self.assertNotIn("low", hosted.levels)
        budget = reasoning.catalog_capability("https://api.siliconflow.cn/v1", "openai", "Qwen/Qwen3-8B")
        self.assertEqual(budget.kind, "budget")
        self.assertIn("none", budget.levels)

    def test_catalog_does_not_guess_third_party_or_unrecognized_versions(self):
        for url, protocol, model in (
            ("https://proxy.test/v1", "openai", "gpt-6-astra"),
            ("https://api.openai.com.proxy.test/v1", "openai", "gpt-6-astra"),
            ("http://api.openai.com/v1", "openai", "gpt-6-astra"),
            ("https://api.openai.com:8443/v1", "openai", "gpt-6-astra"),
            ("https://api.openai.com/CustomProxy", "openai", "gpt-6-astra"),
            ("https://api.openai.com/v1", "openai", "gpt-future"),
            ("https://generativelanguage.googleapis.com", "openai", "gemini-3.8-flash"),
        ):
            with self.subTest(url=url, model=model):
                self.assertFalse(reasoning.catalog_capability(url, protocol, model).known)

    def test_explicit_metadata_beats_catalog_and_boolean_thinking_does_not_supply_levels(self):
        data = {"id": "gpt-6-astra", "capabilities": {"reasoning": {
            "kind": "effort", "levels": ["low", "high"], "default_level": "low",
        }}}
        capability = reasoning.parse_metadata_capability(data, "gpt-6-astra", "openai")
        self.assertEqual(capability.levels, ("low", "high"))
        self.assertEqual(capability.source, "metadata")
        for data in ({"thinking": True}, {"thinking": False}, {"capabilities": {"reasoning": True}}, {}):
            self.assertFalse(reasoning.parse_metadata_capability(data, "m", "openai").known)

    def test_metadata_list_uses_exact_model_and_drops_native_auto(self):
        data = {"data": [
            {"id": "other-model", "reasoning_efforts": ["low", "high"]},
            {"id": "my-model", "supported_reasoning_efforts": ["auto", "medium", "high"]},
        ]}
        capability = reasoning.parse_metadata_capability(data, "my-model", "openai")
        self.assertEqual(capability.levels, ("medium", "high"))
        self.assertFalse(reasoning.parse_metadata_capability(data, "missing", "openai").known)
        self.assertFalse(reasoning.parse_metadata_capability({"id": "other", "reasoning_efforts": ["high"]}, "my-model", "openai").known)
        self.assertFalse(reasoning.parse_metadata_capability({"reasoning_efforts": ["auto"]}, "m", "openai").known)

    def test_metadata_cannot_select_incompatible_or_arbitrary_payload_dialects(self):
        for descriptor in ({"kind": "shell", "levels": ["high"]},
                           {"kind": "budget", "levels": ["-1", "999999999"]},
                           {"kind": "effort", "levels": ["high", "unsafe value"]}):
            data = {"capabilities": {"reasoning": descriptor}}
            self.assertFalse(reasoning.parse_metadata_capability(data, "m", "openai").known)
        self.assertFalse(reasoning.parse_metadata_capability({"supported_thinking_levels": ["low", "high"]}, "m", "openai").known)

    def test_future_native_enums_preserve_server_values_and_order(self):
        data = {"id": "never-seen", "reasoning_efforts": ["light", "balanced", "extreme_v2"]}
        capability = reasoning.parse_metadata_capability(data, "never-seen", "openai")
        self.assertEqual(capability.levels, ("light", "balanced", "extreme_v2"))
        self.assertEqual(capability.source, "metadata")
        native = reasoning.parse_metadata_capability({"supported_thinking_levels": ["LIGHT", "DEEP"]}, "new", "gemini")
        self.assertEqual(native.levels, ("LIGHT", "DEEP"))

    def test_parameter_paths_and_budget_bounds_are_validated_in_snapshots(self):
        capability = reasoning.ReasoningCapability("effort", ("balanced",), "schema", parameter="reasoning.effort")
        self.assertEqual(reasoning.ReasoningCapability.from_dict(capability.to_dict()), capability)
        for extra in ({"parameter": "headers.Authorization"}, {"parameter": "generationConfig.thinkingConfig.thinkingLevel"},
                      {"budget_min": 0, "budget_max": 1024}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                reasoning.ReasoningCapability("effort", ("low",), **extra)
        for minimum, maximum, levels in ((False, 1024, ("1024",)), (512, 1024, ("2048",)),
                                         (1024, 512, ("1024",)), (0, 1000001, ("1024",))):
            with self.subTest(minimum=minimum, maximum=maximum), self.assertRaises(ValueError):
                reasoning.ReasoningCapability("budget", levels, budget_min=minimum, budget_max=maximum)

    def test_model_parameter_schema_supplies_unseen_enum_and_wire_path(self):
        data = {"data": [{"id": "another", "parameters": {"reasoning_effort": {"enum": ["wrong"]}}},
                         {"id": "new", "parameter_schema": {"type": "object", "properties": {
                             "reasoning": {"type": "object", "properties": {
                                 "effort": {"type": "string", "enum": ["gentle", "intense"], "default": "gentle"}}}}}}]}
        capability = reasoning.parse_metadata_capability(data, "new", "openai")
        self.assertEqual(capability.source, "schema")
        self.assertEqual(capability.levels, ("gentle", "intense"))
        self.assertEqual(capability.parameter, "reasoning.effort")
        self.assertEqual(capability.default_level, "gentle")

    def test_parameter_schemas_must_be_scoped_to_current_model(self):
        schema = {"properties": {"reasoning_effort": {"enum": ["low", "high"]}}}
        self.assertFalse(reasoning.parse_metadata_capability({"parameters": schema}, "new", "openai").known)
        self.assertFalse(reasoning.parse_metadata_capability({"id": "another", "parameters": schema}, "new", "openai").known)
        schema["properties"]["model"] = {"const": "new"}
        self.assertTrue(reasoning.parse_metadata_capability({"parameters": schema}, "new", "openai").known)
        schema["properties"]["model"] = {"enum": ["new", "another"]}
        self.assertFalse(reasoning.parse_metadata_capability({"id": "new", "parameters": schema}, "new", "openai").known)

    def test_schema_numeric_budgets_become_application_ticks_with_exact_bounds(self):
        data = {"id": "new", "parameters": {"thinking": {"properties": {
            "budget_tokens": {"type": "integer", "minimum": 1000, "maximum": 9999, "default": 3000}}}}}
        capability = reasoning.parse_metadata_capability(data, "new", "openai")
        self.assertEqual(capability.kind, "budget")
        self.assertEqual(capability.parameter, "thinking.budget_tokens")
        self.assertEqual((capability.budget_min, capability.budget_max), (1000, 9999))
        self.assertEqual(capability.default_level, "3000")
        self.assertEqual(capability.levels[0], "1000")
        self.assertEqual(capability.levels[-1], "9999")
        self.assertIn("应用", capability.note)
        self.assertNotIn("none", capability.levels)

    def test_metadata_budget_range_and_zero_disable_are_preserved(self):
        data = {"reasoning": {"kind": "budget", "minimum": 0, "maximum": 2048, "default_level": 0}}
        capability = reasoning.parse_metadata_capability(data, "new", "openai")
        self.assertEqual(capability.budget_min, 0)
        self.assertEqual(capability.budget_max, 2048)
        self.assertEqual(capability.default_level, "none")
        self.assertEqual(capability.levels[0], "none")
        self.assertIn("2048", capability.levels)

    def test_budget_schema_discrete_numeric_enum_is_preserved(self):
        data = {"id": "new", "parameters": {"thinking_budget": {
            "type": "integer", "enum": [0, 333, 999], "default": 333}}}
        capability = reasoning.parse_metadata_capability(data, "new", "openai")
        self.assertEqual(capability.levels, ("none", "333", "999"))
        self.assertEqual(capability.default_level, "333")
        self.assertEqual(capability.parameter, "thinking_budget")
        data["parameters"]["thinking_budget"]["default"] = False
        self.assertFalse(reasoning.parse_metadata_capability(data, "new", "openai").known)

    def test_intermediate_local_references_resolve_nested_parameters(self):
        schema = {"properties": {"reasoning": {"$ref": "#/$defs/reasoning"}},
                  "$defs": {"reasoning": {"properties": {"effort": {"enum": ["eco", "future_extreme"]}}}}}
        capability = reasoning.parse_metadata_capability({"id": "new", "parameter_schema": schema}, "new", "openai")
        self.assertEqual(capability.parameter, "reasoning.effort")
        self.assertEqual(capability.levels, ("eco", "future_extreme"))
        schema["$defs"]["reasoning"] = {"$ref": "#/$defs/reasoning"}
        self.assertFalse(reasoning.parse_metadata_capability({"id": "new", "parameter_schema": schema}, "new", "openai").known)

    def test_string_zero_default_and_new_enabled_native_enum(self):
        capability = reasoning.parse_metadata_capability({"reasoning": {
            "kind": "budget", "minimum": 0, "maximum": 1024, "default_level": "0"}}, "new", "openai")
        self.assertEqual(capability.default_level, "none")
        effort = reasoning.ReasoningCapability("effort", ("enabled",), "metadata")
        self.assertEqual(effort.levels, ("enabled",))
        combined = reasoning.ReasoningCapability("deepseek", ("eco", "future_extreme"), "probe_error")
        self.assertEqual(combined.levels, ("eco", "future_extreme"))

    def test_strict_nested_budget_schema_must_allow_emitted_type_control(self):
        thinking = {"type": "object", "additionalProperties": False, "properties": {
            "budget_tokens": {"type": "integer", "minimum": 1024, "maximum": 4096}}}
        data = {"id": "new", "parameter_schema": {"properties": {"thinking": thinking}}}
        self.assertFalse(reasoning.parse_metadata_capability(data, "new", "openai").known)
        thinking["properties"]["type"] = {"enum": ["disabled"]}
        self.assertFalse(reasoning.parse_metadata_capability(data, "new", "openai").kind == "budget")
        thinking["properties"]["type"] = {"const": "enabled"}
        thinking["required"] = ["type", "budget_tokens"]
        capability = reasoning.parse_metadata_capability(data, "new", "openai")
        self.assertEqual(capability.kind, "budget")
        self.assertEqual(capability.parameter, "thinking.budget_tokens")
        thinking["properties"]["budget_tokens"]["minimum"] = 0
        capability = reasoning.parse_metadata_capability(data, "new", "openai")
        self.assertEqual(capability.kind, "budget")
        self.assertNotIn("none", capability.levels)

    def test_required_thinking_effort_schema_uses_combined_control(self):
        thinking = {"properties": {"type": {"enum": ["enabled"]}}, "required": ["type"]}
        schema = {"required": ["thinking", "reasoning_effort"], "properties": {
            "reasoning_effort": {"enum": ["none", "eco", "future_extreme"]}, "thinking": thinking}}
        data = {"id": "new", "parameter_schema": schema}
        capability = reasoning.parse_metadata_capability(data, "new", "openai")
        self.assertEqual(capability.kind, "deepseek")
        self.assertEqual(capability.levels, ("eco", "future_extreme"))
        thinking["properties"]["type"] = {"const": "disabled"}
        self.assertFalse(reasoning.parse_metadata_capability(data, "new", "openai").known)
        thinking["properties"]["type"] = {"const": "enabled"}
        thinking["required"].append("budget_tokens")
        self.assertFalse(reasoning.parse_metadata_capability(data, "new", "openai").known)

    def test_malformed_model_identifiers_fail_softly(self):
        for data in ({"id": []}, {"id": {}}, {"data": [{"id": []}, {"id": "new", "reasoning_efforts": ["high"]}]}):
            result = reasoning.parse_metadata_capability(data, "new", "openai")
            self.assertEqual(result.known, isinstance(data.get("data"), list))

    def test_gemini_schema_uses_native_nested_parameter_and_rejects_other_protocol(self):
        data = {"id": "new", "input_schema": {"generationConfig": {"thinkingConfig": {
            "thinkingLevel": {"enum": ["LIGHT", "DEEP"]}}}}}
        capability = reasoning.parse_metadata_capability(data, "new", "gemini")
        self.assertEqual(capability.parameter, "generationConfig.thinkingConfig.thinkingLevel")
        self.assertEqual(capability.levels, ("LIGHT", "DEEP"))
        self.assertFalse(reasoning.parse_metadata_capability(data, "new", "openai").known)

    def test_schema_toggle_and_local_reference_are_bounded(self):
        data = {"id": "new", "parameters": {"$defs": {"efforts": {"enum": ["soft", "hard"]}},
                 "properties": {"reasoning_effort": {"$ref": "#/$defs/efforts"}}}}
        capability = reasoning.parse_metadata_capability(data, "new", "openai")
        self.assertEqual(capability.levels, ("soft", "hard"))
        data["parameters"]["properties"]["reasoning_effort"]["$ref"] = "https://untrusted.test/schema"
        self.assertFalse(reasoning.parse_metadata_capability(data, "new", "openai").known)
        toggle = reasoning.parse_metadata_capability({"id": "new", "parameters": {
            "enable_thinking": {"type": "boolean"}}}, "new", "openai")
        self.assertEqual(toggle.levels, ("none", "enabled"))
        self.assertEqual(toggle.parameter, "enable_thinking")


class ReasoningDiscoveryTests(unittest.TestCase):
    def response(self, data):
        return io.BytesIO(json.dumps(data).encode("utf-8"))

    def test_discovery_uses_read_only_scoped_model_request_and_bounded_response(self):
        response = self.response({"id": "Qwen/My Model", "reasoning_efforts": ["low", "high"]})
        response.read = Mock(wraps=response.read)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(reasoning, "build_opener", return_value=opener) as factory:
            capability = reasoning.discover_capability("https://proxy.test/v1", "openai", "Qwen/My Model", "secret-key")
        self.assertEqual(capability.levels, ("low", "high"))
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://proxy.test/v1/models/Qwen%2FMy%20Model")
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.unredirected_hdrs["Authorization"], "Bearer secret-key")
        self.assertNotIn("Authorization", request.headers)
        self.assertLessEqual(opener.open.call_args.kwargs["timeout"], 4)
        response.read.assert_called_once_with(1_048_577)
        self.assertIsInstance(factory.call_args.args[0], reasoning._NoRedirect)

    def test_redirect_is_never_followed_or_forwarded(self):
        request = Request("https://proxy.test/v1/models/m")
        handler = reasoning._NoRedirect()
        self.assertIsNone(handler.redirect_request(request, None, 302, "redirect", {}, "https://other.test"))
        opener = Mock()
        opener.open.side_effect = HTTPError(request.full_url, 302, "redirect", {}, None)
        with patch.object(reasoning, "build_opener", return_value=opener):
            capability = reasoning.discover_capability("https://proxy.test/v1", "openai", "m", "secret")
        self.assertFalse(capability.known)
        self.assertEqual(opener.open.call_count, 1)

    def test_not_found_lookup_can_fall_back_to_read_only_model_list(self):
        opener = Mock()
        opener.open.side_effect = [HTTPError("https://proxy.test/v1/models/m", 404, "missing", {}, None),
                                   self.response({"data": [{"id": "m", "reasoning_efforts": ["low", "high"]}]})]
        with patch.object(reasoning, "build_opener", return_value=opener):
            capability = reasoning.discover_capability("https://proxy.test/v1", "openai", "m", "secret")
        self.assertTrue(capability.known)
        self.assertEqual([call.args[0].full_url for call in opener.open.call_args_list],
                         ["https://proxy.test/v1/models/m", "https://proxy.test/v1/models"])

    def test_sparse_detail_can_read_richer_exact_model_list(self):
        opener = Mock()
        opener.open.side_effect = [self.response({"id": "m"}), self.response({"data": [
            {"id": "different", "reasoning_efforts": ["wrong"]},
            {"id": "m", "reasoning_efforts": ["balanced", "deep"]}]})]
        with patch.object(reasoning, "build_opener", return_value=opener):
            capability = reasoning.discover_capability("https://proxy.test/v1", "openai", "m")
        self.assertEqual(capability.levels, ("balanced", "deep"))
        self.assertEqual(opener.open.call_count, 2)

    def test_gemini_uses_key_header_and_native_model_path(self):
        opener = Mock()
        opener.open.return_value = self.response({"name": "models/gemini-custom", "supported_thinking_levels": ["low", "high"]})
        with patch.object(reasoning, "build_opener", return_value=opener):
            capability = reasoning.discover_capability("https://proxy.test", "gemini", "models/gemini-custom", "secret")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://proxy.test/v1beta/models/gemini-custom")
        self.assertEqual(request.unredirected_hdrs["X-goog-api-key"], "secret")
        self.assertNotIn("secret", request.full_url)
        self.assertEqual(capability.kind, "gemini")

    def test_missing_or_bad_metadata_uses_only_trusted_catalog(self):
        for body in (b'{}', b'{bad json', b'x' * 1_048_577):
            with self.subTest(length=len(body)):
                opener = Mock()
                opener.open.return_value = io.BytesIO(body)
                with patch.object(reasoning, "build_opener", return_value=opener):
                    capability = reasoning.discover_capability("https://api.deepseek.com", "openai", "deepseek-flash")
                self.assertEqual(capability.source, "catalog")
                self.assertEqual(capability.kind, "deepseek")
        opener = Mock()
        opener.open.side_effect = TimeoutError("timeout with secret details")
        with patch.object(reasoning, "build_opener", return_value=opener):
            self.assertFalse(reasoning.discover_capability("https://proxy.test/v1", "openai", "deepseek-flash").known)

    def test_cache_hit_avoids_network_and_force_refreshes_explicit_metadata(self):
        cache = reasoning.ReasoningCapabilityCache()
        identity = reasoning.capability_identity("https://proxy.test/v1", "openai", "m", "key")
        cache.put(identity, reasoning.ReasoningCapability("effort", ("low", "high"), "metadata"))
        with patch.object(reasoning, "_fetch_metadata") as fetch:
            self.assertEqual(reasoning.discover_capability("https://proxy.test/v1", "openai", "m", "key", cache=cache).source, "cache")
        fetch.assert_not_called()
        with patch.object(reasoning, "_fetch_metadata", return_value=reasoning.ReasoningCapability("effort", ("high",), "metadata")) as fetch:
            capability = reasoning.discover_capability("https://proxy.test/v1", "openai", "m", "key", cache=cache, force=True)
        self.assertEqual(capability.levels, ("high",))
        fetch.assert_called_once()

    def test_force_refresh_unknown_invalidates_stale_scope_only(self):
        cache = reasoning.ReasoningCapabilityCache()
        identity = reasoning.capability_identity("https://proxy.test/v1", "openai", "m", "key")
        other = reasoning.capability_identity("https://proxy.test/v1", "openai", "other", "key")
        old = reasoning.ReasoningCapability("effort", ("high",), "probe_accepted")
        cache.put(identity, old)
        cache.put(other, old)
        with patch.object(reasoning, "_fetch_metadata", return_value=reasoning.ReasoningCapability()):
            result = reasoning.discover_capability("https://proxy.test/v1", "openai", "m", "key", cache=cache, force=True)
        self.assertFalse(result.known)
        self.assertIsNone(cache.get(identity))
        self.assertIsNotNone(cache.get(other))


class ReasoningCacheTests(unittest.TestCase):
    def test_cached_result_retains_evidence_and_wire_dialect(self):
        cache = reasoning.ReasoningCapabilityCache()
        capability = reasoning.ReasoningCapability("effort", ("light", "deep"), "probe_accepted",
                                                   parameter="reasoning.effort")
        cache.put("a" * 64, capability)
        cached = cache.get("a" * 64)
        self.assertEqual(cached.source, "cache")
        self.assertEqual(cached.evidence_source, "probe_accepted")
        self.assertEqual(cached.parameter, "reasoning.effort")
        cache.put("a" * 64, cached)
        self.assertEqual(cache.get("a" * 64).evidence_source, "probe_accepted")

    def test_persistent_cache_contains_hashed_scope_only_and_expires(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capabilities.json"
            key = reasoning.capability_identity("https://private.test/v1", "openai", "private-model", "private-key")
            cache = reasoning.ReasoningCapabilityCache(path)
            capability = reasoning.ReasoningCapability("effort", ("low", "high"), "metadata")
            with patch.object(reasoning.time, "time", return_value=1000):
                cache.put(key, capability)
            text = path.read_text(encoding="utf-8")
            for private in ("private.test", "private-model", "private-key"):
                self.assertNotIn(private, text)
            restored = reasoning.ReasoningCapabilityCache(path, ttl_seconds=60)
            with patch.object(reasoning.time, "time", return_value=1020):
                self.assertEqual(restored.get(key).levels, capability.levels)
            with patch.object(reasoning.time, "time", return_value=1061):
                self.assertIsNone(restored.get(key))

    def test_unknown_results_are_not_cached_and_corrupt_or_unwritable_cache_fails_softly(self):
        key = "a" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capabilities.json"
            path.write_text("bad JSON", encoding="utf-8")
            cache = reasoning.ReasoningCapabilityCache(path)
            cache.put(key, reasoning.ReasoningCapability())
            self.assertIsNone(cache.get(key))
            capability = reasoning.ReasoningCapability("effort", ("low",), "metadata")
            unwritable = reasoning.ReasoningCapabilityCache(Path(directory))
            unwritable.put(key, capability)
            self.assertEqual(unwritable.get(key).levels, ("low",))


if __name__ == "__main__":
    unittest.main()
