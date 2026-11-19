"""Offline acceptance checks for the static worked report and its integration."""
import http.client
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from app import VisionServer
from reconcile import demo_case, reconcile
from report import graphic, outputs, ROOT
from store import Store


class Markup(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class FieldNote(unittest.TestCase):
    def test_generated_assets_reproduce_byte_for_byte(self):
        for name, body in outputs().items():
            self.assertEqual((ROOT/'static'/name).read_bytes(), body.encode())

    def test_chart_scaled_to_exact_lot_contributions(self):
        result = outputs()
        svg = ET.fromstring(result['report-figure.svg'])
        ns = {'s':'http://www.w3.org/2000/svg'}
        bars = [el for el in svg.findall('.//s:rect', ns) if el.get('y')=='208']
        widths = [Decimal(el.attrib['width']) for el in bars]
        self.assertEqual([w/sum(widths) for w in widths],[Decimal('.4'),Decimal('.15'),Decimal('.45')])
        self.assertEqual([Decimal(el.attrib['x']) for el in bars], [56,400,529])
        self.assertEqual(svg.attrib['role'],'img')
        for name in svg.attrib['aria-labelledby'].split():
            self.assertIsNotNone(svg.find(f".//*[@id='{name}']"))

    def test_report_facts_and_fingerprint(self):
        html = outputs()['report.html']
        for value in ('$5,000','$2,750','$2,250','$250','$80','synthetic://ledger/opening-1',reconcile(demo_case())['evidence_hash']):
            self.assertIn(value,html)
        self.assertIn('No wallet ownership',html)

    def test_unresolved_basis_withholds_report(self):
        data = demo_case()
        data['events'][0].pop('price_source')
        with patch('report.demo_case',return_value=data), self.assertRaisesRegex(ValueError,'withheld'):
            outputs()

    def test_graph_does_not_mask_loss_or_unmatched_proceeds(self):
        sale = reconcile(demo_case())['disposals'][0]
        for bad in (dict(sale,gain='-1'),dict(sale,proceeds='9000'),dict(sale,matches=[])):
            with self.assertRaises(ValueError): graphic(bad)

    def test_no_external_resources_or_active_content(self):
        page=Markup(outputs()['report.html'])
        self.assertFalse(any(tag in ('script','iframe','form','object') for tag,attr in page.tags))
        self.assertFalse(any(k.startswith('on') for _,a in page.tags for k in a))
        for _,a in page.tags:
            for k in ('src','href'):
                if k in a and not a[k].startswith('#'):
                    self.assertIn(a[k],('report-figure.svg','report.css'))
                    self.assertTrue((ROOT/'static'/a[k]).is_file())
        self.assertGreaterEqual(sum(tag=='summary' for tag,_ in page.tags),2)

    def test_report_routes_do_not_include_saved_review(self):
        with TemporaryDirectory() as folder:
            store=Store(Path(folder)/'local.sqlite')
            store.review(reconcile(demo_case())['evidence_hash'],'needs_data','INTERNAL-NOTE-TEST-MARKER')
            with VisionServer(0,store) as server:
                t=Thread(target=server.serve_forever);t.start()
                try:
                    conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                    for asset,kind in [('report.html','text/html'),('report.css','text/css'),('report-figure.svg','image/svg+xml')]:
                        conn.request('GET','/static/'+asset); response=conn.getresponse()
                        self.assertEqual(response.status,200)
                        self.assertTrue(response.getheader('Content-Type').startswith(kind))
                        body=response.read()
                        self.assertEqual(body,(ROOT/'static'/asset).read_bytes())
                        self.assertNotIn(b'INTERNAL-NOTE-TEST-MARKER',body)
                    conn.close()
                finally:
                    server.shutdown();t.join()

    def test_single_file_offline_report_embeds_visuals(self):
        html=outputs()['vision-field-note.html']
        tags=Markup(html).tags
        self.assertTrue(any(t=='style' for t,a in tags))
        self.assertTrue(any(t=='svg' for t,a in tags))
        self.assertFalse(any(t in ('link','script','img','iframe') for t,a in tags))
        self.assertNotIn('@import',html)
        self.assertIn(reconcile(demo_case())['evidence_hash'],html)

    def test_review_boundary_matches_browser(self):
        attrs=next(a for tag,a in Markup((ROOT/'static'/'index.html').read_text()).tags if a.get('id')=='review-note')
        limit=int(attrs['maxlength']);self.assertEqual(limit,500)
        with TemporaryDirectory() as folder:
            store=Store(Path(folder)/'local.sqlite')
            store.review('synthetic','reviewed','x'*limit)
            with self.assertRaisesRegex(ValueError,'500'):
                store.review('synthetic','reviewed','x'*(limit+1))
