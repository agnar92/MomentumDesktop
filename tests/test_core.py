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
    good = {"turnover": 120e6, "rev_rr": 20, "dopm": 4, "rs": 60, "beat2": True}
    assert calc.passes(good) and calc.passes({**good, "ps": 15}) and calc.passes({**good, "ps": None})
    assert calc.passes({**good, "turnover": 1e3})                      # obrót nie jest warunkiem (filtr w Finviz)
    for k, v in (("rev_rr", 10), ("dopm", 2), ("dopm", None), ("rs", 40), ("rs", None), ("ps", 25), ("beat2", False), ("beat2", None)):
        assert not calc.passes({**good, k: v})


def test_strategy_conditions_are_configurable():
    row = {"rev_rr": 20, "dopm": 4, "ps": 18, "rs": 55, "beat2": True}
    cfg = calc.normalize_conditions()
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
    assert cfg["ps"] == {"enabled": True, "threshold": calc.MAX_PS}
    assert set(cfg) == set(calc.DEFAULT_CONDITIONS)


def test_build_row():
    w = {"d": ["2026-01-05"] * 40, "o": [1] * 40, "h": [1] * 40, "l": [1] * 40, "c": [100.0] * 38 + [99.0, 104.0], "v": [3e6] * 40}
    row = calc.build_row({"ticker": "X"}, w, [50, 100, 90, 90, 90, 95], {"rev_rr": 30, "dopm": 5})
    assert row["glb"] == 100 and row["glb_state"] == "WYBICIE" and row["glb_pct"] == pytest.approx(4)
    assert row["turnover"] == pytest.approx(104 * 3e6 / 5, rel=0.05)
    assert row["rs"] is None and not row["ok"]          # 40 tygodni historii i brak SPY -> brak siły względnej -> nie spełnia
    r = calc.build_row({"ticker": "Y"}, W, [50, 100, 90, 90, 90, 95], {"rev_rr": 30, "dopm": 5}, SPY, EST)
    assert r["rs"] == pytest.approx(108) and r["ok"] and r["glb_state"] == "SYGNAŁ"
    assert r["surp"] == 8.0 and r["surp_prev"] == 4.0 and r["beat2"] and r["eps_rev"] == 12.0
    valued = calc.build_row({"ticker": "Z", "peg": 2.0, "forward_pe": 30.0, "dividend_yield": 2.0},
                            W, [50, 100, 90, 90, 90, 95], {"rev_rr": 30, "dopm": 5}, SPY, EST)
    assert valued["peg"] == 2.0 and valued["pegy"] == pytest.approx(1.76)
    assert calc.build_row({"ticker": "UP"}, W, [50, 100, 90, 90, 90], {"rev_rr": 30, "dopm": 5},
                          SPY, {**EST, "upside": 34.6})["upside"] == 34.6




def _canslim_eps_history():
    return [
        ["2022-01-31", 0.50], ["2022-04-30", 0.60], ["2022-07-31", 0.70], ["2022-10-31", 0.80],
        ["2023-01-31", 0.65], ["2023-04-30", 0.78], ["2023-07-31", 0.91], ["2023-10-31", 1.04],
        ["2024-01-31", 0.845], ["2024-04-30", 1.014], ["2024-07-31", 1.183], ["2024-10-31", 1.352],
        ["2025-01-31", 1.0985], ["2025-04-30", 1.3182], ["2025-07-31", 1.5379], ["2025-10-31", 1.7576],
    ]


def _canslim_spy(as_of="2026-10-23"):
    today = dt.date.fromisoformat(as_of)
    last_monday = today - dt.timedelta(days=today.weekday())
    dates = [(last_monday - dt.timedelta(weeks=60 - i)).isoformat() for i in range(60)]
    return {"d": dates, "c": [300.0 + i * 2.0 for i in range(60)]}


def test_canslim_glb_score_uses_equal_weights_for_six_letters_without_n_confirmation():
    leader = {
        "ticker": "LEADER", "sector": "Technology", "industry": "Semiconductors", "rs": 60,
        "glb_state": "WYBICIE", "glb_rvol": 1.6, "dil": -1.0, "shares_float": 45e6,
        "institutional_ownership": 50.0, "institutional_transactions": 8.0, "roe": 20.0,
        "rev_rr": 30.0, "accel": 10.0, "dopm": 3.0, "surp": 15.0, "rev_surp": 8.0,
        "eps_q": _canslim_eps_history(),
        "qs": [{"rev": x, "rev_rr": 30.0} for x in [80, 85, 90, 95, 100, 110, 120, 130]],
    }
    laggard = {
        "ticker": "LAGGARD", "sector": "Energy", "industry": "Oil & Gas", "rs": -20,
        "glb_state": "BRAK", "glb_rvol": None, "dil": 5.0, "shares_float": 900e6,
        "institutional_ownership": 8.0, "institutional_transactions": -5.0, "roe": 4.0,
        "rev_rr": 5.0, "accel": -5.0, "dopm": -2.0, "surp": -5.0, "rev_surp": -3.0,
        "eps_q": [[day, value * 0.5] for day, value in _canslim_eps_history()],
        "qs": [{"rev": x, "rev_rr": 5.0} for x in [80, 85, 90, 95, 100, 102, 104, 106]],
    }
    mid = {
        "ticker": "MID", "sector": "Industrials", "industry": "Tools", "rs": 10,
        "glb_state": "NAD", "glb_rvol": None, "dil": None, "shares_float": None,
        "institutional_ownership": None, "institutional_transactions": None, "roe": None,
        "rev_rr": None, "accel": None, "dopm": None, "surp": None, "rev_surp": None,
        "eps_q": [], "qs": [],
    }
    scored = calc.canslim_glb_scores(
        [leader, laggard, mid], market_series=_canslim_spy(), as_of="2026-10-23",
    )
    result = scored["LEADER"]
    assert result["score"] is not None and result["coverage"] == pytest.approx(100)
    assert result["details"]["eps_q_growth"]["value"] == pytest.approx(30.0, abs=0.5)
    assert result["details"]["annual_eps_cagr"]["value"] == pytest.approx(30.0, abs=1.0)
    assert result["details"]["annual_eps_consistency"]["value"] == 3
    assert "new_catalyst" not in result["details"]
    assert result["details"]["breakout_rvol"]["points"] == pytest.approx(result["details"]["breakout_rvol"]["weight"])
    assert result["details"]["institutional_transactions"]["points"] > scored["LAGGARD"]["details"]["institutional_transactions"]["points"]
    assert result["details"]["rs_percentile"]["points"] > scored["LAGGARD"]["details"]["rs_percentile"]["points"]
    assert result["details"]["market_direction"]["points"] == pytest.approx(result["details"]["market_direction"]["weight"])
    assert set(result["categories"]) == {
        "current_earnings", "annual_earnings", "supply_demand", "leadership", "institutional", "market",
    }
    weights = [category["weight"] for category in result["categories"].values()]
    assert all(weight == pytest.approx(100 / 6) for weight in weights)
    assert sum(calc.CANSLIM_GLB_WEIGHTS.values()) == pytest.approx(100)
    assert scored["LAGGARD"]["details"]["breakout_rvol"]["points"] is None
    assert scored["LAGGARD"]["score"] < result["score"]


def test_canslim_market_direction_is_missing_without_weekly_spy_data():
    result = calc.canslim_glb_scores([{"ticker": "A"}], as_of="2026-10-23")["A"]
    assert result["details"]["market_direction"]["points"] is None
    assert "new_catalyst" not in result["details"]
    assert result["score"] is None


def test_breakout_relative_volume_uses_the_actual_daily_close_cross():
    level = 100.0
    closes = [95.0] * 55 + [99.0, 100.5, 101.0]
    volumes = [1_000_000.0] * 56 + [1_500_000.0, 1_100_000.0]
    assert calc.breakout_rel_volume(
        {"d": [str(i) for i in range(len(closes))], "c": closes, "v": volumes}, level, max_age=10
    ) == pytest.approx(1.5)



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


def test_analyst_upside_uses_mean_target_and_current_price():
    assert estimates.analyst_upside({"current": 100, "mean": 125, "median": 120}) == pytest.approx(25)
    assert estimates.analyst_upside({"current": 100, "mean": 80}) == pytest.approx(-20)
    assert estimates.analyst_upside({"current": 0, "mean": 120}) is None
    assert estimates.analyst_upside({"current": 100, "mean": None}) is None
    assert estimates.analyst_upside({"current": "nan", "mean": 120}) is None


def test_estimates_refresh_legacy_cache_without_upside():
    today = dt.date(2026, 10, 22)
    cache = {"A": {"at": today.isoformat(), "surp": [], "rev90": None}}
    fetched = {"surp": [], "revenue_surp": [], "eps_q": [], "rev90": None, "upside": 27.5}
    got = estimates.update(["A"], cache, today=today, pause=0, fetch_one=lambda ticker: fetched)
    assert got == ["A"] and cache["A"]["upside"] == 27.5


def test_upside_is_visible_and_supports_numeric_filter():
    from desktop.app import COLUMNS, cell, pass_filters

    col = next(c for c in COLUMNS if c[0] == "upside")
    assert col[1] == "Upside 12M %" and col[3] == "%"
    assert cell(32.45, col[3]) == "+32.5"
    assert pass_filters({"upside": 35}, {"upside": {"min": 30, "max": 50}})
    assert not pass_filters({"upside": 55}, {"upside": {"min": 30, "max": 50}})
    assert not pass_filters({"upside": None}, {"upside": {"min": 30}})


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
    assert not calc.build_row({"ticker": "B", "market_cap": 9e9}, W, [50, 100, 90, 90, 90], f, SPY)["ok"]      # P/S 30
    rgti = calc.build_row({"ticker": "RGTI", "market_cap": 4e9}, W, [], {"rev_rr": 185, "dopm": 558, "ttm_rev": 20e6}, SPY)
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



def test_growth_score_uses_seven_weighted_signals_and_normalizes_coverage():
    row = {
        "rev_rr": 50, "accel": 10, "eps_rev": 20, "dopm": 6, "surp": 30, "rev_surp": 30,
        "eps_q": [["2025-01-31", 2.0], ["2026-01-31", 4.0]],
        "qs": [{"rev_rr": 10}, {"rev_rr": 20}, {"rev_rr": 30}, {"rev_rr": 40}],
    }
    result = calc.growth_score(row)
    assert sum(calc.GROWTH_SCORE_WEIGHTS.values()) == 100.0
    assert result["score"] == 100.0
    assert result["coverage"] == 100.0
    assert result["points"] == 100.0
    assert result["details"]["eps_growth"]["value"] == pytest.approx(100.0)
    assert set(result["components"]) == set(calc.GROWTH_SCORE_GROUPS)

    weak = {
        "rev_rr": 0, "accel": -10, "eps_rev": -20, "dopm": -5, "surp": -20, "rev_surp": -20,
        "eps_q": [["2025-01-31", 2.0], ["2026-01-31", 1.0]],
        "qs": [{"rev_rr": -10}, {"rev_rr": -20}],
    }
    assert calc.growth_score(weak)["score"] == 0.0


def test_growth_score_skips_missing_data_and_requires_70_points_of_coverage():
    partial = calc.growth_score({"rev_rr": 25, "accel": 5, "eps_rev": 10, "dopm": 3})
    assert partial["coverage"] == 70.0
    assert partial["score"] is not None
    assert partial["details"]["eps_surprise"]["points"] is None
    assert partial["details"]["revenue_surprise"]["points"] is None

    insufficient = calc.growth_score({"rev_rr": 25, "accel": 5})
    assert insufficient["coverage"] == 45.0
    assert insufficient["score"] is None


def test_growth_score_scores_surprises_and_quarterly_growth_durability():
    result = calc.growth_score({
        "surp": 5,
        "rev_surp": 5,
        "qs": [{"rev_rr": 20}, {"rev_rr": 10}, {"rev_rr": -5}, {"rev_rr": 0}],
    })
    assert result["details"]["eps_surprise"]["points"] == pytest.approx(3.0)
    assert result["details"]["revenue_surprise"]["points"] == pytest.approx(3.0)
    assert result["details"]["durability"]["value"] == pytest.approx(50.0)
    assert result["details"]["durability"]["points"] == pytest.approx(2.5)
    assert result["details"]["durability"]["note"].startswith("2/4")
    assert result["coverage"] == 15.0
    assert result["score"] is None


def test_build_row_exposes_latest_revenue_surprise_and_reported_eps_history():
    est = {
        "surp": [["2026-02-09", 6.0]],
        "revenue_surp": [["2026-02-09", 4.5], ["2026-03-10", 7.0]],
        "eps_q": [["2025-02-09", 1.0], ["2026-02-09", 2.0]],
        "rev90": 12.0,
        "upside": 20.0,
    }
    row = calc.build_row(
        {"ticker": "DATA"},
        W,
        [50, 100, 90, 90, 90, 95],
        {"rev_rr": 25, "accel": 5, "dopm": 2, "qs": [{"rev_rr": 10}, {"rev_rr": 15}]},
        SPY,
        est,
    )
    # W kończy się przed raportem 2026-03-10; przyszła niespodzianka nie może wejść do score.
    assert row["rev_surp"] == pytest.approx(4.5)
    assert row["eps_q"] == est["eps_q"]
    assert calc.growth_score(row)["details"]["eps_growth"]["value"] == pytest.approx(100.0)


