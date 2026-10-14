"""하나생명 공시실 수집기.

경로 (RECIPES.md 「하나생명」 참고):
    목록   GET /anm/product/allProduct.do?status=off   판매중지(2014년까지 과거판 보존)
           GET /anm/product/allProduct.do?status=on    판매중   ← 확인 필요(값 추정)
    약관   GET /anm/product/download.do?code=<코드>&seq=1
    방법서 GET /home/download2.do?fileName=PROD/<파일명>
    1월판 코드 610778·610801·610800·610802·610779·610780,
    9월판 약관 코드 611052·611072·611073·611053·611054·611074 (계약자용약관_20260901).
    사업방법서는 「누리는」과 「누리는(간편심사형)」 두 파일을 6상품이 공유한다.

클라우드 환경에서는 TLS 연결 직후 서버가 끊으므로 사용자 Mac에서 돌린다.

디버그: COLLECTOR_DEBUG_DIR=폴더 (또는 --debug-dump 폴더) 로 목록 원본 HTML을 저장한다.
"""
from __future__ import annotations

import os
import re
import urllib.parse

from common import Doc, Edition, run
from siteutil import (allow_missing, consume_debug_flag, dates_in, fail, health_only,
                      norm, norm_loose, request, strip_tags, warn)

SITE = "하나생명"
BASE = "https://www.hanalife.co.kr"
LIST_URL = BASE + "/anm/product/allProduct.do"
TERMS_URL = BASE + "/anm/product/download.do"
FILE_URL = BASE + "/home/download2.do"
# 확인 필요: 판매중 목록의 status 값. 판매중지는 RECIPES.md 에 'off' 로 확인됨.
STATUS_ON = os.environ.get("HANA_STATUS_ON", "on")
STATUS_OFF = "off"
# 확인 필요: 목록이 여러 쪽으로 나뉘는지, 나뉜다면 쪽 번호 인자 이름.
# 서버가 이 인자를 무시하면 2쪽째가 1쪽과 같게 와서 바로 멈추므로 틀려도 해가 없다.
PAGE_PARAM = os.environ.get("HANA_PAGE_PARAM", "pageIndex")
MAX_PAGES = 60
HEADERS = {"Referer": LIST_URL + "?status=off"}

# 링크 패턴 (href·onclick 안에서 찾는다)
P_TERMS = re.compile(r"download\.do\?code=(\d+)(?:&amp;|&)seq=(\d+)")
P_FILE = re.compile(r"download2\.do\?fileName=([^'\"&\s)]+)")
# 확인 필요: 링크가 href 가 아니라 JS 함수 호출(onclick="fnDown('610778','1')")일 경우의 추정 패턴
P_JS_CODE = re.compile(r"\w*[Dd]own\w*\(\s*['\"](\d{5,})['\"]\s*,\s*['\"]?(\d+)['\"]?")
P_JS_FILE = re.compile(r"\w*[Dd]own\w*\(\s*['\"]([^'\"]+\.pdf)['\"]", re.I)


def _label_type(text: str) -> str | None:
    if "사업방법" in text or "방법서" in text:
        return "사업방법서"
    if "요약" in text:
        return "상품요약서"
    if "약관" in text:
        return "약관"
    return None


def _terms_doc(code: str, seq: str, doc_type: str, label: str) -> Doc:
    return Doc(doc_type=doc_type, source=f"{TERMS_URL}?code={code}&seq={seq}",
               fetch={"method": "GET", "url": TERMS_URL, "params": {"code": code, "seq": seq}, "headers": HEADERS},
               orig_name=label)


def _file_doc(fname: str, doc_type: str) -> Doc:
    fname = urllib.parse.unquote(fname)
    if not fname.upper().startswith("PROD/"):
        fname = "PROD/" + fname.lstrip("/")
    return Doc(doc_type=doc_type, source=f"{FILE_URL}?fileName={fname}",
               fetch={"method": "GET", "url": FILE_URL, "params": {"fileName": fname}, "headers": HEADERS},
               orig_name=fname.split("/", 1)[1])


def _row_links(seg: str) -> tuple[list[tuple[Doc, str]], str]:
    """행 HTML에서 다운로드 링크를 찾아 (Doc, 코드) 목록과, 링크를 뺀 행 HTML을 돌려준다."""
    out: list[tuple[Doc, str]] = []
    rest = seg
    for m in re.finditer(r"(?is)<(a|button)\b([^>]*)>(.*?)</\1>", seg):
        attrs, inner = m.group(2).replace("&amp;", "&"), m.group(3)
        title = " ".join(re.findall(r'(?:title|alt)\s*=\s*["\']([^"\']*)', m.group(0)))
        label = (strip_tags(inner) + " " + title).strip()
        lt = _label_type(label)
        found = False
        for pm in list(P_TERMS.finditer(attrs)) + list(P_JS_CODE.finditer(attrs)):
            code, seq = pm.group(1), pm.group(2)
            dt = lt or ("약관" if seq == "1" else None)
            if dt:
                out.append((_terms_doc(code, seq, dt, label), code))
                found = True
        for pm in list(P_FILE.finditer(attrs)) + list(P_JS_FILE.finditer(attrs)):
            fn = pm.group(1)
            dt = lt or _label_type(urllib.parse.unquote(fn))
            if dt:
                out.append((_file_doc(fn, dt), ""))
                found = True
        if found:
            rest = rest.replace(m.group(0), " ")
    return out, rest


def parse_hana_list(page_html: str) -> list[dict]:
    """하나생명 상품 목록 HTML → [{name, start, end, code, docs:[Doc]}].

    확인 필요: 목록 마크업. 지금은 <tr>(없으면 <li>) 한 줄이 한 판이라고 보고,
      - 상품명: '보험'이 들어간 첫 칸(<td>/<th>), 없으면 '(무)…보험(…)' 형태의 문구
      - 판매기간: 링크를 뺀 행 텍스트의 첫 날짜=개시, 둘째 날짜=종료(없으면 판매중)
      - 문서: download.do?code=&seq= (seq=1 은 약관), download2.do?fileName=PROD/…
        링크 글자·title 에 '약관/사업방법서/요약서'가 있으면 그것을 따른다.
    한 상품의 여러 판이 한 행 안에 들어 있거나 상품명이 rowspan 으로 묶여 있으면 고쳐야 한다
    (rowspan 대비로, 상품명 칸이 없는 행은 바로 위 행의 상품명을 물려받는다).
    """
    tag = "tr" if re.search(r"(?i)<tr\b", page_html) else "li"
    segs = re.split(rf"(?i)<{tag}\b", page_html)[1:]
    rows, last_name = [], ""
    for seg in segs:
        seg = re.split(rf"(?i)</{tag}>", seg.split(">", 1)[-1])[0]
        links, rest = _row_links(seg)
        cells = [strip_tags(c) for c in re.findall(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>", rest)]
        name = next((c for c in cells if "보험" in c and not c.lower().endswith(".pdf")), "")
        if not name:
            m = re.search(r"\(무\)[^<>~]*?보험(?:\s*\([^)]*\))*", strip_tags(rest))
            name = m.group(0).strip() if m else ""
        if not links:
            if name:
                last_name = name
            continue
        name = name or last_name
        last_name = name
        ds = dates_in(strip_tags(rest))
        code = next((c for _, c in links if c), "")
        rows.append({"name": name, "start": ds[0] if ds else "", "end": ds[1] if len(ds) > 1 else "",
                     "code": code, "docs": [d for d, _ in links]})
    return rows


def _fetch_list(sess, status: str) -> list[dict]:
    """한 status 의 목록을 모든 쪽에 걸쳐 가져온다. 다운로드 링크가 하나도 없으면 멈춘다."""
    all_rows, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        params = {"status": status}
        if page > 1:
            params[PAGE_PARAM] = page
        text, _ = request(sess, SITE, f"목록_{status}_p{page}", "GET", LIST_URL, params=params, headers=HEADERS)
        rows = parse_hana_list(text)
        if page == 1 and not rows:
            low = text.lower()
            hint = ("JS로 목록을 그리는 빈 틀 페이지로 보입니다(목록용 AJAX 주소를 찾아야 함)"
                    if "<script" in low and "download" not in low else "마크업이 예상과 다릅니다")
            fail(SITE, f"상품 목록(status={status})에서 다운로드 링크를 하나도 찾지 못했습니다 — {hint}.", text,
                 f"목록_{status}_p1")
        new = [r for r in rows if (r["name"], r["start"], r["code"], tuple(d.source for d in r["docs"])) not in seen]
        if not new:
            break
        for r in new:
            seen.add((r["name"], r["start"], r["code"], tuple(d.source for d in r["docs"])))
        all_rows += new
    return all_rows


def _match(name: str, target: str) -> bool:
    return norm(name) == norm(target) or norm_loose(name) == norm_loose(target)


def list_editions(sess, targets: list[str]) -> list[Edition]:
    rows = []
    for status, on_sale in ((STATUS_OFF, False), (STATUS_ON, True)):
        got = _fetch_list(sess, status)
        for r in got:
            r["on_sale"] = on_sale
        rows += got
    eds: dict[tuple, Edition] = {}
    missing = []
    for target in targets:
        hits = [r for r in rows if _match(r["name"], target)]
        if not hits:
            missing.append(target)
            continue
        for r in hits:
            if not r["start"]:
                fail(SITE, f"'{r['name']}' 행에서 판매개시일을 찾지 못했습니다(코드 {r['code']}).")
            end = "" if r["on_sale"] else r["end"]
            k = (target, r["start"], r["code"])
            e = eds.get(k)
            if e is None:
                e = eds[k] = Edition(company=SITE, product=target, start=r["start"], end=end,
                                     disclosure_id=r["code"], docs=[])
            have = {d.doc_type for d in e.docs}
            for d in r["docs"]:
                if d.doc_type not in have:
                    e.docs.append(d)
                    have.add(d.doc_type)
    if missing:
        names = sorted({r["name"] for r in rows if r["name"]})
        msg = (f"공시실 목록에서 대상 상품을 찾지 못했습니다: {missing}\n"
               f"  목록에서 읽은 상품명 예시(최대 30개): {names[:30]}")
        if not eds or not allow_missing():
            fail(SITE, msg + "\n  (일부 누락을 허용하려면 COLLECTOR_ALLOW_MISSING=1)")
        warn(SITE, msg)
    out = sorted(eds.values(), key=lambda e: (e.product, e.start))
    for e in out:
        if not any(d.doc_type == "약관" for d in e.docs):
            warn(SITE, f"{e.product} {e.start}판에 약관 링크가 없습니다(코드 {e.disclosure_id}).")
    return out


def list_products(sess) -> list[str]:
    rows = _fetch_list(sess, STATUS_ON)
    names = health_only(r["name"] for r in rows if r["name"])
    if not names:
        fail(SITE, "판매중 목록에서 건강·보장 계열 상품명을 하나도 읽지 못했습니다.")
    return names


if __name__ == "__main__":
    consume_debug_flag()
    run("하나생명", list_editions, list_products)
