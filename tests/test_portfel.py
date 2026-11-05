"""Portfel CEM10 z raportu XTB (bez sieci): odczyt arkuszy, udziały, stop −40 %, status CEM10, plan wpłaty, krzywa kapitału."""
import datetime as dt
import io
import zipfile

import pytest

from desktop import portfel as P

openpyxl = pytest.importorskip("openpyxl")


def _xlsx():
    """Raport w układzie XTB: 3 arkusze, nagłówki jak w xStation (dwa nagłówki „Product” w Open Positions)."""
    wb = openpyxl.Workbook()
    cp = wb.active
    cp.title = "Closed Positions"
    for r in (["Account number", "1"], ["Closed Positions", ""], ["Date from (UTC)", dt.datetime(2006, 1, 1)],
              ["Instrument", "Ticker", "Category", "Type", "Volume", "Open Price", "Open Time (UTC)", "Close Price", "Close Time (UTC)", "Product",
               "Profit/Loss", "Gross Profit", "Purchase Value", "Sale Value"],
              ["Old", "OLD.US", "STOCK", "BUY", 1.0, 100.0, dt.datetime(2026, 1, 5, 15), 120.0, dt.datetime(2026, 2, 2, 15), "IKE", 76.0, 76.0, 380.0, 456.0]):
        cp.append(r)
    co = wb.create_sheet("Cash Operations")
    for r in (["Account number", "1"], ["Cash Operations", ""],
              ["Type", "Instrument", "Ticker", "Category", "Time", "Amount", "ID", "Comment", "Product", "Position ID"],
              ["IKE deposit", "", "", "", dt.datetime(2026, 1, 2, 9), 2000.0, "1", "", "IKE", ""],
              ["Stock purchase", "Old", "OLD.US", "STOCK", dt.datetime(2026, 1, 5, 15), -380.0, "2", "", "IKE", ""],
              ["Stock sell", "Old", "OLD.US", "STOCK", dt.datetime(2026, 2, 2, 15), 456.0, "3", "", "IKE", ""],
              ["Stock purchase", "Alfa", "AAA.US", "STOCK", dt.datetime(2026, 3, 2, 15), -760.0, "4", "", "IKE", ""],
              ["Stock purchase", "Beta", "BBB.PL", "STOCK", dt.datetime(2026, 3, 2, 10), -500.0, "5", "", "IKE", ""],
              ["Stock purchase", "Gamma", "CCC.US", "STOCK", dt.datetime(2026, 3, 2, 15), -380.0, "6", "", "IKE", ""],
              ["Total", "", "", "", "", 436.0, "", "", "", ""]):
        co.append(r)
    op = wb.create_sheet("Open Positions")
    for r in (["Account number", "1"], ["Open Positions", ""], ["Data as of report generated", dt.datetime(2026, 4, 1, 12)],
              ["Product", "Metric", "Amount", "Currency"], ["IKE", "Open position value", 1900.0, ""],
              ["Product", "Instrument/Position", "Ticker", "Category", "Type", "Volume", "Value", "Current price", "Open price", "Open time (UTC)",
               "Stop Loss", "Take Profit", "Net Profit %", "Net Profit"],
              ["IKE", "Alfa", "AAA.US", "STOCK", "", 2.0, 912.0, "", 100.0, "", "", "", 20.0, 152.0],
              ["IKE", "11", "AAA.US", "", "BUY", 2.0, 912.0, 120.0, 100.0, dt.datetime(2026, 3, 2, 15), "", "", 20.0, 152.0],
              ["IKE", "Beta", "BBB.PL", "STOCK", "", 10.0, 600.0, "", 50.0, "", "", "", 20.0, 100.0],
              ["IKE", "12", "BBB.PL", "", "BUY", 10.0, 600.0, 60.0, 50.0, dt.datetime(2026, 3, 2, 10), "", "", 20.0, 100.0],
              ["IKE", "Gamma", "CCC.US", "STOCK", "", 1.0, 388.0, "", 100.0, "", "", "", 2.1, 8.0],
              ["IKE", "13", "CCC.US", "", "BUY", 1.0, 388.0, 102.1, 100.0, dt.datetime(2026, 3, 2, 15), "", "", 2.1, 8.0]):
        op.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _zip():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("1/IKE_1_2006-01-01_2026-04-01.xlsx", _xlsx())
    return b.getvalue()


CEM = {"usa": {"lead": "SP", "bear": False, "rows": [
    {"t": "AAA", "n": "Alfa", "sp": True, "nq": False, "c": 120.0, "sma": 100.0, "dist": 0.2, "r3": 0.1, "r6": 0.9, "r12": 1.0},
    {"t": "CCC", "n": "Gamma", "sp": True, "nq": False, "c": 102.0, "sma": 110.0, "dist": -0.07, "r3": 0.0, "r6": 0.4, "r12": 0.5},
    {"t": "DDD", "n": "Delta", "sp": True, "nq": False, "c": 50.0, "sma": 40.0, "dist": 0.25, "r3": 0.1, "r6": 0.8, "r12": 1.0}]},
    "gpw": {"bear": False, "rows": [{"t": "BBB", "n": "Beta", "w20": True, "w40": False, "c": 60.0, "sma": 50.0, "dist": 0.2, "r3": 0.1, "r6": 0.5, "r12": 0.6}]}}


def test_load_report_positions_cash_and_closed():
    acc = P.load_report(_zip())[0]
    assert acc["label"] == "IKE" and acc["open_value"] == 1900.0 and acc["cash"] == 436.0
    assert [p["ticker"] for p in acc["positions"]] == ["AAA.US", "BBB.PL", "CCC.US"] and len(acc["lots"]) == 3 and len(acc["closed"]) == 1
    assert round(acc["positions"][0]["fx"], 2) == 3.8 and P.currency(3.8) == "USD" and P.currency(1.0) == "PLN"
    assert P.flows(acc) == [("2026-01-02", 2000.0)] and P.exits(acc) == [("2026-02-02", "OLD", 76.0, 0.2)]


def test_holdings_shares_stop_and_status():
    acc = P.load_report(_zip())[0]
    rows, buckets, total = P.holdings(acc, CEM)
    by = {h["t"]: h for h in rows}
    assert total == 2336.0 and buckets == {"usa": 1300.0, "gpw": 600.0}
    assert round(by["AAA"]["share"], 3) == round(912 / 2336, 3) and by["AAA"]["stop"] == 60.0 and by["AAA"]["status"] == "kandydat #1"
    assert by["CCC"]["status"] == "SPRZEDAJ (pod SMA 10)" and by["BBB"]["status"] == "kandydat #1" and by["BBB"]["bucket_share"] == 1.0
    assert P.base_ticker("BRK.B.US") == "BRK-B" and P.yahoo("BRK.B.US") == "BRK-B" and P.yahoo("ALE.PL") == "ALE.WA" and P.yahoo("CSPX.UK") == "CSPX.L"


def test_plan_sells_buys_new_and_tops_up_to_target():
    acc = P.load_report(_zip())[0]
    acts, s = P.plan(acc, CEM, deposit=1000.0, targets={"usa": 50, "gpw": 50, "etf": 0}, slots={"usa": 2, "gpw": 1})
    a = [(x["akcja"], x["ticker"]) for x in acts]
    assert a[0] == ("SPRZEDAJ", "CCC")                      # pod SMA 10
    assert ("KUP", "DDD") in a                               # wolne miejsce po CCC -> kolejny kandydat z listy
    assert all(x["kwota"] >= P.MIN_TOPUP for x in acts if x["akcja"] != "SPRZEDAJ")
    assert round(s["free"], 2) == round(436 + 1000 + 388, 2)
    bear = {**CEM, "usa": {**CEM["usa"], "bear": True}}
    acts2, s2 = P.plan(acc, bear, deposit=1000.0, targets={"usa": 50, "gpw": 50, "etf": 0}, slots={"usa": 2, "gpw": 1})
    assert not any(x["koszyk"] == "usa" and x["akcja"] != "SPRZEDAJ" for x in acts2) and s2["notes"]


def test_sold_slot_goes_to_next_candidate_even_when_etf_is_underweight():
    acc = P.load_report(_zip())[0]
    acts, s = P.plan(acc, CEM, deposit=1000.0, targets={"usa": 10, "gpw": 10, "etf": 80}, slots={"usa": 3, "gpw": 2})
    a = [(x["akcja"], x["ticker"]) for x in acts]
    assert ("SPRZEDAJ", "CCC") in a and ("KUP", "DDD") in a and ("KUP", "CSPX") in a     # sprzedane miejsce -> kolejny kandydat, reszta do ETF
    assert round(next(x["kwota"] for x in acts if x["ticker"] == "DDD"), 2) == 388.0


def test_plan_sells_position_below_stop_even_above_sma():
    import copy
    acc = copy.deepcopy(P.load_report(_zip())[0])
    for p in acc["positions"]:
        if p["ticker"].startswith("AAA"):
            p["price"] = 55.0                                  # open 100 -> -45 %: stop -40 % przekroczony, choć wiersz listy jest nad SMA 10
            p["value"] *= 55 / 120
    acts, _ = P.plan(acc, CEM, deposit=1000.0, targets={"usa": 50, "gpw": 50, "etf": 0}, slots={"usa": 3, "gpw": 2}, topup="all")
    assert ("SPRZEDAJ", "AAA") in [(x["akcja"], x["ticker"]) for x in acts]
    assert not any(x["akcja"] == "DOPŁAĆ" and x["ticker"] == "AAA" for x in acts)


def test_topup_switch_off_has_no_dopłać():
    acc = P.load_report(_zip())[0]
    acts, s = P.plan(acc, CEM, deposit=1000.0, targets={"usa": 50, "gpw": 50, "etf": 0}, slots={"usa": 2, "gpw": 1}, topup="off")
    assert not any(x["akcja"] == "DOPŁAĆ" for x in acts) and any("wyłączone" in n for n in s["notes"])


def test_topup_only_for_positions_in_profit():
    base = {"open_price": 100.0, "rank": 1}
    assert P._in_profit({**base, "price": 100.0}) and P._in_profit({**base, "price": 130.0})
    assert not P._in_profit({**base, "price": 80.0})                 # Dell -20 %: bez dopłaty
    assert not P._in_profit({"price": 80.0}) and not P._in_profit({"open_price": 100.0})


def test_curve_cash_plus_positions_and_deposits():
    acc = P.load_report(_zip())[0]
    pts = P.curve(acc, px={"AAA": {"2026-03-02": 100.0, "2026-04-01": 120.0}}, fxs={"USD": {"2026-01-01": 3.8}})
    d = {p[0]: p for p in pts}
    assert d["2026-01-02"][1] == 2000.0 and d["2026-01-02"][2] == 2000.0      # sama wpłata
    assert pts[-1][2] == 2000.0 and abs(pts[-1][1] - (436 + 2 * 120 * 3.8 + 600 + 102.1 * 3.8)) < 1


# ---------------------------------------------------------------- wskaźniki jakości
def _pts(vals, deps=None, start="2025-01-01"):
    d0 = dt.date.fromisoformat(start)
    return [((d0 + dt.timedelta(i)).isoformat(), v, (deps or [0] * len(vals))[i]) for i, v in enumerate(vals)]


def test_performance_deposits_are_not_returns():
    # 100 zł, potem wpłata 100 zł (200), spadek do 180 = −10 %, nie −45 %
    vals = [100] * 10 + [200] * 10 + [180] * 10
    deps = [100] * 10 + [200] * 20
    m = P.performance(_pts(vals, deps))
    assert abs(m["max_dd"] + 0.10) < 1e-9 and abs(m["twr"] + 0.10) < 1e-9
    assert abs(m["dd"] + 0.10) < 1e-9


def test_performance_cagr_vol_and_months():
    vals = [100 * 1.001 ** i for i in range(400)]   # stały wzrost 0,1 % dziennie, bez wpłat po starcie
    m = P.performance(_pts(vals, [100] * 400))
    assert m["cagr"] is not None and m["cagr"] > 0.4 and m["max_dd"] == 0 and m["calmar"] is None
    assert m["vol"] is not None and m["vol"] < 1e-6 and m["months"]["pos"] == 1.0 and m["years"] > 1.0
    assert P.performance(_pts([100] * 5)) is None   # za mało danych


def test_performance_xirr_matches_simple_growth():
    # 1000 zł wpłacone na początku, wzrost 10 % rocznie przez ponad rok -> XIRR i CAGR ok. 10 %
    vals = [1000 * 1.1 ** (i / 365) for i in range(400)]
    m = P.performance(_pts(vals, [1000] * 400, start="2025-01-01"))
    assert abs(m["xirr"] - 0.10) < 0.01 and abs(m["cagr"] - 0.10) < 0.01


def test_trade_stats_and_hold():
    acc = {"closed": [
        {"ticker": "AAA.US", "close": "2025-03-10T10:00:00", "open": "2025-01-10T10:00:00", "profit": 200.0, "buy": 1000.0},
        {"ticker": "BBB.US", "close": "2025-04-10T10:00:00", "open": "2025-03-10T10:00:00", "profit": -100.0, "buy": 1000.0},
        {"ticker": "CCC.US", "close": "2025-05-10T10:00:00", "open": "2025-04-10T10:00:00", "profit": 400.0, "buy": 1000.0}]}
    tr = P.trades(acc)
    s = P.trade_stats(tr)
    assert s["n"] == 3 and s["wins"] == 2 and abs(s["win_rate"] - 2 / 3) < 1e-9
    assert abs(s["avg_win"] - 0.3) < 1e-9 and abs(s["avg_loss"] + 0.1) < 1e-9 and abs(s["payoff"] - 3.0) < 1e-9
    assert abs(s["profit_factor"] - 6.0) < 1e-9 and abs(s["expectancy"] - 0.5 / 3) < 1e-9 and abs(s["avg_hold"] - (59 + 31 + 30) / 3) < 1e-9
    assert P.trade_stats([]) is None


def test_assess_early_and_bad_levels():
    short = P.performance(_pts([100 + i for i in range(60)], [100] * 60))
    assert short["verdict"]["level"] == "early"
    # po 3 latach: spadek o 45 % od szczytu jest gorszy niż najgorszy w historii (−33,5 %) -> bad
    vals = [100 * 1.0007 ** i for i in range(800)] + [100 * 1.0007 ** 800 * (1 - 0.45 * i / 200) for i in range(1, 201)]
    m = P.performance(_pts(vals, [100] * len(vals)))
    assert m["months_n"] >= 24 and m["verdict"]["level"] == "bad" and m["dd"] < -0.4


def test_bench_series_aligns_last_known_price():
    out = P.bench_series(["2025-01-02", "2025-01-03", "2025-01-06"], {"2025-01-02": 500.0, "2025-01-06": 510.0}, {"2025-01-01": 4.0})
    assert out == [("2025-01-02", 2000.0), ("2025-01-03", 2000.0), ("2025-01-06", 2040.0)]
    assert P.bench_series(["2025-01-02"], {}, {"2025-01-01": 4.0}) == []
