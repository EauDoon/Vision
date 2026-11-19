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

The CLI accepts up to 128 inclusive blocks per invocation, 1–8 blocks per window and at most two retries. Rerunning the same command resumes exact saved account/range windows after checking their block hashes against the local index; it never assumes another account or an overlapping scan covers the request. A matching checkpoint is local evidence, not independent provider corroboration. Each window is committed separately with block and parent hashes. A failure aborts that window; a finalized hash conflict does not overwrite the prior record. Repeated identical events are deduplicated. Requests, block ranges, response sizes, runtimes and persisted query result sizes are capped. A provider can omit an observation without exposing the omission; the data is not a full node or independently verified proof.

## API

| Method | Resource | Result |
| --- | --- | --- |
| GET | `/api/status` | Version, row counts, demo address, RPC configured flag (not a connectivity check). |
| GET | `/api/search?q=...` | Up to 100 events, matching labels, detected identifier, coverage and truncation flag. |
| GET | `/api/search-export?q=...` | Bounded search evidence + exact supporting crawl windows and checksum. Address searches can also include the 50 latest windows, including empty ones. |
| GET | `/api/scans` | Last 20 live crawl records. |
| POST | `/api/crawl` | JSON `{"address":"0x…","blocks":2,"end":22500000}`; optional end. Returns window, observed event count, coverage and block hashes. |
| GET | `/api/case` | Fixed, fictional input, computed outputs, review history and boundary. |
| POST | `/api/simulate` | JSON `{"realized_gains":"3000","income":"180"}`. Recompute the demo with alternate declarations; never saves a case or review. |
| POST | `/api/review` | JSON `{"decision":"needs_data","note":"Review the fictional acquisition record."}`. Allowed decisions: needs_data, reviewed. Local baseline case only. |
| GET | `/api/evidence` | Fictional-case evidence; not an assessment, notice or verified court record. |

Valid money fields are **decimal strings**, not floating-point JSON numbers. `raw_amount` is an integer string; look at `decimals` before display or comparison. A 64-hex query might be a block or transaction hash, not proof that a matching transaction exists.

In an export, recompute the outer `sha256` by removing that field and hashing UTF-8 JSON using lexicographic keys, compact separators and unescaped Unicode (see `store.encode`). The nested calculation hash has its own defined payload in `reconcile.py`. Hashes are integrity checks, not independent authentication or tamper-proof audit custody. No export signs or transmits a transaction.

## Troubleshooting

- **503 / no provider:** configure `VISION_RPC_URL` and restart. Synthetic examples remain available without it.
- **502 / provider unavailable:** verify your mainnet provider, allowed hostname, egress, quota and finalized/log/receipt method support. Try a smaller range. No partial success is committed. Do not paste the URL with credentials into a bug report.
- **409 / crawl in progress:** wait for the current local request to finish. The dashboard allows one crawl at a time.
- **0 events:** check the range and search the exact address. Zero means no supported match in that range, not inactivity everywhere.
- **Unknown token decimals:** inspect raw units. Do not infer decimals or price.
- **403 / local only:** use exactly the printed loopback URL. This server isn't intended to be exposed, multiuser, or put behind a proxy.
- **Data handling:** the SQLite file is local and unencrypted. Review notes persist; use fictional content only. Backups and deletion are operator-managed. There is no production access or retention policy.
