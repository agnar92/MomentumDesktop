// CEM10 — interfejs: stan z /api/state (serwer lokalny programu), widoki: Ten miesiąc, Portfel (raport XTB albo konto ręczne), Lista USA / GPW, Historia konta, Ustawienia.
// Wykres miesięczny: panel po prawej na szerokim ekranie (przełącza się po kliknięciu spółki albo strzałkami), na wąskim — szuflada.
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
const MSHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];
const monthName = (ym) => { if (!ym) return "—"; const [y, m] = ym.split("-").map(Number); return `${MONTHS[m - 1]} ${y}`; };
const nextMonth = (ym) => { const [y, m] = ym.split("-").map(Number); return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`; };
const numOf = (s) => { const v = parseFloat(String(s ?? "").replace(/\s/g, "").replace(",", ".")); return isFinite(v) ? v : 0; };

let S = null;                       // ostatni stan z serwera
let view = "home";
const ui = { q: { usa: "", gpw: "" }, all: { usa: false, gpw: false }, sel: null, paneOpen: true, range: 60, log: true, histRange: "all", histSales: false, manualEdit: false, draft: null };
try {
  view = localStorage.getItem("cem10_view") || "home";
  Object.assign(ui, JSON.parse(localStorage.getItem("cem10_ui") || "{}"));
} catch (e) { /* bez localStorage */ }
const saveUi = () => { try { localStorage.setItem("cem10_ui", JSON.stringify({ paneOpen: ui.paneOpen, range: ui.range, log: ui.log, histRange: ui.histRange })); } catch (e) { /* bez localStorage */ } };

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
function setTop() { document.documentElement.style.setProperty("--top", ($(".topbar").offsetHeight || 64) + "px"); }
function renderProgress() {
  const t = S.task;
  $("#progress").hidden = !t.busy;
  $("#fetchBtn").disabled = t.busy;
  $("#progressBar").style.width = Math.round((t.progress || 0) * 100) + "%";
  $("#progressTxt").textContent = t.log || "";
  for (const id of ["#curveBtn", "#mPricesBtn"]) { const b = $(id); if (b) b.disabled = t.busy; }
  setTop();
}

// ------------------------------------------------------------------ nawigacja
const PANE_VIEWS = ["home", "pf", "usa", "gpw"];
const wideMQ = window.matchMedia("(min-width: 1320px)");
const paneOn = () => wideMQ.matches && PANE_VIEWS.includes(view) && ui.paneOpen;
wideMQ.addEventListener("change", () => { if (S) renderView(); });
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
  syncPane();
  if (view === "hist") drawCurve();
  else if (curveRO) { curveRO.disconnect(); curveRO = null; }
}

// ------------------------------------------------------------------ Ten miesiąc
function viewHome() {
  const L = S.lists, P = S.portfolio, PL = S.plan;
  const title = L ? `Plan na ${monthName(nextMonth(L.month))}` : "Ten miesiąc";
  const sub = L ? `Z zamknięcia miesiąca: ${monthName(L.month)} · pobrano ${esc(L.generated_at || "")}` : "Lista liczy się z zamkniętych świec miesięcznych.";
  let h = `<header class="page-head"><div><h1>${title}</h1><p>${sub}</p></div></header>`;
  if (!L || !P) {
    h += `<section class="card"><div class="card-head"><h2>Zacznij w dwóch krokach</h2></div><div class="steps">
      <div class="step ${P ? "done" : ""}"><span class="n">${P ? "✓" : "1"}</span><div><b>Dodaj konto</b><p class="muted">Wczytaj raport z XTB (xStation → Historia konta → Eksport) albo wpisz gotówkę i pozycje ręcznie. Program nie łączy się z XTB.</p>
        ${P ? `<span class="pill good">Konto ${esc(P.label)}</span>` : `<div class="row"><button class="btn" data-act="xtb" type="button">Wczytaj raport XTB…</button><button class="btn" data-act="mopen" type="button">Wpisz ręcznie</button></div>`}</div></div>
      <div class="step ${L ? "done" : ""}"><span class="n">${L ? "✓" : "2"}</span><div><b>Pobierz listę CEM10</b><p class="muted">Sito Finviz (S&P 500 i Nasdaq-100) i ceny miesięczne z Yahoo Finance. Około minuty.</p>
        ${L ? `<span class="pill good">Lista za ${esc(monthName(L.month))}</span>` : `<button class="btn primary" data-act="fetch" type="button">Pobierz listę</button>`}</div></div>
    </div></section>`;
  }
  if (P) {
    h += `<div class="kpis">
      <div class="card kpi"><span class="s">Wartość konta</span><span class="v">${zl(P.total)}</span><span class="s">pozycje ${zl(P.positions_value)} · gotówka ${zl(P.cash)}</span></div>
      <div class="card kpi"><span class="s">Wynik</span><span class="v ${cls(P.profit)}">${P.deposited ? zl(P.profit) : "—"}</span><span class="s ${cls(P.profit)}">${P.deposited ? pct(P.profit_pct) + " od wpłat" : "podaj „wpłacono netto”"}</span></div>
      <div class="card kpi"><span class="s">Wpłacono netto</span><span class="v">${zl(P.deposited)}</span><span class="s">${P.manual ? "konto ręczne" : "konto " + esc(P.label) + " · raport " + esc((P.generated || "").slice(0, 10))}</span></div>
      <div class="card kpi"><span class="s">Pozycje CEM10</span><span class="v">${P.rows.filter((r) => r.bucket === "usa").length} / ${S.rules.slots.usa} · ${P.rows.filter((r) => r.bucket === "gpw").length} / ${S.rules.slots.gpw}</span><span class="s">USA · GPW (zajęte / miejsca)</span></div>
    </div>`;
  }
  const warn = P ? P.rows.filter((r) => r.status.startsWith("SPRZEDAJ")) : S.manual.filter((m) => m.decision !== "trzymaj");
  h += `<div class="cols"><div class="stack">`;
  if (warn.length) h += `<div class="alert">⚠ Do sprzedaży: ${warn.map((r) => esc(r.t)).join(", ")} — zamknięcie miesiąca pod SMA 10 albo stop −40 %.</div>`;
  h += `<section class="card"><div class="card-head"><div><h2>Co zrobić</h2><p>Kupujesz i sprzedajesz po zamknięciu miesiąca, w pierwszych dniach nowego.</p></div>
        ${PL && PL.actions.length ? `<button class="btn sm" data-act="copy" type="button">Kopiuj plan</button>` : ""}</div>`;
  if (P && L) {
    h += `<div class="row"><label class="field" style="flex:1;min-width:200px"><span>Wpłata w tym miesiącu</span><span class="money"><input type="text" inputmode="decimal" id="deposit" value="${esc(num(S.settings.deposit, 0))}"><b>zł</b></span></label></div>`;
    h += planList(PL);
  } else if (L && S.manual.length) {
    h += manualList();
  } else {
    h += `<div class="empty">Plan pojawi się po dodaniu konta (raport XTB albo ręcznie) i pobraniu listy.</div>`;
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
      <div class="amt"><b>${zl(a.kwota)}</b><small>${a.akcja === "SPRZEDAJ" ? "całą pozycję" : a.shares ? "≈ " + num(a.shares, a.shares < 10 ? 3 : 1) + " akcji po " + num(a.price) + " " + a.ccy : ""}</small>${a.akcja === "KUP" && a.price && a.koszyk !== "etf" ? `<small class="stopv">stop −40 % ≈ ${num(a.price * (1 - S.rules.stop))} ${a.ccy}</small>` : ""}</div></div>`).join("") + `</div>`;
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
  const tot = P.total || 1, st = S.settings, tg = (PL && PL.targets) || st.targets, ts = (tg.usa || 0) + (tg.gpw || 0) + (tg.etf || 0) || 1;
  const parts = ["usa", "gpw", "etf", "inne"].map((b) => [b, P.buckets[b] || 0]).concat([["cash", P.cash]]);
  const lab = { ...BUCKET, cash: "Gotówka" }, need = PL ? PL.summary.need : null;
  return `<section class="card alloc"><div class="card-head"><h2>Udziały</h2><button class="ghost sm" data-go="set" type="button">Więcej w ustawieniach</button></div>
    <label class="field"><span>Baza: ETF S&amp;P 500 (${esc(st.etf)}) — udział w całym kapitale</span><span class="money sm"><input type="text" inputmode="decimal" id="etfpct" value="${esc(num(st.etf_pct, st.etf_pct % 1 ? 1 : 0))}" aria-label="Udział ETF w procentach"><b>%</b></span></label>
    <p class="xs muted">Reszta idzie w CEM10: USA ${num(tg.usa / ts * 100, 0)} % · GPW ${num(tg.gpw / ts * 100, 0)} %. Wpłaty dzielą się według tych udziałów.</p>
    <div class="stackbar">${parts.map(([b, v]) => `<i style="width:${(v / tot) * 100}%;background:${BCOL[b]}" title="${lab[b]}"></i>`).join("")}</div>
    <div class="alloc-rows"><div class="alloc-row muted xs"><span></span><span class="num">teraz</span><span class="num">cel</span></div>
    ${parts.filter(([b, v]) => v > 0 || ["usa", "gpw", "etf"].includes(b)).map(([b, v]) => `<div class="alloc-row"><span class="tag" style="--c:${BCOL[b]}">${lab[b]}</span>
      <span class="num">${pct(v / tot, 1, false)}</span><span class="num muted">${tg[b] != null ? pct((tg[b] || 0) / ts, 0, false) : ""}</span></div>
      ${need && need[b] > 1 ? `<div class="alloc-row diff xs"><span>do uzupełnienia</span><span class="num"></span><span class="num">${zl(need[b])}</span></div>` : ""}`).join("")}</div></section>`;
}

// ------------------------------------------------------------------ Portfel (raport XTB albo konto ręczne)
const KIND_LAB = { usa: "Akcja USA", gpw: "Akcja GPW", etf: "ETF" };
function blankPos() { return { t: "", kind: "usa", shares: "", open_price: "", ccy: "", price_in: "" }; }
function newDraft() {
  const M = S.manual_acct, defc = { usa: "USD", gpw: "PLN", etf: "USD" };
  return { cash: M.has ? String(M.cash || "") : "", deposited: M.has ? String(M.deposited || "") : "",
    positions: M.positions.map((p) => ({ t: p.t, kind: p.kind, shares: String(p.shares), open_price: p.open_price ? String(p.open_price) : "", ccy: p.ccy === defc[p.kind] ? "" : p.ccy, price_in: p.fixed ? String(p.price) : "" })) };
}
function openManual() {
  ui.manualEdit = true; ui.draft = newDraft();
  if (!ui.draft.positions.length) ui.draft.positions.push(blankPos());
  go("pf");
}
function manualEditor() {
  const d = ui.draft, M = S.manual_acct, fx = M.fx || {};
  const defc = { usa: "USD", gpw: "PLN", etf: "USD" };
  const rows = d.positions.map((p, i) => `<tr data-i="${i}">
    <td><input type="text" class="mi" data-f="t" value="${esc(p.t)}" placeholder="${p.kind === "gpw" ? "ALE" : p.kind === "etf" ? "CSPX.UK" : "NVDA"}" aria-label="Ticker" autocomplete="off"></td>
    <td><select class="mi" data-f="kind" aria-label="Rynek">${Object.entries(KIND_LAB).map(([k, v]) => `<option value="${k}" ${p.kind === k ? "selected" : ""}>${v}</option>`).join("")}</select></td>
    <td><input type="text" inputmode="decimal" class="mi" data-f="shares" value="${esc(p.shares)}" placeholder="np. 2,5" aria-label="Liczba akcji"></td>
    <td><input type="text" inputmode="decimal" class="mi" data-f="open_price" value="${esc(p.open_price)}" placeholder="średnia cena" aria-label="Średnia cena zakupu"></td>
    <td><select class="mi" data-f="ccy" aria-label="Waluta"><option value="">auto (${defc[p.kind]})</option>${["PLN", "USD", "EUR", "GBP"].map((c) => `<option ${p.ccy === c ? "selected" : ""}>${c}</option>`).join("")}</select></td>
    <td><input type="text" inputmode="decimal" class="mi" data-f="price_in" value="${esc(p.price_in)}" placeholder="z Yahoo" aria-label="Cena teraz (opcjonalnie)"></td>
    <td><button class="icon" type="button" data-act="mdel" data-i="${i}" aria-label="Usuń pozycję">✕</button></td></tr>`).join("");
  return `<section class="card" id="mEditor"><div class="card-head"><div><h2>Konto ręczne</h2><p>Gotówka i pozycje wpisane samodzielnie, bez raportu XTB. Zapis jest tylko na tym komputerze.</p></div>
      <span class="muted xs">${M.prices_at ? "ceny z " + esc(M.prices_at.slice(0, 16).replace("T", " ")) : "ceny pobiorą się po zapisie"}</span></div>
    <div class="mrow-k">
      <label class="field"><span>Gotówka na koncie (zł)</span><input type="text" inputmode="decimal" data-m="cash" value="${esc(d.cash)}" placeholder="0"></label>
      <label class="field"><span>Wpłacono netto (zł) — do liczenia wyniku</span><input type="text" inputmode="decimal" data-m="deposited" value="${esc(d.deposited)}" placeholder="0"></label>
      <label class="field"><span>Dodaj wpłatę (zł)</span><span class="row" style="flex-wrap:nowrap"><input type="text" inputmode="decimal" id="mDepAmt" placeholder="np. 500" style="flex:1"><button class="btn" type="button" data-act="mdeposit">＋ Wpłać</button></span></label>
    </div>
    <div class="tbl-wrap"><table class="mtable"><thead><tr><th>Ticker</th><th>Rynek</th><th>Ilość</th><th>Średnia cena zakupu</th><th>Waluta</th><th>Cena teraz</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="note">USA: sam ticker (NVDA, BRK-B). GPW: bez końcówki (ALE). ETF: jak w XTB, np. CSPX.UK. Średnia cena zakupu w walucie instrumentu. „Cena teraz” zostaw puste, żeby program pobrał ostatnie zamknięcie z Yahoo
      (kurs USD/PLN ${fx.USD ? num(fx.USD, 3) : "—"}); wpisana cena zostaje na stałe.</p>
    <div class="row"><button class="btn" type="button" data-act="madd">＋ Dodaj pozycję</button><button class="btn primary" type="button" data-act="msave">Zapisz konto</button>
      ${M.has ? `<button class="btn" id="mPricesBtn" type="button" data-act="mprices" ${S.task.busy ? "disabled" : ""}>Odśwież ceny</button><button class="btn ghost" type="button" data-act="mcancel">Anuluj</button>` : ""}</div></section>`;
}
function adjustCard() {
  const defc = { usa: "USD", gpw: "PLN", etf: "USD" };
  const rows = S.adjust.map((a) => `<tr><td><span class="pill ${a.op === "buy" ? "good" : "bad"}">${a.op === "buy" ? "KUP" : "SPRZEDAJ"}</span></td>
    <td><b>${esc(a.t)}</b> <span class="muted xs">${KIND_LAB[a.kind]}</span></td><td class="r">${num(a.shares, a.shares % 1 ? 4 : 0)}</td><td class="r">${num(a.price)} ${a.ccy || defc[a.kind]}</td>
    <td class="r">${a.amount_pln ? zl(a.amount_pln) : ""}</td><td>${esc(a.ts.slice(0, 10))}</td><td><button class="icon" type="button" data-act="adel" data-id="${esc(a.id)}" aria-label="Usuń wpis">✕</button></td></tr>`).join("");
  return `<section class="card" id="aCard"><div class="card-head"><div><h2>Dopisz zakup lub sprzedaż</h2><p>Transakcje po dacie raportu XTB (np. dzisiejszy zakup). Pozycje, średnia cena zakupu, stop i gotówka liczą się od razu; nowy raport XTB zastępuje te wpisy.</p></div></div>
    <div class="mrow-k">
      <label class="field"><span>Ticker</span><input type="text" id="ad_t" placeholder="np. NVDA, ALE, CSPX.UK" autocomplete="off" style="text-transform:uppercase"></label>
      <label class="field"><span>Rynek</span><select id="ad_kind">${Object.entries(KIND_LAB).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
      <label class="field"><span>Liczba akcji</span><input type="text" inputmode="decimal" id="ad_sh" placeholder="np. 2,5"></label>
      <label class="field"><span>Cena transakcji (waluta instrumentu)</span><input type="text" inputmode="decimal" id="ad_pr" placeholder="np. 187,40"></label>
      <label class="field"><span>Waluta</span><select id="ad_ccy"><option value="">auto (USD / PLN)</option>${["PLN", "USD", "EUR", "GBP"].map((c) => `<option>${c}</option>`).join("")}</select></label>
      <label class="field"><span>Kwota z konta w zł (opcjonalnie)</span><input type="text" inputmode="decimal" id="ad_pln" placeholder="program policzy z kursu"></label>
    </div>
    <div class="row"><button class="btn primary" type="button" data-act="abuy">Dodaj zakup</button><button class="btn" type="button" data-act="asell">Dodaj sprzedaż</button>
      ${S.adjust.length ? "" : `<button class="btn ghost" type="button" data-act="aclose">Zamknij</button>`}</div>
    ${rows ? `<div class="tbl-wrap"><table><thead><tr><th></th><th>Spółka</th><th class="r">Ilość</th><th class="r">Cena</th><th class="r">Z konta</th><th>Dodano</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : ""}</section>`;
}
async function submitAdjust(op) {
  const body = { op, t: $("#ad_t").value, kind: $("#ad_kind").value, shares: numOf($("#ad_sh").value), price: numOf($("#ad_pr").value), ccy: $("#ad_ccy").value || undefined, amount_pln: numOf($("#ad_pln").value) || undefined };
  try {
    setState(await post("adjust", body));
    toast(op === "buy" ? "Dopisano zakup" : "Dopisano sprzedaż");
    const r = await post("manual/prices");
    if (r.started) { S.task.busy = true; setState(S); }
  } catch (e) { toast(e.message, true); }
}
function viewPortfolio() {
  const P = S.portfolio;
  const sel = P && P.accounts.length > 1 ? `<label class="field"><span>Konto</span><select id="account">${P.accounts.map((a) => `<option ${a === P.label ? "selected" : ""}>${esc(a)}</option>`).join("")}</select></label>` : "";
  let h = `<header class="page-head"><div><h1>Portfel</h1><p>${P ? (P.manual ? "Konto ręczne" : `Konto ${esc(P.label)} · raport ${esc((P.generated || "").slice(0, 16).replace("T", " "))} UTC`) : "Pozycje z raportu XTB albo wpisane ręcznie"}</p></div>
    <div class="row-tools">${sel}${P && !P.manual ? `<button class="btn" type="button" data-act="aopen">＋ Dopisz zakup</button>` : ""}<button class="btn" type="button" data-act="mopen">${S.manual_acct.has ? "Edytuj konto ręczne" : "＋ Konto ręczne"}</button></div></header>`;
  if (ui.manualEdit && ui.draft) h += manualEditor();
  if (P && !P.manual && (ui.adjOpen || S.adjust.length)) h += adjustCard();
  if (!P) return ui.manualEdit ? h : h + `<div class="card"><div class="empty"><b>Brak konta</b>Wczytaj raport z XTB (xStation → Historia konta → Eksport) albo wpisz gotówkę i pozycje ręcznie.
      <div class="row"><button class="btn" data-act="xtb" type="button">Wczytaj raport XTB…</button><button class="btn" data-act="mopen" type="button">Wpisz ręcznie</button></div></div></div>`;
  h += `<section class="card"><div class="tbl-wrap"><table><thead><tr><th>Spółka</th><th class="c-opt">Koszyk</th><th class="r">Wartość</th><th class="r">Udział</th><th class="r">Wynik</th>
      <th class="r">Zakup / stop −40 %</th><th class="r c-opt">Cena teraz</th><th class="r">Od SMA 10</th><th class="r c-opt">Do stopu −40 %</th><th>Status</th></tr></thead><tbody>`;
  const max = Math.max(...P.rows.map((r) => r.share), 0.01);
  for (const r of P.rows) {
    const sell = r.status.startsWith("SPRZEDAJ"), dim = r.bucket === "etf" || r.bucket === "inne";
    const st = sell ? "bad" : r.status.startsWith("kandydat") ? "good" : r.status.startsWith("trzymaj") ? "info" : "";
    h += `<tr class="${sell ? "sell" : dim ? "dim" : ""}" data-sym="${esc(r.yahoo)}" data-title="${esc(r.name)}" data-entry="${r.open_price || ""}">
      <td><span class="t">${esc(r.t)}</span> <span class="n">${esc(r.name === r.t ? "" : r.name)}</span>${r.adjusted ? ` <span class="pill info" title="Zmienione ręcznie po raporcie XTB">+</span>` : ""} <span class="tag c-opt-inv" style="--c:${BCOL[r.bucket]}" title="${BUCKET[r.bucket]}"></span></td>
      <td class="c-opt"><span class="tag" style="--c:${BCOL[r.bucket]}">${BUCKET[r.bucket]}</span></td>
      <td class="r">${zl(r.value)}</td>
      <td class="r">${pct(r.share, 1, false)}<span class="minibar" style="--c:${BCOL[r.bucket]}"><i style="width:${(r.share / max) * 100}%"></i></span></td>
      <td class="r ${cls(r.profit_pct)}">${pct(r.profit_pct == null ? null : r.profit_pct / 100)}</td>
      <td class="r">${r.open_price ? `${num(r.open_price)}<small class="ccy"> ${esc(r.ccy || "")}</small><br><span class="stopv">stop ${num(r.stop)}</span>` : "—"}</td><td class="r c-opt">${num(r.price)}</td>
      <td class="r ${cls(r.dist)}">${r.dist == null ? "—" : pct(r.dist)}</td>
      <td class="r c-opt ${r.stop_dist != null && r.stop_dist < 0.15 ? "neg" : ""}">${r.stop_dist == null ? "—" : pct(r.stop_dist)}</td>
      <td><span class="pill ${st}" title="${esc(r.status)}">${esc(r.status)}</span></td></tr>`;
  }
  h += `</tbody></table></div><p class="note">Kliknij spółkę, żeby zobaczyć wykres miesięczny z ceną zakupu i stopem. „Zakup” to średnia cena zakupu, „stop” = 60 % tej ceny (−40 %), obie w walucie instrumentu, czyli tam, gdzie ustawiasz zlecenie stop w XTB. „Do stopu” = ile cena może jeszcze spaść do tego poziomu.</p></section>`;
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
      <span class="muted xs">${X.rows.length} kandydatów z ${X.count} spółek${m === "usa" && X.prefilter ? ` · sito Finviz tylko dla indeksu lidera: ${X.prefilter.lead === "NDX" ? "Nasdaq-100 " + X.prefilter.nq : "S&P 500 " + X.prefilter.sp}` : ""}</span></div>
      <span class="legend-inline"><span><i style="background:var(--good)"></i>do kupienia (pierwsze ${n})</span>${held.size ? `<span><span class="pill info">masz</span></span>` : ""}</span></div>
    <div class="tbl-wrap"><table><thead><tr><th class="r">#</th><th>Spółka</th><th class="r">6 mies.</th>${m === "gpw" ? `<th class="r c-opt">3 mies.</th><th class="r c-opt">12 mies.</th>` : ""}
      <th class="r">Zamknięcie</th><th class="r c-opt">SMA 10</th><th class="r">Nad SMA 10</th><th class="c-opt">Indeks</th><th></th></tr></thead><tbody>`;
  let cut = false;
  for (const r of shown) {
    if (!q && !cut && r.rank > n) { cut = true; h += `<tr class="cutline"><td colspan="10">Poniżej: kandydaci rezerwowi (gdy któraś z pierwszych ${n} jest już w portfelu albo dla dopłat)</td></tr>`; }
    const buy = r.rank <= n && !X.bear;
    const idx = [["S&P 500", r.sp], ["NDX", r.nq], ["WIG20", r.w20], ["mWIG40", r.w40]].filter((x) => x[1]).map((x) => x[0]).join(", ");
    h += `<tr class="${buy ? "buy" : ""}" data-sym="${esc(m === "gpw" ? r.t + ".WA" : r.t)}" data-title="${esc(r.n)}">
      <td class="r muted">${r.rank}</td><td><span class="t">${esc(r.t)}</span> <span class="n">${esc(r.n === r.t ? "" : r.n)}</span></td>
      <td class="r ${cls(r.r6)}"><b>${pct(r.r6)}</b></td>${m === "gpw" ? `<td class="r c-opt ${cls(r.r3)}">${pct(r.r3)}</td><td class="r c-opt ${cls(r.r12)}">${pct(r.r12)}</td>` : ""}
      <td class="r">${num(r.c)}</td><td class="r muted c-opt">${num(r.sma)}</td><td class="r ${cls(r.dist)}">${pct(r.dist)}</td><td class="muted c-opt">${idx}</td>
      <td>${held.has(r.t) ? `<span class="pill info">masz</span>` : buy ? `<span class="pill good">kup</span>` : ""}</td></tr>`;
  }
  if (!shown.length) h += `<tr><td colspan="10" class="muted">Brak spółek${q ? " dla „" + esc(ui.q[m]) + "”" : ""}.</td></tr>`;
  h += `</tbody></table></div>${!q && !ui.all[m] && rows.length > shown.length ? `<button class="btn sm" data-act="all" data-m="${m}" type="button">Pokaż wszystkich (${rows.length})</button>` : ""}
    ${X.missing && X.missing.length ? `<p class="note">Bez notowań w Yahoo: ${X.missing.slice(0, 30).map(esc).join(", ")}${X.missing.length > 30 ? "…" : ""}</p>` : ""}</section>`;
  return h;
}

// ------------------------------------------------------------------ Historia konta
function viewHistory() {
  const H = S.history, P = S.portfolio;
  let h = `<header class="page-head"><div><h1>Historia konta</h1><p>Wartość konta i wpłaty netto z raportu XTB</p></div>
    ${H ? `<button class="btn" id="curveBtn" data-act="curve" type="button" ${S.task.busy ? "disabled" : ""}>${H.exact ? "Przelicz ponownie" : "Wyceń cenami dziennymi"}</button>` : ""}</header>`;
  if (P && P.manual) return h + `<div class="card"><div class="empty"><b>Historia jest dostępna tylko dla raportu XTB</b>Konto ręczne nie ma dat transakcji. Wczytaj raport XTB, żeby zobaczyć krzywą kapitału.
    <button class="btn" data-act="xtb" type="button">Wczytaj raport XTB…</button></div></div>`;
  if (!H) return h + `<div class="card"><div class="empty"><b>Brak raportu XTB</b><button class="btn" data-act="xtb" type="button">Wybierz plik raportu…</button></div></div>`;
  const seg = [["6m", "6 mies."], ["1y", "1 rok"], ["3y", "3 lata"], ["all", "Całość"]].map(([k, l]) => `<button type="button" data-hr="${k}" aria-pressed="${ui.histRange === k}">${l}</button>`).join("");
  h += `<section class="card curve"><div class="card-head"><div class="row-tools"><div class="seg" role="group" aria-label="Zakres">${seg}</div>
      <label class="chk"><input type="checkbox" id="histSales" ${ui.histSales ? "checked" : ""}> pokaż sprzedaże</label></div>
      ${H.exact ? `<span class="pill good">ceny dzienne Yahoo</span>` : `<span class="pill warn">przybliżenie bez cen rynkowych</span>`}</div>
    <div class="curve-kpis" id="curveKpi"></div>
    ${H.points.length > 1 ? `<div class="curve-host" id="curveHost"></div>` : `<div class="empty">Za mało danych do wykresu.</div>`}
    <div class="legend-inline"><span><i style="background:var(--accent)"></i>wartość konta</span><span><i style="background:var(--muted)"></i>wpłacono netto</span>
      <span><i style="background:var(--good);height:10px;opacity:.4"></i>zysk</span><span><i style="background:var(--bad);height:10px;opacity:.4"></i>strata</span><span><i style="background:var(--bad)"></i>obsunięcie od szczytu (indeks zwrotu, bez wpłat)</span></div></section>`;
  h += statsCard(H.stats);
  h += `<section class="card"><div class="card-head"><h2>Zdarzenia</h2><span class="muted xs">${H.events.length}</span></div><div class="tbl-wrap"><table><thead><tr><th>Data</th><th>Zdarzenie</th><th>Spółka</th><th class="r">Kwota / wynik</th><th class="r">Wynik %</th></tr></thead><tbody>
    ${(ui.allEv ? H.events : H.events.slice(0, 40)).map((e) => `<tr><td class="num">${esc(e.d)}</td><td><span class="pill ${e.kind === "wpłata" ? "info" : e.kind === "wypłata" ? "warn" : e.amount >= 0 ? "good" : "bad"}">${e.kind}</span></td>
      <td>${esc(e.t)}</td><td class="r ${e.kind === "sprzedaż" ? cls(e.amount) : ""}">${zl(e.amount)}</td><td class="r ${cls(e.pct)}">${e.pct == null ? "" : pct(e.pct)}</td></tr>`).join("")}
    </tbody></table></div>${!ui.allEv && H.events.length > 40 ? `<button class="btn sm" data-act="allev" type="button">Pokaż wszystkie (${H.events.length})</button>` : ""}</section>`;
  return h;
}

// --- wskaźniki jakości: wynik, ryzyko, jakość, transakcje i porównanie z historią strategii
const LV = { early: ["info", "Za wcześnie"], ok: ["good", "W normie"], warn: ["warn", "Uwaga"], bad: ["bad", "Poniżej historii"], info: ["info", "Informacja"] };
function statsCard(m) {
  if (!m) return `<section class="card"><div class="card-head"><h2>Wskaźniki jakości</h2></div><div class="empty">Za mało danych do wskaźników (min. ok. miesiąca historii z cenami).</div></section>`;
  const t = (label, val, hint, c = "") => `<div class="perf-t" title="${esc(hint)}"><span>${esc(label)}</span><b class="${c}">${val}</b></div>`;
  const v = m.verdict, [vc, vl] = LV[v.level], tr = m.trades, b = m.bench, mo = m.months;
  const yrs = m.years >= 1 ? num(m.years, 1) + " l." : Math.round(m.years * 12) + " mies.";
  let h = `<section class="card perf"><div class="card-head"><div><h2>Wskaźniki jakości</h2><p>Cała historia konta (${esc(m.from)} → ${esc(m.to)}, ${yrs}), liczone na zwrocie bez wpłat i wypłat</p></div><span class="pill ${vc}">${vl}</span></div>
    <p class="verdict ${vc}">${esc(v.text)}</p>
    <div class="perf-grid">
      <div class="perf-g"><h3>Wynik</h3>
        ${t("Zwrot łącznie", pct(m.twr), "Zwrot ważony czasem (TWR): wpłaty i wypłaty nie są zyskiem", cls(m.twr))}
        ${t("Zwrot roczny", m.cagr == null ? "—" : pct(m.cagr), "Średni zwrot roczny (CAGR); liczony od roku historii", cls(m.cagr))}
        ${t("Zwrot z wpłatami (XIRR)", m.xirr == null ? "—" : pct(m.xirr), "Roczna stopa zwrotu ważona terminami wpłat: odpowiada na pytanie, ile zarabiają Twoje pieniądze", cls(m.xirr))}
        ${t("Ostatnie 12 mies.", m.r12 == null ? "—" : pct(m.r12), "Zwrot z ostatnich 365 dni", cls(m.r12))}
        ${b ? t("Względem " + b.name + " (zł)", pct(b.diff), `Różnica zwrotu konta i ${b.name} w złotych w tym samym okresie (${b.name}: ${pct(b.total)}, obsunięcie ${pct(b.max_dd)})`, cls(b.diff)) : t("Względem SPY", "—", "Kliknij „Przelicz ponownie” (ceny dzienne), żeby dołączyć porównanie z SPY")}</div>
      <div class="perf-g"><h3>Ryzyko</h3>
        ${t("Maks. obsunięcie", pct(m.max_dd), "Największy spadek od szczytu indeksu zwrotu, " + m.max_dd_date, "neg")}
        ${t("Obsunięcie teraz", pct(m.dd), "Odległość od ostatniego szczytu", cls(m.dd))}
        ${t("Od szczytu", m.since_peak_days + " dni", "Ile dni minęło od ostatniego szczytu")}
        ${t("Najdłużej pod szczytem", num(m.under_days / 30.4, 0) + " mies.", "Najdłuższy okres bez nowego szczytu")}
        ${t("Zmienność roczna", m.vol == null ? "—" : pct(m.vol, 1, false), "Odchylenie standardowe dziennych zwrotów × √252")}
        ${t("Najgorszy miesiąc", mo.worst == null ? "—" : pct(mo.worst), "Najgorszy miesiąc kalendarzowy", cls(mo.worst))}
        ${t("Miesiące dodatnie", mo.pos == null ? "—" : pct(mo.pos, 0, false), `Udział miesięcy z zyskiem (${mo.n} mies.); w badaniu CEM10: ${pct(m.ref.pos_months, 0, false)}`)}</div>
      <div class="perf-g"><h3>Jakość</h3>
        ${t("Sharpe", m.sharpe == null ? "—" : num(m.sharpe, 2), "Zwrot / zmienność (bez stopy wolnej od ryzyka). W badaniu CEM10: " + num(m.ref.sharpe, 2))}
        ${t("Sortino", m.sortino == null ? "—" : num(m.sortino, 2), "Zwrot / zmienność tylko spadków")}
        ${t("Calmar", m.calmar == null ? "—" : num(m.calmar, 2), "Zwrot roczny / maks. obsunięcie (od 1 roku historii)")}
        ${t("Błąd pomiaru", m.se_annual == null ? "—" : "±" + pct(m.se_annual * 1.96, 0, false) + " rocznie", "Z taką dokładnością (95 %) da się dziś ocenić średni zwrot roczny przy tej zmienności i długości historii. Różnice mniejsze niż ta wartość są szumem")}</div>
      ${tr ? `<div class="perf-g"><h3>Transakcje (${tr.n})</h3>
        ${t("Trafność", pct(tr.win_rate, 0, false), `${tr.wins} z ${tr.n} zamkniętych pozycji z zyskiem`)}
        ${t("Średni zysk / strata", `<span class="pos">${pct(tr.avg_win)}</span> / <span class="neg">${pct(tr.avg_loss)}</span>`, "Średni wynik transakcji wygrywających i przegrywających")}
        ${t("Payoff", tr.payoff == null ? "—" : num(tr.payoff, 2), "Średni zysk ÷ średnia strata")}
        ${t("Profit factor", tr.profit_factor == null ? "—" : num(tr.profit_factor, 2), "Suma zysków ÷ suma strat (powyżej 1 = na plusie)")}
        ${t("Oczekiwany wynik", pct(tr.expectancy), "Średni wynik jednej transakcji", cls(tr.expectancy))}
        ${t("Średni czas", tr.avg_hold == null ? "—" : num(tr.avg_hold / 30.4, 1) + " mies.", "Średni czas trzymania pozycji")}
        ${t("Najlepsza / najgorsza", `<span class="pos">${pct(tr.best)}</span> / <span class="neg">${pct(tr.worst)}</span>`, "Najlepsza i najgorsza transakcja")}</div>` : ""}
    </div>
    ${tr && tr.n < 30 ? `<p class="note">Mało transakcji (${tr.n}): trafność i payoff mogą się jeszcze mocno zmienić.</p>` : ""}
    <h3>Czy to zgodne z historią CEM10?</h3>
    <div class="tbl-wrap"><table><thead><tr><th>Kontrola</th><th class="r">Teraz</th><th>W badaniu historycznym</th><th>Ocena</th></tr></thead><tbody>
      ${v.checks.map((c) => { const [k, l] = LV[c.level]; const now = c.name.startsWith("Najdłuższy") ? num(c.now, 0) + " mies." : pct(c.now, 1, !c.name.startsWith("Zmienność"));
        return `<tr><td>${esc(c.name)}${c.note ? `<div class="muted xs">${esc(c.note)}</div>` : ""}</td><td class="r num">${now}</td><td class="muted">${esc(c.hist).replace(/-(\d)/g, "−$1")}</td><td><span class="pill ${k}">${l}</span></td></tr>`; }).join("")}
    </tbody></table></div>
    <p class="note">Odniesienie to badanie CEM10 USA z lat 1999–2026 (szeroki rynek, miesięcznie, z błędem przeżywalności, więc prawdziwe wyniki mogą być niższe). Konto to całość z bazą ETF, GPW i gotówką, więc porównanie jest orientacyjne. W historii strategia miała ${pct(m.ref.neg_12m, 0, false)} ujemnych rocznych okien i do ${m.ref.under_water_months} mies. pod szczytem, więc ocenę warto robić po minimum 2–3 latach.</p></section>`;
  return h;
}

// --- wspólne: ładne podziałki osi
function niceLin(lo, hi, n = 5) {
  const raw = (hi - lo) / n || 1, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p, step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p, out = [];
  for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}
function niceLog(lo, hi) {
  let out = [];
  for (const mult of [[1, 2, 5], [1, 1.5, 2, 3, 5, 7]]) {
    out = [];
    for (let k = Math.floor(Math.log10(lo)); k <= Math.ceil(Math.log10(hi)); k++) for (const m of mult) { const v = m * Math.pow(10, k); if (v >= lo && v <= hi) out.push(v); }
    if (out.length >= 4) break;
  }
  while (out.length > 8) out = out.filter((_, i) => i % 2 === 0);
  return out;
}
const fmtTick = (v) => num(v, v >= 100 ? 0 : v >= 10 ? (v % 1 ? 1 : 0) : v % 1 ? 2 : 0);
const compact = (v) => (v >= 1e9 ? num(v / 1e9, 2) + " mld" : v >= 1e6 ? num(v / 1e6, 1) + " mln" : v >= 1e3 ? num(v / 1e3, 0) + " tys." : num(v, 0));

// --- krzywa kapitału: rozmiar z kontenera, podziałki, najechanie myszą pokazuje datę, wartość, wpłaty i wynik
let curveRO = null;
function drawCurve() {
  const host = $("#curveHost");
  if (!host || !S.history) return;
  if (curveRO) curveRO.disconnect();
  curveRO = new ResizeObserver(() => renderCurve(host));
  curveRO.observe(host);
  renderCurve(host);
}
// obsunięcie liczone na indeksie zwrotu (wpłaty i wypłaty nie robią z niego fałszywych spadków ani wzrostów): dzienny zwrot = wartość / (wczorajsza wartość + dzisiejszy przepływ) − 1
function drawdownSeries(pts) {
  let idx = 1, peak = 1, prev = null, worst = 0, worstI = 0;
  pts.forEach((p, i) => {
    if (prev) { const base = prev.v + (p.dep - prev.dep); if (base > 1 && p.v > 0) idx *= p.v / base; }
    peak = Math.max(peak, idx); p.dd = idx / peak - 1; p.idx = idx; prev = p;
    if (p.dd < worst) { worst = p.dd; worstI = i; }
  });
  return { worst, worstI };
}
function renderCurve(host) {
  if (!host.isConnected || !$("#curveKpi")) return;
  let pts = S.history.points.map((q) => ({ t: Date.parse(q[0]), d: q[0], v: q[1], dep: q[2] }));
  if (pts.length < 2) return;
  const t1 = pts[pts.length - 1].t, span = { "6m": 183, "1y": 365, "3y": 1096 }[ui.histRange];
  if (span) { const cut = t1 - span * 864e5, f = pts.filter((p) => p.t >= cut); if (f.length > 1) pts = f; }
  const W = Math.max(host.clientWidth, 320), Hh = Math.max(host.clientHeight, 300), mL = 56, mR = 16, mT = 12, mB = 26, ddH = Math.round(Math.min(120, Hh * 0.26)), gap = 30;
  const x0 = mL, x1 = W - mR, y0 = mT, y1 = Hh - mB - ddH - gap, yd0 = y1 + gap, yd1 = Hh - mB;
  const dd = drawdownSeries(pts), ddFloor = Math.min(dd.worst * 1.1, -0.04), Yd = (d) => yd0 + (d / ddFloor) * (yd1 - yd0);
  const ta = pts[0].t, tb = pts[pts.length - 1].t;
  let lo = Math.min(...pts.map((p) => Math.min(p.v, p.dep))), hi = Math.max(...pts.map((p) => Math.max(p.v, p.dep)));
  const pad = (hi - lo) * 0.08 || hi * 0.05 || 1; lo = Math.max(lo - pad, 0); hi += pad;
  const X = (t) => x0 + ((t - ta) / (tb - ta || 1)) * (x1 - x0), Y = (v) => y1 - ((v - lo) / (hi - lo)) * (y1 - y0);
  const k = hi >= 20000, yl = (v) => (k ? num(v / 1000, 0) + " tys." : num(v, 0));
  let s = `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Wartość konta i wpłaty w czasie">`;
  for (const v of niceLin(lo, hi, 5)) s += `<line x1="${x0}" x2="${x1}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/><text x="${x0 - 8}" y="${Y(v) + 4}" text-anchor="end" font-size="11.5" fill="var(--muted)">${yl(v)}</text>`;
  // oś czasu: lata (gdy zakres długi) albo miesiące
  const years = (tb - ta) / 864e5 / 365, d0 = new Date(ta), stepM = years > 6 ? 24 : years > 2.5 ? 12 : years > 1.2 ? 6 : years > 0.6 ? 3 : 1;
  let cur = new Date(Date.UTC(d0.getUTCFullYear(), d0.getUTCMonth() + 1, 1)), lastX = -99;
  while (cur.getTime() <= tb) {
    const m = cur.getUTCMonth(), y = cur.getUTCFullYear();
    if ((y * 12 + m) % stepM === 0 || (stepM >= 12 && m === 0 && (y % (stepM / 12) === 0))) {
      const x = X(cur.getTime());
      if (x - lastX > 44) { s += `<line x1="${x}" x2="${x}" y1="${yd1}" y2="${yd1 + 4}" stroke="var(--line)"/><text x="${x}" y="${Hh - 8}" text-anchor="middle" font-size="11.5" fill="var(--muted)">${m === 0 || stepM >= 12 ? y : MSHORT[m] + " " + String(y).slice(2)}</text>`; lastX = x; }
    }
    cur = new Date(Date.UTC(y, m + 1, 1));
  }
  const vline = pts.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join("");
  const dstep = []; pts.forEach((p, i) => { if (i) dstep.push([X(p.t), Y(pts[i - 1].dep)]); dstep.push([X(p.t), Y(p.dep)]); });
  const dpath = dstep.map((q, i) => `${i ? "L" : "M"}${q[0].toFixed(1)},${q[1].toFixed(1)}`).join("");
  const vrev = pts.slice().reverse().map((p) => `L${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join("");
  const band = `${dpath}${vrev}Z`;                                                   // obszar między wpłatami a wartością: zielony nad linią wpłat, czerwony pod nią
  const above = `${dpath}L${x1},${y0}L${x0},${y0}Z`, below = `${dpath}L${x1},${y1}L${x0},${y1}Z`;
  s += `<defs><clipPath id="cpA"><path d="${above}"/></clipPath><clipPath id="cpB"><path d="${below}"/></clipPath></defs>
    <path d="${band}" fill="var(--good)" opacity=".2" clip-path="url(#cpA)"/><path d="${band}" fill="var(--bad)" opacity=".22" clip-path="url(#cpB)"/>
    <path d="${dpath}" fill="none" stroke="var(--muted)" stroke-width="1.5" stroke-dasharray="5 4"/>
    <path d="${vline}" fill="none" stroke="var(--accent)" stroke-width="2.3" stroke-linejoin="round"/>`;
  if (ui.histSales) for (const e of S.history.events.filter((e) => e.kind === "sprzedaż")) {
    const t = Date.parse(e.d); if (t < ta || t > tb) continue;
    let a = 0, b = pts.length - 1; while (a < b) { const m = (a + b) >> 1; if (pts[m].t < t) a = m + 1; else b = m; }
    s += `<circle cx="${X(pts[a].t)}" cy="${Y(pts[a].v)}" r="3.2" fill="${e.amount >= 0 ? "var(--good)" : "var(--bad)"}" opacity=".85" stroke="var(--surface)" stroke-width="1"><title>${esc(e.d)} ${esc(e.t)} ${zl(e.amount)}</title></circle>`;
  }
  // panel obsunięcia: pole pod zerem, siatka co ~5-10 pp
  const ddStep = Math.abs(ddFloor) > 0.4 ? 0.2 : Math.abs(ddFloor) > 0.2 ? 0.1 : 0.05;
  s += `<text x="${x0}" y="${yd0 - 6}" font-size="11.5" fill="var(--muted)">Obsunięcie od szczytu (bez wpłat)</text>`;
  for (let v = 0; v >= ddFloor - 1e-9; v -= ddStep) s += `<line x1="${x0}" x2="${x1}" y1="${Yd(v)}" y2="${Yd(v)}" stroke="var(--grid)"/><text x="${x0 - 8}" y="${Yd(v) + 4}" text-anchor="end" font-size="11.5" fill="var(--muted)">${v === 0 ? "0" : "−" + num(-v * 100, 0)} %</text>`;
  const dline = pts.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Yd(p.dd).toFixed(1)}`).join("");
  s += `<path d="${dline}L${X(pts[pts.length - 1].t).toFixed(1)},${Yd(0)}L${X(pts[0].t).toFixed(1)},${Yd(0)}Z" fill="var(--bad)" opacity=".22"/><path d="${dline}" fill="none" stroke="var(--bad)" stroke-width="1.6" stroke-linejoin="round"/>`;
  if (dd.worst < -0.005) { const w = pts[dd.worstI]; s += `<circle cx="${X(w.t)}" cy="${Yd(w.dd)}" r="3.5" fill="var(--bad)" stroke="var(--surface)" stroke-width="1"><title>Maks. obsunięcie ${esc(w.d)} ${pct(w.dd)}</title></circle>`; }
  const last = pts[pts.length - 1];
  s += `<line id="cvx" x1="0" x2="0" y1="${y0}" y2="${yd1}" stroke="var(--muted)" stroke-dasharray="3 3" visibility="hidden"/><circle id="cvd" r="4.5" fill="var(--accent)" stroke="var(--surface)" stroke-width="2" visibility="hidden"/><circle id="cvdd" r="4" fill="var(--bad)" stroke="var(--surface)" stroke-width="2" visibility="hidden"/>
    <rect id="cvhit" x="${x0}" y="${y0}" width="${x1 - x0}" height="${yd1 - y0}" fill="transparent"/></svg>`;
  host.innerHTML = s;
  const kpi = (p, hov) => { const r = p.v - p.dep; $("#curveKpi").innerHTML = `<span>${hov ? esc(p.d) : "Na dzień " + esc(p.d)}<b>${zl(p.v)}</b></span><span>Wpłacono netto<b>${zl(p.dep)}</b></span>
    <span>Wynik<b class="${cls(r)}">${zl(r)}${p.dep ? " · " + pct(r / p.dep) : ""}</b></span>
    <span>Obsunięcie${hov ? "" : " teraz"}<b class="${cls(p.dd)}">${pct(p.dd)}</b></span><span>Maks. obsunięcie w zakresie<b class="${cls(dd.worst)}">${pct(dd.worst)}</b></span>`; };
  kpi(last, false);
  const hit = $("#cvhit", host), vx = $("#cvx", host), vd = $("#cvd", host), vdd = $("#cvdd", host);
  hit.addEventListener("mousemove", (e) => {
    const r = host.getBoundingClientRect(), t = ta + ((e.clientX - r.left - x0) / (x1 - x0)) * (tb - ta);
    let a = 0, b = pts.length - 1; while (a < b) { const m = (a + b) >> 1; if (pts[m].t < t) a = m + 1; else b = m; }
    if (a > 0 && Math.abs(pts[a - 1].t - t) < Math.abs(pts[a].t - t)) a--;
    const p = pts[a]; vx.setAttribute("x1", X(p.t)); vx.setAttribute("x2", X(p.t)); vx.setAttribute("visibility", "visible");
    vd.setAttribute("cx", X(p.t)); vd.setAttribute("cy", Y(p.v)); vd.setAttribute("visibility", "visible");
    vdd.setAttribute("cx", X(p.t)); vdd.setAttribute("cy", Yd(p.dd)); vdd.setAttribute("visibility", "visible"); kpi(p, true);
  });
  hit.addEventListener("mouseleave", () => { vx.setAttribute("visibility", "hidden"); vd.setAttribute("visibility", "hidden"); vdd.setAttribute("visibility", "hidden"); kpi(last, false); });
}

// ------------------------------------------------------------------ Ustawienia
function viewSettings() {
  const st = S.settings, tg = st.targets, g = S.gpw, ts = (tg.usa + tg.gpw + tg.etf) || 1;
  const M = S.manual_acct;
  return `<header class="page-head"><div><h1>Ustawienia</h1><p>Zapisują się same. Dane programu: <span class="num">${esc(S.data_dir)}</span></p></div></header>
  <div class="set-grid">
    <section class="card"><div class="card-head"><div><h2>Baza: ETF S&amp;P 500</h2><p>Jaką część całego kapitału trzymasz w ETF jako bazę. Reszta idzie w strategię CEM10, a nowe wpłaty dzielą się według tych udziałów.</p></div></div>
      <div class="etf-ctl"><input type="range" min="0" max="100" step="5" id="etfRange" value="${st.etf_pct}" aria-label="Udział ETF"><span class="money sm"><input type="text" inputmode="decimal" id="etfpct" value="${esc(num(st.etf_pct, st.etf_pct % 1 ? 1 : 0))}" aria-label="Udział ETF w procentach"><b>%</b></span></div>
      <div class="chips"><span class="chip"><span class="tag" style="--c:${BCOL.etf}">ETF ${num(tg.etf / ts * 100, 0)} %</span></span><span class="chip"><span class="tag" style="--c:${BCOL.usa}">USA ${num(tg.usa / ts * 100, 0)} %</span></span><span class="chip"><span class="tag" style="--c:${BCOL.gpw}">GPW ${num(tg.gpw / ts * 100, 0)} %</span></span></div>
      <label class="field"><span>Podział części CEM10: udział GPW (domyślnie 33 % = 5 z 15 miejsc)</span><span class="money sm"><input type="text" inputmode="decimal" id="gpwshare" value="${esc(num(st.gpw_share, st.gpw_share % 1 ? 1 : 0))}"><b>%</b></span></label>
      <label class="field"><span>ETF (ticker XTB)</span><input type="text" id="etf" value="${esc(st.etf)}"></label></section>
    <section class="card"><div class="card-head"><div><h2>Konto</h2><p>Raport z xStation (Historia konta → Eksport, zip z plikami xlsx dla każdego konta) albo konto wpisane ręcznie.</p></div></div>
      <div class="row"><button class="btn" data-act="xtb" type="button">Wczytaj nowy raport XTB…</button><button class="btn" data-act="mopen" type="button">${M.has ? "Edytuj konto ręczne" : "＋ Konto ręczne"}</button>
      ${S.portfolio && S.portfolio.accounts.length > 1 ? `<label class="field"><span>Używane konto</span><select id="account">${S.portfolio.accounts.map((a) => `<option ${a === S.portfolio.label ? "selected" : ""}>${esc(a)}</option>`).join("")}</select></label>` : ""}</div>
      <p class="note">${S.portfolio ? (S.portfolio.manual ? `Używane konto ręczne: ${M.positions.length} pozycji, gotówka ${zl(M.cash)}.` : `Wczytane konto ${esc(S.portfolio.label)}, raport z ${esc((S.portfolio.generated || "").slice(0, 10))}.`) : "Brak konta."}</p></section>
    <section class="card"><div class="card-head"><div><h2>Trzymane spółki (szybka kontrola)</h2><p>Tickery oddzielone spacją albo przecinkiem; GPW z końcówką .WA, np. ALE.WA. Po wybraniu konta uzupełnia się samo.</p></div></div>
      <textarea id="hold" rows="3" placeholder="np. NVDA, PLTR, ALE.WA">${esc(st.hold)}</textarea>
      ${S.manual.length && S.lists ? manualList() : ""}</section>
    <section class="card"><div class="card-head"><div><h2>Skład GPW</h2><p>Popraw po każdej rewizji (marzec, czerwiec, wrzesień, grudzień). Same tickery, bez nazw: jeden na wiersz albo po przecinku (np. skopiowane ze Stooq).</p></div>
      ${g.custom ? `<span class="pill info">własny</span>` : `<span class="pill">domyślny</span>`}</div>
      <label class="field"><span>Data rewizji</span><input type="text" id="g_rew" value="${esc(g.rewizja || "")}"></label>
      <div class="grid3" style="grid-template-columns:1fr 1fr">
        <label class="field"><span>WIG20 (${Object.keys(g.WIG20).length})</span><textarea id="g_w20" rows="10" placeholder="ALE&#10;PKO&#10;…">${esc(Object.keys(g.WIG20).join("\n"))}</textarea></label>
        <label class="field"><span>mWIG40 (${Object.keys(g.mWIG40).length})</span><textarea id="g_w40" rows="10" placeholder="ABE&#10;ACP&#10;…">${esc(Object.keys(g.mWIG40).join("\n"))}</textarea></label></div>
      <div class="row"><button class="btn primary" data-act="gpw" type="button">Zapisz skład</button><button class="btn" data-act="gpwreset" type="button">Przywróć domyślny</button></div></section>
    <section class="card"><div class="card-head"><div><h2>Zasady</h2></div></div>
      <p class="note"><b>USA:</b> lider SPY albo QQQ z wyższym zwrotem 5 mies.; kandydaci z indeksu lidera: 6 mies. &gt; +30 %, zamknięcie nad SMA 10, ranking po 6 mies., 10 pozycji; brak zakupów, gdy SPY zamyka miesiąc pod SMA 12.<br>
      <b>GPW:</b> WIG20 + mWIG40 razem, C-8 (3 mies. &gt; 0, 12 mies. &gt; +30 %, nad SMA 10), ranking po 6 mies., 5 pozycji; brak zakupów, gdy koszyk składników jest pod SMA 12.<br>
      <b>Wyjście:</b> zamknięcie miesiąca pod SMA 10, stop awaryjny −40 % od ceny zakupu.<br>
      <b>Wpłaty:</b> najpierw nowe spółki na wolne miejsca (waga = koszyk / liczba miejsc), potem dopełnienie trzymanych kandydatów do wagi, min. ${zl(S.rules.min_topup)}.</p></section>
  </div>`;
}
const TICKER = /^[A-Z0-9]{2,5}$/;   // tickery GPW: bez nazw, wiersze / spacje / przecinki, końcówka .WA ucinana
function parseTickers(t) {
  const ok = [], bad = [];
  for (let x of t.split(/[\s,;]+/)) {
    x = x.trim().toUpperCase().replace(/\.(WA|PL)$/, "");
    if (!x) continue;
    if (TICKER.test(x)) { if (!ok.includes(x)) ok.push(x); } else bad.push(x);
  }
  return { ok, bad };
}

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
  const ep = $("#etfpct"), er = $("#etfRange");
  if (ep) ep.addEventListener("input", () => { if (er) er.value = numOf(ep.value); saveSoon({ etf_pct: ep.value }, 700); });
  if (er) { er.addEventListener("input", () => { ep.value = er.value; }); er.addEventListener("change", () => saveSoon({ etf_pct: er.value }, 0)); }
  const gs = $("#gpwshare"); if (gs) gs.addEventListener("input", () => saveSoon({ gpw_share: gs.value }, 700));
  const etf = $("#etf"); if (etf) etf.addEventListener("change", () => saveSoon({ etf: etf.value }, 0));
  const hold = $("#hold"); if (hold) hold.addEventListener("input", () => saveSoon({ hold: hold.value }, 700));
  for (const acc of v.querySelectorAll("#account")) acc.addEventListener("change", () => saveSoon({ account: acc.value }, 0));
  for (const m of ["usa", "gpw"]) { const q = $("#q_" + m); if (q) q.addEventListener("input", () => { ui.q[m] = q.value; renderView(); }); }
  const hs = $("#histSales"); if (hs) hs.addEventListener("change", () => { ui.histSales = hs.checked; drawCurve(); });
  for (const b of v.querySelectorAll("[data-hr]")) b.addEventListener("click", () => { ui.histRange = b.dataset.hr; saveUi(); renderView(); });
  for (const el of v.querySelectorAll(".mi, [data-m]")) {   // edytor konta ręcznego: szkic w pamięci, zapis przyciskiem
    const upd = () => {
      if (!ui.draft) return;
      if (el.dataset.m) { ui.draft[el.dataset.m] = el.value; return; }
      const i = +el.closest("tr").dataset.i; ui.draft.positions[i][el.dataset.f] = el.value;
      if (el.dataset.f === "kind") renderView();
    };
    el.addEventListener(el.tagName === "SELECT" ? "change" : "input", upd);
  }
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
    if (act === "mopen") return openManual();
    if (act === "aopen") { ui.adjOpen = true; renderView(); const t = $("#ad_t"); if (t) t.focus(); return; }
    if (act === "aclose") { ui.adjOpen = false; return renderView(); }
    if (act === "abuy" || act === "asell") return submitAdjust(act === "abuy" ? "buy" : "sell");
    if (act === "adel") { try { setState(await post("adjust/delete", { id: a.dataset.id })); } catch (err) { toast(err.message, true); } return; }
    if (act === "madd") { ui.draft.positions.push(blankPos()); renderView(); const rows = document.querySelectorAll(".mtable tbody tr"); const r = rows[rows.length - 1]; if (r) r.querySelector("input").focus(); return; }
    if (act === "mdel") { ui.draft.positions.splice(+a.dataset.i, 1); if (!ui.draft.positions.length) ui.draft.positions.push(blankPos()); return renderView(); }
    if (act === "mcancel") { ui.manualEdit = false; ui.draft = null; return renderView(); }
    if (act === "msave") return saveManual();
    if (act === "mdeposit") return depositManual();
    if (act === "mprices") { try { await post("manual/prices"); S.task.busy = true; setState(S); } catch (err) { toast(err.message, true); } return; }
    if (act === "gpw") { try { const w20 = parseTickers($("#g_w20").value), w40 = parseTickers($("#g_w40").value), bad = [...w20.bad, ...w40.bad];
      setState(await post("gpw", { rewizja: $("#g_rew").value, WIG20: w20.ok, mWIG40: w40.ok })); toast(`Zapisano skład GPW (${w20.ok.length} + ${w40.ok.length}) — pobierz listę, żeby przeliczyć` + (bad.length ? `. Pominięto: ${bad.slice(0, 6).join(", ")}` : ""), bad.length > 0); } catch (err) { toast(err.message, true); } return; }
    if (act === "gpwreset") { try { setState(await post("gpw", { reset: true })); toast("Przywrócono domyślny skład GPW"); } catch (err) { toast(err.message, true); } return; }
  }
  const row = e.target.closest("[data-sym]");
  if (row && $("#view").contains(row)) {
    if (paneOn()) selectEl(row);
    else openChart(row.dataset.sym, row.dataset.title, entryFor(row.dataset.sym, parseFloat(row.dataset.entry) || null));
  }
});
async function saveManual() {
  const d = ui.draft;
  const body = { cash: numOf(d.cash), deposited: numOf(d.deposited), use: true,
    positions: d.positions.filter((p) => String(p.t).trim()).map((p) => ({ t: p.t, kind: p.kind, shares: numOf(p.shares), open_price: numOf(p.open_price), ccy: p.ccy || undefined, price: p.price_in ? numOf(p.price_in) : undefined })) };
  if (d.positions.some((p) => String(p.t).trim() && numOf(p.shares) <= 0)) return toast("Podaj liczbę akcji większą od zera dla każdej pozycji.", true);
  try {
    const s = await post("manual", body);
    ui.manualEdit = false; ui.draft = null; setState(s); toast("Zapisano konto ręczne");
    if (s.manual_acct.positions.length) { await post("manual/prices"); S.task.busy = true; setState(S); }
  } catch (e) { toast(e.message, true); }
}
async function depositManual() {
  const amt = numOf($("#mDepAmt").value);
  if (!amt) return toast("Wpisz kwotę wpłaty.", true);
  try {
    const s = await post("manual/deposit", { amount: amt });
    ui.draft.cash = String(s.manual_acct.cash || ""); ui.draft.deposited = String(s.manual_acct.deposited || "");
    setState(s); toast(`Dodano wpłatę ${zl(amt)}`);
  } catch (e) { toast(e.message, true); }
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#drawer").hidden) closeChart();
  if (e.key === "Enter" && e.target.matches && e.target.matches(".act[data-sym]")) e.target.click();
  if ((e.key === "ArrowDown" || e.key === "ArrowUp") && paneOn() && !(e.target.matches && e.target.matches("input, select, textarea"))) {
    const els = [...$("#view").querySelectorAll("[data-sym]")];
    if (!els.length) return;
    e.preventDefault();
    const i = els.findIndex((x) => ui.sel && x.dataset.sym === ui.sel.sym), n = Math.min(Math.max((i < 0 ? (e.key === "ArrowDown" ? 0 : els.length - 1) : i + (e.key === "ArrowDown" ? 1 : -1)), 0), els.length - 1);
    selectEl(els[n]); els[n].scrollIntoView({ block: "nearest" });
  }
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

// ------------------------------------------------------------------ wykres miesięczny: panel po prawej / szuflada
const charts = {};
let chartReq = 0, paneReq = 0, paneCur = null;
function entryFor(sym, fallback = null) {
  const r = S.portfolio && S.portfolio.rows.find((x) => x.yahoo === sym);
  return (r && r.open_price) || fallback;
}
function markSel() { for (const el of document.querySelectorAll("#view [data-sym]")) el.classList.toggle("sel", !!ui.sel && el.dataset.sym === ui.sel.sym); }
function selectEl(el) {
  ui.sel = { sym: el.dataset.sym, title: el.dataset.title || "", entry: entryFor(el.dataset.sym, parseFloat(el.dataset.entry) || null) };
  markSel(); loadPane();
}
function syncPane() {
  const on = paneOn(), pb = $("#paneBtn");
  $("#work").classList.toggle("has-pane", on); $("#pane").hidden = !on;
  pb.hidden = !(wideMQ.matches && PANE_VIEWS.includes(view)); pb.setAttribute("aria-pressed", String(ui.paneOpen));
  setTop();
  if (!on) return;
  for (const b of $("#pRange").querySelectorAll("button")) b.setAttribute("aria-pressed", String(+b.dataset.r === ui.range));
  for (const b of $("#pScale").querySelectorAll("button")) b.setAttribute("aria-pressed", String((b.dataset.s === "log") === ui.log));
  markSel();
  if (!ui.sel) {
    const first = $("#view [data-sym]");
    if (first) selectEl(first);
    else { $("#pTitle").textContent = "Wykres miesięczny"; $("#pSub").textContent = "Kliknij spółkę na liście albo wpisz ticker powyżej."; $("#pBody").innerHTML = ""; }
  } else if (!paneCur || paneCur.sym !== ui.sel.sym) loadPane();
  else drawPane();
}
const FRESH_MS = 30 * 60 * 1000;   // w tej sesji świece uznajemy za świeże 30 min; dalej decyduje cache serwera (6 godz., data/charts/)
const cachedChart = (sym) => { const h = charts[sym]; return h && Date.now() - h._at < FRESH_MS ? h : null; };
const inflight = {};   // to samo zapytanie nie leci dwa razy naraz (klik + podgląd w tle)
async function fetchChart(sym, refresh = false) {
  const hit = refresh ? null : cachedChart(sym);
  if (hit) return hit;
  const k = sym + (refresh ? "!" : "");
  if (!inflight[k]) inflight[k] = api("chart?sym=" + encodeURIComponent(sym) + (refresh ? "&refresh=1" : "")).then((D) => { D._at = Date.now(); charts[sym] = D; return D; }).finally(() => { delete inflight[k]; });
  return inflight[k];
}
async function loadPane(refresh = false) {
  const sel = ui.sel, id = ++paneReq;
  paneCur = null;
  $("#pTitle").textContent = sel.sym + (sel.title && sel.title !== sel.sym ? " · " + sel.title : "");
  const hit = refresh ? null : cachedChart(sel.sym);
  if (hit) { paneCur = { sym: sel.sym, D: hit }; drawPane(); prefetchNeighbors(); return; }   // z pamięci: bez migania i bez zapytania
  $("#pSub").textContent = refresh ? "Odświeżam dane z Yahoo…" : "Pobieram świece miesięczne…";
  $("#pBody").innerHTML = `<div class="spinner" aria-label="Ładowanie"></div>`;
  try {
    const D = await fetchChart(sel.sym, refresh);
    if (id !== paneReq) return;
    paneCur = { sym: sel.sym, D }; drawPane(); prefetchNeighbors();
  } catch (e) { delete charts[sel.sym]; if (id === paneReq) { $("#pSub").textContent = ""; $("#pBody").innerHTML = `<div class="alert">${esc(e.message)} — sprawdź ticker (GPW z końcówką .WA).</div>`; } }
}
let prefetching = false;
async function prefetchNeighbors() {   // dociąga w tle następne i poprzednią spółkę z listy, żeby przełączanie strzałkami było natychmiastowe
  if (prefetching || !paneOn() || !ui.sel) return;
  prefetching = true;
  try {
    const syms = [...new Set([...$("#view").querySelectorAll("[data-sym]")].map((e) => e.dataset.sym))], i = syms.indexOf(ui.sel.sym);
    if (i < 0) return;
    for (const s of [syms[i + 1], syms[i + 2], syms[i - 1]].filter(Boolean)) if (!cachedChart(s)) { try { await fetchChart(s); } catch (e) { /* podgląd w tle: błędy pomijamy */ } }
  } finally { prefetching = false; }
}
function drawPane() {
  if (!paneCur || !ui.sel || paneCur.sym !== ui.sel.sym || $("#pane").hidden) return;
  const D = paneCur.D, when = D.cached_at ? new Date(D.cached_at * 1000).toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
  $("#pSub").innerHTML = renderChart($("#pBody"), D, { entry: ui.sel.entry, months: ui.range, log: ui.log }) +
    (when ? ` · <span title="Dane z Yahoo, odświeżane co 6 godzin albo przyciskiem ↻">dane z ${when}${D.stale ? ", nieaktualne (brak sieci)" : ""}</span>` : "");
}
new ResizeObserver(() => drawPane()).observe($("#pBody"));
$("#pRange").addEventListener("click", (e) => { const b = e.target.closest("button[data-r]"); if (!b) return; ui.range = +b.dataset.r; saveUi(); syncPane(); });
$("#pScale").addEventListener("click", (e) => { const b = e.target.closest("button[data-s]"); if (!b) return; ui.log = b.dataset.s === "log"; saveUi(); syncPane(); });
$("#pRefresh").addEventListener("click", () => { if (ui.sel) loadPane(true); });
$("#pClose").addEventListener("click", () => { ui.paneOpen = false; saveUi(); renderView(); });
$("#paneBtn").addEventListener("click", () => { ui.paneOpen = !ui.paneOpen; saveUi(); renderView(); });
$("#pForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const sym = $("#pSym").value.trim().toUpperCase().replace(/\.PL$/, ".WA");
  if (!sym) return;
  ui.sel = { sym, title: "", entry: entryFor(sym) }; markSel(); loadPane();
});

async function openChart(sym, title, entry) {   // szuflada (wąskie okno)
  const d = $("#drawer");
  d.hidden = false;
  $("#chTitle").textContent = `${sym}${title && title !== sym ? " · " + title : ""}`;
  $("#chSub").textContent = "Pobieram świece miesięczne…";
  $("#chBody").innerHTML = `<div class="spinner" aria-label="Ładowanie"></div>`;
  $(".drawer-panel [data-close]").focus();
  const id = ++chartReq;
  try {
    const D = await fetchChart(sym);
    if (id !== chartReq) return;
    $("#chSub").innerHTML = renderChart($("#chBody"), D, { entry, months: ui.range, log: ui.log });
  } catch (e) { delete charts[sym]; if (id === chartReq) { $("#chSub").textContent = ""; $("#chBody").innerHTML = `<div class="alert">${esc(e.message)}</div>`; } }
}
function closeChart() { $("#drawer").hidden = true; chartReq++; }

// słupki OHLC + SMA 10 + wolumen (zielony wzrost / czerwony spadek) ze średnią; rozmiar z kontenera; podpowiedź przy najechaniu; zwraca podtytuł (stan SMA 10)
function renderChart(host, D, o) {
  const n = D.c.length, k0 = Math.max(n - o.months, 0), idx = [];
  for (let i = k0; i < n; i++) idx.push(i);
  const sma = D.c.map((_, i) => (i < 9 ? null : D.c.slice(i - 9, i + 1).reduce((a, b) => a + b, 0) / 10));
  const vsma = D.v.map((_, i) => (i < 9 ? null : D.v.slice(i - 9, i + 1).reduce((a, b) => a + b, 0) / 10));
  const stop = o.entry ? o.entry * (1 - S.rules.stop) : null;
  const W = Math.max(host.clientWidth, 320), H = Math.max(host.clientHeight, 280), mL = 6, mR = o.entry ? 104 : 60, mT = 8, mB = 22, gap = 14;
  const plotH = H - mT - mB, volH = Math.max(Math.round(plotH * 0.22), 48), py0 = mT, py1 = mT + plotH - volH - gap, vy0 = py1 + gap, vy1 = H - mB, px0 = mL, px1 = W - mR;
  const vals = idx.flatMap((i) => [D.h[i], D.l[i]]).concat(idx.map((i) => sma[i]), [o.entry, stop]).filter((v) => v > 0);
  const lo = Math.min(...vals) * 0.96, hi = Math.max(...vals) * 1.04, T = o.log ? Math.log : (x) => x;
  const step = (px1 - px0) / idx.length, X = (j) => px0 + (j + 0.5) * step, Y = (p) => py1 - ((T(p) - T(lo)) / (T(hi) - T(lo))) * (py1 - py0);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Wykres miesięczny">`;
  let ticks = o.log ? niceLog(lo, hi) : niceLin(lo, hi, 5);
  if (ticks.length < 3) ticks = niceLin(lo, hi, 5);
  const marks = [[o.entry, "var(--warn)", "zakup"], [stop, "var(--bad)", "stop"]].filter((m) => m[0]);
  for (const p of ticks) {
    s += `<line x1="${px0}" x2="${px1}" y1="${Y(p)}" y2="${Y(p)}" stroke="var(--grid)"/>`;
    if (!marks.some((m) => Math.abs(Y(m[0]) - Y(p)) < 13)) s += `<text x="${px1 + 6}" y="${Y(p) + 4}" font-size="11.5" fill="var(--muted)">${fmtTick(p)}</text>`;
  }
  const sw = Math.max(Math.min(step * 0.2, 2.4), 1.1), tw = Math.max(step * 0.34, 1.5);
  idx.forEach((i, j) => {
    const x = X(j), live = i === n - 1, col = live ? "var(--muted)" : "var(--bar)", op = D.o[i] || D.c[i];
    s += `<g stroke="${col}" stroke-width="${sw}" opacity="${live ? 0.6 : 1}"><line x1="${x}" x2="${x}" y1="${Y(D.h[i])}" y2="${Y(D.l[i])}"/><line x1="${x - tw}" x2="${x}" y1="${Y(op)}" y2="${Y(op)}"/><line x1="${x}" x2="${x + tw}" y1="${Y(D.c[i])}" y2="${Y(D.c[i])}"/></g>`;
    if (D.d[i].endsWith("-01") || (o.months <= 36 && D.d[i].endsWith("-07"))) s += `<text x="${x}" y="${H - 7}" text-anchor="middle" font-size="11.5" fill="var(--muted)">${D.d[i].endsWith("-01") ? D.d[i].slice(0, 4) : MSHORT[6]}</text>`;
  });
  const sp = idx.map((i, j) => (sma[i] ? `${X(j).toFixed(1)},${Y(sma[i]).toFixed(1)}` : null)).filter(Boolean);
  if (sp.length > 1) s += `<polyline points="${sp.join(" ")}" fill="none" stroke="var(--sma)" stroke-width="2.2"/>`;
  for (const [lvl, col, lab] of marks) s += `<line x1="${px0}" x2="${px1}" y1="${Y(lvl)}" y2="${Y(lvl)}" stroke="${col}" stroke-dasharray="6 4" stroke-width="1.5"/><text x="${px1 + 6}" y="${Y(lvl) + 4}" font-size="11.5" font-weight="650" fill="${col}">${lab} ${num(lvl)}</text>`;
  const vmax = Math.max(...idx.map((i) => D.v[i]), 1);
  idx.forEach((i, j) => {
    const up = D.c[i] >= (i > 0 ? D.c[i - 1] : D.o[i]), hh = (D.v[i] / vmax) * (vy1 - vy0);
    s += `<rect x="${X(j) - step * 0.34}" y="${vy1 - hh}" width="${step * 0.68}" height="${hh}" fill="${up ? "var(--vol-up)" : "var(--vol-dn)"}" opacity="${i === n - 1 ? 0.45 : 0.85}"/>`;
  });
  const vp = idx.map((i, j) => (vsma[i] ? `${X(j).toFixed(1)},${(vy1 - (vsma[i] / vmax) * (vy1 - vy0)).toFixed(1)}` : null)).filter(Boolean);
  if (vp.length > 1) s += `<polyline points="${vp.join(" ")}" fill="none" stroke="var(--warn)" stroke-width="1.6"/>`;
  s += `<text x="${px1 + 6}" y="${vy0 + 10}" font-size="11" fill="var(--muted)">wol.</text><line x1="${px0}" x2="${px1}" y1="${vy1}" y2="${vy1}" stroke="var(--line)"/>
    <line id="chx" x1="0" x2="0" y1="${py0}" y2="${vy1}" stroke="var(--muted)" stroke-dasharray="3 3" visibility="hidden"/><rect id="chhit" x="${px0}" y="${py0}" width="${px1 - px0}" height="${vy1 - py0}" fill="transparent"/></svg><div class="ctip" hidden></div>`;
  host.innerHTML = s;
  const tip = $(".ctip", host), vx = $("#chx", host);
  $("#chhit", host).addEventListener("mousemove", (e) => {
    const r = host.getBoundingClientRect(), j = Math.min(Math.max(Math.floor((e.clientX - r.left - px0) / step), 0), idx.length - 1), i = idx[j], pc = i > 0 ? D.c[i - 1] : null;
    vx.setAttribute("x1", X(j)); vx.setAttribute("x2", X(j)); vx.setAttribute("visibility", "visible");
    tip.innerHTML = `<b>${esc(D.d[i])}</b>${i === n - 1 ? " (w toku)" : ""}<br>O ${num(D.o[i] || D.c[i])} · H ${num(D.h[i])} · L ${num(D.l[i])} · C <b>${num(D.c[i])}</b>${pc ? " (" + pct(D.c[i] / pc - 1) + ")" : ""}<br>SMA 10 ${num(sma[i])}${sma[i] ? " (" + pct(D.c[i] / sma[i] - 1) + ")" : ""} · wol. ${compact(D.v[i])}`;
    tip.hidden = false;
    const tx = X(j) + 14, w = tip.offsetWidth; tip.style.left = (tx + w > host.clientWidth ? X(j) - w - 14 : tx) + "px"; tip.style.top = "10px";
  });
  $("#chhit", host).addEventListener("mouseleave", () => { tip.hidden = true; vx.setAttribute("visibility", "hidden"); });
  const lc = n - 2, c = D.c[lc], m = sma[lc];
  return `Zamknięcie ${esc(D.d[lc])}: <b>${num(c)}</b> · SMA 10 ${num(m)} · ` + (m == null ? "" : c >= m ? `<span class="pill good">nad SMA 10 — trzymaj</span>` : `<span class="pill bad">pod SMA 10 — sprzedaj</span>`) +
    (o.entry ? ` · zakup ${num(o.entry)} · stop ${num(stop)}` : "");
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
window.addEventListener("resize", setTop);
