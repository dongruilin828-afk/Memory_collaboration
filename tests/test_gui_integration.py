"""Offline checks for the merged frontend-to-backend task contract."""

import tempfile
import gc
import json
import re
import threading
import tkinter as tk
from tkinter import ttk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import quote, unquote

from gui.app import AIMemoryGUI
from gui.history_store import HistoryStore
from gui.service import FetchResult, build_output_paths, generate_output_bundle
from gui.settings_store import AppSettings
from gui.ui_dispatch import UIDispatcher
from scripts.gemini_summarizer import SummaryConfig, write_summary_outputs


def drain_dispatcher(dispatcher):
    # 手动推进测试时先撤掉真实 Tk 定时器，避免形成重复的轮询链。
    if dispatcher._after_id is not None:
        dispatcher.root.after_cancel(dispatcher._after_id)
    dispatcher._drain()


class MergedGenerationTests(unittest.TestCase):
    def test_fetch_finishes_while_minimized_without_waiting_for_ui(self):
        root = tk.Tk()
        root.withdraw()
        dispatcher = UIDispatcher(root)
        errors = []
        try:
            with tempfile.TemporaryDirectory() as temp:
                app = object.__new__(AIMemoryGUI)
                app.root = root
                app._post_ui = dispatcher.post
                app._ui_dispatcher = dispatcher
                app.progress_bar = Mock()
                app.status_var = Mock()
                app.percent_var = Mock()
                app._show_completed_badge = Mock()
                app._add_history_record = Mock()
                app._on_task_finished = Mock()
                app._confirm_login_required = Mock()
                app._request_attachment_web_link = Mock(return_value=None)

                async def fetch(**kwargs):
                    for index in range(150):
                        kwargs["logger"](f"抓取进度 {index}")
                    return FetchResult(
                        html="", image_map={},
                        messages=[{"role": "User", "content": "完整抓取内容"}],
                        warnings=["附件未下载"],
                    )

                def worker():
                    try:
                        app._run_generation_task(
                            "https://chat.deepseek.com/share/offline", False,
                            {"raw": True}, Path(temp), "result.md", {},
                            AppSettings(Path(temp) / "runtime"),
                        )
                    except Exception as error:
                        errors.append(error)

                with (
                    patch("gui.app.fetch_chat_pipeline", side_effect=fetch),
                    patch("gui.app.messagebox.showwarning") as warning,
                ):
                    thread = threading.Thread(target=worker, daemon=True)
                    thread.start()
                    # 故意不运行 Tk mainloop；旧的 worker -> root.after 会卡住。
                    thread.join(timeout=3)
                    for _ in range(4):
                        drain_dispatcher(dispatcher)
                    warning.assert_not_called()
                    root.deiconify()
                    root.update_idletasks()
                    drain_dispatcher(dispatcher)
                    warning.assert_called_once()
                self.assertFalse(thread.is_alive(), "抓取等待了不可用的 UI 线程")
                self.assertEqual(errors, [])
                paths = build_output_paths(Path(temp), {"raw": True}, "result.md")
                self.assertIn("完整抓取内容", paths["raw_markdown"].read_text(encoding="utf-8"))
                app._on_task_finished.assert_called_once()
                app._add_history_record.assert_called_once()
        finally:
            dispatcher.close()
            root.destroy()

    def test_platforms_and_modes_keep_assets_topics_warnings_and_history(self):
        urls = (
            "https://chatgpt.com/share/example",
            "https://chat.deepseek.com/share/example",
            "https://www.doubao.com/thread/example",
            "https://share.gemini.google/example",
            "https://www.kimi.com/share/example",
            "https://www.qianwen.com/share/example",
            "https://grok.com/share/example",
            "https://chatgpt.com/codex/tasks/example",
        )
        mode_sets = [
            {mode: True} for mode in ("raw", "normal", "simple", "detailed")
        ] + [{mode: True for mode in ("raw", "normal", "simple", "detailed")}]
        for url in urls:
            for modes in mode_sets:
                with self.subTest(url=url, modes=modes), tempfile.TemporaryDirectory() as temp:
                    self._check_task(Path(temp), url, modes)

    def _check_task(self, directory, url, modes):
        settings = AppSettings(directory / "runtime")
        save_dir = directory / "chosen output"
        paths = build_output_paths(save_dir, modes, "中文 result.md")
        result_dir = paths["output_dir"]
        app = object.__new__(AIMemoryGUI)
        app.root = SimpleNamespace(after=lambda _delay, callback: callback())
        app._post_ui = lambda callback, **_kwargs: callback()
        app._ui_dispatcher = SimpleNamespace(wait=lambda event: event.wait())
        app.progress_bar = Mock()
        app.status_var = Mock()
        app.percent_var = Mock()
        app.history_store = HistoryStore(settings.history_file)
        app.history_records = []
        app._refresh_history_list = Mock()
        app._show_completed_badge = Mock()
        app._on_task_finished = Mock()
        app._confirm_login_required = Mock(return_value=True)
        app._request_attachment_web_link = Mock(return_value=None)
        app._show_login_dialog = Mock()
        app._show_summary_topic_dialog = Mock(
            side_effect=lambda topics, on_done: on_done((topics[0]["topic_id"],))
        )
        messages = [
            {"role": "User", "content": "请总结对话"},
            {"role": "AI", "content": "![图片](./asset/image.png) [附件](./asset/document.pdf)"},
        ]
        result = {
            "conversation": {"message_count": 2, "chunk_count": 1},
            "model": "offline-model", "source": url,
            "overall_summary": messages[1]["content"],
            "typed_records": {},
            "topics": [{
                "topic_id": "topic_1", "title": "重点主题", "summary": "主题摘要",
                "memory_ids": [], "source_message_ids": [1, 2],
            }],
        }
        warning = "部分附件不可下载，正文已保留文件名。"

        async def fetch(**kwargs):
            self.assertEqual(kwargs["url"], url)
            self.assertIs(kwargs["login_confirmation_callback"], app._confirm_login_required)
            self.assertIs(
                kwargs["attachment_web_link_callback"],
                app._request_attachment_web_link,
            )
            self.assertIsNotNone(kwargs["login_required_callback"])
            self.assertIsNotNone(kwargs["login_ready_event"])
            owner = paths["asset_markdown"].stem
            self.assertEqual(kwargs["image_output_dir"].name, owner + "_images")
            self.assertEqual(kwargs["document_output_dir"].name, owner + "_files")
            self.assertEqual(kwargs["image_output_dir"].parent, result_dir)
            self.assertEqual(kwargs["document_output_dir"].parent, result_dir)
            self.assertEqual(kwargs["image_reference_base"], result_dir)
            self.assertEqual(kwargs["document_reference_base"], result_dir)
            resources = []
            for key, name in (
                ("image_output_dir", "test image.png"),
                ("document_output_dir", "notes #1.txt"),
            ):
                asset = kwargs[key] / name
                asset.parent.mkdir(parents=True, exist_ok=True)
                asset.write_bytes(b"offline resource")
                resources.append("./" + quote(asset.relative_to(result_dir).as_posix()))
            messages[1]["content"] = f"![图片]({resources[0]}) [附件]({resources[1]})"
            result["overall_summary"] = messages[1]["content"]
            return FetchResult(
                html="", image_map={}, messages=messages, warnings=[warning]
            )

        def summarize(**kwargs):
            self.assertEqual(kwargs["messages"], messages)
            expected_platform = (
                "ChatGPT" if url.startswith("https://chatgpt.com/share/")
                else "doubao" if "doubao.com/" in url
                else "deepseek" if "chat.deepseek.com/" in url else None
            )
            self.assertEqual(kwargs.get("source_platform"), expected_platform)
            self.assertEqual(kwargs["source_dir"], result_dir.resolve())
            self.assertEqual(kwargs["result_cache_dir"], settings.summary_cache_dir.resolve())
            selected = ()
            if modes.get("normal") or modes.get("detailed"):
                selected = kwargs["topic_selector"](result)
                self.assertEqual(selected, ("topic_1",))
            else:
                self.assertIsNone(kwargs["topic_selector"])
            write_summary_outputs(
                result, kwargs["output_json"], kwargs["output_markdown"],
                include_details=kwargs["include_details"], selected_topics=selected,
            )
            return result

        with (
            patch("gui.app.fetch_chat_pipeline", side_effect=fetch),
            patch("scripts.gemini_summarizer.create_gateway", return_value=object()),
            patch("scripts.gemini_summarizer.summarize_conversation", side_effect=summarize) as summary,
            patch("scripts.simple_summarizer.generate_simple_overview", return_value="极简总览"),
            patch("gui.app.messagebox.showwarning") as showwarning,
            patch("gui.app.messagebox.showerror") as showerror,
        ):
            app._run_generation_task(
                url, False, modes, save_dir, "中文 result.md",
                {"gemini": "offline-placeholder"}, settings,
            )

        showerror.assert_not_called()
        showwarning.assert_called_once()
        self.assertIn(warning, showwarning.call_args.args[1])
        self.assertEqual(showwarning.call_args.args[0], "抓取完成，但部分附件未下载")
        self.assertEqual(summary.call_count, 0 if modes == {"raw": True} else 1)
        self.assertEqual(
            app._show_summary_topic_dialog.call_count,
            int(bool(modes.get("normal") or modes.get("detailed"))),
        )
        expected = []
        for mode in ("raw", "normal", "detailed", "simple"):
            if modes.get(mode):
                expected.append(paths[mode + "_markdown"])
                if mode in ("normal", "detailed"):
                    expected.append(paths[mode + "_json"])
        records = app.history_store.load()
        self.assertEqual(records[0]["saved_files"], [str(path.resolve()) for path in expected])
        self.assertEqual(records[0]["output_dir"], str(result_dir.resolve()))
        self.assertEqual(records[0]["file_count"], len(expected))
        self.assertTrue(all(path.is_file() for path in expected))
        self.assertTrue(all(path.parent == result_dir for path in expected))
        for mode in ("raw", "normal", "detailed"):
            if modes.get(mode):
                self.assertIn(
                    messages[1]["content"],
                    paths[mode + "_markdown"].read_text(encoding="utf-8"),
                )
                for reference in re.findall(r"\]\(([^)]+)\)", messages[1]["content"]):
                    self.assertTrue(
                        (paths[mode + "_markdown"].parent / unquote(reference)).is_file(),
                        reference,
                    )
        app._on_task_finished.assert_called_once()


class ImportedAssetIntegrationTests(unittest.TestCase):
    def test_imported_resources_follow_all_outputs_without_changing_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "original"
            originals = {
                "images/test image.png": b"image-bytes",
                "first/notes #1.txt": b"first document",
                "second/notes #1.txt": b"second document",
            }
            for name, content in originals.items():
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            outside = root / "outside.txt"
            outside.write_bytes(b"must not copy")
            references = ["./" + quote(name) for name in originals]
            text = (
                f"![image]({references[0]}) [first]({references[1]}) [second]({references[2]}) "
                "[remote](https://example.com/notes.txt) [missing](./missing.txt) "
                "[outside](../outside.txt)"
            )
            messages = [{"role": "User", "content": text}, {"role": "AI", "content": "已回答"}]
            modes = dict.fromkeys(("raw", "normal", "detailed", "simple"), True)
            destination = root / "chosen"
            paths = build_output_paths(destination, modes, "result.md")

            def summarize(**kwargs):
                self.assertEqual(kwargs["source_dir"], source.resolve())
                self.assertEqual(kwargs["messages"], messages)
                result = {
                    "conversation": {"message_count": 2, "chunk_count": 1},
                    "model": "offline", "source": "original.md",
                    "overall_summary": text, "topics": [], "typed_records": {},
                    "media": [{
                        "media_id": f"M{index}", "message_index": 1,
                        "kind": "image" if index == 0 else "document",
                        "label": name, "reference": references[index],
                        "local_path": str((source / name).resolve()),
                        "status": "described", "can_reverify": True,
                    } for index, name in enumerate(originals)],
                }
                write_summary_outputs(result, kwargs["output_json"], kwargs["output_markdown"])
                return result

            with (
                patch("scripts.gemini_summarizer.summarize_conversation", side_effect=summarize),
                patch("scripts.simple_summarizer.generate_simple_overview", return_value=text),
            ):
                bundle = generate_output_bundle(
                    messages, modes, destination, output_filename="result.md",
                    source_dir=source, project_dir=source,
                    config=SummaryConfig(), gateway=object(), progress=lambda _: None,
                )

            media = bundle.summary_result["media"]
            self.assertEqual(len({item["reference"] for item in media}), 3)
            for item in media:
                self.assertTrue(Path(item["local_path"]).is_file())
            saved_json = json.loads(paths["normal_json"].read_text(encoding="utf-8"))
            self.assertEqual(saved_json["media"], media)
            for name, content in originals.items():
                self.assertEqual((source / name).read_bytes(), content)
            self.assertEqual(messages[0]["content"], text)

            # 分享整个结果目录后，链接仍有效；原目录无需随行。
            moved = root / "shared result"
            paths["output_dir"].rename(moved)
            for mode in modes:
                exported = (moved / paths[mode + "_markdown"].name).read_text(encoding="utf-8")
                self.assertIn("https://example.com/notes.txt", exported)
                self.assertIn("./missing.txt", exported)
                for item, expected in zip(media, originals.values()):
                    self.assertIn(item["reference"], exported)
                    self.assertEqual((moved / unquote(item["reference"])).read_bytes(), expected)
            copied = [p for p in moved.rglob("*") if p.is_file() and p.parent != moved]
            self.assertEqual(len(copied), 3)


class AttachmentPromptIntegrationTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.root = tk.Tk()
        self.root.withdraw()
        self.dispatcher = UIDispatcher(self.root)
        self.app = object.__new__(AIMemoryGUI)
        self.app.root = self.root
        self.app._ui_dispatcher = self.dispatcher
        self.posted = threading.Event()
        self.results, self.errors, self.ui_errors = [], [], []
        self.root.report_callback_exception = lambda *error: self.ui_errors.append(error)

        def post(callback, **kwargs):
            self.dispatcher.post(callback, **kwargs)
            self.posted.set()

        self.app._post_ui = post

        def request():
            try:
                self.results.append(self.app._request_attachment_web_link(["notes.xlsx"]))
            except Exception as error:
                self.errors.append(error)

        self.thread = threading.Thread(target=request, daemon=True)
        self.thread.start()
        self.assertTrue(self.posted.wait(1), "worker attempted a direct Tk call")

    def tearDown(self):
        self.dispatcher.close()
        self.thread.join(timeout=1)
        self.root.destroy()

    def show_dialog(self):
        drain_dispatcher(self.dispatcher)
        self.assertEqual(self.root.winfo_children(), [])
        self.assertTrue(self.thread.is_alive())
        self.root.deiconify()
        self.root.update_idletasks()
        drain_dispatcher(self.dispatcher)
        self.root.update_idletasks()
        return next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))

    def test_attachment_prompt_defers_until_visible_and_validates_link(self):
        dialog = self.show_dialog()
        entry = next(w for w in dialog.winfo_children() if isinstance(w, ttk.Entry))
        buttons = next(w for w in dialog.winfo_children() if isinstance(w, ttk.Frame))
        confirm = next(w for w in buttons.winfo_children() if w.cget("text") == "确定")
        self.assertIn("disabled", confirm.state())
        entry.insert(0, "https://[")
        self.assertIn("disabled", confirm.state())
        entry.delete(0, tk.END)
        url = "https://chat.deepseek.com/a/chat/s/offline"
        entry.insert(0, url)
        self.assertNotIn("disabled", confirm.state())
        confirm.invoke()
        self.thread.join(timeout=1)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.results, [url])
        self.assertEqual(self.errors, [])
        self.assertEqual(self.ui_errors, [])

    def test_attachment_prompt_keeps_automatic_skip(self):
        timers = []
        original_after = tk.Toplevel.after

        def capture_after(dialog, delay, callback=None, *args):
            if delay == 1000:
                timers.append(callback)
            return original_after(dialog, delay, callback, *args)

        with patch.object(tk.Toplevel, "after", capture_after):
            dialog = self.show_dialog()
            self.assertEqual(len(timers), 1)
            timers[0](0)
        self.thread.join(timeout=1)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.results, [None])
        self.assertFalse(dialog.winfo_exists())
        self.assertEqual(self.ui_errors, [])

    def test_closed_window_releases_pending_attachment_request(self):
        self.dispatcher.close()
        self.thread.join(timeout=1)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(len(self.errors), 1)
        self.assertIsInstance(self.errors[0], RuntimeError)

    def test_dialog_creation_failure_does_not_leave_worker_waiting(self):
        with patch("gui.app.tk.Toplevel", side_effect=tk.TclError("unavailable")):
            self.root.deiconify()
            self.root.update_idletasks()
            drain_dispatcher(self.dispatcher)
        self.thread.join(timeout=1)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.results, [None])
        self.assertEqual(len(self.ui_errors), 1)


if __name__ == "__main__":
    unittest.main()
