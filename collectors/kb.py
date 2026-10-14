"""KB라이프 공시실 수집기.

경로 (RECIPES.md 「KB라이프」 참고):
    목록   상품공시 페이지의 아코디언 `.panel` 안에 판매기간별 행이 있고, 행의 `data-seqno`가 공시번호다.
    파일   GET https://www.kblife.co.kr/api/archive/archives/download/product-terms/{공시번호}/{box}
           box 1=사업방법서, box 2=약관, box 0=상품요약서(건강보험 보장성은 비어 있음)
    2026/10/01판 현행 공시번호 501619071~107.

확인 필요: 상품공시 목록 페이지 주소가 RECIPES.md 에 없다. 환경변수 KB_LIST_URLS 에
    브라우저 주소창의 공시실 목록 주소(판매상품·판매중지상품 등, 쉼표로 여러 개)를 넣는다.
    mac/weekly_collect.sh 맨 위 설정에 자리가 있다.

클라우드 환경에서는 응답이 없어(시간 초과) 사용자 Mac에서 돌린다.
디버그: COLLECTOR_DEBUG_DIR=폴더 (또는 --debug-dump 폴더) 로 목록 원본을 저장한다.
"""
from __future__ import annotations

import os
import re

from common import Doc, Edition, run
from siteutil import (allow_missing, consume_debug_flag, dates_in, fail, health_only, norm, norm_loose,
                      request, strip_tags, try_json, walk_dicts, warn)

SITE = "KB라이프"
BASE = "https://www.kblife.co.kr"
DOWN_URL = BASE + "/api/archive/archives/download/product-terms/{seqno}/{box}"
BOXES = [("사업방법서", 1), ("약관", 2)]
# 건강보험 보장성은 box 0(요약서)이 비어 있어 기본으로는 받지 않는다(매주 '다운로드 실패'가 쌓이지 않게).
# 다른 상품에서 요약서가 필요하면 KB_INCLUDE_SUMMARY=1.
if os.environ.get("KB_INCLUDE_SUMMARY", "") in ("1", "true", "yes"):
    BOXES.insert(0, ("상품요약서", 0))

SEQ_ATTR = re.compile(r"""data-seqno\s*=\s*["']?(\d+)""", re.I)
PANEL_OPEN = re.compile(r"""<(div|li|section|dd|article)\b[^>]*\bclass\s*=\s*["']([^"']*)["'][^>]*>""", re.I)
NOISE = re.compile(r"약관|사업방법서|상품요약서|요약서|다운로드|내려받기|판매기간|보기|PDF|~|현재|판매중|[\d.\-/]{8,10}")


def _list_urls() -> list[str]:
    raw = os.environ.get("KB_LIST_URLS", "").strip()
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    if not urls:
        fail(SITE, "공시실 목록 주소가 설정되지 않았습니다. 환경변수 KB_LIST_URLS 에 브라우저에서 연 "
                   "KB라이프 상품공시 목록 페이지 주소(아코디언으로 판매기간이 펼쳐지는 페이지)를 넣어 주세요. "
                   "판매중·판매중지 페이지가 따로면 쉼표로 둘 다 넣습니다.")
    return urls


def _title_candidates(fragment: str) -> list[str]:
    """HTML 조각에서 상품명처럼 보이는 텍스트 덩어리들."""
    chunks = [strip_tags(c) for c in re.split(r"<[^>]+>", fragment)]
    return [c for c in chunks if "보험" in c and len(c) < 120 and not c.lower().endswith(".pdf")]


def parse_kb_panels(page_html: str) -> list[dict]:
    """KB 목록 HTML → [{title, rows:[{seqno, start, end, label}]}].

    확인 필요: 아코디언 마크업. 두 가지 흔한 형태를 모두 받는다.
      (a) <button class="accordion">상품명</button><div class="panel">…행…</div>   (제목이 패널 앞)
      (b) <div class="panel"><div class="panel-heading">상품명</div>…행…</div>     (제목이 패널 안)
    패널 안에서는 <tr>(없으면 <li>) 한 줄을 판매기간 한 줄로 보고,
      - data-seqno: 그 행의 공시번호(같은 행에 버튼별로 여러 번 나와도 하나로 친다)
      - 판매기간: 행 텍스트의 첫 날짜=개시, 둘째=종료('현재'·없음=판매중)
      - label: 날짜·버튼 글자를 뺀 나머지(같은 기간에 공시번호가 여럿일 때 구분용, 예: 일반심사형)
    class 토큰이 정확히 'panel' 인 요소만 패널로 본다(panel-heading 등은 아님).
    """
    opens = [m for m in PANEL_OPEN.finditer(page_html) if "panel" in m.group(2).split()]
    panels = []
    prev_cut = 0
    for i, m in enumerate(opens):
        seg_end = opens[i + 1].start() if i + 1 < len(opens) else len(page_html)
        seg = page_html[m.end():seg_end]
        before = _title_candidates(page_html[prev_cut:m.start()])
        first_seq = SEQ_ATTR.search(seg)
        inside = _title_candidates(seg[:first_seq.start()] if first_seq else seg)
        title = before[-1] if before else (inside[0] if inside else "")
        last_seq = None
        for last_seq in SEQ_ATTR.finditer(seg):
            pass
        prev_cut = m.end() + (last_seq.end() if last_seq else 0)
        tag = "tr" if re.search(r"(?i)<tr\b", seg) else "li" if re.search(r"(?i)<li\b", seg) else None
        parts = re.split(rf"(?i)<{tag}\b", seg) if tag else [seg]
        rows, last_dates = [], []
        for part in parts:
            if tag:
                part = part.split(">", 1)[-1]                       # 여는 태그의 속성 부분 제거
                part = re.split(rf"(?i)</{tag}>", part)[0]          # 행 끝 이후(다음 제목 등) 제거
            seqs = list(dict.fromkeys(SEQ_ATTR.findall(part)))
            text = strip_tags(part)
            ds = dates_in(text)
            if ds:
                last_dates = ds
            if not seqs:
                continue
            ds = ds or last_dates
            label = re.sub(r"\s+", " ", NOISE.sub(" ", text.replace(title, " "))).strip(" -·,|")
            for s in seqs:
                rows.append({"seqno": s, "start": ds[0] if ds else "",
                             "end": ds[1] if len(ds) > 1 else "", "label": label})
        if rows or title:
            panels.append({"title": title, "rows": rows})
    return panels


def parse_kb_json(obj) -> list[dict]:
    """목록이 JSON API 로 올 때를 대비한 파서.

    확인 필요: 필드 이름. 'seq' 가 들어간 키(6자리 이상 숫자) = 공시번호,
    상품명은 prdt/prod/goods/product + nm/name 또는 title, 기간은 start/strt/from/bgn, end/to/cls 키.
    """
    by_title: dict[str, dict] = {}
    for d in walk_dicts(obj):
        keys = {k.lower(): k for k in d}
        seq_k = next((keys[k] for k in keys if "seq" in k and re.fullmatch(r"\d{6,}", str(d[keys[k]]))), None)
        if not seq_k:
            continue
        name_k = next((keys[k] for k in keys if re.search(r"(prdt|prod|goods|product|item).*(nm|name)|title|^name$|^nm$", k)), None)
        st_k = next((keys[k] for k in keys if re.search(r"start|strt|from|bgn|begin|stdt|st_dt|sale.*st", k)), None)
        en_k = next((keys[k] for k in keys if re.search(r"end|to_|todt|cls|close", k)), None)
        title = str(d.get(name_k, "")) if name_k else ""
        st = dates_in(str(d.get(st_k, ""))) if st_k else []
        en = dates_in(str(d.get(en_k, ""))) if en_k else []
        p = by_title.setdefault(title, {"title": title, "rows": []})
        p["rows"].append({"seqno": str(d[seq_k]), "start": st[0] if st else "",
                          "end": en[0] if en and not en[0].startswith("9999") else "", "label": ""})
    return list(by_title.values())


def parse_kb_list(text: str) -> list[dict]:
    obj = try_json(text)
    return parse_kb_json(obj) if obj is not None else parse_kb_panels(text)


def _fetch_panels(sess) -> list[dict]:
    panels = []
    for i, url in enumerate(_list_urls(), 1):
        text, _ = request(sess, SITE, f"목록{i}", "GET", url, headers={"Referer": BASE + "/"})
        got = parse_kb_list(text)
        nseq = sum(len(p["rows"]) for p in got)
        if not nseq:
            low = text.lower()
            hint = ("data-seqno 가 없습니다. 목록을 JS로 나중에 그리는 페이지일 수 있습니다 — 브라우저 개발자도구 "
                    "Network 탭에서 목록을 불러오는 API 주소를 찾아 KB_LIST_URLS 에 넣어 주세요"
                    if "data-seqno" not in low else "패널/행 구조가 예상과 다릅니다")
            fail(SITE, f"목록 주소 {url} 에서 공시번호를 하나도 읽지 못했습니다 — {hint}.", text, f"목록{i}")
        panels += got
    return panels


def _match(title: str, label: str, target: str) -> bool:
    for cand in (title, f"{title}({label})" if label else None, f"{title} {label}" if label else None):
        if cand and (norm(cand) == norm(target) or norm_loose(cand) == norm_loose(target)):
            return True
    return False


def _edition(product: str, row: dict) -> Edition:
    s = row["seqno"]
    docs = [Doc(doc_type=dt, source=DOWN_URL.format(seqno=s, box=box),
                fetch={"method": "GET", "url": DOWN_URL.format(seqno=s, box=box),
                       "headers": {"Referer": BASE + "/"}},
                orig_name=f"{s}/{box}")
            for dt, box in BOXES]
    return Edition(company=SITE, product=product, start=row["start"], end=row["end"],
                   disclosure_id=s, docs=docs)


def list_editions(sess, targets: list[str]) -> list[Edition]:
    panels = _fetch_panels(sess)
    out: list[Edition] = []
    seen = set()
    missing = []
    for target in targets:
        hits = [(p, r) for p in panels for r in p["rows"] if _match(p["title"], r["label"], target)]
        if not hits:
            missing.append(target)
            continue
        # 같은 상품·같은 개시일에 공시번호가 여럿이면(예: 0540 일반/간편 등 하위형별 공시)
        # 저장 경로(기초서류/회사/개시일/상품명/문서.pdf)가 겹치므로 상품명 뒤에 구분자를 붙인다.
        by_start: dict[str, list] = {}
        for p, r in hits:
            if r["seqno"] in seen:
                continue
            seen.add(r["seqno"])
            by_start.setdefault(r["start"], []).append(r)
        for start, rs in by_start.items():
            if not start:
                fail(SITE, f"'{target}' 공시번호 {[r['seqno'] for r in rs]} 의 판매개시일을 읽지 못했습니다.")
            for r in rs:
                name = target if len(rs) == 1 else f"{target} [{r['label'] or r['seqno']}]"
                out.append(_edition(name, r))
    if missing:
        titles = sorted({p["title"] for p in panels if p["title"]})
        msg = (f"공시실 목록에서 대상 상품을 찾지 못했습니다: {missing}\n"
               f"  목록에서 읽은 상품명 예시(최대 30개): {titles[:30]}")
        if not out or not allow_missing():
            fail(SITE, msg + "\n  (일부 누락을 허용하려면 COLLECTOR_ALLOW_MISSING=1)")
        warn(SITE, msg)
    return sorted(out, key=lambda e: (e.product, e.start))


def list_products(sess) -> list[str]:
    """판매중(종료일 없는 행이 있는) 패널의 상품명 중 건강·보장 계열."""
    panels = _fetch_panels(sess)
    names = health_only(p["title"] for p in panels if p["title"] and any(not r["end"] for r in p["rows"]))
    if not names:
        fail(SITE, "판매중 건강·보장 계열 상품명을 하나도 읽지 못했습니다.")
    return names


if __name__ == "__main__":
    consume_debug_flag()
    run("KB라이프", list_editions, list_products)
