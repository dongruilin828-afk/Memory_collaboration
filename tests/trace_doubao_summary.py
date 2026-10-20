"""Observe summary responses without changing requests, configuration or parsed output."""
import argparse
import asyncio
import json
import sys
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import gemini_summarizer as summary
from tests import manual_doubao_review as runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--case', required=True, type=int)
    parser.add_argument('--provider', choices=['siliconflow', 'deepseek'], default='siliconflow')
    args = parser.parse_args()
    diagnostic = args.output.resolve()/'diagnostics'/f'{args.case:02d}_响应观察'
    diagnostic.mkdir(parents=True, exist_ok=True)
    original = summary.urlopen
    serial = 0

    class ObservedResponse:
        def __init__(self, response, host, source_review, synthesis):
            self.response, self.host, self.source_review = response, host, source_review
            self.synthesis = synthesis

        def __enter__(self):
            self.response.__enter__()
            return self

        def __exit__(self, *exc):
            return self.response.__exit__(*exc)

        def read(self, *params):
            nonlocal serial
            body = self.response.read(*params)
            serial += 1
            record = {'sequence': serial, 'host': self.host, 'bytes': len(body)}
            try:
                data = json.loads(body)
                choice = data['choices'][0]
                content = choice['message']['content']
                record.update(model=data.get('model'), finish_reason=choice.get('finish_reason'), usage=data.get('usage'),
                              content_characters=len(content))
                parsed = summary._parse_json_object(content)
                record['parse_success'] = True
                if self.synthesis:
                    record['stage'] = 'global_synthesis'
                    path = diagnostic/f'synthesis_{serial:03d}_{hashlib.sha256(body).hexdigest()[:10]}.json'
                    path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding='utf-8')
                    record['parsed_file'] = path.name
                if self.source_review:
                    record['stage'] = 'source_review'
                    record['review_items'] = parsed.get('items')
            except Exception as error:
                record.update(parse_success=False, parse_error=type(error).__name__)
                path = diagnostic/f'response_{serial:03d}_{hashlib.sha256(body).hexdigest()[:10]}.txt'
                # Responses contain generated data only; never save requests or Authorization.
                path.write_bytes(body)
                record['response_file'] = path.name
            with (diagnostic/'responses.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False)+'\n')
            return body

    def observed(request, **options):
        host = urlsplit(request.full_url).hostname
        if host not in {'api.siliconflow.cn', 'api.deepseek.com'}:
            raise RuntimeError('本轮仅授权硅基流动与DeepSeek')
        payload = json.loads(request.data)
        user_content = payload.get('messages', [{}])[-1].get('content')
        source_review = isinstance(user_content, str) and user_content.startswith('核对豆包最终总结')
        synthesis = isinstance(user_content, str) and '分批记忆：' in user_content and '最近上下文：' in user_content
        return ObservedResponse(original(request, **options), host, source_review, synthesis)

    summary.urlopen = observed
    sys.argv = ['manual_doubao_review.py', '--output', str(args.output.resolve()),
                '--summary-only', '--force-summary', '--preferred-provider', args.provider,
                '--cases', str(args.case)]
    try:
        asyncio.run(runner.main())
    finally:
        summary.urlopen = original


if __name__ == '__main__':
    main()
