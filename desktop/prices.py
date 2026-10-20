"""Ceny z yfinance — tylko dwa zapytania na spółkę:
  - tygodniowe świece z ostatnich 3 lat (wykres, średnie, MACD, wolumen, obrót),
  - miesięczne zamknięcia z całej historii (Green Line). Zakończone miesiące się nie zmieniają, więc trzymamy je w pamięci podręcznej
    i pobieramy ponownie dopiero po zamknięciu kolejnego miesiąca."""
import datetime as dt
import math

WEEKLY_PERIOD = "3y"
BATCH = 100


def _yf():
    import yfinance as yf
    return yf


def _frames(df, tickers):
    """Wynik yf.download (jeden albo wiele tickerów) -> {ticker: DataFrame}."""
    if df is None or getattr(df, "empty", True):
        return {}
    if len(tickers) == 1 and "Close" in df.columns:
        return {tickers[0]: df}
    out = {}
    for t in tickers:
        try:
            out[t] = df[t]
        except KeyError:
            continue
    return out


def _clean(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 4)


def weekly(tickers, log=print, period=WEEKLY_PERIOD):
    """-> {ticker: {d: [daty], o, h, l, c, v}} (tydzień = data poniedziałku jak w Yahoo; ostatni tydzień może być w toku)."""
    out = {}
    for i in range(0, len(tickers), BATCH):
        part = tickers[i:i + BATCH]
        df = _yf().download(part, period=period, interval="1wk", auto_adjust=True, group_by="ticker", progress=False, threads=True)
        for t, f in _frames(df, part).items():
            f = f.dropna(subset=["Close"])
            if len(f) < 10:
                continue
            out[t] = {"d": [d.strftime("%Y-%m-%d") for d in f.index], **{k: [_clean(x) for x in f[col]] for k, col in
                                                                         (("o", "Open"), ("h", "High"), ("l", "Low"), ("c", "Close"), ("v", "Volume"))}}
        log(f"yfinance (tygodniowe 3 lata): {min(i + BATCH, len(tickers))}/{len(tickers)}")
    return out


def last_closed_month(today=None):
    today = today or dt.date.today()
    first = today.replace(day=1)
    return (first - dt.timedelta(days=1)).strftime("%Y-%m")


def monthly(tickers, cache, log=print, today=None):
    """Uzupełnia `cache` {ticker: {"m": [[YYYY-MM, close]...], "upto": YYYY-MM}} o miesięczne zamknięcia z całej historii (tylko ZAMKNIĘTE miesiące).
    Pobiera tylko spółki, których cache nie sięga ostatniego zamkniętego miesiąca. -> lista pobranych tickerów."""
    need_upto = last_closed_month(today)
    todo = [t for t in tickers if (cache.get(t) or {}).get("upto") != need_upto]
    for i in range(0, len(todo), BATCH):
        part = todo[i:i + BATCH]
        df = _yf().download(part, period="max", interval="1mo", auto_adjust=True, group_by="ticker", progress=False, threads=True)
        for t, f in _frames(df, part).items():
            s = f["Close"].dropna()
            rows = [[d.strftime("%Y-%m"), round(float(v), 4)] for d, v in s.items() if d.strftime("%Y-%m") <= need_upto]
            if rows:
                cache[t] = {"m": rows, "upto": need_upto}
        log(f"yfinance (miesięczne, cała historia): {min(i + BATCH, len(todo))}/{len(todo)}")
    return todo


def closed_months(entry):
    return [c for _, c in (entry or {}).get("m", [])]
