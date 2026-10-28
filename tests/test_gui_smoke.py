"""Test dymny GUI — pomijany, gdy brak tkintera lub ekranu (na CI Linux pod xvfb)."""
import pytest

from desktop import calc
from desktop import chart as A_chart
from desktop.store import Store

tk = pytest.importorskip("tkinter")


def _weekly(n=156):
    c = [50 + i * 0.5 + (3 if i % 7 == 0 else 0) for i in range(n)]
    return {"d": [f"{2023 + i // 52}-{(i % 52) // 4.4 + 1:02.0f}-01" for i in range(n)], "o": c, "h": [x * 1.03 for x in c], "l": [x * 0.97 for x in c],
            "c": c, "v": [5e6 + (i % 5) * 1e5 for i in range(n)]}


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
    yield a
    try:
        a.root.destroy()
    except tk.TclError:
        pass


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
    names = list(app.scanner_box["values"])
    assert names[0] == "Sektory top 3 (RS)" and len(names) == 5
    app.select_scanner(names[1])
    assert app.tree.get_children() == () and app.store.settings["scanner"] == names[1]
    app.select_scanner(names[0])
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
    assert "Mój" in app.scanner_box["values"] and app.tree.get_children() == ()


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
    ch.toggle_rwb()                                                                # RWB tylko na wykresie tygodniowym
    assert ch.rwb and ch.rwb_btn.cget("bg") == "#1f3b5c"
    assert len(gmma_lines()) >= 12 and dot_items()                                 # 12 średnich Guppy + ● Blue Dot
    strip = [i for i in ch.cv.find_all() if ch.cv.type(i) == "rectangle" and ch.cv.itemcget(i, "fill") == A_chart.SLOW_C]
    assert strip                                                                   # pasek RWB u dołu panelu ceny
    g = ch.geom["g"]
    ch.on_motion(type("E", (), {"x": g["x0"] + (dots[-1] - ch.geom["i0"] + 0.5) * ch.geom["step"], "y": (g["price"][0] + g["price"][1]) / 2})())
    tooltip = [ch.cv.itemcget(i, "text") for i in ch.cv.find_withtag("tip") if ch.cv.type(i) == "text"]
    assert any(t.startswith("BLUE DOT") for t in tooltip)
    ch.toggle_period("M")
    assert ch.rwb_btn.cget("state") == "disabled"                                  # na miesięcznym RWB nie ma


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
    ch.toggle_period("D")
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
