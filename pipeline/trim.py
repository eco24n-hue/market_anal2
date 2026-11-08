"""특약 블록에서 담보 판정에 필요한 조항만 남긴다."""
import re, sys, json, glob, os, hashlib, difflib, collections as C
SEG, OUT = sys.argv[1], sys.argv[2]
ART = re.compile(r'^\s{0,12}(제\s?\d+(?:-\d+)?\s?조(?:의\s?\d+)?)\s*[\(（【]?\s*([^\)）】\n]{0,60})')
KEEP = re.compile(r'지급사유|세부규정|정의|진단|확정|지급하지 않|보장개시|면책|감액|삭감|지급기준|지급금액|보험금의 지급|급여금의 지급|분류|수술|치료|입원|통원|장해|납입면제|보험료 납입의 면제|용어|대상')
DROP = re.compile(r'계약의 성립|청약|철회|해지|보험료의 납입|부활|효력회복|배당|분쟁|관할|소멸시효|약관의 해석|설명의무|준용|계약내용의 변경|보험나이|양도|주소변경|대리인|계약자적립액|해약환급금|적립이율|공시|개인정보|예금자|갱신|중도인출|추가납입|자동대출|위반')
APPX = re.compile(r'^\s*(통합분류표|<\s*부표\s*\d|부표\s*\d+[\-｜|]|\(?별표\s*\d+\)?)')
def trim(text):
    lines = text.split('\n'); out = []; keep = True; intro = True
    for ln in lines:
        m = ART.match(ln)
        if m:
            intro = False; title = m.group(2)
            keep = bool(KEEP.search(title)) and not DROP.search(title)
        elif APPX.match(ln):
            intro = False; keep = True   # 부표·별표(지급기준표, 분류표 등)는 남긴다
        if keep or intro: out.append(ln)
    t = '\n'.join(out)
    return re.sub(r'\n\s*\n(\s*\n)+', '\n\n', t)
U = json.load(open(SEG + '/unique.json')); os.makedirs(OUT, exist_ok=True)
tot = C.Counter()
for u in U:
    t = open(f"{SEG}/u_{u['hash']}.txt", encoding='utf-8').read(); tt = trim(t)
    u['trim_chars'] = len(tt); tot[u['co'] + ' before'] += len(t); tot[u['co'] + ' after'] += len(tt)
    open(f"{OUT}/t_{u['hash']}.txt", 'w', encoding='utf-8').write(tt)
json.dump(U, open(OUT + '/unique.json', 'w'), ensure_ascii=False)
for k, v in sorted(tot.items()): print(k, v // 1000, 'K')
