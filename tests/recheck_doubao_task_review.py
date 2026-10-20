"""Recheck the actual saved text candidates after the evidence-window repair; no media calls."""
import argparse
import copy
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gui.credential_store import WindowsCredentialStore
from scripts import gemini_summarizer as summary
from scripts.doubao_summary import prepare_text_gateway, review_summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();batch=args.output.resolve();folder=batch/'08'
    result=json.loads((folder/'AI_memory_result.json').read_text(encoding='utf-8'))
    messages=json.loads((folder/'result.json').read_text(encoding='utf-8'))['messages']
    assert result['conversation']['source_fingerprint']==summary.messages_fingerprint(messages)
    diagnostic=batch/'diagnostics/08_最终审核前';diagnostic.mkdir(exist_ok=True)
    backup=diagnostic/'AI_memory_result.json'
    if backup.exists():raise RuntimeError('已有复核备份，不重复覆盖')
    backup.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    before=copy.deepcopy(result['media'])
    checks=result['processing']['doubao_source_review']['checks']
    originals=[copy.deepcopy(row['original']) for row in checks if row['key'].startswith('completed')]
    assert len(originals)==5
    result['current_state']['completed']=originals
    config=replace(summary.SummaryConfig.from_env(provider_override=result['provider'],model_override=result['model']),retries=2)
    gateway=prepare_text_gateway(summary.create_gateway(config,api_key=WindowsCredentialStore().load_api_keys()[result['provider']]),print)
    original_urlopen=summary.urlopen;serial=0
    class Observed:
        def __init__(self,response):self.response=response
        def __enter__(self):self.response.__enter__();return self
        def __exit__(self,*args):return self.response.__exit__(*args)
        def read(self,*args):
            nonlocal serial
            body=self.response.read(*args);serial+=1
            (diagnostic/f'review_response_{serial}.json').write_bytes(body)
            return body
    def observe(request,**options):
        assert urlsplit(request.full_url).hostname in {'api.deepseek.com','api.siliconflow.cn'}
        return Observed(original_urlopen(request,**options))
    summary.urlopen=observe
    try:review_summary(result,messages,gateway,progress=lambda s:print(s,flush=True))
    finally:summary.urlopen=original_urlopen
    assert result['media']==before, '文字复核不能更改媒体读取结果'
    result['processing']['final_source_recheck']={'source':'恢复本批审核日志中原始完成候选，使用修复后的角色证据窗口重新审核；未重抓或重读媒体',
        'previous_result':str(backup.relative_to(batch)), 'previous_result_sha256':hashlib.sha256(backup.read_bytes()).hexdigest()}
    summary.write_summary_outputs(result,folder/'AI_memory_result.json',folder/'AI_memory_summary.md',include_details=False)
    summary.write_summary_outputs(result,folder/'AI_memory_detailed_result.json',folder/'AI_memory_detailed_summary.md',include_details=True)
    print('08原始候选已按新证据窗口复核，媒体逐项保持。',flush=True)


if __name__=='__main__':main()
