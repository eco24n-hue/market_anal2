#!/bin/bash
# 하나생명·KB라이프·동양생명 공시실 주간 수집 (사용자 Mac 전용)
# - 코드 저장소(market_anal2)와 문서 저장소(market_anal2-docs)를 최신으로 당긴 뒤
# - hana.py / kb.py / dongyang.py / heungkuk.py 를 문서 저장소 루트(--root)로 돌리고
# - 기초서류·manifest 에 바뀐 것이 있을 때만 문서 저장소에 commit + push 한다.
# 수동 실행:  bash ~/market_anal2/collectors/mac/weekly_collect.sh            (실제 수집)
#             DRY_RUN=1 bash ~/market_anal2/collectors/mac/weekly_collect.sh  (목록만, 커밋 안 함)

# ───────── 설정 (필요하면 여기만 고친다) ─────────
CODE_DIR="${CODE_DIR:-$HOME/market_anal2}"            # eco24n-hue/market_anal2 클론 위치
DOCS_DIR="${DOCS_DIR:-$HOME/market_anal2-docs}"       # eco24n-hue/market_anal2-docs 클론 위치
PYTHON="${PYTHON:-/usr/bin/python3}"                  # requests 를 설치한 python3
LOG_DIR="${LOG_DIR:-$HOME/Library/Logs/market_anal2}" # 실행 기록
COMPANIES="${COMPANIES:-hana kb dongyang heungkuk}"                       # 돌릴 수집기(파일 이름에서 .py 뺀 것)
GIT_BRANCH="${GIT_BRANCH:-main}"                      # 문서 저장소에 push 할 브랜치
# KB라이프 상품공시 목록 페이지 주소(브라우저 주소창에서 복사, 여러 개면 쉼표). 비우면 kb 가 실패한다.
export KB_LIST_URLS="${KB_LIST_URLS:-}"
# 원본 목록 응답을 매번 저장하려면 폴더를 지정(문제 생겼을 때 이 폴더를 보내 주면 된다)
export COLLECTOR_DEBUG_DIR="${COLLECTOR_DEBUG_DIR:-$LOG_DIR/debug/$(date +%Y%m%d)}"
# 대상 상품 일부를 못 찾아도 나머지는 받으려면 1 (기본: 하나라도 못 찾으면 그 회사는 실패 처리)
export COLLECTOR_ALLOW_MISSING="${COLLECTOR_ALLOW_MISSING:-0}"
# ───────────────────────────────────────────────

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export LANG="${LANG:-ko_KR.UTF-8}" PYTHONIOENCODING=utf-8 PYTHONUTF8=1

mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/collect_$STAMP.log"
exec > >(tee -a "$LOG") 2>&1

LOCK="$LOG_DIR/.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "이미 실행 중입니다($LOCK). 이전 실행이 비정상 종료했다면 그 폴더를 지우세요."; exit 1
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

echo "=== 공시실 수집 시작 $STAMP ==="
for d in "$CODE_DIR" "$DOCS_DIR"; do
  [ -d "$d/.git" ] || { echo "저장소가 없습니다: $d (README 1단계 참고)"; exit 1; }
done

git -C "$CODE_DIR" pull --ff-only || echo "경고: 코드 저장소 pull 실패 — 기존 코드로 계속합니다."
git -C "$DOCS_DIR" pull --ff-only || { echo "문서 저장소 pull 실패 — 충돌을 먼저 해결하세요."; exit 1; }

FAILED=""
EXTRA=""
[ "${DRY_RUN:-0}" = "1" ] && EXTRA="--dry-run"
for c in $COMPANIES; do
  echo "--- $c ---"
  OUT="$LOG_DIR/report_${c}_$STAMP.json"
  if "$PYTHON" "$CODE_DIR/collectors/$c.py" --root "$DOCS_DIR" $EXTRA > "$OUT"; then
    cat "$OUT"
    if grep -q '"errors": \[$' "$OUT"; then   # 비어 있으면 '"errors": []' 한 줄
      echo "경고: $c 보고서에 errors 가 있습니다(일부 문서 다운로드 실패)."
      FAILED="$FAILED $c(일부)"
    fi
  else
    cat "$OUT"
    echo "실패: $c — 위 오류 메시지 참고 (원본 응답: $COLLECTOR_DEBUG_DIR)"
    FAILED="$FAILED $c"
  fi
done

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "DRY_RUN — 커밋하지 않습니다."
else
  cd "$DOCS_DIR" || exit 1
  for p in 기초서류 manifest; do [ -e "$p" ] && git add -A -- "$p"; done
  if git diff --cached --quiet; then
    echo "바뀐 문서 없음 — 커밋하지 않습니다."
  else
    git -c core.quotepath=false diff --cached --stat | tail -20
    git commit -q -m "공시실 주간 수집 $(date +%Y-%m-%d) (하나·KB·동양)" && \
      git push origin "HEAD:$GIT_BRANCH" && echo "push 완료" || { echo "commit/push 실패"; FAILED="$FAILED git"; }
  fi
fi

# 오래된 로그·덤프 정리(60일)
find "$LOG_DIR" -type f -mtime +60 -delete 2>/dev/null
find "$LOG_DIR/debug" -type d -empty -delete 2>/dev/null

if [ -n "$FAILED" ]; then
  echo "=== 끝: 실패/경고 ->$FAILED (로그: $LOG) ==="
  osascript -e "display notification \"실패:$FAILED\" with title \"공시실 수집\"" 2>/dev/null
  exit 1
fi
echo "=== 끝: 정상 (로그: $LOG) ==="
