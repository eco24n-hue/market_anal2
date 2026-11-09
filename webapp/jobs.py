"""'업데이트 실행' 작업: 공시실 다운로드(선택) → 폴더 읽기(개정 판별) → 텍스트 변환 → 특약 분할."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLLECTORS = ["shinhan", "mirae", "hana", "kb", "dongyang", "heungkuk"]


class Runner:
    def __init__(self, docs_root: str, state: Path, work: Path, db_path: str = ""):
        self.docs_root, self.state, self.work, self.db_path = docs_root, state, work, db_path
        self.lock = threading.Lock()
        self.job = {"running": False, "step": "", "log": [], "started": "", "finished": "", "ok": None, "options": {}}

    def status(self):
        with self.lock:
            return json.loads(json.dumps(self.job))

    def _log(self, msg):
        with self.lock:
            self.job["log"].append(f"{dt.datetime.now():%H:%M:%S} {msg}")
            self.job["log"] = self.job["log"][-400:]

    def _step(self, name, cmd, must=True):
        with self.lock:
            self.job["step"] = name
        self._log(f"▶ {name}")
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        for line in p.stdout:
            if line.strip():
                self._log("   " + line.rstrip()[:300])
        p.wait()
        if p.returncode != 0:
            self._log(f"✖ {name} 실패 (종료코드 {p.returncode})")
            return not must
        self._log(f"✔ {name}")
        return True

    def start(self, download: bool, since: str, ai: bool = False, mode: str = "batch") -> bool:
        with self.lock:
            if self.job["running"]:
                return False
            self.job.update(running=True, step="시작", log=[], ok=None, finished="",
                            started=dt.datetime.now().isoformat(timespec="seconds"), options={"download": download, "since": since, "ai": ai, "mode": mode})
        threading.Thread(target=self._run, args=(download, since, ai, mode), daemon=True).start()
        return True

    def _run(self, download, since, ai=False, mode="batch"):
        py, today = sys.executable, dt.date.today().isoformat()
        ok = True
        try:
            if download:
                for c in COLLECTORS:
                    if (ROOT / "collectors" / f"{c}.py").exists():
                        self._step(f"공시실 다운로드: {c}", [py, f"collectors/{c}.py", "--root", self.docs_root], must=False)
            ok = self._step("기초서류 폴더 읽기(개정 판별)", [py, "pipeline/ingest.py", "--docs-root", self.docs_root, "--state", str(self.state), "--run-date", today])
            ok = ok and self._step("바뀐 PDF 텍스트 변환", [py, "pipeline/stage_text.py", "--state", str(self.state), "--out", str(self.work / "txt"), "--since", since])
            ok = ok and self._step("특약 단위 분할", [py, "pipeline/segment.py", str(self.work / "txt"), str(self.work / "seg")])
            ok = ok and self._step("필요 조항 추리기", [py, "pipeline/trim.py", str(self.work / "seg"), str(self.work / "trim")])
            ok = ok and self._step("분류표 부록 분리", [py, "pipeline/refs.py", str(self.work / "seg"), str(self.work / "trim"), str(self.work / "ref"), str(self.work / "txt")])
            ok = ok and self._step("특약 계열 묶기", [py, "pipeline/cluster.py", str(self.work / "trim"), str(self.work / "clu")])
            if ok and ai:
                ok = self._step("AI 분석·새 기준일 DB 만들기", [py, "pipeline/build_snapshot.py", "--work", str(self.work), "--db", self.db_path, "--mode", mode])
        except Exception as e:
            self._log(f"✖ 오류: {e}"); ok = False
        with self.lock:
            self.job.update(running=False, step="", ok=ok, finished=dt.datetime.now().isoformat(timespec="seconds"))
        self._log("완료" if ok else "실패로 끝남 — 위 기록 확인")

    def estimate(self):
        """AI 분석 비용 추정(API 호출 없음). 특약 묶음이 아직 없으면 None."""
        if not (self.work / "clu" / "clusters.json").exists():
            return None
        r = subprocess.run([sys.executable, "pipeline/ai_extract.py", "--work", str(self.work), "--estimate"], cwd=ROOT, capture_output=True, text=True)
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            return None

    def latest_report(self):
        reps = sorted(self.state.glob("ingest_report_*.json"))
        return json.loads(reps[-1].read_text("utf-8")) if reps else None
