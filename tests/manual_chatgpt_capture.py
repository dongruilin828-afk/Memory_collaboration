"""Serial live ChatGPT capture; no summary APIs or credential-store access."""
import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.async_api import async_playwright
from gui.service import launch_browser_context, _set_browser_window_state, fetch_chat_pipeline, generate_raw_markdown
from gui.chatgpt_capture import capture_conversation
from scripts.providers.chatgpt_source import read_conversation


def cases_from_file(path):
    text = path.read_text(encoding="utf-8-sig").split("终章", 1)[0]
    cases, title = [], ""
    for line in text.splitlines():
        heading = re.match(r"\s*\d+\.\s*(.+)", line)
        if heading:
            title = heading[1]
        match = re.search(r"https?://chatgpt\.com/\S+", line)
        if match:
            url = match[0].replace("http://", "https://")
            cases.append({"case": f"{len(cases)+1:02}", "title": title, "url": url,
                          "route": "分享页" if "/share/" in url else "会话页"})
    return cases


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path.home()/"Desktop"/"结果保存"/
                        f"gpt_revise_{datetime.now():%Y%m%d_%H%M%S}"/"live")
    parser.add_argument("--links", type=Path, default=ROOT/"tests/drl_tests.txt")
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--profile", type=Path, default=ROOT/".browser_user_data")
    parser.add_argument("--pipeline", action="store_true", help="Exercise the complete GUI pipeline, using its normal browser fallback")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/"sources").mkdir(exist_ok=True)
    selected = {s.zfill(2) for s in args.cases or []}
    cases = [c for c in cases_from_file(args.links) if not selected or c["case"] in selected]
    manifest_path = args.output/"manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    async with async_playwright() as pw:
        context = None
        try:
            if not args.pipeline:
                context, _ = await launch_browser_context(pw, headless=False, viewport={"width":1440,"height":1000},
                    no_viewport=False, start_minimized=True, profile_root=args.profile)
                page = await context.new_page()
                await _set_browser_window_state(page, "minimized")
                await page.goto(cases_from_file(args.links)[0]["url"], wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(4000)
            for case in cases:
                target = args.output/case["case"]
                target.mkdir(exist_ok=True)
                started = time.perf_counter()
                with (target/"run.log").open("w", encoding="utf-8") as log:
                    def logger(message):
                        line = f'[{case["case"]}] {message}'
                        log.write(line+"\n"); log.flush(); print(line, flush=True)
                    try:
                        if args.pipeline:
                            result = asdict(await fetch_chat_pipeline(case["url"], browser_profile_root=args.profile,
                                image_output_dir=target/"images", image_reference_base=target,
                                document_output_dir=target/"documents", document_reference_base=target,
                                login_confirmation_callback=lambda: False, logger=logger))
                        else:
                            source = await read_conversation(page, case["url"])
                            (args.output/"sources"/(case["case"]+".json")).write_text(json.dumps({"status":200,"data":source,
                                "audit_record":{**case,"retrieved_at":datetime.now(timezone.utc).isoformat()}}, ensure_ascii=False, indent=2), encoding="utf-8")
                            result = await capture_conversation(page, case["url"], source,
                                images_dir=target/"images", image_prefix="./images",
                                documents_dir=target/"documents", document_prefix="./documents", logger=logger)
                            result["error"] = None
                        (target/"snapshot.html").write_text(result.pop("html") or "", encoding="utf-8")
                        result.update(url=case["url"], elapsed=time.perf_counter()-started,
                            files={p.relative_to(target).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                                   for folder in ("images","documents") for p in (target/folder).glob("*") if p.is_file()})
                        (target/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                        if result.get("messages"):
                            generate_raw_markdown(result["messages"], target/"export.md")
                        record = {**case,"messages":len(result.get("messages",[])),"error":result.get("error"),
                                  "warnings":result.get("warnings",[]),"elapsed":result["elapsed"]}
                    except Exception as error:
                        record = {**case,"error":f"{type(error).__name__}: {error}","elapsed":time.perf_counter()-started}
                        if not args.pipeline:
                            try:
                                diagnostics = await page.evaluate('''()=>({url:location.pathname,title:document.title,
                                    messages:Array.from(document.querySelectorAll('[data-chatgpt-search-unit-key],[data-message-author-role]')).map(n=>({
                                        id:n.getAttribute('data-message-id'),key:n.getAttribute('data-chatgpt-search-unit-key'),
                                        ids:n.getAttribute('data-chatgpt-search-message-ids'),text:n.innerText.slice(0,180),length:n.innerText.length})),
                                    scrollers:Array.from(document.querySelectorAll('main *')).filter(n=>n.clientHeight>200&&n.scrollHeight>n.clientHeight+100)
                                        .map(n=>({tag:n.tagName,classes:n.className,top:n.scrollTop,height:n.clientHeight,total:n.scrollHeight,
                                            overflow:getComputedStyle(n).overflowY,direction:getComputedStyle(n).flexDirection})).slice(0,30)})''')
                                (target/'render_diagnostics.json').write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2),encoding='utf-8')
                            except Exception:
                                pass
                        # A failed retry must not leave an older successful JSON
                        # looking like the output of the current attempt.
                        (target/"result.json").write_text(json.dumps({**record,"messages":[],"image_map":{},
                            "document_map":{},"warnings":[],"files":{}}, ensure_ascii=False, indent=2), encoding="utf-8")
                    logger(json.dumps(record, ensure_ascii=False))
                    manifest = sorted([r for r in manifest if r["case"]!=case["case"]]+[record], key=lambda r:r["case"])
                    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            if context:
                await context.close()
    if any(r.get("error") or r.get("warnings") for r in manifest if not selected or r["case"] in selected):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
