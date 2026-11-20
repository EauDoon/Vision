"""Workflow and boundary tests against an actual ephemeral loopback HTTP server."""
import copy
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

from app import VisionServer
from chain import crawl
from store import DEMO_ADDRESS, Store, digest
from test_chain import Fixture, A, T, URL, H


class Workbench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Store(Path(cls.tmp.name) / "index.sqlite")
        cls.server = VisionServer(0, cls.store, URL, crawler=lambda a, **k: crawl(a,http_send=Fixture(),**k))
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()
        cls.tmp.cleanup()

    def req(self, path, body=None, *, headers=None, raw=False):
        conn = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=4)
        try:
            h = dict(headers or {})
            if body is not None:
                h.setdefault('Content-Type','application/json')
            conn.request("GET" if body is None else "POST",path,
                         body=json.dumps(body) if body is not None else None,headers=h)
            res=conn.getresponse()
            data=res.read()
            return res.status, data if raw else json.loads(data)
        finally:
            conn.close()

    def test_01_static_is_served_not_workspace_files(self):
        for path,token in [('/','Vision'),('/static/app.js','/api/search'),('/static/style.css','body')]:
            code,data=self.req(path,raw=True)
            self.assertEqual(code,200)
            self.assertIn(token.encode(),data)
        for path in ('/app.py','/data/vision.sqlite3','/static/../app.py','/.env'):
            self.assertEqual(self.req(path)[0],404)

    def test_02_search_types_and_dataset_labels(self):
        status=self.req('/api/status')[1]
        self.assertEqual(status['version'],'1.3.0')
        self.assertEqual(status['demo_address'],DEMO_ADDRESS)
        for q in ('Atlas',DEMO_ADDRESS,'eip155:1:'+DEMO_ADDRESS):
            data=self.req('/api/search?q='+quote(q))[1]
            self.assertEqual(len([e for e in data['events'] if e['dataset']=='synthetic']),6)
        self.assertEqual(self.req('/api/search?q=USDC')[1]['labels'][0]['dataset'],'reference')
        self.assertEqual(self.req('/api/search?q=1999-no-such-label')[1]['events'],[])
        self.assertEqual(self.req('/api/search?q='+'z'*181)[0],400)
        # Punctuation is treated literally, never as a SQL pattern.
        self.assertEqual(self.req('/api/search?q=%25')[1]['labels'],[])

    def test_03_crawl_end_to_end_with_recorded_rpc_shape(self):
        for _ in range(2):
            code,summary=self.req('/api/crawl',dict(address=A,blocks=1,end=10))
            self.assertEqual(code,201,summary)
            self.assertEqual((summary['events'],summary['from_block'],summary['to_block']),(2,10,10))
        found=self.req('/api/search?q='+T)[1]['events']
        self.assertEqual(len(found),2)
        self.assertTrue(all(row['dataset']=='live' for row in found))
        self.assertEqual(len(self.req('/api/scans')[1]['scans']),2)
        # Same address in both datasets must not donate a synthetic label to a live event.
        self.assertFalse(any(e['dataset']=='live' for e in self.req('/api/search?q=Atlas')[1]['events']))
        e=self.req('/api/search-export?q='+T)[1]
        checksum=e.pop('sha256')
        self.assertEqual(checksum,digest(e))
        self.assertEqual(e['crawl_windows'][0]['blocks'][0]['hash'],H)
        self.assertEqual(len(e['snapshot']['events']),2)
        window_id = e['crawl_windows'][0]['scan_id']
        self.assertEqual(e['event_witnesses'], {event['id']:window_id for event in found})
        self.assertEqual(len(e['crawl_windows'][0]['events_sha256']), 64)

    def test_04_unconfigured_validation_and_origin(self):
        self.assertEqual(self.req('/api/crawl',dict(address='bad',blocks=1))[0],400)
        self.assertEqual(self.req('/api/crawl',dict(address=A,blocks=True))[0],400)
        self.assertEqual(self.req('/api/crawl',dict(address=A,blocks=999))[0],400)
        self.assertEqual(self.req('/api/crawl',dict(address=A,url='https://example.com'))[0],400)
        self.assertEqual(self.req('/api/crawl',dict(address=A,end=-1))[0],400)
        self.assertEqual(self.req('/api/status',headers={'Host':'malicious.invalid'})[0],403)
        self.assertEqual(self.req('/api/review',{},headers={'Origin':'https://not-local.example'})[0],403)
        self.assertEqual(self.req('/api/review',{},headers={'Content-Type':'text/plain'})[0],415)
        saved=self.server.rpc_url
        try:
            self.server.rpc_url=None
            self.assertEqual(self.req('/api/crawl',dict(address=A,blocks=1))[0],503)
        finally: self.server.rpc_url=saved

    def test_05_case_review_and_nonpersistent_simulation(self):
        baseline=self.req('/api/case')[1]
        self.assertEqual(baseline['result']['totals']['realized_gains'],'2250')
        self.assertEqual(baseline['result']['pack']['jurisdiction'],None)
        code,scenario=self.req('/api/simulate',{'realized_gains':'3000','income':'180'})
        self.assertEqual(code,200)
        self.assertFalse(scenario['persisted'])
        self.assertEqual(scenario['result']['differences'],{'realized_gains':'-750','income':'0'})
        self.assertEqual(self.req('/api/simulate',{'realized_gains':'NaN','income':'1'})[0],400)
        self.assertEqual(self.req('/api/case')[1]['result'],baseline['result'])
        self.assertEqual(self.req('/api/review',{'decision':'assess_tax','note':'test'})[0],400)
        self.assertEqual(self.req('/api/review',{'decision':'reviewed','note':''})[0],400)
        self.assertEqual(self.req('/api/review',{'decision':'needs_data','note':'Check fictional records.'})[0],201)
        manifest=self.req('/api/evidence')[1]
        self.assertEqual(manifest['review']['decision'],'needs_data')
        self.assertEqual(manifest['dataset'],'synthetic')
        claimed=manifest.pop('sha256')
        self.assertEqual(digest(manifest),claimed)
        self.assertNotIn(T,json.dumps(manifest))

    def test_06_atomic_conflict_and_mainnet_enforcement(self):
        result=crawl(A,rpc_url=URL,start=10,end=10,http_send=Fixture())
        self.store.record_scan(result)
        before=self.store.status()
        changed=copy.deepcopy(result)
        changed['events'][1]['raw_amount']='3'
        with self.assertRaises(ValueError): self.store.record_scan(changed)
        self.assertEqual(self.store.status(),before)
        changed=copy.deepcopy(result)
        changed['blocks'][0]['hash']='0x'+'0'*64
        with self.assertRaises(ValueError): self.store.record_scan(changed)
        changed=copy.deepcopy(result)
        changed['chain_id']=10
        with self.assertRaises(ValueError): self.store.record_scan(changed)
        self.assertEqual(self.store.status(),before)

    def test_07_index_and_case_reopen(self):
        again=Store(self.store.path)
        self.assertEqual(again.status(),self.store.status())
        self.assertEqual(again.search('Atlas')['events'],self.store.search('Atlas')['events'])

    def test_08_fixed_transfer_review_is_read_only(self):
        before = self.store.status(), self.store.scans()
        code, packet = self.req('/api/transfer-review')
        self.assertEqual(code, 200, packet)
        self.assertEqual(packet['source_mode'], 'constructed_rpc_fixture')
        self.assertEqual([(block['block_number'], block['status'], block['expected']['count'],
                           block['observed']['count']) for block in packet['blocks']], [
            (22431084, 'matched', 2, 2), (17034870, 'matched', 2, 2),
            (17034869, 'verified_zero', 0, 0)])
        claimed = packet.pop('sha256')
        self.assertEqual(claimed, digest(packet))
        self.assertEqual(self.req('/api/transfer-review', {})[0], 404)
        self.assertEqual(self.req('/api/transfer-review?end=1')[0], 400)
        self.assertEqual((self.store.status(), self.store.scans()), before)

    def test_09_replay_dashboard_serves_same_packet_and_preserves_v12(self):
        from replay_compare import packet_bytes
        before = self.store.status(), self.store.scans()
        release_packet = packet_bytes()
        for path in ('/api/replay-compare', '/replay/packet.json'):
            self.assertEqual(self.req(path, raw=True), (200, release_packet))
            self.assertEqual(self.req(path, {})[0], 404)
            self.assertEqual(self.req(path + '?end=1')[0], 400)
        self.assertIn(b'Balancer Vault replay comparison', self.req('/replay/', raw=True)[1])
        v12 = self.req('/api/transfer-review')[1]
        self.assertEqual(v12['schema'], 'vision/transfer-review@1')
        self.assertEqual(json.loads(release_packet)['fixture_packet_sha256'], v12['sha256'])
        self.assertEqual((self.store.status(), self.store.scans()), before)

    def test_10_startup_freezes_supplied_capture(self):
        import app
        from replay_compare import CAPTURE_PATH, packet_bytes
        from unittest.mock import patch

        capture = json.loads(CAPTURE_PATH.read_bytes())
        capture['captured_at'] = '2026-10-01T00:00:00Z'
        expected = packet_bytes(capture)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'capture.json'
            path.write_text(json.dumps(capture))
            def inspect_server(server):
                path.unlink()
                self.assertEqual(server.replay_packet, expected)
            argv = ['app.py', '--replay-capture', str(path), '--port', '0', '--db', str(Path(temp) / 'db')]
            with patch('sys.argv', argv), patch('app.os.umask'), patch.object(VisionServer, 'serve_forever', inspect_server):
                app.main()
