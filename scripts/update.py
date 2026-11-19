"""Оновлення даних RentMapPoltava з відкритого API Prozorro.Продажі.

Запуск:  python scripts/update.py
Вимоги:  Python 3.9+, пакет requests (pip install requests). Ключі API не потрібні.

Що робить:
 1. Бере перелік ocid із data/p3-01_listProzorroSales.csv (набір міста P3-01).
 2. Завантажує картки об'єктів:   POST https://procedure.prozorro.sale/api/search/registry
    фільтр registryObjectId IN [...] (пакетами по 100).
 3. Завантажує орендні аукціони:  POST https://procedure.prozorro.sale/api/search/procedures
    фільтр registryObjectId IN [...] (з пагінацією).
 4. Завантажує всі об'єкти орендодавця (Управління майном, ЄДРПОУ 13967034) — для «Звірки».
 5. Зберігає data/prozorro.json і перебудовує data/data.json, data-defects.csv та index.html.
Ліміти: паузи між запитами 0,4 с; один прохід ≈ 20–30 запитів.
"""
import csv, json, os, sys, time, hashlib, re, datetime as dt
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = 'https://procedure.prozorro.sale/api/search/'
SELLER = '13967034'
S = requests.Session(); S.headers['Content-Type'] = 'application/json'

def post(path, body):
    for attempt in range(4):
        r = S.post(API + path, data=json.dumps(body), timeout=60)
        if r.ok: return r.json()
        time.sleep(2 * (attempt + 1))
    r.raise_for_status()

def g(o, path):
    for k in path.split('.'):
        if o is None: return None
        o = o.get(k) if isinstance(o, dict) else None
    return o
uk = lambda x: (x.get('uk_UA') or x.get('en_US')) if isinstance(x, dict) else x

def obj_row(o, orgs):
    it = (o.get('registryObjectItems') or [{}])[0]; pl = it.get('placing') or {}; rp = it.get('reProps') or {}; ro = o.get('relatedOrganizations') or {}
    for role in ('propertyOwner', 'governer', 'currentTenant'):
        i = g(ro, role + '.identifier') or {}
        if i.get('id') and 'FOP' not in (i.get('scheme') or '') and i.get('scheme') != 'UA-IPN' and not re.fullmatch(r'\d{10}', str(i['id'])):
            orgs.setdefault(i['id'], uk(i.get('legalName')))
    import re
    m = re.search(r"([А-ЯІЇЄҐа-яіїєґ'’]+)\s+район", uk(g(pl, 'address.streetAddress')) or '')
    f = lambda v: round(float(v), 5) if v not in (None, '') else None
    tsch = g(ro, 'currentTenant.identifier.scheme')
    return [o['registryObjectId'], g(o, 'statusesDecisions.statusInList'), uk(o.get('title')), m.group(1) if m else None,
            f(g(pl, 'location.latitude')), f(g(pl, 'location.longitude')), rp.get('totalObjectArea'), rp.get('usableArea'),
            rp.get('generalCondition'), rp.get('floors'), rp.get('locationInBuilding'), g(ro, 'propertyOwner.identifier.id'),
            g(ro, 'sellingEntity.identifier.id'), g(ro, 'governer.identifier.id'), tsch,
            None if (tsch or '').endswith('FOP') or tsch == 'UA-IPN' else g(ro, 'currentTenant.identifier.id'),
            (o.get('datePublished') or '')[:10], (o.get('dateModified') or '')[:10], len(o.get('contracts') or []),
            g(o, 'leaseRules.leaseDuration'), rp.get('heatingType')]

def proc_row(p, orgs):
    bids = p.get('bids') or []; act = [b for b in bids if b.get('status') in ('active', 'pending')]
    aw = next((a for a in p.get('awards') or [] if a.get('status') == 'active'), (p.get('awards') or [None])[0])
    buyer = (aw or {}).get('buyers', [None])[0] if aw else None
    sch = g(buyer, 'identifier.scheme') if buyer else None
    wid = g(buyer, 'identifier.id') if buyer and sch and 'FOP' not in sch else None
    if wid and sch == 'UA-IPN' and '*' not in wid:  # фізособа: зберігаємо лише хеш (правило «ризики, а не особи»)
        wid = 'h:' + hashlib.sha1(('rm' + wid).encode()).hexdigest()[:12]
    if wid and sch == 'UA-EDR' and '*' not in wid: orgs.setdefault(wid, uk(g(buyer, 'identifier.legalName')) or uk(buyer.get('name')))
    ct = next((c for c in p.get('contracts') or [] if c.get('status') == 'active'), (p.get('contracts') or [None])[0])
    return [p.get('auctionId'), p.get('registryObjectId'), p.get('status'), (p.get('sellingMethod') or '').replace('legitimatePropertyLease-', ''),
            (p.get('datePublished') or '')[:10], (g(p, 'auctionPeriod.startDate') or '')[:10], g(p, 'value.amount'), g(p, 'value.valueAddedTaxIncluded'),
            g(aw, 'value.amount') if aw else None, (aw or {}).get('status'), len(bids), len(act), g(p, 'minimalStep.amount'), p.get('tenderAttempts'),
            p.get('previousAuctionId'), p.get('listType'), sch, wid, (ct or {}).get('status'), g(ct, 'value.amount') if ct else None,
            ((ct or {}).get('dateSigned') or '')[:10] or None, p.get('leaseDuration'), p.get('valuePeriod'), len(p.get('cancellations') or []),
            g(p, 'relatedOrganizations.currentTenant.identifier.scheme')]

def privatization_sales():
    """Завершені аукціони малої приватизації Управління → data/privatization_sales.json (покупців не зберігаємо)."""
    rows, page = [], 1
    while True:
        r = post('procedures', {'limit': 100, 'page': page, 'filters': [{'field': 'sellingEntity.identifier.id', 'operator': 'eq', 'value': SELLER}]})
        for p in r['payload']:
            if not (p.get('sellingMethod') or '').startswith('smallPrivatization') or p.get('status') != 'complete': continue
            its = p.get('items') or []
            area = round(sum(float(i.get('quantity') or 0) for i in its if g(i, 'unit.code') == 'MTK'), 1)
            t = uk(p.get('title')) or ''; k = t.find('адрес')
            addr = (t[k:].split(':', 1)[-1].strip().rstrip('.') if k >= 0 else uk(g(its[0], 'address.streetAddress')) if its else '')[:90]
            ct = next((c for c in p.get('contracts') or [] if c.get('status') in ('active', 'paid', 'signed')), None)
            aw = next((a for a in p.get('awards') or [] if a.get('status') == 'active'), None)
            final = g(ct, 'value.amount') if ct else g(aw, 'value.amount') if aw else None
            sa = json.dumps(g(its[0], 'address') if its else {}, ensure_ascii=False)
            dm = re.search(r'(Шевченківський|Подільський|Київський) район', sa)
            district = 'Полтавський' if re.search(r'(^|\s)с\.\s?[А-ЯІЇЄҐ]', addr) or not dm else dm.group(1)
            loc = g(its[0], 'location') if its else None
            rows.append([p.get('auctionId'), (g(p, 'auctionPeriod.startDate') or p.get('datePublished') or '')[:7], addr, area,
                         g(p, 'value.amount'), final, len(p.get('bids') or []), p['sellingMethod'].split('-')[-1], district,
                         round(float(loc['latitude']), 3) if loc and loc.get('latitude') else None, round(float(loc['longitude']), 3) if loc and loc.get('longitude') else None])
        time.sleep(.4)
        if page >= r.get('max_page', 1): break
        page += 1
    rows.sort(key=lambda x: x[1], reverse=True)
    json.dump({'source': 'Prozorro.Продажі, search/procedures; sellingEntity 13967034; smallPrivatization-*; status complete',
               'fetched': dt.date.today().isoformat(), 'note': 'Ціни без ПДВ: стартова і ціна договору купівлі-продажу. Площа — сума items з одиницею MTK.',
               'fields': ['auctionId', 'date', 'addr', 'area', 'start', 'final', 'bids', 'method', 'district', 'lat', 'lng'], 'rows': rows},
              open(os.path.join(ROOT, 'data', 'privatization_sales.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print('аукціонів приватизації (завершених):', len(rows))

def main():
    ocids = [r['ocid'] for r in csv.DictReader(open(os.path.join(ROOT, 'data', 'p3-01_listProzorroSales.csv'), encoding='utf-8'))]
    print('P3-01:', len(ocids), 'ocid')
    orgs, objs, procs, allobj = {}, [], [], []
    for i in range(0, len(ocids), 100):
        r = post('registry', {'limit': 100, 'filters': [{'field': 'registryObjectId', 'operator': 'in', 'value': ocids[i:i + 100]}]})
        objs += [obj_row(o, orgs) for o in r['payload']]; time.sleep(.4)
        page = 1
        while True:
            r = post('procedures', {'limit': 100, 'page': page, 'filters': [{'field': 'registryObjectId', 'operator': 'in', 'value': ocids[i:i + 100]}]})
            procs += [proc_row(p, orgs) for p in r['payload']]; time.sleep(.4)
            if page >= r.get('max_page', 1): break
            page += 1
    page = 1
    while True:
        r = post('registry', {'limit': 100, 'page': page, 'filters': [{'field': 'relatedOrganizations.sellingEntity.identifier.id', 'operator': 'eq', 'value': SELLER}]})
        for o in r['payload']:
            it = (o.get('registryObjectItems') or [{}])[0]; loc = g(it, 'placing.location')
            allobj.append([o['registryObjectId'], g(o, 'statusesDecisions.statusInList'), uk(o.get('title')), g(o, 'relatedOrganizations.propertyOwner.identifier.id'),
                           (o.get('datePublished') or '')[:10], g(it, 'reProps.totalObjectArea'), [loc.get('latitude'), loc.get('longitude')] if loc else None])
        time.sleep(.4)
        if page >= r.get('max_page', 1): break
        page += 1
    missing = set(ocids) - {o[0] for o in objs}
    print(f'об’єктів: {len(objs)} (не знайдено {len(missing)}), аукціонів: {len(procs)}, об’єктів орендодавця: {len(allobj)}')
    out = {'fetched': dt.datetime.utcnow().isoformat(timespec='seconds') + 'Z', 'source': 'procedure.prozorro.sale/api (registry + search)',
           'objects': objs, 'objects_fields': ['ocid','statusInList','title','district','lat','lng','totalArea','usableArea','condition','floors','locationInBuilding','propertyOwnerId','sellingEntityId','governerId','tenantScheme','tenantId','datePublished','dateModified','nContracts','leaseDuration','heating'],
           'procedures': procs, 'procedures_fields': ['auctionId','ocid','status','method','datePublished','auctionDate','startValue','vatIncluded','awardValue','awardStatus','nBids','nActiveBids','minimalStep','tenderAttempts','previousAuctionId','listType','winnerScheme','winnerId','contractStatus','contractValue','dateSigned','leaseDuration','valuePeriod','nCancellations','currentTenantScheme'],
           'orgs': orgs, 'all_seller_objects': allobj, 'all_fields': ['ocid','statusInList','title','propertyOwnerId','datePublished','totalArea','latlng']}
    json.dump(out, open(os.path.join(ROOT, 'data', 'prozorro.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    privatization_sales()
    os.system(f'"{sys.executable}" "{os.path.join(ROOT, "scripts", "build.py")}"')
    os.system(f'"{sys.executable}" "{os.path.join(ROOT, "scripts", "assemble.py")}"')

if __name__ == '__main__':
    main()
