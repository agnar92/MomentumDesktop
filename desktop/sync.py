"""Synchronizacja: Finviz (lista) → yfinance (tygodniowe: tylko nowe tygodnie dla spółek już pobranych; miesięczne High: tylko nowe
miesiące) → SEC (fundamenty, z pamięci podręcznej) → wiersze listy. Funkcje sieciowe można podmienić (testy).
`progress(ułamek 0–1, opis etapu)` dostaje postęp całości (pasek na dole okna)."""
import datetime as dt

from . import calc, estimates, finviz, prices, sec

BENCH = "SPY"   # RS Line (jak Deepvue) i siła względna 52 tyg.

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


def sector_scan(store, sc, log, fetch_list, weekly, progress):
    """Skaner sektorowy: RS sektorów (ETF / SPY nad SMA 52 tyg.) -> N najsilniejszych -> po jednym zapytaniu Finviz na sektor (sektor + wspólny filtr).
    -> (lista spółek bez powtórzeń, suma z Finviz, ranking sektorów [{etf, sector, pct, selected}])."""
    etfs = [e for e, _, _ in calc.SECTOR_ETFS]
    ser = weekly(etfs + [BENCH], log=log, cache=store.series, progress=None)
    ranked = calc.sector_rs({e: ser[e] for e in etfs if e in ser}, ser.get(BENCH) or {})
    top = calc.top_sectors(ranked, int(sc["top_sectors"]))
    names = {x["etf"] for x in top}
    log("Sektory (RS = ETF / SPY, % nad SMA 52 tyg.): " + ", ".join(f"{x['etf']} {x['pct']:+.1f} %" + (" ✓" if x["etf"] in names else "") for x in ranked))
    if not top:
        raise RuntimeError("Żaden sektor nie ma RS nad SMA 52 tyg. (albo brak danych ETF) — lista bez zmian.")
    rows, seen, total = [], set(), 0
    for k, sector in enumerate(top):
        flt = calc.sector_filter(sc["filters"], sector)
        log(f"Finviz [{sector['sector']}]: filtr {flt}")
        part, tot = fetch_list(flt, max_tickers=sc["max_tickers"], log=log, progress=None)
        total += tot or len(part)
        for r in part:
            if r["ticker"] not in seen:
                seen.add(r["ticker"])
                rows.append({**r, "sector": r.get("sector") or sector["sector"]})
    info = [{"etf": x["etf"], "sector": x["sector"], "pct": round(x["pct"], 2), "selected": x["etf"] in names} for x in ranked]
    return rows, total, info


def cached_symbol(sym, store):
    """Buduje wiersz dla tickera, którego świece są już w lokalnym cache; nie wykonuje zapytań sieciowych."""
    w = store.weekly(sym)
    if not w or not w.get("c"):
        return None

    mcache, scache, ecache = store.cache("monthly"), store.cache("sec"), store.cache("estimates")
    spy = w if sym == BENCH else (store.series.get(BENCH) or (store.extra.get(BENCH) or (None, None))[1])
    existing = store.row(sym) or {}
    base = {k: existing[k] for k in ("ticker", "company", "sector", "sector_rs", "market_cap", "peg", "forward_pe", "dividend_yield") if k in existing}
    base["ticker"] = sym
    row = calc.build_row(base, w, prices.monthly_highs(mcache.get(sym)), scache.get(sym), spy, ecache.get(sym),
                         conditions=store.settings.get("strategy_conditions"))
    calc.assign_eps_rating([row], pool=store.rows)

    store.extra[sym] = (row, w)
    return row, w


def symbol(sym, store, log=print, weekly=prices.weekly, monthly=prices.monthly, fund=sec.update, est=estimates.update):
    """Dane jednej dowolnej spółki (Ctrl+Space): te same obliczenia co w skanie. -> (wiersz, świece) albo wyjątek."""
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
    base = {k: existing[k] for k in ("ticker", "company", "sector", "sector_rs", "market_cap", "peg", "forward_pe", "dividend_yield") if k in existing}
    base["ticker"] = sym
    row = calc.build_row(base, w, prices.monthly_highs(mcache.get(sym)), scache.get(sym), spy, ecache.get(sym),
                         conditions=store.settings.get("strategy_conditions"))
    calc.assign_eps_rating([row], pool=store.rows)
    store.extra[sym] = (row, w)
    return row, w


def run(store, log=print, fetch_list=finviz.fetch, weekly=prices.weekly, monthly=prices.monthly, fund=sec.update, now=None, progress=None, est=estimates.update):
    sc = store.scanner
    sectors = None
    if sc.get("top_sectors"):
        fp = stage_progress(progress, 0)
        base, total, sectors = sector_scan(store, sc, log, fetch_list, weekly, None)
        fp(1, 1)
    else:
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
    for t, r in tracked_rows.items():
        store.extra[t] = (r, series[t])
    by_sector = {x["sector"]: x["pct"] for x in sectors or []}
    for r in rows + list(tracked_rows.values()):
        r["sector_rs"] = by_sector.get(r.get("sector"))   # RS sektora spółki (% nad SMA 52 tyg.) — tylko w skanerze sektorowym
    calc.assign_eps_rating(rows + list(tracked_rows.values()))   # EPS Rating 1–99: percentyl wśród spółek tej listy
    keep = {r["ticker"] for r in rows} | set(tracked_rows) | {BENCH} | ({e for e, _, _ in calc.SECTOR_ETFS} if sectors else set())
    store.save_scan(rows, {t: s for t, s in series.items() if t in keep}, (now or dt.datetime.now()).isoformat(timespec="minutes"), sectors=sectors)
    ok = sum(1 for r in rows if r["ok"])
    sig = sum(1 for r in rows if r["ok"] and r["glb_state"] in ("SYGNAŁ", "WYBICIE"))
    if progress:
        progress(1.0, "Gotowe")
    log(f"✓ Gotowe: {len(rows)} spółek, warunki spełnia {ok}, sygnał GLB: {sig}")
    return rows
