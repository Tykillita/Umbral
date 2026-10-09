"""Captura la interfaz real de Umbral; requiere Playwright y una API local offline."""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".production" / "video-work"
CURSOR = r"""(() => {
  addEventListener('DOMContentLoaded', () => {
    const css = document.createElement('style');
    css.textContent = `body,*{cursor:none!important}#tour-pointer{position:fixed;left:0;top:0;width:25px;height:32px;pointer-events:none;z-index:2147483647;filter:drop-shadow(1px 2px 1px #17233766)}.tour-click{position:fixed;width:50px;height:50px;border:4px solid #F7C744;border-radius:50%;pointer-events:none;z-index:2147483646;animation:tour-click .45s ease-out forwards}@keyframes tour-click{from{transform:translate(-50%,-50%) scale(.3);opacity:1}to{transform:translate(-50%,-50%) scale(1.35);opacity:0}}`;
    document.head.append(css);
    const cursor = document.createElement('div');cursor.id='tour-pointer';cursor.setAttribute('aria-hidden','true');
    cursor.innerHTML='<svg viewBox="0 0 25 32"><path d="M2 2L2 26L8.5 20L13 30L17 28L12.5 18L22 18Z" fill="#fffef7" stroke="#172337" stroke-width="2.5" stroke-linejoin="round"/></svg>';
    document.body.append(cursor);
    addEventListener('pointermove',e=>{cursor.style.transform=`translate(${e.clientX}px,${e.clientY}px)`});
    addEventListener('pointerdown',e=>{const ring=document.createElement('div');ring.className='tour-click';ring.style.left=e.clientX+'px';ring.style.top=e.clientY+'px';document.body.append(ring);setTimeout(()=>ring.remove(),500)});
  });
})()"""


def fetch(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=20) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8876")
    parser.add_argument("--chrome", type=Path)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--format", choices=["landscape", "portrait"], default="landscape")
    args = parser.parse_args()
    if not args.base.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise SystemExit("La captura exige loopback.")
    health = fetch(args.base, "/api/v1/health")
    if not health.get("offline") or health.get("dataMode") == "fixture":
        raise SystemExit("La API debe estar offline y servir un snapshot real.")
    topics = fetch(args.base, "/api/v1/topics?limit=30")["items"]
    topic = next((t for t in topics if t["band"] == "alto" and t["evidenceStatus"] == "insuficiente"), topics[0])
    WORK.mkdir(parents=True, exist_ok=True)
    portrait = args.format == "portrait"
    size = {"width": 390, "height": 780} if portrait else {"width": 1440, "height": 820}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(args.chrome) if args.chrome else None)
        context = browser.new_context(viewport=size, device_scale_factor=2 if portrait else 1,
                                      locale="es-PA", timezone_id="America/Panama",
                                      record_video_dir=WORK / f"raw-{args.format}", record_video_size=size)
        requests = []
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(args.base) else (requests.append(route.request.url), route.abort()))
        context.add_init_script(CURSOR)
        page = context.new_page()
        start = time.monotonic()
        events, scenes = [], []
        page.goto(args.base + "/app", wait_until="networkidle")
        page.locator('[data-testid="role-juror"], [data-testid="topic-card"]').first.wait_for(timeout=30000)
        choice = page.get_by_test_id("role-juror")
        if choice.is_visible():
            choice.click()
        page.get_by_test_id("topic-card").first.wait_for(timeout=30000)
        page.wait_for_timeout(1000)
        if args.probe:
            page.screenshot(path=WORK / f"probe-{args.format}.png")
            (WORK / "probe.json").write_text(json.dumps({"topic": topic, "text": page.locator("body").inner_text(), "ids": page.locator("[data-testid]").evaluate_all("els=>els.map(e=>e.dataset.testid)")}, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Captura de inspección lista.")
        else:
            def pause(seconds=1):
                page.wait_for_timeout(seconds * 1000)

            def click(locator):
                locator.scroll_into_view_if_needed()
                pause(.25)
                box = locator.bounding_box()
                x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                page.mouse.move(x, y, steps=22)
                pause(.3)
                events.append({"time": round(time.monotonic() - start, 3), "x": x, "y": y})
                page.mouse.click(x, y)
                pause(.6)

            def begin(name):
                scenes.append({"name": name, "start": round(time.monotonic() - start, 3)})

            def finish():
                scene = scenes[-1]
                scene["duration"] = round(time.monotonic() - start - scene["start"], 3)
                page.screenshot(path=WORK / f"{args.format}-{scene['name']}.png")

            begin("agenda")
            pause(2)
            category = page.get_by_test_id("filter-category")
            if category.count() and category.is_visible():
                click(category)
                pause(.6)
                page.keyboard.press("Escape")
            page.mouse.move(size["width"] * .7, size["height"] * .55, steps=20)
            pause(1)
            page.mouse.wheel(0, 660 if portrait else 620)
            pause(3)
            page.mouse.wheel(0, 380)
            pause(3)
            finish()

            # Navigation is a real app route. Choose one verified high-priority case.
            begin("ficha")
            click(page.locator(f'[data-topic-id="{topic["id"]}"]').get_by_test_id("open-ficha"))
            page.get_by_test_id("ficha").wait_for(timeout=30000)
            pause(1)
            pause(3)
            page.mouse.wheel(0, 410 if portrait else 510)
            pause(4)
            page.mouse.wheel(0, 450)
            pause(3)
            finish()

            page.mouse.wheel(0, -5000)
            pause(.7)
            begin("assistant")
            click(page.get_by_test_id("assistant-toggle"))
            if not portrait:
                click(page.get_by_test_id("assistant-resize"))
            entry = page.get_by_test_id("assistant-input")
            entry.wait_for()
            click(entry)
            entry.press_sequentially("¿Qué falta verificar sobre este tema?", delay=45)
            pause(.4)
            click(page.get_by_test_id("assistant-send"))
            page.get_by_test_id("assistant-answer").last.wait_for(timeout=40000)
            page.get_by_test_id("assistant-answer-text").last.scroll_into_view_if_needed()
            pause(2)
            citations = page.get_by_test_id("assistant-citations").last
            if citations.count():
                citations.scroll_into_view_if_needed()
                pause(2)
            page.get_by_test_id("assistant-passage").first.click()
            pause(2)
            finish()
            close = page.get_by_test_id("assistant-close")
            if close.is_visible():
                click(close)

            begin("draft")
            click(page.get_by_test_id("go-drafts"))
            page.get_by_test_id("draft-generate").wait_for(timeout=30000)
            pause(1)
            pause(2)
            click(page.get_by_test_id("draft-generate"))
            page.get_by_test_id("draft-origin-label").wait_for(timeout=40000)
            pause(3)
            page.get_by_test_id("draft-brief").scroll_into_view_if_needed()
            pause(3)
            click(page.get_by_test_id("draft-angle"))
            page.get_by_test_id("draft-angle").press("End")
            page.get_by_test_id("draft-angle").press_sequentially(" Revisar con la fuente primaria.", delay=25)
            click(page.get_by_test_id("draft-save"))
            pause(1)
            finish()

            reviewer = page.get_by_test_id("review-reviewer")
            reviewer.scroll_into_view_if_needed()
            pause(.7)
            begin("review")
            click(reviewer)
            reviewer.press_sequentially("Equipo de demostración", delay=55)
            click(page.get_by_test_id("review-action-en_revision"))
            page.wait_for_function("document.querySelector('[data-testid=review-status]')?.dataset.status === 'en_revision'")
            pause(2)
            click(page.get_by_test_id("export-markdown"))
            page.get_by_test_id("export-preview").wait_for()
            pause(2)
            finish()

            begin("sources")
            click(page.get_by_test_id("nav-fuentes"))
            page.get_by_test_id("sources-snapshot-id").wait_for(timeout=30000)
            pause(.7)
            pause(3)
            page.mouse.wheel(0, 320 if portrait else 180)
            pause(3)
            finish()
            video = page.video
            context.close()
            path = Path(video.path())
            result = {"snapshotId": health["snapshotId"], "dataMode": health["dataMode"], "offline": True,
                      "topic": {k: topic[k] for k in ["id", "title", "score", "band", "evidenceStatus"]},
                      "size": size, "scenes": scenes, "clicks": events, "externalRequestsBlocked": len(requests), "raw": str(path)}
            (WORK / f"capture-{args.format}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Capturado {args.format}: {len(scenes)} escenas; {len(events)} clics; {len(requests)} solicitudes externas bloqueadas.")
        browser.close()


if __name__ == "__main__":
    main()
