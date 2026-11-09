// 건강보험 담보 레이더 — 화면 로직(데이터는 모두 서버 API에서 받는다)
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const dash = v => (!v || v === "없음") ? `<span class="dash">${v ? "없음" : "–"}</span>` : esc(v);
const X = '<span class="ox x">X</span>';
const S = { snap: "", major: "", q: "", common: false, tab: "list", page: 0, data: null, uw: null };

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Requested-With": "app", ...(opts.headers || {}) } });
  if (res.status === 401) { showLogin(); throw new Error("login"); }
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(j.detail || j.error || res.statusText);
  return j;
}

function showLogin() { $("app").hidden = true; $("login").hidden = false; $("pw").focus(); }
$("login").addEventListener("submit", async e => {
  e.preventDefault();
  try { await api("/api/login", { method: "POST", body: JSON.stringify({ password: $("pw").value }) }); $("login").hidden = true; boot(); }
  catch (err) { if (err.message !== "login") $("login-msg").textContent = err.message; }
});

function grouped(rs, span, cell) {
  let h = "", last = "";
  rs.forEach(it => { const g = it.major + " · " + it.standard;
    if (g !== last) { h += `<tr class="grp"><td class="sticky" colspan="${span}" style="background:var(--accent-soft)">${esc(g)}</td></tr>`; last = g; }
    h += cell(it); });
  return h;
}

function perCompany(field, label, wide) {
  const C = S.data.companies, rs = S.data.items;
  const h = `<table><thead><tr><th class="sticky">세부담보명</th>${C.map(c => `<th class="co">${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
    grouped(rs, C.length + 1, it => `<tr><td class="sticky">${esc(it.detail)}</td>${C.map(c => it.by[c]
      ? `<td class="co${wide ? " wrap" : ""}" style="${wide ? "min-width:180px;font-size:12.5px" : ""}">${dash(it.by[c][field])}</td>` : `<td class="co">${X}</td>`).join("")}</tr>`);
  return [h, `${label} · 세부담보 ${rs.length}종 · 한 회사 안에 값이 여러 개면 가장 많은 값과 "외 n"`];
}

async function render() {
  const P = $("panel"); let html = "", cap = "";
  try {
    if (S.tab === "rows") {
      const r = await api(`/api/rows?snapshot=${S.snap}&q=${encodeURIComponent(S.q)}&page=${S.page}`);
      const pages = Math.max(1, Math.ceil(r.total / r.size));
      html = `<table><thead><tr><th>회사</th><th>상품</th><th class="sticky">특약명</th><th>심사기준</th><th>급부명</th><th>세부담보명</th><th>지급금액</th><th>횟수</th><th>면책</th><th>감액</th><th>근거</th><th>검증</th></tr></thead><tbody>` +
        r.rows.map(x => `<tr><td>${esc(x.company)}</td><td class="wrap" style="min-width:180px;font-size:12.5px">${esc(x.product)}</td><td class="sticky wrap" style="min-width:220px;font-size:12.5px">${esc(x.rider)}</td><td>${esc(x.uw)}</td><td class="wrap" style="min-width:160px">${esc(x.benefit)}</td><td class="wrap" style="min-width:180px">${esc(x.detail)}</td><td>${esc(x.amount)}</td><td>${esc(x.count)}</td><td>${dash(x.exempt)}</td><td>${dash(x.reduce)}</td><td>${esc(x.source)}</td><td>${esc(x.verify)}</td></tr>`).join("");
      cap = `<span class="pager">${r.total.toLocaleString()}행 · ${S.page + 1}/${pages}쪽 <button class="chip" id="prev" ${S.page ? "" : "disabled"}>이전</button><button class="chip" id="next" ${S.page + 1 < pages ? "" : "disabled"}>다음</button></span>`;
    } else if (S.tab === "diff") {
      const d = await api(`/api/diff`);
      if (!d.available) {
        html = `<p class="muted">비교할 이전 기준일이 없습니다. 업데이트로 새 기준일 DB가 쌓이면 회사별 신설·폐지·조건 변경이 여기 표시됩니다. (현재 기준일: ${esc(d.snapshots.join(", "))})</p>`;
      } else {
        html = `<table><thead><tr><th>회사</th><th class="sticky">세부담보</th><th>변경</th><th>항목</th><th>이전 (${esc(d.old)})</th><th>이후 (${esc(d.new)})</th></tr></thead><tbody>` +
          d.changes.map(c => `<tr><td>${esc(c.company)}</td><td class="sticky">${esc(c.detail)}</td><td>${esc(c.change)}</td><td>${esc(c.field)}</td><td>${dash(c.before)}</td><td>${dash(c.after)}</td></tr>`).join("");
        cap = `${d.old} → ${d.new} 변경 ${d.changes.length}건`;
      }
    } else if (S.tab === "uw") {
      const u = S.uw || (S.uw = await api(`/api/underwriting?snapshot=${S.snap}`));
      html = `<table><thead><tr><th class="sticky">심사기준</th>${u.companies.map(c => `<th class="co">${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
        u.underwriting.map(w => `<tr><td class="sticky">${esc(w)}</td>${u.companies.map(c => { const o = u.products.some(p => p.company === c && p.uw.includes(w)); return `<td class="c co"><span class="ox ${o ? "o" : "x"}">${o ? "O" : "X"}</span></td>`; }).join("")}</tr>`).join("") +
        `</tbody></table><h3 style="margin:18px 0 8px">상품별 심사기준</h3><table><thead><tr><th>회사</th><th>상품</th><th>심사기준</th></tr></thead><tbody>` +
        u.products.map(p => `<tr><td>${esc(p.company)}</td><td>${esc(p.product)}</td><td>${p.uw.map(esc).join(", ")}</td></tr>`).join("");
    } else {
      const C = S.data.companies, rs = S.data.items;
      if (S.tab === "list") {
        html = `<table><thead><tr><th class="sticky">세부담보명</th><th>표준담보명</th><th>보유 회사</th><th>정의(대표 원문)</th><th>분류코드</th></tr></thead><tbody>` +
          grouped(rs, 5, it => `<tr><td class="sticky"><strong>${esc(it.detail)}</strong></td><td>${esc(it.standard)}</td><td>${Object.keys(it.by).map(esc).join("<br>")}</td><td class="wrap" style="min-width:320px;font-size:12.5px">${esc(it.definition)}</td><td class="wrap mono" style="min-width:220px;font-size:12px">${esc(it.kcd) || '<span class="dash">–</span>'}</td></tr>`);
        cap = `표준담보 ${new Set(rs.map(r => r.standard)).size}종 · 세부담보 ${rs.length}종`;
      } else if (S.tab === "ox") {
        html = `<table><thead><tr><th class="sticky">세부담보명</th>${C.map(c => `<th class="co">${esc(c)}</th>`).join("")}<th class="c">보유</th></tr></thead><tbody>` +
          grouped(rs, C.length + 2, it => `<tr><td class="sticky">${esc(it.detail)}</td>${C.map(c => `<td class="c co"><span class="ox ${it.by[c] ? "o" : "x"}">${it.by[c] ? "O" : "X"}</span></td>`).join("")}<td class="c">${Object.keys(it.by).length}/${C.length}</td></tr>`);
        cap = "O: 정의·분류코드 범위가 같은 담보를 판매 · X: 미판매 또는 범위가 달라 다른 세부담보로 분류";
      } else if (S.tab === "pay") {
        html = `<table><thead><tr><th class="sticky" rowspan="2">세부담보명</th>${C.map(c => `<th class="co" colspan="2">${esc(c)}</th>`).join("")}</tr><tr>${C.map(() => `<th class="co">지급금액</th><th>지급횟수</th>`).join("")}</tr></thead><tbody>` +
          grouped(rs, C.length * 2 + 1, it => `<tr><td class="sticky">${esc(it.detail)}</td>${C.map(c => it.by[c] ? `<td class="co">${esc(it.by[c].amount)}</td><td>${esc(it.by[c].count)}</td>` : `<td class="co">${X}</td><td><span class="dash">–</span></td>`).join("")}</tr>`);
        cap = "지급금액은 특약 보험가입금액 대비 비율과 지급 단위";
      } else if (S.tab === "exempt") [html, cap] = perCompany("exempt", "면책(보장개시까지 지급하지 않는 기간)");
      else if (S.tab === "reduce") [html, cap] = perCompany("reduce", "감액(경과기간 내 지급률)");
      else if (S.tab === "wait") [html, cap] = perCompany("wait", "대기·지급요건", true);
    }
    P.innerHTML = `<div class="tbl-wrap" style="max-height:72vh">${html}</tbody></table></div>`;
    $("caption").innerHTML = cap;
    const pv = $("prev"), nx = $("next");
    if (pv) pv.onclick = () => { S.page--; render(); };
    if (nx) nx.onclick = () => { S.page++; render(); };
  } catch (e) { if (e.message !== "login") P.innerHTML = `<p class="notice">불러오지 못했습니다: ${esc(e.message)}</p>`; }
}

async function loadCoverages() {
  const p = new URLSearchParams({ snapshot: S.snap, major: S.major, q: S.q, common_only: S.common });
  S.data = await api(`/api/coverages?${p}`);
  const st = S.data.stats;
  $("kpis").innerHTML = [["급부 행", st.rows.toLocaleString()], ["표준담보", st.standards], ["세부담보", st.details], ["전 회사 공통", st.common_all]]
    .concat(Object.entries(st.by_company).map(([c, n]) => [c, n])).map(([k, v]) => `<div class="kpi"><span>${esc(k)}</span><b>${v}</b></div>`).join("");
  render();
}

// ---------- 업데이트 실행 ----------
let timer = null;
function table(title, rows, cols) {
  if (!rows || !rows.length) return `<p class="muted" style="font-size:13px">${title}: 없음</p>`;
  return `<h3 style="margin:6px 0">${title} ${rows.length}건</h3><div class="tbl-wrap"><table><thead><tr>${cols.map(c => `<th>${c[1]}</th>`).join("")}</tr></thead><tbody>` +
    rows.map(r => `<tr>${cols.map(c => `<td class="wrap">${esc(r[c[0]])}</td>`).join("")}</tr>`).join("") + `</tbody></table></div>`;
}
async function pollRun() {
  const { job, report } = await api("/api/runs/latest");
  $("run").disabled = job.running; $("run").textContent = job.running ? "실행 중…" : "실행";
  $("run-state").textContent = job.running ? `진행: ${job.step}` : (job.finished ? `마지막 실행 ${job.finished} · ${job.ok ? "정상" : "실패"}` : "");
  $("run-log").textContent = (job.log || []).join("\n");
  if (report) {
    const d = report["변경"] || {};
    $("run-result").innerHTML = `<div class="kpis"><div class="kpi"><span>판별한 기초서류</span><b>${report["판별"]}</b></div><div class="kpi"><span>새 파일</span><b>${(d.new || []).length}</b></div><div class="kpi"><span>개정</span><b>${(d.changed || []).length}</b></div><div class="kpi"><span>삭제</span><b>${(d.removed || []).length}</b></div><div class="kpi"><span>판별 실패</span><b>${(report["판별 실패"] || []).length}</b></div></div>` +
      table("개정된 기초서류", d.changed, [["company", "회사"], ["product", "상품"], ["doc_type", "문서"], ["previous_edition", "이전 판"], ["edition", "새 판"]]) +
      table("새로 들어온 기초서류", d.new, [["company", "회사"], ["product", "상품"], ["doc_type", "문서"], ["edition", "개정일"]]) +
      table("판별 실패", report["판별 실패"], [["path", "파일"], ["이유", "판별 못한 항목"]]);
  }
  if (!job.running && timer) { clearInterval(timer); timer = null; }
  if (job.running && !timer) timer = setInterval(pollRun, 1500);
}
$("run").addEventListener("click", async () => {
  try { await api("/api/runs", { method: "POST", body: JSON.stringify({ download: $("dl").checked, since: $("since").value.trim(), ai: $("ai").checked }) }); pollRun(); }
  catch (e) { $("run-state").textContent = e.message; }
});

$("ai").addEventListener("change", async e => {
  const el = $("ai-est"); el.hidden = !e.target.checked; if (!e.target.checked) return;
  el.textContent = "비용 추정 중…";
  try {
    const { estimate: x } = await api("/api/ai/estimate");
    el.textContent = x ? `이번에 새로 분석할 특약 묶음 ${x["새로 분석"]}개 / 전체 ${x["묶음"]}개 · 추정 비용 약 $${x["추정 비용(USD, 배치 50%)"]} (배치 할인 적용, 근사치). 본문이 같은 묶음은 다시 분석하지 않습니다.`
      : "특약 묶음이 아직 없습니다. 먼저 AI 없이 한 번 실행하면 추정할 수 있습니다.";
  } catch (err) { el.textContent = "추정 실패: " + err.message; }
});

// ---------- 시작 ----------
async function boot() {
  const m = await api("/api/meta");
  $("app").hidden = false;
  $("snap").innerHTML = m.snapshots.map(s => `<option>${esc(s)}</option>`).join("");
  S.snap = m.snapshots[0] || "";
  $("root").textContent = m.docs_root + (m.docs_root_exists ? "" : " (폴더 없음 — DOCS_ROOT 설정 확인)");
  const f = $("filters");
  ["전체", ...m.majors].forEach(name => { const b = document.createElement("button"); b.className = "chip"; b.type = "button"; b.textContent = name; b.setAttribute("aria-pressed", name === "전체");
    b.onclick = () => { S.major = name === "전체" ? "" : name; f.querySelectorAll(".chip").forEach(c => c.setAttribute("aria-pressed", c === b)); loadCoverages(); }; f.appendChild(b); });
  const dls = await api("/api/downloads");
  $("downloads").innerHTML = dls.map(d => `<li><a href="/download/${encodeURIComponent(d.name)}">${esc(d.name)}</a> <span class="muted" style="font-size:12px">${(d.size / 1048576).toFixed(1)}MB</span></li>`).join("");
  await loadCoverages(); pollRun();
}
$("snap").onchange = e => { S.snap = e.target.value; S.uw = null; S.page = 0; loadCoverages(); };
let qt; $("q").oninput = e => { clearTimeout(qt); qt = setTimeout(() => { S.q = e.target.value.trim(); S.page = 0; S.tab === "rows" ? render() : loadCoverages(); }, 250); };
$("common").onchange = e => { S.common = e.target.checked; loadCoverages(); };
document.querySelectorAll("#tabs .tab").forEach(t => t.onclick = () => { S.tab = t.dataset.tab; S.page = 0;
  document.querySelectorAll("#tabs .tab").forEach(x => x.setAttribute("aria-selected", x === t)); render(); });
boot().catch(e => { if (e.message !== "login") document.body.insertAdjacentHTML("afterbegin", `<p class="notice">서버에 연결할 수 없습니다: ${esc(e.message)}</p>`); });
