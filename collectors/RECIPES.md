# 회사별 공시실 수집 경로

출처: Drive `work/2601/README_수집현황.md`(2026-10-11)에서 옮김. 1월판 수집에 실제로 쓴 방법이다.

## 하나생명
판매중지 목록 `https://www.hanalife.co.kr/anm/product/allProduct.do?status=off`에 2014년까지의 과거판이 보존돼 있다. 약관은 `/anm/product/download.do?code=<코드>&seq=1`, 사업방법서는 `/home/download2.do?fileName=PROD/<파일명>`이다. 1월판 코드는 610778(누리는) · 610801(누리는 간편) · 610800(누리는 갱신) · 610802(누리는 갱신 간편) · 610779(라이트 3.10.5) · 610780(라이트 갱신). 9월판 약관 파일명 앞 번호는 611052 · 611072 · 611073 · 611053 · 611054 · 611074 (계약자용약관_20260901). 사업방법서는 「누리는」과 「누리는(간편심사형)」 두 파일을 6상품이 공유한다.

## KB라이프
아코디언 `.panel`의 과거 판매기간과 `data-seqno`로 공시번호를 찾고, `https://www.kblife.co.kr/api/archive/archives/download/product-terms/{공시번호}/{box}`에서 box 1=사업방법서, box 2=약관을 받는다. 건강보험 보장성은 box 0(요약서)이 비어 있다. 2026/10/01판 현행 공시번호 501619071~107.

## 신한라이프
`/hp/cdhi0030.do` 페이지의 함수를 그대로 쓴다. `dp.Ajax.send`에 `trId: 'co/wcms/nodeInfoList'`, `jsonData.method='selectAllListGoods'`, `meta05=<상품명>`을 넘기면 전체 판 목록이 온다. 판별 필드는 `meta07`(개시) `meta08`(종료) `meta09`(요약서) `meta10`(방법서) `meta11`(약관)이다. 파일 경로는 `/repo/...`가 아니라 **`/bizxpress/cdh/cdhi/gd/pr/__etc/<파일명>`** 으로 바꿔야 받아진다(`dp.Utils.getFileObject`가 하는 일). 목록 조회는 `co/wcms/nodeInfoListPage.pwkjson`.

## 미래에셋생명
`POST https://life.miraeasset.com/micro/cmmnFileDown.do`에 `pathType=gongci_u1`, `filePath=/uploadwas/life/html/gongci/upload/1/`, `fileName`=`orgFileName`=`<상품명>_약관_20260101.pdf` 형식으로 보내면 바로 받아진다. 파일명 규칙이 일정해서 존재 여부 확인용 프로브로도 쓸 수 있다(없는 판은 29,950바이트 HTML이 온다). 2026-10-14 클라우드에서 `M-케어 건강보험 무배당_약관_20260101.pdf`(24.9MB, 2,876쪽)를 62초에 받는 것을 확인했다. 미래에셋 상품요약서 PDF는 이미지 스캔본이라 텍스트 추출이 안 된다.

## 흥국생명
`POST /front/public/saleProductAjax.do` 에 `searchFlgSale=Y`, `searchCdPublicPrtType1=I101`, `searchCdPublicPrtType3=<상품명>`을 보낸다. 상품명은 `escape(encodeURIComponent(name))` 이중 인코딩이고 응답은 EUC-KR이다. 응답은 `%||%`로 섹션이 갈리고 세 번째 섹션이 다운로드 행이다. 행은 `%,%`로 쪼개 `[0]`개시일 `[1]`종료일 `[2]`공시번호 `[4]`약관토큰 `[5]`약관파일명 `[6]`방법서토큰 `[7]`방법서파일명 `[8]`요약서토큰 `[9]`요약서파일명 순이다. 토큰을 `encValue`로 `POST /servlet/DownLoadEnc.do`에 보내면 PDF가 내려온다(`beforeYn`은 결과에 영향 없음 — 과거판이 기본으로 전부 나온다).

## 동양생명
목록은 `POST https://pbano.myangel.co.kr/paging/WE_AC_WEPAAP020100L` 에 `_biz_op_code=IQY`, `sale_kind=ALL`(중요 — `1`로 보내면 빈 목록이 온다), `goods_kind=ALL`, `nameStr=<검색어>`. 과거판은 `POST /process/WE_AC_WEPAAP020100D` 에 `_biz_op_code=IQY_D`, `GOODS_NM=<공백 없는 상품명>`, `SALE_KIND=01`. 파일은 `POST /process/CO_ComDownload` 에 `_biz_op_code=FDL`, `FILE_GRP_ID=<FILE_GRP_ID3(약관)/2(방법서)>`.

## 접속 가능 여부 (2026-10-14, 클라우드 환경)
| 회사 | 결과 |
|---|---|
| 미래에셋 · 신한 | 접속됨 |
| 흥국 | 2026-10-14 오후부터 모든 경로가 "해외 IP 로그인 일시 제한 안내"(2,281바이트) 페이지를 돌려줌. 공지상 차단 기간 2026-10-07~10-26 |
| 하나 | TLS 연결 직후 서버가 끊음 |
| KB · 동양 | 응답 없음(시간 초과) |

하나·KB·동양은 사용자 Mac에서 수집한다.
