"""Capability snapshots produce native reasoning controls without network I/O."""

import io
import json
import unittest
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import patch

from scripts import gemini_summarizer as summary
from scripts.api_config import normalize_custom_api
from scripts.reasoning_capabilities import ReasoningCapability, capability_identity


def settings(level="auto", *, kind="effort", levels=("none", "low", "high", "max"),
             protocol="openai", model="my-model", url="https://example.test/v1",
             parameter="", budget_min=None, budget_max=None, **kwargs):
    capability = ReasoningCapability(kind, levels, "manual", parameter=parameter,
                                     budget_min=budget_min, budget_max=budget_max)
    return dict(name="测试接口", url=url, model=model, protocol=protocol,
                thinking_level=level, reasoning_config={
                    **capability.to_dict(), "identity": capability_identity(url, protocol, model),
                    "override": True,
                }, **kwargs)


class ReasoningSnapshotTests(unittest.TestCase):
    def test_detected_levels_cannot_follow_a_different_key_at_request_time(self):
        values = settings("high")
        values["reasoning_config"].update(
            override=False, scope=capability_identity(values["url"], values["protocol"], values["model"], "old-key"),
        )
        config = summary.custom_summary_config(values)
        with patch.object(summary, "SiliconFlowGateway") as factory:
            with self.assertRaises(summary.GeminiSummaryError):
                summary.create_gateway(config, api_key="new-key")
            factory.assert_not_called()
            summary.create_gateway(replace(config, thinking_level="auto"), api_key="new-key")
            factory.assert_called_once()

    def test_observation_timestamp_is_sanitized_and_roundtrips(self):
        values = settings("high")
        values["reasoning_config"]["observed_at"] = 1000.5
        self.assertEqual(normalize_custom_api(values)["reasoning_config"]["observed_at"], 1000.5)
        for timestamp in (float("inf"), float("nan"), -1, True, "yesterday"):
            values["reasoning_config"]["observed_at"] = timestamp
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                normalize_custom_api(values)

    def test_environment_auto_uses_service_defaults_for_every_builtin_provider(self):
        for provider in ("gemini", "deepseek", "siliconflow"):
            with self.subTest(provider=provider), patch.dict(
                summary.os.environ, {"GEMINI_THINKING_LEVEL": "auto"}, clear=True,
            ):
                config = summary.SummaryConfig.from_env(provider_override=provider)
                self.assertEqual(config.thinking_level, "auto")
                if provider == "gemini":
                    self.assertEqual(summary._gemini_reasoning_parameters(config), {})
                else:
                    endpoint = summary.DEEPSEEK_API_BASE if provider == "deepseek" else summary.SILICONFLOW_API_BASE
                    self.assertEqual(summary._http_reasoning_parameters(config, endpoint, config.model), {})

    def test_legacy_profiles_keep_shape_and_do_not_inherit_another_snapshot(self):
        old = dict(name="旧接口", url="https://legacy.test/v1", model="legacy-model",
                   protocol="openai", thinking_level="minimal")
        normalized = normalize_custom_api(old)
        self.assertNotIn("reasoning_config", normalized)
        config = summary.custom_summary_config(old, summary.custom_summary_config(settings()))
        self.assertIsNone(config.reasoning_config)
        self.assertEqual(config.thinking_level, "minimal")
        with self.assertRaises(ValueError):
            normalize_custom_api({**old, "protocol": "gemini", "thinking_level": "none"})

    def test_snapshot_binds_to_normalized_endpoint_protocol_and_exact_model(self):
        values = settings("high", url="https://API.Example.test:443/v1/chat/completions/")
        config = summary.custom_summary_config(values)
        self.assertEqual(config.api_base, "https://API.Example.test:443/v1")
        for changed in ({"url": "https://another.test/v1"}, {"model": "another-model"},
                        {"protocol": "gemini"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                normalize_custom_api({**values, **changed})
        missing = {**values, "reasoning_config": dict(values["reasoning_config"])}
        missing["reasoning_config"].pop("identity")
        with self.assertRaises(ValueError):
            normalize_custom_api(missing)

    def test_snapshot_drops_unrecognized_fields_and_validates_native_choices(self):
        values = settings("max")
        values["reasoning_config"].update(api_key="private-placeholder", headers={"Authorization": "private-placeholder"})
        config = summary.custom_summary_config(values)
        self.assertNotIn("private-placeholder", json.dumps(asdict(config)))
        self.assertEqual(config.reasoning_config["levels"], ["none", "low", "high", "max"])
        with self.assertRaises(ValueError):
            normalize_custom_api({**values, "thinking_level": "medium"})
        with self.assertRaises(ValueError):
            normalize_custom_api(settings("auto", kind="gemini", levels=("low", "high")))
        with self.assertRaises(ValueError):
            normalize_custom_api(settings("auto", kind="effort", protocol="gemini"))
        unknown = settings("auto", kind="unknown", levels=())
        self.assertEqual(normalize_custom_api(unknown)["thinking_level"], "auto")
        with self.assertRaises(ValueError):
            normalize_custom_api({**unknown, "thinking_level": "high"})

    def test_only_gemini_budget_shares_output_allowance(self):
        sf = settings("32768", kind="budget", levels=("none", "32768"), max_output_tokens=128)
        self.assertEqual(normalize_custom_api(sf)["thinking_level"], "32768")
        gemini = settings("1024", kind="budget", levels=("none", "1024"), protocol="gemini",
                          max_output_tokens=1024)
        with self.assertRaises(ValueError):
            normalize_custom_api(gemini)
        self.assertEqual(normalize_custom_api({**gemini, "max_output_tokens": 2048})["thinking_level"], "1024")

    def test_snapshot_retains_only_a_valid_hashed_credential_scope(self):
        values = settings("high")
        scope = capability_identity(values["url"], values["protocol"], values["model"], "private-key")
        values["reasoning_config"]["scope"] = scope
        normalized = normalize_custom_api(values)
        self.assertEqual(normalized["reasoning_config"]["scope"], scope)
        self.assertNotIn("private-key", json.dumps(normalized))
        for invalid in ("private-key", None, 42, "A" * 64):
            values["reasoning_config"]["scope"] = invalid
            with self.subTest(scope=invalid), self.assertRaises(ValueError):
                normalize_custom_api(values)

    def test_explicit_parameter_cannot_cross_protocols(self):
        values = settings("1024", kind="budget", levels=("1024",),
                          parameter="generationConfig.thinkingConfig.thinkingBudget")
        with self.assertRaises(ValueError):
            normalize_custom_api(values)
        values = settings("1024", kind="budget", levels=("1024",), protocol="gemini",
                          parameter="thinking.budget_tokens")
        with self.assertRaises(ValueError):
            normalize_custom_api(values)


class HTTPReasoningParametersTests(unittest.TestCase):
    def payload(self, config, *, mutate_gateway=None, media_assets=None):
        requests = []

        def respond(request, **_kwargs):
            requests.append(json.loads(request.data))
            response = io.BytesIO(b'{"choices":[{"message":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]}')
            response.status = 200
            return response

        with patch.object(summary, "urlopen", side_effect=respond):
            gateway = summary.create_gateway(config, api_key="placeholder")
            if mutate_gateway:
                mutate_gateway(gateway)
            self.assertEqual(gateway.generate_json("test", {"type": "object"}, media_assets=media_assets), {"ok": True})
        self.assertEqual(len(requests), 1)
        return requests[0]

    def test_auto_omits_every_reasoning_control_in_custom_and_builtin_requests(self):
        configs = [summary.custom_summary_config(settings("auto", kind=kind, levels=levels))
                   for kind, levels in (("effort", ("low", "high")), ("deepseek", ("none", "low", "high", "max")),
                                        ("budget", ("none", "1024")), ("toggle", ("none", "enabled")),
                                        ("unknown", ()), ("none", ()))]
        configs.extend((summary.SummaryConfig(provider="deepseek", model="deepseek-flash", thinking_level="auto"),
                        summary.SummaryConfig(provider="siliconflow", model="Qwen/Qwen3-8B", thinking_level="auto"),
                        summary.SummaryConfig(provider="siliconflow", model="Qwen/Qwen3.5-35B", thinking_level="auto")))
        for config in configs:
            with self.subTest(provider=config.provider, capability=config.reasoning_config):
                payload = self.payload(config)
                for field in ("reasoning_effort", "thinking", "enable_thinking", "thinking_budget"):
                    self.assertNotIn(field, payload)

    def test_effort_preserves_native_max_and_ultra_without_arbitrary_mapping(self):
        for level in ("none", "low", "max", "ultra"):
            with self.subTest(level=level):
                config = summary.custom_summary_config(settings(level, levels=("none", "low", "max", "ultra")))
                payload = self.payload(config)
                self.assertEqual(payload["reasoning_effort"], level)
                self.assertNotIn("thinking", payload)

    def test_new_model_enum_and_nested_effort_use_declared_wire_path(self):
        config = summary.custom_summary_config(settings(
            "future_extreme", levels=("eco", "future_extreme"), parameter="reasoning.effort"))
        payload = self.payload(config)
        self.assertEqual(payload["reasoning"], {"effort": "future_extreme"})
        self.assertNotIn("reasoning_effort", payload)
        config = summary.custom_summary_config(settings(
            "eco", levels=("eco", "future_extreme"), parameter="reasoning_effort"))
        self.assertEqual(self.payload(config)["reasoning_effort"], "eco")

    def test_nested_budget_and_type_switch_emit_declared_controls(self):
        for level in ("none", "2048"):
            config = summary.custom_summary_config(settings(
                level, kind="budget", levels=("none", "2048"),
                parameter="thinking.budget_tokens", budget_min=0, budget_max=8192))
            payload = self.payload(config)
            expected = {"type": "disabled"} if level == "none" else {"type": "enabled", "budget_tokens": 2048}
            self.assertEqual(payload["thinking"], expected)
            self.assertNotIn("enable_thinking", payload)
            self.assertNotIn("thinking_budget", payload)
        for level in ("none", "enabled"):
            payload = self.payload(summary.custom_summary_config(settings(
                level, kind="toggle", levels=("none", "enabled"), parameter="thinking.type")))
            self.assertEqual(payload["thinking"], {"type": "enabled" if level == "enabled" else "disabled"})

    def test_declared_top_level_budget_adds_no_undeclared_toggle(self):
        for level in ("none", "2048"):
            payload = self.payload(summary.custom_summary_config(settings(
                level, kind="budget", levels=("none", "2048"), parameter="thinking_budget",
                budget_min=0, budget_max=8192)))
            self.assertEqual(payload["thinking_budget"], 0 if level == "none" else 2048)
            self.assertNotIn("enable_thinking", payload)
            self.assertNotIn("thinking", payload)

    def test_kimi_pro_native_efforts_and_strict_json_schema_payload(self):
        for level in ("auto", "low", "high", "max"):
            with self.subTest(level=level):
                values = settings(level, url="https://api.moonshot.cn/v1", model="kimi-k3.1-pro",
                                  levels=("low", "high", "max"), json_mode="json_schema")
                payload = self.payload(summary.custom_summary_config(values))
                if level == "auto":
                    self.assertNotIn("reasoning_effort", payload)
                else:
                    self.assertEqual(payload["reasoning_effort"], level)
                self.assertNotIn("thinking", payload)
                self.assertNotIn("temperature", payload)
                self.assertEqual(payload["response_format"]["type"], "json_schema")
                self.assertIs(payload["response_format"]["json_schema"]["strict"], True)

    def test_deepseek_off_and_max_use_native_toggle_and_effort(self):
        for level in ("none", "low", "high", "max"):
            with self.subTest(level=level):
                config = summary.custom_summary_config(settings(level, kind="deepseek"))
                payload = self.payload(config)
                self.assertEqual(payload["thinking"], {"type": "disabled" if level == "none" else "enabled"})
                if level == "none":
                    self.assertNotIn("reasoning_effort", payload)
                else:
                    self.assertEqual(payload["reasoning_effort"], level)

    def test_budget_and_toggle_emit_only_their_native_parameters(self):
        for level, enabled in (("none", False), ("32768", True)):
            with self.subTest(kind="budget", level=level):
                config = summary.custom_summary_config(settings(level, kind="budget", levels=("none", "32768"),
                                                                max_output_tokens=128))
                payload = self.payload(config)
                self.assertEqual(payload["enable_thinking"], enabled)
                self.assertEqual(payload["max_tokens"], 128)
                if enabled:
                    self.assertEqual(payload["thinking_budget"], 32768)
                else:
                    self.assertNotIn("thinking_budget", payload)
                self.assertNotIn("reasoning_effort", payload)
        for level, enabled in (("none", False), ("enabled", True)):
            with self.subTest(kind="toggle", level=level):
                payload = self.payload(summary.custom_summary_config(
                    settings(level, kind="toggle", levels=("none", "enabled"))))
                self.assertEqual(payload["enable_thinking"], enabled)
                self.assertNotIn("reasoning_effort", payload)
                self.assertNotIn("thinking_budget", payload)

    def test_saved_snapshot_cannot_follow_another_model_or_endpoint(self):
        config = summary.custom_summary_config(settings("high"))
        for changed in ({"model": "other-model"}, {"api_base": "https://other.test/v1"}):
            with self.subTest(changed=changed), patch.object(summary, "urlopen") as request:
                with self.assertRaises(summary.GeminiSummaryError):
                    summary.create_gateway(replace(config, **changed), api_key="placeholder").generate_json("test", {})
                request.assert_not_called()

    def test_builtin_fallback_ignores_custom_snapshot_and_keeps_legacy_aliases(self):
        custom = summary.custom_summary_config(settings("high"))
        fallback = replace(custom, provider="deepseek", model="deepseek-flash", thinking_level="medium")
        payload = self.payload(fallback)
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        maximum = self.payload(replace(fallback, thinking_level="max"))
        self.assertEqual(maximum["reasoning_effort"], "max")

    def test_vision_request_does_not_reuse_text_model_budget(self):
        config = summary.SummaryConfig(provider="siliconflow", model="Qwen/Qwen3-8B", thinking_level="medium")
        self.assertEqual(summary._http_reasoning_parameters(config, summary.SILICONFLOW_API_BASE,
                                                           summary.SILICONFLOW_VISION_MODEL), {})

    def test_auto_vision_request_preserves_actual_model_default(self):
        asset = SimpleNamespace(local_path=SimpleNamespace(read_bytes=lambda: b"test-image"),
                                mime_type="image/png", media_id="test", label="test")
        def visual(gateway):
            gateway._doubao_visual_model = "visual-model"
        for level in ("auto", "high"):
            with self.subTest(level=level):
                config = summary.SummaryConfig(provider="siliconflow", model="Qwen/Qwen3-8B", thinking_level=level)
                payload = self.payload(config, mutate_gateway=visual, media_assets=[asset])
                self.assertEqual(payload["model"], "visual-model")
                if level == "auto":
                    for field in ("thinking", "reasoning_effort", "enable_thinking", "thinking_budget"):
                        self.assertNotIn(field, payload)
                else:
                    self.assertIs(payload["enable_thinking"], False)

    def test_legacy_custom_profiles_still_pass_existing_effort(self):
        old = dict(name="旧接口", url="https://legacy.test/v1", model="legacy-model",
                   protocol="openai", thinking_level="minimal")
        self.assertEqual(self.payload(summary.custom_summary_config(old))["reasoning_effort"], "minimal")


class GeminiReasoningParametersTests(unittest.TestCase):
    def generation_config(self, config):
        from google import genai
        calls = []

        def generate(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text='{"ok": true}')

        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        with patch.object(genai, "Client", return_value=client):
            gateway = summary.create_gateway(config, api_key="placeholder")
            self.assertEqual(gateway.generate_json("test", {}), {"ok": True})
        self.assertEqual(len(calls), 1)
        return calls[0]["config"]

    def test_native_levels_and_explicit_off_use_sdk_thinking_config(self):
        for level in ("minimal", "low", "medium", "high", "none"):
            with self.subTest(level=level):
                config = summary.custom_summary_config(settings(
                    level, kind="gemini", levels=("none", "minimal", "low", "medium", "high"),
                    protocol="gemini"))
                thinking = self.generation_config(config).thinking_config
                if level == "none":
                    self.assertEqual(thinking.thinking_budget, 0)
                    self.assertIsNone(thinking.thinking_level)
                else:
                    self.assertEqual(thinking.thinking_level.value.lower(), level)
                    self.assertIsNone(thinking.thinking_budget)

    def test_auto_omits_thinking_config_for_native_and_builtin_gemini(self):
        configs = (summary.custom_summary_config(settings("auto", kind="gemini", levels=("low", "high"), protocol="gemini")),
                   summary.SummaryConfig(thinking_level="auto"))
        for config in configs:
            with self.subTest(provider=config.provider):
                self.assertIsNone(self.generation_config(config).thinking_config)

    def test_future_enum_reaches_actual_sdk_transport_without_enum_translation(self):
        import httpx
        from google import genai
        from google.genai import types
        requests = []

        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"candidates": [{"content": {
                "role": "model", "parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}]})

        config = summary.custom_summary_config(settings(
            "future_extreme", kind="gemini", levels=("eco", "future_extreme"), protocol="gemini",
            parameter="generationConfig.thinkingConfig.thinkingLevel"))
        client = genai.Client(api_key="placeholder", http_options=types.HttpOptions(
            base_url="https://example.test/v1", httpx_client=httpx.Client(transport=httpx.MockTransport(respond))))
        try:
            with patch.object(genai, "Client", return_value=client):
                gateway = summary.create_gateway(config, api_key="placeholder")
                self.assertEqual(gateway.generate_json("test", {"type": "object"}), {"ok": True})
        finally:
            client.close()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["generationConfig"]["thinkingConfig"], {"thinkingLevel": "future_extreme"})
        self.assertEqual(requests[0]["generationConfig"]["maxOutputTokens"], config.max_output_tokens)

    def test_numeric_budget_is_native_and_connection_probe_reserves_answer_space(self):
        config = summary.custom_summary_config(settings("2048", kind="budget", levels=("none", "2048"),
                                                        protocol="gemini", max_output_tokens=4096))
        thinking = self.generation_config(config).thinking_config
        self.assertEqual(thinking.thinking_budget, 2048)
        captures = []

        def create(probe, **_kwargs):
            captures.append(probe)
            return SimpleNamespace(generate_json=lambda *_args: {"ok": True})

        with patch.object(summary, "create_gateway", side_effect=create):
            summary.test_api_connection(config, "placeholder")
        self.assertGreater(captures[0].max_output_tokens, 2048)
        self.assertLessEqual(captures[0].max_output_tokens, config.max_output_tokens)
        sf = summary.custom_summary_config(settings("32768", kind="budget", levels=("32768",)))
        with patch.object(summary, "create_gateway", side_effect=create):
            summary.test_api_connection(sf, "placeholder")
        self.assertEqual(captures[-1].max_output_tokens, 1024)


if __name__ == "__main__":
    unittest.main()
