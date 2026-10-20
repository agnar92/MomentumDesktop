"""Test dymny GUI — pomijany, gdy brak tkintera lub ekranu (na CI Linux pod xvfb)."""
import pytest

from desktop import calc
from desktop import chart as A_chart
from desktop.store import Store

tk = pytest.importorskip("tkinter")


def _weekly(n=156):
    c = [50 + i * 0.5 + (3 if i % 7 == 0 else 0) for i in range(n)]
    return {"d": [f"{2023 + i // 52}-{(i % 52) // 4.4 + 1:02.0f}-01" for i in range(n)], "o": c, "h": [x * 1.03 for x in c], "l": [x * 0.97 for x in c],
            "c": c, "v": [2e6 + (i % 5) * 1e5 for i in range(n)]}


@pytest.fixture
def app(tmp_path):
    w = _weekly()
    rows = [calc.build_row({"ticker": t, "company": t + " Inc"}, w, [40, 120, 110, 110, 110], {"rev_rr": 30, "dopm": d}) for t, d in (("AAA", 5), ("BBB", 1))]
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
    assert app.tree.get_children() == ("AAA",)          # domyślnie tylko spełniające warunki (BBB: marża +1 pp)
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
    assert app.tree.get_children() == ("AAA",)
    d = A.SettingsDialog(app)
    d.new()
    d.name.set("Mój")
    d.filters.set("cap_largeover")
    d.save()
    assert app.store.settings["scanner"] == "Mój" and app.store.scanner["filters"] == "cap_largeover"
    assert "Mój" in app.scanner_box["values"] and app.tree.get_children() == ()


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
    assert "AAA" in st.alerts["pos"] and "AAA" in st.alerts["watch"] and "⚠" in ch.ptext.get("1.0", "end") and "Potencjał" in ch.ptext.get("1.0", "end")
    assert app.tree.item("AAA")["values"][0].startswith("📌") and "poswarn" in app.tree.item("AAA")["tags"]
    lines_ = A.checklist(row, st.alerts["pos"]["AAA"])
    assert any(ln.startswith("⚠ Masz pozycję") for ln in lines_)
    A.GuideDialog(app).destroy()
    shown = ch.show_panel
    ch.toggle_panel()
    assert ch.show_panel != shown and app.store.settings["fund_panel"] == ch.show_panel and ch.fund_btn.cget("text").startswith("◀" if shown else "▶")
    assert A.cell(3, "n") == "★★★☆☆" and A.cell("HAMUJE", "w") == "⚠ hamuje"


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
    texts = [ch.cv.itemcget(i, "text") for i in ch.cv.find_all() if ch.cv.type(i) == "text"]
    assert any(t.startswith("Stochastic (10, 1)") for t in texts)
