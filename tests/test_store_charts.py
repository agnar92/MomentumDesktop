
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
