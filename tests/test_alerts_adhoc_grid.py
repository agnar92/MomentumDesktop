import sys
import types

import numpy as np
import pandas as pd
import pytest

from desktop import adhoc, alerts, charts, grid, store


# ---------- alerty ----------

def test_infer_direction_and_describe():
    assert alerts.infer_direction(110, 100) == "above" and alerts.infer_direction(90, 100) == "below" and alerts.infer_direction(100, 100) == "above"
    a = {"dir": "below", "price": 90.0, "note": "stop", "triggered_on": "2026-10-09", "triggered_close": 88.5}
    assert alerts.Alerts.describe(a) == "alert 90.00 ↓ poniżej — przebity 2026-10-09 (zamknięcie 88.50)   „stop”"
    assert alerts.Alerts.describe({"dir": "above", "price": 120.0}) == "alert 120.00 ↑ powyżej"


def test_alerts_crud_persist_and_evaluate(tmp_path):
    al = alerts.Alerts(tmp_path)
    up = al.add("nvda", 110, "above", "wybicie", ref_date="2026-10-02")
    dn = al.add("NVDA", 90, "below", ref_date="2026-10-02")
    other = al.add("AMD", 50, "above", ref_date="2026-10-02")
    assert alerts.Alerts(tmp_path).items[0]["ticker"] == "NVDA" and len(al.for_ticker("NVDA")) == 2
    dates = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]
    hi = [120, 120, 105, 111, 100]      # 10-01 / 10-02 sprzed alertu: nie liczą się (ref_date = 2026-10-02)
    lo = [80, 80, 95, 92, 91]
    cl = [100, 100, 100, 108, 95]
    hit = al.evaluate(lambda t: (dates, hi, lo, cl) if t == "NVDA" else None, tickers={"NVDA", "AMD"})
    assert [a["id"] for a in hit] == [up["id"]]                                   # „powyżej 110” przebite 10-06 (High 111); „poniżej 90” nie (Low 91)
    assert up["active"] is False and up["triggered_on"] == "2026-10-06" and up["triggered_close"] == 108
    assert other["active"] and dn["active"]                                        # brak danych AMD / nieprzebity
    assert al.evaluate(lambda t: (dates, hi, lo, cl)) and not al.for_ticker("NVDA", active_only=True) == []   # drugi przebieg: „poniżej 90” nadal nie
    assert al.last_triggered("NVDA")["id"] == up["id"] and al.evaluate(lambda t: None) == []
    al.reactivate(up["id"])
    assert up["active"] and up["triggered_on"] is None
    al.remove(dn["id"])
    assert [a["id"] for a in alerts.Alerts(tmp_path).items] == [up["id"], other["id"]]
    assert al.evaluate(lambda t: (dates, hi, lo, cl), tickers={"ZZZ"}) == []        # tylko spółki z danego skanera


def test_alert_below_uses_low_not_close():
    al = alerts.Alerts.__new__(alerts.Alerts)
    al.items = [{"id": "x", "ticker": "T", "price": 90.0, "dir": "below", "active": True, "ref_date": "2026-01-01"}]
    al.path = types.SimpleNamespace()
    al.save = lambda: None
    hit = al.evaluate(lambda t: (["2026-01-02", "2026-01-03"], [100, 100], [95, 89], [99, 98]))
    assert hit and hit[0]["triggered_on"] == "2026-01-03"                           # wystarczy Low sesji, zamknięcie było nad poziomem


# ---------- skala odwrotna i komórki siatki ----------

def test_inverse_scale_roundtrip():
    for log in (True, False):
        y = charts.make_scale(50, 400, 10, 500, log)
        inv = charts.inverse_scale(50, 400, 10, 500, log)
        for p in (50, 77.5, 123, 399):
            assert inv(y(p)) == pytest.approx(p, rel=1e-9)


def test_cell_specs_layouts():
    t = ["A", "B", "C", "D", "E"]
    assert grid.cell_specs("4", t, 3, "D", "bars", "W") == [("D", "W", "bars"), ("E", "W", "bars"), (None, "W", "bars"), (None, "W", "bars")]
    assert grid.cell_specs("td", t, 0, "B", "darcard", "D") == [("B", "W", "darcard"), ("B", "D", "darcard")]
    assert grid.cell_specs("cb", t, 0, "B", "bars", "D") == [("B", "D", "darcard"), ("B", "D", "bars")]


# ---------- dowolny ticker ----------

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
