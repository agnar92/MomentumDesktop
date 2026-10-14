"""Okna aplikacji Momentum Desktop — prosty, „retro” interfejs w stylu TC2000: główne okno (skaner domyślny), własne skanery w osobnych oknach,
wykresy, boxy, kreator skanerów Finviz, synchronizacja."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import changes, exporter, finviz_codes, merge, scanners, session, store, sync
from . import columns as columns_mod
from . import flags as flags_mod
from .builder import ScannerEditor, ScannerManager, WatchlistEditor
from .chartwin import ChartWindow
from .launcher import LauncherWindow
from .dialogs import (BoxesWindow, CanslimWindow, ColumnsWindow, FilterWindow, FinvizCriteriaWindow, ListNamesWindow, PinnedWindow, SymbolDialog,
                      WhatsNewWindow)
from .theme import BG, FG, PANEL, Flow, MenuBar, apply_dark, autowrap, fit_window, setup_style
from .widgets import LoadingFrame, StockTable, SyncWindow


class ScannerView(tk.Frame):
    """Lista jednego skanera (własne dane, kolumny, skala, filtr lokalny, wykres) — w głównym oknie albo w osobnym oknie skanera."""

    def __init__(self, master, app, scanner, root_window, loaded=None):
        super().__init__(master, bg=PANEL)
        self.app, self.scanner, self.root = app, scanner, root_window
        default = scanner["id"] == scanners.DEFAULT_ID
        self.store = loaded or store.Store(scanners.scanner_dir(app.data_root, scanner["id"]), seed=default)
        self.chart = self.filter_win = self.boxes = None
        self.main_filter = {}
        self.kind = scanner.get("kind") or scanners.KIND_FINVIZ
        tb = Flow(self)   # pasek zawija się do kolejnych wierszy zamiast ucinać przyciski
        tb.pack(fill="x")
        self.prices_btn = tk.Button(tb, text="⟳ Ceny (F5)" if default else "⟳ Ceny", command=lambda: self.start_sync(sync.PRICES), width=12, relief="flat")
        tb.add(self.prices_btn)
        self.fund_btn = tk.Button(tb, text="⟳ Fundamenty", command=lambda: self.start_sync(sync.FUNDAMENTALS), width=13, relief="flat")
        if self.kind == scanners.KIND_FINVIZ:
            tb.add(self.fund_btn)
        else:
            self.prices_btn.config(text="⟳ Ceny", width=12)
        tb.add(tk.Button(tb, text="Filtr…", command=self.open_filter, relief="flat"))
        tb.add(tk.Button(tb, text="Boxy…", command=self.open_boxes, relief="flat"))
        self.news_btn = tk.Button(tb, text="Co nowego", command=self.open_changes, relief="flat")
        tb.add(self.news_btn)
        mb = tk.Menubutton(tb, text="Narzędzia ▾", relief="flat", bg=PANEL, fg=FG, activebackground="#2d3744", padx=8)
        tools = tk.Menu(mb, tearoff=0)
        for item in (("Szukaj dowolnego symbolu…  (Ctrl+K lub /)", self.open_symbol_dialog), None,
                     ("Kolumny…", self.choose_columns), ("Kryteria Finviz (co synchronizujemy)", self.open_criteria), ("✎ Edytuj skaner…", self.edit_scanner), None,
                     ("Kopiuj tickery (przecinki — np. do TradingView)", lambda: self.copy_tickers(",")), ("Kopiuj tickery (po jednym w linii)", lambda: self.copy_tickers("\n")),
                     ("Zapisz tickery do pliku .txt…", self.save_tickers), ("Zapisz CSV — Excel PL (średnik)…", lambda: self.save_csv("xl")),
                     ("Zapisz CSV — standardowy…", lambda: self.save_csv("std")), None, ("Nazwy list (flagi 1–4)…", self.app.edit_list_names)):
            if item is None:
                tools.add_separator()
            else:
                tools.add_command(label=item[0], command=item[1])
        mb.config(menu=tools)
        tb.add(mb)
        self.tf = tk.StringVar(value=self.store.tf)
        tb.add(tk.Label(tb, text="Skala:", bg=PANEL))
        for text, val in (("Tydzień", "W"), ("Dzień", "D")):
            tb.add(tk.Radiobutton(tb, text=text, value=val, variable=self.tf, command=lambda: self.set_tf(self.tf.get()), bg=PANEL,
                                  indicatoron=False, padx=9, relief="flat"))
        tb.add(tk.Label(tb, text="Lista:", bg=PANEL))
        self.flag_filter = tk.StringVar(value="Wszystkie")
        self.flag_box = ttk.Combobox(tb, textvariable=self.flag_filter, state="readonly", width=15)
        tb.add(self.flag_box)
        self.flag_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_lists())
        tb.add(tk.Label(tb, text="Szukaj:", bg=PANEL))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh_lists())
        tb.add(tk.Entry(tb, textvariable=self.search, width=12, relief="flat"))
        self.filter_lbl = tk.Label(tb, text="", bg=PANEL, fg="#ffd166")
        tb.add(self.filter_lbl)
        self.age_lbl = tk.Label(tb, text="", bg=PANEL, anchor="e")
        tb.add(self.age_lbl)
        self.table = StockTable(self, self.open_chart, self.open_chart_new, self.open_canslim, columns=self.columns(), flags=app.flags, on_flag=self.set_flag)
        self.status = autowrap(tk.Label(self, text="", bg=PANEL), pad=8)
        self.status.pack(fill="x", side="bottom")
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Up>", lambda e: self.root.after_idle(self._link))
        self.table.tree.bind("<Down>", lambda e: self.root.after_idle(self._link))
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
            self.chart.set_ticker(ticker, focus)
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


class ChartHost:
    """Lekki „widok” dla wykresu otwieranego spoza okna skanera (okno przypiętych boxów): ma dane skanera z dysku, ale NIE otwiera okna
    skanera ani watchlisty. Zapewnia to, czego oczekuje ChartWindow (store, root, open_canslim, step_chart…). Jeden host obsługuje cały
    wykres — przy przejściu na box z innego skanera podmieniamy tylko dane (`use`), więc strzałki ↑/↓ przechodzą przez całą listę."""

    def __init__(self, app, parent):
        self.app, self.root, self.parent = app, parent, parent
        self.scanner = self.store = None
        self.chart = None

    def use(self, scanner):
        """Przełącza dane na skaner `scanner` (świeże z dysku, tylko gdy to inny skaner niż poprzednio)."""
        if self.scanner is None or self.scanner["id"] != scanner["id"]:
            self.scanner = scanner
            self.store = store.Store(scanners.scanner_dir(self.app.data_root, scanner["id"]), seed=scanner["id"] == scanners.DEFAULT_ID)

    def open_chart(self, ticker, focus=None):
        if not ticker:
            return
        if self.chart is None or not self.chart.winfo_exists():
            self.chart = ChartWindow(self, ticker)
            if focus:
                self.chart.set_focus(focus)
                self.chart.redraw()
        else:
            self.chart.set_ticker(ticker, focus)
            self.chart.lift()

    def open_canslim(self, ticker):
        if ticker and self.store.row(ticker):
            CanslimWindow(self, ticker)

    def step_chart(self, delta):
        """↑/↓ w oknie wykresu: przechodzi do następnego / poprzedniego boxa na liście przypiętych."""
        if self.parent.winfo_exists():
            self.parent.step(delta)

    def open_symbol_dialog(self):
        pass

    def refresh_lists(self):
        """Po przypięciu / odpięciu na wykresie: odśwież listę przypiętych i otwarty widok tego skanera (zapis jest na dysku)."""
        view = self.app.view_for(self.scanner["id"]) if self.scanner else None
        if view is not None and view.store is not self.store:
            view.store.pinned = dict(self.store.pinned)
            view.refresh_lists()
        if self.parent.winfo_exists():
            self.parent.refresh(keep=True)


class WatchlistView(ScannerView):
    """Watchlista: mała lista tickerów (z kilku skanów wg kryteriów) do odpalania Dar-Card i wykresu słupkowego. Bez filtrów i paska narzędzi skanera —
    kliknięcie tickera (albo ↑/↓) otwiera / przełącza wykres."""

    DEFAULT_COLUMNS = ["ticker", "flag", "price", "qm_max_ratio", "low_ratio_1m", "low_ratio_3m", "low_ratio_6m", "qm_windows", "darvas"]

    def __init__(self, master, app, scanner, root_window, loaded=None):
        tk.Frame.__init__(self, master, bg=PANEL)
        self.app, self.scanner, self.root = app, scanner, root_window
        self.store = loaded or store.Store(scanners.scanner_dir(app.data_root, scanner["id"]), seed=False)
        self.chart = self.filter_win = self.boxes = None
        self.main_filter = {}
        self.kind = scanners.KIND_WATCHLIST
        self.tf = tk.StringVar(value=self.store.tf)
        self.search, self.flag_filter = tk.StringVar(), tk.StringVar(value="Wszystkie")
        tb = Flow(self)
        tb.pack(fill="x")
        self.prices_btn = tk.Button(tb, text="⟳ Odśwież", command=lambda: self.start_sync(sync.PRICES), relief="flat")
        tb.add(self.prices_btn)
        tb.add(tk.Button(tb, text="✎ Kryteria…", command=self.edit_scanner, relief="flat"))
        tb.add(tk.Button(tb, text="▤ Kolumny…", command=self.choose_columns, relief="flat"))   # dodatkowe dane ze skanów do sortowania (klik w nagłówek)
        for text, val in (("Tydz.", "W"), ("Dzień", "D")):
            tb.add(tk.Radiobutton(tb, text=text, value=val, variable=self.tf, command=lambda: self.set_tf(self.tf.get()), bg=PANEL,
                                  indicatoron=False, padx=7, relief="flat"))
        self.status = autowrap(tk.Label(self, text="", bg=PANEL, fg="#8b95a3"), pad=8)
        self.status.pack(fill="x", side="bottom")
        self.table = StockTable(self, self.open_chart, self.open_chart_new, self.open_canslim, columns=self.columns(), flags=app.flags, on_flag=self.set_flag)
        self.table.pack(fill="both", expand=True)
        if "qm_max_ratio" in self.table.columns:   # lista Qullamaggie: domyślnie od największego cena / min Low (klik w nagłówek zmienia sortowanie)
            self.table.sort_col, self.table.sort_rev = "qm_max_ratio", True
            self.table._fill()
        self.table.on_select = lambda t: self.open_chart(t)   # zaznaczenie (kliknięcie, ↑/↓) przełącza wykres
        self.table.tree.bind("<slash>", lambda e: self.open_symbol_dialog())
        self.set_title()
        self.app.flags.tag(self.store.rows)
        self.refresh_lists()

    def columns(self):
        cols = self.scanner.get("columns") or self.DEFAULT_COLUMNS
        return cols if "ticker" in cols else ["ticker"] + list(cols)

    def set_title(self):
        self.root.title(f"Watchlista — {self.scanner['name']}")

    def _rows(self):
        return list(self.store.rows)

    def refresh_lists(self):
        rows = self._rows()
        self.table.set_rows(rows)
        self.table.set_tf_label(self.store.tf)
        wl = self.store.watchlist
        src = ", ".join(x["name"] for x in (scanners.get(self.app.data_root, s["id"]) for s in self.scanner.get("sources") or []) if x)
        self.status.config(text=f"  {len(rows)} tickerów · dane z sesji: {wl.get('data_as_of', '—')} · ze skanów: {src or '—'}")
        if self.boxes and self.boxes.winfo_exists():
            self.boxes.refresh()

    def update_age(self):
        pass

    def set_sync_enabled(self, on):
        self.prices_btn.config(state="normal" if on else "disabled")


def load_store_async(root, scanner, app, done):
    """Wczytuje dane skanera w wątku (okno z kręcącym się kółkiem nie zamarza); `done(store)` woła się w pętli Tk, store=None przy błędzie."""
    result = {}

    def work():
        try:
            result["store"] = store.Store(scanners.scanner_dir(app.data_root, scanner["id"]), seed=scanner["id"] == scanners.DEFAULT_ID)
        except Exception:   # noqa: BLE001 — okno zbuduje wtedy własny Store i pokaże błąd normalnie
            result["store"] = None

    def poll():
        if "store" in result:
            done(result["store"])
        else:
            root.after(40, poll)

    threading.Thread(target=work, daemon=True).start()
    root.after(40, poll)


class _ScannerWindowBase(tk.Toplevel):
    """Wspólne dla okien skanera i watchlisty: przy `defer=True` (start programu) okno pokazuje się od razu z kółkiem „wczytuję”, a dane
    dochodzą w tle; `self.view` jest None, dopóki nie skończą się wczytywać."""

    VIEW = None
    SIZE = (1360, 720)

    def __init__(self, app, scanner, defer=False):
        super().__init__(app.root)
        self.app, self.scanner, self.view, self.loader = app, scanner, None, None
        self.configure(bg=BG)
        self.title(f"{scanner['name']} — wczytuję…")
        apply_dark(self)
        self.protocol("WM_DELETE_WINDOW", lambda: app.window_closed(scanner["id"]))
        if defer:
            self.geometry(f"{self.SIZE[0]}x{self.SIZE[1]}")
            self.loader = LoadingFrame(self, f"Wczytuję „{scanner['name']}”…")
            self.loader.pack(fill="both", expand=True)
            load_store_async(self, scanner, app, self._finish)
        else:
            self._build(None)

    def _finish(self, loaded):
        if self.winfo_exists():
            self._build(loaded, resize=False)
            self.app.refresh_launcher()

    def _build(self, loaded, resize=True):
        if self.loader is not None:
            self.loader.destroy()
            self.loader = None
        self.view = self.VIEW(self, self.app, self.scanner, self, loaded=loaded)
        self.view.pack(fill="both", expand=True)
        self.after_build(resize)

    def after_build(self, resize):
        pass


class WatchlistWindow(_ScannerWindowBase):
    """Małe okno watchlisty (wąskie, z samymi tickerami)."""

    VIEW = WatchlistView
    SIZE = (560, 620)

    def after_build(self, resize):
        width = sum(columns_mod.DEFS[c][1] for c in self.view.columns() if c in columns_mod.DEFS) + 40   # szerokość = suma kolumn
        if resize:
            fit_window(self, min(max(width, 430), 900), 620, min_w=360)
        else:
            self.geometry(f"{min(max(width, 430), 900)}x620")
            self.minsize(360, 300)


class ScannerListWindow(_ScannerWindowBase):
    """Osobne okno własnego skanera."""

    VIEW = ScannerView

    def after_build(self, resize):
        if resize:
            fit_window(self, 1360, 720)
        self.bind("<F5>", lambda e: self.view.start_sync(sync.PRICES))
        self.bind("<Shift-F5>", lambda e: self.view.start_sync(sync.FUNDAMENTALS))


class App:
    def __init__(self, data_base=None):
        self.root = tk.Tk()
        self.root.geometry("1420x760")
        setup_style(self.root)
        apply_dark(self.root)
        self.data_root = store.data_dir(data_base)
        self.windows = {}   # id skanera -> ScannerListWindow
        self.flags = flags_mod.Flags(self.data_root)
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
            ("Skanery", [("Szybkie okno skanerów", self.open_launcher), ("📌 Przypięte boxy (wszystkie skanery)", self.open_pinned), ("Moje skanery…", self.open_manager), ("Nowy skaner Finviz…", self.new_scanner),
                         ("Nowy skan Qullamaggie (dane do watchlisty)…", lambda: self.new_scanner(scanners.KIND_QM)),
                         ("Nowy skan Wish (Green Line Breakout)…", lambda: self.new_scanner(preset="wish")),
                         ("Nowa watchlista (lista tickerów z kilku skanów)…", lambda: self.new_scanner(scanners.KIND_WATCHLIST)),
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
        return [self.view] + [w.view for w in self.windows.values() if w.winfo_exists() and w.view is not None]

    def refresh_flag_views(self):
        """Flagi są wspólne dla wszystkich skanerów: po zmianie odświeżamy wszystkie listy."""
        for v in self.all_views():
            self.flags.tag(v.store.rows)
            v.refresh_lists()

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

    def open_pinned(self):
        if getattr(self, "pinned_win", None) is None or not self.pinned_win.winfo_exists():
            self.pinned_win = PinnedWindow(self)
        else:
            self.pinned_win.refresh()
        self.pinned_win.lift()

    def open_manager(self):
        if self.manager is None or not self.manager.winfo_exists():
            self.manager = ScannerManager(self)
        self.manager.refresh()
        self.manager.lift()

    def new_scanner(self, kind=scanners.KIND_FINVIZ, preset=None):
        (WatchlistEditor(self) if kind == scanners.KIND_WATCHLIST else ScannerEditor(self, kind=kind, preset=preset))

    def edit_scanner(self, sid):
        sc = scanners.get(self.data_root, sid)
        if sc:
            (WatchlistEditor(self, sc) if sc.get("kind") == scanners.KIND_WATCHLIST else ScannerEditor(self, sc))

    def open_scanner_window(self, sid, defer=False):
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
                    self.windows[sid] = (WatchlistWindow if sc.get("kind") == scanners.KIND_WATCHLIST else ScannerListWindow)(self, sc, defer=defer)
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
                self.open_scanner_window(sid, defer=True)   # okno od razu z kółkiem „wczytuję”, dane w tle
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
        no_cache = not any((d / "eps_cache.json").exists() for d in (view.store.dir, self.data_root))
        kind = view.scanner.get("kind") or scanners.KIND_FINVIZ
        if kind == scanners.KIND_WATCHLIST:
            self.start_merge(view)
            return
        upgraded = kind == scanners.KIND_FINVIZ and mode == sync.PRICES and not (view.store.dir / "sync_state.json").exists() and no_cache
        if upgraded:   # nigdzie nie ma jeszcze EPS ani estymat (ani w skanerze, ani we wspólnym cache) — pierwszy Sync pobiera fundamenty
            mode = sync.FUNDAMENTALS
        view.set_sync_enabled(False)
        fund = mode == sync.FUNDAMENTALS
        name = view.scanner["name"]
        win = SyncWindow(self, f"Synchronizacja {'fundamentów' if fund else 'cen'} — {name}")
        self.syncing[sid] = win
        win.log(f"Skaner: {name}")
        if mode == sync.PRICES and sid != scanners.DEFAULT_ID and not (view.store.dir / "sync_state.json").exists():
            win.log("Nowy skaner: ceny pobieram szybko, EPS bierzemy ze wspólnego cache; spółki bez EPS dostaną dane po „Fundamenty”.")
        if upgraded:
            win.log("To pierwsza synchronizacja tego skanera — pobieram też fundamenty (EPS, estymaty), żeby CANSLIM i oceny miały dane.")
        if not skip_finviz:   # co dokładnie pobieramy z Finviz
            cfg = view.store.finviz_config()
            for line in finviz_codes.summary_lines(cfg.get("filters"), cfg.get("max_tickers")):
                win.log(line)
            if view.scanner.get("extra"):
                win.log(f"  + dodatkowe kolumny z Finviz: {', '.join(view.scanner['extra'])}")
        if kind == scanners.KIND_QM:
            two = (scanners.load_config(view.store.dir).get("qm") or {}).get("two_stage")
            win.log("Skaner Qullamaggie: tylko ceny (bez EPS i estymat). Lista z Finviz dzielona po sektorach (darmowy screener oddaje max 1000 wierszy). "
                    + ("Szybki Sync: etap 1 = tylko Finviz (cały zbiór), etap 2 = ceny z yfinance tylko dla kandydatów — kilka minut."
                       if two else "Pełny Sync: ceny z yfinance dla całego zbioru — to potrwa kilka–kilkanaście minut.") + " Zostają spółki powyżej progów pobierania.")
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

    def start_merge(self, view):
        """Watchlista: składa listę z danych skanów wg kryteriów (bez sieci)."""
        sid = view.scanner["id"]
        if sid in self.syncing:
            return
        sc = scanners.get(self.data_root, sid) or view.scanner
        view.set_sync_enabled(False)
        win = SyncWindow(self, f"Watchlista — {sc['name']}")
        self.syncing[sid] = win
        win.log("Składam z: " + ", ".join(s["name"] for s in (scanners.get(self.data_root, x["id"]) for x in sc.get("sources") or []) if s))

        def work():
            try:
                n = merge.build(self.data_root, sc, log=lambda s: self.q.put(("log", sid, s)))
                self.q.put(("done", sid, n > 0))
            except Exception as e:   # błąd składania listy nie może zawiesić okna synchronizacji
                self.q.put(("log", sid, f"❌ Błąd składania watchlisty: {e}"))
                self.q.put(("done", sid, False))

        threading.Thread(target=work, daemon=True).start()

    def refresh_merges(self, source_id):
        """Po Sync skanu odświeża watchlisty, które z niego korzystają (po cichu)."""
        for sc in scanners.load(self.data_root):
            if sc.get("kind") == scanners.KIND_WATCHLIST and any(x["id"] == source_id for x in sc.get("sources", [])):
                v = self.view_for(sc["id"])
                try:
                    merge.build(self.data_root, sc, log=lambda s: None)
                except Exception:
                    continue
                if v is not None:
                    v.reload()

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
                            view.reload() if view.kind == scanners.KIND_WATCHLIST else self.after_sync(view)
                    if val:
                        self.refresh_merges(sid)
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
        d = changes.merge(view.store.changes["diff"], fresh) if old else view.store.changes["diff"]
        names = {t: old[t].get("name") for t in d.get("dropped", []) if t in old}
        names = {**view.store.changes.get("names", {}), **names}
        view.store.set_changes(d, sync.now_iso(), names)
        view.refresh_lists()
        if changes.total(fresh):
            view.open_changes()

    def run(self):
        self.root.mainloop()


def main():
    App().run()
