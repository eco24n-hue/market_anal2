# 기초서류 폴더 기반 파이프라인

GitHub 저장소 대신 **정해진 폴더**(기본: iCloud `work` 폴더)의 기초서류를 읽는다. 폴더 이름이 회사·개정일을 담고 있으면 패턴이 제각각이어도 된다.

## 준비 (Mac, 1회)

```bash
git clone https://github.com/eco24n-hue/market_anal2.git ~/market_anal2
brew install poppler          # pdftotext
pip3 install --user requests
```

iCloud의 "Mac 저장 공간 최적화"가 켜져 있으면 PDF가 아직 내려받아지지 않았을 수 있다. Finder에서 `work` 폴더를 우클릭 → **다운로드 유지**.

## 앱에서 실행 버튼으로 돌리기

```bash
cd ~/market_anal2
DOCS_ROOT="$HOME/Library/Mobile Documents/com~apple~CloudDocs/work" python3 pipeline/app_server.py
```

브라우저에서 http://127.0.0.1:8765 를 열고 **실행**을 누른다. 담보 비교 화면 위에 '개정된 기초서류 읽어오기' 칸이 붙어 있다.

- 실행하면 ① (체크 시) 공시실에서 새 개정판 다운로드 → ② 폴더 다시 읽기(새 파일·개정·삭제 판별) → ③ 바뀐 PDF만 텍스트 변환 → ④ 특약 단위 분할까지 돈다.
- 결과는 화면에 바로 표시된다: 판별 수, 새 파일, 개정(이전 판 → 새 판), 삭제, 판별 실패, iCloud 미다운로드.
- 기준일: 이 날짜에 유효했던 판과 그 이후 판을 분석 대상으로 삼는다(기본 20260901).
- 서버는 이 Mac(127.0.0.1)에서만 열리고, 다른 사이트에서 보낸 실행 요청은 거절한다.
- 담보 판정(AI 정독)과 DB 갱신은 아직 버튼에 포함되지 않는다. Claude Code에서 4단계로 실행한다.

## 실행 순서 (명령어로 직접)

```bash
cd ~/market_anal2
export DOCS_ROOT="$HOME/Library/Mobile Documents/com~apple~CloudDocs/work"

# 1) 폴더 점검: 회사·개정일·문서종류·상품명 판별, 지난 실행 대비 새 파일·개정 파일
python3 pipeline/ingest.py --docs-root "$DOCS_ROOT" --state state

# 2) PDF → 텍스트 (바뀐 파일만)
python3 pipeline/stage_text.py --state state --out work/txt --since 20260901

# 3) 특약 단위 분할 → 필요한 조항만 남기기 → 특약 계열 묶기
python3 pipeline/segment.py work/txt work/seg
python3 pipeline/trim.py work/seg work/trim
python3 pipeline/cluster.py work/trim work/clu
```

4단계(특약별 정독·검증, 세부·표준담보 판정)는 AI가 원문을 읽는 단계라 Mac에서 실행한 **Claude Code**가 수행한다. Claude Code에 "pipeline 4단계를 work/clu 로 실행해줘"라고 요청하면 된다. 그 뒤:

```bash
python3 pipeline/assemble.py work <추출 결과 json들>
python3 pipeline/sig.py work
python3 pipeline/build_db.py work 2026-11-08 data/health_coverage_db.sqlite data/건강보험_표준담보DB_20261108.xlsx
```

## 판별 규칙

`pipeline/folder_rules.json` 에 회사 별칭(상품 브랜드 포함: `M-케어`→미래에셋생명, `우리WON`→동양생명 등)과 문서종류 키워드가 있다.

| 항목 | 찾는 순서 |
|---|---|
| 회사 | 파일명 → 가까운 상위 폴더명 |
| 개정일 | 파일명의 날짜(`20260901`, `260901`, `202609`) → 상위 폴더명의 날짜(`…_20260916`, `2601`) |
| 문서종류 | 파일명 → 상위 폴더명(`01_상품요약서` 등) → **PDF 첫 두 쪽 내용**(iCloud가 긴 파일명을 잘라 저장한 경우) |
| 상품명 | 파일명에서 날짜·공시번호·문서종류를 뺀 나머지. 파일명이 `약관.pdf`뿐이면 상위 폴더명 |

- `Claude outputs`, `_to_delete`, 이름이 `.`·`_`로 시작하는 폴더는 건너뛴다.
- 판별하지 못한 파일은 `state/ingest_report_<날짜>.json` 의 `판별 실패`에 이유와 함께 남는다. 규칙을 `folder_rules.json` 에 추가하면 다음 실행부터 반영된다.
- 같은 파일이 같은 회사·상품·문서로 두 곳에 있으면 하나만 쓴다. 여러 상품이 한 파일을 함께 쓰면(공유 사업방법서) 상품별로 모두 남기고 `shared_with` 로 표시한다.

## 결과물

| 파일 | 내용 |
|---|---|
| `state/catalog.json` | 현재 폴더의 기초서류 목록(회사·개정일·문서종류·상품명·sha256) |
| `state/history/catalog_<날짜>.json` | 실행일별 목록 |
| `state/ingest_report_<날짜>.json` | 새 파일·개정 파일(이전 판 포함)·삭제 파일, 판별 실패, iCloud 미다운로드 |

## 한계

- 특약 분할 규칙(`segment.py`)은 현재 **신한라이프·미래에셋생명** 약관 서식만 있다. 하나·KB·동양·흥국은 규칙이 없어 건너뛰며, 해당 약관 텍스트를 보고 규칙을 추가해야 한다.
- 미래에셋 사업방법서·상품요약서는 스캔 이미지라 텍스트가 없다(OCR 필요).
