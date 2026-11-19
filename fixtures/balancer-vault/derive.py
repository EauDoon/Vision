"""Build the independent archive answer and compact replay inputs from pinned local YAML."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path

import rlp
from eth_hash.auto import keccak

REPOSITORY = "https://github.com/ethereum/portal-spec-tests"
REVISION = "938744a83d4f85dcdcf9bac12b798e15f2eac2b1"
DIRECTORY = "tests/mainnet/history/block_data"
PINS = {
    22431084: "1d2bc4903770dacaddbe8c1d4c0462190c6ca88c107505c930b357ef5e8b265b",
    17034870: "393c0eb2f909906dc64bcc0bd492265fdf8e0450add350c67f6483c6b9a73185",
    17034869: "0df98aff47b6dd38e13bb548eed51bd8706359e46ea70417ed83f3dffb9701a8",
}
VAULT = bytes.fromhex("ba12222222228d8ba445958a75a0704d566bf2c8")
INDEXED_VAULT = VAULT.rjust(32, b"\0")
TRANSFER = keccak(b"Transfer(address,address,uint256)")
APPROVAL_CONTROLS = {(22431084, 136), (17034870, 403)}


def hex_data(raw):
    return "0x" + raw.hex()


def decode(number, source):
    digest = hashlib.sha256(source).hexdigest()
    if digest != PINS[number]:
        raise ValueError(f"Wrong SHA-256 for block {number}: {digest}")
    # The pinned files are three single-line hex scalars.
    raw = {k: bytes.fromhex(v) for k, v in
           (line.split(": 0x") for line in source.decode("ascii").splitlines())}
    header = rlp.decode(raw["header"])
    if int.from_bytes(header[8], "big") != number:
        raise ValueError("Header number disagrees with archive path")
    transactions = rlp.decode(raw["body"])[0]
    receipts = rlp.decode(raw["receipts"])
    block_hash = hex_data(keccak(raw["header"]))
    fixture = dict(number=number, block_hash=block_hash, parent_hash=hex_data(header[0]),
                   timestamp=int.from_bytes(header[11], "big"), directions=["sender", "recipient"],
                   receipts=[])
    expected = []
    index = 0
    # Portal receipts contain [transaction type, status, cumulative gas, logs].
    # Typed transactions are signed envelope bytes. Legacy transactions are RLP lists.
    for tx, (_, status_bytes, _, logs) in zip(transactions, receipts, strict=True):
        tx_hash = hex_data(keccak(rlp.encode(tx) if isinstance(tx, list) else tx))
        status = int.from_bytes(status_bytes, "big")
        if status not in (0, 1):
            raise ValueError("Invalid historical status")
        projected = []
        for address, topics, data in logs:
            entry = dict(log_index=index, topics=[hex_data(word) for word in topics])
            transfer = len(topics) == 3 and topics[0] == TRANSFER
            vault_transfer = transfer and INDEXED_VAULT in topics[1:]
            if vault_transfer or (number, index) in APPROVAL_CONTROLS:
                entry.update(address=hex_data(address), data=hex_data(data))
            projected.append(entry)
            if status and vault_transfer:
                if (len(address) != 20 or len(data) != 32 or
                        any(len(t) != 32 or t[:12] != bytes(12) for t in topics[1:])):
                    raise ValueError("Malformed candidate Transfer payload")
                expected.append(dict(tx_hash=tx_hash, log_index=index, contract=hex_data(address),
                                     from_address=hex_data(topics[1][-20:]), to_address=hex_data(topics[2][-20:]),
                                     raw_amount=str(int.from_bytes(data, "big"))))
            index += 1
        fixture["receipts"].append(dict(tx_hash=tx_hash, status=status, log_count=len(logs), logs=projected))
    record = dict(number=number, block_hash=block_hash, path=f"{DIRECTORY}/block-data-{number}.yaml",
                  sha256=digest, receipt_count=len(receipts), log_count=index, rows=expected)
    return fixture, record


def compressed_json(value):
    data = io.BytesIO()
    with gzip.GzipFile(fileobj=data, mode="wb", mtime=0, compresslevel=9) as output:
        output.write(json.dumps(value, separators=(",", ":")).encode("ascii"))
    return data.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path, help="directory containing the three block-data-*.yaml files")
    parser.add_argument("output_dir", type=Path, help="directory for rebuilt fixtures and manifest")
    args = parser.parse_args()
    archive = dict(repository=REPOSITORY, revision=REVISION, license="MIT", blocks=[])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for number in PINS:
        source = (args.source_dir / f"block-data-{number}.yaml").read_bytes()
        fixture, record = decode(number, source)
        packed = compressed_json(fixture)
        (args.output_dir / f"{number}.json.gz").write_bytes(packed)
        record["fixture_sha256"] = hashlib.sha256(packed).hexdigest()
        archive["blocks"].append(record)
    (args.output_dir / "archive.json").write_text(json.dumps(archive, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
