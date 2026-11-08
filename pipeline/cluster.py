"""이름 기준으로 같은 특약 계열을 묶고, 대표 본문 + 나머지의 차이만 남긴다."""
import re, sys, json, difflib, collections as C, os
TR, OUT = sys.argv[1], sys.argv[2]
U = json.load(open(TR + '/unique.json'))
def base(name):
    s = name or ''
    s = re.sub(r'^\((N|간편|간편N)\)', '', s)
    s = re.sub(r'\((?:무배당|갱신형|해약환급금 ?미지급형|[0-9.]+ ?간편고지|355간편고지 ?고당|간편고지)(?:, ?[^()]*)?\)', '', s)
    s = re.sub(r'(특약)D', r'\1', s); s = re.sub(r'\s+|무배당', '', s)
    return s
def lines(h):
    t = open(f"{TR}/t_{h}.txt", encoding='utf-8').read()
    return [re.sub(r'\s+', ' ', l).strip() for l in t.split('\n') if l.strip()]
fam = C.defaultdict(list)
for u in U: fam[(u['co'], base(u['rider']))].append(u)
os.makedirs(OUT, exist_ok=True); clusters = []; tot = C.Counter()
for (co, b), us in fam.items():
    us = sorted(us, key=lambda u: -len(u['products']))
    rep = us[0]; rl = lines(rep['hash']); body = '\n'.join(rl)
    diffs = []
    for u in us[1:]:
        d = [l for l in difflib.unified_diff(rl, lines(u['hash']), lineterm='', n=0) if not l.startswith(('---', '+++'))]
        diffs.append(dict(hash=u['hash'], rider=u['rider'], products=u['products'], diff='\n'.join(d)))
    cid = f"c{len(clusters):04d}"
    clusters.append(dict(id=cid, co=co, base=b, rep=rep['hash'], rep_rider=rep['rider'], rep_products=rep['products'],
                         members=[dict(hash=x['hash'], rider=x['rider'], products=x['products']) for x in us],
                         chars=len(body) + sum(len(x['diff']) for x in diffs)))
    with open(f"{OUT}/{cid}.txt", 'w', encoding='utf-8') as f:
        f.write(f"#### 대표 특약: {rep['rider']}\n#### 대표 본문 해시: {rep['hash']} / 수록 상품: {', '.join(rep['products'])}\n\n{body}\n")
        for x in diffs:
            f.write(f"\n\n#### 변형 특약: {x['rider']} (해시 {x['hash']}) / 수록 상품: {', '.join(x['products'])}\n#### 대표 본문과의 차이(- 대표에만, + 이 특약에만):\n{x['diff'] or '(차이 없음)'}\n")
    tot[co] += clusters[-1]['chars']; tot[co + ' n'] += 1
json.dump(clusters, open(OUT + '/clusters.json', 'w'), ensure_ascii=False)
for k, v in sorted(tot.items()): print(k, v if k.endswith(' n') else f"{v//1000}K")
