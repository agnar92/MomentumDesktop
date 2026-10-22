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


def test_chart_sync_button_refreshes_only_the_open_ticker(app, monkeypatch):
    import datetime as dt
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

    daily_closes = [20 + i * 0.2 for i in range(160)]
    daily_dates = [(dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(160)]
    daily = {
        "d": daily_dates, "o": daily_closes,
        "h": [v + 1 for v in daily_closes], "l": [v - 1 for v in daily_closes],
        "c": daily_closes, "v": [1e6] * len(daily_closes),
    }
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
    monkeypatch.setattr(prices, "daily_ohlc", lambda ticker: dict(daily))
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
    assert app.store.daily("AAA")["c"] == daily_closes
    assert app.store.row("AAA")["rvol_d"] == 1.0
    assert app.store.row("AAA")["cc250"] == daily_closes[-1] / daily_closes[0]
    assert ch.other["D"]["AAA"]["c"] == daily_closes
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
    assert names[0] == "Bezpieczny (backtest)" and len(names) == 4
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
    y = (g["price"][0] + g["price"][1]) / 2
    ch.press(E(200, y))
    ch.drag_line(E(260, y - 20))
    ch.drag_line(E(500, y - 60))
    ch.release(E(500, y - 60))
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
    assert any(t.startswith("S&P 500 (SPY)") for t in texts) and any(t.startswith("Przychody kw.") and "1.2 mld" in t for t in texts)
    g = ch.geom["g"]
    assert g["spx"][1] < g["price"][0] and g["vol"][1] < g["rev"][0] < g["rev"][1] < g["macd"][0]
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


def test_monthly_chart_shows_green_line_history(app, monkeypatch):
    import time
    from desktop import calc as C, prices
    h = [10, 12, 30, 20, 21, 22, 25, 28, 29, 31, 29, 28, 27]          # rekord 30 (3. mies.) stoi; 31 jeszcze nie przestał 3 zamkniętych miesięcy
    d = [f"2025-{m:02d}-01" for m in range(1, 13)] + ["2026-01-01"]
    m = {"d": d, "o": h, "h": h, "l": [x * 0.9 for x in h], "c": h, "v": [1e6] * len(h)}
    monkeypatch.setattr(prices, "monthly_ohlc", lambda t: dict(m))
    assert C.green_line_series(h)[:6] == [None, None, None, None, None, None] and C.green_line_series(h)[6] == 30
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
    assert any(t.startswith("rekord ") for t in texts) and any(t.startswith("Green Line z wykresu") for t in texts)
    ch.toggle_period("W")
    assert ch.period == "W" and ch.geom["n"] == 156


def test_daily_chart_rwb_and_blue_dot(app, monkeypatch):
    import time
    from desktop import calc as C, prices
    n = 160
    c = [50 + i * 0.4 for i in range(n)]
    c[150:154] = [c[149] - 3, c[149] - 6, c[149] - 7, c[149] - 1]       # korekta w trendzie, potem odbicie: Stochastic przecina 20 w górę
    d = [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]
    m = {"d": d, "o": c, "h": [x + 1 for x in c], "l": [x - 1 for x in c], "c": c, "v": [1e6] * n}
    assert C.rwb(c)[148] and not C.rwb([100 - i for i in range(80)])[-1]   # spadek: szybkie pod wolnymi
    dots = C.blue_dots(m["h"], m["l"], c, 40)
    assert dots and dots[-1] >= 150 and not C.blue_dots(m["h"], m["l"], c, 1e9)   # pod Green Line nie ma kropek
    monkeypatch.setattr(prices, "daily_ohlc", lambda t: dict(m))
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.toggle_period("D")
    for _ in range(50):
        app.root.update()
        if ch.geom and ch.geom["n"] == min(n, 260):
            break
        time.sleep(0.02)
    assert ch.period == "D" and ch.geom["n"] == min(n, 260)
    assert ch.daily_style == "bars" and ch.daily_style_btn.cget("text") == "D: RWB"
    ch.toggle_daily_style()     # nadal można przełączyć dzienny na RWB / GMMA
    ch.redraw()
    assert ch.daily_style == "line" and ch.daily_style_btn.cget("text") == "D: słupki"
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    assert not any(t.startswith("Stochastic") or t.startswith("Przychody kw.") or t.startswith("MACD") for t in texts)   # dzienny: RWB + Blue Dot + GLB
    assert any("Blue Dot" in t for t in texts) and ch.geom["g"]["rev"] is None




def test_revenue_surprise_is_computed_if_actual_and_estimate_are_supplied():
    from desktop.estimates import _revenue_surprise

    assert _revenue_surprise({"Reported Revenue": 110, "Revenue Estimate": 100}) == 10.0
    assert _revenue_surprise({"Reported Revenue": 90, "Revenue Estimate": 100}) == -10.0
    assert _revenue_surprise({"Reported Revenue": 90, "Revenue Estimate": 0}) is None


def test_earnings_markers_on_weekly_and_daily_charts(app, monkeypatch):
    import datetime as dt
    import time
    from desktop import prices

    weekly = app.store.weekly("AAA")
    week_event = weekly["d"][80]
    n = 120
    daily_dates = [(dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(n)]
    closes = [50 + i * 0.2 for i in range(n)]
    daily_event = daily_dates[70]
    daily = {"d": daily_dates, "o": closes, "h": [x + 1 for x in closes], "l": [x - 1 for x in closes],
             "c": closes, "v": [1e6] * n}
    monkeypatch.setattr(prices, "daily_ohlc", lambda ticker: dict(daily))
    app.store.save_cache("estimates", {"AAA": {
        "at": "2026-10-20",
        "surp": [[week_event, 6.7], [daily_event, -2.5]],
        "revenue_surp": [[week_event, 4.1], [daily_event, 8.2]],
        "rev90": None,
        "earnings_dates": [week_event, daily_event],
    }})

    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    assert "E" in texts   # raport trafia pod świecę tygodnia zawierającego datę publikacji
    g = ch.geom["g"]
    from desktop.chart import earnings_indices
    weekly_index = earnings_indices(weekly["d"], [week_event], "W")[0]
    x = g["x0"] + (weekly_index + 0.5) * ch.geom["step"]
    ch.on_motion(type("E", (), {"x": x, "y": (g["price"][0] + g["price"][1]) / 2})())
    tooltip = [ch.cv.itemcget(i, "text") for i in ch.cv.find_withtag("tip") if ch.cv.type(i) == "text"]
    assert "Earnings Surprise: +6.7%" in tooltip
    assert "Revenue Surprise: +4.1%" in tooltip

    ch.toggle_period("D")
    for _ in range(60):
        app.root.update()
        if ch.geom and ch.geom.get("n") == n:
            break
        time.sleep(0.02)
    assert ch.period == "D" and ch.geom and ch.geom.get("n") == n
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    assert "E" in texts   # w interwale dziennym E jest pod sesją raportu
    g = ch.geom["g"]
    x = g["x0"] + (70 + 0.5) * ch.geom["step"]
    ch.on_motion(type("E", (), {"x": x, "y": (g["price"][0] + g["price"][1]) / 2})())
    tooltip = [ch.cv.itemcget(i, "text") for i in ch.cv.find_withtag("tip") if ch.cv.type(i) == "text"]
    assert "Earnings Surprise: -2.5%" in tooltip
    assert "Revenue Surprise: +8.2%" in tooltip

def test_daily_trend_lines_right_click_menu_and_preserve_weekly_lines(app, monkeypatch):
    import datetime as dt
    import time
    from desktop import prices

    n = 100
    dates = [(dt.date(2026, 5, 1) + dt.timedelta(days=i)).isoformat() for i in range(n)]
    close = [40 + i * 0.2 for i in range(n)]
    daily = {"d": dates, "o": close, "h": [x + 1 for x in close], "l": [x - 1 for x in close],
             "c": close, "v": [1e6] * n}
    monkeypatch.setattr(prices, "daily_ohlc", lambda ticker: dict(daily))
    weekly = app.store.weekly("AAA")
    weekly_line = {"id": "weekly-line", "d1": weekly["d"][20], "p1": 55, "d2": weekly["d"][50], "p2": 62, "alert": True}
    app.store.alerts["lines"]["AAA"] = [weekly_line]
    app.store.save_alerts()
    app.refresh_daily_alerts = lambda: None

    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.toggle_period("D")
    for _ in range(50):
        app.root.update()
        if ch.geom and ch.geom["n"] == n:
            break
        time.sleep(0.02)
    assert ch.period == "D" and ch.daily_style == "bars"
    assert app.store.daily("AAA")["d"] == dates

    g = ch.geom["g"]
    E = lambda x, y, xr=300, yr=300: type("E", (), {"x": x, "y": y, "x_root": xr, "y_root": yr})()
    x0 = g["x0"] + 25
    x1 = g["x0"] + (g["x1"] - g["x0"]) * 0.7
    y0 = (g["price"][0] + g["price"][1]) / 2
    ch.press(E(x0, y0))
    ch.drag_line(E(x0 + 15, y0 - 10))
    ch.drag_line(E(x1, y0 - 35))
    ch.release(E(x1, y0 - 35))
    daily_lines = [ln for ln in app.store.alerts["lines"]["AAA"] if ln.get("period") == "D"]
    assert len(daily_lines) == 1 and daily_lines[0]["alert"] is False
    daily_id = daily_lines[0]["id"]

    menus = []
    monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, x, y: menus.append(self))
    monkeypatch.setattr(tk.Menu, "grab_release", lambda self: None)
    seg = ch.geom["segs"][0]
    ch.right_click(E((seg["x1"] + seg["x2"]) / 2, (seg["y1"] + seg["y2"]) / 2))
    menu = menus[-1]
    labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) != "separator"]
    assert "Dodaj alert linii" in labels and "Usuń linię" in labels
    menu.invoke(0)
    assert next(ln for ln in app.store.alerts["lines"]["AAA"] if ln["id"] == daily_id)["alert"] is True
    assert any(ln["id"] == "weekly-line" for ln in app.store.alerts["lines"]["AAA"])

    seg = ch.geom["segs"][0]
    ch.right_click(E((seg["x1"] + seg["x2"]) / 2, (seg["y1"] + seg["y2"]) / 2))
    menu = menus[-1]
    assert menu.entrycget(0, "label") == "Wyłącz alert linii"
    menu.invoke(2)
    remaining = app.store.alerts["lines"]["AAA"]
    assert all(ln["id"] != daily_id for ln in remaining)
    assert any(ln["id"] == "weekly-line" for ln in remaining)


def test_exit_method_toggle_and_position_plan(app):
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.toggle_pos()
    ch.toggle_exit()
    assert app.store.settings["exit"] == "GLB" and ch.exit_btn.cget("text") == "🚪 Wyjście: pod GLB"
    ch.redraw()
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    assert any("wyjście: zamknięcie tyg. pod linią" in t for t in texts) and any(t.startswith("stop −10 %") for t in texts)
    assert "PLAN WYJŚCIA" in ch.ptext.get("1.0", "end")
    ch.toggle_exit()
    assert app.store.settings["exit"] == "MACD"


def test_period_buttons_and_ibd_rs_line(app):
    st = app.store
    w = st.weekly("AAA")
    st.series["SPY"] = {**w, "c": [400 - i for i in range(len(w["c"]))]}   # SPY spada -> RS rośnie, na szczycie 52 tyg.
    app.open_chart("AAA")
    ch = app.chart
    ch.update()
    ch.redraw()
    assert set(ch.per_btns) == {"M", "W", "D"} and ch.per_btns["W"].cget("text") == "T" and ch.per_btns["W"].cget("bg") == "#1f3b5c"
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    rs = st.row("AAA")["rs"]
    assert f"{rs:+.0f} pp" in texts and not any(t.startswith("RS (cena") for t in texts)   # na końcu linii RS tylko liczba pp
    assert A_chart.rs_line([10, 20, None], [5, 4, 2]) == [2, 5, None]


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


def test_ctrl_k_fetches_symbol_that_has_only_candles(app, monkeypatch):
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



def test_growth_score_dialog_can_expand_component_breakdown(app):
    from desktop import app as A

    app.store.row("AAA").update(rev_rr=30, accel=8, eps_rev=15, dopm=5, surp=4, surp_prev=3, beat2=True)
    dialog = A.GrowthScoreDialog(app)
    dialog.update()
    assert dialog.show_components is False
    dialog.toggle_components()
    dialog.update()
    assert dialog.show_components is True
    details = dialog.detail_text.get("1.0", "end")
    assert "AAA · Growth Score:" in details
    assert "Pokrycie danych: 100/100" in details
    assert "Przychody r/r: +30,0% →" in details
    assert "Dwa pozytywne zaskoczenia EPS: TAK" in details

    # Brakujące dane są jawnie pokazane jako pominięte i nie dostają punktów automatycznie.
    app.store.row("BBB").update(rev_rr=None, accel=None, eps_rev=None, dopm=None, surp=None, surp_prev=None, beat2=None)
    dialog.tree.selection_set("BBB")
    dialog.update_components()
    details = dialog.detail_text.get("1.0", "end")
    assert "BBB · Growth Score: brak (za małe pokrycie)" in details
    assert "brak danych · pominięte" in details
    dialog.toggle_components()
    dialog.close()


def test_growth_score_dialog_lists_ranked_tickers_and_opens_chart_on_ticker_click(app, monkeypatch):
    from desktop import app as A

    app.store.row("AAA").update(rev_rr=30, accel=8, eps_rev=15, dopm=5, surp=4, surp_prev=3, beat2=True)
    app.store.row("BBB").update(rev_rr=10, accel=0, eps_rev=0, dopm=0, surp=-2, surp_prev=1, beat2=False)
    dialog = A.GrowthScoreDialog(app)
    dialog.update()
    assert dialog.tree.get_children() == ("AAA", "BBB")
    assert float(dialog.tree.set("AAA", "score")) > float(dialog.tree.set("BBB", "score"))

    opened = []
    monkeypatch.setattr(app, "open_chart", lambda ticker: opened.append(ticker))
    box = dialog.tree.bbox("AAA", column="#1")
    assert box
    event = type("E", (), {"x": box[0] + 8, "y": box[1] + box[3] // 2})()
    dialog.on_cell_click(event)
    assert opened == ["AAA"]

    # Zmiana danych i odświeżenie odświeża istniejące okno.
    app.store.row("BBB").update(rev_rr=40, accel=10, eps_rev=20, dopm=4, surp=3, surp_prev=2, beat2=True)
    app.refresh()
    assert dialog.tree.get_children()[0] == "BBB"
    dialog.close()
