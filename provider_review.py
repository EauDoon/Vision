"""Compare two public providers with the pinned Balancer Vault archive observations."""
import argparse
from datetime import datetime, timezone
import json

from chain import ChainError, crawl
from transfer_review import VAULT, build_packet, decision, event_rows


PROVIDERS = (
    ("PublicNode", "https://ethereum-rpc.publicnode.com"),
    ("dRPC", "https://eth.drpc.org"),
)


def compare_providers():
    packet = build_packet()
    providers = []
    for name, endpoint in PROVIDERS:
        blocks = []
        for block in packet["blocks"]:
            number = block["block_number"]
            expected = block["expected"]
            if not block["coverage"]["complete"]:
                expected = {**expected, "count": None}
            try:
                result = crawl(VAULT, rpc_url=endpoint, start=number, end=number, max_blocks=1)
            except ChainError as exc:
                observed = {"block_hash": None, "count": None, "rows": None}
                reason = str(exc)
            else:
                rows = event_rows(result)
                observed = {"block_hash": result["blocks"][0]["hash"], "count": len(rows), "rows": rows}
                reason = None
            blocks.append({"block_number": number, "archive_coverage": block["coverage"],
                           "decision": decision(expected, observed),
                           "expected": expected, "observed": observed, "error": reason})
        providers.append({"name": name, "endpoint": endpoint, "blocks": blocks})
    return {"source_mode": "public_rpc", "completed_at": datetime.now(timezone.utc).isoformat(),
            "scope": packet["scope"], "archive": packet["archive"],
            "fixture_packet_sha256": packet["sha256"], "providers": providers}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", action="store_true", required=True,
                        help="Read three finalized blocks from PublicNode and dRPC. Set VISION_RPC_ALLOWED_HOSTS=eth.drpc.org.")
    parser.parse_args(argv)
    report = compare_providers()
    print(json.dumps(report, indent=2))
    return int(any(block["decision"] not in {"matched", "verified_zero"}
                   for provider in report["providers"] for block in provider["blocks"]))


if __name__ == "__main__":
    raise SystemExit(main())
