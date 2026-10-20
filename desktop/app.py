"""Główne okno: jedna lista (skan Finviz + warunki strategii), Sync, ustawienia filtra i wykres tygodniowy. Ctrl+K = dowolny symbol."""
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import calc, finviz, sec, sync
from .chart import ChartWindow
from .store import Store
from .theme import BG, PANEL, apply_dark, autowrap, setup_style

COLUMNS = [  # (klucz, nagłówek, szerokość, format)
    ("ticker", "Ticker", 70, "s"), ("company", "Spółka", 200, "s"), ("sector", "Sektor", 140, "s"), ("price", "Cena", 80, "p"),
    ("glb", "Green Line", 90, "p"), ("glb_pct", "Do linii %", 85, "%"), ("glb_state", "GLB", 85, "s"), ("macd", "MACD", 60, "s"),
    ("macd_stop", "Stop MACD", 85, "p"), ("dopm", "Δ marża oper. pp", 120, "%"), ("rev_rr", "Przychody r/r %", 115, "%"),
    ("dgm", "Δ marża brutto pp", 125, "%"), ("quarter", "Kwartał", 105, "s"), ("turnover", "Obrót mln $", 95, "m"),
    ("ok", "Warunki", 75, "b"),
]
SIGNAL = ("WYBICIE", "SYGNAŁ")


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
    return str(v)


def default_order(r):
    """Najpierw spółki spełniające warunki z sygnałem GLB, potem spełniające warunki, w grupie od największej zmiany marży operacyjnej."""
    return (not (r.get("ok") and r.get("glb_state") in SIGNAL), not r.get("ok"), -(r.get("dopm") if r.get("dopm") is not None else -1e9))


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
        tk.Button(bar, text="Filtr Finviz / ustawienia…", command=self.open_settings, relief="flat").pack(side="left", padx=4)
        self.only_ok = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="tylko spełniające warunki", variable=self.only_ok, command=self.refresh, bg=PANEL).pack(side="left", padx=8)
        tk.Label(bar, text="Szukaj:", bg=PANEL).pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh())
        tk.Entry(bar, textvariable=self.search, width=12, relief="flat").pack(side="left", padx=4)
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
        self.tree.bind("<Double-1>", lambda e: self.open_chart(self.current()))
        self.tree.bind("<Return>", lambda e: self.open_chart(self.current()))
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._follow())
        self.status = autowrap(tk.Label(self.root, text="", bg=PANEL, padx=8))
        self.status.pack(fill="x", side="bottom")
        self.root.bind("<F5>", lambda e: self.start_sync())
        self.root.bind("<Control-k>", lambda e: self.open_symbol())
        self.root.bind("<slash>", lambda e: self.open_symbol() if e.widget is self.tree else None)
        self.root.after(150, self._poll)
        self.refresh()

    # --- lista
    def rows(self):
        text = self.search.get().strip().upper()
        rows = [r for r in self.store.rows if (not self.only_ok.get() or r.get("ok")) and (not text or text in r["ticker"] or text in (r.get("company") or "").upper())]
        if self.sort:
            key, rev = self.sort
            filled = sorted((r for r in rows if r.get(key) is not None), key=lambda r: r[key], reverse=rev)
            return filled + [r for r in rows if r.get(key) is None]
        rows.sort(key=default_order)
        return rows

    def refresh(self):
        sel = self.current()
        self.tree.delete(*self.tree.get_children())
        for r in self.rows():
            tag = "signal" if r.get("ok") and r.get("glb_state") in SIGNAL else "" if r.get("ok") else "dim"
            self.tree.insert("", "end", iid=r["ticker"], values=[cell(r.get(k), f) for k, _, _, f in COLUMNS], tags=(tag,))
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)
        n_ok = sum(1 for r in self.store.rows if r.get("ok"))
        n_sig = sum(1 for r in self.store.rows if r.get("ok") and r.get("glb_state") in SIGNAL)
        self.status.config(text=f"  Dane: {self.store.at or 'brak — kliknij ⟳ Sync'}   Spółek: {len(self.store.rows)}   spełnia warunki: {n_ok}   sygnał GLB: {n_sig}"
                                f"   (warunki: obrót ≥ {calc.MIN_TURNOVER / 1e6:.0f} mln $, przychody ≥ +{calc.MIN_REV_GROWTH:.0f} %, marża oper. ≥ +{calc.MIN_DOPM:.0f} pp r/r;"
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

        def work():
            try:
                sync.run(self.store, log=log)
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
                elif kind == "synced":
                    self.sync_btn.config(state="normal")
                    self.refresh()
                    if self.chart is not None and self.chart.winfo_exists():
                        self.chart.set_ticker(self.chart.ticker)
                elif kind == "error":
                    self.sync_btn.config(state="normal")
                    self.status.config(text=f"  ❌ {val}")
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def open_settings(self):
        SettingsDialog(self)

    def run(self):
        self.root.mainloop()


class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Filtr Finviz i ustawienia")
        self.configure(bg=PANEL)
        apply_dark(self)
        s = app.store.settings
        tk.Label(self, text="Filtr Finviz (kody f= z adresu screenera; tylko wstępne cięcie listy do pobrania):", bg=PANEL).pack(anchor="w", padx=10, pady=(10, 2))
        self.filters = tk.StringVar(value=s.get("filters"))
        tk.Entry(self, textvariable=self.filters, width=90).pack(padx=10, fill="x")
        tk.Label(self, text=f"Domyślny (bezpieczny — nie odcina dużych zwycięzców z testu): {finviz.DEFAULT_FILTERS}", bg=PANEL, fg="#8b95a3").pack(anchor="w", padx=10)
        tk.Label(self, text="User-Agent dla SEC (SEC prosi o nazwę i e-mail kontaktowy):", bg=PANEL).pack(anchor="w", padx=10, pady=(10, 2))
        self.ua = tk.StringVar(value=s.get("sec_ua"))
        tk.Entry(self, textvariable=self.ua, width=90).pack(padx=10, fill="x")
        row = tk.Frame(self, bg=PANEL)
        row.pack(fill="x", padx=10, pady=10)
        tk.Button(row, text="Zapisz", command=self.save, relief="flat").pack(side="left")
        tk.Button(row, text="Przywróć domyślne", command=lambda: (self.filters.set(finviz.DEFAULT_FILTERS), self.ua.set(sec.UA)), relief="flat").pack(side="left", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())

    def save(self):
        self.app.store.settings.update(filters=self.filters.get().strip() or finviz.DEFAULT_FILTERS, sec_ua=self.ua.get().strip() or sec.UA)
        self.app.store.save_settings()
        self.destroy()


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
