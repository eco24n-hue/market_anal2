"""급부 행의 분류코드가 비어 있고 분류표 참조만 있으면, 부록(work/ref)에서 그 표를 찾아 KCD 를 채운다.

사용:  python3 pipeline/fill_kcd.py work
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import refs  # noqa: E402

work = Path(sys.argv[1])
rows = json.loads((work / "rows_all.json").read_text("utf-8"))
idx = json.loads((work / "ref" / "index.json").read_text("utf-8")) if (work / "ref" / "index.json").exists() else {}
texts, n = {}, 0
for r in rows:
    if r.get("kcd") or not r.get("class_refs"):
        continue
    name = idx.get(r["company"], {}).get(r["product"]) or next(iter(idx.get(r["company"], {}).values()), None)
    if not name:
        continue
    t = texts.setdefault(name, (work / "ref" / name).read_text("utf-8"))
    found = [(c, refs.codes(refs.lookup(t, r["company"], c))) for c in r["class_refs"]]
    found = [(c, k) for c, k in found if k]
    if found:
        r["kcd"] = "; ".join(k for _, k in found)
        r["kcd_source"] = "분류표 조회: " + ", ".join(c for c, _ in found)
        n += 1
(work / "rows_all.json").write_text(json.dumps(rows, ensure_ascii=False), "utf-8")
print(f"분류코드 채움 {n}행 / 전체 {len(rows)}행")
