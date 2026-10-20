"""Synchronizacja: Finviz (lista) → yfinance (tygodniowe 3 lata + miesięczne z całej historii, z pamięci podręcznej) → SEC (fundamenty,
z pamięci podręcznej) → wiersze listy. Funkcje sieciowe można podmienić (testy)."""
import datetime as dt

from . import calc, finviz, prices, sec


def symbol(sym, store, log=print, weekly=prices.weekly, monthly=prices.monthly, fund=sec.update):
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
    row = calc.build_row({"ticker": sym}, w, prices.closed_months(mcache.get(sym)), scache.get(sym))
    store.extra[sym] = (row, w)
    return row, w


def run(store, log=print, fetch_list=finviz.fetch, weekly=prices.weekly, monthly=prices.monthly, fund=sec.update, now=None):
    filters = store.settings.get("filters") or finviz.DEFAULT_FILTERS
    log(f"Finviz: filtr {filters}")
    base, total = fetch_list(filters, log=log)
    if not base:
        raise RuntimeError("Finviz nie zwrócił spółek (blokada albo zły filtr) — lista bez zmian.")
    tickers = [r["ticker"] for r in base]
    log(f"Finviz: {len(tickers)} spółek{f' z {total}' if total and total != len(tickers) else ''}")
    series = weekly(tickers, log=log)
    # fundamenty i całą historię miesięczną pobieramy tylko dla spółek, które przechodzą próg obrotu (reszta i tak odpada)
    liquid = [t for t in tickers if t in series and (calc.turnover(series[t]["c"], series[t]["v"]) or 0) >= calc.MIN_TURNOVER]
    log(f"Obrót ≥ {calc.MIN_TURNOVER / 1e6:.0f} mln $ dziennie: {len(liquid)} spółek")
    mcache, scache = store.cache("monthly"), store.cache("sec")
    monthly(liquid, mcache, log=log)
    store.save_cache("monthly", mcache)
    try:
        fund(liquid, scache, ua=store.settings.get("sec_ua") or sec.UA, log=log)
    except Exception as e:
        log(f"⚠ SEC niedostępny ({e}) — używam zapisanych fundamentów.")
    store.save_cache("sec", scache)
    rows = [calc.build_row(b, series[b["ticker"]], prices.closed_months(mcache.get(b["ticker"])), scache.get(b["ticker"]))
            for b in base if b["ticker"] in series]
    keep = {r["ticker"] for r in rows}
    store.save_scan(rows, {t: s for t, s in series.items() if t in keep}, (now or dt.datetime.now()).isoformat(timespec="minutes"))
    ok = sum(1 for r in rows if r["ok"])
    sig = sum(1 for r in rows if r["ok"] and r["glb_state"] in ("SYGNAŁ", "WYBICIE"))
    log(f"✓ Gotowe: {len(rows)} spółek, warunki spełnia {ok}, sygnał GLB: {sig}")
    return rows
