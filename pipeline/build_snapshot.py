"""특약 묶음(work/clu) → AI 추출·검증 → 급부 행 → 분류코드 → 담보 판정 → 새 기준일 DB 스냅샷.

사용:  python3 pipeline/build_snapshot.py --work work --db data/health_coverage_db.sqlite [--mode batch|sync] [--snapshot YYYY-MM-DD]
"""
import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def step(name, cmd):
    print(f"▶ {name}", flush=True)
    r = subprocess.run([sys.executable, *cmd])
    if r.returncode != 0:
        raise SystemExit(f"✖ {name} 실패")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="work"); ap.add_argument("--db", default="data/health_coverage_db.sqlite")
    ap.add_argument("--mode", choices=["batch", "sync"], default="batch")
    ap.add_argument("--snapshot", default=dt.date.today().isoformat())
    a = ap.parse_args(argv)
    w = a.work
    step("AI 특약 정독·검증", [str(HERE / "ai_extract.py"), "--work", w, "--mode", a.mode])
    step("급부 행 조립", [str(HERE / "assemble.py"), w, f"{w}/ai/results.json"])
    step("분류코드 채우기", [str(HERE / "fill_kcd.py"), w])
    step("매칭키 계산", [str(HERE / "sig.py"), w])
    step("세부·표준담보 판정", [str(HERE / "ai_classify.py"), "--work", w, "--db", a.db])
    step("DB 스냅샷 쓰기", [str(HERE / "write_snapshot.py"), "--work", w, "--db", a.db, "--snapshot", a.snapshot])
    print("완료")


if __name__ == "__main__":
    main()
