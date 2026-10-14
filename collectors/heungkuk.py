"""흥국생명 공시실 수집기.

경로 (RECIPES.md 「흥국생명」 참고):
    목록  POST /front/public/saleProductAjax.do
          searchFlgSale=Y, searchCdPublicPrtType1=I101(보장성),
          searchCdPublicPrtType3=<상품명>, searchText=<검색어>
          값은 escape(encodeURIComponent(x)) 이중 인코딩, 응답은 EUC-KR.
          응답 구분자: %||% (섹션) / %|% (행) / %,% (필드).
          세 번째 섹션이 판별 다운로드 행:
            [0]개시일 [1]종료일 [2]공시번호 [4]약관토큰 [5]약관파일명
            [6]방법서토큰 [7]방법서파일명 [8]요약서토큰 [9]요약서파일명
    파일  POST /servlet/DownLoadEnc.do  encValue=<토큰>  → PDF

주의: 2026-10-07 ~ 10-26 흥국생명이 해외 IP를 WAF로 막고 있어 클라우드에서는
      모든 경로가 「해외 IP 로그인 일시 제한 안내」 HTML(2,281바이트)을 돌려준다.
      이 경우 BlockedError를 낸다(빈 목록으로 조용히 넘어가지 않는다).
"""
from __future__ import annotations

import re
import sys
import urllib.parse

from common import Doc, Edition, run

BASE = "https://www.heungkuklife.co.kr"
LIST_URL = BASE + "/front/public/saleProductAjax.do"
DOWN_URL = BASE + "/servlet/DownLoadEnc.do"
PAGE_URL = BASE + "/front/public/saleProduct.do"   # 판매상품 공시 페이지(Referer용)
PRT_TYPE_PROTECT = "I101"                          # 보장성

# 다운로드 행 필드 위치: (문서종류, 토큰 위치, 파일명 위치)
DOC_FIELDS = (("약관", 4, 5), ("사업방법서", 6, 7), ("상품요약서", 8, 9))

# 신상품 감지용 건강·보장 계열 키워드
HEALTH_RE = re.compile(r"건강|질병|암|간편|케어|Care|통합|종합|다사랑|튼튼")


class BlockedError(RuntimeError):
    """WAF 차단 페이지나 예상 밖 HTML이 온 경우."""


# ── 인코딩·요청 ──────────────────────────────────────────────

def js_double_encode(s: str) -> str:
    """JS escape(encodeURIComponent(s))와 같은 결과."""
    once = urllib.parse.quote(s, safe="-_.!~*'()")      # encodeURIComponent
    return urllib.parse.quote(once, safe="@*_+-./")     # escape (% → %25)


def _post_list(sess, product: str = "", text: str = "") -> str:
    data = {
        "searchFlgSale": "Y",
        "searchCdPublicPrtType1": PRT_TYPE_PROTECT,
        "searchCdPublicPrtType3": js_double_encode(product) if product else "",
        "searchText": js_double_encode(text) if text else "",
    }
    r = sess.post(LIST_URL, data=data, timeout=60,
                  headers={"Referer": PAGE_URL, "X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    raw = r.content
    # WAF 차단 페이지는 UTF-8 HTML이다
    if b"<html" in raw[:500].lower() or "해외 IP".encode() in raw:
        title = re.search(rb"<title>(.*?)</title>", raw, re.S)
        msg = title.group(1).decode("utf-8", "replace").strip() if title else raw[:80]
        raise BlockedError(f"흥국생명 공시실 응답이 HTML입니다(차단 추정): {msg}")
    return raw.decode("euc-kr", "replace")


def _sections(text: str) -> list[list[list[str]]]:
    """응답을 섹션 → 행 → 필드로 나눈다."""
    out = []
    for sec in text.split("%||%"):
        rows = [[f.strip() for f in row.split("%,%")] for row in sec.split("%|%") if row.strip()]
        out.append(rows)
    return out


def _ymd(s: str) -> str:
    """'2026.09.14' / '2026-09-14' / '20260914' → '20260914'. 판매중(빈값·9999)은 ''."""
    d = re.sub(r"\D", "", s or "")
    if len(d) != 8 or d.startswith("9999"):
        return ""
    return d


# ── 상품명 매칭 ──────────────────────────────────────────────

def _norm(s: str) -> str:
    """비교용 정규화: 회사 접두어·(무)·무배당·공백·괄호 차이를 없앤다."""
    s = s.replace("흥국생명", "").replace("(무)", "").replace("무배당", "")
    s = s.replace("多", "").replace("（", "(").replace("）", ")")
    return re.sub(r"[\s()\[\]·_]", "", s).lower()


def _candidates(target: str) -> list[str]:
    """공시실 검색에 넣어 볼 상품명 후보(원문 우선)."""
    base = re.sub(r"^\s*흥국생명\s*", "", target).strip()
    cands = [base, "(무)" + base, "(무)흥국생명 " + base, target]
    return list(dict.fromkeys(cands))


def _download_rows(text: str) -> list[list[str]]:
    secs = _sections(text)
    rows = secs[2] if len(secs) > 2 else []
    # 개시일이 날짜인 행만 판으로 본다
    return [r for r in rows if len(r) >= 6 and _ymd(r[0])]


def _row_to_edition(product: str, row: list[str]) -> Edition:
    docs = []
    for doc_type, ti, ni in DOC_FIELDS:
        token = row[ti] if len(row) > ti else ""
        if not token:
            continue  # 토큰이 비면 해당 문서 없음
        name = row[ni] if len(row) > ni else ""
        docs.append(Doc(doc_type=doc_type,
                        source=f"POST {DOWN_URL} encValue=… ({name or doc_type})",
                        fetch={"method": "POST", "url": DOWN_URL, "data": {"encValue": token},
                               "headers": {"Referer": PAGE_URL}},
                        orig_name=name))
    return Edition(company="흥국생명", product=product, start=_ymd(row[0]), end=_ymd(row[1]),
                   disclosure_id=row[2] if len(row) > 2 else "", docs=docs)


# ── 공개 함수 ───────────────────────────────────────────────

def list_editions(sess, targets: list[str]) -> list[Edition]:
    """대상 상품마다 공시실 이름 후보로 조회해 모든 판을 돌려준다."""
    eds: list[Edition] = []
    catalog = None   # 이름 후보가 다 빗나갈 때만 판매상품 목록으로 보정
    missing = []
    for target in targets:
        found = None
        for name in _candidates(target):
            rows = _download_rows(_post_list(sess, product=name))
            if rows:
                found = (name, rows)
                break
        if not found:
            # 판매상품 목록에서 정규화 일치하는 공시실 원문명을 찾아 재조회
            if catalog is None:
                catalog = list_products(sess, health_only=False)
            hits = [n for n in catalog if _norm(n) == _norm(target)]
            for name in hits:
                rows = _download_rows(_post_list(sess, product=name))
                if rows:
                    found = (name, rows)
                    break
        if not found:
            missing.append(target)
            continue
        name, rows = found
        if _norm(name) != _norm(target) or name != target:
            print(f"[흥국생명] 이름 보정: {target!r} → 공시실 {name!r}", file=sys.stderr)
        seen = set()
        for row in rows:
            e = _row_to_edition(name, row)
            k = (e.start, e.disclosure_id)
            if k not in seen:
                seen.add(k)
                eds.append(e)
    for t in missing:
        print(f"[흥국생명] 공시실에서 찾지 못함: {t}", file=sys.stderr)
    return eds


def list_products(sess, health_only: bool = True) -> list[str]:
    """판매상품(보장성) 공시 목록의 상품명. 첫 번째 섹션의 각 행에서 상품명을 고른다.

    판매상품 페이지는 상품명을 비운 채 같은 saleProductAjax.do를 불러 목록을 그린다.
    행 구조가 확인되지 않아, 각 행에서 '보험' 이 들어간 가장 긴 필드를 상품명으로 본다.
    """
    text = _post_list(sess)
    names = []
    for sec in _sections(text)[:2]:
        for row in sec:
            cand = [f for f in row if "보험" in f and not f.lower().endswith(".pdf")]
            if cand:
                names.append(max(cand, key=len))
    names = list(dict.fromkeys(names))
    if health_only:
        names = [n for n in names if HEALTH_RE.search(n)]
    return names


if __name__ == "__main__":
    run("흥국생명", list_editions, list_products)
