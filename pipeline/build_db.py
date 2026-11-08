"""급부 행 + 담보 판정 → 주차별 스냅샷 DB(SQLite)와 엑셀."""
import json, sys, re, sqlite3, collections as C
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
S, SNAP, OUTDB, OUTX = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
R = json.load(open(S + '/rows_all.json')); M = json.load(open(S + '/cls_map.json'))
HANA = json.load(open(S + '/rows_hana.json')) if len(sys.argv) > 5 and sys.argv[5] == '--with-hana' else []
def uw_product(co, p):
    if co == '하나생명':
        return ['간편심사 3.10.5'] if '라이트' in p else (['간편심사 3.0.5~3.10.5'] if '간편' in p else ['일반심사'])
    if co == '신한라이프':
        if '라이트원' in p: return ['간편심사 3.10.5']
        if '슈퍼원' in p: return ['일반심사']
        return ['일반심사', '간편심사 3N5']
    if '3.10.5' in p: return ['간편고지 3.10.5']
    if '355' in p: return ['간편고지 3.5.5(고혈압·당뇨)']
    if '간편고지' in p: return ['간편고지']
    return ['일반심사']
def uw_rider(co, p, rider):
    opts = uw_product(co, p)
    if len(opts) == 1: return opts[0]
    return '간편심사 3N5' if re.match(r'^\((간편|간편N)\)', rider or '') else '일반심사'
COS = ['신한라이프', '미래에셋생명'] + (['하나생명'] if HANA else [])
for r in R:
    m = M.get(r['sig'], {})
    for k in ('major', 'standard', 'detail', 'disease_group', 'pay_form', 'basis'): r[k] = m.get(k, '')
    r['uw'] = uw_rider(r['company'], r['product'], r['rider']); r['snapshot'] = SNAP
for r in HANA: r['uw'] = r['uw_fixed']; r['snapshot'] = SNAP
R = R + HANA
def red(r):
    if r.get('reduce_months') not in (None, '') and r.get('reduce_pct') not in (None, ''):
        mo = int(float(r['reduce_months'])); p = f"{mo//12}년" if mo % 12 == 0 else f"{mo}개월"
        return f"{p} 미만 {float(r['reduce_pct']):g}%"
    return '경과기간별 차등' if r.get('reduce_raw') else '없음'
def exm(r):
    d = r.get('exempt_days')
    if d not in (None, '') and float(d) > 0: return f"{float(d):g}일"
    if d in (0, 0.0, '0'): return '없음'
    return '원문 참조' if r.get('exempt_raw') else '미기재'
def amt(r):
    p = r.get('amount_pct')
    return (f"{float(p):g}%" if p not in (None, '') else (r.get('amount_raw') or '')[:40]) + (f" / {r['amount_unit']}" if r.get('amount_unit') else '')
def cnt(r): return r.get('count_code') + (f" ({r['count_limit'][:40]})" if r.get('count_limit') and r['count_code'] not in ('최초1회',) else '')
def rep(vals):
    c = C.Counter(v for v in vals if v); 
    if not c: return ''
    top, _ = c.most_common(1)[0]; return top + (f" 외 {len(c)-1}" if len(c) > 1 else '')
for r in R: r['_amt'], r['_cnt'], r['_red'], r['_exm'] = amt(r), cnt(r), red(r), exm(r)
det = C.OrderedDict()
for r in sorted(R, key=lambda r: (r['major'], r['standard'], r['detail'])):
    d = det.setdefault(r['detail'], dict(major=r['major'], std=r['standard'], detail=r['detail'], group=r['disease_group'], form=r['pay_form'],
        event=r['event'], definition=r['definition'], kcd=r.get('kcd', ''), refs=', '.join(r.get('class_refs') or []), basis=r['basis'], by=C.defaultdict(list)))
    d['by'][r['company']].append(r)
UWS = sorted({u for co in COS for p in {r['product'] for r in R if r['company'] == co} for u in uw_product(co, p)})
# SQLite
con = sqlite3.connect(OUTDB); cur = con.cursor()
cur.executescript('''
create table if not exists benefit_row(snapshot text, company text, product text, start text, rider text, uw text, benefit text, event text,
  major text, standard text, detail text, target text, definition text, class_refs text, kcd text, amount_raw text, amount_pct real, amount_unit text,
  count_code text, count_limit text, reduce_raw text, reduce_months real, reduce_pct real, exempt_raw text, exempt_days real, exempt_base text,
  wait_raw text, exclusions text, source text, confidence text, verify_status text, cluster text, member_hash text);
create table if not exists coverage_master(snapshot text, major text, standard text, detail text, disease_group text, pay_form text, event text, definition text, kcd text, class_refs text, basis text);
create table if not exists underwriting_master(snapshot text, uw text);
''')
cur.execute('delete from benefit_row where snapshot=?', (SNAP,)); cur.execute('delete from coverage_master where snapshot=?', (SNAP,)); cur.execute('delete from underwriting_master where snapshot=?', (SNAP,))
cur.executemany('insert into benefit_row values (' + ','.join('?' * 33) + ')', [(SNAP, r['company'], r['product'], r['start'], r['rider'], r['uw'], r['benefit'], r['event'], r['major'], r['standard'], r['detail'], r['target'], r['definition'], ', '.join(r.get('class_refs') or []), r.get('kcd', ''), r.get('amount_raw', ''), r.get('amount_pct'), r.get('amount_unit', ''), r.get('count_code', ''), r.get('count_limit', ''), r.get('reduce_raw', ''), r.get('reduce_months'), r.get('reduce_pct'), r.get('exempt_raw', ''), r.get('exempt_days'), r.get('exempt_base', ''), r.get('wait_raw', ''), r.get('exclusions', ''), r.get('source', ''), r.get('confidence', ''), r['status'], r['cluster'], r['member_hash']) for r in R])
cur.executemany('insert into coverage_master values (?,?,?,?,?,?,?,?,?,?,?)', [(SNAP, d['major'], d['std'], d['detail'], d['group'], d['form'], d['event'], d['definition'], d['kcd'], d['refs'], d['basis']) for d in det.values()])
cur.executemany('insert into underwriting_master values (?,?)', [(SNAP, u) for u in UWS]); con.commit(); con.close()
# Excel
wb = Workbook(); H = PatternFill('solid', fgColor='1D5C74'); HF = Font(bold=True, color='FFFFFF'); thin = Side(style='thin', color='D9DEE3'); BD = Border(top=thin, bottom=thin, left=thin, right=thin)
OK = PatternFill('solid', fgColor='E2F2E9'); NO = PatternFill('solid', fgColor='F6E4E1')
def sheet(ws, hdr, rows, widths, freeze='D2'):
    ws.append(hdr)
    for c in ws[1]: c.fill = H; c.font = HF; c.alignment = Alignment(vertical='center', wrap_text=True)
    for r in rows: ws.append(r)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.border = BD; c.alignment = Alignment(vertical='top', wrap_text=True)
            if c.value == 'O': c.fill = OK
            elif c.value == 'X': c.fill = NO
    for i, w in enumerate(widths, 1): ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = freeze; ws.auto_filter.ref = ws.dimensions
ws = wb.active; ws.title = 'README'
for line in [[f'건강보험 표준·세부담보 DB — 스냅샷 {SNAP}'], [],
    ['범위', '신한라이프 6상품(20260804·20260901판), 미래에셋생명 9상품(20260701·20260711판). 2026-09-01에 유효했던 판 기준'],
    ['원천', '각 사 공시실 약관 원문(market_anal2-docs 저장소). 특약별 지급사유·정의·분류표·보험금 지급기준표를 에이전트가 정독하고, 독립 검증 에이전트가 원문과 대조'],
    ['세부담보', '정의와 분류코드 범위가 같으면 회사가 달라도 같은 세부담보명. 범위가 하나라도 다르면 분리'],
    ['표준담보', '세부담보의 공통 부분(보장사건+질병군+지급형태)'],
    ['대표값', '한 회사 안에 같은 세부담보가 여러 특약·상품에 있으면 가장 많은 값을 쓰고 다른 값이 있으면 "외 n"'],
    ['검증', f"급부 {len(R)}행 중 검증 후 수정 {sum(1 for r in R if r['status']=='corrected')}행 · 원문 확인 {sum(1 for r in R if r['status']=='verified')}행"],
    ['하나생명', '상품요약서(2026.09.01) 기준 파일럿. 약관 미확인이라 분류코드 없음. 약관 확보 후 재검증'],
    ['한계', 'KB·동양·흥국은 Mac 수집 후 추가. 미래에셋 사업방법서·상품요약서는 스캔 이미지라 심사기준은 상품명 기준']]:
    ws.append(line)
ws['A1'].font = Font(bold=True, size=14); ws.column_dimensions['A'].width = 12; ws.column_dimensions['B'].width = 120
it = list(det.values())
sheet(wb.create_sheet('담보마스터'), ['대분류', '표준담보명', '세부담보명', '질병군', '보장사건', '지급형태', '정의(대표 원문)', '분류표 참조', '분류코드', '판정 근거', '보유 회사 수'],
      [[d['major'], d['std'], d['detail'], d['group'], d['event'], d['form'], d['definition'], d['refs'], d['kcd'], d['basis'], len(d['by'])] for d in it], [14, 24, 40, 12, 8, 10, 60, 28, 40, 40, 8])
sheet(wb.create_sheet('심사기준마스터'), ['심사기준', '운영 회사'], [[u, ', '.join(co for co in COS if any(u in uw_product(co, p) for p in {r['product'] for r in R if r['company'] == co}))] for u in UWS], [28, 40], 'A2')
sheet(wb.create_sheet('보장여부'), ['대분류', '표준담보명', '세부담보명'] + COS + ['보유 회사 수'], [[d['major'], d['std'], d['detail']] + ['O' if co in d['by'] else 'X' for co in COS] + [len(d['by'])] for d in it], [14, 24, 40, 14, 14, 8])
sheet(wb.create_sheet('심사기준 보유'), ['심사기준'] + COS, [[u] + ['O' if any(u in uw_product(co, p) for p in {r['product'] for r in R if r['company'] == co}) else 'X' for co in COS] for u in UWS], [28, 14, 14], 'B2')
def bytab(name, fn, hdr):
    sheet(wb.create_sheet(name), ['대분류', '표준담보명', '세부담보명'] + [f"{co}\n{hdr}" for co in COS], [[d['major'], d['std'], d['detail']] + [rep([fn(x) for x in d['by'][co]]) if co in d['by'] else 'X' for co in COS] for d in it], [14, 24, 40, 30, 30])
sheet(wb.create_sheet('지급금액·횟수'), ['대분류', '표준담보명', '세부담보명'] + [f"{co}\n{k}" for co in COS for k in ('지급금액', '지급횟수')],
      [[d['major'], d['std'], d['detail']] + [v for co in COS for v in ((rep([x['_amt'] for x in d['by'][co]]), rep([x['_cnt'] for x in d['by'][co]])) if co in d['by'] else ('X', '–'))] for d in it], [14, 24, 40, 26, 22, 26, 22])
bytab('면책', lambda x: x['_exm'], '면책')
bytab('감액', lambda x: x['_red'], '감액')
bytab('대기기간', lambda x: (x.get('wait_raw') or '없음')[:60], '대기·지급요건')
F = ['snapshot', 'company', 'product', 'start', 'uw', 'rider', 'benefit', 'major', 'standard', 'detail', 'event', 'target', 'definition', 'kcd', 'amount_raw', 'amount_pct', 'amount_unit', 'count_code', 'count_limit', 'reduce_raw', 'reduce_months', 'reduce_pct', 'exempt_raw', 'exempt_days', 'wait_raw', 'exclusions', 'source', 'status']
K = ['기준일', '회사', '상품', '판 개시일', '심사기준', '특약명', '급부명', '대분류', '표준담보명', '세부담보명', '보장사건', '보장대상', '정의', '분류코드', '지급금액 원문', '지급률(%)', '지급단위', '지급횟수', '한도', '감액 원문', '감액기간(월)', '감액지급률(%)', '면책 원문', '면책일수', '대기·지급요건', '지급제한', '근거 조항', '검증']
sheet(wb.create_sheet('상품별 세부담보'), K, [[r.get(f) if not isinstance(r.get(f), list) else ', '.join(r.get(f)) for f in F] for r in sorted(R, key=lambda r: (r['company'], r['product'], r['rider'], r['benefit']))], [10, 12, 30, 10, 14, 34, 26, 12, 20, 30, 8, 26, 40, 26, 26, 8, 12, 10, 16, 26, 8, 8, 26, 8, 26, 26, 14, 10], 'H2')
wb.save(OUTX)
print('details', len(it), 'std', len({d['std'] for d in it}), 'uw', UWS, 'rows', len(R))
