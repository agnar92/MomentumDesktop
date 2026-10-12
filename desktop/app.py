"""Okna aplikacji Momentum Desktop — prosty, „retro” interfejs w stylu TC2000: główna lista, okna wykresów, skaner, boxy, synchronizacja."""
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import canslim, charts, darvas, finviz_codes, store, sync
from .theme import BG, FG, MONO, PANEL, MenuBar, apply_dark, setup_style
STATE_COLORS = {"BUY": "#3ddc84", "SELL": "#ff5c5c", "OUT": "#ff9f43", "NOVOL": "#ffd166", "LATE": "#ffd166", "HOLD": FG, "WAIT": "#6ea8ff"}

COLUMNS = [  # id, nagłówek, szerokość, wyrównanie
    ("ticker", "Symbol", 78, "w"), ("company", "Spółka", 190, "w"), ("price", "Cena", 86, "e"), ("rs_rating", "RS", 50, "e"),
    ("eps_rating", "EPS", 54, "e"), ("composite_rating", "Comp", 60, "e"), ("cs", "CANSLIM", 84, "e"), ("cs_letters", "C A N S L I M", 150, "w"),
    ("pct_from_high_52w", "% od szczytu", 114, "e"), ("base", "Baza", 130, "w"), ("pct_to_pivot", "Do pivotu %", 108, "e"),
    ("darvas", "Darvas", 140, "w"), ("pbox", "Box 📌", 84, "w"), ("sector", "Sektor", 130, "w"),
]
SECTIONS = [("pinned", "📌 Monitorowane (przypięte)"), ("fresh", "🆕 Nowe boxy"), ("buy", "🟢 KUP — wybicie na wolumenie"),
            ("check", "🟡 Do sprawdzenia (bez wolumenu / za późno)"), ("hold", "Trzymaj"), ("sell", "🔴 Sprzedaj / poza"), ("wait", "Czekaj na wybicie")]


def cell(r, col):
    v = r.get(col)
    if col == "base":
        return store.base_label(r)
    if col == "darvas":
        return store.STATE_LABELS.get(v, "")
    if col == "pbox":
        return {"NONE": "", "ABOVE": "wybity", "INSIDE": "w boxie", "ZONE": "STREFA!", "EXIT": "EXIT!"}.get(v, "")
    if col == "cs":
        return "–" if v is None else f"{v}/7"
    if isinstance(v, float):
        return f"{v:.2f}" if col == "price" else f"{v:.1f}"
    if v is None:
        return "–" if col in ("price", "rs_rating", "eps_rating", "composite_rating", "pct_from_high_52w", "pct_to_pivot", "cs") else ""
    return str(v)


def sort_key(r, col):
    v = r.get(col)
    if col == "base":
        v = store.base_label(r)
    if col == "pbox":
        return r.get("pbox_rank", 9)
    return (v is None, v if v is not None else 0)


class StockTable(tk.Frame):
    """Lista spółek (Treeview) z sortowaniem po nagłówku; Enter / dwuklik = otwórz wykres."""

    def __init__(self, master, on_open, on_new_window=None, on_canslim=None):
        super().__init__(master, bg=BG)
        self.on_open, self.on_new_window = on_open, on_new_window
        self.rows, self.sort_col, self.sort_rev = [], None, False
        self.tree = ttk.Treeview(self, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        for cid, title, w, anchor in COLUMNS:
            self.tree.heading(cid, text=title, command=lambda c=cid: self.sort_by(c))
            self.tree.column(cid, width=w, anchor=anchor, stretch=cid == "sector")
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb.set, xscrollcommand=hb.set)
        hb.pack(side="bottom", fill="x")
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        for st, col in STATE_COLORS.items():
            self.tree.tag_configure(st, foreground=col)
        self.tree.tag_configure("odd", background="#10141a")   # naprzemienne tło wierszy
        self.tree.bind("<Double-1>", lambda e: self._open())
        self.tree.bind("<Return>", lambda e: self._open())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._selected())
        self.on_select = None
        menu = tk.Menu(self.tree, tearoff=0)
        menu.add_command(label="Wykres (okno połączone)", command=self._open)
        if on_new_window:
            menu.add_command(label="Wykres w nowym oknie", command=lambda: self.on_new_window(self.current()))
        if on_canslim:
            menu.add_command(label="CANSLIM — szczegóły…", command=lambda: on_canslim(self.current()))
        self.tree.bind("<Button-3>", lambda e: (self.tree.selection_set(self.tree.identify_row(e.y)), menu.tk_popup(e.x_root, e.y_root)))

    def set_rows(self, rows):
        keep = self.current()
        self.rows = list(rows)
        self._fill(keep)

    def _fill(self, keep=None):
        rows = self.rows
        if self.sort_col:
            rows = sorted(rows, key=lambda r: sort_key(r, self.sort_col), reverse=self.sort_rev)
            rows = [r for r in rows if r.get(self.sort_col) is not None] + [r for r in rows if r.get(self.sort_col) is None] if self.sort_col not in ("base", "pbox") else rows
        self.tree.delete(*self.tree.get_children())
        for n, r in enumerate(rows):
            self.tree.insert("", "end", iid=r["ticker"], values=[cell(r, c[0]) for c in COLUMNS],
                             tags=(r.get("darvas", ""), "odd" if n % 2 else "even"))
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)

    def set_tf_label(self, tf):
        self.tree.heading("darvas", text="Darvas (dzień)" if tf == "D" else "Darvas (tydz.)")

    def sort_by(self, col):
        self.sort_rev = (not self.sort_rev) if self.sort_col == col else col not in ("ticker", "company", "base", "sector", "pct_to_pivot", "cs_letters")
        self.sort_col = col
        self._fill(self.current())

    def current(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def visible(self):
        return list(self.tree.get_children())

    def step(self, delta):
        ids = self.visible()
        if not ids:
            return None
        cur = self.current()
        i = ids.index(cur) + delta if cur in ids else 0
        i = max(0, min(len(ids) - 1, i))
        self.tree.selection_set(ids[i])
        self.tree.see(ids[i])
        return ids[i]

    def _open(self):
        t = self.current()
        if t:
            self.on_open(t)

    def _selected(self):
        if self.on_select and self.current():
            self.on_select(self.current())


class ChartWindow(tk.Toplevel):
    """Okno wykresu: Dar-Card i/lub wykres słupkowy tej samej spółki. Klik w box = zaznaczenie (poziomy na osi), Przybliż / Przypnij."""

    def __init__(self, app, ticker):
        super().__init__(app.root)
        self.app, self.ticker = app, ticker
        self.title("Wykres")
        self.geometry("1180x720")
        self.configure(bg=BG)
        apply_dark(self)
        self.mode = tk.StringVar(value="darcard")
        self.tf = tk.StringVar(value=app.store.tf)   # „W” tygodniowy / „D” dzienny — własny przełącznik okna, startuje z przełącznika listy
        self.n_show, self.end = self.default_n(), None
        self.focus_box, self.selected, self.cands, self.hit_geom = None, None, [], None
        self.geoms = {}
        head = tk.Frame(self, bg=PANEL)
        head.pack(fill="x")
        self.title_lbl = tk.Label(head, text="", font=("Consolas", 12, "bold"), bg=PANEL, fg="#ffffff", anchor="w")
        self.title_lbl.pack(side="left", padx=8, pady=4)
        self.status_lbl = tk.Label(self, text="", bg=PANEL, anchor="w")
        self.status_lbl.pack(fill="x", padx=8)
        for text, val in (("Słupkowy", "bars"), ("Dar-Card", "darcard")):
            tk.Radiobutton(head, text=text, value=val, variable=self.mode, command=self.redraw, bg=PANEL, indicatoron=False, padx=8).pack(side="right", padx=1, pady=3)
        tk.Label(head, text=" ", bg=PANEL).pack(side="right")
        for text, val in (("Dzień", "D"), ("Tydz.", "W")):
            tk.Radiobutton(head, text=text, value=val, variable=self.tf, command=self.change_tf, bg=PANEL, indicatoron=False, padx=8).pack(side="right", padx=1, pady=3)
        self.cs_btn = tk.Button(head, text="CANSLIM", command=lambda: app.open_canslim(self.ticker), relief="flat", padx=8)
        self.cs_btn.pack(side="right", padx=8)
        self.slider = tk.Canvas(self, height=46, bg=BG, highlightthickness=0, cursor="sb_h_double_arrow")
        self.slider.pack(fill="x", padx=2, pady=(2, 0))
        self.drag = None
        self.slider.bind("<Button-1>", self.slider_press)
        self.slider.bind("<B1-Motion>", self.slider_move)
        self.slider.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))
        self.slider.bind("<Configure>", lambda e: self.after_idle(self.draw_slider))
        self.slider.bind("<MouseWheel>", self.on_wheel)
        self.slider.bind("<Button-4>", lambda e: self.zoom(0.85))
        self.slider.bind("<Button-5>", lambda e: self.zoom(1.18))
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True)
        self.cv_card = tk.Canvas(self.body, bg=BG, highlightthickness=0)
        self.cv_bars = tk.Canvas(self.body, bg=BG, highlightthickness=0)
        self.read = tk.Label(self, text="", anchor="w", bg=PANEL, fg=FG)
        self.read.pack(fill="x", side="bottom")
        self.bar = tk.Frame(self, bg=PANEL)
        self.bar.pack(fill="x", side="bottom")
        self.info_lbl = tk.Label(self.bar, text="", anchor="w", justify="left", bg=PANEL)
        self.info_lbl.pack(side="left", padx=8, pady=3)
        self.btn_close = tk.Button(self.bar, text="✕", command=self.deselect)
        self.btn_pin = tk.Button(self.bar, text="📌 Przypnij", command=self.toggle_pin)
        self.btn_zoom = tk.Button(self.bar, text="🔍 Przybliż", command=self.zoom_selected)
        self.btn_full = tk.Button(self.bar, text="← pełny wykres", command=self.clear_focus)
        self.cv_card.bind("<Button-1>", self.on_click)
        for cv in (self.cv_card, self.cv_bars):
            cv.bind("<Configure>", lambda e: self.after_idle(self.redraw))
            cv.bind("<MouseWheel>", self.on_wheel)
            cv.bind("<Button-4>", lambda e: self.zoom(0.85))
            cv.bind("<Button-5>", lambda e: self.zoom(1.18))
            cv.bind("<Motion>", lambda e, c=cv: self.on_motion(e, c))
            cv.bind("<Leave>", lambda e: self.cv_bars.delete("cross") or self.cv_card.delete("cross"))
        for key, fn in (("<Up>", lambda e: app.step_chart(-1)), ("<Down>", lambda e: app.step_chart(1)),
                        ("<Left>", lambda e: self.scroll(-4)), ("<Right>", lambda e: self.scroll(4)),
                        ("<space>", lambda e: self.toggle_mode()), ("<plus>", lambda e: self.zoom(0.85)), ("<minus>", lambda e: self.zoom(1.18)),
                        ("<Escape>", lambda e: self.deselect() if self.selected is not None else self.focus_box and self.clear_focus() or self.destroy())):
            self.bind(key, fn)
        self.set_ticker(ticker)

    # --- dane
    def default_n(self):
        return 126 if self.tf.get() == "D" else 104   # ~pół roku sesji / 2 lata tygodni

    def series(self):
        """(dane OHLCV, daty, S&P 500, średnie) w skali czasu okna; brak danych dziennych = wracamy do tygodniowych."""
        full, dates, spx, smas = self.app.store.series(self.ticker, self.tf.get())
        if full is None and self.tf.get() == "D":
            self.tf.set("W")
            full, dates, spx, smas = self.app.store.series(self.ticker, "W")
        return full, dates, spx, smas

    @property
    def full(self):
        return self.series()[0]

    @property
    def dates(self):
        return self.series()[1]

    def unit(self):
        return "sesji" if self.tf.get() == "D" else "tyg."

    def change_tf(self):
        self.focus_box, self.selected, self.end = None, None, None
        self.n_show = self.default_n()
        self.set_status()
        self.update_bar()
        self.redraw()

    def set_status(self):
        row = self.app.store.row(self.ticker) or {}
        d = self.tf.get() == "D"
        st = row.get("darvas_d" if d else "darvas_w")
        txt = row.get("darvas_text_d" if d else "darvas_text_w") or ""
        self.status_lbl.config(text=f"📦 {'Dzień' if d else 'Tydzień'}: {txt}", fg=STATE_COLORS.get(st, FG))
        cs = row.get("cs")
        self.cs_btn.config(text=f"CANSLIM {cs}/7" if cs is not None else "CANSLIM ?")

    def set_ticker(self, ticker, focus=None, tf=None):
        self.ticker, self.focus_box, self.selected, self.end = ticker, None, None, None
        if tf:
            self.tf.set(tf)
        self.n_show = self.default_n()
        row = self.app.store.row(ticker) or {}
        self.title(f"{ticker} — {row.get('company', '')}")
        self.title_lbl.config(text=f"{ticker}  {row.get('price', '')}")
        self.set_status()
        if focus:
            self.set_focus(focus)
        self.update_bar()
        self.after_idle(self.redraw)

    def set_focus(self, box):
        """Widok po „Przybliż”: wykres słupkowy zawężony do boxa + poziomy wejścia / dołu / exitu na osi ceny."""
        self.focus_box = box
        n = len(self.dates)
        k = 5 if self.tf.get() == "D" else 1   # tygodnie -> sesje
        i0, i1 = charts.box_focus_window(n, box, 14 * k, 6 * k)
        self.n_show, self.end = i1 - i0, i1
        self.mode.set("bars")   # po „Przybliż” pokazujemy wykres słupkowy zawężony do boxa
        self.update_bar()

    def clear_focus(self):
        self.focus_box, self.n_show, self.end = None, self.default_n(), None
        self.mode.set("darcard")
        self.update_bar()
        self.redraw()

    # --- rysowanie
    def layout(self):
        mode = self.mode.get()
        self.cv_card.pack_forget()
        self.cv_bars.pack_forget()
        (self.cv_card if mode == "darcard" else self.cv_bars).pack(fill="both", expand=True)

    def redraw(self):
        self.layout()
        full, dates, spx, smas = self.series()
        if not full:
            return
        self.draw_slider()
        n = len(full["c"])
        win = charts.window(n, self.n_show, self.end)
        st = self.app.store
        pinned = st.pinned.get(self.ticker)
        if self.mode.get() == "darcard":
            self.update_idletasks()
            self.geoms["card"] = charts.draw_darcard(self.cv_card, full, dates, win, {"pinned": pinned, "selected": self.selected})
            self.hit_geom = self.geoms["card"]
        if self.mode.get() == "bars":
            opts = {"macd": True, "spx": True, "smas": smas, "tf": self.tf.get()}
            fb = self.focus_box or (self.selected_box())
            if fb:
                opts["tags"] = [(fb["top"], charts.GREEN), (fb["bottom"], charts.WHITE), (round(fb["bottom"] * 0.95, 2), charts.RED)]
                opts["levels"] = [v for v, _ in opts["tags"]]
                opts["boxes"] = [{"i0": fb["i0"], "i1": fb["i1"] if fb.get("outcome") != "open" else len(full["c"]) - 1, "top": fb["top"], "bottom": fb["bottom"],
                                  "extend": fb.get("outcome") == "open", "color": charts.GOLD}]
            row = st.row(self.ticker) or {}
            if row.get("pivot") and row.get("base_type") in store.BUYABLE_BASES and abs(row.get("pct_to_pivot") or 99) < 15:
                opts["pivot"] = row["pivot"]
            self.geoms["bars"] = charts.draw_bars(self.cv_bars, full, dates, spx, win, opts)

    def on_motion(self, e, cv):
        geom = self.geoms.get("card" if cv is self.cv_card else "bars")
        i = charts.week_at(geom, e.x)
        full = self.full
        for c in (self.cv_card, self.cv_bars):
            c.delete("cross")
        if i is None or not full or i >= len(full["c"]) or full["c"][i] is None:
            return
        for name, c in (("card", self.cv_card), ("bars", self.cv_bars)):
            g = self.geoms.get(name)
            if g and c.winfo_ismapped():
                x = g["xf"](i)
                c.create_line(x, g["p_top"], x, g["m_bot"], fill="#3a4350", tags="cross", dash=(2, 2))
        dates = self.dates
        w = dates[i] if i < len(dates) else ""
        f = full
        self.read.config(text=f"  {w}   H {f['h'][i]:.2f}  L {f['l'][i]:.2f}  C {f['c'][i]:.2f}   Wol {charts.fmt_vol(f['v'][i]) if f['v'][i] is not None else '-'}")

    # --- zaznaczanie boxów (Dar-Card)
    def selected_box(self):
        g = self.geoms.get("card")
        if self.selected is None or not g or self.selected >= len(g.get("hits", [])):
            return None
        return g["hits"][self.selected]["box"]

    def on_click(self, e):
        g = self.geoms.get("card")
        found = charts.hit_boxes(g, e.x, e.y)
        if not found:
            self.deselect()
            return
        nxt = found[0]
        if self.selected in found and len(found) > 1:
            nxt = found[(found.index(self.selected) + 1) % len(found)]   # nakładające się boxy: kolejne kliknięcia przełączają
        self.selected = nxt
        self.update_bar()
        self.redraw()

    def deselect(self):
        self.selected = None
        self.update_bar()
        self.redraw()

    def update_bar(self):
        for b in (self.btn_close, self.btn_pin, self.btn_zoom, self.btn_full):
            b.pack_forget()
        box = self.focus_box or self.selected_box()
        if not box:
            self.info_lbl.config(text="Klik w box = poziomy · spacja = przełącz widok · suwak u góry = okno czasu · ↑/↓ = następna spółka · kółko = zoom")
            return
        info = darvas.box_info(box["top"], box["bottom"])
        pinned = self.app.store.pinned.get(self.ticker)
        is_pin = pinned and abs(pinned["top"] - box["top"]) < 0.005 and abs(pinned["bottom"] - box["bottom"]) < 0.005
        risk = (1 - info["stop"] / info["entry"]) * 100
        self.info_lbl.config(text=f"BOX {info['cancel']}–{info['entry']} (głęb. {info['depth_pct']} %)   wejście: zamknięcie {'dnia' if self.tf.get() == 'D' else 'tygodnia'} > {info['entry']}\n"
                                  f"strefa zagrożenia {info['cancel']} → {info['stop']} (exit)   ryzyko od wejścia do exitu: {risk:.1f} % na akcję")
        self.btn_close.pack(side="right", padx=4)
        self.btn_pin.config(text="🗑 Odepnij" if is_pin else "📌 Przypnij")
        self.btn_pin.pack(side="right", padx=2)
        if self.focus_box:
            self.btn_full.pack(side="right", padx=2)
        else:
            self.btn_zoom.pack(side="right", padx=2)

    def toggle_mode(self):
        self.mode.set("bars" if self.mode.get() == "darcard" else "darcard")
        self.redraw()

    def zoom_selected(self):
        box = self.selected_box()
        if box:
            self.set_focus(box)
            self.selected = None
            self.redraw()

    def toggle_pin(self):
        box = self.focus_box or self.selected_box()
        if not box:
            return
        pinned = self.app.store.pinned.get(self.ticker)
        if pinned and abs(pinned["top"] - box["top"]) < 0.005 and abs(pinned["bottom"] - box["bottom"]) < 0.005:
            self.app.store.pin(self.ticker, None)
        else:
            self.app.store.pin(self.ticker, {"top": box["top"], "bottom": box["bottom"], "start": box.get("start", "")})
        self.app.refresh_lists()
        self.set_status()
        self.update_bar()
        self.redraw()

    # --- suwak okna czasu
    def _state(self):
        n = len(self.full["c"]) if self.full else 0
        return n, min(self.n_show, n), (n if self.end is None else self.end)

    def draw_slider(self):
        if self.full:
            n, n_show, end = self._state()
            charts.draw_slider(self.slider, self.full["c"], n_show, end, self.unit())

    def slider_press(self, e):
        if not self.full:
            return
        n, n_show, end = self._state()
        W = self.slider.winfo_width()
        x0, x1 = charts.slider_rect(n, n_show, end, W)
        mode = charts.slider_mode(e.x, x0, x1)
        if mode == "jump":
            self.n_show, self.end = charts.slider_jump(e.x, n, n_show, W)
            self.end = None if self.end >= n else self.end
            self.redraw()
            return
        self.drag = (mode, e.x, (n_show, end))

    def slider_move(self, e):
        if not self.drag or not self.full:
            return
        mode, x_start, start = self.drag
        n = len(self.full["c"])
        self.n_show, end = charts.slider_drag(mode, start, e.x - x_start, n, self.slider.winfo_width())
        self.end = None if end >= n else end
        self.redraw()

    # --- okno czasowe
    def zoom(self, factor):
        n = len(self.full["c"]) if self.full else 0
        self.n_show = int(max(12, min(n, self.n_show * factor)))
        self.redraw()

    def scroll(self, d):
        d = d * 5 if self.tf.get() == "D" else d
        n = len(self.full["c"]) if self.full else 0
        end = (self.end if self.end is not None else n) + d
        self.end = None if end >= n else max(self.n_show, end)
        self.redraw()

    def on_wheel(self, e):
        self.zoom(0.85 if e.delta > 0 else 1.18)


class SyncWindow(tk.Toplevel):
    """Dziennik synchronizacji (Finviz + yfinance) z paskiem postępu."""

    def __init__(self, app, title="Synchronizacja danych"):
        super().__init__(app.root)
        self.title(title)
        self.geometry("760x420")
        self.configure(bg=BG)
        apply_dark(self)
        self.text = tk.Text(self, bg="#0f1318", fg=FG, wrap="word", state="disabled")
        self.text.pack(fill="both", expand=True)
        self.bar = ttk.Progressbar(self, mode="indeterminate")
        self.bar.pack(fill="x")
        self.bar.start(12)
        self.btn = tk.Button(self, text="Zamknij", state="disabled", command=self.destroy)
        self.btn.pack(pady=4)

    def log(self, line):
        self.text.config(state="normal")
        self.text.insert("end", line + "\n")
        self.text.see("end")
        self.text.config(state="disabled")

    def done(self, ok):
        self.bar.stop()
        self.bar.config(mode="determinate", value=100 if ok else 0)
        self.btn.config(state="normal")
        self.log("✅ Gotowe." if ok else "❌ Synchronizacja nie powiodła się — zostają poprzednie dane.")


class ScannerWindow(tk.Toplevel):
    """Skaner: filtry po pobranych danych + edycja filtrów Finviz i przycisk pobrania."""

    FIELDS = [("rs_min", "RS ≥"), ("eps_min", "EPS Rating ≥"), ("comp_min", "Composite ≥"), ("max_to_pivot", "Do pivotu ≤ %"),
              ("max_from_high", "Pod szczytem 52t ≤ %"), ("min_adr", "ADR ≥ %"), ("cs_min", "CANSLIM ≥ (n/7)")]

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Skaner")
        self.geometry("1100x760")
        self.configure(bg=BG)
        apply_dark(self)
        form = tk.Frame(self, bg=PANEL)
        form.pack(fill="x")
        self.vars = {k: tk.StringVar() for k, _ in self.FIELDS}
        for n, (k, label) in enumerate(self.FIELDS):
            tk.Label(form, text=label, bg=PANEL).grid(row=n // 3, column=(n % 3) * 2, sticky="e", padx=(8, 2), pady=3)
            e = tk.Entry(form, textvariable=self.vars[k], width=6)
            e.grid(row=n // 3, column=(n % 3) * 2 + 1, sticky="w")
            e.bind("<Return>", lambda ev: self.run())
        self.state_vars = {}
        sf = tk.Frame(form, bg=PANEL)
        sf.grid(row=3, column=0, columnspan=6, sticky="w", padx=8, pady=2)
        tk.Label(sf, text="Darvas:", bg=PANEL).pack(side="left")
        for st in ("BUY", "NOVOL", "LATE", "HOLD", "WAIT", "SELL", "OUT"):
            v = tk.BooleanVar()
            self.state_vars[st] = v
            tk.Checkbutton(sf, text=store.STATE_LABELS[st], variable=v, bg=PANEL, command=self.run).pack(side="left", padx=3)
        self.sector = tk.StringVar()
        row3 = tk.Frame(form, bg=PANEL)
        row3.grid(row=4, column=0, columnspan=6, sticky="w", padx=8, pady=2)
        tk.Label(row3, text="Sektor:", bg=PANEL).pack(side="left")
        self.sector_box = ttk.Combobox(row3, textvariable=self.sector, state="readonly", width=24)
        self.sector_box.pack(side="left", padx=4)
        self.sector_box.bind("<<ComboboxSelected>>", lambda e: self.run())
        self.base_only, self.pinned_only, self.cs_core = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
        tk.Checkbutton(row3, text="CANSLIM: C i A obowiązkowe", variable=self.cs_core, bg=PANEL, command=self.run).pack(side="left", padx=6)
        tk.Checkbutton(row3, text="tylko z bazą do kupienia", variable=self.base_only, bg=PANEL, command=self.run).pack(side="left", padx=6)
        tk.Checkbutton(row3, text="tylko przypięte boxy", variable=self.pinned_only, bg=PANEL, command=self.run).pack(side="left", padx=6)
        row4 = tk.Frame(form, bg=PANEL)
        row4.grid(row=5, column=0, columnspan=6, sticky="we", padx=8, pady=4)
        tk.Label(row4, text="Gotowe skany:", bg=PANEL).pack(side="left")
        self.preset = ttk.Combobox(row4, values=list(store.PRESETS), state="readonly", width=38)
        self.preset.pack(side="left", padx=4)
        self.preset.bind("<<ComboboxSelected>>", lambda e: self.load_preset())
        tk.Button(row4, text="Skanuj", command=self.run).pack(side="left", padx=4)
        tk.Button(row4, text="Reset", command=self.reset).pack(side="left")
        tk.Button(row4, text="Pokaż na liście głównej", command=lambda: app.apply_main_filter(self.collect())).pack(side="left", padx=8)
        self.count = tk.Label(row4, text="", bg=PANEL)
        self.count.pack(side="right")
        self.table = StockTable(self, app.open_chart, app.open_chart_new, app.open_canslim)
        self.table.pack(fill="both", expand=True)
        self.table.set_tf_label(app.store.tf)
        fv = tk.LabelFrame(self, text=" Finviz — skaner źródłowy (pobierany przez Sync) ", bg=PANEL, fg=FG)
        fv.pack(fill="x", padx=4, pady=4)
        cfg = app.store.finviz_config()
        self.fv_filters = tk.StringVar(value=cfg.get("filters", ""))
        self.fv_max = tk.StringVar(value=str(cfg.get("max_tickers", 300)))
        tk.Entry(fv, textvariable=self.fv_filters).pack(fill="x", padx=6, pady=(4, 2))
        self.fv_desc = tk.Label(fv, text="", bg=PANEL, fg="#8b95a3", justify="left", anchor="w", wraplength=1000)
        self.fv_desc.pack(fill="x", padx=6)
        self.fv_filters.trace_add("write", lambda *_: self.show_criteria())
        r = tk.Frame(fv, bg=PANEL)
        r.pack(fill="x", padx=6, pady=3)
        tk.Label(r, text="max spółek:", bg=PANEL).pack(side="left")
        tk.Entry(r, textvariable=self.fv_max, width=6).pack(side="left", padx=4)
        tk.Button(r, text="Zapisz filtry", command=self.save_finviz).pack(side="left", padx=4)
        tk.Button(r, text="⟳ Zapisz i pobierz ceny", command=lambda: (self.save_finviz(), app.start_sync(sync.PRICES))).pack(side="left", padx=4)
        tk.Button(r, text="⟳ Zapisz i pobierz fundamenty", command=lambda: (self.save_finviz(), app.start_sync(sync.FUNDAMENTALS))).pack(side="left", padx=4)
        tk.Label(r, text="Kody z adresu skanera finviz.com (f=). Nieznany kod Finviz ignoruje po cichu.", bg=PANEL, fg="#6b7684").pack(side="left", padx=8)
        self.show_criteria()
        self.refresh()

    def refresh(self):
        sectors = sorted({r.get("sector") for r in self.app.store.rows if r.get("sector")})
        self.sector_box.config(values=[""] + sectors)
        self.run()

    @staticmethod
    def _num(s):
        try:
            return float(str(s).replace(",", ".")) if str(s).strip() else None
        except ValueError:
            return None

    def collect(self):
        f = {k: self._num(v.get()) for k, v in self.vars.items()}
        f.update(states=[s for s, v in self.state_vars.items() if v.get()], sector=self.sector.get(), base_only=self.base_only.get(),
                 pinned_only=self.pinned_only.get(), cs_core=self.cs_core.get())
        return f

    def run(self):
        rows = store.scan(self.app.store.rows, self.collect())
        self.table.set_rows(rows)
        self.count.config(text=f"{len(rows)} / {len(self.app.store.rows)} spółek")

    def reset(self):
        for v in self.vars.values():
            v.set("")
        for v in self.state_vars.values():
            v.set(False)
        self.sector.set("")
        self.base_only.set(False)
        self.pinned_only.set(False)
        self.cs_core.set(False)
        self.preset.set("")
        self.run()

    def load_preset(self):
        f = store.PRESETS.get(self.preset.get(), {})
        self.reset()
        self.preset.set(self.preset.get() or "")
        for k, v in f.items():
            if k in self.vars:
                self.vars[k].set(str(v))
            elif k == "states":
                for s in v:
                    self.state_vars[s].set(True)
            elif k == "base_only":
                self.base_only.set(bool(v))
            elif k == "cs_core":
                self.cs_core.set(bool(v))
        self.run()

    def show_criteria(self):
        items = finviz_codes.describe(self.fv_filters.get())
        self.fv_desc.config(text="Kryteria: " + "  •  ".join(t if k else f"⚠ {c}" for c, t, k in items))

    def save_finviz(self):
        try:
            self.app.store.save_finviz_config(self.fv_filters.get(), int(self.fv_max.get() or 300))
        except ValueError:
            messagebox.showerror("Finviz", "Maksymalna liczba spółek musi być liczbą.", parent=self)


class BoxesWindow(tk.Toplevel):
    """Przegląd boxów Darvasa dla wszystkich spółek w sekcjach (jak podstrona „Boxy” w Momentum)."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Boxy Darvasa")
        self.geometry("900x620")
        self.configure(bg=BG)
        apply_dark(self)
        self.tree = ttk.Treeview(self, columns=("price", "text"), show="tree headings")
        self.tree.heading("#0", text="Spółka")
        self.tree.heading("price", text="Cena")
        self.tree.heading("text", text="Status")
        self.tree.column("#0", width=210)
        self.tree.column("price", width=80, anchor="e")
        self.tree.column("text", width=560)
        self.tree.pack(fill="both", expand=True)
        for st, col in STATE_COLORS.items():
            self.tree.tag_configure(st, foreground=col)
        self.tree.bind("<Double-1>", self.open_row)
        self.rows = {}
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        ov = self.app.store.overview()
        for key, title in SECTIONS:
            items = ov.get(key, [])
            sec = self.tree.insert("", "end", iid=f"sec:{key}", text=f"{title} ({len(items)})", open=key in ("pinned", "buy", "fresh"))
            for n, r in enumerate(items):
                iid = f"{key}:{n}:{r['ticker']}"
                self.rows[iid] = r
                self.tree.insert(sec, "end", iid=iid, text=r["ticker"], values=(f"{r['price']:.2f}" if r.get("price") else "", r["text"]), tags=(r["state"],))

    def open_row(self, _e):
        sel = self.tree.selection()
        r = self.rows.get(sel[0]) if sel else None
        if not r:
            return
        box = dict(r["box"])
        _, dates, _, _ = self.app.store.series(r["ticker"], self.app.store.tf)
        if box.get("i0", -1) < 0:   # przypięty: indeks z daty startu
            box["i0"] = next((i for i, w in enumerate(dates) if w >= box.get("start", "")), max(0, len(dates) - 20))
            box["i1"] = len(dates) - 1
            box["outcome"] = "open"
        self.app.open_chart(r["ticker"], focus=box)


class FinvizCriteriaWindow(tk.Toplevel):
    """Co synchronizujemy: kryteria skanera Finviz (kody filtrów z data/finviz_screen.json) po ludzku."""

    def __init__(self, app):
        super().__init__(app.root)
        cfg = app.store.finviz_config()
        self.title("Kryteria Finviz — co synchronizujemy")
        self.geometry("760x470")
        self.configure(bg=BG)
        apply_dark(self)
        t = tk.Text(self, wrap="word", bg="#0f1318", fg=FG, padx=12, pady=10, relief="flat", font=MONO)
        t.pack(fill="both", expand=True)
        t.tag_configure("h", font=("Consolas", 12, "bold"), foreground="#ffffff")
        t.tag_configure("warn", foreground="#ff9f43")
        t.tag_configure("dim", foreground="#8b95a3")
        lines = finviz_codes.summary_lines(cfg.get("filters"), cfg.get("max_tickers"))
        t.insert("end", lines[0] + "\n\n", "h")
        for (code, text, known), line in zip(finviz_codes.describe(cfg.get("filters")), lines[1:]):
            t.insert("end", f"  • {text}", "" if known else "warn")
            t.insert("end", f"   [{code}]\n", "dim")
        wl = app.store.watchlist
        t.insert("end", f"\nOstatnia lista: {wl.get('n_stocks', '?')} spółek (Finviz podał łącznie {wl.get('finviz_total', '?')}); "
                        "filtry zmienisz w oknie Skaner (sekcja Finviz) albo w pliku data/finviz_screen.json.\n", "dim")
        t.insert("end", "\nRównież z Finviz (dla każdej spółki z listy): sektor, branża, kapitalizacja, P/E, EPS w tym / przyszłym roku, ROE, sprzedaż q/q, "
                        "instytucje, zadłużenie, rekomendacja analityków i cena docelowa. Resztę (ceny, RS, EPS Rating, bazy, CANSLIM) liczy aplikacja.\n", "dim")
        t.config(state="disabled")
        t.bind("<Escape>", lambda ev: self.destroy())


class CanslimWindow(tk.Toplevel):
    """CANSLIM litera po literze: werdykt, liczby, które mamy, i reguła (te same dane, na których liczy się n/7)."""

    def __init__(self, app, ticker):
        super().__init__(app.root)
        row = app.store.row(ticker) or {}
        e = canslim.explain(row, app.store.mkt)
        self.title(f"{ticker} — CANSLIM {e['score']}/7")
        self.geometry("820x640")
        self.configure(bg=BG)
        apply_dark(self)
        t = tk.Text(self, wrap="word", bg="#0f1318", fg=FG, padx=12, pady=10, relief="flat", font=MONO)
        t.pack(fill="both", expand=True)
        t.tag_configure("h", font=("Consolas", 12, "bold"), foreground="#ffffff", spacing1=10)
        t.tag_configure("ok", foreground="#3ddc84")
        t.tag_configure("no", foreground="#ff5c5c")
        t.tag_configure("na", foreground="#8b95a3")
        t.tag_configure("dim", foreground="#8b95a3")
        t.insert("end", f"{ticker} — {row.get('company', '')}\n", "h")
        t.insert("end", f"Spełnione: {e['score']}/7 (znane kryteria: {e['known']}). Progi i reguły jak w Momentum (wg O'Neila); heurystyka, nie porada.\n", "dim")
        for key, name, ok, have, rule in e["rows"]:
            tag, mark = ("ok", "✓ spełnione") if ok is True else ("no", "✗ niespełnione") if ok is False else ("na", "? brak danych")
            t.insert("end", f"\n{key}  {name}   ", "h")
            t.insert("end", mark + "\n", tag)
            t.insert("end", "Mamy:   ", "dim")
            t.insert("end", have + "\n")
            t.insert("end", "Reguła: ", "dim")
            t.insert("end", rule + "\n")
        t.config(state="disabled")
        t.bind("<Escape>", lambda ev: self.destroy())


class App:
    def __init__(self, data_base=None):
        self.root = tk.Tk()
        self.root.title("Momentum Desktop")
        self.root.geometry("1420x760")
        setup_style(self.root)
        apply_dark(self.root)
        self.store = store.Store(data_base)
        self.chart = None
        self.scanner = self.boxes = self.sync_win = None
        self.q = queue.Queue()
        self.syncing = False
        self.main_filter = {}
        self.menubar = MenuBar(self.root, self._menu_spec())
        self.menubar.pack(fill="x")
        tb = tk.Frame(self.root, bg=PANEL)
        tb.pack(fill="x")
        self.prices_btn = tk.Button(tb, text="⟳ Ceny (F5)", command=lambda: self.start_sync(sync.PRICES), width=13, relief="flat")
        self.prices_btn.pack(side="left", padx=(6, 2), pady=5)
        self.fund_btn = tk.Button(tb, text="⟳ Fundamenty", command=lambda: self.start_sync(sync.FUNDAMENTALS), width=13, relief="flat")
        self.fund_btn.pack(side="left", padx=2)
        tk.Button(tb, text="Skaner…", command=self.open_scanner, relief="flat").pack(side="left", padx=(12, 2))
        tk.Button(tb, text="Boxy…", command=self.open_boxes, relief="flat").pack(side="left", padx=2)
        tk.Button(tb, text="Kryteria Finviz", command=self.open_criteria, relief="flat").pack(side="left", padx=2)
        self.tf = tk.StringVar(value=self.store.tf)
        tk.Label(tb, text="Skala:", bg=PANEL).pack(side="left", padx=(14, 2))
        for text, val in (("Tydzień", "W"), ("Dzień", "D")):
            tk.Radiobutton(tb, text=text, value=val, variable=self.tf, command=lambda: self.set_tf(self.tf.get()), bg=PANEL,
                           indicatoron=False, padx=9, relief="flat").pack(side="left", padx=1)
        tk.Label(tb, text="Szukaj:", bg=PANEL).pack(side="left", padx=(14, 2))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh_lists())
        tk.Entry(tb, textvariable=self.search, width=14, relief="flat").pack(side="left")
        self.filter_lbl = tk.Label(tb, text="", bg=PANEL, fg="#ffd166")
        self.filter_lbl.pack(side="left", padx=8)
        self.age_lbl = tk.Label(tb, text="", bg=PANEL, anchor="e")
        self.age_lbl.pack(side="right", padx=8)
        self.table = StockTable(self.root, self.open_chart, self.open_chart_new, self.open_canslim)
        self.table.pack(fill="both", expand=True)
        self.table.on_select = self.on_select
        self.status = tk.Label(self.root, text="", anchor="w", bg=PANEL)
        self.status.pack(fill="x", side="bottom")
        self.root.bind("<F5>", lambda e: self.start_sync(sync.PRICES))
        self.root.bind("<Shift-F5>", lambda e: self.start_sync(sync.FUNDAMENTALS))
        self.table.tree.bind("<Up>", lambda e: self.root.after_idle(self._link))
        self.table.tree.bind("<Down>", lambda e: self.root.after_idle(self._link))
        self.refresh_lists()
        self.root.after(150, self._poll)

    def _menu_spec(self):
        return [
            ("Plik", [("Sync cen (Finviz + yfinance, szybko)\tF5", lambda: self.start_sync(sync.PRICES)),
                      ("Sync fundamentów (EPS, estymaty — raz w tygodniu)\tShift+F5", lambda: self.start_sync(sync.FUNDAMENTALS)),
                      ("Ceny tylko z yfinance (bez Finviz)", lambda: self.start_sync(sync.PRICES, skip_finviz=True)),
                      ("Wczytaj dane z dysku", self.reload), None, ("Zakończ", self.root.destroy)]),
            ("Skaner", [("Skaner…", self.open_scanner), ("Boxy Darvasa…", self.open_boxes),
                        ("Kryteria Finviz (co synchronizujemy)…", self.open_criteria),
                        ("Wyczyść filtr listy", lambda: self.apply_main_filter({}))]),
            ("Okno", [("Wykres wybranej spółki", lambda: self.open_chart(self.table.current())),
                      ("Wykres w nowym oknie", lambda: self.open_chart_new(self.table.current())),
                      ("CANSLIM wybranej spółki…", lambda: self.open_canslim(self.table.current()))]),
            ("Pomoc", [("O programie", lambda: messagebox.showinfo(
                "Momentum Desktop", "Lista z Finviz + ceny z yfinance, wykresy Dar-Card i słupkowy (tygodniowe i dzienne), CANSLIM.\n"
                "Logika jak w Momentum. Tylko informacyjnie — nie jest to porada inwestycyjna.\n\nDane: " + str(self.store.dir)))]),
        ]

    # --- skala czasu listy
    def set_tf(self, tf):
        self.store.set_tf(tf)
        self.tf.set(self.store.tf)
        if tf == "D" and self.store.tf != "D":
            messagebox.showinfo("Skala dzienna", "Brak danych dziennych — zrób Sync cen.")
        self.refresh_lists()

    # --- listy
    def _rows(self):
        return store.scan(self.store.rows, {**self.main_filter, "text": self.search.get()})

    def refresh_lists(self):
        rows = self._rows()
        self.table.set_rows(rows)
        self.table.set_tf_label(self.store.tf)
        wl = self.store.watchlist
        mk = self.store.mkt or {}
        regime = {"uptrend": "✅ trend wzrostowy", "correction": "🛑 korekta"}.get(mk.get("regime"), "—")
        self.status.config(text=f"  Dane z sesji: {wl.get('data_as_of', 'brak — kliknij Sync')}   Spółek: {len(rows)}/{len(self.store.rows)}   Rynek (M): {regime}"
                                f"   Finviz: {'(stare dane!)' if wl.get('finviz_stale') else 'ok'}   Katalog: {self.store.dir}")
        self.filter_lbl.config(text="⚑ filtr skanera aktywny" if any(v for v in self.main_filter.values()) else "")
        self.update_age()
        if self.scanner and self.scanner.winfo_exists():
            self.scanner.run()
            self.scanner.table.set_tf_label(self.store.tf)
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
        self.refresh_lists()
        if self.scanner and self.scanner.winfo_exists():
            self.scanner.refresh()

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

    def open_criteria(self):
        FinvizCriteriaWindow(self)

    def open_canslim(self, ticker):
        if ticker and self.store.row(ticker):
            CanslimWindow(self, ticker)

    def step_chart(self, delta):
        t = self.table.step(delta)
        if t:
            self.open_chart(t)

    def _link(self):
        if self.chart is not None and self.chart.winfo_exists() and self.table.current():
            self.chart.set_ticker(self.table.current())

    def on_select(self, ticker):
        pass

    def open_scanner(self):
        if self.scanner is None or not self.scanner.winfo_exists():
            self.scanner = ScannerWindow(self)
        self.scanner.lift()

    def open_boxes(self):
        if self.boxes is None or not self.boxes.winfo_exists():
            self.boxes = BoxesWindow(self)
        self.boxes.lift()

    # --- synchronizacja (w tle, log przez kolejkę)
    def start_sync(self, mode=sync.PRICES, skip_finviz=False):
        if self.syncing:
            return
        self.syncing = True
        for b in (self.prices_btn, self.fund_btn):
            b.config(state="disabled")
        fund = mode == sync.FUNDAMENTALS
        self.sync_win = SyncWindow(self, "Synchronizacja fundamentów" if fund else "Synchronizacja cen")
        if not skip_finviz:   # co dokładnie pobieramy z Finviz
            cfg = self.store.finviz_config()
            for line in finviz_codes.summary_lines(cfg.get("filters"), cfg.get("max_tickers")):
                self.sync_win.log(line)
        self.sync_win.log("Start: Finviz → yfinance → EPS i estymaty analityków → obliczenia (kilka–kilkanaście minut)…" if fund
                          else "Start: " + ("yfinance" if skip_finviz else "Finviz → yfinance") + " → obliczenia na zapisanych fundamentach (ok. minuty)…")

        def work():
            code = sync.run_sync(self.store.dir, log=lambda s: self.q.put(("log", s)), mode=mode, skip_finviz=skip_finviz)
            self.q.put(("done", code == 0))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log" and self.sync_win and self.sync_win.winfo_exists():
                    self.sync_win.log(val)
                elif kind == "done":
                    self.syncing = False
                    for b in (self.prices_btn, self.fund_btn):
                        b.config(state="normal")
                    if val:
                        self.reload()
                    if self.sync_win and self.sync_win.winfo_exists():
                        self.sync_win.done(val)
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def run(self):
        self.root.mainloop()


def main():
    App().run()
