// CEM10 — interfejs: stan z /api/state (serwer lokalny programu), widoki: Ten miesiąc, Portfel, Lista USA / GPW, Historia konta, Ustawienia; wykres miesięczny w szufladzie.
"use strict";
const TOKEN = new URLSearchParams(location.hash.slice(1)).get("t") || "";
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nbsp = " ";
const grp = (s) => s.replace(/\B(?=(\d{3})+(?!\d))/g, nbsp);
function zl(x) { if (x == null || !isFinite(x)) return "—"; const n = Math.round(x); return (n < 0 ? "−" : "") + grp(String(Math.abs(n))) + nbsp + "zł"; }
function num(x, d = 2) { if (x == null || !isFinite(x)) return "—"; const [a, b] = Math.abs(x).toFixed(d).split("."); return (x < 0 ? "−" : "") + grp(a) + (b ? "," + b : ""); }
function pct(x, d = 1, sign = true) { if (x == null || !isFinite(x)) return "—"; const v = x * 100; return (v > 0 && sign ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d).replace(".", ",") + nbsp + "%"; }
const cls = (x) => (x == null ? "" : x > 0 ? "pos" : x < 0 ? "neg" : "");
const BUCKET = { usa: "CEM10 USA", gpw: "CEM10 GPW", etf: "ETF", inne: "Inne" };
const BCOL = { usa: "var(--usa)", gpw: "var(--gpw)", etf: "var(--etf)", inne: "var(--inne)", cash: "var(--cash)" };
const MONTHS = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień"];
const monthName = (ym) => { if (!ym) return "—"; const [y, m] = ym.split("-").map(Number); return `${MONTHS[m - 1]} ${y}`; };
const nextMonth = (ym) => { const [y, m] = ym.split("-").map(Number); return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`; };

let S = null;                       // ostatni stan z serwera
let view = "home";
try { view = localStorage.getItem("cem10_view") || "home"; } catch (e) { /* bez localStorage */ }
const ui = { q: { usa: "", gpw: "" }, all: { usa: false, gpw: false } };

async function api(path, opt = {}) {
  const r = await fetch("/api/" + path, { ...opt, headers: { "X-CEM10": TOKEN, ...(opt.headers || {}) } });
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}), headers: { "Content-Type": "application/json" } });

function toast(msg, bad = false) {
  const el = document.createElement("div");
  el.className = "toast" + (bad ? " bad" : "");
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), bad ? 7000 : 3800);
}

// ------------------------------------------------------------------ stan i odświeżanie
async function load() {
  try { setState(await api("state")); } catch (e) { $("#view").innerHTML = `<div class="alert">Brak połączenia z programem: ${esc(e.message)}</div>`; }
}
let polling = null;
function setState(s) {
  const was = S && S.task && S.task.busy;
  S = s;
  renderTop();
  renderView();
  const t = S.task;
  if (t.busy && !polling) polling = setInterval(pollTask, 700);
  if (!t.busy && polling) { clearInterval(polling); polling = null; }
  if (was && !t.busy) { if (t.error) toast(t.error, true); else if (t.done) toast(t.done); }
}
async function pollTask() {
  try {
    const s = await api("state");
    if (s.task.busy) { S.task = s.task; renderProgress(); } else setState(s);
  } catch (e) { /* program zamknięty */ }
}

// ------------------------------------------------------------------ pasek górny
function renderTop() {
  const L = S.lists, chips = [];
  if (L) {
    const lead = L.usa.lead === "NDX" ? "Nasdaq-100" : "S&P 500";
    chips.push(`<span class="chip"><i></i>Lista: ${esc(monthName(L.month))}</span>`);
    chips.push(`<span class="chip ${L.usa.bear ? "bad" : "good"}" title="SPY ${num(L.usa.spy)} / SMA 12 ${num(L.usa.spy_sma12)}"><i></i>USA: ${L.usa.bear ? "brak zakupów" : "zakupy dozwolone"} · lider ${lead}</span>`);
    chips.push(`<span class="chip ${L.gpw.bear ? "bad" : "good"}"><i></i>GPW: ${L.gpw.bear ? "brak zakupów" : "zakupy dozwolone"}</span>`);
  } else chips.push(`<span class="chip warn"><i></i>Brak listy — kliknij „Pobierz listę”</span>`);
  $("#topStatus").innerHTML = chips.join("");
  const nu = $("#navUsa"), ng = $("#navGpw");
  nu.textContent = L ? (L.usa.bear ? "stop" : String(Math.min(L.usa.rows.length, L.usa.n))) : "";
  ng.textContent = L ? (L.gpw.bear ? "stop" : String(Math.min(L.gpw.rows.length, L.gpw.n))) : "";
  nu.className = L && L.usa.bear ? "off" : ""; ng.className = L && L.gpw.bear ? "off" : "";
  renderProgress();
  const th = S.settings.theme || "auto";
  $("#themeLbl").textContent = { auto: "system", light: "jasny", dark: "ciemny" }[th];
  if (th === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = th;
  try { localStorage.setItem("cem10_theme", th); } catch (e) { /* bez localStorage */ }
}
function renderProgress() {
  const t = S.task;
  $("#progress").hidden = !t.busy;
  $("#fetchBtn").disabled = t.busy;
  $("#progressBar").style.width = Math.round((t.progress || 0) * 100) + "%";
  $("#progressTxt").textContent = t.log || "";
  const cb = $("#curveBtn");
  if (cb) cb.disabled = t.busy;
}

// ------------------------------------------------------------------ nawigacja
function go(v) {
  view = v;
  try { localStorage.setItem("cem10_view", v); } catch (e) { /* bez localStorage */ }
  renderView();
  $("#view").focus({ preventScroll: true });
  window.scrollTo(0, 0);
}
$("#nav").addEventListener("click", (e) => { const b = e.target.closest("button[data-view]"); if (b) go(b.dataset.view); });
function renderView() {
  for (const b of document.querySelectorAll("#nav button")) { if (b.dataset.view === view) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); }
  const f = { home: viewHome, pf: viewPortfolio, usa: () => viewList("usa"), gpw: () => viewList("gpw"), hist: viewHistory, set: viewSettings }[view] || viewHome;
  const el = $("#view");
  const active = document.activeElement && document.activeElement.id;
  el.innerHTML = f();
  bindView();
  if (active && $("#" + active)) { const a = $("#" + active); a.focus(); if (a.setSelectionRange && a.type === "text") a.setSelectionRange(a.value.length, a.value.length); }
}

// ------------------------------------------------------------------ Ten miesiąc
function viewHome() {
  const L = S.lists, P = S.portfolio, PL = S.plan;
  const title = L ? `Plan na ${monthName(nextMonth(L.month))}` : "Ten miesiąc";
  const sub = L ? `Z zamknięcia miesiąca: ${monthName(L.month)} · pobrano ${esc(L.generated_at || "")}` : "Lista liczy się z zamkniętych świec miesięcznych.";
  let h = `<header class="page-head"><div><h1>${title}</h1><p>${sub}</p></div></header>`;
  if (!L || !P) {
    h += `<section class="card"><div class="card-head"><h2>Zacznij w dwóch krokach</h2></div><div class="steps">
      <div class="step ${P ? "done" : ""}"><span class="n">${P ? "✓" : "1"}</span><div><b>Wczytaj raport z XTB</b><p class="muted">xStation → Historia konta → Eksport. Program czyta tylko plik, nie łączy się z XTB.</p>
        ${P ? `<span class="pill good">Konto ${esc(P.label)}</span>` : `<button class="btn" data-act="xtb" type="button">Wybierz plik raportu…</button>`}
        ${P ? "" : `<button class="ghost sm" data-go="set" type="button">albo wpisz trzymane spółki ręcznie</button>`}</div></div>
      <div class="step ${L ? "done" : ""}"><span class="n">${L ? "✓" : "2"}</span><div><b>Pobierz listę CEM10</b><p class="muted">Skład indeksów, sito Finviz i ceny miesięczne z Yahoo Finance. Około minuty.</p>
        ${L ? `<span class="pill good">Lista za ${esc(monthName(L.month))}</span>` : `<button class="btn primary" data-act="fetch" type="button">Pobierz listę</button>`}</div></div>
    </div></section>`;
  }
  if (P) {
    h += `<div class="kpis">
      <div class="card kpi"><span class="s">Wartość konta</span><span class="v">${zl(P.total)}</span><span class="s">pozycje ${zl(P.positions_value)} · gotówka ${zl(P.cash)}</span></div>
      <div class="card kpi"><span class="s">Wynik</span><span class="v ${cls(P.profit)}">${zl(P.profit)}</span><span class="s ${cls(P.profit)}">${pct(P.profit_pct)} od wpłat</span></div>
      <div class="card kpi"><span class="s">Wpłacono netto</span><span class="v">${zl(P.deposited)}</span><span class="s">konto ${esc(P.label)} · raport ${esc((P.generated || "").slice(0, 10))}</span></div>
      <div class="card kpi"><span class="s">Pozycje CEM10</span><span class="v">${P.rows.filter((r) => r.bucket === "usa").length} / ${S.rules.slots.usa} · ${P.rows.filter((r) => r.bucket === "gpw").length} / ${S.rules.slots.gpw}</span><span class="s">USA · GPW (zajęte / miejsca)</span></div>
    </div>`;
  }
  const warn = P ? P.rows.filter((r) => r.status.startsWith("SPRZEDAJ")) : S.manual.filter((m) => m.decision !== "trzymaj");
  h += `<div class="cols"><div class="stack">`;
  if (warn.length) h += `<div class="alert">⚠ Do sprzedaży: ${warn.map((r) => esc(r.t)).join(", ")} — zamknięcie miesiąca pod SMA 10, spadek z indeksu albo stop −40 %.</div>`;
  h += `<section class="card"><div class="card-head"><div><h2>Co zrobić</h2><p>Kupujesz i sprzedajesz po zamknięciu miesiąca, w pierwszych dniach nowego.</p></div>
        ${PL && PL.actions.length ? `<button class="btn sm" data-act="copy" type="button">Kopiuj plan</button>` : ""}</div>`;
  if (P && L) {
    h += `<div class="row"><label class="field" style="flex:1;min-width:200px"><span>Wpłata w tym miesiącu</span><span class="money"><input type="text" inputmode="decimal" id="deposit" value="${esc(num(S.settings.deposit, 0))}"><b>zł</b></span></label></div>`;
    h += planList(PL);
  } else if (L && S.manual.length) {
    h += manualList();
  } else {
    h += `<div class="empty">Plan pojawi się po wczytaniu raportu XTB i pobraniu listy.</div>`;
  }
  h += `</section>`;
  h += `</div><div class="stack">`;
  if (L) h += marketCard(L);
  if (P) h += allocCard(P, PL);
  h += `</div></div>`;
  return h;
}
function planList(PL) {
  if (!PL) return "";
  const s = PL.summary;
  let h = "";
  if (!PL.actions.length) {
    h += `<div class="empty"><b>Nic do zrobienia</b>Wszystkie pozycje trzymasz. ${zl(s.free)} zostaje w gotówce (za mało na zakup ≥ ${zl(S.rules.min_topup)} albo koszyki są na wadze docelowej).</div>`;
  } else {
    const kind = { SPRZEDAJ: "bad", KUP: "good", "DOPŁAĆ": "info" };
    h += `<div class="actions">` + PL.actions.map((a) => `<div class="act" data-sym="${esc(a.yahoo)}" data-title="${esc(a.name || a.ticker)}" tabindex="0" role="button">
      <span class="pill ${kind[a.akcja] || ""}">${esc(a.akcja)}</span>
      <div class="who"><b>${esc(a.ticker)}</b> <span class="tag" style="--c:${BCOL[a.koszyk]}">${BUCKET[a.koszyk]}</span><small>${esc(a.name || "")}${a.uwagi ? " · " + esc(a.uwagi) : ""}</small></div>
      <div class="amt"><b>${zl(a.kwota)}</b><small>${a.akcja === "SPRZEDAJ" ? "całą pozycję" : a.shares ? "≈ " + num(a.shares, a.shares < 10 ? 3 : 1) + " akcji po " + num(a.price) + " " + a.ccy : ""}</small></div></div>`).join("") + `</div>`;
  }
  const al = s.alloc;
  h += `<p class="note">Do rozdysponowania ${zl(s.free)} (gotówka + wpłata + sprzedaże): USA ${zl(al.usa)}, GPW ${zl(al.gpw)}, ETF ${zl(al.etf)}; zostaje w gotówce ${zl(s.cash_left)}.
        Liczba akcji z zamknięcia miesiąca${PL.usd ? `, kurs USD ${num(PL.usd, 2)}` : ""}; w XTB kupujesz za kwotę. ${s.notes.map(esc).join(" ")}</p>`;
  return h;
}
function manualList() {
  return `<div class="tbl-wrap"><table><thead><tr><th>Spółka</th><th>Rynek</th><th class="r">Od SMA 10</th><th>Decyzja</th></tr></thead><tbody>` +
    S.manual.map((m) => `<tr class="${m.decision === "trzymaj" ? "" : "sell"}" data-sym="${esc(m.yahoo)}" data-title="${esc(m.row ? m.row.n : m.t)}">
      <td><span class="t">${esc(m.t)}</span> <span class="n">${esc(m.row ? m.row.n : m.note)}</span></td><td>${m.market}</td>
      <td class="r ${cls(m.row && m.row.dist)}">${m.row ? pct(m.row.dist) : "—"}</td>
      <td><span class="pill ${m.decision === "trzymaj" ? "good" : m.decision === "sprzedaj" ? "bad" : "warn"}">${m.decision}</span></td></tr>`).join("") + `</tbody></table></div>`;
}
function marketCard(L) {
  const U = L.usa, G = L.gpw, lead = U.lead === "NDX" ? "Nasdaq-100 (QQQ)" : "S&P 500 (SPY)";
  return `<section class="card"><div class="card-head"><h2>Rynek</h2><span class="muted xs">${esc(monthName(L.month))}</span></div>
    <div class="alloc-rows">
      <div class="alloc-row"><span>Lider USA (zwrot 5 mies.)</span><b>${lead}</b><span></span></div>
      <div class="alloc-row"><span class="muted">SPY / QQQ</span><span class="num ${cls(U.spy5)}">${pct(U.spy5)}</span><span class="num ${cls(U.qqq5)}">${pct(U.qqq5)}</span></div>
      <div class="alloc-row"><span>Filtr rynku USA</span><span class="pill ${U.bear ? "bad" : "good"}">${U.bear ? "SPY pod SMA 12" : "SPY nad SMA 12"}</span><span class="num muted">${num(U.spy)} / ${num(U.spy_sma12)}</span></div>
      <div class="alloc-row"><span>Filtr rynku GPW</span><span class="pill ${G.bear ? "bad" : "good"}">${G.bear ? "koszyk pod SMA 12" : "koszyk nad SMA 12"}</span><span class="num muted">${num(G.lv, 3)} / ${num(G.lv12, 3)}</span></div>
      <div class="alloc-row"><span>Kandydaci</span><span class="num">USA ${U.rows.length}</span><span class="num">GPW ${G.rows.length}</span></div>
    </div>
    ${U.bear || G.bear ? `<div class="alert warn">Przy filtrze rynku nie kupujesz nowych spółek; trzymane pozycje zostają do wyjścia pod SMA 10.</div>` : ""}</section>`;
}
function allocCard(P, PL) {
  const tot = P.total || 1, tg = (PL && PL.targets) || S.settings.targets, ts = (tg.usa || 0) + (tg.gpw || 0) + (tg.etf || 0) || 1;
  const parts = ["usa", "gpw", "etf", "inne"].map((b) => [b, P.buckets[b] || 0]).concat([["cash", P.cash]]);
  const lab = { ...BUCKET, cash: "Gotówka" };
  return `<section class="card alloc"><div class="card-head"><h2>Udziały</h2><button class="ghost sm" data-go="set" type="button">Zmień cel</button></div>
    <div class="stackbar">${parts.map(([b, v]) => `<i style="width:${(v / tot) * 100}%;background:${BCOL[b]}" title="${lab[b]}"></i>`).join("")}</div>
    <div class="alloc-rows"><div class="alloc-row muted xs"><span></span><span class="num">teraz</span><span class="num">cel</span></div>
    ${parts.filter(([b, v]) => v > 0 || ["usa", "gpw", "etf"].includes(b)).map(([b, v]) => `<div class="alloc-row"><span class="tag" style="--c:${BCOL[b]}">${lab[b]}</span>
      <span class="num">${pct(v / tot, 1, false)}</span><span class="num muted">${tg[b] != null ? pct((tg[b] || 0) / ts, 0, false) : ""}</span></div>`).join("")}</div></section>`;
}

// ------------------------------------------------------------------ Portfel
function viewPortfolio() {
  const P = S.portfolio;
  let h = `<header class="page-head"><div><h1>Portfel</h1><p>${P ? `Konto ${esc(P.label)} · raport ${esc((P.generated || "").slice(0, 16).replace("T", " "))} UTC` : "Pozycje z raportu XTB"}</p></div>
    ${P && P.accounts.length > 1 ? `<label class="field"><span>Konto</span><select id="account">${P.accounts.map((a) => `<option ${a === P.label ? "selected" : ""}>${esc(a)}</option>`).join("")}</select></label>` : ""}</header>`;
  if (!P) return h + `<div class="card"><div class="empty"><b>Brak raportu XTB</b>W xStation: Historia konta → Eksport (zip). <button class="btn" data-act="xtb" type="button">Wybierz plik raportu…</button></div></div>`;
  h += `<section class="card"><div class="tbl-wrap"><table><thead><tr><th>Spółka</th><th>Koszyk</th><th class="r">Wartość</th><th class="r">Udział</th><th class="r">Wynik</th>
      <th class="r">Cena zakupu</th><th class="r">Cena teraz</th><th class="r">Od SMA 10</th><th class="r">Do stopu −40 %</th><th>Status</th></tr></thead><tbody>`;
  const max = Math.max(...P.rows.map((r) => r.share), 0.01);
  for (const r of P.rows) {
    const sell = r.status.startsWith("SPRZEDAJ"), dim = r.bucket === "etf" || r.bucket === "inne";
    const st = sell ? "bad" : r.status.startsWith("kandydat") ? "good" : r.status.startsWith("trzymaj") ? "info" : "";
    h += `<tr class="${sell ? "sell" : dim ? "dim" : ""}" data-sym="${esc(r.yahoo)}" data-title="${esc(r.name)}" data-entry="${r.open_price || ""}">
      <td><span class="t">${esc(r.t)}</span> <span class="n">${esc(r.name)}</span></td>
      <td><span class="tag" style="--c:${BCOL[r.bucket]}">${BUCKET[r.bucket]}</span></td>
      <td class="r">${zl(r.value)}</td>
      <td class="r">${pct(r.share, 1, false)}<span class="minibar" style="--c:${BCOL[r.bucket]}"><i style="width:${(r.share / max) * 100}%"></i></span></td>
      <td class="r ${cls(r.profit_pct)}">${pct(r.profit_pct == null ? null : r.profit_pct / 100)}</td>
      <td class="r">${num(r.open_price)}</td><td class="r">${num(r.price)}</td>
      <td class="r ${cls(r.dist)}">${r.dist == null ? "—" : pct(r.dist)}</td>
      <td class="r ${r.stop_dist != null && r.stop_dist < 0.15 ? "neg" : ""}">${r.stop_dist == null ? "—" : pct(r.stop_dist)}</td>
      <td><span class="pill ${st}">${esc(r.status)}</span></td></tr>`;
  }
  h += `</tbody></table></div><p class="note">Kliknij spółkę, żeby zobaczyć wykres miesięczny z ceną zakupu i stopem. „Do stopu” = ile cena może jeszcze spaść do −40 % od średniej ceny zakupu.</p></section>`;
  return h;
}

// ------------------------------------------------------------------ Listy USA / GPW
function viewList(m) {
  const L = S.lists;
  const name = m === "usa" ? "Lista USA" : "Lista GPW";
  if (!L) return `<header class="page-head"><div><h1>${name}</h1></div></header><div class="card"><div class="empty"><b>Brak listy</b><button class="btn primary" data-act="fetch" type="button">Pobierz listę</button></div></div>`;
  const X = L[m], n = X.n;
  const held = new Set((S.portfolio ? S.portfolio.rows.filter((r) => r.bucket === m).map((r) => r.t) : []).concat(S.manual.filter((x) => x.market === m.toUpperCase()).map((x) => x.t)));
  const sub = m === "usa"
    ? `Lider ${X.lead === "NDX" ? "Nasdaq-100" : "S&P 500"} · zwrot 6 mies. &gt; +30 % i zamknięcie nad SMA 10 · ranking po 6 mies. · ${n} pozycji`
    : `WIG20 + mWIG40 razem · C-8: 3 mies. &gt; 0, 12 mies. &gt; +30 %, nad SMA 10 · ranking po 6 mies. · ${n} pozycji · skład z rewizji ${esc(X.rewizja || "—")}`;
  const q = ui.q[m].trim().toUpperCase();
  let rows = X.rows.map((r, i) => ({ ...r, rank: i + 1 }));
  if (q) rows = rows.filter((r) => r.t.includes(q) || (r.n || "").toUpperCase().includes(q));
  const shown = ui.all[m] || q ? rows : rows.slice(0, Math.max(n + 10, 20));
  let h = `<header class="page-head"><div><h1>${name}</h1><p>${sub}</p></div>
    <span class="chip ${X.bear ? "bad" : "good"}"><i></i>${X.bear ? "Filtr rynku: brak zakupów" : "Filtr rynku: zakupy dozwolone"}</span></header>
    <section class="card"><div class="card-head"><div class="tools"><input type="text" id="q_${m}" placeholder="Szukaj spółki…" value="${esc(ui.q[m])}" aria-label="Szukaj">
      <span class="muted xs">${X.rows.length} kandydatów z ${X.count} spółek${m === "usa" && X.prefilter ? ` · sito Finviz: S&P 500 ${X.prefilter.sp}, Nasdaq-100 ${X.prefilter.nq}` : ""}</span></div>
      <span class="legend-inline"><span><i style="background:var(--good)"></i>do kupienia (pierwsze ${n})</span>${held.size ? `<span><span class="pill info">masz</span></span>` : ""}</span></div>
    <div class="tbl-wrap"><table><thead><tr><th class="r">#</th><th>Spółka</th><th class="r">6 mies.</th>${m === "gpw" ? `<th class="r">3 mies.</th><th class="r">12 mies.</th>` : ""}
      <th class="r">Zamknięcie</th><th class="r">SMA 10</th><th class="r">Nad SMA 10</th><th>Indeks</th><th></th></tr></thead><tbody>`;
  let cut = false;
  for (const r of shown) {
    if (!q && !cut && r.rank > n) { cut = true; h += `<tr class="cutline"><td colspan="10">Poniżej: kandydaci rezerwowi (gdy któraś z pierwszych ${n} jest już w portfelu albo dla dopłat)</td></tr>`; }
    const buy = r.rank <= n && !X.bear;
    const idx = [["S&P 500", r.sp], ["NDX", r.nq], ["WIG20", r.w20], ["mWIG40", r.w40]].filter((x) => x[1]).map((x) => x[0]).join(", ");
    h += `<tr class="${buy ? "buy" : ""}" data-sym="${esc(m === "gpw" ? r.t + ".WA" : r.t)}" data-title="${esc(r.n)}">
      <td class="r muted">${r.rank}</td><td><span class="t">${esc(r.t)}</span> <span class="n">${esc(r.n)}</span></td>
      <td class="r ${cls(r.r6)}"><b>${pct(r.r6)}</b></td>${m === "gpw" ? `<td class="r ${cls(r.r3)}">${pct(r.r3)}</td><td class="r ${cls(r.r12)}">${pct(r.r12)}</td>` : ""}
      <td class="r">${num(r.c)}</td><td class="r muted">${num(r.sma)}</td><td class="r ${cls(r.dist)}">${pct(r.dist)}</td><td class="muted">${idx}</td>
      <td>${held.has(r.t) ? `<span class="pill info">masz</span>` : buy ? `<span class="pill good">kup</span>` : ""}</td></tr>`;
  }
  if (!shown.length) h += `<tr><td colspan="10" class="muted">Brak spółek${q ? " dla „" + esc(ui.q[m]) + "”" : ""}.</td></tr>`;
  h += `</tbody></table></div>${!q && !ui.all[m] && rows.length > shown.length ? `<button class="btn sm" data-act="all" data-m="${m}" type="button">Pokaż wszystkich (${rows.length})</button>` : ""}
    ${X.missing && X.missing.length ? `<p class="note">Bez notowań w Yahoo: ${X.missing.slice(0, 30).map(esc).join(", ")}${X.missing.length > 30 ? "…" : ""}</p>` : ""}</section>`;
  return h;
}

// ------------------------------------------------------------------ Historia konta
function viewHistory() {
  const H = S.history;
  let h = `<header class="page-head"><div><h1>Historia konta</h1><p>Wartość konta i wpłaty netto z raportu XTB</p></div>
    ${H ? `<button class="btn" id="curveBtn" data-act="curve" type="button" ${S.task.busy ? "disabled" : ""}>${H.exact ? "Przelicz ponownie" : "Wyceń cenami dziennymi"}</button>` : ""}</header>`;
  if (!H) return h + `<div class="card"><div class="empty"><b>Brak raportu XTB</b><button class="btn" data-act="xtb" type="button">Wybierz plik raportu…</button></div></div>`;
  const p = H.points;
  h += `<section class="card curve"><div class="card-head"><div class="legend-inline"><span><i style="background:var(--accent)"></i>wartość konta</span><span><i style="background:var(--muted)"></i>wpłacono netto</span>
      <span><i style="background:var(--good);height:8px;width:8px;border-radius:50%"></i>sprzedaż z zyskiem</span><span><i style="background:var(--bad);height:8px;width:8px;border-radius:50%"></i>ze stratą</span></div>
      ${H.exact ? `<span class="pill good">ceny dzienne Yahoo</span>` : `<span class="pill warn">przybliżenie bez cen rynkowych</span>`}</div>
    ${p.length > 1 ? curveSvg(p, H.events) : `<div class="empty">Za mało danych do wykresu.</div>`}</section>`;
  h += `<section class="card"><div class="card-head"><h2>Zdarzenia</h2><span class="muted xs">${H.events.length}</span></div><div class="tbl-wrap"><table><thead><tr><th>Data</th><th>Zdarzenie</th><th>Spółka</th><th class="r">Kwota / wynik</th><th class="r">Wynik %</th></tr></thead><tbody>
    ${(ui.allEv ? H.events : H.events.slice(0, 40)).map((e) => `<tr><td class="num">${esc(e.d)}</td><td><span class="pill ${e.kind === "wpłata" ? "info" : e.kind === "wypłata" ? "warn" : e.amount >= 0 ? "good" : "bad"}">${e.kind}</span></td>
      <td>${esc(e.t)}</td><td class="r ${e.kind === "sprzedaż" ? cls(e.amount) : ""}">${zl(e.amount)}</td><td class="r ${cls(e.pct)}">${e.pct == null ? "" : pct(e.pct)}</td></tr>`).join("")}
    </tbody></table></div>${!ui.allEv && H.events.length > 40 ? `<button class="btn sm" data-act="allev" type="button">Pokaż wszystkie (${H.events.length})</button>` : ""}</section>`;
  return h;
}
function curveSvg(p, events) {
  const W = 1000, Hh = 340, x0 = 64, x1 = W - 16, y0 = 16, y1 = Hh - 30;
  let lo = Math.min(...p.map((q) => Math.min(q[1], q[2]))), hi = Math.max(...p.map((q) => Math.max(q[1], q[2])));
  const pad = (hi - lo) * 0.08 || 1; lo = Math.max(lo - pad, 0); hi += pad;
  const X = (i) => x0 + ((x1 - x0) * i) / (p.length - 1), Y = (v) => y1 - ((v - lo) / (hi - lo)) * (y1 - y0);
  let s = `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Wartość konta w czasie">`;
  for (let k = 0; k <= 4; k++) { const v = lo + ((hi - lo) * k) / 4; s += `<line x1="${x0}" x2="${x1}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/><text x="${x0 - 8}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${zl(v).replace(nbsp + "zł", "")}</text>`; }
  const step = Math.max(Math.floor(p.length / 6), 1);
  for (let i = 0; i < p.length; i += step) s += `<text x="${X(i)}" y="${Hh - 8}" text-anchor="middle" font-size="11" fill="var(--muted)">${esc(p[i][0].slice(0, 7))}</text>`;
  const line = (k) => p.map((q, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(q[k]).toFixed(1)}`).join("");
  s += `<path d="${line(1)}L${X(p.length - 1)},${y1}L${x0},${y1}Z" fill="var(--accent)" opacity=".08"/>`;
  s += `<path d="${line(2)}" fill="none" stroke="var(--muted)" stroke-width="1.6" stroke-dasharray="5 4"/>`;
  s += `<path d="${line(1)}" fill="none" stroke="var(--accent)" stroke-width="2.2"/>`;
  const days = p.map((q) => q[0]);
  const at = (d) => { let a = 0, b = days.length - 1; while (a < b) { const m = (a + b) >> 1; if (days[m] < d) a = m + 1; else b = m; } return a; };
  for (const e of events.filter((e) => e.kind === "sprzedaż")) {
    const i = at(e.d);
    s += `<circle cx="${X(i)}" cy="${Y(p[i][1])}" r="4" fill="${e.amount >= 0 ? "var(--good)" : "var(--bad)"}" stroke="var(--surface)" stroke-width="1.5"><title>${esc(e.d)} ${esc(e.t)} ${zl(e.amount)}</title></circle>`;
  }
  const last = p[p.length - 1];
  s += `<text x="${x1}" y="${Y(last[1]) - 8}" text-anchor="end" font-size="12" font-weight="650" fill="var(--accent)">${zl(last[1])}</text></svg>`;
  return s;
}

// ------------------------------------------------------------------ Ustawienia
function viewSettings() {
  const st = S.settings, tg = st.targets || {}, g = S.gpw;
  const sum = (tg.usa || 0) + (tg.gpw || 0) + (tg.etf || 0);
  return `<header class="page-head"><div><h1>Ustawienia</h1><p>Zapisują się same. Dane programu: <span class="num">${esc(S.data_dir)}</span></p></div></header>
  <div class="set-grid">
    <section class="card"><div class="card-head"><div><h2>Udziały docelowe</h2><p>Jak dzielić wpłaty między koszyki (w procentach).</p></div></div>
      <div class="grid3">${["usa", "gpw", "etf"].map((b) => `<label class="field"><span><span class="tag" style="--c:${BCOL[b]}">${BUCKET[b]}</span></span><input type="number" min="0" max="100" step="5" id="tg_${b}" value="${tg[b] ?? ""}"></label>`).join("")}</div>
      <p class="xs ${Math.abs(sum - 100) < 0.01 ? "sum-ok" : "sum-bad"}">Razem ${num(sum, 0)} %${Math.abs(sum - 100) < 0.01 ? "" : " — program przeliczy proporcjonalnie do 100 %"}</p>
      <label class="field"><span>ETF (ticker XTB)</span><input type="text" id="etf" value="${esc(st.etf)}"></label></section>
    <section class="card"><div class="card-head"><div><h2>Raport XTB</h2><p>xStation → Historia konta → Eksport (zip z plikami xlsx dla każdego konta).</p></div></div>
      <div class="row"><button class="btn" data-act="xtb" type="button">Wczytaj nowy raport…</button>
      ${S.portfolio && S.portfolio.accounts.length > 1 ? `<label class="field"><span>Konto</span><select id="account">${S.portfolio.accounts.map((a) => `<option ${a === S.portfolio.label ? "selected" : ""}>${esc(a)}</option>`).join("")}</select></label>` : ""}</div>
      <p class="note">${S.portfolio ? `Wczytane konto ${esc(S.portfolio.label)}, raport z ${esc((S.portfolio.generated || "").slice(0, 10))}.` : "Brak raportu."}</p></section>
    <section class="card"><div class="card-head"><div><h2>Trzymane spółki (bez raportu XTB)</h2><p>Tickery oddzielone spacją albo przecinkiem; GPW z końcówką .WA, np. ALE.WA. Po wczytaniu raportu uzupełnia się samo.</p></div></div>
      <textarea id="hold" rows="3" placeholder="np. NVDA, PLTR, ALE.WA">${esc(st.hold)}</textarea>
      ${S.manual.length && S.lists ? manualList() : ""}</section>
    <section class="card"><div class="card-head"><div><h2>Skład GPW</h2><p>Popraw po każdej rewizji (marzec, czerwiec, wrzesień, grudzień): jeden ticker na wiersz, po spacji nazwa.</p></div>
      ${g.custom ? `<span class="pill info">własny</span>` : `<span class="pill">domyślny</span>`}</div>
      <label class="field"><span>Data rewizji</span><input type="text" id="g_rew" value="${esc(g.rewizja || "")}"></label>
      <div class="grid3" style="grid-template-columns:1fr 1fr">
        <label class="field"><span>WIG20 (${Object.keys(g.WIG20).length})</span><textarea id="g_w20" rows="10">${esc(Object.entries(g.WIG20).map(([k, v]) => `${k} ${v}`).join("\n"))}</textarea></label>
        <label class="field"><span>mWIG40 (${Object.keys(g.mWIG40).length})</span><textarea id="g_w40" rows="10">${esc(Object.entries(g.mWIG40).map(([k, v]) => `${k} ${v}`).join("\n"))}</textarea></label></div>
      <div class="row"><button class="btn primary" data-act="gpw" type="button">Zapisz skład</button><button class="btn" data-act="gpwreset" type="button">Przywróć domyślny</button></div></section>
    <section class="card"><div class="card-head"><div><h2>Zasady</h2></div></div>
      <p class="note"><b>USA:</b> lider SPY albo QQQ z wyższym zwrotem 5 mies.; kandydaci z indeksu lidera: 6 mies. &gt; +30 %, zamknięcie nad SMA 10, ranking po 6 mies., 10 pozycji; brak zakupów, gdy SPY zamyka miesiąc pod SMA 12.<br>
      <b>GPW:</b> WIG20 + mWIG40 razem, C-8 (3 mies. &gt; 0, 12 mies. &gt; +30 %, nad SMA 10), ranking po 6 mies., 5 pozycji; brak zakupów, gdy koszyk składników jest pod SMA 12.<br>
      <b>Wyjście:</b> zamknięcie miesiąca pod SMA 10 (w USA także wypadnięcie z indeksów), stop awaryjny −40 % od ceny zakupu.<br>
      <b>Wpłaty:</b> najpierw nowe spółki na wolne miejsca (waga = koszyk / liczba miejsc), potem dopełnienie trzymanych kandydatów do wagi, min. ${zl(S.rules.min_topup)}.</p></section>
  </div>`;
}
const parseLines = (t) => Object.fromEntries(t.split(/\n/).map((l) => l.trim().split(/\s+(.*)/s)).filter((p) => p[0]).map((p) => [p[0].toUpperCase().replace(/\.WA$/, ""), (p[1] || p[0]).trim()]));

// ------------------------------------------------------------------ zdarzenia widoku
let saveTimer = null;
function saveSoon(body, delay = 450) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => { try { setState(await post("settings", body)); } catch (e) { toast(e.message, true); } }, delay);
}
function bindView() {
  const v = $("#view");
  const dep = $("#deposit");
  if (dep) dep.addEventListener("input", () => saveSoon({ deposit: dep.value }, 600));
  for (const b of ["usa", "gpw", "etf"]) { const el = $("#tg_" + b); if (el) el.addEventListener("input", () => saveSoon({ targets: { usa: $("#tg_usa").value, gpw: $("#tg_gpw").value, etf: $("#tg_etf").value } }, 700)); }
  const etf = $("#etf"); if (etf) etf.addEventListener("change", () => saveSoon({ etf: etf.value }, 0));
  const hold = $("#hold"); if (hold) hold.addEventListener("input", () => saveSoon({ hold: hold.value }, 700));
  for (const acc of v.querySelectorAll("#account")) acc.addEventListener("change", () => saveSoon({ account: acc.value }, 0));
  for (const m of ["usa", "gpw"]) { const q = $("#q_" + m); if (q) q.addEventListener("input", () => { ui.q[m] = q.value; renderView(); }); }
}
document.addEventListener("click", async (e) => {
  const go_ = e.target.closest("[data-go]");
  if (go_) return go(go_.dataset.go);
  if (e.target.closest("[data-close]")) return closeChart();
  const a = e.target.closest("[data-act]");
  if (a) {
    const act = a.dataset.act;
    if (act === "fetch") return startFetch();
    if (act === "xtb") return $("#xtbFile").click();
    if (act === "all") { ui.all[a.dataset.m] = true; return renderView(); }
    if (act === "allev") { ui.allEv = true; return renderView(); }
    if (act === "curve") { try { await post("curve"); S.task.busy = true; setState(S); } catch (err) { toast(err.message, true); } return; }
    if (act === "copy") return copyPlan();
    if (act === "gpw") { try { setState(await post("gpw", { rewizja: $("#g_rew").value, WIG20: parseLines($("#g_w20").value), mWIG40: parseLines($("#g_w40").value) })); toast("Zapisano skład GPW — pobierz listę, żeby przeliczyć"); } catch (err) { toast(err.message, true); } return; }
    if (act === "gpwreset") { try { setState(await post("gpw", { reset: true })); toast("Przywrócono domyślny skład GPW"); } catch (err) { toast(err.message, true); } return; }
  }
  const row = e.target.closest("[data-sym]");
  if (row && $("#view").contains(row)) openChart(row.dataset.sym, row.dataset.title, parseFloat(row.dataset.entry) || null);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#drawer").hidden) closeChart();
  if (e.key === "Enter" && e.target.matches && e.target.matches(".act[data-sym]")) e.target.click();
});
$("#fetchBtn").addEventListener("click", startFetch);
async function startFetch() {
  try { const r = await post("fetch"); if (r.started) { S.task = { busy: true, log: "Start…", progress: 0 }; setState(S); } } catch (e) { toast(e.message, true); }
}
$("#xtbFile").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  try {
    const s = await api("xtb", { method: "POST", body: await f.arrayBuffer(), headers: { "X-Name": encodeURIComponent(f.name) } });
    setState(s); toast(s.message || "Wczytano raport");
    if (view === "set" || view === "hist") return;
    go(S.lists ? "home" : "pf");
  } catch (err) { toast("Nie udało się wczytać raportu: " + err.message, true); }
});
$("#themeBtn").addEventListener("click", async () => {
  const order = ["auto", "light", "dark"], th = order[(order.indexOf(S.settings.theme || "auto") + 1) % 3];
  try { setState(await post("settings", { theme: th })); } catch (e) { toast(e.message, true); }
});
async function copyPlan() {
  const PL = S.plan;
  const txt = [`CEM10 — plan na ${monthName(nextMonth(S.lists.month))}`, ...PL.actions.map((a) => `${a.akcja} ${a.ticker} (${BUCKET[a.koszyk]}): ${zl(a.kwota)}${a.shares ? ` ≈ ${num(a.shares, 3)} akcji` : ""}${a.uwagi ? " — " + a.uwagi : ""}`)].join("\n").replace(/ /g, " ");
  try { await navigator.clipboard.writeText(txt); toast("Skopiowano plan"); } catch (e) { toast("Nie udało się skopiować", true); }
}

// ------------------------------------------------------------------ wykres miesięczny
const charts = {};
let chartReq = 0;
async function openChart(sym, title, entry) {
  const d = $("#drawer");
  d.hidden = false;
  $("#chTitle").textContent = `${sym}${title && title !== sym ? " · " + title : ""}`;
  $("#chSub").textContent = "Pobieram świece miesięczne…";
  $("#chBody").innerHTML = `<div class="spinner" aria-label="Ładowanie"></div>`;
  $(".drawer-panel [data-close]").focus();
  const id = ++chartReq;
  try {
    const D = charts[sym] || (charts[sym] = await api("chart?sym=" + encodeURIComponent(sym)));
    if (id !== chartReq) return;
    drawChart(D, entry);
  } catch (e) { delete charts[sym]; if (id === chartReq) { $("#chSub").textContent = ""; $("#chBody").innerHTML = `<div class="alert">${esc(e.message)}</div>`; } }
}
function closeChart() { $("#drawer").hidden = true; chartReq++; }
function drawChart(D, entry) {
  const n = D.c.length, k0 = Math.max(n - 60, 0), idx = [];
  for (let i = k0; i < n; i++) idx.push(i);
  const sma = D.c.map((_, i) => (i < 9 ? null : D.c.slice(i - 9, i + 1).reduce((a, b) => a + b, 0) / 10));
  const vsma = D.v.map((_, i) => (i < 9 ? null : D.v.slice(i - 9, i + 1).reduce((a, b) => a + b, 0) / 10));
  const stop = entry ? entry * (1 - S.rules.stop) : null;
  const W = 1000, H = 600, x0 = 30, x1 = W - 92, py0 = 12, py1 = 430, vy0 = 452, vy1 = H - 26;
  const vals = idx.flatMap((i) => [D.h[i], D.l[i]]).concat(idx.map((i) => sma[i]), [entry, stop]).filter((v) => v > 0);
  const lmin = Math.log(Math.min(...vals) * 0.95), lmax = Math.log(Math.max(...vals) * 1.05);
  const step = (x1 - x0) / idx.length, X = (j) => x0 + (j + 0.5) * step, Y = (p) => py1 - ((Math.log(p) - lmin) / (lmax - lmin)) * (py1 - py0);
  let s = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Wykres miesięczny">`;
  for (let k = 0; k <= 5; k++) { const p = Math.exp(lmin + ((lmax - lmin) * k) / 5); s += `<line x1="${x0}" x2="${x1}" y1="${Y(p)}" y2="${Y(p)}" stroke="var(--grid)"/><text x="${x1 + 8}" y="${Y(p) + 4}" font-size="11" fill="var(--muted)">${num(p)}</text>`; }
  idx.forEach((i, j) => {
    const x = X(j), live = i === n - 1, col = live ? "var(--muted)" : "var(--bar)", w = Math.max(step * 0.32, 1.5);
    s += `<g stroke="${col}" stroke-width="${Math.max(Math.min(step * 0.18, 2.4), 1.2)}" opacity="${live ? 0.6 : 1}"><line x1="${x}" x2="${x}" y1="${Y(D.h[i])}" y2="${Y(D.l[i])}"/><line x1="${x - w}" x2="${x}" y1="${Y(D.o[i] || D.c[i])}" y2="${Y(D.o[i] || D.c[i])}"/><line x1="${x}" x2="${x + w}" y1="${Y(D.c[i])}" y2="${Y(D.c[i])}"/></g>`;
    if (j % 12 === 0 || j === idx.length - 1) s += `<text x="${x}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--muted)">${esc(D.d[i])}</text>`;
  });
  const sp = idx.map((i, j) => (sma[i] ? `${X(j).toFixed(1)},${Y(sma[i]).toFixed(1)}` : null)).filter(Boolean);
  if (sp.length > 1) s += `<polyline points="${sp.join(" ")}" fill="none" stroke="var(--sma)" stroke-width="2.2"/>`;
  for (const [lvl, col, lab] of [[entry, "var(--warn)", "zakup"], [stop, "var(--bad)", "stop −40 %"]]) {
    if (lvl) s += `<line x1="${x0}" x2="${x1}" y1="${Y(lvl)}" y2="${Y(lvl)}" stroke="${col}" stroke-dasharray="6 4" stroke-width="1.5"/><text x="${x1 + 8}" y="${Y(lvl) + 4}" font-size="11" font-weight="650" fill="${col}">${lab}</text>`;
  }
  const vmax = Math.max(...idx.map((i) => D.v[i]), 1);
  idx.forEach((i, j) => {
    const up = D.c[i] >= (i > 0 ? D.c[i - 1] : D.o[i]), hh = (D.v[i] / vmax) * (vy1 - vy0);
    s += `<rect x="${X(j) - step * 0.34}" y="${vy1 - hh}" width="${step * 0.68}" height="${hh}" fill="${up ? "var(--vol-up)" : "var(--vol-dn)"}" opacity="${i === n - 1 ? 0.45 : 0.85}"/>`;
  });
  const vp = idx.map((i, j) => (vsma[i] ? `${X(j).toFixed(1)},${(vy1 - (vsma[i] / vmax) * (vy1 - vy0)).toFixed(1)}` : null)).filter(Boolean);
  if (vp.length > 1) s += `<polyline points="${vp.join(" ")}" fill="none" stroke="var(--warn)" stroke-width="1.6"/>`;
  s += `<line x1="${x0}" x2="${x1}" y1="${vy1}" y2="${vy1}" stroke="var(--line)"/></svg>`;
  $("#chBody").innerHTML = s;
  const lc = n - 2, c = D.c[lc], m = sma[lc];
  $("#chSub").innerHTML = `Zamknięcie ${esc(D.d[lc])}: <b>${num(c)}</b> · SMA 10 ${num(m)} · ` +
    (m == null ? "" : c >= m ? `<span class="pill good">nad SMA 10 — trzymaj</span>` : `<span class="pill bad">pod SMA 10 — sprzedaj</span>`) +
    (entry ? ` · zakup ${num(entry)} · stop ${num(stop)}` : "");
}
$("#drawer").addEventListener("keydown", (e) => {  // fokus zostaje w szufladzie
  if (e.key !== "Tab") return;
  const f = [...$("#drawer").querySelectorAll("button")];
  if (f.length) { e.preventDefault(); f[0].focus(); }
});

// ------------------------------------------------------------------ start
load();
setInterval(() => post("ping").catch(() => {}), 30000);
post("ping").catch(() => {});
