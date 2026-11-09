"""급부 행에 세부담보·표준담보를 붙인다.

순서: ① 직전 기준일 DB 에 같은 (회사, 보장사건, 급부명, 보장대상) 이 있으면 그 판정을 그대로 쓴다
      ② 없으면 보장사건 그룹별로 Claude API 에 판정을 맡긴다(기존 담보 이름 목록을 함께 줘 이름을 맞춘다)
결과: work/cls_map.json (sig → 판정)

사용:  python3 pipeline/ai_classify.py --work work --db data/health_coverage_db.sqlite [--offline]
  --offline : API 를 부르지 않고 ①만 수행(남은 건수만 보고)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

MODEL = "claude-opus-5-5"
GROUPS = {"진단": ["진단"], "수술": ["수술"], "치료·검사": ["치료", "검사"], "입원·통원·기타": ["입원", "통원", "간병/요양", "사망", "장해", "납입면제", "서비스/기타"]}
S = {"type": "string"}
SCHEMA = {"type": "object", "additionalProperties": False, "properties": {"items": {"type": "array", "items": {
    "type": "object", "additionalProperties": False,
    "properties": {"sig": S, "major": S, "standard": S, "detail": S, "disease_group": S, "pay_form": S, "basis": S},
    "required": ["sig", "major", "standard", "detail", "disease_group", "pay_form", "basis"]}}}, "required": ["items"]}
SYSTEM = """너는 생명보험 상품개발 전문가다. 보험 약관에서 뽑은 급부에 세부담보명과 표준담보명을 붙인다.
1. 담보명, 정의, 분류코드를 모두 읽고 세부담보명을 정한다.
2. 회사가 달라도 정의와 분류코드(보장 범위)가 실질적으로 같으면 반드시 같은 세부담보명과 표준담보명을 쓴다. 표기 차이는 무시하고 실제 코드 범위를 비교한다. 범위가 하나라도 다르면 나눈다.
3. 표준담보 = 세부담보들의 공통 부분(보장사건 + 질병군 + 지급형태).
4. 세부담보명은 범위가 드러나게(괄호에 핵심 범위). 갱신형·간편·D형 같은 상품 유형, 금액·감액·면책 차이는 나누는 기준이 아니다.
5. 기존 담보 목록에 범위가 같은 것이 있으면 그 이름을 그대로 쓴다. 범위 판단이 불확실하면 basis 를 "확인 필요:" 로 시작한다.
모든 sig 에 정확히 1개씩 답한다."""


def key(company, event, benefit, target):
    return (company, event, (benefit or "").replace(" ", ""), (target or "").replace(" ", ""))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="work"); ap.add_argument("--db", default="data/health_coverage_db.sqlite")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)
    work = Path(a.work)
    rows = json.loads((work / "rows_all.json").read_text("utf-8"))
    prev, vocab = {}, {}
    if Path(a.db).exists():
        con = sqlite3.connect(a.db); con.row_factory = sqlite3.Row
        snap = con.execute("select max(snapshot) from benefit_row").fetchone()[0]
        for r in con.execute("select * from benefit_row where snapshot=?", (snap,)):
            prev.setdefault(key(r["company"], r["event"], r["benefit"], r["target"]),
                            {k: r[k] for k in ("major", "standard", "detail")} | {"disease_group": "", "pay_form": "", "basis": "직전 기준일 판정 재사용"})
            vocab.setdefault(r["detail"], {"대분류": r["major"], "표준담보": r["standard"], "세부담보": r["detail"], "분류코드": (r["kcd"] or "")[:80]})
        con.close()
    out, todo = {}, {}
    for r in rows:
        if r["sig"] in out or r["sig"] in todo:
            continue
        hit = prev.get(key(r["company"], r["event"], r["benefit"], r["target"]))
        if hit:
            out[r["sig"]] = hit
        else:
            todo[r["sig"]] = {"sig": r["sig"], "company": r["company"], "event": r["event"], "benefit": r["benefit"], "target": r["target"],
                              "kcd": r.get("kcd", ""), "class_refs": r.get("class_refs", []), "definition": (r.get("definition") or "")[:260]}
    print(f"판정 재사용 {len(out)}종 · 새로 판정할 급부 {len(todo)}종")
    if todo and not a.offline:
        import anthropic
        client = anthropic.Anthropic()
        voc = json.dumps(list(vocab.values()), ensure_ascii=False)
        for g, evs in GROUPS.items():
            items = [t for t in todo.values() if t["event"] in evs]
            if not items:
                continue
            content = [{"type": "text", "text": "기존 담보 목록(JSON):\n" + voc, "cache_control": {"type": "ephemeral"}},
                       {"type": "text", "text": f"판정할 급부(그룹: {g}, JSON):\n" + json.dumps(items, ensure_ascii=False)}]
            with client.beta.messages.stream(model=MODEL, max_tokens=64000, system=SYSTEM, messages=[{"role": "user", "content": content}],
                                             output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
                                             betas=["server-side-fallback-2026-07-01"], fallbacks="default") as s:
                msg = s.get_final_message()
            if msg.stop_reason != "end_turn":
                print(f"[{g}] 판정 실패: stop_reason={msg.stop_reason}", file=sys.stderr); continue
            for it in json.loads(next(b.text for b in msg.content if b.type == "text"))["items"]:
                if it["sig"] in todo:
                    out[it["sig"]] = it
            print(f"[{g}] {len(items)}종 판정")
    missing = [s for s in todo if s not in out]
    (work / "cls_map.json").write_text(json.dumps(out, ensure_ascii=False), "utf-8")
    print(f"판정 완료 {len(out)}종 · 미판정 {len(missing)}종")
    sys.exit(1 if missing and not a.offline else 0)


if __name__ == "__main__":
    main()
