"""Testy bez sieci: Green Line, stan GLB, MACD, obrót, warunki, parser Finviz, fundamenty SEC i synchronizacja z podmienionymi źródłami."""
import datetime as dt
import math

import pytest

from desktop import calc, estimates, finviz, prices, sec, sync
from desktop.store import Store

_D = [(dt.date(2025, 1, 6) + dt.timedelta(weeks=i)).isoformat() for i in range(60)]
W = {"d": _D, "o": [1] * 60, "h": [1] * 60, "l": [1] * 60, "c": [50.0] * 19 + [100.0] * 40 + [104.0], "v": [1e7] * 60}   # +108 % w 52 tyg.
EST = {"surp": [["2025-11-10", 4.0], ["2026-02-09", 8.0]], "rev90": 12.0}   # 2 raporty powyżej konsensusu, ostatni w ostatnich tygodniach W
SPY = {"d": _D, "o": [1] * 60, "h": [1] * 60, "l": [1] * 60, "c": [400.0] * 60, "v": [1e7] * 60}


def test_green_line_needs_peak_plus_two_closed_months_and_keeps_old_line():
    assert calc.green_line([10, 12, 11]) == (None, None)                # rekord 12 + 1 miesiąc = 2 świece
    assert calc.green_line([10, 12, 11, 11]) == (12, 1)                 # szczyt + 2 zamknięte miesiące = 3 świece -> linia
    assert calc.green_line([10, 12, 11, 11, 11, 15, 14]) == (12, 1)     # nowy rekord 15 ma szczyt + 1 miesiąc: obowiązuje stara linia
    assert calc.green_line([10, 12, 11, 11, 11, 15, 14, 14]) == (15, 5)  # nowy rekord 15 + 2 miesiące: zastępuje starą linię
    assert calc.green_line([10, 12, 11, 11, 11, 11, 11, 11, 11])[0] == 12   # rekord stojący dłużej nadal jest linią


def test_glb_state():
    assert calc.glb_state(105, 99, 100) == "WYBICIE"
    assert calc.glb_state(105, 103, 100) == "SYGNAŁ"
    assert calc.glb_state(110, 103, 100) == "SYGNAŁ"
    assert calc.glb_state(111, 103, 100) == "NAD"
    assert calc.glb_state(125, 99, 100) == "WYBICIE"                    # tydzień przebicia: dowolnie wysoko = mocne wybicie
    assert calc.glb_state(105, 103, 100, armed=False) == "NAD"          # powrót w strefę po wyjściu wyżej: kupowanie spadku, nie sygnał


def test_glb_armed_only_after_breakout_from_below_and_expires_after_a_run():
    assert calc.glb_armed([90, 95, 101, 104], 100)                       # zamknięcie pod linią, potem przebicie i kolejny tydzień w strefie
    assert calc.glb_armed([90, 105, 95, 103], 100)                       # zeszła pod linię i przebiła ponownie bez rajdu > 10 %: nadal sygnał
    assert not calc.glb_armed([90, 101, 115, 108], 100)                  # wyszła > 10 % nad linię i wróciła w strefę (CDLX 03/2020)
    assert not calc.glb_armed([90, 101, 115, 98], 100)                   # po rajdzie > 10 % linia wygasa także po zejściu pod nią
    assert not calc.glb_armed([105, 108, 104], 100)                      # nigdy pod linią w oknie
    assert not calc.glb_armed([90, 95], None)
    row = calc.build_row({"ticker": "X"}, {"d": [f"2026-01-{i + 1:02d}" for i in range(4)], "o": [0] * 4, "h": [0] * 4, "l": [1] * 4,
                                           "c": [90, 115, 108, 106], "v": [1] * 4}, [100] * 5, None)
    assert row["glb"] == 100 and row["glb_state"] == "NAD"
    row = calc.build_row({"ticker": "X"}, {"d": [f"2026-01-{i + 1:02d}" for i in range(3)], "o": [0] * 3, "h": [0] * 3, "l": [1] * 3,
                                           "c": [90, 95, 104], "v": [1] * 3}, [100] * 5, None)
    assert row["glb_state"] == "WYBICIE"


def test_fresh_blue_dot_only_in_last_weeks():
    n = 160
    c = [50 + i * 0.4 for i in range(n)]
    c[150:154] = [c[149] - 3, c[149] - 6, c[149] - 7, c[149] - 1]       # korekta w trendzie, potem odbicie: Stochastic przecina 20 w górę
    d = {"d": [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)], "h": [x + 1 for x in c], "l": [x - 1 for x in c], "c": c}
    assert calc.fresh_blue_dot(d, 40, weeks=10) == d["d"][153]
    assert calc.fresh_blue_dot(d, 40, weeks=5) is None                    # kropka starsza niż 5 tygodni
    assert calc.fresh_blue_dot(d, 1e9) is None and calc.fresh_blue_dot(None, 40) is None
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
    good = {"turnover": 120e6, "rev_rr": 20, "dopm": 4}
    assert calc.passes(good) and calc.passes({**good, "turnover": 1e3})   # obrót nie jest warunkiem (filtr w Finviz)
    # domyślnie (badanie 2011–2025) RS, P/S i beat2 nie blokują
    assert calc.passes({**good, "rs": 10, "ps": 40, "beat2": False})
    for k, v in (("rev_rr", 10), ("rev_rr", None), ("dopm", 2), ("dopm", None)):
        assert not calc.passes({**good, k: v})


def test_strategy_conditions_are_configurable():
    row = {"rev_rr": 20, "dopm": 4, "ps": 18, "rs": 55, "beat2": True}
    cfg = calc.normalize_conditions()
    assert not cfg["ps"]["enabled"] and not cfg["rs"]["enabled"] and not cfg["beat2"]["enabled"]
    for k in ("ps", "rs"):
        cfg[k]["enabled"] = True
    assert calc.passes(row, cfg)

    cfg["rev_growth"]["threshold"] = 25
    assert not calc.passes(row, cfg)
    cfg["rev_growth"]["enabled"] = False
    assert calc.passes(row, cfg)

    cfg["op_margin"]["threshold"] = 5
    assert not calc.passes(row, cfg)
    cfg["op_margin"]["enabled"] = False
    assert calc.passes(row, cfg)

    cfg["ps"]["threshold"] = 10
    assert not calc.passes(row, cfg)
    cfg["ps"]["enabled"] = False
    assert calc.passes(row, cfg)

    cfg["rs"]["threshold"] = 60
    assert not calc.passes(row, cfg)
    cfg["rs"]["enabled"] = False
    assert calc.passes(row, cfg)

    cfg["beat2"]["enabled"] = True
    assert not calc.passes({**row, "beat2": False}, cfg)
    cfg["beat2"]["enabled"] = False
    assert calc.passes({**row, "beat2": False}, cfg)

    assert calc.passes({}) is False                    # domyślnie brak danych nie spełnia wymagań
    assert calc.passes({}, {key: {"enabled": False} for key in calc.DEFAULT_CONDITIONS}) is True


def test_strategy_condition_normalization_falls_back_for_invalid_thresholds():
    cfg = calc.normalize_conditions({
        "rev_growth": {"enabled": False, "threshold": "nan"},
        "op_margin": {"threshold": "invalid"},
        "ps": {"threshold": -2},
        "unknown": {"enabled": False},
    })
    assert cfg["rev_growth"] == {"enabled": False, "threshold": calc.MIN_REV_GROWTH}
    assert cfg["op_margin"] == {"enabled": True, "threshold": calc.MIN_DOPM}
    assert cfg["ps"] == {"enabled": False, "threshold": calc.MAX_PS}
    assert set(cfg) == set(calc.DEFAULT_CONDITIONS)


def test_build_row():
    w = {"d": ["2026-01-05"] * 40, "o": [1] * 40, "h": [1] * 40, "l": [1] * 40, "c": [100.0] * 38 + [99.0, 104.0], "v": [3e6] * 40}
    row = calc.build_row({"ticker": "X"}, w, [50, 100, 90, 90, 90, 95], {"rev_rr": 30, "dopm": 5})
    assert row["glb"] == 100 and row["glb_state"] == "WYBICIE" and row["glb_pct"] == pytest.approx(4)
    assert row["turnover"] == pytest.approx(104 * 3e6 / 5, rel=0.05)
    assert row["rs"] is None and row["ok"]              # brak SPY -> brak RS, ale RS domyślnie nie jest warunkiem
    r = calc.build_row({"ticker": "Y"}, W, [50, 100, 90, 90, 90, 95], {"rev_rr": 30, "dopm": 5}, SPY, EST)
    assert r["rs"] == pytest.approx(108) and r["ok"] and r["glb_state"] == "SYGNAŁ"
    assert r["surp"] == 8.0 and r["surp_prev"] == 4.0 and r["beat2"] and r["eps_rev"] == 12.0
    valued = calc.build_row({"ticker": "Z", "peg": 2.0, "forward_pe": 30.0, "dividend_yield": 2.0},
                            W, [50, 100, 90, 90, 90, 95], {"rev_rr": 30, "dopm": 5}, SPY, EST)
    assert valued["peg"] == 2.0 and valued["pegy"] == pytest.approx(1.76)


def test_pegy_ratio_adds_dividend_yield_to_implied_growth():
    # Forward P/E 30 / PEG 2 = implied EPS growth 15%; dividend yield 2% => 30 / 17.
    assert calc.pegy_ratio(2.0, 30.0, 2.0) == pytest.approx(1.76)
    assert calc.pegy_ratio(1.2, 24.0, 0.0) == pytest.approx(1.2)
    assert calc.pegy_ratio(None, 24.0, 2.0) is None
    assert calc.pegy_ratio(0.0, 24.0, 2.0) is None
    assert calc.pegy_ratio(1.2, None, 2.0) is None
    assert calc.pegy_ratio(1.2, 24.0, None) is None


def test_peg_and_pegy_are_visible_scanner_columns():
    from desktop.app import COLUMNS, cell, pass_filters

    by_key = {column[0]: column for column in COLUMNS}
    assert by_key["peg"][1] == "PEG" and by_key["pegy"][1] == "PEGY"
    assert cell(1.236, by_key["peg"][3]) == "1.24"
    assert cell(0.987, by_key["pegy"][3]) == "0.99"
    assert pass_filters({"peg": 1.2}, {"peg": {"max": 1.5}})
    assert not pass_filters({"pegy": None}, {"pegy": {"max": 1.5}})


def test_estimates_refresh_legacy_cache_without_revenue_surprises():
    today = dt.date(2026, 10, 22)
    cache = {"A": {"at": today.isoformat(), "surp": [], "rev90": None},
             "B": {"at": today.isoformat(), "surp": [], "revenue_surp": [], "eps_q": [], "rev90": None}}   # stary wpis z upside nie wymusza pobrania
    fetched = {"surp": [], "revenue_surp": [["2026-10-01", 3.0]], "eps_q": [], "rev90": None}
    got = estimates.update(["A", "B"], cache, today=today, pause=0, fetch_one=lambda ticker: fetched)
    assert got == ["A"] and cache["A"]["revenue_surp"] == [["2026-10-01", 3.0]]


def test_rel_strength_vs_spy():
    spy = {"d": W["d"], "c": [400.0] * 30 + [480.0] * 30}               # SPY +20 % w 52 tyg.
    assert calc.rel_strength(W, spy) == pytest.approx(108 - 20)
    assert calc.rel_strength(W, None) is None and calc.rel_strength({**W, "c": W["c"][-40:], "d": W["d"][-40:]}, spy) is None


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


VALUATION_LAYOUT = """<div>#1 / 2 Total</div>
<div class="fv-table_row" data-row-key="NVDA"><div data-column-id="forwardPE">30.0</div><div data-column-id="peg">2.0</div></div>
<div class="fv-table_row" data-row-key="MU"><div data-column-id="forwardPE">24.0</div><div data-column-id="peg">1.2</div></div>"""

FINANCIAL_LAYOUT = """<div>#1 / 2 Total</div>
<div class="fv-table_row" data-row-key="NVDA"><div data-column-id="dividend">2.00%</div><div data-column-id="roe">20.0%</div></div>
<div class="fv-table_row" data-row-key="MU"><div data-column-id="dividend">-</div><div data-column-id="roe">10.0%</div></div>"""

OWNERSHIP_LAYOUT = """<div>#1 / 2 Total</div>
<div class="fv-table_row" data-row-key="NVDA">
  <div data-column-id="outstanding">24.5B</div><div data-column-id="float">23.9B</div>
  <div data-column-id="instOwn">65.00%</div><div data-column-id="instTrans">8.25%</div>
  <div data-column-id="shortFloat">1.25%</div><div data-column-id="shortRatio">1.2</div>
</div>
<div class="fv-table_row" data-row-key="MU">
  <div data-column-id="outstanding">1.12B</div><div data-column-id="float">1.08B</div>
  <div data-column-id="instOwn">72.00%</div><div data-column-id="instTrans">-2.50%</div>
  <div data-column-id="shortFloat">3.20%</div><div data-column-id="shortRatio">2.1</div>
</div>"""


def test_finviz_parser_normalizes_valuation_and_dividend_column_id_aliases():
    page = """<div>#1 / 1 Total</div>
    <div class="fv-table_row" data-row-key="NVDA">
      <div data-column-id="forwardpe">30.0</div>
      <div data-column-id="pegRatio">2.0</div>
    </div>
    <div class="fv-table_row" data-row-key="KO">
      <div data-column-id="fwdPe">24.0</div>
      <div data-column-id="PEG">1.2</div>
      <div data-column-id="dividendYield">2.00%</div>
      <div data-column-id="instOwn">60.25%</div>
      <div data-column-id="instTrans">5.80%</div>
      <div data-column-id="float">12.5M</div>
      <div data-column-id="roe">17.5%</div>
    </div>"""
    rows, total = finviz.parse_page(page)
    assert total == 1
    assert rows[0]["forward_pe"] == pytest.approx(30.0)
    assert rows[0]["peg"] == pytest.approx(2.0)
    assert rows[1]["forward_pe"] == pytest.approx(24.0)
    assert rows[1]["peg"] == pytest.approx(1.2)
    assert rows[1]["dividend_yield"] == pytest.approx(2.0)
    assert rows[1]["institutional_ownership"] == pytest.approx(60.25)
    assert rows[1]["institutional_transactions"] == pytest.approx(5.8)
    assert rows[1]["shares_float"] == pytest.approx(12.5e6)
    assert rows[1]["roe"] == pytest.approx(17.5)


def test_finviz_fetch_merges_peg_and_dividend_yield_by_ticker():
    class R:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    pages = {"111": NEW_LAYOUT, "121": VALUATION_LAYOUT, "161": FINANCIAL_LAYOUT, "131": OWNERSHIP_LAYOUT}
    requests_seen = []
    def get(_url, params, **_kwargs):
        requests_seen.append(dict(params))
        return R(pages[params["v"]])

    rows, total = finviz.fetch("x", max_tickers=20, pause=0, log=lambda _s: None, get=get)
    assert total == 2 and [row["ticker"] for row in rows] == ["NVDA", "MU"]
    nvda, mu = rows
    assert nvda["peg"] == pytest.approx(2.0) and nvda["forward_pe"] == pytest.approx(30.0)
    assert nvda["dividend_yield"] == pytest.approx(2.0)
    assert nvda["roe"] == pytest.approx(20.0)
    assert nvda["institutional_ownership"] == pytest.approx(65.0)
    assert nvda["institutional_transactions"] == pytest.approx(8.25)
    assert nvda["shares_float"] == pytest.approx(23.9e9)
    assert calc.pegy_ratio(nvda["peg"], nvda["forward_pe"], nvda["dividend_yield"]) == pytest.approx(1.76)
    assert mu["peg"] == pytest.approx(1.2) and mu["dividend_yield"] == 0.0
    assert mu["institutional_transactions"] == pytest.approx(-2.5)
    assert calc.pegy_ratio(mu["peg"], mu["forward_pe"], mu["dividend_yield"]) == pytest.approx(1.2)
    assert any(request.get("v") == "121" and request.get("t") == "NVDA,MU" for request in requests_seen)
    assert any(request.get("v") == "161" and request.get("t") == "NVDA,MU" for request in requests_seen)
    assert any(request.get("v") == "131" and request.get("t") == "NVDA,MU" for request in requests_seen)


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
    assert "rev_rr1" not in m and [q["rev"] for q in m["qs"]] == [100, 110, 120, 140, 150] and m["qs"][-1]["rev_rr"] == pytest.approx(50)


def test_slowdown():
    assert calc.slowdown({"accel": 4, "dgm": 1}) is None
    assert calc.slowdown({"accel": -12, "dgm": 0.5}) == "HAMUJE" and calc.slowdown({"accel": -12, "dgm": -1}) == "HAMUJE+MB"


def test_sec_update_uses_cache(monkeypatch):
    cache = {"OLD": {"at": dt.date.today().isoformat(), "rev_rr": 1, "v": sec.SEC_VERSION},
             "V1": {"at": dt.date.today().isoformat(), "rev_rr": 1}}      # świeży, ale bez historii kwartałów -> pobierz ponownie
    monkeypatch.setattr(sec, "cik_map", lambda ua: {"NEW": 1, "V1": 2})
    monkeypatch.setattr(sec, "_get", lambda url, ua: {"facts": {}})
    assert sec.update(["OLD", "NEW", "ZZZ", "V1"], cache, log=lambda s: None, pause=0) == ["NEW", "V1"]
    assert cache["OLD"]["rev_rr"] == 1 and "at" in cache["ZZZ"]


class _Frame(dict):
    empty = False

    def dropna(self, subset=None):
        return self


def _yf_fake(monkeypatch, calls, frames):
    monkeypatch.setattr(prices, "_yf", lambda: type("Y", (), {"download": staticmethod(lambda part, **k: calls.append((list(part), k["period"])) or "df")}))
    monkeypatch.setattr(prices, "_frames", lambda df, part: {t: frames[t] for t in part if t in frames})


def test_monthly_updates_only_new_months_and_uses_high(monkeypatch):
    import pandas as pd
    calls = []
    hi = pd.Series([10.0, 12.0], index=pd.to_datetime(["2026-08-01", "2026-09-01"]))
    cache = {"A": {"h": [["2026-07", 9.0], ["2026-08", 10.0]], "upto": "2026-08", "raw": 1}, "C": {"h": [], "upto": "2026-09", "raw": 1},
             "B": {"m": [["2026-09", 1.0]], "upto": "2026-09"},     # stary wpis z zamknięciami (nawet aktualny) -> cała historia
             "D": {"h": [["2026-09", 1.0]], "upto": "2026-09"}}     # aktualny, ale ze skorygowanymi cenami (bez "raw") -> cała historia
    _yf_fake(monkeypatch, calls, {"A": {"High": hi}, "B": {"High": hi}, "D": {"High": hi}})
    prices.monthly(["A", "B", "C", "D"], cache, log=lambda s: None, today=dt.date(2026, 10, 20))
    assert calls == [(["A"], "6mo"), (["B", "D"], "max")]            # C aktualne: bez zapytania
    assert cache["A"] == {"h": [["2026-07", 9.0], ["2026-08", 10.0], ["2026-09", 12.0]], "upto": "2026-09", "raw": 1}
    assert prices.monthly_highs(cache["B"]) == [10.0, 12.0]


def test_monthly_refetches_full_history_when_prices_changed(monkeypatch):
    import pandas as pd
    calls = []
    _yf_fake(monkeypatch, calls, {"A": {"High": pd.Series([5.0, 6.0], index=pd.to_datetime(["2026-08-01", "2026-09-01"]))}})
    cache = {"A": {"h": [["2026-08", 10.0]], "upto": "2026-08", "raw": 1}}   # split 2:1 — 10 -> 5
    prices.monthly(["A"], cache, log=lambda s: None, today=dt.date(2026, 10, 20))
    assert calls == [(["A"], "6mo"), (["A"], "max")] and cache["A"]["h"] == [["2026-08", 5.0], ["2026-09", 6.0]]


def test_merge_weekly_appends_new_weeks_and_detects_adjusted_history():
    old = {k: [1, 2, 3] for k in "ohlcv"} | {"d": ["2026-09-28", "2026-10-05", "2026-10-12"]}
    new = {k: [3.01, 4] for k in "ohlcv"} | {"d": ["2026-10-12", "2026-10-19"]}
    m = prices.merge_weekly(old, new)
    assert m["d"] == ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"] and m["c"] == [1, 2, 3.01, 4]
    assert prices.merge_weekly(old, {**new, "c": [1.5, 2]}) is None
    assert prices.merge_weekly(old, new, keep=2)["d"] == ["2026-10-12", "2026-10-19"]


def test_weekly_fetches_only_recent_weeks_for_cached(monkeypatch):
    import pandas as pd
    calls = []
    idx = pd.to_datetime(["2026-10-12", "2026-10-19"])
    f = {"Open": [3.0, 4.0], "High": [3.0, 4.0], "Low": [3.0, 4.0], "Close": [3.0, 4.0], "Volume": [1.0, 1.0]}
    df = pd.DataFrame(f, index=idx)
    full = pd.DataFrame({k: [1.0] * 12 for k in f}, index=pd.date_range("2026-08-03", periods=12, freq="W-MON"))
    monkeypatch.setattr(prices, "_yf", lambda: type("Y", (), {"download": staticmethod(lambda part, **k: calls.append((list(part), k["period"])) or k["period"])}))
    monkeypatch.setattr(prices, "_frames", lambda d, part: {t: (full if d == "3y" else df) for t in part})
    cache = {"A": {k: [1, 2, 3] for k in "ohlcv"} | {"d": ["2026-09-28", "2026-10-05", "2026-10-12"], "raw": 1},
             "S": {k: [1, 2, 3] for k in "ohlcv"} | {"d": ["2026-09-28", "2026-10-05", "2026-10-12"]}}   # bez "raw": ceny skorygowane -> 3 lata
    out = prices.weekly(["A", "N", "S"], log=lambda s: None, cache=cache, today=dt.date(2026, 10, 20))
    assert calls == [(["A"], "1mo"), (["N", "S"], "3y")] and out["A"]["raw"] == 1
    assert out["A"]["c"] == [1, 2, 3.0, 4.0] and len(out["N"]["c"]) == 12


def test_sync_run_with_fake_sources(tmp_path):
    store = Store(tmp_path)
    store.select("Bezpieczny (backtest)")
    w = W

    def monthly(ts, cache, log, progress=None):
        for t in ts:
            cache[t] = {"h": [["2025-01", 50], ["2025-02", 100], ["2025-03", 90], ["2025-04", 90], ["2025-05", 90]], "upto": "2025-05", "raw": 1}

    def fund(ts, cache, ua, log, progress=None):
        for t in ts:
            cache[t] = {"at": "2026-10-20", "rev_rr": 25, "dopm": 6}
    steps = []
    rows = sync.run(store, log=lambda s: None, fetch_list=lambda f, max_tickers, log, progress: ([{"ticker": "A"}, {"ticker": "B"}], 2),
                    weekly=lambda ts, log, cache, progress: {"A": w, "B": {**w, "v": [1e3] * 60}, "SPY": SPY}, monthly=monthly, fund=fund,
                    est=lambda ts, cache, log: cache.update({t: {"at": "2026-10-20", **EST} for t in ts}),
                    progress=lambda f, st: steps.append((round(f, 2), st)))
    assert [f for f, _ in steps] == [0.0, 0.15, 0.4, 0.6, 1.0] and steps[-1][1] == "Gotowe"
    a = next(r for r in rows if r["ticker"] == "A")
    assert a["ok"] and a["glb_state"] == "SYGNAŁ"
    assert a["rvol_w"] == pytest.approx(1.0) and "rvol_d" not in a and a["cc52w"] == pytest.approx(calc.price_ratio(w["c"])) and a["mom121"] == calc.momentum_12_1(w["c"]) and a["mom6"] == calc.momentum_6(w["c"]) and a["tempo"] == calc.tempo_margin(w["c"])   # RVol tygodniowy; C/C[52 tyg.], Momentum 12-1 i 6 mies., TEMPO z tygodniowych zamknięć
    assert next(r for r in rows if r["ticker"] == "B")["ok"]       # mały obrót nie blokuje (płynność = filtr Finviz)
    assert Store(tmp_path).rows and Store(tmp_path).weekly("A")["c"][-1] == 104.0


def test_scanners_have_own_lists_and_share_weekly(tmp_path):
    store = Store(tmp_path)
    names = [x["name"] for x in store.settings["scanners"]]
    assert names[0] == "Sektory top 3 (RS)" and store.settings["scanner"] == names[0] and names[1] == "Bezpieczny (backtest)" and len(names) == 5
    w = {"d": ["2026-01-05"] * 40, "o": [1] * 40, "h": [1] * 40, "l": [1] * 40, "c": [100.0] * 40, "v": [5e6] * 40}
    store.save_scan([{"ticker": "A"}], {"A": w}, "x")
    store.select(names[1])
    assert store.rows == [] and store.weekly("A")                     # inny skaner: pusta lista, świece wspólne
    store.save_scan([{"ticker": "B"}], {"B": w}, "y")
    store.select(names[0])
    s2 = Store(tmp_path)
    assert [r["ticker"] for r in s2.rows] == ["A"] and set(s2.series) == {"A", "B"}


def test_old_settings_filter_becomes_first_scanner(tmp_path):
    from desktop import store as S
    S.write(tmp_path / "settings.json", {"filters": "cap_largeover"})
    S.write(tmp_path / "scan.json", {"at": "a", "rows": [{"ticker": "OLD"}], "series": {"OLD": {"c": [1]}}})
    store = Store(tmp_path)
    assert store.settings["scanners"][0] == {"name": "Mój filtr", "filters": "cap_largeover", "max_tickers": 1500}
    assert [r["ticker"] for r in store.rows] == ["OLD"] and store.weekly("OLD")


def test_monthly_highs_ignores_dividend_adjusted_entries():
    assert prices.monthly_highs({"h": [["2026-09", 5.0]], "upto": "2026-09"}) == []
    assert prices.monthly_highs({"h": [["2026-09", 5.0]], "upto": "2026-09", "raw": 1}) == [5.0]


def test_conditions_cut_rgti_and_expensive():
    """RGTI: „Δ marży” +558 pp przy przychodach 5 mln $ — odpada na P/S (≈ 200); drogie (P/S ≥ 20) odpadają; brak kapitalizacji: cena × akcje."""
    f = {"rev_rr": 30, "dopm": 12, "ttm_rev": 300e6}
    assert calc.build_row({"ticker": "A", "market_cap": 3e9}, W, [50, 100, 90, 90, 90], f, SPY, EST)["ok"]      # P/S 10
    assert calc.build_row({"ticker": "B", "market_cap": 9e9}, W, [50, 100, 90, 90, 90], f, SPY)["ok"]          # P/S domyślnie nie blokuje
    with_ps = {**calc.normalize_conditions(), "ps": {"enabled": True, "threshold": calc.MAX_PS}}
    assert not calc.build_row({"ticker": "B", "market_cap": 9e9}, W, [50, 100, 90, 90, 90], f, SPY, conditions=with_ps)["ok"]   # P/S 30
    rgti = calc.build_row({"ticker": "RGTI", "market_cap": 4e9}, W, [], {"rev_rr": 185, "dopm": 558, "ttm_rev": 20e6}, SPY, conditions=with_ps)
    assert rgti["ps"] == 200 and not rgti["ok"]
    assert calc.build_row({"ticker": "D"}, W, [], {**f, "shares": 60e6}, SPY)["ps"] == pytest.approx(104 * 60e6 / 300e6)


def test_sec_metrics_ttm_revenue_and_dilution():
    rev = [_q("2025-01-01", "2025-03-31", 100), _q("2025-04-01", "2025-06-30", 110), _q("2025-07-01", "2025-09-30", 120),
           _q("2025-10-01", "2025-12-31", 140), _q("2026-01-01", "2026-03-31", 150)]
    op = [dict(x, val=x["val"] / 10) for x in rev]
    sh = [_q("2025-01-01", "2025-03-31", 100), _q("2026-01-01", "2026-03-31", 110), _q("2025-01-01", "2025-12-31", 105)]   # roczna średnia nie daje Q4
    facts = {"us-gaap": {"Revenues": {"units": {"USD": rev}}, "OperatingIncomeLoss": {"units": {"USD": op}},
                         "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": sh}}}}
    m = sec.metrics(facts)
    assert m["ttm_rev"] == pytest.approx(520) and m["shares"] == 110 and m["dil"] == pytest.approx(10) and m["v"] == sec.SEC_VERSION


def test_trend_sma10_above_sma30():
    up = calc.build_row({"ticker": "U"}, W, [50, 100, 90, 90, 90], {"rev_rr": 30, "dopm": 5}, SPY)
    down = calc.build_row({"ticker": "D"}, {**W, "c": W["c"][::-1]}, [50, 100, 90, 90, 90], {"rev_rr": 30, "dopm": 5}, SPY)
    short = calc.build_row({"ticker": "S"}, {k: v[:20] for k, v in W.items()}, [], None)
    assert up["trend"] is True and down["trend"] is False and short["trend"] is None


def test_rel_volume():
    assert calc.rel_volume([10] * 10 + [25], 10) == pytest.approx(2.5)
    assert calc.rel_volume([10] * 5, 10) is None and calc.rel_volume([0] * 10 + [5], 10) is None


def test_surprises_known_at_date_and_fresh():
    est = {"surp": [["2025-08-01", -2.0], ["2025-11-01", 3.0], ["2026-02-01", 6.0]]}
    assert calc.surprises(est, "2026-03-01") == (6.0, 3.0, True)
    assert calc.surprises(est, "2026-01-15") == (3.0, -2.0, False)
    assert calc.surprises(est, "2026-07-01") == (None, None, None)


def test_build_row_exposes_latest_revenue_surprise_and_reported_eps_history():
    est = {
        "surp": [["2026-02-09", 6.0]],
        "revenue_surp": [["2026-02-09", 4.5], ["2026-03-10", 7.0]],
        "eps_q": [["2025-02-09", 1.0], ["2026-02-09", 2.0]],
        "rev90": 12.0,
    }
    row = calc.build_row(
        {"ticker": "DATA"},
        W,
        [50, 100, 90, 90, 90, 95],
        {"rev_rr": 25, "accel": 5, "dopm": 2, "qs": [{"rev_rr": 10}, {"rev_rr": 15}]},
        SPY,
        est,
    )
    # W kończy się przed raportem 2026-03-10; przyszła niespodzianka nie może wejść do wiersza.
    assert row["rev_surp"] == pytest.approx(4.5)
    assert row["eps_q"] == est["eps_q"]


def test_old_saved_conditions_reset_to_study_rules(tmp_path):
    """Zapisane przed badaniem 2011–2025 warunki (RS, P/S, beat2 włączone) wracają raz do nowych domyślnych; późniejsze zmiany zostają."""
    import json
    old = {k: {"enabled": True, "threshold": v["threshold"]} if "threshold" in v else {"enabled": True} for k, v in calc.DEFAULT_CONDITIONS.items()}
    (tmp_path / "settings.json").write_text(json.dumps({"strategy_conditions": old}), encoding="utf-8")
    st = Store(tmp_path)
    cfg = st.settings["strategy_conditions"]
    assert cfg["rev_growth"]["enabled"] and cfg["op_margin"]["enabled"] and not cfg["rs"]["enabled"] and not cfg["ps"]["enabled"] and not cfg["beat2"]["enabled"]
    st.settings["strategy_conditions"]["rs"]["enabled"] = True
    st.save_settings()
    assert Store(tmp_path).settings["strategy_conditions"]["rs"]["enabled"]


def test_upside_and_rs_rating_removed():
    """Kolumny Upside 12M % i RS Rating usunięte (nie działały) razem z danymi, z których je liczono."""
    from desktop.app import COLUMNS
    keys = [c[0] for c in COLUMNS]
    assert "upside" not in keys and "rs_rating" not in keys
    row = calc.build_row({"ticker": "X"}, W, [50, 100, 90, 90, 90], {"rev_rr": 30, "dopm": 5}, SPY, EST)
    assert "upside" not in row and "rs_rating_score" not in row
    assert not hasattr(calc, "rank_rs_rating") and not hasattr(estimates, "analyst_upside")


def test_ruler_text_percent_and_bars():
    from desktop.chart import ruler_text
    assert ruler_text(100, 150, 10, 22).startswith("+50.0 % · 12 tyg.")
    assert " mies." in ruler_text(10, 11, 0, 4, "M")


def test_momentum_12_1_skips_last_month():
    closes = [100.0] + [90.0] * 47 + [150.0] + [10.0] * 3 + [60.0]       # 52 + 1 = 53 zamknięcia
    assert len(closes) == 53 and closes[-5] == 150.0 and closes[-53] == 100.0
    assert calc.momentum_12_1(closes) == pytest.approx(50.0)             # (150 / 100 − 1) · 100; ostatni miesiąc (10, 10, 10, 60) pominięty
    assert calc.momentum_12_1(closes[1:]) is None                        # 52 zamknięcia = za krótka historia
    assert calc.momentum_12_1([100.0] * 60) == pytest.approx(0.0)
    assert calc.momentum_12_1([0.0] + [5.0] * 52) is None                # zero w mianowniku


def test_price_ratio_52_weeks():
    closes = [100.0] + [50.0] * 51 + [75.0]
    assert calc.price_ratio(closes) == pytest.approx(0.75)        # 53 zamknięcia tygodni: baza = pierwsze (sprzed 52 tygodni)
    assert calc.price_ratio([10.0, 20.0]) == pytest.approx(2.0)    # krótsza historia: najstarsze zamknięcie
    assert calc.price_ratio([5.0]) is None


def test_store_migrates_cc250(tmp_path):
    import json
    d = [f"2025-{1 + i // 5:02d}-{1 + (i % 5) * 6:02d}" for i in range(60)]
    series = {"SPY": {"d": d, "c": [100.0] * 60}, "A": {"d": d, "c": [100.0 + i for i in range(60)]}, "B": {"d": d, "c": [100.0] * 60}}
    (tmp_path / "weekly.json").write_text(json.dumps(series), encoding="utf-8")
    (tmp_path / "scan.json").write_text(json.dumps({"at": "x", "rows": [{"ticker": "A", "cc250": 1.4}, {"ticker": "B"}]}), encoding="utf-8")
    st = Store(tmp_path)
    a, b = st.rows
    assert a["cc52w"] == 1.4 and "cc250" not in a and "rs_rating" not in a and "rs_rating" not in b


def _etf(mult):
    """ETF rosnący szybciej niż SPY (stały): 60 tygodni."""
    return {**SPY, "c": [100.0 * (1 + 0.01 * mult) ** i for i in range(60)]}


def test_sector_rs_ranks_and_picks_only_positive_top():
    d = [(dt.date(2025, 1, 6) + dt.timedelta(weeks=i)).isoformat() for i in range(60)]
    spy = {"d": d, "c": [100.0] * 60}
    sectors = {"XLK": {"d": d, "c": [100.0 * 1.01 ** i for i in range(60)]}, "XLE": {"d": d, "c": [100.0 * 1.005 ** i for i in range(60)]},
               "XLU": {"d": d, "c": [100.0 * 0.99 ** i for i in range(60)]}}
    ranked = calc.sector_rs(sectors, spy)
    assert [x["etf"] for x in ranked] == ["XLK", "XLE", "XLU"] and ranked[0]["pct"] > ranked[1]["pct"] > 0 > ranked[2]["pct"]
    assert [x["etf"] for x in calc.top_sectors(ranked, 3)] == ["XLK", "XLE"]
    assert calc.sector_filter("sh_price_o15", ranked[0]) == "sec_technology,sh_price_o15"


def test_eps_rating_is_percentile_of_raw_score():
    days = [(dt.date(2022, 1, 15) + dt.timedelta(days=91 * i)).isoformat() for i in range(16)]
    grow = [[d, 1.0 + 0.3 * i] for i, d in enumerate(days)]
    flat = [[d, 1.0] for d in days]
    f = calc.eps_features(grow)
    assert f and f["raw"] > calc.eps_features(flat)["raw"]
    assert calc.eps_features([]) is None
    rows = [{"eps_raw": 10}, {"eps_raw": 50}, {"eps_raw": 90}, {"eps_raw": None}]
    calc.assign_eps_rating(rows)
    assert rows[0]["eps_rating"] < rows[1]["eps_rating"] < rows[2]["eps_rating"] and rows[3]["eps_rating"] is None
    assert all(1 <= r["eps_rating"] <= 99 for r in rows[:3])


def test_sync_sector_scanner_runs_one_query_per_top_sector(tmp_path):
    store = Store(tmp_path)
    assert store.scanner.get("top_sectors") == 3
    queries = []

    def fetch(f, max_tickers, log, progress):
        queries.append(f)
        return [{"ticker": "A", "sector": "Technology"}], 1

    def weekly(ts, log, cache, progress):
        out = {t: _etf(1.0) for t in ts}
        out["SPY"] = {**SPY, "c": [100.0] * 60}
        out["A"] = W
        return out

    def monthly(ts, cache, log, progress=None):
        for t in ts:
            cache[t] = {"h": [["2025-01", 50], ["2025-02", 100], ["2025-03", 90], ["2025-04", 90], ["2025-05", 90]], "upto": "2025-05", "raw": 1}
    rows = sync.run(store, log=lambda s: None, fetch_list=fetch, weekly=weekly, monthly=monthly,
                    fund=lambda ts, cache, ua, log, progress=None: None, est=lambda ts, cache, log: None)
    assert len(queries) == 3 and all(q.startswith("sec_") and "sh_price_o15" in q for q in queries)
    assert [r["ticker"] for r in rows] == ["A"] and Store(tmp_path).sectors and sum(x["selected"] for x in Store(tmp_path).sectors) == 3


def _weekly(closes, vols=None, spread=0.01):
    d = [(dt.date(2024, 1, 1) + dt.timedelta(weeks=i)).isoformat() for i in range(len(closes))]
    return {"d": d, "o": closes, "h": [x * (1 + spread) for x in closes], "l": [x * (1 - spread) for x in closes], "c": closes, "v": vols or [1e6] * len(closes)}


def test_cup_and_handle_detected_and_flat_trend_is_not():
    up = [50 + i * 1.2 for i in range(30)]                      # silny wzrost do szczytu 85
    cup = [85 - (i + 1) * 3.0 for i in range(8)] + [61 + (i + 1) * 3.0 for i in range(8)]   # spadek ok. 28 % i powrót
    handle = [83.5, 82.5]
    w = _weekly(up + cup + handle)
    pats = calc.find_patterns(w)
    assert pats and pats[0]["name"] == "Cup & Handle" and pats[0]["state"] == "BUDUJE SIĘ" and pats[0]["pct"] < 0
    assert pats[0]["shapes"][0]["kind"] == "curve" and pats[0]["shapes"][1]["kind"] == "box"
    w2 = _weekly(up + cup + handle + [pats[0]["buy"] * 1.03])  # wybicie ponad górę uchwytu
    assert [p["state"] for p in calc.find_patterns(w2) if p["name"] == "Cup & Handle"] == ["WYBICIE"]
    assert calc.find_patterns(_weekly([100.0 + (i % 2) for i in range(80)])) == []   # płaski rynek bez poprzedzającego wzrostu


def test_flat_base_flag_and_parabola():
    base = [50 + i * 1.5 for i in range(30)] + [96 + (i % 3) * 0.4 for i in range(12)]
    vols = [2e6] * 30 + [1e6] * 12
    pats = calc.find_patterns(_weekly(base, vols))
    assert any(p["name"] in ("Flat Base", "Ascending Triangle") for p in pats)
    flag = [50 + i * 0.5 for i in range(32)] + [66, 72, 80, 88, 94] + [91, 90, 90.5]   # drążek ok. +40 % i pauza
    fp = calc.find_patterns(_weekly(flag, [1e6] * 32 + [3e6] * 5 + [8e5] * 3))
    assert any(p["name"] == "Flaga/Proporzec" for p in fp)


def _steps(n=60, c2=0.0003, amp=0.08):
    """Schodkowy, przyspieszający wzrost: wypukła krzywa (log) z oscylacją co 7 tyg. — dołki leżą na coraz bardziej stromych liniach."""
    return [20 * math.exp(0.004 * i + c2 * i * i) * (1 + amp * math.sin(2 * math.pi * i / 7)) for i in range(n)]


def test_parabolic_curve_needs_three_steepening_lines_and_flags_the_break():
    r = calc.parabola(_weekly(_steps()))
    assert r and r["state"] == "TRWA" and r["n"] == 3 and r["gain"] >= 100 and r["exit"] > 0
    assert [ln["p2"] for ln in r["lines"]] == sorted(ln["p2"] for ln in r["lines"])                       # każda następna linia kończy wyżej
    gap = _steps(56) + [x * 1.6 for x in _steps(60)[56:]]                                                        # luka w górę: cena daleko nad najbardziej stromą linią
    assert calc.parabola(_weekly(gap)) is None
    assert calc.parabola(_weekly([20 * 1.02 ** i * (1 + 0.08 * math.sin(2 * math.pi * i / 7)) for i in range(60)])) is None   # stałe tempo = jedna linia, nie parabola
    c = _steps(58) + [_steps(58)[-1] * 0.8, _steps(58)[-1] * 0.7]                                                  # załamanie pod najbardziej stromą linią
    broken = calc.parabola(_weekly(c, [1e6] * 59 + [4e6]))
    assert broken and broken["state"] == "ZŁAMANA" and broken["broken"] and broken["vol_x"] == 4.0


def test_build_row_carries_patterns_and_position_status_warns_on_parabola():
    from desktop import lines
    para = _steps()
    row = calc.build_row({"ticker": "P"}, _weekly(para), [], None)
    assert row["parabola"] and "patterns" in row and "pattern" in row
    assert any("PARABOLA" in m for m in lines.position_status({"last": para[-1]}, row))
    row["parabola"]["state"] = "ZŁAMANA"
    assert any("złamana" in m for m in lines.position_status({"last": para[-1]}, row))


def _pts_weekly(pts, vols=None, spread=0.01):
    """Seria tygodniowa z punktów (tydzień, cena) interpolowanych liniowo — do kształtów wzorców."""
    c = []
    for (i0, p0), (i1, p1) in zip(pts, pts[1:]):
        c += [p0 + (p1 - p0) * (i - i0) / (i1 - i0) for i in range(i0, i1)]
    c.append(pts[-1][1])
    return _weekly(c, vols, spread)


def _zigzag(lows, highs, last, start=30, leg=3):
    pts, i = [(0, 50), (start, 100)], start
    for lo, hi in zip(lows, highs):
        pts += [(i + leg, hi), (i + 2 * leg, lo)]
        i += 2 * leg
    return pts + [(i + leg, last)]


def _only(w, name):
    return next((p for p in calc.find_patterns(w) if p["name"] == name), None)


def test_line_based_zanger_patterns_buy_side():
    sym = _only(_pts_weekly(_zigzag([100 + 3 * k for k in range(5)], [130 - 3 * k for k in range(5)], 116)), "Symmetrical Triangle")
    assert sym and sym["side"] == "buy" and sym["state"] == "BUDUJE SIĘ" and -8 <= sym["pct"] < 0
    assert [s["kind"] for s in sym["shapes"]] == ["line", "line"]
    ch = _only(_pts_weekly(_zigzag([100] * 6, [118] * 6, 117.5)), "Channel")
    assert ch and ch["side"] == "buy"
    fw = _only(_pts_weekly(_zigzag([100 - k for k in range(5)], [130 - 4 * k for k in range(5)], 108)), "Falling Wedge")
    assert fw and fw["side"] == "buy" and fw["state"] == "BUDUJE SIĘ"
    fw_up = _only(_pts_weekly(_zigzag([100 - k for k in range(5)], [130 - 4 * k for k in range(5)], 113)), "Falling Wedge")
    assert fw_up and fw_up["state"] == "WYBICIE" and fw_up["pct"] > 0   # cena nad opadającą linią


def test_head_and_shoulders_is_a_sell_warning_and_inverted_is_a_buy():
    hs = [(0, 50), (30, 100), (36, 120), (40, 105), (46, 135), (50, 106), (56, 121), (60, 112)]
    warn = _only(_pts_weekly(hs), "Head & Shoulders")
    assert warn and warn["side"] == "sell" and warn["state"] == "OSTRZEŻENIE" and [s["text"] for s in warn["shapes"] if s["kind"] == "mark"] == ["LS", "H", "RS"]
    broken = _only(_pts_weekly(hs[:-1] + [(60, 103)]), "Head & Shoulders")
    assert broken and broken["state"] == "ZŁAMANA" and broken["pct"] < 0
    inv = _only(_pts_weekly([(0, 130), (30, 100), (36, 88), (40, 97), (46, 80), (50, 98), (56, 88), (60, 95)]), "Inverted H&S")
    assert inv and inv["side"] == "buy" and inv["state"] == "BUDUJE SIĘ"


def test_rising_wedge_warns_and_buy_patterns_come_first_in_row_columns():
    rw = _only(_pts_weekly(_zigzag([100 + 4 * k for k in range(5)], [120 + 2 * k for k in range(5)], 120)), "Rising Wedge")
    assert rw and rw["side"] == "sell"
    pats = calc.find_patterns(_pts_weekly(_zigzag([100 + 3 * k for k in range(5)], [130 - 3 * k for k in range(5)], 116)))
    sides = [p["side"] for p in pats]
    assert sides == sorted(sides, key=lambda x: x == "sell")                      # kupno przed ostrzeżeniami
    row = calc.build_row({"ticker": "S"}, _pts_weekly(_zigzag([100 + 3 * k for k in range(5)], [130 - 3 * k for k in range(5)], 116)), [], None)
    assert row["pattern"] == "Symmetrical Triangle" and row["pattern_pct"] < 0 and all(p["side"] == "buy" or row["pattern_exit"] for p in row["patterns"])


def test_flag_buys_over_the_descending_trend_line():
    w = _pts_weekly([(0, 50), (30, 66), (32, 80), (34, 94), (35, 91), (37, 88), (39, 85.5)], [1e6] * 30 + [3e6] * 5 + [8e5] * 5)
    f = _only(w, "Flaga/Proporzec")
    assert f and f["state"] == "BUDUJE SIĘ" and any(s["kind"] == "line" and s["d2"] == w["d"][-1] for s in f["shapes"][2:])   # linia opadająca przedłużona do ostatniego tygodnia


def test_rwb_starts_mark_return_of_rwb_after_pullback():
    c = [100 + i for i in range(120)] + [220 - 3 * i for i in range(25)] + [145 + 2 * i for i in range(60)]   # trend, cofnięcie, powrót
    r = calc.rwb(c)
    starts = calc.rwb_starts(c)
    assert starts and all(r[i] and not r[i - 1] for i in starts)
    assert all(i >= 60 for i in starts) and starts[-1] > 145        # ostatni start po cofnięciu
    assert calc.rwb_starts([100 + i for i in range(50)]) == []      # za krótka historia


def test_rwb_weeks_counts_weeks_since_start_of_current_rwb():
    c = [100 + i for i in range(120)] + [220 - 3 * i for i in range(25)] + [145 + 2 * i for i in range(60)]
    start = calc.rwb_starts(c)[-1]
    assert calc.rwb_weeks(c) == len(c) - 1 - start                   # tygodnie od ostatniego startu RWB
    assert calc.rwb_weeks(c[:start + 1]) == 0                        # start w tym tygodniu
    assert calc.rwb_weeks([100 - i * 0.5 for i in range(100)]) is None   # RWB wyłączone
    assert calc.rwb_weeks(c[:40]) is None                            # za krótka historia


def _trend(n=170):
    return [100 + i for i in range(n)]


def test_rwb_gap_exists_only_while_red_band_is_above_blue_band():
    c = _trend()
    gap = calc.rwb_gap(c)
    lo, hi = gap[150]
    assert lo is not None and hi > lo                                  # przerwa: najwyższa wolna < najniższa szybka
    f, s = calc.gmma(c)
    assert lo == max(x[150] for x in s) and hi == min(x[150] for x in f)
    down = calc.rwb_gap([300 - i for i in range(120)])
    assert all(g == (None, None) for g in down[60:])                   # w spadku nie ma RWB, więc nie ma przerwy


def test_rwb_dokup_is_price_entering_the_gap_while_rwb_lasts():
    c = _trend()
    low = [x - 1 for x in c]                                           # zwykłe świece nie dochodzą do czerwonego pasa
    assert calc.rwb_dokup(low, c) == []
    lo, hi = calc.rwb_gap(c)[120]
    assert lo < hi
    low[120] = (lo + hi) / 2                                           # Low w środku przerwy
    low[121] = hi - 0.01                                               # kolejna świeca nadal w przerwie = ta sama okazja
    low[135] = hi - 0.01                                               # po wyjściu nad czerwony pas kolejne wejście = nowa strzałka
    assert calc.rwb_dokup(low, c) == [120, 135]
    close_in = list(c)
    close_in[150] = calc.rwb_gap(c)[150][1] - 4                      # samo zamknięcie w przerwie też liczy się (Low = None)
    assert 150 in calc.rwb_dokup([None] * len(c), close_in)
    assert calc.rwb_dokup([x - 5 for x in c[:50]], c[:50]) == []        # za krótka historia (rozgrzewka 60 świec)
    d = [300 - i for i in range(120)]
    assert calc.rwb_dokup([x - 30 for x in d], d) == []                # bez RWB nie ma dokupu, choćby cena spadała


def test_watchlists_store_logic_and_persistence(tmp_path):
    from desktop import store as S
    st = Store(tmp_path)
    assert [w["name"] for w in st.watchlists()] == [S.DEFAULT_WATCHLIST] and st.settings["main_view"] == {"mode": "list", "watchlist": S.DEFAULT_WATCHLIST, "ask": True}
    assert S.split_tickers(" nvda, AMD;msft\nnvda ") == ["NVDA", "AMD", "MSFT"]
    assert st.add_to_watchlist(S.DEFAULT_WATCHLIST, " nvda, AMD;msft nvda") == ["NVDA", "AMD", "MSFT"]
    assert st.add_to_watchlist(S.DEFAULT_WATCHLIST, ["amd", "TSLA"]) == ["TSLA"]                 # AMD już jest -> nowe tylko TSLA
    assert st.add_to_watchlist("brak takiej", "X") == []
    assert st.add_watchlist("Energia") == "Energia" and st.add_watchlist("energia") is None and st.add_watchlist("  ") is None   # unikalne nazwy bez względu na wielkość liter
    st.add_to_watchlist("Energia", "XOM")
    assert st.watch_tickers() == {"NVDA", "AMD", "MSFT", "TSLA", "XOM"}
    assert st.remove_from_watchlist(S.DEFAULT_WATCHLIST, "amd, zzz") == ["AMD"]
    again = Store(tmp_path)                                                                      # zapis w settings.json
    assert again.watchlist("Energia")["tickers"] == ["XOM"] and again.watchlist(S.DEFAULT_WATCHLIST)["tickers"] == ["NVDA", "MSFT", "TSLA"]
    assert again.rename_watchlist("Energia", "Ropa") and not again.rename_watchlist("Ropa", S.DEFAULT_WATCHLIST) and again.watchlist("Ropa")
    again.set_view("watch", "Ropa")
    assert again.settings["main_view"]["mode"] == "watch" and again.rename_watchlist("Ropa", "Ropa i gaz") and again.settings["main_view"]["watchlist"] == "Ropa i gaz"
    assert again.delete_watchlist("Ropa i gaz") and again.settings["main_view"] == {"mode": "list", "watchlist": S.DEFAULT_WATCHLIST, "ask": True}   # widok z usuniętej wraca do listy
    assert not again.delete_watchlist(S.DEFAULT_WATCHLIST)                                       # ostatniej nie da się usunąć
    again.set_view("watch", "nie ma takiej")
    assert again.settings["main_view"]["mode"] == "list"


def test_watchlist_view_rows_are_added_tickers_and_dedupe(tmp_path):
    from desktop import store as S
    st = Store(tmp_path)
    st.save_scan([{"ticker": "A", "price": 10}, {"ticker": "B", "price": 20}], {"A": W, "B": W}, "2026-10-20")
    st.add_to_watchlist(S.DEFAULT_WATCHLIST, "B, ZZ")                                           # B jest też w skanie, ZZ nie ma danych
    assert st.view_rows() == (st.rows, set())                                                   # widok „Lista”: sam skaner
    st.set_view("watch", S.DEFAULT_WATCHLIST)
    rows, added = st.view_rows()
    assert [r["ticker"] for r in rows] == ["B", "ZZ"] and added == {"B", "ZZ"} and rows[1].get("price") is None   # tylko dodane; ZZ = pusty wiersz do czasu Sync
    st.extra["ZZ"] = ({"ticker": "ZZ", "price": 5.0}, W)
    assert st.view_rows()[0][1]["price"] == 5.0                                                 # po pobraniu danych wiersz ma wartości


def test_add_scanner_rejects_duplicates_and_uses_default_filter(tmp_path):
    from desktop import finviz
    st = Store(tmp_path)
    n = len(st.settings["scanners"])
    assert st.add_scanner("Moja lista", "") == "Moja lista" and len(st.settings["scanners"]) == n + 1
    assert st.settings["scanners"][-1]["filters"] == finviz.DEFAULT_FILTERS
    assert st.add_scanner("moja LISTA") is None and st.add_scanner("  ") is None
    assert Store(tmp_path).settings["scanners"][-1]["name"] == "Moja lista"


def test_watchlist_merges_lists_of_many_scanners_without_duplicates(tmp_path):
    from desktop import store as S
    st = Store(tmp_path)
    names = [x["name"] for x in st.settings["scanners"]][:3]
    for name, tickers in zip(names, (["A", "B"], ["B", "C"], ["D"])):
        st.select(name)
        st.save_scan([{"ticker": t, "price": 10} for t in tickers], {t: W for t in tickers}, "2026-10-20")
    wl = S.DEFAULT_WATCHLIST
    st.set_view("watch", wl)
    st.set_watchlist_sources(wl, names)                                                         # trzy listy skanerów w jednej watchliście
    st.add_to_watchlist(wl, "ZZ, A")                                                            # plus ręcznie dodany ticker (A jest już ze skanu)
    assert [r["ticker"] for r in st.view_rows()[0]] == ["A", "B", "C", "D", "ZZ"]               # bez powtórzeń
    st.set_watchlist_sources(wl, [names[2], "nie ma takiego"])
    assert st.watchlist(wl)["sources"] == [names[2]] and [r["ticker"] for r in st.view_rows()[0]] == ["D", "ZZ", "A"]
    assert Store(tmp_path).watchlist(wl)["sources"] == [names[2]]                               # zapisane w settings.json


def test_sync_refreshes_watchlist_tickers_outside_the_scanner(tmp_path):
    store = Store(tmp_path)
    store.select("Bezpieczny (backtest)")
    store.add_to_watchlist(store.watchlists()[0]["name"], "ZZ")
    seen = []

    def weekly(ts, log, cache, progress):
        seen.append(set(ts))
        return {t: W for t in ts if t != "SPY"} | {"SPY": SPY}

    def monthly(ts, cache, log, progress=None):
        for t in ts:
            cache[t] = {"h": [["2025-01", 50], ["2025-02", 100]], "upto": "2025-05", "raw": 1}
    sync.run(store, log=lambda s: None, fetch_list=lambda f, max_tickers, log, progress: ([{"ticker": "A"}], 1), weekly=weekly, monthly=monthly,
             fund=lambda ts, cache, ua, log, progress=None: None, est=lambda ts, cache, log: None)
    assert "ZZ" in seen[0] and store.row("ZZ") is not None                                       # tickery z watchlist są pobierane razem ze skanerem
    assert [r["ticker"] for r in store.rows] == ["A"]                                           # ale nie trafiają do listy skanera


def test_momentum_6_and_tempo_margin():
    c = [100.0 * 1.01 ** i for i in range(60)]
    assert calc.momentum_6(c) == pytest.approx((c[-1] / c[-27] - 1) * 100) and calc.momentum_6(c[:20]) is None
    assert calc.tempo_margin(c) is not None and abs(calc.tempo_margin(c)) < 1e-6                       # stały wzrost: tempo 3 i 12 mies. równe
    accel = [100.0 * 1.005 ** i for i in range(47)] + [100.0 * 1.005 ** 46 * 1.03 ** k for k in range(1, 14)]
    fade = [100.0 * 1.03 ** i for i in range(47)] + [100.0 * 1.03 ** 46 * 1.001 ** k for k in range(1, 14)]
    assert calc.tempo_margin(accel) > 0 > calc.tempo_margin(fade) and calc.tempo_margin(c[:40]) is None   # przyspiesza >= 0, wygasa < 0
