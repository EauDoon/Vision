# Changelog

Changes that affect how Vision is used, newest first. Release evidence and limits live in the [verification record](docs/VERIFICATION.md).

## Unreleased

- Fixed: `python3 app.py --db PATH` now stops with `Cannot start Vision: ...` and exit status 1 when the path is a directory or is not an SQLite database. It used to end in a Python traceback.
- Changed: `python3 app.py --help` describes `--port` and `--db`.
- Docs: the README opens with what Vision is, who it is for and a quick start. Per-release notes moved from the top of the README to this file.

## 1.4.0 (26 Nov 2026)

- Added the [evidence atlas](https://eaudoon.github.io/Vision/atlas.html): a map from the pinned archive to the verifier, with a source directory that works without JavaScript and a read-only JSON view of the selected component.
- Added **Compare sources side by side** and **Download visible comparison summaries** to the replay comparison.
- Replay filters travel with the page URL and survive the local redirect from `/replay` to `/replay/`.
- Release check: reopen a filtered public link and confirm that the complete downloaded packet still matches the pinned digest.

## 1.3 (20 Nov 2026)

- Added the replay comparison for the Balancer Vault across three pinned Ethereum mainnet blocks, with a reviewer packet and `python3 replay_compare.py --verify`. See the [v1.3 notes](docs/V1.3.md).

## 1.2

- Added the Balancer Vault transfer review against archived receipts, with `python3 transfer_review.py --verify`. See the [archive notes](fixtures/balancer-vault/README.md).

## 1.1

- Added the illustrated field note for the fictional case. See the [v1.1 notes](docs/V1.1.md).
