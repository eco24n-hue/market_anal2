"""약관 끝에 붙은 분류표 부록(미래에셋 통합분류표, 신한 별첨2)을 특약 본문에서 떼어 참조 파일로 저장하고,
분류표 이름으로 해당 표의 KCD 코드를 찾아 준다.

사용:  python3 pipeline/refs.py work/seg work/trim work/ref
  - work/trim/t_<해시>.txt 에서 부록 부분을 잘라 낸다(특약 본문만 남김)
  - work/ref/<회사>_<부록해시>.txt 로 부록을 저장하고, work/ref/index.json 에 상품 → 부록 파일을 기록한다
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

CODE = re.compile(r"(?<![A-Z0-9])([A-Z]\d{2}(?:\.\d{1,2})?)(?:\s*[~∼～\-]\s*([A-Z]?\d{2}(?:\.\d{1,2})?))?")


def appendix_start(lines: list[str], company: str) -> int | None:
    if company == "미래에셋생명":
        for i, l in enumerate(lines):
            if l.strip() == "통합분류표" and "[일반사항1]" in "\n".join(lines[i:i + 400]):
                return i
    elif company == "신한라이프":
        idx = [i for i, l in enumerate(lines) if re.match(r"^\s*표\s*1\s*[｜|]\s*재해분류표", l)]
        return idx[-1] if idx else None
    return None


def shinhan_from_txt(txt: Path, out: Path, index: dict):
    """신한 별첨2는 특약 분할 전에 잘려 나가므로, 약관 텍스트에서 바로 떼어 낸다."""
    for f in sorted(txt.glob("*__신한라이프__*__약관.txt")):
        lines = f.read_text("utf-8").split("\n")
        j = appendix_start(lines, "신한라이프")
        if j is None:
            continue
        app = "\n".join(lines[j:])
        h = hashlib.sha1(re.sub(r"\s+", "", app).encode()).hexdigest()[:10]
        name = f"신한라이프_{h}.txt"
        (out / name).write_text(app, "utf-8")
        index.setdefault("신한라이프", {})[f.name.split("__")[3]] = name


def split_appendices(seg: Path, trim: Path, out: Path, txt: Path | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    index = {}
    if txt:
        shinhan_from_txt(txt, out, index)
    for u in json.loads((trim / "unique.json").read_text("utf-8")):
        full = (seg / f"u_{u['hash']}.txt").read_text("utf-8").split("\n")
        j = appendix_start(full, u["co"])
        if j is None:
            continue
        app = "\n".join(full[j:])
        h = hashlib.sha1(re.sub(r"\s+", "", app).encode()).hexdigest()[:10]
        name = f"{u['co']}_{h}.txt"
        (out / name).write_text(app, "utf-8")
        for p in u["products"]:
            index.setdefault(u["co"], {})[p] = name
        tp = trim / f"t_{u['hash']}.txt"
        t = tp.read_text("utf-8").split("\n")
        k = appendix_start(t, u["co"])
        if k is not None:
            tp.write_text("\n".join(t[:k]), "utf-8")
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
    return index


def table_sections(text: str, company: str) -> dict[str, str]:
    """부록을 표 단위로 나눈다. 키는 표 이름(미래에셋 '[암1]', 신한 '표5-1')."""
    if company == "미래에셋생명":
        head = re.compile(r"^\s*\[([^\]\n]{1,30})\]\s*$")
    else:
        head = re.compile(r"^\s*(?:-\s*\d+\s*-\s*)?(?:\[별첨2\]\s*)?(표\s*[\d\-]+)\s*(?:[｜|]|\.\s)")
    out, cur, buf = {}, None, []
    for line in text.split("\n"):
        m = head.match(line)
        if m:
            if cur:
                out.setdefault(cur, "\n".join(buf))
            cur, buf = re.sub(r"\s+", "", m.group(1)), [line]
        elif cur:
            buf.append(line)
    if cur:
        out.setdefault(cur, "\n".join(buf))
    return out


def lookup(ref_text: str, company: str, class_ref: str) -> str:
    """분류표 참조 문구(예: '통합분류표-[암1]', '<부표2-2>… 별첨2 [표 24]')에 해당하는 표 본문을 돌려준다."""
    secs = table_sections(ref_text, company)
    keys = re.findall(r"\[([^\]]{1,30})\]", class_ref) if company == "미래에셋생명" else \
        ["표" + k for k in re.findall(r"표\s*([\d\-]+)", class_ref)]
    for k in keys:
        k = re.sub(r"\s+", "", k)
        if k in secs:
            return secs[k]
    return ""


def codes(table_text: str, limit: int = 60) -> str:
    """표 본문에서 KCD 코드·범위를 순서대로 뽑아 요약한다."""
    seen, out = set(), []
    for a, b in CODE.findall(table_text):
        s = f"{a}~{b if b[:1].isalpha() else a[0] + b}" if b else a
        if s not in seen:
            seen.add(s); out.append(s)
    return ", ".join(out[:limit]) + (f" 외 {len(out) - limit}개" if len(out) > limit else "")


if __name__ == "__main__":
    seg, trim, ref = map(Path, sys.argv[1:4])
    txt = Path(sys.argv[4]) if len(sys.argv) > 4 else seg.parent / "txt"
    idx = split_appendices(seg, trim, ref, txt)
    print("부록 분리:", {co: len(set(v.values())) for co, v in idx.items()})
