"""Offline checks for the fixed two-provider command."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from chain import ChainError
from provider_review import PROVIDERS, main
from transfer_review import VAULT, build_packet


class ProviderReviewTests(unittest.TestCase):
    def test_command_requires_explicit_public_mode(self):
        with patch("provider_review.crawl") as crawler, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as failure:
                main([])
        self.assertEqual(failure.exception.code, 2)
        crawler.assert_not_called()

    def test_unavailable_and_disagreeing_provider_each_keep_their_own_results(self):
        expected = {b["block_number"]: b["expected"] for b in build_packet()["blocks"]}
        calls = []

        def read(address, *, rpc_url, start, end, max_blocks):
            calls.append((rpc_url, start))
            self.assertEqual((address, end, max_blocks), (VAULT, start, 1))
            reference = expected[start]
            block_hash = reference["block_hash"]
            events = [dict(row, kind="erc20_transfer") for row in reference["rows"]]
            if rpc_url == PROVIDERS[1][1]:
                if start == 22431084:
                    raise ChainError("Provider did not return a receipt.")
                if start == 17034870:
                    events[0]["raw_amount"] = "1"
                else:
                    block_hash = "0x" + "f" * 64
            return {"blocks": [{"hash": block_hash}], "events": events}

        output = io.StringIO()
        with patch("provider_review.crawl", side_effect=read), contextlib.redirect_stdout(output):
            self.assertEqual(main(["--public"]), 1)
        report = json.loads(output.getvalue())
        self.assertCountEqual(calls, [(url, n) for _, url in PROVIDERS for n in (22431084, 17034870, 17034869)])
        first, second = report["providers"]
        self.assertEqual([b["decision"] for b in first["blocks"]], ["matched", "matched", "verified_zero"])
        missing, row_diff, hash_diff = second["blocks"]
        self.assertEqual(missing["decision"], "unavailable")
        self.assertIsNone(missing["observed"]["count"])
        self.assertEqual(missing["expected"]["count"], 2)
        self.assertEqual(row_diff["decision"], "mismatch")
        self.assertEqual(row_diff["expected"]["count"], row_diff["observed"]["count"])
        self.assertNotEqual(row_diff["expected"]["rows"], row_diff["observed"]["rows"])
        self.assertEqual(hash_diff["decision"], "mismatch")
        self.assertNotEqual(hash_diff["expected"]["block_hash"], hash_diff["observed"]["block_hash"])

    def test_missing_archive_coverage_preserves_the_provider_zero(self):
        packet = build_packet()
        zero = next(b for b in packet["blocks"] if b["block_number"] == 17034869)
        zero["coverage"]["complete"] = False
        result = {"blocks": [{"hash": zero["expected"]["block_hash"]}], "events": []}
        with patch("provider_review.build_packet", return_value=packet), patch("provider_review.crawl", return_value=result):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["--public"]), 1)
        for provider in json.loads(output.getvalue())["providers"]:
            comparison = next(b for b in provider["blocks"] if b["block_number"] == 17034869)
            self.assertEqual(comparison["decision"], "unavailable")
            self.assertIsNone(comparison["expected"]["count"])
            self.assertEqual(comparison["observed"]["count"], 0)
