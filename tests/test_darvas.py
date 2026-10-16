"""Parytet z docs/js/darvas.js z Momentum: oczekiwane wartości policzone tamtym kodem (node) na tej samej serii."""

from desktop import darvas

C = [10, 10.5, 11, 12, 11.5, 11.2, 11.4, 11.1, 12.5, 13, 12.8, 12.6, 12.2, 12.9, 14, 15, 14.5, 14.2, 14.4, 14.1, 13.9, 16]


def test_boxes_match_js():
    got = [(b["i0"], b["i1"], b["top"], b["bottom"], b["confirmed"], b["outcome"]) for b in darvas.boxes(C, 3)]
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


def test_pure_darvas_buys_on_plain_breakout_and_daily_text_uses_sessions():
    vol = [100] * 21 + [50]                       # przebicie na słabym wolumenie
    assert darvas.status(C, vol)["state"] == "NOVOL"
    assert darvas.status(C, vol, pure=True)["state"] == "BUY"
    far = C[:-1] + [C[-2] * 1.5]                  # daleko nad górą: normalnie ZA PÓŹNO, w czystym — KUP
    assert darvas.status(far)["state"] == "LATE" and darvas.status(far, pure=True)["state"] == "BUY"
    assert "sesji" in darvas.status([10, 11, 12, 13, 12.5, 12.0, 11.8, 12.2, 12.4, 12.1], **darvas.DAILY)["text"]


def test_weekly_confirm_is_two_and_daily_three():
    # IOVA 2026-05…08 (zamknięcia tygodniowe): silny trend z krótkimi konsolidacjami — przy „zamknięcie + 2 kolejne” powstają niepotwierdzone boxy
    c = [3.45, 4.11, 4.1, 4.23, 4.08, 3.91, 4.25, 4.31, 4.23, 5.0, 4.99, 4.07, 6.34, 6.98, 8.29, 8.01, 8.79, 8.6]
    two = [(b["top"], b["bottom"], b["confirmed"], b["outcome"]) for b in darvas.boxes(c)]
    assert (4.23, 3.91, False, "up") in two and (5.0, 4.07, False, "up") in two
    assert darvas.boxes(c, 3) == [] and darvas.confirm_for("W") == 2 and darvas.confirm_for("D") == 3
    assert darvas.DAILY["confirm"] == 3


MRVL = [66.14, 65.35, 58.92, 60.22, 68.93, 71.44, 75.81, 65.83, 74.06, 73.45, 70.59, 73.0, 73.65, 79.47, 81.22, 84.36, 93.35, 87.41, 92.07, 92.25,
        112.97, 120.19, 111.36, 113.08, 117.61, 113.83, 124.22, 123.49, 112.38, 110.15, 106.05, 103.36, 91.43, 70.54, 68.45, 70.09, 61.77]


def test_falling_series_without_confirmed_bottom_is_not_a_box():
    c = [10, 11, 12, 13, 12, 11, 10, 9, 8, 7, 6]
    assert darvas.boxes(c) == []


def test_zone_is_observed_and_only_exit_level_sells():
    base = [10, 11, 12, 13, 12.5, 12.0, 11.8, 12.2, 12.4, 12.1, 11.9, 12.3, 12.0]
    zone = darvas.status(base + [11.7])                    # pod dnem 11,8, ale nad poziomem wyjścia 11,21 = strefa zagrożenia: obserwuj
    assert zone["state"] != "SELL" and zone["stop"] == 11.21
    sell = darvas.status(base + [11.7, 11.0])              # zamknięcie pod 11,21 = box przestaje obowiązywać
    assert sell["state"] == "SELL" and sell["stop"] == 11.21 and "poziom wyjścia" in sell["text"]
    assert darvas.status(base + [11.7, 11.0, 12.1])["state"] != "SELL"   # powrót w górę: nie ma już sygnału sprzedaży


def test_exit_level_is_zone_edge_or_10_pct_under_top_for_large_box():
    assert darvas.exit_level(120.19, 111.36) == 111.36 * 0.95           # głębokość 7,3 % — dolna krawędź strefy zagrożenia
    assert darvas.exit_level(100, 80) == 90                             # duży box (20 %): 10 % pod górą


MRVL = [66.14, 65.35, 58.92, 60.22, 68.93, 71.44, 75.81, 65.83, 74.06, 73.45, 70.59, 73.0, 73.65, 79.47, 81.22, 84.36, 93.35, 87.41, 92.07, 92.25,
        112.97, 120.19, 111.36, 113.08, 117.61, 113.83, 124.22, 123.49, 112.38, 110.15, 106.05, 103.36, 91.43, 70.54, 68.45, 70.09, 61.77]


def test_broken_out_box_is_tracked_until_price_leaves_its_zone():
    # box 120,19 / 111,36 wybity; powrót do boxa i do strefy zagrożenia go nie kończy, dopiero zamknięcie pod 105,79 (103,36)
    bx = darvas.boxes(MRVL)
    r = next(b for b in bx if b["top"] == 120.19)
    assert r["outcome"] == "up" and r["end"] == MRVL.index(103.36)
    assert not any(b["top"] == 124.22 for b in bx)                      # nowy box nie powstał (dół się nie ustalił) — nie jest rysowany
    assert not any(b["i0"] > r["end"] and b["top"] - b["bottom"] > 0.3 * b["top"] for b in bx)   # po wyjściu nie ma „boxa” z samego spadku
    st = darvas.status(MRVL)
    assert st["state"] == "SELL" and st["stop"] == 105.79
    assert darvas.status(MRVL[:30])["state"] == "HOLD"                  # 110,15: w strefie zagrożenia, obserwujemy


def test_double_breakout_buys_again_after_dip_inside_box():
    c = [10, 11, 12, 13, 12.5, 12.0, 11.8, 12.2, 12.4, 12.1, 11.9, 13.5, 12.8, 13.6]
    assert darvas.status(c[:12])["state"] == "BUY"        # pierwsze wybicie nad 13
    assert darvas.status(c[:13])["state"] == "HOLD"       # powrót do boxa: box nadal obowiązuje
    assert darvas.status(c)["state"] == "BUY"             # drugie wybicie
