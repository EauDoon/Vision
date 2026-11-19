# Balancer Vault archive evidence

The reference answer in `archive.json` covers Ethereum mainnet, Vault `0xba12222222228d8ba445958a75a0704d566bf2c8`, and the three named blocks. Each entry pins the original YAML by revision, path and SHA-256. The source is the Portal Network Contributors' MIT-licensed fixture set. The upstream notice is included in this directory. [Pinned archive](https://github.com/ethereum/portal-spec-tests/tree/938744a83d4f85dcdcf9bac12b798e15f2eac2b1/tests/mainnet/history/block_data) · [Pinned license](https://github.com/ethereum/portal-spec-tests/blob/938744a83d4f85dcdcf9bac12b798e15f2eac2b1/LICENSE)

| Block | Receipts examined | Logs examined | Vault matches |
|---:|---:|---:|---:|
| 22,431,084 | 95 | 233 | 2 |
| 17,034,870 | 184 | 510 | 2 |
| 17,034,869 | 93 | 208 | 0 |

## What the files contain

`derive.py` reads the header, body and receipts directly from each pinned file, without importing Vision. It hashes the encoded header and signed transaction envelopes with Ethereum Keccak-256. It pairs each transaction with its receipt by ordinal and numbers logs from zero across the entire block. To select a row, it checks for success, three topics, the `Transfer(address,address,uint256)` signature and a padded Vault address in either indexed position. It records each selected contract, indexed address pair and unsigned integer amount in the reference answer.

Each `*.json.gz` is an input for constructing JSON-RPC fixture responses. It preserves every receipt’s transaction hash, status and log count, and every log’s block-wide index and topics. Three-topic Transfer logs with an indexed Vault endpoint also retain emitter and data. Approval logs 136 and 403 in the positive windows retain those fields to make the adjacent exclusions inspectable. The original transaction bodies, gas and unrelated log payloads are omitted. A reviewer can therefore examine every indexed address relevant to the zero without downloading the YAML. The importer consumes constructed responses for the scoped ERC-20-shaped comparison. These files contain no public provider observations.

## Rebuild from the upstream files

The workbench and packet verifier use Python’s standard library. Rebuilding the compact inputs from the original RLP uses `rlp` and Ethereum Keccak in a separate environment. Run from the repository root on Python 3.10 or later.

```sh
work=$(mktemp -d)
python3 -m venv "$work/venv"
"$work/venv/bin/pip" install 'rlp==4.1.0' 'eth-hash[pycryptodome]==0.7.1'
rev=938744a83d4f85dcdcf9bac12b798e15f2eac2b1
for height in 22431084 17034870 17034869; do
  curl --fail --silent --show-error \
    "https://raw.githubusercontent.com/ethereum/portal-spec-tests/$rev/tests/mainnet/history/block_data/block-data-$height.yaml" \
    -o "$work/block-data-$height.yaml"
done
"$work/venv/bin/python" fixtures/balancer-vault/derive.py "$work" "$work/rebuilt"
```

Compare the rebuilt `archive.json` with the committed answer. The source SHA-256 values cover the original YAML bytes, while each `fixture_sha256` covers the distributed gzip bytes. If a different compression library produces a different gzip digest, compare the decompressed JSON and the archive fields as well.
