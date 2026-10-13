import sys
import types

import numpy as np
import pandas as pd
import pytest

from desktop import adhoc, store


def synthetic(n=420, seed=1, last="2026-10-09"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=last, periods=n)
    close = 50 * np.exp(np.cumsum(rng.normal(0.001, 0.015, n)))
    return pd.DataFrame({"Open": close * 0.998, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": rng.integers(1_000_000, 5_000_000, n)}, index=idx)


def test_normalize_symbols():
    assert adhoc.normalize("  nvda ") == "NVDA" and adhoc.normalize("brk-b") == "BRK-B" and adhoc.normalize("^gspc") == "^GSPC"
    assert adhoc.normalize("") is None and adhoc.normalize("to nie symbol!!!") is None and adhoc.normalize("a" * 30) is None


def test_build_aligns_to_scanner_axes_and_own_axes():
    df = synthetic()
    s = store.Store.__new__(store.Store)
    data = adhoc.build("XYZ", df)                                              # bez osi skanera: własne
    assert len(data["weeks"]) == len(data["weekly"]["c"]) <= adhoc.N_WEEKS and len(data["dates"]) == len(data["daily"]["c"])
    assert data["last_date"] == "2026-10-09" and data["price"] == pytest.approx(float(df["Close"].iloc[-1]))
    weeks = data["weeks"][-60:]
    dates = data["dates"][-100:]
    data2 = adhoc.build("XYZ", df, weeks, dates)                               # na osiach skanera
    assert data2["weeks"] == weeks and len(data2["weekly"]["c"]) == 60 and data2["dates"] == dates and len(data2["daily"]["c"]) == 100
    assert data2["weekly"]["sma10"][-1] is not None and data2["daily"]["v"][-1] == int(df["Volume"].iloc[-1] / 1000)
    with pytest.raises(ValueError):
        adhoc.build("XYZ", df.head(10))
    del s


def test_store_adhoc_row_series_and_tf(tmp_path):
    s = store.Store(tmp_path / "d")
    data = adhoc.build("XYZ", synthetic(), s.weeks, s.charts_d.get("dates"))
    row = s.add_adhoc("XYZ", data, "Xyz Corp")
    assert s.row("XYZ") is row and row["company"] == "Xyz Corp" and row["darvas_w"] and row["darvas_d"] and "cs_letters" in row
    full, dates, spx, smas = s.series("XYZ", "W")
    assert full is data["weekly"] and len(spx) == len(dates)                    # oś zgodna ze skanerem -> jest linia S&P
    full, dates, spx, smas = s.series("XYZ", "D")
    assert [n for _, n in smas] == [10, 50, 200] and len(full["c"]) == len(dates)
    s.set_tf("D")
    assert row["darvas"] == row["darvas_d"]
    assert all(r["ticker"] != "XYZ" for r in s.rows)                            # nie wchodzi na listę skanera
    s2 = store.Store(tmp_path / "e", seed=False)
    d2 = adhoc.build("QQQQ", synthetic(seed=3))
    s2.add_adhoc("QQQQ", d2)
    assert s2.series("QQQQ", "W")[2] is None and s2.series("QQQQ", "W")[1] == d2["weeks"]   # skaner bez danych: własna oś, bez S&P


def test_fetch_uses_engine_download_and_reports_missing(monkeypatch):
    df = synthetic()
    eng = types.SimpleNamespace(download_prices=lambda syms: {syms[0]: df} if syms == ["OK"] else {}, drop_incomplete_bar=lambda d, now: d,
                                weekly_ohlcv=None, build_chart=None)
    from desktop import sync
    sync._engine_path()
    import watchlist
    eng.weekly_ohlcv, eng.build_chart = watchlist.weekly_ohlcv, watchlist.build_chart
    monkeypatch.setattr(adhoc, "_engine", lambda: eng)
    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = lambda s: types.SimpleNamespace(get_info=lambda: {"shortName": "Ok Inc"})
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    data, name = adhoc.fetch("OK")
    assert name == "Ok Inc" and data["last_date"] == "2026-10-09"
    with pytest.raises(ValueError, match="Nie znalazłem"):
        adhoc.fetch("NOPE")
