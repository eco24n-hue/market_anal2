"""benefit_row 테이블을 화면용 집계로 바꾼다(세부담보 × 회사 대표값, 스냅샷 간 변경)."""
from __future__ import annotations

import collections as C
import sqlite3
from functools import lru_cache

COMPANY_ORDER = ["신한라이프", "미래에셋생명", "하나생명", "KB라이프", "동양생명", "흥국생명"]


def red(r):
    if r["reduce_months"] not in (None, "") and r["reduce_pct"] not in (None, ""):
        mo = int(float(r["reduce_months"])); p = f"{mo // 12}년" if mo % 12 == 0 else f"{mo}개월"
        return f"{p} 미만 {float(r['reduce_pct']):g}%"
    return "경과기간별 차등" if r["reduce_raw"] else "없음"


def exm(r):
    d = r["exempt_days"]
    if d not in (None, "") and float(d) > 0: return f"{float(d):g}일"
    if d is not None and d != "" and float(d) == 0: return "없음"
    return "원문 참조" if r["exempt_raw"] else "미기재"


def amt(r):
    p = r["amount_pct"]
    s = f"{float(p):g}%" if p not in (None, "") else (r["amount_raw"] or "")[:30]
    return s + (f" / {r['amount_unit']}" if r["amount_unit"] else "")


def cnt(r):
    return (r["count_code"] or "") + (f" ({r['count_limit'][:30]})" if r["count_limit"] and r["count_code"] != "최초1회" else "")


def wait(r):
    return (r["wait_raw"] or "없음")[:50]


def rep(vals):
    c = C.Counter(v for v in vals if v)
    if not c: return ""
    top, _ = c.most_common(1)[0]
    return top + (f" 외 {len(c) - 1}" if len(c) > 1 else "")


def connect(db_path: str):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def snapshots(con):
    return [r[0] for r in con.execute("select distinct snapshot from benefit_row order by snapshot desc")]


@lru_cache(maxsize=16)
def coverage_table(db_path: str, snapshot: str):
    """세부담보마다 회사별 대표값을 모은다."""
    con = connect(db_path)
    rows = con.execute("select * from benefit_row where snapshot=? order by major, standard, detail", (snapshot,)).fetchall()
    companies = [c for c in COMPANY_ORDER if any(r["company"] == c for r in rows)] + sorted({r["company"] for r in rows} - set(COMPANY_ORDER))
    det = C.OrderedDict()
    for r in rows:
        d = det.setdefault(r["detail"], {"major": r["major"], "standard": r["standard"], "detail": r["detail"], "definition": "", "kcd": "", "by": C.defaultdict(list)})
        if not d["definition"] or (r["company"] != "하나생명" and not d["kcd"]):
            d["definition"] = d["definition"] or (r["definition"] or "")[:220]
            if r["kcd"]: d["kcd"] = (r["kcd"] or "")[:160]
        d["by"][r["company"]].append(r)
    items = []
    for d in det.values():
        by = {}
        for co, rs in d["by"].items():
            by[co] = {"amount": rep([amt(x) for x in rs]), "count": rep([cnt(x) for x in rs]), "exempt": rep([exm(x) for x in rs]),
                      "reduce": rep([red(x) for x in rs]), "wait": rep([wait(x) for x in rs]),
                      "products": len({x["product"] for x in rs}), "uw": sorted({x["uw"] for x in rs if x["uw"]}),
                      "riders": sorted({x["rider"] for x in rs})[:12]}
        items.append({k: d[k] for k in ("major", "standard", "detail", "definition", "kcd")} | {"by": by})
    products = C.OrderedDict()
    for r in rows: products.setdefault((r["company"], r["product"]), set()).add(r["uw"])
    con.close()
    return {"snapshot": snapshot, "companies": companies, "items": items,
            "products": [{"company": c, "product": p, "uw": sorted(u)} for (c, p), u in products.items()],
            "underwriting": sorted({u for (_, _), us in products.items() for u in us if u}),
            "rows": len(rows)}


def diff(db_path: str, old: str, new: str):
    """두 스냅샷 사이의 회사별 담보 변화(신설·폐지·조건 변경)."""
    a, b = coverage_table(db_path, old), coverage_table(db_path, new)
    ia = {i["detail"]: i for i in a["items"]}; ib = {i["detail"]: i for i in b["items"]}
    out = []
    for det in sorted(set(ia) | set(ib)):
        ca = ia.get(det, {}).get("by", {}); cb = ib.get(det, {}).get("by", {})
        for co in sorted(set(ca) | set(cb)):
            if co in cb and co not in ca:
                out.append({"company": co, "detail": det, "change": "신설", "field": "", "before": "", "after": ""})
            elif co in ca and co not in cb:
                out.append({"company": co, "detail": det, "change": "폐지", "field": "", "before": "", "after": ""})
            else:
                for f, label in (("amount", "지급금액"), ("count", "지급횟수"), ("exempt", "면책"), ("reduce", "감액"), ("wait", "대기")):
                    if ca[co][f] != cb[co][f]:
                        out.append({"company": co, "detail": det, "change": "조건 변경", "field": label, "before": ca[co][f], "after": cb[co][f]})
    return out
