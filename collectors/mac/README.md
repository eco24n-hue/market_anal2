# Mac에서 하나생명 · KB라이프 · 동양생명 공시실 수집하기

이 세 회사 공시실은 클라우드에서 접속이 안 됩니다(하나생명은 TLS 연결 직후 끊기고, KB라이프·동양생명은 시간 초과).
그래서 사용자 Mac에서 매주 월요일 07:10에 자동으로 수집하고, 결과를 `market_anal2-docs` 저장소에 push합니다.

| 파일 | 역할 |
|---|---|
| `collectors/hana.py`, `kb.py`, `dongyang.py` | 회사별 수집기 (`common.run()` 공통 인자: `--root`, `--dry-run`, `--limit`, `--since`) |
| `collectors/siteutil.py` | 세 수집기 공통 도우미(디버그 덤프, 오류 메시지, 날짜·상품명 정규화) |
| `collectors/mac/weekly_collect.sh` | 세 수집기를 차례로 돌리고, 바뀐 것이 있을 때만 docs 저장소에 commit + push |
| `collectors/mac/com.market_anal2.collect.plist` | launchd 예약(매주 월요일 07:10, Mac 현지 시각) |

---

## 1. 저장소 두 개 받기

홈 폴더 바로 아래를 권장합니다. `~/Documents`·`~/Desktop`·`~/Downloads` 안에 두면 macOS 개인정보 보호 때문에
launchd 실행이 막힐 수 있습니다(그 경우 「시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한」에 `/bin/bash`를 추가).

```bash
cd ~
git clone https://github.com/eco24n-hue/market_anal2.git
git clone https://github.com/eco24n-hue/market_anal2-docs.git
```

다른 위치에 받았다면 `collectors/mac/weekly_collect.sh` 맨 위 설정의 `CODE_DIR` / `DOCS_DIR`을 고칩니다.

**push 인증**: 예약 실행 중에는 비밀번호를 물어볼 수 없으므로, 터미널에서 한 번 `git push`가 묻지 않고 되는 상태여야 합니다.
`gh auth login`(GitHub CLI, HTTPS) 또는 SSH 키 등록 중 하나를 해 두세요. 확인:

```bash
cd ~/market_anal2-docs && git push --dry-run
```

## 2. requests 설치

```bash
python3 --version          # 3.9 이상이면 됨 (없으면 xcode-select --install)
pip3 install --user requests
python3 -c "import requests; print(requests.__version__)"
```

Homebrew 파이썬을 쓰는 경우 `pip3 install` 이 막히면 `python3 -m pip install --user --break-system-packages requests`
또는 가상환경을 만들고 `weekly_collect.sh` 의 `PYTHON=` 을 그 가상환경의 `python3` 경로로 바꿉니다.
스크립트 기본값은 `/usr/bin/python3` 이므로, 다른 파이썬에 설치했다면 반드시 `PYTHON=` 을 맞춰 주세요(`which python3`).

## 3. KB라이프 목록 주소 넣기 (한 번만)

KB라이프 공시실 목록 페이지 주소는 이전 수집 기록(RECIPES.md)에 남아 있지 않습니다.
브라우저로 KB라이프 홈페이지 → 공시실 → 상품공시(아코디언을 펼치면 판매기간이 나오는 페이지)를 열고
주소창의 주소를 복사해 `weekly_collect.sh` 의

```bash
export KB_LIST_URLS="${KB_LIST_URLS:-여기에_주소}"
```

에 넣습니다. 판매중·판매중지 페이지가 따로면 쉼표로 둘 다 넣습니다.
그 페이지가 목록을 자바스크립트로 나중에 불러오는 형태라면 kb.py 가 「data-seqno 가 없습니다」라고 멈춥니다.
그때는 개발자도구(⌥⌘I) → Network 탭에서 목록을 불러오는 요청(JSON) 주소를 찾아 그 주소를 넣으세요(kb.py 는 JSON 응답도 읽도록 되어 있습니다).

## 4. 처음 한 번 손으로 확인

받지 않고 목록만 보는 dry-run 부터:

```bash
cd ~/market_anal2/collectors
python3 hana.py     --root ~/market_anal2-docs --dry-run --debug-dump ~/collector_debug
python3 kb.py       --root ~/market_anal2-docs --dry-run --debug-dump ~/collector_debug
python3 dongyang.py --root ~/market_anal2-docs --dry-run --debug-dump ~/collector_debug
```

- 성공하면 받을 파일 목록이 JSON 으로 나옵니다(`new_docs`).
- 실패하면 `[하나생명] …` 처럼 한국어 오류와 함께 **원본 응답 저장 위치**가 나옵니다.
  `~/collector_debug` 폴더(또는 오류에 나온 파일)를 그대로 보내 주시면 파서를 맞춰 고칩니다.
  수집기는 빈 목록을 조용히 넘기지 않고 반드시 멈춥니다.
- `--debug-dump 폴더` 는 환경변수 `COLLECTOR_DEBUG_DIR=폴더` 와 같습니다.

그다음 문서 2개만 실제로 받아 봅니다:

```bash
python3 dongyang.py --root ~/market_anal2-docs --limit 2
ls -R ~/market_anal2-docs/기초서류/동양생명 | head
```

전체 흐름(커밋 없이)도 확인:

```bash
DRY_RUN=1 bash ~/market_anal2/collectors/mac/weekly_collect.sh
```

오프라인 파서 테스트(접속 불필요):

```bash
cd ~/market_anal2 && python3 collectors/tests/test_offline_parsers.py
```

## 5. 매주 자동 실행 등록 (launchd)

설치 — plist 안의 `/Users/YOUR_NAME` 을 내 홈 폴더로 바꿔 복사하고 등록합니다:

```bash
mkdir -p ~/Library/LaunchAgents ~/Library/Logs/market_anal2
sed "s#/Users/YOUR_NAME#$HOME#g" ~/market_anal2/collectors/mac/com.market_anal2.collect.plist \
  > ~/Library/LaunchAgents/com.market_anal2.collect.plist
plutil -lint ~/Library/LaunchAgents/com.market_anal2.collect.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.market_anal2.collect.plist
launchctl print gui/$(id -u)/com.market_anal2.collect | grep -E "state|path"
```

(저장소를 홈 바로 아래가 아닌 곳에 두었다면 복사된 plist 의 스크립트 경로도 고칩니다.)

지금 바로 한 번 돌려 보기:

```bash
launchctl kickstart -k gui/$(id -u)/com.market_anal2.collect
tail -f ~/Library/Logs/market_anal2/launchd.out.log
```

해제:

```bash
launchctl bootout gui/$(id -u)/com.market_anal2.collect
rm ~/Library/LaunchAgents/com.market_anal2.collect.plist
```

plist 나 스크립트 경로를 바꾼 뒤에는 해제 → 설치를 다시 합니다(스크립트 내용만 고친 경우는 다시 등록할 필요 없음).

**참고**
- 월요일 07:10 에 Mac 이 잠자기 상태였다면 깨어날 때 실행됩니다. 전원이 꺼져 있었다면 그 주는 건너뜁니다
  (다음에 켰을 때 `launchctl kickstart …` 로 손으로 돌리면 됩니다).
  잠자기에서 깨우려면: `sudo pmset repeat wakeorpoweron M 07:05:00`.
- 실패하면 알림 센터에 「공시실 수집 — 실패: kb」처럼 알림이 뜨고 종료 코드 1로 끝납니다.

## 6. 매주 무슨 일이 일어나나

`weekly_collect.sh` 순서:

1. `market_anal2`(코드) `git pull --ff-only` — 실패해도 기존 코드로 계속
2. `market_anal2-docs` `git pull --ff-only` — 실패하면 중단(충돌을 먼저 해결)
3. `hana.py` → `kb.py` → `dongyang.py` 를 `--root ~/market_anal2-docs` 로 실행.
   한 회사가 실패해도 나머지는 계속합니다. 회사별 결과 JSON 은 `~/Library/Logs/market_anal2/report_<회사>_<시각>.json`.
4. docs 저장소에서 `git add 기초서류 manifest` → 바뀐 것이 있을 때만 `git commit` + `git push origin HEAD:main`
5. 60일 지난 로그·덤프 삭제

저장 위치(공통 규칙): `기초서류/<회사>/<판매개시일>/<상품명>/<약관|사업방법서|상품요약서>.pdf`, `manifest/<회사>.json`.
기본으로 2026-09-01 이후 개시된 판만 받습니다(`--since` 로 바꿈). 이미 manifest 에 있는 문서는 다시 받지 않습니다.

## 7. 설정 한눈에 (`weekly_collect.sh` 맨 위)

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `CODE_DIR` | `~/market_anal2` | 코드 저장소 |
| `DOCS_DIR` | `~/market_anal2-docs` | 문서 저장소(`--root`) |
| `PYTHON` | `/usr/bin/python3` | requests 를 설치한 파이썬 |
| `LOG_DIR` | `~/Library/Logs/market_anal2` | 로그·보고서 |
| `COMPANIES` | `hana kb dongyang` | 돌릴 수집기 |
| `GIT_BRANCH` | `main` | push 할 브랜치 |
| `KB_LIST_URLS` | (비어 있음 — 꼭 채울 것) | KB라이프 목록 주소 |
| `COLLECTOR_DEBUG_DIR` | `LOG_DIR/debug/날짜` | 목록 원본 응답 저장 폴더 |
| `COLLECTOR_ALLOW_MISSING` | `0` | 1이면 대상 상품 일부를 못 찾아도 나머지는 수집 |

수집기별 추가 환경변수: `HANA_STATUS_ON`(하나 판매중 목록 status 값, 기본 `on`), `HANA_PAGE_PARAM`(쪽 번호 인자, 기본 `pageIndex`),
`KB_INCLUDE_SUMMARY=1`(KB 상품요약서 box 0 도 받기).

## 8. 문제가 생기면

- 「요청 실패(ConnectTimeout/SSLError)」: 브라우저로 그 사이트가 열리는지 먼저 확인합니다(회사 VPN·보안 프로그램 영향 가능).
- 「다운로드 링크를 하나도 찾지 못했습니다」「공시번호를 하나도 읽지 못했습니다」「JSON 이 아닌 응답」:
  사이트 마크업·응답 형식이 추정과 다른 경우입니다. 오류에 나온 원본 파일 또는 `~/Library/Logs/market_anal2/debug/` 폴더를 보내 주세요.
- 「대상 상품을 찾지 못했습니다」: 공시실 상품명이 `collectors/products.json` 과 다릅니다. 오류에 목록에서 읽은 상품명 예시가 같이 나오니
  그것을 보고 products.json 을 고치거나 알려 주세요.
- 한글 파일명이 git 에서 `\354\225…` 처럼 보이면: `git config --global core.quotepath false`.
