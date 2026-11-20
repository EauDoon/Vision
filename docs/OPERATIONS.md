# Running Vision

The dashboard and API share the same local origin. Start in the repository root using `python3 app.py`, or `py -3 app.py` on Windows. Python 3.10 or higher includes all runtime dependencies. Node is only needed for optional frontend checks. Press Ctrl+C to stop.

## Configuration

| Name | Default | Purpose |
| --- | --- | --- |
| `VISION_DB`, or `--db` | `./data/vision.sqlite3` | Local index and synthetic review history. |
| `--port` | `8765` | HTTP listens only on 127.0.0.1. |
| `VISION_RPC_URL` | unset | Operator-supplied mainnet HTTPS RPC URL; no provider call occurs until a crawl. |
| `VISION_RPC_ALLOWED_HOSTS` | built-in public hostnames | Additional exact trusted hosts. No URL from the client, localhost, redirects, plain HTTP or userinfo. |

The provider is read-only. No signing library, private keys, wallets or write RPC methods are used. Some paid providers put a secret in their URL; supply it outside the repository. Don't paste it into issue threads, review notes or URLs sent to others. An allowlisted provider can still be unavailable or supply incomplete data.

## Crawling and resuming

The dashboard and `POST /api/crawl` index a single bounded account window. Omit `end` for the latest finalized window. To inspect meaningful historical activity, use a known block height from your research instead of assuming a quiet address will transact in the most recent eight blocks. To select an account, match its full Ethereum address, not a token symbol. An ERC-20 amount is indexed if that account was sender or recipient of the token transfer.

Use the bundled historical backfill CLI from the same directory:

```bash
python3 backfill.py --help
# With VISION_RPC_URL set, substitute the public address and finalized range of interest:
python3 backfill.py 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 --start 21000000 --end 21000015 --window 8 --retries 1
```

The CLI accepts up to 128 inclusive blocks per invocation, 1–8 blocks per window and at most two retries. Rerunning the same command resumes an exact saved account/range window after checking its block headers, event count, and links to the stored live event rows. New scans also record a SHA-256 over those rows. A nonempty scan from an older database is read again once to establish that record. Empty windows can resume with zero linked events. A matching checkpoint is local evidence, not independent provider corroboration. Each window is committed in one SQLite write transaction. Its headers must agree with both adjacent stored windows wherever present, including when importing older blocks after newer ones. Older databases retain parent evidence in saved scan records. A missing parent for an existing successor requires re-observing that successor. Failed windows leave earlier evidence intact. Repeated identical events are deduplicated.

A successful token transfer observation must match its receipt log by transaction, block, log index, emitting contract, topics and raw amount. Every scoped transfer in an already fetched successful receipt must also appear in the corresponding address filter replies. A self-transfer must appear in both directions but is indexed once. A known omission withholds the entire window; this check does not prove coverage of receipts that were never fetched. Receipts from before Byzantium can contain a state root without a success status. A window that needs such a receipt is withheld because Vision cannot establish execution success from it.

Each crawl attempt has a 60-second acceptance deadline, a request-count budget, and caps on blocks, events and response bytes. The transport checks remaining time between reads. If an operating-system DNS or socket call returns late, Vision discards the result before handing it to the index. Retries, backoff, SQLite lock waits and commit time are additional elapsed time. A provider can omit an observation without exposing the omission; the data is not a full node or independently verified proof.

## Optional two-provider check for the Vault

### v1.3 capture and comparison

Open `/replay/` on the local workbench or visit the [static dashboard](https://eaudoon.github.io/Vision/). Both use the same release packet. Loading or filtering the report reads bundled evidence. The JSON includes the complete set of comparison sources and explicitly labels the diagnostic examples.

To reproduce the bundled comparison from the repository root, run the following commands.

```sh
python3 replay_compare.py > vision-replay-review.json
python3 replay_compare.py --verify vision-replay-review.json
```

To collect a **new dated observation**, these commands contact the two fixed, public Ethereum endpoints. They use the actual importer, the three single-block windows and both Vault topic filters. A provider-wide preflight transport failure stops further attempts against that endpoint. Keep the capture alongside the review so a reviewer can reproduce your export using that input.

```sh
VISION_RPC_ALLOWED_HOSTS=public.1rpc.io python3 capture_providers.py --public > capture.json
python3 replay_compare.py --capture capture.json > my-replay.json
python3 replay_compare.py --capture capture.json --verify my-replay.json
python3 app.py --replay-capture capture.json
```

An unsuccessful public capture writes its evidence and exits with status 1. The other commands work offline with that file. The dashboard server accepts the capture path at startup and uses that snapshot until restart. A verifier given the same capture can reproduce the decisions. Establishing who collected an independently supplied file requires its provenance.

The operators publish keyless endpoints. The host override applies to this capture command and permits Automata's public endpoint. [Allnodes PublicNode](https://ethereum.publicnode.com/) · [Automata 1RPC network table](https://docs.1rpc.io/using-the-web3-api/networks)

For a static copy, run `python3 publish_report.py --output vision-site` with a new output directory. Serve its HTML, local script, stylesheet, packet and archive license together. The build and comparison verification run offline. The published [v1.2 report](https://eaudoon.github.io/Vision/v1.2/) and [original download](https://eaudoon.github.io/Vision/vision-balancer-vault-review.json) remain available.

### v1.2 provider comparison

Two-provider live importer verification remains open. To collect a separate public observation, run this from the repository root. The command contacts both public Ethereum endpoints and writes its results to the named local file.

```bash
VISION_RPC_ALLOWED_HOSTS=eth.drpc.org python3 provider_review.py --public > vault-providers.json
```

PublicNode and dRPC publish keyless HTTPS endpoints. The command grants the importer access to dRPC for this process. PublicNode is already on its allowlist. Each provider receives the Vault address in two log filters per block. Historical data access and quotas depend on the provider. [PublicNode Ethereum endpoint](https://ethereum.publicnode.com/) · [dRPC Ethereum API](https://drpc.org/docs/ethereum-api)

The command starts a fresh importer run for each provider and each of blocks 22,431,084, 17,034,870 and 17,034,869. It checks the provider’s finalized height, bypasses the SQLite index and checkpoints, then compares the block hash and full transfer rows with the pinned archive observations. The JSON keeps each provider’s decisions, expected rows and observed rows. A provider failure has a null observed count and an error. Incomplete archive coverage yields a null expected count while retaining the provider observation. Exit status 0 requires agreement for all six provider/block comparisons. A mismatch or unavailable result gives exit status 1 and preserves the other comparisons.

## API

| Method | Resource | Result |
| --- | --- | --- |
| GET | `/api/status` | Version, row counts, demo address, RPC configured flag (not a connectivity check). |
| GET | `/api/search?q=...` | Up to 100 events, matching labels, detected identifier, coverage and truncation flag. |
| GET | `/api/search-export?q=...` | Bounded search evidence, supporting crawl windows and checksum. `event_witnesses` maps each exported live event ID to a local `scan_id` in `crawl_windows`. A null witness means that the index lacks a saved link. Address searches can also include the 50 latest windows, including empty ones. |
| GET | `/api/scans` | Last 20 live crawl records. |
| GET | `/api/transfer-review` | Offline Balancer Vault review for the three fixed Ethereum blocks. Returns the versioned packet used by the dashboard download. |
| GET | `/api/replay-compare` or `/replay/packet.json` | v1.3 comparison with dated source observations, witness checks, field-level differences and an outer canonical SHA-256. |
| POST | `/api/crawl` | JSON `{"address":"0x…","blocks":2,"end":22500000}`; optional end. Returns window, observed event count, coverage and block hashes. |
| GET | `/api/case` | Fixed, fictional input, computed outputs, review history and boundary. |
| POST | `/api/simulate` | JSON `{"realized_gains":"3000","income":"180"}`. Recompute the demo with alternate declarations; never saves a case or review. |
| POST | `/api/review` | JSON `{"decision":"needs_data","note":"Review the fictional acquisition record."}`. Allowed decisions: needs_data, reviewed. Local baseline case only. |
| GET | `/api/evidence` | Fictional-case evidence; not an assessment, notice or verified court record. |

Valid money fields are **decimal strings**, not floating-point JSON numbers. `raw_amount` is an integer string; look at `decimals` before display or comparison. A 64-hex query might be a block or transaction hash, not proof that a matching transaction exists.

In an export, recompute the outer `sha256` by removing that field and hashing UTF-8 JSON using lexicographic keys, compact separators and unescaped Unicode (see `store.encode`). The nested calculation hash has its own defined payload in `reconcile.py`. Hashes are integrity checks, not independent authentication or tamper-proof audit custody. No export signs or transmits a transaction.

### Reviewing a transfer packet offline

Start Vision, open the transfer review and expand a block. Each decision compares the block hash and every transfer’s transaction hash, block-wide log index, emitting contract, indexed sender, indexed recipient and raw integer amount. Native ETH and internal movements fall outside the predicate. The report reads its evidence from the bundled fixtures and leaves the index and scan history untouched.

| Decision | Interpretation |
| --- | --- |
| `matched` | Both observations completed and their block hash and transfer rows agree. |
| `verified_zero` | The archive covers every receipt and log in the block. Both directional filter reads completed and the importer also returned zero matching transfers at the same hash. |
| `mismatch` | Both observations completed, with different block hashes or transfer rows. Inspect the two sides even when the counts agree. |
| `unavailable` | Evidence or replay coverage is incomplete. The missing observation has a JSON null count. |

To check a downloaded packet, run `python3 transfer_review.py --verify vision-balancer-vault-review.json` from a trusted checkout. The verifier checks the outer digest and rebuilds the packet against the pinned evidence, including coverage and witnesses. A successful exit validates the supplied packet for this fixture version. Two-provider live importer verification remains open.

## Troubleshooting

- **503 / no provider:** configure `VISION_RPC_URL` and restart. Synthetic examples remain available without it.
- **502 / provider unavailable:** verify your mainnet provider, allowed hostname, egress, quota and finalized/log/receipt method support. Try a smaller range. No partial success is committed. Do not paste the URL with credentials into a bug report.
- **409 / crawl in progress:** wait for the current local request to finish. The dashboard allows one crawl at a time.
- **0 events:** check the range and search the exact address. Zero means no supported match in that range, not inactivity everywhere.
- **Unknown token decimals:** inspect raw units. Do not infer decimals or price.
- **403 / local only:** use exactly the printed loopback URL. This server isn't intended to be exposed, multiuser, or put behind a proxy.
- **Data handling:** the SQLite file is local and unencrypted. Review notes persist; use fictional content only. Backups and deletion are operator-managed. There is no production access or retention policy.
