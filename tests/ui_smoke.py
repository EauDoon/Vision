"""Optional real-browser test. Run from repository root: python tests/ui_smoke.py.

Uses a temporary SQLite database and a loopback server with RPC explicitly disabled.
Never reads the operator's database or calls a live RPC. See docs/UI-TESTS.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]


def main():
    try:
        from playwright.sync_api import sync_playwright, expect
    except ImportError:
        raise SystemExit("Optional dependency missing. Install Playwright as described in docs/UI-TESTS.md.")
    with tempfile.TemporaryDirectory(prefix="vision-ui-") as temp:
        env = dict(os.environ)
        env.pop("VISION_RPC_URL", None)
        env.pop("VISION_DB", None)
        proc = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "app.py"), "--port", "0", "--db", str(Path(temp) / "test.sqlite3")],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
        )
        try:
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(proc.stdout.readline()), daemon=True).start()
            try:
                banner = lines.get(timeout=15)
            except queue.Empty:
                raise RuntimeError("Local test server did not start within 15 seconds.")
            match = re.search(r"http://127\.0\.0\.1:\d+", banner)
            if not match:
                raise RuntimeError("Local test server failed to start: " + banner)
            base = match.group(0)
            with sync_playwright() as playwright:
                launch = {"headless": True}
                if os.getenv("VISION_TEST_CHROMIUM"):
                    launch["executable_path"] = os.environ["VISION_TEST_CHROMIUM"]
                browser = playwright.chromium.launch(**launch)
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 1050})
                    page.set_default_timeout(10000)
                    js_errors = []
                    page.on("pageerror", lambda error: js_errors.append(str(error)))
                    page.goto(base)
                    expect(page.locator("#event-rows tr")).to_have_count(6)
                    expect(page.locator("#connection")).to_contain_text("RPC not configured")
                    expect(page.locator("#event-rows")).to_contain_text("SYNTHETIC")
                    if os.getenv("VISION_UI_SCREENSHOTS"):
                        out = Path(os.environ["VISION_UI_SCREENSHOTS"])
                        out.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(out / "desktop.png"), full_page=True)
                    page.get_by_role("link",name="Read the fictional case").click()
                    expect(page.get_by_role("heading",level=1)).to_contain_text("actually a gain")
                    page.get_by_text("Inspect the four fixture records and their price sources").click()
                    expect(page.locator(".sources")).to_contain_text("synthetic://ledger/opening-1")
                    for width in (1440, 768, 390):
                        page.set_viewport_size({"width":width,"height":900})
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Report overflow: {width}px"
                    page.set_viewport_size({"width":1440,"height":1050})
                    page.go_back()
                    page.locator("#load-demo").click()
                    expect(page.locator("#query")).to_have_value(re.compile(r"^0x[0-9a-f]{40}$"))
                    page.locator(".record-button").first.click()
                    expect(page.locator("#record-detail")).to_be_visible()
                    expect(page.locator("#record-json")).to_contain_text('"dataset": "synthetic"')
                    # Server failure is displayed without making up live records.
                    page.locator("#crawl-address").fill("0x" + "a" * 40)
                    page.locator("#crawl-button").click()
                    expect(page.locator("#notice")).to_contain_text("No provider configured")
                    expect(page.locator("#crawl-button")).to_be_enabled()
                    page.locator("#query").fill("no-such-record-vision-ui-test")
                    page.locator('#search-form button').click()
                    expect(page.locator("#no-events")).to_be_visible()
                    page.locator("#load-demo").click()
                    expect(page.locator("#event-rows tr")).to_have_count(6)
                    page.locator('[data-view="labels"]').click()
                    expect(page.locator(".label-card")).to_have_count(6)
                    page.locator("#label-query").fill("USDC")
                    page.locator("#label-form button").click()
                    expect(page.locator(".label-card")).to_have_count(1)
                    expect(page.locator(".label-card")).to_contain_text("REFERENCE")
                    page.locator(".label-card button").click()
                    expect(page.locator("#view-explore")).to_be_visible()
                    page.locator('[data-view="case"]').click()
                    expect(page.locator("#case-state")).to_have_text("illustrative")
                    original = page.request.get(base + "/api/case").json()
                    page.locator("#simulate-gains").fill("1000")
                    page.locator("#simulate-income").fill("50")
                    page.locator("#simulate-form button").click()
                    expect(page.locator("#simulate-result")).to_contain_text("Preview only")
                    assert page.request.get(base + "/api/case").json() == original, "Preview persisted baseline changes"
                    note = "Synthetic UI smoke test: more price-source evidence needed."
                    page.locator("#review-note").fill(note)
                    page.locator("#review-form button").click()
                    expect(page.locator("#review-result")).to_contain_text(note)
                    with page.expect_download() as event:
                        page.locator("#export").click()
                    payload = json.loads(Path(event.value.path()).read_text())
                    assert payload["dataset"] == "synthetic"
                    assert payload["result"]["evidence_hash"] == original["result"]["evidence_hash"]
                    page.locator('[data-view="scope"]').click()
                    expect(page.locator("#view-scope")).to_be_visible()
                    page.go_back()
                    expect(page.locator("#view-case")).to_be_visible()
                    for width in (1440, 768, 390):
                        page.set_viewport_size({"width": width, "height": 900})
                        for view in ("explore", "labels", "case", "scope"):
                            page.locator('[data-view="' + view + '"]').click()
                            expect(page.locator("#view-" + view)).to_be_visible()
                            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Overflow: {view}, {width}px"
                    page.locator('[data-view="explore"]').click()
                    page.locator("#load-demo").click()
                    expect(page.locator("#event-rows tr")).to_have_count(6)
                    if os.getenv("VISION_UI_SCREENSHOTS"):
                        page.screenshot(path=str(out / "mobile.png"), full_page=True)
                    with page.expect_download() as event:
                        page.locator(".export-search").click()
                    index = json.loads(Path(event.value.path()).read_text())
                    assert index, "Empty indexed-evidence export"
                    assert not js_errors, js_errors
                    print("PASS: real local API/browser integration, search, labels, error state, preview isolation, review, exports, history, and desktop/mobile overflow.")
                finally:
                    browser.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


if __name__ == "__main__":
    main()
