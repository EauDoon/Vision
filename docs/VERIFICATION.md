# Verification log

## Vision v1.3 · Replay comparison

On 20 November 2026, both release jobs checked out implementation commit `5dc1c178da88fe131bf23cb1a6eb1f7d56c75bfb` and passed. The workflow ran 118 offline Python tests, the generated-report check, both JavaScript syntax checks, static export and offline verification, and the loopback Chromium smoke test. [Implementation CI](https://github.com/EauDoon/Vision/actions/runs/44702425122) · [Final PR head checks](https://github.com/EauDoon/Vision/pull/6/checks)

The browser selected sources and blocks, inspected disagreements and the incomplete zero example, and downloaded the full 50,537-byte JSON after further packet requests were blocked. Its bytes matched the displayed JSON, and the canonical SHA-256 was `f0444484fdcdf5a8aadb8179a6d4b069b3f687c3c0ce95d4ec41149494d65a6b`. The v1.2 fixture packet also passed its original verifier. [Comparison results and public capture](V1.3.md#release-observations)

## Vision v1.2.0 candidate · Balancer Vault

**Fixture-backed reconciliation passed for these three blocks.** On 19 November 2026, the `verify` and `browser` jobs both checked out implementation commit `2b8fd7a8d09302b36299beb829902b2e49e3cb3a`. The input is the pinned archive’s receipt projection served as constructed JSON-RPC responses. [Candidate CI](https://github.com/EauDoon/Vision/actions/runs/44529661598) · [Checks on the current draft PR head](https://github.com/EauDoon/Vision/pull/5/checks)

| Ethereum block | Archive receipts / logs examined | Expected / observed | Decision |
| ---: | ---: | ---: | --- |
| 22,431,084 | 95 / 233 | 2 / 2 | `matched` |
| 17,034,870 | 184 / 510 | 2 / 2 | `matched` |
| 17,034,869 | 93 / 208 | 0 / 0 | `verified_zero` |

The four nonzero rows agreed on block hash, transaction hash, block-wide log index, contract, sender, recipient and raw amount. For the zero, the receipt projection covers all 208 log positions. Both Vault filters returned empty and the importer rechecked the block hash. The archive answer and all three compressed inputs were independently rebuilt and compared byte for byte. [Source pins, MIT notice and rebuild instructions](../fixtures/balancer-vault/README.md)

**Reviewer packet SHA-256** `494a8f18c04b3f1ce533eeb00ad979b5d7ddb5036f8b4f6d976f12ef4929583c`

The 93 offline Python tests, `python3 report.py --check`, `node --check static/app.js` and the loopback Chromium download passed locally and on candidate CI. The browser received the report once, blocked further requests to the report endpoint, and downloaded it. The response body, on-screen JSON and saved bytes matched. The displayed digest matched the packet, and the CLI verified it against the pinned evidence. Regression tests rejected edited amounts, coverage and witnesses even after recalculating the outer checksum.

Two-provider live importer verification remains open. The separate public replay command was exercised with offline test doubles. [Operator command](OPERATIONS.md#optional-two-provider-check-for-the-vault)

## Earlier releases

The historical v1.0.0 results below apply to that release only. For v1.1.0 coverage and remaining gaps, see [the v1.1 release record](V1.1.md).

## Vision v1.0.0 release verification

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
