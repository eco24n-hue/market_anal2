"""약관 텍스트를 특약 블록으로 분할하고 본문 기준으로 중복을 묶는다."""
import re, sys, glob, json, hashlib, collections as C, os
T, OUT = sys.argv[1], sys.argv[2]
MIRAE = re.compile(r'^\s*\[([A-Z0-9]{3,})_D(\d{2})_(\d{8})\]\s*$')
SH_FOOT = re.compile(r'^\s*(\d{12,})\s{2,}(.+?)\s{2,}(\d{1,4})\s*$')
MIRAE_FOOT = re.compile(r'^\s*\d{1,4}\s+Mirae Asset Life Insurance\s*$')
def norm(s, name):
    s = s.replace(name, '')
    s = re.sub(r'\((?:무배당|갱신형|해약환급금 ?미지급형|[0-9.]+ ?간편고지|355간편고지 ?고당|간편고지|간편심사형|[^()]*간편[^()]*)(?:,[^()]*)?\)', '', s)
    s = re.sub(r'[ⅠⅡⅢⅣ]|\s+|\d{12,}', '', s)
    return s
blocks = []
for f in sorted(glob.glob(T + "/*약관.txt")):
    parts = os.path.basename(f).split('__'); co, start, prod = parts[1], parts[2], parts[3]
    if co not in ('미래에셋생명', '신한라이프'):
        # 특약 경계 표지가 회사마다 달라서, 규칙을 만든 회사만 나눈다
        print(f'[건너뜀] {co}: 특약 분할 규칙 없음 ({os.path.basename(f)[:60]})', file=sys.stderr)
        continue
    pages = open(f, encoding='utf-8').read().split('\f')
    cur, buf = None, []
    def flush():
        if cur and buf:
            blocks.append(dict(co=co, start=start, product=prod, rider=cur[1], code=cur[0], text='\n'.join(buf)))
    for pg in pages:
        lines = pg.split('\n')
        if co == '미래에셋생명':
            for ln in lines:
                m = MIRAE.match(ln)
                if m:
                    flush(); cur = (m.group(0).strip(), None); buf = []
                    continue
                if MIRAE_FOOT.match(ln): continue
                if cur and cur[1] is None and ln.strip() and not ln.strip().startswith('['):
                    cur = (cur[0], ln.strip())
                if cur: buf.append(ln)
        else:
            foot = None
            for ln in reversed(lines[-8:] + lines[:4]):
                m = SH_FOOT.match(ln)
                if m and 'SHINHAN' not in m.group(2).upper(): foot = ('', m.group(2).strip()); break
            body = [ln for ln in lines if not SH_FOOT.match(ln)]
            if foot and (cur is None or foot != cur):
                flush(); cur = foot; buf = []
            if cur: buf.extend(body)
    flush()
# 중복 묶기
groups = C.OrderedDict()
for b in blocks:
    h = hashlib.sha1(norm(b['text'], b['rider'] or '').encode()).hexdigest()[:16]
    b['hash'] = h; groups.setdefault(h, []).append(b)
os.makedirs(OUT, exist_ok=True)
json.dump([{k: v for k, v in b.items() if k != 'text'} for b in blocks], open(OUT + '/blocks_index.json', 'w'), ensure_ascii=False)
uniq = []
for h, bs in groups.items():
    b = bs[0]; uniq.append(dict(hash=h, co=b['co'], rider=b['rider'], chars=len(b['text']), members=len(bs),
        products=sorted({x['product'] for x in bs}), riders=sorted({x['rider'] or '' for x in bs})))
    open(f"{OUT}/u_{h}.txt", 'w', encoding='utf-8').write(b['text'])
json.dump(uniq, open(OUT + '/unique.json', 'w'), ensure_ascii=False)
for co in ('미래에셋생명', '신한라이프'):
    bb = [b for b in blocks if b['co'] == co]; uu = [u for u in uniq if u['co'] == co]
    print(co, 'blocks', len(bb), 'unique', len(uu), 'chars all', sum(len(b['text']) for b in bb)//1000, 'K unique', sum(u['chars'] for u in uu)//1000, 'K')
