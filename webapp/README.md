# 건강보험 담보 레이더 웹앱

서버(API) + 브라우저 화면으로 된 웹앱이다. 화면은 데이터를 서버에서 받아 그린다.

## 기능
| 화면 | 내용 | API |
|---|---|---|
| 요약 | 급부 행·표준담보·세부담보·전 회사 공통·회사별 세부담보 수 | `GET /api/coverages` |
| 담보 목록 / 보장여부 / 지급금액·횟수 / 면책 / 감액 / 대기 | 세부담보 × 회사 비교, 대분류·검색·전 회사 공통 필터 | `GET /api/coverages` |
| 심사기준 | 회사별 심사기준 O/X, 상품별 심사기준 | `GET /api/underwriting` |
| 상품별 세부담보 | 상품·특약·급부 한 줄씩(페이지 단위) | `GET /api/rows` |
| 기간별 변경 | 두 기준일 사이 회사별 신설·폐지·조건 변경 | `GET /api/diff` |
| 업데이트 실행 | 공시실 다운로드(선택) → 폴더 읽기(개정 판별) → 텍스트 → 특약 분할 | `POST /api/runs`, `GET /api/runs/latest` |
| 내려받기 | DB·엑셀 | `GET /api/downloads`, `/download/{파일}` |

기준일(스냅샷)을 고르면 그 주의 DB로 화면이 바뀐다.

## 내 PC에서 실행
```bash
cd ~/market_anal2
pip3 install -r webapp/requirements.txt
DOCS_ROOT="$HOME/Library/Mobile Documents/com~apple~CloudDocs/work" uvicorn webapp.server:app --port 8000
```
브라우저에서 http://127.0.0.1:8000

## 설정 (환경변수)
| 이름 | 뜻 | 기본값 |
|---|---|---|
| `DB_PATH` | 담보 DB(SQLite) | `data/health_coverage_db.sqlite` |
| `DOCS_ROOT` | 기초서류 폴더 | iCloud `work` 폴더 |
| `STATE_DIR`, `WORK_DIR` | 개정 판별 결과·작업 폴더 | `state/`, `work/` |
| `APP_PASSWORD` | 설정하면 로그인 필요 | 없음(로그인 없음) |
| `APP_SECRET` | 로그인 쿠키 서명 키. `APP_PASSWORD`를 쓰면 필수 | 없음 |

비밀번호와 서명 키는 코드나 저장소에 넣지 말고 서버의 비밀값 저장소(예: Google Secret Manager)에 둔다.

## 서버에 배포 (Docker)
```bash
docker build -t coverage-radar .
docker run -p 8080:8080 -v /path/to/기초서류:/docs -e APP_PASSWORD=... -e APP_SECRET=... coverage-radar
```
Google Cloud Run 등 컨테이너를 돌리는 서비스에 그대로 올릴 수 있다. 이때 기초서류 폴더(`/docs`)는 클라우드 저장소를 연결해야 한다.

## 아직 웹앱 안에 없는 것
- **AI 약관 정독·검증과 담보 판정**: 지금은 Claude Code에서 실행한다. 웹앱의 실행 버튼은 특약 분할까지 하고, 새 기준일 DB는 그 다음 단계에서 만들어진다. 웹앱 안에서 돌리려면 Claude API 연동(API 키 필요)을 추가해야 한다.
- 주간 자동 실행: 서버의 예약 기능(Cloud Scheduler 등)에서 `POST /api/runs`를 호출하도록 설정한다.
