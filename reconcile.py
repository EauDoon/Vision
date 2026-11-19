"""Synthetic FIFO reconciliation. Not a country rule pack or a tax assessment.

JSON numeric inputs MUST be decimal strings. Every unit price, including acquisition
basis, must have a source. Event order for a shared timestamp is the input order.
Opening history must be supplied as acquisition events; transfers are deliberately
unsupported because ownership/valuation cannot be inferred from chain movements.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import re

PACK = {"id": "VISION-DEMO-FIFO", "version": "1.0", "jurisdiction": None}
LIMITATIONS = [
    "Illustrative FIFO reconciliation only; no tax liability, evasion finding, or country-law approval.",
    "Completeness, beneficial ownership, classifications and supplied prices require human review.",
    "Fees, transfers, swaps, corporate actions, FX, reliefs and off-chain activity are not inferred.",
    "FIFO applies per supplied asset identifier in this single synthetic case; same-time input order is authoritative.",
    "Hash proves content consistency, not source authenticity or an immutable chain of custody.",
]


def _text(value, field, maximum=512):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be a nonempty string of at most {maximum} characters")
    return value


def _number(value, field, positive=False):
    if not isinstance(value, str) or not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,29})(?:\.[0-9]{1,18})?", value):
        raise ValueError(f"{field} must be a finite plain decimal string (30 integer, 18 fractional digits maximum)")
    number = Decimal(value)
    if positive and number <= 0:
        raise ValueError(f"{field} must be positive")
    return number


def _instant(value, field):
    _text(value, field, 40)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
        raise ValueError(f"{field} must be an ISO UTC timestamp ending Z")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _day(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    return date.fromisoformat(value)


def _string(number):
    value = format(number, "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def reconcile(case):
    """Return all-or-nothing synthetic reconstruction with a canonical evidence hash.

    Validation failures return status=blocked and totals/differences=None. Successful
    outputs retain price and source provenance for every realized lot match.
    """
    result = {"case_id": None, "status": "blocked", "pack": dict(PACK), "currency": None,
              "period": None, "as_of": None, "totals": None, "declared": None,
              "differences": None, "lots": [], "disposals": [], "income_events": [],
              "issues": [], "evidence_hash": None, "human_review_required": True,
              "limitations": list(LIMITATIONS)}
    try:
        # Prevent mutable input references escaping and non-JSON values entering evidence.
        canonical_input = json.loads(json.dumps(case, allow_nan=False))
        if not isinstance(canonical_input, dict):
            raise ValueError("case must be an object")
        case = canonical_input
        result["case_id"] = _text(case.get("case_id"), "case_id", 128)
        currency = case.get("currency")
        if currency != "USD":
            raise ValueError("Demo pack accepts USD only; no implicit FX conversion")
        result["currency"] = currency
        period = case.get("period")
        if not isinstance(period, dict):
            raise ValueError("period must be an object")
        start, end = _day(period.get("start"), "period.start"), _day(period.get("end"), "period.end")
        if start > end:
            raise ValueError("period.start must not follow period.end")
        as_of = _instant(case.get("as_of"), "as_of")
        if as_of.date() < end:
            raise ValueError("as_of must cover the full fiscal period")
        if as_of.date() == end and as_of.time().isoformat() != "23:59:59.999999":
            raise ValueError("as_of must follow period.end or include its final microsecond")
        result.update(period=dict(period), as_of=case["as_of"])
        declared = case.get("declared")
        if not isinstance(declared, dict) or set(declared) != {"realized_gains", "income"}:
            raise ValueError("declared must contain exactly realized_gains and income")
        declared_numbers = {key: _number(value, f"declared.{key}") for key, value in declared.items()}
        if declared_numbers["income"] < 0:
            raise ValueError("declared.income must not be negative")
        result["declared"] = {key: _string(value) for key, value in declared_numbers.items()}
        events = case.get("events")
        if not isinstance(events, list) or len(events) > 10000:
            raise ValueError("events must be a list of at most 10000 events")
        parsed, ids, refs = [], set(), set()
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                raise ValueError("each event must be an object")
            eid = _text(event.get("id"), "event.id", 128)
            if eid in ids:
                raise ValueError(f"Duplicate event identifier: {eid}")
            ids.add(eid)
            source_ref = _text(event.get("source_ref"), f"{eid}.source_ref")
            if source_ref in refs:
                raise ValueError("Duplicate source_ref; use a unique source line or event locator")
            refs.add(source_ref)
            timestamp = _instant(event.get("timestamp"), f"{eid}.timestamp")
            if timestamp > as_of or timestamp.date() > end:
                raise ValueError(f"{eid}: event occurs after period or snapshot")
            kind = event.get("kind")
            if kind not in {"acquisition", "disposal", "income"}:
                raise ValueError(f"{eid}: unsupported classification")
            asset = _text(event.get("asset"), f"{eid}.asset", 128)
            quantity = _number(event.get("quantity"), f"{eid}.quantity", positive=True)
            price = _number(event.get("unit_price"), f"{eid}.unit_price")
            if price < 0:
                raise ValueError(f"{eid}: price must not be negative")
            _text(event.get("price_source"), f"{eid}.price_source")
            parsed.append((timestamp, index, event, asset, quantity, price))
        parsed.sort(key=lambda row: (row[0], row[1]))
        lots, disposals, incomes = defaultdict(deque), [], []
        gains, income = Decimal(0), Decimal(0)
        with localcontext() as context:
            context.prec = 110  # Exact products/sums under the bounded input schema.
            for timestamp, index, event, asset, quantity, price in parsed:
                within = start <= timestamp.date() <= end
                kind = event["kind"]
                if kind in {"acquisition", "income"}:
                    lots[asset].append({"remaining": quantity, "price": price, "event": event})
                    if kind == "income" and within:
                        amount = quantity * price
                        income += amount
                        incomes.append({"event_id": event["id"], "amount": _string(amount), "source_ref": event["source_ref"], "price_source": event["price_source"]})
                    continue
                remaining, basis, matches = quantity, Decimal(0), []
                while remaining > 0:
                    if not lots[asset]:
                        raise ValueError(f"{event['id']}: missing opening/acquisition basis for {asset}")
                    lot = lots[asset][0]
                    used = min(remaining, lot["remaining"])
                    cost = used * lot["price"]
                    basis += cost
                    matches.append({"acquisition_id": lot["event"]["id"], "quantity": _string(used), "basis": _string(cost), "source_ref": lot["event"]["source_ref"], "price_source": lot["event"]["price_source"]})
                    lot["remaining"] -= used
                    remaining -= used
                    if lot["remaining"] == 0:
                        lots[asset].popleft()
                if within:
                    proceeds = quantity * price
                    gain = proceeds - basis
                    gains += gain
                    disposals.append({"event_id": event["id"], "asset": asset, "quantity": _string(quantity), "proceeds": _string(proceeds), "basis": _string(basis), "gain": _string(gain), "source_ref": event["source_ref"], "price_source": event["price_source"], "matches": matches})
            total = {"realized_gains": gains, "income": income}
            result.update(status="illustrative", totals={key: _string(value) for key, value in total.items()}, differences={key: _string(value - declared_numbers[key]) for key, value in total.items()}, disposals=disposals, income_events=incomes, lots=[{"asset": asset, "acquisition_id": lot["event"]["id"], "remaining_quantity": _string(lot["remaining"]), "unit_basis": _string(lot["price"]), "source_ref": lot["event"]["source_ref"], "price_source": lot["event"]["price_source"]} for asset in sorted(lots) for lot in lots[asset]])
        result["evidence_hash"] = _hash({"input": canonical_input, "result": {key: value for key, value in result.items() if key != "evidence_hash"}})
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        result.update(status="blocked", totals=None, differences=None, lots=[], disposals=[], income_events=[], evidence_hash=None, issues=[str(error)])
    return result


def demo_case():
    """Return independent fictional source records, not observations of real wallets."""
    events = [
        ("opening-1", "2025-12-01T12:00:00Z", "acquisition", "2", "1000"),
        ("buy-2", "2026-02-01T12:00:00Z", "acquisition", "1", "1500"),
        ("sell-3", "2026-03-01T12:00:00Z", "disposal", "2.5", "2000"),
        ("reward-4", "2026-04-01T12:00:00Z", "income", "0.1", "1800"),
    ]
    return {"case_id": "SYNTHETIC-001", "currency": "USD", "period": {"start": "2026-01-01", "end": "2026-12-31"}, "as_of": "2027-01-01T00:00:00Z", "declared": {"realized_gains": "2000", "income": "100"}, "events": [{"id": eid, "timestamp": timestamp, "kind": kind, "asset": "DEMO-ETH", "quantity": quantity, "unit_price": price, "price_source": f"synthetic://prices/{eid}", "source_ref": f"synthetic://ledger/{eid}"} for eid, timestamp, kind, quantity, price in events]}
