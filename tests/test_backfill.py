import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backfill import run_backfill, main
from chain import ChainError
from store import Store

A='0x'+'1'*40
B='0x'+'2'*40
URL='https://ethereum.publicnode.com'

class FakeCrawler:
    def __init__(self): self.calls=[]; self.fail_at=None; self.remaining_failures=0
    def __call__(self,address,**kw):
        self.calls.append((address,kw['start'],kw['end']))
        if kw['start']==self.fail_at and self.remaining_failures:
            self.remaining_failures-=1
            raise ChainError('https://provider.invalid/secret-key')
        blocks=[dict(number=n,hash='0x'+format(n,'064x'),parent_hash='0x'+format(max(n-1,0),'064x'),timestamp='2026-01-01T00:00:00Z') for n in range(kw['start'],kw['end']+1)]
        return dict(chain_id=1,address=address,from_block=kw['start'],to_block=kw['end'],blocks=blocks,events=[],coverage='Fixture bounded window')

class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'vision.db'); self.crawler=FakeCrawler()
    def run_fill(self,**kwargs):
        args=dict(start=10,end=27,rpc_url=URL,crawler=self.crawler,sleep=lambda _:None)
        args.update(kwargs)
        return run_backfill(self.store,A,**args)
    def test_windows_inclusive(self):
        r=self.run_fill()
        self.assertEqual(r['status'],'complete')
        self.assertEqual(self.crawler.calls,[(A,10,17),(A,18,25),(A,26,27)])
        self.assertEqual(len(self.store.scans()),3)
    def test_restart_skips_exact_durable_windows(self):
        self.run_fill(); self.crawler.calls=[]
        self.store=Store(Path(self.tmp.name)/'vision.db')
        r=self.run_fill()
        self.assertEqual(self.crawler.calls,[])
        self.assertEqual(len(r['resumed_windows']),3)
    def test_failure_and_resume_no_false_coverage(self):
        self.crawler.fail_at=18; self.crawler.remaining_failures=5
        r=self.run_fill(retries=1)
        self.assertEqual(r['status'],'failed'); self.assertEqual(r['failed_window'],{'from_block':18,'to_block':25})
        self.assertEqual(len(self.store.scans()),1)
        self.assertEqual(len(self.crawler.calls),3)
        self.assertNotIn('secret',str(r))
        self.crawler.fail_at=None; self.crawler.calls=[]
        r=self.run_fill()
        self.assertEqual(r['status'],'complete')
        self.assertEqual(self.crawler.calls,[(A,18,25),(A,26,27)])
    def test_other_address_does_not_count(self):
        run_backfill(self.store,B,start=10,end=17,rpc_url=URL,crawler=self.crawler)
        self.crawler.calls=[]; self.run_fill(end=17)
        self.assertEqual(self.crawler.calls,[(A,10,17)])
    def test_overlapping_window_does_not_count(self):
        self.run_fill(start=9,end=16); self.crawler.calls=[]
        self.run_fill(end=17)
        self.assertEqual(self.crawler.calls,[(A,10,17)])
    def test_incomplete_checkpoint_not_reused(self):
        self.run_fill(end=17)
        with self.store.db() as db: db.execute('DELETE FROM blocks WHERE height=12')
        self.crawler.calls=[]; self.run_fill(end=17)
        self.assertEqual(self.crawler.calls,[(A,10,17)])
    def test_malformed_checkpoint_not_reused(self):
        self.run_fill(end=17)
        with self.store.db() as db: db.execute("UPDATE scans SET record='[]'")
        self.crawler.calls=[]; self.run_fill(end=17)
        self.assertEqual(self.crawler.calls,[(A,10,17)])
    def test_max_range_accepted(self):
        r=self.run_fill(start=0,end=127)
        self.assertEqual(r['status'],'complete')
        self.assertEqual(len(self.crawler.calls),16)
    def test_transient_retry_succeeds(self):
        self.crawler.fail_at=10; self.crawler.remaining_failures=1
        self.assertEqual(self.run_fill(end=17)['status'],'complete')
        self.assertEqual(len(self.crawler.calls),2)
    def test_no_retry_option(self):
        self.crawler.fail_at=10; self.crawler.remaining_failures=5
        self.assertEqual(self.run_fill(retries=0)['status'],'failed')
        self.assertEqual(len(self.crawler.calls),1)
    def test_validation_before_crawl(self):
        for args in (dict(start=-1),dict(start=28),dict(end=138),dict(window=9),dict(window=True),dict(retries=3),dict(end=2**54),dict(rpc_url='http://localhost')):
            with self.subTest(args=args),self.assertRaises(ValueError): self.run_fill(**args)
        self.assertEqual(self.crawler.calls,[])
    def test_scope_mismatch_not_persisted(self):
        def bad(address,**kwargs):
            r=self.crawler(address,**kwargs); r['address']=B; return r
        r=self.run_fill(crawler=bad)
        self.assertEqual(r['status'],'failed'); self.assertEqual(self.store.scans(),[])
    def test_incomplete_result_not_persisted(self):
        def bad(address,**kwargs):
            r=self.crawler(address,**kwargs); r['blocks'].pop(); return r
        self.assertEqual(self.run_fill(crawler=bad)['status'],'failed')
        self.assertEqual(self.store.scans(),[])
    def test_conflict_stops_no_checkpoint(self):
        with self.store.db() as db: db.execute('INSERT INTO blocks VALUES(?,?)',(10,'wrong-hash'))
        self.assertEqual(self.run_fill()['status'],'failed')
        self.assertEqual(self.store.scans(),[])
    def test_cli_requires_operator_rpc(self):
        with patch.dict('os.environ',{'VISION_RPC_URL':''}), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            main([A,'--start','10','--end','17'])
        self.assertEqual(exc.exception.code,2)

if __name__=='__main__': unittest.main()
