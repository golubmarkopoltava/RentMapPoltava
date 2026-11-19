"""RentMapPoltava — збирання даних.
Входи: prozorro.json (API Prozorro.Продажі), leases.json (перелік 554 договорів, PDF міста),
inventory.txt (перелік 459 нежитлових об'єктів), перелік приватизації (вбудовано нижче),
listProzorroSales (553 ocid — вбудовано в prozorro.json як objects).
Вихід: data.json для RentMapPoltava.html + data-defects.csv.
"""
import json, re, csv, collections, statistics as st, hashlib, datetime as dt, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, 'data')
P_JSON = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, 'prozorro.json')
CFG_FILE = os.path.join(ROOT, 'rules.json')
TODAY = dt.date.today()
CFG = json.load(open(CFG_FILE, encoding='utf-8'))['thresholds']  # пороги правил — rules.json

d = json.load(open(P_JSON, encoding='utf-8'))
O = [dict(zip(d['objects_fields'], r)) for r in d['objects']]
P = [dict(zip(d['procedures_fields'], r)) for r in d['procedures']]
A = [dict(zip(d['all_fields'], r)) for r in d['all_seller_objects']]
ORGS = d['orgs']
leases = json.load(open(os.path.join(BASE, 'leases.json'), encoding='utf-8'))

# ---------- inventory ----------
inv = []
lines = open(os.path.join(BASE, 'inventory.txt'), encoding='utf-8').read().split('\n')
for i, l in enumerate(lines):
    m = re.match(r'^\s*(\d{1,3})\s{2,}(.+?)\s*$', l)
    if m and int(m.group(1)) <= 459 and re.search(r'Полтав|район', m.group(2)):
        a = m.group(2)
        if i + 1 < len(lines) and re.fullmatch(r'\s{4,}\d{1,3}\s*', lines[i + 1]):
            a += ' ' + lines[i + 1].strip()
        inv.append({'n': int(m.group(1)), 'address': a})
assert len(inv) == 459

PRIV = [  # перелік приватизації 2026 (рішення 74 сесії 17.12.2025 + 81 сесії 17.07.2026)
    ('м. Полтава, вул. Сортувальна, 33а', 35.5, 'Приватизовано 25.05.2026'),
    ('м. Полтава, вул. Новий Базар, 18', 19.8, 'Приватизовано 15.06.2026'),
    ('м. Полтава, вул. Шевченка, 18', 27.3, 'Приватизовано 16.06.2026'),
    ('м. Полтава, узвіз Воскресенський, 3/5', 44.8, 'У переліку приватизації'),
    ('м. Полтава, вул. Лесі Українки, 4', 99.1, 'Аукціон SPE001-UA-20260823-44702'),
    ('с. Ковалівка, вул. Гаврилка Михайла, 2-в', 838.6, 'У переліку приватизації'),
    ('с. Валок, вул. Шкільна, 12-А', 207.6, 'У переліку приватизації'),
    ('с. Супрунівка, вул. Нафтовиків, 15', 59.2, 'Аукціон SPE001-UA-20260823-30821'),
    ('с. Супрунівка, вул. Нафтовиків, 5', 42.2, 'Аукціон SPE001-UA-20260823-74225'),
    ('м. Полтава, вул. Мстислава Патріарха, 13', 79.5, 'Додано 17.07.2026'),
    ('м. Полтава, вул. Кириченко Раїси, 22', 21.6, 'Додано 17.07.2026'),
    ('м. Полтава, провул. Спортивний, 13в', 62.2, 'Додано 17.07.2026'),
]

# ---------- address normalisation ----------
ST = r'(вулиця|вул\.?|провулок|провул\.?|пров\.?|проспект|просп\.?|пр-т|бульвар|бульв\.?|б-р\.?|площа|пл\.?|узвіз|майдан|мн\.?|шосе|мікрорайон)'
def norm(a):
    a = (a or '').lower().replace('’', "'").replace('`', "'").replace('ʼ', "'")
    a = re.sub(r'^.*?адресою:?\s*', '', a)
    a = re.sub(r'площею.*$', '', a)
    a = re.sub(r'\([^)]*\)', '', a)
    a = a.replace('1100-річчя', 'річчя').replace('1100- річчя', 'річчя').replace('н.базар', 'новий базар').replace('н. базар', 'новий базар')
    a = re.sub(r'м\.\s*полтава,?', '', a)
    a = re.sub(r'полтавський р-?н\.?,?|полтавський район,?|полтавська обл\S*,?', '', a)
    a = re.sub(r'нежит\S*\s*прим\S*\s*\S+', '', a); a = re.sub(r'корп\.?\s*\d+', '', a)
    a = re.sub(r'приміщення\s*\d+', '', a)
    village = None
    mv = re.search(r'(?:с\.|село)\s*([а-яіїєґ\'-]+)', a)
    if mv: village = mv.group(1); a = a.replace(mv.group(0), '')
    a = re.sub(ST, ' ', a); a = re.sub(r'буд\.?|будинок', '', a)
    a = a.replace('"', '').replace('«', '').replace('»', '')
    m = re.search(r'(\d+[\-/]?\s*[а-яa-z]?(?:/\d+[а-я]?)?)', a)
    house = re.sub(r'[\s\-]', '', m.group(1)).replace('a', 'а') if m else ''
    street = a[:m.start()] if m else a
    words = sorted(w for w in re.findall(r"[а-яіїєґ']{3,}", street) if w not in ('полтава', 'район', 'громадська', 'площею'))
    return (village or 'полтава', tuple(words), house)
def kmatch(k1, k2):
    if k1[2] != k2[2] or not k1[2]: return False
    if k1[0] != k2[0] and 'полтава' not in (k1[0], k2[0]): return False
    s1, s2 = set(k1[1]), set(k2[1])
    return bool(s1 & s2) or any(a[:5] == b[:5] for a in s1 for b in s2)

for x in inv: x['key'] = norm(x['address'])
for x in leases: x['key'] = norm(x['address'])
for o in O:
    o['addr'] = re.sub(r'^.*?адресою:?\s*', '', o['title'] or '').strip()
    o['addr'] = re.sub(r'\s*площею.*$', '', o['addr']).strip().rstrip(',')
    o['key'] = norm(o['title'])

# ---------- helpers ----------
def anon_tenant(t):
    t = t or ''
    if re.match(r'\s*(ФОП|Фізична особа)', t) or re.fullmatch(r"[А-ЯІЇЄҐ][а-яіїєґ'’]+ [А-ЯІЇЄҐ]\.\s?[А-ЯІЇЄҐ]\.", t.strip()):
        return 'Фізична особа-підприємець', True
    return t, False
def pseudo(s):
    return 'Учасник-' + hashlib.sha1(('rm' + s).encode()).hexdigest()[:5].upper()
def days(a, b): return (b - a).days
D = lambda s: dt.date.fromisoformat(s) if s else None
def bucket(a):
    return '<30' if a < 30 else '30–100' if a < 100 else '100–300' if a < 300 else '300+'

# ---------- leases: rates ----------
COMM = re.compile(r'будь-яким|торгів|магазин|офіс|кафе|аптек|банк|салон|послуг|майстерн|склад', re.I)
for x in leases:
    x['tenant_pub'], x['tenant_person'] = anon_tenant(x['tenant'])
    x['rate'] = round(x['rent_month'] / 1.2 / x['area'], 2) if x['rent_type'] == 'paid' and x['area'] and x['section'] == 'general' else None
    x['commercial'] = bool(COMM.search(x['purpose'] or '')) and x['section'] == 'general'

# ---------- procedures ----------
byobj = collections.defaultdict(list)
for p in P: byobj[p['ocid']].append(p)
area_by = {o['ocid']: o['totalArea'] for o in O}
for p in P:
    a = area_by.get(p['ocid'])
    p['rate'] = round(p['awardValue'] / a, 2) if p['status'] == 'complete' and p['awardValue'] and a and p['valuePeriod'] == 'month' else None

# analog medians (грн/м²/міс без ПДВ): ставки аукціонів + комерційні договори
rates = collections.defaultdict(list)
for p in P:
    if p['rate']: rates[bucket(area_by[p['ocid']])].append(p['rate'])
for x in leases:
    if x['rate'] and x['commercial']: rates[bucket(x['area'])].append(x['rate'])
MED = {k: round(st.median(v), 2) for k, v in rates.items() if len(v) >= 5}
ALLMED = round(st.median([r for v in rates.values() for r in v]), 2)
def analog(a): return MED.get(bucket(a), ALLMED)

# ---------- match objects <-> leases / inventory / privatization ----------
for o in O:
    cand = [x for x in leases if kmatch(o['key'], x['key'])]
    best = None
    if cand:
        best = min(cand, key=lambda x: abs((x['area'] or 0) - (o['totalArea'] or 0)))
        o['lease_match'] = 'exact' if abs((best['area'] or 0) - (o['totalArea'] or 0)) <= 1 else 'address'
    else:
        o['lease_match'] = 'none'
    o['lease'] = best['n'] if best else None
    o['area_city'] = best['area'] if best else None
    o['lease_cands'] = len(cand)
    o['inv'] = [i['n'] for i in inv if kmatch(o['key'], i['key'])]
    o['priv'] = next((s for a, ar, s in PRIV if kmatch(o['key'], norm(a))), None)
for x in leases:
    x['inv'] = [i['n'] for i in inv if kmatch(x['key'], i['key'])]
    x['objs'] = [o['ocid'] for o in O if o['lease'] == x['n']]

# ---------- red flags ----------
RULES = {
 'one_bidder': {'title': 'Аукціон з одним учасником', 'w': 1, 'level': 'auction',
   'formula': 'status = complete AND кількість ставок = 1', 'why': 'Відсутність конкуренції: ставка дорівнює стартовій ціні.',
   'legit': 'Низький попит на об’єкт; аукціон із переважним правом чинного орендаря; специфічне призначення.'},
 'min_increase': {'title': 'Мінімальне підвищення ціни', 'w': 2, 'level': 'auction',
   'formula': f'ставок ≥ 2 AND (фінальна / стартова − 1) < {int(CFG["min_increase"]*100)}%', 'why': 'Кілька учасників, але ціна майже не зросла — можлива відсутність реальної конкуренції.',
   'legit': 'Обмежений бюджет учасників; висока стартова ціна.'},
 'repeat_winner': {'title': 'Повторна перемога одного учасника', 'w': 1, 'level': 'auction',
   'formula': f'один і той самий переможець ≥ {CFG["repeat_winner_min"]} аукціонів', 'why': 'Концентрація об’єктів в одного орендаря.',
   'legit': 'Мережевий бізнес, банк або оператор зв’язку з багатьма точками.'},
 'priority_no_comp': {'title': 'Продовження з переважним правом без конкуренції', 'w': 1, 'level': 'auction',
   'formula': 'метод = priorityEnglish AND ставок = 1', 'why': 'Договір фактично продовжено чинному орендарю без альтернативних пропозицій.',
   'legit': 'Закон передбачає переважне право сумлінного орендаря на продовження.'},
 'unsucc_then_drop': {'title': 'Аукціон не відбувся → зниження ціни', 'w': 1, 'level': 'auction',
   'formula': 'є попередній аукціон AND стартова ціна < стартової попереднього', 'why': 'Знижена ціна може бути вигідна заздалегідь визначеному учаснику.',
   'legit': 'Стандартна процедура: після аукціону, що не відбувся, ціна знижується на 50% за законом.'},
 'low_rate': {'title': 'Ставка нижча за медіану аналогів', 'w': 2, 'level': 'auction',
   'formula': f'грн/м² < {int(CFG["low_rate_ratio"]*100)}% медіани аналогів тієї ж групи площі', 'why': 'Можливі недоотримані доходи громади.',
   'legit': 'Поганий стан приміщення, підвал, погодинна оренда, пільгова категорія.'},
 'status_conflict': {'title': 'Розбіжність статусу між джерелами', 'w': 1, 'level': 'object',
   'formula': 'Prozorro: «включено до переліку» (approved) AND у переліку договорів міста є договір на ту саму адресу й площу (±1 м²)', 'why': 'Незрозуміло, чи приміщення вільне: інвестор може подати заявку на зайняте приміщення, а громада — недооцінити або переоцінити доходи.',
   'legit': 'Об’єкт включено до переліку для продовження договору чинному орендарю (аукціон з переважним правом); статус у Prozorro ще не оновлено.'},
 'area_mismatch': {'title': 'Площа різниться між джерелами', 'w': 1, 'level': 'object',
   'formula': 'адреса збігається з договором у переліку міста, але площа відрізняється більш ніж на 1 м² (або в Prozorro площа = 0)', 'why': 'Від площі залежить орендна плата: помилка в площі означає помилку в доходах.',
   'legit': 'За однією адресою кілька приміщень (договір стосується іншого); площа уточнена після обмірів.'},
 'long_vacant': {'title': 'Довго в переліку без договору', 'w': 2, 'level': 'object',
   'formula': f'«включено до переліку» AND договору немає в жодному джерелі AND > {CFG["long_vacant_days"]} днів від публікації', 'why': 'Приміщення не приносить доходу громаді.',
   'legit': 'Потреба в ремонті; відсутність попиту; об’єкт зарезервовано під потреби громади.'},
 'repeat_unsucc': {'title': 'Кілька аукціонів, що не відбулися', 'w': 1, 'level': 'object',
   'formula': f'аукціонів зі статусом unsuccessful ≥ {CFG["repeat_unsuccessful_min"]}', 'why': 'Умови оренди можуть бути невідповідними ринку.',
   'legit': 'Об’єкт у поганому стані або з обмеженим призначенням.'},
 'term_expired': {'title': 'Строк договору минув (за переліком міста)', 'w': 1, 'level': 'lease',
   'formula': 'строк дії договору < 30.06.2026 (дата переліку)', 'why': 'Договір у переліку чинних, хоча строк скінчився.',
   'legit': 'Продовження на час воєнного стану за постановою КМУ №634 (примітка ** у переліку).'},
 'symbolic_rent': {'title': 'Символічна плата 1,20 грн/рік', 'w': 0, 'level': 'lease',
   'formula': 'орендна плата = 1,20 грн на рік', 'why': 'Пільгова ставка — варто бачити, кому і на якій підставі.',
   'legit': 'Бюджетні установи, держоргани, комунальні заклади, бібліотеки (дозволено законом).'},
 'zero_rent': {'title': 'Плата 0,00 грн', 'w': 1, 'level': 'lease',
   'formula': 'орендна плата = 0,00', 'why': 'Не вказано, яку пільгу застосовано.',
   'legit': 'Звільнення мобілізованих орендарів і площ під гуманітарні склади (примітка * у переліку).'},
 'no_contract_no': {'title': 'Договір без номера', 'w': 1, 'level': 'lease',
   'formula': 'номер договору відсутній', 'why': 'Ускладнює ідентифікацію договору.',
   'legit': 'Технічна помилка при формуванні переліку.'},
 'date_conflict': {'title': 'Строк дії раніше за дату договору', 'w': 1, 'level': 'lease',
   'formula': 'строк дії < дата укладення', 'why': 'Логічна помилка в даних.', 'legit': 'Описка в переліку.'},
}

win = collections.Counter()
for p in P:
    if p['status'] == 'complete' and p['winnerScheme']:
        wid = p['winnerId'] if p['winnerId'] and '*' not in p['winnerId'] else None
        p['winner_key'] = (p['winnerScheme'], wid) if wid else None
        if wid: win[(p['winnerScheme'], wid)] += 1
    else:
        p['winner_key'] = None
byauc = {p['auctionId']: p for p in P}
for p in P:
    f = []
    if p['status'] == 'complete':
        if p['nBids'] == 1: f.append('one_bidder')
        if p['nBids'] >= 2 and p['startValue'] and p['awardValue'] and p['awardValue'] / p['startValue'] - 1 < CFG['min_increase']: f.append('min_increase')
        if p['winner_key'] and win[p['winner_key']] >= CFG['repeat_winner_min']: f.append('repeat_winner')
        if p['method'] == 'priorityEnglish' and p['nBids'] == 1: f.append('priority_no_comp')
        if p['rate'] and p['rate'] < CFG['low_rate_ratio'] * analog(area_by[p['ocid']]): f.append('low_rate')
    q = byauc.get(p['previousAuctionId'])
    if q and p['startValue'] and q['startValue'] and p['startValue'] < q['startValue']: f.append('unsucc_then_drop')
    p['flags'] = f
    p['score'] = sum(RULES[k]['w'] for k in f)
    # публічне ім'я переможця: лише юрособи (ЄДРПОУ), фізособи — псевдонім
    if p['winnerScheme'] == 'UA-EDR' and p['winner_key']:
        p['winner_pub'] = ORGS.get(p['winner_key'][1], 'Юридична особа') + f" (ЄДРПОУ {p['winner_key'][1]})"
    elif p['winnerScheme'] == 'UA-EDR':
        p['winner_pub'] = 'Юридична особа (код приховано в джерелі)'
    elif p['winnerScheme']:
        p['winner_pub'] = 'Фізична особа' + (f' · {pseudo(p["winner_key"][1])}' if p['winner_key'] else '')
    else:
        p['winner_pub'] = None

for o in O:
    ps = sorted(byobj.get(o['ocid'], []), key=lambda p: p['datePublished'])
    o['n_auc'] = len(ps); o['n_unsucc'] = sum(p['status'] == 'unsuccessful' for p in ps)
    comp = [p for p in ps if p['status'] == 'complete']
    o['last_rate'] = comp[-1]['rate'] if comp else None
    o['last_award'] = comp[-1]['awardValue'] if comp else None
    o['last_period'] = comp[-1]['valuePeriod'] if comp else None
    o['first_auc'] = ps[0]['datePublished'] if ps else None
    o['first_contract'] = min((p['dateSigned'] for p in comp if p['dateSigned']), default=None)
    o['days_to_auc'] = days(D(o['datePublished']), D(o['first_auc'])) if o['first_auc'] else None
    o['days_to_contract'] = days(D(o['datePublished']), D(o['first_contract'])) if o['first_contract'] else None
    o['list_type'] = next((p['listType'] for p in reversed(ps) if p['listType']), None)
    o['active_lot'] = next((p['auctionId'] for p in reversed(ps) if p['status'] in ('active_tendering', 'active_auction', 'active_qualification', 'pending')), None)
    f = []
    age = days(D(o['datePublished']), TODAY)
    # Статус використання: «вільне» НЕ визначаємо з одного джерела.
    if o['statusInList'] == 'sold': o['use'] = 'leased'
    elif o['statusInList'] == 'approved' and o['lease_match'] == 'exact': o['use'] = 'conflict'      # у переліку Prozorro, але є договір у переліку міста
    elif o['statusInList'] == 'approved' and o['lease_match'] == 'address': o['use'] = 'check'       # за адресою є договір іншого приміщення — уточнити
    elif o['statusInList'] == 'approved': o['use'] = 'available'                                     # жодне джерело не показує договору
    else: o['use'] = 'inactive'
    if o['use'] == 'conflict': f.append('status_conflict')
    if o['lease_match'] == 'address' or (o['area_city'] and not o['totalArea']): f.append('area_mismatch')
    if o['use'] in ('available', 'check') and age > CFG['long_vacant_days'] and not comp: f.append('long_vacant')
    if o['n_unsucc'] >= CFG['repeat_unsuccessful_min']: f.append('repeat_unsucc')
    o['flags'] = f
    o['auc_flags'] = sorted({k for p in ps for k in p['flags']})
    o['score'] = sum(RULES[k]['w'] for k in f) + max([p['score'] for p in ps], default=0)
    o['vacant_days'] = age if o['use'] in ('available', 'check') else None
    o['analog'] = analog(o['totalArea'] or 0)
    o['lost_year'] = round((o['totalArea'] or 0) * o['analog'] * 12) if o['use'] == 'available' else 0

for x in leases:
    f = []
    if x['term'] and x['term'] < '2026-06-30': f.append('term_expired')
    if x['rent_type'] == 'symbolic': f.append('symbolic_rent')
    if x['rent_type'] == 'zero': f.append('zero_rent')
    if x['rent_type'] != 'none' and not x['contract_no']: f.append('no_contract_no')
    if x['contract_date'] and x['term']:
        cd = '-'.join(reversed(x['contract_date'].split('.')))
        if x['term'] < cd: f.append('date_conflict')
    if x['rate'] and x['commercial'] and x['rate'] < CFG['low_rate_ratio'] * analog(x['area']): f.append('low_rate')
    x['flags'] = f
    x['score'] = sum(RULES[k]['w'] for k in f)

# ---------- reconciliation & data defects ----------
inlist = {o['ocid'] for o in O}
extra = [a for a in A if a['ocid'] not in inlist]
defects = []
def defect(src, rid, kind, desc, action):
    defects.append({'dataset': src, 'record': rid, 'defect': kind, 'description': desc, 'action': action})
for o in O:
    if not o['lat']: defect('Prozorro.Продажі', o['ocid'], 'Немає координат', o['addr'], 'Геокодувати за адресою')
    if not o['district']: defect('Prozorro.Продажі', o['ocid'], 'Не вказано район', o['addr'], 'Додати район у картку об’єкта')
    if o['lease_match'] == 'none' and o['statusInList'] == 'sold': defect('Звірка P3-01 ↔ перелік договорів', o['ocid'], 'Орендований об’єкт без договору в переліку міста', o['addr'], 'Ручна перевірка')
    if 'area_mismatch' in o['flags']: defect('Звірка Prozorro ↔ перелік договорів', o['ocid'], 'Площа різниться між джерелами', f"{o['addr']}: Prozorro {o['totalArea']} м², перелік міста {o['area_city']} м²", 'Звірити площу за технічною документацією')
    if o['use'] == 'conflict': defect('Звірка Prozorro ↔ перелік договорів', o['ocid'], 'Статус «включено до переліку», але є чинний договір', o['addr'], 'Оновити статус у Prozorro або пояснити')
    if not o['inv']: defect('Звірка P3-01 ↔ інвентар', o['ocid'], 'Адреси немає в переліку нежитлових об’єктів', o['addr'], 'Перевірити облік об’єкта')
for a in extra:
    defect('Звірка P3-01 ↔ Prozorro.Продажі', a['ocid'], f"Об’єкт орендодавця 13967034 відсутній у наборі міста (статус {a['statusInList']})", a['title'] or '', 'Додати до набору або пояснити виключення')
for x in leases:
    if not x['inv']: defect('Перелік договорів ↔ інвентар', f"№{x['n']}", 'Адреси договору немає в інвентарі', x['address'], 'Перевірити облік об’єкта')
    if 'date_conflict' in x['flags']: defect('Перелік договорів', f"№{x['n']}", 'Строк дії раніше дати договору', x['address'], 'Виправити дату')
    if x['rent_type'] == 'none': defect('Перелік договорів', f"№{x['n']}", 'Рядок без орендаря, договору і плати', x['address'], 'Уточнити статус приміщення')
    if 'no_contract_no' in x['flags']: defect('Перелік договорів', f"№{x['n']}", 'Договір без номера', x['address'], 'Додати номер договору')
seen = collections.defaultdict(list)
for i in inv: seen[i['key']].append(i['n'])
for k, v in seen.items():
    if len(v) > 1: defect('Перелік нежитлових об’єктів', ','.join(f'№{n}' for n in v), 'Дублікат адреси', inv[v[0]-1]['address'], 'Видалити дублікат')
for i in inv:
    if 'Диканський' in i['address']: defect('Перелік нежитлових об’єктів', f"№{i['n']}", 'Неактуальний район (ліквідовано 2020)', i['address'], 'Оновити адресу')
    if 'Бащар' in i['address']: defect('Перелік нежитлових об’єктів', f"№{i['n']}", 'Описка в назві вулиці', i['address'], 'Виправити на «Новий Базар»')
for a, ar, s in PRIV:
    if not any(kmatch(norm(a), i['key']) for i in inv): defect('Перелік приватизації ↔ інвентар', a, 'Об’єкт приватизації відсутній в інвентарі', a, 'Перевірити облік')
titles = collections.Counter()
defect('P3-01 listProzorroSales', 'усі 553', 'Лише 3 поля (ocid, title, url)', 'Немає адреси, площі, статусу, балансоутримувача', 'Публікувати збагачений набір (експорт RentMap)')
defect('P3-01 listProzorroSales', 'усі 553', 'Неоднорідні url', '299 з «/» в кінці, 250 без, 4 з «planning//»', 'Формувати url за шаблоном з ocid')
defect('P3-01 listProzorroSales', '16 варіантів', 'Неінформативні назви', 'Регістр, пробіли, описка «нежитові»', 'Брати тип і адресу з Prozorro')
defect('Портал відкритих даних Полтави', 'e1aad732-4eee-4e41-9737-0cd73fc9edd8', 'Назва набору не відповідає вмісту', 'Набір «Перелік об’єктів… що передані в оренду (з даними про умови передачі)» містить лише listProzorroSales.xlsx з 3 полями', 'Додати умови оренди або виправити назву')
defect('Звіт управління за І півріччя 2026', '573 договори', 'Розбіжність кількості договорів', '573 «укладено (продовжено)» проти 554 у переліку на 30.06.2026', 'Пояснити різницю')

# ---------- summary ----------
comp = [p for p in P if p['status'] == 'complete']
S = {
  'fetched': d['fetched'][:16].replace('T', ' '),
  'n_obj': len(O), 'n_obj_all': len(A), 'n_extra': len(extra), 'extra_status': collections.Counter(a['statusInList'] for a in extra),
  'status': collections.Counter(o['statusInList'] for o in O), 'area_total': round(sum(o['totalArea'] or 0 for o in O), 1),
  'area_by_status': {s: round(sum(o['totalArea'] or 0 for o in O if o['statusInList'] == s), 1) for s in ('sold', 'approved', 'inactive')},
  'n_proc': len(P), 'proc_status': collections.Counter(p['status'] for p in P), 'obj_with_proc': len({p['ocid'] for p in P}),
  'one_bidder_share': round(100 * sum(p['nBids'] == 1 for p in comp) / len(comp)), 'n_complete': len(comp),
  'n_leases': len(leases), 'lease_sum': round(sum(x['rent_month'] or 0 for x in leases if x['rent_type'] == 'paid')),
  'lease_area': round(sum(x['area'] or 0 for x in leases), 1),
  'lease_types': collections.Counter(x['rent_type'] for x in leases), 'expired': sum('term_expired' in x['flags'] for x in leases),
  'n_inv': len(inv), 'inv_no_lease': sum(1 for i in inv if not any(i['n'] in x['inv'] for x in leases)),
  'lease_inv_match': sum(1 for x in leases if x['inv']), 'obj_lease': collections.Counter(o['lease_match'] for o in O),
  'obj_inv': sum(1 for o in O if o['inv']), 'use': collections.Counter(o['use'] for o in O), 'area_by_use': {u: round(sum(o['totalArea'] or 0 for o in O if o['use'] == u), 1) for u in ('leased','conflict','check','available','inactive')}, 'lost_year': sum(o['lost_year'] for o in O), 'med': MED, 'allmed': ALLMED,
  'report_contracts': 573, 'report_income_h1': 9858767,
  'flag_counts': {k: sum(k in p['flags'] for p in P) + sum(k in o['flags'] for o in O) + sum(k in x['flags'] for x in leases) for k in RULES},
  'years': collections.Counter(o['ocid'][10:14] for o in O), 'n_defects': len(defects), 'cfg': CFG,
}

# ---------- export ----------
def r2(v): return round(v, 2) if isinstance(v, float) else v
def fl(v):
    try: return round(float(v), 5)
    except Exception: return None
objs = [{k: (o[k] if k in ('lat','lng') else r2(o[k])) for k in ('ocid','statusInList','use','addr','district','lat','lng','totalArea','condition','locationInBuilding','datePublished','n_auc','n_unsucc','last_rate','last_award','last_period','first_auc','first_contract','days_to_auc','days_to_contract','list_type','lease','lease_match','lease_cands','area_city','inv','priv','flags','auc_flags','score','vacant_days','analog','lost_year','nContracts','leaseDuration')} | {
    'owner': ORGS.get(o['propertyOwnerId'], o['propertyOwnerId']), 'governer': ORGS.get(o['governerId'], o['governerId']), 'owner_id': o['propertyOwnerId']} for o in O]
procs = [{k: r2(p[k]) for k in ('auctionId','ocid','status','method','datePublished','auctionDate','startValue','awardValue','nBids','minimalStep','previousAuctionId','listType','contractStatus','contractValue','dateSigned','leaseDuration','valuePeriod','rate','flags','score','winner_pub')} for p in P]
lz = [{k: r2(x[k]) for k in ('n','page','section','address','area','tenant_pub','tenant_person','contract_no','contract_date','term','purpose','rent_type','rent_month','rate','commercial','inv','objs','flags','score')} for x in leases]
invo = [{'n': i['n'], 'address': i['address'], 'leases': [x['n'] for x in leases if i['n'] in x['inv']], 'objs': [o['ocid'] for o in O if i['n'] in o['inv']]} for i in inv]
extra_o = [{'ocid': a['ocid'], 'status': a['statusInList'], 'title': a['title'], 'area': a['totalArea'], 'datePublished': a['datePublished'],
            'lat': fl(a['latlng'][0]) if a['latlng'] else None, 'lng': fl(a['latlng'][1]) if a['latlng'] else None,
            'owner': ORGS.get(a['propertyOwnerId'], a['propertyOwnerId'])} for a in extra]
priv = [{'address': a, 'area': ar, 'status': s, 'in_inv': any(kmatch(norm(a), i['key']) for i in inv)} for a, ar, s in PRIV]
# Завершені аукціони малої приватизації Управління (для калькулятора доходу громади)
_ps = os.path.join(BASE, 'privatization_sales.json')
PRIVSALES = json.load(open(_ps, encoding='utf-8')) if os.path.exists(_ps) else {'rows': []}
S['report_priv_h1'] = 1894090  # звіт Управління майном за І півріччя 2026: надходження від приватизації
out = {'summary': S, 'rules': RULES, 'objects': objs, 'procedures': procs, 'leases': lz, 'inventory': invo, 'extra': extra_o, 'privatization': priv, 'privsales': PRIVSALES, 'defects': defects}
json.dump(out, open(os.path.join(BASE, 'data.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
with open(os.path.join(ROOT, 'data-defects.csv'), 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['dataset', 'record', 'defect', 'description', 'action']); w.writeheader(); w.writerows(defects)
print(json.dumps(S, ensure_ascii=False, indent=0, default=str)[:4000])
