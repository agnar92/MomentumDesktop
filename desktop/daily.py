"""Dane dzienne do wykresów: ostatnie ~2 lata sesji każdej spółki wyrównane do wspólnej osi dat (silnik Momentum trzyma tylko wykresy
tygodniowe, więc dzienne budujemy z tej samej migawki cen, bez dodatkowego pobierania)."""
import math

KEEP = 504   # ~2 lata sesji (SMA200 ma się z czego policzyć na początku okna)


def _r(v, d=2):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), d)


def build_daily(frames, benchmark=None, keep=KEEP):
    """frames: {ticker: DataFrame[Open, High, Low, Close, Volume]}; benchmark: DataFrame S&P 500 (opcjonalnie).
    -> {"dates": [...], "spx": [...], "stocks": {T: {o, h, l, c, v (tys.)}}} (None tam, gdzie spółka nie handlowała)."""
    import pandas as pd
    idx = None
    if benchmark is not None and len(benchmark):
        idx = pd.DatetimeIndex(benchmark.index).tz_localize(None) if benchmark.index.tz is not None else pd.DatetimeIndex(benchmark.index)
    if idx is None:
        parts = [pd.DatetimeIndex(f.index).tz_localize(None) if f.index.tz is not None else pd.DatetimeIndex(f.index) for f in frames.values()]
        idx = parts[0].union_many(parts[1:]) if len(parts) > 1 else (parts[0] if parts else pd.DatetimeIndex([]))
    # oś = sesje benchmarku, ale tylko do ostatniej sesji, na której handlowała jakakolwiek spółka
    last = max((f.index.max() for f in frames.values()), default=None)
    if last is not None:
        idx = idx[idx <= pd.Timestamp(last).tz_localize(None)]
    idx = idx.sort_values()[-keep:]
    out = {"dates": [d.strftime("%Y-%m-%d") for d in idx], "spx": [], "stocks": {}}
    if benchmark is not None and len(benchmark):
        b = benchmark["Close"].copy()
        b.index = pd.DatetimeIndex(b.index).tz_localize(None) if b.index.tz is not None else pd.DatetimeIndex(b.index)
        out["spx"] = [_r(v) for v in b.reindex(idx).values]
    for t, df in frames.items():
        d = df.copy()
        d.index = pd.DatetimeIndex(d.index).tz_localize(None) if d.index.tz is not None else pd.DatetimeIndex(d.index)
        d = d[~d.index.duplicated()].reindex(idx)
        out["stocks"][t] = {"o": [_r(v) for v in d["Open"].values], "h": [_r(v) for v in d["High"].values],
                            "l": [_r(v) for v in d["Low"].values], "c": [_r(v) for v in d["Close"].values],
                            "v": [None if math.isnan(v) else int(v / 1000) for v in d["Volume"].values]}
    return out


def sma(values, n):
    """Prosta średnia krocząca (None, dopóki nie ma n kolejnych wartości)."""
    out, win, s = [None] * len(values), [], 0.0
    for i, v in enumerate(values):
        if v is None:
            win, s = [], 0.0
            continue
        win.append(v)
        s += v
        if len(win) > n:
            s -= win.pop(0)
        if len(win) == n:
            out[i] = s / n
    return out
