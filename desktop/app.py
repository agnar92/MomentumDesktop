"""Główne okno: jedna lista (skan Finviz + warunki strategii), Sync, ustawienia filtra i wykres tygodniowy. Ctrl+K = dowolny symbol."""
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import datetime as dt

from . import calc, finviz, lines, sec, sync
from .chart import ChartWindow
from .store import DEFAULT_SCANNERS, Store, normalize_scanners
from .theme import BG, PANEL, apply_dark, autowrap, setup_style

COLUMNS = [  # (klucz, nagłówek, szerokość, format)
    ("ticker", "Ticker", 70, "s"), ("company", "Spółka", 200, "s"), ("sector", "Sektor", 140, "s"), ("price", "Cena", 80, "p"),
    ("glb", "Green Line", 90, "p"), ("glb_pct", "Do linii %", 85, "%"), ("glb_state", "GLB", 85, "s"), ("macd", "MACD", 60, "s"),
    ("macd_stop", "Stop MACD", 85, "p"), ("dopm", "Δ marża oper. pp", 120, "%"), ("rev_rr", "Przychody r/r %", 115, "%"),
    ("dgm", "Δ marża brutto pp", 125, "%"), ("quarter", "Kwartał", 105, "s"), ("turnover", "Obrót mln $", 95, "m"),
    ("ps", "P/S", 60, "x"), ("rs", "RS 52 tyg. pp", 105, "%"), ("ok", "Warunki", 75, "b"), ("slow", "Hamuje", 95, "w"),
]
SIGNAL = ("WYBICIE", "SYGNAŁ")
# filtry listy (wszystkie naraz, ORAZ): {kolumna: {"in": [wartości]} | {"min", "max"}}; liczby w jednostkach tabeli (obrót w mln $)
FILTER_CHOICES = {"glb_state": ["WYBICIE", "SYGNAŁ", "NAD", "POD", "BRAK"], "macd": ["nad", "pod"], "ok": ["tak", "nie"], "slow": ["HAMUJE", "HAMUJE+MB", "—"]}
FILTER_SCALE = {"turnover": 1e6}
FILTER_PRESETS = [
    ("Sygnał kupna: warunki + 0–10 % nad GLB", {"ok": {"in": ["tak"]}, "glb_state": {"in": ["WYBICIE", "SYGNAŁ"]}}),
    ("Liderzy: RS 52 tyg. ≥ 50 pp + nad GLB", {"rs": {"min": 50}, "glb_state": {"in": ["WYBICIE", "SYGNAŁ", "NAD"]}}),
    ("Nad GLB + MACD dodatni", {"glb_state": {"in": ["WYBICIE", "SYGNAŁ", "NAD"]}, "macd": {"in": ["nad"]}}),
    ("Sygnał kupna + MACD dodatni", {"glb_state": {"in": ["WYBICIE", "SYGNAŁ"]}, "macd": {"in": ["nad"]}}),
    ("Blisko linii (−10…+10 %)", {"glb_pct": {"min": -10, "max": 10}}),
]


def filter_value(r, k):
    if k == "ok":
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
        self.only_ok = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="tylko spełniające warunki", variable=self.only_ok, command=self.refresh, bg=PANEL).pack(side="left", padx=8)
        self.flt_btn = tk.Button(bar, text="Filtry…", command=lambda: FilterDialog(self), relief="flat")
        self.flt_btn.pack(side="left", padx=4)
        tk.Label(bar, text="Szukaj:", bg=PANEL).pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh())
        tk.Entry(bar, textvariable=self.search, width=12, relief="flat").pack(side="left", padx=4)
        tk.Button(bar, text="📖 Poradnik", command=lambda: GuideDialog(self), relief="flat").pack(side="left", padx=4)
        self.alert_btn = tk.Button(bar, text="🔔 Alerty", command=lambda: AlertsDialog(self), relief="flat")
        self.alert_btn.pack(side="left", padx=4)
        tk.Label(bar, text="Ctrl+K — dowolny symbol (np. SPY, NVDA)", bg=PANEL, fg="#8b95a3").pack(side="left", padx=12)
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        for key, head, width, _ in COLUMNS:
            self.tree.heading(key, text=head, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, anchor="w" if key in ("ticker", "company", "sector", "glb_state", "macd") else "e", stretch=key == "company")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
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
        self.status.config(text=f"  Skaner: {self.store.settings['scanner']}   Dane: {self.store.at or 'brak — kliknij ⟳ Sync'}   Na liście: {len(self.tree.get_children())} z {len(self.store.rows)}   spełnia warunki: {n_ok}   sygnał GLB: {n_sig}"
                                f"   (warunki: obrót ≥ {calc.MIN_TURNOVER / 1e6:.0f} mln $, przychody ≥ +{calc.MIN_REV_GROWTH:.0f} %, marża oper. ≥ +{calc.MIN_DOPM:.0f} pp r/r,"
                                f" P/S < {calc.MAX_PS:.0f}, RS 52 tyg. ≥ +{calc.MIN_RS:.0f} pp;"
                                f" sygnał: zamknięcie tyg. 0–{calc.ENTRY_MAX_PCT:.0f} % nad Green Line; wyjście: MACD tyg. + stop {calc.STOP_PCT:.0f} %)")

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
        if self.sync_btn["state"] == "disabled":
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

    def open_symbol(self):
        SymbolDialog(self)

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
    def check_alerts(self):
        st = self.store
        weeks = [s["d"][-1] for s in st.series.values() if s and s.get("d")]
        fresh = lines.eval_alerts(st.alerts, st.row, st.weekly, dt.datetime.now().isoformat(timespec="seconds"), max(weeks) if weeks else "")
        st.save_alerts()
        self.alert_badge()
        if fresh:
            self.status.config(text=f"  🔔 {len(fresh)} nowych alertów: " + " · ".join(f"{a['t']} {a['msg']}" for a in fresh[:3]))

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
   obrót ≥ 100 mln $ dziennie	odcina małe, dziwne spółki
   przychody kwartału ≥ +15 % r/r	bez tego 34,9 % rocznie
   marża operacyjna ≥ +3 pp r/r	bez tego 28,9 %
   wycena P/S < 20	bez tego 31,5 % (drogie tracą; odpada też RGTI)
   siła względna 52 tyg. ≥ +50 pp nad S&P 500 (kolumna RS)	bez tego 21,4 %
Razem: +15,6 % na transakcję, portfel wszystkich sygnałów 36,6 % rocznie (2015–20: 43,9 %, 2021–26: 29,6 %; same lata 2020–26: 46,5 %), S&P 500 13,6 %.
Cena za to: mało sygnałów naraz (średnio 2–4) i głębszy spadek portfela (−55 %).
Wspólny mianownik dużych ruchów po GLB: rosnące przychody i marża (fundamenty) + akcja już jest liderem rynku (siła względna).
Sama technika (GLB, średnie, RS bez fundamentów, wybicia dzienne w stylu Qullamaggie) w 2020–26 nie pobiła S&P 500.
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
Kupno: zamknięcie tygodnia 0–10 % nad Green Line, na otwarciu następnego tygodnia. Stop 10 % pod wejściem — zleceniem (stop „na zamknięciu tygodnia”
dawał podobny wynik, ale straty 15–35 %). Po przecięciu MACD tyg. w dół stop pod Low tego tygodnia. Po wybiciu stopem wchodzisz ponownie przy następnym sygnale.
⚠ Hamowanie (kolumna Hamuje, alert dla 📌 pozycji): tempo przychodów spadło o ≥ 10 pp — spadek ≥ 20 % w 6 mies. w 44 % przypadków (normalnie 33 %);
⚠⚠ z marżą brutto spadającą r/r — 50 %, średnio −1,8 % po 3 i 6 mies. Wtedy zacieśnij stop albo nie dokładaj.

RWB + BLUE DOT (wykres dzienny, 📅 / klawisz D) — do podglądu, NIE jako sygnał
Linia zamknięć, GMMA (6 szybkich EMA czerwonych / 6 wolnych niebieskich, jasne tło = RWB), ● Blue Dot (Stochastic 10,1 ↑ 20 przy RWB nad Green Line) i Green Line.
Test 2015–2026: RWB + nad GLB + Blue Dot, stop pod Low kropki, wyjście MACD: tylko +1,0…+1,2 % na transakcję, trafność 14–15 %.

CZEGO NIE SZUKAĆ (nic nie wnosiło)
ROE / ROI, Blue Dot jako wejście, stan MACD przy wejściu, trend S&P 500, wolumen wybicia, długość bazy, kup +0,1 % / sprzedaj −0,1 % przy linii
(dziennie: −0,3 % rocznie), samo przyspieszenie przychodów, poziom marży brutto i operacyjnej, sam EPS, zmiana marży kwartał do kwartału.
Wykres tygodniowy: S&P 500 nad ceną = kierunek rynku; słupki przychodów pod wolumenem — zielony ≥ +25 % r/r, żółty ≥ +15 %.

Heurystyka z backtestu na spółkach notowanych dziś (bez wycofanych z giełdy), nie porada inwestycyjna."""


def checklist(row, pos=None):
    """Lista kontrolna spółki -> linie tekstu."""
    def yes(v):
        return "✓" if v is True else "✗" if v is False else "—"

    def f(v, u):
        return "—" if v is None else f"{v:+.1f}{u}"

    def cond(v, test):
        return None if v is None else test(v)
    r = row
    ps_txt = f"{r['ps']:.1f}" if r.get("ps") else "—"
    t_txt = f"{r['turnover'] / 1e6:.0f}" if r.get("turnover") else "—"
    lines_ = [f"{r['ticker']} {r.get('company') or ''} — {'spełnia warunki' if r.get('ok') else 'nie spełnia warunków'}"
              + (f" · 📌 pozycja od {pos['since']} ({pos['price']:.2f})" if pos and pos.get("price") else ""),
              f"Przychody {f(r.get('rev_rr'), ' %')} r/r (kwartał wcześniej {f(r.get('rev_rr1'), ' %')}), Δ marży oper. {f(r.get('dopm'), ' pp')} "
              f"(wcześniej {f(r.get('dopm1'), ' pp')}), marża oper. {f(r.get('opm'), ' %')} · kwartał {r.get('quarter') or '—'}", "",
              f"{yes(cond(r.get('turnover'), lambda v: v >= calc.MIN_TURNOVER))} Obrót ≥ 100 mln $ dziennie ({t_txt} mln $)",
              f"{yes(cond(r.get('rev_rr'), lambda v: v >= calc.MIN_REV_GROWTH))} Przychody kw. ≥ +15 % r/r ({f(r.get('rev_rr'), ' %')})",
              f"{yes(cond(r.get('dopm'), lambda v: v >= calc.MIN_DOPM))} Marża oper. ≥ +3 pp r/r ({f(r.get('dopm'), ' pp')})",
              f"{yes(cond(r.get('ps'), lambda v: v < calc.MAX_PS))} Wycena P/S < 20 ({ps_txt})",
              f"{yes(cond(r.get('rs'), lambda v: v >= calc.MIN_RS))} Siła względna 52 tyg. ≥ +50 pp nad S&P 500 ({f(r.get('rs'), ' pp')})"]
    st = r.get("glb_state")
    lines_.append(f"{yes(True if st in SIGNAL else None if st == 'NAD' else False)} Green Line: {st or '—'} ({f(r.get('glb_pct'), ' %')} od linii; kupno 0–10 % nad)")
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
            for n, ln in enumerate(checklist(row, app.store.alerts["pos"].get(t))):
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
        if self.app.store.weekly(sym):
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
