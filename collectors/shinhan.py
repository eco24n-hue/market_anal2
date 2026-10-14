"""신한라이프 공시실 수집기.

공시실 화면: https://www.shinhanlife.co.kr/hp/cdhi0030.do (공시실 > 상품공시 > 전체상품 > 판매중)

화면 JS(dp.common.js 의 dp.Ajax.send)가 보내는 요청을 그대로 재현한다.
    POST https://www.shinhanlife.co.kr/<trId>.pwkjson
    Content-Type: application/json; charset=UTF-8
    X-AJAX-CALL: true / Proworks-Body: Y / Proworks-Lang: ko
    본문: {"elData": {...검색조건, "scrnId": "cdhi0030"},
           "userHeader": {"scrnId": "cdhi0030", "appliDtptDutjCd": "DH"}}
    응답: {"elHeader": {"resSuc": true, ...}, "elData": {"nodeInfoVoList": [...], "listCount": N}}

- 판매중 목록: trId=co/wcms/nodeInfoListPage, method=selectListGoods, meta06=TRUE (50건씩 페이지)
  상품별 "현재 판" 한 줄만 온다. 같은 상품이 채널(meta02: TM/일반/방카/인터넷모바일…)별로 중복된다.
- 과거 판 목록: trId=co/wcms/nodeInfoList, method=selectAllListGoods, meta05=<공시실 상품명>
  현재 판은 빠지고 그 이전 판만 온다. meta02/meta03 을 비우면 모든 채널 것이 온다.
- 필드: meta04 상품코드, meta05 상품명, meta07 개시, meta08 종료(99991231=판매중),
        meta09 상품요약서, meta10 사업방법서, meta11 약관 (각각 /repo/DigitalPlattform/... 경로)
- 파일 URL: dp.Utils.getFileObject 처럼 '/repo/<wsId>' 를 '/bizxpress' 로 바꾼다.
  하위 폴더(__etc, __media)는 그대로 둬야 한다 — 상품요약서는 __media 에 있어 __etc 로 바꾸면 404.
"""
from __future__ import annotations

import json
import re
import sys
import time
from urllib.parse import quote

import requests

from common import Doc, Edition, run

BASE = "https://www.shinhanlife.co.kr"
PAGE = BASE + "/hp/cdhi0030.do"
SCRN = "cdhi0030"
CAT_ID = "M160991914330045272"   # 판매중 상품공시 카테고리(cdhi0030.js UserVal.catId)
HEADERS = {
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-AJAX-CALL": "true",
    "X-Requested-With": "XMLHttpRequest",
    "Proworks-Body": "Y",
    "Proworks-Lang": "ko",
    "Origin": BASE,
    "Referer": PAGE,
}
DOC_FIELDS = (("약관", "meta11"), ("사업방법서", "meta10"), ("상품요약서", "meta09"))
CHANNEL_PREF = {"일반": 0, "TM": 1, "방카": 2, "인터넷모바일": 3}  # 같은 개시일에 파일이 다르면 앞 채널 우선


# ───────────────────────── 통신 ─────────────────────────

def _req(sess, method: str, url: str, tries: int = 4, **kw):
    """서버가 가끔 연결을 끊는다(Connection reset). 연결 오류만 짧게 재시도."""
    for i in range(tries):
        try:
            return sess.request(method, url, **kw)
        except requests.exceptions.ConnectionError:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def _call(sess, tr_id: str, el: dict) -> dict:
    """dp.Ajax.send 재현. elData 를 돌려준다."""
    body = {"elData": dict(el, scrnId=SCRN),
            "userHeader": {"scrnId": SCRN, "appliDtptDutjCd": "DH"}}
    r = _req(sess, "POST", f"{BASE}/{tr_id}.pwkjson", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                  headers=HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    hd = j.get("elHeader") or {}
    if not hd.get("resSuc"):
        raise RuntimeError(f"{tr_id} 실패: {hd.get('resCode')} {hd.get('resMsg')}")
    return j.get("elData") or {}


def _warm(sess):
    """세션 쿠키(JSESSIONID 등)를 받기 위해 화면을 한 번 연다."""
    if not getattr(sess, "_shinhan_warm", False):
        _req(sess, "GET", PAGE, timeout=30)
        sess._shinhan_warm = True


def _list_selling(sess) -> list[dict]:
    """판매중 목록 전체(모든 페이지)."""
    _warm(sess)
    rows, page = [], 1
    while True:
        d = _call(sess, "co/wcms/nodeInfoListPage", {
            "catId": CAT_ID, "pageSize": 50, "pageIndex": page, "method": "selectListGoods",
            "meta02": "", "meta03": "", "title": "", "meta06": "TRUE"})
        lst = d.get("nodeInfoVoList") or []
        rows += lst
        if not lst or len(rows) >= int(d.get("listCount") or 0) or page > 50:
            return rows
        page += 1


def _list_history(sess, name: str) -> list[dict]:
    """상품명(공시실 원문)의 과거 판 전체(모든 채널)."""
    _warm(sess)
    d = _call(sess, "co/wcms/nodeInfoList", {
        "catId": CAT_ID, "method": "selectAllListGoods", "meta05": name,
        "meta02": "", "meta03": "", "title": ""})
    return d.get("nodeInfoVoList") or []


# ───────────────────────── 상품명 매칭 ─────────────────────────

def _main_name(s: str) -> str:
    """'A<br>(구)B' 형태면 앞부분만."""
    return re.split(r"<br\s*/?>", s or "", flags=re.I)[0].strip()


def _norm(s: str) -> str:
    """공백·괄호 종류·전각 차이를 없앤 비교용 문자열."""
    s = _main_name(s)
    s = s.translate(str.maketrans("［］〔〕【】（）", "[][][]()"))
    s = s.replace("[", "(").replace("]", ")")
    s = re.sub(r"\s+", "", s)
    s = s.replace("해지환급금", "해약환급금")
    return s.lower()


def _split(s: str) -> tuple[str, frozenset]:
    """정규화 이름을 (본체, 괄호 속 속성 토큰 집합)으로 나눈다.
    예) 신한통합건강보험슈퍼원(one)(무배당,해약환급금미지급형) → ('신한통합건강보험슈퍼원(one)', {무배당, 해약환급금미지급형})"""
    n = _norm(s)
    m = re.search(r"\((무배당|유배당)", n)
    if not m:
        return n, frozenset()
    body, tail = n[:m.start()], n[m.start():]
    # '해약환급금 미지급형' ↔ '미지급형', '무해지형' 같은 축약을 같은 토큰으로 본다
    alias = {"무해지형": "미지급형", "무해지": "미지급형"}
    toks = frozenset(alias.get(t, t) for t in (re.sub(r"^해약환급금", "", x) for x in re.split(r"[(),]+", tail)) if t)
    return body, toks


def _match(target: str, names: list[str]) -> str | None:
    """목표 상품명에 맞는 공시실 상품명. ①정규화 완전일치 ②본체 일치 + 속성 토큰 포함관계(유일할 때)."""
    nt = _norm(target)
    for n in names:
        if _norm(n) == nt:
            return n
    tb, tt = _split(target)
    cand = []
    for n in names:
        b, t = _split(n)
        if b == tb and (tt <= t or t <= tt):
            cand.append(n)
    return cand[0] if len(cand) == 1 else None


# ───────────────────────── 판 조립 ─────────────────────────

def _file_url(ws_id: str, path: str) -> str:
    """dp.Utils.getFileObject: /repo/<wsId>/... → /bizxpress/... (하위 폴더 유지)."""
    if path.startswith(f"/repo/{ws_id}"):
        path = "/bizxpress" + path[len(f"/repo/{ws_id}"):]
    elif path.startswith("/repo/"):
        path = "/bizxpress/" + path.split("/", 3)[3]
    return BASE + quote(path)


def _edition(product: str, r: dict) -> Edition:
    docs = []
    for doc_type, key in DOC_FIELDS:
        p = (r.get(key) or "").strip()
        if not p:
            continue
        url = _file_url(r.get("wsId") or "DigitalPlattform", p)
        docs.append(Doc(doc_type=doc_type, source=url, fetch={"method": "GET", "url": url, "headers": {"Referer": PAGE}},
                        orig_name=p.rsplit("/", 1)[-1]))
    end = (r.get("meta08") or "")[:8]
    return Edition(company="신한라이프", product=product, start=(r.get("meta07") or "")[:8],
                   end="" if end.startswith("9999") else end,
                   disclosure_id=r.get("meta04") or "", docs=docs)


def _dedupe(product: str, rows: list[dict]) -> list[Edition]:
    """채널 중복 제거: 개시일당 한 판. 파일 구성이 다르면 CHANNEL_PREF 순으로 하나만 남긴다."""
    rows = sorted(rows, key=lambda r: CHANNEL_PREF.get(r.get("meta02"), 9))
    by_start: dict[str, dict] = {}
    for r in rows:
        st = (r.get("meta07") or "")[:8]
        if not st:
            continue
        if st in by_start:
            a, b = by_start[st], r
            if any((a.get(k) or "") != (b.get(k) or "") for _, k in DOC_FIELDS):
                print(f"[신한] {product} {st}: 채널 {a.get('meta02')}/{b.get('meta02')} 파일 다름 → {a.get('meta02')} 사용",
                      file=sys.stderr)
            continue
        by_start[st] = r
    eds = [_edition(product, r) for r in by_start.values()]
    # 메타 코드(meta04)가 채널마다 다를 수 있어(예: 7000430/70004300) 판 키를 흔들지 않게 대표값 하나로 맞춘다
    code = next((e.disclosure_id for e in eds if e.disclosure_id), "")
    for e in eds:
        e.disclosure_id = code
    return sorted(eds, key=lambda e: e.start, reverse=True)


# ───────────────────────── 공개 인터페이스 ─────────────────────────

def list_editions(sess, targets: list[str]) -> list[Edition]:
    selling = _list_selling(sess)
    names = sorted({r["meta05"] for r in selling if r.get("meta05")})
    out = []
    for t in targets:
        name = _match(t, names)
        if name is None:
            # 판매중 목록에 없으면(판매중지 등) 목표명 그대로 과거판 조회를 시도한다
            hist = _list_history(sess, t)
            if not hist:
                print(f"[신한] 공시실에서 못 찾음: {t}", file=sys.stderr)
                continue
            name, cur = t, []
        else:
            if name != t:
                print(f"[신한] 이름 다름: 목표 '{t}' → 공시실 '{name}'", file=sys.stderr)
            cur = [r for r in selling if r.get("meta05") == name]
            hist = _list_history(sess, name)
        out += _dedupe(_main_name(name), cur + hist)
    return out


HEALTH = re.compile(r"건강|질병|암|간편|치매|간병|뇌심|뇌|심장|수술|폴립|입원|실손|의료비")
NOT_HEALTH = re.compile(r"종신|정기보험|연금|저축|적립|변액|경영인")


def list_products(sess) -> list[str]:
    """판매중 건강·질병·암·간편 보장성 상품명(채널 중복 제거)."""
    out = set()
    for r in _list_selling(sess):
        n = _main_name(r.get("meta05") or "")
        if r.get("meta03") == "보장" and HEALTH.search(n) and not NOT_HEALTH.search(n):
            out.add(n)
    return sorted(out)


if __name__ == "__main__":
    run("신한라이프", list_editions, list_products)
