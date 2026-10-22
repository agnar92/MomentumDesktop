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


def _number(value):
    """Wartość liczbowa z danych Yahoo albo None (obsługa NaN / braków / pól tekstowych)."""
    try:
        number = float(str(value).strip().replace("%", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _revenue_surprise(row):
    """Procentowa niespodzianka przychodów, jeśli źródło dostarczy actual i consensus."""
    explicit = None
    for key in ("Revenue Surprise(%)", "Revenue Surprise (%)"):
        explicit = _number(row.get(key))
        if explicit is not None:
            return round(explicit, 2)
    actual = next((_number(row.get(key)) for key in ("Reported Revenue", "Revenue Actual", "Actual Revenue")
                   if _number(row.get(key)) is not None), None)
    estimate = next((_number(row.get(key)) for key in ("Revenue Estimate", "Estimated Revenue")
                     if _number(row.get(key)) is not None), None)
    if actual is None or estimate is None or estimate == 0:
        return None
    return round((actual - estimate) / abs(estimate) * 100, 2)


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


def _eps_history(frame):
    """Compact quarterly EPS history [[period-end, EPS]], tolerant of yfinance schema changes."""
    if frame is None or getattr(frame, "empty", True):
        return []
    for label in ("Diluted EPS", "Basic EPS", "Normalized Diluted EPS"):
        try:
            if label not in frame.index:
                continue
            vals = []
            for stamp, value in frame.loc[label].items():
                n = _number(value)
                if n is not None:
                    day = stamp.strftime("%Y-%m-%d") if hasattr(stamp, "strftime") else str(stamp)[:10]
                    vals.append([day, round(n, 4)])
            return sorted(vals)[-12:]
        except Exception:
            continue
    return []


def _estimate_rows(frame):
    """Serialize earnings_estimate periods, including next-year EPS growth."""
    if frame is None or getattr(frame, "empty", True):
        return []
    out = []
    for period, row in frame.iterrows():
        item = {"period": str(period)}
        for key in ("numberOfAnalysts", "avg", "low", "high", "yearAgoEps", "growth"):
            value = row.get(key)
            if key == "numberOfAnalysts":
                try:
                    item[key] = int(value) if _number(value) is not None else None
                except (TypeError, ValueError, OverflowError):
                    item[key] = None
            else:
                n = _number(value)
                if key == "growth" and n is not None and "%" not in str(value):
                    n *= 100
                item[key] = round(n, 4) if n is not None else None
        out.append(item)
    return out


def fetch(t):
    """-> niespodzianki EPS/przychodów, rewizja EPS i upside do średniego celu analityków."""
    tk = _yf().Ticker(t)
    surp, revenue_surp, earnings_dates = [], [], []
    try:
        # Większy zakres, aby znaczniki E objęły historię widoczną na wykresie tygodniowym.
        d = tk.get_earnings_dates(limit=32)
        if d is not None and len(d):
            today = dt.date.today().isoformat()
            for ts, r in d.sort_index().iterrows():
                est, rep, s = r.get("EPS Estimate"), r.get("Reported EPS"), r.get("Surprise(%)")
                report_date = ts.strftime("%Y-%m-%d")
                # Datę raportu zapisujemy także wtedy, gdy Yahoo nie podało konsensusu lub niespodzianki EPS.
                rev_surp = _revenue_surprise(r)
                if (_number(rep) is not None or _number(r.get("Reported Revenue")) is not None or
                        _number(r.get("Revenue Actual")) is not None or _number(r.get("Actual Revenue")) is not None) and report_date <= today:
                    earnings_dates.append(report_date)
                if all(_number(x) is not None for x in (est, rep, s)) and abs(float(est)) >= 0.01:
                    surp.append([report_date, round(float(s), 2)])
                if rev_surp is not None and report_date <= today:
                    revenue_surp.append([report_date, rev_surp])
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
    eps_q, eps_est = [], []
    try:
        eps_q = _eps_history(tk.quarterly_income_stmt)
    except Exception:
        pass
    try:
        eps_est = _estimate_rows(tk.earnings_estimate)
    except Exception:
        pass
    return {"surp": surp[-24:], "revenue_surp": revenue_surp[-24:], "rev90": rev90,
            "upside": upside, "earnings_dates": sorted(set(earnings_dates))[-24:],
            "eps_q": eps_q, "eps_est": eps_est}


def update(tickers, cache, log=print, today=None, pause=0.1, progress=None, fetch_one=None):
    """Uzupełnia `cache` dla spółek bez świeżych danych (co FRESH_DAYS dni); rewizję dopisuje do historii. -> lista pobranych."""
    today = today or dt.date.today()
    fetch_one = fetch_one or fetch
    # Odśwież również stare wpisy, w których nie zapisywaliśmy jeszcze pola upside.
    # Odśwież stare wpisy, w których nie zapisaliśmy jeszcze historii EPS i prognozy wzrostu +1y.
    todo = [t for t in tickers if not (
        cache.get(t) and all(k in cache[t] for k in ("upside", "eps_q", "eps_est", "revenue_surp"))
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
