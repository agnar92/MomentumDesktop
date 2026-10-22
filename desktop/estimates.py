"""Prognozy analityków z yfinance (ten sam plik w Momentum Desktop): niespodzianki EPS (konsensus vs wynik, kolejne raporty) i rewizja konsensusu EPS
na przyszły rok obrotowy (dziś vs 90 dni temu). Backtest 2015–2026 (niespodzianki od 2014 r.): 2 ostatnie raporty powyżej konsensusu = +5,8 pp rocznie
w obecnej regule. Rewizji nie da się sprawdzić wstecz (yfinance podaje tylko stan dziś) — zapisujemy ją co tydzień w `hist`, żeby kiedyś to przetestować.
Cache zawiera też daty publikacji raportów `earnings_dates`, używane do oznaczeń E na wykresie; odświeżany co FRESH_DAYS dni."""
import datetime as dt
import math
import time

FRESH_DAYS = 7
KEEP_HIST = 104   # tygodni historii rewizji


def _yf():
    import yfinance as yf
    return yf


def analyst_upside(targets):
    """Upside (%) od bieżącej ceny do średniego celu analityków, jeśli obie wartości istnieją."""
    if not isinstance(targets, dict):
        return None
    try:
        current, mean = float(targets.get("current")), float(targets.get("mean"))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(current) and math.isfinite(mean)) or current <= 0 or mean <= 0:
        return None
    return round((mean / current - 1) * 100, 2)


def fetch(t):
    """-> niespodzianki EPS, daty wyników, rewizja EPS i upside do średniego celu analityków."""
    tk = _yf().Ticker(t)
    surp, earnings_dates = [], []
    try:
        # Większy zakres, aby znaczniki E objęły historię widoczną na wykresie tygodniowym.
        d = tk.get_earnings_dates(limit=32)
        if d is not None and len(d):
            today = dt.date.today().isoformat()
            for ts, r in d.sort_index().iterrows():
                est, rep, s = r.get("EPS Estimate"), r.get("Reported EPS"), r.get("Surprise(%)")
                report_date = ts.strftime("%Y-%m-%d")
                # Datę raportu zapisujemy także wtedy, gdy Yahoo nie podało konsensusu lub niespodzianki EPS.
                if isinstance(rep, (int, float)) and math.isfinite(rep) and report_date <= today:
                    earnings_dates.append(report_date)
                if all(isinstance(x, (int, float)) and math.isfinite(x) for x in (est, rep, s)) and abs(est) >= 0.01:
                    surp.append([report_date, round(float(s), 2)])
    except Exception:   # brak kalendarza wyników (ETF, spółka zagraniczna) — bez niespodzianek
        pass
    upside = None
    try:
        upside = analyst_upside(tk.get_analyst_price_targets())
    except Exception:   # brak pokrycia analitycznego nie blokuje pobrania reszty danych
        pass
    rev90 = None
    try:
        tr = tk.eps_trend
        if tr is not None and "+1y" in tr.index:
            cur, old = tr.loc["+1y", "current"], tr.loc["+1y", "90daysAgo"]
            if math.isfinite(cur) and math.isfinite(old) and old > 0:
                rev90 = round((cur / old - 1) * 100, 2)
    except Exception:
        pass
    return {"surp": surp[-8:], "rev90": rev90, "upside": upside,
            "earnings_dates": sorted(set(earnings_dates))[-24:]}


def update(tickers, cache, log=print, today=None, pause=0.1, progress=None, fetch_one=None):
    """Uzupełnia `cache` dla spółek bez świeżych danych (co FRESH_DAYS dni); rewizję dopisuje do historii. -> lista pobranych."""
    today = today or dt.date.today()
    fetch_one = fetch_one or fetch
    # Odśwież również stare wpisy, w których nie zapisywaliśmy jeszcze pola upside.
    todo = [t for t in tickers if not (
        cache.get(t) and "upside" in cache[t]
        and (today - dt.date.fromisoformat(cache[t]["at"])).days < FRESH_DAYS
    )]
    done = []
    for n, t in enumerate(todo, 1):
        try:
            e = fetch_one(t)
        except Exception as ex:   # pojedyncza spółka bez danych nie przerywa odświeżenia; zostają poprzednie
            log(f"prognozy: {t} — {ex}")
            continue
        hist = (cache.get(t) or {}).get("hist", [])
        if e.get("rev90") is not None:
            hist = (hist + [[today.isoformat(), e["rev90"]]])[-KEEP_HIST:]
        cache[t] = {"at": today.isoformat(), **e, "hist": hist}
        done.append(t)
        if progress:
            progress(n, len(todo))
        if n % 50 == 0 or n == len(todo):
            log(f"yfinance prognozy EPS: {n}/{len(todo)}")
        time.sleep(pause)
    return done
