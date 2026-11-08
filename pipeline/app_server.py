"""로컬 앱 서버: 담보 비교 화면에 '실행' 버튼을 붙여, 누르면 기초서류 폴더의 개정판을 읽어 온다.

Mac 에서:
  python3 pipeline/app_server.py            → 브라우저에서 http://127.0.0.1:8765
설정(환경변수):
  DOCS_ROOT  기초서류 폴더 (기본: iCloud work 폴더)
  APP_PORT   포트 (기본 8765)

실행 버튼이 하는 일(백그라운드):
  1. (선택) collectors/*.py 로 공시실에서 새 개정판 다운로드 → DOCS_ROOT/기초서류/<회사>/<개정일>/
  2. pipeline/ingest.py  : 폴더 전체를 다시 읽어 새 파일·개정 파일·삭제 파일 판별
  3. pipeline/stage_text.py : 바뀐 PDF 만 텍스트로 변환
  4. segment.py → trim.py → cluster.py : 특약 단위 분할(신한·미래에셋 서식)
서버는 127.0.0.1 에만 열리고, 실행 요청은 같은 주소에서 온 것만 받는다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPE = ROOT / "pipeline"
DOCS_ROOT = os.path.expanduser(os.environ.get("DOCS_ROOT", "~/Library/Mobile Documents/com~apple~CloudDocs/work"))
STATE = ROOT / "state"
WORK = ROOT / "work"
PAGE = ROOT / "docs" / "coverage-standardization.html"
PORT = int(os.environ.get("APP_PORT", "8765"))
COLLECTORS = ["shinhan", "mirae", "hana", "kb", "dongyang", "heungkuk"]

JOB = {"running": False, "step": "", "log": [], "started": "", "finished": "", "ok": None, "report": None}
LOCK = threading.Lock()


def log(msg: str):
    with LOCK:
        JOB["log"].append(f"{dt.datetime.now():%H:%M:%S} {msg}")
        JOB["log"] = JOB["log"][-400:]


def step(name: str, cmd: list[str], must: bool = True) -> bool:
    with LOCK:
        JOB["step"] = name
    log(f"▶ {name}")
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    for line in p.stdout:
        line = line.rstrip()
        if line:
            log("   " + line[:300])
    p.wait()
    if p.returncode != 0:
        log(f"✖ {name} 실패 (종료코드 {p.returncode})")
        return not must
    log(f"✔ {name}")
    return True


def run_job(opts: dict):
    today = dt.date.today().isoformat()
    ok = True
    try:
        if opts.get("download"):
            for c in COLLECTORS:
                if (ROOT / "collectors" / f"{c}.py").exists():
                    step(f"공시실 다운로드: {c}", [sys.executable, f"collectors/{c}.py", "--root", DOCS_ROOT], must=False)
        ok = step("기초서류 폴더 읽기(개정 판별)", [sys.executable, str(PIPE / "ingest.py"), "--docs-root", DOCS_ROOT,
                                         "--state", str(STATE), "--run-date", today])
        if ok:
            ok = step("바뀐 PDF 텍스트 변환", [sys.executable, str(PIPE / "stage_text.py"), "--state", str(STATE),
                                         "--out", str(WORK / "txt"), "--since", opts.get("since") or "20260901"])
        if ok and opts.get("segment", True):
            ok = (step("특약 단위 분할", [sys.executable, str(PIPE / "segment.py"), str(WORK / "txt"), str(WORK / "seg")])
                  and step("필요 조항 추리기", [sys.executable, str(PIPE / "trim.py"), str(WORK / "seg"), str(WORK / "trim")])
                  and step("특약 계열 묶기", [sys.executable, str(PIPE / "cluster.py"), str(WORK / "trim"), str(WORK / "clu")]))
        rp = STATE / f"ingest_report_{today}.json"
        rep = json.loads(rp.read_text("utf-8")) if rp.exists() else None
        with LOCK:
            JOB["report"] = rep
    except Exception as e:  # 예기치 못한 오류도 화면에 보이게 한다
        log(f"✖ 오류: {e}")
        ok = False
    with LOCK:
        JOB.update(running=False, step="", ok=ok, finished=dt.datetime.now().isoformat(timespec="seconds"))
    log("완료" if ok else "실패로 끝남 — 위 기록 확인")


PANEL = """
<section id="runner" style="display:flex;flex-direction:column;gap:12px">
  <div class="sec-head"><span class="eyebrow">기초서류 업데이트</span><h2>개정된 기초서류 읽어오기</h2></div>
  <p class="muted" style="font-size:14px">기초서류 폴더: <code id="run-root"></code></p>
  <div class="controls">
    <button type="button" class="chip" id="run-btn" style="background:var(--accent);color:var(--surface);border-color:var(--accent);font-weight:600;padding:8px 18px">실행</button>
    <label><input type="checkbox" id="run-dl"> 공시실에서 새 개정판 먼저 다운로드</label>
    <label for="run-since" style="margin-left:8px">기준일</label>
    <input id="run-since" value="20260901" style="font:inherit;font-size:13px;width:7.5em;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--fg)">
    <span id="run-state" class="muted" style="font-size:13px"></span>
  </div>
  <div id="run-result"></div>
  <details><summary class="muted" style="font-size:13px;cursor:pointer">실행 기록</summary>
    <pre id="run-log" style="max-height:260px;overflow:auto;font-size:12px;background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:10px;white-space:pre-wrap"></pre></details>
</section>
"""

SCRIPT = """
<script>
(() => {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  let timer = null;
  function table(title, rows, cols) {
    if (!rows || !rows.length) return `<p class="muted" style="font-size:13px">${title}: 없음</p>`;
    return `<h3 style="margin:6px 0">${title} ${rows.length}건</h3><div class="tbl-wrap"><table><thead><tr>${cols.map(c => `<th>${c[1]}</th>`).join("")}</tr></thead><tbody>` +
      rows.map(r => `<tr>${cols.map(c => `<td class="wrap">${esc(r[c[0]])}</td>`).join("")}</tr>`).join("") + `</tbody></table></div>`;
  }
  function show(s) {
    $("run-btn").disabled = s.running;
    $("run-btn").textContent = s.running ? "실행 중…" : "실행";
    $("run-state").textContent = s.running ? `진행: ${s.step}` : (s.finished ? `마지막 실행 ${s.finished} · ${s.ok ? "정상" : "실패"}` : "");
    $("run-log").textContent = (s.log || []).join("\\n");
    const r = s.report;
    if (r) {
      const d = r["변경"] || {};
      $("run-result").innerHTML =
        `<div class="kpis"><div class="kpi"><span>판별한 기초서류</span><b>${r["판별"]}</b></div><div class="kpi"><span>새 파일</span><b>${(d.new||[]).length}</b></div>` +
        `<div class="kpi"><span>개정</span><b>${(d.changed||[]).length}</b></div><div class="kpi"><span>삭제</span><b>${(d.removed||[]).length}</b></div>` +
        `<div class="kpi"><span>판별 실패</span><b>${(r["판별 실패"]||[]).length}</b></div><div class="kpi"><span>iCloud 미다운로드</span><b>${(r["iCloud 미다운로드"]||[]).length}</b></div></div>` +
        table("개정된 기초서류", d.changed, [["company","회사"],["product","상품"],["doc_type","문서"],["previous_edition","이전 판"],["edition","새 판"]]) +
        table("새로 들어온 기초서류", d.new, [["company","회사"],["product","상품"],["doc_type","문서"],["edition","개정일"],["path","위치"]]) +
        table("판별 실패", r["판별 실패"], [["path","파일"],["이유","판별 못한 항목"]]) +
        table("iCloud에서 아직 내려받지 않은 파일", r["iCloud 미다운로드"], [["path","파일"]]);
    }
    if (!s.running && timer) { clearInterval(timer); timer = null; }
  }
  async function poll() { try { show(await (await fetch("/api/status")).json()); } catch (e) { $("run-state").textContent = "앱 서버에 연결할 수 없습니다"; } }
  $("run-btn").addEventListener("click", async () => {
    const res = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "app" },
      body: JSON.stringify({ download: $("run-dl").checked, since: $("run-since").value.trim() }) });
    const j = await res.json(); if (!res.ok) { $("run-state").textContent = j.error || "실행할 수 없습니다"; return; }
    if (!timer) timer = setInterval(poll, 1500); poll();
  });
  fetch("/api/config").then(r => r.json()).then(c => { $("run-root").textContent = c.docs_root; });
  poll().then(() => { fetch("/api/status").then(r => r.json()).then(s => { if (s.running && !timer) timer = setInterval(poll, 1500); }); });
})();
</script>
"""


def page() -> bytes:
    html = PAGE.read_text("utf-8")
    html = html.replace("</header>", "</header>\n" + PANEL, 1)
    head = '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>'
    return (head + html + SCRIPT + "</body></html>").encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, page(), "text/html; charset=utf-8")
        if self.path == "/api/status":
            with LOCK:
                return self._json(200, JOB)
        if self.path == "/api/config":
            return self._json(200, {"docs_root": DOCS_ROOT, "exists": os.path.isdir(DOCS_ROOT)})
        self._json(404, {"error": "없는 주소"})

    def do_POST(self):
        if self.path != "/api/run":
            return self._json(404, {"error": "없는 주소"})
        # 다른 사이트가 이 서버로 실행 요청을 보내지 못하게 막는다
        origin = self.headers.get("Origin", "")
        if self.headers.get("X-Requested-With") != "app" or (origin and not origin.startswith(("http://127.0.0.1", "http://localhost"))):
            return self._json(403, {"error": "허용되지 않은 요청"})
        if not os.path.isdir(DOCS_ROOT):
            return self._json(400, {"error": f"기초서류 폴더가 없습니다: {DOCS_ROOT}"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            opts = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            opts = {}
        since = str(opts.get("since") or "20260901")
        if not (since.isdigit() and len(since) == 8):
            return self._json(400, {"error": "기준일은 YYYYMMDD 8자리로 입력하세요"})
        with LOCK:
            if JOB["running"]:
                return self._json(409, {"error": "이미 실행 중입니다"})
            JOB.update(running=True, step="시작", log=[], started=dt.datetime.now().isoformat(timespec="seconds"), finished="", ok=None)
        threading.Thread(target=run_job, args=({"download": bool(opts.get("download")), "since": since},), daemon=True).start()
        self._json(202, {"started": True})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"담보 레이더 로컬 앱: http://127.0.0.1:{PORT}  (기초서류 폴더: {DOCS_ROOT})")
    srv.serve_forever()
