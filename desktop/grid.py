"""Siatka wykresów (jak okna powiązane w TC2000): kilka wykresów naraz, wszystkie podążają za zaznaczeniem na liście skanera.
Układy: 4 kolejne spółki z listy (2×2), ta sama spółka tydzień | dzień, ta sama spółka Dar-Card | słupkowy."""
import tkinter as tk

from . import charts, store
from .theme import BG, FG, PANEL, apply_dark
from .widgets import STATE_COLORS

LAYOUTS = (("4 spółki z listy", "4"), ("Tydzień | Dzień", "td"), ("Dar-Card | słupkowy", "cb"))
DEFAULT_N = {"W": 104, "D": 126}


def cell_specs(layout, tickers, start, current, mode, tf):
    """[(ticker | None, tf, tryb)] dla komórek siatki. tickers = widoczna lista, start = indeks pierwszej spółki, current = zaznaczona."""
    if layout == "4":
        return [((tickers[start + k] if start + k < len(tickers) else None), tf, mode) for k in range(4)]
    if layout == "td":
        return [(current, "W", mode), (current, "D", mode)]
    return [(current, tf, "darcard"), (current, tf, "bars")]


class GridWindow(tk.Toplevel):
    def __init__(self, view):
        super().__init__(view.root)
        self.view = view
        self.title(f"Siatka wykresów — {view.scanner['name']}")
        self.geometry("1360x820")
        self.configure(bg=BG)
        apply_dark(self)
        self.layout_var = tk.StringVar(value="4")
        self.mode = tk.StringVar(value="bars")
        self.tf = tk.StringVar(value=view.store.tf)
        self.log = tk.BooleanVar(value=True)
        self.macd = tk.BooleanVar(value=False)
        self.zoom_f, self.back = 1.0, 0
        head = tk.Frame(self, bg=PANEL)
        head.pack(fill="x")
        tk.Label(head, text="Układ:", bg=PANEL).pack(side="left", padx=(8, 2))
        for text, val in LAYOUTS:
            tk.Radiobutton(head, text=text, value=val, variable=self.layout_var, command=self.rebuild, bg=PANEL, indicatoron=False, padx=8).pack(side="left", padx=1, pady=4)
        tk.Label(head, text="   Widok:", bg=PANEL).pack(side="left")
        for text, val in (("Słupkowy", "bars"), ("Dar-Card", "darcard")):
            tk.Radiobutton(head, text=text, value=val, variable=self.mode, command=self.refresh, bg=PANEL, indicatoron=False, padx=8).pack(side="left", padx=1)
        tk.Label(head, text="   Skala:", bg=PANEL).pack(side="left")
        for text, val in (("Tydz.", "W"), ("Dzień", "D")):
            tk.Radiobutton(head, text=text, value=val, variable=self.tf, command=self.refresh, bg=PANEL, indicatoron=False, padx=8).pack(side="left", padx=1)
        tk.Checkbutton(head, text="log", variable=self.log, command=self.refresh, bg=PANEL).pack(side="left", padx=6)
        tk.Checkbutton(head, text="MACD", variable=self.macd, command=self.refresh, bg=PANEL).pack(side="left")
        self.hint = tk.Label(head, text="↑/↓ zmieniają spółkę na liście · ←/→ przewijanie · kółko = zoom · klik w nagłówek = zaznacz · dwuklik = pełny wykres", bg=PANEL, fg="#6b7684")
        self.hint.pack(side="right", padx=8)
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True)
        self.cells = []
        for key, fn in (("<Up>", lambda e: self.step(-1)), ("<Down>", lambda e: self.step(1)), ("<Left>", lambda e: self.scroll(4)),
                        ("<Right>", lambda e: self.scroll(-4)), ("<space>", lambda e: (self.mode.set("darcard" if self.mode.get() == "bars" else "bars"), self.refresh())),
                        ("<Escape>", lambda e: self.destroy())):
            self.bind(key, fn)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.rebuild()

    # --- układ komórek
    def rebuild(self):
        for c in self.cells:
            c["frame"].destroy()
        self.cells = []
        n = 4 if self.layout_var.get() == "4" else 2
        cols = 2
        rows = 2 if n == 4 else 1
        for r in range(rows):
            self.body.rowconfigure(r, weight=1, uniform="r")
        for c in range(cols):
            self.body.columnconfigure(c, weight=1, uniform="c")
        for k in range(n):
            fr = tk.Frame(self.body, bg=BG, highlightthickness=1, highlightbackground="#1b2027")
            fr.grid(row=k // cols, column=k % cols, sticky="nsew", padx=1, pady=1)
            hd = tk.Label(fr, text="", bg=PANEL, fg=FG, anchor="w", font=("Consolas", 11, "bold"), cursor="hand2")
            hd.pack(fill="x")
            cv = tk.Canvas(fr, bg=BG, highlightthickness=0)
            cv.pack(fill="both", expand=True)
            cell = {"frame": fr, "head": hd, "cv": cv, "geom": None, "ticker": None, "tf": "W", "mode": "bars", "k": k}
            hd.bind("<Button-1>", lambda e, c=cell: self.select(c))
            cv.bind("<Double-1>", lambda e, c=cell: c["ticker"] and self.view.open_chart(c["ticker"]))
            cv.bind("<Motion>", lambda e, c=cell: self.on_motion(e, c))
            cv.bind("<Leave>", lambda e, c=cell: c["cv"].delete("cross"))
            cv.bind("<MouseWheel>", self.on_wheel)
            cv.bind("<Button-4>", lambda e: self.zoom(0.85))
            cv.bind("<Button-5>", lambda e: self.zoom(1.18))
            cv.bind("<Configure>", lambda e, c=cell: self.after_idle(lambda: self.draw_cell(c)))
            self.cells.append(cell)
        self.after_idle(self.refresh)

    # --- dane komórek
    def specs(self):
        tickers = self.view.table.visible()
        cur = self.view.table.current() or (tickers[0] if tickers else None)
        start = tickers.index(cur) if cur in tickers else 0
        return cell_specs(self.layout_var.get(), tickers, start, cur, self.mode.get(), self.tf.get())

    def refresh(self):
        for cell, (t, tf, mode) in zip(self.cells, self.specs()):
            cell["ticker"], cell["tf"], cell["mode"] = t, tf, mode
            self.draw_cell(cell)

    def draw_cell(self, cell):
        cv, t, tf, mode = cell["cv"], cell["ticker"], cell["tf"], cell["mode"]
        cv.delete("all")
        cell["geom"] = None
        row = self.view.store.row(t) if t else None
        if not t:
            cell["head"].config(text="  —", fg=FG)
            return
        st = row.get("darvas_d" if tf == "D" else "darvas_w") if row else None
        label = store.STATE_LABELS.get(st, "")
        cell["head"].config(text=f"  {t}   {row.get('price', '') if row else ''}   {label}   · {'dzień' if tf == 'D' else 'tydzień'} · {'Dar-Card' if mode == 'darcard' else 'słupkowy'}",
                            fg=STATE_COLORS.get(st, FG))
        full, dates, spx, smas = self.view.store.series(t, tf)
        if not full:
            cv.create_text(20, 20, text="brak danych dla tej skali — zrób Sync cen", fill="#6b7684", anchor="nw")
            return
        n = len(full["c"])
        n_show = max(12, min(n, int(DEFAULT_N[tf] * self.zoom_f)))
        end = max(n_show, n - self.back * (5 if tf == "D" else 1))
        win = charts.window(n, n_show, end)
        al = self.view.app.alerts.for_ticker(t)
        cv.update_idletasks()
        if mode == "darcard":
            cell["geom"] = charts.draw_darcard(cv, full, dates, win, {"pinned": self.view.store.pinned.get(t), "log": self.log.get(), "alerts": al})
        else:
            cell["geom"] = charts.draw_bars(cv, full, dates, spx, win, {"macd": self.macd.get(), "spx": True, "smas": smas, "tf": tf, "log": self.log.get(), "alerts": al})

    # --- interakcje
    def select(self, cell):
        if cell["ticker"] and self.layout_var.get() == "4":
            self.view.table.tree.selection_set(cell["ticker"])
            self.view.table.tree.see(cell["ticker"])
            self.refresh()

    def step(self, delta):
        self.view.table.step(delta)
        self.refresh()

    def scroll(self, d):
        self.back = max(0, self.back + d)
        self.refresh()

    def zoom(self, factor):
        self.zoom_f = min(4.0, max(0.15, self.zoom_f * factor))
        self.refresh()

    def on_wheel(self, e):
        self.zoom(0.85 if e.delta > 0 else 1.18)

    def on_motion(self, e, cell):
        cv, geom, t = cell["cv"], cell["geom"], cell["ticker"]
        cv.delete("cross")
        if not geom or not t:
            return
        full, dates, _spx, smas = self.view.store.series(t, cell["tf"])
        i = charts.week_at(geom, e.x)
        if i is None or not full or i >= len(full["c"]) or full["c"][i] is None:
            return
        x = geom["xf"](i)
        cv.create_line(x, geom["p_top"], x, geom["m_bot"], fill="#3a4350", tags="cross", dash=(2, 2))
        lines = charts.tooltip_card(full, dates, i, cell["tf"]) if cell["mode"] == "darcard" else charts.tooltip_bars(full, dates, i, smas, cell["tf"])
        charts.draw_tooltip(cv, e.x, e.y, lines)

    def close(self):
        if self.view.grid is self:
            self.view.grid = None
        self.destroy()
