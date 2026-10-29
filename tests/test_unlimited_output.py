"""Unlimited summary output omits wire limits while connection tests stay bounded."""

from dataclasses import replace
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import gemini_summarizer as summary
from scripts.api_config import normalize_custom_api
from scripts.reasoning_capabilities import ReasoningCapability, capability_identity


def config(protocol="openai", limit=None):
    return summary.SummaryConfig(
        provider="custom", model="unseen-model", api_base="https://example.test/v1",
        api_protocol=protocol, thinking_level="auto", max_output_tokens=limit, retries=1,
    )


def with_budget(settings, budget=2048):
    capability = ReasoningCapability("budget", (str(budget),), "manual")
    return replace(settings, thinking_level=str(budget), reasoning_config={
        **capability.to_dict(),
        "identity": capability_identity(settings.api_base, settings.api_protocol, settings.model),
        "override": True,
    })


class UnlimitedOutputTests(unittest.TestCase):
    def http_payload(self, settings, *, finish_reason="stop", prepare=None):
        captured = []

        def respond(request, **_kwargs):
            captured.append(json.loads(request.data))
            response = io.BytesIO(json.dumps({"choices": [{
                "message": {"content": '{"ok": true}'}, "finish_reason": finish_reason,
            }]}).encode())
            response.status = 200
            return response

        with patch.object(summary, "urlopen", side_effect=respond):
            gateway = summary.create_gateway(settings, api_key="placeholder")
            if prepare is not None:
                prepare(gateway)
            gateway.generate_json("test", {"type": "object"})
        self.assertEqual(len(captured), 1)
        return captured[0]

    def gemini_payload(self, settings):
        import httpx
        from google import genai
        from google.genai import types
        captured = []

        def respond(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"candidates": [{"content": {
                "role": "model", "parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}]})

        client = genai.Client(api_key="placeholder", http_options=types.HttpOptions(
            base_url=settings.api_base, httpx_client=httpx.Client(transport=httpx.MockTransport(respond))))
        try:
            with patch.object(genai, "Client", return_value=client):
                gateway = summary.create_gateway(settings, api_key="placeholder")
                self.assertEqual(gateway.generate_json("test", {"type": "object"}), {"ok": True})
        finally:
            client.close()
        self.assertEqual(len(captured), 1)
        return captured[0]

    def test_normalized_unlimited_aliases_roundtrip_as_null(self):
        values = dict(name="test", url="https://example.test/v1", model="unseen-model")
        for value in (None, "无限制", "unlimited"):
            with self.subTest(value=value):
                normalized = normalize_custom_api({**values, "max_output_tokens": value})
                self.assertIsNone(normalized["max_output_tokens"])
                self.assertIsNone(normalize_custom_api(json.loads(json.dumps(normalized)))["max_output_tokens"])
                self.assertIsNone(summary.custom_summary_config(normalized).max_output_tokens)

    def test_openai_unlimited_omits_both_output_limit_fields_in_each_json_mode(self):
        for mode in ("prompt", "json_object", "json_schema"):
            with self.subTest(mode=mode):
                payload = self.http_payload(replace(config(), json_mode=mode))
                self.assertNotIn("max_tokens", payload)
                self.assertNotIn("max_completion_tokens", payload)
                self.assertNotIn("max_output_tokens", payload)

    def test_openai_explicit_limit_stays_on_wire(self):
        self.assertEqual(self.http_payload(config(limit=8192))["max_tokens"], 8192)

    def test_gemini_sdk_omits_unlimited_and_preserves_explicit_output_limit(self):
        payload = self.gemini_payload(config("gemini"))
        self.assertNotIn("maxOutputTokens", payload["generationConfig"])
        self.assertNotIn("max_output_tokens", payload["generationConfig"])
        payload = self.gemini_payload(config("gemini", 8192))
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 8192)

    def test_gemini_thinking_budget_is_independent_of_unlimited_output(self):
        payload = self.gemini_payload(with_budget(config("gemini")))
        thinking = payload["generationConfig"]["thinkingConfig"]
        self.assertEqual(thinking.get("thinkingBudget", thinking.get("thinking_budget")), 2048)
        self.assertNotIn("maxOutputTokens", payload["generationConfig"])

    def test_connection_tests_keep_short_limits_for_unlimited_and_numeric_configs(self):
        captured = []

        def create(settings, **_kwargs):
            captured.append(settings)
            return SimpleNamespace(generate_json=lambda *_args: {"ok": True})

        with patch.object(summary, "create_gateway", side_effect=create):
            for protocol in ("openai", "gemini"):
                for limit, expected in ((None, 1024), (16384, 1024), (512, 512)):
                    summary.test_api_connection(config(protocol, limit), "placeholder")
                    self.assertEqual(captured[-1].max_output_tokens, expected)
            summary.test_api_connection(with_budget(config("gemini")), "placeholder")
            self.assertEqual(captured[-1].max_output_tokens, 2176)

    def test_unlimited_truncation_reports_server_limit_and_remains_a_failure(self):
        with self.assertRaises(summary.SummaryOutputTruncatedError) as raised:
            self.http_payload(config(), finish_reason="length")
        self.assertIn("服务端或模型", str(raised.exception))
        self.assertNotIn("请提高输出上限", str(raised.exception))

    def test_unlimited_internal_doubao_truncation_does_not_index_a_missing_limit(self):
        settings = replace(config(), provider="deepseek", model="deepseek-flash")
        with self.assertRaises(summary.SummaryOutputTruncatedError) as raised:
            self.http_payload(settings, finish_reason="length",
                              prepare=lambda gateway: setattr(gateway, "_doubao_output_limit", 16384))
        self.assertIn("服务端或模型", str(raised.exception))

    def test_legacy_budget_aliases_have_a_default_without_setting_output_limit(self):
        for settings in (
            replace(config(), provider="siliconflow", model="Qwen/Qwen3-8B", thinking_level="medium"),
            replace(config(), provider="siliconflow", model="Qwen/Qwen3.5-35B", thinking_level="medium"),
        ):
            with self.subTest(model=settings.model):
                parameters = summary._http_reasoning_parameters(settings, summary.SILICONFLOW_API_BASE, settings.model)
                self.assertGreater(parameters["thinking_budget"], 0)


if __name__ == "__main__":
    unittest.main()
