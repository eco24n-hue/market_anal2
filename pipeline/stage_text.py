"""ingest.py 가 만든 catalog.json 의 PDF를 텍스트로 바꿔 분석 단계 입력 폴더에 놓는다.

파일명 규칙: 기초서류__<회사>__<개정일>__<상품명>__<문서종류>.txt  (segment.py 가 이 이름을 읽는다)
같은 sha256 은 다시 변환하지 않는다.

사용:
  python3 pipeline/stage_text.py --state state/ --out work/txt [--since 20260901] [--companies 신한라이프,미래에셋생명]
"""
import argparse, json, os, re, subprocess, shutil, sys
from pathlib import Path


def safe(s): return re.sub(r'[\\/:*?"<>|]', '_', s)[:100]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--state', default='state'); ap.add_argument('--out', default='work/txt')
    ap.add_argument('--since', default='', help='이 날짜에 유효했던 판과 그 이후 판만 (YYYYMMDD)')
    ap.add_argument('--companies', default='', help='쉼표로 구분한 회사명. 비우면 전체')
    a = ap.parse_args(argv)
    if not shutil.which('pdftotext'):
        raise SystemExit('pdftotext 가 필요합니다. Mac: brew install poppler')
    cat = json.loads((Path(a.state) / 'catalog.json').read_text('utf-8'))
    root = Path(cat['docs_root']); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    done_p = Path(a.state) / 'stage_done.json'
    done = json.loads(done_p.read_text('utf-8')) if done_p.exists() else {}
    cos = {c for c in a.companies.split(',') if c}
    # 회사·상품·문서별로 기준일 이후 판 전부 + 기준일 직전의 최신 판(기준일에 유효했던 판)을 남긴다
    keep = set()
    groups = {}
    for f in cat['files']:
        groups.setdefault((f['company'], f['product'], f['doc_type']), []).append(f)
    for fs in groups.values():
        before = [f for f in fs if a.since and f['edition'] < a.since]
        if before:
            last = max(f['edition'] for f in before)
            keep.update(id(f) for f in before if f['edition'] == last)
        keep.update(id(f) for f in fs if not a.since or f['edition'] >= a.since)
    n = 0
    for f in cat['files']:
        if cos and f['company'] not in cos: continue
        if id(f) not in keep: continue
        name = f"기초서류__{f['company']}__{f['edition']}__{safe(f['product'])}__{f['doc_type']}.txt"
        key = f"{f['sha256']}|{name}"
        if done.get(key) and (out / name).exists(): continue
        r = subprocess.run(['pdftotext', '-layout', str(root / f['path']), str(out / name)], capture_output=True)
        if r.returncode != 0:
            print(f"[실패] {f['path']}: {r.stderr.decode('utf-8', 'ignore')[:200]}", file=sys.stderr); continue
        done[key] = True; n += 1
    done_p.write_text(json.dumps(done, ensure_ascii=False, indent=1), 'utf-8')
    print(f'텍스트 변환 {n}개 → {out}')


if __name__ == '__main__':
    main()
