"""Test dymny GUI — pomijany, gdy brak tkintera lub ekranu (na CI Linux uruchamiany pod xvfb)."""

import pytest

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
    ch.on_click(ev)
    assert ch.selected is not None and ch.selected_box()
    ch.zoom_selected()
    assert ch.focus_box
    app.open_scanner()
    app.scanner.vars["rs_min"].set("90")
    app.scanner.run()
    assert 0 < len(app.scanner.table.visible()) < len(app.store.rows)
    app.open_boxes()
    app.root.update()
