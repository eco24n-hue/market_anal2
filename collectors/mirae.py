"""미래에셋생명 공시실 수집기.

공시실(https://life.miraeasset.com/micro/disclosure/) > 상품공시 > 상품목록
(PC-HO-080301-000000.do) 화면이 쓰는 XHR을 그대로 호출한다.

목록 조회 (comExcelDraw.js 의 COMEXCEL.fn_getWorkDvsnDataPaging)
    POST /micro/disclosure/selectWorkDvsnDataPaging.do
        workDvsn=D, text1=판매중인상품|판매중지상품, text2=<상품분류>, text3=<상품명 검색어>, pageNum=0,1,...
    응답 JSON: {"list":[...최대 100행], "rows":총행수, "pageNum":현재쪽(1부터), "totalPage":총쪽수}
    각 행의 jsonData(문자열 JSON)가 표의 한 줄(=한 판)이다.
        판매중인상품: cell0 분류, cell1 상품명, cell2 판매시작일, cell3 판매종료일,
                      cell4 상품요약서, cell5 약관, cell6 사업방법서, cell7 경로
        판매중지상품: cell0 분류, cell1 상품명, cell2 판매시작일, cell3 판매종료일, cell4 최종판매일,
                      cell5 상품요약서, cell6 약관, cell7 사업방법서, cell8 경로
    파일 칸에는 파일명이 들어 있고 여러 개면 줄바꿈(\n)으로 구분된다.
    ※ X-Requested-With: XMLHttpRequest 헤더가 없으면 404 HTML이 온다.

상품분류 목록: POST /micro/disclosure/selectProdDvsnGroup.do (workDvsn=D, text1=판매중인상품)
현재 게시본: POST /micro/disclosure/selectDvsnGroupData.do (workDvsn=D, ignoreUse=1)
    → 공시실 표는 월별 엑셀 업로드본(예: "2026년 08월공시")이라 실제 판매개시보다 늦게 반영된다.

다운로드 (COMUTIL.fileDown)
    POST /micro/cmmnFileDown.do  pathType=gongci_u1, filePath=/uploadwas/life<경로>, fileName=orgFileName=<파일명>
    없는 파일이면 200 + text/html(약 3만 바이트)이 온다.

표가 아직 갱신되지 않은 새 판은 파일명 규칙 `<상품명>_<문서>_<YYYYMMDD>.pdf`로 프로브해 보충한다
(stream=True로 Content-Type만 보고 바로 끊으므로 본문은 받지 않는다).
"""
from __future__ import annotations

import datetime as dt
import json
import re

from common import Doc, Edition, run

COMPANY = "미래에셋생명"
BASE = "https://life.miraeasset.com"
LIST_PAGE = BASE + "/micro/disclosure/product/PC-HO-080301-000000.do"
LIST_URL = BASE + "/micro/disclosure/selectWorkDvsnDataPaging.do"
DVSN_URL = BASE + "/micro/disclosure/selectDvsnGroupData.do"
DOWN_URL = BASE + "/micro/cmmnFileDown.do"
DEFAULT_PATH = "/html/gongci/upload/1/"
XHR = {"X-Requested-With": "XMLHttpRequest", "Referer": LIST_PAGE, "Accept": "application/json, text/javascript, */*; q=0.01"}

SALE, STOP = "판매중인상품", "판매중지상품"
# 판매구분별 칸 배치: (요약서, 약관, 사업방법서, 경로)
CELLS = {SALE: ("cell4", "cell5", "cell6", "cell7"), STOP: ("cell5", "cell6", "cell7", "cell8")}
HEALTH_CATS = ("보장성▷건강/암", "보장성▷간편고지/간편심사")
PROBE_DAYS = ("01", "11")  # 미래에셋 개정판은 주로 1일·11일 개시(예: 20260701, 20260711)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def ymd(s: str) -> str:
    return re.sub(r"\D", "", s or "")[:8]


def _post_json(sess, url, data):
    r = sess.post(url, data=data, headers=XHR, timeout=60)
    r.raise_for_status()
    if "json" not in r.headers.get("Content-Type", ""):
        raise RuntimeError(f"JSON 아님({url}): {r.text[:80]!r}")
    return r.json()


def query_rows(sess, gubun: str, cat: str = "", keyword: str = "") -> list[dict]:
    """상품목록 표를 쪽 단위로 끝까지 읽어 행(jsonData 펼친 dict) 목록을 돌려준다."""
    rows, page = [], 0
    while True:
        d = _post_json(sess, LIST_URL, {"workDvsn": "D", "text1": gubun, "text2": cat, "text3": keyword, "pageNum": page})
        for it in d.get("list") or []:
            m = json.loads(it["jsonData"])
            m["_seq"], m["_title"], m["_gubun"] = it.get("seq"), it.get("title"), gubun
            rows.append(m)
        page += 1
        if not d.get("list") or page >= int(d.get("totalPage") or 0):
            return rows


def current_title(sess) -> str:
    """현재 게시 중인 공시 엑셀 제목(예: '2026년 08월공시')."""
    try:
        g = _post_json(sess, DVSN_URL, {"workDvsn": "D", "ignoreUse": "1"}).get("dvsnGroupData") or []
        return g[0]["TITLE"] if g else ""
    except Exception:
        return ""


def make_doc(doc_type: str, fname: str, path: str = DEFAULT_PATH) -> Doc:
    fpath = "/uploadwas/life" + (path or DEFAULT_PATH)
    return Doc(doc_type=doc_type, source=f"{DOWN_URL} {fpath}{fname}", orig_name=fname,
               fetch={"method": "POST", "url": DOWN_URL,
                      "data": {"pathType": "gongci_u1", "filePath": fpath, "fileName": fname, "orgFileName": fname}})


def row_docs(m: dict) -> list[Doc]:
    s_cell, t_cell, b_cell, p_cell = CELLS[m["_gubun"]]
    path = m.get(p_cell) or DEFAULT_PATH
    docs = []
    for doc_type, cell in (("약관", t_cell), ("사업방법서", b_cell), ("상품요약서", s_cell)):
        names = [n.strip() for n in (m.get(cell) or "").split("\n") if n.strip().lower().endswith(".pdf")]
        for i, n in enumerate(names):
            # 한 칸에 파일이 여러 개면 두 번째부터 문서종류 뒤에 번호를 붙인다(저장 경로 충돌 방지)
            docs.append(make_doc(doc_type if i == 0 else f"{doc_type}_{i + 1}", n, path))
    return docs


def probe(sess, fname: str) -> bool:
    """파일명이 실제로 있는지 확인(PDF면 True). 본문은 받지 않고 끊는다."""
    d = make_doc("약관", fname)
    try:
        with sess.request(timeout=60, stream=True, **d.fetch) as r:
            return r.status_code == 200 and "pdf" in r.headers.get("Content-Type", "").lower()
    except Exception:
        return False


def probe_dates(after: str, today: dt.date) -> list[str]:
    """after(YYYYMMDD) 다음부터 오늘까지의 1일·11일 후보."""
    out, y, mo = [], int(after[:4]), int(after[4:6])
    while (y, mo) <= (today.year, today.month):
        for d in PROBE_DAYS:
            c = f"{y:04d}{mo:02d}{d}"
            if after < c <= today.strftime("%Y%m%d"):
                out.append(c)
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return out


def list_editions(sess, targets) -> list[Edition]:
    want = {norm(t): t for t in targets}
    # 검색어: 상품명에서 괄호·대괄호·쉼표 앞부분 (서버 검색이 괄호/쉼표가 섞이면 엉뚱하게 동작함) → 결과는 상품명으로 다시 거른다
    keywords = sorted({norm(re.split(r"[(\[,]", t)[0]) for t in targets})
    rows, seen = [], set()
    for gubun in (SALE, STOP):
        for kw in keywords:
            for m in query_rows(sess, gubun, keyword=kw):
                key = (gubun, m["_seq"])
                if key not in seen:
                    seen.add(key)
                    rows.append(m)

    eds: dict[tuple, Edition] = {}
    for m in rows:
        name = norm(m.get("cell1"))
        # 정확히 같은 이름, 또는 '<상품명> [해약환급금이 없는 유형]' 같은 유형 꼬리표가 붙은 이름
        base = norm(re.sub(r"\s*\[[^\]]*\]$", "", name))
        if name not in want and base not in want:
            continue
        start = ymd(m.get("cell2"))
        if not start:
            continue
        k = (name, start)
        e = Edition(company=COMPANY, product=name, start=start, end=ymd(m.get("cell3")),
                    disclosure_id="", docs=row_docs(m))
        # 판매중/판매중지 양쪽에 같은 판이 있으면 문서가 더 많은 쪽을 쓴다
        if k not in eds or len(e.docs) > len(eds[k].docs):
            eds[k] = e

    # 표에 아직 안 올라온 새 판 보충: 상품별 최신 개시일 이후 1일·11일을 파일명으로 프로브
    today = dt.date.today()
    for t in targets:
        name = norm(t)
        mine = sorted((e for e in eds.values() if e.product == name), key=lambda e: e.start)
        if not mine:
            continue  # 목록에 아예 없는 상품은 이름이 틀렸을 수 있으니 추측하지 않는다
        last = mine[-1]
        for date in probe_dates(last.start, today):
            if not probe(sess, f"{name}_약관_{date}.pdf"):
                continue
            docs = [make_doc("약관", f"{name}_약관_{date}.pdf")]
            for doc_type in ("사업방법서", "상품요약서"):
                fn = f"{name}_{doc_type}_{date}.pdf"
                if probe(sess, fn):
                    docs.append(make_doc(doc_type, fn))
                else:  # 개정되지 않은 문서는 직전 판 파일을 그대로 쓴다(공시실 표에서도 흔한 일)
                    docs += [d for d in last.docs if d.doc_type == doc_type]
            last.end = last.end or ymd((dt.datetime.strptime(date, "%Y%m%d") - dt.timedelta(days=1)).strftime("%Y%m%d"))
            last = Edition(company=COMPANY, product=name, start=date, end="", disclosure_id="", docs=docs)
            eds[(name, date)] = last

    return sorted(eds.values(), key=lambda e: (e.product, e.start))


def list_products(sess) -> list[str]:
    """판매중인 건강/암·간편고지 보장성 상품명.

    '판매중인상품' 표에는 같은 상품의 과거 판(종료일 있음)과 오래된 구상품도 섞여 있으므로
    판매종료일이 빈 행(=현재 판매 중인 판)이 있는 상품만 고른다.
    """
    names = set()
    for cat in HEALTH_CATS:
        for m in query_rows(sess, SALE, cat=cat):
            if m.get("cell1") and not ymd(m.get("cell3")):
                names.add(norm(m["cell1"]))
    return sorted(names)


if __name__ == "__main__":
    run(COMPANY, list_editions, list_products)
