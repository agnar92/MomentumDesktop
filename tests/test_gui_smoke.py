"""Test dymny GUI — pomijany, gdy brak tkintera lub ekranu (na CI Linux pod xvfb)."""
import gc

import pytest

from desktop import calc
from desktop import chart as A_chart
from desktop.store import Store

tk = pytest.importorskip("tkinter")


def _weekly(n=156):
    c = [50 + i * 0.5 + (3 if i % 7 == 0 else 0) for i in range(n)]
    return {"d": [f"{2023 + i // 52}-{(i % 52) // 4.4 + 1:02.0f}-01" for i in range(n)], "o": c, "h": [x * 1.03 for x in c], "l": [x * 0.97 for x in c],
            "c": c, "v": [5e6 + (i % 5) * 1e5 for i in range(n)]}


def _spy_monthly(rising=True):
    """Miesięczny SPY od 2018-01 do bieżącego miesiąca (rosnący albo spadający) — źródło tła wykresów T / M / Z."""
    import datetime as dt
    today = dt.date.today()
    n = (today.year - 2018) * 12 + today.month
    d = [f"{2018 + i // 12}-{1 + i % 12:02d}-01" for i in range(n)]
    c = [100 + (i if rising else -i * 0.3) for i in range(n)]
    return {"d": d, "o": c, "h": [x + 1 for x in c], "l": [x - 1 for x in c], "c": c, "v": [1e9] * n, "period": "M", "open_last": True}


@pytest.fixture
def app(tmp_path):
    w = _weekly()
    spy = {**w, "c": [400 - i * 1.5 for i in range(len(w["c"]))]}      # SPY spada -> siła względna AAA / BBB > 50 pp
    est = {"surp": [[w["d"][-30], 3.0], [w["d"][-5], 6.0]]}           # 2 raporty powyżej konsensusu
    rows = [calc.build_row({"ticker": t, "company": t + " Inc"}, w, [40, 120, 110, 110, 110], {"rev_rr": 30, "dopm": d}, spy, est) for t, d in (("AAA", 5), ("BBB", 1))]
    Store(tmp_path).save_scan(rows, {"AAA": w, "BBB": w}, "2026-10-20T08:00")
    try:
        from desktop import app as A
        a = A.App(tmp_path)
    except tk.TclError:
        pytest.skip("brak ekranu")
    a.store.save_cache("monthly_ohlc", {"SPY": _spy_monthly()})   # świeży miesięczny SPY w cache: tło wykresu bez pobierania z sieci
    a.store.settings["full_weekly"] = False   # testy bez pobierania pełnej historii z sieci
    a.store.settings["view"] = {"W": {"fut": 0}, "M": {"fut": 0}}   # bez pustych świec w przyszłości (osobne testy)
    yield a
    try:
        a.root.destroy()
    except tk.TclError:
        pass
    del a
    gc.collect()   # zmienne Tk zwalniamy w głównym wątku: GC w wątku roboczym (np. pobieranie wykresu) wywraca tkintera (segfault)


def test_list_chart_and_navigation(app):
    app.root.update()
    assert app.only_ok.get() is False
    assert set(app.tree.get_children()) == {"AAA", "BBB"}  # domyślnie filtr warunków jest wyłączony
    app.only_ok.set(True)
    app.refresh()
    assert app.tree.get_children() == ("AAA",)              # po włączeniu zostają tylko spełniające warunki
    app.only_ok.set(False)
    app.refresh()
    assert set(app.tree.get_children()) == {"AAA", "BBB"}
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    assert ch.geom and ch.geom["n"] == 156
    g = ch.geom["g"]   # środek wykresu (szerokość zależy od ekranu i panelu fundamentów)
    ev = type("E", (), {"x": (g["x0"] + g["x1"]) / 2, "y": (g["price"][0] + g["price"][1]) / 2})()
    ch.on_motion(ev)
    assert ch.cv.find_withtag("tip")
    E = type("E", (), {})
    a, b = E(), E()   # miarka: prawy przycisk przytrzymany od a do b
    a.x, a.y, a.x_root, a.y_root = g["x0"] + 50, g["price"][1] - 20, 0, 0
    b.x, b.y = g["x1"] - 50, g["price"][0] + 20
    ch.right_click(a)
    assert ch.ruler and ch.ruler["k"] < ch.geom["n"]
    ch.ruler_move(b)
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_withtag("ruler") if ch.cv.type(i) == "text"]
    assert texts and texts[0].startswith("+") and " tyg." in texts[0]
    ch.ruler_end(b)
    assert not ch.cv.find_withtag("ruler") and ch.ruler is None
    ch.zoom(0.5)                                         # kółko: okno 78 tygodni, prawy brzeg zostaje
    assert ch.geom["n"] == 78 and ch.geom["i0"] == 78
    ch.slider.update()
    W = ch.slider.winfo_width()
    x0, x1 = A_chart.slider_rect(156, ch.n_show, ch.end, W)
    ch.slider_press(type("E", (), {"x": (x0 + x1) / 2})())
    ch.slider_move(type("E", (), {"x": (x0 + x1) / 2 - W / 4})())   # przesuń ramkę w lewo
    assert ch.end is not None and ch.geom["i0"] < 78 and ch.geom["n"] == 78
    ch.step(1)
    assert ch.ticker == "BBB" and ch.end is None and ch.n_show == 78
    app.sort_by("dopm")
    assert app.tree.get_children()[0] == "AAA"


def test_ctrl_space_ticker_stays_open_after_chart_sync_refreshes_table(app, monkeypatch):
    import time
    from desktop import prices, sync

    # Simulate a previously selected list stock, then open another symbol using Ctrl+Space.
    app.tree.selection_set("AAA")
    app.root.update()
    app.open_chart("ZZZ")
    ch = app.chart
    ch.update()
    assert ch.ticker == "ZZZ"

    previous_row = dict(app.store.row("AAA"))
    old_weekly = app.store.weekly("AAA")
    refreshed_weekly = {k: list(v) if isinstance(v, list) else v for k, v in old_weekly.items()}
    refreshed_weekly["c"][-1] += 1
    refreshed_row = {**previous_row, "ticker": "ZZZ", "company": "ZZZ Inc", "price": 123.45}
    refreshed_row["glb_state"] = "SYGNAŁ"

    monthly_closes = [20, 22, 21, 24, 23, 25]
    monthly = {
        "d": [f"2026-{i:02d}-01" for i in range(1, 7)],
        "o": monthly_closes, "h": [v + 1 for v in monthly_closes],
        "l": [v - 1 for v in monthly_closes], "c": monthly_closes, "v": [1e6] * len(monthly_closes),
    }
    calls = []

    def fake_symbol(ticker, store, log=print):
        calls.append(ticker)
        return dict(refreshed_row), dict(refreshed_weekly)

    monkeypatch.setattr(sync, "symbol", fake_symbol)
    monkeypatch.setattr(prices, "monthly_ohlc", lambda ticker: dict(monthly))

    ch.sync_btn.invoke()
    for _ in range(100):
        app.root.update()
        if app.store.row("ZZZ") and app.store.row("ZZZ").get("price") == 123.45 and ch.sync_btn["state"] == "normal":
            break
        time.sleep(0.02)
    app.root.update()

    assert calls == ["ZZZ"]
    assert app.store.row("ZZZ")["price"] == 123.45
    assert ch.ticker == "ZZZ"
    assert "Odświeżono ZZZ" in app.status.cget("text")


def test_chart_sync_button_refreshes_only_the_open_ticker(app, monkeypatch):
    import time
    from desktop import prices, sync

    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    original = dict(app.store.row("AAA"))
    old_weekly = app.store.weekly("AAA")
    refreshed_weekly = {k: list(v) if isinstance(v, list) else v for k, v in old_weekly.items()}
    refreshed_weekly["c"][-1] = refreshed_weekly["c"][-1] + 1
    refreshed_row = {**original, "price": 123.45, "glb_state": "SYGNAŁ"}

    monthly_closes = [20, 22, 21, 24, 23, 25]
    monthly = {
        "d": [f"2026-{i:02d}-01" for i in range(1, 7)],
        "o": monthly_closes, "h": [v + 1 for v in monthly_closes],
        "l": [v - 1 for v in monthly_closes], "c": monthly_closes, "v": [1e6] * len(monthly_closes),
    }
    calls = []

    def fake_symbol(ticker, store, log=print):
        calls.append(ticker)
        return dict(refreshed_row), dict(refreshed_weekly)

    monkeypatch.setattr(sync, "symbol", fake_symbol)
    monkeypatch.setattr(prices, "monthly_ohlc", lambda ticker: dict(monthly))

    ch.sync_btn.invoke()
    for _ in range(100):
        app.root.update()
        if app.store.row("AAA").get("price") == 123.45 and ch.sync_btn["state"] == "normal":
            break
        time.sleep(0.02)

    assert calls == ["AAA"]
    assert app.store.row("AAA")["price"] == 123.45
    assert app.store.weekly("AAA")["c"][-1] == refreshed_weekly["c"][-1]
    assert ch.other["M"]["AAA"]["c"] == monthly_closes
    assert ch.sync_btn["text"] == "⟳ Sync"
    assert "Odświeżono AAA" in app.status.cget("text")


def test_progress_bar_text_and_visibility(app):
    from desktop import app as A
    assert A.progress_text(0.5, "Etap 2/4: yfinance — tygodniowe 100/200", 60) == "Etap 2/4: yfinance — tygodniowe 100/200 · 50 % · 1:00 · zostało ~1:00"
    app.q.put(("progress", (0.25, "Etap 2/4")))
    app.root.after(0, app._poll)
    app.root.update()
    assert app.pbar["value"] == 250


def test_scanner_switch_and_settings_dialog(app):
    from desktop import app as A
    names = [x["name"] for x in app.store.settings["scanners"]]
    assert names[0] == "Sektory top 3 (RS)" and len(names) == 5
    app.open_list(names[1])
    assert app.tree.get_children() == () and app.store.settings["scanner"] == names[1]
    app.open_list(names[0])
    assert set(app.tree.get_children()) == {"AAA", "BBB"}  # domyślnie pokazujemy wszystkie akcje
    app.only_ok.set(True)
    app.refresh()
    assert app.tree.get_children() == ("AAA",)             # filtr można włączyć świadomie
    d = A.SettingsDialog(app)
    d.new()
    d.name.set("Mój")
    d.filters.set("cap_largeover")
    d.save()
    assert app.store.settings["scanner"] == "Mój" and app.store.scanner["filters"] == "cap_largeover"
    assert app.view_var.get() == "📋 Mój" and app.tree.get_children() == ()


def test_strategy_conditions_dialog_recalculates_and_persists(app, tmp_path):
    from desktop import app as A
    from desktop.store import Store

    assert not next(row for row in app.store.rows if row["ticker"] == "BBB")["ok"]
    d = A.StrategyConditionsDialog(app)
    assert d.enabled["op_margin"].get() is True
    d.enabled["op_margin"].set(False)
    d.save()

    cfg = app.store.settings["strategy_conditions"]
    assert cfg["op_margin"]["enabled"] is False
    assert next(row for row in app.store.rows if row["ticker"] == "BBB")["ok"] is True
    app.only_ok.set(True)
    app.refresh()
    assert set(app.tree.get_children()) == {"AAA", "BBB"}

    # Ustawienia obowiązują również po ponownym uruchomieniu i przełączeniu skanera.
    reloaded = Store(tmp_path)
    assert reloaded.settings["strategy_conditions"]["op_margin"]["enabled"] is False
    assert next(row for row in reloaded.rows if row["ticker"] == "BBB")["ok"] is True


def test_trend_line_draw_move_delete_and_filters(app):
    from desktop import app as A
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    g = ch.geom["g"]
    E = lambda x, y: type("E", (), {"x": x, "y": y})()   # noqa: E731
    # Use positions relative to the actual plot area. The chart width depends
    # on display height and the now-wider fundamentals panel; fixed x=500 can
    # fall outside the plot on smaller displays and clamp both endpoints to
    # the same candle, so save_lines() correctly removes the zero-length line.
    plot_width = max(1.0, g["x1"] - g["x0"])
    x_start = g["x0"] + plot_width * 0.15
    x_drag = g["x0"] + plot_width * 0.35
    x_end = g["x0"] + plot_width * 0.75
    price_top, price_bottom = g["price"]
    price_height = max(1.0, price_bottom - price_top)
    y = (price_top + price_bottom) / 2
    y_drag = y - max(6.0, price_height * 0.07)
    y_end = y - max(15.0, price_height * 0.20)
    ch.press(E(x_start, y))
    ch.drag_line(E(x_drag, y_drag))
    ch.drag_line(E(x_end, y_end))
    ch.release(E(x_end, y_end))
    ls = app.store.alerts["lines"]["AAA"]
    assert len(ls) == 1 and ls[0]["d1"] < ls[0]["d2"] and ch.sel == ls[0]["id"]
    assert (app.store.dir / "alerts.json").exists()
    p1 = ls[0]["p1"]
    ch.redraw()
    s = ch.geom["segs"][0]
    mx, my = (s["x1"] + s["x2"]) / 2, (s["y1"] + s["y2"]) / 2
    ch.press(E(mx, my))
    ch.drag_line(E(mx, my + 30))
    ch.release(E(mx, my + 30))
    assert app.store.alerts["lines"]["AAA"][0]["p1"] < p1     # przesunięta w dół
    ch.toggle_watch()
    assert "AAA" in app.store.alerts["watch"]
    ch.delete_selected()
    assert "AAA" not in app.store.alerts["lines"]
    app.only_ok.set(False)
    d = A.FilterDialog(app)
    d.preset({"dopm": {"min": 3}})
    assert app.tree.get_children() == ("AAA",)
    d.preset({})
    assert set(app.tree.get_children()) == {"AAA", "BBB"}
    A.AlertsDialog(app).destroy()


def test_guide_position_and_ibd_panels(app):
    from desktop import app as A
    st = app.store
    w = st.weekly("AAA")
    st.series["SPY"] = {**w, "c": [x * 4 for x in w["c"]]}
    row = st.row("AAA")
    row.update(qs=[{"quarter": w["d"][100], "rev": 1e9, "rev_rr": 30}, {"quarter": w["d"][113], "rev": 1.2e9, "rev_rr": 12}], slow="HAMUJE+MB", accel=-12)
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    assert any(t.startswith("RS Line") or t.startswith("RS /") for t in texts)   # T: panel RS Line jest
    assert not any(t.startswith("Przychody kw.") or t.startswith("S&P 500") for t in texts)   # ale bez przychodów
    g = ch.geom["g"]
    assert g["rs"] and g["rs"][1] < g["price"][0] and g["rev"] is None and g["price"][1] < g["vol"][0] < g["vol"][1] < g["macd"][0] < g["macd"][1]
    bands = [i for i in ch.cv.find_all() if ch.cv.type(i) == "rectangle" and ch.cv.itemcget(i, "fill") == A_chart.REGIME_BG]
    assert bands and any(ch.cv.type(i) == "line" and ch.cv.itemcget(i, "fill") == A_chart.SMA_C for i in ch.cv.find_all())   # tło SPY > SMA 10 i niebieska SMA 10
    panel_text = ch.ptext.get("1.0", "end")
    assert "Growth Score" not in panel_text and "CAN SLIM" not in panel_text and "RS Rating" not in panel_text
    ch.toggle_pos()
    assert "AAA" in st.alerts["pos"] and "AAA" in st.alerts["watch"] and "⚠" in ch.ptext.get("1.0", "end") and "spełnia warunki" in ch.ptext.get("1.0", "end")
    assert app.tree.item("AAA")["values"][0].startswith("📌") and "poswarn" in app.tree.item("AAA")["tags"]
    lines_ = A.checklist(row, st.alerts["pos"]["AAA"])
    assert any(ln.startswith("⚠ Masz pozycję") for ln in lines_)
    A.GuideDialog(app).destroy()
    shown = ch.show_panel
    ch.toggle_panel()
    assert ch.show_panel != shown and app.store.settings["fund_panel"] == ch.show_panel and ch.fund_btn.cget("text").startswith("◀" if shown else "▶")
    assert A.cell(12.34, "x") == "12.3" and A.cell("HAMUJE", "w") == "⚠ hamuje"


def test_monthly_chart_shows_dotted_green_line(app, monkeypatch):
    import time
    from desktop import calc as C, prices
    h = [10, 12, 30, 20, 21, 22, 25, 28, 29, 31, 29, 28, 27]          # rekord 30 (3. mies.) + 2 zamknięte miesiące = linia; 31 (10. mies.) ma dopiero 2 kolejne świece
    d = [f"2025-{m:02d}-01" for m in range(1, 13)] + ["2026-01-01"]
    m = {"d": d, "o": h, "h": h, "l": [x * 0.9 for x in h], "c": h, "v": [1e6] * len(h)}
    monkeypatch.setattr(prices, "monthly_ohlc", lambda t: dict(m))
    assert C.green_line_series(h)[:5] == [None] * 5 and C.green_line_series(h)[5] == 30
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.toggle_period("M")
    for _ in range(50):
        app.root.update()
        if ch.geom and ch.geom["n"] == len(h):
            break
        time.sleep(0.02)
    assert ch.period == "M" and ch.geom["n"] == len(h)
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    assert texts.count("31.00") == 2   # Green Line 31 (rekord ze 10. miesiąca + 2 zamknięte, 4. po nim jest bieżący): cena nad świecą rekordu i na osi
    dotted = [i for i in ch.cv.find_all() if ch.cv.type(i) == "line" and ch.cv.itemcget(i, "fill") == A_chart.GLB_COLOR and ch.cv.itemcget(i, "dash")]
    assert len(dotted) == 1
    ch.toggle_period("W")
    assert ch.period == "W" and ch.geom["n"] == 156


def test_weekly_rwb_toggle_draws_gmma_rwb_strip_and_blue_dot(app):
    import datetime as dt
    from desktop import calc as C
    n = 160
    c = [50 + i * 0.4 for i in range(n)]
    c[150:154] = [c[149] - 3, c[149] - 6, c[149] - 7, c[149] - 1]       # korekta w trendzie, potem odbicie: Stochastic przecina 20 w górę
    d = [(dt.date(2023, 1, 2) + dt.timedelta(weeks=i)).isoformat() for i in range(n)]
    w = {"d": d, "o": c, "h": [x + 1 for x in c], "l": [x - 1 for x in c], "c": c, "v": [1e6] * n}
    assert C.rwb(c)[148] and not C.rwb([100 - i for i in range(80)])[-1]   # spadek: szybkie pod wolnymi
    dots = C.blue_dots(w["h"], w["l"], c, 40)
    assert dots and dots[-1] >= 150 and not C.blue_dots(w["h"], w["l"], c, 1e9)   # pod Green Line nie ma kropek
    app.store.series["AAA"] = w
    app.store.row("AAA")["glb"] = 40
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    dot_items = lambda: [i for i in ch.cv.find_all() if ch.cv.type(i) == "oval" and ch.cv.itemcget(i, "fill") == A_chart.BLUE_DOT]   # noqa: E731
    assert not ch.rwb and not dot_items() and ch.rwb_btn.cget("state") == "normal"
    gmma_lines = lambda: [i for i in ch.cv.find_all() if ch.cv.type(i) == "line" and ch.cv.itemcget(i, "fill") in (A_chart.FAST_C, A_chart.SLOW_C)]   # noqa: E731
    assert not gmma_lines()
    ch.toggle_rwb()
    assert ch.rwb and ch.rwb_btn.cget("bg") == "#1f3b5c"
    assert not gmma_lines() and dot_items()                                        # sam wskaźnik: bez wachlarza średnich Guppy, z ● Blue Dot
    strip = [i for i in ch.cv.find_all() if ch.cv.type(i) == "rectangle" and ch.cv.itemcget(i, "fill") == A_chart.SLOW_C]
    assert strip                                                                   # pasek RWB u dołu panelu ceny
    g = ch.geom["g"]
    ch.on_motion(type("E", (), {"x": g["x0"] + (dots[-1] - ch.geom["i0"] + 0.5) * ch.geom["step"], "y": (g["price"][0] + g["price"][1]) / 2})())
    tooltip = [ch.cv.itemcget(i, "text") for i in ch.cv.find_withtag("tip") if ch.cv.type(i) == "text"]
    assert any(t.startswith("BLUE DOT") for t in tooltip)
    ch.toggle_period("M")
    assert ch.rwb_btn.cget("state") == "normal" and ch.rwb                         # RWB działa też na miesięcznym


def test_revenue_surprise_is_computed_if_actual_and_estimate_are_supplied():
    from desktop.estimates import _revenue_surprise

    assert _revenue_surprise({"Reported Revenue": 110, "Revenue Estimate": 100}) == 10.0
    assert _revenue_surprise({"Reported Revenue": 90, "Revenue Estimate": 100}) == -10.0
    assert _revenue_surprise({"Reported Revenue": 90, "Revenue Estimate": 0}) is None


def test_earnings_tooltip_on_weekly_chart(app):
    weekly = app.store.weekly("AAA")
    week_event = weekly["d"][80]
    app.store.save_cache("estimates", {"AAA": {
        "at": "2026-10-20",
        "surp": [[week_event, 6.7]],
        "revenue_surp": [[week_event, 4.1]],
        "rev90": None,
        "earnings_dates": [week_event],
    }})
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    assert "E" not in texts   # prosty wykres T nie ma liter E (wyniki tylko w dymku)
    g = ch.geom["g"]
    from desktop.chart import earnings_indices
    weekly_index = earnings_indices(weekly["d"], [week_event], "W")[0]
    assert earnings_indices(weekly["d"], [week_event], "M") == []
    x = g["x0"] + (weekly_index + 0.5) * ch.geom["step"]
    ch.on_motion(type("E", (), {"x": x, "y": (g["price"][0] + g["price"][1]) / 2})())
    tooltip = [ch.cv.itemcget(i, "text") for i in ch.cv.find_withtag("tip") if ch.cv.type(i) == "text"]
    assert "Earnings Surprise: +6.7%" in tooltip
    assert "Revenue Surprise: +4.1%" in tooltip


def test_monthly_trend_lines_are_drawn_on_monthly_and_shown_read_only_on_weekly(app, monkeypatch):
    import time
    from desktop import prices

    n = 60
    close = [40 + i * 0.5 for i in range(n)]
    dates = [f"{2021 + i // 12}-{i % 12 + 1:02d}-01" for i in range(n)]
    monthly = {"d": dates, "o": close, "h": [x + 2 for x in close], "l": [x - 2 for x in close], "c": close, "v": [1e6] * n}
    monkeypatch.setattr(prices, "monthly_ohlc", lambda ticker: dict(monthly))
    weekly = app.store.weekly("AAA")
    weekly_line = {"id": "weekly-line", "d1": weekly["d"][20], "p1": 55, "d2": weekly["d"][50], "p2": 62, "alert": True}
    app.store.alerts["lines"]["AAA"] = [weekly_line]
    app.store.save_alerts()

    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.toggle_period("M")
    for _ in range(50):
        app.root.update()
        if ch.geom and ch.geom["n"] == n:
            break
        time.sleep(0.02)
    assert ch.period == "M" and ch.geom["n"] == n and ch.lines() == []            # tygodniowa linia nie jest na miesięcznym

    g = ch.geom["g"]
    E = lambda x, y, xr=300, yr=300: type("E", (), {"x": x, "y": y, "x_root": xr, "y_root": yr})()   # noqa: E731
    x0 = g["x0"] + (g["x1"] - g["x0"]) * 0.6          # lata 2024–2025: mieszczą się w 3-letniej historii tygodniowej
    x1 = g["x0"] + (g["x1"] - g["x0"]) * 0.9
    y0 = (g["price"][0] + g["price"][1]) / 2
    ch.press(E(x0, y0))
    ch.drag_line(E(x0 + 15, y0 - 10))
    ch.drag_line(E(x1, y0 - 35))
    ch.release(E(x1, y0 - 35))
    monthly_lines = [ln for ln in app.store.alerts["lines"]["AAA"] if ln.get("period") == "M"]
    assert len(monthly_lines) == 1 and monthly_lines[0]["alert"] is False       # rysowanie na miesięcznym; nowa linia bez alarmu
    mid = monthly_lines[0]["id"]

    menus = []
    monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, x, y: menus.append(self))
    monkeypatch.setattr(tk.Menu, "grab_release", lambda self: None)
    seg = ch.geom["segs"][0]
    ch.right_click(E((seg["x1"] + seg["x2"]) / 2, (seg["y1"] + seg["y2"]) / 2))
    labels = [menus[-1].entrycget(i, "label") for i in range(menus[-1].index("end") + 1) if menus[-1].type(i) != "separator"]
    assert "Dodaj alert linii" in labels and "Usuń linię" in labels

    ch.toggle_period("W")                                                          # na tygodniowym ta linia jest widoczna, ale tylko do odczytu
    assert ch.period == "W" and [ln["id"] for ln in ch.lines()] == ["weekly-line"]
    ro = [ln for ln in ch.shown_lines() if ln.get("ro")]
    assert [ln["id"] for ln in ro] == [mid] and len(ch.geom["segs"]) == 1          # w segs tylko własna linia tygodniowa
    pale = [i for i in ch.cv.find_all() if ch.cv.type(i) == "line" and ch.cv.itemcget(i, "fill") == A_chart.TLINE_RO]
    assert pale and all(ch.cv.itemcget(i, "dash") for i in pale)
    ch.save_lines()                                                                # zapis tygodniowych nie kasuje miesięcznych
    assert {ln["id"] for ln in app.store.alerts["lines"]["AAA"]} == {"weekly-line", mid}

    ch.toggle_period("M")
    seg = ch.geom["segs"][0]
    ch.right_click(E((seg["x1"] + seg["x2"]) / 2, (seg["y1"] + seg["y2"]) / 2))
    menus[-1].invoke(menus[-1].index("end"))                                       # „Usuń linię"
    assert {ln["id"] for ln in app.store.alerts["lines"]["AAA"]} == {"weekly-line"}


def test_exit_method_toggle_and_position_plan(app):
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.toggle_pos()
    ch.toggle_exit()
    assert app.store.settings["exit"] == "GLB" and ch.exit_btn.cget("text") == "🚪 Wyjście: pod GLB"
    ch.redraw()
    assert "PLAN WYJŚCIA" in ch.ptext.get("1.0", "end")
    ch.toggle_exit()
    assert app.store.settings["exit"] == "MACD"


def test_period_buttons_without_daily_with_rs_panel(app):
    st = app.store
    w = st.weekly("AAA")
    st.series["SPY"] = {**w, "c": [400 - i for i in range(len(w["c"]))]}   # SPY spada -> RS rośnie, na szczycie 52 tyg.
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    assert set(ch.per_btns) == {"M", "W"} and ch.per_btns["W"].cget("text") == "T" and ch.per_btns["W"].cget("bg") == "#1f3b5c"
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    assert any(t.startswith("RS") for t in texts)   # T: panel RS Line (akcja / SPY)
    assert hasattr(A_chart, "rs_line") and not hasattr(ch, "daily_style")        # RS Line wrócił, dziennego wykresu nie ma
    ch.toggle_period()
    assert ch.period == "M" and ch.per_btns["M"].cget("bg") == "#1f3b5c"
    ch.toggle_period()
    assert ch.period == "W" and ch.per_btns["W"].cget("bg") == "#1f3b5c"


def test_positions_and_watch_panel(app):
    from desktop import app as A
    st = app.store
    w = st.weekly("AAA")
    st.alerts["pos"]["AAA"] = {"since": w["d"][100], "price": 80.0}
    st.alerts["watch"]["AAA"] = {}
    st.alerts["watch"]["BBB"] = {}
    rows = A.pos_rows(st)
    assert rows[0][0] == "AAA" and rows[0][1][3] == "80.00" and rows[0][1][1]        # kupno 80, status (trzymaj albo komunikaty)
    assert [t for t, _ in A.watch_rows(st)] == ["BBB"]                                # pozycja nie dubluje się w obserwowanych
    d = A.PositionsDialog(app)
    d.update()
    assert d.pos.get_children() == ("AAA",) and d.watch.get_children() == ("BBB",)
    d.watch.selection_set("BBB")
    d.del_watch()
    assert "BBB" not in st.alerts["watch"] and d.watch.get_children() == ()
    d.destroy()


def test_axis_labels_do_not_overlap():
    assert A_chart.axis_spots(100, 105, None) == (116, None)            # cena tuż pod Green Line -> niżej
    assert A_chart.axis_spots(100, 95, 300) == (84, 300)                # cena tuż nad -> wyżej, stop daleko bez zmian
    last, stop = A_chart.axis_spots(100, 200, 110)
    assert last == 200 and stop == 116


def test_ctrl_space_fetches_symbol_that_has_only_candles(app, monkeypatch):
    from desktop import app as A, sync
    app.store.series["ZZZ"] = app.store.weekly("AAA")          # świece z innego skanera, ale bez policzonego wiersza
    called = []
    monkeypatch.setattr(sync, "symbol", lambda sym, store, log=None: called.append(sym))
    d = A.SymbolDialog(app)
    d.var.set("zzz")
    d.go()
    for _ in range(50):
        app.root.update()
        if called:
            break
    assert called == ["ZZZ"]


def test_fundamentals_panel_layout_is_wider_styled_and_scrollable(app):
    app.open_chart("AAA")
    ch = app.chart
    ch.update()

    assert int(ch.panel.cget("width")) >= 360
    assert ch.p_scrollbar.winfo_manager() == "pack"
    assert ch.ptext.cget("yscrollcommand")
    assert ch.ptext.cget("wrap") == "word"
    assert ch.ptext.tag_cget("sec", "foreground") == "#7cc4ff"
    assert ch.ptext.tag_cget("status_ok", "background") == "#13271f"


def test_chart_ticker_entry_uses_cached_symbol_without_network(app, monkeypatch):
    from desktop import sync

    monkeypatch.setattr(sync, "symbol", lambda *args, **kwargs: pytest.fail("cached ticker should not trigger a download"))
    monthly_close = [10, 11, 12, 13]
    monthly = {
        "d": ["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01"],
        "o": monthly_close, "h": [v + 1 for v in monthly_close],
        "l": [v - 1 for v in monthly_close], "c": monthly_close, "v": [1e6] * len(monthly_close),
    }
    app.store.save_cache("monthly_ohlc", {"BBB": monthly})

    app.open_chart("AAA")
    chart = app.chart
    chart.symbol_var.set("bbb")
    chart.submit_ticker()
    app.root.update()

    assert chart.ticker == "BBB"
    assert chart.symbol_entry.get() == "BBB"
    assert chart.head.cget("text") == "  ·  BBB Inc"
    chart.toggle_period("M")
    assert chart.other["M"]["BBB"] == monthly
    assert app.root.bind("<Control-space>")
    assert not app.root.bind("<Control-k>")


def test_chart_ticker_entry_fetches_and_saves_missing_symbol(app, monkeypatch):
    import time
    from desktop import sync

    weekly = app.store.weekly("AAA")
    row = calc.build_row({"ticker": "ZZZ", "company": "ZZZ Corp"}, weekly, [40, 120, 110, 110, 110], None, weekly, None)
    called = []

    def fake_symbol(sym, store, log=None):
        called.append(sym)
        return row, weekly

    monkeypatch.setattr(sync, "symbol", fake_symbol)
    app.open_chart("AAA")
    chart = app.chart
    chart.symbol_var.set("zzz")
    chart.submit_ticker()

    for _ in range(50):
        app.root.update()
        if app.store.weekly("ZZZ") is not None:
            break
        time.sleep(0.02)

    assert called == ["ZZZ"]
    assert chart.ticker == "ZZZ"
    assert chart.head.cget("text") == "  ·  ZZZ Corp"
    assert app.store.weekly("ZZZ") is not None
    assert app.store.row("ZZZ")["company"] == "ZZZ Corp"
    assert app.store.settings["symbols"][0] == "ZZZ"


def test_zanger_view_draws_patterns_and_hides_indicators(app):
    from desktop import calc as C
    w = app.store.weekly("AAA")
    row = app.store.row("AAA")
    row["patterns"] = [{"name": "Flat Base", "state": "BUDUJE SIĘ", "buy": w["c"][-1] * 1.02, "pct": -2.0, "start": w["d"][-10], "end": w["d"][-1], "vol_x": None, "note": "",
                        "shapes": [{"kind": "box", "d1": w["d"][-10], "d2": w["d"][-1], "lo": w["c"][-1] * 0.95, "hi": w["c"][-1] * 1.02}]}]
    row["parabola"] = {"exit": w["c"][-1] * 0.9, "shapes": [{"kind": "curve", "d1": w["d"][-20], "pts": [[w["d"][-20 + k], w["c"][-1] * (0.8 + 0.01 * k)] for k in range(20)]}], "note": "x"}
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.toggle_zanger()
    ch.update()
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    assert ch.zanger and any("kupno >" in t and "Flat Base" in t for t in texts) and any(t.startswith("PARABOLA") for t in texts)
    assert not any(t.startswith("MACD") or t.startswith("Przychody") for t in texts) and ch.geom["g"]["rs"] is None
    ch.toggle_period("M")
    assert not ch.zanger and C.PATTERN_NAMES


def test_trend_line_horizontal_snap_hint_and_undo(app):
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    g = ch.geom["g"]
    E = lambda x, y: type("E", (), {"x": x, "y": y})()   # noqa: E731
    w = g["x1"] - g["x0"]
    y = sum(g["price"]) / 2
    ch.press(E(g["x0"] + w * 0.2, y))
    ch.drag_line(E(g["x0"] + w * 0.5, y - 40))
    ch.drag_line(E(g["x0"] + w * 0.7, y + 1))           # prawie poziomo -> magnes poziomy
    hint = [ch.cv.itemcget(i, "text") for i in ch.cv.find_withtag("hint") if ch.cv.type(i) == "text"]
    assert hint and "poziomo" in hint[0]
    ch.release(E(g["x0"] + w * 0.7, y + 1))
    ln = app.store.alerts["lines"]["AAA"][0]
    assert ln["p1"] == ln["p2"] and not ch.cv.find_withtag("hint")
    assert str(ch.undo_btn.cget("state")) == "normal"
    ch.undo_line()                                      # ↶ usuwa nową linię
    assert "AAA" not in app.store.alerts["lines"] and str(ch.undo_btn.cget("state")) == "disabled"


def test_zanger_bars_are_single_colour(app):
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.toggle_zanger()
    ch.update()
    from desktop.chart import DOWN, UP
    from desktop.theme import FG
    cols = {ch.cv.itemcget(i, "fill") for i in ch.cv.find_all() if ch.cv.type(i) == "line" and float(ch.cv.itemcget(i, "width")) <= 4}
    assert FG in cols and UP not in cols and DOWN not in cols   # żadnych słupków w kolorze wzrost / spadek


def test_new_trend_line_has_no_alert_and_no_extension_until_alert_is_enabled(app):
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    g = ch.geom["g"]
    E = lambda x, y: type("E", (), {"x": x, "y": y})()   # noqa: E731
    w, y = g["x1"] - g["x0"], sum(g["price"]) / 2
    ch.press(E(g["x0"] + w * 0.2, y))
    ch.drag_line(E(g["x0"] + w * 0.4, y - 30))
    ch.drag_line(E(g["x0"] + w * 0.5, y - 40))
    ch.release(E(g["x0"] + w * 0.5, y - 40))
    ln = app.store.alerts["lines"]["AAA"][0]
    assert ln["alert"] is False
    s = ch.geom["segs"][0]
    assert s["xe"] == s["x2"] and s["ye"] == s["y2"]          # bez przedłużenia
    ch.toggle_line_alert()
    ch.redraw()
    s = ch.geom["segs"][0]
    assert app.store.alerts["lines"]["AAA"][0]["alert"] is True and s["xe"] > s["x2"]   # z alarmem: przedłużenie do ostatniego tygodnia


def test_spy_regime_background_weekly_and_monthly():
    rising = {"d": [f"2025-{m:02d}-01" for m in range(1, 13)], "c": [10 + m for m in range(12)]}
    falling = {"d": rising["d"], "c": [30 - m for m in range(12)]}
    dates = rising["d"]
    r = A_chart.spy_regime(dates, rising, "M")
    assert r[:9] == [None] * 9 and r[9:] == [True, True, True]          # SMA 10 liczy się od 10. świecy
    assert A_chart.spy_regime(dates, falling, "M")[9:] == [False, False, False]
    assert A_chart.spy_regime(dates, None, "M") == [None] * 12
    import datetime as dt
    weekly = {"d": [(dt.date(2026, 1, 5) + dt.timedelta(days=7 * i)).isoformat() for i in range(14)], "c": list(range(1, 15))}
    wk = A_chart.spy_regime(weekly["d"], weekly, "W")
    assert wk[9:] == [True] * 5 and wk[0] is None
    assert A_chart.spy_regime(["2025-05-14"], {"d": ["2025-01-06", "2025-03-03"], "c": [1, 2]}, "W") == [None]   # świeca SPY sprzed miesięcy to nie ta sama świeca


def test_position_size_pln_to_usd():
    from desktop import lines
    r = lines.position_size(40000, 4.0, 100.0, 95.0, 1.0)           # 10 000 USD kapitału, ryzyko 100 USD, 5 USD na akcję
    assert r["capital_usd"] == 10000 and r["risk_usd"] == 100 and r["shares"] == 20 and r["limited_by"] == "ryzyko"
    assert r["value_usd"] == 2000 and r["value_pln"] == 8000 and r["loss_usd"] == 100 and r["loss_pln"] == 400 and abs(r["loss_pct"] - 1) < 1e-9
    assert r["full_shares"] == 100 and r["full_loss_usd"] == 500 and abs(r["full_loss_pct"] - 5) < 1e-9
    tight = lines.position_size(4000, 4.0, 100.0, 99.0, 5.0)         # 1000 USD: ryzyko 50 USD / 1 USD = 50 akcji, ale kapitał starcza na 10
    assert tight["shares"] == 10 and tight["limited_by"] == "kapitał" and tight["value_usd"] == 1000
    frac = lines.position_size(4000, 4.0, 300.0, 285.0, 1.0)          # 1000 USD, ryzyko 10 USD / 15 USD = 0,6666 akcji (ułamkowe, w dół)
    assert frac["shares"] == 0.6666 and frac["limited_by"] == "ryzyko" and frac["loss_usd"] <= 10 and A_chart.shares_text(frac["shares"]) == "0,6666"
    assert A_chart.shares_text(20.0) == "20" and A_chart.shares_text(12.5) == "12,5"
    assert lines.position_size(1000, 4.0, 100.0, 100.0, 1.0) is None and lines.position_size(1000, 4.0, 100.0, 120.0, 1.0) is None
    assert lines.position_size(1000, 0, 100.0, 90.0, 1.0) is None and lines.position_size("x", 4.0, 100.0, 90.0, 1.0) is None
    assert A_chart.num("12 345,5") == 12345.5 and A_chart.num("abc") is None and A_chart.money(1234567.891, 2) == "1 234 567,89"


def test_usdpln_from_yfinance(monkeypatch):
    import pandas as pd
    from desktop import prices
    idx = pd.to_datetime(["2026-10-26", "2026-10-27", "2026-10-28"])
    df = pd.DataFrame({"Open": [3.6, 3.7, 3.7], "High": [3.7, 3.7, 3.8], "Low": [3.6, 3.6, 3.7], "Close": [3.65, 3.7, 3.72], "Volume": [0, 0, 0]}, index=idx)
    yf = type("YF", (), {"download": staticmethod(lambda *a, **k: df)})
    monkeypatch.setattr(prices, "_yf", lambda: yf)
    assert prices.usdpln() == 3.72
    monkeypatch.setattr(prices, "_yf", lambda: type("YF", (), {"download": staticmethod(lambda *a, **k: pd.DataFrame())}))
    assert prices.usdpln() is None


def test_position_size_dialog_uses_position_stop_and_saves_capital(app, monkeypatch):
    from desktop import prices
    monkeypatch.setattr(prices, "usdpln", lambda: 4.0)
    app.store.save_cache("fx", {"usdpln": 4.0, "date": __import__("datetime").date.today().isoformat()})
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.open_size()
    dlg = ch.size_dialog
    app.root.update()
    row = app.store.row("AAA")
    entry0, stop0, src = ch.size_defaults()
    assert "Bez pozycji" in src and stop0 < entry0                              # bez pozycji: cena i Green Line / −10 %
    dlg.vars["capital"].set("40000")
    dlg.vars["risk"].set("1")
    dlg.vars["entry"].set("100")
    dlg.vars["stop"].set("95")
    assert "POZYCJA AAA: 20 akcji" in dlg.out.cget("text") and "8 000 PLN" in dlg.out.cget("text")   # 40 000 PLN / 4,0 = 10 000 USD
    assert app.store.settings["capital_pln"] == 40000 and app.store.settings["risk_pct"] == 1
    dlg.vars["stop"].set("100")
    assert "ryzyka nie da się policzyć" in dlg.out.cget("text")
    ch.set_manual_stop(None)                                                     # stop wpisany w oknie to ręczny stop z wykresu — usuwamy go
    ch.toggle_pos()                                                              # pozycja: wejście z pozycji, stop = max(−10 %, MACD)
    entry1, stop1, src1 = ch.size_defaults()
    assert "pozycja" in src1 and entry1 == app.store.alerts["pos"]["AAA"]["price"] and stop1 >= entry1 * 0.9 - 1e-9
    assert dlg.vars["entry"].get() == f"{entry1:.2f}" and row is not None
    dlg.destroy()


def test_glb_zone_grey_band_and_dashed_5_percent_line(app):
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    fills = {A_chart.mix(A_chart.BG, A_chart.ZONE_C, A_chart.ZONE_ALPHA), A_chart.mix(A_chart.REGIME_BG, A_chart.ZONE_C, A_chart.ZONE_ALPHA)}
    band = [i for i in ch.cv.find_all() if ch.cv.type(i) == "rectangle" and ch.cv.itemcget(i, "fill") in fills]
    assert all(not ch.cv.itemcget(i, "stipple") for i in band)                   # jednolity pas, bez kropkowania (migotanie)
    dashed = [i for i in ch.cv.find_all() if ch.cv.type(i) == "line" and ch.cv.itemcget(i, "fill") == A_chart.ZONE_C and ch.cv.itemcget(i, "dash")]
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    assert app.store.row("AAA").get("glb") and band and len(dashed) == 1 and "+5 %" in texts
    top = min(ch.cv.coords(i)[1] for i in band)
    bottom = max(ch.cv.coords(i)[3] for i in band)
    assert top < ch.cv.coords(dashed[0])[1] < bottom                              # przerywana 5 % leży w pasie 0–10 %
    assert A_chart.mix("#000000", "#ffffff", 0.5) == "#808080" and A_chart.mix("#102030", "#ffffff", 0) == "#102030"



def test_manual_stop_drag_double_click_persistence_and_dialog_sync(app, monkeypatch):
    import datetime as dt
    from desktop import prices
    from desktop.store import Store
    monkeypatch.setattr(prices, "usdpln", lambda: 4.0)
    app.store.save_cache("fx", {"usdpln": 4.0, "date": dt.date.today().isoformat()})
    E = lambda x, y: type("E", (), {"x": x, "y": y, "x_root": 0, "y_root": 0})()   # noqa: E731
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    assert ch.manual_stop() is None and ch.geom["stop_y"] is None
    ch.toggle_stop()                                                             # domyślny stop (Green Line albo −10 %) do przeciągnięcia
    s0 = ch.manual_stop()
    assert s0 and ch.stop_btn.cget("text") == "🛑 Stop ✕" and ch.geom["stop_y"] is not None
    red = [i for i in ch.cv.find_all() if ch.cv.type(i) == "line" and ch.cv.itemcget(i, "fill") == A_chart.STOP_COLOR and ch.cv.itemcget(i, "dash")]
    assert red and any(t.startswith("STOP ") for t in (ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"))
    g = ch.geom["g"]
    x = (g["x0"] + g["x1"]) / 2
    ch.on_motion(E(x, ch.geom["stop_y"]))
    assert ch.cv.cget("cursor") == "sb_v_double_arrow"                           # kursor „przeciągnij" nad linią stopu
    ch.open_size()
    dlg = ch.size_dialog
    ch.press(E(x, ch.geom["stop_y"]))
    assert ch.gest and ch.gest["mode"] == "stop"
    ch.drag_line(E(x, ch.geom["stop_y"] - 40))                                   # w górę = wyższy stop
    ch.release(E(x, ch.geom["stop_y"]))
    s1 = ch.manual_stop()
    assert s1 > s0 and Store(app.store.dir).settings["stops"]["AAA"] == s1       # zapisany w settings.json
    assert dlg.vars["stop"].get() == f"{s1:.2f}"                                 # okno wielkości pozycji widzi nowy stop
    ch.stop_here(E(x, g["price"][0] + (g["price"][1] - g["price"][0]) * 0.8))    # dwuklik = stop w tym miejscu
    s2 = ch.manual_stop()
    assert s2 < s1 and dlg.vars["stop"].get() == f"{s2:.2f}"
    dlg.vars["stop"].set("55")                                                   # wpisany w oknie = stop na wykresie
    assert ch.manual_stop() == 55
    dlg.vars["capital"].set("40000")
    dlg.vars["risk"].set("1")
    entry = float(dlg.vars["entry"].get())
    label = ch.stop_label()
    assert label.startswith("STOP 55.00") and "akcji" in label and f"{(55 / entry - 1) * 100:+.1f} %" in label
    ch.right_click(E(x, g["price"][0] + 5))                                      # prawy przycisk poza linią stopu = miarka, stop zostaje
    assert ch.manual_stop() == 55
    ch.toggle_stop()                                                             # ✕ usuwa
    assert ch.manual_stop() is None and ch.stop_btn.cget("text") == "🛑 Stop" and "AAA" not in app.store.settings["stops"]
    dlg.destroy()


def test_manual_stop_is_drawn_on_monthly_and_zanger_views(app, monkeypatch):
    import time
    from desktop import prices
    h = [10, 12, 30, 20, 21, 22, 25, 28, 29, 31, 29, 28, 27]
    d = [f"2025-{m:02d}-01" for m in range(1, 13)] + ["2026-01-01"]
    monkeypatch.setattr(prices, "monthly_ohlc", lambda t: {"d": d, "o": h, "h": h, "l": [x * 0.9 for x in h], "c": h, "v": [1e6] * len(h)})
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.set_manual_stop(25.0)
    ch.toggle_period("M")
    for _ in range(50):
        app.root.update()
        if ch.geom and ch.geom["n"] == len(h):
            break
        time.sleep(0.02)
    assert ch.period == "M" and ch.geom["stop_y"] is not None                    # ten sam stop na wykresie miesięcznym
    ch.toggle_period("W")
    ch.toggle_zanger()
    ch.update()
    assert ch.zanger and ch.manual_stop() == 25.0
    ch.set_manual_stop(1.0)                                                      # poza widocznym zakresem: tylko strzałka przy dolnej krawędzi
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    assert ch.geom["stop_y"] is None and any(t.startswith("▼ STOP") for t in texts)
    ch.set_manual_stop(90.0)
    assert ch.geom["stop_y"] is not None                                         # w widoku Zangera stop jest nadal rysowany (obok stopu MACD)


def test_future_slots_price_view_and_persistence(app):
    app.store.settings["view"] = {"W": {"fut": 12, "n": 10 ** 6}}   # okno: cała historia
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    real = len(app.store.weekly("AAA")["c"])
    assert ch.geom["n"] == real + 12 and ch.geom["real"] == real       # 12 pustych świec po prawej
    vd = ch.vdata()
    assert vd["d"][real] > vd["d"][real - 1] and vd["c"][real] is None
    g = ch.geom["g"]
    x = g["x0"] + (real + 5.5) * ch.geom["step"]                       # linia rysowana w przyszłość
    d, p, k = ch.value(x, (g["price"][0] + g["price"][1]) / 2)
    assert k == real + 5 and d == vd["d"][real + 5]
    ln = {"id": "f", "period": "W", "d1": vd["d"][real - 20], "p1": 100.0, "d2": d, "p2": 120.0, "alert": False}
    app.store.alerts["lines"]["AAA"] = [ln]
    ch.redraw()
    assert any(s_["id"] == "f" and s_["x2"] > g["x0"] + real * ch.geom["step"] for s_ in ch.geom["segs"])
    # skala ceny: powiększenie i przesunięcie zmieniają zakres, reset przywraca automatyczny
    l0 = (ch.geom["lmin"], ch.geom["lmax"])
    ch.save_view(z=2.0)
    ch.redraw()
    assert abs((ch.geom["lmax"] - ch.geom["lmin"]) * 2 - (l0[1] - l0[0])) < 1e-9
    ch.save_view(s=0.5)
    ch.redraw()
    assert ch.geom["lmin"] > l0[0]
    ch.reset_price()
    ch.redraw()
    assert (ch.geom["lmin"], ch.geom["lmax"]) == l0
    # zapamiętanie: długość okna i przyszłość trafiają do ustawień
    ch._set(60, 10 ** 6)
    assert app.store.settings["view"]["W"]["n"] == 60
    ch.cycle_future()
    assert app.store.settings["view"]["W"]["fut"] == 20 and ch.fut_btn.cget("text") == "⇥ 20"


def test_weekly_lines_shown_on_monthly_and_zanger_has_spy_background(app):
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    w = app.store.weekly("AAA")
    app.store.alerts["lines"]["AAA"] = [{"id": "w1", "period": "W", "d1": w["d"][-60], "p1": 90.0, "d2": w["d"][-10], "p2": 110.0, "alert": False}]
    assert ch.shown_lines() and not ch.shown_lines()[0].get("ro")
    ch.period = "M"
    assert [x["id"] for x in ch.shown_lines()] == ["w1"] and ch.shown_lines()[0]["ro"]   # linia T / Z widoczna na M, bez edycji
    assert ch.lines() == []
    ch.period = "W"
    app.store.series["SPY"] = {**w, "c": [100 + i for i in range(len(w["c"]))]}   # SPY rośnie -> nad SMA 10
    spy = app.store.weekly("SPY")
    ch.toggle_zanger()
    ch.update()
    bg = [i for i in ch.cv.find_all() if ch.cv.type(i) == "rectangle" and ch.cv.itemcget(i, "fill") == A_chart.REGIME_BG]
    regime = A_chart.spy_regime(w["d"], spy, "W")
    assert bool(bg) == any(regime)                                          # tło SPY > SMA 10 także w widoku Z


def test_sma_line_hidden_outside_price_scale(app):
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.save_view(z=6.0, s=-3.0)   # skala daleko pod ceną: SMA poza widokiem
    ch.redraw()
    sma = [i for i in ch.cv.find_all() if ch.cv.type(i) == "line" and ch.cv.itemcget(i, "fill") == A_chart.SMA_C and float(ch.cv.itemcget(i, "width")) == 2.4]
    assert not sma                                            # nie ma linii przyklejonej do krawędzi panelu
    assert A_chart.clip_seg(0, -10, 10, 10, (0, 0, 10, 10)) == (5.0, 0.0, 10.0, 10.0) and A_chart.clip_seg(0, -5, 10, -1, (0, 0, 10, 10)) is None
    ch.reset_price()
    ch.redraw()
    assert [i for i in ch.cv.find_all() if ch.cv.type(i) == "line" and ch.cv.itemcget(i, "fill") == A_chart.SMA_C and float(ch.cv.itemcget(i, "width")) == 2.4]


def test_filter_dialog_has_from_to_for_eps_rating_and_other_number_columns(app):
    from desktop import app as A
    d = A.FilterDialog(app)
    d.update()
    for k in ("eps_rating", "rwb_weeks", "rvol_w", "ps", "cc52w", "mom121"):
        assert (k, "min") in d.vars and (k, "max") in d.vars       # pola „od – do” także dla EPS Rating i innych liczb
    d.vars[("eps_rating", "min")].set("80")
    d.vars[("eps_rating", "max")].set("99")
    assert app.store.settings["list_filters"]["eps_rating"] == {"min": 80.0, "max": 99.0}
    d.preset({})


def test_full_weekly_history_is_loaded_on_open_cached_and_joined(app, monkeypatch):
    import datetime as dt
    from desktop import prices
    app.store.settings["full_weekly"] = True
    w = app.store.weekly("AAA")
    d0 = dt.date.fromisoformat(w["d"][0])
    older = 200
    full = {"raw": 1, "d": [(d0 - dt.timedelta(weeks=older - i)).isoformat() for i in range(older)] + list(w["d"][:5]),
            **{k: [50.0 + i * 0.1 for i in range(older)] + list(w[k][:5]) for k in ("o", "h", "l", "c", "v")}}
    calls = []
    monkeypatch.setattr(prices, "weekly_full", lambda ts: calls.append(list(ts)) or {t: full for t in ts})
    app.open_chart("AAA")
    ch = app.chart
    for _ in range(40):
        ch.update()
        ch.after(50)
        if ch.other["W"].get("AAA"):
            break
    ch.update()
    assert calls and "AAA" in calls[0]
    joined = ch.data()
    assert len(joined["c"]) == older + len(w["c"]) and joined["d"] == sorted(joined["d"])   # dłuższa historia, bez dubli
    assert "AAA" in app.store.cache("weekly_full")                                          # zapisane w cache
    assert prices.join_weekly(full, {**w, "c": [x * 2 for x in w["c"]]}) is None            # split po zapisaniu -> bez sklejania
    assert ch.n_show == 156                                                                 # domyślne okno nadal 3 lata


def test_gist_dialog_saves_settings_and_sends_in_background(app, monkeypatch):
    from desktop import app as A, gist
    sent = {}

    def fake_upload(files, token, gist_id, log=print):
        sent.update(files=files, token=token, gist_id=gist_id)
        return {"id": "g123", "url": "https://gist.github.com/g123"}
    monkeypatch.setattr(gist, "upload", fake_upload)
    d = A.GistDialog(app)
    d.update()
    assert "spółek" in d.info.cget("text")                       # podsumowanie tego, co zostanie wysłane
    d.token.set("tok")
    d.auto.set(True)
    d.send()
    for _ in range(40):
        app.root.update()
        if not str(d.send_btn.cget("state")) == "disabled":
            break
        __import__("time").sleep(0.05)
    cfg = app.store.settings["gist"]
    assert cfg["token"] == "tok" and cfg["auto"] is True and cfg["id"] == "g123"      # ID zapamiętane po utworzeniu gista
    assert sent["token"] == "tok" and gist.MANIFEST in sent["files"]
    assert "g123" in d.info.cget("text")


def test_rwb_dokup_arrow_marks_price_entering_the_gap(app):
    import datetime as dt
    n = 170
    c = [100 + i for i in range(n)]
    d = [(dt.date(2023, 1, 2) + dt.timedelta(weeks=i)).isoformat() for i in range(n)]
    lo_, hi_ = calc.rwb_gap(c)[150]
    low = [x - 1 for x in c]
    low[150] = (lo_ + hi_) / 2
    app.store.series["AAA"] = {"d": d, "o": c, "h": [x + 1 for x in c], "l": low, "c": c, "v": [1e6] * n}
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.toggle_rwb()
    ch.update()
    arrows = [i for i in ch.cv.find_all() if ch.cv.type(i) == "polygon" and ch.cv.itemcget(i, "fill") == A_chart.RWB_START_C]
    assert len(arrows) == 1                                            # jedna strzałka: świeca 150 (Low w przerwie), nie start RWB
    g = ch.geom["g"]
    ch.on_motion(type("E", (), {"x": g["x0"] + (150 - ch.geom["i0"] + 0.5) * ch.geom["step"], "y": (g["price"][0] + g["price"][1]) / 2})())
    tip = [ch.cv.itemcget(i, "text") for i in ch.cv.find_withtag("tip") if ch.cv.type(i) == "text"]
    assert any(t.startswith("DOKUP") for t in tip)


def test_position_entry_line_follows_the_entry_price_also_after_editing(app):
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    texts = lambda: [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]   # noqa: E731
    entry_lines = lambda: [i for i in ch.cv.find_all() if ch.cv.type(i) == "line" and ch.cv.itemcget(i, "fill") == A_chart.ENTRY_COLOR]   # noqa: E731
    assert not entry_lines() and not any(t.startswith("WEJŚCIE") for t in texts())          # bez pozycji nie ma linii
    last = app.store.weekly("AAA")["c"][-1]
    ch.toggle_pos()                                                                         # 📌 Pozycja: wejście = ostatnia cena
    assert entry_lines() and any(t.startswith(f"WEJŚCIE {A_chart.fmt(app.store.row('AAA')['price'])}") for t in texts())
    pos = app.store.alerts["pos"]["AAA"]
    pos["price"] = last * 0.9                                                               # edycja ceny w oknie Pozycje
    app.redraw_chart()
    t = [x for x in texts() if x.startswith("WEJŚCIE")]
    assert t and A_chart.fmt(last * 0.9) in t[0] and "+11.1 %" in t[0]                      # linia i napis przesunięte na nową cenę, wynik od wejścia
    w = app.store.weekly("AAA")
    months = {"d": [f"{2015 + i // 12}-{1 + i % 12:02d}-01" for i in range(60)], "period": "M", "open_last": False,
              **{k: [w[k][i] for i in range(60)] for k in ("o", "h", "l", "c", "v")}}      # miesięczne dane bez sieci
    ch.other["M"]["AAA"] = months
    ch.toggle_period("M")
    ch.update()
    assert any("WEJŚCIE" in x for x in texts())                                             # ta sama linia na M (poza skalą: ze strzałką)
    ch.toggle_period("W")
    ch.toggle_zanger()
    assert any("WEJŚCIE" in x for x in texts())                                             # i w widoku Z
    pos["price"] = last * 100                                                               # daleko poza skalą: strzałka przy krawędzi, bez linii
    ch.redraw()
    assert any(x.startswith("▲ WEJŚCIE") for x in texts()) and not entry_lines()
    ch.toggle_pos()                                                                         # zamknięcie pozycji = linia znika
    assert not any("WEJŚCIE" in x for x in texts())


def _wait(app, cond, n=150):
    import time
    for _ in range(n):
        app.root.update()
        if cond():
            return True
        time.sleep(0.02)
    app.root.update()
    return cond()


def test_view_switch_between_list_and_watchlist_with_added_tickers(app, monkeypatch):
    from desktop import sync
    name = app.store.watchlists()[0]["name"]
    assert app.view_var.get().startswith("📋") and set(app.tree.get_children()) == {"AAA", "BBB"}
    zrow = {**app.store.row("AAA"), "ticker": "ZZZ", "company": "ZZZ Inc"}
    monkeypatch.setattr(sync, "symbol", lambda sym, store, log=print: (dict(zrow), dict(app.store.weekly("AAA"))))
    assert app.add_tickers_to(name, "zzz, aaa") == ["ZZZ", "AAA"]                           # AAA jest już w skanerze, ZZZ trzeba pobrać
    assert _wait(app, lambda: app.store.row("ZZZ") is not None and "ZZZ" not in app._symbol_openings)
    assert set(app.tree.get_children()) == {"AAA", "BBB"}                                   # widok „Lista” bez zmian
    app.open_watchlist(name)
    assert app.store.settings["main_view"]["mode"] == "watch" and set(app.tree.get_children()) == {"AAA", "ZZZ"}   # watchlista = tylko dodane
    assert app.tree.item("ZZZ", "values")[0] == "★ ZZZ" and app.view_var.get() == f"★ {name}"
    assert "Watchlista" in app.status.cget("text") and "2 dodanych" in app.status.cget("text")
    app.open_list(app.store.settings["scanner"])
    assert app.store.settings["main_view"]["mode"] == "list" and set(app.tree.get_children()) == {"AAA", "BBB"}
    assert "Lista (skaner)" in app.status.cget("text") and "Watchlista" not in app.status.cget("text")
    app.store.add_watchlist("Pusta")
    app.open_watchlist("Pusta")                                                             # pusta watchlista nie pokazuje skanera i mówi, co zrobić
    assert not app.tree.get_children() and "pusta" in app.status.cget("text") and "Skaner" not in app.status.cget("text")


def test_main_window_has_no_list_management_controls(app):
    assert not hasattr(app, "scanner_box") and not hasattr(app, "add_selected_to_watchlist") and not hasattr(app, "watch_menu")
    assert app.view_var.get().startswith("📋")                                              # tylko podpis aktualnego widoku


def test_view_dialog_double_click_opens_list_or_watchlist(app, monkeypatch):
    from desktop import app as A
    from tkinter import messagebox, simpledialog
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
    st = app.store
    dlg = A.ViewDialog(app)
    dlg.update()
    assert dlg.lists.size() == len(st.settings["scanners"]) and dlg.watch.size() == 1 and dlg.ask.get() is True
    answers = iter(["Energia"])                                                             # dodaj watchlistę
    monkeypatch.setattr(simpledialog, "askstring", lambda *a, **k: next(answers))
    dlg.add_watchlist()
    assert st.watchlist("Energia") is not None and dlg.watch.size() == 2 and dlg.picked(dlg.watch) == "Energia"
    answers = iter(["Moja lista", "sh_price_o20"])                                          # dodaj listę/skaner: nazwa + filtr
    dlg.add_list()
    assert st.settings["scanners"][-1]["name"] == "Moja lista" and st.settings["scanners"][-1]["filters"] == "sh_price_o20"
    assert dlg.lists.size() == len(st.settings["scanners"])
    st.add_to_watchlist("Energia", "XOM")
    dlg.open_watch()                                                                        # dwuklik na watchliście
    assert st.settings["main_view"]["mode"] == "watch" and st.settings["main_view"]["watchlist"] == "Energia" and app.view_var.get() == "★ Energia"
    assert "XOM" in app.tree.get_children() and not dlg.winfo_exists()
    dlg = A.ViewDialog(app)
    dlg.update()
    first = st.settings["scanners"][0]["name"]
    dlg.lists.selection_clear(0, "end")
    dlg.lists.selection_set(0)
    dlg.open_list()                                                                         # dwuklik na liście
    assert st.settings["main_view"]["mode"] == "list" and st.settings["scanner"] == first and app.view_var.get() == f"📋 {first}"
    dlg = A.ViewDialog(app)
    dlg.update()
    dlg.ask.set(False)
    dlg.save_ask()
    assert st.settings["main_view"]["ask"] is False
    dlg.destroy()


def test_view_dialog_manages_watchlist_content_and_lists(app, monkeypatch):
    from desktop import app as A
    from tkinter import messagebox, simpledialog
    st = app.store
    first = st.watchlists()[0]["name"]
    names = [x["name"] for x in st.settings["scanners"]]
    monkeypatch.setattr(app, "fetch_symbol_quiet", lambda sym: None)                        # bez sieci
    dlg = A.ViewDialog(app)
    dlg.update()
    assert dlg.picked(dlg.watch) == first
    st.add_to_watchlist(first, "NVDA, AMD")
    dlg.fill_watch()
    assert dlg.tickers.size() == 2
    dlg.tickers.selection_set(0)
    dlg.remove_tickers()
    assert st.watchlist(first)["tickers"] == ["AMD"] and dlg.tickers.size() == 1
    ed = A.WatchlistEditor(app, dlg, first)                                                 # zawartość watchlisty: dwa panele jak w menedżerze plików
    ed.update()
    assert app.editor is ed and ed.left.get(0, "end") == tuple(names) and ed.right.get(0, "end") == ("AMD",)
    ed.left.selection_set(0, 1)                                                             # ▶ przenosi dowolnie wiele list na prawo
    ed.add_selected()
    assert st.watchlist(first)["sources"] == names[:2] and ed.left.get(0, "end") == tuple(names[2:])
    assert ed.right.get(0, "end") == (ed.LIST + names[0], ed.LIST + names[1], "AMD")
    ed.right.selection_set(0)                                                               # ◀ cofa listę
    ed.remove_selected()
    assert st.watchlist(first)["sources"] == [names[1]] and names[0] in ed.left.get(0, "end")
    monkeypatch.setattr(simpledialog, "askstring", lambda *a, **k: "xom, cvx")              # ＋ Ticker…
    monkeypatch.setattr(app, "fetch_symbol_quiet", lambda sym: None)
    ed.add_ticker()
    assert st.watchlist(first)["tickers"] == ["AMD", "XOM", "CVX"] and ed.right.get(0, "end")[-1] == "CVX"
    ed.right.selection_clear(0, "end")
    ed.right.selection_set(ed.right.get(0, "end").index("XOM"))
    ed.remove_selected()                                                                    # to samo pole usuwa tickery
    assert st.watchlist(first)["tickers"] == ["AMD", "CVX"]
    ed.destroy()
    assert app.editor is None and dlg.picked(dlg.watch) == first
    monkeypatch.setattr(simpledialog, "askstring", lambda *a, **k: "Ropa")
    dlg.rename()
    assert st.watchlist("Ropa") is not None and st.watchlist(first) is None and dlg.picked(dlg.watch) == "Ropa"
    infos = []
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: infos.append(a))
    dlg.delete_watchlist()                                                                  # została jedna: nie można usunąć
    assert st.watchlist("Ropa") is not None and infos and "co najmniej jedna" in infos[0][1]
    st.add_watchlist("Energia")
    dlg.fill(select_watch="Energia")
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    dlg.delete_watchlist()
    assert st.watchlist("Energia") is None
    dlg.lists.selection_clear(0, "end")
    dlg.lists.selection_set(1)
    gone = names[1]
    dlg.delete_list()                                                                       # usunięcie listy zdejmuje ją też z watchlist
    assert gone not in [x["name"] for x in st.settings["scanners"]] and gone not in st.watchlist("Ropa")["sources"]
    dlg.destroy()


def test_drag_ticker_from_table_and_between_watchlists(app, monkeypatch):
    from types import SimpleNamespace as NS
    from desktop import app as A
    st = app.store
    monkeypatch.setattr(app, "fetch_symbol_quiet", lambda sym: None)
    first = st.watchlists()[0]["name"]
    st.add_watchlist("Energia")
    app.root.update()
    dlg = A.ViewDialog(app)
    dlg.update()
    assert app.view_dialog is dlg                                                           # okno nie blokuje głównego (cel przeciągania)
    lx, ly = dlg.watch.winfo_rootx() + 20, dlg.watch.winfo_rooty()
    row_h = dlg.watch.bbox(0)[3] if dlg.watch.bbox(0) else 16
    # przeciągnięcie wiersza z tabeli (zdarzenia myszy) na drugą watchlistę w oknie
    iid = app.tree.get_children()[0]
    y_row = int(app.tree.bbox(iid)[1] + 3)
    app._drag_press(NS(y=y_row, x_root=500, y_root=400))
    assert app._drag_move(NS(x_root=502, y_root=401)) == "break"                            # mały ruch nie zaczyna przeciągania
    assert not app._drag["on"]
    assert app._drag_move(NS(x_root=lx, y_root=ly + row_h + 6)) == "break" and app._drag["on"] and dlg._label is not None
    app._drag_release(NS(x_root=lx, y_root=ly + row_h + 6))
    assert st.watchlist("Energia")["tickers"] == [iid] and st.watchlist(first)["tickers"] == [] and dlg._label is None
    assert dlg.picked(dlg.watch) == "Energia" and dlg.tickers.size() == 1
    # upuszczenie na listę tickerów = do wybranej watchlisty
    other = app.tree.get_children()[1]
    dlg.tickers.update()
    dlg.receive(other, dlg.tickers.winfo_rootx() + 10, dlg.tickers.winfo_rooty() + 10)
    assert st.watchlist("Energia")["tickers"] == [iid, other]
    # ticker z listy przeciągnięty na inną watchlistę: przenieś, z Ctrl kopiuj
    dlg.tickers.update()
    dlg._src_press(NS(y=3))
    dlg._src_release(NS(x_root=lx, y_root=ly + 3, state=0))
    assert st.watchlist(first)["tickers"] == [iid] and st.watchlist("Energia")["tickers"] == [other]
    dlg.watch.selection_clear(0, "end")
    dlg.watch.selection_set(0)
    dlg.fill_watch()
    dlg._src_press(NS(y=3))
    dlg._src_release(NS(x_root=lx, y_root=ly + row_h + 6, state=0x4))
    assert st.watchlist(first)["tickers"] == [iid] and iid in st.watchlist("Energia")["tickers"]   # Ctrl: skopiowano
    # bez otwartego okna zwykłe zaznaczanie wierszy
    dlg.destroy()
    assert app.view_dialog is None
    app._drag_press(NS(y=y_row, x_root=500, y_root=400))
    assert app._drag_move(NS(x_root=600, y_root=500)) is None


def test_watchlist_editor_drag_lists_and_drop_ticker_from_table(app, monkeypatch):
    from types import SimpleNamespace as NS
    from desktop import app as A
    st = app.store
    monkeypatch.setattr(app, "fetch_symbol_quiet", lambda sym: None)
    name = st.watchlists()[0]["name"]
    names = [x["name"] for x in st.settings["scanners"]]
    dlg = A.ViewDialog(app)
    dlg.update()
    ed = A.WatchlistEditor(app, dlg, name)
    ed.update()
    lx, ly = ed.left.winfo_rootx() + 20, ed.left.winfo_rooty() + 3
    rx, ry = ed.right.winfo_rootx() + 20, ed.right.winfo_rooty() + 3
    ed._press(NS(y=3), ed.left)                                                             # przeciągnięcie listy z lewego panelu na prawy
    ed._release(NS(x_root=rx, y_root=ry), ed.left)
    assert st.watchlist(name)["sources"] == [names[0]] and ed.right.get(0) == ed.LIST + names[0]
    ed._press(NS(y=3), ed.right)                                                            # i z powrotem
    ed._release(NS(x_root=lx, y_root=ly), ed.right)
    assert st.watchlist(name)["sources"] == [] and ed.right.size() == 0
    iid = app.tree.get_children()[0]                                                        # spółka z tabeli upuszczona na prawy panel
    y_row = int(app.tree.bbox(iid)[1] + 3)
    app._drag_press(NS(y=y_row, x_root=500, y_root=400))
    assert app._drag_move(NS(x_root=rx, y_root=ry)) == "break" and ed._label is not None and dlg._label is None   # edytor ma pierwszeństwo jako cel
    app._drag_release(NS(x_root=rx, y_root=ry))
    assert st.watchlist(name)["tickers"] == [iid] and ed.right.get(0, "end") == (iid,) and ed._label is None
    ed.destroy()
    dlg.destroy()


def test_run_asks_for_view_at_start_only_when_enabled(app, monkeypatch):
    from desktop import app as A
    monkeypatch.setattr(app.root, "mainloop", lambda: None)
    app.run()
    assert _wait(app, lambda: any(isinstance(w, A.ViewDialog) for w in app.root.winfo_children()), 40)
    for w in app.root.winfo_children():
        if isinstance(w, A.ViewDialog):
            w.destroy()
    app.store.set_view("list", ask=False)                                                   # „Pytaj przy każdym starcie” wyłączone
    app.run()
    app.root.update()
    import time
    time.sleep(0.4)
    app.root.update()
    assert not any(isinstance(w, A.ViewDialog) for w in app.root.winfo_children())


def test_background_always_uses_monthly_spy_sma10_also_on_weekly_and_z(app):
    w = app.store.weekly("AAA")
    # tygodniowy SPY spada (SMA 10 tyg. dałaby brak tła), miesięczny rośnie -> tło ma być na T i Z, bo liczy się SPY miesięczny
    app.store.series["SPY"] = {**w, "c": [400 - i for i in range(len(w["c"]))]}
    bands = lambda: [i for i in ch.cv.find_all() if ch.cv.type(i) == "rectangle" and ch.cv.itemcget(i, "fill") == A_chart.REGIME_BG]   # noqa: E731
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    assert bands()                                                    # T: tło z miesięcznego SPY nad SMA 10
    ch.toggle_zanger()
    ch.update()
    assert bands()                                                    # Z: to samo
    ch.toggle_zanger()
    # miesięczny SPY spada -> brak tła na T, choćby tygodniowy rósł
    app.store.series["SPY"] = {**w, "c": [100 + i for i in range(len(w["c"]))]}
    ch._spy_m = _spy_monthly(rising=False)
    ch.redraw()
    assert not bands()
    assert A_chart.monthly_regime(["2025-03-03", "2025-03-31"], _spy_monthly(), "W") == [True, True]    # tydzień dostaje stan miesiąca swojego piątku
    assert A_chart.monthly_regime(["2025-03-03"], None, "W") == [None]
    d = _spy_monthly()["d"]
    assert A_chart.monthly_regime(d, _spy_monthly(), "M") == A_chart.spy_regime(d, _spy_monthly(), "M")   # na M bez zmian
