"""급부 행 + 담보 판정을 새 기준일 스냅샷으로 DB 에 쓴다. 이번에 처리하지 않은 회사는 직전 기준일 행을 그대로 이어받는다.

사용:  python3 pipeline/write_snapshot.py --work work --db data/health_coverage_db.sqlite --snapshot 2026-11-09
"""
import argparse
import json
import re
import sqlite3
from pathlib import Path

COLS = ["snapshot", "company", "product", "start", "rider", "uw", "benefit", "event", "major", "standard", "detail", "target", "definition",
        "class_refs", "kcd", "amount_raw", "amount_pct", "amount_unit", "count_code", "count_limit", "reduce_raw", "reduce_months", "reduce_pct",
        "exempt_raw", "exempt_days", "exempt_base", "wait_raw", "exclusions", "source", "confidence", "verify_status", "cluster", "member_hash"]


def uw_of(co, product, rider):
    """상품명·특약명으로 심사기준을 정한다(사업방법서가 스캔본인 회사가 있어 상품명 기준)."""
    p = product or ""
    if co == "신한라이프":
        if "라이트원" in p: return "간편심사 3.10.5"
        if "슈퍼원" in p: return "일반심사"
        return "간편심사 3N5" if re.match(r"^\((간편|간편N)\)", rider or "") else "일반심사"
    m = re.search(r"(\d\.\d{1,2}\.\d(?:\.\d)?|3N5|355)", p)
    if "간편" in p or m:
        return ("간편고지 " if "고지" in p else "간편심사 ") + (m.group(1) if m else "")
    return "일반심사"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="work"); ap.add_argument("--db", required=True); ap.add_argument("--snapshot", required=True)
    a = ap.parse_args(argv)
    work = Path(a.work)
    rows = json.loads((work / "rows_all.json").read_text("utf-8"))
    cls = json.loads((work / "cls_map.json").read_text("utf-8"))
    con = sqlite3.connect(a.db)
    con.execute(f"create table if not exists benefit_row({', '.join(c + ' text' for c in COLS)})")
    prev = con.execute("select max(snapshot) from benefit_row where snapshot < ?", (a.snapshot,)).fetchone()[0]
    con.execute("delete from benefit_row where snapshot=?", (a.snapshot,))
    done = {r["company"] for r in rows}
    ins, skipped = [], 0
    for r in rows:
        c = cls.get(r["sig"])
        if not c:
            skipped += 1; continue
        v = {**r, **{k: c[k] for k in ("major", "standard", "detail")}, "snapshot": a.snapshot, "verify_status": r.get("status", ""),
             "uw": uw_of(r["company"], r["product"], r["rider"]), "class_refs": ", ".join(r.get("class_refs") or [])}
        ins.append(tuple(v.get(k) for k in COLS))
    con.executemany(f"insert into benefit_row({','.join(COLS)}) values ({','.join('?' * len(COLS))})", ins)
    carried = 0
    if prev:
        q = f"insert into benefit_row({','.join(COLS)}) select ?, {','.join(COLS[1:])} from benefit_row where snapshot=? and company not in ({','.join('?' * len(done))})"
        carried = con.execute(q, (a.snapshot, prev, *done)).rowcount
    con.commit(); con.close()
    print(f"스냅샷 {a.snapshot}: 새로 분석 {len(ins)}행({', '.join(sorted(done))}), 직전({prev}) 이어받음 {carried}행, 판정 없어 제외 {skipped}행")


if __name__ == "__main__":
    main()
