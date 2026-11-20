"""Independent comparison and offline reviewer acceptance for the three fixed windows."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import replay_compare
from store import encode
from transfer_review import VAULT, build_packet as build_v12_packet


ROOT = Path(__file__).resolve().parents[1]
FIRST, SECOND, EMPTY = 22_431_084, 17_034_870, 17_034_869
OTHER_HASH = "0x" + "ab" * 32
OTHER_ADDRESS = "0x" + "3a" * 20


def observed(reference, *, rows=None, block_hash=None):
    """Construct coherent test evidence independently from the comparison engine."""
    number = reference["block_number"]
    header = block_hash or reference["expected"]["block_hash"]
    rows = copy.deepcopy(reference["expected"]["rows"] if rows is None else rows)
    by_direction = {
        "sender": [r for r in rows if r["from_address"] == VAULT],
        "recipient": [r for r in rows if r["to_address"] == VAULT],
    }
    receipts = []
    for tx_hash in sorted({row["tx_hash"] for row in rows}):
        included = [r for r in rows if r["tx_hash"] == tx_hash]
        receipts.append({"tx_hash": tx_hash, "returned_tx_hash": tx_hash,
                         "block_number": number, "block_hash": header, "status": 1,
                         "log_count": len(included), "rows": copy.deepcopy(included)})
    return {
        "block_number": number, "chain_id": 1, "address": VAULT,
        "pinned_block_hash": reference["expected"]["block_hash"],
        "block_hash": header, "rows": rows, "count": len(rows),
        "attempted": True, "started_at": "2026-11-20T07:00:00Z",
        "stage": "complete", "error_kind": None, "error": None,
        "witness": {
            "finalized_height": number + 1, "requested_block_number": number,
            "end_block_number": number, "end_block_hash": header,
            "filter_counts": {direction: len(matches) for direction, matches in by_direction.items()},
            "filter_rows": copy.deepcopy(by_direction), "filter_excluded": {"sender": [], "recipient": []},
            "receipts": receipts,
        },
    }


def packet_digest(packet):
    body = {key: value for key, value in packet.items() if key != "sha256"}
    return hashlib.sha256(encode(body).encode("utf-8")).hexdigest()


class ReplayComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v12 = build_v12_packet()
        cls.references = {b["block_number"]: b for b in cls.v12["blocks"]}

    def compare(self, obs, number=FIRST):
        return replay_compare.compare_block(self.references[number], obs)

    def assert_incomplete(self, obs, number=FIRST):
        result = self.compare(obs, number)
        self.assertEqual(result["decision"], "incomplete", result["issues"])
        self.assertTrue(result["issues"])
        return result

    def test_corroborated_rows_and_covered_zero(self):
        for number, count, expected in ((FIRST, 2, "matched"), (SECOND, 2, "matched"), (EMPTY, 0, "verified_zero")):
            with self.subTest(block=number):
                ref = self.references[number]
                result = self.compare(observed(ref), number)
                self.assertEqual(result["decision"], expected, result["issues"])
                self.assertEqual(result["expected"]["count"], count)
                self.assertEqual(result["observed"]["rows"], ref["expected"]["rows"])
                for diff in ("missing", "extra", "changed"):
                    self.assertEqual(result["diff"][diff], [])
        coverage = self.references[EMPTY]["coverage"]
        self.assertEqual((coverage["receipts_examined"], coverage["logs_examined"]), (93, 208))

    def test_wrong_chain_address_and_height_cannot_match(self):
        for field, value in (("chain_id", 10), ("chain_id", True), ("address", OTHER_ADDRESS),
                             ("block_number", SECOND), ("block_number", float(FIRST)),
                             ("pinned_block_hash", OTHER_HASH)):
            with self.subTest(field=field, value=value):
                obs = observed(self.references[FIRST])
                obs[field] = value
                result = self.assert_incomplete(obs)
                self.assertEqual(result["observed"][field], value)
                self.assertEqual(result["expected"]["count"], 2)

    def test_equal_counts_with_different_block_hash_even_at_zero(self):
        for number in (FIRST, EMPTY):
            with self.subTest(block=number):
                ref = self.references[number]
                result = self.compare(observed(ref, block_hash=OTHER_HASH), number)
                self.assertEqual(result["decision"], "disagreement", result["issues"])
                self.assertTrue(result["diff"]["block_hash_changed"])
                self.assertEqual(result["expected"]["block_hash"], ref["expected"]["block_hash"])
                self.assertEqual(result["observed"]["block_hash"], OTHER_HASH)
                self.assertEqual(result["expected"]["count"], result["observed"]["count"])

    def test_event_diffs_use_block_wide_log_index_and_keep_both_sides(self):
        ref = self.references[FIRST]
        for key, new_value in (("contract", OTHER_ADDRESS), ("tx_hash", OTHER_HASH),
                               ("from_address", OTHER_ADDRESS), ("raw_amount", "99")):
            with self.subTest(field=key):
                changed = copy.deepcopy(ref["expected"]["rows"])
                changed[0][key] = new_value
                result = self.compare(observed(ref, rows=changed))
                self.assertEqual(result["decision"], "disagreement", result["issues"])
                self.assertEqual(result["expected"]["count"], result["observed"]["count"])
                self.assertEqual(result["diff"]["missing"], [])
                self.assertEqual(result["diff"]["extra"], [])
                pair, = result["diff"]["changed"]
                self.assertEqual(pair["log_index"], 138)
                self.assertEqual(pair["fields"], [key])
                self.assertEqual(pair["expected"], ref["expected"]["rows"][0])
                self.assertEqual(pair["observed"], changed[0])

    def test_missing_and_extra_at_equal_counts(self):
        ref = self.references[FIRST]
        rows = copy.deepcopy(ref["expected"]["rows"])
        rows[0]["log_index"] = 140
        result = self.compare(observed(ref, rows=rows))
        self.assertEqual(result["decision"], "disagreement", result["issues"])
        self.assertEqual(result["diff"]["changed"], [])
        self.assertEqual(result["diff"]["missing"], [ref["expected"]["rows"][0]])
        self.assertEqual(result["diff"]["extra"], [rows[0]])

    def test_invalid_counts_and_rows_do_not_turn_into_disagreements(self):
        for field, value in (("count", True), ("count", 2.0), ("count", "2"), ("count", -1),
                             ("log_index", True), ("log_index", -1), ("log_index", 138.0),
                             ("raw_amount", 0), ("raw_amount", True),
                             ("raw_amount", "-1"), ("raw_amount", "1.1"), ("raw_amount", "0x7")):
            with self.subTest(field=field, value=value):
                obs = observed(self.references[FIRST])
                if field == "count":
                    obs[field] = value
                else:
                    obs["rows"][0][field] = value
                self.assert_incomplete(obs)

    def test_duplicate_index_is_incomplete_even_with_different_transactions(self):
        ref = self.references[FIRST]
        rows = copy.deepcopy(ref["expected"]["rows"])
        rows[1].update(tx_hash=OTHER_HASH, log_index=rows[0]["log_index"])
        result = self.assert_incomplete(observed(ref, rows=rows))
        self.assertEqual(len(result["observed"]["rows"]), 2)

    def test_zero_needs_archive_coverage_both_filters_and_final_header(self):
        ref = self.references[EMPTY]
        for key in ("sender", "recipient"):
            with self.subTest(missing=key):
                obs = observed(ref)
                obs["witness"]["filter_counts"][key] = None
                self.assert_incomplete(obs, EMPTY)
        for key, value in (("end_block_hash", None), ("finalized_height", EMPTY - 1),
                           ("finalized_height", True), ("requested_block_number", SECOND),
                           ("end_block_number", SECOND)):
            with self.subTest(field=key):
                obs = observed(ref)
                obs["witness"][key] = value
                self.assert_incomplete(obs, EMPTY)
        missing_archive = copy.deepcopy(ref)
        missing_archive["coverage"]["complete"] = False
        result = replay_compare.compare_block(missing_archive, observed(ref))
        self.assertEqual(result["decision"], "incomplete")
        self.assertEqual(result["observed"]["count"], 0)

    def test_nonempty_filter_can_only_support_zero_if_every_exclusion_is_explained(self):
        obs = observed(self.references[EMPTY])
        witness = obs["witness"]
        witness["filter_counts"]["sender"] = 1
        self.assert_incomplete(obs, EMPTY)
        excluded = {"tx_hash": OTHER_HASH, "log_index": 12, "topics": [
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
            "0x" + VAULT[2:].rjust(64, "0"), "0x" + OTHER_ADDRESS[2:].rjust(64, "0"), "0x" + "1" * 64]}
        witness["filter_excluded"]["sender"] = [excluded]
        self.assertEqual(self.compare(obs, EMPTY)["decision"], "verified_zero")
        excluded["topics"].pop()
        self.assert_incomplete(obs, EMPTY)

    def test_partial_receipt_and_filter_evidence_stays_inspectable(self):
        ref = self.references[FIRST]
        for label in ("receipt", "failed_receipt", "receipt_status_bool", "receipt_log",
                      "receipt_hash", "filter_rows", "filter_count_bool"):
            with self.subTest(missing=label):
                obs = observed(ref)
                witness = obs["witness"]
                if label == "receipt":
                    witness["receipts"] = []
                elif label == "failed_receipt":
                    witness["receipts"][0]["status"] = 0
                elif label == "receipt_status_bool":
                    witness["receipts"][0]["status"] = True
                elif label == "receipt_log":
                    witness["receipts"][0]["rows"].pop()
                elif label == "receipt_hash":
                    witness["receipts"][0]["block_hash"] = OTHER_HASH
                elif label == "filter_rows":
                    witness["filter_rows"]["recipient"] = []
                else:
                    witness["filter_counts"]["sender"] = True
                result = self.assert_incomplete(obs)
                self.assertEqual(result["observed"]["rows"], obs["rows"])
                self.assertEqual(result["observed"]["witness"], witness)

    def test_transport_failure_skipped_block_and_partial_attempt(self):
        ref = self.references[FIRST]
        failures = []
        for error_kind, attempted, stage, expected in (
            ("transport", True, "chain_id", "unavailable"),
            ("not_run", False, "not_run", "unavailable"),
            ("incomplete", True, "receipt", "incomplete"),
        ):
            with self.subTest(error_kind=error_kind):
                obs = observed(ref)
                obs.update(error_kind=error_kind, error=f"test {error_kind}", attempted=attempted,
                           stage=stage, count=None, rows=None)
                if error_kind in ("transport", "not_run"):
                    obs.update(block_hash=None, chain_id=None)
                    obs["witness"].update(finalized_height=None, requested_block_number=None,
                                          end_block_hash=None, end_block_number=None, receipts=[],
                                          filter_rows={"sender": None, "recipient": None},
                                          filter_excluded={"sender": None, "recipient": None},
                                          filter_counts={"sender": None, "recipient": None})
                if not attempted:
                    obs["started_at"] = None
                result = self.compare(obs)
                self.assertEqual(result["decision"], expected, result["issues"])
                self.assertEqual(result["observed"]["error_kind"], error_kind)
                self.assertIs(result["observed"]["attempted"], attempted)
                self.assertIsNone(result["observed"]["count"])
                self.assertTrue(result["issues"])
                failures.append(tuple(result["issues"]))
        self.assertEqual(len(set(failures)), 3)

    def test_skipped_record_cannot_be_assigned_to_the_wrong_window(self):
        capture = json.loads(replay_compare.CAPTURE_PATH.read_bytes())
        skipped = copy.deepcopy(capture["providers"][0]["blocks"][1])
        self.assertFalse(skipped["attempted"])
        for field, value in (("block_number", EMPTY), ("pinned_block_hash", OTHER_HASH),
                             ("address", OTHER_ADDRESS)):
            with self.subTest(field=field):
                obs = {**skipped, field: value}
                self.assert_incomplete(obs, SECOND)

    def test_separately_supplied_capture_binds_the_offline_verifier(self):
        capture = json.loads(replay_compare.CAPTURE_PATH.read_bytes())
        ref = self.references[FIRST]
        capture["providers"][1]["blocks"][0] = observed(ref)
        packet = replay_compare.build_packet(capture)
        sources = {source["id"]: source for source in packet["sources"]}
        self.assertEqual(sources["1rpc"]["blocks"][0]["decision"], "matched")
        self.assertEqual(sources["publicnode"]["blocks"][0]["decision"], "unavailable")
        with self.assertRaises(ValueError):
            replay_compare.verify_packet(packet)
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "test-capture.json"
            packet_path = Path(directory) / "review.json"
            input_path.write_text(json.dumps(capture), encoding="utf-8")
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            verified = subprocess.run([sys.executable, str(ROOT / "replay_compare.py"), "--verify",
                                       str(packet_path), "--capture", str(input_path)], cwd=directory,
                                      capture_output=True, text=True)
            self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)

    def test_export_is_deterministic_offline_and_sources_remain_separate(self):
        with patch("socket.create_connection", side_effect=AssertionError("offline replay contacted a host")):
            packet = replay_compare.build_packet()
            self.assertEqual(encode(packet), encode(replay_compare.build_packet()))
        self.assertEqual(packet["sha256"], packet_digest(packet))
        self.assertEqual(packet["fixture_packet_sha256"], self.v12["sha256"])
        self.assertEqual([b["status"] for b in self.v12["blocks"]], ["matched", "matched", "verified_zero"])
        by_id = {s["id"]: s for s in packet["sources"]}
        self.assertEqual({key: s["kind"] for key, s in by_id.items()}, {
            "fixture": "fixture", "publicnode": "public_capture", "1rpc": "public_capture",
            "diagnostic": "diagnostic",
        })
        self.assertEqual([b["decision"] for b in by_id["fixture"]["blocks"]],
                         ["matched", "matched", "verified_zero"])
        self.assertEqual([b["decision"] for b in by_id["diagnostic"]["blocks"]],
                         ["disagreement", "disagreement", "incomplete"])
        for source in packet["sources"]:
            self.assertCountEqual([b["block_number"] for b in source["blocks"]], (FIRST, SECOND, EMPTY))

    def test_cli_rebuild_rejects_changed_witness_even_with_fresh_checksum(self):
        packet = replay_compare.build_packet()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "packet.json"
            cmd = [sys.executable, str(ROOT / "replay_compare.py"), "--verify", str(path)]
            path.write_text(json.dumps(packet, indent=4), encoding="utf-8")
            verified = subprocess.run(cmd, cwd=temp, capture_output=True, text=True)
            self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)
            source = next(s for s in packet["sources"] if s["id"] == "fixture")
            source["blocks"][0]["observed"]["witness"]["filter_counts"]["sender"] += 1
            with self.assertRaises(ValueError):
                replay_compare.verify_packet(packet)
            packet["sha256"] = packet_digest(packet)
            path.write_text(encode(packet), encoding="utf-8")
            rejected = subprocess.run(cmd, cwd=temp, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertNotIn("Traceback", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
