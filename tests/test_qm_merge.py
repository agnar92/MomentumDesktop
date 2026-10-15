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
    assert len(store.scan(rows, {})) == 10   # skan pokazuje wszystkie pobrane spółki — progi Qullamaggiego są w watchliście
    root = tmp_path
    sc = scanners.upsert(root, {"name": "QM", "kind": "qm"}, "cap_smallover", 3000, {"min_adr": 4})
    assert scanners.get(root, sc["id"])["kind"] == "qm" and scanners.load_config(scanners.scanner_dir(root, sc["id"]))["qm"]["min_adr"] == 4
    scanners.save_qm(scanners.scanner_dir(root, sc["id"]), {"top_pct": 5})
    cfg = scanners.load_config(scanners.scanner_dir(root, sc["id"]))
    assert cfg["qm"]["top_pct"] == 5 and cfg["filters"] == "cap_smallover" and cfg["max_tickers"] == 3000
    m = scanners.upsert(root, {"name": "M", "kind": "merge", "sources": [sc["id"]]})   # stary zapis: kind merge + samo id
    got = scanners.get(root, m["id"])
    assert got["kind"] == "watchlist" and got["sources"] == [{"id": sc["id"], "rule": {"type": "all"}}]
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
    m = scanners.upsert(root, {"name": "Razem", "kind": "watchlist", "sources": [{"id": a["id"], "rule": {"type": "all"}}, {"id": b["id"], "rule": {"type": "all"}}]})
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
    q = scanners.upsert(root, {"name": "QM", "kind": "qm"}, "x", 10)
    qd = scanners.scanner_dir(root, q["id"])
    _write(qd, ["T1", "T2", "T3", "T4"], 10)
    w = json.loads((qd / "watchlist.json").read_text())
    for i, s in enumerate(w["stocks"]):
        s["low_ratio_1m"] = 1 + i
    (qd / "watchlist.json").write_text(json.dumps(w))
    rule = {"type": "qm", "min_dollar_mln": 50, "min_adr": 3, "top_pct": 25, "windows": ["1m"]}
    m = scanners.upsert(root, {"name": "M", "kind": "watchlist", "sources": [{"id": q["id"], "rule": rule}]})
    assert merge.build(root, m, log=lambda s: None) == 1   # górne 25 % z 4 spółek = 1
    wl = json.loads((scanners.scanner_dir(root, m["id"]) / "watchlist.json").read_text())
    assert [s["ticker"] for s in wl["stocks"]] == ["T4"] and wl["stocks"][0]["qm_windows"] == "1M"


def test_prune_to_keeps_only_given_tickers(tmp_path):
    _write(tmp_path, ["A", "B", "C"], 10)
    sync.prune_to(tmp_path, {"A", "C"}, lambda s: None)
    wl = json.loads((tmp_path / "watchlist.json").read_text())
    assert [s["ticker"] for s in wl["stocks"]] == ["A", "C"] and wl["qm_universe"] == 3 and wl["n_stocks"] == 2
    assert set(json.loads((tmp_path / "charts.json").read_text())["stocks"]) == {"A", "C"}


def test_sanitize_frames_and_safe_metrics():
    import pandas as pd
    idx = pd.bdate_range("2026-10-01", periods=4)
    good = pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 1.0, "Close": 1.5, "Volume": 10}, index=idx)
    bad = good.copy()
    bad.loc[idx[1], "Low"] = 0.0   # Yahoo: Low = 0 -> dzielenie przez zero w silniku
    logs = []
    out = sync.sanitize_frames({"G": good, "B": bad}, logs.append)
    assert len(out["G"]) == 4 and len(out["B"]) == 3 and (out["B"]["Low"] > 0).all() and logs
    def boom(df):
        raise ZeroDivisionError("float division by zero")
    msgs = []
    assert sync.safe_metrics(boom, msgs.append)(good) is None and "ZeroDivisionError" in msgs[0]
    assert sync.safe_metrics(lambda df: {"ok": 1})(good) == {"ok": 1}


def test_history_downloader_defaults_to_three_years_but_keeps_explicit_period():
    seen = []
    dl = sync.history_downloader(lambda tickers, period="10y", batch_size=50: seen.append((tickers, period)) or {})
    dl(["A"])
    dl(["PLN=X"], period="10d")
    assert seen == [(["A"], "3y"), (["PLN=X"], "10d")]


def _u(t, price=20.0, avgvol=3e6, vol_m=3.0, p1=1.0, p3=1.0, p6=1.0):
    return {"ticker": t, "price": price, "avgvol": avgvol, "vol_m": vol_m, "p1m": p1, "p3m": p3, "p6m": p6}


def test_stage1_candidates_pool_and_select_uses_universe_size():
    uni = [_u(f"U{i}", p1=i, p3=-i, p6=i % 7) for i in range(400)]
    uni += [_u("ILLIQ", price=1.0, avgvol=1e5, p1=9999), _u("CALM", vol_m=0.3, p1=9999)]   # nie płynne -> nie kandydaci
    cfg = {"min_dollar_mln": 50, "min_adr": 3, "top_pct": 10, "keep_dollar_mln": 25, "keep_adr": 2}
    cand = {u["ticker"] for u in qm.candidates(uni, cfg)}
    assert "ILLIQ" not in cand and "CALM" not in cand
    assert "U399" in cand and "U0" in cand               # czołówka okna 1M i okna 3M (zwroty ujemne)
    assert len(cand) < len(uni) and len(cand) >= qm.CAND_MIN
    pairs = qm.pool_pairs(uni)
    assert len(pairs) == len(uni) and qm.pool_size(pairs, cfg) == 400   # obrót 60 mln >= 50*0.6, zmienność 3 >= 3-0.75; ILLIQ i CALM odpadają
    rows = [stock(f"S{i}", r1=1 + i / 100) for i in range(30)]   # zapisani kandydaci: 30
    base = {"min_dollar_mln": 50, "min_adr": 3, "top_pct": 10, "windows": ["1m"]}
    assert len(qm.select(rows, base)) == 3                       # 10 % z 30 zapisanych
    assert len(qm.select(rows, base, pairs)) == 30               # 10 % z 400 płynnych w całym zbiorze = 40, ale zapisanych jest tylko 30
    assert qm.normalize({"two_stage": False})["two_stage"] is False and qm.normalize(None)["two_stage"] is True


def test_fetch_universe_uses_custom_view_and_restores_settings():
    seen = {}

    def fetch_view(view, filters, max_t, **k):
        seen["cols"] = dict(fv.VIEW_COLUMNS[view])
        seen["params"] = dict(fv.VIEW_PARAMS[view])
        return [{"ticker": "A"}], 1

    fv = types.SimpleNamespace(fetch_view=fetch_view, VIEW_COLUMNS={"152": {"Recom": "recom"}}, VIEW_PARAMS={"152": {"c": "0,1"}}, TEXT_KEYS={"company"})
    rows, total = sync.fetch_universe(fv, "cap_smallover", 3000, lambda s: None)
    assert rows == [{"ticker": "A"}] and seen["cols"]["Perf Month"] == "p1m" and seen["params"]["c"] == qm.UNIVERSE_IDS
    assert fv.VIEW_COLUMNS["152"] == {"Recom": "recom"} and fv.VIEW_PARAMS["152"] == {"c": "0,1"} and fv.TEXT_KEYS == {"company"}


def test_watchlist_takes_top_percent_of_each_window_separately_and_canslim_rule(tmp_path):
    root = tmp_path
    q = scanners.upsert(root, {"name": "QM", "kind": "qm"}, "x", 10)
    qd = scanners.scanner_dir(root, q["id"])
    tick = [f"T{i:02d}" for i in range(20)]
    _write(qd, tick, 10)
    w = json.loads((qd / "watchlist.json").read_text())
    for i, s in enumerate(w["stocks"]):   # każde okno ma innego lidera: 1M rośnie z i, 3M maleje z i, 6M — liderem jest T10
        s["low_ratio_1m"], s["low_ratio_3m"], s["low_ratio_6m"] = 1 + i / 100, 2 - i / 100, 1 + (5 if i == 10 else 0) + i / 1000
    (qd / "watchlist.json").write_text(json.dumps(w))
    rule = {"type": "qm", "min_dollar_mln": 50, "min_adr": 3, "top_pct": 10, "windows": ["1m", "3m", "6m"]}   # 10 % z 20 = 2 spółki na okno
    items = merge.select_source(root, scanners.get(root, q["id"]), rule)[0]
    got = {s["ticker"]: win for s, win in items}
    assert got["T19"] == ["1m", "6m"] and got["T18"] == ["1m"] and got["T00"] == ["3m"] and got["T01"] == ["3m"] and got["T10"] == ["6m"]
    assert set(got) == {"T19", "T18", "T00", "T01", "T10"}   # 2 spółki z każdego okna, suma bez duplikatów
    # CANSLIM: tylko spółki z cs >= n
    cs = merge.select_source(root, scanners.get(root, q["id"]), {"type": "canslim", "cs_min": 8})[0]
    assert cs == []   # dane testowe nie mają CANSLIM >= 8/7


# ---------- Wish: Green Line Breakout (miesięczne zamknięcia) ----------
def test_glb_analyze_states():
    from desktop import glb
    base = [10, 12, 14, 16, 18, 20]   # rosnące szczyty do 20
    # szczyt 20, potem 4 miesiące bez pobicia, ostatni miesiąc nad linią → WYBICIE
    r = glb.analyze(base + [18, 17, 18, 19, 21])
    assert r["glb_state"] == "BREAK" and r["glb_level"] == 20 and r["glb_dist_pct"] < 0 and r["glb_months"] == 0
    # ten sam układ, cena nadal pod linią → CZEKA (potwierdzona linia, odległość do niej)
    r = glb.analyze(base + [18, 17, 18, 19, 19])
    assert r["glb_state"] == "WAIT" and r["glb_level"] == 20 and abs(r["glb_dist_pct"] - 5.26) < 0.01 and r["glb_months"] == 5
    # wybicie dwa miesiące temu, cena +5 % nad linią → po wybiciu; +30 % → za późno
    assert glb.analyze(base + [18, 17, 18, 19, 21, 21, 21])["glb_state"] == "AFTER"
    assert glb.analyze(base + [18, 17, 18, 19, 21, 26, 26])["glb_state"] == "LATE"
    # po wybiciu cena wróciła pod linię → czeka na ponowne przebicie
    assert glb.analyze(base + [18, 17, 18, 19, 21, 19, 19])["glb_state"] == "WAIT"
    # ciągłe nowe szczyty (brak 3-miesięcznej przerwy) i za mało danych → brak linii
    assert glb.analyze([10, 11, 12, 13, 14, 15, 16, 17])["glb_state"] == "NONE"
    assert glb.analyze([10, 11])["glb_state"] == "NONE"
    # za krótka przerwa (2 miesiące) nie tworzy linii: 20, 18, 19, 21
    assert glb.analyze(base + [18, 19, 21])["glb_state"] != "BREAK"
    # parametry z konfiguracji: 2 miesiące wystarczą
    assert glb.analyze(base + [18, 19, 21], {"confirm_months": 2})["glb_state"] == "BREAK"
    assert glb.normalize({"confirm_months": "abc", "late_pct": -1}) == glb.DEFAULTS


def test_glb_apply_writes_fields_and_rule_selects(tmp_path):
    import json

    from desktop import glb, scanners
    d = tmp_path
    wl = {"stocks": [{"ticker": "AAA"}, {"ticker": "BBB"}, {"ticker": "CCC"}, {"ticker": "DDD"}]}
    (d / "watchlist.json").write_text(json.dumps(wl))
    base = [10, 12, 14, 16, 18, 20]
    monthly = {"AAA": {"d": [], "c": base + [18, 17, 18, 19, 21]}, "BBB": {"d": [], "c": base + [18, 17, 18, 19, 19]},
               "CCC": {"d": [], "c": base + [18, 17, 18, 19, 15]}, "DDD": {"d": [], "c": [10, 11, 12, 13, 14, 15, 16, 17]}}
    n = glb.apply(d, {}, lambda *_: None, fetch=lambda tickers, log: monthly)
    out = {s["ticker"]: s for s in json.loads((d / "watchlist.json").read_text())["stocks"]}
    assert n == 1 and out["AAA"]["glb_state"] == "BREAK" and out["BBB"]["glb_state"] == "WAIT" and out["DDD"]["glb_state"] == "NONE"
    assert (d / "monthly.json").exists()
    rows = list(out.values())
    assert [r["ticker"] for r in glb.select(rows, {"states": ["BREAK"]})] == ["AAA"]
    assert {r["ticker"] for r in glb.select(rows, {})} == {"AAA", "BBB"}      # CCC czeka, ale jest > 10 % pod linią
    assert {r["ticker"] for r in glb.select(rows, {"max_dist_pct": 40})} == {"AAA", "BBB", "CCC"}
    # kolumna GLB sortuje wybicia przed czekającymi, na końcu brak linii
    from desktop import columns
    keys = sorted(rows, key=lambda r: columns.sort_value(r, "glb_state"))
    assert [r["ticker"] for r in keys][:2] == ["AAA", "BBB"] and keys[-1]["ticker"] == "DDD"
    assert columns.format_cell(out["AAA"], "glb_state") == "WYBICIE" and scanners.norm_source({"id": "x", "rule": {"type": "glb"}})["rule"]["type"] == "glb"


def test_glb_monthly_cache_fetches_only_missing_and_uses_live_price(tmp_path):
    import json
    from datetime import datetime

    from desktop import glb
    d = tmp_path
    base = [10, 12, 14, 16, 18, 20, 18, 17, 18, 19]
    dates = [f"2026-{m:02d}-01" for m in range(1, 10)] + ["2026-10-01"]
    (d / "watchlist.json").write_text(json.dumps({"stocks": [{"ticker": "AAA", "price": 21.0}, {"ticker": "BBB", "price": 9.0}]}))
    calls = []

    def fetch(tickers, log):
        calls.append(list(tickers))
        return {t: {"d": dates, "c": base} for t in tickers}   # ostatni punkt = trwający miesiąc (2026-10) — odrzucamy go, cena idzie z Sync
    log = []
    glb.apply(d, {}, log.append, fetch=fetch, today=datetime(2026, 10, 15))
    out = {s["ticker"]: s for s in json.loads((d / "watchlist.json").read_text())["stocks"]}
    assert calls == [["AAA", "BBB"]]
    # AAA: zakończone miesiące do września + cena 21 jako bieżący miesiąc → wybicie nad linią 20; BBB: cena 9 → czeka
    assert out["AAA"]["glb_state"] == "BREAK" and out["AAA"]["glb_level"] == 20 and out["BBB"]["glb_state"] == "WAIT"
    # drugi Sync w tym samym miesiącu: wszystko z pamięci podręcznej, bez pobierania; zmiana ceny zmienia stan
    wl = json.loads((d / "watchlist.json").read_text())
    wl["stocks"][0]["price"] = 19.0
    (d / "watchlist.json").write_text(json.dumps(wl))
    glb.apply(d, {}, log.append, fetch=lambda t, lg: (_ for _ in ()).throw(AssertionError("nie powinno pobierać")), today=datetime(2026, 10, 20))
    assert json.loads((d / "watchlist.json").read_text())["stocks"][0]["glb_state"] == "WAIT" and any("pamięci podręcznej" in x for x in log)
    # nowy miesiąc: brakuje wrześniowego / październikowego zakończonego miesiąca → pobieramy ponownie
    glb.apply(d, {}, log.append, fetch=fetch, today=datetime(2026, 11, 3))
    assert len(calls) == 2


def test_wish_scan_sync_is_prices_only(tmp_path):
    from desktop import scanners
    scanners.save_config(tmp_path, "sh_price_o1", 500, glb_cfg={"confirm_months": 3})
    cfg = scanners.load_config(tmp_path)
    assert cfg["glb"]["confirm_months"] == 3 and "qm" not in cfg


def test_wish_preset_has_no_finviz_ath_filter():
    from desktop import builder
    assert "ta_alltime" not in builder.WISH_FILTERS and "sh_price_o1" in builder.WISH_FILTERS


def test_glb_prefilter_skips_far_from_high_and_fetch_respects_budget(tmp_path, monkeypatch):
    import json
    import time

    from desktop import glb
    base = [10, 12, 14, 16, 18, 20, 18, 17, 18, 19]
    wl = {"stocks": [{"ticker": "NEAR", "price": 19.0, "pct_from_high_52w": -5.0}, {"ticker": "FAR", "price": 8.0, "pct_from_high_52w": -60.0},
                     {"ticker": "UNK", "price": 19.0}]}
    (tmp_path / "watchlist.json").write_text(json.dumps(wl))
    asked = []
    glb.apply(tmp_path, {}, lambda *_: None, fetch=lambda t, log: asked.extend(t) or {x: {"d": [], "c": base} for x in t})
    out = {s["ticker"]: s for s in json.loads((tmp_path / "watchlist.json").read_text())["stocks"]}
    assert sorted(asked) == ["NEAR", "UNK"] and out["FAR"]["glb_state"] == "NONE" and out["NEAR"]["glb_state"] == "WAIT"
    # twardy limit czasu: wiszące zapytania nie blokują Synca, a masowe błędy nie uruchamiają wolnej ścieżki yfinance
    monkeypatch.setattr(glb, "_fetch_one", lambda session, t: time.sleep(5))
    monkeypatch.setattr(glb, "_fetch_yfinance", lambda *a, **k: (_ for _ in ()).throw(AssertionError("zapasowa ścieżka nie powinna ruszyć")))
    logs, t0 = [], time.time()
    res = glb.fetch_monthly([f"T{i}" for i in range(300)], logs.append, workers=4, budget=1)
    assert res == {} and time.time() - t0 < 4 and any("limit czasu" in x for x in logs)
