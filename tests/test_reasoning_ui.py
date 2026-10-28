"""Per-model discovery, automatic mode and manual overrides in the actual editor."""

import queue
import threading
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gui.custom_api_dialog import CustomAPIEditor
from scripts.reasoning_capabilities import ReasoningCapability, capability_identity


class ReasoningEditorTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0)
        self.root.geometry("740x820")
        self.callbacks = queue.Queue()
        self.saved = []
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.root.tk.call("set", "::reasoning_ui_errors", "")
        self.root.tk.call("proc", "bgerror", "message", "lappend ::reasoning_ui_errors $message")
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.root.destroy()
        self.root.tk.call("update")
        self.assertEqual(tuple(self.root.tk.splitlist(self.root.tk.call("set", "::reasoning_ui_errors"))), ())
        self.assertEqual(self.errors, [])

    def editor(self, values=None, key=""):
        values = values or dict(url="https://unknown.test/v1", model="unknown-model")
        editor = CustomAPIEditor(self.root, values, key, self.callbacks.put, lambda *args: self.saved.append(args))
        editor.pack(fill=tk.BOTH, expand=True)
        editor.advanced_button.invoke()
        self.root.update()
        return editor

    def test_unknown_is_auto_highlighted_and_slider_cannot_change(self):
        editor = self.editor()
        slider = editor.entries["thinking_level"]
        self.assertTrue(editor.reasoning_auto_button.selected)
        self.assertEqual(slider.values, ())
        self.assertEqual(slider.cget("state"), "disabled")
        slider.event_generate("<ButtonPress-1>", x=40, y=10)
        slider.focus_force()
        self.root.update()
        slider.event_generate("<End>")
        self.assertEqual(slider.get(), "auto")

    def test_known_models_have_native_levels_and_auto_omits_override(self):
        editor = self.editor(dict(url="https://api.deepseek.com", model="deepseek-flash"))
        slider = editor.entries["thinking_level"]
        self.assertEqual(slider.values, ("none", "low", "high", "max"))
        self.assertEqual(slider.cget("state"), "normal")
        slider._select(3)
        self.assertEqual(editor._reasoning_status.get(), "最高")
        self.assertFalse(editor.reasoning_auto_button.selected)
        editor.reasoning_auto_button.invoke()
        self.assertTrue(editor.reasoning_auto_button.selected)
        self.assertEqual(editor._values()["thinking_level"], "auto")
        self.assertEqual(editor._reasoning_status.get(), "默认")
        editor.variables["protocol"].set("gemini")
        editor.variables["url"].set("https://generativelanguage.googleapis.com")
        editor.variables["model"].set("gemini-3.8-flash")
        self.assertEqual(slider.values, ("low", "medium", "high"))
        self.assertNotIn("auto", slider.values)

    def test_kimi_pro_is_detected_without_server_metadata_and_saves_schema_choice(self):
        editor = self.editor(dict(url="https://api.moonshot.cn/v1", model="kimi-k3.1-pro"))
        slider = editor.entries["thinking_level"]
        self.assertEqual(slider.values, ("low", "high", "max"))
        self.assertEqual(slider.default_level, "max")
        self.assertEqual(slider.cget("state"), "normal")
        self.assertTrue(editor.reasoning_auto_button.selected)
        self.assertEqual(editor.variables["thinking_level"].get(), "auto")
        editor.variables["json_mode"].set("json_schema")
        slider._select(1)
        self.assertEqual(editor._reasoning_status.get(), "高")
        editor.save()
        self.assertEqual(self.saved[0][0]["thinking_level"], "high")
        self.assertEqual(self.saved[0][0]["json_mode"], "json_schema")
        self.assertEqual(self.saved[0][0]["reasoning_config"]["kind"], "effort")

    def test_stale_metadata_after_model_key_or_protocol_changes_is_ignored(self):
        capability = ReasoningCapability("effort", ("low", "high"), "metadata")
        for field, value in (("model", "another-model"), ("key", "changed-placeholder"), ("protocol", "gemini")):
            with self.subTest(field=field):
                editor = self.editor()
                context, revision = editor._reasoning_context(), editor._reasoning_revision
                (editor.key_var if field == "key" else editor.variables[field]).set(value)
                editor._finish_reasoning_discovery(context, revision, capability)
                self.assertFalse(editor._reasoning_capability.known)
                self.assertEqual(editor.entries["thinking_level"].cget("state"), "disabled")
                editor.destroy()

    def test_current_result_is_applied_and_late_result_after_close_is_safe(self):
        editor = self.editor()
        context, revision = editor._reasoning_context(), editor._reasoning_revision
        capability = ReasoningCapability("effort", ("low", "high"), "metadata")
        editor._finish_reasoning_discovery(context, revision, capability)
        self.assertEqual(editor.entries["thinking_level"].values, ("low", "high"))
        self.assertTrue(editor.reasoning_auto_button.selected)
        editor.destroy()
        editor._finish_reasoning_discovery(context, revision, capability)

    def test_background_discovery_only_updates_through_ui_queue(self):
        editor = self.editor()
        context, revision = editor._reasoning_context(), editor._reasoning_revision
        capability = ReasoningCapability("effort", ("low", "high"), "metadata")
        with patch("gui.custom_api_dialog.discover_capability", return_value=capability):
            editor._start_reasoning_discovery(context, revision)
            callback = self.callbacks.get(timeout=3)
        self.assertFalse(editor._reasoning_capability.known)
        callback()
        self.assertEqual(editor.entries["thinking_level"].values, ("low", "high"))

    def test_manual_override_roundtrips_and_does_not_follow_another_model(self):
        editor = self.editor()
        self.root.grab_set()
        editor._open_reasoning_settings()
        settings = editor._reasoning_settings
        self.assertIs(self.root.grab_current(), settings)
        settings.levels_var.set("low, high, max")
        settings.apply()
        self.root.update()
        self.assertIs(self.root.grab_current(), self.root)
        self.assertEqual(editor.entries["thinking_level"].values, ("low", "high", "max"))
        editor.entries["thinking_level"]._select(2)
        editor.save()
        values = self.saved[0][0]
        self.assertTrue(values["reasoning_config"]["override"])
        reopened = self.editor(values)
        self.assertEqual(reopened.variables["thinking_level"].get(), "max")
        reopened.variables["model"].set("another-model")
        self.assertEqual(reopened.entries["thinking_level"].cget("state"), "disabled")
        self.assertEqual(reopened.variables["thinking_level"].get(), "auto")
        reopened.variables["model"].set(values["model"])
        self.assertEqual(reopened.variables["thinking_level"].get(), "max")
        self.root.grab_release()

    def test_redetect_removes_manual_override_and_explicit_auto_stays_selected(self):
        editor = self.editor()
        identity = capability_identity(*editor._reasoning_context()[:3])
        editor._reasoning_overrides[identity] = ReasoningCapability("effort", ("low", "high"), "manual")
        editor._schedule_reasoning_discovery()
        editor.entries["thinking_level"]._select(1)
        editor.reasoning_auto_button.invoke()
        editor._open_reasoning_settings()
        editor._reasoning_settings.redetect()
        self.assertNotIn(identity, editor._reasoning_overrides)
        self.assertEqual(editor.variables["thinking_level"].get(), "auto")
        self.assertEqual(editor.entries["thinking_level"].cget("state"), "disabled")

    def test_manual_validation_and_parent_destroy_cleanup(self):
        editor = self.editor()
        editor._open_reasoning_settings()
        settings = editor._reasoning_settings
        settings.levels_var.set("auto, invalid-field")
        settings.apply()
        self.assertTrue(settings.winfo_exists())
        self.assertTrue(settings.error_var.get())
        editor.destroy()
        self.root.update()
        self.assertFalse(settings.winfo_exists())

    def test_probe_is_opt_in_and_preserves_evidence_on_apply_and_reopen(self):
        capability = ReasoningCapability("effort", ("standard", "extreme"), "probe_error",
                                         parameter="reasoning.effort", note="未确认实际生效")
        with patch.object(CustomAPIEditor, "_start_reasoning_discovery"), patch(
                "gui.custom_api_dialog.probe_reasoning_capability", return_value=SimpleNamespace(
                capability=capability, message="接口校验声明了档位；未确认实际生效。")) as probe:
            editor = self.editor(key="placeholder")
            editor._open_reasoning_settings()
            settings = editor._reasoning_settings
            self.root.update()
            probe.assert_not_called()
            settings.probe()
            settings.probe()
            callback = self.callbacks.get(timeout=3)
            probe.assert_called_once()
            callback()
            self.assertIn("未确认", settings.source_var.get())
            self.assertEqual(editor.entries["thinking_level"].values, ())
            settings.apply()
            self.assertEqual(editor._reasoning_capability.source, "probe_error")
            self.assertEqual(editor.entries["thinking_level"].values, ("standard", "extreme"))
            self.assertIn("接口校验声明", editor._reasoning_evidence.get())
            editor.entries["thinking_level"]._select(1)
            self.assertEqual(editor._reasoning_status.get(), "extreme")
            editor.save()
            saved = self.saved[0][0]
            self.assertFalse(saved["reasoning_config"]["override"])
            reopened = self.editor(saved, key="placeholder")
            self.assertEqual(reopened.entries["thinking_level"].values, ("standard", "extreme"))
            reopened.key_var.set("another-placeholder")
            self.assertFalse(reopened._reasoning_capability.known)

    def test_probe_cancels_on_context_change_and_stale_result_cannot_apply(self):
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        capability = ReasoningCapability("effort", ("low", "high"), "probe_error")
        def detect(*_args, **kwargs):
            started.set()
            release.wait(3)
            self.assertTrue(kwargs["cancel_event"].is_set())
            return SimpleNamespace(capability=capability, message="检测完成")
        editor = self.editor()
        editor._open_reasoning_settings()
        settings = editor._reasoning_settings
        with patch("gui.custom_api_dialog.probe_reasoning_capability", side_effect=detect):
            settings.probe()
            self.assertTrue(started.wait(2))
            editor.variables["model"].set("new-model")
            self.assertFalse(settings._probing)
            release.set()
            self.callbacks.get(timeout=3)()
        self.assertFalse(editor._reasoning_capability.known)
        self.assertIn("配置已更改", settings.error_var.get())
        settings.levels_var.set("low, high")
        settings.apply()
        self.assertFalse(editor._reasoning_capability.known)

    def test_probe_unknown_keeps_locked_auto_and_close_cancels(self):
        editor = self.editor()
        editor._open_reasoning_settings()
        settings = editor._reasoning_settings
        with patch("gui.custom_api_dialog.probe_reasoning_capability", return_value=SimpleNamespace(
                capability=ReasoningCapability(), message="接口可能忽略参数，无法确认。")):
            settings.probe()
            self.callbacks.get(timeout=3)()
        self.assertFalse(editor._reasoning_capability.known)
        self.assertTrue(editor.reasoning_auto_button.selected)
        self.assertIn("无法确认", settings.error_var.get())
        editor._reasoning_probe_cancel = threading.Event()
        cancel = editor._reasoning_probe_cancel
        settings._probing = True
        settings.close()
        self.assertTrue(cancel.is_set())

    def test_manual_parameter_path_and_declared_budget_range_are_visible(self):
        editor = self.editor()
        budget = ReasoningCapability("budget", ("1024", "4096"), "schema", parameter="thinking.budget_tokens",
                                     budget_min=1024, budget_max=4096)
        editor._apply_reasoning_capability(budget)
        editor._open_reasoning_settings()
        settings = editor._reasoning_settings
        self.assertIn("1024–4096", settings.range_var.get())
        self.assertEqual(settings.parameter_var.get(), "thinking.budget_tokens")
        settings.levels_var.set("1024, 2048")
        settings.apply()
        self.assertEqual(editor._reasoning_capability.source, "manual")
        self.assertEqual(editor._reasoning_capability.parameter, "thinking.budget_tokens")

    def test_reasoning_settings_actions_remain_visible_at_high_dpi(self):
        previous = float(self.root.tk.call("tk", "scaling"))
        self.addCleanup(lambda: self.root.tk.call("tk", "scaling", previous))
        self.root.tk.call("tk", "scaling", 2.0)
        editor = self.editor()
        editor._open_reasoning_settings()
        settings = editor._reasoning_settings
        capability = ReasoningCapability("budget", ("1024", "4096"), "probe_error",
                                         parameter="thinking_budget", budget_min=1024, budget_max=4096)
        settings.finish_probe(capability, "接口声明了预算范围；未确认实际生效。" * 3)
        self.root.update()
        self.assertLessEqual(settings.winfo_height(), settings.winfo_screenheight() - 96)
        for button in settings._buttons:
            self.assertTrue(button.winfo_ismapped())
            self.assertGreaterEqual(button.winfo_height(), 30)
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                 settings.winfo_rooty() + settings.winfo_height())

    def test_saved_automatic_snapshot_expires_instead_of_bypassing_cache_ttl(self):
        url, protocol, model, key = "https://unknown.test/v1", "openai", "unknown-model", ""
        capability = ReasoningCapability("effort", ("low", "high"), "probe_error")
        values = dict(url=url, protocol=protocol, model=model, reasoning_config={
            **capability.to_dict(), "identity": capability_identity(url, protocol, model),
            "scope": capability_identity(url, protocol, model, key), "override": False,
            "observed_at": time.time() - 90000,
        })
        editor = self.editor(values)
        self.assertFalse(editor._reasoning_capability.known)
        self.assertEqual(editor.variables["thinking_level"].get(), "auto")


if __name__ == "__main__":
    unittest.main()
