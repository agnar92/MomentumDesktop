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
    (app.data_root / "eps_cache.json").unlink(missing_ok=True)   # nigdzie nie ma EPS -> pierwszy Sync pobiera fundamenty
    app.start_sync(view, sync.PRICES)
    assert _wait(app, lambda: not app.syncing)
    assert seen["mode"] == sync.FUNDAMENTALS and seen["shared_root"] == app.data_root


def test_new_scanner_with_shared_eps_cache_syncs_only_prices(app, monkeypatch):
    from desktop import scanners, sync
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *a, **k: None)
    sc = scanners.upsert(app.data_root, {"name": "Nowy2"}, "geo_usa", 20)
    app.open_scanner_window(sc["id"])
    view = app.view_for(sc["id"])
    seen = {}
    monkeypatch.setattr(sync, "run_in_subprocess", lambda data_dir, log, **k: seen.update(k) or 0)
    (app.data_root / "eps_cache.json").write_text("{}")
    app.start_sync(view, sync.PRICES)
    assert _wait(app, lambda: not app.syncing)
    assert seen["mode"] == sync.PRICES


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


def test_closing_main_window_keeps_app_alive_while_other_windows_open(app, monkeypatch):
    from desktop import app as A
    from desktop import scanners
    sc = scanners.upsert(app.data_root, {"name": "Drugi"}, "geo_usa", 20)
    app.open_scanner_window(sc["id"])
    app.root.update()
    quits = []
    monkeypatch.setattr(app, "quit_app", lambda: quits.append(1))
    app.close_main()                                         # są inne okna -> główne się chowa, program żyje
    app.root.update()
    assert not quits and app.root.state() == "withdrawn" and app.main_hidden and app.launcher.winfo_exists()
    app.launcher.box.selection_clear(0, "end")
    app.launcher.box.selection_set(app.launcher.ids.index(scanners.DEFAULT_ID))
    app.launcher.open()                                      # powrót do głównego z małego okna
    app.root.update()
    assert app.root.state() == "normal" and not app.main_hidden
    app.close_main()
    app.window_closed(sc["id"])                              # ostatni skaner zamknięty, główne schowane -> zostaje małe okno
    assert app.launcher.winfo_exists() and not quits
    app.save_session()
    app.quit_app = lambda: None
    app2 = A.App(app.data_root)                              # sesja: główne było schowane -> start też bez głównego, z małym oknem
    try:
        app2.root.update()
        assert app2.root.state() == "withdrawn" and app2.launcher is not None and app2.launcher.winfo_exists()
    finally:
        app2.root.destroy()


def test_closing_main_window_with_nothing_else_quits(app, monkeypatch):
    quits = []
    monkeypatch.setattr(app, "quit_app", lambda: quits.append(1))
    app.close_main()
    assert quits == [1]


def test_hover_tooltip_and_sma_detection(app):
    v = app.view
    v.open_chart("NVDA")
    ch = v.chart
    ch.update()
    ch.tf.set("D")
    ch.change_tf()
    ch.mode.set("bars")
    ch.redraw()
    ch.update()
    g = ch.geoms["bars"]
    full, dates, _spx, smas = ch.series()
    i = g["i1"] - 5
    arr50 = next(a for a, n in smas if n == 50)
    Ev = type("E", (), {})
    e = Ev()
    e.x, e.y = g["xf"](i), g["y"](arr50[i]) + 2             # kursor tuż przy linii SMA 50
    assert ch.hovered_sma(g, e, i, smas) == 50
    e.y = g["y"](arr50[i]) - 120
    assert ch.hovered_sma(g, e, i, smas) in (None, 10, 200)  # daleko od linii 50
    e.y = g["y"](arr50[i]) + 2
    ch.on_motion(e, ch.cv_bars)
    texts = [ch.cv_bars.itemcget(it, "text") for it in ch.cv_bars.find_withtag("cross") if ch.cv_bars.type(it) == "text"]
    assert any(t.startswith("SMA 50 (dzienna)") for t in texts) and any("do szczytu 52t" in t for t in texts)
    ch.mode.set("darcard")
    ch.redraw()
    ch.update()
    gc = ch.geoms["card"]
    e.x, e.y = gc["xf"](gc["i1"] - 3), gc["H"] // 2
    ch.on_motion(e, ch.cv_card)
    texts = [ch.cv_card.itemcget(it, "text") for it in ch.cv_card.find_withtag("cross") if ch.cv_card.type(it) == "text"]
    assert any(t.startswith("zamknięcie") for t in texts)
    ch.log.set(False)                                         # przełącznik skali log -> liniowa przerysowuje się bez błędu
    ch.macd_on.set(False)
    ch.mode.set("bars")
    ch.redraw()
    ch.update()


def test_flags_keys_filter_and_shared_between_scanners(app, monkeypatch):
    from desktop import scanners
    sc = scanners.upsert(app.data_root, {"name": "Inny"}, "geo_usa", 20)
    v = app.view
    t = v.table.visible()[0]
    v.table.tree.selection_set(t)
    ev = type("E", (), {"char": "2"})()
    v.table._key(ev)                                        # klawisz 2 = „Kupione”
    assert app.flags.get(t) == "bought" and v.store.row(t)["flag"] == "bought" and "flag_bought" in v.table.tree.item(t)["tags"]
    assert v.table.tree.item(t)["values"][v.table.columns.index("flag")] == "🛒"
    v.table._key(type("E", (), {"char": "2"})())              # ten sam klawisz drugi raz = zdjęcie flagi
    assert app.flags.get(t) is None
    v.table._key(type("E", (), {"char": "1"})())
    v.flag_filter.set("⭐ Obserwuję")
    v.refresh_lists()
    assert v.table.visible() == [t]
    v.flag_filter.set("Bez listy")
    v.refresh_lists()
    assert t not in v.table.visible() and len(v.table.visible()) == len(v.store.rows) - 1
    app.open_scanner_window(sc["id"])
    assert app.view_for(sc["id"]).store.rows == []           # flagi są globalne, ale inny skaner nie ma tej spółki
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *a, **k: None)
    app.edit_list_names()


def test_whats_new_after_sync_and_marks(app, monkeypatch):
    v = app.view
    app.syncing["default"] = None
    rows = v.store.rows
    gone, up = rows[0]["ticker"], rows[1]["ticker"]
    for r in rows:
        if r["ticker"] == up:
            r["darvas_w"] = "HOLD"                           # przed Sync nie było KUP

    def fake_reload():
        v.store.rows = [r for r in v.store.rows if r["ticker"] != gone]   # wypadła ze skanera
        for r in v.store.rows:
            if r["ticker"] == up:
                r["darvas_w"] = "BUY"                        # nowe KUP
        v.store.rows.append({"ticker": "NEWCO", "company": "Nowa", "price": 5.0, "darvas_w": "WAIT", "darvas_d": "WAIT", "pbox": "NONE", "cs": None})
        v.store._mark_changes()

    monkeypatch.setattr(v, "reload", fake_reload)
    opened = []
    monkeypatch.setattr(v, "open_changes", lambda: opened.append(1))
    app.q.put(("done", "default", True))
    assert _wait(app, lambda: v.store.changes["at"] is not None)
    d = v.store.changes["diff"]
    assert d["new"] == ["NEWCO"] and d["dropped"] == [gone] and d["buy_w"] == [up] and opened == [1]
    assert v.store.row(up)["change"] == "▲ KUP tyg." and v.store.row("NEWCO")["change"] == "★ nowa" and v.news_btn["text"].startswith("Co nowego (3")
    from desktop.dialogs import WhatsNewWindow
    w = WhatsNewWindow(v)
    w.update()
    assert w.tree.exists("sec:buy_w") and w.tree.exists(f"buy_w:{up}") and w.tree.exists("sec:dropped")
    w.clear()
    assert v.store.changes["diff"] == {} and v.store.row(up)["change"] == ""


def test_export_actions(app, monkeypatch, tmp_path):
    v = app.view
    v.copy_tickers(",")
    clip = app.root.clipboard_get()
    assert clip.split(",") == v.table.visible()
    v.copy_tickers("\n")
    assert app.root.clipboard_get().split("\n") == v.table.visible()
    out = tmp_path / "x.csv"
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **k: str(out))
    v.save_csv("xl")
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and raw.decode("utf-8-sig").splitlines()[0].startswith("Symbol;") and len(raw.decode("utf-8-sig").splitlines()) == len(v.table.visible()) + 1
    t = tmp_path / "t.txt"
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **k: str(t))
    v.save_tickers()
    assert t.read_text(encoding="utf-8").split(",") == v.table.visible()


def test_symbol_search(app, monkeypatch):
    import numpy as np
    import pandas as pd
    from desktop import adhoc
    from desktop.dialogs import SymbolDialog
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *a, **k: None)
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda *a, **k: None)
    v = app.view
    # --- szukanie symbolu: spółka ze skanera otwiera się od razu, obca jest pobierana (tu: atrapa pobierania)
    rng = np.random.default_rng(7)
    idx = pd.bdate_range(end="2026-10-09", periods=420)
    close = 40 * np.exp(np.cumsum(rng.normal(0.001, 0.015, 420)))
    df = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": rng.integers(1e6, 4e6, 420)}, index=idx)
    monkeypatch.setattr(adhoc, "fetch", lambda sym, weeks=None, dates=None: (adhoc.build(sym, df, weeks, dates), "Obca Spółka"))
    d = SymbolDialog(v)
    d.var.set(" nvda ")
    d.go()
    assert v.chart is not None and v.chart.ticker == "NVDA" and "NVDA" in app.session["symbols"]
    d = SymbolDialog(v)
    d.var.set("obca")
    d.go()
    assert _wait(app, lambda: v.store.row("OBCA") is not None)
    assert v.chart.ticker == "OBCA" and v.store.row("OBCA")["company"] == "Obca Spółka" and app.session["symbols"][0] == "OBCA"
    v.chart.update()
    v.chart.redraw()
    assert v.chart.geoms["card"] and v.chart.full is not None
    d = SymbolDialog(v)
    d.var.set("to nie symbol!!")
    d.go()
    assert "nie wygląda" in d.msg["text"]
    d.destroy()
