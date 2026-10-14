"""동양생명 공시실 수집기.

경로 (RECIPES.md 「동양생명」 참고):
    목록   POST https://pbano.myangel.co.kr/paging/WE_AC_WEPAAP020100L
           _biz_op_code=IQY, sale_kind=ALL(중요 — '1'이면 빈 목록), goods_kind=ALL, nameStr=<검색어>
    과거판 POST /process/WE_AC_WEPAAP020100D
           _biz_op_code=IQY_D, GOODS_NM=<공백 없는 상품명>, SALE_KIND=01
    파일   POST /process/CO_ComDownload
           _biz_op_code=FDL, FILE_GRP_ID=<FILE_GRP_ID3(약관) / FILE_GRP_ID2(방법서)>
           FILE_GRP_ID1 = 상품요약서로 추정(확인 필요)

클라우드 환경에서는 응답이 없어(시간 초과) 사용자 Mac에서 돌린다.
디버그: COLLECTOR_DEBUG_DIR=폴더 (또는 --debug-dump 폴더) 로 목록·과거판 원본을 저장한다.
"""
from __future__ import annotations

import re

from common import Doc, Edition, run
from siteutil import (allow_missing, consume_debug_flag, fail, health_only, norm, norm_loose, request,
                      try_json, walk_dicts, warn, ymd)

SITE = "동양생명"
BASE = "https://pbano.myangel.co.kr"
LIST_URL = BASE + "/paging/WE_AC_WEPAAP020100L"
DETAIL_URL = BASE + "/process/WE_AC_WEPAAP020100D"
DOWN_URL = BASE + "/process/CO_ComDownload"
HEADERS = {"Referer": BASE + "/", "X-Requested-With": "XMLHttpRequest"}

# 문서종류 ↔ FILE_GRP_ID 필드. 확인 필요: FILE_GRP_ID1 이 상품요약서인지.
FILE_FIELDS = (("약관", "FILE_GRP_ID3"), ("사업방법서", "FILE_GRP_ID2"), ("상품요약서", "FILE_GRP_ID1"))

# 확인 필요: 응답 필드 이름. 아래 후보를 순서대로 찾고, 없으면 키 이름 패턴으로 찾는다.
NAME_KEYS = ("GOODS_NM", "goods_nm", "GOODSNM", "goodsNm")
START_KEYS = ("SALE_STRT_DT", "SALE_STR_DT", "SALE_ST_DT", "SALE_BGN_DT", "STRT_DT", "SALE_START_DT", "START_DT")
END_KEYS = ("SALE_END_DT", "SALE_ED_DT", "END_DT", "SALE_CLS_DT")
START_PAT = re.compile(r"(STRT|STR|START|BGN|BEGIN|FROM|_ST_|ST_DT|STA)", re.I)
END_PAT = re.compile(r"(END|_ED_|ED_DT|CLS|CLOSE|_TO_)", re.I)
DATE_KEY_PAT = re.compile(r"(DT|DATE|YMD|DAY)", re.I)


def _get(d: dict, exact: tuple, pat: re.Pattern | None = None) -> str:
    for k in exact:
        if k in d and d[k] not in (None, ""):
            return str(d[k])
    if pat:
        for k, v in d.items():
            if pat.search(k) and DATE_KEY_PAT.search(k) and v not in (None, ""):
                return str(v)
    return ""


def _post(sess, label: str, url: str, data: dict):
    text, _ = request(sess, SITE, label, "POST", url, data=data, headers=HEADERS)
    obj = try_json(text)
    if obj is None:
        fail(SITE, f"{label}: JSON 이 아닌 응답이 왔습니다(차단 페이지이거나 형식이 바뀜).", text, label)
    return obj


def parse_dongyang_list(obj) -> list[dict]:
    """목록 응답(JSON) → 상품 행 dict 목록(GOODS_NM 이 있는 dict).

    확인 필요: 실제 목록 키 이름과 쪽 나눔(paging) 인자. 지금은 JSON 어디에 있든 GOODS_NM 을 가진
    dict 를 모두 상품 행으로 본다.
    """
    return [d for d in walk_dicts(obj) if _get(d, NAME_KEYS)]


def parse_dongyang_detail(obj) -> list[dict]:
    """과거판 응답(JSON) → [{name, start, end, files:{문서종류: FILE_GRP_ID}, id}].

    확인 필요: 판매개시·종료일 필드 이름(START_KEYS/END_KEYS 후보, 없으면 키 패턴),
    FILE_GRP_ID1 이 상품요약서인지. FILE_GRP_ID 로 시작하는 키를 가진 dict 만 판으로 본다.
    """
    out = []
    for d in walk_dicts(obj):
        if not any(str(k).upper().startswith("FILE_GRP_ID") for k in d):
            continue
        files = {}
        for dt, key in FILE_FIELDS:
            v = d.get(key) if key in d else d.get(key.lower())
            if v not in (None, "", "0"):
                files[dt] = str(v)
        start = ymd(_get(d, START_KEYS, START_PAT))
        end = ymd(_get(d, END_KEYS, END_PAT))
        out.append({"name": _get(d, NAME_KEYS), "start": start, "end": end, "files": files,
                    "id": files.get("약관") or next(iter(files.values()), "")})
    return out


def _list(sess, name_str: str) -> list[dict]:
    obj = _post(sess, f"목록_{name_str or '전체'}", LIST_URL,
                {"_biz_op_code": "IQY", "sale_kind": "ALL", "goods_kind": "ALL", "nameStr": name_str})
    return parse_dongyang_list(obj)


def _detail(sess, goods_nm: str) -> list[dict]:
    nospace = re.sub(r"\s+", "", goods_nm)
    obj = _post(sess, f"과거판_{nospace}", DETAIL_URL,
                {"_biz_op_code": "IQY_D", "GOODS_NM": nospace, "SALE_KIND": "01"})
    return parse_dongyang_detail(obj)


def _same(a: str, b: str) -> bool:
    return norm(a) == norm(b) or norm_loose(a) == norm_loose(b)


def _doc(dt: str, grp: str) -> Doc:
    return Doc(doc_type=dt, source=f"POST {DOWN_URL} FILE_GRP_ID={grp} ({dt})",
               fetch={"method": "POST", "url": DOWN_URL, "data": {"_biz_op_code": "FDL", "FILE_GRP_ID": grp},
                      "headers": {"Referer": BASE + "/"}},
               orig_name=grp)


def list_editions(sess, targets: list[str]) -> list[Edition]:
    out: list[Edition] = []
    missing = []
    catalog = None
    for target in targets:
        rows = [r for r in _detail(sess, target) if not r["name"] or _same(r["name"], target)]
        if not rows:
            # 목록 검색으로 공시실 원문명을 찾아 다시 조회
            if catalog is None:
                catalog = [_get(d, NAME_KEYS) for d in _list(sess, "")]
            for site_name in dict.fromkeys(n for n in catalog if _same(n, target)):
                rows = [r for r in _detail(sess, site_name) if not r["name"] or _same(r["name"], target)]
                if rows:
                    warn(SITE, f"이름 보정: {target!r} → 공시실 {site_name!r}")
                    break
        if not rows:
            missing.append(target)
            continue
        seen = set()
        for r in rows:
            if not r["start"]:
                fail(SITE, f"'{target}' 과거판 행에서 판매개시일을 읽지 못했습니다(필드 이름 확인 필요): {r}")
            if not r["files"]:
                warn(SITE, f"{target} {r['start']}판에 FILE_GRP_ID 가 비어 있습니다.")
                continue
            k = (r["start"], r["id"])
            if k in seen:
                continue
            seen.add(k)
            out.append(Edition(company=SITE, product=target, start=r["start"], end=r["end"],
                               disclosure_id=r["id"], docs=[_doc(dt, g) for dt, g in r["files"].items()]))
    if missing:
        msg = f"과거판 조회에서 대상 상품을 찾지 못했습니다: {missing}"
        if catalog:
            msg += f"\n  목록에서 읽은 상품명 예시(최대 30개): {sorted(set(catalog))[:30]}"
        if not out or not allow_missing():
            fail(SITE, msg + "\n  (일부 누락을 허용하려면 COLLECTOR_ALLOW_MISSING=1)")
        warn(SITE, msg)
    return sorted(out, key=lambda e: (e.product, e.start))


def list_products(sess) -> list[str]:
    """전체 목록(sale_kind=ALL)에서 건강·보장 계열 상품명.

    확인 필요: 목록 행에 판매중/판매중지 구분 필드가 있으면(예: SALE_YN, SALE_STAT_CD) 판매중만 고르도록
    고친다. 지금은 종료일 필드가 비었거나 9999 인 행만 판매중으로 보고, 종료일 필드가 아예 없으면 전부 쓴다.
    """
    rows = _list(sess, "")
    if not rows:
        fail(SITE, "상품 목록이 비어 있습니다(nameStr 빈값으로 전체 조회가 안 될 수 있음 — 확인 필요).")
    names = []
    for d in rows:
        end_raw = _get(d, END_KEYS, END_PAT)
        if end_raw and ymd(end_raw):
            continue
        names.append(_get(d, NAME_KEYS))
    names = health_only(names)
    if not names:
        fail(SITE, "판매중 건강·보장 계열 상품명을 하나도 읽지 못했습니다.")
    return names


if __name__ == "__main__":
    consume_debug_flag()
    run("동양생명", list_editions, list_products)
