"""Linie trendu, alerty i filtry listy (ta sama logika co tests/js/lines.test.js w wersji webowej)."""
import math

import pytest

from desktop import lines as L

D = ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26", "2026-02-02"]


def test_date_index_and_line_at():
    assert L.date_index(D, "2026-01-19") == 2 and L.date_index(D, "2026-01-21") == 2
    assert L.date_index(D, "2025-12-01") == -1 and L.date_index(D, "2027-01-01") == 4
    ln = {"d1": D[0], "p1": 10, "d2": D[2], "p2": 40}
    assert math.isclose(L.line_at(ln, D, 1), 20) and math.isclose(L.line_at(ln, D, 4), 160)
    assert L.line_at({"d1": D[1], "p1": 1, "d2": D[1], "p2": 2}, D, 3) is None


def test_line_cross():
    flat = {"d1": D[0], "p1": 100, "d2": D[1], "p2": 100}
    assert L.line_cross(flat, {"d": D, "c": [90, 95, 96, 98, 101]}) == "up"
    assert L.line_cross(flat, {"d": D, "c": [90, 95, 96, 102, 99]}) == "down"
    assert L.line_cross(flat, {"d": D, "c": [90, 95, 96, 98, 99]}) is None


def test_hit_and_snap():
    segs = [{"id": "a", "x1": 0, "y1": 0, "x2": 100, "y2": 0, "xe": 200, "ye": 0}]
    assert L.hit_line(segs, 3, 2, 7) == ("a", "p1")
    assert L.hit_line(segs, 50, 4, 7) == ("a", "body") and L.hit_line(segs, 150, 3, 7) == ("a", "body")
    assert L.hit_line(segs, 50, 20, 7) is None
    assert L.snap_price(57, 60, 40, lambda p: 200 - p, 143, 8) == 60
    assert L.snap_price(50, 60, 40, lambda p: 200 - p, 150, 8) == 50


def test_eval_alerts_dedup():
    prev = {"glb_state": "POD", "macd": "nad", "macd_stop": 90, "price": 95, "ok": False}
    row = {"ticker": "A", "glb_state": "WYBICIE", "glb": 100, "macd": "pod", "macd_stop": 105, "price": 104, "ok": True}
    assert len(L.state_alerts(prev, row)) == 4
    st = {"lines": {"A": [{"id": "x", "d1": D[0], "p1": 100, "d2": D[1], "p2": 100}]}, "watch": {"A": prev}, "log": []}
    series = {"d": D, "c": [90, 95, 96, 98, 104]}
    assert len(L.eval_alerts(st, lambda t: row, lambda t: series, "2026-02-07T08:00", D[4])) == 5
    assert st["watch"]["A"]["glb_state"] == "WYBICIE"
    assert L.eval_alerts(st, lambda t: row, lambda t: series, "2026-02-07T09:00", D[4]) == []



def test_monthly_line_alert_uses_weekly_close_and_deduplicates():
    dates = ["2026-10-05", "2026-10-12", "2026-10-19"]
    weekly = {"d": dates, "c": [98, 99, 101]}
    ln = {"id": "m-1", "period": "M", "d1": dates[0], "p1": 100, "d2": dates[1], "p2": 100, "alert": True}
    st = {"lines": {"AAA": [ln]}, "watch": {}, "pos": {}, "log": []}

    fresh = L.eval_alerts(st, lambda t: None, lambda t: weekly, "2026-10-22T09:00")
    assert len(fresh) == 1
    assert fresh[0]["key"] == "L:AAA:m-1:2026-10-19:up"
    assert "zamknięcie tyg. (linia miesięczna) nad linią trendu" in fresh[0]["msg"]
    assert L.eval_alerts(st, lambda t: None, lambda t: weekly, "2026-10-22T10:00") == []


def test_list_filters():
    from desktop.app import FILTER_PRESETS, active_filters, pass_filters
    rows = [{"ticker": "A", "ok": True, "glb_state": "NAD", "macd": "nad", "glb_pct": 15, "turnover": 80e6},
            {"ticker": "B", "ok": True, "glb_state": "NAD", "macd": "pod", "glb_pct": 12, "turnover": 60e6},
            {"ticker": "C", "ok": False, "glb_state": "POD", "macd": "nad", "glb_pct": -5, "turnover": None}]
    assert [r["ticker"] for r in rows if pass_filters(r, dict(FILTER_PRESETS)["Nad GLB + MACD dodatni"])] == ["A"]
    assert [r["ticker"] for r in rows if pass_filters(r, {"turnover": {"min": 70}})] == ["A"]
    assert [r["ticker"] for r in rows if pass_filters(r, {"glb_pct": {"max": 12}, "ok": {"in": ["nie"]}})] == ["C"]
    assert active_filters({"a": {"in": []}, "b": {"min": 1}, "c": {}}) == 1


def test_default_order_signal_first_then_nearest_line():
    from desktop.app import default_order, is_signal
    rows = [{"ticker": "A", "ok": True, "glb_state": "SYGNAŁ", "glb_pct": 7, "rs": 55}, {"ticker": "B", "ok": True, "glb_state": "WYBICIE", "glb_pct": 2, "rs": 10},
            {"ticker": "C", "ok": True, "glb_state": "POD", "glb_pct": -20, "rs": 120}, {"ticker": "D", "ok": False, "rs": 300},
            {"ticker": "E", "ok": True, "glb_state": "WYBICIE", "glb_pct": 15, "rs": 99}]
    assert [r["ticker"] for r in sorted(rows, key=default_order)] == ["B", "A", "E", "C", "D"]
    assert not is_signal({"glb_state": "BLUE DOT", "glb_pct": 12}) and not is_signal(rows[4]) and is_signal(rows[1])


def test_macd_stop_since_entry():
    n, d, c, lo = 60, [], [], []
    for i in range(n):
        d.append(f"2025-{1 + i // 5:02d}-{1 + (i % 5) * 6:02d}")
        v = 100 + i if i < 20 else 120 - (i - 20) * 3 if i < 26 else 102 + (i - 26) * 2 if i < 45 else 140 - (i - 45) * 2
        c.append(v)
        lo.append(v - 1)
    s = {"d": d, "c": c, "l": lo}
    allx = L.macd_stop_since(s, "")
    assert allx is not None and L.macd_stop_since(s, d[46]) == allx
    assert L.macd_stop_since(s, d[-1]) is None and L.position_plan({"since": d[-1], "price": 120}, s, {})["macd_stop"] is None


def test_position_plan_and_half_sell_alert():
    d = ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26", "2026-02-02"]
    s = {"d": d, "c": [100, 120, 150, 130, 118]}
    pl = L.position_plan({"since": d[1], "price": 120}, s, {"glb": 125})
    assert pl["stop_init"] == pytest.approx(108) and pl["peak"] == 150 and pl["half_at"] == pytest.approx(120) and pl["half"] and pl["glb_exit"]
    assert not L.position_plan({"since": d[1], "price": 120}, {"d": d[:3], "c": [100, 120, 150]}, {"glb": 110})["half"]
    st = {"lines": {}, "watch": {"X": {"glb_state": "SYGNAŁ", "macd": "nad", "price": 130, "ok": True}}, "pos": {"X": {"since": d[1], "price": 120}}, "log": []}
    row = {"ticker": "X", "glb": 125, "glb_state": "POD", "macd": "nad", "price": 118, "ok": True}
    msgs = [a["msg"] for a in L.eval_alerts(st, lambda t: row, lambda t: s, "now", d[4])]
    assert any("sprzedaj połowę" in m for m in msgs) and any("pod Green Line" in m for m in msgs)
    assert L.eval_alerts(st, lambda t: row, lambda t: s, "later", d[4]) == []          # raz na szczyt / tydzień


def test_trend_filter_and_preset():
    from desktop.app import FILTER_PRESETS, filter_value, pass_filters
    assert filter_value({"trend": True}, "trend") == "tak" and filter_value({}, "trend") == "nie"
    f = dict(FILTER_PRESETS)["Przebicie GLB + SMA 10 > 30 (dowolnie wysoko)"]
    assert pass_filters({"trend": True, "glb_state": "NAD"}, f) and not pass_filters({"trend": False, "glb_state": "NAD"}, f)


def test_position_status():
    pl = {"last": 100, "stop_init": 108, "half": True, "glb_exit": True}
    assert L.position_status(pl, {"slow": "HAMUJE"}, "GLB") == ["STOP −10 %", "WYJŚCIE: zamknięcie pod GLB", "SPRZEDAJ ½ (−20 % od szczytu)", "⚠ hamuje"]
    assert L.position_status({**pl, "stop_init": 90, "half": False}, {"macd_stop": 105}, "MACD") == ["WYJŚCIE: pod stopem MACD"]
    assert L.position_status({"last": 150, "stop_init": 108}, {"macd_stop": 105}, "MACD") == []
    assert L.position_status({"last": 100, "stop_init": 90, "macd_stop": None}, {"macd_stop": 105}, "MACD") == []   # MACD sprzed wejścia się nie liczy
    assert L.position_status({"last": 100, "stop_init": 90, "macd_stop": 104}, {"macd_stop": 95}, "MACD") == ["WYJŚCIE: pod stopem MACD"]
