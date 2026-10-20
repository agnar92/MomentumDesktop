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
    ev = type("E", (), {"x": 300, "y": 200})()
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
