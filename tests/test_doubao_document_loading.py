"""豆包卡片延迟挂载、稳定末尾及一次会话补充加载。"""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from gui import service


def browser(visible=None):
    page = MagicMock()
    page.url = 'https://www.doubao.com/chat/123'
    page.wait_for_timeout = AsyncMock()
    scroller = MagicMock()
    scroller.first = scroller
    scroller.wait_for = AsyncMock()
    scroller.locator.return_value = scroller
    state = {'blocked': True, 'top': 0, 'height': 900, 'ids': ['other']}
    scroller.evaluate = AsyncMock(return_value=state)
    target = MagicMock()
    target.first = target
    target.get_by_text.return_value = target
    target.is_visible = AsyncMock(side_effect=visible or (lambda: False))
    page.locator.side_effect = lambda selector: scroller if 'v_list_scroller' in selector else target
    return page, target, scroller


class DoubaoDocumentLoadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_visible_list_and_message_before_accepting_target(self):
        page, target, scroller = browser(lambda: True)
        with patch.object(service.doubao, 'collect_html', new=AsyncMock()) as collect:
            self.assertTrue(await service._reveal_doubao_document_message(page, '101', '报告'))
        self.assertEqual(scroller.wait_for.await_count, 2)
        self.assertEqual(scroller.wait_for.await_args_list[0].kwargs['state'], 'visible')
        self.assertEqual(scroller.wait_for.await_args_list[1].kwargs['state'], 'attached')
        collect.assert_not_awaited()
        target.get_by_text.assert_called_once_with('报告', exact=True)

    async def test_delayed_target_at_temporarily_blocked_bottom_does_not_need_reload(self):
        page, target, scroller = browser()
        steps = 0

        async def evaluate(script, *_args):
            nonlocal steps
            if 'const before' in script:
                steps += 1
            return {'blocked': True, 'top': 0, 'height': 900, 'ids': ['other']}

        scroller.evaluate.side_effect = evaluate
        target.is_visible.side_effect = lambda: steps >= 2
        with patch.object(service.doubao, 'collect_html', new=AsyncMock()) as collect:
            self.assertTrue(await service._reveal_doubao_document_message(page, '101', '报告'))
        collect.assert_not_awaited()
        self.assertEqual(steps, 2)

    async def test_new_message_ids_reset_bottom_stability(self):
        page, target, scroller = browser()
        steps = 0

        async def evaluate(script, *_args):
            nonlocal steps
            if 'const before' in script:
                steps += 1
            return {'blocked': True, 'top': 0, 'height': 900,
                    'ids': ['new' if steps >= 3 else 'other']}

        scroller.evaluate.side_effect = evaluate
        target.is_visible.side_effect = lambda: steps >= 4
        with patch.object(service.doubao, 'collect_html', new=AsyncMock()) as collect:
            self.assertTrue(await service._reveal_doubao_document_message(page, '101', '报告'))
        collect.assert_not_awaited()
        self.assertEqual(steps, 4)

    async def test_collects_once_then_retries_the_same_message(self):
        ready = False
        page, target, scroller = browser(lambda: ready)

        async def loaded(_page):
            nonlocal ready
            ready = True

        with patch.object(service.doubao, 'collect_html', new=AsyncMock(side_effect=loaded)) as collect:
            self.assertTrue(await service._reveal_doubao_document_message(page, '101', '同名报告'))
        collect.assert_awaited_once_with(page)
        self.assertEqual(target.get_by_text.call_count, 2)
        self.assertTrue(all(call.args == ('同名报告',) for call in target.get_by_text.call_args_list))
        page.get_by_text.assert_not_called()

    async def test_missing_list_or_network_failure_stops_after_one_collection(self):
        for missing_list in (False, True):
            with self.subTest(missing_list=missing_list):
                page, _, scroller = browser()
                if missing_list:
                    scroller.wait_for.side_effect = TimeoutError()
                with patch.object(service.doubao, 'collect_html', new=AsyncMock(side_effect=TimeoutError())) as collect:
                    self.assertFalse(await service._reveal_doubao_document_message(page, '101', '报告'))
                collect.assert_awaited_once_with(page)

    async def test_exhausted_total_budget_does_not_start_collection(self):
        page, _, _ = browser()
        with patch.object(service, 'time', SimpleNamespace(monotonic=MagicMock(side_effect=[0, 0, 121, 121]))), patch.object(
            service.doubao, 'collect_html', new=AsyncMock(),
        ) as collect:
            self.assertFalse(await service._reveal_doubao_document_message(page, '101', '报告'))
        collect.assert_not_awaited()

    async def test_failed_recovery_keeps_existing_attachment_warning(self):
        for message_present in (0, 1):
            with self.subTest(message_present=message_present):
                page, target, _ = browser()
                page.frames = []
                target.count = AsyncMock(return_value=message_present)
                title_node = MagicMock()
                title_node.count = AsyncMock(return_value=0)
                target.get_by_text.return_value = title_node
                with patch.object(service, '_reveal_doubao_document_message', new=AsyncMock(return_value=False)) as reveal:
                    warnings = []
                    mapping, count = await service._save_doubao_ai_documents(
                        page, '', Path('unused'), './documents', warnings, entries=[('缺失报告', '', '101')],
                    )
                self.assertEqual((mapping, count), ({}, 1))
                self.assertIn('未能下载完整正文', warnings[0])
                reveal.assert_awaited_once_with(page, '101', '缺失报告')


if __name__ == '__main__':
    unittest.main()
