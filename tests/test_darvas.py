"""Reguły boxów Darvasa (tygodniowe zamknięcia): góra / dół = zamknięcie nieprzebite przez 3 kolejne tygodnie, tylko potwierdzone boxy, sam top = linia."""
from desktop import darvas

S = [10, 11, 12, 13, 12.5, 12.0, 11.8, 12.2, 12.4, 12.1, 12.3]      # top 13 (idx 3), dół 11,8 (idx 6) potwierdzony po 3 tygodniach (idx 9)
MRVL = [66.14, 65.35, 58.92, 60.22, 68.93, 71.44, 75.81, 65.83, 74.06, 73.45, 70.59, 73.0, 73.65, 79.47, 81.22, 84.36, 93.35, 87.41, 92.07, 92.25,
        112.97, 120.19, 111.36, 113.08, 117.61, 113.83, 124.22, 123.49, 112.38, 110.15, 106.05, 103.36, 91.43, 70.54, 68.45, 70.09, 61.77]


def test_top_and_bottom_need_three_weeks():
    bx = darvas.boxes(S)
    assert [(b["i0"], b["top"], b["bottom"], b["outcome"]) for b in bx] == [(3, 13, 11.8, "open")]
    assert darvas.top_lines(S) == []
    assert darvas.top_lines([10, 11, 12, 13, 12.5, 12.0]) == []          # za wcześnie: tylko 2 tygodnie po topie
    assert darvas.confirm_for("W") == 3 and darvas.confirm_for("D") == 3


def test_only_top_is_a_dashed_line_until_broken_with_8_pct_stop():
    c = [10, 11, 12, 13, 12.5, 12.0, 11.8]
    assert darvas.boxes(c) == []                                            # dół jeszcze niepotwierdzony — nie ma boxa
    assert darvas.top_lines(c) == [{"i0": 3, "i1": 6, "top": 13, "open": True}]
    st = darvas.status(c)
    assert st["state"] == "WAIT" and st["stop"] == 11.96 and darvas.line_info(13)["stop"] == 11.96
    broken = c + [13.5]
    assert darvas.boxes(broken) == [] and darvas.top_lines(broken) == [{"i0": 3, "i1": 7, "top": 13, "open": False}]
    st = darvas.status(broken)
    assert st["state"] == "BUY" and st["stop"] == 11.96                     # wybicie samego topu: stop 8 %


def test_breakout_attempt_keeps_box_until_price_falls_into_its_zone():
    up = S + [13.5]
    assert darvas.boxes(up)[0]["outcome"] == "up" and darvas.status(up)["state"] == "BUY"
    back = darvas.status(up + [12.8, 12.0])                                 # powrót do boxa: nadal obowiązuje
    assert back["state"] == "HOLD" and "w boxie" in back["text"]
    bx = darvas.boxes(up + [12.8, 12.0, 11.5])                              # zejście pod dno 11,8 = strefa zagrożenia: anulowany
    assert bx[0]["cancelled"] and bx[0]["end"] == len(up) + 2
    assert darvas.status(up + [12.8, 12.0, 11.5])["state"] == "SELL"


def test_double_breakout_buys_again_after_dip_inside_box():
    c = [10, 11, 12, 13, 12.5, 12.0, 11.8, 12.2, 12.4, 12.1, 11.9, 13.5, 12.8, 13.6]
    assert darvas.status(c[:12])["state"] == "BUY"        # pierwsza próba przebicia
    assert darvas.status(c[:13])["state"] == "HOLD"       # powrót do boxa: box obowiązuje
    assert darvas.status(c)["state"] == "BUY"             # druga próba


def test_new_box_above_replaces_the_broken_out_one():
    c = S + [13.5, 14, 14.5, 14.2, 14.0, 14.1, 14.3, 14.2]
    old, new = darvas.boxes(c)
    assert old["outcome"] == "up" and old["end"] == new["i0"] == 13 and not old.get("cancelled")
    assert (new["top"], new["bottom"]) == (14.5, 14.0)


def test_box_broken_below_without_breakout_is_inverted_and_new_search_starts():
    c = S + [11.5]
    bx = darvas.boxes(c)
    assert bx[0]["outcome"] == "down" and bx[0]["i1"] == len(S)
    assert darvas.status(c)["state"] == "SELL"
    assert darvas.status(S + [11.5, 12.9])["state"] == "WAIT"               # cena wróciła nad dno, box i tak anulowany — czekamy na nowy


def test_falling_knife_makes_no_box():
    assert darvas.boxes([10, 11, 12, 13, 12, 11, 10, 9, 8, 7, 6]) == []


def test_mrvl_breakout_box_cancelled_in_danger_zone_and_no_giant_box():
    bx = darvas.boxes(MRVL)
    r = next(b for b in bx if b["top"] == 120.19)
    assert r["outcome"] == "up" and r["cancelled"] and r["end"] == MRVL.index(110.15)       # pod dnem 111,36
    assert not any(b["top"] == 124.22 for b in bx)                         # tego „boxa” nie ma — dół się nie ustalił
    assert max((b["top"] - b["bottom"]) / b["top"] for b in bx) < 0.2      # żadnego wielkiego boxa przez całą korektę
    assert darvas.status(MRVL[:28])["state"] == "HOLD" and darvas.status(MRVL)["state"] == "SELL"


def test_status_late_and_volume_rules():
    vol = [100] * 11 + [300]
    st = darvas.status(S + [13.5], vol)
    assert st["state"] == "BUY" and st["vol_ratio"] == 3 and st["text"].startswith("KUP — zamknięcie nad górą 13 na wolumenie 3.00×")
    assert darvas.status(S + [13.5], [100] * 12)["state"] == "NOVOL"
    assert darvas.status(S + [15])["state"] == "LATE"
    weak = [100] * 11 + [50]
    assert darvas.status(S + [13.5], weak, pure=True)["state"] == "BUY"
    assert darvas.status(S + [15], pure=True)["state"] == "BUY"
    assert "sesji" in darvas.status(S + [12.2], **darvas.DAILY)["text"]


def test_pin_status():
    box = {"top": 12, "bottom": 10}
    assert darvas.pin_status(box, 9.8) == {"state": "ZONE", "rank": 0, "text": "W STREFIE ZAGROŻENIA 9.5–10 — potencjalny exit"}
    assert darvas.pin_status(box, 13)["state"] == "ABOVE"
    assert darvas.pin_status(box, 11)["state"] == "INSIDE"
    assert darvas.pin_status(box, 9)["state"] == "EXIT"
    assert darvas.pin_status(None, 9)["state"] == "NONE"


def test_box_info_zone_is_5_pct_under_bottom():
    info = darvas.box_info(230.1, 218.29)
    assert info["stop"] == 207.38 and info["entry"] == 230.1 and info["depth_pct"] == 5.13


def test_too_short_series():
    assert darvas.boxes([1, 2, 3]) == []
    assert darvas.status([1, 2, 3])["state"] == "NONE"


def test_overview_sections():
    items = [{"ticker": "AAA", "price": 13.5, "c": S + [13.5], "v": [100] * 11 + [300]}, {"ticker": "BBB", "price": 5, "c": [1, 2]}]
    ov = darvas.overview(items, ["w"] * 12, {"AAA": {"top": 13, "bottom": 11.8, "start": "w"}})
    assert [r["ticker"] for r in ov["buy"]] == ["AAA"]
    assert ov["pinned"][0]["state"] == "ABOVE"


def test_pinned_top_line_has_8_pct_stop_and_no_danger_zone():
    pin = {"top": 13, "bottom": 11.96, "line": True}
    assert darvas.pin_status(pin, 13.5)["state"] == "ABOVE"
    assert darvas.pin_status(pin, 12.5)["state"] == "INSIDE"
    assert darvas.pin_status(pin, 12.0)["state"] == "INSIDE"                # nie ma strefy zagrożenia: poniżej stopu od razu EXIT
    st = darvas.pin_status(pin, 11.9)
    assert st["state"] == "EXIT" and "11.96" in st["text"]
