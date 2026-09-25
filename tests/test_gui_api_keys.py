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
from gui.app import (
    AUTH_NOT_REQUIRED_LABEL,
    AUTH_REUSE_LABEL,
    AIMemoryGUI,
    GENERATE_BUTTON_LABEL,
    GENERATION_SOURCE_LABELS,
    _direct_summary_output_filename,
    _load_direct_summary_file,
)
from gui.service import (
    generate_output_bundle,
    gui_summary_attempt_configs,
    resolve_gui_summary_config,
)
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
            "deepseek": "deepseek-user-key",
        })
        self.assertEqual(store.load_api_keys(), {
            "gemini": "gemini-user-key",
            "siliconflow": "silicon-user-key",
            "deepseek": "deepseek-user-key",
        })
        store.save_provider_order(
            ("deepseek", "gemini", "siliconflow")
        )
        self.assertEqual(
            store.load_provider_order(),
            ("deepseek", "gemini", "siliconflow"),
        )
        self.assertEqual(
            list(store.load_api_keys()),
            ["deepseek", "gemini", "siliconflow"],
        )

        store.save_api_keys({
            "gemini": "replacement-key",
            "siliconflow": "",
            "deepseek": "",
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
            _refresh_generation_summary=lambda: None,
            _update_generate_button_state=lambda: updates.append(True),
        )

        AIMemoryGUI._on_url_changed(fake_gui)

        self.assertFalse(fake_gui.card_need_login.checked)
        self.assertTrue(fake_gui.card_no_login.checked)
        self.assertIn("账号内对话链接", statuses[0])
        self.assertIn("复用登录状态", statuses[0])
        self.assertEqual(updates, [True])

    def test_generation_ui_copy(self):
        self.assertEqual(GENERATION_SOURCE_LABELS, {
            "url": "当前对话",
            "file": "已选文件",
        })
        self.assertEqual(AUTH_REUSE_LABEL, "复用登录状态")
        self.assertEqual(AUTH_NOT_REQUIRED_LABEL, "本地文件无需登录")
        self.assertEqual(GENERATE_BUTTON_LABEL, "开始生成  →")

    def test_omnibox_send_opens_generation_page_for_url_or_file(self):
        for url, selected_file, expected_pages in (
            ("https://example.com/share", None, [1]),
            ("", Path("dialog.md"), [1]),
            ("https://example.com/share", Path("dialog.md"), [1]),
            ("", None, []),
        ):
            with self.subTest(url=bool(url), file=selected_file is not None):
                shown_pages = []
                fake_gui = SimpleNamespace(
                    capsule_entry=SimpleNamespace(get_text=lambda: url),
                    selected_summary_file=selected_file,
                    _show_page=shown_pages.append,
                )
                AIMemoryGUI._on_omnibox_send(fake_gui)
                self.assertEqual(shown_pages, expected_pages)

    def test_file_source_disables_raw_and_does_not_require_login(self):
        class FakeOption:
            def __init__(self, checked=False):
                self.checked = checked
                self.disabled = False
                self.manager = ""

            def set_checked(self, checked):
                self.checked = bool(checked)

            def set_disabled(self, disabled):
                self.disabled = bool(disabled)

            def winfo_manager(self):
                return self.manager

            def pack(self, **_kwargs):
                self.manager = "pack"

            def pack_forget(self):
                self.manager = ""

        auth_labels = []
        generate_states = []
        fake_gui = SimpleNamespace(
            is_running=False,
            generation_source=None,
            capsule_entry=SimpleNamespace(
                get_text=lambda: "https://example.com/share",
                set_locked=lambda _locked: None,
            ),
            selected_summary_file=Path("dialog.md"),
            card_raw=FakeOption(checked=True),
            card_normal=FakeOption(checked=True),
            card_simple=FakeOption(),
            card_detailed=FakeOption(),
            card_no_login=FakeOption(),
            card_need_login=FakeOption(),
            card_source_url=FakeOption(),
            card_source_file=FakeOption(),
            generation_auth_var=SimpleNamespace(set=auth_labels.append),
            btn_generate=SimpleNamespace(set_enabled=generate_states.append),
            file_select_button=SimpleNamespace(config=lambda **_kwargs: None),
            clear_file_button=SimpleNamespace(config=lambda **_kwargs: None),
            api_key_button=SimpleNamespace(config=lambda **_kwargs: None),
        )
        fake_gui._refresh_generation_summary = lambda: (
            AIMemoryGUI._refresh_generation_summary(fake_gui)
        )
        fake_gui._refresh_generation_sources = lambda: (
            AIMemoryGUI._refresh_generation_sources(fake_gui)
        )
        fake_gui._update_generate_button_state = lambda: (
            AIMemoryGUI._update_generate_button_state(fake_gui)
        )

        AIMemoryGUI._refresh_generation_sources(fake_gui)
        self.assertEqual(fake_gui.generation_source, "url")
        self.assertTrue(fake_gui.card_raw.checked)
        self.assertEqual(auth_labels[-1], AUTH_REUSE_LABEL)

        AIMemoryGUI._on_generation_source_toggled(
            fake_gui, fake_gui.card_source_file
        )
        self.assertEqual(fake_gui.generation_source, "file")
        self.assertFalse(fake_gui.card_raw.checked)
        self.assertTrue(fake_gui.card_raw.disabled)
        self.assertTrue(fake_gui.card_no_login.disabled)
        self.assertTrue(fake_gui.card_source_file.checked)
        self.assertEqual(auth_labels[-1], AUTH_NOT_REQUIRED_LABEL)
        self.assertEqual(generate_states[-1], True)

        AIMemoryGUI._set_inputs_locked(fake_gui, True)
        AIMemoryGUI._set_inputs_locked(fake_gui, False)
        self.assertTrue(fake_gui.card_raw.disabled)
        self.assertFalse(fake_gui.card_source_file.disabled)

        AIMemoryGUI._on_generation_source_toggled(
            fake_gui, fake_gui.card_source_url
        )
        self.assertEqual(fake_gui.generation_source, "url")
        self.assertFalse(fake_gui.card_raw.disabled)

    def test_source_options_only_show_available_sources(self):
        visible = []

        class FakeOption:
            def __init__(self, key):
                self.key = key
                self.checked = False
                self.disabled = False

            def set_checked(self, checked):
                self.checked = bool(checked)

            def set_disabled(self, disabled):
                self.disabled = bool(disabled)

            def winfo_manager(self):
                return "pack" if self.key in visible else ""

            def pack(self, **_kwargs):
                if self.key not in visible:
                    visible.append(self.key)

            def pack_forget(self):
                if self.key in visible:
                    visible.remove(self.key)

        url = {"value": ""}
        fake_gui = SimpleNamespace(
            is_running=False,
            generation_source=None,
            _generation_url_available=False,
            capsule_entry=SimpleNamespace(get_text=lambda: url["value"]),
            selected_summary_file=Path("dialog.md"),
            card_raw=FakeOption("raw"),
            card_no_login=FakeOption("no_login"),
            card_need_login=FakeOption("need_login"),
            card_source_url=FakeOption("url"),
            card_source_file=FakeOption("file"),
            _refresh_generation_summary=lambda: None,
        )

        AIMemoryGUI._refresh_generation_sources(fake_gui)
        self.assertEqual(visible, ["file"])

        url["value"] = "https://example.com/share"
        AIMemoryGUI._refresh_generation_sources(fake_gui)
        self.assertEqual(visible, ["url", "file"])

        fake_gui.selected_summary_file = None
        AIMemoryGUI._refresh_generation_sources(fake_gui)
        self.assertEqual(visible, ["url"])

        url["value"] = ""
        AIMemoryGUI._refresh_generation_sources(fake_gui)
        self.assertEqual(visible, [])

    def test_first_url_after_file_defaults_to_url_and_keeps_manual_file_choice(self):
        class FakeOption:
            def __init__(self):
                self.checked = False
                self.disabled = False
                self.manager = ""

            def set_checked(self, checked):
                self.checked = bool(checked)

            def set_disabled(self, disabled):
                self.disabled = bool(disabled)

            def winfo_manager(self):
                return self.manager

            def pack(self, **_kwargs):
                self.manager = "pack"

            def pack_forget(self):
                self.manager = ""

        url = {"value": ""}
        fake_gui = SimpleNamespace(
            is_running=False,
            generation_source=None,
            _generation_url_available=False,
            capsule_entry=SimpleNamespace(get_text=lambda: url["value"]),
            selected_summary_file=Path("dialog.md"),
            card_raw=FakeOption(),
            card_normal=FakeOption(),
            card_simple=FakeOption(),
            card_detailed=FakeOption(),
            card_no_login=FakeOption(),
            card_need_login=FakeOption(),
            card_source_url=FakeOption(),
            card_source_file=FakeOption(),
            _refresh_generation_summary=lambda: None,
            _update_generate_button_state=lambda: None,
        )
        fake_gui._refresh_generation_sources = lambda: (
            AIMemoryGUI._refresh_generation_sources(fake_gui)
        )

        AIMemoryGUI._refresh_generation_sources(fake_gui)
        self.assertEqual(fake_gui.generation_source, "file")

        url["value"] = "https://example.com/share"
        AIMemoryGUI._refresh_generation_sources(fake_gui)
        self.assertEqual(fake_gui.generation_source, "url")

        AIMemoryGUI._on_generation_source_toggled(
            fake_gui, fake_gui.card_source_file
        )
        self.assertEqual(fake_gui.generation_source, "file")
        url["value"] = "https://example.com/share/edited"
        AIMemoryGUI._refresh_generation_sources(fake_gui)
        self.assertEqual(fake_gui.generation_source, "file")
        url["value"] = ""
        AIMemoryGUI._refresh_generation_sources(fake_gui)
        url["value"] = "https://example.com/share/restored"
        AIMemoryGUI._refresh_generation_sources(fake_gui)
        self.assertEqual(fake_gui.generation_source, "file")

    def test_start_generate_uses_file_route_when_selected(self):
        direct_calls = []
        fake_gui = SimpleNamespace(
            generation_source="file",
            _on_direct_summary=lambda: direct_calls.append(True),
        )

        AIMemoryGUI._on_start_generate(fake_gui)

        self.assertEqual(direct_calls, [True])

    def test_private_url_no_login_reaches_pipeline_as_no_login(self):
        fake_gui, _opened = self._fake_gui(raw=True)
        fake_gui.capsule_entry = SimpleNamespace(
            get_text=lambda: (
                "https://chatgpt.com/c/"
                "11111111-2222-3333-4444-555555555555"
            )
        )
        fake_gui.root = object()
        fake_gui._run_generation_task = lambda *_args: None
        fake_gui._set_inputs_locked = lambda _locked: None
        fake_gui._update_generate_button_state = lambda: None
        fake_gui.done_badge = SimpleNamespace(pack_forget=lambda: None)
        fake_gui.progress_bar = SimpleNamespace(
            reset=lambda: None,
            set_progress=lambda _value: None,
        )
        fake_gui.status_var = SimpleNamespace(set=lambda _value: None)
        fake_gui.percent_var = SimpleNamespace(set=lambda _value: None)
        captured = {}

        class FakeThread:
            def __init__(self, *, target, args, daemon):
                captured["args"] = args

            def start(self):
                pass

        with patch(
            "gui.app._prompt_output_target",
            return_value=(Path("output"), "result.md"),
        ), patch("gui.app.threading.Thread", FakeThread):
            AIMemoryGUI._on_start_generate(fake_gui)

        self.assertFalse(captured["args"][1])

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

    def test_configured_provider_order_drops_missing_keys(self):
        base_config = summary.SummaryConfig(
            provider="deepseek",
            model=summary.DEEPSEEK_DEFAULT_MODEL,
        )

        def providers(keys):
            return list(dict.fromkeys(
                item.provider
                for item in gui_summary_attempt_configs(base_config, keys)
            ))

        self.assertEqual(
            providers({
                "gemini": "g",
                "siliconflow": "s",
                "deepseek": "d",
            }),
            ["gemini", "siliconflow", "deepseek"],
        )
        self.assertEqual(
            providers({"gemini": "g", "deepseek": "d"}),
            ["gemini", "deepseek"],
        )
        self.assertEqual(
            providers({"siliconflow": "s", "deepseek": "d"}),
            ["siliconflow", "deepseek"],
        )
        self.assertEqual(providers({"deepseek": "d"}), ["deepseek"])
        self.assertEqual(
            providers({
                "deepseek": "d",
                "gemini": "g",
                "siliconflow": "s",
            }),
            ["deepseek", "gemini", "siliconflow"],
        )

    def test_output_generation_keeps_custom_provider_order(self):
        base_config = summary.SummaryConfig(
            provider="gemini",
            model="gemini-3.5-flash",
        )
        created = []

        def fake_create_gateway(config, api_key=None):
            created.append((config.provider, config.model, api_key))
            return object()

        with tempfile.TemporaryDirectory() as temp_dir, patch(
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
                api_keys={
                    "deepseek": "deepseek-user-key",
                    "gemini": "gemini-user-key",
                },
            )

        self.assertEqual(
            created,
            [(
                "deepseek",
                summary.DEEPSEEK_DEFAULT_MODEL,
                "deepseek-user-key",
            )],
        )

    def test_gemini_timeout_switches_to_configured_siliconflow_key(self):
        base_config = summary.SummaryConfig(
            provider="gemini",
            model="gemini-3.5-flash",
            request_timeout_seconds=180,
        )
        keys = {
            "gemini": "stored-gemini-user-key",
            "siliconflow": "stored-silicon-user-key",
        }
        created = []
        attempts = []
        progress = []

        def fake_create_gateway(config, api_key=None):
            created.append((config.provider, config.model, api_key))
            return object()

        def fake_summarize(**kwargs):
            provider = kwargs["config"].provider
            attempts.append((provider, kwargs["config"].model))
            if provider == "gemini":
                raise summary.SummaryRequestTimeoutError(
                    f"模拟超时：{keys['gemini']}"
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
                api_keys=keys,
                progress=progress.append,
            )

        self.assertEqual(
            [provider for provider, _model in attempts],
            ["gemini", "siliconflow"],
        )
        self.assertEqual(
            created[1],
            (
                "siliconflow",
                summary.SILICONFLOW_DEFAULT_MODEL,
                keys["siliconflow"],
            ),
        )
        progress_text = "\n".join(progress)
        self.assertIn("正在切换到 siliconflow", progress_text)
        self.assertNotIn(keys["gemini"], progress_text)
        self.assertNotIn(keys["siliconflow"], progress_text)

    def test_generation_lock_keeps_input_draft_editable(self):
        locked_values = []
        disabled_values = []
        button_configs = []
        file_button_configs = []

        fake_gui = SimpleNamespace(
            capsule_entry=SimpleNamespace(
                set_locked=locked_values.append
            ),
            card_raw=SimpleNamespace(set_disabled=disabled_values.append),
            card_normal=SimpleNamespace(set_disabled=disabled_values.append),
            card_simple=SimpleNamespace(set_disabled=disabled_values.append),
            card_detailed=SimpleNamespace(set_disabled=disabled_values.append),
            card_no_login=SimpleNamespace(set_disabled=disabled_values.append),
            card_need_login=SimpleNamespace(set_disabled=disabled_values.append),
            file_select_button=SimpleNamespace(
                config=lambda **kwargs: file_button_configs.append(kwargs)
            ),
            clear_file_button=SimpleNamespace(
                config=lambda **kwargs: file_button_configs.append(kwargs)
            ),
            api_key_button=SimpleNamespace(config=lambda **kwargs: button_configs.append(kwargs)),
        )

        AIMemoryGUI._set_inputs_locked(fake_gui, True)

        self.assertEqual(locked_values, [])
        self.assertEqual(disabled_values, [True] * 6)
        self.assertEqual(file_button_configs, [])
        self.assertEqual(
            button_configs,
            [{"state": "normal", "cursor": "hand2"}],
        )

    def test_running_task_keeps_url_edits_out_of_progress_status(self):
        updates = []
        statuses = []
        fake_gui = SimpleNamespace(
            is_running=True,
            capsule_entry=SimpleNamespace(get_text=lambda: "https://example.com/next"),
            _update_send_button_state=lambda: updates.append("send"),
            status_var=SimpleNamespace(set=statuses.append),
            _refresh_generation_sources=lambda: updates.append("sources"),
            _refresh_generation_summary=lambda: updates.append("summary"),
            _update_generate_button_state=lambda: updates.append("generation"),
        )

        AIMemoryGUI._on_url_changed(fake_gui)
        AIMemoryGUI._refresh_generation_sources(fake_gui)

        self.assertEqual(updates, ["send"])
        self.assertEqual(statuses, [])

    def test_start_captures_url_and_modes_and_ignores_duplicate_start(self):
        url = ["https://example.com/start"]
        fake_gui, _opened = self._fake_gui(raw=True)
        fake_gui.capsule_entry = SimpleNamespace(get_text=lambda: url[0])
        fake_gui.root = object()
        fake_gui._run_generation_task = lambda *_args: None
        fake_gui._set_inputs_locked = lambda _locked: None
        fake_gui._update_generate_button_state = lambda: None
        fake_gui.done_badge = SimpleNamespace(pack_forget=lambda: None)
        fake_gui.progress_bar = SimpleNamespace(
            reset=lambda: None, set_progress=lambda _value: None,
        )
        fake_gui.status_var = SimpleNamespace(set=lambda _value: None)
        fake_gui.percent_var = SimpleNamespace(set=lambda _value: None)
        captured = {}

        class FakeThread:
            def __init__(self, *, target, args, daemon):
                captured["args"] = args

            def start(self):
                captured["started"] = True

        with patch(
            "gui.app._prompt_output_target",
            return_value=(Path("output"), "result.md"),
        ) as prompt, patch("gui.app.threading.Thread", FakeThread):
            AIMemoryGUI._on_start_generate(fake_gui)
            url[0] = "https://example.com/edited"
            fake_gui.card_raw.checked = False
            AIMemoryGUI._on_start_generate(fake_gui)

        self.assertEqual(captured["args"][0], "https://example.com/start")
        self.assertEqual(captured["args"][2], {
            "raw": True, "normal": False, "simple": False, "detailed": False,
        })
        self.assertTrue(captured["started"])
        prompt.assert_called_once()

    def test_direct_summary_uses_file_modes_and_ignores_raw_and_login(self):
        captured = {}

        class KeyStore:
            @staticmethod
            def load_api_keys():
                return {"gemini": "user-key"}

        class FakeThread:
            def __init__(self, *, target, args, daemon):
                captured["target"] = target
                captured["args"] = args

            def start(self):
                captured["started"] = True

        class FakeRoot:
            @staticmethod
            def after(_delay, callback):
                callback()

        def fake_generate_output_bundle(**kwargs):
            captured["worker_messages"] = kwargs["messages"]
            captured["worker_source_name"] = kwargs["source_name"]
            captured["worker_source_dir"] = kwargs["source_dir"]
            output_path = Path(kwargs["save_dir"]) / kwargs["output_filename"]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "\n".join(message["content"] for message in kwargs["messages"]),
                encoding="utf-8",
            )
            captured["output_path"] = output_path
            captured["output_content"] = output_path.read_text(encoding="utf-8")
            return SimpleNamespace(saved_files=[output_path], summary_result=None)

        with tempfile.TemporaryDirectory() as temp:
            source_path = Path(temp) / "原始对话.md"
            source_path.write_text(
                "## 🔵 👤 用户提问\n\n原始问题内容\n\n"
                "## 🟣 🤖 AI 回答\n\n原始回答内容\n",
                encoding="utf-8",
            )
            replacement_path = Path(temp) / "运行中替换.md"
            replacement_path.write_text(
                "## 🔵 👤 用户提问\n\n替换文件内容\n",
                encoding="utf-8",
            )
            fake_gui = SimpleNamespace(
                selected_summary_file=source_path,
                is_running=False,
                card_raw=SimpleNamespace(checked=True),
                card_normal=SimpleNamespace(checked=True),
                card_simple=SimpleNamespace(checked=False),
                card_detailed=SimpleNamespace(checked=False),
                card_need_login=SimpleNamespace(checked=True),
                credential_store=KeyStore(),
                app_settings=SimpleNamespace(
                    runtime_data_dir=Path(temp) / "runtime",
                    default_results_dir=Path(temp) / "results",
                ),
                root=FakeRoot(),
                selected_file_name_var=SimpleNamespace(set=lambda _value: None),
                selected_file_row=SimpleNamespace(pack=lambda **_kwargs: None),
                file_select_button=SimpleNamespace(config=lambda **_kwargs: None),
                capsule_entry=object(),
                done_badge=SimpleNamespace(pack_forget=lambda: None),
                _set_inputs_locked=lambda _locked: None,
                _update_generate_button_state=lambda: None,
                _update_send_button_state=lambda: None,
                _refresh_generation_sources=lambda: None,
                progress_bar=SimpleNamespace(
                    reset=lambda: None,
                    set_progress=lambda _value: None,
                ),
                status_var=SimpleNamespace(set=lambda _value: None),
                percent_var=SimpleNamespace(set=lambda _value: None),
                _run_generation_task=lambda *args: AIMemoryGUI._run_generation_task(
                    fake_gui, *args,
                ),
                _show_completed_badge=lambda _duration: None,
                _add_history_record=lambda record: captured.setdefault(
                    "history", [],
                ).append(record),
                _on_task_finished=lambda: None,
            )

            with patch(
                "gui.app._prompt_output_target",
                return_value=(Path(temp), "原始对话_summary.md"),
            ) as prompt, patch("gui.app.threading.Thread", FakeThread), patch(
                "gui.app.generate_output_bundle",
                side_effect=fake_generate_output_bundle,
            ):
                AIMemoryGUI._on_direct_summary(fake_gui)
                AIMemoryGUI._select_summary_file(
                    fake_gui, replacement_path,
                )
                captured["target"](*captured["args"])

        args = captured["args"]
        self.assertEqual(args[0:2], ("", False))
        self.assertEqual(
            args[2],
            {"raw": False, "normal": True, "simple": False, "detailed": False},
        )
        self.assertEqual(args[-1], source_path.resolve())
        self.assertEqual(
            fake_gui.selected_summary_file,
            replacement_path.resolve(),
        )
        self.assertEqual(captured["worker_source_name"], source_path.name)
        self.assertEqual(captured["worker_source_dir"], source_path.parent)
        self.assertEqual(
            [message["content"] for message in captured["worker_messages"]],
            ["原始问题内容", "原始回答内容"],
        )
        output_path = Path(temp) / "原始对话_summary.md"
        self.assertEqual(captured["output_path"], output_path)
        self.assertEqual(
            captured["output_content"],
            "原始问题内容\n原始回答内容",
        )
        self.assertNotIn("替换文件内容", captured["output_content"])
        self.assertEqual(captured["history"][0]["saved_files"], [output_path.name])
        self.assertEqual(captured["history"][0]["title"], source_path.name)
        self.assertTrue(captured["started"])
        self.assertEqual(
            prompt.call_args.kwargs["suggested_name"],
            "原始对话_summary.md",
        )

    def test_direct_file_validation_and_default_names(self):
        with tempfile.TemporaryDirectory() as temp:
            source_path = Path(temp) / "课程对话.txt"
            source_path.write_text(
                "## 🔵 👤 用户提问\n\n问题\n\n"
                "## 🟣 🤖 AI 回答\n\n回答\n",
                encoding="utf-8",
            )
            messages = _load_direct_summary_file(source_path)
            self.assertEqual([item["role"] for item in messages], ["User", "AI"])
            self.assertEqual(
                _direct_summary_output_filename(
                    source_path, {"simple": True}
                ),
                "课程对话_simple.md",
            )
            self.assertEqual(
                _direct_summary_output_filename(
                    source_path, {"normal": True, "detailed": True}
                ),
                "课程对话.md",
            )

            unsupported = Path(temp) / "课程对话.pdf"
            unsupported.write_text("text", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "仅支持"):
                _load_direct_summary_file(unsupported)

    def test_dropped_file_is_selected(self):
        with tempfile.TemporaryDirectory() as temp:
            source_path = Path(temp) / "拖入对话.md"
            source_path.write_text(
                "## 🔵 👤 用户提问\n\n问题\n\n"
                "## 🟣 🤖 AI 回答\n\n回答\n",
                encoding="utf-8",
            )
            selected_names = []
            shown_rows = []
            button_styles = []
            file_button_configs = []
            capsule_entry = object()
            fake_gui = SimpleNamespace(
                is_running=False,
                root=SimpleNamespace(
                    tk=SimpleNamespace(splitlist=lambda _data: (str(source_path),))
                ),
                selected_summary_file=None,
                selected_file_name_var=SimpleNamespace(set=selected_names.append),
                selected_file_row=SimpleNamespace(
                    pack=lambda **kwargs: shown_rows.append(kwargs)
                ),
                capsule_entry=capsule_entry,
                file_select_button=SimpleNamespace(
                    config=lambda **kwargs: file_button_configs.append(kwargs)
                ),
                _omnibox=SimpleNamespace(
                    config=lambda **kwargs: button_styles.append(kwargs),
                    winfo_children=lambda: [],
                ),
                _refresh_generation_sources=lambda: None,
                _update_send_button_state=lambda: None,
                _update_generate_button_state=lambda: None,
                _select_summary_file=lambda path: AIMemoryGUI._select_summary_file(
                    fake_gui, path
                ),
                _set_file_drop_highlight=lambda value: (
                    AIMemoryGUI._set_file_drop_highlight(fake_gui, value)
                ),
            )

            AIMemoryGUI._on_file_drag_enter(
                fake_gui,
                SimpleNamespace(action="copy"),
            )
            self.assertEqual(button_styles[-1]["bg"], "#EFF6FF")

            action = AIMemoryGUI._on_file_drop(
                fake_gui,
                SimpleNamespace(data="ignored", action="copy"),
            )

            self.assertEqual(action, "copy")
            self.assertEqual(fake_gui.selected_summary_file, source_path.resolve())
            self.assertTrue(selected_names[0].startswith("📄 " + source_path.name + " ·"))
            self.assertEqual(shown_rows[0]["fill"], "x")
            self.assertEqual(shown_rows[0]["pady"], (0, 8))
            self.assertIs(shown_rows[0]["before"], capsule_entry)
            self.assertEqual(file_button_configs, [{"text": "📎 重新添加"}])
            self.assertEqual(button_styles[-1]["bg"], "#F0F4F9")

    def test_cancelled_file_picker_keeps_current_attachment(self):
        selected_file = Path("current.md")
        selections = []
        fake_gui = SimpleNamespace(
            root=object(),
            selected_summary_file=selected_file,
            _select_summary_file=selections.append,
        )

        with patch("gui.app.filedialog.askopenfilename", return_value=""):
            AIMemoryGUI._choose_summary_file(fake_gui)

        self.assertEqual(fake_gui.selected_summary_file, selected_file)
        self.assertEqual(selections, [])

    def test_clear_file_resets_add_button(self):
        button_configs = []
        hidden_rows = []
        fake_gui = SimpleNamespace(
            selected_summary_file=Path("current.md"),
            selected_file_name_var=SimpleNamespace(set=lambda _value: None),
            selected_file_row=SimpleNamespace(pack_forget=lambda: hidden_rows.append(True)),
            file_select_button=SimpleNamespace(
                config=lambda **kwargs: button_configs.append(kwargs)
            ),
            _refresh_generation_sources=lambda: None,
            _update_send_button_state=lambda: None,
            _update_generate_button_state=lambda: None,
        )

        AIMemoryGUI._clear_summary_file(fake_gui)

        self.assertIsNone(fake_gui.selected_summary_file)
        self.assertEqual(button_configs, [{"text": "📎 添加文件"}])
        self.assertEqual(hidden_rows, [True])

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

