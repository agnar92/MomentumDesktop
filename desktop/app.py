"""Okna aplikacji Momentum Desktop — prosty, „retro” interfejs w stylu TC2000: główne okno (skaner domyślny), własne skanery w osobnych oknach,
wykresy, boxy, kreator skanerów Finviz, synchronizacja."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import alerts as alerts_mod
from . import changes, exporter, finviz_codes, scanners, session, store, sync
from . import columns as columns_mod
from . import flags as flags_mod
from .builder import ScannerEditor, ScannerManager
from .chartwin import ChartWindow
from .launcher import LauncherWindow
from .dialogs import (AlertsWindow, BoxesWindow, CanslimWindow, ColumnsWindow, FilterWindow, FinvizCriteriaWindow, ListNamesWindow, SymbolDialog,
                      WhatsNewWindow)
from .grid import GridWindow
from .theme import BG, FG, PANEL, MenuBar, apply_dark, setup_style
from .widgets import StockTable, SyncWindow


class ScannerView(tk.Frame):
    """Lista jednego skanera (własne dane, kolumny, skala, filtr lokalny, wykres) — w głównym oknie albo w osobnym oknie skanera."""

    def __init__(self, master, app, scanner, root_window):
        super().__init__(master, bg=PANEL)
        self.app, self.scanner, self.root = app, scanner, root_window
        default = scanner["id"] == scanners.DEFAULT_ID
        self.store = store.Store(scanners.scanner_dir(app.data_root, scanner["id"]), seed=default)
        self.chart = self.filter_win = self.boxes = self.grid = None
        self.main_filter = {}
        tb = tk.Frame(self, bg=PANEL)
        tb.pack(fill="x")
        self.prices_btn = tk.Button(tb, text="⟳ Ceny (F5)" if default else "⟳ Ceny", command=lambda: self.start_sync(sync.PRICES), width=12, relief="flat")
        self.prices_btn.pack(side="left", padx=(6, 2), pady=5)
        self.fund_btn = tk.Button(tb, text="⟳ Fundamenty", command=lambda: self.start_sync(sync.FUNDAMENTALS), width=13, relief="flat")
        self.fund_btn.pack(side="left", padx=2)
        tk.Button(tb, text="Filtr…", command=self.open_filter, relief="flat").pack(side="left", padx=(12, 2))
        tk.Button(tb, text="Boxy…", command=self.open_boxes, relief="flat").pack(side="left", padx=2)
        self.news_btn = tk.Button(tb, text="Co nowego", command=self.open_changes, relief="flat")
        self.news_btn.pack(side="left", padx=2)
        mb = tk.Menubutton(tb, text="Narzędzia ▾", relief="flat", bg=PANEL, fg=FG, activebackground="#2d3744", padx=8)
        tools = tk.Menu(mb, tearoff=0)
        for item in (("Szukaj dowolnego symbolu…  (Ctrl+K lub /)", self.open_symbol_dialog), ("Siatka wykresów…", self.open_grid), ("Alerty cenowe…", self.app.open_alerts), None,
                     ("Kolumny…", self.choose_columns), ("Kryteria Finviz (co synchronizujemy)", self.open_criteria), ("✎ Edytuj skaner…", self.edit_scanner), None,
                     ("Kopiuj tickery (przecinki — np. do TradingView)", lambda: self.copy_tickers(",")), ("Kopiuj tickery (po jednym w linii)", lambda: self.copy_tickers("\n")),
                     ("Zapisz tickery do pliku .txt…", self.save_tickers), ("Zapisz CSV — Excel PL (średnik)…", lambda: self.save_csv("xl")),
                     ("Zapisz CSV — standardowy…", lambda: self.save_csv("std")), None, ("Nazwy list (flagi 1–4)…", self.app.edit_list_names)):
            if item is None:
                tools.add_separator()
            else:
                tools.add_command(label=item[0], command=item[1])
        mb.config(menu=tools)
        mb.pack(side="left", padx=2)
        self.tf = tk.StringVar(value=self.store.tf)
        tk.Label(tb, text="Skala:", bg=PANEL).pack(side="left", padx=(12, 2))
        for text, val in (("Tydzień", "W"), ("Dzień", "D")):
            tk.Radiobutton(tb, text=text, value=val, variable=self.tf, command=lambda: self.set_tf(self.tf.get()), bg=PANEL,
                           indicatoron=False, padx=9, relief="flat").pack(side="left", padx=1)
        tk.Label(tb, text="Lista:", bg=PANEL).pack(side="left", padx=(12, 2))
        self.flag_filter = tk.StringVar(value="Wszystkie")
        self.flag_box = ttk.Combobox(tb, textvariable=self.flag_filter, state="readonly", width=15)
        self.flag_box.pack(side="left")
        self.flag_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_lists())
        tk.Label(tb, text="Szukaj:", bg=PANEL).pack(side="left", padx=(12, 2))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh_lists())
        tk.Entry(tb, textvariable=self.search, width=12, relief="flat").pack(side="left")
        self.filter_lbl = tk.Label(tb, text="", bg=PANEL, fg="#ffd166")
        self.filter_lbl.pack(side="left", padx=8)
        self.age_lbl = tk.Label(tb, text="", bg=PANEL, anchor="e")
        self.age_lbl.pack(side="right", padx=8)
        self.table = StockTable(self, self.open_chart, self.open_chart_new, self.open_canslim, columns=self.columns(), flags=app.flags, on_flag=self.set_flag)
        self.status = tk.Label(self, text="", anchor="w", bg=PANEL)
        self.status.pack(fill="x", side="bottom")
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Up>", lambda e: self.root.after_idle(self._link))
        self.table.tree.bind("<Down>", lambda e: self.root.after_idle(self._link))
        self.table.on_select = lambda t: self.grid is not None and self.grid.winfo_exists() and self.grid.refresh()   # siatka podąża za zaznaczeniem
        self.table.tree.bind("<slash>", lambda e: self.open_symbol_dialog())
        self.root.bind("<Control-k>", lambda e: self.open_symbol_dialog())
        self.set_title()
        self.app.flags.tag(self.store.rows)
        self.refresh_lists()

    # --- kolumny
    def columns(self):
        cols = self.scanner.get("columns") or columns_mod.DEFAULT_COLUMNS
        return cols if "ticker" in cols else ["ticker"] + list(cols)

    def set_columns(self, cols):
        self.scanner["columns"] = list(cols)
        scanners.upsert(self.app.data_root, self.scanner)
        self.table.set_columns(self.columns())
        self.table.set_tf_label(self.store.tf)

    def choose_columns(self):
        ColumnsWindow(self)

    def set_title(self):
        self.root.title(f"Momentum Desktop — {self.scanner['name']}")

    # --- skala czasu
    def set_tf(self, tf):
        self.store.set_tf(tf)
        self.tf.set(self.store.tf)
        if tf == "D" and self.store.tf != "D":
            messagebox.showinfo("Skala dzienna", "Brak danych dziennych — zrób Sync cen.", parent=self.root)
        self.refresh_lists()

    # --- lista
    FLAG_CHOICES = {"Wszystkie": "", "Dowolna lista": "any", "Bez listy": "none"}

    def _flag_code(self):
        name = self.flag_filter.get()
        if name in self.FLAG_CHOICES:
            return self.FLAG_CHOICES[name]
        return next((lst["id"] for lst in self.app.flags.lists if f"{lst['icon']} {lst['name']}" == name), "")

    def _rows(self):
        self.flag_box.config(values=list(self.FLAG_CHOICES) + [f"{lst['icon']} {lst['name']}" for lst in self.app.flags.lists])
        return store.scan(self.store.rows, {**self.main_filter, "text": self.search.get(), "flag": self._flag_code()})

    def set_flag(self, ticker, lid):
        if ticker:
            self.app.flags.set(ticker, lid)
            self.app.refresh_flag_views()

    def refresh_lists(self):
        rows = self._rows()
        self.table.set_rows(rows)
        self.table.set_tf_label(self.store.tf)
        wl = self.store.watchlist
        mk = self.store.mkt or {}
        regime = {"uptrend": "✅ trend wzrostowy", "correction": "🛑 korekta"}.get(mk.get("regime"), "—")
        self.status.config(text=f"  Dane z sesji: {wl.get('data_as_of', 'brak — kliknij Sync')}   Spółek: {len(rows)}/{len(self.store.rows)}   Rynek (M): {regime}"
                                f"   Finviz: {'(stare dane!)' if wl.get('finviz_stale') else 'ok'}   Katalog: {self.store.dir}")
        self.filter_lbl.config(text="⚑ filtr aktywny" if any(v for v in self.main_filter.values()) else "")
        n = changes.total(self.store.changes["diff"])
        self.news_btn.config(text=f"Co nowego ({n})" if n else "Co nowego", fg="#ffd166" if n else FG)
        self.update_age()
        if self.filter_win and self.filter_win.winfo_exists():
            self.filter_win.run()
            self.filter_win.table.set_tf_label(self.store.tf)
        if self.boxes and self.boxes.winfo_exists():
            self.boxes.refresh()

    def update_age(self):
        """Wiek ostatnich synchronizacji: fundamenty starsze niż tydzień podświetlamy na pomarańczowo."""
        st = sync.read_state(self.store.dir)

        def fmt(iso):
            d = sync.age_days(iso)
            return "brak" if d is None else "dziś" if d < 1 else f"{int(d)} d temu"

        fd = sync.age_days(st.get("fundamentals"))
        stale = fd is None or fd > sync.FUNDAMENTALS_STALE_DAYS
        self.age_lbl.config(text=f"Ceny: {fmt(st.get('prices'))}   Fundamenty: {fmt(st.get('fundamentals'))}{'  ⚠ czas na Sync fundamentów' if stale else ''}",
                            fg="#ff9f43" if stale else FG)

    def apply_main_filter(self, f):
        self.main_filter = {k: v for k, v in f.items() if v not in (None, "", [], False)}
        self.refresh_lists()

    def reload(self):
        self.store.reload()
        self.store.set_tf(self.store.tf)
        self.app.flags.tag(self.store.rows)
        self.table.set_columns(self.columns())
        self.refresh_lists()
        if self.filter_win and self.filter_win.winfo_exists():
            self.filter_win.refresh()

    def set_sync_enabled(self, on):
        for b in (self.prices_btn, self.fund_btn):
            b.config(state="normal" if on else "disabled")

    # --- okna
    def open_chart(self, ticker, focus=None):
        if not ticker:
            return
        if self.chart is None or not self.chart.winfo_exists():
            self.chart = ChartWindow(self, ticker)
            if focus:
                self.chart.set_focus(focus)
                self.chart.redraw()
        else:
            self.chart.set_ticker(ticker, focus, self.store.tf if focus else None)
            self.chart.lift()

    def open_chart_new(self, ticker):
        if ticker:
            ChartWindow(self, ticker)

    def open_canslim(self, ticker):
        if ticker and self.store.row(ticker):
            CanslimWindow(self, ticker)

    def open_criteria(self):
        FinvizCriteriaWindow(self)

    def step_chart(self, delta):
        t = self.table.step(delta)
        if t:
            self.open_chart(t)

    def _link(self):
        if self.chart is not None and self.chart.winfo_exists() and self.table.current():
            self.chart.set_ticker(self.table.current())
        if self.grid is not None and self.grid.winfo_exists():
            self.grid.refresh()

    def open_grid(self):
        if self.grid is None or not self.grid.winfo_exists():
            self.grid = GridWindow(self)
        self.grid.lift()
        self.grid.refresh()

    def open_symbol_dialog(self):
        SymbolDialog(self)

    def open_symbol(self, symbol):
        """Otwiera wykres symbolu spoza skanera (pobiera go, jeśli trzeba)."""
        d = SymbolDialog(self)
        d.var.set(symbol)
        d.go()

    def open_filter(self):
        if self.filter_win is None or not self.filter_win.winfo_exists():
            self.filter_win = FilterWindow(self)
        self.filter_win.lift()

    def open_boxes(self):
        if self.boxes is None or not self.boxes.winfo_exists():
            self.boxes = BoxesWindow(self)
        self.boxes.lift()

    # --- co nowego, eksport
    def open_changes(self):
        WhatsNewWindow(self)

    def clear_changes(self):
        self.store.set_changes({}, self.store.changes.get("at"))
        self.refresh_lists()

    def copy_tickers(self, sep):
        text = exporter.tickers_text(self._shown_rows(), sep)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.config(text=f"  Skopiowano {len(self._shown_rows())} tickerów do schowka.")

    def _shown_rows(self):
        """Wiersze w kolejności, w jakiej widać je na liście (po filtrach i sortowaniu)."""
        by = {r["ticker"]: r for r in self.table.rows}
        return [by[t] for t in self.table.visible() if t in by]

    def save_tickers(self):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".txt", initialfile=f"{self.scanner['id']}-tickery.txt", filetypes=[("Tekst", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(exporter.tickers_text(self._shown_rows(), ","))

    def save_csv(self, fmt):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".csv", initialfile=f"{self.scanner['id']}.csv", filetypes=[("CSV", "*.csv")])
        if path:
            flag_labels = {lst["id"]: f"{lst['icon']} {lst['name']}" for lst in self.app.flags.lists}
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(exporter.to_csv(self._shown_rows(), self.table.columns, fmt, store.STATE_LABELS, flag_labels))

    def edit_scanner(self):
        self.app.edit_scanner(self.scanner["id"])

    def start_sync(self, mode=sync.PRICES, skip_finviz=False):
        self.app.start_sync(self, mode, skip_finviz)


class ScannerListWindow(tk.Toplevel):
    """Osobne okno własnego skanera."""

    def __init__(self, app, scanner):
        super().__init__(app.root)
        self.geometry("1360x720")
        self.configure(bg=BG)
        apply_dark(self)
        self.view = ScannerView(self, app, scanner, self)
        self.view.pack(fill="both", expand=True)
        self.bind("<F5>", lambda e: self.view.start_sync(sync.PRICES))
        self.bind("<Shift-F5>", lambda e: self.view.start_sync(sync.FUNDAMENTALS))
        self.protocol("WM_DELETE_WINDOW", lambda: app.window_closed(scanner["id"]))


class App:
    def __init__(self, data_base=None):
        self.root = tk.Tk()
        self.root.geometry("1420x760")
        setup_style(self.root)
        apply_dark(self.root)
        self.data_root = store.data_dir(data_base)
        self.windows = {}   # id skanera -> ScannerListWindow
        self.flags = flags_mod.Flags(self.data_root)
        self.alerts = alerts_mod.Alerts(self.data_root)
        self.alerts_win = None
        self.q = queue.Queue()
        self.syncing = {}   # id skanera -> okno dziennika; synchronizacje różnych skanerów mogą trwać równolegle
        self.session = session.prune(session.load(self.data_root), [s["id"] for s in scanners.load(self.data_root)])
        self.launcher = None
        self.root.protocol("WM_DELETE_WINDOW", self.close_main)
        self.main_hidden = False
        self.menubar = MenuBar(self.root, self._menu_spec())
        self.menubar.pack(fill="x")
        self.view = ScannerView(self.root, self, scanners.get(self.data_root, scanners.DEFAULT_ID), self.root)
        self.view.pack(fill="both", expand=True)
        self.manager = None
        self.root.bind("<F5>", lambda e: self.view.start_sync(sync.PRICES))
        self.root.bind("<Shift-F5>", lambda e: self.view.start_sync(sync.FUNDAMENTALS))
        self.root.after(150, self._poll)
        self.restore_session()

    # skróty do widoku głównego (domyślny skaner)
    @property
    def store(self):
        return self.view.store

    @property
    def table(self):
        return self.view.table

    def _menu_spec(self):
        v = lambda: self.view   # noqa: E731
        return [
            ("Plik", [("Sync cen (Finviz + yfinance, szybko)\tF5", lambda: v().start_sync(sync.PRICES)),
                      ("Sync fundamentów (EPS, estymaty — raz w tygodniu)\tShift+F5", lambda: v().start_sync(sync.FUNDAMENTALS)),
                      ("Ceny tylko z yfinance (bez Finviz)", lambda: v().start_sync(sync.PRICES, skip_finviz=True)),
                      ("Wczytaj dane z dysku", lambda: v().reload()), None, ("Zakończ", self.quit_app)]),
            ("Skanery", [("Szybkie okno skanerów", self.open_launcher), ("Moje skanery…", self.open_manager), ("Nowy skaner Finviz…", self.new_scanner),
                         ("Edytuj skaner domyślny…", lambda: self.edit_scanner(scanners.DEFAULT_ID))]),
            ("Widok", [("Filtr listy…", lambda: v().open_filter()), ("Boxy Darvasa…", lambda: v().open_boxes()), ("Kolumny…", lambda: v().choose_columns()),
                       ("Kryteria Finviz (co synchronizujemy)…", lambda: v().open_criteria()),
                       ("Wyczyść filtr listy", lambda: v().apply_main_filter({}))]),
            ("Okno", [("Wykres wybranej spółki", lambda: v().open_chart(v().table.current())),
                      ("Wykres w nowym oknie", lambda: v().open_chart_new(v().table.current())),
                      ("CANSLIM wybranej spółki…", lambda: v().open_canslim(v().table.current()))]),
            ("Pomoc", [("O programie", lambda: messagebox.showinfo(
                "Momentum Desktop", "Własne skanery Finviz + ceny z yfinance, wykresy Dar-Card i słupkowy (tygodniowe i dzienne), CANSLIM.\n"
                "Logika jak w Momentum. Tylko informacyjnie — nie jest to porada inwestycyjna.\n\nDane: " + str(self.data_root)))]),
        ]

    def all_views(self):
        return [self.view] + [w.view for w in self.windows.values() if w.winfo_exists()]

    def refresh_flag_views(self):
        """Flagi są wspólne dla wszystkich skanerów: po zmianie odświeżamy wszystkie listy."""
        for v in self.all_views():
            self.flags.tag(v.store.rows)
            v.refresh_lists()

    def open_alerts(self):
        if self.alerts_win is None or not self.alerts_win.winfo_exists():
            self.alerts_win = AlertsWindow(self)
        self.alerts_win.refresh()
        self.alerts_win.lift()

    def refresh_alert_views(self):
        """Po zmianie alertów: odśwież okno alertów, wykresy i siatki."""
        if self.alerts_win is not None and self.alerts_win.winfo_exists():
            self.alerts_win.refresh()
        for v in self.all_views():
            for w in (v.chart, v.grid):
                if w is not None and w.winfo_exists():
                    w.redraw() if w is v.chart else w.refresh()

    def remember_symbol(self, sym):
        self.session["symbols"] = [sym] + [s for s in self.session.get("symbols", []) if s != sym][:14]
        self.save_session()

    def edit_list_names(self):
        ListNamesWindow(self)

    # --- skanery
    def view_for(self, sid):
        if sid == scanners.DEFAULT_ID:
            return self.view
        w = self.windows.get(sid)
        return w.view if w is not None and w.winfo_exists() else None

    def open_manager(self):
        if self.manager is None or not self.manager.winfo_exists():
            self.manager = ScannerManager(self)
        self.manager.refresh()
        self.manager.lift()

    def new_scanner(self):
        ScannerEditor(self)

    def edit_scanner(self, sid):
        sc = scanners.get(self.data_root, sid)
        if sc:
            ScannerEditor(self, sc)

    def open_scanner_window(self, sid):
        session.touch(self.session, sid)
        if sid == scanners.DEFAULT_ID:
            self.show_main()
        else:
            w = self.windows.get(sid)
            if w is not None and w.winfo_exists():
                w.lift()
            else:
                sc = scanners.get(self.data_root, sid)
                if sc:
                    self.windows[sid] = ScannerListWindow(self, sc)
        self.save_session()
        self.refresh_launcher()

    def window_closed(self, sid):
        w = self.windows.pop(sid, None)
        if w is not None and w.winfo_exists():
            w.destroy()
        if self.main_hidden and not self.other_windows():   # nic nie zostało na ekranie: zostawiamy małe okno jako punkt wejścia
            self.open_launcher()
        self.save_session()
        self.refresh_launcher()

    def other_windows(self, ignore_launcher=False):
        """Okna widoczne poza głównym (skanery, wykresy, małe okno, dialogi)."""
        return [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_exists() and w.state() != "withdrawn"
                and not (ignore_launcher and w is self.launcher)]

    def close_main(self):
        """Zamknięcie głównego okna (skaner domyślny) nie kończy programu, dopóki są inne okna: chowamy je, a wrócić można z małego okna skanerów."""
        if self.other_windows():
            self.root.withdraw()
            self.main_hidden = True
            self.open_launcher()
            self.save_session()
        else:
            self.quit_app()

    def show_main(self):
        self.main_hidden = False
        self.root.deiconify()
        self.root.lift()
        self.save_session()

    # --- szybkie okno i pamięć sesji
    def open_launcher(self):
        if self.launcher is None or not self.launcher.winfo_exists():
            self.launcher = LauncherWindow(self)
            self.launcher.protocol("WM_DELETE_WINDOW", self._close_launcher)
        self.launcher.refresh()
        self.launcher.lift()
        self.save_session()

    def _close_launcher(self):
        self.launcher.destroy()
        if self.main_hidden and not self.other_windows():   # to było ostatnie okno — kończymy program
            self.quit_app()
            return
        self.save_session()

    def refresh_launcher(self):
        if self.launcher is not None and self.launcher.winfo_exists():
            self.launcher.refresh()

    def save_session(self):
        self.session["open"] = [sid for sid, w in self.windows.items() if w.winfo_exists()]
        self.session["launcher"] = self.launcher is not None and self.launcher.winfo_exists()
        self.session["main_hidden"] = self.main_hidden
        session.save(self.data_root, self.session)

    def restore_session(self):
        """Po starcie otwiera skanery, które były otwarte przy ostatnim zamknięciu, i małe okno szybkiego startu.
        Stan odczytujemy z góry: otwieranie okien zapisuje sesję i nadpisałoby flagę szybkiego okna."""
        to_open, want_launcher, hidden = list(self.session["open"]), self.session["launcher"], self.session["main_hidden"]
        if hidden:   # główne okno było schowane — chowamy je i dajemy małe okno jako punkt wejścia
            self.root.withdraw()
            self.main_hidden, want_launcher = True, True
        for sid in to_open:
            if sid != scanners.DEFAULT_ID and scanners.get(self.data_root, sid):
                self.open_scanner_window(sid)
        if want_launcher:
            self.open_launcher()

    def quit_app(self):
        self.save_session()
        self.root.destroy()

    def scanner_saved(self, sc, then_sync=None):
        """Po zapisie w edytorze: odśwież widoki; nowy skaner od razu otwieramy w oknie; opcjonalnie od razu Sync."""
        view = self.view_for(sc["id"])
        if view is not None:
            view.scanner.update(sc)
            view.set_title()
            view.table.set_columns(view.columns())
        elif sc["id"] != scanners.DEFAULT_ID:
            self.open_scanner_window(sc["id"])
            view = self.view_for(sc["id"])
        if self.manager is not None and self.manager.winfo_exists():
            self.manager.refresh()
        self.refresh_launcher()
        if then_sync and view is not None:
            self.start_sync(view, then_sync)

    def delete_scanner(self, sid):
        w = self.windows.pop(sid, None)
        if w is not None and w.winfo_exists():
            w.destroy()
        scanners.delete(self.data_root, sid)
        session.prune(self.session, [s["id"] for s in scanners.load(self.data_root)])
        self.save_session()
        self.refresh_launcher()

    # --- synchronizacja: każdy skaner w osobnym procesie, więc kilka może trwać równolegle
    def start_sync(self, view, mode=sync.PRICES, skip_finviz=False):
        sid = view.scanner["id"]
        if sid in self.syncing:
            messagebox.showinfo("Synchronizacja", "Ten skaner już się synchronizuje — poczekaj, aż skończy (inne skanery możesz synchronizować równolegle).", parent=view.root)
            return
        upgraded = mode == sync.PRICES and sid != scanners.DEFAULT_ID and not (view.store.dir / "sync_state.json").exists()
        if upgraded:   # nowy skaner nie ma jeszcze EPS ani estymat — pierwszy Sync musi pobrać fundamenty
            mode = sync.FUNDAMENTALS
        view.set_sync_enabled(False)
        fund = mode == sync.FUNDAMENTALS
        name = view.scanner["name"]
        win = SyncWindow(self, f"Synchronizacja {'fundamentów' if fund else 'cen'} — {name}")
        self.syncing[sid] = win
        win.log(f"Skaner: {name}")
        if upgraded:
            win.log("To pierwsza synchronizacja tego skanera — pobieram też fundamenty (EPS, estymaty), żeby CANSLIM i oceny miały dane.")
        if not skip_finviz:   # co dokładnie pobieramy z Finviz
            cfg = view.store.finviz_config()
            for line in finviz_codes.summary_lines(cfg.get("filters"), cfg.get("max_tickers")):
                win.log(line)
            if view.scanner.get("extra"):
                win.log(f"  + dodatkowe kolumny z Finviz: {', '.join(view.scanner['extra'])}")
        win.log("Start: Finviz → yfinance → EPS i estymaty analityków → obliczenia (kilka–kilkanaście minut)…" if fund
                else "Start: " + ("yfinance" if skip_finviz else "Finviz → yfinance") + " → obliczenia na zapisanych fundamentach (ok. minuty)…")
        data_dir, extra = view.store.dir, list(view.scanner.get("extra") or [])
        shared = None if sid == scanners.DEFAULT_ID else self.data_root

        def work():
            code = sync.run_in_subprocess(data_dir, lambda s: self.q.put(("log", sid, s)), mode=mode, skip_finviz=skip_finviz,
                                          extra_keys=extra, shared_root=shared)
            self.q.put(("done", sid, code == 0))

        threading.Thread(target=work, daemon=True).start()
        self.refresh_launcher()

    def _poll(self):
        try:
            while True:
                kind, sid, val = self.q.get_nowait()
                win = self.syncing.get(sid)
                if kind == "log":
                    if win is not None and win.winfo_exists():
                        win.log(val)
                elif kind == "done":
                    self.syncing.pop(sid, None)
                    view = self.view_for(sid)
                    if view is not None:
                        view.set_sync_enabled(True)
                        if val:
                            self.after_sync(view)
                    if self.manager is not None and self.manager.winfo_exists():
                        self.manager.refresh()
                    if win is not None and win.winfo_exists():
                        win.done(val)
                    self.refresh_launcher()
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def after_sync(self, view):
        """Przeładowuje dane skanera i porównuje listę z poprzednią (co nowego); okno zmian otwiera się samo, gdy coś się zmieniło."""
        old = changes.snapshot(view.store.rows)
        view.reload()
        new = changes.snapshot(view.store.rows)
        fresh = changes.diff(old, new)
        hit = self.alerts.evaluate(lambda t: self._daily_or_weekly(view, t), tickers={r["ticker"] for r in view.store.rows})   # alerty cenowe przebite od ostatnich danych
        if hit:
            fresh["alert"] = sorted({a["ticker"] for a in hit})
        d = changes.merge(view.store.changes["diff"], fresh) if (old or hit) else view.store.changes["diff"]
        names = {t: old[t].get("name") for t in d.get("dropped", []) if t in old}
        names = {**view.store.changes.get("names", {}), **names}
        view.store.set_changes(d, sync.now_iso(), names)
        view.refresh_lists()
        if changes.total(fresh):
            view.open_changes()
        self.refresh_alert_views()

    @staticmethod
    def _daily_or_weekly(view, ticker):
        """(daty, High, Low, zamknięcia) do sprawdzania alertów: dzienne świece, a bez nich tygodniowe."""
        for tf in ("D", "W"):
            full, dates, _spx, _ = view.store.series(ticker, tf)
            if full and full.get("c"):
                return dates, full["h"], full["l"], full["c"]
        return None

    def run(self):
        self.root.mainloop()


def main():
    App().run()
