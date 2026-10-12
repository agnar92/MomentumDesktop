import sys
import types

import pandas as pd

from desktop import daily, store, sync


def frame(n, start=100.0, dates=None):
    idx = dates if dates is not None else pd.bdate_range("2026-01-01", periods=n)
    c = [start + i for i in range(n)]
    return pd.DataFrame({"Open": c, "High": [x + 1 for x in c], "Low": [x - 1 for x in c], "Close": c, "Volume": [2_000_000] * n}, index=idx)


def test_build_daily_aligns_to_benchmark_and_keeps_tail():
    bench = frame(300, 5000)
    short = frame(50, 10, dates=bench.index[-50:])   # spółka z krótką historią: None przed debiutem
    d = daily.build_daily({"AAA": frame(300), "NEW": short}, bench, keep=100)
    assert len(d["dates"]) == len(d["spx"]) == 100 and d["dates"][-1] == bench.index[-1].strftime("%Y-%m-%d")
    assert d["stocks"]["AAA"]["c"][-1] == 399.0 and d["stocks"]["AAA"]["v"][-1] == 2000   # wolumen w tysiącach
    assert d["stocks"]["NEW"]["c"][0] is None and d["stocks"]["NEW"]["c"][-1] == 59.0


def test_sma():
    out = daily.sma([1, 2, 3, 4, 5], 3)
    assert out == [None, None, 2.0, 3.0, 4.0]
    assert daily.sma([1, None, 3, 4, 5], 2)[2:] == [None, 3.5, 4.5]


def test_store_timeframe_switch(tmp_path):
    s = store.Store(tmp_path / "d")
    assert s.tf == "W" and s.charts_d.get("stocks")
    t = s.rows[0]["ticker"]
    s.set_tf("D")
    assert s.tf == "D" and s.rows[0]["darvas"] == s.rows[0]["darvas_d"]
    full, dates, spx, smas = s.series(t, "D")
    assert len(full["c"]) == len(dates) == len(spx) and [n for _, n in smas] == [10, 50, 200]
    s.set_tf("W")
    assert s.rows[0]["darvas"] == s.rows[0]["darvas_w"] and s.series(t, "W")[0] is s.stocks_full[t]
    assert s.overview()   # sekcje liczone na wybranej skali


def test_store_without_daily_data_stays_weekly(tmp_path):
    s = store.Store(tmp_path / "x")
    s.charts_d = {}
    s.set_tf("D")
    assert s.tf == "W" and s.series(s.rows[0]["ticker"], "D")[0] is None


def _fake_engine(calls):
    fin = types.ModuleType("finviz")
    fin.load_config = lambda path=None: {"filters": "x", "max_tickers": 1}
    wl = types.ModuleType("watchlist")
    wl.RAW_PROFILE = "canslim"
    wl.load_raw = lambda profile, raw_dir=None: None
    wl.update_eps_cache = lambda tickers, cache_path=None, **k: calls.append("eps_net") or {"net": 1}
    wl.update_estimates = lambda tickers, path=None, **k: calls.append("est_net") or {"net": 1}

    def run(output_path, **k):
        calls.append(("eps", wl.update_eps_cache(["A"], output_path.parent / "eps_cache.json")))
        calls.append(("est", wl.update_estimates(["A"], output_path.parent / "estimates.json")))
        return 0

    wl.run = run
    return fin, wl


def test_prices_mode_does_not_fetch_fundamentals(tmp_path, monkeypatch):
    d = store.data_dir(tmp_path / "d")
    store.write_json(d / "eps_cache.json", {"A": {"cached": True}})
    store.write_json(d / "estimates.json", {"stocks": {"A": {"cached": True}}})
    calls = []
    fin, wl = _fake_engine(calls)
    monkeypatch.setitem(sys.modules, "finviz", fin)
    monkeypatch.setitem(sys.modules, "watchlist", wl)
    logs = []
    assert sync.run_sync(d, log=logs.append, mode=sync.PRICES) == 0
    assert "eps_net" not in calls and "est_net" not in calls
    assert ("eps", {"A": {"cached": True}}) in calls and ("est", {"A": {"cached": True}}) in calls
    st = sync.read_state(d)
    assert (d / "sync_state.json").exists() and st["prices"]
    before = st["fundamentals"]
    assert before != st["prices"]   # dane startowe mają starszą datę fundamentów (generated_at), sync cen jej nie odświeża
    assert sync.run_sync(d, log=logs.append, mode=sync.PRICES) == 0
    assert sync.read_state(d)["fundamentals"] == before   # sync cen nie rusza daty fundamentów


def test_fundamentals_mode_fetches_and_updates_state(tmp_path, monkeypatch):
    d = store.data_dir(tmp_path / "d")
    calls = []
    fin, wl = _fake_engine(calls)
    monkeypatch.setitem(sys.modules, "finviz", fin)
    monkeypatch.setitem(sys.modules, "watchlist", wl)
    assert sync.run_sync(d, log=lambda s: None, mode=sync.FUNDAMENTALS) == 0
    assert "eps_net" in calls and "est_net" in calls
    st = sync.read_state(d)
    assert st["fundamentals"] == st["prices"]
    assert sync.age_days(st["fundamentals"]) < 0.01
    assert sync.age_days(None) is None
