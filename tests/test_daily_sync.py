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


def test_worker_command_and_args_roundtrip(tmp_path):
    cmd = sync.worker_command(tmp_path / "d", sync.PRICES, True, ["fv_beta", "fv_rsi"], tmp_path)
    assert cmd[-9:-7] == ["--sync", str(tmp_path / "d")] or "--sync" in cmd
    i = cmd.index("--sync")
    ns = sync.parse_worker_args(cmd[i + 1:])
    assert ns.data_dir == str(tmp_path / "d") and ns.mode == sync.PRICES and ns.skip_finviz and ns.extra == ["fv_beta", "fv_rsi"] and ns.shared == str(tmp_path)
    ns = sync.parse_worker_args([str(tmp_path)])
    assert ns.mode == sync.PRICES and ns.extra == [] and ns.shared is None and not ns.skip_finviz


def test_run_in_subprocess_streams_log_and_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "worker_command", lambda *a, **k: [sys.executable, "-c", "print('pierwsza ✅'); print(); print('druga'); raise SystemExit(3)"])
    lines = []
    assert sync.run_in_subprocess(tmp_path, lines.append, mode=sync.PRICES) == 3
    assert lines == ["pierwsza ✅", "druga", "Proces synchronizacji zakończony (kod 3)."]
    monkeypatch.setattr(sync, "worker_command", lambda *a, **k: ["/nie/ma/takiego/programu"])
    assert sync.run_in_subprocess(tmp_path, lines.append) == 1 and "Nie można uruchomić" in lines[-1]


def test_two_parallel_cache_merges_do_not_lose_entries(tmp_path):
    import threading
    from desktop import scanners
    root = tmp_path / "root"
    root.mkdir()
    dirs = []
    for n in range(4):
        d = tmp_path / f"s{n}"
        d.mkdir()
        store.write_json(d / "eps_cache.json", {f"T{n}": {"fetched": "2026-10-11"}})
        dirs.append(d)
    ts = [threading.Thread(target=scanners.merge_cache, args=(d, root)) for d in dirs]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert set(store.read_json(root / "eps_cache.json")) == {"T0", "T1", "T2", "T3"} and not (root / ".cache.lock").exists()


def test_market_ema_line_macd_column_and_filter(tmp_path):
    from desktop import canslim, columns
    s = store.Store(tmp_path / "d")
    e = canslim.ema_market(s.watchlist)
    assert e["up"] is True and "EMA10/20" in canslim.market_line(s.watchlist) and "S&P 500" in canslim.market_line(s.watchlist)
    down = {"market": {"sp500": {"ema10w": 90, "ema20w": 100}, "nasdaq": {"ema10w": 110, "ema20w": 100}}}
    assert canslim.ema_market(down)["up"] is False and "🛑" in canslim.market_line(down)
    ups = [r for r in s.rows if r["macd_up"] is True]
    assert ups and len(ups) < len(s.rows) and "macd_up" in columns.available(s.rows)
    assert {r["ticker"] for r in store.scan(s.rows, {"macd_only": True})} == {r["ticker"] for r in ups}
    assert columns.format_cell(ups[0], "macd_up") == "✓"
    buy = next(r for r in s.rows if r["darvas_w"] == "BUY") if any(r["darvas_w"] == "BUY" for r in s.rows) else None
    st = store.enrich({"ticker": "X"}, {"c": [10, 10.5, 11, 12, 11.5, 11.2, 11.4, 11.1, 12.5, 13, 12.8, 12.6, 12.2, 12.9, 14, 15, 14.5, 14.2, 14.4, 14.1, 13.9, 16]},
                      None, [], market_up=False)
    assert st["darvas_w"] == "BUY" and "rynek w korekcie" in st["darvas_text_w"]
    assert buy is None or "rynek" not in buy["darvas_text_w"]   # przy trendzie wzrostowym brak ostrzeżenia
    s.set_pure(True)
    try:
        assert all(r["darvas_w"] not in ("NOVOL", "LATE") for r in s.rows)
    finally:
        s.set_pure(False)
