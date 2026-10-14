import json
import sys
import types

from desktop import columns, finviz_catalog as fc, scanners, store, sync


def test_catalog_codes_unique_and_roundtrip():
    codes = [c for _, _, opts in fc.FILTERS for _, c in opts]
    assert len(codes) == len(set(codes)) > 200
    seed = "cap_smallover,fa_epsqoq_high,geo_usa,ind_stocksonly,sh_avgvol_o300,sh_price_o1,ta_sma200_pa"
    sel, rest = fc.selection_from_filters(seed)
    assert rest == [] and sel["Kraj"] == "geo_usa" and sel["Cena vs SMA 200"] == "ta_sma200_pa"
    assert set(fc.filters_from_selection(sel, rest).split(",")) == set(seed.split(","))
    sel, rest = fc.selection_from_filters("geo_usa,nieznany,sh_price_o5,sh_price_o10")   # dwa kody tej samej grupy: drugi zostaje „resztą”
    assert rest == ["nieznany", "sh_price_o10"] and fc.filters_from_selection(sel, rest).split(",")[0] == "geo_usa"


def test_parse_finviz_input():
    assert fc.parse_finviz_input("https://finviz.com/screener.ashx?v=111&f=cap_smallover,geo_usa&ft=4&o=-marketcap") == "cap_smallover,geo_usa"
    assert fc.parse_finviz_input("f=geo_usa,ind_stocksonly") == "geo_usa,ind_stocksonly"
    assert fc.parse_finviz_input(" geo_usa , sh_price_o10 ") == "geo_usa,sh_price_o10"
    assert fc.parse_finviz_input("") == ""


def test_extra_columns_have_unique_ids_and_headers():
    ids = [v[0] for v in fc.EXTRA_COLUMNS.values()]
    assert len(ids) == len(set(ids)) and fc.extra_ids(["fv_beta"]) == [0, 1, 48]


def test_scanners_crud(tmp_path):
    root = store.data_dir(tmp_path / "d")
    assert [s["id"] for s in scanners.load(root)] == ["default"]
    sc = scanners.upsert(root, {"name": "Dywidendowe spółki", "extra": ["fv_dividend"]}, "geo_usa, fa_div_pos", 50)
    assert sc["id"] == "dywidendowe-spolki" and scanners.load_config(scanners.scanner_dir(root, sc["id"])) == {"filters": "geo_usa,fa_div_pos", "max_tickers": 50}
    cp = scanners.duplicate(root, sc["id"], "Kopia")
    assert cp["extra"] == ["fv_dividend"] and scanners.load_config(scanners.scanner_dir(root, cp["id"]))["max_tickers"] == 50
    assert scanners.slug("Dywidendowe spółki", {"dywidendowe-spolki"}) == "dywidendowe-spolki-2" and scanners.slug("ĄĆĘ!", set()) == "ace"
    assert scanners.delete(root, sc["id"]) and not scanners.scanner_dir(root, sc["id"]).exists()
    assert scanners.delete(root, "default") is False


def test_shared_cache_keeps_newest(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    store.write_json(a / "eps_cache.json", {"X": {"fetched": "2026-10-10", "v": 1}, "Y": {"fetched": "2026-10-01", "v": 1}})
    store.write_json(b / "eps_cache.json", {"X": {"fetched": "2026-10-05", "v": 0}, "Y": {"fetched": "2026-10-09", "v": 2}})
    store.write_json(a / "estimates.json", {"updated": "u", "stocks": {"Z": {"f": "2026-10-10"}}})
    scanners.merge_cache(a, b)
    merged = store.read_json(b / "eps_cache.json")
    assert merged["X"]["v"] == 1 and merged["Y"]["v"] == 2     # nowszy wpis wygrywa
    assert store.read_json(b / "estimates.json")["stocks"]["Z"] == {"f": "2026-10-10"}
    scanners.merge_cache(a, a)   # ten sam katalog = brak operacji


def test_columns_available_and_format():
    rows = [{"ticker": "A", "market_cap": 2.5e9, "price": 12.345, "leader": True, "weird_new_field": 3.14159, "spark": [1, 2]}]
    av = columns.available(rows, ["fv_dividend"])
    assert "market_cap" in av and "weird_new_field" in av and "fv_dividend" in av and "spark" not in av and "cs" in av   # policzone lokalnie są zawsze
    assert columns.format_cell(rows[0], "market_cap") == "2.50B" and columns.format_cell(rows[0], "price") == "12.35"
    assert columns.format_cell(rows[0], "leader") == "✓" and columns.format_cell({}, "price") == "–"
    assert columns.format_cell(rows[0], "weird_new_field") == "3.14"
    assert columns.sort_value({"price": None}, "price")[0] is True and columns.sort_value({"price": 5}, "price") == (False, 5)


def test_fetch_extra_patches_and_restores_finviz():
    seen = {}
    fin = types.SimpleNamespace(VIEW_COLUMNS={"152": {"Recom": "recom"}}, VIEW_PARAMS={"152": {"c": "0,1,62"}}, TEXT_KEYS={"company"})

    def fetch_view(view, filters, max_tickers):
        seen.update(view=view, filters=filters, cols=dict(fin.VIEW_COLUMNS["152"]), params=dict(fin.VIEW_PARAMS["152"]), text=set(fin.TEXT_KEYS))
        return [{"ticker": "AAA", "fv_beta": 1.2, "fv_country": "USA"}], 1

    fin.fetch_view = fetch_view
    out = sync.fetch_extra(fin, "geo_usa", 50, ["fv_beta", "fv_country", "nieznane"])
    assert out == {"AAA": {"fv_beta": 1.2, "fv_country": "USA"}}
    assert seen["cols"] == {"Beta": "fv_beta", "Country": "fv_country"} and seen["params"] == {"c": "0,1,48,5"} and "fv_country" in seen["text"]
    assert fin.VIEW_COLUMNS["152"] == {"Recom": "recom"} and fin.VIEW_PARAMS["152"] == {"c": "0,1,62"} and fin.TEXT_KEYS == {"company"}   # silnik dostaje swoje ustawienia z powrotem


def test_run_sync_writes_extra_and_merges_shared(tmp_path, monkeypatch):
    root = store.data_dir(tmp_path / "root")
    d = scanners.scanner_dir(root, "moj")
    d.mkdir(parents=True)
    scanners.save_config(d, "geo_usa", 10)
    store.write_json(root / "eps_cache.json", {"T": {"fetched": "2026-10-10"}})
    calls = {}
    fin = types.ModuleType("finviz")
    fin.load_config = lambda path=None: {"filters": "geo_usa", "max_tickers": 10}
    fin.fetch_watchlist = lambda filters, max_tickers=300, *a, **k: ([{"ticker": "T"}], 1)
    fin.VIEW_COLUMNS, fin.VIEW_PARAMS, fin.TEXT_KEYS = {"152": {}}, {"152": {}}, set()
    fin.fetch_view = lambda view, filters, max_tickers: ([{"ticker": "T", "fv_beta": 0.9}], 1)
    wl = types.ModuleType("watchlist")
    wl.RAW_PROFILE = "canslim"
    wl.load_raw = lambda *a, **k: None
    wl.update_eps_cache = lambda *a, **k: {}
    wl.update_estimates = lambda *a, **k: {}

    def run(output_path, **k):
        calls["eps_in_scanner_dir"] = (output_path.parent / "eps_cache.json").exists()   # cache ze wspólnego katalogu trafił do skanera przed uruchomieniem
        rows, _ = fin.fetch_watchlist("geo_usa", 10)
        calls["rows"] = rows
        store.write_json(output_path.parent / "eps_cache.json", {"T": {"fetched": "2026-10-11"}, "N": {"fetched": "2026-10-11"}})
        return 0

    wl.run = run
    monkeypatch.setitem(sys.modules, "finviz", fin)
    monkeypatch.setitem(sys.modules, "watchlist", wl)
    assert sync.run_sync(d, log=lambda s: None, mode=sync.PRICES, extra_keys=["fv_beta"], shared_root=root) == 0
    assert calls["eps_in_scanner_dir"] and json.loads((d / "finviz_extra.json").read_text()) == {"T": {"fv_beta": 0.9}}
    assert set(store.read_json(root / "eps_cache.json")) == {"T", "N"}    # nowe wpisy wracają do wspólnego cache
    assert fin.fetch_watchlist("x")[0] == [{"ticker": "T"}]                # po synchronizacji silnik ma z powrotem oryginalną funkcję


def test_store_merges_finviz_extra(tmp_path):
    d = store.data_dir(tmp_path / "d")
    ticker = store.Store(d).rows[0]["ticker"]
    store.write_json(d / "finviz_extra.json", {ticker: {"fv_beta": 1.5}})
    assert store.Store(d).rows[0]["fv_beta"] == 1.5


def test_empty_scanner_store_has_no_rows(tmp_path):
    s = store.Store(tmp_path / "e", seed=False)
    assert s.rows == [] and s.mkt is None


def test_prices_sync_uses_only_overview_view_and_carries_fundamentals(tmp_path):
    import json
    import types

    from desktop import sync
    prev = {"stocks": [{"ticker": "AAA", "eps_this_y": 33.0, "roe": 21.0, "company": "stara nazwa"}]}
    (tmp_path / "watchlist.json").write_text(json.dumps(prev))
    seen = {}

    def orig(filters, max_tickers=300, pause_s=0.7, views=("121", "161", "152")):
        seen["views"] = views
        return [{"ticker": "AAA", "company": "Nowa"}, {"ticker": "BBB"}], 2
    fin = types.SimpleNamespace(VIEW_COLUMNS={"121": {"EPS This Y": "eps_this_y"}, "161": {"ROE": "roe"}, "152": {"Recom": "recom"}})
    logs = []
    rows, total = sync.light_finviz(fin, orig, tmp_path, logs.append)("geo_usa", 10)
    assert seen["views"] == () and total == 2                       # tylko Overview — bez widoków fundamentalnych
    assert rows[0] == {"ticker": "AAA", "company": "Nowa", "eps_this_y": 33.0, "roe": 21.0} and rows[1] == {"ticker": "BBB"}   # AAA dostaje stare fundamenty, nie nadpisujemy nowych pól
    assert any("dla 1 spółek" in x for x in logs)
