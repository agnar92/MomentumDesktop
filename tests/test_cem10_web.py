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
    assert s["gpw"]["custom"] and s["gpw"]["WIG20"] == {"PKO": "PKO BP"} and s["gpw"]["mWIG40"] == {"ALE": "ALE"}
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
