"""GUI API KEY 路由与安全存储测试。"""

import os
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from gui.credential_store import (
    CredentialStoreError,
    WindowsCredentialStore,
)
from gui.app import AIMemoryGUI
from gui.service import generate_output_bundle, resolve_gui_summary_config
from scripts import gemini_summarizer as summary


class FakeCredentialBackend:
    def __init__(self):
        self.passwords = {}

    def get_password(self, service, account):
        return self.passwords.get((service, account))

    def set_password(self, service, account, password):
        self.passwords[(service, account)] = password

    def delete_password(self, service, account):
        self.passwords.pop((service, account), None)


class CredentialStoreTests(unittest.TestCase):
    def test_keys_round_trip_without_plaintext_file_storage(self):
        backend = FakeCredentialBackend()
        store = WindowsCredentialStore(backend=backend)

        store.save_api_keys({
            "gemini": "  gemini-user-key  ",
            "siliconflow": "silicon-user-key",
        })
        self.assertEqual(store.load_api_keys(), {
            "gemini": "gemini-user-key",
            "siliconflow": "silicon-user-key",
        })

        store.save_api_keys({
            "gemini": "replacement-key",
            "siliconflow": "",
        })
        self.assertEqual(store.load_api_keys(), {
            "gemini": "replacement-key",
        })

    def test_backend_error_never_exposes_secret(self):
        secret = "credential-that-must-not-leak"

        class BrokenBackend(FakeCredentialBackend):
            def set_password(self, _service, _account, password):
                raise RuntimeError(f"failed with {password}")

        store = WindowsCredentialStore(backend=BrokenBackend())
        with self.assertRaises(CredentialStoreError) as raised:
            store.save_api_keys({"gemini": secret})

        self.assertNotIn(secret, str(raised.exception))


class GUIApiKeyRoutingTests(unittest.TestCase):
    @staticmethod
    def _fake_gui(*, raw=False, normal=False, simple=False, detailed=False):
        opened = []
        fake_gui = SimpleNamespace(
            capsule_entry=SimpleNamespace(
                get_text=lambda: "https://example.com/share"
            ),
            card_need_login=SimpleNamespace(checked=False),
            card_raw=SimpleNamespace(checked=raw),
            card_normal=SimpleNamespace(checked=normal),
            card_simple=SimpleNamespace(checked=simple),
            card_detailed=SimpleNamespace(checked=detailed),
            _show_api_key_settings=lambda require_key=False: opened.append(
                require_key
            ),
        )
        return fake_gui, opened

    def test_private_url_change_preserves_login_card_selection(self):
        class FakeCard:
            def __init__(self, checked):
                self.checked = checked

            def set_checked(self, value):
                self.checked = bool(value)

        statuses = []
        updates = []
        fake_gui = SimpleNamespace(
            capsule_entry=SimpleNamespace(
                get_text=lambda: (
                    "https://chatgpt.com/c/"
                    "11111111-2222-3333-4444-555555555555"
                )
            ),
            card_need_login=FakeCard(False),
            card_no_login=FakeCard(True),
            status_var=SimpleNamespace(set=statuses.append),
            _update_generate_button_state=lambda: updates.append(True),
        )

        AIMemoryGUI._on_url_changed(fake_gui)

        self.assertFalse(fake_gui.card_need_login.checked)
        self.assertTrue(fake_gui.card_no_login.checked)
        self.assertIn("账号内对话链接", statuses[0])
        self.assertIn("复用已保存", statuses[0])
        self.assertEqual(updates, [True])
    def test_start_summary_without_key_opens_settings_before_save_dialog(self):
        class EmptyStore:
            @staticmethod
            def load_api_keys():
                return {}

        fake_gui, opened = self._fake_gui(normal=True)
        fake_gui.credential_store = EmptyStore()
        with patch(
            "gui.app.filedialog.asksaveasfilename"
        ) as save_dialog:
            AIMemoryGUI._on_start_generate(fake_gui)

        self.assertEqual(opened, [True])
        save_dialog.assert_not_called()

    def test_start_raw_does_not_touch_credential_store(self):
        class ForbiddenStore:
            @staticmethod
            def load_api_keys():
                raise AssertionError("raw 模式不应读取 API KEY")

        fake_gui, opened = self._fake_gui(raw=True)
        fake_gui.credential_store = ForbiddenStore()
        with patch(
            "gui.app.filedialog.asksaveasfilename",
            return_value="",
        ) as save_dialog:
            AIMemoryGUI._on_start_generate(fake_gui)

        self.assertEqual(opened, [])
        save_dialog.assert_called_once()

    @staticmethod
    def _write_success(**kwargs):
        kwargs["output_json"].write_text("{}", encoding="utf-8")
        kwargs["output_markdown"].write_text("summary", encoding="utf-8")
        return {"typed_records": {}, "topics": []}

    def test_only_silicon_key_selects_silicon_directly_and_keeps_fallback(self):
        base_config = summary.SummaryConfig(
            provider="gemini",
            model="gemini-3.5-flash",
        )
        user_key = "stored-silicon-user-key"
        created = []
        attempts = []
        progress = []

        def fake_create_gateway(config, api_key=None):
            created.append((config.provider, config.model, api_key))
            return config.model

        def fake_summarize(**kwargs):
            attempts.append((kwargs["config"].provider, kwargs["config"].model))
            if len(attempts) == 1:
                raise summary.GeminiSummaryError(
                    f"模拟额度限制：{user_key}"
                )
            return self._write_success(**kwargs)

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "scripts.gemini_summarizer.SummaryConfig.from_env",
            return_value=base_config,
        ), patch(
            "scripts.gemini_summarizer.create_gateway",
            side_effect=fake_create_gateway,
        ), patch(
            "scripts.gemini_summarizer.summarize_conversation",
            side_effect=fake_summarize,
        ):
            generate_output_bundle(
                messages=[
                    {"role": "User", "content": "测试"},
                    {"role": "AI", "content": "回答"},
                ],
                modes={"normal": True},
                save_dir=Path(temp_dir),
                api_keys={"siliconflow": user_key},
                progress=progress.append,
            )

        self.assertEqual(
            [provider for provider, _model in attempts],
            ["siliconflow", "siliconflow"],
        )
        self.assertEqual(
            [model for _provider, model in attempts],
            [
                summary.SILICONFLOW_DEFAULT_MODEL,
                "Qwen/Qwen3-8B",
            ],
        )
        self.assertTrue(all(key == user_key for _p, _m, key in created))
        self.assertNotIn(user_key, "\n".join(progress))
        self.assertIn("<redacted>", "\n".join(progress))

    def test_user_gemini_key_overrides_environment_key(self):
        base_config = summary.SummaryConfig(
            provider="gemini",
            model="gemini-3.5-flash",
        )
        created_keys = []

        def fake_create_gateway(_config, api_key=None):
            created_keys.append(api_key)
            return object()

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "developer-environment-key"},
            clear=False,
        ), patch(
            "scripts.gemini_summarizer.SummaryConfig.from_env",
            return_value=base_config,
        ), patch(
            "scripts.gemini_summarizer.create_gateway",
            side_effect=fake_create_gateway,
        ), patch(
            "scripts.gemini_summarizer.summarize_conversation",
            side_effect=self._write_success,
        ):
            generate_output_bundle(
                messages=[
                    {"role": "User", "content": "测试"},
                    {"role": "AI", "content": "回答"},
                ],
                modes={"normal": True},
                save_dir=Path(temp_dir),
                api_keys={"gemini": "user-gemini-key"},
            )

        self.assertEqual(created_keys, ["user-gemini-key"])

    def test_raw_mode_never_requires_or_reads_an_api_key(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "scripts.gemini_summarizer.SummaryConfig.from_env",
            side_effect=AssertionError("raw 模式不应读取 API 配置"),
        ):
            bundle = generate_output_bundle(
                messages=[{"role": "User", "content": "只抓取"}],
                modes={"raw": True},
                save_dir=Path(temp_dir),
                api_keys={},
            )

        self.assertEqual(len(bundle.saved_files), 1)

    def test_empty_gui_keys_reject_summary(self):
        base_config = summary.SummaryConfig()
        with self.assertRaisesRegex(summary.GeminiSummaryError, "请先配置"):
            resolve_gui_summary_config(base_config, {})

    def test_explicit_secret_is_redacted_without_environment_variable(self):
        secret = "user-provided-secret-value"
        message = summary.safe_error_message(
            summary.GeminiSummaryError(f"失败：{secret}"),
            (secret,),
        )
        self.assertNotIn(secret, message)
        self.assertIn("<redacted>", message)


if __name__ == "__main__":
    unittest.main()

