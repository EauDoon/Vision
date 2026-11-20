"""Capture the fixed Vault cases from two public Ethereum gateways."""
import argparse
from datetime import datetime, timezone
import json

from chain import MAX_EVENTS, ChainError, TransportError, _endpoint, _hash, _log_evidence, _quantity, crawl
from transfer_review import BLOCKS, FILTERS, PADDED_VAULT, SIGNATURE, VAULT, build_packet, event_rows


PROVIDERS = (
    ("publicnode", "Allnodes PublicNode", "https://ethereum-rpc.publicnode.com"),
    ("1rpc", "Automata 1RPC", "https://public.1rpc.io/eth"),
)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _blank_block(number, pin):
    return {
        "block_number": number, "address": VAULT, "pinned_block_hash": pin,
        "attempted": False, "started_at": None, "stage": "not_run", "error_kind": None, "error": None,
        "chain_id": None, "block_hash": None, "count": None, "rows": None,
        "witness": {
            "finalized_height": None, "requested_block_number": None,
            "end_block_number": None, "end_block_hash": None,
            "filter_counts": {"sender": None, "recipient": None},
            "filter_rows": {"sender": None, "recipient": None}, "receipts": [],
            "filter_excluded": {"sender": None, "recipient": None},
        },
    }


def _transfer_rows(logs):
    """Project receipt or filter replies independently of the importer's event output."""
    if len(logs) > MAX_EVENTS:
        raise ChainError("Log list exceeds the importer limit.")
    rows = []
    for log in logs:
        topics = log.get("topics") if isinstance(log, dict) else None
        if not isinstance(topics, list):
            raise ChainError("Log evidence is missing topics.")
        if len(topics) != 3 or not all(isinstance(t, str) for t in topics):
            continue
        signature, sender, recipient = [t.lower() for t in topics]
        if signature != SIGNATURE or PADDED_VAULT not in (sender, recipient):
            continue
        evidence = _log_evidence(log)
        if sender[2:26] != "0" * 24 or recipient[2:26] != "0" * 24:
            raise ChainError("Transfer has malformed indexed addresses.")
        rows.append({"tx_hash": evidence.tx_hash, "log_index": evidence.index, "contract": evidence.contract,
                     "from_address": "0x" + sender[-40:], "to_address": "0x" + recipient[-40:],
                     "raw_amount": str(int(evidence.data, 16))})
    return sorted(rows, key=lambda row: (row["log_index"], row["tx_hash"]))


def _filter_projection(logs, pattern, block):
    """Account for every returned log, including other event shapes sharing the signature."""
    if len(logs) > MAX_EVENTS:
        raise ChainError("Filter response exceeds the importer limit.")
    candidates, excluded = [], []
    for log in logs:
        if not isinstance(log, dict) or not isinstance(log.get("topics"), list):
            raise ChainError("Filter log is missing topics.")
        if not len(pattern) <= len(log["topics"]) <= 4:
            raise ChainError("Filter log has impossible topic count for the requested direction.")
        topics = [_hash(t) for t in log["topics"]]
        if any(value is not None and value != actual for value, actual in zip(pattern, topics)):
            raise ChainError("Provider returned a log outside the requested filter direction.")
        if (log.get("removed") is not False or _quantity(log.get("blockNumber")) != block["block_number"]
                or _hash(log.get("blockHash")) != block["block_hash"]):
            raise ChainError("Filter log has inconsistent block inclusion.")
        if len(topics) == 3:
            candidates.append(log)
        else:
            excluded.append({"tx_hash": _hash(log.get("transactionHash")),
                             "log_index": _quantity(log.get("logIndex")), "topics": topics})
    return _transfer_rows(candidates), excluded


class CaptureWitness:
    """Record requests and reply fields used by this one-block importer run."""

    def __init__(self, block):
        self.block = block
        self.witness = block["witness"]

    def __call__(self, phase, method, params, result):
        block, witness = self.block, self.witness
        if method == "eth_chainId":
            block["stage"] = "chain_id"
            if phase == "response":
                block["chain_id"] = _quantity(result)
        elif method == "eth_getBlockByNumber":
            selector, full = params
            stage = "finalized_header" if selector == "finalized" else "block_header" if full else "end_header"
            block["stage"] = stage
            if phase == "response":
                if not isinstance(result, dict):
                    raise ChainError("Missing header fields.")
                height = _quantity(result.get("number"))
                if stage == "finalized_header":
                    witness["finalized_height"] = height
                elif stage == "block_header":
                    witness["requested_block_number"] = height
                    block["block_hash"] = _hash(result.get("hash"))
                else:
                    witness["end_block_number"] = height
                    witness["end_block_hash"] = _hash(result.get("hash"))
                    if height != block["block_number"]:
                        raise ChainError("Final header has the wrong block height.")
        elif method == "eth_getLogs":
            query, = params
            direction = next((key for key, topics in FILTERS.items() if topics == query.get("topics")), None)
            if not direction or query.get("fromBlock") != hex(block["block_number"]) or query.get("toBlock") != query["fromBlock"]:
                raise ChainError("Importer requested a filter outside the capture scope.")
            block["stage"] = direction + "_filter"
            if phase == "response":
                if not isinstance(result, list):
                    raise ChainError("Missing filter log list.")
                witness["filter_counts"][direction] = len(result)
                rows, excluded = _filter_projection(result, FILTERS[direction], block)
                witness["filter_rows"][direction] = rows
                witness["filter_excluded"][direction] = excluded
        elif method == "eth_getTransactionReceipt":
            block["stage"] = "receipt"
            if phase == "request":
                witness["receipts"].append({"tx_hash": params[0], "returned_tx_hash": None,
                                            "block_number": None, "block_hash": None, "status": None,
                                            "log_count": None, "rows": None})
            else:
                receipt = witness["receipts"][-1]
                if not isinstance(result, dict):
                    raise ChainError("Missing receipt reply.")
                receipt["returned_tx_hash"] = _hash(result.get("transactionHash"))
                receipt["block_number"] = _quantity(result.get("blockNumber"))
                receipt["block_hash"] = _hash(result.get("blockHash"))
                receipt["status"] = _quantity(result.get("status"))
                logs = result.get("logs")
                if not isinstance(logs, list):
                    raise ChainError("Receipt is missing its log list.")
                receipt["log_count"] = len(logs)
                receipt["rows"] = _transfer_rows(logs)


def capture_block(number, pinned_block_hash, endpoint, *, http_send=None, started_at=None):
    if number not in BLOCKS:
        raise ValueError("Capture is limited to the three pinned block heights.")
    if http_send is None and endpoint not in {url for _, _, url in PROVIDERS}:
        raise ValueError("Public capture requires one of the two fixed keyless endpoints.")
    block = _blank_block(number, pinned_block_hash)
    block.update(attempted=True, started_at=started_at or utc_now(), stage="configuration")
    try:
        result = crawl(VAULT, rpc_url=endpoint, start=number, end=number, max_blocks=1,
                       http_send=http_send, observer=CaptureWitness(block))
        witness = block["witness"]
        if (None in witness["filter_counts"].values() or witness["end_block_number"] != number
                or witness["end_block_hash"] != block["block_hash"]):
            raise ChainError("Importer returned without both filters and a concordant final header.")
        rows = event_rows(result)
        block.update(count=len(rows), rows=rows, stage="complete")
    except ChainError as exc:
        preflight = block["stage"] in {"chain_id", "finalized_header"}
        block["error_kind"] = "transport" if preflight and isinstance(exc, TransportError) else "incomplete"
        block["error"] = str(exc)
    return block


def capture_providers():
    archive = build_packet()
    pins = {b["block_number"]: b["expected"]["block_hash"] for b in archive["blocks"]}
    providers = []
    for identifier, name, endpoint in PROVIDERS:
        blocks = []
        stop = False
        for number in BLOCKS:
            if stop:
                block = _blank_block(number, pins[number])
                block.update(error_kind="not_run", error="Skipped after this provider's transport failed during preflight.")
            else:
                block = capture_block(number, pins[number], endpoint)
                stop = block["error_kind"] == "transport"
            blocks.append(block)
        providers.append({"id": identifier, "name": name, "endpoint": endpoint, "blocks": blocks})
    return {"schema": "vision/provider-capture@1", "captured_at": utc_now(), "source_mode": "public_rpc",
            "scope": archive["scope"], "providers": providers}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", action="store_true", required=True,
                        help="Read the three fixed blocks from PublicNode and Automata 1RPC.")
    parser.parse_args(argv)
    try:
        for _, _, endpoint in PROVIDERS:
            _endpoint(endpoint)
    except ChainError:
        parser.error("Set VISION_RPC_ALLOWED_HOSTS=public.1rpc.io for this command.")
    report = capture_providers()
    print(json.dumps(report, indent=2))
    return int(any(block["error_kind"] for provider in report["providers"] for block in provider["blocks"]))


if __name__ == "__main__":
    raise SystemExit(main())
