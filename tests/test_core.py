"""Testy bez sieci: Green Line, stan GLB, MACD, obrót, warunki, parser Finviz, fundamenty SEC i synchronizacja z podmienionymi źródłami."""
import datetime as dt

import pytest

from desktop import calc, finviz, prices, sec, sync
from desktop.store import Store


def test_green_line_needs_three_closed_months_and_keeps_old_line():
    assert calc.green_line([10, 12, 11, 11]) == (None, None)            # rekord 12 stoi dopiero 2 miesiące
    assert calc.green_line([10, 12, 11, 11, 11]) == (12, 1)             # ≥ 3 miesiące -> linia
    assert calc.green_line([10, 12, 11, 11, 11, 15, 14]) == (12, 1)     # nowy rekord 15 jeszcze nie stoi 3 miesięcy: obowiązuje stara linia
    assert calc.green_line([10, 12, 11, 11, 11, 15, 14, 14, 14]) == (15, 5)
    assert calc.green_line([10, 12, 11, 11, 11, 11, 11, 11, 11])[0] == 12   # „3 lub więcej” — rekord stojący dłużej nadal jest linią


def test_glb_state():
    assert calc.glb_state(105, 99, 100) == "WYBICIE"
    assert calc.glb_state(105, 103, 100) == "SYGNAŁ"
    assert calc.glb_state(110, 103, 100) == "SYGNAŁ"
    assert calc.glb_state(111, 103, 100) == "NAD"
    assert calc.glb_state(99, 103, 100) == "POD"
    assert calc.glb_state(99, 103, None) == "BRAK"


def test_macd_cross_and_stop_is_low_of_cross_week():
    closes = [float(i) for i in range(1, 60)] + [60 - i * 2.0 for i in range(1, 15)]
    lows = [c - 1 for c in closes]
    _, _, h = calc.macd(closes)
    cross = calc.macd_cross_down(h)
    assert cross and h[cross[-1]] < 0 <= h[cross[-1] - 1]
    info = calc.macd_info(closes, lows)
    assert info["state"] == "pod" and info["stop"] == lows[cross[-1]]


def test_turnover_and_conditions():
    assert calc.turnover([10, 10, 10, 10], [5e7] * 4) == pytest.approx(1e8)
    good = {"turnover": 60e6, "rev_rr": 20, "dopm": 4}
    assert calc.passes(good)
    for k, v in (("turnover", 40e6), ("rev_rr", 10), ("dopm", 2), ("dopm", None)):
        assert not calc.passes({**good, k: v})


def test_build_row():
    w = {"d": ["2026-01-05"] * 40, "o": [1] * 40, "h": [1] * 40, "l": [1] * 40, "c": [100.0] * 38 + [99.0, 104.0], "v": [3e6] * 40}
    row = calc.build_row({"ticker": "X"}, w, [50, 100, 90, 90, 90, 95], {"rev_rr": 30, "dopm": 5})
    assert row["glb"] == 100 and row["glb_state"] == "WYBICIE" and row["glb_pct"] == pytest.approx(4)
    assert row["ok"] and row["turnover"] == pytest.approx(104 * 3e6 / 5, rel=0.05)


NEW_LAYOUT = """<div>#1 / 2 Total</div>
<div class="fv-table_row" data-row-key="NVDA"><div data-column-id="company">NVIDIA Corp</div><div data-column-id="sector">Technology</div>
<div data-column-id="marketCap">4.5T</div></div>
<div class="fv-table_row" data-row-key="MU"><div data-column-id="company">Micron</div><div data-column-id="marketCap">120.1B</div></div>"""


def test_finviz_parse_and_fetch_pages():
    rows, total = finviz.parse_page(NEW_LAYOUT)
    assert total == 2 and rows[0] == {"ticker": "NVDA", "company": "NVIDIA Corp", "sector": "Technology", "market_cap": 4.5e12}
    assert rows[1]["market_cap"] == pytest.approx(120.1e9)

    class R:
        text = NEW_LAYOUT

        def raise_for_status(self):
            pass
    out, total = finviz.fetch("x", pause=0, log=lambda s: None, get=lambda *a, **k: R())
    assert [r["ticker"] for r in out] == ["NVDA", "MU"] and total == 2


def _q(start, end, val):
    return {"start": start, "end": end, "val": val, "filed": "2026-01-01"}


def test_sec_metrics_quarter_vs_year_ago_q4_from_annual():
    rev = [_q("2025-01-01", "2025-03-31", 100), _q("2025-04-01", "2025-06-30", 110), _q("2025-07-01", "2025-09-30", 120),
           _q("2025-01-01", "2025-12-31", 470), _q("2026-01-01", "2026-03-31", 150)]   # Q4 2025 = 470 − 330 = 140
    op = [_q("2025-01-01", "2025-03-31", 10), _q("2025-04-01", "2025-06-30", 11), _q("2025-07-01", "2025-09-30", 12),
          _q("2025-01-01", "2025-12-31", 47), _q("2026-01-01", "2026-03-31", 30)]
    facts = {"us-gaap": {"Revenues": {"units": {"USD": rev}}, "OperatingIncomeLoss": {"units": {"USD": op}}}}
    m = sec.metrics(facts)
    assert m["quarter"] == "2026-03-31" and m["rev_rr"] == pytest.approx(50)
    assert m["opm"] == pytest.approx(20) and m["dopm"] == pytest.approx(10)


def test_sec_update_uses_cache(monkeypatch):
    cache = {"OLD": {"at": dt.date.today().isoformat(), "rev_rr": 1}}
    monkeypatch.setattr(sec, "cik_map", lambda ua: {"NEW": 1})
    monkeypatch.setattr(sec, "_get", lambda url, ua: {"facts": {}})
    assert sec.update(["OLD", "NEW", "ZZZ"], cache, log=lambda s: None, pause=0) == ["NEW"]
    assert cache["OLD"]["rev_rr"] == 1 and "at" in cache["ZZZ"]


def test_monthly_cache_only_refetches_after_month_close(monkeypatch):
    calls = []

    class F:
        empty = False
    monkeypatch.setattr(prices, "_yf", lambda: type("Y", (), {"download": staticmethod(lambda part, **k: calls.append(part) or F())}))
    monkeypatch.setattr(prices, "_frames", lambda df, part: {})
    cache = {"A": {"m": [], "upto": "2026-09"}}
    prices.monthly(["A", "B"], cache, log=lambda s: None, today=dt.date(2026, 10, 20))
    assert calls == [["B"]]


def test_sync_run_with_fake_sources(tmp_path):
    store = Store(tmp_path)
    w = {"d": ["2026-01-05"] * 40, "o": [1] * 40, "h": [1] * 40, "l": [1] * 40, "c": [100.0] * 39 + [104.0], "v": [5e6] * 40}

    def monthly(ts, cache, log):
        for t in ts:
            cache[t] = {"m": [["2025-01", 50], ["2025-02", 100], ["2025-03", 90], ["2025-04", 90], ["2025-05", 90]], "upto": "2025-05"}

    def fund(ts, cache, ua, log):
        for t in ts:
            cache[t] = {"at": "2026-10-20", "rev_rr": 25, "dopm": 6}
    rows = sync.run(store, log=lambda s: None, fetch_list=lambda f, log: ([{"ticker": "A"}, {"ticker": "B"}], 2),
                    weekly=lambda ts, log: {"A": w, "B": {**w, "v": [1e3] * 40}}, monthly=monthly, fund=fund)
    a = next(r for r in rows if r["ticker"] == "A")
    assert a["ok"] and a["glb_state"] == "SYGNAŁ"
    assert not next(r for r in rows if r["ticker"] == "B")["ok"]   # za mały obrót
    assert Store(tmp_path).rows and Store(tmp_path).weekly("A")["c"][-1] == 104.0
