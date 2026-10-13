"""Okno wykresu: Dar-Card i wykres słupkowy (tygodniowe i dzienne) wybranej spółki, z suwakiem czasu i boxami."""
import tkinter as tk

from . import charts, darvas, store
from .theme import BG, FG, PANEL, apply_dark
from .widgets import STATE_COLORS


class ChartWindow(tk.Toplevel):
    """Okno wykresu: Dar-Card i/lub wykres słupkowy tej samej spółki. Klik w box = zaznaczenie (poziomy na osi), Przybliż / Przypnij."""

    def __init__(self, view, ticker):
        super().__init__(view.root)
        self.app, self.ticker = view, ticker   # „app” = widok skanera, z którego otwarto wykres (jego dane, lista, CANSLIM)
        self.title("Wykres")
        h = min(940, max(600, self.winfo_screenheight() - 90))   # okno pionowe (prostokąt w pionie) — wykres wygląda lepiej niż w poziomie
        self.geometry(f"{min(720, int(h * 0.78))}x{h}")
        self.configure(bg=BG)
        apply_dark(self)
        self.mode = tk.StringVar(value="darcard")
        self.tf = tk.StringVar(value=view.store.tf)   # „W” tygodniowy / „D” dzienny — własny przełącznik okna, startuje z przełącznika listy
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
        self.log = tk.BooleanVar(value=True)    # skala logarytmiczna ceny (domyślnie); L przełącza
        self.macd_on = tk.BooleanVar(value=True)
        tk.Checkbutton(head, text="MACD", variable=self.macd_on, command=self.redraw, bg=PANEL).pack(side="right", padx=4)
        tk.Checkbutton(head, text="log", variable=self.log, command=self.redraw, bg=PANEL).pack(side="right", padx=4)
        self.cs_btn = tk.Button(head, text="CANSLIM", command=lambda: view.open_canslim(self.ticker), relief="flat", padx=8)
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
        for key, fn in (("<Up>", lambda e: view.step_chart(-1)), ("<Down>", lambda e: view.step_chart(1)),
                        ("<Left>", lambda e: self.scroll(-4)), ("<Right>", lambda e: self.scroll(4)),
                        ("<space>", lambda e: self.toggle_mode()), ("<l>", lambda e: (self.log.set(not self.log.get()), self.redraw())),
                        ("<m>", lambda e: (self.macd_on.set(not self.macd_on.get()), self.redraw())),
                        ("<slash>", lambda e: view.open_symbol_dialog()), ("<Control-k>", lambda e: view.open_symbol_dialog()), ("<plus>", lambda e: self.zoom(0.85)), ("<minus>", lambda e: self.zoom(1.18)),
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
        if "confirmed" not in box:   # box z listy Boxy nie niesie flagi — bierzemy ją z boxów Darvasa tej spółki
            full = self.series()[0]
            m = next((b for b in darvas.boxes(full["c"]) if b["i0"] == box.get("i0")), None) if full else None
            box = {**box, "confirmed": m["confirmed"] if m else True}
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
            self.geoms["card"] = charts.draw_darcard(self.cv_card, full, dates, win, {"pinned": pinned, "selected": self.selected, "log": self.log.get()})
            self.hit_geom = self.geoms["card"]
        if self.mode.get() == "bars":
            opts = {"macd": self.macd_on.get(), "spx": True, "smas": smas, "tf": self.tf.get(), "log": self.log.get()}
            fb = self.focus_box or (self.selected_box())
            if fb:
                opts["tags"] = [(fb["top"], charts.GREEN), (fb["bottom"], charts.WHITE), (round(fb["bottom"] * 0.95, 2), charts.RED)]
                opts["levels"] = [v for v, _ in opts["tags"]]
                opts["boxes"] = [{"i0": fb["i0"], "i1": fb["i1"] if fb.get("outcome") != "open" else len(full["c"]) - 1, "top": fb["top"], "bottom": fb["bottom"],
                                  "extend": fb.get("outcome") == "open", "color": charts.GOLD, "confirmed": fb.get("confirmed", True)}]
            row = st.row(self.ticker) or {}
            if row.get("pivot") and row.get("base_type") in store.BUYABLE_BASES and abs(row.get("pct_to_pivot") or 99) < 15:
                opts["pivot"] = row["pivot"]
            self.geoms["bars"] = charts.draw_bars(self.cv_bars, full, dates, spx, win, opts)

    SMA_HOVER_PX = 6   # tak blisko linii średniej (w pikselach) kursor ją „łapie”

    def hovered_sma(self, geom, e, i, smas):
        """n średniej, której linia przebiega najbliżej kursora (w granicach SMA_HOVER_PX), albo None."""
        best, best_d = None, self.SMA_HOVER_PX + 1
        for arr, n in smas:
            if i < len(arr) and arr[i] is not None:
                d = abs(geom["y"](arr[i]) - e.y)
                if d < best_d:
                    best, best_d = n, d
        return best

    def on_motion(self, e, cv):
        name = "card" if cv is self.cv_card else "bars"
        geom = self.geoms.get(name)
        i = charts.week_at(geom, e.x)
        full, dates, _spx, smas = self.series()
        for c in (self.cv_card, self.cv_bars):
            c.delete("cross")
        if i is None or not full or i >= len(full["c"]) or full["c"][i] is None:
            return
        for nm, c in (("card", self.cv_card), ("bars", self.cv_bars)):
            g = self.geoms.get(nm)
            if g and c.winfo_ismapped():
                x = g["xf"](i)
                c.create_line(x, g["p_top"], x, g["m_bot"], fill="#3a4350", tags="cross", dash=(2, 2))
        tf = self.tf.get()
        if name == "bars":
            hover = self.hovered_sma(geom, e, i, smas) if e.y <= geom.get("p_bot", geom["m_bot"]) else None
            if hover is not None:   # podświetlenie linii średniej, nad którą jest kursor
                arr = next(a for a, n in smas if n == hover)
                pts = [(geom["xf"](j), geom["y"](arr[j])) for j in range(geom["i0"], min(geom["i1"], len(arr))) if arr[j] is not None]
                if len(pts) > 1:
                    cv.create_line(*[v for p in pts for v in p], fill=charts.SMA_COLORS.get(hover, charts.SMA40), width=4, tags="cross")
            lines = charts.tooltip_bars(full, dates, i, smas, tf, hover)
        else:
            lines = charts.tooltip_card(full, dates, i, tf)
        charts.draw_tooltip(cv, e.x, e.y, lines)
        f = full
        self.read.config(text=f"  {dates[i] if i < len(dates) else ''}   H {f['h'][i]:.2f}  L {f['l'][i]:.2f}  C {f['c'][i]:.2f}   Wol {charts.fmt_vol(f['v'][i]) if f['v'][i] is not None else '-'}")

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
