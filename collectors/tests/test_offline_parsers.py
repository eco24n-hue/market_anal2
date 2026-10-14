"""접속 없이 파서만 확인하는 테스트. RECIPES.md 설명으로 손으로 만든 샘플 응답을 쓴다.

실행:  python3 -m pytest collectors/tests   또는   python3 collectors/tests/test_offline_parsers.py
실제 사이트 응답을 받으면(COLLECTOR_DEBUG_DIR) 그 파일로 샘플을 바꿔 넣어 다시 확인한다.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dongyang  # noqa: E402
import hana  # noqa: E402
import kb  # noqa: E402
import siteutil  # noqa: E402


class FakeResp:
    def __init__(self, body, status=200, ctype="text/html; charset=utf-8"):
        self.content = body.encode("utf-8") if isinstance(body, str) else body
        self.status_code = status
        self.headers = {"Content-Type": ctype}


class FakeSess:
    """(method, url, 조건) → 응답 본문. 조건은 params/data 의 부분 일치."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, timeout=None, params=None, data=None, headers=None):
        self.calls.append((method, url, params, data))
        args = dict(params or {}, **(data or {}))
        for (m, u, cond), body in self.routes:
            if m == method and u == url and all(str(args.get(k)) == str(v) for k, v in cond.items()):
                return FakeResp(body)
        return FakeResp("<html><body>없음</body></html>")


# ── 하나생명 ────────────────────────────────────────────────

HANA_OFF = """<html><body><table class="tbl"><thead><tr><th>상품명</th><th>판매기간</th><th>약관</th><th>사업방법서</th></tr></thead>
<tbody>
<tr><td class="left">(무)하나로 누리는 건강보험</td><td>2026.01.01 ~ 2026.08.31</td>
<td><a href="/anm/product/download.do?code=610778&amp;seq=1" title="약관 다운로드"><img alt="PDF"></a></td>
<td><a href="/home/download2.do?fileName=PROD/%EB%88%84%EB%A6%AC%EB%8A%94_%EC%82%AC%EC%97%85%EB%B0%A9%EB%B2%95%EC%84%9C.pdf">다운로드</a></td></tr>
<tr><td class="left">(무)하나로 누리는 건강보험(갱신형)</td><td>2026.01.01 ~ 2026.08.31</td>
<td><a href="javascript:void(0)" onclick="fnDown('610800','1')">약관</a></td>
<td><a href="/home/download2.do?fileName=PROD/누리는_사업방법서.pdf">사업방법서</a></td></tr>
<tr><td>(무)하나로 행복한 연금보험</td><td>2014.01.01 ~ 2014.12.31</td>
<td><a href="/anm/product/download.do?code=100001&seq=1">약관</a></td><td></td></tr>
</tbody></table></body></html>"""

HANA_ON = """<html><body><table><tbody>
<tr><td>(무)하나로 누리는 건강보험</td><td>2026.09.01 ~</td>
<td><a href="/anm/product/download.do?code=611052&seq=1">계약자용약관_20260901</a></td>
<td><a href="/home/download2.do?fileName=PROD/누리는_사업방법서_20260901.pdf">사업방법서</a></td>
<td><a href="/home/download2.do?fileName=PROD/누리는_상품요약서_20260901.pdf">상품요약서</a></td></tr>
<tr><td>(무)하나로 누리는 건강보험(갱신형)</td><td>2026.09.01 ~</td>
<td><a href="/anm/product/download.do?code=611053&seq=1">약관</a></td></tr>
<tr><td>(무)하나로 든든한 종신보험</td><td>2026.04.01 ~</td>
<td><a href="/anm/product/download.do?code=611000&seq=1">약관</a></td></tr>
</tbody></table></body></html>"""


def hana_sess(on=HANA_ON, off=HANA_OFF):
    return FakeSess([
        (("GET", hana.LIST_URL, {"status": "off", "pageIndex": "None"}), off),
        (("GET", hana.LIST_URL, {"status": "on", "pageIndex": "None"}), on),
        (("GET", hana.LIST_URL, {"status": "off"}), off),   # 2쪽째도 같은 내용 → 멈춤
        (("GET", hana.LIST_URL, {"status": "on"}), on),
    ])


def test_hana_parse_rows():
    rows = hana.parse_hana_list(HANA_OFF)
    assert [r["name"] for r in rows] == ["(무)하나로 누리는 건강보험", "(무)하나로 누리는 건강보험(갱신형)",
                                         "(무)하나로 행복한 연금보험"]
    r0 = rows[0]
    assert (r0["start"], r0["end"], r0["code"]) == ("20260101", "20260831", "610778")
    types = {d.doc_type: d for d in r0["docs"]}
    assert set(types) == {"약관", "사업방법서"}
    assert types["사업방법서"].fetch["params"]["fileName"] == "PROD/누리는_사업방법서.pdf"
    assert rows[1]["code"] == "610800"  # onclick JS 호출형


def test_hana_editions():
    targets = ["(무)하나로 누리는 건강보험", "(무)하나로 누리는 건강보험(갱신형)"]
    eds = hana.list_editions(hana_sess(), targets)
    got = [(e.product, e.start, e.end, e.disclosure_id, sorted(d.doc_type for d in e.docs)) for e in eds]
    assert got == [
        ("(무)하나로 누리는 건강보험", "20260101", "20260831", "610778", ["사업방법서", "약관"]),
        ("(무)하나로 누리는 건강보험", "20260901", "", "611052", ["사업방법서", "상품요약서", "약관"]),
        ("(무)하나로 누리는 건강보험(갱신형)", "20260101", "20260831", "610800", ["사업방법서", "약관"]),
        ("(무)하나로 누리는 건강보험(갱신형)", "20260901", "", "611053", ["약관"]),
    ], got


def test_hana_products():
    assert hana.list_products(hana_sess()) == ["(무)하나로 누리는 건강보험", "(무)하나로 누리는 건강보험(갱신형)",
                                               "(무)하나로 든든한 종신보험"]


def test_hana_fails_loudly_on_empty_page():
    with tempfile.TemporaryDirectory() as d:
        os.environ[siteutil.DEBUG_ENV] = d
        try:
            sess = hana_sess(off="<html><script>loadList()</script><div id='list'></div></html>")
            try:
                hana.list_editions(sess, ["(무)하나로 누리는 건강보험"])
            except siteutil.CollectorError as e:
                assert "다운로드 링크를 하나도" in str(e) and "원본 응답 저장 위치" in str(e)
            else:
                raise AssertionError("빈 목록에서 오류가 나야 함")
            assert any(Path(d).iterdir())  # 디버그 덤프가 저장됨
        finally:
            del os.environ[siteutil.DEBUG_ENV]


def test_hana_missing_target_fails():
    try:
        hana.list_editions(hana_sess(), ["(무)하나로 없는 건강보험"])
    except siteutil.CollectorError as e:
        assert "찾지 못했습니다" in str(e)
    else:
        raise AssertionError


# ── KB라이프 ────────────────────────────────────────────────

KB_A = """<html><body><div class="accordion-wrap">
<button class="accordion"><span class="tit">KB 딱좋은 0540 건강보험 무배당</span></button>
<div class="panel"><table><tr><th>판매기간</th><th>구분</th><th>사업방법서</th><th>약관</th></tr>
<tr><td>2026.10.01 ~ 현재</td><td>일반심사형</td><td><button data-seqno="501619081" data-box="1">사업방법서</button></td><td><button data-seqno="501619081" data-box="2">약관</button></td></tr>
<tr><td>2026.10.01 ~ 현재</td><td>간편심사형(3.5.5)</td><td><button data-seqno="501619077">사업방법서</button></td><td><button data-seqno="501619077">약관</button></td></tr>
<tr><td>2026.04.01 ~ 2026.09.30</td><td>일반심사형</td><td><button data-seqno="501618143">사업방법서</button></td><td><button data-seqno="501618143">약관</button></td></tr>
</table></div>
<button class="accordion"><span class="tit">KB 3.10.5 딱좋은 초경증 건강보험 무배당(간편심사형)</span></button>
<div class="panel"><ul><li><span>2026.10.01 ~ 현재</span><a href="#" data-seqno="501619100">약관</a></li>
<li><span>2026.01.01 ~ 2026.09.30</span><a href="#" data-seqno="501618118">약관</a></li></ul></div>
<button class="accordion"><span class="tit">KB 착한 정기보험 무배당</span></button>
<div class="panel"><ul><li>2025.01.01 ~ 2025.12.31<a data-seqno="501600001">약관</a></li></ul></div>
</div></body></html>"""

KB_B = """<div class="panel"><div class="panel-heading"><h4>KB 딱좋은 요즘 건강보험 무배당(일반심사형)</h4></div>
<div class="panel-collapse"><div class="panel-body"><table>
<tr><td>2026.10.01~</td><td><a data-seqno="501619090">약관</a></td></tr></table></div></div></div>"""


def test_kb_panels_pattern_a():
    ps = kb.parse_kb_panels(KB_A)
    assert [p["title"] for p in ps] == ["KB 딱좋은 0540 건강보험 무배당",
                                        "KB 3.10.5 딱좋은 초경증 건강보험 무배당(간편심사형)", "KB 착한 정기보험 무배당"]
    rows = ps[0]["rows"]
    assert [(r["seqno"], r["start"], r["end"], r["label"]) for r in rows] == [
        ("501619081", "20261001", "", "일반심사형"),
        ("501619077", "20261001", "", "간편심사형(3.5.5)"),
        ("501618143", "20260401", "20260930", "일반심사형"),
    ], rows


def test_kb_panels_pattern_b():
    ps = kb.parse_kb_panels(KB_B)
    assert ps[0]["title"] == "KB 딱좋은 요즘 건강보험 무배당(일반심사형)"
    assert ps[0]["rows"][0]["seqno"] == "501619090" and ps[0]["rows"][0]["start"] == "20261001"


def test_kb_editions():
    os.environ["KB_LIST_URLS"] = "https://example.invalid/list"
    try:
        sess = FakeSess([(("GET", "https://example.invalid/list", {}), KB_A)])
        eds = kb.list_editions(sess, ["KB 딱좋은 0540 건강보험 무배당",
                                      "KB 3.10.5 딱좋은 초경증 건강보험 무배당(간편심사형)"])
        got = [(e.product, e.start, e.end, e.disclosure_id) for e in eds]
        assert got == [
            ("KB 3.10.5 딱좋은 초경증 건강보험 무배당(간편심사형)", "20260101", "20260930", "501618118"),
            ("KB 3.10.5 딱좋은 초경증 건강보험 무배당(간편심사형)", "20261001", "", "501619100"),
            ("KB 딱좋은 0540 건강보험 무배당", "20260401", "20260930", "501618143"),
            ("KB 딱좋은 0540 건강보험 무배당 [간편심사형(3.5.5)]", "20261001", "", "501619077"),
            ("KB 딱좋은 0540 건강보험 무배당 [일반심사형]", "20261001", "", "501619081"),
        ], got
        d = {x.doc_type: x for x in eds[-1].docs}
        assert d["약관"].fetch["url"].endswith("/product-terms/501619081/2")
        assert d["사업방법서"].fetch["url"].endswith("/product-terms/501619081/1")
        assert kb.list_products(sess) == ["KB 딱좋은 0540 건강보험 무배당",
                                          "KB 3.10.5 딱좋은 초경증 건강보험 무배당(간편심사형)"]
    finally:
        del os.environ["KB_LIST_URLS"]


def test_kb_json_fallback():
    obj = {"data": {"list": [{"prdtNm": "KB 딱좋은 0540 건강보험 무배당", "seqNo": "501619081",
                              "saleStartDt": "20261001", "saleEndDt": "99991231"}]}}
    ps = kb.parse_kb_list(json.dumps(obj, ensure_ascii=False))
    assert ps == [{"title": "KB 딱좋은 0540 건강보험 무배당",
                   "rows": [{"seqno": "501619081", "start": "20261001", "end": "", "label": ""}]}]


def test_kb_requires_url_and_fails_on_spa():
    os.environ.pop("KB_LIST_URLS", None)
    try:
        kb.list_editions(FakeSess([]), ["x"])
    except siteutil.CollectorError as e:
        assert "KB_LIST_URLS" in str(e)
    else:
        raise AssertionError
    os.environ["KB_LIST_URLS"] = "https://example.invalid/list"
    try:
        kb.list_editions(FakeSess([(("GET", "https://example.invalid/list", {}), "<div id=app></div>")]), ["x"])
    except siteutil.CollectorError as e:
        assert "data-seqno" in str(e)
    else:
        raise AssertionError
    finally:
        del os.environ["KB_LIST_URLS"]


# ── 동양생명 ────────────────────────────────────────────────

DY_LIST = {"totalCnt": 3, "list": [
    {"GOODS_NM": "무배당 우리WON하는 간편보장보험", "SALE_STRT_DT": "20260101", "SALE_END_DT": ""},
    {"GOODS_NM": "무배당 우리WON하는 간편보장보험(갱신형)", "SALE_STRT_DT": "20260101", "SALE_END_DT": ""},
    {"GOODS_NM": "무배당 수호천사 연금보험", "SALE_STRT_DT": "20200101", "SALE_END_DT": "20221231"},
]}
DY_DETAIL = {"result": "OK", "list": [
    {"GOODS_NM": "무배당 우리WON하는 간편보장보험", "SALE_STRT_DT": "2026-09-01", "SALE_END_DT": "9999-12-31",
     "FILE_GRP_ID1": "", "FILE_GRP_ID2": "G2002", "FILE_GRP_ID3": "G3002"},
    {"GOODS_NM": "무배당 우리WON하는 간편보장보험", "SALE_STRT_DT": "2026-01-01", "SALE_END_DT": "2026-08-31",
     "FILE_GRP_ID1": "G1001", "FILE_GRP_ID2": "G2001", "FILE_GRP_ID3": "G3001"},
    {"GOODS_NM": "무배당 우리WON하는 간편보장보험(갱신형)", "SALE_STRT_DT": "2026-09-01", "SALE_END_DT": "",
     "FILE_GRP_ID2": "X", "FILE_GRP_ID3": "Y"},
]}


def dy_sess(detail=DY_DETAIL):
    return FakeSess([
        (("POST", dongyang.DETAIL_URL, {"GOODS_NM": "무배당우리WON하는간편보장보험"}), json.dumps(detail, ensure_ascii=False)),
        (("POST", dongyang.LIST_URL, {"nameStr": ""}), json.dumps(DY_LIST, ensure_ascii=False)),
    ])


def test_dongyang_detail_parse():
    rows = dongyang.parse_dongyang_detail(DY_DETAIL)
    assert rows[0]["start"] == "20260901" and rows[0]["end"] == ""
    assert rows[0]["files"] == {"약관": "G3002", "사업방법서": "G2002"}
    assert rows[1]["files"]["상품요약서"] == "G1001"


def test_dongyang_editions():
    eds = dongyang.list_editions(dy_sess(), ["무배당 우리WON하는 간편보장보험"])
    got = [(e.start, e.end, e.disclosure_id, sorted(d.doc_type for d in e.docs)) for e in eds]
    assert got == [("20260101", "20260831", "G3001", ["사업방법서", "상품요약서", "약관"]),
                   ("20260901", "", "G3002", ["사업방법서", "약관"])], got  # 갱신형 행은 걸러짐
    d = eds[1].docs[0]
    assert d.fetch["method"] == "POST" and d.fetch["data"] == {"_biz_op_code": "FDL", "FILE_GRP_ID": "G3002"}


def test_dongyang_products():
    assert dongyang.list_products(dy_sess()) == ["무배당 우리WON하는 간편보장보험", "무배당 우리WON하는 간편보장보험(갱신형)"]


def test_dongyang_non_json_fails():
    sess = FakeSess([])  # 모든 요청에 HTML
    try:
        dongyang.list_editions(sess, ["무배당 우리WON하는 간편보장보험"])
    except siteutil.CollectorError as e:
        assert "JSON 이 아닌" in str(e)
    else:
        raise AssertionError


def test_dongyang_missing_fails():
    try:
        dongyang.list_editions(dy_sess(detail={"list": []}), ["무배당 우리WON하는 간편보장보험"])
    except siteutil.CollectorError as e:
        assert "찾지 못했습니다" in str(e)
    else:
        raise AssertionError


# ── 공통 ───────────────────────────────────────────────────

def test_debug_flag():
    argv = ["x.py", "--root", "r", "--debug-dump", "/tmp/dd", "--dry-run"]
    old = os.environ.pop(siteutil.DEBUG_ENV, None)
    siteutil.consume_debug_flag(argv)
    assert argv == ["x.py", "--root", "r", "--dry-run"] and os.environ[siteutil.DEBUG_ENV] == "/tmp/dd"
    del os.environ[siteutil.DEBUG_ENV]
    if old:
        os.environ[siteutil.DEBUG_ENV] = old


def test_dates():
    assert siteutil.dates_in("2026.10.01 ~ 현재") == ["20261001"]
    assert siteutil.dates_in("2026-4-1~2026/09/30") == ["20260401", "20260930"]
    assert siteutil.ymd("99991231") == "" and siteutil.ymd("2026년 9월 1일") == "20260901"


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, type(e).__name__, e)
    print(f"{'실패 ' + str(fails) + '건' if fails else '모두 통과'}")
    sys.exit(1 if fails else 0)
