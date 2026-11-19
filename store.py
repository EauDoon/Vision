"""A local, bounded index. A source label describes a contract, never its users."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ADDRESS = re.compile(r"0x[0-9a-f]{40}", re.I)
HASH = re.compile(r"0x[0-9a-f]{64}", re.I)
DEMO_ADDRESS = "0x" + "11" * 20
TREASURY = "0x" + "22" * 20
VAULT = "0x" + "33" * 20
TOKEN = "0x" + "44" * 20
COVERAGE = ("Matches only locally indexed records, never complete wallet history. "
            "Reference labels describe contracts, not owners or counterparties.")
FIELDS = ["id","tx_hash","block_number","block_hash","timestamp","kind","from_address","to_address",
          "asset","raw_amount","decimals","contract","log_index","status"]
LABELS = [
    (DEMO_ADDRESS,"Atlas sample wallet","fixture:vision/explorer-v1","Example wallet","synthetic"),
    (TREASURY,"Sample treasury","fixture:vision/explorer-v1","Example counterparty","synthetic"),
    (VAULT,"Sample vault","fixture:vision/explorer-v1","Example counterparty","synthetic"),
    (TOKEN,"Unit token (UNIT)","fixture:vision/explorer-v1","Example asset","synthetic"),
    ("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48","USD Coin (USDC)",
     "https://developers.circle.com/stablecoins/usdc-contract-addresses","Token contract","reference"),
    ("0x1f98431c8ad98523631ae4a59f267346ea31f984","Uniswap V3 Factory",
     "https://developers.uniswap.org/docs/protocols/v3/deployments/v3-ethereum-deployments","Factory contract","reference"),
]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(obj):
    return hashlib.sha256(encode(obj).encode()).hexdigest()


def sample_events():
    for i, (sender, receiver, asset, amount) in enumerate([
        (TREASURY,DEMO_ADDRESS,"ETH","2500000000000000000"),
        (DEMO_ADDRESS,VAULT,"ETH","750000000000000000"),
        (VAULT,DEMO_ADDRESS,"UNIT","48000000"),
        (DEMO_ADDRESS,TREASURY,"UNIT","12000000"),
        (TREASURY,DEMO_ADDRESS,"ETH","125000000000000000"),
        (DEMO_ADDRESS,VAULT,"UNIT","7250000"),
    ], 1):
        tx = "0x" + hashlib.sha256(f"vision:fixture:tx:{i}".encode()).hexdigest()
        bh = "0x" + hashlib.sha256(f"vision:fixture:block:{i}".encode()).hexdigest()
        is_eth = asset == "ETH"
        yield dict(id=f"fixture:eth:{i}", tx_hash=tx, block_number=1_100_000+i,
                   block_hash=bh, timestamp=f"2025-03-{i+10:02d}T09:30:00Z",
                   kind="native_transfer" if is_eth else "erc20_transfer", from_address=sender,
                   to_address=receiver,asset=asset,raw_amount=amount,decimals=18 if is_eth else 6,
                   contract=None if is_eth else TOKEN,log_index=None if is_eth else 0,status="success")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    dataset TEXT NOT NULL, id TEXT NOT NULL, tx_hash TEXT NOT NULL, block_number INTEGER NOT NULL,
                    block_hash TEXT NOT NULL, timestamp TEXT NOT NULL, kind TEXT NOT NULL,
                    from_address TEXT NOT NULL, to_address TEXT, asset TEXT NOT NULL,
                    raw_amount TEXT NOT NULL, decimals INTEGER, contract TEXT, log_index INTEGER,
                    status TEXT NOT NULL, PRIMARY KEY (dataset,id));
                CREATE INDEX IF NOT EXISTS ev_tx ON events(tx_hash);
                CREATE INDEX IF NOT EXISTS ev_sender ON events(from_address);
                CREATE INDEX IF NOT EXISTS ev_receiver ON events(to_address);
                CREATE INDEX IF NOT EXISTS ev_contract ON events(contract);
                CREATE TABLE IF NOT EXISTS labels (
                    address TEXT NOT NULL, name TEXT NOT NULL, source TEXT NOT NULL,
                    category TEXT NOT NULL, dataset TEXT NOT NULL,PRIMARY KEY (dataset,address));
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY, address TEXT NOT NULL, from_block INTEGER NOT NULL,
                    to_block INTEGER NOT NULL, scan_time TEXT NOT NULL, record TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scan_events (
                    scan_id INTEGER NOT NULL, event_id TEXT NOT NULL, PRIMARY KEY (scan_id,event_id));
                CREATE INDEX IF NOT EXISTS event_witness ON scan_events(event_id,scan_id);
                CREATE TABLE IF NOT EXISTS blocks (height INTEGER PRIMARY KEY, hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY, case_hash TEXT NOT NULL, decision TEXT NOT NULL,note TEXT NOT NULL, at TEXT NOT NULL);
            """)
            db.executemany("INSERT OR IGNORE INTO labels VALUES(?,?,?,?,?)", LABELS)
            for event in sample_events():
                self.insert_event(db, "synthetic", event)

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def insert_event(db, dataset, event):
        vals = [event[k] for k in FIELDS]
        db.execute(f"INSERT OR IGNORE INTO events (dataset,{','.join(FIELDS)}) "
                   f"VALUES ({','.join('?' for _ in range(1+len(FIELDS)))})", [dataset,*vals])
        saved = db.execute("SELECT * FROM events WHERE dataset=? AND id=?", (dataset,event["id"])).fetchone()
        if vals != [saved[k] for k in FIELDS]:
            raise ValueError("Existing event conflicts with provider response; index unchanged.")

    def status(self):
        with self.db() as db:
            return {key: db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
                    for key,table in (("events","events"),("labels","labels"),("crawls","scans"))}

    def search(self, q):
        if not isinstance(q, str) or len(q)>180:
            raise ValueError("Search must be at most 180 characters.")
        q = q.strip().lower()
        if q.startswith("eip155:1:") and ADDRESS.fullmatch(q[9:]):
            q = q[9:]
        with self.db() as db:
            labq = (" FROM labels WHERE instr(lower(name),?) OR instr(address,?) OR instr(lower(category),?)")
            labels = [dict(r) for r in db.execute("SELECT *"+labq+" ORDER BY dataset,name LIMIT 50",(q,)*3)]
            where, args = "", []
            if q:
                where = (" WHERE (lower(id)=? OR lower(tx_hash)=? OR lower(block_hash)=? OR from_address=? "
                         "OR to_address=? OR contract=? OR lower(asset)=? OR CAST(block_number AS TEXT)=? "
                         "OR lower(kind)=?)")
                args = [q]*9
                for l in labels:
                    # Synthetic label matches never confer meaning on real-chain addresses.
                    where += " OR (dataset=? AND (?=from_address OR ?=to_address OR ?=contract))"
                    args += ["synthetic" if l["dataset"]=="synthetic" else "live",l["address"],l["address"],l["address"]]
            rows = [dict(r) for r in db.execute(
                "SELECT * FROM events"+where+" ORDER BY timestamp DESC, id LIMIT 101",args)]
        identifiers = []
        if ADDRESS.fullmatch(q):
            identifiers.append(dict(type="EVM account (not an identity)",value="eip155:1:"+q))
        if HASH.fullmatch(q):
            identifiers.append(dict(type="32-byte hash (transaction or block)",value=q))
        return dict(events=rows[:100],truncated=len(rows)>100,labels=labels,identifiers=identifiers,coverage=COVERAGE)

    def record_scan(self, result):
        address,first,last = result["address"],result["from_block"],result["to_block"]
        if type(result["chain_id"]) is not int or result["chain_id"] != 1:
            raise ValueError("Only Ethereum mainnet observations can be indexed.")
        blocks = result["blocks"]
        recorded = {"dataset":"live","chain_id":result["chain_id"],"address":address,"from_block":first,
                    "to_block":last,"coverage":result["coverage"],"blocks":blocks,
                    "events":len(result["events"]), "at":now(),"provider":result.get("provider","unspecified RPC"),
                    "provider_finalized_block":result.get("provider_finalized_block")}
        with self.db() as db:
            for b in blocks:
                n, h = b["number"], b["hash"]
                row = db.execute("SELECT hash FROM blocks WHERE height=?",(n,)).fetchone()
                if row and row[0] != h:
                    raise ValueError("Conflicting finalized block hash; index unchanged. Verify provider.")
                db.execute("INSERT OR IGNORE INTO blocks VALUES(?,?)",(n,h))
            for e in result["events"]:
                self.insert_event(db,"live",e)
            scan_id=db.execute("INSERT INTO scans(address,from_block,to_block,scan_time,record) VALUES(?,?,?,?,?)",
                               (address,first,last,recorded["at"],encode(recorded))).lastrowid
            db.executemany("INSERT INTO scan_events(scan_id,event_id) VALUES(?,?)",
                           ((scan_id,e["id"]) for e in result["events"]))
        return recorded

    def scans(self, limit=20):
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT record FROM scans ORDER BY id DESC LIMIT ?",(limit,))]

    def search_export(self,q):
        page=self.search(q)
        with self.db() as db:
            relevant={}
            def add(rows):
                for row in rows:
                    relevant[row["id"]]=json.loads(row["record"])
            norm=q.strip().lower().removeprefix("eip155:1:")
            if ADDRESS.fullmatch(norm):
                add(db.execute("SELECT id,record FROM scans WHERE address=? ORDER BY id DESC LIMIT 50",(norm,)))
            for event in page["events"]:
                if event["dataset"]!="live": continue
                add(db.execute("SELECT id,record FROM scans JOIN scan_events ON scan_id=id "
                               "WHERE event_id=? ORDER BY id DESC LIMIT 1",(event["id"],)))
        body={"schema":"vision/index-extract@1","query":q,"snapshot":page,"crawl_windows":list(relevant.values()),
              "scope":"At most 100 matching events; recent coverage for searched accounts and a witnessing window per live event. Synthetic fixtures never came from an RPC provider."}
        return {**body,"sha256":digest(body)}

    def reviews(self, case_hash):
        with self.db() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,decision,note,at FROM reviews WHERE case_hash=? ORDER BY id", (case_hash,))]

    def review(self, case_hash, decision, note):
        if decision not in ("needs_data","reviewed"):
            raise ValueError("Choose needs_data or reviewed.")
        if not isinstance(note,str) or not 1<=len(note.strip())<=500:
            raise ValueError("Add a review note between 1 and 500 characters.")
        at, note = now(), note.strip()
        with self.db() as db:
            db.execute("INSERT INTO reviews(case_hash,decision,note,at) VALUES(?,?,?,?)",(case_hash,decision,note,at))
        return dict(decision=decision,note=note,at=at)
