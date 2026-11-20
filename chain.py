"""Bounded, read-only Ethereum finalized-block ingestion (Python stdlib).

Sources: https://ethereum.org/developers/docs/apis/json-rpc/
         https://eips.ethereum.org/EIPS/eip-20
No full-wallet-history claim: excludes traces/internal ETH, fees, consensus rewards,
NFTs, off-chain balances and tax classifications. ERC-20-shaped logs are observations,
not proof of token legitimacy. Decimals remain unknown rather than guessed.
"""
from datetime import datetime, timezone
import ipaddress
import json
import os
import re
import socket
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from typing import NamedTuple

TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
DEFAULT_HOSTS = frozenset({'ethereum-rpc.publicnode.com', 'ethereum.publicnode.com', 'eth.llamarpc.com', 'cloudflare-eth.com'})
MAX_RESPONSE = 16 * 1024 * 1024
MAX_EVENTS = 10000
ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')
HASH = re.compile(r'^0x[0-9a-fA-F]{64}$')


class ChainError(ValueError):
    """Safe, credential-free error for the API boundary."""


class TransportError(ChainError):
    """The configured provider could not be reached through the normal transport."""


def normalize_address(value):
    if not isinstance(value, str) or not ADDRESS.fullmatch(value):
        raise ChainError('Expected a 20-byte hexadecimal EVM address.')
    return value.lower()


def _hash(value):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ChainError('Provider returned an invalid hash.')
    return value.lower()


def _quantity(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]+', value):
        raise ChainError('Provider returned an invalid integer.')
    return int(value, 16)


def _endpoint(url):
    try:
        parsed = urlsplit(url)
        allowed = DEFAULT_HOSTS | frozenset(x.strip().lower() for x in os.getenv('VISION_RPC_ALLOWED_HOSTS', '').split(',') if x.strip())
        if parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443):
            raise ValueError()
        return parsed.hostname
    except (ValueError, TypeError):
        raise ChainError('RPC endpoint must use HTTPS and an operator-allowlisted provider.') from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ChainError('RPC redirects are not permitted.')


def _remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise ChainError('Crawl time budget exhausted; use a smaller range.')
    return seconds


def _http_send(url, payload, deadline):
    host = _endpoint(url)
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise TransportError('RPC provider must resolve to public network addresses.')
        request = Request(url, json.dumps(payload).encode(), {'Content-Type': 'application/json', 'User-Agent': 'Vision/1.0'})
        # Do not inherit proxy credentials or allow redirect-based endpoint changes.
        from urllib.request import ProxyHandler
        timeout = min(15, _remaining(deadline))
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
            body = bytearray()
            while True:
                _remaining(deadline)
                chunk = response.read1(min(65536, MAX_RESPONSE + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > MAX_RESPONSE:
                    raise ChainError('RPC response exceeded the size limit; use a smaller range.')
        return json.loads(body)
    except ChainError:
        raise
    except OSError:
        raise TransportError('RPC provider unavailable or returned unreadable data.') from None
    except Exception:
        raise ChainError('RPC provider unavailable or returned unreadable data.') from None


class LogEvidence(NamedTuple):
    tx_hash: str
    block_number: int
    block_hash: str
    index: int
    contract: str
    topics: tuple
    data: str


def _log_evidence(log):
    """Comparable receipt and filter-log fields for an ERC-20-shaped observation."""
    if log.get('removed', False) is not False:
        raise ChainError('Receipt contains a removed transfer.')
    return LogEvidence(
        tx_hash=_hash(log.get('transactionHash')), block_number=_quantity(log.get('blockNumber')),
        block_hash=_hash(log.get('blockHash')), index=_quantity(log.get('logIndex')),
        contract=normalize_address(log.get('address')), topics=tuple(_hash(t) for t in log['topics']),
        data=_hash(log.get('data')),
    )


def crawl(address, *, rpc_url, start=None, end=None, max_blocks=8, http_send=None, observer=None):
    """Return finalized native transfers + ERC-20-shaped logs for one address.

    ``rpc_url`` is server/operator configuration, never a client-supplied URL.
    Hosts are allowlisted using VISION_RPC_ALLOWED_HOSTS (comma separated), in
    addition to DEFAULT_HOSTS. Ethereum mainnet only; no silent chain fallback.
    Optional ``http_send(url, JSON_payload) -> JSON_response`` enables fixture tests.
    An optional observer receives (phase, method, params, result) at each request
    and valid JSON-RPC envelope, including replies the importer later rejects.
    A failure aborts the entire crawl: callers must never record partial success.
    Persist block hashes and compare overlaps on later ingestion. Finality is the
    configured provider's assertion, not an independently verified consensus proof.
    """
    address = normalize_address(address)
    provider_host = _endpoint(rpc_url)
    if type(max_blocks) is not int or not 1 <= max_blocks <= 64:
        raise ChainError('max_blocks must be an integer from 1 to 64.')
    for value in (start, end):
        if value is not None and (type(value) is not int or value < 0):
            raise ChainError('Block bounds must be non-negative integers.')
    padded = '0x' + address[2:].rjust(64, '0')
    sequence = 0
    deadline = time.monotonic() + 60

    def rpc(method, params):
        nonlocal sequence
        sequence += 1
        _remaining(deadline)
        if sequence > 256:
            raise ChainError('Crawl request budget exhausted; use a smaller range.')
        try:
            payload = {'jsonrpc': '2.0', 'id': sequence, 'method': method, 'params': params}
            if observer is not None:
                observer('request', method, params, None)
            reply = http_send(rpc_url, payload) if http_send else _http_send(rpc_url, payload, deadline)
            _remaining(deadline)
        except ChainError:
            raise
        except Exception:
            raise ChainError('RPC request failed.') from None
        if not isinstance(reply, dict) or reply.get('id') != sequence or reply.get('jsonrpc') != '2.0' or 'error' in reply or reply.get('result') is None:
            raise ChainError('RPC provider returned an error or incomplete response.')
        if observer is not None:
            observer('response', method, params, reply['result'])
        return reply['result']

    chain_id = _quantity(rpc('eth_chainId', []))
    if chain_id != 1:
        raise ChainError('Vision v1 live ingestion supports Ethereum mainnet only.')
    tip = rpc('eth_getBlockByNumber', ['finalized', False])
    if not isinstance(tip, dict):
        raise ChainError('Provider does not supply finalized blocks.')
    finalized = _quantity(tip.get('number'))
    end = finalized if end is None else end
    start = max(0, end - max_blocks + 1) if start is None else start
    if start > end or end > finalized or end - start + 1 > max_blocks:
        raise ChainError('Range must fit max_blocks and contain only finalized blocks.')
    blocks = {}
    events = {}
    receipts = {}
    receipt_log_count = 0

    def receipt(tx_hash, number, block_hash):
        nonlocal receipt_log_count
        if tx_hash not in receipts:
            r = rpc('eth_getTransactionReceipt', [tx_hash])
            if not isinstance(r, dict) or _hash(r.get('transactionHash')) != tx_hash or _quantity(r.get('blockNumber')) != number or _hash(r.get('blockHash')) != block_hash:
                raise ChainError('Receipt disagrees with block evidence; retry the crawl.')
            if 'status' not in r and 'root' in r:
                raise ChainError('Historical receipt has no success status (pre-Byzantium); window withheld.')
            status = _quantity(r.get('status'))
            if status not in (0, 1):
                raise ChainError('Provider returned an invalid receipt status.')
            witnesses = {}
            logs = r.get('logs', [])
            if not isinstance(logs, list) or len(logs) > MAX_EVENTS:
                raise ChainError('Invalid or oversized receipt log list.')
            for entry in (logs if status else ()):
                topics = entry.get('topics') if isinstance(entry, dict) else None
                if not isinstance(topics, list) or len(topics) != 3:
                    continue
                if not all(isinstance(t, str) for t in topics):
                    continue
                if topics[0].lower() != TRANSFER or padded not in (topics[1].lower(), topics[2].lower()):
                    continue
                evidence = _log_evidence(entry)
                index = evidence.index
                inclusion = (evidence.tx_hash, evidence.block_number, evidence.block_hash)
                if inclusion != (tx_hash, number, block_hash) or index in witnesses:
                    raise ChainError('Conflicting receipt log inclusion evidence.')
                witnesses[index] = evidence
                receipt_log_count += 1
                if receipt_log_count > MAX_EVENTS:
                    raise ChainError('Receipt log limit exceeded; use a smaller range.')
            receipts[tx_hash] = (status, number, block_hash, witnesses)
        status, receipt_number, receipt_hash, witnesses = receipts[tx_hash]
        if (receipt_number, receipt_hash) != (number, block_hash):
            raise ChainError('Conflicting transaction inclusion evidence.')
        return status, witnesses

    def add_event(tx_hash, block, kind, sender_address, recipient, amount, contract=None, index=None):
        identifier = f'eip155:1:{tx_hash}:{"native" if index is None else index}'
        event = dict(id=identifier, tx_hash=tx_hash, block_number=block['number'], block_hash=block['hash'], timestamp=block['timestamp'], kind=kind, from_address=sender_address, to_address=recipient, asset='ETH' if contract is None else f'eip155:1/erc20:{contract}', raw_amount=str(amount), decimals=18 if contract is None else None, contract=contract, log_index=index, status='confirmed', source='ethereum-json-rpc', finality='finalized')
        if identifier in events and events[identifier] != event:
            raise ChainError('Conflicting duplicate event evidence.')
        events[identifier] = event
        if len(events) > MAX_EVENTS:
            raise ChainError('Event limit exceeded; use a smaller range.')

    for number in range(start, end + 1):
        raw = rpc('eth_getBlockByNumber', [hex(number), True])
        if not isinstance(raw, dict) or _quantity(raw.get('number')) != number or not isinstance(raw.get('transactions'), list):
            raise ChainError('Provider returned an incomplete block.')
        try:
            timestamp = datetime.fromtimestamp(_quantity(raw.get('timestamp')), timezone.utc).isoformat().replace('+00:00', 'Z')
        except (ValueError, OverflowError, OSError):
            raise ChainError('Invalid block timestamp.') from None
        block = dict(number=number, hash=_hash(raw.get('hash')), parent_hash=_hash(raw.get('parentHash')), timestamp=timestamp)
        if number > start and block['parent_hash'] != blocks[number-1]['hash']:
            raise ChainError('Block continuity changed; retry the crawl.')
        blocks[number] = block
        for tx in raw['transactions']:
            if not isinstance(tx, dict):
                raise ChainError('Provider did not return full transactions.')
            source = normalize_address(tx.get('from'))
            target = normalize_address(tx['to']) if tx.get('to') is not None else None
            if address not in (source, target):
                continue
            amount = _quantity(tx.get('value'))
            if not amount or target is None:  # Creation value needs receipt contract attribution, not assumed here.
                continue
            tx_hash = _hash(tx.get('hash'))
            status, _ = receipt(tx_hash, number, block['hash'])
            if status:
                add_event(tx_hash, block, 'native_transfer', source, target, amount)

    for topics in ([TRANSFER, padded], [TRANSFER, None, padded]):
        logs = rpc('eth_getLogs', [{'fromBlock': hex(start), 'toBlock': hex(end), 'topics': topics}])
        if not isinstance(logs, list) or len(logs) > MAX_EVENTS:
            raise ChainError('Invalid or oversized log response.')
        for log in logs:
            if not isinstance(log, dict):
                raise ChainError('Malformed transfer log.')
            ts = log.get('topics', [])
            if not isinstance(ts, list) or any(not isinstance(t, str) for t in ts):
                raise ChainError('Malformed transfer topics.')
            if len(ts) != 3:  # ERC-721 Transfer has 4 topics, not an ERC-20 amount.
                continue
            if ts[0].lower() != TRANSFER:
                raise ChainError('Provider returned unrelated log topics.')
            if log.get('removed') is not False:
                raise ChainError('Removed or unconfirmed log encountered; retry the crawl.')
            number = _quantity(log.get('blockNumber'))
            if number not in blocks or _hash(log.get('blockHash')) != blocks[number]['hash']:
                raise ChainError('Log disagrees with block evidence; retry the crawl.')
            decoded = []
            for topic in ts[1:]:
                if not HASH.fullmatch(topic) or topic[2:26] != '0' * 24:
                    raise ChainError('Malformed indexed address.')
                decoded.append(normalize_address('0x' + topic[-40:]))
            if address not in decoded:
                raise ChainError('Provider returned an unrelated transfer.')
            if not isinstance(log.get('data'), str) or not HASH.fullmatch(log['data']):
                raise ChainError('Malformed ERC-20 transfer amount.')
            tx_hash = _hash(log.get('transactionHash'))
            status, witnesses = receipt(tx_hash, number, blocks[number]['hash'])
            if status:
                evidence = _log_evidence(log)
                index = evidence.index
                if witnesses.get(index) != evidence:
                    raise ChainError('Filter log disagrees with transaction receipt; window withheld.')
                add_event(tx_hash, blocks[number], 'erc20_transfer', *decoded, int(log['data'], 16), evidence.contract, index)
    check = rpc('eth_getBlockByNumber', [hex(end), False])
    if not isinstance(check, dict) or _hash(check.get('hash')) != blocks[end]['hash']:
        raise ChainError('Canonical block changed during crawl; nothing was committed.')
    result = dict(provider=provider_host if provider_host in DEFAULT_HOSTS else 'operator-approved RPC', chain_id=chain_id, address=address, account_id=f'eip155:1:{address}', from_block=start, to_block=end, events=sorted(events.values(), key=lambda x: (x['block_number'], x['tx_hash'], -1 if x['log_index'] is None else x['log_index'])), blocks=list(blocks.values()), coverage='Bounded finalized blocks only. Native top-level transfers and ERC-20-shaped Transfer logs; excludes internal transfers, fees, contract-creation value, NFTs, swaps classification, prices, historical cost basis and off-chain activity. Empty results do not mean no wallet activity.', provider_finalized_block=finalized)
    _remaining(deadline)
    return result
