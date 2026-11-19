"""Explicit bounded Ethereum historical ingestion. No autonomous/background scanning."""
import argparse
import json
import os
import time

from chain import ChainError, HASH, _endpoint, crawl, normalize_address
from store import Store

MAX_BLOCKS = 128
LIMITS = ('Ethereum mainnet, finalized blocks only. At most 128 inclusive blocks per invocation, '
          '1–8 blocks per window, at most two retries per failed RPC window. Only exact successful '
          'address/window checkpoints are reused. No internal transfers, fees, NFT or complete-history claim. '
          'A checkpoint is local provider-observed evidence, not independent consensus verification. '
          'Rerun the identical command after failure; successful windows remain committed.')


def _bounds(start, end, window, retries):
    if any(type(v) is not int for v in (start, end, window, retries)):
        raise ValueError('Start, end, window and retries must be integers.')
    if not 0 <= start <= end <= 2**53-1 or end-start+1 > MAX_BLOCKS:
        raise ValueError('Choose an inclusive range of 1–128 non-negative blocks.')
    if not 1 <= window <= 8:
        raise ValueError('Window must be 1–8 blocks.')
    if not 0 <= retries <= 2:
        raise ValueError('Retries must be 0–2 per RPC window.')


def _checkpoint(store, address, first, last):
    """Accept only an exact successful scan backed by every persisted block hash."""
    with store.db() as db:
        rows = db.execute('SELECT record FROM scans WHERE address=? AND from_block=? AND to_block=? ORDER BY id DESC', (address, first, last))
        for row in rows:
            try:
                record = json.loads(row[0])
                if not isinstance(record, dict) or type(record.get('chain_id')) is not int:
                    continue
                if (record.get('dataset'), record.get('chain_id'), record.get('address'), record.get('from_block'), record.get('to_block')) != ('live', 1, address, first, last):
                    continue
                blocks = record['blocks']
                if len(blocks) != last-first+1 or [b['number'] for b in blocks] != list(range(first, last+1)):
                    continue
                if any(not isinstance(b.get('hash'), str) or not HASH.fullmatch(b['hash']) for b in blocks):
                    continue
                if type(record.get('events')) is not int or record['events'] < 0:
                    continue
                persisted = {r['height']:r['hash'] for r in db.execute('SELECT height,hash FROM blocks WHERE height BETWEEN ? AND ?', (first,last))}
                if any(persisted.get(b['number']) != b['hash'] for b in blocks):
                    continue
                # Presence of a scan is the commit marker: Store.record_scan writes
                # events, blocks and scan in a single transaction. No new marker file.
                return True
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
    return False


def run_backfill(store, address, *, start, end, rpc_url, window=8, retries=1,
                 crawler=crawl, sleep=time.sleep):
    """Return a credential-free report. Failed window is never checkpointed.

    RPC URL is operator-controlled environment configuration, not a client field.
    Earlier commits survive failure. Resume checks exact same address AND window;
    overlapping scans or another address's scan never substitute for coverage.
    """
    address = normalize_address(address)
    _bounds(start, end, window, retries)
    _endpoint(rpc_url)
    report = dict(status='complete', chain_id=1, address=address, from_block=start,
                  to_block=end, completed_windows=[], resumed_windows=[], failed_window=None,
                  limits=LIMITS)
    for first in range(start, end+1, window):
        last = min(end, first+window-1)
        interval = dict(from_block=first, to_block=last)
        if _checkpoint(store, address, first, last):
            report['resumed_windows'].append(interval)
            continue
        result = None
        for attempt in range(retries+1):
            try:
                result = crawler(address, rpc_url=rpc_url, start=first, end=last, max_blocks=window)
                break
            except ChainError:
                if attempt < retries:
                    sleep(min(2**attempt, 2))
            except Exception:
                # Unexpected provider failures are not echoed or retried.
                break
        if result is None:
            report.update(status='failed', failed_window=interval,
                          error='RPC window failed. Verify provider configuration, finality and access, then rerun. No failed-window data was committed.')
            return report
        # Defend the boundary even when an alternate adapter is supplied.
        try:
            if type(result.get('chain_id')) is not int:
                raise ValueError('Invalid chain identifier')
            if (result.get('chain_id'),result.get('address'),result.get('from_block'),result.get('to_block')) != (1,address,first,last):
                raise ValueError('Adapter scope mismatch')
            if [b['number'] for b in result['blocks']] != list(range(first,last+1)):
                raise ValueError('Adapter omitted a block')
            record = store.record_scan(result)
        except Exception:
            report.update(status='failed', failed_window=interval,
                          error='Window evidence could not be committed. Verify local index and block consistency before rerunning.')
            return report
        report['completed_windows'].append({**interval, 'events':record['events']})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=LIMITS)
    parser.add_argument('address', help='Explicit public Ethereum address to inspect')
    parser.add_argument('--start', type=int, required=True, help='First block, inclusive')
    parser.add_argument('--end', type=int, required=True, help='Last block, inclusive; must be finalized')
    parser.add_argument('--window', type=int, default=8)
    parser.add_argument('--retries', type=int, default=1)
    parser.add_argument('--db', default=os.getenv('VISION_DB','./data/vision.sqlite3'))
    args = parser.parse_args(argv)
    try:
        normalize_address(args.address)
        _bounds(args.start,args.end,args.window,args.retries)
        rpc_url = os.getenv('VISION_RPC_URL')
        if not rpc_url:
            raise ValueError('Set VISION_RPC_URL in the server environment before historical ingestion.')
        _endpoint(rpc_url)
    except (ValueError, ChainError) as error:
        parser.error(str(error))
    os.umask(0o077)
    try:
        report = run_backfill(Store(args.db), args.address, start=args.start,end=args.end,
                              window=args.window,retries=args.retries,rpc_url=rpc_url)
    except Exception:
        print(json.dumps({'status':'failed','error':'Local index could not be accessed. Verify path and permissions.','limits':LIMITS}))
        return 1
    print(json.dumps(report,sort_keys=True))
    return 0 if report['status']=='complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
