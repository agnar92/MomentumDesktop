import json
import types


from desktop import merge, qm, scanners, store, sync


def stock(t, dv=60e6, adr=3.5, r1=1.5, r3=1.5, r6=1.5):
    return {"ticker": t, "price": 10.0, "dollar_volume_avg": dv, "adr_pct": adr, "low_ratio_1m": r1, "low_ratio_3m": r3, "low_ratio_6m": r6}


def test_select_top_percent_per_window_and_union():
    rows = [stock(f"S{i}", r1=1 + i / 100, r3=2 - i / 100, r6=1.0) for i in range(20)]
    rows += [stock("ILLIQ", dv=1e6, r1=9, r3=9, r6=9), stock("LOWADR", adr=1.0, r1=9, r3=9, r6=9)]
    picks = qm.select(rows, {"min_dollar_mln": 50, "min_adr": 3, "top_pct": 10, "windows": ["1m", "3m"]})
    assert "ILLIQ" not in picks and "LOWADR" not in picks
    assert picks["S19"] == ["1m"] and picks["S18"] == ["1m"] and picks["S0"] == ["3m"] and picks["S1"] == ["3m"]   # 10 % z 20 = 2 spółki na okno
    assert len(picks) == 4
    r = {}
    qm.annotate(r, ["1m", "6m"])
    assert r["qm_windows"] == "1M 6M"
    assert qm.select(rows, {"top_pct": 0}) == {}


def test_keep_below_keep_and_suggest_filters():
    rows = [stock("A", dv=30e6, adr=2.5), stock("B", dv=20e6), stock("C", adr=1.0)]
    assert [r["ticker"] for r in qm.keep(rows, qm.DEFAULTS)] == ["A"]
    assert qm.below_keep({"min_dollar_mln": 10}) and not qm.below_keep({"min_dollar_mln": 50})
    f = qm.suggest_filters({"keep_dollar_mln": 50, "keep_adr": 4}).split(",")
    assert "sh_avgvol_o300" in f and "ta_volatility_mo3" in f and "ind_stocksonly" in f
    assert "sh_avgvol_o100" in qm.suggest_filters(qm.DEFAULTS).split(",") and not any(c.startswith("ta_volatility") for c in qm.suggest_filters(qm.DEFAULTS).split(","))


def test_scan_qm_filter_and_scanner_kinds(tmp_path):
    rows = [stock(f"S{i}", r1=1 + i / 100) for i in range(10)]
    out = store.scan(rows, {"qm": {"min_dollar_mln": 50, "min_adr": 3, "top_pct": 20, "windows": ["1m"]}})
    assert [r["ticker"] for r in out] == ["S9", "S8"] or {r["ticker"] for r in out} == {"S8", "S9"}
    assert out[0]["qm_windows"] == "1M"
    root = tmp_path
    sc = scanners.upsert(root, {"name": "QM", "kind": "qm"}, "cap_smallover", 3000, {"min_adr": 4})
    assert scanners.get(root, sc["id"])["kind"] == "qm" and scanners.load_config(scanners.scanner_dir(root, sc["id"]))["qm"]["min_adr"] == 4
    scanners.save_qm(scanners.scanner_dir(root, sc["id"]), {"top_pct": 5})
    cfg = scanners.load_config(scanners.scanner_dir(root, sc["id"]))
    assert cfg["qm"]["top_pct"] == 5 and cfg["filters"] == "cap_smallover" and cfg["max_tickers"] == 3000
    m = scanners.upsert(root, {"name": "M", "kind": "merge", "sources": [sc["id"]]})
    assert scanners.get(root, m["id"])["sources"] == [sc["id"]]
    assert scanners.get(root, scanners.DEFAULT_ID)["kind"] == "finviz"


def test_old_default_filter_is_migrated(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "finviz_screen.json").write_text(json.dumps({"filters": store.OLD_DEFAULT_FILTERS, "max_tickers": 300}))
    store.data_dir(d)
    assert json.loads((d / "finviz_screen.json").read_text())["filters"] == store.NEW_DEFAULT_FILTERS
    (d / "finviz_screen.json").write_text(json.dumps({"filters": "cap_smallover", "max_tickers": 300}))   # własny filtr użytkownika zostaje
    store.data_dir(d)
    assert json.loads((d / "finviz_screen.json").read_text())["filters"] == "cap_smallover"


def test_fetch_sliced_splits_by_sector_above_free_limit():
    calls = []

    def fetch_view(view, filters, max_t, **k):
        calls.append((filters, max_t))
        if max_t == sync.PAGE_PROBE:
            return [], 2400
        sec = filters.rsplit("sec_", 1)[-1]
        return [{"ticker": f"{sec}{i}"} for i in range(3)] + [{"ticker": "DUP"}], 4

    fv = types.SimpleNamespace(fetch_view=fetch_view)
    rows, total = sync.fetch_sliced(fv, "cap_smallover", 3000, lambda s: None)
    assert len(calls) == 1 + len(sync.SECTORS) and total == len(rows) == 3 * len(sync.SECTORS) + 1   # DUP raz
    calls.clear()
    fv2 = types.SimpleNamespace(fetch_view=lambda v, f, m, **k: (calls.append(f) or ([{"ticker": "A"}], 500)))
    rows, total = sync.fetch_sliced(fv2, "cap_smallover", 3000, lambda s: None)
    assert rows == [{"ticker": "A"}] and all("sec_" not in f for f in calls)


def _write(d, tickers, last_week, spx_offset=0):
    d.mkdir(parents=True, exist_ok=True)
    weeks = [f"2026-{m:02d}-01" for m in range(1, 6)][-last_week:] if False else [f"w{i}" for i in range(last_week - 4, last_week + 1)]
    stocks = [stock(t) | {"company": t} for t in tickers]
    (d / "watchlist.json").write_text(json.dumps({"generated_at": "2026-10-01T00:00:00Z", "data_as_of": f"d{last_week}", "stocks": stocks, "market": {"regime": "uptrend"}}))
    ch = {"weeks": weeks, "spx": list(range(len(weeks))), "stocks": {t: {"c": [100 + i + len(t) for i in range(len(weeks))], "bases": [], "eps": [1, 2]} for t in tickers}}
    (d / "charts.json").write_text(json.dumps(ch))
    (d / "charts_daily.json").write_text(json.dumps({"dates": weeks, "spx": [], "stocks": {t: {"c": ch["stocks"][t]["c"]} for t in tickers}}))


def test_merge_builds_union_with_sources_and_realigns_axes(tmp_path):
    root = tmp_path
    a = scanners.upsert(root, {"name": "Alfa"}, "x", 10)
    b = scanners.upsert(root, {"name": "Beta"}, "x", 10)
    _write(scanners.scanner_dir(root, a["id"]), ["AAA", "BBB"], 10)
    _write(scanners.scanner_dir(root, b["id"]), ["BBB", "CCC"], 11)   # nowsza oś (przesunięta o tydzień)
    m = scanners.upsert(root, {"name": "Razem", "kind": "merge", "sources": [a["id"], b["id"]]})
    assert merge.build(root, m, log=lambda s: None) == 3
    d = scanners.scanner_dir(root, m["id"])
    wl = json.loads((d / "watchlist.json").read_text())
    srcs = {s["ticker"]: s["merge_src"] for s in wl["stocks"]}
    assert srcs == {"AAA": "Alfa", "BBB": "Alfa, Beta", "CCC": "Beta"} and wl["data_as_of"] == "d11" and wl["n_stocks"] == 3
    ch = json.loads((d / "charts.json").read_text())
    assert ch["weeks"][-1] == "w11" and set(ch["stocks"]) == {"AAA", "BBB", "CCC"}
    aaa = ch["stocks"]["AAA"]["c"]
    assert len(aaa) == 5 and aaa[-1] is None and aaa[-2] == 100 + 4 + 3   # oś Alfa kończyła się tydzień wcześniej -> ostatni punkt pusty
    assert len(json.loads((d / "charts_daily.json").read_text())["stocks"]) == 3
    st = store.Store(d, seed=False)
    assert {r["ticker"] for r in st.rows} == {"AAA", "BBB", "CCC"}


def test_merge_takes_only_qm_selected_stocks(tmp_path):
    root = tmp_path
    q = scanners.upsert(root, {"name": "QM", "kind": "qm"}, "x", 10, {"min_dollar_mln": 50, "min_adr": 3, "top_pct": 25, "windows": ["1m"]})
    qd = scanners.scanner_dir(root, q["id"])
    _write(qd, ["T1", "T2", "T3", "T4"], 10)
    w = json.loads((qd / "watchlist.json").read_text())
    for i, s in enumerate(w["stocks"]):
        s["low_ratio_1m"] = 1 + i
    (qd / "watchlist.json").write_text(json.dumps(w))
    m = scanners.upsert(root, {"name": "M", "kind": "merge", "sources": [q["id"]]})
    assert merge.build(root, m, log=lambda s: None) == 1   # górne 25 % z 4 spółek = 1
    wl = json.loads((scanners.scanner_dir(root, m["id"]) / "watchlist.json").read_text())
    assert [s["ticker"] for s in wl["stocks"]] == ["T4"] and wl["stocks"][0]["qm_windows"] == "1M"


def test_prune_to_keeps_only_given_tickers(tmp_path):
    _write(tmp_path, ["A", "B", "C"], 10)
    sync.prune_to(tmp_path, {"A", "C"}, lambda s: None)
    wl = json.loads((tmp_path / "watchlist.json").read_text())
    assert [s["ticker"] for s in wl["stocks"]] == ["A", "C"] and wl["qm_universe"] == 3 and wl["n_stocks"] == 2
    assert set(json.loads((tmp_path / "charts.json").read_text())["stocks"]) == {"A", "C"}
