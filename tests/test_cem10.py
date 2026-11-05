"""Testy CEM10 bez sieci: lista z podmienionymi cenami, kandydaci USA / GPW, tickery trzymanych spółek, decyzja wg SMA 10."""
import datetime as dt

from desktop import cem10


def _px(series, start=dt.date(2024, 11, 28)):
    """Miesięczne wartości -> świece (jedna na miesiąc, adj = raw)."""
    d, y, m = [], start.year, start.month
    for _ in series:
        d.append(f"{y}-{m:02d}-28")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return d, list(series), list(series)


def test_build_leader_market_filter_and_candidates():
    n = 24
    up = [100 * 1.03 ** i for i in range(n)]
    px = {"SPY": _px(up), "QQQ": _px([100] * n), "AAA": _px([50] * 12 + [50 * 1.1 ** i for i in range(12)]), "BBB": _px([50] * n),
          "PKO.WA": _px([10] * 12 + [10 * 1.06 ** i for i in range(12)]), "ALE.WA": _px([10] * n)}
    mem = {"sp": {"AAA": "A Inc", "BBB": "B Inc"}, "nq": {"AAA": "A Inc"}}
    gpw = {"rewizja": "2026-09-18", "WIG20": {"PKO": "PKO BP"}, "mWIG40": {"ALE": "Allegro"}}
    upto = _px(up)[0][-1][:7]
    out = cem10.build(mem, gpw, px, upto, dt.date(2026, 11, 2))
    u, g = out["usa"], out["gpw"]
    assert out["month"] == upto and u["lead"] == "SP" and not u["bear"] and u["n"] == 10 and g["n"] == 5
    assert [r["t"] for r in cem10.usa_candidates(u["rows"], u["lead"])] == ["AAA"]
    assert [r["t"] for r in cem10.gpw_candidates(g["rows"])] == ["PKO"] and g["missing"] == [] and not g["bear"]


def test_closed_months_only_and_sma_in_raw_prices():
    d = ["2026-09-01", "2026-10-01", "2026-11-01"]
    assert cem10.month_closes(d, [1, 2, 3], "2026-10") == {"2026-09": 1.0, "2026-10": 2.0}
    adj = [10] * 6 + [12, 13, 14, 15, 16, 17, 20]
    r = cem10.stock_row("X", "X", adj, [a * 2 for a in adj], sp=True)
    assert r["c"] == 40 and r["r6"] == round(20 / 12 - 1, 4) and r["sma"] == round(sum(adj[-10:]) / 10 * 2, 2)


def test_held_tickers_and_decision():
    assert cem10.parse_tickers("dell, CRWD;ale.wa  pko\nDELL") == ["DELL", "CRWD", "ALE.WA", "PKO"]
    assert cem10.decide({"dist": 0.01}) == "trzymaj" and cem10.decide({"dist": -0.01}) == "sprzedaj" and cem10.decide(None) == "sprawdź"


def test_default_gpw_members():
    g = cem10.GPW_DEFAULT
    assert len(g["WIG20"]) == 20 and len(g["mWIG40"]) == 40 and g["rewizja"]


def test_finviz_sieve_members():
    class R:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass
    calls = []

    def get(url, params=None, **k):
        calls.append(params["f"])
        return R("")
    from desktop import finviz
    orig = finviz.parse_page
    finviz.parse_page = lambda text: ([{"ticker": "BRK.B", "company": "Berkshire"}, {"ticker": "MRNA", "company": "Moderna"}], 2)
    try:
        out = cem10.finviz_members("idx_sp500", get=get, pause=0)
        assert out == {"BRK-B": "Berkshire", "MRNA": "Moderna"} and calls == ["idx_sp500"]
        finviz.parse_page = lambda text: ([], None)
        try:
            cem10.finviz_members("x", get=get, pause=0)
            assert False
        except ValueError:
            pass
    finally:
        finviz.parse_page = orig
    assert cem10.INDEX_FILTERS == ("idx_sp500", "idx_ndx")


def test_index_members_only_for_leader_and_fetch_order(monkeypatch):
    calls = []
    sp = {f"S{i}": "x" for i in range(500)}
    nq = {f"N{i}": "x" for i in range(100)}
    monkeypatch.setattr(cem10, "finviz_members", lambda f, get=None, pause=0.7, **k: calls.append(f) or (sp if f == "idx_sp500" else nq))
    assert cem10.index_members("SP", log=lambda *a: None) == {"sp": sp, "nq": {}} and calls == ["idx_sp500"]
    calls.clear()
    assert cem10.index_members("NDX", log=lambda *a: None) == {"sp": {}, "nq": nq} and calls == ["idx_ndx"]
    monkeypatch.setattr(cem10, "finviz_members", lambda f, get=None, pause=0.7, **k: {"A": "a"})
    try:
        cem10.index_members("SP", log=lambda *a: None)
        assert False
    except ValueError:
        pass
    # fetch: najpierw SPY + QQQ, potem skład jednego indeksu, potem reszta
    n, order = 24, []
    monkeypatch.setattr(cem10, "finviz_members", lambda f, get=None, pause=0.7, **k: calls.append(f) or {f"N{i}": "x" for i in range(100)})

    def fake_download(tickers, log=print, progress=None):
        order.append(list(tickers))
        mk = {"SPY": [100] * n, "QQQ": [100 * 1.03 ** i for i in range(n)], "N0": [50] * 12 + [50 * 1.1 ** i for i in range(12)]}
        return {t: _px(mk.get(t, [10] * n)) for t in tickers}
    monkeypatch.setattr(cem10, "download", fake_download)
    calls.clear()
    out = cem10.fetch({"rewizja": "x", "WIG20": {}, "mWIG40": {}}, today=dt.date(2026, 11, 2), log=lambda *a: None)
    assert order[0] == ["SPY", "QQQ"] and len(order[1]) == 100 and calls == ["idx_ndx"]
    assert out["usa"]["lead"] == "NDX" and out["usa"]["index"] == {"lead": "NDX", "n": 100}
    assert [r["t"] for r in cem10.usa_candidates(out["usa"]["rows"], "NDX")] == ["N0"]
