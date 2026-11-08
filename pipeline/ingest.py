"""기초서류 폴더를 읽어 회사·개정일·문서종류·상품명을 판별하고, 지난 실행과 비교해 새로 들어오거나 바뀐 파일을 찾는다.

폴더 구조가 일정하지 않아도 된다. 판별 순서:
  회사     : 파일명 → 가까운 상위 폴더명 순으로 folder_rules.json 의 별칭을 찾는다
  개정일   : 파일명의 날짜(YYYYMMDD, YYMMDD, YYYYMM) → 상위 폴더명의 날짜
  문서종류 : 파일명 → 상위 폴더명(01_상품요약서 등)
판별하지 못한 파일은 버리지 않고 '판별 실패' 목록에 남긴다.

사용:
  python3 pipeline/ingest.py --docs-root "~/Library/Mobile Documents/com~apple~CloudDocs/work" --state state/
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

RULES = json.loads((Path(__file__).parent / "folder_rules.json").read_text("utf-8"))
DATE_PATTERNS = [
    (re.compile(r"(?<!\d)(20\d{2})[-.]?(0[1-9]|1[0-2])[-.]?(0[1-9]|[12]\d|3[01])(?!\d)"), lambda m: m.group(1) + m.group(2) + m.group(3)),
    (re.compile(r"(?<!\d)(2\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)"), lambda m: "20" + m.group(1) + m.group(2) + m.group(3)),
    (re.compile(r"(?<!\d)(20\d{2})[-.]?(0[1-9]|1[0-2])(?!\d)"), lambda m: m.group(1) + m.group(2) + "01"),
    (re.compile(r"^(2\d)(0[1-9]|1[0-2])$"), lambda m: "20" + m.group(1) + m.group(2) + "01"),  # '2601' 같은 폴더명
]


def nfc(s: str) -> str:
    # macOS/iCloud 는 한글 파일명을 NFD 로 저장한다. 비교 전에 NFC 로 맞춘다.
    return unicodedata.normalize("NFC", s)


def find_date(text: str) -> str:
    for pat, fmt in DATE_PATTERNS:
        m = pat.search(text)
        if m:
            return fmt(m)
    return ""


def find_company(text: str) -> str:
    best = ("", -1)
    for co, aliases in RULES["companies"].items():
        for a in aliases:
            i = text.find(a)
            if i >= 0 and (best[1] < 0 or i < best[1]):
                best = (co, i)
    return best[0]


def find_doc_type(text: str) -> str:
    for dt_, keys in RULES["doc_types"].items():
        if any(k in text for k in keys):
            return dt_
    return ""


def doc_type_from_content(p: Path) -> str:
    """파일명이 잘려 문서종류를 알 수 없을 때 PDF 첫 두 쪽 글자로 판별한다(pdftotext 또는 pypdf 필요)."""
    text = ""
    if shutil.which("pdftotext"):
        try:
            text = subprocess.run(["pdftotext", "-f", "1", "-l", "2", str(p), "-"], capture_output=True, timeout=60).stdout.decode("utf-8", "ignore")
        except Exception:
            text = ""
    if not text:
        try:
            import logging
            logging.getLogger("pypdf").setLevel(logging.ERROR)
            from pypdf import PdfReader
            text = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages[:2])
        except Exception:
            return ""
    text = re.sub(r"\s+", "", nfc(text))
    for dt_, key in (("사업방법서", "사업방법서"), ("상품요약서", "상품요약서"), ("약관", "약관")):
        if key in text:
            return dt_
    return ""


def product_name(stem: str, doc_type: str) -> str:
    s = re.sub(r"^\d+\.\s*", "", stem)
    s = re.sub(r"_?\d{9,}", "", s)                                 # 9자리 이상 공시번호
    s = re.sub(r"^(?:\d{6,}|KLT\d+)_", "", s)                       # 앞쪽 공시번호·문서코드
    s = re.sub(r"^(판매약관|사업방법서|통합약관|상품요약서)_", "", s)
    for k in sum(RULES["doc_types"].values(), []):
        s = s.replace("_" + k, "_").replace(k + "_", "_")
    s = re.sub(r"[_(\[]?\d{6,8}(?:_[\d~_]+)?[)\]]?", "", s)          # 날짜·코드 묶음
    s = re.sub(r"\(\d{6}\)|_v[\d.]+|_음영제거|_opt|_공시용|_공시|_신체부위설명도", "", s)
    s = re.sub(r"\[[\d\s_,~]+\]|[\s_]*,?[\d\s_~,]{5,}\)?$", "", s)          # 대괄호·꼬리의 보종코드 묶음
    s = re.sub(r"_+", " ", s).strip(" _-")
    s = re.sub(r"\s+(\(\d*|[가-힣\u1100-\u11ff]{1,2}(\s\d)?)$", "", s)  # iCloud가 잘라 남긴 꼬리
    return s


def folder_product(parts: list[str]) -> str:
    """파일명이 '약관.pdf'처럼 상품명을 담지 않을 때, 가까운 폴더 중 회사·날짜·문서종류만 있는 이름이 아닌 것을 상품명으로 쓴다."""
    for d in reversed(parts):
        rest = d
        for k in sum(RULES["companies"].values(), []) + sum(RULES["doc_types"].values(), []) + ["기초서류", "건강보험"]:
            rest = rest.replace(k, "")
        rest = re.sub(r"[\d_\-. ]", "", rest)
        if len(rest) >= 2:
            return product_name(d, "")
    return ""


def product_from(stem: str, doc: str, parts: list[str]) -> str:
    p = product_name(stem, doc)
    if not p or p in sum(RULES["doc_types"].values(), []):
        p = folder_product(parts)
    return p


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(root: Path) -> tuple[list[dict], list[dict]]:
    files, not_local = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = [d for d in dirnames if nfc(d) not in RULES["skip_dirs"] and not nfc(d).startswith(tuple(RULES["skip_prefixes"]))]
        for fn in filenames:
            name = nfc(fn)
            # iCloud '저장 공간 최적화'로 아직 내려받지 않은 파일은 '.이름.pdf.icloud' 로 보인다
            if name.startswith(".") and name.endswith(".icloud"):
                not_local.append({"path": nfc(str(rel_dir / name[1:-7]))})
                continue
            if name.startswith(tuple(RULES["skip_prefixes"])) or not name.lower().endswith(".pdf"):
                continue
            p = Path(dirpath) / fn
            parts = [nfc(x) for x in rel_dir.parts]
            stem = name[:-4]
            # 가까운 폴더부터 거슬러 올라가며 빈 값을 채운다
            co = find_company(stem); date_file = find_date(stem); doc = find_doc_type(stem)
            date_dir = ""
            for d in reversed(parts):
                co = co or find_company(d)
                date_dir = date_dir or find_date(d)
                doc = doc or find_doc_type(d)
            doc_src = "이름"
            if not doc:
                doc = doc_type_from_content(p); doc_src = "내용" if doc else ""
            st = p.stat()
            files.append({
                "path": nfc(str(rel_dir / fn)), "company": co, "edition": date_file or date_dir,
                "date_in_name": date_file, "date_in_folder": date_dir, "doc_type": doc, "doc_type_from": doc_src,
                "product": product_from(stem, doc, parts), "size": st.st_size,
                "mtime": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                "sha256": sha256(p),
            })
    return files, not_local


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs-root", default=os.environ.get("DOCS_ROOT", "~/Library/Mobile Documents/com~apple~CloudDocs/work"))
    ap.add_argument("--state", default=os.environ.get("PIPELINE_STATE", str(Path(__file__).resolve().parent.parent / "state")))
    ap.add_argument("--run-date", default=dt.date.today().isoformat())
    a = ap.parse_args(argv)
    root = Path(os.path.expanduser(a.docs_root)); state = Path(a.state); state.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise SystemExit(f"기초서류 폴더를 찾을 수 없습니다: {root}")
    files, not_local = scan(root)

    ok = [f for f in files if f["company"] and f["edition"] and f["doc_type"]]
    bad = [dict(f, 이유=", ".join(k for k, v in (("회사", f["company"]), ("개정일", f["edition"]), ("문서종류", f["doc_type"])) if not v)) for f in files if f not in ok]
    # 같은 파일이 같은 회사·상품·문서로 두 번 있으면(예: 2601 폴더와 회사 폴더) 하나만 쓴다.
    # 여러 상품이 같은 파일을 함께 쓰는 경우(공유 사업방법서 등)는 상품별로 모두 남기고 shared_with 로 표시한다.
    seen, uniq, dup, by_sha = set(), [], [], {}
    for f in sorted(ok, key=lambda f: (f["company"], f["edition"], f["path"])):
        k = (f["sha256"], f["company"], f["product"], f["doc_type"])
        if k in seen:
            dup.append({"path": f["path"]}); continue
        seen.add(k); uniq.append(f); by_sha.setdefault(f["sha256"], []).append(f["path"])
    for f in uniq:
        f["shared_with"] = [x for x in by_sha[f["sha256"]] if x != f["path"]]

    prev_p = state / "catalog.json"
    prev_files = json.loads(prev_p.read_text("utf-8"))["files"] if prev_p.exists() else []
    prev = {(f["sha256"], f["path"]): f for f in prev_files}
    prev_sha = {f["sha256"] for f in prev_files}
    prev_by_key = {(f["company"], f["product"], f["doc_type"]): f for f in prev_files}
    diff = {"new": [], "changed": [], "removed": []}
    for f in uniq:
        if f["sha256"] in prev_sha:
            continue
        old = prev_by_key.get((f["company"], f["product"], f["doc_type"]))
        diff["changed" if old else "new"].append({**{k: f[k] for k in ("company", "product", "doc_type", "edition", "path")}, **({"previous_edition": old["edition"], "previous_path": old["path"]} if old else {})})
    cur = {f["sha256"] for f in uniq}
    diff["removed"] = [{k: f[k] for k in ("company", "product", "doc_type", "edition", "path")} for f in prev_files if f["sha256"] not in cur]

    out = {"run_date": a.run_date, "docs_root": str(root), "files": uniq}
    prev_p.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    (state / "history").mkdir(exist_ok=True)
    (state / "history" / f"catalog_{a.run_date}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    report = {"run_date": a.run_date, "판별": len(uniq), "중복": len(dup), "판별 실패": bad, "iCloud 미다운로드": not_local, "변경": diff}
    (state / f"ingest_report_{a.run_date}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")

    by = {}
    for f in uniq: by.setdefault(f["company"], set()).add(f["edition"])
    print(f"기초서류 {len(uniq)}개 판별 (중복 {len(dup)}개 제외)")
    for co, eds in sorted(by.items()): print(f"  {co}: {len(eds)}개 개정일 {sorted(eds)[-3:]}")
    print(f"새 파일 {len(diff['new'])} · 개정 {len(diff['changed'])} · 삭제 {len(diff['removed'])}")
    if bad: print(f"판별 실패 {len(bad)}개 → {state}/ingest_report_{a.run_date}.json 의 '판별 실패' 확인, folder_rules.json 에 규칙 추가")
    if not_local: print(f"iCloud에서 아직 내려받지 않은 파일 {len(not_local)}개: Finder에서 work 폴더를 우클릭 → '다운로드 유지'")
    return report


if __name__ == "__main__":
    main()
