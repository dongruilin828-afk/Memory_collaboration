"""Prepare this round's GUI exports for the existing summary runner, without copying media."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gui.service import generate_raw_markdown
from scripts.gemini_summarizer import load_exported_markdown
from tests.manual_doubao_review import CASES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', type=int, nargs='+', required=True)
    args = parser.parse_args()
    batch = args.output.resolve()
    manifest_path = batch / 'manifest.json'
    records = json.loads(manifest_path.read_text(encoding='utf-8'))
    for number in args.cases:
        case = f'{number:02}'
        source = batch / '人工抓取' / case / 'AI_memory_export.md'
        target = batch / case
        target.mkdir(exist_ok=True)
        if (target / 'result.json').exists():
            raise RuntimeError(f'{case}已有结果，不覆盖')
        messages = load_exported_markdown(source)
        files = {f'../人工抓取/{case}/{p.relative_to(source.parent).as_posix()}':
                 hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in source.parent.rglob('*') if p.is_file() and p != source}
        for message in messages:
            message['content'] = message['content'].replace(
                '](./AI_memory_export_images/', f'](../人工抓取/{case}/AI_memory_export_images/')
        warning = '本次GUI输入有25张低清截图、6张原尺寸图片；不能据文件存在认定逐字OCR正确。'
        payload = {'url': CASES[number-1], 'messages': messages, 'files': files,
                   'image_map': {ref: ref for ref in files}, 'document_map': {},
                   'error': None, 'warnings': [warning], 'capture_mode': 'manual_GUI',
                   'gui_source': source.relative_to(batch).as_posix(),
                   'gui_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        (target / 'result.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        generate_raw_markdown(messages, target / 'export.md')
        records = [r for r in records if r['case'] != case] + [
            {'case': case, 'url': payload['url'], 'capture_mode': 'manual_GUI',
             'messages': len(messages), 'images': len(files), 'documents': 0,
             'error': None, 'warnings': [warning], 'gui_source': payload['gui_source']}]
        print(case, 'GUI messages', len(messages), 'images', len(files))
    manifest_path.write_text(json.dumps(sorted(records, key=lambda r:r['case']), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
