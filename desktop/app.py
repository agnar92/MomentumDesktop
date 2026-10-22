"""Główne okno: jedna lista (skan Finviz + warunki strategii), Sync, ustawienia filtra i wykres tygodniowy. Ctrl+K = dowolny symbol."""
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import datetime as dt
import math

from . import calc, finviz, lines, prices, sec, sync
from .chart import ChartWindow
from .store import DEFAULT_SCANNERS, Store, normalize_scanners
from .theme import BG, FG, PANEL, apply_dark, autowrap, setup_style

COLUMNS = [  # (klucz, nagłówek, szerokość, format)
    ("ticker", "Ticker", 70, "s"), ("company", "Spółka", 200, "s"), ("sector", "Sektor", 140, "s"), ("price", "Cena", 80, "p"),
    ("upside", "Upside 12M %", 110, "%"), ("glb", "Green Line", 90, "p"), ("glb_pct", "Do linii %", 85, "%"), ("glb_state", "GLB", 85, "s"), ("macd", "MACD", 60, "s"), ("trend", "SMA 10>30", 85, "b"),
    ("macd_stop", "Stop MACD", 85, "p"), ("dopm", "Δ marża oper. pp", 120, "%"), ("rev_rr", "Przychody r/r %", 115, "%"),
    ("dgm", "Δ marża brutto pp", 125, "%"), ("quarter", "Kwartał", 105, "s"), ("turnover", "Obrót mln $", 95, "m"),
    ("ps", "P/S", 60, "x"), ("rs", "RS 52 tyg. pp", 105, "%"), ("surp", "Niesp. EPS %", 95, "%"), ("beat2", "2× nad konsensus", 115, "b"), ("eps_rev", "Rewizja EPS 90 dni %", 140, "%"), ("rvol_w", "RVol tyg.", 80, "x"), ("rvol_d", "RVol dz.", 75, "x"), ("cc250", "C/C250", 85, "r"), ("ok", "Warunki", 75, "b"), ("slow", "Hamuje", 95, "w"),
]
SIGNAL = ("WYBICIE", "SYGNAŁ", "BLUE DOT")
# filtry listy (wszystkie naraz, ORAZ): {kolumna: {"in": [wartości]} | {"min", "max"}}; liczby w jednostkach tabeli (obrót w mln $)
FILTER_CHOICES = {"glb_state": ["WYBICIE", "SYGNAŁ", "BLUE DOT", "NAD", "POD", "BRAK"], "macd": ["nad", "pod"], "ok": ["tak", "nie"], "trend": ["tak", "nie"], "beat2": ["tak", "nie"], "slow": ["HAMUJE", "HAMUJE+MB", "—"]}
FILTER_SCALE = {"turnover": 1e6}
FILTER_PRESETS = [
    ("Sygnał kupna: warunki + wybicie / 0–10 % / Blue Dot", {"ok": {"in": ["tak"]}, "glb_state": {"in": ["WYBICIE", "SYGNAŁ", "BLUE DOT"]}}),
    ("Liderzy: RS 52 tyg. ≥ 50 pp + nad GLB", {"rs": {"min": 50}, "glb_state": {"in": ["WYBICIE", "SYGNAŁ", "BLUE DOT", "NAD"]}}),
    ("Przebicie GLB + SMA 10 > 30 (dowolnie wysoko)", {"trend": {"in": ["tak"]}, "glb_state": {"in": ["WYBICIE", "SYGNAŁ", "BLUE DOT", "NAD"]}}),
    ("Aktywne: RVol tyg. ≥ 1,5 + nad GLB", {"rvol_w": {"min": 1.5}, "glb_state": {"in": ["WYBICIE", "SYGNAŁ", "BLUE DOT", "NAD"]}}),
    ("Nad GLB + MACD dodatni", {"glb_state": {"in": ["WYBICIE", "SYGNAŁ", "BLUE DOT", "NAD"]}, "macd": {"in": ["nad"]}}),
    ("Sygnał kupna (wybicie / 0–10 % / Blue Dot) + MACD dodatni", {"glb_state": {"in": ["WYBICIE", "SYGNAŁ", "BLUE DOT"]}, "macd": {"in": ["nad"]}}),
    ("Blisko linii (−10…+10 %)", {"glb_pct": {"min": -10, "max": 10}}),
]


def filter_value(r, k):
    if k in ("ok", "trend", "beat2"):
        return "tak" if r.get(k) else "nie"
    return "—" if r.get(k) is None else str(r[k])


def pass_filters(r, filters):
    for k, f in (filters or {}).items():
        if f.get("in") and filter_value(r, k) not in f["in"]:
            return False
        if f.get("min") is None and f.get("max") is None:
            continue
        v = None if r.get(k) is None else r[k] / FILTER_SCALE.get(k, 1)
        if v is None or (f.get("min") is not None and v < f["min"]) or (f.get("max") is not None and v > f["max"]):
            return False
    return True


def active_filters(filters):
    return sum(1 for f in (filters or {}).values() if f.get("in") or f.get("min") is not None or f.get("max") is not None)


def cell(v, f):
    if v is None:
        return ""
    if f == "p":
        return f"{v:,.2f}"
    if f == "%":
        return f"{v:+.1f}"
    if f == "m":
        return f"{v / 1e6:,.0f}"
    if f == "b":
        return "✓" if v else ""
    if f == "x":
        return f"{v:.1f}"
    if f == "r":
        return f"{v:.2f}"
    if f == "w":
        return "⚠⚠ + marża" if v == "HAMUJE+MB" else "⚠ hamuje" if v else ""
    return str(v)


def fmt_time(sec):
    sec = int(max(0, sec))
    return f"{sec // 60}:{sec % 60:02d}"


def progress_text(frac, stage, elapsed):
    """Napis przy pasku postępu: etap, procent, czas od startu i szacunek do końca (gdy jest z czego liczyć)."""
    eta = f" · zostało ~{fmt_time(elapsed * (1 - frac) / frac)}" if 0.03 < frac < 1 else ""
    return f"{stage} · {frac * 100:.0f} % · {fmt_time(elapsed)}{eta}"


def default_order(r):
    """Najpierw spełniające warunki z sygnałem GLB, potem spełniające warunki; w grupie od największej siły względnej."""
    sig = r.get("glb_state") in SIGNAL
    return (not (r.get("ok") and sig), not r.get("ok"), -(r.get("rs") if r.get("rs") is not None else -1e9))


class App:
    def __init__(self, base=None):
        self.root = tk.Tk()
        self.root.title("Momentum Desktop — GLB + marża operacyjna")
        self.root.geometry("1500x780")
        setup_style(self.root)
        apply_dark(self.root)
        self.store = Store(base)
        self.q, self.chart, self.sort = queue.Queue(), None, None
        self.growth_dialog = None
        self._daily_alert_refreshing = False
        self._symbol_syncs = set()
        bar = tk.Frame(self.root, bg=PANEL)
        bar.pack(fill="x")
        self.sync_btn = tk.Button(bar, text="⟳ Sync (F5)", command=self.start_sync, relief="flat")
        self.sync_btn.pack(side="left", padx=4, pady=4)
        tk.Label(bar, text="Skaner:", bg=PANEL).pack(side="left", padx=(8, 2))
        self.scanner = tk.StringVar(value=self.store.settings["scanner"])
        self.scanner_box = ttk.Combobox(bar, textvariable=self.scanner, state="readonly", width=24)
        self.scanner_box.pack(side="left", padx=2)
        self.scanner_box.bind("<<ComboboxSelected>>", lambda e: self.select_scanner(self.scanner.get()))
        tk.Button(bar, text="Skanery / ustawienia…", command=self.open_settings, relief="flat").pack(side="left", padx=4)
        tk.Button(bar, text="Growth Score", command=self.open_growth_score, relief="flat").pack(side="left", padx=4)
        self.only_ok = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="tylko spełniające warunki", variable=self.only_ok, command=self.refresh, bg=PANEL).pack(side="left", padx=8)
        tk.Button(bar, text="Warunki…", command=lambda: StrategyConditionsDialog(self), relief="flat").pack(side="left", padx=2)
        self.flt_btn = tk.Button(bar, text="Filtry…", command=lambda: FilterDialog(self), relief="flat")
        self.flt_btn.pack(side="left", padx=4)
        tk.Label(bar, text="Szukaj:", bg=PANEL).pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh())
        tk.Entry(bar, textvariable=self.search, width=12, relief="flat").pack(side="left", padx=4)
        tk.Button(bar, text="📖 Poradnik", command=lambda: GuideDialog(self), relief="flat").pack(side="left", padx=4)
        self.alert_btn = tk.Button(bar, text="🔔 Alerty", command=lambda: AlertsDialog(self), relief="flat")
        self.alert_btn.pack(side="left", padx=4)
        tk.Button(bar, text="📌 Pozycje", command=lambda: PositionsDialog(self), relief="flat").pack(side="left", padx=4)
        tk.Button(bar, text="Kolumny…", command=lambda: ColumnsDialog(self), relief="flat").pack(side="left", padx=4)
        tk.Label(bar, text="Ctrl+K — dowolny symbol (np. SPY, NVDA)", bg=PANEL, fg="#8b95a3").pack(side="left", padx=12)
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        for key, head, width, _ in COLUMNS:
            self.tree.heading(key, text=head, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, minwidth=width, anchor="w" if key in ("ticker", "company", "sector", "glb_state", "macd") else "e", stretch=False)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        all_columns = [c[0] for c in COLUMNS]
        display_columns = self.store.settings.get("main_columns")
        if display_columns:
            display_columns = [k for k in display_columns if k in all_columns]
            # Dodaj nową kolumnę do wcześniej zapisanych układów, aby Upside było od razu widoczne.
            if "upside" not in display_columns:
                display_columns.append("upside")
                self.store.settings["main_columns"] = display_columns
                self.store.save_settings()
            self.tree["displaycolumns"] = display_columns or all_columns
        else:
            self.tree["displaycolumns"] = all_columns
        self.tree.tag_configure("signal", background="#123a24")
        self.tree.tag_configure("dim", foreground="#6b7684")
        self.tree.tag_configure("poswarn", foreground="#ffb020")
        self.tree.bind("<Double-1>", lambda e: self.open_chart(self.current()))
        self.tree.bind("<Return>", lambda e: self.open_chart(self.current()))
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._follow())
        self.status = autowrap(tk.Label(self.root, text="", bg=PANEL, padx=8))
        self.status.pack(fill="x", side="bottom")
        # pasek postępu Sync (na samym dole, widoczny tylko w trakcie)
        self.pframe = tk.Frame(self.root, bg=PANEL)
        self.pbar = ttk.Progressbar(self.pframe, orient="horizontal", mode="determinate", maximum=1000)
        self.pbar.pack(side="left", fill="x", expand=True, padx=(8, 8), pady=4)
        self.plabel = tk.Label(self.pframe, text="", bg=PANEL, anchor="w", width=70)
        self.plabel.pack(side="left", padx=(0, 8))
        self.t0 = None
        self.root.bind("<F5>", lambda e: self.start_sync())
        self.root.bind("<Control-k>", lambda e: self.open_symbol())
        self.root.bind("<slash>", lambda e: self.open_symbol() if e.widget is self.tree else None)
        self.root.after(150, self._poll)
        self.fill_scanners()
        self.refresh()
        self.check_alerts()

    # --- skanery
    def fill_scanners(self):
        self.scanner_box["values"] = [x["name"] for x in self.store.settings["scanners"]]
        self.scanner.set(self.store.settings["scanner"])

    def select_scanner(self, name):
        if self.sync_btn["state"] == "disabled":   # w trakcie Sync zostaje skaner, który się synchronizuje
            self.scanner.set(self.store.settings["scanner"])
            return
        self.store.select(name)
        self.refresh()

    # --- lista
    def rows(self):
        text = self.search.get().strip().upper()
        flt = self.store.settings.get("list_filters") or {}
        rows = [r for r in self.store.rows if (not self.only_ok.get() or r.get("ok")) and pass_filters(r, flt)
                and (not text or text in r["ticker"] or text in (r.get("company") or "").upper())]
        if self.sort:
            key, rev = self.sort
            filled = sorted((r for r in rows if r.get(key) is not None), key=lambda r: r[key], reverse=rev)
            return filled + [r for r in rows if r.get(key) is None]
        rows.sort(key=default_order)
        return rows

    def apply_strategy_conditions(self):
        """Przelicza stan „Warunki” dla bieżących i obserwowanych wierszy po edycji wymagań."""
        conditions = calc.normalize_conditions(self.store.settings.get("strategy_conditions"))
        self.store.settings["strategy_conditions"] = conditions
        for row in self.store.rows:
            row["ok"] = calc.passes(row, conditions)
        for ticker, (row, series) in list(self.store.extra.items()):
            if row:
                row["ok"] = calc.passes(row, conditions)
                self.store.extra[ticker] = (row, series)
        self.refresh()
        if self.chart is not None and self.chart.winfo_exists():
            self.chart.render_panel()
            self.chart.redraw()

    def pos_warn(self, r):
        """📌 pozycja do uwagi: wyjście wg wybranej metody (MACD: zamknięcie pod stopem MACD, GLB: pod Green Line), −20 % od szczytu, hamowanie."""
        st, price = self.store, r.get("price") or 0
        plan = lines.position_plan(st.alerts["pos"][r["ticker"]], st.weekly(r["ticker"]), r)
        exit_now = (r.get("glb") and price < r["glb"]) if st.settings.get("exit", "MACD") == "GLB" else (r.get("macd_stop") and price < r["macd_stop"])
        return bool(r.get("slow") or exit_now or plan["half"])

    def refresh(self):
        sel = self.current()
        self.tree.delete(*self.tree.get_children())
        for r in self.rows():
            tag = "signal" if r.get("ok") and r.get("glb_state") in SIGNAL else "" if r.get("ok") else "dim"
            held = r["ticker"] in self.store.alerts["pos"]
            if held and self.pos_warn(r):
                tag = "poswarn"
            vals = [cell(r.get(k), f) for k, _, _, f in COLUMNS]
            if held:
                vals[0] = "📌 " + vals[0]
            self.tree.insert("", "end", iid=r["ticker"], values=vals, tags=(tag,))
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)
        nf = active_filters(self.store.settings.get("list_filters"))
        self.flt_btn.config(text=f"Filtry ({nf})…" if nf else "Filtry…")
        n_ok = sum(1 for r in self.store.rows if r.get("ok"))
        n_sig = sum(1 for r in self.store.rows if r.get("ok") and r.get("glb_state") in SIGNAL)
        cfg = calc.normalize_conditions(self.store.settings.get("strategy_conditions"))
        required = []
        if cfg["rev_growth"]["enabled"]:
            required.append(f"przychody ≥ {cfg['rev_growth']['threshold']:g} %")
        if cfg["op_margin"]["enabled"]:
            required.append(f"Δ marży oper. ≥ {cfg['op_margin']['threshold']:g} pp")
        if cfg["ps"]["enabled"]:
            required.append(f"P/S < {cfg['ps']['threshold']:g}")
        if cfg["rs"]["enabled"]:
            required.append(f"RS 52 tyg. ≥ {cfg['rs']['threshold']:g} pp")
        if cfg["beat2"]["enabled"]:
            required.append("2× EPS nad konsensusem")
        condition_text = ", ".join(required) if required else "brak obowiązkowych kryteriów"
        self.status.config(text=f"  Skaner: {self.store.settings['scanner']}   Dane: {self.store.at or 'brak — kliknij ⟳ Sync'}   Na liście: {len(self.tree.get_children())} z {len(self.store.rows)}   spełnia warunki: {n_ok}   sygnał GLB: {n_sig}"
                                f"   (warunki konieczne: {condition_text};"
                                f" sygnał: zamknięcie tyg. 0–{calc.ENTRY_MAX_PCT:g} % nad Green Line; wyjście: MACD tyg. + stop {calc.STOP_PCT:g} %)")

        self.refresh_growth_dialog()

    def sort_by(self, key):
        self.sort = (key, not self.sort[1]) if self.sort and self.sort[0] == key else (key, key not in ("ticker", "company", "sector"))
        self.refresh()

    def current(self):
        s = self.tree.selection()
        return s[0] if s else None

    def step(self, ticker, d):
        ids = list(self.tree.get_children())
        if ticker not in ids:
            return ids[0] if ids else None
        i = max(0, min(len(ids) - 1, ids.index(ticker) + d))
        self.tree.selection_set(ids[i])
        self.tree.see(ids[i])
        return ids[i]

    # --- wykres
    def open_chart(self, ticker):
        if not ticker:
            return
        if self.chart is None or not self.chart.winfo_exists():
            self.chart = ChartWindow(self, ticker)
        else:
            self.chart.set_ticker(ticker)
            self.chart.lift()

    def _follow(self):
        if self.chart is not None and self.chart.winfo_exists() and self.current() and self.current() != self.chart.ticker:
            self.chart.set_ticker(self.current())

    # --- Sync i symbole (w wątkach; komunikaty przez kolejkę do pętli Tk)
    def start_sync(self):
        if self.sync_btn["state"] == "disabled" or self._symbol_syncs:
            return
        self.sync_btn.config(state="disabled")
        log = lambda s: self.q.put(("log", s))   # noqa: E731
        self.t0 = time.monotonic()
        self.pbar["value"] = 0
        self.plabel.config(text="Start…")
        self.pframe.pack(fill="x", side="bottom", before=self.status)

        def work():
            try:
                sync.run(self.store, log=log, progress=lambda f, st: self.q.put(("progress", (f, st))))
                self.q.put(("synced", None))
            except Exception as e:   # błąd sieci / Finviz: lista zostaje stara, komunikat w pasku
                self.q.put(("error", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def start_symbol_sync(self, ticker):
        """Odświeża dane jednej spółki w tle bez pobierania całej listy Finviz."""
        chart = self.chart if self.chart is not None and self.chart.winfo_exists() else None
        if self.sync_btn["state"] == "disabled":
            self.status.config(text="  Pełna synchronizacja już trwa — spróbuj ponownie po jej zakończeniu.")
            return
        if ticker in self._symbol_syncs:
            return
        self._symbol_syncs.add(ticker)
        if chart is not None:
            chart.set_sync_state(ticker, True)
        self.status.config(text=f"  ⟳ Odświeżam dane {ticker}…")
        log = lambda msg: self.q.put(("log", msg))  # noqa: E731

        def work():
            try:
                row, weekly = sync.symbol(ticker, self.store, log=log)
                try:
                    daily = prices.daily_ohlc(ticker)
                except Exception as exc:
                    log(f"Dane dzienne {ticker}: {exc}")
                    daily = None
                try:
                    monthly = prices.monthly_ohlc(ticker)
                except Exception as exc:
                    log(f"Dane miesięczne {ticker}: {exc}")
                    monthly = None
                self.q.put(("symbol_synced", (ticker, row, weekly, daily, monthly)))
            except Exception as exc:
                self.q.put(("symbol_sync_error", (ticker, str(exc))))

        threading.Thread(target=work, daemon=True).start()

    def open_symbol(self):
        SymbolDialog(self)

    def open_growth_score(self):
        if self.growth_dialog is not None:
            try:
                if self.growth_dialog.winfo_exists():
                    self.growth_dialog.fill()
                    self.growth_dialog.lift()
                    return
            except tk.TclError:
                pass
        self.growth_dialog = GrowthScoreDialog(self)

    def refresh_growth_dialog(self):
        dialog = self.growth_dialog
        if dialog is not None:
            try:
                if dialog.winfo_exists():
                    dialog.fill()
                else:
                    self.growth_dialog = None
            except tk.TclError:
                self.growth_dialog = None

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.status.config(text="  " + val)
                elif kind == "progress":
                    frac, stage = val
                    self.pbar["value"] = frac * 1000
                    self.plabel.config(text=progress_text(frac, stage, time.monotonic() - (self.t0 or time.monotonic())))
                elif kind == "symbol_synced":
                    ticker, row, weekly, daily, monthly = val
                    self._symbol_syncs.discard(ticker)
                    old = self.store.row(ticker) or {}
                    if daily and daily.get("c"):
                        row["rvol_d"] = calc.rel_volume(daily.get("v") or [], calc.RVOL_D)
                        closes = daily["c"]
                        base_i = max(0, len(closes) - 251)
                        row["cc250"] = closes[-1] / closes[base_i] if len(closes) >= 2 and closes[base_i] else None
                        blue_dot = calc.fresh_blue_dot(daily, row.get("glb")) if row.get("glb_state") == "NAD" else None
                        if blue_dot:
                            row["glb_state"], row["bdot"] = "BLUE DOT", blue_dot
                        else:
                            row.pop("bdot", None)
                        daily["period"] = "D"
                        self.store.save_daily_series(ticker, daily)
                    else:
                        for key in ("rvol_d", "cc250", "bdot"):
                            if key in old:
                                row[key] = old[key]
                    if monthly:
                        monthly["period"] = "M"
                        monthly["open_last"] = monthly["d"][-1][:7] == dt.date.today().strftime("%Y-%m")
                    self.store.save_symbol(ticker, row, weekly)
                    chart = self.chart if self.chart is not None and self.chart.winfo_exists() else None
                    if chart is not None:
                        chart.set_sync_state(ticker, False)
                        if daily:
                            chart.other["D"][ticker] = daily
                        if monthly:
                            chart.other["M"][ticker] = monthly
                        if chart.ticker == ticker:
                            chart.load_period()
                            chart.render_panel()
                    self.refresh()
                    self.check_alerts(refresh_daily=False)
                    dlg = getattr(self, "_positions_dialog", None)
                    if dlg is not None and dlg.winfo_exists():
                        dlg.fill()
                    parts = ["tygodniowe i fundamenty"]
                    if daily:
                        parts.append("dzienne")
                    if monthly:
                        parts.append("miesięczne")
                    self.status.config(text=f"  ✓ Odświeżono {ticker}: " + ", ".join(parts))
                elif kind == "symbol_sync_error":
                    ticker, error = val
                    self._symbol_syncs.discard(ticker)
                    chart = self.chart if self.chart is not None and self.chart.winfo_exists() else None
                    if chart is not None:
                        chart.set_sync_state(ticker, False)
                    self.status.config(text=f"  ❌ Nie udało się odświeżyć {ticker}: {error}")
                elif kind == "daily_alert_data":
                    self._daily_alert_refreshing = False
                    for ticker, series in val.items():
                        self.store.save_daily_series(ticker, series)
                        if self.chart is not None and self.chart.winfo_exists():
                            self.chart.other["D"][ticker] = series
                            if self.chart.ticker == ticker and self.chart.period == "D":
                                self.chart.redraw()
                    self.check_alerts(refresh_daily=False)
                elif kind == "synced":
                    self.pframe.pack_forget()
                    self.sync_btn.config(state="normal")
                    self.refresh()
                    self.check_alerts()
                    if self.chart is not None and self.chart.winfo_exists():
                        self.chart.set_ticker(self.chart.ticker)
                elif kind == "error":
                    self.pframe.pack_forget()
                    self.sync_btn.config(state="normal")
                    self.status.config(text=f"  ❌ {val}")
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def open_settings(self):
        SettingsDialog(self)

    # --- alerty (linie trendu + obserwowane spółki), sprawdzane po starcie i po Sync
    def check_alerts(self, refresh_daily=True):
        st = self.store
        weeks = [s["d"][-1] for s in st.series.values() if s and s.get("d")]
        fresh = lines.eval_alerts(
            st.alerts, st.row, st.weekly, dt.datetime.now().isoformat(timespec="seconds"),
            max(weeks) if weeks else "", daily_for=st.daily,
        )
        st.save_alerts()
        self.alert_badge()
        if fresh:
            self.status.config(text=f"  🔔 {len(fresh)} nowych alertów: " + " · ".join(f"{a['t']} {a['msg']}" for a in fresh[:3]))
        if refresh_daily:
            self.refresh_daily_alerts()

    def refresh_daily_alerts(self):
        """Odświeża świece tylko dla dziennych linii, dla których włączono alert."""
        if self._daily_alert_refreshing:
            return
        tickers = sorted(
            ticker for ticker, items in self.store.alerts["lines"].items()
            if any(ln.get("period") == "D" and ln.get("alert") is not False for ln in items)
        )
        if not tickers:
            return
        self._daily_alert_refreshing = True

        def work():
            fresh = {}
            for ticker in tickers:
                try:
                    data = prices.daily_ohlc(ticker)
                    if data:
                        fresh[ticker] = data
                except Exception as exc:
                    self.q.put(("log", f"Alert dzienny {ticker}: {exc}"))
            self.q.put(("daily_alert_data", fresh))

        threading.Thread(target=work, daemon=True).start()

    def alert_badge(self):
        n = sum(1 for a in self.store.alerts["log"] if a["at"] > self.store.alerts["seen"])
        self.alert_btn.config(text=f"🔔 Alerty ({n})" if n else "🔔 Alerty", bg="#1f3b5c" if n else self.flt_btn.cget("bg"))

    def run(self):
        self.root.mainloop()



class SettingsDialog(tk.Toplevel):
    """Skanery Finviz (nazwa + filtr + limit spółek; każdy liczy tę samą strategię, ma własną listę po Sync) i User-Agent dla SEC."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Skanery Finviz i ustawienia")
        self.configure(bg=PANEL)
        apply_dark(self)
        self.items = [dict(x) for x in app.store.settings["scanners"]]
        self.cur = next(i for i, x in enumerate(self.items) if x["name"] == app.store.settings["scanner"])
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        self.lst = tk.Listbox(top, height=8, width=30, bg=BG, fg="#c9d1d9", selectbackground="#1f3a5f", selectforeground="#ffffff", exportselection=False, relief="flat")
        self.lst.pack(side="left", fill="y")
        self.lst.bind("<<ListboxSelect>>", lambda e: self.pick())
        form = tk.Frame(top, bg=PANEL)
        form.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.name, self.filters, self.maxn = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for lab, var, w in (("Nazwa:", self.name, 40), ("Filtr Finviz (kody f= z adresu screenera):", self.filters, 80), ("Limit spółek:", self.maxn, 8)):
            tk.Label(form, text=lab, bg=PANEL).pack(anchor="w")
            tk.Entry(form, textvariable=var, width=w).pack(anchor="w", fill="x" if w > 10 else None, pady=(0, 6))
        tk.Label(form, text="Finviz po cichu ignoruje nieznany kod — po zmianie sprawdź liczbę spółek po Sync.", bg=PANEL, fg="#8b95a3").pack(anchor="w")
        btns = tk.Frame(form, bg=PANEL)
        btns.pack(anchor="w", pady=6)
        for text, cmd in (("＋ Nowy", self.new), ("Usuń", self.delete), ("Przywróć domyślne skanery", self.defaults)):
            tk.Button(btns, text=text, command=cmd, relief="flat").pack(side="left", padx=(0, 6))
        tk.Label(self, text="User-Agent dla SEC (SEC prosi o nazwę i e-mail kontaktowy):", bg=PANEL).pack(anchor="w", padx=10, pady=(6, 2))
        self.ua = tk.StringVar(value=app.store.settings.get("sec_ua"))
        tk.Entry(self, textvariable=self.ua, width=90).pack(padx=10, fill="x")
        row = tk.Frame(self, bg=PANEL)
        row.pack(fill="x", padx=10, pady=10)
        tk.Button(row, text="Zapisz", command=self.save, relief="flat").pack(side="left")
        tk.Button(row, text="Anuluj", command=self.destroy, relief="flat").pack(side="left", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        self.fill()

    def fill(self):
        self.lst.delete(0, "end")
        for x in self.items:
            self.lst.insert("end", x["name"])
        self.lst.selection_set(self.cur)
        x = self.items[self.cur]
        self.name.set(x["name"])
        self.filters.set(x["filters"])
        self.maxn.set(str(x["max_tickers"]))

    def keep(self):
        """Zapamiętuje pola formularza w bieżącym skanerze."""
        x = self.items[self.cur]
        x["old"] = x.get("old", x["name"])
        x["name"] = self.name.get().strip() or x["name"]
        x["filters"] = self.filters.get().strip() or x["filters"]
        try:
            x["max_tickers"] = max(20, int(self.maxn.get()))
        except ValueError:
            pass

    def pick(self):
        sel = self.lst.curselection()
        if sel:
            self.keep()
            self.cur = sel[0]
            self.fill()

    def new(self):
        self.keep()
        self.items.append({"name": f"Skaner {len(self.items) + 1}", "filters": finviz.DEFAULT_FILTERS, "max_tickers": finviz.MAX_TICKERS})
        self.cur = len(self.items) - 1
        self.fill()

    def delete(self):
        if len(self.items) > 1:
            self.items.pop(self.cur)
            self.cur = 0
            self.fill()

    def defaults(self):
        self.items = [dict(x) for x in DEFAULT_SCANNERS]
        self.cur = 0
        self.fill()

    def save(self):
        self.keep()
        st = self.app.store
        current = self.items[self.cur]["name"]
        for x in self.items:   # zmiana nazwy przenosi listę spółek skanera
            old = x.pop("old", None)
            if old and old != x["name"] and st.scan_path(old).exists() and not st.scan_path(x["name"]).exists():
                st.scan_path(old).rename(st.scan_path(x["name"]))
        st.settings.update(scanners=self.items, scanner=current, sec_ua=self.ua.get().strip() or sec.UA)
        normalize_scanners(st.settings)
        st.save_settings()
        st.reload()
        self.app.fill_scanners()
        self.app.refresh()
        self.destroy()


class StrategyConditionsDialog(tk.Toplevel):
    """Edytor kryteriów, które muszą być spełnione, aby wiersz otrzymał status „Warunki”."""

    NUMERIC = (
        ("rev_growth", "Przychody kwartalne r/r ≥", "%"),
        ("op_margin", "Zmiana marży operacyjnej r/r ≥", "pp"),
        ("ps", "P/S <", ""),
        ("rs", "Siła względna 52 tyg. vs S&P 500 ≥", "pp"),
    )

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Warunki konieczne strategii")
        self.configure(bg=PANEL)
        apply_dark(self)
        self.resizable(False, False)
        self.transient(app.root)
        self.cfg = calc.normalize_conditions(app.store.settings.get("strategy_conditions"))
        self.enabled = {}
        self.threshold = {}
        self.entries = {}
        tk.Label(
            self,
            text="Zaznaczone kryteria są wymagane, aby spółka spełniała warunki. Zmiany działają od razu i są zapisywane.",
            bg=PANEL, fg="#c9d1d9", wraplength=650, justify="left",
        ).pack(anchor="w", padx=14, pady=(14, 10))
        grid = tk.Frame(self, bg=PANEL)
        grid.pack(fill="x", padx=14)
        for i, (key, label, unit) in enumerate(self.NUMERIC):
            var = tk.BooleanVar(value=self.cfg[key]["enabled"])
            self.enabled[key] = var
            tk.Checkbutton(
                grid, text=label, variable=var, command=lambda k=key: self._toggle_entry(k),
                bg=PANEL, activebackground=PANEL,
            ).grid(row=i, column=0, sticky="w", pady=4)
            threshold = tk.StringVar(value=f"{self.cfg[key]['threshold']:g}")
            self.threshold[key] = threshold
            entry = tk.Entry(grid, textvariable=threshold, width=10, justify="right")
            entry.grid(row=i, column=1, sticky="w", padx=(8, 4), pady=4)
            self.entries[key] = entry
            suffix = " (brak danych P/S nie blokuje)" if key == "ps" else unit
            tk.Label(grid, text=suffix, bg=PANEL, fg="#8b95a3").grid(row=i, column=2, sticky="w", pady=4)
        self.enabled["beat2"] = tk.BooleanVar(value=self.cfg["beat2"]["enabled"])
        tk.Checkbutton(
            grid,
            text="2 ostatnie raporty EPS powyżej konsensusu",
            variable=self.enabled["beat2"], bg=PANEL, activebackground=PANEL,
        ).grid(row=len(self.NUMERIC), column=0, columnspan=3, sticky="w", pady=4)
        tk.Label(
            self,
            text="P/S bez dostępnych danych nie odrzuca spółki. Pozostałe włączone warunki wymagają danych.",
            bg=PANEL, fg="#8b95a3", wraplength=650, justify="left",
        ).pack(anchor="w", padx=14, pady=(8, 4))
        buttons = tk.Frame(self, bg=PANEL)
        buttons.pack(fill="x", padx=14, pady=12)
        tk.Button(buttons, text="Domyślne", command=self.reset_defaults, relief="flat").pack(side="left")
        tk.Button(buttons, text="Zapisz", command=self.save, relief="flat").pack(side="right")
        tk.Button(buttons, text="Anuluj", command=self.destroy, relief="flat").pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        self._sync_entries()

    def _sync_entries(self):
        for key, entry in self.entries.items():
            entry.configure(state="normal" if self.enabled[key].get() else "disabled")

    def _toggle_entry(self, key):
        entry = self.entries.get(key)
        if entry:
            entry.configure(state="normal" if self.enabled[key].get() else "disabled")

    def reset_defaults(self):
        self.cfg = calc.normalize_conditions(calc.DEFAULT_CONDITIONS)
        for key, enabled in self.enabled.items():
            enabled.set(self.cfg[key]["enabled"])
        for key, threshold in self.threshold.items():
            threshold.set(f"{self.cfg[key]['threshold']:g}")
        self._sync_entries()

    def save(self):
        conditions = {}
        for key, _label, _unit in self.NUMERIC:
            raw = self.threshold[key].get().strip().replace(",", ".")
            try:
                value = float(raw)
            except ValueError:
                messagebox.showerror("Nieprawidłowy próg", f"Wpisz liczbę dla warunku: {_label}.", parent=self)
                return
            if not math.isfinite(value) or (key == "ps" and value <= 0):
                messagebox.showerror("Nieprawidłowy próg", f"Próg dla warunku „{_label}” jest nieprawidłowy.", parent=self)
                return
            conditions[key] = {"enabled": self.enabled[key].get(), "threshold": value}
        conditions["beat2"] = {"enabled": self.enabled["beat2"].get()}
        self.app.store.settings["strategy_conditions"] = calc.normalize_conditions(conditions)
        self.app.store.save_settings()
        self.app.apply_strategy_conditions()
        self.destroy()


class FilterDialog(tk.Toplevel):
    """Filtry listy po kolumnach (wszystkie naraz): wartości tekstowe do zaznaczenia, liczby od–do; zmiany działają od razu."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Filtry listy")
        self.configure(bg=PANEL)
        apply_dark(self)
        self.vars = {}
        pre = tk.Frame(self, bg=PANEL)
        pre.pack(fill="x", padx=10, pady=(10, 6))
        tk.Label(pre, text="Gotowe:", bg=PANEL).pack(side="left")
        for name, f in FILTER_PRESETS:
            tk.Button(pre, text=name, relief="flat", command=lambda f=f: self.preset(f)).pack(side="left", padx=3)
        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill="both", padx=10)
        row = tk.Frame(self, bg=PANEL)
        row.pack(fill="x", padx=10, pady=10)
        tk.Button(row, text="Wyczyść filtry", command=lambda: self.preset({}), relief="flat").pack(side="left")
        tk.Button(row, text="Zamknij", command=self.destroy, relief="flat").pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.build()

    def filters(self):
        return self.app.store.settings.setdefault("list_filters", {})

    def build(self):
        for w in self.body.winfo_children():
            w.destroy()
        f, heads = self.filters(), {k: h for k, h, _, _ in COLUMNS}
        choices = {**FILTER_CHOICES, "sector": sorted({r["sector"] for r in self.app.store.rows if r.get("sector")})}
        r = 0
        for k, vals in choices.items():
            tk.Label(self.body, text=heads[k], bg=PANEL, fg="#8b95a3").grid(row=r, column=0, sticky="nw", pady=3)
            box = tk.Frame(self.body, bg=PANEL)
            box.grid(row=r, column=1, columnspan=3, sticky="w")
            on = (f.get(k) or {}).get("in") or []
            for i, v in enumerate(vals):
                var = tk.BooleanVar(value=v in on)
                tk.Checkbutton(box, text=v, variable=var, bg=PANEL, command=lambda k=k, v=v, var=var: self.toggle(k, v, var.get())).grid(row=i // 6, column=i % 6, sticky="w")
            r += 1
        for k, h, _, fm in COLUMNS:
            if fm not in "p%mn":
                continue
            tk.Label(self.body, text=h + (" (mln $)" if k in FILTER_SCALE else ""), bg=PANEL, fg="#8b95a3").grid(row=r, column=0, sticky="w", pady=2)
            for c, b in ((1, "min"), (3, "max")):
                v = (f.get(k) or {}).get(b)
                var = tk.StringVar(value="" if v is None else f"{v:g}")
                var.trace_add("write", lambda *_, k=k, b=b, var=var: self.number(k, b, var.get()))
                tk.Entry(self.body, textvariable=var, width=10).grid(row=r, column=c, padx=2)
                self.vars[(k, b)] = var
            tk.Label(self.body, text="do", bg=PANEL).grid(row=r, column=2)
            r += 1
        tk.Label(self.body, text="od", bg=PANEL, fg="#8b95a3").grid(row=r, column=1)

    def set(self, k, upd):
        f = {**(self.filters().get(k) or {}), **upd}
        f = {a: b for a, b in f.items() if b not in (None, [])}
        if f:
            self.filters()[k] = f
        else:
            self.filters().pop(k, None)
        self.app.store.save_settings()
        self.app.refresh()

    def toggle(self, k, v, on):
        cur = (self.filters().get(k) or {}).get("in") or []
        self.set(k, {"in": cur + [v] if on else [x for x in cur if x != v]})

    def number(self, k, b, raw):
        raw = raw.strip().replace(",", ".")
        try:
            v = None if raw in ("", "-") else float(raw)
        except ValueError:
            return
        self.set(k, {b: v})

    def preset(self, f):
        self.app.store.settings["list_filters"] = {k: dict(v) for k, v in f.items()}
        self.app.store.save_settings()
        self.app.refresh()
        self.build()


def pos_rows(store):
    """Wiersze panelu pozycji: (ticker, wartości kolumn, status) — status = lines.position_status (pusty = trzymaj)."""
    exit_m, out = store.settings.get("exit", "MACD"), []
    for t, p in store.alerts["pos"].items():
        r = store.row(t) or {}
        pl = lines.position_plan(p, store.weekly(t), r)
        last = pl["last"] if pl["last"] is not None else r.get("price")
        ch = (last / pl["entry"] - 1) * 100 if last and pl["entry"] else None
        ex = r.get("glb") if exit_m == "GLB" else r.get("macd_stop")
        st = lines.position_status(pl, r, exit_m)
        out.append((t, [t, " · ".join(st) or "trzymaj", p.get("since") or "", cell(pl["entry"], "p"), cell(last, "p"), cell(ch, "%"), cell(pl["peak"], "p"),
                        cell(pl["half_at"], "p"), cell(pl["stop_init"], "p"), cell(ex, "p"), r.get("glb_state") or "", r.get("macd") or ""], st))
    return out


def watch_rows(store):
    out = []
    for t in store.alerts["watch"]:
        if t in store.alerts["pos"]:
            continue
        r = store.row(t) or {}
        out.append((t, [t, cell(r.get("price"), "p"), cell(r.get("glb"), "p"), cell(r.get("glb_pct"), "%"), r.get("glb_state") or "", r.get("macd") or "",
                        cell(r.get("trend"), "b"), cell(r.get("rs"), "%"), cell(r.get("ok"), "b")]))
    return out


class PositionsDialog(tk.Toplevel):
    """📌 Pozycje (plan wyjścia i co zrobić teraz) i 🔔 obserwowane spółki; dwuklik = wykres."""
    POS = ("Ticker", "Co teraz", "Od", "Kupno", "Cena", "Zmiana %", "Szczyt", "½ przy", "Stop −10 %", "Wyjście", "GLB", "MACD")
    WATCH = ("Ticker", "Cena", "Green Line", "Do linii %", "GLB", "MACD", "SMA 10>30", "RS 52 tyg. pp", "Warunki")

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Pozycje i obserwowane")
        self.configure(bg=PANEL)
        apply_dark(self)
        m = app.store.settings.get("exit", "MACD")
        tk.Label(self, text=f"📌 POZYCJE · metoda wyjścia: {'pod GLB (zamknięcie tygodnia pod Green Line)' if m == 'GLB' else 'MACD (stop pod Low tygodnia przecięcia w dół)'}"
                 " · zawsze stop −10 % i ½ przy −20 % od szczytu · dwuklik = wykres", bg=PANEL, fg="#8b95a3").pack(anchor="w", padx=10, pady=(10, 4))
        self.pos = self._tree(self.POS, 8, "pos_columns")
        tk.Label(self, text="🔔 OBSERWOWANE (bez pozycji)", bg=PANEL, fg="#8b95a3").pack(anchor="w", padx=10, pady=(10, 4))
        self.watch = self._tree(self.WATCH, 8, "watch_columns")
        self.app._positions_dialog = self
        row = tk.Frame(self, bg=PANEL)
        row.pack(fill="x", padx=10, pady=10)
        tk.Button(row, text="Kolumny…", command=lambda: ColumnsDialog(self.app), relief="flat").pack(side="left")
        tk.Button(row, text="Edytuj wejście…", command=self.edit_entry, relief="flat").pack(side="left", padx=6)
        tk.Button(row, text="Usuń pozycję", command=self.del_pos, relief="flat").pack(side="left", padx=6)
        tk.Button(row, text="Przestań obserwować", command=self.del_watch, relief="flat").pack(side="left", padx=6)
        tk.Button(row, text="Zamknij", command=self.destroy, relief="flat").pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.fill()

    def _close(self):
        if getattr(self.app, "_positions_dialog", None) is self:
            self.app._positions_dialog = None
        self.destroy()

    def _tree(self, cols, h, setting_key):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=10)
        tr = ttk.Treeview(wrap, columns=cols, show="headings", height=h)
        for c in cols:
            tr.heading(c, text=c)
            tr.column(c, width=230 if c == "Co teraz" else 90 if c in ("Od", "RS 52 tyg. pp", "Green Line", "C/C[max]") else 75,
                      minwidth=230 if c == "Co teraz" else 90 if c in ("Od", "RS 52 tyg. pp", "Green Line", "C/C[max]") else 75,
                      anchor="w" if c in ("Ticker", "Co teraz", "GLB", "MACD") else "e", stretch=False)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tr.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=tr.xview)
        tr.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tr.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        tr["displaycolumns"] = self.app.store.settings.get(setting_key) or list(cols)
        tr.tag_configure("warn", foreground="#ffb020")
        tr.bind("<Double-1>", lambda e, t=tr: self.open(t))
        return tr

    def fill(self):
        for tr in (self.pos, self.watch):
            tr.delete(*tr.get_children())
        for t, vals, st in pos_rows(self.app.store):
            self.pos.insert("", "end", iid=t, values=vals, tags=("warn",) if st else ())
        for t, vals in watch_rows(self.app.store):
            self.watch.insert("", "end", iid=t, values=vals)

    def open(self, tr):
        s = tr.selection()
        if s:
            self.app.open_chart(s[0])

    def edit_entry(self):
        """Edytuj ręcznie datę i cenę wejścia dla wybranej pozycji."""
        selected = self.pos.selection()
        if not selected:
            messagebox.showinfo("Edytuj wejście", "Najpierw zaznacz pozycję.", parent=self)
            return
        ticker = selected[0]
        pos = self.app.store.alerts["pos"].get(ticker)
        if not pos:
            return
        dlg = tk.Toplevel(self)
        dlg.title(f"Edytuj wejście · {ticker}")
        dlg.configure(bg=PANEL)
        dlg.transient(self)
        dlg.grab_set()
        tk.Label(dlg, text=f"{ticker} — rzeczywiste wejście", bg=PANEL, fg=FG).pack(anchor="w", padx=12, pady=(12, 6))
        form = tk.Frame(dlg, bg=PANEL)
        form.pack(fill="x", padx=12)
        tk.Label(form, text="Data wejścia (RRRR-MM-DD)", bg=PANEL, fg=FG).grid(row=0, column=0, sticky="w", pady=4)
        date_var = tk.StringVar(value=pos.get("since") or "")
        tk.Entry(form, textvariable=date_var, width=18).grid(row=0, column=1, padx=(10, 0), pady=4)
        tk.Label(form, text="Cena kupna", bg=PANEL, fg=FG).grid(row=1, column=0, sticky="w", pady=4)
        price_var = tk.StringVar(value=str(pos.get("price") if pos.get("price") is not None else ""))
        tk.Entry(form, textvariable=price_var, width=18).grid(row=1, column=1, padx=(10, 0), pady=4)
        def save():
            date = date_var.get().strip()
            raw_price = price_var.get().strip().replace(",", ".")
            try:
                dt.date.fromisoformat(date)
                price = float(raw_price)
                if price <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                messagebox.showerror("Nieprawidłowe dane", "Podaj datę RRRR-MM-DD i cenę większą od zera.", parent=dlg)
                return
            pos["since"] = date
            pos["price"] = price
            self.app.store.save_alerts()
            self.app.refresh()
            self.fill()
            dlg.destroy()
        buttons = tk.Frame(dlg, bg=PANEL)
        buttons.pack(fill="x", padx=12, pady=12)
        tk.Button(buttons, text="Zapisz", command=save, relief="flat").pack(side="right", padx=(6, 0))
        tk.Button(buttons, text="Anuluj", command=dlg.destroy, relief="flat").pack(side="right")
        dlg.bind("<Return>", lambda e: save())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def del_pos(self):
        for t in self.pos.selection():
            self.app.store.alerts["pos"].pop(t, None)
        self._save()

    def del_watch(self):
        for tr in (self.pos, self.watch):
            for t in tr.selection():
                self.app.store.alerts["watch"].pop(t, None)
                if tr is self.pos:
                    self.app.store.alerts["pos"].pop(t, None)
        self._save()

    def _save(self):
        self.app.store.save_alerts()
        self.app.refresh()
        self.fill()


class ColumnsDialog(tk.Toplevel):
    """Wybór widocznych kolumn dla listy skanera, pozycji i obserwowanych; wybór zapisuje się w settings.json."""

    GROUPS = (
        ("Lista skanera", "main_columns", [(c[0], c[1]) for c in COLUMNS]),
        ("Pozycje", "pos_columns", [(c, c) for c in PositionsDialog.POS]),
        ("Obserwowane", "watch_columns", [(c, c) for c in PositionsDialog.WATCH]),
    )

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Widoczne kolumny")
        self.configure(bg=PANEL)
        apply_dark(self)
        self.vars = {}
        outer = tk.Frame(self, bg=PANEL)
        outer.pack(fill="both", expand=True, padx=12, pady=12)
        tk.Label(outer, text="Zaznacz kolumny, które chcesz widzieć. Zmiany zapisują się na przyszłe uruchomienia.",
                 bg=PANEL, fg="#8b95a3", wraplength=520, justify="left").pack(anchor="w", pady=(0, 8))
        for title, setting_key, choices in self.GROUPS:
            group = tk.LabelFrame(outer, text=title, bg=PANEL, fg="#c9d1d9", padx=8, pady=6)
            group.pack(fill="x", expand=False, pady=4)
            current = app.store.settings.get(setting_key)
            selected = set(current) if current else {key for key, _ in choices}
            for i, (key, label) in enumerate(choices):
                var = tk.BooleanVar(value=key in selected)
                self.vars[(setting_key, key)] = var
                cb = tk.Checkbutton(group, text=label, variable=var, bg=PANEL, anchor="w")
                cb.grid(row=i // 4, column=i % 4, sticky="w", padx=3, pady=1)
            for col in range(4):
                group.grid_columnconfigure(col, weight=1)
        buttons = tk.Frame(outer, bg=PANEL)
        buttons.pack(fill="x", pady=(10, 0))
        tk.Button(buttons, text="Wszystkie", command=self.select_all, relief="flat").pack(side="left")
        tk.Button(buttons, text="Zapisz", command=self.save, relief="flat").pack(side="right")
        tk.Button(buttons, text="Anuluj", command=self.destroy, relief="flat").pack(side="right", padx=6)
        self.bind("<Escape>", lambda e: self.destroy())

    def select_all(self):
        for var in self.vars.values():
            var.set(True)

    def save(self):
        for title, setting_key, choices in self.GROUPS:
            visible = [key for key, _ in choices if self.vars[(setting_key, key)].get()]
            if not visible:
                messagebox.showinfo("Kolumny", f"Wybierz przynajmniej jedną kolumnę: {title}.", parent=self)
                return
            self.app.store.settings[setting_key] = visible
            if setting_key == "main_columns":
                self.app.tree["displaycolumns"] = visible
            else:
                dialog = getattr(self.app, "_positions_dialog", None)
                if dialog is not None and dialog.winfo_exists():
                    tree = dialog.pos if setting_key == "pos_columns" else dialog.watch
                    tree["displaycolumns"] = visible
        self.app.store.save_settings()
        self.destroy()


class AlertsDialog(tk.Toplevel):
    """Dziennik alertów (nowe na górze), obserwowane spółki i spółki z liniami trendu; dwuklik otwiera wykres."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Alerty")
        self.configure(bg=PANEL)
        apply_dark(self)
        st = app.store.alerts
        tk.Label(self, text="Sprawdzane po starcie i po każdym Sync (zamknięcia tygodni). Dwuklik = wykres.", bg=PANEL, fg="#8b95a3").pack(anchor="w", padx=10, pady=(10, 4))
        self.lst = tk.Listbox(self, width=110, height=18, bg=BG, fg="#c9d1d9", selectbackground="#1f3a5f", relief="flat")
        self.lst.pack(fill="both", expand=True, padx=10)
        self.items = []
        for a in st["log"]:
            self.items.append(a["t"])
            self.lst.insert("end", f"{'● ' if a['at'] > st['seen'] else '  '}{a['t']:<7} {a['msg']}   (tydz. {a['week']}, {a['at'][:10]})")
        if not st["log"]:
            self.lst.insert("end", "Brak alertów.")
        self.lst.bind("<Double-1>", lambda e: self.open())
        info = (f"📌 Pozycje: {', '.join(t + (' ⚠' if (app.store.row(t) or {}).get('slow') else '') for t in st['pos']) or '—'}   ·   "
                f"Obserwowane: {', '.join(st['watch']) or '—'} (🔕 Obserwuj na wykresie)   ·   "
                f"Linie trendu: {', '.join(f'{t} ({len(v)})' for t, v in st['lines'].items()) or '—'}")
        autowrap(tk.Label(self, text=info, bg=PANEL, anchor="w", justify="left")).pack(fill="x", padx=10, pady=6)
        row = tk.Frame(self, bg=PANEL)
        row.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(row, text="Wyczyść", command=self.clear, relief="flat").pack(side="left")
        tk.Button(row, text="Zamknij", command=self.destroy, relief="flat").pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        st["seen"] = dt.datetime.now().isoformat(timespec="seconds")
        app.store.save_alerts()
        app.alert_badge()

    def open(self):
        sel = self.lst.curselection()
        if sel and sel[0] < len(self.items):
            self.app.open_chart(self.items[sel[0]])

    def clear(self):
        self.app.store.alerts["log"] = []
        self.app.store.save_alerts()
        self.destroy()


GUIDE = """WARUNKI (październik 2026) — tylko to, co w strategii GLB + MACD działało najmocniej (wszystkie sygnały 2015–2026, ceny bez korekty)
   przychody kwartału ≥ +15 % r/r	bez tego 34,9 % rocznie
   marża operacyjna ≥ +3 pp r/r	bez tego 28,9 %
   wycena P/S < 20	bez tego 31,5 % (drogie tracą; odpada też RGTI)
   siła względna 52 tyg. ≥ +50 pp nad S&P 500 (kolumna RS)	bez tego 21,4 %
   2 ostatnie raporty powyżej konsensusu EPS (kolumna „2× nad konsensus”)	bez tego 36,6 % (z nim 42,4 %)
Niespodzianki EPS (konsensus vs wynik, yfinance, od 2014): z warunkiem 42,4 % rocznie (2015–20 48,7 / 2021–26 36,4; 2020–26 53,7 %), +19,2 % na transakcję,
DD −51 %; spółki, które ostatnio zawiodły rynek: 3 % rocznie. Progi ≥ 5 / 10 % i przyspieszenie przychodów przez 2 kwartały — bez poprawy.
Rewizja EPS 90 dni (prognoza na przyszły rok dziś vs 90 dni temu) — tylko podgląd: brak historii do testu, zapisujemy ją co tydzień.
Razem (z niespodziankami EPS): +19,2 % na transakcję, portfel wszystkich sygnałów 42,4 % rocznie (2015–20: 48,7 %, 2021–26: 36,4 %; 2020–26: 53,7 %), S&P 500 13,6 %.
Cena za to: mało sygnałów naraz (średnio 2–4) i głębszy spadek portfela (−51 %).
Wspólny mianownik dużych ruchów po GLB: rosnące przychody i marża (fundamenty) + akcja już jest liderem rynku (siła względna).
Sama technika (GLB, średnie, RS bez fundamentów, wybicia dzienne w stylu Qullamaggie) w 2020–26 nie pobiła S&P 500.
Obrót nie jest warunkiem — płynność ustawiasz filtrem skanera w Finviz (np. średni wolumen). Backtest liczono na spółkach z obrotem ≥ 100 mln $
dziennie; przy mniej płynnych wyniki mogą być inne (sam obrót ≥ 50 mln $: +9,4 % zamiast +15,6 % na transakcję).
Usunięte, bo przy tych warunkach nic nie zmieniały: przychody kw. ≥ 25 mln $, zysk oper. w $ ↑, „Mocne” (Δ marży ≥ 10 pp), rozwodnienie, potencjał ★.

JAK WYGLĄDA DUŻY RUCH W RAPORTACH
Start: w dołku fundamenty są słabe (mediana: przychody +5 %, EPS −6 %, marża oper. −1 pp); poprawę widać 2–3 raporty później. Od wyprzedzenia jest Green Line.
Szczyt: kurs kończy ruch przy raporcie z najwyższym tempem wzrostu (EPS +33 %); kolejne raporty dalej dobre, ale wolniejsze (EPS +27 → +15 → +11 %).

WYJŚCIE — DWIE METODY (przycisk 🚪 na wykresie) + SPRZEDAŻ POŁOWY
   MACD (domyślna)	po przecięciu MACD tyg. w dół stop pod Low tego tygodnia (czerwona przerywana)
   pod GLB (jak Dr Wish)	sprzedaj, gdy tydzień zamknie się pod Green Line; linia stoi na poziomie wybicia, dopóki akcja robi nowe rekordy,
	a gdy szczyt przestoi 3 mies., staje się nową linią — trzymasz, póki trend trwa
   zawsze	stop 10 % pod ceną kupna; spadek 20 % od szczytu (zamknięcie tyg. od wejścia) = sprzedaj połowę (📌 alert, żółta przerywana „½ przy”)
Test 2015–2026 (pozycje po 20 % kapitału): metoda pod GLB trzyma największe ruchy (SNDK 09/25 +2409 %, MU 10/25 +472 %, NVDA 05/23 +221 %, PLTR 11/24
+169 %; z MACD +1833 / +115 / +3 / +28 %), ale 77–82 % transakcji to małe straty. Najlepiej z wejściem „przebicie GLB dowolnie wysoko” + warunki:
19,7 % rocznie (2020–26: 37,8 %), DD −51 %. Przy wejściu 0–10 % nad linią lepszy jest MACD: 22,2 % rocznie, DD −35 % (pod GLB 15,8 %, DD −41 %).
Sprzedaż połowy przy −20 % od szczytu: płytsze spadki portfela (MACD: −35 → −31 %, pod GLB: −51 → −45 %) za 1–3 pp rocznie (20,6 % i 17,2 %).

WEJŚCIE I WYJŚCIE
Kupno: tydzień przebicia GLB (poprzedni pod linią) przy dowolnej wysokości albo zamknięcie tyg. 0–10 % nad linią, na otwarciu następnego tygodnia;
gdy to kolejny tydzień i cena > 10 % nad linią — wejście po Blue Dot na dziennym (stan BLUE DOT; nie testowane wstecz w tym połączeniu). Stop 10 % pod wejściem — zleceniem (stop „na zamknięciu tygodnia”
dawał podobny wynik, ale straty 15–35 %). Po przecięciu MACD tyg. w dół stop pod Low tego tygodnia. Po wybiciu stopem wchodzisz ponownie przy następnym sygnale.
⚠ Hamowanie (kolumna Hamuje, alert dla 📌 pozycji): tempo przychodów spadło o ≥ 10 pp — spadek ≥ 20 % w 6 mies. w 44 % przypadków (normalnie 33 %);
⚠⚠ z marżą brutto spadającą r/r — 50 %, średnio −1,8 % po 3 i 6 mies. Wtedy zacieśnij stop albo nie dokładaj.

RWB + BLUE DOT (wykres dzienny, przycisk D / klawisz d) — do podglądu, NIE jako sygnał
Linia zamknięć, GMMA (6 szybkich EMA czerwonych / 6 wolnych niebieskich, jasne tło = RWB), ● Blue Dot (Stochastic 10,1 ↑ 20 przy RWB nad Green Line) i Green Line.
Test 2015–2026: RWB + nad GLB + Blue Dot, stop pod Low kropki, wyjście MACD: tylko +1,0…+1,2 % na transakcję, trafność 14–15 %.

CZEGO NIE SZUKAĆ (nic nie wnosiło)
ROE / ROI, Blue Dot jako wejście, stan MACD przy wejściu, trend S&P 500, wolumen wybicia, długość bazy, kup +0,1 % / sprzedaj −0,1 % przy linii
(dziennie: −0,3 % rocznie), samo przyspieszenie przychodów, poziom marży brutto i operacyjnej, sam EPS, zmiana marży kwartał do kwartału.
Wykres tygodniowy: S&P 500 nad ceną = kierunek rynku; słupki przychodów pod wolumenem — zielony ≥ +25 % r/r, żółty ≥ +15 %.

Heurystyka z backtestu na spółkach notowanych dziś (bez wycofanych z giełdy), nie porada inwestycyjna."""


def checklist(row, pos=None, conditions=None):
    """Lista kontrolna spółki -> linie tekstu, zgodnie z konfigurowalnymi warunkami koniecznymi."""
    cfg = calc.normalize_conditions(conditions)

    def yes(v):
        return "✓" if v is True else "✗" if v is False else "—"

    def f(v, u):
        return "—" if v is None else f"{v:+.1f}{u}"

    def cond(v, test):
        return None if v is None else test(v)

    def criterion(enabled, result, label):
        return f"{yes(result)} {label}" if enabled else f"— Kryterium wyłączone: {label}"

    r = row
    ps_txt = f"{r['ps']:.1f}" if r.get("ps") else "—"
    t_txt = f"{r['turnover'] / 1e6:.0f}" if r.get("turnover") else "—"
    lines_ = [f"{r['ticker']} {r.get('company') or ''} — {'spełnia warunki' if r.get('ok') else 'nie spełnia warunków'}"
              + (f" · 📌 pozycja od {pos['since']} ({pos['price']:.2f})" if pos and pos.get("price") else ""),
              f"Przychody {f(r.get('rev_rr'), ' %')} r/r (kwartał wcześniej {f(r.get('rev_rr1'), ' %')}), Δ marży oper. {f(r.get('dopm'), ' pp')} "
              f"(wcześniej {f(r.get('dopm1'), ' pp')}), marża oper. {f(r.get('opm'), ' %')} · kwartał {r.get('quarter') or '—'}", "",
              f"Obrót {t_txt} mln $ dziennie (bez progu — płynność ustawiasz filtrem w Finviz)",
              criterion(cfg["rev_growth"]["enabled"],
                        cond(r.get("rev_rr"), lambda v: v >= cfg["rev_growth"]["threshold"]),
                        f"Przychody kw. ≥ +{cfg['rev_growth']['threshold']:g} % r/r ({f(r.get('rev_rr'), ' %')})"),
              criterion(cfg["op_margin"]["enabled"],
                        cond(r.get("dopm"), lambda v: v >= cfg["op_margin"]["threshold"]),
                        f"Marża oper. ≥ +{cfg['op_margin']['threshold']:g} pp r/r ({f(r.get('dopm'), ' pp')})"),
              criterion(cfg["ps"]["enabled"], cond(r.get("ps"), lambda v: v < cfg["ps"]["threshold"]),
                        f"Wycena P/S < {cfg['ps']['threshold']:g} ({ps_txt})"),
              criterion(cfg["rs"]["enabled"], cond(r.get("rs"), lambda v: v >= cfg["rs"]["threshold"]),
                        f"Siła względna 52 tyg. ≥ +{cfg['rs']['threshold']:g} pp nad S&P 500 ({f(r.get('rs'), ' pp')})"),
              criterion(cfg["beat2"]["enabled"], r.get("beat2"),
                        f"2 ostatnie raporty powyżej konsensusu EPS ({f(r.get('surp'), ' %')}, wcześniej {f(r.get('surp_prev'), ' %')})"),
              f"{yes(cond(r.get('eps_rev'), lambda v: v > 0))} Rewizja prognozy EPS na przyszły rok, 90 dni: {f(r.get('eps_rev'), ' %')} (podgląd, bez backtestu)"]
    st = r.get("glb_state")
    lines_.append(f"{yes(True if st in SIGNAL else None if st == 'NAD' else False)} Green Line: {st or '—'} ({f(r.get('glb_pct'), ' %')} od linii; kupno: tydzień przebicia dowolnie wysoko, 0–10 % nad albo Blue Dot na dziennym, gdy > 10 %)")
    stop = f"{r['macd_stop']:.2f}" if r.get("macd_stop") else "—"
    lines_.append(f"{yes(r.get('macd') == 'nad')} MACD tyg. {r.get('macd') or '—'} sygnałem (stop pod {stop})")
    glb = r.get("glb")
    lines_.append(f"{yes(None if glb is None or r.get('price') is None else r['price'] >= glb)} Zamknięcie nad Green Line {glb if glb is not None else '—'} "
                  f"(wyjście metodą GLB: zamknięcie tygodnia pod linią)")
    lines_.append(f"{yes(False if r.get('slow') else None if r.get('accel') is None else True)} Brak hamowania (tempo przychodów {f(r.get('accel'), ' pp')}, "
                  f"Δ marży brutto {f(r.get('dgm'), ' pp')})")
    if pos and r.get("slow"):
        lines_ += ["", f"⚠ Masz pozycję, a ostatni raport pokazuje hamowanie{' i spadek marży brutto' if r['slow'] == 'HAMUJE+MB' else ''} — spadek ≥ 20 % w 6 mies. "
                       f"w {'50' if r['slow'] == 'HAMUJE+MB' else '44'} % przypadków (normalnie 33 %). Rozważ zacieśnienie stopu."]
    return lines_


class GrowthScoreDialog(tk.Toplevel):
    """Ranking Growth Score; rozwijany panel pokazuje wejścia i punkty każdej składowej."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.descending = True
        self.show_components = False
        self.title("Growth Score — ranking wzrostu")
        self.geometry("390x650")
        self.minsize(330, 350)
        self.configure(bg=PANEL)
        apply_dark(self)
        self.transient(app.root)
        tk.Label(self, text="Growth Score · bieżący skaner", bg=PANEL, fg=FG,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        self.count_label = tk.Label(self, text="", bg=PANEL, fg="#8b95a3", anchor="w")
        self.count_label.pack(fill="x", padx=12, pady=(0, 8))

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=10)
        self.tree = ttk.Treeview(wrap, columns=("ticker", "score"), show="headings", height=24, selectmode="browse")
        self.tree.heading("ticker", text="Ticker")
        self.tree.heading("score", text="Score ↓", command=self.toggle_sort)
        self.tree.column("ticker", width=190, minwidth=130, anchor="w", stretch=True)
        self.tree.column("score", width=100, minwidth=80, anchor="e", stretch=False)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        self.tree.tag_configure("high", foreground="#3ddc84")
        self.tree.bind("<ButtonRelease-1>", self.on_cell_click)
        self.tree.bind("<<TreeviewSelect>>", self.update_components)
        self.tree.bind("<Double-1>", self.open_selected)
        self.tree.bind("<Return>", self.open_selected)

        # Panel jest domyślnie zwinięty, tak jak panel fundamentów na wykresie.
        self.detail_frame = tk.Frame(self, bg=PANEL)
        self.detail_heading = tk.Label(
            self.detail_frame, text="Składowe Growth Score", bg=PANEL, fg=FG,
            font=("Segoe UI", 10, "bold"), anchor="w"
        )
        self.detail_heading.pack(fill="x", padx=12, pady=(4, 2))
        self.detail_text = tk.Text(
            self.detail_frame, bg="#151a21", fg="#dde3ea", relief="flat", wrap="word",
            font=("Segoe UI", 9), padx=10, pady=7, height=8, highlightthickness=0,
            cursor="arrow", state="disabled"
        )
        self.detail_text.tag_configure("h", font=("Segoe UI", 10, "bold"), foreground="#ffffff")
        self.detail_text.tag_configure("good", foreground="#3ddc84")
        self.detail_text.tag_configure("muted", foreground="#8b95a3")
        self.detail_text.pack(fill="x", padx=10, pady=(0, 4))

        self.weights_label = tk.Label(
            self,
            text=("Wagi: przyspieszenie wzrostu 30, zaskoczenia EPS 20, przyszły wzrost/revizje 20, "
                  "jakość biznesu 20, trwałość wzrostu 10. Braki danych są pomijane; score pokazujemy "
                  "przy pokryciu co najmniej 70/100. ROIC jest estymowany z SEC; trwałość opiera się na historii, a katalizatory wymagają ręcznej oceny."),
            bg=PANEL, fg="#8b95a3", justify="left", wraplength=365, anchor="w"
        )
        self.weights_label.pack(fill="x", padx=12, pady=(8, 4))
        buttons = tk.Frame(self, bg=PANEL)
        buttons.pack(fill="x", padx=10, pady=(4, 10))
        self.components_btn = tk.Button(
            buttons, text="▸ Składowe score", command=self.toggle_components, relief="flat"
        )
        self.components_btn.pack(side="left", padx=(0, 4))
        tk.Button(buttons, text="Katalizator…", command=self.edit_catalyst, relief="flat").pack(side="left", padx=(0, 4))
        tk.Button(buttons, text="Odśwież", command=self.fill, relief="flat").pack(side="left")
        tk.Button(buttons, text="Zamknij", command=self.close, relief="flat").pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.close)
        app.growth_dialog = self
        self.fill()

    @staticmethod
    def _fmt_value(value, suffix=""):
        if value is None:
            return "brak danych"
        try:
            return f"{float(value):+.1f}{suffix}".replace(".", ",")
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _fmt_points(points, weight):
        return "brak danych · pominięte" if points is None else f"{points:.1f}/{weight} pkt".replace(".", ",")

    def fill(self):
        selected = self.tree.selection()
        selected_ticker = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        rows = []
        for row in self.app.store.rows:
            ticker = row.get("ticker")
            if not ticker:
                continue
            assessment = (self.app.store.settings.get("growth_catalysts") or {}).get(ticker) or {}
            result = calc.growth_score({**row, "catalyst_score": assessment.get("score")})
            rows.append((ticker, result["score"], result["coverage"]))
        def key(item):
            ticker, score, _ = item
            if score is None:
                return (1, 0.0, ticker)
            return (0, -score if self.descending else score, ticker)
        rows.sort(key=key)
        rows = rows[:10]
        for ticker, score, coverage in rows:
            shown = f"{score:.1f}" if score is not None else "—"
            tags = ("high",) if score is not None and score >= 75 else ()
            self.tree.insert("", "end", iid=ticker, values=(ticker, shown), tags=tags)
        scored = sum(1 for _, score, _ in rows if score is not None)
        self.count_label.config(text=f"{scored} z {len(rows)} spółek ma wystarczające dane · sortowanie po score")
        if selected_ticker in self.tree.get_children():
            self.tree.selection_set(selected_ticker)
        elif self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
        self.update_components()

    def toggle_sort(self):
        self.descending = not self.descending
        self.tree.heading("score", text=f"Score {'↓' if self.descending else '↑'}", command=self.toggle_sort)
        self.fill()

    def toggle_components(self):
        self.show_components = not self.show_components
        if self.show_components:
            self.detail_frame.pack(fill="x", padx=10, pady=(0, 4), before=self.weights_label)
            self.components_btn.config(text="▾ Ukryj składowe")
            if not self.tree.selection() and self.tree.get_children():
                self.tree.selection_set(self.tree.get_children()[0])
            self.update_components()
        else:
            self.detail_frame.pack_forget()
            self.components_btn.config(text="▸ Składowe score")

    def update_components(self, _event=None):
        if not self.show_components:
            return
        selected = self.tree.selection()
        ticker = selected[0] if selected else None
        row = next((r for r in self.app.store.rows if r.get("ticker") == ticker), None)
        if row is None:
            content = "Zaznacz spółkę w rankingu, aby zobaczyć szczegóły."
        else:
            assessment = (self.app.store.settings.get("growth_catalysts") or {}).get(ticker) or {}
            result = calc.growth_score({**row, "catalyst_score": assessment.get("score")})
            score = "brak (za małe pokrycie)" if result["score"] is None else f"{result['score']:.1f}/100".replace(".", ",")
            content = (
                f"{ticker} · Growth Score: {score}\n"
                f"Pokrycie danych: {result['coverage']:.0f}/100 pkt wag; wynik = suma punktów ÷ dostępne wagi × 100\n"
            )
            components = result["components"]
            specs = (
                ("acceleration", "Przyspieszenie wzrostu", None, "", 30),
                ("surprises", "Zaskoczenia EPS + przychodów", row.get("surp"), "%", 20),
                ("future", "Przyszły wzrost / rewizje EPS", row.get("eps_rev"), "%", 20),
                ("quality", "Jakość biznesu (marża + ROIC)", row.get("roic"), "%", 20),
                ("durability", "Trwałość wzrostu (katalizator / proxy)", assessment.get("score"), "/10", 10),
            )
            content += "\\n"
            for key, label, value, suffix, weight in specs:
                content += f"{label}: {self._fmt_value(value, suffix)} → {self._fmt_points(components.get(key), weight)} (pokrycie {result['component_coverage'].get(key, 0)}/{weight})\\n"
            content += (
                f"EPS surprise (najnowszy / poprzedni): "
                f"{self._fmt_value(row.get('surp'), '%')} / {self._fmt_value(row.get('surp_prev'), '%')}\\n"
                f"Revenue surprise (ostatni raport): {self._fmt_value(row.get('rev_surp'), '%')}\\n"
                f"ROIC (szacunek SEC): {self._fmt_value(row.get('roic'), '%')}\\n"
                f"Katalizator / uzasadnienie: {assessment.get('note') or 'brak ręcznej oceny; użyto proxy historii przychodów'}\\n"
                f"Suma punktów: {result['points']:.1f}/{result['coverage']:.0f} dostępnych wag".replace(".", ",")
            )
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", content)
        if row is not None:
            self.detail_text.tag_add("h", "1.0", "1.end")
        self.detail_text.configure(state="disabled")

    def edit_catalyst(self):
        selected = self.tree.selection()
        ticker = selected[0] if selected else None
        if not ticker:
            messagebox.showinfo("Growth Score", "Najpierw zaznacz spółkę w rankingu.")
            return
        saved = (self.app.store.settings.get("growth_catalysts") or {}).get(ticker) or {}
        score = simpledialog.askinteger(
            "Ocena katalizatora",
            f"{ticker}: oceń wiarygodność dalszego wzrostu w skali 0–10.\nUwzględnij popyt, nowe produkty, kontrakty lub ekspansję.",
            parent=self, minvalue=0, maxvalue=10, initialvalue=saved.get("score")
        )
        if score is None:
            return
        note = simpledialog.askstring(
            "Uzasadnienie katalizatora", "Wpisz konkretny powód dalszego wzrostu (produkt, kontrakt, popyt):",
            parent=self, initialvalue=saved.get("note", "")
        )
        if note is None:
            return
        all_scores = self.app.store.settings.setdefault("growth_catalysts", {})
        all_scores[ticker] = {"score": score, "note": note.strip()}
        self.app.store.save_settings()
        self.fill()
        self.update_components()

    def on_cell_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        ticker = self.tree.identify_row(event.y)
        if not ticker:
            return
        self.tree.selection_set(ticker)
        self.tree.focus(ticker)
        if self.tree.identify_column(event.x) == "#1":
            self.app.open_chart(ticker)
        else:
            self.update_components()

    def open_selected(self, event=None):
        selected = self.tree.selection()
        if selected:
            self.app.open_chart(selected[0])

    def close(self):
        if getattr(self.app, "growth_dialog", None) is self:
            self.app.growth_dialog = None
        self.destroy()


class GuideDialog(tk.Toplevel):
    """📖 Poradnik: zasady z badań + lista kontrolna spółki otwartej na wykresie (albo zaznaczonej na liście)."""

    def __init__(self, app):
        super().__init__(app.root)
        self.title("Poradnik — czego szukać w spółce")
        self.configure(bg=PANEL)
        apply_dark(self)
        t = app.chart.ticker if app.chart is not None and app.chart.winfo_exists() else app.current()
        row = app.store.row(t) if t else None
        self.geometry("1000x900")
        txt = tk.Text(self, bg="#151a21", fg="#e1e6ec", relief="flat", wrap="word", font=("Segoe UI", 12), padx=28, pady=18,
                      spacing1=4, spacing2=3, spacing3=4, tabs=("540",), highlightthickness=0)
        txt.tag_configure("h", font=("Segoe UI", 15, "bold"), foreground="#ffffff", spacing1=18, spacing3=6)
        txt.tag_configure("ok", foreground="#3ddc84")
        txt.tag_configure("no", foreground="#ff5c5c")
        txt.tag_configure("warn", foreground="#ffb020")
        if row:
            for n, ln in enumerate(checklist(row, app.store.alerts["pos"].get(t), app.store.settings.get("strategy_conditions"))):
                tag = "h" if n == 0 else "ok" if ln.startswith("✓") else "no" if ln.startswith("✗") else "warn" if ln.startswith("⚠") else ""
                txt.insert("end", ln + "\n", tag)
        else:
            txt.insert("end", "Zaznacz spółkę na liście albo otwórz wykres, żeby zobaczyć jej listę kontrolną.\n")
        txt.insert("end", "\n")
        for ln in GUIDE.split("\n"):
            txt.insert("end", ln + "\n", "h" if ln[:2].rstrip(".").isdigit() else "")
        txt.config(state="disabled")
        tk.Button(self, text="Zamknij", command=self.destroy, relief="flat").pack(side="bottom", pady=10)
        sb = ttk.Scrollbar(self, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)
        self.bind("<Escape>", lambda e: self.destroy())


class SymbolDialog(tk.Toplevel):
    """Ctrl+K: spółka z listy otwiera się od razu, każda inna (np. SPY, ^GSPC) jest pobierana z yfinance (i SEC, jeśli to spółka z USA)."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app, self.q = app, queue.Queue()
        self.title("Szukaj symbolu")
        self.configure(bg=PANEL)
        apply_dark(self)
        tk.Label(self, text="Symbol (np. NVDA, SPY, ^GSPC) i Enter:", bg=PANEL).pack(padx=12, pady=(10, 4))
        self.var = tk.StringVar()
        box = ttk.Combobox(self, textvariable=self.var, values=app.store.settings.get("symbols", []), width=24)
        box.pack(padx=12)
        box.focus_set()
        self.msg = tk.Label(self, text="", bg=PANEL, fg="#8b95a3", wraplength=300)
        self.msg.pack(padx=12, pady=8)
        box.bind("<Return>", lambda e: self.go())
        self.bind("<Escape>", lambda e: self.destroy())

    def go(self):
        sym = self.var.get().strip().upper()
        if not sym:
            return
        if self.app.store.row(sym):   # policzona spółka (lista skanera albo wcześniejszy Ctrl+K) — od razu; same świece z innego skanera to za mało
            self.done(sym)
            return
        self.msg.config(text=f"Pobieram {sym}…")

        def work():
            try:
                sync.symbol(sym, self.app.store, log=lambda s: None)
                self.q.put(("ok", sym))
            except Exception as e:
                self.q.put(("err", str(e)))
        threading.Thread(target=work, daemon=True).start()
        self.after(150, self.poll)

    def poll(self):
        try:
            kind, val = self.q.get_nowait()
        except queue.Empty:
            self.after(150, self.poll)
            return
        if kind == "ok":
            self.done(val)
        else:
            self.msg.config(text=val, fg="#ff5c5c")

    def done(self, sym):
        s = self.app.store.settings
        s["symbols"] = [sym] + [x for x in s.get("symbols", []) if x != sym][:14]
        self.app.store.save_settings()
        self.destroy()
        self.app.open_chart(sym)


def main():
    try:
        App().run()
    except tk.TclError as e:
        messagebox.showerror("Momentum Desktop", str(e))
