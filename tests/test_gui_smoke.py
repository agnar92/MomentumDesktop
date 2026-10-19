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
    assert ch.mode.get() == "karta"
    ch.on_click(ev)
    assert ch.selected is not None and ch.selected_box()
    ch.zoom_selected()
    assert ch.focus_box and ch.mode.get() == "bars"
    ch.clear_focus()
    assert ch.mode.get() == "karta"
    ch.toggle_mode()                       # spacja: 🃏 Karta → 🟩 GLB → Słupkowy
    assert ch.mode.get() == "glb"
    ch.redraw()
    assert ch.geoms["card"].get("kind") == "glb"
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
    leaves = lambda: [i for g in mg.tree.get_children() for i in mg.tree.get_children(g)]   # skanery są w grupach „Skany” / „Watchlisty”
    assert len(leaves()) == 2
    mg.tree.selection_set(sc["id"])
    mg.duplicate()
    assert len(leaves()) == 3
    app.delete_scanner(sc["id"])
    assert sc["id"] not in [s["id"] for s in scanners.load(app.data_root)] and not w.winfo_exists()


def _wait(app, cond, seconds=4):
    import time
    end = time.time() + seconds
    while time.time() < end and not cond():
        app.root.update()
        time.sleep(0.03)
    return cond()


def test_prices_sync_of_new_scanner_never_fetches_fundamentals(app, monkeypatch):
    from desktop import scanners, sync
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *a, **k: None)
    sc = scanners.upsert(app.data_root, {"name": "Nowy"}, "geo_usa", 20)
    app.open_scanner_window(sc["id"])
    view = app.view_for(sc["id"])
    seen = {}
    monkeypatch.setattr(sync, "run_in_subprocess", lambda data_dir, log, **k: seen.update(k) or 0)
    (app.data_root / "eps_cache.json").unlink(missing_ok=True)   # nigdzie nie ma EPS — „ceny” i tak pobierają same ceny
    app.start_sync(view, sync.PRICES)
    assert _wait(app, lambda: not app.syncing)
    assert seen["mode"] == sync.PRICES
    app.start_sync(view, sync.FUNDAMENTALS)                      # dopiero „fundamenty” pobierają ceny i fundamenty
    assert _wait(app, lambda: not app.syncing)
    assert seen["mode"] == sync.FUNDAMENTALS


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
    assert lw.ids[:3] == [None, b["id"], a["id"]]          # nagłówek grupy, potem ostatnio otwarty pierwszy
    assert lw.box.get(1).startswith("●") and "Beta" in lw.box.get(1)
    app.window_closed(a["id"])                              # zamknięty skaner traci ●, ale zostaje na liście
    assert lw.box.get(lw.ids.index(a["id"])).startswith("○")
    lw.box.selection_clear(0, "end")
    lw.box.selection_set(lw.ids.index(a["id"]))
    lw.open()
    assert app.view_for(a["id"]) is not None and lw.ids[1] == a["id"]
    app.window_closed(a["id"])
    app.save_session()
    sess = session.load(app.data_root)
    assert sess["open"] == [b["id"]] and sess["launcher"] is True
    app.quit_app()                                           # zamknięcie programu zapisuje sesję; nowa instancja ją odtwarza
    app2 = A.App(app.data_root)
    try:
        app2.root.update()
        assert _wait(app2, lambda: app2.view_for(b["id"]) is not None)   # okna z sesji wczytują się w tle (kółko „wczytuję”)
        assert app2.view_for(a["id"]) is None
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


def test_unconfirmed_box_has_red_dashed_bottom_and_focus_keeps_flag(app):
    from desktop import darvas
    v = app.view
    app.root.update()
    for t in [r["ticker"] for r in v.store.rows]:
        full = v.store.series(t, "W")[0]
        bx = darvas.boxes(full["c"]) if full else []
        if any(not b["confirmed"] and b["outcome"] != "down" for b in bx):
            break
    else:
        pytest.skip("brak niepotwierdzonego boxa w danych testowych")
    v.open_chart(t)
    ch = v.chart
    ch.update()
    ch.redraw()
    ch.update()
    cv = ch.cv_card
    reds = [i for i in cv.find_all() if cv.type(i) == "line" and cv.itemcget(i, "dash") and cv.itemcget(i, "fill") == charts.RED]
    assert reds and any(not h["box"]["confirmed"] for h in ch.geoms["card"]["hits"])
    ub = next(h["box"] for h in ch.geoms["card"]["hits"] if not h["box"]["confirmed"] and h["box"]["outcome"] != "down")
    ch.set_focus({k: ub[k] for k in ("top", "bottom", "i0", "i1", "outcome")})
    assert ch.focus_box["confirmed"] is False


def test_watchlist_window_from_qm_scan_and_canslim_scan(app, monkeypatch):
    import shutil

    from desktop import qm, scanners
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *a, **k: None)
    sc = scanners.upsert(app.data_root, {"name": "QM", "kind": "qm", "columns": list(qm.DEFAULT_COLUMNS)}, "cap_smallover", 3000,
                         {"keep_dollar_mln": 25, "keep_adr": 2, "top_pct": 10})
    d = scanners.scanner_dir(app.data_root, sc["id"])
    d.mkdir(parents=True, exist_ok=True)
    for f in ("watchlist.json", "charts.json", "charts_daily.json"):
        shutil.copy(app.data_root / f, d / f)
    app.open_scanner_window(sc["id"])
    v = app.view_for(sc["id"])
    assert v.kind == "qm" and len(v.table.visible()) == len(v.store.rows)   # skan pokazuje wszystkie pobrane spółki (z filtrem, bez progów QM)
    rule = {"type": "qm", "min_dollar_mln": 50, "min_adr": 3, "top_pct": 10, "windows": ["1m", "3m", "6m"]}
    wl = scanners.upsert(app.data_root, {"name": "Małe okno", "kind": "watchlist", "sources": [{"id": sc["id"], "rule": rule},
                                                                                              {"id": scanners.DEFAULT_ID, "rule": {"type": "canslim", "cs_min": 6, "cs_core": True}}]})
    app.open_scanner_window(wl["id"])
    w = app.windows[wl["id"]]
    assert type(w).__name__ == "WatchlistWindow"
    mv = app.view_for(wl["id"])
    app.start_sync(mv, "prices")
    assert _wait(app, lambda: not app.syncing)
    tickers = [r["ticker"] for r in mv.store.rows]
    assert 0 < len(tickers) < len(v.store.rows) and len(set(tickers)) == len(tickers)
    assert any(r.get("qm_windows") for r in mv.store.rows) and all(r.get("merge_src") for r in mv.store.rows)
    # kliknięcie tickera na małej liście otwiera wykres
    app.root.update()
    t = mv.table.visible()[0]
    mv.table.tree.selection_set(t)
    app.root.update()
    assert mv.chart is not None and mv.chart.ticker == t
    # lista Qullamaggie: kolumny cena/min Low i sortowanie po największej wartości
    assert {"low_ratio_1m", "low_ratio_3m", "low_ratio_6m", "qm_max_ratio"} <= set(mv.columns())
    assert mv.table.sort_col == "qm_max_ratio"
    # dodatkowa kolumna z danych skanów (do sortowania po kliknięciu nagłówka)
    mv.set_columns(mv.columns() + ["adr_pct"])
    assert "adr_pct" in mv.table.columns
    assert "adr_pct" in mv.columns()


def _clipped_buttons(win):
    win.update_idletasks()
    win.update()
    W, H, rx, ry = win.winfo_width(), win.winfo_height(), win.winfo_rootx(), win.winfo_rooty()
    bad = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Toplevel):
                continue   # okna potomne (np. wykres otwarty z okna przypiętych boxów) sprawdzamy osobno
            if isinstance(c, (tk.Button, tk.Checkbutton, tk.Radiobutton)) and c.winfo_ismapped():
                if c.winfo_rootx() - rx + c.winfo_width() > W + 1 or c.winfo_rooty() - ry + c.winfo_height() > H + 1:
                    bad.append(c.cget("text"))
            walk(c)
    walk(win)
    return bad


def test_dialog_buttons_not_clipped(app):
    from desktop import scanners
    v = app.view
    app.root.update()
    v.open_chart("NVDA")
    opened = [v.chart, v.open_filter() or v.filter_win, v.open_boxes() or v.boxes]
    app.open_manager()
    opened.append(app.manager)
    app.new_scanner(scanners.KIND_QM)
    app.new_scanner(scanners.KIND_WATCHLIST)
    v.choose_columns()
    for w in app.root.winfo_children():
        if isinstance(w, tk.Toplevel) and w not in opened:
            opened.append(w)
    for w in opened:
        assert not _clipped_buttons(w), (w.title(), _clipped_buttons(w))


def test_tooltip_broken_box_and_chart_placement(app):
    from desktop import darvas
    # złamany box: bez „do wybicia”, z exitem / stopem; tooltip wybranego tygodnia
    c = [10, 11, 12, 13, 12, 11, 10.5, 11, 11.5, 11, 10, 9.5, 9]
    bx = [b for b in darvas.boxes(c) if b["outcome"] == "down"]
    full = {"c": c}
    dates = [f"2025-{n // 4 + 1:02d}-{n % 4 * 7 + 1:02d}" for n in range(len(c))]
    assert bx
    if bx:
        i = bx[0]["i1"]
        lines = [t for t, _ in charts.tooltip_card(full, dates, i, "W")]
        assert any("złamany" in t for t in lines) and not any("do wybicia" in t for t in lines)
    # wykres otwiera się przy lewej krawędzi skanera (prawa krawędź wykresu przylega do lewej skanera)
    v = app.view
    app.root.geometry("900x500+1000+100")
    app.root.update()
    v.open_chart("NVDA")
    v.chart.update()
    assert v.chart.winfo_x() + v.chart.winfo_width() <= app.root.winfo_x() + 2


def test_pinned_window_and_grouped_launcher(app):
    from desktop import scanners
    v = app.view
    app.root.update()
    t = v.store.rows[0]["ticker"]
    _, dates, _, _ = v.store.series(t, v.store.tf)
    v.store.pin(t, {"top": 1e6, "bottom": 1e5, "start": dates[-10]})   # cena poniżej boxa → EXIT, na górze listy
    scanners.upsert(app.data_root, {"name": "WL x", "kind": scanners.KIND_WATCHLIST, "sources": []})
    app.open_launcher()
    app.root.update()
    items = list(app.launcher.box.get(0, "end"))
    assert any("Skany" in x and x.startswith("──") for x in items) and any("Watchlisty" in x and x.startswith("──") for x in items)
    assert app.launcher.ids[0] is None and app.launcher.current_id() is not None
    app.open_pinned()
    app.root.update()
    pw = app.pinned_win
    assert pw.rows and any(r["ticker"] == t for _, r in pw.rows.values())
    pw.tree.selection_set(next(iter(pw.rows)))
    pw.open_row()
    app.root.update()
    assert pw.host.chart is not None and pw.host.chart.focus_box
    assert not _clipped_buttons(pw) and not _clipped_buttons(app.launcher)
    app.open_manager()
    app.root.update()
    kids = app.manager.tree.get_children()
    assert any(k.startswith("grp:") for k in kids)


def test_pinned_box_chart_does_not_open_scanner_window(app):
    import shutil
    from desktop import scanners
    v = app.view
    app.root.update()
    rows = [r["ticker"] for r in v.store.rows[:2]]
    _, dates, _, _ = v.store.series(rows[0], v.store.tf)
    for t in rows:
        v.store.pin(t, {"top": 1e6, "bottom": 1e5, "start": dates[-10]})
    dup = scanners.duplicate(app.data_root, scanners.DEFAULT_ID, "Kopia")   # skaner z danymi i przypiętymi boxami, bez otwartego okna
    src, dst = scanners.scanner_dir(app.data_root, scanners.DEFAULT_ID), scanners.scanner_dir(app.data_root, dup["id"])
    for f in src.iterdir():
        if f.is_file() and f.name != "finviz_screen.json":
            shutil.copy(f, dst / f.name)
    app.open_pinned()
    app.root.update()
    pw = app.pinned_win
    assert len(pw.rows) >= 4
    iid = next(i for i, (sid, _r) in pw.rows.items() if sid == dup["id"])
    pw.tree.selection_set(iid)
    pw.open_row()                                   # pierwsze otwarcie: dwuklik / Enter
    app.root.update()
    assert dup["id"] not in app.windows and app.view_for(dup["id"]) is None   # okno skanera się nie otworzyło
    ch = pw.host.chart
    assert ch is not None and ch.winfo_exists() and ch.focus_box
    first = (pw.rows[iid][0], ch.ticker)
    # strzałki w oknie wykresu zmieniają zaznaczenie na liście i wykres (event_generate klawisza wymaga fokusu okna — na Windowsie CI go nie ma,
    # więc sprawdzamy, że skrót jest podpięty, i wołamy to, co wywołuje)
    assert ch.bind("<Down>") and ch.bind("<Up>")
    pw.host.step_chart(1)
    app.root.update()
    ids = list(pw.tree.get_children())
    cur = pw.current()
    assert cur != iid and cur in ids
    assert ch.ticker == pw.rows[cur][1]["ticker"] and pw.host.scanner["id"] == pw.rows[cur][0]
    assert (pw.rows[cur][0], ch.ticker) != first or len(ids) == 1
    # zmiana zaznaczenia na liście (strzałką na liście) też przełącza otwarty wykres
    pw.tree.selection_set(ids[0])
    app.root.update()
    assert ch.ticker == pw.rows[ids[0]][1]["ticker"]


def test_restored_scanner_windows_load_in_background(app):
    from desktop import scanners
    sc = scanners.upsert(app.data_root, {"name": "Ładowany", "kind": scanners.KIND_WATCHLIST, "sources": []})
    app.open_scanner_window(sc["id"], defer=True)
    w = app.windows[sc["id"]]
    assert w.view is None and w.loader is not None          # od razu okno z kółkiem „wczytuję”
    app.root.update()
    assert _wait(app, lambda: w.view is not None)
    assert w.loader is None and app.view_for(sc["id"]) is w.view


def test_chart_window_remembers_settings_across_tickers_and_windows(app):
    from desktop import session
    v = app.view
    app.root.update()
    t1, t2 = [r["ticker"] for r in v.store.rows[:2]]
    v.open_chart(t1)
    ch = v.chart
    ch.update()
    ch.tf.set("D")
    ch.change_tf()                      # przełączenie na dzienny
    ch.mode.set("bars")
    ch.on_mode()                        # widok słupkowy
    ch.log.set(False)
    ch.on_toggle()
    ch.zoom(0.7)                        # krótsze okno czasu
    n = ch.n_show
    # inna spółka (także z boxem) — ustawienia zostają, nie wracają do tygodniowego
    _, wd, _, _ = v.store.series(t2, "W")
    box = {"top": 100.0, "bottom": 80.0, "start": wd[-12], "i0": len(wd) - 12, "i1": -1, "outcome": "open", "dates": wd}
    v.open_chart(t2, focus=box)
    ch.update()
    assert ch.tf.get() == "D" and ch.ticker == t2 and ch.focus_box            # box policzony w tygodniach, wykres zostaje dzienny
    assert ch.focus_box["i0"] > 0 and "dates" not in ch.focus_box
    ch.clear_focus()
    assert ch.mode.get() == "bars" and ch.log.get() is False and ch.n_show == n
    v.open_chart(t1)                                                           # zwykłe przełączenie bez boxa
    assert ch.tf.get() == "D" and ch.mode.get() == "bars"
    # nowe okno wykresu (po zamknięciu) startuje z tych samych ustawień — zapisanych w sesji na dysku
    ch.destroy()
    v.chart = None
    sess = session.load(app.data_root)["chart"]
    assert sess["tf"] == "D" and sess["mode"] == "bars" and sess["log"] is False and sess["n"]["D"] == n
    v.open_chart(t2)
    c2 = v.chart
    assert c2.tf.get() == "D" and c2.mode.get() == "bars" and c2.log.get() is False and c2.n_show == n


def test_sync_window_log_has_elapsed_stamp(app):
    from desktop.widgets import SyncWindow
    w = SyncWindow(app, "x")
    w.log("pierwsza linia")
    app.root.update()
    text = w.text.get("1.0", "end")
    assert text.startswith("[0:0") and "pierwsza linia" in text
    w.destroy()


def test_poll_survives_errors_in_done_handler_and_finishes_sync_window(app, monkeypatch):
    from desktop import scanners
    from desktop.widgets import SyncWindow
    sc = scanners.upsert(app.data_root, {"name": "Awaria"}, "geo_usa", 20)
    app.open_scanner_window(sc["id"])
    app.root.update()
    view = app.view_for(sc["id"])
    win = SyncWindow(app, "x")
    app.syncing[sc["id"]] = win

    def boom(_view):
        raise RuntimeError("awaria odświeżania")
    monkeypatch.setattr(app, "after_sync", boom)
    app.q.put(("done", sc["id"], True))
    assert _wait(app, lambda: sc["id"] not in app.syncing)
    app.root.update()
    text = win.text.get("1.0", "end")
    assert "awaria odświeżania" in text and str(win.btn["state"]) == "normal"   # błąd widoczny w dzienniku, okno zakończone, przycisk Zamknij aktywny
    assert (app.data_root / "error.log").exists()
    # pętla odbioru żyje: kolejne komunikaty nadal są obsługiwane
    win2 = SyncWindow(app, "y")
    app.syncing["inny"] = win2
    app.q.put(("log", "inny", "linia po awarii"))
    assert _wait(app, lambda: "linia po awarii" in win2.text.get("1.0", "end"))
    assert view is not None


def test_darvas_boxes_tolerate_gaps_in_closes_and_store_loads_them(app):
    from desktop import darvas
    c = [10, 11, None, 13, 12, None, 11, 10.5, 11, None, 11.5, 11, 10, None, 9.5, 9]
    bx = darvas.boxes(c)                       # luki (None) w środku serii nie wywalają boxów ani stanu
    st = darvas.status(c)
    assert isinstance(bx, list) and st["state"] in ("WAIT", "HOLD", "OUT", "SELL", "NONE", "BUY", "NOVOL", "LATE")
    assert darvas.boxes([10, None, 12, None, None, None, None]) is not None
    # pełna ścieżka: spółka z lukami w danych tygodniowych i dziennych ładuje się do listy bez wyjątku
    v = app.view
    t = v.store.rows[0]["ticker"]
    full = v.store.stocks_full[t]
    full["c"] = [None if i % 7 == 3 else x for i, x in enumerate(full["c"])]
    d = v.store.charts_d.get("stocks", {}).get(t)
    if d:
        d["c"] = [None if i % 9 == 4 else x for i, x in enumerate(d["c"])]
    row = darvas.status(full["c"], full.get("v"))
    assert row["state"] is not None
    v.store.reload()


def test_watchlist_expression_filter_is_saved_and_applied(app, monkeypatch):
    from desktop import scanners
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *a, **k: None)
    wl = scanners.upsert(app.data_root, {"name": "Filtrowana", "kind": scanners.KIND_WATCHLIST, "sources": [{"id": scanners.DEFAULT_ID, "rule": {"type": "all"}}]})
    app.open_scanner_window(wl["id"])
    mv = app.view_for(wl["id"])
    from desktop import merge
    merge.build(app.data_root, scanners.get(app.data_root, wl["id"]), lambda *_: None)
    mv.reload()
    app.root.update()
    total = len(mv.store.rows)
    assert total > 5 and len(mv.table.visible()) == total
    prices = sorted(r["price"] for r in mv.store.rows if isinstance(r.get("price"), (int, float)))
    cut = prices[len(prices) // 2]
    mv.open_expr_filter()
    win = mv.expr_win
    app.root.update()
    win.text.insert("1.0", f"price >= {cut}\n")
    assert win.preview() and "pasuje" in win.status.cget("text")
    win.apply()
    app.root.update()
    shown = mv.table.visible()
    assert 0 < len(shown) < total and all(mv.store.row(t)["price"] >= cut for t in shown)
    assert scanners.get(app.data_root, wl["id"])["filter"].startswith("price >=")           # zapisany przy watchliście
    assert "filtr:" in mv.status.cget("text") and "●" in mv.expr_btn.cget("text")
    # błędny skrypt: lista nie znika, błąd widać w oknie i w pasku statusu
    win.text.delete("1.0", "end")
    win.text.insert("1.0", "price >=")
    assert not win.preview() and "oczekiwałem wartości" in win.status.cget("text")
    mv.set_expr_filter("nie_ma_kolumny > 1")
    assert len(mv.table.visible()) == total and "filtr" in mv.status.cget("text") and "nieznana kolumna" in mv.status.cget("text")
    win.clear()
    assert len(mv.table.visible()) == total and scanners.get(app.data_root, wl["id"])["filter"] == ""


def test_scan_window_expression_filter(app):
    from desktop import scanners
    app.open_scanner_window(scanners.DEFAULT_ID)
    sv = app.view_for(scanners.DEFAULT_ID)
    app.root.update()
    total = len(sv.table.visible())
    assert total > 5
    prices = sorted(r["price"] for r in sv.store.rows if isinstance(r.get("price"), (int, float)))
    cut = prices[len(prices) // 2]
    sv.set_expr_filter(f"price >= {cut}")
    app.root.update()
    assert 0 < len(sv.table.visible()) < total and "●" in sv.expr_btn.cget("text")
    assert scanners.get(app.data_root, scanners.DEFAULT_ID)["filter"].startswith("price >=")
    sv.set_expr_filter("")
    assert len(sv.table.visible()) == total


def test_measure_profit_while_dragging_disappears_on_release(app):
    v = app.view
    app.root.update()
    v.open_chart("NVDA")
    ch = v.chart
    ch.mode.set("bars")                                    # pomiar działa na wykresie słupkowym (karty nie mają osi czasu)
    ch.update()
    ch.redraw()
    ch.update()
    g = ch.geoms["bars"]
    ev = lambda x, y: type("E", (), {"x": x, "y": y})()   # noqa: E731
    xa, xb = g["xf"](g["i0"] + 10), g["xf"](g["i0"] + 18)
    ya, yb = g["p_top"] + 200, g["p_top"] + 100            # drugi punkt wyżej = zysk
    m = charts.measure(g, (xa, ya), (xb, yb))
    assert m["bars"] == 8 and m["pct"] > 0 and m["price1"] > m["price0"]
    assert charts.measure(g, (xb, yb), (xa, ya))["pct"] < 0
    cv = ch.cv_bars
    ch.meas_press(ev(xa, ya), cv)
    ch.meas_drag(ev(xb, yb), cv)
    ch.update()
    assert cv.find_withtag("measure") and "tyg." in " ".join(str(cv.itemcget(i, "text")) for i in cv.find_withtag("measure") if cv.type(i) == "text")
    ch.meas_release(ev(xb, yb), cv)
    assert not cv.find_withtag("measure") and ch.selected is None    # puszczenie kasuje pomiar, przeciągnięcie nie zaznacza boxa
    ch.mode.set("karta")
    ch.redraw()
    ch.update()
    x0, y0, x1, y1 = ch.geoms["card"]["hits"][-1]["rect"]
    c = ev((x0 + x1) / 2, (y0 + y1) / 2)
    ch.meas_press(c, ch.cv_card)
    ch.meas_release(c, ch.cv_card)                           # zwykłe kliknięcie na karcie zaznacza box
    assert ch.selected is not None


def test_krok_po_kroku_steps_and_watchlist_from_selection(app, monkeypatch):
    import json

    from desktop import overview, scanners
    weeks = [f"2024-{m:02d}-{d:02d}" for m in range(1, 13) for d in (1, 15)] * 5   # 120 tygodni (daty tylko do podpisów)
    up = [100 * 1.01 ** i for i in range(120)]
    items = {t: up for t, _ in overview.INDEXES} | {t: [v * (1 + k * 0.001 * i) for i, v in enumerate(up)] for k, (t, _, _) in enumerate(overview.SECTOR_ETFS)}
    (app.data_root / overview.FILE).write_text(json.dumps({"fetched": "2999-01-01T00:00:00Z", "weeks": weeks, "items": items}))
    rows = [{"ticker": f"T{i}", "company": f"Spółka {i}", "sector": "Energy", "industry": "Oil"} for i in range(6)]
    closes = {f"T{i}": [v * (1 + i * 0.002 * j) for j, v in enumerate(up)] for i in range(6)}
    u = {"fetched": "2999-01-01T00:00:00Z", "key": overview.universe_key(["Energy"], ""), "sectors": ["Energy"], "extra": "", "weeks": weeks,
         "etf": {"XLE": up, "^GSPC": up}, "rows": rows, "closes": closes}
    (app.data_root / overview.UNIVERSE_FILE).write_text(json.dumps(u))
    app.open_krok()
    k = app.krok_win
    k.update()
    assert k.step_var.get() == "rynek"
    k.go(1)
    k.update()
    assert k.step_var.get() == "sektory" and k.sectors                    # domyślnie zaznaczone sektory z dodatnim RS
    k.sectors = ["Energy"]
    k.app.session.setdefault("krok", {})["extra"] = ""
    k.go(1)
    k.update()
    ids = list(k.tree.get_children())
    assert ids[0] == "T5"                                                 # najsilniejsza względem ETF sektora na górze
    mrs = [r["mrs"] for r in k.rows["rows"] if r["mrs"] is not None]
    assert mrs == sorted(mrs, reverse=True)
    ev = lambda iid: type("E", (), {"y": k.tree.bbox(iid)[1] + 3})()   # noqa: E731
    k.tree.see(ids[0])
    k.update()
    k.toggle(ev(ids[0]))
    k.toggle(ev(ids[1]))
    k.toggle(ev(ids[1]))                                                  # drugie kliknięcie odznacza
    assert k.rows["checked"] == {ids[0]} and k.tree.item(ids[0], "text").startswith("☑")
    monkeypatch.setattr(app, "scanner_saved", lambda sc, then_sync=None: None)
    saved = k.make_watchlist([k.rows["by"][ids[0]]], name="Test krok")
    cfg = scanners.load_config(scanners.scanner_dir(app.data_root, saved["id"]))
    assert saved["kind"] == scanners.KIND_FINVIZ and [r["ticker"] for r in cfg["tickers"]] == [ids[0]] and "glb" in cfg
