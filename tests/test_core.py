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
    w = {"d": ["2026-01-05"] * 40, "o": [1] * 40, "h": [1] * 40, "l": [1] * 40, "c": [100.0] * 39 + [104.0], "v": [5e6] * 40}

    def monthly(ts, cache, log, progress=None):
        for t in ts:
            cache[t] = {"h": [["2025-01", 50], ["2025-02", 100], ["2025-03", 90], ["2025-04", 90], ["2025-05", 90]], "upto": "2025-05", "raw": 1}

    def fund(ts, cache, ua, log, progress=None):
        for t in ts:
            cache[t] = {"at": "2026-10-20", "rev_rr": 25, "dopm": 6}
    steps = []
    rows = sync.run(store, log=lambda s: None, fetch_list=lambda f, max_tickers, log, progress: ([{"ticker": "A"}, {"ticker": "B"}], 2),
                    weekly=lambda ts, log, cache, progress: {"A": w, "B": {**w, "v": [1e3] * 40}}, monthly=monthly, fund=fund,
                    progress=lambda f, st: steps.append((round(f, 2), st)))
    assert [f for f, _ in steps] == [0.0, 0.15, 0.4, 0.6, 1.0] and steps[-1][1] == "Gotowe"
    a = next(r for r in rows if r["ticker"] == "A")
    assert a["ok"] and a["glb_state"] == "SYGNAŁ"
    assert not next(r for r in rows if r["ticker"] == "B")["ok"]   # za mały obrót
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
