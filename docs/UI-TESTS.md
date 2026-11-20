# Browser smoke tests

The runtime has no frontend package dependencies. The browser smoke suite
uses Python Playwright and Chromium. It is intentionally named
`ui_smoke.py`, not `test_*.py`, so the standard-library unit test discovery does not
require Playwright.

From the repository root, in a development environment:

```sh
python -m venv .venv-ui
. .venv-ui/bin/activate
python -m pip install playwright==1.65.2
python -m playwright install chromium
python tests/ui_smoke.py
```

Windows: activate with `.venv-ui\Scripts\activate` instead. Browser installation
may require additional OS libraries; follow Playwright's official installation
instructions for your operating system. Use a disposable development environment,
not a production machine, to install browser dependencies.

To use an existing compatible Chromium executable:

```sh
VISION_TEST_CHROMIUM=/path/to/chromium python tests/ui_smoke.py
```

To save optional desktop and mobile screenshots outside the repository:

```sh
VISION_UI_SCREENSHOTS=/tmp/vision-ui-screenshots python tests/ui_smoke.py
```

The suite captures the explorer and Vault review at 1440 × 900 and 390 × 844,
including the initial viewport and the full page. Vault filenames begin with `vault-`.
To capture another local checkout with the same framing, pass its directory:

```sh
VISION_UI_SCREENSHOTS=/tmp/vision-ui-before python tests/ui_smoke.py --app-root ../vision-before --capture-only
```

## Isolation and coverage

The test starts the actual `app.py` server on an operating-system-assigned loopback
port and a temporary SQLite database. It clears `VISION_RPC_URL` and `VISION_DB`
from the child environment, never reads the operator's database, and terminates
the child server in `finally`. Most checks use the loopback server. A set of
intercepted test responses
covers delayed reads, a mixed-source preview, a directory error, and the import
control when a provider is configured. The import request still reaches the
RPC-disabled loopback server. Fixture data stays in the temporary database.

Checks include:

- Initial fixture records and data-boundary badges.
- Sample lookup, loading, recovery, empty and failed searches, source-record keyboard focus and return.
- Export availability, mixed-source labeling, changed snapshots and the intentional all-records query.
- Label search, directory failure, navigation focus and preserving the active view on skip.
- Missing-RPC crawl error, with no fabricated success records.
- Fictional calculation, unsaved what-if preview, and unchanged baseline evidence.
- Saved synthetic review and downloaded JSON evidence.
- Replay comparison filters, failed and skipped provider reads, labeled diagnostic examples, field-level differences and incomplete witnesses. The test inspects the responsive dashboard and checks the downloaded comparison against its preview, response bytes, canonical digest and offline verifier.
- Balancer Vault decisions, transfer rows, filter counts and final header check. With the packet endpoint then unavailable, the actual download must match the preview and original response byte for byte. The suite checks the displayed digest and runs the offline verifier on the downloaded file.
- Hash navigation and browser Back.
- Horizontal overflow at 1440, 768, 390, and 320 pixels across the dashboard views.
- Uncaught browser JavaScript errors.

This is a smoke test, not a full accessibility audit, visual regression suite,
security review, live-provider test, or verification of every interrupted flow.
Screenshot capture alone is not a visual pass: inspect the saved images manually.

## Continuous integration

The Verify Vision workflow checks out the pull request head and runs the Python
suite, the report generator's byte-for-byte check, dashboard JavaScript syntax, and the loopback browser
suite. The browser job uses the Ubuntu runner's Google Chrome and a pinned
Playwright installation. Its `vision-ui-renders` artifact retains the desktop
and mobile captures for seven days.
