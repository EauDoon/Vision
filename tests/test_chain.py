import copy
import unittest
from unittest.mock import patch
from chain import crawl, ChainError, TRANSFER, normalize_address

A='0x'+'1'*40
B='0x'+'2'*40
C='0x'+'3'*40
H='0x'+'a'*64
P='0x'+'b'*64
T='0x'+'c'*64
U='0x'+'d'*64
URL='https://ethereum.publicnode.com'

def topic(a): return '0x'+a[2:].rjust(64,'0')

class Fixture:
    def __init__(self):
        self.calls=[]
        self.chain='0x1'
        self.block={'number':'0xa','hash':H,'parentHash':P,'timestamp':'0x6553f100','transactions':[{'hash':T,'from':A,'to':B,'value':hex(10**18)}]}
        self.receipt={'transactionHash':T,'blockNumber':'0xa','blockHash':H,'status':'0x1'}
        self.logs=[{'address':C,'topics':[TRANSFER,topic(A),topic(A)],'data':'0x'+format(10**30,'064x'),'transactionHash':T,'blockNumber':'0xa','blockHash':H,'logIndex':'0x0','removed':False}]
        self.mutate=None
    def __call__(self,url,p):
        self.calls.append(p)
        m=p['method']
        if m=='eth_chainId': result=self.chain
        elif m=='eth_getBlockByNumber': result=self.block
        elif m=='eth_getLogs': result=self.logs
        elif m=='eth_getTransactionReceipt': result={'logs':self.logs, **self.receipt}
        else: raise AssertionError(m)
        response={'jsonrpc':'2.0','id':p['id'],'result':copy.deepcopy(result)}
        if self.mutate: self.mutate(p,response)
        return response

class ChainTests(unittest.TestCase):
    def run_crawl(self,f=None,**kwargs):
        return crawl(A,rpc_url=URL,start=10,end=10,http_send=f or Fixture(),**kwargs)
    def test_exact_units_dedupe_and_provenance(self):
        f=Fixture(); r=self.run_crawl(f)
        self.assertEqual(len(r['events']),2)
        native,token=r['events']
        self.assertEqual(native['raw_amount'],'1000000000000000000')
        self.assertEqual(token['raw_amount'],'1000000000000000000000000000000')
        self.assertEqual(native['decimals'],18); self.assertIsNone(token['decimals'])
        self.assertEqual(token['block_hash'],H)
        self.assertEqual(token['from_address'],token['to_address'])
        self.assertEqual(sum(p['method']=='eth_getTransactionReceipt' for p in f.calls),1)
        self.assertIn('excludes',r['coverage'])
    def test_reverted_ignored(self):
        f=Fixture(); f.receipt['status']='0x0'
        self.assertEqual(self.run_crawl(f)['events'],[])
    def test_nft_not_misclassified(self):
        f=Fixture(); f.logs[0]['topics'].append('0x'+'0'*64)
        self.assertEqual(len(self.run_crawl(f)['events']),1)
    def test_zero_token_transfer_retained(self):
        f=Fixture(); f.logs[0]['data']='0x'+'0'*64
        self.assertEqual(self.run_crawl(f)['events'][1]['raw_amount'],'0')
    def test_filter_and_receipt_agree_on_exact_log(self):
        f = Fixture()
        f.receipt['logs'] = copy.deepcopy(f.logs)
        f.receipt['logs'][0]['data'] = '0x' + format(7, '064x')
        with self.assertRaisesRegex(ChainError, 'disagrees with transaction receipt'):
            self.run_crawl(f)

    def test_receipt_needs_an_entry_for_filtered_transfer(self):
        f = Fixture()
        f.receipt['logs'] = []
        with self.assertRaisesRegex(ChainError, 'disagrees with transaction receipt'):
            self.run_crawl(f)

    def test_root_only_receipt_has_specific_coverage_error(self):
        f = Fixture()
        del f.receipt['status']
        f.receipt['root'] = H
        with self.assertRaisesRegex(ChainError, 'pre-Byzantium'):
            self.run_crawl(f)

    def test_final_response_must_arrive_within_budget(self):
        f = Fixture()
        clock = [0]
        def advance_at_final_header(request, reply):
            if request['method'] == 'eth_getBlockByNumber' and request['params'] == ['0xa', False]:
                clock[0] = 61
        f.mutate = advance_at_final_header
        with patch('chain.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(ChainError, 'time budget'):
                self.run_crawl(f)

    def test_wrong_chain(self):
        f=Fixture(); f.chain='0x89'
        with self.assertRaises(ChainError): self.run_crawl(f)
    def test_removed_log(self):
        f=Fixture(); f.logs[0]['removed']=True
        with self.assertRaises(ChainError): self.run_crawl(f)
    def test_receipt_hash_mismatch(self):
        f=Fixture(); f.receipt['blockHash']=P
        with self.assertRaises(ChainError): self.run_crawl(f)
    def test_log_hash_mismatch(self):
        f=Fixture(); f.logs[0]['blockHash']=P
        with self.assertRaises(ChainError): self.run_crawl(f)
    def test_reorg_at_completion(self):
        f=Fixture()
        def mutate(p,r):
            if p['method']=='eth_getBlockByNumber' and p['params']==['0xa',False]: r['result']['hash']=P
        f.mutate=mutate
        with self.assertRaises(ChainError): self.run_crawl(f)
    def test_unfinalized_or_excessive_range(self):
        for start,end in [(10,11),(0,10),(11,10),(-1,1),(True,10)]:
            with self.subTest(start=start,end=end),self.assertRaises(ChainError):
                crawl(A,rpc_url=URL,start=start,end=end,http_send=Fixture())
    def test_invalid_bounds(self):
        for limit in (0,65,True,2.5):
            with self.subTest(limit=limit),self.assertRaises(ChainError): self.run_crawl(max_blocks=limit)
    def test_invalid_address(self):
        for a in ('alice.eth','0x123',None,'0x'+'g'*40):
            with self.subTest(a=a),self.assertRaises(ChainError): normalize_address(a)
    def test_endpoint_restrictions(self):
        for url in ('http://ethereum.publicnode.com','https://localhost','https://127.0.0.1','https://ethereum.publicnode.com:8080','https://user:password@ethereum.publicnode.com','https://example.org'):
            with self.subTest(url=url),self.assertRaises(ChainError): crawl(A,rpc_url=url,http_send=Fixture())
    def test_rpc_error_is_redacted(self):
        f=Fixture(); f.mutate=lambda p,r:r.update(error={'message':'secret-token-private'})
        with self.assertRaises(ChainError) as error: self.run_crawl(f)
        self.assertNotIn('secret',str(error.exception))
    def test_transport_error_is_redacted(self):
        def broken(*args): raise RuntimeError('secret-token-private')
        with self.assertRaises(ChainError) as error: self.run_crawl(broken)
        self.assertNotIn('secret',str(error.exception))
    def test_only_read_methods(self):
        f=Fixture(); self.run_crawl(f)
        self.assertEqual(set(p['method'] for p in f.calls),{'eth_chainId','eth_getBlockByNumber','eth_getLogs','eth_getTransactionReceipt'})
    def test_empty_window_honest(self):
        f=Fixture(); f.block['transactions']=[]; f.logs=[]
        r=self.run_crawl(f)
        self.assertEqual(r['events'],[])
        self.assertIn('Empty results do not mean',r['coverage'])
    def test_duplicate_conflict_rejected(self):
        f=Fixture(); f.logs.append(copy.deepcopy(f.logs[0])); f.logs[1]['data']='0x'+'0'*64
        with self.assertRaises(ChainError): self.run_crawl(f)
    def test_no_finalized_fallback(self):
        f=Fixture()
        def mutate(p,r):
            if p['method']=='eth_getBlockByNumber' and p['params'][0]=='finalized': r['result']=None
        f.mutate=mutate
        with self.assertRaises(ChainError): self.run_crawl(f)
    def test_malformed_topics(self):
        for topics in (None, [TRANSFER, 12, topic(A)]):
            f=Fixture(); f.logs[0]['topics']=topics
            with self.subTest(topics=topics),self.assertRaises(ChainError): self.run_crawl(f)
    def test_malformed_data(self):
        f=Fixture(); f.logs[0]['data']=None
        with self.assertRaises(ChainError): self.run_crawl(f)
    def test_continuity_mismatch(self):
        f=Fixture()
        def mutate(p,r):
            if p['method']=='eth_getBlockByNumber' and p['params'][0]=='0x9':
                r['result']['number']='0x9'; r['result']['transactions']=[]
        f.mutate=mutate
        with self.assertRaises(ChainError): crawl(A,rpc_url=URL,start=9,end=10,http_send=f)
    def test_request_deadline(self):
        with patch('chain.time.monotonic',side_effect=[0,61]), self.assertRaises(ChainError): self.run_crawl()
    def test_inbound_outbound_filters(self):
        f=Fixture(); self.run_crawl(f)
        calls=[p['params'][0]['topics'] for p in f.calls if p['method']=='eth_getLogs']
        self.assertEqual(calls, [[TRANSFER,topic(A)],[TRANSFER,None,topic(A)]])
    def test_provider_response_id(self):
        f=Fixture(); f.mutate=lambda p,r:r.update(id=9999)
        with self.assertRaises(ChainError): self.run_crawl(f)

if __name__=='__main__': unittest.main()
