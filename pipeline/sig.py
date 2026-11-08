"""급부 행에 KCD 정규화와 매칭 서명을 붙이고 고유 서명을 센다."""
import json, sys, re, hashlib, collections as C
S = sys.argv[1]; R = json.load(open(S + '/rows_all.json'))
def kcd_norm(s):
    s = (s or '').upper().replace('∼', '~').replace('～', '~').replace('–', '~')
    s = re.sub(r'(?<=[A-Z]\d{2})\s*-\s*(?=[A-Z]\d{2})', '~', s)
    s = re.sub(r'\s+', '', s)
    return s
def refs_norm(rs):
    return '|'.join(sorted(re.sub(r'\s+|&LT;|&GT;|<|>|&lt;|&gt;', '', x) for x in rs or []))
def tgt_norm(s):
    return re.sub(r'\s+|[‘’\'"“”]', '', s or '')
for r in R:
    r['kcd_norm'] = kcd_norm(r.get('kcd'))
    r['refs_norm'] = refs_norm(r.get('class_refs'))
    r['sig'] = hashlib.sha1('|'.join([r['company'] if not r['kcd_norm'] else '', r['event'], r['kcd_norm'], tgt_norm(r['target'])]).encode()).hexdigest()[:12]
json.dump(R, open(S + '/rows_all.json', 'w'), ensure_ascii=False)
U = {}
for r in R:
    U.setdefault(r['sig'], dict(sig=r['sig'], event=r['event'], target=r['target'], kcd=r['kcd'], refs=r.get('class_refs'),
        definition=(r.get('definition') or '')[:260], benefit=r['benefit'], companies=set(), n=0))
    U[r['sig']]['companies'].add(r['company']); U[r['sig']]['n'] += 1
print('rows', len(R), 'unique sigs', len(U), C.Counter(len(u['companies']) for u in U.values()), C.Counter(u['event'] for u in U.values()).most_common())
for u in U.values(): u['companies'] = sorted(u['companies'])
json.dump(list(U.values()), open(S + '/sigs.json', 'w'), ensure_ascii=False)
