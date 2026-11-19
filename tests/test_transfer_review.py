import copy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from store import encode
from transfer_review import FixtureRPC, build_packet, review_block, verify_packet


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "balancer-vault"
VAULT = "0xba12222222228d8ba445958a75a0704d566bf2c8"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
RETH = "0xae78736cd615f374d3085123a210448e74fc6393"
SENDER = "0x16d5a408e807db8ef7c578279beeee6b228f1c1c"
RECIPIENT_2025 = "0x47eaaca9819460771db6881165e10e5a26e41155"
RECIPIENT_2023 = "0xf1cb05330f24ac26e267083363ec6d3abf8633b9"
TX_2025 = "0xcd474a3f5b5e3995dc1c2c0c6d63ce14787cea8c1203af11c7170a7d62985da4"
TX_2023 = "0xc6a609d5bfc2ace7794244a2e23032269d2f41177aebdd234e5a6df7ea950df9"
APPROVAL = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"

# Independently decoded from the pinned archive's RLP bodies and receipts.
FIELDS = ("tx_hash", "log_index", "contract", "from_address", "to_address", "raw_amount")
ROWS = {
    22_431_084: [
        (TX_2025, 138, WETH, SENDER, VAULT, "433410975363818"),
        (TX_2025, 139, RETH, VAULT, RECIPIENT_2025, "381986670507558"),
    ],
    17_034_870: [
        (TX_2023, 405, WETH, SENDER, VAULT, "91000000000000000"),
        (TX_2023, 406, RETH, VAULT, RECIPIENT_2023, "85250402043920592"),
    ],
    17_034_869: [],
}
# Block header Keccak-256, receipt count, block-wide log count, archive file SHA-256.
BLOCKS = {
    22_431_084: (
        "0x50c8cab760b2948349c590461b166773c45d8f4858cccf5a43025ab2960152e8", 95, 233,
        "1d2bc4903770dacaddbe8c1d4c0462190c6ca88c107505c930b357ef5e8b265b",
    ),
    17_034_870: (
        "0xe22c56f211f03baadcc91e4eb9a24344e6848c5df4473988f893b58223f5216c", 184, 510,
        "393c0eb2f909906dc64bcc0bd492265fdf8e0450add350c67f6483c6b9a73185",
    ),
    17_034_869: (
        "0xc2558f8143d5f5acb8382b8cb2b8e2f1a10c8bdfeededad850eaca048ed85d8f", 93, 208,
        "0df98aff47b6dd38e13bb548eed51bd8706359e46ea70417ed83f3dffb9701a8",
    ),
}


def fixture(number):
    with gzip.open(FIXTURES / f"{number}.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


def log_at(block, index):
    return next(log for receipt in block["receipts"] for log in receipt["logs"]
                if log["log_index"] == index)


def checksum(packet):
    unsigned = {k: v for k, v in packet.items() if k != "sha256"}
    return hashlib.sha256(encode(unsigned).encode("utf-8")).hexdigest()


class TransferReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = json.loads((FIXTURES / "archive.json").read_text(encoding="utf-8"))
        cls.archive = {b["number"]: b for b in manifest["blocks"]}
        cls.packet = build_packet()

    def test_full_rows_block_hash_archive_pins_and_coverage(self):
        reviews = self.packet["blocks"]
        self.assertCountEqual([b["block_number"] for b in reviews], BLOCKS)
        for review in reviews:
            number = review["block_number"]
            with self.subTest(block=number):
                rows = ROWS[number]
                block_hash, receipt_count, log_count, source_sha = BLOCKS[number]
                self.assertEqual(review["status"], "matched" if rows else "verified_zero")
                self.assertEqual(review["archive"]["sha256"], source_sha)
                for side in ("expected", "observed"):
                    observation = review[side]
                    self.assertEqual(observation["block_hash"], block_hash)
                    self.assertEqual(observation["count"], len(rows))
                    self.assertCountEqual(
                        [tuple(row[k] for k in FIELDS) for row in observation["rows"]], rows)
                coverage = review["coverage"]
                self.assertIs(coverage["complete"], True)
                for key in ("receipts", "receipts_examined"):
                    self.assertEqual(coverage[key], receipt_count)
                for key in ("logs", "logs_examined"):
                    self.assertEqual(coverage[key], log_count)

    def test_packet_scope_and_importer_witness(self):
        self.assertEqual(self.packet["schema"], "vision/transfer-review@1")
        self.assertEqual(self.packet["scope"]["chain_id"], 1)
        self.assertEqual(self.packet["scope"]["address"], VAULT)
        self.assertEqual(self.packet["source_mode"], "constructed_rpc_fixture")
        self.assertEqual(self.packet["archive"]["revision"], "938744a83d4f85dcdcf9bac12b798e15f2eac2b1")
        for block in self.packet["blocks"]:
            number = block["block_number"]
            with self.subTest(block=number):
                rows = ROWS[number]
                witness = block["witness"]
                self.assertIs(witness["end_header_checked"], True)
                self.assertCountEqual(witness["receipt_transactions"], {row[0] for row in rows})
                self.assertEqual(witness["filter_counts"], {
                    "sender": sum(row[3] == VAULT for row in rows),
                    "recipient": sum(row[4] == VAULT for row in rows),
                })

    def test_adjacent_approval_is_present_and_excluded(self):
        data = fixture(22_431_084)
        control = log_at(data, 136)
        transfer = log_at(data, 138)
        self.assertEqual(control["topics"][0], APPROVAL)
        self.assertEqual(control["topics"][1:], transfer["topics"][1:])
        self.assertEqual((control["address"], control["data"]), (transfer["address"], transfer["data"]))
        decision = review_block(self.archive[22_431_084], data)
        self.assertEqual([r["log_index"] for r in decision["observed"]["rows"]], [138, 139])

    def test_missing_receipt_prevents_verified_zero(self):
        data = fixture(17_034_869)
        data["receipts"].pop()
        decision = review_block(self.archive[17_034_869], data)
        self.assertEqual(decision["status"], "unavailable")
        self.assertIsNone(decision["observed"]["count"])
        self.assertIs(decision["coverage"]["complete"], False)

    def test_missing_archive_rows_keep_completed_replay(self):
        archive = copy.deepcopy(self.archive[22_431_084])
        del archive["rows"]
        decision = review_block(archive, fixture(22_431_084))
        self.assertEqual(decision["status"], "unavailable")
        self.assertIsNone(decision["expected"]["count"])
        self.assertIsNone(decision["expected"]["rows"])
        observed = decision["observed"]
        self.assertEqual(observed["count"], 2)
        self.assertEqual([tuple(row[k] for k in FIELDS) for row in observed["rows"]], ROWS[22_431_084])

    def test_nonempty_replay_requires_a_receipt_witness(self):
        send = FixtureRPC.__call__

        def without_receipt_witness(transport, url, request):
            response = send(transport, url, request)
            if request["method"] == "eth_getTransactionReceipt":
                transport.witness["receipt_transactions"].clear()
            return response

        with patch.object(FixtureRPC, "__call__", without_receipt_witness):
            decision = review_block(self.archive[22_431_084], fixture(22_431_084))
        self.assertEqual(decision["status"], "unavailable")
        self.assertIsNone(decision["observed"]["count"])
        self.assertEqual(decision["expected"]["count"], 2)

    def test_missing_log_prevents_verified_zero(self):
        data = fixture(17_034_869)
        next(r for r in data["receipts"] if r["logs"])["logs"].pop()
        decision = review_block(self.archive[17_034_869], data)
        self.assertEqual(decision["status"], "unavailable")
        self.assertIsNone(decision["observed"]["count"])

    def test_both_filters_required_even_for_empty_block(self):
        for direction in ("sender", "recipient"):
            with self.subTest(missing=direction):
                data = fixture(17_034_869)
                data["directions"].remove(direction)
                decision = review_block(self.archive[17_034_869], data)
                self.assertEqual(decision["status"], "unavailable")
                self.assertIsNone(decision["observed"]["count"])
                self.assertEqual(decision["expected"]["count"], 0)

    def test_same_count_different_amount_preserves_both_rows(self):
        data = fixture(22_431_084)
        log_at(data, 138)["data"] = "0x" + format(7, "064x")
        decision = review_block(self.archive[22_431_084], data)
        self.assertEqual(decision["status"], "mismatch")
        self.assertEqual((decision["expected"]["count"], decision["observed"]["count"]), (2, 2))
        self.assertEqual(decision["expected"]["rows"][0]["raw_amount"], "433410975363818")
        self.assertEqual(decision["observed"]["rows"][0]["raw_amount"], "7")

    def test_same_count_different_event_identity_is_mismatch(self):
        data = fixture(22_431_084)
        replacements = {"tx_hash": TX_2023, "log_index": 137, "contract": RETH,
                        "from_address": VAULT, "to_address": SENDER}
        for field, replacement in replacements.items():
            with self.subTest(field=field):
                archive = copy.deepcopy(self.archive[22_431_084])
                archive["rows"][0][field] = replacement
                decision = review_block(archive, data)
                self.assertEqual(decision["status"], "mismatch")
                self.assertEqual(decision["expected"]["rows"][0][field], replacement)
                original = ROWS[22_431_084][0][FIELDS.index(field)]
                self.assertEqual(decision["observed"]["rows"][0][field], original)

    def test_header_disagreement_even_when_both_sides_empty(self):
        data = fixture(17_034_869)
        data["block_hash"] = "0x" + "ef" * 32
        decision = review_block(self.archive[17_034_869], data)
        self.assertEqual(decision["status"], "mismatch")
        self.assertEqual(decision["expected"]["block_hash"], BLOCKS[17_034_869][0])
        self.assertEqual(decision["observed"]["block_hash"], data["block_hash"])
        self.assertEqual(decision["expected"]["rows"], decision["observed"]["rows"])

    def test_verify_cli_works_outside_checkout_and_rejects_stale_digest(self):
        self.assertEqual(self.packet["sha256"], checksum(self.packet))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            command = [sys.executable, str(ROOT / "transfer_review.py"), "--verify", str(path)]
            path.write_text(json.dumps(self.packet, indent=4), encoding="utf-8")
            verified = subprocess.run(command, cwd=directory, capture_output=True, text=True)
            self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)

            packet = copy.deepcopy(self.packet)
            packet["sha256"] = "0" * 64
            path.write_text(json.dumps(packet), encoding="utf-8")
            rejected = subprocess.run(command, cwd=directory, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)

    def test_recomputed_digest_cannot_validate_edited_evidence(self):
        for field in ("amount", "coverage", "witness"):
            with self.subTest(changed=field):
                packet = copy.deepcopy(self.packet)
                block = next(b for b in packet["blocks"] if b["block_number"] == 22_431_084)
                if field == "amount":
                    block["observed"]["rows"][0]["raw_amount"] = "7"
                elif field == "coverage":
                    block["coverage"]["receipts_examined"] -= 1
                else:
                    block["witness"]["end_header_checked"] = False
                packet["sha256"] = checksum(packet)
                with self.assertRaises(ValueError):
                    verify_packet(packet)


if __name__ == "__main__":
    unittest.main()
