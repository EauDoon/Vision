# Vision v1.0.0 release verification

Verified on 18 November 2026 against Python 3.12 in a clean temporary SQLite database. Use the commands in the main README to reproduce the offline checks. No private taxpayer data or credentials are included.

| Check | Result | What was verified |
| --- | --- | --- |
| Chain adapter tests | **25 passed** | Ethereum-only scope, finalized bounds, receipt outcomes, log/topic shapes, exact raw integers, deduplication, self-transfers, changed hashes, failure conditions and request limits. All provider responses here are fixtures. |
| Historical backfill tests | **15 passed** | Inclusive windows, bound and retry limits, interruptions, exact resumptions, corrupt checkpoints, wrong chain/address, conflicts and preserved earlier commits. |
| Reconciliation tests | **11 passed** | Decimal FIFO, split lots, opening history, income, negative differences, missing-data blocking, duplicate inputs and stable evidence hashing. No country law or liability is encoded. |
| End-to-end HTTP + SQLite tests | **7 passed** | A real loopback server processes search, static assets, origin and input guards, a **fixture-backed** crawl, atomic writes, DB reopen, both exports, review persistence and an unsaved what-if. |
| Dashboard JavaScript | **Syntax passed** | Node parsed the shipped script. |
| Client/server interaction | **Passed without a browser renderer** | jsdom exercised the dashboard against the real local API and a disposable SQLite database. Covers initialization, sample lookup, offline RPC error, reconciliation, preview isolation, review, evidence export and label filtering. See [UI test notes](UI-TESTS.md). |
| Real public RPC smoke | **Not verified** | Both the original and published PublicNode RPC hostname were unavailable from this release environment. No live result or historical transfer has been substituted with fixture data. Run a one-window crawl with your approved accessible provider and check the export's block hashes. |
| Desktop/mobile visual and full Playwright acceptance | **Not verified** | Restricted browser process could not open local sockets. The optional real-browser suite is included for a suitable developer machine. No rendered screenshot or visual pass is claimed. |
| Legal/production/security validation | **Not performed** | No live taxpayer pilot, legal clearance, licensed dataset, court admissibility, production penetration test, independent consensus proof, or real-case accuracy claim. |

**Offline Python suite: 58 passed.** The 58 automated checks are not 58 live chain observations. Passing synthetic cases is not a measure of taxpayer or investigation accuracy.

## Manual release smoke

1. Run the app without an RPC URL. Open the sample address, check the six marked fixture records, inspect a tx and download the index extract.
2. Open the synthetic case. Confirm reconstructed gains = 2250 and income = 180, with separate declared figures 2000 and 100. Preview 3000 and 180: the gains difference is -750, income difference is 0, and the baseline is unchanged.
3. Configure a trusted working Ethereum mainnet provider. Pick a known finalized transfer involving the address under review; run a narrow window containing that block. Confirm the tx, log index, raw units and block hash independently against a second source. An empty window tests connectivity but does not validate matching-event extraction.
4. Re-run the same window. Event count in the local index must not grow; a new completed crawl record is expected. Confirm the export names the observed window. Interrupt a later CLI batch and restart: the exact previously committed windows should resume.
5. Run the optional browser suite and visually inspect the layouts before any hosted or wider distribution.
