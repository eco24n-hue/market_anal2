"""추출·검증 결과를 합쳐 상품·특약별 급부 행으로 펼친다."""
import json, sys, copy, collections as C
S = sys.argv[1]; files = sys.argv[2:]
clusters = {c['id']: c for c in json.load(open(S + '/clu/clusters.json'))}
blocks = json.load(open(S + '/seg/blocks_index.json'))
by_hash = C.defaultdict(list)
for b in blocks: by_hash[b['hash']].append(b)
res, stat = {}, C.Counter()
for f in files:
    for b in json.load(open(f)):
        if not b: continue
        ex = {c['cluster_id']: c for c in b['extract']['clusters']}
        ver = {c['cluster_id']: c for c in (b.get('verify') or {}).get('clusters', [])}
        for cid, c in ex.items():
            v = ver.get(cid)
            if v and v.get('verdict') == 'corrected' and v.get('corrected', {}).get('rep_rows') is not None:
                res[cid] = (v['corrected'], 'corrected', v.get('corrections', [])); stat['corrected'] += 1
            elif v:
                res[cid] = (c, 'verified', v.get('corrections', [])); stat['verified'] += 1
            else:
                res[cid] = (c, 'unverified', []); stat['unverified'] += 1
NUM = {'amount_pct', 'reduce_months', 'reduce_pct', 'exempt_days'}
rows, issues = [], []
for cid, (c, status, corr) in res.items():
    meta = clusters.get(cid)
    if not meta: issues.append(f'{cid}: 묶음 정보 없음'); continue
    base = c.get('rep_rows', [])
    var = {v['hash']: v['overrides'] for v in c.get('variants', [])}
    for m in meta['members']:
        rs = copy.deepcopy(base)
        if m['hash'] != meta['rep']:
            for o in var.get(m['hash'], []):
                if o['op'] == 'remove_row':
                    rs = [r for r in rs if r['benefit'] != o['benefit']]
                elif o['op'] == 'add_row':
                    try: rs.append(json.loads(o['value']))
                    except Exception: issues.append(f"{cid}/{m['hash']}: add_row 파싱 실패")
                elif o['op'] == 'set':
                    hit = rs if (o['benefit'].strip().startswith('*') or o['benefit'].strip() in ('전체', 'ALL', '모든 급부')) else [r for r in rs if r['benefit'] == o['benefit']]
                    if not hit:
                        import re as _re
                        nb = lambda s: _re.sub(r'\([^)]*\)|\s|\*', '', s)
                        key = nb(o['benefit']); hit = [r for r in rs if nb(r['benefit']) == key or (key and nb(r['benefit']).startswith(key)) or (key and key.startswith(nb(r['benefit'])) and nb(r['benefit']))]
                    if not hit: issues.append(f"{cid}/{m['hash']}: set 대상 없음 {o['benefit']}"); continue
                    val = o['value']
                    if o['field'] in NUM:
                        try: val = None if val in ('', 'null', 'None') else float(val)
                        except ValueError: pass
                    for r in hit: r[o['field']] = val
        for bl in by_hash.get(m['hash'], []):
            for r in rs:
                rows.append(dict(company=bl['co'], start=bl['start'], product=bl['product'], rider=bl['rider'] or m['rider'],
                                 cluster=cid, member_hash=m['hash'], status=status, **r))
json.dump(rows, open(S + '/rows_all.json', 'w'), ensure_ascii=False)
json.dump(issues, open(S + '/assemble_issues.json', 'w'), ensure_ascii=False)
print(stat, 'rows', len(rows), 'issues', len(issues))
print(C.Counter((r['company'], r['status']) for r in rows))
