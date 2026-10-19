import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from scripts import gemini_summarizer as summary


class DeepSeekGatewayTests(unittest.TestCase):
    def test_default_config_uses_public_deepseek_model(self):
        with patch.dict(summary.os.environ, {}, clear=True):
            config = summary.SummaryConfig.from_env(provider_override="deepseek")
        self.assertEqual(config.model, "deepseek-flash")

    def gateway(self, retries=3):
        self.sleeps = []
        return summary.SiliconFlowGateway(
            summary.SummaryConfig(provider="deepseek", model=summary.DEEPSEEK_DEFAULT_MODEL,
                                  retries=retries),
            api_key="user-secret-key", sleep=self.sleeps.append,
        )

    def http_error(self, code, message):
        return HTTPError("https://api.deepseek.com/chat/completions", code,
                         "Rejected", {}, io.BytesIO(json.dumps({
                             "error": {"message": message}
                         }).encode()))

    def test_bad_request_shows_server_reason_without_retry_or_secret(self):
        gateway = self.gateway()
        error = self.http_error(400, "Invalid model; key=user-secret-key")
        with patch.object(summary, "urlopen", side_effect=error) as request:
            with self.assertRaises(summary.GeminiSummaryError) as raised:
                gateway.generate_json("测试", {"type": "object"})
        message = str(raised.exception)
        self.assertIn("Invalid model", message)
        self.assertIn("code=400", message)
        self.assertIn("尝试 1 次", message)
        self.assertNotIn("user-secret-key", message)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_permanent_errors_have_specific_guidance(self):
        for code, guidance in [(401, "API KEY 无效"), (402, "余额不足"),
                               (403, "账户权限"), (404, "接口不存在"),
                               (422, "格式或参数")]:
            with self.subTest(code=code):
                gateway = self.gateway()
                with patch.object(summary, "urlopen", side_effect=self.http_error(code, "")) as request:
                    with self.assertRaisesRegex(summary.GeminiSummaryError, guidance):
                        gateway.generate_json("测试", {})
                self.assertEqual(request.call_count, 1)

    def test_html_error_body_does_not_hide_http_status(self):
        error = HTTPError("https://api.deepseek.com", 400, "Bad Request", {},
                          io.BytesIO(b"<html>proxy error</html>"))
        with patch.object(summary, "urlopen", side_effect=error):
            with self.assertRaises(summary.GeminiSummaryError) as raised:
                self.gateway().generate_json("测试", {})
        self.assertIn("code=400", str(raised.exception))
        self.assertNotIn("<html>", str(raised.exception))

    def test_transient_errors_still_retry(self):
        for code in (429, 500, 503):
            with self.subTest(code=code):
                gateway = self.gateway()
                errors = [self.http_error(code, "temporary") for _ in range(3)]
                with patch.object(summary, "urlopen", side_effect=errors) as request:
                    with self.assertRaises(summary.GeminiSummaryError):
                        gateway.generate_json("测试", {})
                self.assertEqual(request.call_count, 3)
                self.assertEqual(len(self.sleeps), 2)

    def test_thinking_levels_use_documented_effort_values(self):
        for level, effort in [("minimal", "low"), ("low", "low"),
                              ("medium", "high"), ("high", "high")]:
            with self.subTest(level=level):
                gateway = self.gateway(retries=1)
                gateway.config = summary.replace(gateway.config, thinking_level=level)
                response = MagicMock()
                response.__enter__.return_value.read.return_value = json.dumps({
                    "choices": [{"message": {"content": "{\"ok\": true}"}}]
                }).encode()
                with patch.object(summary, "urlopen", return_value=response) as request:
                    self.assertEqual(gateway.generate_json("测试", {}), {"ok": True})
                payload = json.loads(request.call_args.args[0].data)
                self.assertEqual(payload["model"], "deepseek-flash")
                self.assertEqual(payload["reasoning_effort"], effort)


if __name__ == "__main__":
    unittest.main()
