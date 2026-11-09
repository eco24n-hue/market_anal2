"""건강보험 담보 레이더 웹앱 서버.

실행:  uvicorn webapp.server:app --host 0.0.0.0 --port 8000
환경변수:
  DB_PATH       담보 DB(SQLite)              기본: data/health_coverage_db.sqlite
  DOCS_ROOT     기초서류 폴더                기본: iCloud work 폴더
  STATE_DIR     개정 판별 결과 폴더          기본: state/
  WORK_DIR      작업 폴더                    기본: work/
  APP_PASSWORD  설정하면 로그인 필요(비우면 로그인 없음)
  APP_SECRET    로그인 쿠키 서명 키(APP_PASSWORD를 쓸 때 반드시 설정)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import aggregate as agg
from .jobs import Runner

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("DB_PATH", str(ROOT / "data" / "health_coverage_db.sqlite"))
DOCS_ROOT = os.path.expanduser(os.environ.get("DOCS_ROOT", "~/Library/Mobile Documents/com~apple~CloudDocs/work"))
STATE = Path(os.environ.get("STATE_DIR", ROOT / "state"))
WORK = Path(os.environ.get("WORK_DIR", ROOT / "work"))
PASSWORD = os.environ.get("APP_PASSWORD", "")
SECRET = os.environ.get("APP_SECRET", "")
DATA_DIR = ROOT / "data"
SESSION_HOURS = 12

if PASSWORD and not SECRET:
    raise SystemExit("APP_PASSWORD 를 쓰려면 APP_SECRET 도 설정해야 합니다.")

app = FastAPI(title="건강보험 담보 레이더", docs_url=None, redoc_url=None)
runner = Runner(DOCS_ROOT, STATE, WORK, DB_PATH)


# ---------- 로그인 ----------
def _sign(exp: int) -> str:
    return f"{exp}.{hmac.new(SECRET.encode(), str(exp).encode(), hashlib.sha256).hexdigest()}"


def _valid(token: str) -> bool:
    try:
        exp, _ = token.split(".", 1)
        return int(exp) > time.time() and hmac.compare_digest(token, _sign(int(exp)))
    except Exception:
        return False


@app.middleware("http")
async def guard(request: Request, call_next):
    p = request.url.path
    if PASSWORD and p.startswith("/api/") and p not in ("/api/login", "/api/health") and not _valid(request.cookies.get("sess", "")):
        return JSONResponse({"error": "로그인이 필요합니다"}, status_code=401)
    if PASSWORD and p.startswith("/download/") and not _valid(request.cookies.get("sess", "")):
        return JSONResponse({"error": "로그인이 필요합니다"}, status_code=401)
    # 실행처럼 상태를 바꾸는 요청은 같은 사이트에서 온 것만 받는다
    if request.method == "POST" and p != "/api/login" and request.headers.get("X-Requested-With") != "app":
        return JSONResponse({"error": "허용되지 않은 요청"}, status_code=403)
    return await call_next(request)


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    if not PASSWORD:
        return {"ok": True}
    if not hmac.compare_digest(str(body.get("password", "")), PASSWORD):
        time.sleep(1)
        raise HTTPException(401, "비밀번호가 맞지 않습니다")
    resp = JSONResponse({"ok": True})
    resp.set_cookie("sess", _sign(int(time.time()) + SESSION_HOURS * 3600), httponly=True, samesite="strict",
                    secure=request.url.scheme == "https", max_age=SESSION_HOURS * 3600)
    return resp


@app.get("/api/health")
def health():
    return {"ok": True, "login_required": bool(PASSWORD)}


# ---------- 조회 ----------
def _snap(snapshot: str | None) -> str:
    con = agg.connect(DB_PATH); snaps = agg.snapshots(con); con.close()
    if not snaps:
        raise HTTPException(404, "DB에 스냅샷이 없습니다")
    if snapshot and snapshot not in snaps:
        raise HTTPException(404, f"없는 스냅샷: {snapshot}")
    return snapshot or snaps[0]


@app.get("/api/meta")
def meta():
    con = agg.connect(DB_PATH); snaps = agg.snapshots(con); con.close()
    t = agg.coverage_table(DB_PATH, snaps[0]) if snaps else None
    return {"snapshots": snaps, "companies": t["companies"] if t else [], "majors": sorted({i["major"] for i in t["items"]}) if t else [],
            "docs_root": DOCS_ROOT, "docs_root_exists": os.path.isdir(DOCS_ROOT)}


@app.get("/api/coverages")
def coverages(snapshot: str | None = None, major: str = "", q: str = "", common_only: bool = False):
    t = agg.coverage_table(DB_PATH, _snap(snapshot))
    q = q.strip().lower()
    items = [i for i in t["items"] if (not major or i["major"] == major) and (not q or q in (i["standard"] + i["detail"]).lower())
             and (not common_only or len(i["by"]) == len(t["companies"]))]
    stats = {"rows": t["rows"], "details": len(t["items"]), "standards": len({i["standard"] for i in t["items"]}),
             "common_all": sum(1 for i in t["items"] if len(i["by"]) == len(t["companies"])),
             "by_company": {c: sum(1 for i in t["items"] if c in i["by"]) for c in t["companies"]}}
    return {"snapshot": t["snapshot"], "companies": t["companies"], "items": items, "stats": stats}


@app.get("/api/underwriting")
def underwriting(snapshot: str | None = None):
    t = agg.coverage_table(DB_PATH, _snap(snapshot))
    return {"companies": t["companies"], "underwriting": t["underwriting"], "products": t["products"]}


@app.get("/api/rows")
def rows(snapshot: str | None = None, company: str = "", q: str = "", page: int = Query(0, ge=0), size: int = Query(200, ge=1, le=500)):
    s = _snap(snapshot); con = agg.connect(DB_PATH)
    where, args = ["snapshot=?"], [s]
    if company: where.append("company=?"); args.append(company)
    if q: where.append("(rider like ? or detail like ? or product like ?)"); args += [f"%{q}%"] * 3
    w = " and ".join(where)
    total = con.execute(f"select count(*) from benefit_row where {w}", args).fetchone()[0]
    rs = con.execute(f"select * from benefit_row where {w} order by company, product, rider, benefit limit ? offset ?", args + [size, page * size]).fetchall()
    con.close()
    out = [{"company": r["company"], "product": r["product"], "rider": r["rider"], "uw": r["uw"], "benefit": r["benefit"], "detail": r["detail"],
            "amount": agg.amt(r), "count": agg.cnt(r), "exempt": agg.exm(r), "reduce": agg.red(r), "source": r["source"], "verify": r["verify_status"]} for r in rs]
    return {"total": total, "page": page, "size": size, "rows": out}


@app.get("/api/diff")
def snapshot_diff(old: str | None = None, new: str | None = None):
    con = agg.connect(DB_PATH); snaps = agg.snapshots(con); con.close()
    if len(snaps) < 2 and not (old and new):
        return {"available": False, "snapshots": snaps, "changes": []}
    new = new or snaps[0]; old = old or snaps[1]
    _snap(new); _snap(old)
    return {"available": True, "old": old, "new": new, "changes": agg.diff(DB_PATH, old, new)}


# ---------- 업데이트 실행 ----------
@app.post("/api/runs")
async def start_run(request: Request):
    body = await request.json()
    since = str(body.get("since") or "20260901")
    if not re.fullmatch(r"\d{8}", since):
        raise HTTPException(400, "기준일은 YYYYMMDD 8자리로 입력하세요")
    if not os.path.isdir(DOCS_ROOT):
        raise HTTPException(400, f"기초서류 폴더가 없습니다: {DOCS_ROOT}")
    mode = "sync" if body.get("mode") == "sync" else "batch"
    if not runner.start(bool(body.get("download")), since, bool(body.get("ai")), mode):
        raise HTTPException(409, "이미 실행 중입니다")
    return JSONResponse({"started": True}, status_code=202)


@app.get("/api/ai/estimate")
def ai_estimate():
    return {"estimate": runner.estimate()}


@app.get("/api/runs/latest")
def run_status():
    return {"job": runner.status(), "report": runner.latest_report()}


# ---------- 내려받기 ----------
@app.get("/api/downloads")
def downloads():
    return [{"name": p.name, "size": p.stat().st_size} for p in sorted(DATA_DIR.glob("*")) if p.suffix in (".xlsx", ".sqlite")]


@app.get("/download/{name}")
def download(name: str):
    p = (DATA_DIR / name).resolve()
    if p.parent != DATA_DIR.resolve() or p.suffix not in (".xlsx", ".sqlite") or not p.exists():
        raise HTTPException(404, "없는 파일")
    return FileResponse(p, filename=p.name)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
