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
    try:
        a.root.destroy()
    except tk.TclError:
        pass


def test_windows_open_and_select_box(app):
    v = app.view
    app.root.update()
    assert len(v.table.visible()) == len(v.store.rows) > 0
    v.open_chart("NVDA")
    ch = v.chart
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
    n = len(v.store.weeks)
    W = ch.slider.winfo_width()
    x0, x1 = charts.slider_rect(n, ch.n_show, ch.end, W)
    ch.slider_press(type("E", (), {"x": (x0 + x1) / 2})())
    ch.slider_move(type("E", (), {"x": (x0 + x1) / 2 - 80})())
    assert ch.end is not None and ch.end < n
    v.set_tf("D")
    assert v.store.tf == "D" and "dzień" in v.table.tree.heading("darvas")["text"]
    ch.tf.set("D")
    ch.change_tf()
    ch.mode.set("bars")
    ch.redraw()
    ch.update()
    assert ch.geoms["bars"]["i1"] > 0 and ch.unit() == "sesji"
    v.open_canslim("NVDA")
    v.open_criteria()
    v.open_filter()
    f = v.filter_win
    f.vars["cs_min"].set("5")
    f.cs_core.set(True)
    f.run()
    assert 0 < len(f.table.visible()) < len(v.store.rows)
    f.reset()
    f.vars["rs_min"].set("90")
    f.run()
    assert 0 < len(f.table.visible()) < len(v.store.rows)
    v.open_boxes()
    app.root.update()


def test_scanner_builder_columns_and_windows(app, monkeypatch):
    from desktop import scanners
    from desktop.builder import ScannerEditor, ScannerManager
    from desktop.dialogs import ColumnsWindow
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *a, **k: None)
    ed = ScannerEditor(app)
    ed.update()
    ed.name.set("Dywidendowy")
    ed.combos["Dywidenda"].set("Dodatnia")
    ed.combos["Kraj"].set("USA")
    ed.from_combos()
    assert ed.raw.get() == "geo_usa,fa_div_pos"        # lista wyboru -> kody (kolejność katalogu)
    ed.raw.set("geo_usa,fa_div_pos,ta_sma200_pa,zly_kod")  # kody -> listy wyboru, nieznany kod zostaje
    assert ed.combos["Cena vs SMA 200"].get() == "Powyżej" and ed.rest == ["zly_kod"]
    ed.url.set("https://finviz.com/screener.ashx?v=111&f=cap_smallover,sh_price_o10&ft=4")
    ed.import_url()
    assert ed.raw.get() == "cap_smallover,sh_price_o10" and ed.combos["Cena"].get() == "> 10 $"
    ed.extra_vars["fv_dividend"].set(True)
    ed.save(None)
    sc = [s for s in scanners.load(app.data_root) if s["name"] == "Dywidendowy"][0]
    assert sc["extra"] == ["fv_dividend"] and scanners.load_config(scanners.scanner_dir(app.data_root, sc["id"]))["filters"] == "cap_smallover,sh_price_o10"
    w = app.windows[sc["id"]]                       # nowy skaner od razu otwiera się w osobnym oknie, bez danych
    w.update()
    assert w.view.store.rows == [] and app.view_for(sc["id"]) is w.view
    cw = ColumnsWindow(app.view)
    cw.update()
    assert "ticker" in cw.cols and "market_cap" in cw.avail
    cw.cols = ["ticker", "price", "market_cap"]
    cw.apply()
    assert app.view.table.columns == ["ticker", "price", "market_cap"] and scanners.get(app.data_root, "default")["columns"] == ["ticker", "price", "market_cap"]
    assert app.view.table.tree.item("NVDA")["values"][2].endswith("B") or app.view.table.tree.item("NVDA")["values"][2].endswith("T")
    mg = ScannerManager(app)
    mg.update()
    assert len(mg.tree.get_children()) == 2
    mg.tree.selection_set(sc["id"])
    mg.duplicate()
    assert len(mg.tree.get_children()) == 3
    app.delete_scanner(sc["id"])
    assert sc["id"] not in [s["id"] for s in scanners.load(app.data_root)] and not w.winfo_exists()


def _wait(app, cond, seconds=4):
    import time
    end = time.time() + seconds
    while time.time() < end and not cond():
        app.root.update()
        time.sleep(0.03)
    return cond()


def test_first_sync_of_new_scanner_fetches_fundamentals(app, monkeypatch):
    from desktop import scanners, sync
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *a, **k: None)
    sc = scanners.upsert(app.data_root, {"name": "Nowy"}, "geo_usa", 20)
    app.open_scanner_window(sc["id"])
    view = app.view_for(sc["id"])
    seen = {}
    monkeypatch.setattr(sync, "run_in_subprocess", lambda data_dir, log, **k: seen.update(k) or 0)
    app.start_sync(view, sync.PRICES)
    assert _wait(app, lambda: not app.syncing)
    assert seen["mode"] == sync.FUNDAMENTALS and seen["shared_root"] == app.data_root


def test_two_scanners_sync_in_parallel(app, monkeypatch):
    import threading
    from desktop import scanners, sync
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *a, **k: None)
    a = scanners.upsert(app.data_root, {"name": "A"}, "geo_usa", 20)
    b = scanners.upsert(app.data_root, {"name": "B"}, "geo_usa", 20)
    app.open_scanner_window(a["id"])
    app.open_scanner_window(b["id"])
    va, vb = app.view_for(a["id"]), app.view_for(b["id"])
    release, started = threading.Event(), []

    def fake(data_dir, log, **k):
        started.append(data_dir.name)
        log("linia dziennika")
        assert release.wait(5)
        return 0

    monkeypatch.setattr(sync, "run_in_subprocess", fake)
    app.start_sync(va, sync.FUNDAMENTALS)
    app.start_sync(vb, sync.FUNDAMENTALS)
    assert _wait(app, lambda: len(started) == 2)          # oba procesy ruszyły, zanim pierwszy się skończył
    assert set(app.syncing) == {a["id"], b["id"]} and str(va.prices_btn["state"]) == "disabled" and str(app.view.prices_btn["state"]) == "normal"
    app.start_sync(va, sync.PRICES)                       # ten sam skaner drugi raz = odmowa, nie nowy proces
    assert len(started) == 2
    release.set()
    assert _wait(app, lambda: not app.syncing)
    assert str(va.prices_btn["state"]) == "normal" and str(vb.prices_btn["state"]) == "normal"


def test_launcher_orders_by_recent_and_session_is_restored(app, tmp_path):
    from desktop import app as A
    from desktop import scanners, session
    a = scanners.upsert(app.data_root, {"name": "Alfa"}, "geo_usa", 20)
    b = scanners.upsert(app.data_root, {"name": "Beta"}, "geo_usa", 20)
    app.open_scanner_window(a["id"])
    app.open_scanner_window(b["id"])
    app.open_launcher()
    lw = app.launcher
    lw.update()
    assert lw.ids[:2] == [b["id"], a["id"]]                # ostatnio otwarty pierwszy
    assert lw.box.get(0).startswith("●") and "Beta" in lw.box.get(0)
    app.window_closed(a["id"])                              # zamknięty skaner traci ●, ale zostaje na liście
    assert lw.box.get(lw.ids.index(a["id"])).startswith("○")
    lw.box.selection_clear(0, "end")
    lw.box.selection_set(lw.ids.index(a["id"]))
    lw.open()
    assert app.view_for(a["id"]) is not None and lw.ids[0] == a["id"]
    app.window_closed(a["id"])
    app.save_session()
    sess = session.load(app.data_root)
    assert sess["open"] == [b["id"]] and sess["launcher"] is True
    app.quit_app()                                           # zamknięcie programu zapisuje sesję; nowa instancja ją odtwarza
    app2 = A.App(app.data_root)
    try:
        app2.root.update()
        assert app2.view_for(b["id"]) is not None and app2.view_for(a["id"]) is None
        assert app2.launcher is not None and app2.launcher.winfo_exists()
    finally:
        app2.root.destroy()
