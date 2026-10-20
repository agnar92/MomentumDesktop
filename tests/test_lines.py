"""Linie trendu, alerty i filtry listy (ta sama logika co tests/js/lines.test.js w wersji webowej)."""
import math

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


def test_list_filters():
    from desktop.app import FILTER_PRESETS, active_filters, pass_filters
    rows = [{"ticker": "A", "ok": True, "glb_state": "NAD", "macd": "nad", "glb_pct": 15, "turnover": 80e6},
            {"ticker": "B", "ok": True, "glb_state": "NAD", "macd": "pod", "glb_pct": 12, "turnover": 60e6},
            {"ticker": "C", "ok": False, "glb_state": "POD", "macd": "nad", "glb_pct": -5, "turnover": None}]
    assert [r["ticker"] for r in rows if pass_filters(r, dict(FILTER_PRESETS)["Nad GLB + MACD dodatni"])] == ["A"]
    assert [r["ticker"] for r in rows if pass_filters(r, {"turnover": {"min": 70}})] == ["A"]
    assert [r["ticker"] for r in rows if pass_filters(r, {"glb_pct": {"max": 12}, "ok": {"in": ["nie"]}})] == ["C"]
    assert active_filters({"a": {"in": []}, "b": {"min": 1}, "c": {}}) == 1


def test_default_order_strong_signal_first():
    from desktop.app import default_order
    rows = [{"ticker": "A", "ok": True, "glb_state": "SYGNAŁ", "dopm": 5}, {"ticker": "B", "ok": True, "strong": True, "glb_state": "WYBICIE", "dopm": 11},
            {"ticker": "C", "ok": True, "strong": True, "glb_state": "POD", "dopm": 30}, {"ticker": "D", "ok": False, "dopm": 50}]
    assert [r["ticker"] for r in sorted(rows, key=default_order)] == ["B", "A", "C", "D"]
