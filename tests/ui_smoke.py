"""Optional real-browser test. Run from repository root: python tests/ui_smoke.py.

Uses a temporary SQLite database and a loopback server with RPC explicitly disabled.
Never reads the operator's database or calls a live RPC. See docs/UI-TESTS.md.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
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


def exercise_index_states(page, expect, base):
    """Use only the local fixture and intercepted responses for transient states."""
    sample = page.request.get(base + "/api/status").json()["demo_address"]
    page.locator("#load-demo").click()
    expect(page.locator("#source-mix")).to_have_text("6 fictional")
    export = page.locator("#export-search")
    expect(export).to_be_enabled()

    page.locator("#query").fill("fixture-pending")
    expect(export).to_be_disabled()
    held = []
    pending_url = "**/api/search?q=fixture-pending"
    def hold(route):
        held.append(route)
    page.route(pending_url, hold)
    with page.expect_request(lambda request: request.url.endswith("q=fixture-pending")):
        page.locator("#query").press("Enter")
    expect(page.locator("#result-count")).to_have_text("Searching…")
    expect(page.locator("#event-rows tr")).to_have_count(0)
    expect(export).to_be_hidden()
    expect(page.locator("#no-events")).to_be_hidden()
    held[0].fulfill(status=503, json={"error": "Fixture index paused."})
    expect(page.locator("#result-count")).to_have_text("Search unavailable")
    expect(page.locator("#coverage")).to_contain_text("Fixture index paused.")
    expect(export).to_be_hidden()
    page.unroute(pending_url, hold)

    # Model one indexed chain observation sharing a fictional address. All values
    # originate in the synthetic fixture; no RPC or external address is queried.
    preview = page.request.get(base + "/api/search?q=" + sample).json()
    mixed = copy.deepcopy(preview)
    mixed["events"] = mixed["events"][:2]
    mixed["events"][1]["dataset"] = "live"
    url = "**/api/search?q=" + sample
    page.route(url, lambda route: route.fulfill(json=mixed))
    page.locator("#load-demo").click()
    expect(page.locator("#source-mix")).to_have_text("1 fictional · 1 live")
    expect(page.locator("#coverage")).to_contain_text("fictional sample address")
    expect(page.locator("#event-rows")).to_contain_text("LIVE")

    # The export endpoint sees the original fixture, unlike the displayed result.
    downloads = []
    page.on("download", lambda item: downloads.append(item))
    export.click()
    expect(page.locator("#export-help")).to_contain_text("index changed")
    expect(export).to_be_disabled()
    assert not downloads
    page.unroute(url)
    page.locator("#query").fill("")
    page.locator("#query").press("Enter")
    expect(page.locator("#source-mix")).to_have_text("6 fictional")
    with page.expect_download() as downloaded:
        export.click()
    data = json.loads(Path(downloaded.value.path()).read_text())
    assert data["query"] == ""
    assert data["snapshot"] == page.request.get(base + "/api/search?q=").json()

    # A provider-availability fixture enables the normal import button. The
    # actual loopback server still has RPC off and returns its real 503 response.
    status = page.request.get(base + "/api/status").json()
    status["rpc_configured"] = True
    page.route("**/api/status", lambda route: route.fulfill(json=status))
    page.reload()
    page.locator("#jump-import").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#crawl-address")).to_be_focused()
    page.locator("#crawl-address").fill(sample)
    page.locator("#crawl-button").click()
    expect(page.locator("#crawl-result")).to_contain_text("No provider configured")
    expect(page.locator("#crawl-button")).to_be_enabled()
    page.unroute("**/api/status")
    page.reload()


def exercise_transfer_review(page, expect, app_root, screenshot_dir):
    url = "**/api/transfer-review"
    page.route(url, lambda route: route.fulfill(status=503, json={"error": "Fixture paused."}))
    page.get_by_role("link", name="Vault transfer review").click()
    expect(page.locator("#transfer-review-title")).to_be_focused()
    expect(page.locator("#transfer-review-status")).to_contain_text("Fixture paused")
    expect(page.locator("#download-transfer-review")).to_be_hidden()
    page.unroute(url)
    with page.expect_response(url) as loaded:
        page.get_by_role("button", name="Retry review").click()
    blocks = page.locator(".review-block")
    expect(blocks).to_have_count(3)
    expect(blocks.locator(".pill")).to_have_text(["Matched", "Matched", "Verified zero"])
    expect(blocks.last).to_contain_text("93 archived receipts and 208 logs")
    expect(blocks.last).to_contain_text("Archive expected 0 · Importer observed 0")
    if screenshot_dir:
        capture_screens(page, Path(screenshot_dir), prefix="vault-")
    blocks.last.locator("summary").click()
    expect(blocks.last).to_contain_text("Sender filter: 0 · Recipient filter: 0 · Final block header: checked")
    blocks.first.locator("summary").focus()
    page.keyboard.press("Enter")
    columns = blocks.first.locator(".review-sides section")
    expect(columns).to_have_count(2)
    for column in columns.all():
        expect(column).to_contain_text("Log 138 · WETH in")
        expect(column).to_contain_text("433410975363818")
        expect(column).to_contain_text("Log 139 · rETH out")
        expect(column).to_contain_text("381986670507558")

    # The handoff must work from the displayed snapshot even once the API goes offline.
    page.route(url, lambda route: route.abort())
    page.get_by_text("View the exact JSON", exact=True).click()
    with page.expect_download() as event:
        page.get_by_role("button", name="Download JSON").click()
    assert event.value.suggested_filename == "vision-balancer-vault-review.json"
    path = Path(event.value.path())
    data = path.read_bytes()
    assert data == loaded.value.body() == page.locator("#transfer-review-json").text_content().encode()
    assert json.loads(data)["sha256"] == page.locator("#transfer-review-digest").inner_text()
    subprocess.run([sys.executable, str(app_root / "transfer_review.py"), "--verify", str(path)], check=True)
    page.unroute(url)


def exercise_replay_dashboard(page, expect, base, app_root, screenshot_dir):
    url = "**/replay/packet.json"
    scans_before = page.request.get(base + "/api/scans").json()
    requests = []
    page.on("request", lambda req: requests.append(req.url))
    page.route(url, lambda route: route.fulfill(status=503, body="Packet unavailable"))
    page.get_by_role("link", name="Replay dashboard").first.click()
    expect(page.locator("#retry-packet")).to_be_visible()
    expect(page.locator("#results details.observation")).to_have_count(0)
    page.unroute(url)
    with page.expect_response(url) as response:
        page.locator("#retry-packet").click()
    data = response.value.body()
    packet = json.loads(data)
    cards = page.locator("#results details.observation")
    expect(cards).to_have_count(9)
    expect(page.locator('#results [data-source="diagnostic"]')).to_have_count(0)
    block, source, state = (page.locator("#" + key + "-filter") for key in ("block", "source", "state"))
    if screenshot_dir:
        capture_screens(page, Path(screenshot_dir), prefix="replay-")

    source.select_option("publicnode")
    for height, evidence in (("22431084", "transport"), ("17034870", "not_run")):
        block.select_option(height)
        expect(cards).to_have_count(1)
        cards.first.locator(":scope > summary").click()
        expect(cards.first).to_contain_text(evidence)
        expect(cards.first).to_contain_text("Observed unavailable")

    block.select_option("")
    source.select_option("fixture")
    expect(cards).to_have_count(3)
    block.select_option("22431084")
    state.select_option("matched")
    expect(cards).to_have_count(1)
    cards.first.locator(":scope > summary").focus()
    page.keyboard.press("Enter")
    for text in ("433410975363818", "381986670507558"):
        expect(cards.first).to_contain_text(text)
    block.select_option("17034869")
    state.select_option("verified_zero")
    expect(cards).to_have_count(1)
    cards.first.locator(":scope > summary").click()
    expect(cards.first).to_contain_text("93")
    expect(cards.first).to_contain_text("208")

    # Diagnostic cases remain identifiable when filtered to a single example.
    page.locator("#show-diagnostics").check()
    state.select_option("")
    source.select_option("diagnostic")
    block.select_option("22431084")
    state.select_option("disagreement")
    expect(cards).to_have_count(1)
    cards.first.locator(":scope > summary").click()
    examples = next(s["blocks"] for s in packet["sources"] if s["kind"] == "diagnostic")
    cases = {b["block_number"]: b for b in examples}
    difference, = cases[22431084]["diff"]["changed"]
    for amount in (difference["expected"]["raw_amount"], difference["observed"]["raw_amount"]):
        expect(cards.first).to_contain_text(amount)
    block.select_option("17034870")
    cards.first.locator(":scope > summary").click()
    for key in ("missing", "extra"):
        row, = cases[17034870]["diff"][key]
        expect(cards.first).to_contain_text(str(row["log_index"]))
    state.select_option("incomplete")
    block.select_option("17034869")
    expect(cards).to_have_count(1)
    cards.first.locator(":scope > summary").click()
    expect(cards.first).to_contain_text(re.compile("recipient", re.I))
    if screenshot_dir:
        capture_screens(page, Path(screenshot_dir), prefix="replay-detail-")
    for width in (1440, 768, 390, 320):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Replay detail overflow at {width}px"

    # Changing filters cannot change, re-fetch or truncate the reviewed packet.
    shared = page.url
    page.goto(shared)
    expect(cards).to_have_count(1)
    expect(cards.first).to_have_attribute("data-source", "diagnostic")
    expect(cards.first).to_have_attribute("data-state", "incomplete")
    # Clear must be offered even while a filtered view still has results.
    expect(page.get_by_role("button", name="Clear filters")).to_be_visible()
    page.get_by_role("button", name="Clear filters").click()
    expect(cards).to_have_count(9)
    expect(page.locator("#show-diagnostics")).not_to_be_checked()
    page.goto(shared)
    expect(cards).to_have_count(1)
    # Clearing an empty view also works and restores the default evidence-only set.
    state.select_option("matched")
    page.locator("#reset-filters").click()
    expect(cards).to_have_count(9)
    expect(page.locator("#show-diagnostics")).not_to_be_checked()
    assert "diagnostics=" not in page.url and "source=" not in page.url
    expect(page.locator("#reset-filters")).to_be_hidden()

    # A write failure may leave the address unchanged but must not freeze the
    # evidence view or leave an accessible announcement claiming it is shareable.
    page.evaluate("""() => {
      const original = history.replaceState;
      history.replaceState = () => { throw new DOMException("Unavailable", "SecurityError"); };
      window.restoreHistory = () => { history.replaceState = original; };
    }""")
    source.select_option("fixture")
    block.select_option("17034869")
    expect(cards).to_have_count(1)
    expect(cards.first).to_have_attribute("data-state", "verified_zero")
    expect(page.locator("#view-link-unavailable")).to_be_visible()
    assert "source=" not in page.url
    page.evaluate("window.restoreHistory()")
    block.select_option("17034870")
    expect(cards.first).to_have_attribute("data-state", "matched")
    expect(page.locator("#view-link-unavailable")).to_be_hidden()
    assert "block=17034870" in page.url and "source=fixture" in page.url
    page.route(url, lambda route: route.abort())
    page.get_by_text("View the exact JSON", exact=True).click()
    expect(page.locator("#packet-json")).to_be_visible()
    with page.expect_download() as event:
        page.locator("#download-packet").click()
    downloaded = event.value
    assert downloaded.suggested_filename == "vision-replay-review.json"
    path = Path(downloaded.path())
    assert path.read_bytes() == data == page.locator("#packet-json").text_content().encode("utf-8")
    body = {key: value for key, value in packet.items() if key != "sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == packet["sha256"]
    expect(page.locator("#packet-digest")).to_have_text(packet["sha256"])
    subprocess.run([sys.executable, str(app_root / "replay_compare.py"), "--verify", str(path)], check=True)
    assert scans_before == page.request.get(base + "/api/scans").json()
    assert all(url.startswith(base + "/") or url.startswith("blob:") for url in requests), requests
    page.unroute(url)


def exercise_atlas_and_matrix(page, expect, base):
    # The slashless link used by the local workbench must keep its selected source.
    page.goto(base + "/replay?source=publicnode&block=17034869")
    cards = page.locator("#results .observation")
    expect(cards).to_have_count(1)
    expect(cards.first).to_have_attribute("data-source", "publicnode")
    digest = page.locator("#packet-digest").text_content()
    with page.expect_download() as event:
        page.locator("#download-selection").click()
    export = json.loads(Path(event.value.path()).read_text())
    assert export["packet_sha256"] == digest
    assert export["comparisons"] == [{"block": 17034869, "source": "publicnode", "kind": "public_capture",
                                      "decision": "unavailable", "archive_count": 0, "observed_count": None}]
    page.get_by_text("Compare sources side by side", exact=True).click()
    expect(page.locator("#matrix tbody tr")).to_have_count(3)
    page.get_by_role("button", name="Constructed fixture replay, block 17034869, Verified zero").click()
    expect(cards).to_have_count(1)
    expect(cards.first.locator("summary").first).to_be_focused()
    assert cards.first.evaluate("(card) => card.open")
    page.locator("#show-diagnostics").check()
    expect(page.locator("#matrix tbody tr")).to_have_count(4)
    page.get_by_role("button", name="Clear filters").click()
    expect(page.locator("#matrix tbody tr")).to_have_count(3)

    page.get_by_role("link", name="Evidence atlas").click()
    selector = page.get_by_label("Inspect", exact=True)
    expect(selector).to_have_value("compare")
    page.emulate_media(reduced_motion="reduce")
    selector.select_option("verify")
    expect(page.locator("#inspector-title")).to_have_text("Offline verifier")
    assert "node=verify" in page.url
    page.reload()
    expect(selector).to_have_value("verify")
    page.locator("#query-panel summary").click()
    result = json.loads(page.locator("#answer").text_content())["data"]["component"]
    assert result["id"] == "verify"
    assert [item["id"] for item in result["inputs"]] == ["packet", "compare"]
    scene = page.locator("#scene")
    initial = scene.evaluate("(c) => c.toDataURL()")
    scene.focus()
    page.keyboard.press("ArrowRight")
    assert initial != scene.evaluate("(c) => c.toDataURL()")
    page.get_by_role("button", name="Reset view").click()
    assert initial == scene.evaluate("(c) => c.toDataURL()")
    for width in (1440, 768, 390, 320):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Atlas overflow at {width}px"
    context = page.context.browser.new_context(java_script_enabled=False)
    try:
        fallback = context.new_page()
        fallback.goto(base + "/replay/atlas.html")
        expect(fallback.locator(".cards article")).to_have_count(6)
        fallback.locator("#verify .inputs a").first.click()
        assert fallback.url.endswith("#packet")
    finally:
        context.close()


def exercise_atlas_touch(browser, base):
    """Use a real gesture stream so Chromium can recognize (or suppress) the next tap."""
    context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    try:
        page = context.new_page()
        page.goto(base + "/replay/atlas.html")
        page.locator("#viewer").wait_for()
        page.locator("#viewer").evaluate("el => scrollBy(0, el.getBoundingClientRect().top - 10)")
        canvas = page.locator("#scene")
        initial = canvas.evaluate("c => c.toDataURL()")
        box = canvas.bounding_box()
        x, y = box["x"] + 80, box["y"] + 100
        cdp = context.new_cdp_session(page)

        def touch(kind, px=None, py=None):
            points = [] if px is None else [{"x": px, "y": py}]
            cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

        touch("touchStart", x, y)
        for offset in (40, 80):
            page.wait_for_timeout(40)
            touch("touchMove", x + offset, y)
        touch("touchEnd")
        assert canvas.evaluate("c => c.toDataURL()") != initial
        reset = page.locator("#reset").bounding_box()
        page.wait_for_timeout(50)
        # Send one physical tap to the visible button without Playwright retries.
        page.touchscreen.tap(reset["x"] + reset["width"]/2, reset["y"] + reset["height"]/2)
        page.wait_for_function("expected => document.querySelector('#scene').toDataURL() === expected", arg=initial)

        scroll = page.evaluate("scrollY")
        touch("touchStart", x, y)
        for offset in (40, 80):
            page.wait_for_timeout(40)
            touch("touchMove", x, y - offset)
        touch("touchEnd")
        page.wait_for_function("start => scrollY > start + 20", arg=scroll)
        assert canvas.evaluate("c => c.toDataURL()") == initial
    finally:
        context.close()


def capture_screens(page, out, prefix=""):
    out.mkdir(parents=True, exist_ok=True)
    for name, width, height in (("desktop", 1440, 900), ("mobile", 390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(out / (prefix + name + "-viewport.png")))
        page.screenshot(path=str(out / (prefix + name + ".png")), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1050})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, default=ROOT, help="Checkout to serve on loopback.")
    parser.add_argument("--capture-only", action="store_true", help="Capture the initial dashboard at both widths.")
    args = parser.parse_args()
    destination = os.getenv("VISION_UI_SCREENSHOTS")
    if args.capture_only and not destination:
        parser.error("--capture-only needs VISION_UI_SCREENSHOTS")
    try:
        from playwright.sync_api import sync_playwright, expect
    except ImportError:
        raise SystemExit("Optional dependency missing. Install Playwright as described in docs/UI-TESTS.md.")
    with tempfile.TemporaryDirectory(prefix="vision-ui-") as temp:
        env = dict(os.environ)
        env.pop("VISION_RPC_URL", None)
        env.pop("VISION_DB", None)
        proc = subprocess.Popen(
            [sys.executable, "-u", str(args.app_root / "app.py"), "--port", "0", "--db", str(Path(temp) / "test.sqlite3")],
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
                    if destination:
                        capture_screens(page, Path(destination))
                    if args.capture_only:
                        return
                    page.get_by_role("link",name="Read the fictional case").click()
                    expect(page.get_by_role("heading",level=1)).to_contain_text("actually a gain")
                    page.get_by_text("Inspect the four fixture records and their price sources").click()
                    expect(page.locator(".sources")).to_contain_text("synthetic://ledger/opening-1")
                    for width in (1440, 768, 390, 320):
                        page.set_viewport_size({"width":width,"height":900})
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Report overflow: {width}px"
                    page.set_viewport_size({"width":1440,"height":1050})
                    page.go_back()
                    page.locator("#load-demo").click()
                    expect(page.locator("#query")).to_have_value(re.compile(r"^0x[0-9a-f]{40}$"))
                    page.locator(".record-button").first.focus()
                    page.keyboard.press("Enter")
                    expect(page.locator("#source-summary")).to_be_focused()
                    expect(page.locator("#record-detail")).to_be_visible()
                    expect(page.locator("#record-json")).to_contain_text('"dataset": "synthetic"')
                    page.keyboard.press("Tab")
                    if page.locator("#record-json").evaluate("(el) => el === document.activeElement"):
                        page.keyboard.press("Tab")
                    expect(page.locator("#return-record")).to_be_focused()
                    page.keyboard.press("Enter")
                    expect(page.locator(".record-button").first).to_be_focused()
                    expect(page.locator("#crawl-button")).to_be_disabled()
                    expect(page.locator("#rpc-help")).to_contain_text("Import unavailable")
                    exercise_index_states(page, expect, base)
                    page.locator("#query").fill("no-such-record-vision-ui-test")
                    page.locator('#search-form button').click()
                    expect(page.locator("#no-events")).to_be_visible()
                    page.locator("#load-demo").click()
                    expect(page.locator("#event-rows tr")).to_have_count(6)
                    page.locator('[data-view="labels"]').click()
                    expect(page.locator(".label-card")).to_have_count(6)
                    expect(page.locator("#label-title")).to_be_focused()
                    expect(page.locator("#label-list")).to_contain_text("REFERENCE")
                    page.locator("#label-query").fill("no-fixture-label")
                    page.locator("#label-query").press("Enter")
                    expect(page.locator("#label-status")).to_contain_text("No matching labels")
                    # A directory request failure must be different from an empty result.
                    page.route("**/api/search?q=paused-label", lambda route: route.fulfill(status=503, json={"error": "Fixture paused."}))
                    page.locator("#label-query").fill("paused-label")
                    page.locator("#label-query").press("Enter")
                    expect(page.locator("#label-status")).to_contain_text("Directory unavailable")
                    page.unroute("**/api/search?q=paused-label")
                    page.locator("#label-query").fill("Atlas")
                    page.locator("#label-form button").click()
                    expect(page.locator(".label-card")).to_have_count(1)
                    expect(page.locator(".label-card")).to_contain_text("SYNTHETIC")
                    page.locator(".label-card button").click()
                    expect(page.locator("#view-explore")).to_be_visible()
                    expect(page.locator("#explore-title")).to_be_focused()
                    page.go_back()
                    expect(page.locator("#label-query")).to_have_value("Atlas")
                    expect(page.locator(".label-card")).to_have_count(1)
                    page.go_forward()
                    expect(page.locator("#view-explore")).to_be_visible()
                    exercise_transfer_review(page, expect, args.app_root, destination)
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
                    page.locator(".skip").focus()
                    page.keyboard.press("Enter")
                    expect(page.locator("#scope-title")).to_be_focused()
                    assert page.url.endswith("#scope")
                    page.go_back()
                    expect(page.locator("#view-case")).to_be_visible()
                    for width in (1440, 768, 390, 320):
                        page.set_viewport_size({"width": width, "height": 900})
                        for view in ("explore", "transfer-review", "labels", "case", "scope"):
                            page.locator('[data-view="' + view + '"]').click()
                            expect(page.locator("#view-" + view)).to_be_visible()
                            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Overflow: {view}, {width}px"
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.locator('[data-view="explore"]').click()
                    page.locator("#load-demo").click()
                    expect(page.locator("#event-rows tr")).to_have_count(6)
                    with page.expect_download() as event:
                        page.locator(".export-search").click()
                    index = json.loads(Path(event.value.path()).read_text())
                    assert index, "Empty indexed-evidence export"
                    exercise_replay_dashboard(page, expect, base, args.app_root, destination)
                    exercise_atlas_and_matrix(page, expect, base)
                    exercise_atlas_touch(browser, base)
                    assert not js_errors, js_errors
                    print("PASS: loopback workbench, Vault review, replay dashboard filters, row diffs, responsive layouts and verified packet downloads.")
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
