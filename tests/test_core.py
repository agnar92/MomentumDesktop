"""Testy bez sieci: Green Line, stan GLB, MACD, obrót, warunki, parser Finviz, fundamenty SEC i synchronizacja z podmienionymi źródłami."""
import datetime as dt

import pytest

from desktop import calc, estimates, finviz, prices, sec, sync
from desktop.store import Store

_D = [(dt.date(2025, 1, 6) + dt.timedelta(weeks=i)).isoformat() for i in range(60)]
W = {"d": _D, "o": [1] * 60, "h": [1] * 60, "l": [1] * 60, "c": [50.0] * 19 + [100.0] * 40 + [104.0], "v": [1e7] * 60}   # +108 % w 52 tyg.
EST = {"surp": [["2025-11-10", 4.0], ["2026-02-09", 8.0]], "rev90": 12.0}   # 2 raporty powyżej konsensusu, ostatni w ostatnich tygodniach W
SPY = {"d": _D, "o": [1] * 60, "h": [1] * 60, "l": [1] * 60, "c": [400.0] * 60, "v": [1e7] * 60}


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
    assert calc.glb_state(125, 99, 100) == "WYBICIE"                    # tydzień przebicia: dowolnie wysoko = mocne wybicie
    assert calc.glb_state(105, 103, 100, armed=False) == "NAD"          # powrót w strefę po wyjściu wyżej: kupowanie spadku, nie sygnał


def test_glb_armed_only_after_breakout_from_below():
    assert calc.glb_armed([90, 95, 101, 104], 100)                       # zamknięcie pod linią, potem przebicie i kolejny tydzień w strefie
    assert not calc.glb_armed([90, 101, 115, 108], 100)                  # wyszła > 10 % nad linię i wróciła w strefę (CDLX 03/2020)
    assert calc.glb_armed([90, 101, 115, 98, 103], 100)                  # zeszła pod linię i przebiła ponownie: znów sygnał
    assert not calc.glb_armed([105, 108, 104], 100)                      # nigdy pod linią w oknie
    assert not calc.glb_armed([90, 95], None)
    row = calc.build_row({"ticker": "X"}, {"d": [f"2026-01-{i + 1:02d}" for i in range(4)], "o": [0] * 4, "h": [0] * 4, "l": [1] * 4,
                                           "c": [90, 115, 108, 106], "v": [1] * 4}, [100] * 5, None)
    assert row["glb"] == 100 and row["glb_state"] == "NAD"


def test_fresh_blue_dot_only_in_last_sessions():
    n = 160
    c = [50 + i * 0.4 for i in range(n)]
    c[150:154] = [c[149] - 3, c[149] - 6, c[149] - 7, c[149] - 1]       # korekta w trendzie, potem odbicie: Stochastic przecina 20 w górę
    d = {"d": [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)], "h": [x + 1 for x in c], "l": [x - 1 for x in c], "c": c}
    assert calc.fresh_blue_dot(d, 40, sessions=10) == d["d"][153]
    assert calc.fresh_blue_dot(d, 40, sessions=5) is None                 # kropka starsza niż 5 sesji
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
                    daily=lambda ts, log, **kw: {t: {**w, "v": [1e6] * 59 + [3e6]} for t in ts},
                    progress=lambda f, st: steps.append((round(f, 2), st)))
    assert [f for f, _ in steps] == [0.0, 0.15, 0.4, 0.6, 1.0] and steps[-1][1] == "Gotowe"
    a = next(r for r in rows if r["ticker"] == "A")
    assert a["ok"] and a["glb_state"] == "SYGNAŁ"
    assert a["rvol_w"] == pytest.approx(1.0) and a["rvol_d"] == pytest.approx(3.0)     # wolumen relatywny: tydzień / 10, sesja / 50
    assert next(r for r in rows if r["ticker"] == "B")["ok"]       # mały obrót nie blokuje (płynność = filtr Finviz)
    assert Store(tmp_path).rows and Store(tmp_path).weekly("A")["c"][-1] == 104.0


def test_scanners_have_own_lists_and_share_weekly(tmp_path):
    store = Store(tmp_path)
    names = [x["name"] for x in store.settings["scanners"]]
    assert names[0] == "Bezpieczny (backtest)" and store.settings["scanner"] == names[0] and len(names) == 4
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
    assert ruler_text(100, 80, 5, 2, "D").startswith("-20.0 % · 3 sesji")
    assert " mies." in ruler_text(10, 11, 0, 4, "M")


def test_price_ratio_252_sessions():
    closes = [100.0] + [50.0] * 251 + [75.0]
    assert calc.price_ratio(closes) == pytest.approx(0.75)        # 253 zamknięcia: baza = pierwsze (sprzed 252 sesji)
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
