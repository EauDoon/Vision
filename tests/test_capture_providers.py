"""Offline checks for capturing what reached each stage of the fixed importer."""
import contextlib
import gzip
import io
import json
import unittest
from unittest.mock import patch

from capture_providers import PROVIDERS, capture_block, capture_providers, main
from chain import TransportError
from transfer_review import BLOCKS, FIXTURE_DIR, FixtureRPC


class CaptureTests(unittest.TestCase):
    def fixture_transport(self, number):
        with gzip.open(FIXTURE_DIR / f"{number}.json.gz", "rt", encoding="utf-8") as source:
            fixture = json.load(source)
        return fixture["block_hash"], FixtureRPC(fixture, {"receipt_transactions": [], "filter_counts": {}})

    def replay(self, number, header_hash, transport):
        return capture_block(number, header_hash, PROVIDERS[0][2], http_send=transport,
                             started_at="2026-01-01T00:00:00+00:00")

    def test_capture_records_requested_receipts_filter_rows_and_final_header(self):
        number = 22_431_084
        header_hash, transport = self.fixture_transport(number)
        block = self.replay(number, header_hash, transport)
        witness = block["witness"]
        self.assertEqual((block["stage"], block["chain_id"], block["count"]), ("complete", 1, 2))
        self.assertEqual(witness["finalized_height"], number)
        self.assertEqual(witness["requested_block_number"], number)
        self.assertEqual(witness["end_block_number"], number)
        self.assertEqual((block["block_hash"], witness["end_block_hash"]), (header_hash, header_hash))
        self.assertEqual(witness["filter_counts"], {"sender": 1, "recipient": 1})
        first, second = block["rows"]
        self.assertEqual(witness["filter_rows"], {"sender": [second], "recipient": [first]})
        receipt, = witness["receipts"]
        self.assertEqual((receipt["returned_tx_hash"], receipt["tx_hash"]), (first["tx_hash"], first["tx_hash"]))
        self.assertEqual(receipt["block_number"], number)
        self.assertEqual(receipt["block_hash"], header_hash)
        self.assertEqual(receipt["status"], 1)
        self.assertGreater(receipt["log_count"], 2)
        self.assertEqual(receipt["rows"], block["rows"])

    def test_missing_receipt_fields_keep_the_request_and_unavailable_count(self):
        number = 22_431_084
        header_hash, fixture = self.fixture_transport(number)

        def omit_logs(url, request):
            response = fixture(url, request)
            if request["method"] == "eth_getTransactionReceipt":
                del response["result"]["logs"]
            return response

        block = self.replay(number, header_hash, omit_logs)
        self.assertEqual((block["error_kind"], block["stage"]), ("incomplete", "receipt"))
        self.assertIsNone(block["count"])
        self.assertIsNone(block["rows"])
        receipt, = block["witness"]["receipts"]
        self.assertEqual(receipt["status"], 1)
        self.assertIsNone(receipt["rows"])
        self.assertIsNone(receipt["log_count"])
        self.assertIsNone(block["witness"]["filter_counts"]["recipient"])

    def test_wrong_final_header_height_preserves_witness_and_withholds_zero(self):
        number = 17_034_869
        header_hash, fixture = self.fixture_transport(number)

        def wrong_final_number(url, request):
            response = fixture(url, request)
            if request["params"] == [hex(number), False]:
                response["result"] = dict(response["result"], number=hex(number + 1))
            return response

        capture = self.replay(number, header_hash, wrong_final_number)
        self.assertEqual((capture["error_kind"], capture["stage"]), ("incomplete", "end_header"))
        self.assertEqual(capture["witness"]["end_block_number"], number + 1)
        self.assertEqual(capture["witness"]["end_block_hash"], header_hash)
        self.assertIsNone(capture["count"])

    def test_four_topic_filter_reply_records_its_exclusion_before_reporting_zero(self):
        number = 17_034_869
        header_hash, fixture = self.fixture_transport(number)
        tx_hash = "0x" + "ab" * 32

        def nft_shaped(url, request):
            response = fixture(url, request)
            if request["method"] == "eth_getLogs":
                pattern = request["params"][0]["topics"]
                if len(pattern) == 2:
                    response["result"] = [{"topics": [*pattern, "0x" + "00" * 32, "0x" + "ff" * 32],
                                           "transactionHash": tx_hash, "logIndex": "0x5",
                                           "blockNumber": hex(number), "blockHash": header_hash, "removed": False}]
            return response

        capture = self.replay(number, header_hash, nft_shaped)
        self.assertEqual(capture["count"], 0)
        witness = capture["witness"]
        self.assertEqual(witness["filter_counts"], {"sender": 1, "recipient": 0})
        self.assertEqual(witness["filter_rows"], {"sender": [], "recipient": []})
        exclusion, = witness["filter_excluded"]["sender"]
        self.assertEqual((exclusion["tx_hash"], exclusion["log_index"], len(exclusion["topics"])), (tx_hash, 5, 4))
        self.assertEqual(witness["filter_excluded"]["recipient"], [])

        def invalid_inclusion(url, request):
            response = nft_shaped(url, request)
            if request["method"] == "eth_getLogs" and response["result"]:
                response["result"][0]["blockHash"] = "0x" + "ef" * 32
            return response

        invalid = self.replay(number, header_hash, invalid_inclusion)
        self.assertEqual(invalid["error_kind"], "incomplete")
        self.assertIsNone(invalid["count"])
        self.assertIsNone(invalid["witness"]["filter_excluded"]["sender"])

    def test_transport_preflight_skips_the_rest_of_that_provider_only(self):
        def scripted(number, pin, endpoint):
            if endpoint == PROVIDERS[0][2]:
                def send(url, payload):
                    self.assertEqual(payload["method"], "eth_chainId")
                    raise TransportError("Offline transport failure.")
            else:
                _, send = self.fixture_transport(number)
            return self.replay(number, pin, send)

        with patch("capture_providers.capture_block", side_effect=scripted) as attempt:
            report = capture_providers()
        self.assertEqual(attempt.call_count, 4)
        failed, completed = report["providers"]
        self.assertEqual([b["error_kind"] for b in failed["blocks"]], ["transport", "not_run", "not_run"])
        self.assertEqual([b["attempted"] for b in failed["blocks"]], [True, False, False])
        self.assertIsNone(failed["blocks"][1]["started_at"])
        self.assertEqual([b["block_number"] for b in completed["blocks"]], list(BLOCKS))
        self.assertEqual([b["count"] for b in completed["blocks"]], [2, 2, 0])

    def test_capture_command_requires_opt_in(self):
        with patch("capture_providers.capture_providers") as capture, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                main([])
        self.assertEqual(exc.exception.code, 2)
        capture.assert_not_called()
