"""Build Vision's public, fictional worked report; no database, URLs or case inputs."""
from decimal import Decimal, localcontext
from html import escape
from pathlib import Path

from reconcile import demo_case, reconcile

ROOT = Path(__file__).resolve().parent


def money(value):
    num = Decimal(value)
    return ('−' if num < 0 else '') + '$' + format(abs(num), ',f').removesuffix('.0')


def graphic(sale):
    """Encode the actual lot matches and residual gain on a common proceeds axis."""
    total = Decimal(sale['proceeds'])
    parts = [Decimal(row['basis']) for row in sale['matches']] + [Decimal(sale['gain'])]
    if len(parts) != 3 or min(parts) < 0 or total <= 0 or sum(parts) != total:
        raise ValueError('This two-lot report needs a positive, completely matched example.')
    x = Decimal(56)
    rects = []
    for n, (amount, color) in enumerate(zip(parts, ('#8bdfcd','#ffcf79','#cbb6ff')), 1):
        with localcontext() as ctx:
            ctx.prec = 56
            width = amount * 860 / total
        rects.append(f'<rect x="{x:.3f}" y="208" width="{width:.3f}" height="62" fill="{color}"/>')
        # The text legend remains usable even when a segment is too narrow for a label.
        if width >= 46:
            rects.append(f'<text x="{x+width/2:.3f}" y="248" text-anchor="middle" font-size="23" fill="#162d2a">0{n}</text>')
        x += width
    legend = ''.join(f'<g transform="translate({x},311)"><circle cy="-5" r="7" fill="{color}"/><text x="15" font-size="18" fill="#e4eae5">{lab}</text><text x="15" y="35" fill="white" font-size="27">{money(val)}</text></g>'
                     for x,color,lab,val in zip((63,338,643),('#8bdfcd','#ffcf79','#cbb6ff'),('01  Opening lot','02  Next lot','03  Gain'),parts))
    desc = escape(' + '.join(money(v) for v in parts) + ' = ' + money(total) + ' of synthetic proceeds. Widths are proportional to proceeds.')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 972 398" role="img" aria-labelledby="title desc">
<title id="title">Where the sale proceeds go</title><desc id="desc">{desc}</desc>
<rect width="972" height="398" rx="15" fill="#172f2e"/><g font-family="DejaVu Sans,Arial,sans-serif">
<text x="56" y="57" fill="#8bdfcd" font-size="16" letter-spacing="3">VISION   /   FIELD NOTE 01</text>
<text x="56" y="120" fill="white" font-size="42" font-weight="bold">One sale, two cost lots.</text>
<text x="56" y="164" fill="#d1ded9" font-size="21">{money(total)} in fictional proceeds, split by contribution</text>
{''.join(rects)}{legend}</g></svg>'''


def outputs():
    data = demo_case()
    r = reconcile(data)
    if r['status'] != 'illustrative' or not r['evidence_hash'] or len(r['disposals']) != 1 or len(r['income_events']) != 1:
        raise ValueError('Report withheld: the frozen worked case is incomplete or its shape changed.')
    sale, = r['disposals']
    chart = graphic(sale)
    events = {e['id']: e for e in data['events']}
    income_event, = r['income_events']
    reward = events[income_event['event_id']]
    rows = []
    for match in sale['matches']:
        e = events[match['acquisition_id']]
        rows.append(f"<tr><th>{escape(e['timestamp'][:10])}</th><td>{match['quantity']}</td><td>{money(e['unit_price'])}</td><td>{money(match['basis'])}</td></tr>")
    compare = ''.join(f'<tr><th>{name}</th><td>{money(r["totals"][key])}</td><td>{money(r["declared"][key])}</td><td><b>{money(r["differences"][key])}</b></td></tr>' for key, name in [('realized_gains','Realized gain'),('income','Income')])
    refs = ''.join(f'<li><b>{escape(e["id"])}</b><span>{escape(e["source_ref"])}</span><span>{escape(e["price_source"])}</span></li>' for e in data['events'])
    mapping = {'gain':money(r['totals']['realized_gains']), 'basis':money(sale['basis']), 'firstcost':money(sale['matches'][0]['basis']), 'secondcost':money(sale['matches'][1]['basis']), 'sale':money(sale['proceeds']), 'quantity':escape(sale['quantity']), 'table':''.join(rows), 'compare':compare, 'refs':refs, 'gdiff':money(r['differences']['realized_gains']), 'idiff':money(r['differences']['income']), 'hash':escape(r['evidence_hash']), 'start':escape(r['period']['start']), 'end':escape(r['period']['end'])}
    mapping.update(reward_id=escape(reward['id']), reward_quantity=escape(reward['quantity']),
                   reward_price=money(reward['unit_price']), reward_amount=money(income_event['amount']))
    page = (ROOT/'templates'/'report.html').read_text(encoding='utf-8')
    from string import Template
    html = Template(page).substitute(mapping)
    import re
    standalone = html.replace('<link rel="stylesheet" href="report.css">', '<style>' + (ROOT/'static'/'report.css').read_text(encoding='utf-8') + '</style>')
    standalone = re.sub(r'<img src="report-figure\.svg" alt="[^"]*">', lambda _: chart, standalone, count=1)
    return {'report-figure.svg': chart+'\n', 'report.html': html, 'vision-field-note.html': standalone}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail if the shipped report is stale; write nothing.')
    args = parser.parse_args()
    for name, text in outputs().items():
        target = ROOT/'static'/name
        if args.check:
            if not target.exists() or target.read_bytes() != text.encode('utf-8'):
                raise SystemExit('Stale generated asset: '+name)
        else:
            target.write_bytes(text.encode('utf-8'))
