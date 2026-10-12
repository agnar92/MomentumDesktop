"""Test dymny GUI — pomijany, gdy brak tkintera lub ekranu (na CI Linux uruchamiany pod xvfb)."""

import pytest

from desktop import charts

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app(tmp_path):
    try:
        from desktop import app as A
        a = A.App(tmp_path / "d")
    except tk.TclError:
        pytest.skip("brak ekranu")
    yield a
    a.root.destroy()


def test_windows_open_and_select_box(app):
    app.root.update()
    assert len(app.table.visible()) == len(app.store.rows) > 0
    app.open_chart("NVDA")
    ch = app.chart
    ch.update()
    ch.redraw()
    ch.update()
    g = ch.geoms["card"]
    assert g["hits"]
    x0, y0, x1, y1 = g["hits"][-1]["rect"]
    ev = type("E", (), {"x": (x0 + x1) / 2, "y": (y0 + y1) / 2})()
    assert ch.mode.get() == "darcard"
    ch.on_click(ev)
    assert ch.selected is not None and ch.selected_box()
    ch.zoom_selected()
    assert ch.focus_box and ch.mode.get() == "bars"
    ch.clear_focus()
    assert ch.mode.get() == "darcard"
    ch.toggle_mode()
    assert ch.mode.get() == "bars"
    ch.update()
    n = len(app.store.weeks)
    W = ch.slider.winfo_width()
    x0, x1 = charts.slider_rect(n, ch.n_show, ch.end, W)
    ch.slider_press(type("E", (), {"x": (x0 + x1) / 2})())
    ch.slider_move(type("E", (), {"x": (x0 + x1) / 2 - 80})())
    assert ch.end is not None and ch.end < n
    app.set_tf("D")
    assert app.store.tf == "D" and "dzień" in app.table.tree.heading("darvas")["text"]
    ch.tf.set("D")
    ch.change_tf()
    ch.mode.set("bars")
    ch.redraw()
    ch.update()
    assert ch.geoms["bars"]["i1"] > 0 and ch.unit() == "sesji"
    app.open_canslim("NVDA")
    app.open_criteria()
    app.open_scanner()
    app.scanner.vars["cs_min"].set("5")
    app.scanner.cs_core.set(True)
    app.scanner.run()
    assert 0 < len(app.scanner.table.visible()) < len(app.store.rows)
    app.scanner.reset()
    app.scanner.vars["rs_min"].set("90")
    app.scanner.run()
    assert 0 < len(app.scanner.table.visible()) < len(app.store.rows)
    app.open_boxes()
    app.root.update()
