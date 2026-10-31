"""Batch editor, queue geometry and application bridge on isolated Tk stores."""
import asyncio
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gui.app import AIMemoryGUI
from gui.batch_processing import BatchPlan, ItemPlan
from gui.batch_processing_dialog import BatchProcessingDialog
from gui.batch_queue_panel import BatchQueuePanel
from tests import test_gui_layout as layouts


def link_plan(count=3):
    return BatchPlan("links", tuple(ItemPlan(f"https://chatgpt.com/c/item-{i}", ("raw",)) for i in range(count)), 3)


class _TkTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.tk.call("tk", "scaling", 4 / 3)
        self.root.attributes("-alpha", 0)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.addCleanup(self.close)

    def close(self):
        self.root.update_idletasks()
        self.root.destroy()
        self.assertEqual(self.errors, [])

    def dialog(self, **kwargs):
        dialog = BatchProcessingDialog(self.root, on_submit=Mock(return_value=False), **kwargs)
        dialog.attributes("-alpha", 0)
        self.root.update()
        return dialog

class BatchEditorTests(_TkTests):
    def test_submitting_one_tab_preserves_the_other_tab_in_both_directions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "待处理.txt"
            path.write_text("正文", encoding="utf-8")
            closed = Mock()
            dialog = self.dialog(initial_text="https://chatgpt.com/c/keep", on_close=closed)
            dialog.identify()
            dialog.kind.set("files")
            dialog._render()
            dialog.add_paths([path])
            dialog.kind.set("links")
            dialog._render()
            dialog.on_submit = Mock(return_value=True)
            dialog.submit()
            state = closed.call_args.args[0]
            self.assertEqual(state["links"], [])
            restored = self.dialog(draft=state)
            self.assertEqual(restored.get_plan().items[0].source, str(path))
            restored.destroy()

            dialog = self.dialog(initial_text="https://chatgpt.com/c/not-yet-identified", on_close=closed)
            dialog.kind.set("files")
            dialog._render()
            dialog.add_paths([path])
            dialog.on_submit = Mock(return_value=True)
            dialog.submit()
            restored = self.dialog(draft=closed.call_args.args[0])
            self.assertEqual(restored.kind.get(), "links")
            self.assertEqual(restored.links_text.get("1.0", "end-1c"), "https://chatgpt.com/c/not-yet-identified")
            self.assertTrue(restored.identify())

    def test_native_tabs_auto_spinner_limits_and_api_multiselect(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test.txt"
            path.write_text("正文", encoding="utf-8")
            dialog = self.dialog(providers=[("gemini", "Google Gemini"), ("deepseek", "DeepSeek")])
            self.assertEqual(dialog.concurrency.get(), "3")
            dialog.notebook.select(1)
            self.root.update()
            self.assertEqual(dialog.kind.get(), "files")
            dialog.add_paths([path])
            dialog.concurrency_box.invoke("buttonup")
            self.assertEqual(dialog.concurrency.get(), "1")
            dialog.concurrency_box.invoke("buttondown")
            self.assertEqual(dialog.concurrency.get(), "自动")
            dialog.concurrency.set("10")
            self.assertEqual(dialog.get_plan().concurrency, 10)
            dialog.api_menu.invoke(0)
            self.assertEqual(dialog.get_plan().api_providers, ("deepseek",))
            dialog.notebook.select(0)
            self.root.update()
            self.assertEqual(tuple(dialog.tk.splitlist(dialog.concurrency_box.cget("values"))), tuple(str(i) for i in range(1, 11)))
            dialog.concurrency.set("1")
            dialog.concurrency_box.invoke("buttondown")
            self.assertEqual(dialog.concurrency.get(), "1")
            dialog.concurrency.set("自动")
            with self.assertRaisesRegex(ValueError, "并发"):
                dialog.get_plan()
            dialog.links_text.insert("1.0", "https://chatgpt.com/c/ten")
            self.assertTrue(dialog.identify())
            dialog.concurrency.set("9")
            dialog.concurrency_box.invoke("buttonup")
            self.assertEqual(dialog.get_plan().concurrency, 10)
            dialog.concurrency_box.invoke("buttonup")
            self.assertEqual(dialog.concurrency.get(), "10")
            for value in ("0", "11", "2.5"):
                dialog.concurrency.set(value)
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "并发"):
                    dialog.get_plan()
            dialog.concurrency.set("10")
            dialog.notebook.select(1)
            self.root.update()
            self.assertEqual(dialog.concurrency.get(), "10")
            dialog.concurrency.set("11")
            with self.assertRaises(ValueError):
                dialog.get_plan()
            dialog.concurrency.set("自动")
            dialog.api_menu.invoke(1)
            with self.assertRaisesRegex(ValueError, "API"):
                dialog.get_plan()
            state = dialog.draft_state()
            state["concurrency_by_kind"]["links"] = "自动"
            dialog.destroy()
            dialog = self.dialog(draft=state)
            dialog.notebook.select(0)
            self.root.update()
            self.assertEqual(dialog.concurrency.get(), "3")

    def test_disabled_add_button_is_legible_and_footer_controls_stay_centered(self):
        for scaling in (1, 4 / 3, 2, 8 / 3):
            with self.subTest(scaling=scaling):
                self.root.tk.call("tk", "scaling", scaling)
                dialog = self.dialog()
                dialog.notebook.select(1)
                self.root.update()
                dialog.geometry(f"{dialog.minsize()[0]}x{dialog.minsize()[1]}")
                self.root.update()
                self.assertEqual(dialog.submit_button.cget("state"), "disabled")
                self.assertEqual(dialog.submit_button.cget("disabledforeground"), "white")
                center = dialog.settings.winfo_rootx() + dialog.settings.winfo_width()/2
                self.assertLessEqual(abs(center - (dialog.footer.winfo_rootx()+dialog.footer.winfo_width()/2)), 2)
                self.assertGreaterEqual(dialog.submit_button.winfo_width(), dialog.submit_button.winfo_reqwidth())
                self.assertLessEqual(dialog.settings.winfo_rooty()+dialog.settings.winfo_height(), dialog.winfo_rooty()+dialog.winfo_height())
                dialog.destroy()

    def test_initial_actions_filtering_and_append_cancel_do_not_drop_valid_rows(self):
        dialog = self.dialog(initial_text="说明文字\nhttps://unsupported.test/foo\nhttps://chatgpt.com/c/one")
        self.assertFalse(dialog.heading.winfo_manager())
        self.assertFalse(dialog.table_actions.winfo_manager())
        self.assertTrue(dialog.input_close.winfo_ismapped())
        self.assertTrue(dialog.identify())
        self.root.update()
        self.assertEqual(len(dialog.rows), 1)
        self.assertTrue(dialog.footer.winfo_ismapped())
        dialog.show_append()
        dialog.append_text.insert("1.0", "not a link")
        self.assertFalse(dialog.identify(append=True))
        self.assertIn("没有合法", dialog.notice.cget("text"))
        self.assertFalse(dialog.append_text.winfo_manager())
        self.assertEqual(len(dialog.rows), 1)
        dialog.show_append()
        dialog.append_text.insert("1.0", "https://chatgpt.com/c/two")
        dialog.append_cancel.invoke()
        self.assertEqual(len(dialog.rows), 1)
        self.assertEqual(dialog.append_text.get("1.0", "end-1c"), "")

    def test_editor_and_main_can_minimize_independently_without_a_modal_grab(self):
        dialog = self.dialog()
        self.assertFalse(dialog.transient())
        self.assertIsNone(dialog.grab_current())
        for window in (dialog, self.root):
            window.iconify()
            self.root.update()
            self.assertEqual(window.state(), "iconic")
            window.deiconify()
            self.root.update()

    def test_close_retains_both_tabs_text_modes_concurrency_and_pending_append(self):
        closed = Mock()
        dialog = self.dialog(initial_text="https://chatgpt.com/c/one", on_close=closed)
        dialog.identify()
        dialog.rows[0]["checks"]["normal"].set(True)
        dialog._mode_changed(dialog.drafts["links"][0], "normal", dialog.rows[0]["checks"]["normal"])
        dialog.concurrency.set(2)
        dialog.show_append()
        dialog.append_text.insert("1.0", "还没有写完的链接")
        dialog.close()
        draft = closed.call_args.args[0]
        restored = self.dialog(draft=draft)
        self.assertEqual(restored.concurrency.get(), "2")
        self.assertEqual(restored.append_text.get("1.0", "end-1c"), "还没有写完的链接")
        self.assertEqual(restored.get_plan().items[0].modes, ("raw", "normal"))

    def test_large_tables_reuse_existing_widgets_and_header_checkboxes_align(self):
        dialog = self.dialog(plan=link_plan(173))
        original = list(dialog.rows)
        dialog.move_row(0, 1)
        self.assertIs(dialog.rows[1], original[0])
        dialog.column_vars["normal"].set(True)
        dialog.select_column("normal")
        self.assertIs(dialog.rows[1], original[0])
        dialog.delete_row(2)
        self.assertEqual(len(dialog.drafts["links"]), 172)
        self.assertLess(len(dialog.rows), 30)
        self.assertTrue(original[0]["frame"].winfo_exists())
        self.assertFalse(original[2]["frame"].winfo_exists())
        self.root.update()
        for column in range(3, 7):
            header = dialog.table_header.grid_slaves(column=column)[0]
            check = dialog.rows[0]["frame"].grid_slaves(column=column)[0]
            self.assertLessEqual(abs(header.winfo_rootx() - check.winfo_rootx()), 2)
        self.assertTrue(all(button.cget("cursor") == "hand2" for _, button in dialog.rows[1]["arrows"]))

    def test_large_table_scroll_keeps_all_edits_and_can_return_to_a_small_table(self):
        dialog = self.dialog(plan=link_plan(173))
        dialog.rows[0]["variable"].set("https://chatgpt.com/c/edited-first")
        dialog.column_vars["normal"].set(True)
        dialog.select_column("normal")
        dialog.area.canvas.yview_moveto(1)
        self.root.update()
        self.assertEqual(dialog.rows[-1]["index"], 172)
        self.assertTrue(dialog.rows[-1]["checks"]["normal"].get())
        dialog.rows[-1]["variable"].set("https://chatgpt.com/c/edited-last")
        dialog.area.canvas.yview_moveto(0)
        self.root.update()
        self.assertEqual(dialog.rows[0]["variable"].get(), "https://chatgpt.com/c/edited-first")
        self.assertEqual(dialog.get_plan().items[-1].source, "https://chatgpt.com/c/edited-last")
        del dialog.drafts["links"][40:]
        dialog._render()
        self.root.update()
        self.assertEqual(len(dialog.rows), 40)
        self.assertTrue(all(row["frame"].winfo_manager() == "grid" for row in dialog.rows))

    def test_virtual_file_table_keeps_modes_order_and_alignment_across_dpi(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = [Path(temporary) / f"文档-{i:03d}.md" for i in range(173)]
            for path in paths:
                path.write_text("正文", encoding="utf-8")
            for scaling in (1, 4 / 3, 2, 8 / 3):
                with self.subTest(scaling=scaling):
                    self.root.tk.call("tk", "scaling", scaling)
                    plan = BatchPlan("files", tuple(ItemPlan(str(path), ("normal",)) for path in paths), 2)
                    dialog = self.dialog(plan=plan)
                    dialog.geometry(f"{dialog.minsize()[0]}x{dialog.minsize()[1]}")
                    self.root.update()
                    self.assertLess(len(dialog.rows), 30)
                    for column in (3, 4, 5):
                        header = dialog.table_header.grid_slaves(column=column)[0]
                        check = dialog.rows[0]["frame"].grid_slaves(column=column)[0]
                        self.assertLessEqual(abs(header.winfo_rootx() - check.winfo_rootx()), 2)
                    dialog.column_vars["detailed"].set(True)
                    dialog.select_column("detailed")
                    dialog.area.canvas.yview_moveto(1)
                    self.root.update()
                    last = dialog.rows[-1]
                    self.assertEqual(last["index"], 172)
                    self.assertTrue(last["checks"]["detailed"].get())
                    last["arrows"][0][1].invoke()
                    self.assertEqual(dialog.get_plan().items[171].source, str(paths[-1]))
                    self.assertEqual(len(dialog.draft_state()["files"]), 173)
                    self.assertTrue(all("detailed" in item.modes for item in dialog.get_plan().items))
                    dialog.destroy()

    def test_background_click_clears_selection_and_edit_focus(self):
        from gui.ui_dispatch import clear_background_focus
        dialog = self.dialog(plan=link_plan(1))
        entry = dialog.rows[0]["source"]
        entry.focus_force()
        entry.selection_range(0, "end")
        self.root.update()
        clear_background_focus(SimpleNamespace(widget=dialog.toolbar))
        self.assertFalse(entry.selection_present())
        self.assertIs(dialog.focus_get(), dialog)

    def test_many_invalid_files_keep_error_bounded_and_footer_visible(self):
        dialog = self.dialog()
        dialog.kind.set("files")
        dialog._render()
        dialog.add_paths(["不支持的很长文件名称" * 12 + str(i) + ".pdf" for i in range(50)])
        self.root.update()
        self.assertIn("50", dialog.notice.cget("text"))
        self.assertLess(len(dialog.notice.cget("text")), 160)
        dialog.geometry(f"{dialog.minsize()[0]}x{dialog.minsize()[1]}")
        self.root.update()
        self.assertLessEqual(dialog.footer.winfo_rooty() + dialog.footer.winfo_height(),
                             dialog.winfo_rooty() + dialog.winfo_height())

    def test_identify_edit_reorder_modes_delete_and_append(self):
        dialog = self.dialog(initial_text="https://chatgpt.com/c/one\nhttps://gemini.google.com/app/two")
        self.assertEqual(dialog.kind.get(), "links")
        self.assertEqual(tuple(dialog.tk.splitlist(dialog.concurrency_box.cget("values"))), tuple(str(i) for i in range(1, 11)))
        self.assertTrue(dialog.identify())
        self.assertEqual(len(dialog.rows), 2)
        dialog.rows[0]["variable"].set("https://chat.deepseek.com/share/edited")
        dialog.move_row(0, 1)
        self.assertEqual(dialog.get_plan().items[1].source, "https://chat.deepseek.com/share/edited")
        dialog.column_vars["detailed"].set(True)
        dialog.select_column("detailed")
        self.assertTrue(all("detailed" in item.modes for item in dialog.get_plan().items))
        dialog.show_append()
        dialog.append_text.insert("1.0", "https://chatgpt.com/c/three\nhttps://chatgpt.com/c/four")
        dialog._append_return(None)
        self.assertEqual(len(dialog.rows), 4)
        dialog.delete_row(1)
        self.assertEqual(len(dialog.rows), 3)
        dialog.submit()
        self.assertTrue(dialog.on_submit.called)

    def test_validation_stays_inline_and_does_not_submit_invalid_drafts(self):
        dialog = self.dialog(initial_text="https://unsupported.test/conversation")
        self.assertFalse(dialog.identify())
        self.assertTrue(dialog.notice.cget("text"))
        self.assertFalse(dialog.on_submit.called)
        dialog.links_text.delete("1.0", "end")
        dialog.links_text.insert("1.0", "https://chatgpt.com/c/one")
        dialog.identify()
        dialog.column_vars["raw"].set(False)
        dialog.select_column("raw")
        dialog.submit()
        self.assertFalse(dialog.on_submit.called)
        self.assertIn("生成模式", dialog.notice.cget("text"))

    def test_folder_import_is_recursive_deduplicated_and_files_are_replaceable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            first, second = root / "first.md", root / "nested" / "second.TXT"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            (root / "skip.pdf").write_bytes(b"pdf")
            dialog = self.dialog()
            dialog.kind.set("files")
            dialog._render()
            with patch("gui.batch_processing_dialog.filedialog.askdirectory", return_value=str(root)):
                dialog.choose_folder()
                dialog.choose_folder()
            self.assertEqual(len(dialog.rows), 2)
            self.assertEqual(set(dialog.rows[0]["checks"]), {"normal", "simple", "detailed"})
            with patch("gui.batch_processing_dialog.filedialog.askopenfilename", return_value=str(second)):
                dialog.replace_file(0)
            self.assertEqual(dialog.get_plan().items[0].source, str(second))
            self.assertEqual(first.read_text(encoding="utf-8"), "first")

    def test_default_and_minimum_editor_sizes_keep_every_action_visible_across_dpi(self):
        for scaling in (1, 4 / 3, 2, 8 / 3):
            with self.subTest(scaling=scaling):
                self.root.tk.call("tk", "scaling", scaling)
                dialog = self.dialog(plan=link_plan(32))
                for width in (dialog.winfo_width(), dialog.minsize()[0]):
                    dialog.geometry(f"{width}x{dialog.minsize()[1]}")
                    self.root.update()
                    for row in dialog.rows:
                        frame = row["frame"]
                        for widget in frame.grid_slaves():
                            self.assertGreaterEqual(widget.winfo_x(), 0)
                            self.assertLessEqual(widget.winfo_x() + widget.winfo_width(), frame.winfo_width())
                            self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth()
                                                    if widget is not row["source"] else 100)
                    self.assertLessEqual(dialog.footer.winfo_rooty() + dialog.footer.winfo_height(),
                                         dialog.winfo_rooty() + dialog.winfo_height())
                    self.assertGreaterEqual(dialog.submit_button.winfo_width(), dialog.submit_button.winfo_reqwidth())
                    self.assertLess(dialog.area.canvas.yview()[1], 1)
                dialog.destroy()


class BatchAppIntegrationTests(_TkTests):
    def test_clicking_home_placeholder_keeps_keyboard_focus_in_the_input(self):
        app = self.app()
        self.root.geometry("1300x900")
        self.root.focus_force()
        self.root.update()
        app.capsule_entry._placeholder_label.event_generate("<Button-1>", x=10, y=10)
        self.root.update()
        self.assertIs(self.root.focus_get(), app.capsule_entry.entry)
        app.capsule_entry.entry.event_generate("<KeyPress>", keysym="a")
        self.root.update()
        self.assertEqual(app.capsule_entry.get_text(), "a")

    def test_removing_all_batches_restores_the_initial_home_positions(self):
        app = self.app()
        self.root.geometry("1300x1000")
        layouts.GUIResponsiveGeometryTests()._settle_resize(self.root, app)
        positions = [widget.winfo_y() for widget in (app._home_welcome, app._omnibox, app.batch_capture_button)]
        for _ in range(2):
            app._refresh_batch_queue([batch_view("queued"), batch_view("queued2")])
            layouts.GUIResponsiveGeometryTests()._settle_resize(self.root, app)
            self.assertFalse(app.batch_capture_button.winfo_manager())
            app._refresh_batch_queue([])
            layouts.GUIResponsiveGeometryTests()._settle_resize(self.root, app)
            self.assertFalse(app._batch_queue_slot.winfo_manager())
            self.assertEqual([widget.winfo_y() for widget in (app._home_welcome, app._omnibox, app.batch_capture_button)], positions)

    def test_switching_modeless_editors_preserves_draft_and_releases_previous_hold(self):
        app = self.app()
        queue = app._batch_queue = Mock()
        queue.hold.return_value = True
        queue.snapshot.return_value = [batch_view("one"), batch_view("two")]
        app._edit_batch("one")
        first = app._batch_processing_dialog
        first.rows[0]["variable"].set("https://chatgpt.com/c/edited")
        app._edit_batch("one")
        self.assertIs(app._batch_processing_dialog, first)
        app._edit_batch("two")
        self.assertFalse(first.winfo_exists())
        self.assertEqual(app._batch_processing_dialog.batch_id, "two")
        self.assertEqual(app._batch_edit_drafts["one"]["links"][0]["source"], "https://chatgpt.com/c/edited")
        queue.resume.assert_called_once_with("one")

    def test_draft_survives_dialog_close_and_application_reload(self):
        app = self.app()
        app._show_batch_processing_dialog()
        dialog = app._batch_processing_dialog
        dialog.links_text.insert("1.0", "https://chatgpt.com/c/draft")
        dialog.close()
        saved = app._load_batch_draft()
        self.assertEqual(saved["input"], "https://chatgpt.com/c/draft")
        app._show_batch_processing_dialog()
        self.assertEqual(app._batch_processing_dialog.links_text.get("1.0", "end-1c"), saved["input"])
        app._batch_processing_dialog.close()
        app._save_batch_draft(None)
        self.assertIsNone(app._load_batch_draft())

    def test_failed_batch_items_write_local_history(self):
        app = self.app()
        from gui.batch_processing import BatchProcessingQueue
        plan = link_plan(1)
        item = BatchProcessingQueue._items(plan)[0]
        item.update(status="failed", error="网页连接超时", elapsed_seconds=5, fetch_seconds=5)
        app._batch_item_done(dict(kind="links"), item)
        layouts.GUIResponsiveGeometryTests._flush(self.root, 120)
        self.assertEqual(len(app.history_records), 1)
        self.assertFalse(app.history_records[0]["succeeded"])
        self.assertEqual(app.history_store.load()[0]["error"], "网页连接超时")

    def test_closing_application_rejects_new_single_tasks_and_editors(self):
        app = self.app()
        app._closing_application = True
        with patch("gui.app.threading.Thread") as thread, patch("gui.app.messagebox.showwarning") as warning:
            app._on_start_generate()
            app._on_direct_summary()
            app._show_batch_processing_dialog()
        thread.assert_not_called()
        warning.assert_not_called()

    def app(self):
        settings = layouts._SettingsStore()
        self.addCleanup(settings.scratch.cleanup)
        with patch("gui.app.WindowsCredentialStore", return_value=layouts._CredentialStore()), \
                patch("gui.app.WindowsAppSettingsStore", return_value=settings):
            app = AIMemoryGUI(self.root)
        self.root.update()
        return app

    def test_batch_entry_is_available_while_single_task_is_running_and_does_not_change_it(self):
        app = self.app()
        app.is_running = True
        token = app._generation_cancel_event
        app._show_batch_processing_dialog()
        self.root.update()
        self.assertTrue(app._batch_processing_dialog.winfo_exists())
        self.assertEqual(app.batch_capture_button.cget("text"), "批量处理")
        self.assertIs(app._generation_cancel_event, token)
        self.assertTrue(app.is_running)

    def test_single_capture_and_queue_share_only_browser_stage_lock(self):
        app = self.app()
        app._batch_browser_lock.acquire()
        called = threading.Event()
        async def capture():
            called.set()
            return "done"
        app._fetch_with_cancellation = lambda coro: coro
        result = []
        def run():
            loop = asyncio.new_event_loop()
            try:
                result.append(app._run_browser_fetch(loop, capture))
            finally:
                loop.close()
        worker = threading.Thread(target=run)
        worker.start()
        self.assertFalse(called.wait(.15))
        app._batch_browser_lock.release()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, ["done"])
        self.assertTrue(app._batch_browser_lock.acquire(blocking=False))
        app._batch_browser_lock.release()

    def test_submit_edit_and_complete_keep_single_task_snapshot_and_write_isolated_history(self):
        from tests.test_batch_processing import BatchQueueTests
        async def capture(links, root, **options):
            records = []
            for index, link in enumerate(links, 1):
                record = BatchQueueTests.complete_record(self, root, index, link, options["save_raw"][index - 1])
                options["on_result"](record)
                records.append(record)
            return records
        app = self.app()
        app.is_running = True
        token = app._generation_cancel_event
        held = True
        app._batch_browser_lock.acquire()
        try:
            with tempfile.TemporaryDirectory() as temporary, patch("gui.app.filedialog.askdirectory", return_value=temporary), \
                    patch("gui.batch_processing.capture_links", capture):
                self.assertTrue(app._submit_batch(link_plan(1), self.root))
                queue = app._batch_queue
                batch_id = queue.snapshot()[0]["id"]
                self.assertEqual(queue.snapshot()[0]["status"], "queued")
                app._edit_batch(batch_id)
                editor = app._batch_processing_dialog
                editor.rows[0]["variable"].set("https://chatgpt.com/c/edited")
                editor.concurrency.set(1)
                editor.submit()
                self.assertEqual(queue.snapshot()[0]["items"][0]["source"], "https://chatgpt.com/c/edited")
                self.assertEqual(queue.snapshot()[0]["concurrency"], 1)
                self.assertIs(app._generation_cancel_event, token)
                self.assertTrue(app.is_running)
                app._batch_browser_lock.release()
                held = False
                deadline = time.monotonic() + 3
                while queue.has_work and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(.01)
                layouts.GUIResponsiveGeometryTests._flush(self.root, 120)
                self.assertEqual(queue.snapshot()[0]["status"], "completed")
                self.assertEqual(len(app.history_records), 1)
                self.assertTrue(app.app_settings.history_file.is_file())
                self.assertTrue(Path(app.history_records[0]["saved_files"][0]).is_file())
                queue.close()
                self.assertTrue(queue.wait(2))
        finally:
            if held:
                app._batch_browser_lock.release()

    def test_batch_prompts_are_serialized_and_cancelled_requests_release_waiters(self):
        app = self.app()
        tokens = [threading.Event(), threading.Event()]
        shown, replies, results = [], [], []
        def factory(done):
            dialog = tk.Toplevel(self.root)
            shown.append(dialog)
            replies.append(done)
            return dialog
        workers = [threading.Thread(target=lambda i=i: results.append(app._wait_batch_prompt(factory, tokens[i])), daemon=True)
                   for i in range(2)]
        for worker in workers:
            worker.start()
        deadline = time.monotonic() + 2
        while not shown and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertEqual(len(shown), 1)
        replies[0](True)
        deadline = time.monotonic() + 2
        while len(shown) < 2 and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertEqual(len(shown), 2)
        replies[1](False)
        for worker in workers:
            worker.join(1)
        layouts.GUIResponsiveGeometryTests._flush(self.root, 120)
        self.assertCountEqual(results, [True, False])
        self.assertFalse(app._batch_prompt_active)

    def test_cancelling_visible_prompt_releases_window_and_worker(self):
        app = self.app()
        token = threading.Event()
        outcomes, shown = [], []
        def factory(done):
            dialog = tk.Toplevel(self.root)
            shown.append(dialog)
            return dialog
        def run():
            try:
                app._wait_batch_prompt(factory, token)
            except BaseException as error:
                outcomes.append(error)
        worker = threading.Thread(target=run)
        worker.start()
        deadline = time.monotonic() + 2
        while not shown and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(shown)
        token.set()
        worker.join(2)
        layouts.GUIResponsiveGeometryTests._flush(self.root, 120)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(outcomes[0], asyncio.CancelledError)
        self.assertFalse(shown[0].winfo_exists())
        self.assertFalse(app._batch_prompt_active)


def batch_view(key, status="queued"):
    return dict(id=key, kind="links", concurrency=3, started=status != "queued", editing=False,
                status=status, done=2 if status == "completed" else 0, total=2,
                failed=0, warnings=0, output_dir="output", items=[
                    dict(index=1, source="https://chatgpt.com/c/first", modes=["raw"], status=status,
                         message="", error=None, warnings=[], output_dir=None),
                    dict(index=2, source="https://chatgpt.com/c/second", modes=["raw"], status=status,
                         message="", error=None, warnings=[], output_dir=None)])


class BatchQueueCardTests(_TkTests):
    def test_auto_card_shows_dynamic_limit_and_adjustment_reason(self):
        board = BatchQueuePanel(self.root, on_edit=Mock(), on_remove=Mock(), on_move=Mock(), on_open=Mock())
        board.pack(fill=tk.BOTH, expand=True)
        view = batch_view("auto", "running")
        view.update(kind="files", requested_concurrency=None, concurrency=4, summaries=2,
                    auto_status={"reason":"接口正常运行", "last_adjustment":"接口限流，降低容量并按服务端提示冷却"})
        board.set_batches([view])
        self.root.update()
        self.assertIn("2 项处理中", board.cards["auto"]["preview_text"])
        self.assertIn("上限 4", board.cards["auto"]["preview_text"])
        self.assertIn("接口正常运行", board.cards["auto"]["tooltip"]._text)
        self.assertIn("上次调整：接口限流", board.cards["auto"]["tooltip"]._text)

    def test_drag_previews_follow_pointer_and_mark_target_before_committing(self):
        move = Mock()
        board = BatchQueuePanel(self.root, on_edit=Mock(), on_remove=Mock(), on_move=move, on_open=Mock())
        board.pack(fill=tk.BOTH, expand=True)
        board.set_batches([batch_view("one"), batch_view("two")])
        self.root.geometry(f"{board.minimum_width + 30}x500")
        self.root.update()
        source, target = [board.cards[key]["frame"] for key in ("two", "one")]
        board._drag_start("two", SimpleNamespace(x_root=source.winfo_rootx(), y_root=source.winfo_rooty()))
        point = SimpleNamespace(x_root=target.winfo_rootx()+20, y_root=target.winfo_rooty()+20)
        board._drag_motion(point)
        self.root.update()
        self.assertIsNotNone(board._drag_preview)
        self.assertEqual(board._drag_target, "one")
        move.assert_not_called()
        board._drag_end(point)
        self.assertIsNone(board._drag_preview)
        move.assert_called_once_with("two", "one")

    def test_drag_outside_target_or_over_completed_batch_does_not_reorder(self):
        move = Mock()
        board = BatchQueuePanel(self.root, on_edit=Mock(), on_remove=Mock(), on_move=move, on_open=Mock())
        board.pack(fill=tk.BOTH, expand=True)
        board.set_batches([batch_view("one"), batch_view("two")])
        self.root.geometry(f"{board.minimum_width + 30}x500")
        self.root.update()
        source, target = [board.cards[key]["frame"] for key in ("two", "one")]
        start = SimpleNamespace(x_root=source.winfo_rootx(), y_root=source.winfo_rooty())
        over = SimpleNamespace(x_root=target.winfo_rootx()+20, y_root=target.winfo_rooty()+20)
        outside = SimpleNamespace(x_root=0, y_root=0)
        board._drag_start("two", start)
        board._drag_motion(over)
        board._drag_motion(outside)
        self.assertIsNone(board._drag_target)
        board._drag_end(outside)
        move.assert_not_called()
        board._drag_start("two", start)
        board._drag_motion(over)
        board.set_batches([batch_view("one", "completed"), batch_view("two")])
        board._drag_end(over)
        move.assert_not_called()

    def test_details_open_for_active_and_finished_batches_with_errors_and_result_action(self):
        opened = Mock()
        board = BatchQueuePanel(self.root, on_edit=Mock(), on_remove=Mock(), on_move=Mock(), on_open=opened)
        board.pack(fill=tk.BOTH, expand=True)
        for status in ("running", "completed", "failed", "cancelled"):
            with self.subTest(status=status):
                view = batch_view("details", status)
                view["items"][0].update(status="failed", error="下载失败", warnings=["附件不可用"], output_dir="output/item")
                board.set_batches([view])
                board.cards["details"]["edit"].invoke()
                self.root.update()
                dialog = next(widget for widget in board.winfo_children() if isinstance(widget, tk.Toplevel))
                text = next(widget for widget in dialog.winfo_children() if isinstance(widget, tk.Text))
                content = text.get("1.0", "end")
                self.assertIn("https://chatgpt.com/c/first", content)
                self.assertIn("下载失败", content)
                self.assertIn("附件不可用", content)
                toolbar = dialog.winfo_children()[0]
                next(widget for widget in toolbar.winfo_children() if isinstance(widget, tk.Button)).invoke()
                opened.assert_called_with("output")
                dialog.destroy()

    def test_connection_error_is_readable_and_call_log_is_hidden_until_requested(self):
        board = BatchQueuePanel(self.root, on_edit=Mock(), on_remove=Mock(), on_move=Mock(), on_open=Mock())
        view = batch_view("failed", "failed")
        view["items"][0].update(error="Page.goto: net::ERR_CONNECTION_TIMED_OUT\nCall log: technical")
        board.set_batches([view])
        board._edit("failed")
        dialog = next(widget for widget in board.winfo_children() if isinstance(widget, tk.Toplevel))
        text = next(widget for widget in dialog.winfo_children() if isinstance(widget, tk.Text))
        self.assertIn("网页连接超时", text.get("1.0", "end"))
        self.assertTrue(text.tk.getboolean(text.tag_cget("technical", "elide")))
        toolbar = dialog.winfo_children()[0]
        next(widget for widget in toolbar.winfo_children() if isinstance(widget, tk.Checkbutton)).invoke()
        self.assertFalse(text.tk.getboolean(text.tag_cget("technical", "elide")))
        dialog.destroy()

    def test_cards_keep_actions_visible_in_two_and_three_columns_and_completed_last(self):
        for scaling in (1, 4 / 3, 2, 8 / 3):
            with self.subTest(scaling=scaling):
                self.root.tk.call("tk", "scaling", scaling)
                board = BatchQueuePanel(self.root, on_edit=Mock(), on_remove=Mock(), on_move=Mock(), on_open=Mock())
                board.pack(fill=tk.BOTH, expand=True)
                views = [batch_view("done", "completed"), batch_view("active", "running")] + [batch_view(str(i)) for i in range(6)]
                board.set_batches(views)
                self.assertEqual(board.views[-1]["id"], "done")
                for columns in (2, 3):
                    self.root.geometry(f"{columns * board.minimum_card_width + 50}x700")
                    self.root.update()
                    self.assertEqual(board._columns, columns)
                    for card in board.cards.values():
                        frame = card["frame"]
                        self.assertLessEqual(frame.winfo_x() + frame.winfo_width(), board.area.canvas.winfo_width())
                        for name in ("edit", "remove"):
                            button = card[name]
                            self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
                            self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), frame.winfo_rootx() + frame.winfo_width())
                        for name in ("title", "status", "counts"):
                            label = card[name]
                            font = tkfont.Font(master=label, font=label.cget("font"))
                            self.assertLessEqual(font.measure(label.cget("text")), label.winfo_width())
                board.destroy()

    def test_progress_updates_retain_widgets_and_drag_changes_only_pending_order(self):
        move = Mock()
        board = BatchQueuePanel(self.root, on_edit=Mock(), on_remove=Mock(), on_move=move, on_open=Mock())
        board.pack(fill=tk.BOTH, expand=True)
        board.set_batches([batch_view("one"), batch_view("two")])
        self.root.geometry(f"{board.minimum_width + 30}x500")
        self.root.update()
        first = board.cards["one"]["frame"]
        board.set_batches([batch_view("one"), batch_view("two")])
        self.assertIs(board.cards["one"]["frame"], first)
        board._drag_start("two", None)
        with patch.object(board, "winfo_containing", return_value=first):
            board._drag_end(SimpleNamespace(x_root=1, y_root=1))
        move.assert_called_once_with("two", "one")
        board.set_batches([batch_view("one", "running"), batch_view("two")])
        board._drag_start("one", None)
        self.assertEqual(board._drag, "one")
        board._clear_drag()


if __name__ == "__main__":
    unittest.main()
