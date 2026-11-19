"""Vision 1.1.0 | local-only read-only chain exploration and fictional case review."""
import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from chain import ChainError, crawl, normalize_address
from reconcile import demo_case, reconcile
from store import DEMO_ADDRESS, Store, digest, encode

VERSION = "1.1.0"
STATIC = Path(__file__).resolve().parent / "static"
FILES = {"/":("index.html","text/html; charset=utf-8"),"/index.html":("index.html","text/html; charset=utf-8"),
         "/static/app.js":("app.js","text/javascript; charset=utf-8"),"/static/style.css":("style.css","text/css; charset=utf-8")}
for asset, mime in (("report.html", "text/html; charset=utf-8"), ("report.css", "text/css; charset=utf-8"), ("report-figure.svg", "image/svg+xml")):
    FILES["/static/" + asset] = (asset, mime)
BOUNDARY = "Local research workbench. Public-chain observations and simulated case evidence are separate."


class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class VisionServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, store, rpc_url=None, crawler=crawl):
        self.store, self.rpc_url, self.crawler = store, rpc_url, crawler
        self.crawl_lock = threading.Lock()
        super().__init__(("127.0.0.1",port), Handler)

    def case(self):
        data = demo_case()
        result = reconcile(data)
        reviews = self.store.reviews(result["evidence_hash"])
        return dict(input=data,result=result,review=reviews[-1] if reviews else None,
                    reviews=reviews,dataset="synthetic",boundary=BOUNDARY)


class Handler(BaseHTTPRequestHandler):
    server_version = "Vision/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, *args):
        # Never print URLs, wallet identifiers, review content or provider credentials.
        return

    def send_data(self, code, data, mime, download=None):
        self.send_response(code)
        self.send_header("Content-Type",mime)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'")
        if download:
            self.send_header("Content-Disposition",'attachment; filename="'+download+'"')
        self.end_headers()
        self.wfile.write(data)

    def json(self, code, obj, download=None):
        self.send_data(code,encode(obj).encode(),"application/json; charset=utf-8",download)

    def guard(self, write=False):
        # Bind to loopback and reject DNS rebinding and arbitrary cross-site browser writes.
        host = self.headers.get("Host","")
        port = self.server.server_port
        if host not in {f"127.0.0.1:{port}",f"localhost:{port}"}:
            raise Problem(403,"Local access only; open the printed loopback URL.")
        origin = self.headers.get("Origin")
        if write and ((origin and origin!="http://"+host)
                      or self.headers.get("Sec-Fetch-Site")=="cross-site"):
            raise Problem(403,"Cross-origin writes are not accepted.")

    def payload(self):
        if self.headers.get("Content-Type","").split(";")[0]!="application/json":
            raise Problem(415,"JSON body required.")
        if self.headers.get("Transfer-Encoding"):
            raise Problem(400,"Send a fixed-length JSON body.")
        try: size = int(self.headers.get("Content-Length",""))
        except ValueError: raise Problem(411,"A content length is required.")
        if not 1<=size<=32768: raise Problem(413,"Body must be 1–32768 bytes.")
        try:
            data=json.loads(self.rfile.read(size))
        except (ValueError,UnicodeError,RecursionError):
            raise Problem(400,"Invalid JSON.")
        if not isinstance(data,dict): raise Problem(400,"Send a JSON object.")
        return data

    def dispatch(self,write):
        self.guard(write)
        url=urlsplit(self.path)
        path=url.path
        if not write and path in FILES:
            name,mime=FILES[path]
            return self.send_data(200,(STATIC/name).read_bytes(),mime)
        db=self.server.store
        if not write and path=="/api/status":
            return self.json(200,dict(name="Vision",version=VERSION,counts=db.status(),
                rpc_configured=bool(self.server.rpc_url),demo_address=DEMO_ADDRESS,boundary=BOUNDARY))
        if not write and path in ("/api/search","/api/search-export"):
            qs=parse_qs(url.query,max_num_fields=4)
            q=qs.get("q",[""])[0]
            if path.endswith("export"):
                return self.json(200,db.search_export(q),"vision-index-extract.json")
            return self.json(200,db.search(q))
        if not write and path=="/api/scans":
            return self.json(200,{"scans":db.scans()})
        if not write and path=="/api/case":
            return self.json(200,self.server.case())
        if not write and path=="/api/evidence":
            case=self.server.case()
            if case["result"]["status"]!="illustrative" or not case["result"]["evidence_hash"]:
                raise Problem(409,"Cannot export incomplete case lineage.")
            case.update(schema="vision/case-evidence@1",integrity="Canonical JSON SHA-256. Not a signature or proof of authenticity.")
            return self.json(200,{**case,"sha256":digest(case)},"vision-fictional-case.json")
        if write and path=="/api/simulate":
            data=self.payload()
            if set(data)!={"realized_gains","income"}:
                raise Problem(400,"Supply both declared amounts as plain decimal strings.")
            example=demo_case()
            example["declared"]=data
            result=reconcile(example)
            if result["status"]!="illustrative":
                raise Problem(400,"; ".join(result["issues"]))
            return self.json(200,{"result":result,"dataset":"synthetic","persisted":False})
        if write and path=="/api/review":
            data=self.payload()
            if set(data)!={"decision","note"}: raise Problem(400,"Expected decision and note.")
            result=self.server.case()["result"]
            return self.json(201,db.review(result["evidence_hash"],data.get("decision"),data.get("note")))
        if write and path=="/api/crawl":
            data=self.payload()
            if set(data)-{"address","blocks","end"}: raise Problem(400,"Unexpected crawl parameters.")
            addr=normalize_address(data.get("address"))
            count=data.get("blocks",4)
            end=data.get("end")
            if type(count) is not int or not 1<=count<=8: raise Problem(400,"Choose 1–8 blocks.")
            if end is not None and (type(end) is not int or not 0<=end<=2**53-1):
                raise Problem(400,"End must be a non-negative block height.")
            if not self.server.rpc_url:
                raise Problem(503,"No provider configured. Set VISION_RPC_URL in the server environment and restart.")
            if not self.server.crawl_lock.acquire(blocking=False):
                raise Problem(409,"One crawl is already running.")
            try:
                try:
                    record=self.server.crawler(addr,rpc_url=self.server.rpc_url,end=end,max_blocks=count)
                except ChainError as exc:
                    raise Problem(502,str(exc)) from None
                result=db.record_scan(record)
            finally:
                self.server.crawl_lock.release()
            return self.json(201,result)
        raise Problem(404,"Route not found.")

    def run_method(self,write):
        try:
            self.dispatch(write)
        except Problem as exc:
            self.json(exc.status,{"error":exc.message})
        except (ValueError,TypeError) as exc:
            self.json(400,{"error":str(exc)[:200]})
        except (BrokenPipeError,ConnectionResetError,TimeoutError):
            return
        except Exception:
            self.json(500,{"error":"Internal error. No provider credentials or case data are logged."})

    def do_GET(self): self.run_method(False)
    def do_POST(self): self.run_method(True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--db",default=os.getenv("VISION_DB","./data/vision.sqlite3"))
    args=parser.parse_args()
    if not 0<=args.port<=65535: parser.error("Port out of range.")
    os.umask(0o077)
    with VisionServer(args.port,Store(args.db),os.getenv("VISION_RPC_URL")) as server:
        print(f"Vision {VERSION} · http://127.0.0.1:{server.server_port} · Ctrl+C to stop",flush=True)
        try: server.serve_forever()
        except KeyboardInterrupt: pass


if __name__=="__main__": main()
