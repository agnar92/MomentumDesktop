"""Wykres dowolnego tickera spoza skanera: pobranie z yfinance na żądanie i zbudowanie serii (tygodniowej i dziennej) w tym samym formacie
co dane skanera, więc ten sam wykres, Dar-Card, boxy, alerty i flagi działają bez żadnych zmian."""
import re

from . import daily

SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-^=]{0,14}$")
N_WEEKS = 312


def normalize(text):
    """'  nvda ' -> 'NVDA'; zwraca None, gdy to nie wygląda na symbol giełdowy."""
    s = (text or "").strip().upper().replace(" ", "")
    return s if SYMBOL_RE.match(s) else None


def _engine():
    from . import sync
    sync._engine_path()
    import watchlist
    return watchlist


def build(symbol, df, weeks=None, dates=None, now=None):
    """DataFrame z yfinance (Open, High, Low, Close, Volume) -> {weekly, weeks, daily, dates, price, last_date}.
    weeks / dates = osie czasu skanera (żeby linia S&P i okna się zgadzały); gdy ich brak, wyznaczamy własne."""
    import pandas as pd
    wl = _engine()
    if now is not None:
        df = wl.drop_incomplete_bar(df, now)
    if df is None or len(df) < 30:
        raise ValueError(f"Za mało danych dla {symbol} ({0 if df is None else len(df)} sesji).")
    last = pd.DatetimeIndex(df.index).tz_localize(None).normalize()[-1] if getattr(df.index, "tz", None) is not None else pd.DatetimeIndex(df.index).normalize()[-1]
    wk = wl.weekly_ohlcv(df, last)
    wlist = list(weeks) if weeks else [d.strftime("%Y-%m-%d") for d in wk.index[-N_WEEKS:]]
    weekly = wl.build_chart(wk.tail(N_WEEKS + 80), wlist)
    idx_d = pd.DatetimeIndex(dates) if dates else pd.DatetimeIndex(pd.DatetimeIndex(df.index).tz_localize(None) if df.index.tz is not None else df.index)[-daily.KEEP:]
    dlist = list(dates) if dates else [d.strftime("%Y-%m-%d") for d in idx_d]
    return {"weekly": weekly, "weeks": wlist, "daily": daily.align_frame(df, idx_d), "dates": dlist,
            "price": float(df["Close"].iloc[-1]), "last_date": last.strftime("%Y-%m-%d")}


def fetch(symbol, weeks=None, dates=None):
    """Pobiera symbol z yfinance (silnik Momentum: auto_adjust, 10 lat) i buduje dane; zwraca (dane, nazwa spółki albo None)."""
    wl = _engine()
    frames = wl.download_prices([symbol])
    df = frames.get(symbol)
    if df is None or not len(df):
        raise ValueError(f"Nie znalazłem notowań dla „{symbol}” (sprawdź symbol, np. BRK-B zamiast BRK.B).")
    name = None
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).get_info()
        name = info.get("shortName") or info.get("longName")
    except Exception:
        pass
    import pandas as pd
    return build(symbol, df, weeks, dates, now=pd.Timestamp.now(tz="UTC")), name
