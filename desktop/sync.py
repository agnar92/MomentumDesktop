"""Synchronizacja: Finviz (lista) → yfinance (tygodniowe: tylko nowe tygodnie dla spółek już pobranych; miesięczne High: tylko nowe
miesiące) → SEC (fundamenty, z pamięci podręcznej) → wiersze listy. Funkcje sieciowe można podmienić (testy).
`progress(ułamek 0–1, opis etapu)` dostaje postęp całości (pasek na dole okna)."""
import datetime as dt

from . import calc, estimates, finviz, prices, sec

BENCH = "SPY"   # S&P 500 nad wykresem (jak w IBD) i siła względna 52 tyg.

# etapy i ich udział w pasku postępu (SEC trwa najdłużej: jedno zapytanie na spółkę)
STAGES = (("Finviz — lista spółek", 0.15), ("yfinance — tygodniowe", 0.25), ("yfinance — miesięczne High", 0.2), ("SEC — fundamenty", 0.4))


def stage_progress(progress, k):
    """-> funkcja (zrobione, wszystkie) dla etapu k, przeliczająca na postęp całości."""
    start = sum(w for _, w in STAGES[:k])
    name, weight = STAGES[k]

    def f(done, total):
        if progress:
            frac = done / total if total else 1.0
            progress(start + weight * min(1.0, frac), f"Etap {k + 1}/{len(STAGES)}: {name} {done}/{total}")
    if progress:
        progress(start, f"Etap {k + 1}/{len(STAGES)}: {name}")
    return f


def symbol(sym, store, log=print, weekly=prices.weekly, monthly=prices.monthly, fund=sec.update, est=estimates.update):
    """Dane jednej dowolnej spółki (Ctrl+K): te same obliczenia co w skanie. -> (wiersz, świece) albo wyjątek."""
    w = weekly([sym], log=log).get(sym)
    if not w:
        raise ValueError(f"Brak danych tygodniowych dla {sym} w yfinance.")
    mcache, scache = store.cache("monthly"), store.cache("sec")
    monthly([sym], mcache, log=log)
    try:
        fund([sym], scache, ua=store.settings.get("sec_ua") or sec.UA, log=log)
    except Exception as e:   # brak fundamentów nie blokuje wykresu (np. ETF, indeks, spółka zagraniczna)
        log(f"SEC: {e}")
    store.save_cache("monthly", mcache)
    store.save_cache("sec", scache)
    ecache = store.cache("estimates")
    try:
        est([sym], ecache, log=log)
    except Exception as e:
        log(f"prognozy: {e}")
    store.save_cache("estimates", ecache)
    spy = w if sym == BENCH else (store.series.get(BENCH) or (store.extra.get(BENCH) or (None, None))[1])
    existing = store.row(sym) or {}
    base = {k: existing[k] for k in ("ticker", "company", "sector", "market_cap") if k in existing}
    base["ticker"] = sym
    row = calc.build_row(base, w, prices.monthly_highs(mcache.get(sym)), scache.get(sym), spy, ecache.get(sym),
                         conditions=store.settings.get("strategy_conditions"))
    store.extra[sym] = (row, w)
    return row, w


def run(store, log=print, fetch_list=finviz.fetch, weekly=prices.weekly, monthly=prices.monthly, fund=sec.update, now=None, progress=None, daily=prices.daily,
        est=estimates.update):
    sc = store.scanner
    log(f"Finviz [{sc['name']}]: filtr {sc['filters']}")
    base, total = fetch_list(sc["filters"], max_tickers=sc["max_tickers"], log=log, progress=stage_progress(progress, 0))
    if not base:
        raise RuntimeError("Finviz nie zwrócił spółek (blokada albo zły filtr) — lista bez zmian.")
    tickers = [r["ticker"] for r in base]
    tracked = sorted((set(store.alerts.get("pos", {})) | set(store.alerts.get("watch", {}))) - set(tickers))
    all_tickers = tickers + tracked
    log(f"Finviz: {len(tickers)} spółek{f' z {total}' if total and total != len(tickers) else ''}; pozycje/obserwowane poza skanerem: {len(tracked)}")
    # Pozycje i obserwowane odświeżamy niezależnie od tego, czy należą do aktualnego skanera.
    series = weekly(all_tickers + [x for x in (BENCH,) if x not in all_tickers], log=log, cache=store.series, progress=stage_progress(progress, 1))
    # Miesięczne High (Green Line), fundamenty i prognozy także dla pozycji/obserwowanych spoza skanera.
    liquid = [t for t in all_tickers if t in series]
    mcache, scache = store.cache("monthly"), store.cache("sec")
    monthly(liquid, mcache, log=log, progress=stage_progress(progress, 2))
    store.save_cache("monthly", mcache)
    try:
        fund(liquid, scache, ua=store.settings.get("sec_ua") or sec.UA, log=log, progress=stage_progress(progress, 3))
    except Exception as e:
        log(f"⚠ SEC niedostępny ({e}) — używam zapisanych fundamentów.")
    store.save_cache("sec", scache)
    ecache = store.cache("estimates")   # niespodzianki EPS i rewizja prognoz (yfinance), co 7 dni
    try:
        est(liquid, ecache, log=log)
    except Exception as e:
        log(f"⚠ prognozy EPS niedostępne ({e}) — używam zapisanych.")
    store.save_cache("estimates", ecache)
    rows = [calc.build_row(b, series[b["ticker"]], prices.monthly_highs(mcache.get(b["ticker"])), scache.get(b["ticker"]), series.get(BENCH), ecache.get(b["ticker"]),
                            conditions=store.settings.get("strategy_conditions"))
            for b in base if b["ticker"] in series]
    # Wiersze pomocnicze nie trafiają do listy skanera, ale zasilają panel pozycji/obserwowanych.
    tracked_rows = {}
    for t in tracked:
        if t in series:
            tracked_rows[t] = calc.build_row({"ticker": t}, series[t], prices.monthly_highs(mcache.get(t)), scache.get(t), series.get(BENCH), ecache.get(t),
                                              conditions=store.settings.get("strategy_conditions"))
    try:   # Dwieście pięćdziesiąt sesji do C/C[250], a także RVol i Blue Dot.
        dser = daily(liquid, log=log, period="2y") if liquid else {}
    except Exception as e:
        log(f"⚠ dzienne (RVol/C/C[250]) niedostępne ({e})")
        dser = {}
    for r in rows + list(tracked_rows.values()):
        sd = dser.get(r["ticker"])
        r["rvol_d"] = calc.rel_volume(sd["v"], calc.RVOL_D) if sd else None
        closes = sd.get("c", []) if sd else []
        # C/C[max]: use the oldest available close when fewer than 250 prior sessions exist.
        r["cc250"] = closes[-1] / closes[max(0, len(closes) - 251)] if len(closes) >= 2 and closes[max(0, len(closes) - 251)] else None
        bd = calc.fresh_blue_dot(sd, r.get("glb")) if r.get("glb_state") == "NAD" else None
        if bd:   # > 10 % nad linią i nie tydzień przebicia: wejście po Blue Dot na dziennym
            r["glb_state"], r["bdot"] = "BLUE DOT", bd
    for t, r in tracked_rows.items():
        store.extra[t] = (r, series[t])
    keep = {r["ticker"] for r in rows} | set(tracked_rows) | {BENCH}
    store.save_scan(rows, {t: s for t, s in series.items() if t in keep}, (now or dt.datetime.now()).isoformat(timespec="minutes"))
    ok = sum(1 for r in rows if r["ok"])
    sig = sum(1 for r in rows if r["ok"] and r["glb_state"] in ("SYGNAŁ", "WYBICIE"))
    if progress:
        progress(1.0, "Gotowe")
    log(f"✓ Gotowe: {len(rows)} spółek, warunki spełnia {ok}, sygnał GLB: {sig}")
    return rows
