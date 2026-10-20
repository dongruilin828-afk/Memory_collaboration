"""Read-only checks for the 38th Doubao OCR/topic repair batch."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.gemini_summarizer import messages_fingerprint
from scripts.doubao_summary import _topic_role
from scripts.summary_grounding import _plain


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    batch = parser.parse_args().output.resolve()
    load = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
    inventory = load(batch/'batch_inventory.json')
    changed = [s for s, sha in inventory['source_sha256'].items()
               if hashlib.sha256((ROOT/s).read_bytes()).hexdigest() != sha]
    rows = []
    for case in ('07', '08', '21'):
        folder = batch/case
        row = {'case':case, 'errors':[]}
        rows.append(row)
        try:
            captured = load(folder/'result.json')
            result = load(folder/'AI_memory_result.json')
            messages = captured['messages']
            assert result == load(folder/'AI_memory_detailed_result.json'), '两份JSON不一致'
            assert result['conversation']['source_fingerprint'] == messages_fingerprint(messages), '来源指纹错配'
            for name in ('AI_memory_summary.md','AI_memory_simple.md','AI_memory_detailed_summary.md'):
                assert (folder/name).stat().st_size > 0, name+'为空'
            for ref, sha in captured.get('files', {}).items():
                assert hashlib.sha256((folder/unquote(ref)).read_bytes()).hexdigest() == sha, '源文件改变：'+ref
            for topic in result['topics']:
                role = _topic_role(topic)
                evidence = topic.get('source_review', {}).get('evidence', [])
                for e in evidence:
                    if e['source'] in {'user','assistant'}:
                        m = messages[e['message_id']-1]
                        assert e['source'] == ('user' if m['role']=='User' else 'assistant'), '主题证据角色错配'
                        assert e['quote'] in _plain(m['content']), '主题证据不是原文'
                        assert not role or e['source'] == role, '标题与摘录角色错配'
            if case in ('07','08'):
                assert len(result['topics']) == 1, '持续任务仍被拆分'
                topic = result['topics'][0]
                users = [i for i,m in enumerate(messages,1) if m['role']=='User']
                assert topic.get('task_user_message_ids') == users, '用户修改轮次遗漏'
                assert set(topic['memory_ids']) == {m['memory_id'] for m in result['memory_items']}, '合并丢失记忆'
                assert all(t in topic['summary'] for t in ('16：9','9：16','5次')), '修改约束遗漏'
                assert any(not m.get('can_reverify') for m in result['media']), '失效原图状态丢失'
                row['input_limits'] = '本轮GUI：25张低清、6张原尺寸；逐字OCR不能全量验收。'
            row.update(topics=len(result['topics']), memories=len(result['memory_items']),
                       media=len(result['media']), backend=result['provider'],
                       unread_media=[m['media_id'] for m in result['media'] if m['status']!='described'])
        except (OSError, AssertionError, KeyError, ValueError) as error:
            row['errors'].append(str(error))
    report = {'source_files_changed_after_freeze':changed, 'cases':rows,
              'limits':'程序检查覆盖主题、角色、来源和文件。原图专项OCR结果单列diagnostics，不把缩略图当原图验收。'}
    (batch/'三项修复检查.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    main()
