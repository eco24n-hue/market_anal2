"""특약 묶음(work/clu/cXXXX.txt)을 Claude API 로 1차 추출 → 독립 검증한다.

- 출력 형식은 Claude Code 워크플로 결과와 같아서 assemble.py 가 그대로 읽는다.
- 증분 처리: 묶음 본문 해시로 결과를 work/ai/cache 에 저장하고, 본문이 같으면 다시 호출하지 않는다.
- 비용 절감: 기본은 Message Batches API(표준가의 50%). 1차 추출과 검증이 같은 원문 블록을 앞에 두어 프롬프트 캐시를 쓴다.
  검증이 '맞음'이면 결과를 다시 쓰지 않는다.
- --estimate: API 를 부르지 않고 대상 묶음 수·글자 수·대략 비용만 출력한다.

사용:
  python3 pipeline/ai_extract.py --work work --estimate
  python3 pipeline/ai_extract.py --work work --mode batch      # 주간 처리(기본)
  python3 pipeline/ai_extract.py --work work --mode sync       # 소량 즉시 처리
인증: 환경변수 ANTHROPIC_API_KEY 또는 `ant auth login` 프로필.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from pathlib import Path

MODEL = "claude-opus-5-5"
EFFORT = "high"          # 약관 정독은 정확도가 우선이라 high
MAX_TOKENS = 64000
BATCH_CHAR_CAP = 160_000  # 한 요청에 넣을 묶음 글자 수 상한
BATCH_CLUSTER_CAP = 12

NUM = {"anyOf": [{"type": "number"}, {"type": "null"}]}
S = {"type": "string"}
ROW = {"type": "object", "additionalProperties": False, "properties": {
    "benefit": S, "event": {"type": "string", "enum": ["진단", "수술", "입원", "통원", "치료", "검사", "간병/요양", "사망", "장해", "납입면제", "서비스/기타"]},
    "target": S, "definition": S, "class_refs": {"type": "array", "items": S}, "kcd": S,
    "amount_raw": S, "amount_pct": NUM, "amount_unit": S,
    "count_code": {"type": "string", "enum": ["최초1회", "연간1회", "치료별연간1회", "매회", "1일당", "기타", "미기재"]},
    "count_limit": S, "reduce_raw": S, "reduce_months": NUM, "reduce_pct": NUM,
    "exempt_raw": S, "exempt_days": NUM, "exempt_base": S, "wait_raw": S, "exclusions": S, "source": S,
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]}}}
ROW["required"] = list(ROW["properties"])
OVR = {"type": "object", "additionalProperties": False, "properties": {
    "benefit": S, "op": {"type": "string", "enum": ["set", "add_row", "remove_row"]}, "field": S, "value": S},
    "required": ["benefit", "op", "field", "value"]}
CLUSTER = {"type": "object", "additionalProperties": False, "properties": {
    "cluster_id": S, "rep_rows": {"type": "array", "items": ROW},
    "variants": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                 "properties": {"hash": S, "overrides": {"type": "array", "items": OVR}}, "required": ["hash", "overrides"]}},
    "no_benefit": {"type": "boolean"}, "issues": {"type": "array", "items": S}},
    "required": ["cluster_id", "rep_rows", "variants", "no_benefit", "issues"]}
EXTRACT_SCHEMA = {"type": "object", "additionalProperties": False,
                  "properties": {"clusters": {"type": "array", "items": CLUSTER}}, "required": ["clusters"]}
VERIFY_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {"clusters": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "properties": {
        "cluster_id": S, "verdict": {"type": "string", "enum": ["ok", "corrected"]},
        "corrected": {"anyOf": [CLUSTER, {"type": "null"}]}, "corrections": {"type": "array", "items": S}},
    "required": ["cluster_id", "verdict", "corrected", "corrections"]}}}, "required": ["clusters"]}

SYSTEM = """너는 생명보험 상품계리 전문가다. 보험 약관의 특약 묶음을 읽고 급부(보험금) 단위로 지급조건을 구조화하거나, 다른 사람이 구조화한 결과를 원문과 대조해 검증한다.

묶음 형식:
- "#### 대표 특약" 본문과, 그 아래 "#### 변형 특약"별 대표와의 차이(unified diff, -는 대표에만, +는 변형에만)가 이어진다. 묶음마다 "======== 묶음 cXXXX" 머리줄이 있다.
- 본문은 pdftotext 결과라 표 칸이 줄에 섞여 있다. 열 위치로 재조립하라.

규칙:
- 대표 특약의 모든 급부를 rep_rows 에 1행씩. 종별·구간별 금액이 다르면 각각 1행. 경과기간별 감액(1년 미만 50% 등)은 reduce_* 에 쓰고 amount_pct 는 감액 전 기준.
- 변형 특약은 diff 를 읽고 대표와 다른 점만 overrides 로. 상품명·특약명·쪽번호만 다른 diff 는 overrides 빈 배열. 모든 행에 적용되는 변경은 benefit 을 "*" 로.
- 정의(definition)와 분류표 참조(class_refs)는 원문 정의 조항에서. 분류코드가 같은 본문에 직접 있으면 kcd 에 범위 그대로, 별표·별첨·통합분류표에만 있으면 kcd 는 빈 문자열로 두고 class_refs 에 표 이름(예: 통합분류표-[암1], 별첨2 표11-2 뇌출혈 분류표)을 정확히 적어라.
- 면책: 암보장개시일 90일 같은 보장개시 규정. 별도 규정이 없으면 exempt_days=0.
- 원문에 없는 내용은 쓰지 마라. 모르면 빈 문자열/null/미기재, confidence 를 낮춰라.
- cluster_id 는 머리줄의 cXXXX 를 그대로 쓴다. 급부가 없는 제도성 특약은 no_benefit=true, rep_rows 빈 배열."""

TASK_EXTRACT = "위 묶음들 각각에 대해 결과를 하나씩 만들어라."
TASK_VERIFY = """위 묶음들을 다른 사람이 추출한 결과가 아래에 있다. 원문을 직접 끝까지 읽고 모든 행과 필드를 원문과 대조하라.
빠진 급부, 틀린 금액·횟수·감액·면책·정의·분류표 참조, 잘못 적용된 변형 차이를 찾아라.
- 고칠 것이 없으면 verdict="ok", corrected=null, corrections 빈 배열.
- 고칠 것이 있으면 verdict="corrected", corrected 에 고친 전체 결과, corrections 에 '급부/필드/전→후/근거 조항'.
- 확신이 없으면 고치지 말고 corrections 에 "확인 필요: …" 로 남겨라.

1차 추출 결과(JSON):
"""


def content_key(text: str) -> str:
    return hashlib.sha256((MODEL + EFFORT + SYSTEM + text).encode()).hexdigest()[:24]


def load_clusters(work: Path):
    meta = json.loads((work / "clu" / "clusters.json").read_text("utf-8"))
    out = []
    for c in meta:
        text = (work / "clu" / f"{c['id']}.txt").read_text("utf-8")
        out.append({"id": c["id"], "co": c["co"], "text": text, "key": content_key(text)})
    return out


def pack(items):
    batches, cur, acc = [], [], 0
    for c in sorted(items, key=lambda c: (c["co"], c["id"])):
        if cur and (acc + len(c["text"]) > BATCH_CHAR_CAP or len(cur) >= BATCH_CLUSTER_CAP or cur[0]["co"] != c["co"]):
            batches.append(cur); cur, acc = [], 0
        cur.append(c); acc += len(c["text"])
    if cur:
        batches.append(cur)
    return batches


def bundle(batch) -> str:
    return "\n\n".join(f"======== 묶음 {c['id']}\n{c['text']}" for c in batch)


def params(batch, task: str, prior=None) -> dict:
    content = [{"type": "text", "text": bundle(batch), "cache_control": {"type": "ephemeral", "ttl": "1h"}},
               {"type": "text", "text": task + (json.dumps(prior, ensure_ascii=False) if prior is not None else "")}]
    return {"model": MODEL, "max_tokens": MAX_TOKENS, "system": SYSTEM,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": EFFORT, "format": {"type": "json_schema",
                              "schema": VERIFY_SCHEMA if prior is not None else EXTRACT_SCHEMA}}}


def parse_message(msg):
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"거절됨: {getattr(msg.stop_details, 'category', None)}")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("출력이 max_tokens 에서 잘림 — 묶음을 더 작게 나눠야 함")
    text = next(b.text for b in msg.content if b.type == "text")
    return json.loads(text), msg.usage


# ---------- 실행기 ----------
class SyncRunner:
    """소량 즉시 처리. 거절 시 서버 쪽 대체 모델(fallbacks)을 쓴다."""
    def __init__(self, client):
        self.client = client

    def run(self, reqs: dict) -> dict:
        out = {}
        for cid, p in reqs.items():
            with self.client.beta.messages.stream(**p, betas=["server-side-fallback-2026-07-01"], fallbacks="default") as s:
                out[cid] = s.get_final_message()
        return out


class BatchRunner:
    """Message Batches API(50% 할인). 대체 모델(fallbacks)은 Batches 에서 쓸 수 없다."""
    def __init__(self, client, state: Path, poll: int = 60):
        self.client, self.state, self.poll = client, state, poll

    def run(self, reqs: dict, tag: str) -> dict:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request
        st = json.loads(self.state.read_text("utf-8")) if self.state.exists() else {}
        bid = st.get(tag)
        if not bid:  # 같은 단계 배치를 이미 보냈으면 이어서 기다린다(재실행 시 중복 과금 방지)
            b = self.client.messages.batches.create(requests=[Request(custom_id=cid, params=MessageCreateParamsNonStreaming(**p)) for cid, p in reqs.items()])
            bid = b.id; st[tag] = bid; self.state.write_text(json.dumps(st), "utf-8")
            print(f"배치 제출 {tag}: {bid} ({len(reqs)}건)", flush=True)
        while True:
            b = self.client.messages.batches.retrieve(bid)
            if b.processing_status == "ended":
                break
            print(f"  {tag} 진행 중: 처리 {b.request_counts.processing} · 완료 {b.request_counts.succeeded}", flush=True)
            time.sleep(self.poll)
        out = {}
        for r in self.client.messages.batches.results(bid):
            out[r.custom_id] = r.result.message if r.result.type == "succeeded" else RuntimeError(f"{r.result.type}")
        st.pop(tag, None); self.state.write_text(json.dumps(st), "utf-8")
        return out


def run(work: Path, runner, tag_prefix: str = "") -> dict:
    ai = work / "ai"; cache = ai / "cache"; cache.mkdir(parents=True, exist_ok=True)
    clusters = load_clusters(work)
    todo = [c for c in clusters if not (cache / f"{c['key']}.json").exists()]
    batches = pack(todo)
    print(f"묶음 {len(clusters)}개 중 새로 분석할 것 {len(todo)}개 → 요청 {len(batches)}건 (나머지는 캐시)", flush=True)
    usage = {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0}
    errors = []

    def add_usage(u):
        usage["input"] += u.input_tokens or 0; usage["output"] += u.output_tokens or 0
        usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0

    if batches:
        ex_req = {f"ex-{i}": params(b, TASK_EXTRACT) for i, b in enumerate(batches)}
        ex_res = runner.run(ex_req, tag_prefix + "extract") if isinstance(runner, BatchRunner) else runner.run(ex_req)
        extracted = {}
        for i, b in enumerate(batches):
            m = ex_res.get(f"ex-{i}")
            try:
                if isinstance(m, Exception) or m is None:
                    raise RuntimeError(str(m))
                data, u = parse_message(m); add_usage(u); extracted[i] = data
            except Exception as e:
                errors.append(f"추출 실패 {[c['id'] for c in b]}: {e}")
        vf_req = {f"vf-{i}": params(batches[i], TASK_VERIFY, prior=extracted[i]) for i in extracted}
        vf_res = runner.run(vf_req, tag_prefix + "verify") if isinstance(runner, BatchRunner) else runner.run(vf_req)
        for i, data in extracted.items():
            ver = None
            m = vf_res.get(f"vf-{i}")
            try:
                if isinstance(m, Exception) or m is None:
                    raise RuntimeError(str(m))
                ver, u = parse_message(m); add_usage(u)
            except Exception as e:
                errors.append(f"검증 실패 {[c['id'] for c in batches[i]]}: {e} (1차 결과만 저장, 검증 필요 표시)")
            exs = {c["cluster_id"]: c for c in data["clusters"]}
            vfs = {c["cluster_id"]: c for c in (ver or {}).get("clusters", [])}
            for c in batches[i]:
                if c["id"] not in exs:
                    errors.append(f"응답에 묶음 없음 {c['id']}"); continue
                (cache / f"{c['key']}.json").write_text(json.dumps({"extract": exs[c["id"]], "verify": vfs.get(c["id"])}, ensure_ascii=False), "utf-8")

    # 캐시에서 이번 묶음 번호로 결과를 다시 엮는다(assemble.py 입력 형식)
    results = []
    for b in pack(clusters):
        ex, vf = [], []
        for c in b:
            p = cache / f"{c['key']}.json"
            if not p.exists():
                continue
            r = json.loads(p.read_text("utf-8"))
            e = copy.deepcopy(r["extract"]); e["cluster_id"] = c["id"]; ex.append(e)
            if r["verify"]:
                v = copy.deepcopy(r["verify"]); v["cluster_id"] = c["id"]
                if v.get("corrected"):
                    v["corrected"]["cluster_id"] = c["id"]
                vf.append(v)
        if ex:
            results.append({"batch": [c["id"] for c in b], "extract": {"clusters": ex}, "verify": {"clusters": vf} if vf else None})
    (ai / "results.json").write_text(json.dumps(results, ensure_ascii=False), "utf-8")
    report = {"clusters": len(clusters), "new": len(todo), "requests": len(batches), "usage": usage, "errors": errors}
    (ai / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return report


def estimate(work: Path):
    """API 를 부르지 않는 대략 추정. 한국어 약관은 글자 1.4자당 1토큰 안팎으로 잡았다(실측 전 근사)."""
    cache = work / "ai" / "cache"
    clusters = load_clusters(work)
    todo = [c for c in clusters if not (cache / f"{c['key']}.json").exists()]
    chars = sum(len(c["text"]) for c in todo)
    tin = chars / 1.4
    # 1차 추출: 원문 입력(캐시 쓰기) + 출력 약 30%, 검증: 원문(캐시 읽기) + 1차 결과 입력 + 출력 약 10%
    out = tin * 0.30 + tin * 0.10
    price = {"input": 4.0, "cache_write_1h": 8.0, "cache_read": 0.20, "output": 20.0}  # $/MTok, claude-opus-5-5 표준가
    cost = (tin * price["cache_write_1h"] + tin * price["cache_read"] + tin * 0.30 * price["input"] + out * price["output"]) / 1e6
    print(json.dumps({"묶음": len(clusters), "새로 분석": len(todo), "요청 수": len(pack(todo)), "원문 글자": chars,
                      "추정 입력 토큰": int(tin), "추정 출력 토큰": int(out),
                      "추정 비용(USD, 표준가)": round(cost, 1), "추정 비용(USD, 배치 50%)": round(cost / 2, 1),
                      "주의": "근사치. 실제 청구는 콘솔 사용량에서 확인. 캐시가 배치 안에서 적중하지 않으면 더 나올 수 있음"},
                     ensure_ascii=False, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="work")
    ap.add_argument("--mode", choices=["batch", "sync"], default="batch")
    ap.add_argument("--estimate", action="store_true")
    a = ap.parse_args(argv)
    work = Path(a.work)
    if a.estimate:
        return estimate(work)
    import anthropic
    client = anthropic.Anthropic()
    try:
        runner = BatchRunner(client, work / "ai" / "batch_state.json") if a.mode == "batch" else SyncRunner(client)
        rep = run(work, runner)
    except anthropic.AuthenticationError:
        raise SystemExit("Claude API 인증 실패: ANTHROPIC_API_KEY 또는 `ant auth login` 을 확인하세요.")
    except TypeError as e:
        if "authentication" not in str(e):
            raise
        raise SystemExit("Claude API 키가 없습니다: 서버 환경변수 ANTHROPIC_API_KEY 를 설정한 뒤 다시 실행하세요.")
    except anthropic.RateLimitError as e:
        raise SystemExit(f"요청 한도 초과: {e.message}. 잠시 뒤 다시 실행하세요(이미 끝난 묶음은 캐시에 남음).")
    except anthropic.APIConnectionError:
        raise SystemExit("Claude API 에 연결할 수 없습니다(네트워크 확인).")
    sys.exit(1 if rep["errors"] else 0)


if __name__ == "__main__":
    main()
