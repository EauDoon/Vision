"""Reconcile three fixed Balancer Vault windows against pinned Ethereum archive facts."""
import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

from chain import ADDRESS, HASH, ChainError, crawl
from store import digest, encode

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "balancer-vault"
ARCHIVE_DIGEST = "52bf7734d489898841c8c5596ebe897bfb0657c617aea300b58ed2d820bef9e9"
VAULT = "0xba12222222228d8ba445958a75a0704d566bf2c8"
BLOCKS = (22431084, 17034870, 17034869)
# The fixture transport evaluates its topic queries independently of chain.py.
SIGNATURE = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
PADDED_VAULT = "0x" + VAULT[2:].zfill(64)
FILTERS = {"sender": [SIGNATURE, PADDED_VAULT], "recipient": [SIGNATURE, None, PADDED_VAULT]}
ROW_FIELDS = ("tx_hash", "log_index", "contract", "from_address", "to_address", "raw_amount")


def event_rows(result):
    rows = [{key: event[key] for key in ROW_FIELDS}
            for event in result["events"] if event["kind"] == "erc20_transfer"]
    return sorted(rows, key=lambda row: (row["log_index"], row["tx_hash"]))


def decision(expected, observed):
    if expected["count"] is None or observed["count"] is None:
        return "unavailable"
    if expected != observed:
        return "mismatch"
    return "matched" if observed["count"] else "verified_zero"


def _check_coverage(receipts, coverage):
    """Require every projected receipt and consecutive block-wide log position."""
    seen_tx = set()
    for receipt in receipts:
        tx = receipt["tx_hash"]
        if not HASH.fullmatch(tx) or tx in seen_tx or type(receipt["status"]) is not int or receipt["status"] not in (0, 1):
            raise ValueError("Missing or invalid receipt inclusion or outcome.")
        seen_tx.add(tx)
        logs = receipt["logs"]
        if not isinstance(logs, list) or len(logs) != receipt["log_count"]:
            raise ValueError("Receipt projection has incomplete log coverage.")
        for log in logs:
            if type(log["log_index"]) is not int or log["log_index"] != coverage["logs_examined"]:
                raise ValueError("Receipt projection has a missing or repeated block-wide log index.")
            topics = log["topics"]
            if not isinstance(topics, list) or len(topics) > 4 or not all(HASH.fullmatch(t) for t in topics):
                raise ValueError("Receipt projection has malformed topics.")
            if len(topics) == 3 and topics[0] == SIGNATURE and PADDED_VAULT in topics[1:]:
                if not ADDRESS.fullmatch(log["address"]) or not HASH.fullmatch(log["data"]):
                    raise ValueError("Transfer projection lacks an emitter or a 32-byte amount.")
            coverage["logs_examined"] += 1
        coverage["receipts_examined"] += 1
    if (coverage["receipts_examined"], coverage["logs_examined"]) != (coverage["receipts"], coverage["logs"]):
        raise ValueError("Receipt or log total differs from the pinned archive coverage.")
    coverage["complete"] = True


class FixtureRPC:
    """Serve constructed replies using only the receipt projection, never the expected rows."""

    def __init__(self, fixture, witness):
        self.number = hex(fixture["number"])
        self.header = {"number": self.number, "hash": fixture["block_hash"],
                       "parentHash": fixture["parent_hash"], "timestamp": hex(fixture["timestamp"])}
        self.directions = fixture["directions"]
        self.witness = witness
        self.receipts = {}
        self.logs = []
        for receipt in fixture["receipts"]:
            inclusion = {"transactionHash": receipt["tx_hash"], "blockNumber": self.number,
                         "blockHash": self.header["hash"]}
            logs = [{**log, **inclusion, "logIndex": hex(log["log_index"]), "removed": False}
                    for log in receipt["logs"]]
            self.receipts[receipt["tx_hash"]] = {**inclusion, "status": hex(receipt["status"]), "logs": logs}
            self.logs.extend(logs)

    def __call__(self, _url, payload):
        method, params = payload["method"], payload["params"]
        if method == "eth_chainId" and params == []:
            result = "0x1"
        elif method == "eth_getBlockByNumber" and params == ["finalized", False]:
            result = self.header
        elif method == "eth_getBlockByNumber" and params == [self.number, True]:
            # This review covers log transfers only. No native transactions are replayed.
            result = {**self.header, "transactions": []}
        elif method == "eth_getBlockByNumber" and params == [self.number, False]:
            self.witness["end_header_checked"] = True
            result = self.header
        elif method == "eth_getTransactionReceipt" and len(params) == 1 and params[0] in self.receipts:
            self.witness["receipt_transactions"].append(params[0])
            result = self.receipts[params[0]]
        elif method == "eth_getLogs":
            result = self.filter_logs(params)
        else:
            raise ChainError("Request has no matching fixture response.")
        return {"jsonrpc": "2.0", "id": payload["id"], "result": result}

    def filter_logs(self, params):
        for direction, topics in FILTERS.items():
            if params != [{"fromBlock": self.number, "toBlock": self.number, "topics": topics}]:
                continue
            if direction not in self.directions:
                raise ChainError(f"Missing {direction} filter response.")
            logs = [log for log in self.logs if len(log["topics"]) >= len(topics)
                    and all(t is None or t == log["topics"][i] for i, t in enumerate(topics))]
            self.witness["filter_counts"][direction] = len(logs)
            return logs
        raise ChainError("Request does not match a fixed Vault filter.")


def review_block(archive_block, fixture):
    number = archive_block["number"]
    expected_rows = archive_block.get("rows")
    if expected_rows is not None:
        expected_rows = sorted(expected_rows, key=lambda row: (row["log_index"], row["tx_hash"]))
    expected_hash = archive_block.get("block_hash")
    expected = {"block_hash": expected_hash, "rows": expected_rows,
                "count": len(expected_rows) if expected_rows is not None and expected_hash else None}
    observed = {"block_hash": None, "rows": None, "count": None}
    coverage = {"receipts": archive_block["receipt_count"], "logs": archive_block["log_count"],
                "receipts_examined": 0, "logs_examined": 0, "complete": False}
    witness = {"fixture_path": f"{number}.json.gz", "filter_counts": {"sender": None, "recipient": None},
               "receipt_transactions": [], "end_header_checked": False}
    try:
        if fixture is None:
            raise ValueError("Pinned receipt projection is missing, unreadable or failed its checksum.")
        if fixture["number"] != number:
            raise ValueError("Fixture has the wrong block height.")
        _check_coverage(fixture["receipts"], coverage)
        transport = FixtureRPC(fixture, witness)
        # crawl validates the endpoint format even with an injected transport. This
        # hostname is never contacted and the synthetic finalized tip is the case height.
        result = crawl(VAULT, start=number, end=number, max_blocks=1,
                       rpc_url="https://ethereum.publicnode.com", http_send=transport)
        if None in witness["filter_counts"].values() or not witness["end_header_checked"]:
            raise ValueError("Importer did not complete both Vault filters and its final header check.")
        rows = event_rows(result)
        if {row["tx_hash"] for row in rows}.difference(witness["receipt_transactions"]):
            raise ValueError("Importer did not request a receipt for each observed transfer.")
        observed = {"block_hash": result["blocks"][0]["hash"], "count": len(rows), "rows": rows}
        status = decision(expected, observed)
        if status == "unavailable":
            reason = "The archive expectation is missing its transfer rows or block hash."
        elif status == "verified_zero":
            reason = (f"All {coverage['receipts']} archived receipts and {coverage['logs']} logs were "
                      "examined. Both replay filters completed with no qualifying transfer.")
        elif status == "matched":
            reason = "Block hash and every transfer field agree."
        else:
            reason = "Archived and replayed block hashes or transfer rows differ."
    except (ChainError, ValueError, KeyError, TypeError) as exc:
        status, reason = "unavailable", str(exc)
    return {"block_number": number, "archive": {k: archive_block[k] for k in ("path", "sha256", "fixture_sha256")},
            "coverage": coverage, "expected": expected, "observed": observed, "witness": witness,
            "status": status, "reason": reason}


def build_packet():
    archive = json.loads((FIXTURE_DIR / "archive.json").read_bytes())
    if digest(archive) != ARCHIVE_DIGEST:
        raise ValueError("The bundled archive manifest differs from its pinned SHA-256.")
    cases = {case["number"]: case for case in archive["blocks"]}
    blocks = []
    for number in BLOCKS:
        case = cases[number]
        fixture = None
        try:
            compressed = (FIXTURE_DIR / f"{number}.json.gz").read_bytes()
            if hashlib.sha256(compressed).hexdigest() == case["fixture_sha256"]:
                fixture = json.loads(gzip.decompress(compressed))
        except (OSError, EOFError, ValueError):
            pass
        blocks.append(review_block(case, fixture))
    scope = {
        "chain_id": 1, "address": VAULT, "blocks": list(BLOCKS),
        "predicate": "Successful receipt, three-topic Transfer, Vault as indexed sender or recipient.",
        "unit": "Raw integer strings in the emitting contract's units.",
        "exclusions": ["Native ETH", "Internal movements"],
    }
    packet = {"schema": "vision/transfer-review@1", "scope": scope, "source_mode": "constructed_rpc_fixture",
              "archive": {k: archive[k] for k in ("repository", "revision", "license")}, "blocks": blocks}
    return {**packet, "sha256": digest(packet)}


def verify_packet(packet):
    if not isinstance(packet, dict) or "sha256" not in packet:
        raise ValueError("Expected a review packet with a SHA-256 digest.")
    body = {k: v for k, v in packet.items() if k != "sha256"}
    if digest(body) != packet["sha256"]:
        raise ValueError("Packet SHA-256 does not match its canonical JSON.")
    # Rebuild exclusively from this checkout. No paths, URLs, or counts in the
    # untrusted packet control the replay. Canonical JSON distinguishes 1 from true.
    rebuilt = build_packet()
    if any(block["status"] == "unavailable" for block in rebuilt["blocks"]):
        raise ValueError("Offline evidence or importer replay is unavailable. Verification is incomplete.")
    if encode(packet) != encode(rebuilt):
        raise ValueError("Packet differs from the pinned archive evidence and offline replay.")


def _unique_fields(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON field in review packet.")
        obj[key] = value
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, metavar="FILE", help="Verify a downloaded packet offline.")
    args = parser.parse_args()
    try:
        if args.verify is None:
            print(encode(build_packet()))
        else:
            packet = json.loads(args.verify.read_bytes(), object_pairs_hook=_unique_fields)
            verify_packet(packet)
            print(f"Verified transfer review packet {packet['sha256']}")
            for block in packet["blocks"]:
                print(f"{block['block_number']}: {block['status']}")
    except (OSError, ValueError, RecursionError) as exc:
        print(f"Transfer review failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
