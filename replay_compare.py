"""Compare fixed Balancer Vault archive rows with separately identified replay observations."""
import argparse
from copy import deepcopy
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

import capture_providers
from chain import MAX_EVENTS
import transfer_review as archive
from store import digest, encode

CAPTURE_PATH = archive.FIXTURE_DIR / "provider-capture.json"
HASH = re.compile(r"0x[0-9a-f]{64}")
ADDRESS = re.compile(r"0x[0-9a-f]{40}")
AMOUNT = re.compile(r"(?:0|[1-9][0-9]{0,77})")
MAX_UINT256 = 2**256 - 1


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _natural(value):
    return type(value) is int and 0 <= value < 2**53


def _hex(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _index_rows(rows, label):
    _require(isinstance(rows, list) and len(rows) <= MAX_EVENTS, f"{label} rows are missing, malformed or oversized.")
    indexed = {}
    for row in rows:
        _require(isinstance(row, dict) and row.keys() == set(archive.ROW_FIELDS),
                 f"{label} contains an incomplete transfer tuple.")
        i, raw = row["log_index"], row["raw_amount"]
        _require(_natural(i) and i not in indexed, f"{label} has a repeated or invalid block-wide log index.")
        _require(_hex(HASH, row["tx_hash"]) and
                 all(_hex(ADDRESS, row[k]) for k in ("contract", "from_address", "to_address")),
                 f"{label} log {i} has a malformed hash or address.")
        _require(archive.VAULT in (row["from_address"], row["to_address"]),
                 f"{label} log {i} does not involve the scoped Vault.")
        _require(_hex(AMOUNT, raw) and int(raw) <= MAX_UINT256,
                 f"{label} log {i} has an invalid raw uint256 amount.")
        indexed[i] = row
    return indexed


def _excluded_rows(entries, direction, eligible):
    _require(isinstance(entries, list), f"Missing excluded-log witnesses for the {direction} filter.")
    index = {}
    mask = archive.FILTERS[direction]
    for entry in entries:
        _require(isinstance(entry, dict), f"Malformed excluded {direction} log.")
        i, topics = entry.get("log_index"), entry.get("topics")
        _require(_natural(i) and i not in index and i not in eligible and _hex(HASH, entry.get("tx_hash")),
                 f"Invalid or repeated excluded {direction} log identity.")
        _require(isinstance(topics, list) and len(mask) <= len(topics) <= 4 and len(topics) != 3
                 and all(_hex(HASH, t) for t in topics)
                 and all(t is None or t == topics[j] for j, t in enumerate(mask)),
                 f"Excluded {direction} log {i} lacks an out-of-scope topic shape for that filter.")
        index[i] = entry
    return index


def _observation_rows(observed, reference):
    height = reference["block_number"]
    _require(observed.get("attempted") is True and observed.get("stage") == "complete",
             "Importer completion was not witnessed.")
    _require(observed.get("chain_id") == 1, "Mainnet chain ID was not witnessed.")
    block_hash = observed.get("block_hash")
    _require(_hex(HASH, block_hash), "Requested block header hash is absent or malformed.")
    rows = _index_rows(observed.get("rows"), "Observation")
    _require(_natural(observed.get("count")) and observed["count"] == len(rows),
             "Observed count does not equal the number of full rows.")
    witness = observed.get("witness")
    _require(isinstance(witness, dict), "Missing importer witnesses.")
    _require(_natural(witness.get("finalized_height")) and witness["finalized_height"] >= height,
             "Finalized height does not cover the requested block.")
    for key in ("requested_block_number", "end_block_number"):
        _require(type(witness.get(key)) is int and witness[key] == height,
                 "Requested and final header witnesses must both identify the selected height.")
    _require(witness.get("end_block_hash") == block_hash, "Final header hash does not match the requested header.")

    counts, filters, excluded = (witness.get(k) for k in ("filter_counts", "filter_rows", "filter_excluded"))
    _require(all(isinstance(v, dict) for v in (counts, filters, excluded)), "Directional filter witnesses are missing.")
    limit = MAX_EVENTS
    if block_hash == reference["expected"]["block_hash"]:
        limit = min(limit, reference["coverage"]["logs"])
    excluded_by_direction = {}
    for direction, address_field in (("sender", "from_address"), ("recipient", "to_address")):
        _require(_natural(counts.get(direction)), f"Missing or invalid {direction} filter count.")
        candidates = _index_rows(filters.get(direction), f"{direction.capitalize()} filter")
        other = _excluded_rows(excluded.get(direction), direction, rows)
        excluded_by_direction[direction] = other
        if block_hash == reference["expected"]["block_hash"]:
            _require(all(i < reference["coverage"]["logs"] for i in (*other, *candidates)),
                     "A block-wide log index exceeds the size of the pinned block.")
        _require(counts[direction] == len(candidates) + len(other) and counts[direction] <= limit,
                 f"{direction.capitalize()} filter count does not equal its eligible and excluded logs.")
        scoped = {i: row for i, row in rows.items() if row[address_field] == archive.VAULT}
        _require(candidates == scoped, f"{direction.capitalize()} filter rows do not corroborate the observation.")

    # An excluded self-transfer log would appear in both directional replies too.
    for direction, opposite, pos in (("sender", "recipient", 2), ("recipient", "sender", 1)):
        for i, entry in excluded_by_direction[direction].items():
            topics = entry["topics"]
            other = excluded_by_direction[opposite].get(i)
            if len(topics) > pos and topics[pos] == archive.PADDED_VAULT:
                _require(other == entry, "Directional replies disagree on an excluded self-transfer log.")
            else:
                _require(other is None, "Different excluded logs share a block-wide log index.")

    receipts = witness.get("receipts")
    _require(isinstance(receipts, list), "Receipt witnesses are missing.")
    seen, corroborated = set(), {}
    for receipt in receipts:
        _require(isinstance(receipt, dict), "Malformed receipt witness.")
        tx = receipt.get("tx_hash")
        _require(_hex(HASH, tx) and tx not in seen and receipt.get("returned_tx_hash") == tx,
                 "Receipt has a repeated or inconsistent transaction identity.")
        seen.add(tx)
        _require(type(receipt.get("block_number")) is int and receipt["block_number"] == height
                 and receipt.get("block_hash") == block_hash, "Receipt inclusion differs from the requested block.")
        status = receipt.get("status")
        _require(type(status) is int and status in (0, 1), "Missing or invalid receipt success status.")
        entries = _index_rows(receipt.get("rows"), f"Receipt {tx}")
        _require(_natural(receipt.get("log_count")) and len(entries) <= receipt["log_count"] <= limit,
                 "Receipt log count is outside the supported bounds for its projected rows.")
        for i, row in entries.items():
            _require(status == 1 and row["tx_hash"] == tx and i not in corroborated,
                     f"Log {i} lacks unique successful receipt inclusion.")
            corroborated[i] = row
    _require(sum(r["log_count"] for r in receipts) <= reference["coverage"]["logs"]
             or block_hash != reference["expected"]["block_hash"], "Receipt log counts exceed the pinned block total.")
    _require(corroborated == rows, "Successful receipt rows and observed rows differ.")
    return rows


def _archive_rows(reference):
    coverage = reference.get("coverage")
    _require(isinstance(coverage, dict) and coverage.get("complete") is True, "Archive coverage is incomplete.")
    for unit in ("receipts", "logs"):
        examined = coverage.get(unit + "_examined")
        _require(_natural(coverage.get(unit)) and _natural(examined) and examined == coverage[unit],
                 f"Examined {unit} do not cover the archive.")
    expected = reference.get("expected")
    _require(isinstance(expected, dict) and _hex(HASH, expected.get("block_hash")),
             "Archive block hash is missing or malformed.")
    rows = _index_rows(expected.get("rows"), "Archive")
    _require(_natural(expected.get("count")) and expected["count"] == len(rows),
             "Archive count differs from its rows.")
    return rows


def compare_block(reference, observation, *, captured_at=None):
    """Retain both sides. Issue a tuple diff only after their evidence is complete."""
    diff = {"block_hash_changed": None, "missing": [], "extra": [], "changed": []}
    result = {"block_number": reference.get("block_number"), "archive": reference.get("archive"),
              "coverage": reference.get("coverage"), "expected": reference.get("expected"), "observed": observation,
              "decision": "incomplete", "issues": [], "diff": diff}
    try:
        _require(type(reference.get("block_number")) is int and reference["block_number"] in archive.BLOCKS,
                 "Archive reference does not identify one of the fixed windows.")
        expected = _archive_rows(reference)
        _require(isinstance(observation, dict), "Missing observation record.")
        _require(type(observation.get("block_number")) is int and observation["block_number"] == reference["block_number"]
                 and observation.get("address") == archive.VAULT
                 and observation.get("pinned_block_hash") == reference["expected"]["block_hash"],
                 "Configured attempt height, Vault or archive hash does not identify this window.")
        if captured_at is not None:
            _require(type(observation.get("attempted")) is bool, "Missing or invalid public attempt flag.")
            if observation["attempted"]:
                _require(_utc(observation.get("started_at")) <= _utc(captured_at),
                         "Public attempt starts after the capture was completed.")
            else:
                _require(observation.get("started_at") is None, "Unattempted window claims a start time.")
        chain_id = observation.get("chain_id")
        _require(chain_id is None or type(chain_id) is int and chain_id == 1, "Chain ID differs from Ethereum mainnet.")
        error_kind = observation.get("error_kind")
        if error_kind in ("not_run", "transport"):
            _require(observation.get("attempted") is (error_kind == "transport"),
                     "Availability status contradicts the attempt record.")
            _require(observation.get("rows") is None and observation.get("count") is None,
                     "Unavailable observation also claims a completed row set.")
            stage = observation.get("stage")
            if error_kind == "not_run":
                _require(stage == "not_run" and chain_id is None and observation.get("started_at") is None,
                         "Skipped window contains an incompatible attempt, stage or chain reply.")
            else:
                _require((stage == "chain_id" and chain_id is None) or (stage == "finalized_header" and chain_id == 1),
                         "Transport failure conflicts with the preflight stage or chain reply.")
            _require(observation.get("block_hash") is None and isinstance(observation.get("error"), str)
                     and observation["error"].strip(), "Availability record is missing its failure reason or claims a header.")
            witness = observation.get("witness")
            _require(isinstance(witness, dict) and witness.get("receipts") == []
                     and all(witness.get(k) is None for k in ("requested_block_number", "finalized_height",
                                                              "end_block_hash", "end_block_number"))
                     and all(witness.get(k) == {"sender": None, "recipient": None}
                             for k in ("filter_counts", "filter_rows"))
                     and ("filter_excluded" not in witness or witness["filter_excluded"] == {"sender": None, "recipient": None}),
                     "Preflight or skipped window contains conflicting importer witnesses.")
            result["decision"] = "unavailable"
            result["issues"].append(observation.get("error") or "No provider observation was available.")
            return result
        if error_kind == "incomplete":
            raise ValueError(observation.get("error") or "Importer stopped before all witnesses were collected.")
        _require(error_kind is None and observation.get("error") is None, "Unknown or inconsistent observation outcome.")
        observed = _observation_rows(observation, reference)
    except ValueError as exc:
        result["issues"].append(str(exc))
        return result

    diff["block_hash_changed"] = reference["expected"]["block_hash"] != observation["block_hash"]
    diff["missing"] = [expected[i] for i in sorted(expected.keys() - observed.keys())]
    diff["extra"] = [observed[i] for i in sorted(observed.keys() - expected.keys())]
    for i in sorted(expected.keys() & observed.keys()):
        fields = [k for k in archive.ROW_FIELDS if expected[i][k] != observed[i][k]]
        if fields:
            diff["changed"].append({"log_index": i, "fields": fields, "expected": expected[i], "observed": observed[i]})
    if any(diff.values()):
        result["decision"] = "disagreement"
        if diff["block_hash_changed"]:
            result["issues"].append("Archive and observation identify different block hashes.")
        for category in ("missing", "extra", "changed"):
            if diff[category]:
                result["issues"].append(f"{category.capitalize()} block-wide log indices: " +
                                        ", ".join(str(r["log_index"]) for r in diff[category]) + ".")
    else:
        result["decision"] = "matched" if observed else "verified_zero"
    return result


def _fixture_block(reference):
    number = reference["block_number"]
    packed = (archive.FIXTURE_DIR / f"{number}.json.gz").read_bytes()
    _require(hashlib.sha256(packed).hexdigest() == reference["archive"]["fixture_sha256"],
             "Bundled receipt projection differs from its pin.")
    fixture = json.loads(gzip.decompress(packed))
    legacy_witness = {"receipt_transactions": [], "filter_counts": {}, "end_header_checked": False}
    observation = capture_providers.capture_block(
        number, reference["expected"]["block_hash"], "https://ethereum.publicnode.com",
        http_send=archive.FixtureRPC(fixture, legacy_witness), started_at="offline")
    observation["started_at"] = None
    return observation


def _diagnostics(fixture_observations):
    """Change internally consistent fixture observations to exercise the diff."""
    examples = deepcopy(fixture_observations)
    for case, index, field, value in ((examples[0], 138, "raw_amount", "433410975363819"),
                                      (examples[1], 406, "log_index", 407)):
        # Keep the altered observation's own filters and receipts internally consistent.
        witness = case["witness"]
        groups = [case["rows"], *witness["filter_rows"].values(), *(r["rows"] for r in witness["receipts"])]
        for rows in groups:
            for row in rows:
                if row["log_index"] == index:
                    row[field] = value
    examples[2]["witness"]["filter_counts"]["recipient"] = None
    examples[2]["witness"]["filter_rows"]["recipient"] = None
    examples[2]["witness"]["filter_excluded"]["recipient"] = None
    return examples


def read_json(path):
    data = json.loads(path.read_bytes(), object_pairs_hook=archive._unique_fields)
    _require(isinstance(data, dict), "Expected a JSON object.")
    return data


def _utc(stamp):
    _require(isinstance(stamp, str), "Expected a dated UTC capture or attempt.")
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    _require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0,
             "Capture and attempt timestamps must identify UTC instants.")
    return parsed


def _validate_capture(capture, scope):
    _require(isinstance(capture, dict) and capture.get("schema") == "vision/provider-capture@1"
             and capture.get("source_mode") == "public_rpc", "Unrecognized public capture format.")
    _require(encode(capture.get("scope")) == encode(scope), "Capture scope differs from the pinned review scope.")
    _utc(capture.get("captured_at"))
    expected = {identifier: (name, endpoint) for identifier, name, endpoint in capture_providers.PROVIDERS}
    sources = capture.get("providers")
    _require(isinstance(sources, list) and len(sources) == len(expected), "Expected both fixed provider records.")
    by_id = {}
    for source in sources:
        _require(isinstance(source, dict), "Malformed provider record.")
        key = source.get("id")
        _require(isinstance(key, str) and key in expected and key not in by_id
                 and (source.get("name"), source.get("endpoint")) == expected[key],
                 "Duplicate or incorrect provider identity or endpoint.")
        by_id[key] = source
    return [by_id[key] for key in expected]


def build_packet(capture=None):
    reference = archive.build_packet()
    _require(all(block["status"] in ("matched", "verified_zero") for block in reference["blocks"]),
             "Pinned v1.2 archive and fixture review could not be verified.")
    if capture is None:
        capture = read_json(CAPTURE_PATH)
        _require(digest(capture) == "eac94ede47b9f5ca728cac3276d14824f6c66de70c8459c49982ddfb80a55b79",
                 "Bundled public capture differs from its pinned SHA-256.")
    public = _validate_capture(capture, reference["scope"])
    refs = reference["blocks"]
    fixtures = [_fixture_block(record) for record in refs]
    sources = []

    def add(identifier, label, kind, description, observations, captured_at=None, endpoint=None):
        blocks = [compare_block(record, obs, captured_at=captured_at) for record, obs in zip(refs, observations, strict=True)]
        sources.append({"id": identifier, "label": label, "kind": kind, "description": description,
                        "captured_at": captured_at, "endpoint": endpoint, "blocks": blocks})

    add("fixture", "Constructed fixture replay", "fixture",
        "The importer read constructed RPC responses from the pinned receipt projections.", fixtures)
    for provider in public:
        observations = provider.get("blocks")
        _require(isinstance(observations, list) and len(observations) == len(refs),
                 "Capture must retain all three attempted or skipped windows per provider.")
        _require(all(isinstance(obs, dict) for obs in observations), "Malformed provider block observation.")
        # Captures have three explicit window slots in scope order. Check the height
        # inside each slot independently so a swapped response cannot be compared.
        add(provider["id"], provider["name"], "public_capture",
            "Dated public RPC capture. Each window retains its attempt, stage and returned evidence.",
            observations, capture["captured_at"], provider["endpoint"])
    add("diagnostic", "Constructed diagnostic examples", "diagnostic",
        "Fixture edits demonstrate a changed amount, a moved log index and a missing recipient filter.",
        _diagnostics(fixtures))
    packet = {"schema": "vision/replay-compare@1", "scope": reference["scope"], "archive": reference["archive"],
              "fixture_packet_sha256": reference["sha256"],
              "capture": {"captured_at": capture["captured_at"], "sha256": digest(capture)}, "sources": sources}
    return {**packet, "sha256": digest(packet)}


def packet_bytes(capture=None):
    return (json.dumps(build_packet(capture), indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def verify_packet(packet, capture=None):
    _require(isinstance(packet, dict) and "sha256" in packet, "Missing comparison packet digest.")
    body = {key: value for key, value in packet.items() if key != "sha256"}
    _require(digest(body) == packet["sha256"], "Packet SHA-256 differs from its canonical JSON.")
    _require(encode(packet) == encode(build_packet(capture)),
             "Comparison differs from the pinned archive, replay witnesses or selected capture.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, metavar="FILE", help="Verify an exported comparison packet offline.")
    parser.add_argument("--capture", type=Path, metavar="FILE", help="Use this separately supplied provider capture.")
    args = parser.parse_args(argv)
    try:
        capture = read_json(args.capture) if args.capture else None
        if args.verify:
            packet = read_json(args.verify)
            verify_packet(packet, capture)
            print(f"Verified comparison packet {packet['sha256']}")
        else:
            sys.stdout.buffer.write(packet_bytes(capture))
    except (ValueError, OSError, RecursionError) as exc:
        print(f"Replay comparison failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
