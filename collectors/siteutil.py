"""하나·KB·동양 수집기가 같이 쓰는 도우미.

- 원본 응답 저장(디버그 덤프): 환경변수 COLLECTOR_DEBUG_DIR 이 있으면 모든 목록 응답을
  그 폴더에 저장한다. 명령줄에서 `--debug-dump DIR` 을 주면 같은 효과다
  (run()의 argparse는 공통이라, 실행 전에 이 인자를 빼내 환경변수로 옮긴다).
- 파싱 실패 시에는 COLLECTOR_DEBUG_DIR 이 없어도 임시 폴더에 원본을 저장하고
  그 경로를 오류 메시지에 넣는다. 사용자는 그 파일을 보내 주면 된다.
- 빈 목록을 조용히 돌려주지 않는다: 예상 밖 응답은 CollectorError 로 멈춘다.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path

DEBUG_ENV = "COLLECTOR_DEBUG_DIR"

# 신상품 감지용 건강·보장 계열 키워드
HEALTH_RE = re.compile(r"건강|질병|암|간편|보장|케어|Care|종신|치매|간병|수술|입원|통합|종합|어린이|자녀")


class CollectorError(RuntimeError):
    """공시실이 예상과 다른 응답을 준 경우. 메시지는 사용자에게 그대로 보인다."""


# ── 디버그 덤프 ─────────────────────────────────────────────

def consume_debug_flag(argv: list[str] | None = None) -> None:
    """sys.argv 에서 `--debug-dump DIR` / `--debug-dump=DIR` 을 빼 환경변수로 옮긴다."""
    argv = sys.argv if argv is None else argv
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--debug-dump" and i + 1 < len(argv):
            os.environ[DEBUG_ENV] = argv[i + 1]
            del argv[i:i + 2]
            continue
        if a.startswith("--debug-dump="):
            os.environ[DEBUG_ENV] = a.split("=", 1)[1]
            del argv[i]
            continue
        i += 1


_dump_seq = 0


def dump(site: str, label: str, content, force: bool = False) -> str | None:
    """원본 응답을 파일로 저장하고 경로를 돌려준다.

    COLLECTOR_DEBUG_DIR 이 있으면 항상, 없으면 force=True 일 때만 임시 폴더에 저장한다.
    """
    global _dump_seq
    d = os.environ.get(DEBUG_ENV)
    if not d:
        if not force:
            return None
        d = os.path.join(tempfile.gettempdir(), "collector_debug")
    p = Path(d).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    _dump_seq += 1
    safe = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", label)[:80]
    ext = ".txt"
    if isinstance(content, (bytes, bytearray)):
        head = bytes(content[:200]).lstrip().lower()
        ext = ".json" if head[:1] in (b"{", b"[") else ".html" if b"<" in head[:5] else ".bin"
        data = bytes(content)
    else:
        s = str(content)
        ext = ".json" if s.lstrip()[:1] in ("{", "[") else ".html" if s.lstrip()[:1] == "<" else ".txt"
        data = s.encode("utf-8")
    f = p / f"{site}_{time.strftime('%Y%m%d-%H%M%S')}_{_dump_seq:02d}_{safe}{ext}"
    f.write_bytes(data)
    return str(f)


def fail(site: str, msg: str, raw=None, label: str = "응답") -> "NoReturn":  # noqa: F821
    """원본을 저장하고 CollectorError 를 낸다."""
    path = dump(site, label, raw, force=True) if raw is not None else None
    tail = f"\n  원본 응답 저장 위치: {path}\n  이 파일을 보내 주시면 파서를 고칠 수 있습니다." if path else ""
    raise CollectorError(f"[{site}] {msg}{tail}")


# ── 요청 ───────────────────────────────────────────────────

def decode(r) -> str:
    """requests 응답을 문자열로. 한국 사이트의 EUC-KR 응답도 처리한다."""
    raw = r.content
    ctype = r.headers.get("Content-Type", "")
    m = re.search(r"charset=([\w-]+)", ctype, re.I) or re.search(rb'charset=["\']?([\w-]+)', raw[:3000], re.I)
    enc = m.group(1) if m else None
    if isinstance(enc, bytes):
        enc = enc.decode("ascii", "ignore")
    for e in (enc, "utf-8", "cp949"):
        if not e:
            continue
        try:
            return raw.decode(e)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def request(sess, site: str, label: str, method: str, url: str, timeout: int = 60, **kw):
    """요청 + 상태 확인 + 덤프. 네트워크 오류도 한국어로 감싼다. 응답(문자열, 원본 Response)을 돌려준다."""
    try:
        r = sess.request(method, url, timeout=timeout, **kw)
    except Exception as e:  # 접속 실패·시간 초과
        raise CollectorError(f"[{site}] {label} 요청 실패({type(e).__name__}): {url}\n  {e}\n"
                             f"  사이트 접속이 되는지 브라우저로 먼저 확인해 주세요.") from e
    dump(site, label, r.content)
    if r.status_code != 200:
        fail(site, f"{label}: HTTP {r.status_code} ({url})", r.content, label)
    if not r.content.strip():
        fail(site, f"{label}: 빈 응답 ({url})", r.content, label)
    return decode(r), r


# ── 문자열 ─────────────────────────────────────────────────

DATE_RE = re.compile(r"((?:19|20)\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})|((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)")


def dates_in(s: str) -> list[str]:
    """문자열 안의 날짜들을 YYYYMMDD 로."""
    out = []
    for m in DATE_RE.finditer(s or ""):
        if m.group(1):
            y, mo, d = m.group(1), m.group(2), m.group(3)
        else:
            y, mo, d = m.group(4), m.group(5), m.group(6)
        if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
            out.append(f"{y}{int(mo):02d}{int(d):02d}")
    return out


def ymd(s) -> str:
    """단일 날짜 값 → YYYYMMDD. 빈값·9999xxxx·'현재'는 '' (판매중)."""
    if s is None:
        return ""
    s = str(s)
    ds = dates_in(s)
    if not ds:
        digits = re.sub(r"\D", "", s)
        if len(digits) == 8 and digits.startswith("9999"):
            return ""
        return ""
    return "" if ds[0].startswith("9999") else ds[0]


def norm(s: str) -> str:
    """상품명 비교용 정규화: 공백·전각괄호·가운뎃점 차이를 없앤다. (무)/무배당은 남긴다."""
    s = html.unescape(s or "")
    s = s.replace("（", "(").replace("）", ")").replace("ㆍ", "·").replace("・", "·").replace("‧", "·")
    return re.sub(r"\s+", "", s).lower()


def norm_loose(s: str) -> str:
    """더 느슨한 비교: (무)/무배당/괄호/가운뎃점까지 지운다."""
    s = norm(s).replace("(무)", "").replace("무배당", "")
    return re.sub(r"[()\[\]·_,]", "", s)


def strip_tags(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def health_only(names) -> list[str]:
    return [n for n in dict.fromkeys(names) if HEALTH_RE.search(n)]


# ── HTML 이벤트 펼치기 ──────────────────────────────────────

class Flatten(HTMLParser):
    """HTML을 (kind, tag, attrs, text, pos) 이벤트 목록으로 편다. BeautifulSoup 대용."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events: list[tuple] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        self.events.append(("start", tag, dict((k, v or "") for k, v in attrs), ""))

    def handle_startendtag(self, tag, attrs):
        self.events.append(("start", tag, dict((k, v or "") for k, v in attrs), ""))
        self.events.append(("end", tag, {}, ""))

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        self.events.append(("end", tag, {}, ""))

    def handle_data(self, data):
        if self._skip:
            return
        t = re.sub(r"\s+", " ", data).strip()
        if t:
            self.events.append(("text", "", {}, t))


def flatten(s: str) -> list[tuple]:
    p = Flatten()
    p.feed(s)
    p.close()
    return p.events


def walk_dicts(obj):
    """JSON 트리 안의 모든 dict 를 차례로 내놓는다."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def try_json(text: str):
    t = text.strip()
    if t[:1] not in ("{", "["):
        return None
    try:
        return json.loads(t)
    except ValueError:
        return None


def warn(site: str, msg: str) -> None:
    print(f"[{site}] 경고: {msg}", file=sys.stderr)


def allow_missing() -> bool:
    """COLLECTOR_ALLOW_MISSING=1 이면 일부 대상 상품을 못 찾아도 경고만 하고 계속한다."""
    return os.environ.get("COLLECTOR_ALLOW_MISSING", "") in ("1", "true", "yes")
