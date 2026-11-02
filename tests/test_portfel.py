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


def test_curve_cash_plus_positions_and_deposits():
    acc = P.load_report(_zip())[0]
    pts = P.curve(acc, px={"AAA": {"2026-03-02": 100.0, "2026-04-01": 120.0}}, fxs={"USD": {"2026-01-01": 3.8}})
    d = {p[0]: p for p in pts}
    assert d["2026-01-02"][1] == 2000.0 and d["2026-01-02"][2] == 2000.0      # sama wpłata
    assert pts[-1][2] == 2000.0 and abs(pts[-1][1] - (436 + 2 * 120 * 3.8 + 600 + 102.1 * 3.8)) < 1
