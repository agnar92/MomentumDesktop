
from desktop import charts, store

ROWS = [
    {"ticker": "AAA", "company": "Alpha", "rs_rating": 90, "eps_rating": 80, "composite_rating": 85, "pct_to_pivot": 2.0,
     "pct_from_high_52w": -3, "darvas": "BUY", "base_type": "cup", "sector": "Tech", "pbox": "NONE"},
    {"ticker": "BBB", "company": "Beta", "rs_rating": 50, "eps_rating": 99, "composite_rating": 70, "pct_to_pivot": 12,
     "pct_from_high_52w": -25, "darvas": "WAIT", "base_type": "correction", "sector": "Health", "pbox": "ZONE"},
    {"ticker": "CCC", "company": "Gamma", "rs_rating": None, "darvas": "SELL", "pbox": "NONE"},
]


def tick(rows):
    return [r["ticker"] for r in rows]


def test_scan_numeric_filters_drop_unknown():
    assert tick(store.scan(ROWS, {"rs_min": 80})) == ["AAA"]   # brak RS (None) nie przechodzi filtra
    assert tick(store.scan(ROWS, {"eps_min": 90})) == ["BBB"]
    assert tick(store.scan(ROWS, {"max_to_pivot": 5})) == ["AAA"]
    assert tick(store.scan(ROWS, {"max_from_high": 10})) == ["AAA"]


def test_scan_state_sector_base_pinned_text():
    assert tick(store.scan(ROWS, {"states": ["BUY", "SELL"]})) == ["AAA", "CCC"]
    assert tick(store.scan(ROWS, {"sector": "Health"})) == ["BBB"]
    assert tick(store.scan(ROWS, {"base_only": True})) == ["AAA"]
    assert tick(store.scan(ROWS, {"pinned_only": True})) == ["BBB"]
    assert tick(store.scan(ROWS, {"text": "gam"})) == ["CCC"]
    assert tick(store.scan(ROWS, {})) == ["AAA", "BBB", "CCC"]


def test_presets_are_valid_filters():
    for f in store.PRESETS.values():
        assert set(f) <= set(store.DEFAULT_FILTERS)


def test_store_seed_pin_roundtrip(tmp_path):
    s = store.Store(tmp_path / "d")
    assert s.rows and (tmp_path / "d" / "watchlist.json").exists()
    t = s.rows[0]["ticker"]
    s.pin(t, {"top": 1000, "bottom": 900, "start": "2026-01-02"})
    assert store.Store(tmp_path / "d").pinned[t]["top"] == 1000
    assert s.row(t)["pbox"] == "ABOVE" or s.row(t)["pbox"] in ("INSIDE", "ZONE", "EXIT")
    s.pin(t, None)
    assert t not in s.pinned and s.row(t)["pbox"] == "NONE"


def test_nice_ticks_and_window():
    assert charts.nice_ticks(0, 100, 5) == [0, 20, 40, 60, 80, 100]
    assert charts.window(300, 100) == (200, 300)
    assert charts.window(300, 100, 150) == (50, 150)
    assert charts.window(50, 500) == (0, 50)
    i0, i1 = charts.box_focus_window(300, {"i0": 100, "i1": 110})
    assert i0 == 86 and i1 >= 112


def test_macd_lengths_and_flat_series():
    c = [float(i) for i in range(1, 80)]
    line, sig, hist = charts.macd(c)
    assert len(line) == len(sig) == len(hist) == 79
    assert line[24] is None and line[25] is not None and hist[33] is not None
    assert all(abs(v) < 1e-9 for v in charts.macd([5.0] * 60)[0] if v is not None)


def test_hit_boxes_smallest_first():
    geom = {"hits": [{"rect": (0, 0, 100, 100)}, {"rect": (10, 10, 20, 20)}]}
    assert charts.hit_boxes(geom, 15, 15) == [1, 0]
    assert charts.hit_boxes(geom, 50, 50) == [0]
    assert charts.hit_boxes(geom, 500, 500) == []


def test_slider_geometry_and_drag():
    x0, x1 = charts.slider_rect(300, 100, None, 608)   # tor 600 px na 300 tygodni = 2 px / tydzień
    assert (x0, x1) == (4 + 400, 604)
    assert charts.slider_mode(x0 + 1, x0, x1) == "left" and charts.slider_mode(x1 - 2, x0, x1) == "right"
    assert charts.slider_mode((x0 + x1) / 2, x0, x1) == "move" and charts.slider_mode(50, x0, x1) == "jump"
    assert charts.slider_drag("move", (100, 300), -100, 300, 608) == (100, 250)   # -100 px = -50 tyg.
    assert charts.slider_drag("move", (100, 300), 5000, 300, 608) == (100, 300)    # nie wychodzi poza dane
    assert charts.slider_drag("move", (100, 300), -5000, 300, 608) == (100, 100)
    assert charts.slider_drag("left", (100, 300), -100, 300, 608) == (150, 300)    # dłuższe okno
    assert charts.slider_drag("left", (100, 300), 5000, 300, 608) == (charts.MIN_WEEKS, 300)
    assert charts.slider_drag("right", (100, 200), 100, 300, 608) == (150, 250)
    assert charts.slider_jump(304, 300, 100, 608) == (100, 200)


def test_log_scale_and_ticks():
    y = charts.make_scale(100, 400, 0, 100, True)
    assert round(y(100)) == 100 and round(y(400)) == 0 and round(y(200)) == 50          # podwojenie ceny = ten sam odstęp
    yl = charts.make_scale(100, 400, 0, 100, False)
    assert round(yl(200)) == 67                                                          # na skali liniowej nie
    assert round(charts.make_scale(0, 10, 0, 100, True)(5)) == 50                       # lo = 0 -> awaryjnie liniowo
    t = charts.price_ticks(10, 1000, 8, True)
    assert t[0] >= 10 and t[-1] <= 1000 and len(t) <= 8 and 100 in t and all(a < b for a, b in zip(t, t[1:]))
    assert charts.price_ticks(200, 240, 6, True) == charts.nice_ticks(200, 240, 6)       # wąski zakres: okrągłe liczby liniowe
    assert charts.price_ticks(10, 1000, 8, False) == charts.nice_ticks(10, 1000, 8)


def _series():
    import json
    from pathlib import Path
    d = json.loads((Path(__file__).resolve().parent.parent / "seed_data" / "charts_daily.json").read_text(encoding="utf-8"))
    full = d["stocks"]["NVDA"]
    from desktop import daily
    smas = [(daily.sma(full["c"], n), n) for n in (10, 50, 200)]
    return full, d["dates"], smas


def test_tooltip_bars_contents_and_sma_hover():
    full, dates, smas = _series()
    i = len(dates) - 1
    lines = [t for t, _ in charts.tooltip_bars(full, dates, i, smas, "D")]
    assert lines[0].startswith(dates[i]) and any(t.startswith("SMA 50:") and "cena" in t for t in lines) and any("do szczytu 52t" in t for t in lines)
    assert any(t.startswith("wolumen") and "średniej 50" in t for t in lines) and any(t.startswith("MACD") for t in lines)
    hov = charts.tooltip_bars(full, dates, i, smas, "D", hover=50)
    assert hov[0][0].startswith("SMA 50 (dzienna) =") and "średnia" in hov[2][0] and hov[0][1] == charts.SMA_COLORS[50]
    assert charts.tooltip_bars(full, dates, -1, smas, "D") == [] and charts.tooltip_bars(full, dates, 10 ** 6, smas, "D") == []


def test_tooltip_card_distance_to_box_levels():
    c = [10, 10.5, 11, 12, 11.5, 11.2, 11.4, 11.1, 11.8, 11.9, 11.6, 11.7]
    full = {"c": c}
    lines = [t for t, _ in charts.tooltip_card(full, [f"d{k}" for k in range(len(c))], len(c) - 1, "W")]
    assert any(t.startswith("box ") for t in lines) and any(t.startswith("do wybicia") and "+2.6%" in t for t in lines)   # 12 / 11.7 - 1
    assert any(t.startswith("do exitu") and "-" in t for t in lines)


def test_tooltip_has_volume_average_and_breakout_highlight_rule():
    full, dates, smas = _series()
    i = len(dates) - 1
    lines = [t for t, _ in charts.tooltip_bars(full, dates, i, smas, "D")]
    assert any(t.startswith("średnia wolumenu SMA 50:") for t in lines)
    wk = {"c": [10.0 + k for k in range(30)], "h": [11.0 + k for k in range(30)], "l": [9.0 + k for k in range(30)], "v": [100] * 29 + [300]}
    lines = [t for t, _ in charts.tooltip_bars(wk, [f"w{k}" for k in range(30)], 29, [], "W")]
    assert any(t.startswith("wolumen") and "3.00× średniej 10" in t for t in lines) and any(t.startswith("średnia wolumenu SMA 10:") for t in lines)
