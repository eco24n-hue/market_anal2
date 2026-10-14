"""공시실 수집기 공통 모듈.

저장 구조 (docs 저장소 루트 기준):
    기초서류/<회사>/<판매개시일 YYYYMMDD>/<상품명>/<문서종류>.pdf
    manifest/<회사>.json

문서종류: 약관 / 사업방법서 / 상품요약서
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests

DOC_TYPES = ("약관", "사업방법서", "상품요약서")
BASELINE = "20260901"  # 이 날짜에 유효했던 판과 그 이후 판을 받는다
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


@dataclasses.dataclass
class Doc:
    doc_type: str          # DOC_TYPES 중 하나
    source: str            # 사람이 읽을 수 있는 출처(URL 또는 요청 설명)
    fetch: dict            # requests.request(**fetch) 인자: method, url, data/params/headers
    orig_name: str = ""    # 공시실 원본 파일명


@dataclasses.dataclass
class Edition:
    company: str
    product: str           # 공시실 상품명(원문)
    start: str             # 판매개시일 YYYYMMDD
    end: str               # 판매종료일 YYYYMMDD 또는 "" (판매중)
    disclosure_id: str     # 공시번호 등 회사 고유 키(없으면 "")
    docs: list[Doc]


def safe_name(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', "_", s).strip()
    return s[:120]


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def fetch_pdf(sess: requests.Session, doc: Doc, retries: int = 3) -> bytes:
    last = None
    for i in range(retries):
        try:
            r = sess.request(timeout=300, **doc.fetch)
            r.raise_for_status()
            b = r.content
            if not b.startswith(b"%PDF"):
                raise ValueError(f"PDF 아님: {len(b)}바이트, 앞부분={b[:60]!r}")
            return b
        except Exception as e:  # 네트워크·서버 오류는 재시도
            last = e
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f"다운로드 실패 {doc.source}: {last}")


class Manifest:
    def __init__(self, root: Path, company: str):
        self.path = root / "manifest" / f"{company}.json"
        self.data = json.loads(self.path.read_text("utf-8")) if self.path.exists() else {"company": company, "editions": {}, "products_seen": {}}

    @staticmethod
    def key(e: Edition) -> str:
        return f"{e.product}|{e.start}|{e.disclosure_id}"

    def has(self, e: Edition, doc_type: str) -> bool:
        return doc_type in self.data["editions"].get(self.key(e), {}).get("docs", {})

    def add(self, e: Edition, doc: Doc, rel: str, blob: bytes, fetched_at: str):
        ent = self.data["editions"].setdefault(self.key(e), {
            "product": e.product, "start": e.start, "end": e.end, "disclosure_id": e.disclosure_id, "docs": {}})
        ent["end"] = e.end
        ent["docs"][doc.doc_type] = {"file": rel, "sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob),
                                     "source": doc.source, "orig_name": doc.orig_name, "fetched_at": fetched_at}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")


def run(company: str, list_editions, list_products=None, argv=None):
    """회사 모듈의 진입점.

    list_editions(sess, targets) -> list[Edition]   대상 상품의 모든 판
    list_products(sess) -> list[str]                건강·보장 계열 판매상품명(신상품 감지용, 선택)
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="docs 저장소 루트")
    ap.add_argument("--since", default=BASELINE)
    ap.add_argument("--dry-run", action="store_true", help="목록만 출력하고 받지 않음")
    ap.add_argument("--limit", type=int, default=0, help="테스트용: 받을 문서 수 상한")
    ap.add_argument("--fetched-at", default=time.strftime("%Y-%m-%dT%H:%M:%S"))
    a = ap.parse_args(argv)
    root = Path(a.root)
    targets = [p["상품명"] for p in json.loads((Path(__file__).parent / "products.json").read_text("utf-8")).get(company, [])]
    sess = session()
    man = Manifest(root, company)
    report = {"company": company, "new_docs": [], "new_products": [], "errors": []}

    if list_products:
        try:
            for name in list_products(sess):
                if name not in man.data["products_seen"]:
                    man.data["products_seen"][name] = a.fetched_at
                    report["new_products"].append(name)
        except Exception as e:
            report["errors"].append(f"상품목록 조회 실패: {e}")

    eds = list_editions(sess, targets)
    # 기준일에 유효했던 판(종료일이 기준일 이후이거나 판매중)과 그 이후 판을 받는다.
    # 기준일 이후 개시분만 받으면 7월판이 현행인 상품은 기준선에서 빠진다.
    eds = [e for e in eds if not e.end or e.end >= a.since]
    n = 0
    for e in eds:
        for d in e.docs:
            if man.has(e, d.doc_type):
                continue
            rel = f"기초서류/{company}/{e.start}/{safe_name(e.product)}/{d.doc_type}.pdf"
            if a.dry_run:
                report["new_docs"].append({"file": rel, "source": d.source})
                continue
            if a.limit and n >= a.limit:
                break
            try:
                blob = fetch_pdf(sess, d)
            except Exception as ex:
                report["errors"].append(str(ex))
                continue
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(blob)
            man.add(e, d, rel, blob, a.fetched_at)
            report["new_docs"].append({"file": rel, "size": len(blob)})
            n += 1
    if not a.dry_run:
        man.save()
    json.dump(report, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return report
