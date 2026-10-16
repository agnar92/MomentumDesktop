"""Parytet z docs/js/darvas.js z Momentum: oczekiwane wartości policzone tamtym kodem (node) na tej samej serii."""

from desktop import darvas

C = [10, 10.5, 11, 12, 11.5, 11.2, 11.4, 11.1, 12.5, 13, 12.8, 12.6, 12.2, 12.9, 14, 15, 14.5, 14.2, 14.4, 14.1, 13.9, 16]


def test_boxes_match_js():
    got = [(b["i0"], b["i1"], b["top"], b["bottom"], b["confirmed"], b["outcome"]) for b in darvas.boxes(C)]
    assert got == [(3, 8, 12, 11.1, False, "up"), (9, 14, 13, 12.2, False, "up"), (15, 21, 15, 13.9, False, "up")]


def test_status_buy_needs_volume():
    vol = [100] * 21 + [300]
    st = darvas.status(C, vol)
    assert st["state"] == "BUY" and st["vol_ratio"] == 3 and st["stop"] == 13.5
    assert st["text"].startswith("KUP — zamknięcie nad górą boxa 15 na wolumenie 3.00×")
    weak = darvas.status(C, [100] * 22)
    assert weak["state"] == "NOVOL"


def test_status_late_when_over_10_pct():
    c = C[:-1] + [17.5]
    assert darvas.status(c)["state"] == "LATE"


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
    items = [{"ticker": "AAA", "price": 16, "c": C, "v": [100] * 21 + [300]}, {"ticker": "BBB", "price": 5, "c": [1, 2]}]
    ov = darvas.overview(items, ["w"] * 22, {"AAA": {"top": 15, "bottom": 13.9, "start": "w"}})
    assert [r["ticker"] for r in ov["buy"]] == ["AAA"]
    assert ov["pinned"][0]["state"] == "ABOVE"


def test_close_under_box_bottom_is_sell_without_prior_breakout():
    base = [10, 11, 12, 13, 12.5, 12.0, 11.8, 12.2, 12.4, 12.1, 11.9, 12.3, 12.0]
    st = darvas.status(base + [11.7])                      # zamknięcie pod dnem 11.8
    assert st["state"] == "SELL" and st["bottom"] == 11.8 and st["stop"] == 11.21 and "pod dno" in st["text"]
    assert darvas.status(base + [11.7, 11.0, 10.5, 10.8])["state"] == "SELL"   # nowy box pod złamanym dnem nie kasuje sygnału
    assert darvas.status(base + [11.7, 11.0, 10.5, 12.1])["state"] != "SELL"   # powrót nad złamane dno


def test_pure_darvas_buys_on_plain_breakout_and_daily_text_uses_sessions():
    vol = [100] * 21 + [50]                       # przebicie na słabym wolumenie
    assert darvas.status(C, vol)["state"] == "NOVOL"
    assert darvas.status(C, vol, pure=True)["state"] == "BUY"
    far = C[:-1] + [C[-2] * 1.5]                  # daleko nad górą: normalnie ZA PÓŹNO, w czystym — KUP
    assert darvas.status(far)["state"] == "LATE" and darvas.status(far, pure=True)["state"] == "BUY"
    assert "sesji" in darvas.status([10, 11, 12, 13, 12.5, 12.0, 11.8, 12.2, 12.4, 12.1], **darvas.DAILY)["text"]
