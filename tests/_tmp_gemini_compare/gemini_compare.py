"""Read-only structural golden comparison; only CRLF/U+200B are ignored."""
import difflib
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from functools import lru_cache
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(r'C:\Users\东东\Desktop\结果保存\全量重跑_20261026_44e087b\Gemini')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'results/gpt_revise_20261023/render_deps'))
from bs4 import BeautifulSoup
from PIL import Image
from markdown_it import MarkdownIt
from scripts.providers import gemini
from gui.service import _clean_attachment_display

RIGHT = ROOT / 'tests/Right/01_Gemini_Right'
SEPARATOR = re.compile(r'\n<hr style="border: 0; border-top: 5px solid #[A-Fa-f0-9]{6}; margin: 48px 0 24px 0;">\n\n## (🔵 👤 用户提问|🟣 🤖 AI 回答)\n\n')
LINK = re.compile(r'!?\[[^\]\n]*(?:\\\][^\]\n]*)*\]\((<?[^\n]+?>?)\)')
PARSER = MarkdownIt('commonmark', {'html': True})

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def normalize(text):
    return text.replace('\r\n', '\n').replace('\r', '\n').replace('\u200b', '')

def messages(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    marks = list(SEPARATOR.finditer(text))
    assert marks, 'No export message separators'
    result = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        content = text[mark.end():end]
        if content.endswith('\n\n'):
            content = content[:-2]
        result.append({'role': 'User' if mark[1].startswith('🔵') else 'AI', 'content': content})
    return result

def file_map(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for kind in ('images', 'documents') for p in (folder / kind).glob('*') if p.is_file()}

@lru_cache(maxsize=None)
def image_identity(path):
    with Image.open(path) as image:
        frames = []
        for index in range(getattr(image, 'n_frames', 1)):
            image.seek(index)
            frames.append((image.size, image.info.get('duration'), hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest()))
        return hashlib.sha256(repr(frames).encode()).hexdigest()

@lru_cache(maxsize=None)
def file_identity(path):
    if path.parent.name == 'images':
        return 'image-pixels:' + image_identity(path)
    if path.suffix.lower() in {'.py', '.txt', '.md', '.json', '.csv', '.yaml', '.yml', '.js', '.ts', '.css', '.html', '.xml'}:
        try:
            # Keep BOM, indentation and blank lines; only line encoding/ZWSP
            # are accepted, and raw-byte differences are still reported.
            text = path.read_bytes().decode('utf-8')
            return 'document-text:' + hashlib.sha256(normalize(text).encode('utf-8')).hexdigest()
        except UnicodeDecodeError:
            pass
    return 'asset-sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()

def destination(ref):
    ref = ref.strip()
    if ref.startswith('<'):
        return ref[1:ref.find('>')]
    return re.sub(r'\s+[\'\"].*[\'\"]$', '', ref)

def local_path(root, ref):
    parsed = urlparse(ref)
    if parsed.scheme or ref.startswith(('#', '//')):
        return None
    candidate = (root / unquote(parsed.path)).resolve()
    if not candidate.is_relative_to(root.resolve()):
        return None
    return candidate

def canonical_assets(text, root):
    broken = []
    used = []
    valid_refs = set()
    def walk(tokens):
        for token in tokens:
            if token.type in {'image', 'link_open'}:
                ref = token.attrGet('src' if token.type == 'image' else 'href')
                valid_refs.update((ref, unquote(ref)))
            if token.children:
                walk(token.children)
    walk(PARSER.parse(text))
    def replace(match):
        ref = destination(match[1])
        if ref not in valid_refs:
            return match[0]
        path = local_path(root, ref)
        if path is None:
            return match[0]
        if not path.is_file():
            broken.append(ref)
            return match[0]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        identity = file_identity(path)
        used.append({'reference': ref, 'sha256': digest, 'content_identity': identity})
        return match[0].replace(ref, identity)
    return LINK.sub(replace, normalize(text)), broken, used

def inventory():
    result = {}
    for p in sorted(RIGHT.rglob('*')):
        if p.is_file():
            result[p.relative_to(RIGHT).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result

def main():
    output = Path(read(HERE / 'output_location.json')['output'])
    report = HERE / 'report'
    report.mkdir(exist_ok=True)
    provenance = read(output / 'run_provenance.json')
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == digest for p, digest in provenance['code_hashes'].items())
    baseline = read(HERE / 'reference_hashes.json')
    assert inventory() == baseline, 'Standard answers changed during capture'
    rows = []
    manifest = {c['case']: c for c in read(output / 'manifest.json')}
    for case in provenance['cases']:
        number = case['case']
        candidates = [p for p in RIGHT.iterdir() if p.is_dir() and re.match(r'^' + number + r'(?:_|$)', p.name)]
        assert len(candidates) == 1, (number, candidates)
        expected_dir, actual_dir = candidates[0], output / f'{number}_live'
        row = {**case, 'reference_directory': expected_dir.name, 'issues': [], 'messages_checked': []}
        if number not in manifest:
            row['issues'].append('尚未执行')
            rows.append(row)
            continue
        record = manifest[number]
        result = read(actual_dir / 'result.json')
        row.update(error=result.get('error'), warnings=result.get('warnings') or [], elapsed=record['elapsed'])
        if result.get('error'):
            row['issues'].append('抓取失败：' + result['error'])
        expected_text = (expected_dir / 'export.md').read_text(encoding='utf-8-sig')
        expected = messages(expected_text)
        actual = result.get('messages') or []
        row.update(expected_messages=len(expected), actual_messages=len(actual))
        actual_files, expected_files = file_map(actual_dir), file_map(expected_dir)
        for kind in ('images', 'documents'):
            af = {p: sha for p, sha in actual_files.items() if p.startswith(kind + '/')}
            ef = {p: sha for p, sha in expected_files.items() if p.startswith(kind + '/')}
            ac, ec = Counter(af.values()), Counter(ef.values())
            row[kind] = {'actual': len(af), 'expected': len(ef), 'hash_multiset_equal': ac == ec,
                'missing_hashes': list((ec - ac).elements()), 'extra_hashes': list((ac - ec).elements()),
                'actual_files': af, 'expected_files': ef}
            if kind == 'images':
                ap = Counter(image_identity(actual_dir / p) for p in af)
                ep = Counter(image_identity(expected_dir / p) for p in ef)
                row[kind]['decoded_pixels_equal'] = ap == ep
                row[kind]['missing_pixel_hashes'] = list((ep - ap).elements())
                row[kind]['extra_pixel_hashes'] = list((ap - ep).elements())
            else:
                ap = Counter(file_identity(actual_dir / p) for p in af)
                ep = Counter(file_identity(expected_dir / p) for p in ef)
                row[kind]['content_equal_after_text_format_normalization'] = ap == ep
            if ac != ec and ap != ep:
                row['issues'].append(kind + '附件内容或数量不同')
        if result.get('files') != actual_files:
            row['issues'].append('本轮文件清单与实际文件不符')
        if len(expected) != len(actual):
            row['issues'].append('消息数量不同')
        for index, (a, e) in enumerate(zip(actual, expected), 1):
            ac, broken, used = canonical_assets(a['content'], actual_dir)
            ec, reference_broken, reference_used = canonical_assets(e['content'], expected_dir)
            status = '逐字一致' if a['content'] == e['content'] else ('仅换行编码或零宽空格' if normalize(a['content']) == normalize(e['content']) else ('仅附件路径或编码变化' if ac == ec else '正文差异'))
            # Keep attachment content differences separate from prose, while
            # preserving each link's label, position and number of occurrences.
            text_equal = re.sub(r'(?:image-pixels|asset-sha256|document-text):[0-9a-f]{64}', '<ASSET>', ac) == re.sub(r'(?:image-pixels|asset-sha256|document-text):[0-9a-f]{64}', '<ASSET>', ec)
            if ac != ec and text_equal:
                status = '文字结构一致，附件内容不同'
            checked = {'index': index, 'role': a['role'], 'expected_role': e['role'], 'status': status,
                'broken_local_links': broken, 'reference_broken_links': reference_broken,
                'used_files': used, 'reference_used_files': reference_used}
            if ac != ec or a['role'] != e['role']:
                checked['diff'] = list(difflib.unified_diff(ec.splitlines(), ac.splitlines(), fromfile='标准答案', tofile='本轮结果', lineterm=''))
                row['issues'].append(f'第{index}条' + ('附件像素或文件内容不同' if text_equal and a['role'] == e['role'] else '正文或角色不同'))
            if broken:
                row['issues'].append(f'第{index}条有失效本地附件链接')
            row['messages_checked'].append(checked)
        if actual:
            export_path = actual_dir / 'export.md'
            exported = messages(export_path.read_text(encoding='utf-8'))
            row['markdown_roundtrip_equal'] = exported == [{'role': m['role'], 'content': m['content'].replace('\r\n', '\n').replace('\r', '\n')} for m in actual]
            if not row['markdown_roundtrip_equal']:
                row['issues'].append('保存的Markdown回读结构不同')
            parsed = gemini.parse_messages(BeautifulSoup((actual_dir / 'snapshot.html').read_text(encoding='utf-8'), 'html.parser'),
                {**result['image_map'], **result['document_map']})
            if parsed:
                _clean_attachment_display(parsed, [])
            row['html_roundtrip_equal'] = parsed == actual
            if not row['html_roundtrip_equal']:
                row['issues'].append('保存的HTML回读与结果不同（需核查附件替换阶段）')
        row['issues'] = list(dict.fromkeys(row['issues']))
        row['message_status_counts'] = dict(Counter(m['status'] for m in row['messages_checked']))
        write(report / 'cases' / (number + '.json'), row)
        rows.append(row)
        print(number, 'messages', len(actual), '/', len(expected), 'issues', len(row['issues']), flush=True)
    write(report / 'comparison.json', {'cases': rows, 'unmatched_cases': [c['case'] for c in rows if c['issues']],
        'production_code_unchanged': True, 'reference_files_unchanged': True})

if __name__ == '__main__':
    if '--inventory' in sys.argv:
        write(HERE / 'reference_hashes.json', inventory())
        print('Reference hashes saved')
    else:
        main()


