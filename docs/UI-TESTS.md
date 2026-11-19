# Optional browser smoke tests

The runtime has no frontend package dependencies. This optional contributor test
uses Python Playwright and a locally installed Chromium. It is intentionally named
`ui_smoke.py`, not `test_*.py`, so the standard-library unit test discovery does not
require Playwright.

From the repository root, in a development environment:

```sh
python -m venv .venv-ui
. .venv-ui/bin/activate
python -m pip install playwright
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

## Isolation and coverage

The test starts the actual `app.py` server on an operating-system-assigned loopback
port and a temporary SQLite database. It clears `VISION_RPC_URL` and `VISION_DB`
from the child environment, never reads the operator's database, and terminates
the child server in `finally`. All API responses are real server responses. It
does not call external RPCs or mutate a real case.

Checks include:

- Initial fixture records and data-boundary badges.
- Sample lookup, empty search, source-record detail, label search and navigation.
- Missing-RPC crawl error, with no fabricated success records.
- Fictional calculation, unsaved what-if preview, and unchanged baseline evidence.
- Saved synthetic review and downloaded JSON evidence.
- Hash navigation and browser Back.
- Horizontal overflow at 1440, 768, and 390 pixels, across all four views.
- Uncaught browser JavaScript errors.

This is a smoke test, not a full accessibility audit, visual regression suite,
security review, live-provider test, or verification of every interrupted flow.
Screenshot capture alone is not a visual pass: inspect the saved images manually.

## Verification status in the build environment

The JavaScript passed `node --check`. Mocked DOM interaction tests passed using a
temporary jsdom installation, covering search, precise amounts, safe text
rendering, source detail, crawler request parameters, review, isolated preview,
and both exports.

An additional integrated jsdom run **passed against the actual server** started
as a child in the same execution lifetime, with a temporary SQLite database and
RPC disabled. Its 10 real client API calls covered initialization, sample lookup,
the missing-RPC error, calculation display, isolated preview, saved synthetic
review, evidence integrity, and label filtering. This verifies DOM/API behavior,
not browser layout, CSS, or screenshot appearance.

The real-browser suite was **not verified as passing** in the build environment:
Playwright's bundled browser was absent, and the installed Chromium could not
start because its socket creation was denied (`Operation not permitted`). Run
this optional suite in an environment that permits local server and browser
processes. A test startup failure is not a UI pass.
