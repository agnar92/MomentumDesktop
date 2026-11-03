"""Nowy interfejs CEM10 (desktop/cem10_web.py) bez sieci: stan dla strony, ustawienia, raport XTB, plan, zadania w tle, serwer z tokenem."""
import json
import time
import urllib.request

import pytest

from desktop import cem10_web as W
from desktop import portfel
from desktop.store import Store

pytest.importorskip("openpyxl")
from tests.test_portfel import CEM, _zip  # noqa: E402

LIST = {"generated_at": "2026-04-02", "month": "2026-03", **{k: {**v, "n": 10 if k == "usa" else 5, **(
    {"spy5": 0.0, "qqq5": 0.0, "spy": 1.0, "spy_sma12": 1.0, "missing": []} if k == "usa" else {"lv": 1.0, "lv12": 1.0, "rewizja": "x", "missing": []})}
    for k, v in CEM.items()}}


@pytest.fixture
def api(tmp_path):
    return W.Api(Store(tmp_path))


def test_state_empty_then_list_and_manual(api):
    s = api.state()
    assert s["lists"] is None and s["portfolio"] is None and s["plan"] is None and not s["task"]["busy"]
    assert (W.static_dir() / "index.html").is_file() and (W.static_dir() / "app.js").is_file()
    api.store.save_cache("cem10", LIST)
    s = api.save_settings({"hold": "AAA, CCC, BBB.wa, ZZZ"})
    assert s["lists"]["month"] == "2026-03"
    assert {m["t"]: m["decision"] for m in s["manual"]} == {"AAA": "trzymaj", "CCC": "sprzedaj", "BBB": "trzymaj", "ZZZ": "sprawdź"}
    assert api.store.settings["cem10_hold"] == "AAA, CCC, BBB.wa, ZZZ"


def test_xtb_report_portfolio_plan_history(api):
    api.store.save_cache("cem10", LIST)
    s = api.import_xtb(_zip(), "raport.zip")
    P = s["portfolio"]
    assert {r["t"] for r in P["rows"]} == {"AAA", "BBB", "CCC"} and "Wczytano" in s["message"]
    assert next(r for r in P["rows"] if r["t"] == "CCC")["status"].startswith("SPRZEDAJ")
    assert "AAA" in api.store.settings["cem10_hold"]                       # trzymane z raportu -> sito pobierania
    s = api.save_settings({"deposit": "1 000", "targets": {"usa": 50, "gpw": 50, "etf": 0}})
    assert api.store.settings["cem10_deposit"] == 1000.0
    acts = s["plan"]["actions"]
    assert any(a["akcja"] == "SPRZEDAJ" and a["ticker"] == "CCC" for a in acts)
    assert all("yahoo" in a and "name" in a for a in acts)
    H = s["history"]
    assert H["points"] and not H["exact"] and any(e["kind"] == "wpłata" for e in H["events"])
    json.dumps(s, default=str)                                               # stan da się wysłać jako JSON


def test_background_tasks_fetch_and_curve(api):
    api.store.save_cache("xtb", {"accounts": portfel.load_report(_zip())})
    assert api.start_fetch(fetch=lambda gpw, old, log, progress, held: (log("x"), progress(0.5), LIST)[2])
    for _ in range(100):
        if not api.task["busy"]:
            break
        time.sleep(0.02)
    assert api.task["done"] == "Lista za 2026-03 gotowa" and api.state()["lists"]
    assert api.start_curve(prices=lambda acc, log: ({}, {}))
    for _ in range(100):
        if not api.task["busy"]:
            break
        time.sleep(0.02)
    assert api.state()["history"]["exact"]
    assert api.start_fetch(fetch=lambda *a, **k: (_ for _ in ()).throw(ValueError("za mało cen")))
    for _ in range(100):
        if not api.task["busy"]:
            break
        time.sleep(0.02)
    assert api.task["error"] == "za mało cen"


def test_gpw_members_save_and_reset(api):
    s = api.save_gpw({"rewizja": "2026-12-19", "WIG20": {"pko.wa": "PKO BP"}, "mWIG40": {"ALE": ""}})
    assert s["gpw"]["custom"] and s["gpw"]["WIG20"] == {"PKO": "PKO BP"} and s["gpw"]["mWIG40"] == {"ALE": "Allegro.eu S.A."}   # pusta nazwa = nazwa znanej spółki
    assert not api.save_gpw({"reset": True})["gpw"]["custom"]


def test_server_token_and_static(api):
    srv, url = W.make_server(api, token="tok")
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = url.split("/index.html")[0]
    try:
        assert b"CEM10" in urllib.request.urlopen(base + "/index.html").read()
        with pytest.raises(urllib.error.HTTPError) as e:                     # bez tokenu: 403
            urllib.request.urlopen(base + "/api/state")
        assert e.value.code == 403
        req = urllib.request.Request(base + "/api/settings", data=json.dumps({"deposit": 700}).encode(), headers={"X-CEM10": "tok"}, method="POST")
        assert json.loads(urllib.request.urlopen(req).read())["settings"]["deposit"] == 700
        with pytest.raises(urllib.error.HTTPError) as e:                     # poza folderem strony: 404
            urllib.request.urlopen(base + "/../desktop/store.py")
        assert e.value.code == 404
    finally:
        srv.shutdown()


def _fake_download(frames):
    """Podmiana yfinance: {symbol: [(data, zamknięcie)]} -> DataFrame jak z group_by='ticker'."""
    import pandas as pd

    def download(syms):
        cols = {}
        for s in syms:
            if s in frames:
                d, c = zip(*frames[s])
                cols[(s, "Close")] = pd.Series(c, index=pd.to_datetime(d))
        df = pd.DataFrame(cols)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df
    return download


def test_manual_account_without_xtb(api):
    api.store.save_cache("cem10", LIST)
    s = api.save_manual({"cash": "1 000", "deposited": 10000, "positions": [
        {"t": "aaa", "kind": "usa", "shares": "2", "open_price": "100"},                  # lista: zamknięcie 120 USD, kurs USD 3,8
        {"t": "bbb.wa", "kind": "gpw", "shares": 10, "open_price": 50},                    # lista: 60 zł
        {"t": "CSPX.UK", "kind": "etf", "shares": 1, "open_price": 800, "price": 900},      # cena wpisana ręcznie, USD
        {"t": "AAA", "kind": "usa", "shares": 2, "open_price": 140},                      # duplikat scalany: 4 akcje po 120
        {"t": "", "kind": "usa", "shares": 5}, {"t": "ZZZ", "kind": "usa", "shares": 0}]})  # puste i zerowe pomijane
    P = s["portfolio"]
    assert P["manual"] and P["label"] == "Ręczne" and P["accounts"] == ["Ręczne"] and s["history"] is None
    by = {r["t"]: r for r in P["rows"]}
    assert set(by) == {"AAA", "BBB", "CSPX"} and by["AAA"]["volume"] == 4 and by["AAA"]["open_price"] == 120.0
    assert by["AAA"]["value"] == 4 * 120.0 * 3.8 and by["BBB"]["value"] == 600.0 and by["CSPX"]["bucket"] == "etf" and by["CSPX"]["value"] == 900 * 3.8
    assert P["cash"] == 1000.0 and P["deposited"] == 10000.0 and P["total"] == 1000 + 1824 + 600 + 3420
    assert by["AAA"]["status"] == "kandydat #1" and s["manual_acct"]["positions"][2]["price_src"] == "ręczna"
    assert s["plan"] is not None and api.state()["manual_acct"]["has"]
    d = api.add_deposit("500")["manual_acct"]
    assert d["cash"] == 1500.0 and d["deposited"] == 10500.0
    assert api.add_deposit(-9999)["manual_acct"]["cash"] == 0.0


def test_manual_prices_refresh_keeps_typed_price(api):
    api.save_manual({"cash": 0, "positions": [{"t": "AAA", "kind": "usa", "shares": 1, "open_price": 100}, {"t": "CSPX.UK", "kind": "etf", "shares": 1, "open_price": 800, "price": 900}]})
    dl = _fake_download({"AAA": [("2026-10-29", 130.0), ("2026-10-30", 131.5)], "CSPX.L": [("2026-10-30", 950.0)], "USDPLN=X": [("2026-10-30", 3.7)]})
    assert api.start_prices(download=dl)
    for _ in range(100):
        if not api.task["busy"]:
            break
        time.sleep(0.02)
    assert api.task["done"].startswith("Ceny odświeżone")
    m = api.state()["manual_acct"]
    by = {p["t"]: p for p in m["positions"]}
    assert by["AAA"]["price"] == 131.5 and by["AAA"]["price_src"] == "Yahoo" and by["CSPX.UK"]["price"] == 900 and m["fx"]["USD"] == 3.7
    assert api.state()["portfolio"]["rows"][0]["fx"] == 3.7


def test_etf_share_targets(api):
    s = api.state()
    assert s["settings"]["etf_pct"] == 30.0 and s["settings"]["gpw_share"] == round(23 / 70 * 100, 1)
    s = api.save_settings({"etf_pct": "40", "gpw_share": 25})
    assert s["settings"]["targets"] == {"etf": 40.0, "usa": 45.0, "gpw": 15.0} and s["settings"]["etf_pct"] == 40.0 and s["settings"]["gpw_share"] == 25.0
    assert api.save_settings({"etf_pct": 100})["settings"]["targets"]["usa"] == 0.0
    assert api.save_settings({"etf_pct": 150})["settings"]["etf_pct"] == 100.0           # ograniczone do 0-100 %
    s = api.save_settings({"etf_pct": 0})
    assert s["settings"]["targets"]["etf"] == 0.0 and abs(s["settings"]["targets"]["usa"] + s["settings"]["targets"]["gpw"] - 100) < 0.01


def test_gpw_members_tickers_only(api):
    """Same tickery (lista albo tekst, .WA ucinane, duplikaty i śmieci pomijane); nazwy znanych spółek zostają z wbudowanego składu."""
    s = api.save_gpw({"rewizja": "2026-12-18", "WIG20": ["ale", "PKO.WA", "pko", "NOWA", "zły ticker!"], "mWIG40": "ABE, ACP;\nXYZ"})
    g = s["gpw"]
    assert g["custom"] and list(g["WIG20"]) == ["ALE", "PKO", "NOWA"] and list(g["mWIG40"]) == ["ABE", "ACP", "XYZ"]
    assert g["WIG20"]["ALE"] == "Allegro.eu S.A." and g["WIG20"]["NOWA"] == "NOWA" and g["mWIG40"]["XYZ"] == "XYZ"


def test_adjust_purchase_on_xtb_account(api):
    """Dzisiejsza transakcja dopisana do konta z raportu: nowa pozycja, dokupienie (średnia cena), sprzedaż, gotówka; nowy raport kasuje starsze wpisy."""
    api.store.save_cache("cem10", LIST)
    s = api.import_xtb(_zip(), "raport.zip")
    base = {r["t"]: r for r in s["portfolio"]["rows"]}
    cash0 = s["portfolio"]["cash"]
    assert base["AAA"]["volume"] == 2 and base["AAA"]["open_price"] == 100.0
    s = api.add_adjust({"t": "ddd", "kind": "usa", "op": "buy", "shares": 1, "price": 10})                       # nowa spółka: 10 USD * 3,8 = 38 zł
    s = api.add_adjust({"t": "AAA", "kind": "usa", "op": "buy", "shares": 1, "price": 130, "amount_pln": 75})   # dokupienie: z konta zeszło 75 zł (kwota podana)
    rows = {r["t"]: r for r in s["portfolio"]["rows"]}
    assert rows["DDD"]["volume"] == 1 and rows["DDD"]["open_price"] == 10 and rows["DDD"]["bucket"] == "usa"
    assert rows["AAA"]["volume"] == 3 and round(rows["AAA"]["open_price"], 4) == round((200 + 130) / 3, 4)
    assert round(s["portfolio"]["cash"], 2) == round(cash0 - 38 - 75, 2) and len(s["adjust"]) == 2
    s = api.add_adjust({"t": "CCC", "kind": "usa", "op": "sell", "shares": 1, "price": 100})                     # sprzedaż całej pozycji CCC
    assert "CCC" not in {r["t"] for r in s["portfolio"]["rows"]} and round(s["portfolio"]["cash"], 2) == round(cash0 - 113 + 380, 2)
    with pytest.raises(ValueError):
        api.add_adjust({"t": "", "kind": "usa", "op": "buy", "shares": 1, "price": 1})
    aid = s["adjust"][0]["id"]
    assert len(api.del_adjust(aid)["adjust"]) == 2
    api.add_adjust({"t": "ZZZ", "kind": "usa", "op": "buy", "shares": 1, "price": 10})
    s = api.import_xtb(_zip(), "raport2.zip")                                  # raport z datą sprzed dopisanych transakcji: wpisy zostają
    assert len(s["adjust"]) == 3
    d = api.store.cache("cem10_adjust")
    d["IKE"][0]["ts"] = "2000-01-01T00:00:00"
    api.store.save_cache("cem10_adjust", d)
    assert len(api.import_xtb(_zip(), "raport3.zip")["adjust"]) == 2          # wpis starszy niż raport znika (raport już go zawiera)
    api.save_manual({"cash": 100, "positions": [], "use": True})
    with pytest.raises(ValueError):
        api.add_adjust({"t": "AAA", "kind": "usa", "op": "buy", "shares": 1, "price": 1})   # konto ręczne edytuje się w tabeli pozycji


def test_clean_bars_fixes_bad_yahoo_candles():
    """Zerowe / puste / absurdalne High i Low nie rozciągają wykresu; poprawne świece zostają bez zmian."""
    nan = float("nan")
    o, h, lo, c = W.clean_bars([100, 100, nan, 100, 100], [110, 110, 105, 900, 105], [90, 1.0, 0, 95, nan], [105, 105, 104, 102, 101])
    assert (o[0], h[0], lo[0], c[0]) == (100, 110, 90, 105)          # poprawna świeca bez zmian
    assert lo[1] == 100 and h[1] == 110                               # Low = 1 przy cenie 100 -> dolna krawędź korpusu
    assert o[2] == 104 and lo[2] == 104 and h[2] == 105               # puste Open i zerowe Low -> zamknięcie
    assert h[3] == 102 and lo[3] == 95                                # High 900 przy cenie ~100 -> górna krawędź korpusu
    assert lo[4] == 100                                               # brak Low -> korpus


def test_yahoo_symbol_accepts_xtb_and_yahoo_tickers():
    assert [W.yahoo_symbol(x) for x in ("CSPX.UK", "cspx.l", "ALE.PL", "ale.wa", "NVDA.US", "NVDA", "BRK.B", "BRK-B", " pko ")] == ["CSPX.L", "CSPX.L", "ALE.WA", "ALE.WA", "NVDA", "NVDA", "BRK-B", "BRK-B", "PKO"]


def test_plan_etf_action_uses_yahoo_symbol(api):
    """Akcja KUP dla ETF-a prowadzi do wykresu po symbolu Yahoo (CSPX.UK -> CSPX.L), a nie po samym CSPX."""
    api.store.save_cache("cem10", LIST)
    api.import_xtb(_zip(), "raport.zip")
    api.save_settings({"deposit": 5000, "etf_pct": 40, "etf": "cspx.uk"})
    etf = [a for a in api.state()["plan"]["actions"] if a["koszyk"] == "etf"]
    assert etf and etf[0]["ticker"] == "CSPX" and etf[0]["yahoo"] == "CSPX.L"
