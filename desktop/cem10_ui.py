"""Okno CEM10: portfel z raportu XTB (udziały, stop −40 %, plan wpłat), krzywa kapitału, lista miesięczna (USA / GPW), wykres miesięczny.
Używane przez Momentum Desktop (przycisk 📈 CEM10) i przez osobny program CEM10 (cem10_main.py); host = obiekt z `root` i `store`."""
import math
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from . import cem10, portfel
from .theme import BG, FG, PANEL, apply_dark, autowrap

MUTED, GREEN, RED, AMBER, BLUE, BAR = "#8b95a3", "#3fb950", "#f85149", "#d29922", "#4a9eff", "#9aa4b2"
BUCKET = {"usa": "CEM10 USA", "gpw": "CEM10 GPW", "etf": "ETF", "inne": "Inne"}


def pct(x):
    return "" if x is None else f"{x * 100:+.1f} %".replace(".", ",")


def share(x):
    return "" if x is None else f"{x * 100:.1f} %".replace(".", ",")


def num(x):
    return "" if x is None else f"{x:,.2f}".replace(",", " ").replace(".", ",")


def zl(x):
    return "" if x is None else f"{x:,.0f} zł".replace(",", " ")


class CEM10Dialog(tk.Toplevel):
    """Portfel CEM10 (raport XTB), krzywa kapitału, lista miesięczna USA (lider SPY / QQQ z 5M, 10 pozycji) i GPW (WIG20 + mWIG40, C-8, 5 pozycji).
    Dane: data/cem10.json (⟳ Pobierz listę), data/xtb.json (raport XTB), skład GPW: data/cem10_gpw.json albo cem10.GPW_DEFAULT. Dwuklik = wykres miesięczny."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("CEM10 — portfel i lista miesięczna")
        self.configure(bg=PANEL)
        self.geometry("1280x860")
        apply_dark(self)
        self.q = queue.Queue()
        self.busy = False
        self.info = autowrap(tk.Label(self, text="", bg=PANEL, anchor="w", justify="left"))
        self.info.pack(fill="x", padx=10, pady=(10, 4))
        row = tk.Frame(self, bg=PANEL)
        row.pack(fill="x", padx=10)
        self.fetch_btn = tk.Button(row, text="⟳ Pobierz listę (ostatni zamknięty miesiąc)", command=self.start_fetch, relief="flat")
        self.fetch_btn.pack(side="left")
        tk.Button(row, text="📂 Wczytaj raport XTB…", command=self.import_xtb, relief="flat").pack(side="left", padx=6)
        tk.Button(row, text="Skład GPW…", command=lambda: CEM10GpwDialog(self), relief="flat").pack(side="left")
        tk.Button(row, text="Zamknij", command=self.destroy, relief="flat").pack(side="right")
        self.pbar = ttk.Progressbar(row, orient="horizontal", mode="determinate", maximum=1000, length=180)
        self.pbar.pack(side="left", padx=8)
        self.plabel = tk.Label(row, text="", bg=PANEL, fg=MUTED)
        self.plabel.pack(side="left")
        tk.Label(self, text="Wyjście: zamknięcie miesiąca pod SMA 10 (w USA też wypadnięcie z indeksów), stop awaryjny −40 % od ceny zakupu. Kupujesz tylko na zamknięciu miesiąca. "
                            "Skład GPW popraw po każdej rewizji (marzec, czerwiec, wrzesień, grudzień). Dwuklik na spółce = wykres miesięczny. To wynik reguł, nie rekomendacja.",
                 bg=PANEL, fg=MUTED, anchor="w", justify="left", wraplength=1160).pack(side="bottom", fill="x", padx=10, pady=(4, 8))
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(8, 0))
        self.tab_pf, self.tab_cv, self.tab_usa, self.tab_gpw, self.tab_man = (tk.Frame(self.tabs, bg=PANEL) for _ in range(5))
        for f, t in ((self.tab_pf, "📊 Portfel"), (self.tab_cv, "📈 Krzywa kapitału"), (self.tab_usa, "USA"), (self.tab_gpw, "GPW"), (self.tab_man, "✋ Ręcznie")):
            self.tabs.add(f, text=t)
        self._build_portfel(self.tab_pf)
        self._build_curve(self.tab_cv)
        self.usa_lbl = tk.Label(self.tab_usa, text="USA", bg=PANEL, anchor="w", font=("TkDefaultFont", 10, "bold"))
        self.usa_lbl.pack(fill="x", pady=(6, 2))
        self.usa = self._tree([("rank", "#", 36), ("t", "Ticker", 70), ("n", "Spółka", 260), ("r6", "Zwrot 6M", 90), ("c", "Zamknięcie", 100),
                               ("sma", "SMA 10", 100), ("dist", "Nad SMA 10", 100), ("idx", "Indeks", 140)], 16, parent=self.tab_usa)
        self.gpw_lbl = tk.Label(self.tab_gpw, text="GPW", bg=PANEL, anchor="w", font=("TkDefaultFont", 10, "bold"))
        self.gpw_lbl.pack(fill="x", pady=(6, 2))
        self.gpw = self._tree([("rank", "#", 36), ("t", "Ticker", 70), ("n", "Spółka", 260), ("r6", "Zwrot 6M", 90), ("r3", "3M", 80),
                               ("r12", "12M", 80), ("c", "Zamknięcie", 100), ("sma", "SMA 10", 100), ("idx", "Indeks", 90)], 16, parent=self.tab_gpw)
        tk.Label(self.tab_man, text="Bez raportu XTB: wpisz tickery, które trzymasz (USA i GPW oddzielone spacją lub przecinkiem; GPW można wymusić końcówką .WA, np. ALE.WA). "
                                    "Po wczytaniu raportu XTB lista uzupełnia się sama.", bg=PANEL, anchor="w", justify="left", wraplength=1140).pack(fill="x", pady=(8, 2))
        self.hold = tk.StringVar(value=app.store.settings.get("cem10_hold", ""))
        tk.Entry(self.tab_man, textvariable=self.hold, relief="flat").pack(fill="x")
        self.held = self._tree([("t", "Ticker", 70), ("n", "Spółka", 260), ("m", "Rynek", 150), ("c", "Zamknięcie", 100), ("sma", "SMA 10", 100),
                                ("dist", "Od SMA 10", 100), ("r6", "Zwrot 6M", 90), ("dec", "Decyzja", 100)], 14, parent=self.tab_man)
        self.held.tag_configure("sell", foreground="#ff8b7e")
        self.hold.trace_add("write", lambda *_: self.on_hold())
        self.bind("<Escape>", lambda e: self.destroy())
        self.data = app.store.cache("cem10") or None
        self.accounts = app.store.cache("xtb").get("accounts") or []
        self.render()
        self.render_portfel()
        self.render_curve()
        self.after(150, self._poll)

    # ------------------------------------------------------------ wspólne
    def _tree(self, cols, height, parent=None, expand=True):
        frame = tk.Frame(parent or self, bg=PANEL)
        frame.pack(fill="both" if expand else "x", expand=expand)
        tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="headings", height=height, selectmode="browse")
        for key, head, width in cols:
            tree.heading(key, text=head)
            tree.column(key, width=width, anchor="w" if key in ("t", "n", "idx", "m", "dec", "b", "st", "a", "u", "d") else "e", stretch=key in ("n", "st", "u"))
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        tree.tag_configure("buy", background="#123a24")
        tree.tag_configure("sell", foreground="#ff8b7e")
        tree.tag_configure("dim", foreground=MUTED)
        tree.bind("<Double-1>", lambda e, tr=tree: self.open(tr))
        return tree

    def open(self, tree):
        """Dwuklik: wykres miesięczny spółki (iid = symbol Yahoo; dla pozycji z XTB z ceną zakupu i stopem −40 %)."""
        sel = tree.selection()
        if not sel or tree not in (self.usa, self.gpw, self.held, self.pf):
            return
        sym = sel[0]
        pos = next((h for h in getattr(self, "hold_rows", []) if portfel.yahoo(h["ticker"]) == sym), None)
        CEM10Chart(self, sym, (pos or {}).get("name") or sym, entry=(pos or {}).get("open_price"))

    def gpw_members(self):
        return self.app.store.cache("cem10_gpw") or cem10.GPW_DEFAULT

    def account(self):
        if not self.accounts:
            return None
        lab = self.acc_var.get()
        return next((a for a in self.accounts if a.get("label") == lab), self.accounts[0])

    # ------------------------------------------------------------ zakładka Portfel
    def _build_portfel(self, tab):
        top = tk.Frame(tab, bg=PANEL)
        top.pack(fill="x", pady=(8, 4))
        tk.Label(top, text="Konto:", bg=PANEL).pack(side="left")
        self.acc_var = tk.StringVar(value=self.app.store.settings.get("xtb_account", ""))
        self.acc_box = ttk.Combobox(top, textvariable=self.acc_var, width=12, state="readonly")
        self.acc_box.pack(side="left", padx=6)
        self.acc_box.bind("<<ComboboxSelected>>", lambda e: self.on_account())
        self.kpi = tk.Label(top, text="", bg=PANEL, anchor="w", justify="left", font=("TkDefaultFont", 10, "bold"))
        self.kpi.pack(side="left", padx=10)
        self.kpi2 = autowrap(tk.Label(tab, text="", bg=PANEL, fg=MUTED, anchor="w", justify="left"))
        self.kpi2.pack(fill="x")
        pw = ttk.PanedWindow(tab, orient="vertical")   # pozycje u góry, plan u dołu; granicę można przeciągnąć
        pw.pack(fill="both", expand=True)
        up = tk.Frame(pw, bg=PANEL)
        self.pf = self._tree([("t", "Ticker", 60), ("n", "Spółka", 140), ("b", "Koszyk", 96), ("v", "Wartość", 84), ("s", "Udział", 62), ("sb", "W koszyku", 82),
                              ("p", "Wynik", 66), ("op", "Cena zakupu", 96), ("cp", "Cena teraz", 90), ("stop", "Stop −40 %", 90), ("sd", "Do stopu", 78),
                              ("st", "Status CEM10", 200)], 8, parent=up)
        box = tk.LabelFrame(pw, text=" Wpłata i plan na zamknięcie miesiąca (dopełnianie do wagi docelowej) ", bg=PANEL, fg=FG)
        pw.add(up, weight=3)
        pw.add(box, weight=2)
        r1 = tk.Frame(box, bg=PANEL)
        r1.pack(fill="x", padx=6, pady=4)
        st = self.app.store.settings
        self.dep_var = tk.StringVar(value=str(st.get("cem10_deposit", 500)))
        tg = st.get("cem10_targets") or {}
        self.tg_vars = {k: tk.StringVar(value=str(tg.get(k, ""))) for k in ("usa", "gpw", "etf")}
        self.etf_var = tk.StringVar(value=st.get("cem10_etf", "CSPX.UK"))
        for lab, var, w in (("Wpłata (zł):", self.dep_var, 8), ("Udział docelowy  USA %:", self.tg_vars["usa"], 5), ("GPW %:", self.tg_vars["gpw"], 5),
                            ("ETF %:", self.tg_vars["etf"], 5), ("ETF (ticker XTB):", self.etf_var, 10)):
            tk.Label(r1, text=lab, bg=PANEL).pack(side="left", padx=(8, 2))
            tk.Entry(r1, textvariable=var, width=w, relief="flat").pack(side="left")
        tk.Button(r1, text="Policz plan", command=self.render_plan, relief="flat").pack(side="left", padx=10)
        self.plan_lbl = autowrap(tk.Label(box, text="", bg=PANEL, fg=MUTED, anchor="w", justify="left"))
        self.plan_lbl.pack(fill="x", padx=6)
        self.plan_tree = self._tree([("a", "Akcja", 80), ("t", "Ticker", 70), ("b", "Koszyk", 90), ("k", "Kwota", 90), ("sh", "≈ akcji", 80), ("u", "Uwagi", 400)], 5,
                                    parent=box)

    def import_xtb(self):
        path = filedialog.askopenfilename(parent=self, title="Raport XTB (zip albo xlsx z xStation: Historia → Eksport)",
                                          filetypes=[("Raport XTB", "*.zip *.xlsx"), ("Wszystkie pliki", "*.*")])
        if not path:
            return
        try:
            accs = portfel.load_report(path)
        except Exception as exc:
            self.plabel.config(text=f"❌ Nie udało się wczytać raportu: {exc}")
            return
        self.accounts = accs
        self.app.store.save_cache("xtb", {"accounts": accs})
        self.acc_var.set(accs[0].get("label") or "")
        self.plabel.config(text=f"✓ Wczytano raport XTB: {', '.join(a.get('label') or '?' for a in accs)}")
        self.on_account()
        self.tabs.select(self.tab_pf)

    def on_account(self):
        self.app.store.settings["xtb_account"] = self.acc_var.get()
        self.app.store.save_settings()
        acc = self.account()
        if acc:   # trzymane spółki CEM10 -> zakładka „Ręcznie” i sito pobierania
            hold, _, _ = portfel.holdings(acc, self.data)
            self.hold.set(", ".join(h["t"] + (".WA" if h["bucket"] == "gpw" else "") for h in hold if h["bucket"] in ("usa", "gpw")))
        self.render_portfel()
        self.render_curve()

    def render_portfel(self):
        self.pf.delete(*self.pf.get_children())
        self.acc_box["values"] = [a.get("label") or "?" for a in self.accounts]
        acc = self.account()
        self.hold_rows = []
        if not acc:
            self.kpi.config(text="Brak raportu XTB.")
            self.kpi2.config(text="Kliknij „📂 Wczytaj raport XTB…”: w xStation Historia konta → Eksport (zip z plikami xlsx dla każdego konta). Program nie łączy się z XTB, czyta tylko plik.")
            self.render_plan()
            return
        if not self.acc_var.get():
            self.acc_var.set(acc.get("label") or "")
        hold, buckets, total = portfel.holdings(acc, self.data)
        self.hold_rows = hold
        dep = sum(x for _, x in portfel.flows(acc))
        prof = total - dep
        self.kpi.config(text=f"Wartość konta {zl(total)}   ·   pozycje {zl(acc['open_value'])}   ·   gotówka {zl(acc['cash'])}   ·   "
                             f"wpłacono netto {zl(dep)}   ·   wynik {zl(prof)} ({pct(prof / dep if dep else None)})")
        parts = "   ·   ".join(f"{BUCKET[b]} {share(v / total if total else 0)} ({zl(v)})" for b, v in buckets.items())
        self.kpi2.config(text=f"Raport z {(acc.get('generated') or '')[:16].replace('T', ' ')} UTC.   Udziały: {parts}   ·   gotówka {share(acc['cash'] / total if total else 0)}"
                              + ("" if self.data else "   ·   brak listy CEM10 — kliknij ⟳ Pobierz listę, żeby zobaczyć statusy"))
        for h in hold:
            tag = "sell" if h["status"].startswith("SPRZEDAJ") else ("dim" if h["bucket"] in ("etf", "inne") else ())
            stop_hit = h.get("stop_dist") is not None and h["stop_dist"] <= 0
            self.pf.insert("", "end", iid=portfel.yahoo(h["ticker"]), tags=("sell",) if stop_hit else tag,
                           values=(h["t"], h["name"], BUCKET[h["bucket"]], zl(h["value"]), share(h["share"]), share(h["bucket_share"]), pct((h.get("profit_pct") or 0) / 100),
                                   num(h.get("open_price")), num(h.get("price")), num(h.get("stop")), pct(h.get("stop_dist")),
                                   "SPRZEDAJ (stop −40 %)" if stop_hit else h["status"]))
        tg = self.app.store.settings.get("cem10_targets")
        if not tg or not any(tg.values()):   # pierwsze wczytanie: udziały docelowe = obecne, zaokrąglone do 5 %
            base = {b: buckets.get(b, 0.0) for b in ("usa", "gpw", "etf")}
            s = sum(base.values()) or 1.0
            for b, var in self.tg_vars.items():
                var.set(str(int(round(base[b] / s * 20) * 5)))
        self.render_plan()

    def _targets(self):
        out = {}
        for b, var in self.tg_vars.items():
            try:
                out[b] = max(float(var.get().replace(",", ".") or 0), 0.0)
            except ValueError:
                out[b] = 0.0
        return out

    def render_plan(self):
        self.plan_tree.delete(*self.plan_tree.get_children())
        acc = self.account()
        if not acc:
            self.plan_lbl.config(text="Plan pojawi się po wczytaniu raportu XTB.")
            return
        try:
            dep = max(float(self.dep_var.get().replace(",", ".").replace(" ", "") or 0), 0.0)
        except ValueError:
            dep = 0.0
        tg = self._targets()
        st = self.app.store.settings
        st["cem10_deposit"], st["cem10_targets"], st["cem10_etf"] = dep, tg, self.etf_var.get().strip() or "CSPX.UK"
        self.app.store.save_settings()
        if not self.data:
            self.plan_lbl.config(text="Najpierw pobierz listę CEM10 (⟳ Pobierz listę) — plan potrzebuje kandydatów i statusów.")
            return
        actions, s = portfel.plan(acc, self.data, deposit=dep, targets=tg, etf_ticker=st["cem10_etf"])
        prices = {r["t"]: r["c"] for r in self.data["usa"]["rows"]} | {r["t"]: r["c"] for r in self.data["gpw"]["rows"]}
        usd = next((h["fx"] for h in self.hold_rows if h.get("ccy") == "USD" and h.get("fx")), 3.8)
        for i, a in enumerate(actions):
            p = prices.get(a["ticker"])
            k = usd if a["koszyk"] == "usa" else 1.0
            shares = f"{a['kwota'] / (p * k):.4f}".replace(".", ",") if p and a["akcja"] != "SPRZEDAJ" else ("wszystkie" if a["akcja"] == "SPRZEDAJ" else "")
            self.plan_tree.insert("", "end", iid=f"{i}", values=(a["akcja"], a["ticker"], BUCKET[a["koszyk"]], zl(a["kwota"]), shares, a["uwagi"]),
                                  tags=("sell",) if a["akcja"] == "SPRZEDAJ" else ("buy",))
        al = s["alloc"]
        self.plan_lbl.config(text=(f"Do rozdysponowania {zl(s['free'])} (gotówka + wpłata + sprzedaże). Podział wg niedoboru do udziałów docelowych: "
                                   f"USA {zl(al['usa'])}, GPW {zl(al['gpw'])}, ETF {zl(al['etf'])}; zostaje w gotówce {zl(s['cash_left'])}. "
                                   "Liczba akcji z zamknięcia miesiąca (kurs USD z raportu), w XTB kupujesz za kwotę. "
                                   + " ".join(s["notes"])) if actions or s["notes"] else
                            f"Brak działań: wszystko trzymasz, a {zl(s['free'])} zostaje w gotówce (za mało na zakup ≥ {zl(portfel.MIN_TOPUP)} albo koszyki są na wadze docelowej).")

    # ------------------------------------------------------------ zakładka Krzywa kapitału
    def _build_curve(self, tab):
        top = tk.Frame(tab, bg=PANEL)
        top.pack(fill="x", pady=(8, 4))
        self.curve_btn = tk.Button(top, text="⟳ Przelicz krzywą (ceny dzienne z Yahoo)", command=self.start_curve, relief="flat")
        self.curve_btn.pack(side="left")
        self.curve_lbl = tk.Label(top, text="", bg=PANEL, fg=MUTED)
        self.curve_lbl.pack(side="left", padx=8)
        self.cv = tk.Canvas(tab, bg=BG, highlightthickness=0, height=380)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Configure>", lambda e: self.draw_curve())
        self.ev = self._tree([("d", "Data", 90), ("a", "Zdarzenie", 110), ("t", "Ticker", 80), ("k", "Kwota / wynik", 110), ("p", "Wynik %", 80)], 7, parent=tab, expand=False)

    def start_curve(self):
        acc = self.account()
        if not acc or self.busy:
            return
        self.busy = True
        self.curve_btn.config(state="disabled")
        self.curve_lbl.config(text="Pobieram ceny dzienne…")

        def work():
            try:
                px, fxs = portfel.curve_prices(acc, log=lambda m: self.q.put(("log", m)))
                self.q.put(("curve", {"generated": acc.get("generated"), "label": acc.get("label"), "points": portfel.curve(acc, px, fxs)}))
            except Exception as exc:
                self.q.put(("curve_error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def curve_points(self):
        acc = self.account()
        c = self.app.store.cache("xtb_curve")
        if acc and c.get("label") == acc.get("label") and c.get("generated") == acc.get("generated"):
            return c.get("points") or []
        return portfel.curve(acc) if acc else []   # bez cen z sieci: wycena lotów liniowo między ceną otwarcia i zamknięcia

    def render_curve(self):
        self.ev.delete(*self.ev.get_children())
        acc = self.account()
        if not acc:
            self.curve_lbl.config(text="Wczytaj raport XTB.")
            self.draw_curve()
            return
        cached = self.app.store.cache("xtb_curve")
        exact = cached.get("label") == acc.get("label") and cached.get("generated") == acc.get("generated")
        self.curve_lbl.config(text="Wycena z cen dziennych Yahoo." if exact else "Przybliżenie bez cen rynkowych — kliknij ⟳ Przelicz krzywą, żeby wycenić pozycje cenami dziennymi.")
        evs = [(d, "wpłata" if x > 0 else "wypłata", "", zl(x), "") for d, x in portfel.flows(acc)]
        evs += [(d, "sprzedaż", t, zl(p), pct(r)) for d, t, p, r in portfel.exits(acc)]
        for i, e in enumerate(sorted(evs, reverse=True)):
            self.ev.insert("", "end", iid=f"e{i}", values=e, tags=("buy",) if e[1] == "wpłata" else ("sell",) if e[3].startswith("-") else ())
        self.draw_curve()

    def draw_curve(self):
        cv = self.cv
        cv.delete("all")
        acc = self.account()
        w, h = max(cv.winfo_width(), 200), max(cv.winfo_height(), 120)
        pts = self.curve_points() if acc else []
        if len(pts) < 2:
            cv.create_text(w / 2, h / 2, text="Krzywa kapitału pojawi się po wczytaniu raportu XTB.", fill=MUTED)
            return
        x0, x1, y0, y1 = 70, w - 20, 20, h - 30
        lo = min(min(p[1] for p in pts), min(p[2] for p in pts))
        hi = max(max(p[1] for p in pts), max(p[2] for p in pts))
        lo, hi = lo - (hi - lo) * 0.05, hi + (hi - lo) * 0.05 or 1
        n = len(pts)

        def xf(i):
            return x0 + (x1 - x0) * i / (n - 1)

        def yf(v):
            return y1 - (v - lo) / (hi - lo) * (y1 - y0)
        for k in range(5):   # siatka i oś
            v = lo + (hi - lo) * k / 4
            cv.create_line(x0, yf(v), x1, yf(v), fill="#1c232c")
            cv.create_text(x0 - 6, yf(v), text=f"{v:,.0f}".replace(",", " "), fill=MUTED, anchor="e", font=("TkDefaultFont", 8))
        step = max(n // 6, 1)
        for i in range(0, n, step):
            cv.create_text(xf(i), y1 + 12, text=pts[i][0], fill=MUTED, font=("TkDefaultFont", 8))
        cv.create_line(*[c for i, p in enumerate(pts) for c in (xf(i), yf(p[2]))], fill=AMBER, width=1.5, dash=(4, 3))
        cv.create_line(*[c for i, p in enumerate(pts) for c in (xf(i), yf(p[1]))], fill=BLUE, width=2)
        idx = {p[0]: i for i, p in enumerate(pts)}
        days = [p[0] for p in pts]

        def at(d):
            from bisect import bisect_left
            return idx.get(d, min(bisect_left(days, d), n - 1))
        for d, x in portfel.flows(acc):
            i = at(d)
            cv.create_polygon(xf(i) - 5, yf(pts[i][2]) + 9, xf(i) + 5, yf(pts[i][2]) + 9, xf(i), yf(pts[i][2]) + 1, fill=GREEN if x > 0 else RED, outline="")
        for d, t, p, r in portfel.exits(acc):
            i = at(d)
            cv.create_polygon(xf(i) - 4, yf(pts[i][1]) - 9, xf(i) + 4, yf(pts[i][1]) - 9, xf(i), yf(pts[i][1]) - 2, fill=GREEN if p >= 0 else RED, outline="")
        last = pts[-1]
        cv.create_text(x0 + 6, y0 + 4, anchor="nw", fill=FG, font=("TkDefaultFont", 9),
                       text=f"— wartość konta {zl(last[1])}     - - wpłacono netto {zl(last[2])}     ▲ wpłata     ▼ sprzedaż (zielona = zysk, czerwona = strata)")

    # ------------------------------------------------------------ lista CEM10
    def render(self):
        D = self.data
        for tr in (self.usa, self.gpw):
            tr.delete(*tr.get_children())
        if not D:
            self.info.config(text="Brak listy. Kliknij „⟳ Pobierz listę” (skład z Wikipedii, sito Finviz, ceny miesięczne z Yahoo Finance dla ok. 180 spółek, ok. minuty).")
            self.on_hold()
            return
        U, G = D["usa"], D["gpw"]
        lead = "Nasdaq-100" if U["lead"] == "NDX" else "S&P 500"
        self.info.config(text=f"Lista CEM10 na zamknięcie {D['month']} (pobrano {D['generated_at']}).   USA: lider {lead} (5M: SPY {pct(U['spy5'])}, QQQ {pct(U['qqq5'])}), "
                              f"filtr rynku {'BRAK ZAKUPÓW (SPY pod SMA 12)' if U['bear'] else 'zakupy dozwolone'} (SPY {num(U['spy'])} / SMA 12 {num(U['spy_sma12'])}).   "
                              f"GPW: filtr rynku {'BRAK ZAKUPÓW' if G['bear'] else 'zakupy dozwolone'} (indeks koszyka {num(G['lv'])} / SMA 12 {num(G['lv12'])}), "
                              f"skład z rewizji {G.get('rewizja') or '—'}.")
        uc = cem10.usa_candidates(U["rows"], U["lead"])
        pf = U.get("prefilter")
        sito = f" · sito Finviz 6M > +20 %: S&P 500 {pf['sp']}, Nasdaq-100 {pf['nq']}" if pf else ""
        self.usa_lbl.config(text=f"USA · {U['n']} pozycji · kandydaci z {lead}: {len(uc)}{sito}")
        self.tabs.tab(self.tab_usa, text=f"USA · {lead} · {min(len(uc), U['n'])} do kupienia" if not U["bear"] else "USA · brak zakupów")
        for i, r in enumerate(uc):
            idx = ", ".join(x for x, f in (("S&P 500", r.get("sp")), ("NDX", r.get("nq"))) if f)
            self.usa.insert("", "end", iid=r["t"], values=(i + 1, r["t"], r["n"], pct(r["r6"]), num(r["c"]), num(r["sma"]), pct(r["dist"]), idx),
                            tags=("buy",) if i < U["n"] and not U["bear"] else ())
        gc_ = cem10.gpw_candidates(G["rows"])
        self.gpw_lbl.config(text=f"GPW · {G['n']} pozycji · WIG20 + mWIG40 bez lidera, C-8 · kandydaci: {len(gc_)}")
        self.tabs.tab(self.tab_gpw, text=f"GPW · {min(len(gc_), G['n'])} do kupienia" if not G["bear"] else "GPW · brak zakupów")
        for i, r in enumerate(gc_):
            self.gpw.insert("", "end", iid=r["t"] + ".WA", values=(i + 1, r["t"], r["n"], pct(r["r6"]), pct(r["r3"]), pct(r["r12"]), num(r["c"]), num(r["sma"]),
                                                                   "WIG20" if r.get("w20") else "mWIG40"), tags=("buy",) if i < G["n"] and not G["bear"] else ())
        self.on_hold()

    def on_hold(self):
        text = self.hold.get()
        if self.app.store.settings.get("cem10_hold", "") != text:
            self.app.store.settings["cem10_hold"] = text
            self.app.store.save_settings()
        self.held.delete(*self.held.get_children())
        D = self.data or {"usa": {"rows": []}, "gpw": {"rows": []}}
        us = {r["t"]: r for r in D["usa"]["rows"]}
        gp = {r["t"]: r for r in D["gpw"]["rows"]}
        for t in cem10.parse_tickers(text):
            if t.endswith(".WA"):            # .WA = spółka z GPW (np. ALE.WA = Allegro, ALE = Allete w USA)
                t = t[:-3]
                r, m, iid = gp.get(t), "GPW", t + ".WA"
            else:
                r, m, iid = us.get(t) or us.get(t.replace(".", "-")), "USA", t
                if r is None and t in gp:
                    r, m, iid = gp[t], "GPW", t + ".WA"
            if self.held.exists(iid):
                continue
            dec = cem10.decide(r)
            if r is None and m == "USA" and t in (D["usa"].get("all") or []):
                self.held.insert("", "end", iid=iid, values=(t, "jest w S&P 500 / Nasdaq-100, ale nie było jej w pobranych danych (dopisana po pobraniu) — kliknij ⟳ Pobierz listę",
                                                              "", "", "", "", "", dec), tags=("sell",))
            elif r is None:
                self.held.insert("", "end", iid=iid, values=(t, "nie ma w S&P 500, Nasdaq-100, WIG20 ani mWIG40 — w USA oznacza to sprzedaż", "", "", "", "", "", dec), tags=("sell",))
            else:
                idx = ", ".join(x for x, f in (("S&P 500", r.get("sp")), ("NDX", r.get("nq")), ("WIG20", r.get("w20")), ("mWIG40", r.get("w40"))) if f)
                self.held.insert("", "end", iid=iid, values=(r["t"], r["n"], f"{m} · {idx}", num(r["c"]), num(r["sma"]), pct(r["dist"]), pct(r["r6"]), dec),
                                 tags=("sell",) if dec != "trzymaj" else ())

    def start_fetch(self):
        if self.busy:
            return
        self.busy = True
        self.fetch_btn.config(state="disabled")
        self.pbar["value"] = 0
        gpw, old, held = self.gpw_members(), self.data, cem10.parse_tickers(self.hold.get())

        def work():
            try:
                d = cem10.fetch(gpw, old, log=lambda m: self.q.put(("log", m)), progress=lambda f: self.q.put(("progress", f)), held=held)
                self.q.put(("done", d))
            except Exception as exc:
                self.q.put(("error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.plabel.config(text=val)
                elif kind == "progress":
                    self.pbar["value"] = val * 1000
                elif kind == "done":
                    self.busy = False
                    self.fetch_btn.config(state="normal")
                    self.data = val
                    self.app.store.save_cache("cem10", val)
                    self.plabel.config(text=f"✓ Lista za {val['month']}")
                    self.render()
                    self.render_portfel()
                elif kind == "error":
                    self.busy = False
                    self.fetch_btn.config(state="normal")
                    self.plabel.config(text=f"❌ {val}")
                elif kind == "curve":
                    self.busy = False
                    self.curve_btn.config(state="normal")
                    self.app.store.save_cache("xtb_curve", val)
                    self.render_curve()
                elif kind == "curve_error":
                    self.busy = False
                    self.curve_btn.config(state="normal")
                    self.curve_lbl.config(text=f"❌ {val}")
        except queue.Empty:
            pass
        self.after(150, self._poll)


class CEM10Chart(tk.Toplevel):
    """Wykres miesięczny (Yahoo, ostatnie lata): słupki OHLC w jednym kolorze, SMA 10 z zamknięć, wolumen (zielony = wzrost, czerwony = spadek) ze średnią 10,
    linia ceny zakupu i stop −40 % dla pozycji z raportu XTB. Ostatni słupek = miesiąc w toku (jaśniejszy)."""

    def __init__(self, parent, sym, title, entry=None, data=None):
        super().__init__(parent)
        self.sym, self.entry, self.data = sym, entry, data
        self.title(f"{sym} — wykres miesięczny")
        self.configure(bg=PANEL)
        self.geometry("980x620")
        apply_dark(self)
        self.head = tk.Label(self, text=f"{title} ({sym}) — pobieram świece miesięczne…", bg=PANEL, anchor="w", font=("TkDefaultFont", 10, "bold"))
        self.head.pack(fill="x", padx=10, pady=(8, 2))
        self.cv = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.cv.pack(fill="both", expand=True, padx=6, pady=6)
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.bind("<Escape>", lambda e: self.destroy())
        self.q = queue.Queue()
        if data is None:
            threading.Thread(target=self._load, daemon=True).start()
            self.after(150, self._poll)

    def _load(self):
        try:
            from .prices import _yf
            df = _yf().download(self.sym, period="10y", interval="1mo", auto_adjust=False, progress=False)
            if hasattr(df.columns, "levels"):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=["Close"])
            self.q.put(("ok", {"d": [x.strftime("%Y-%m") for x in df.index], **{k: [float(v) for v in df[c]] for k, c in
                                                                                    (("o", "Open"), ("h", "High"), ("l", "Low"), ("c", "Close"), ("v", "Volume"))}}))
        except Exception as exc:
            self.q.put(("err", str(exc)))

    def _poll(self):
        if not self.winfo_exists():
            return
        try:
            kind, val = self.q.get_nowait()
        except queue.Empty:
            self.after(150, self._poll)
            return
        if kind == "ok":
            self.data = val
            self.draw()
        else:
            self.head.config(text=f"❌ {self.sym}: {val}")

    def draw(self):
        cv = self.cv
        cv.delete("all")
        D = self.data
        if not D or len(D["c"]) < 3:
            return
        n_all = len(D["c"])
        k0 = max(n_all - 60, 0)                       # ostatnie 5 lat
        sma = [None if i < 9 else sum(D["c"][i - 9:i + 1]) / 10 for i in range(n_all)]
        vsma = [None if i < 9 else sum(D["v"][i - 9:i + 1]) / 10 for i in range(n_all)]
        idx = list(range(k0, n_all))
        n = len(idx)
        w, h = max(cv.winfo_width(), 300), max(cv.winfo_height(), 200)
        x0, x1 = 10, w - 120
        py0, py1 = 24, int(h * 0.72)
        vy0, vy1 = py1 + 14, h - 22
        stop = self.entry * (1 - portfel.STOP) if self.entry else None
        vals = [v for i in idx for v in (D["h"][i], D["l"][i]) if v] + [v for v in (self.entry, stop) if v] + [sma[i] for i in idx if sma[i]]
        lmin, lmax = math.log(min(vals) * 0.95), math.log(max(vals) * 1.05)
        step = (x1 - x0) / n

        def xf(j):
            return x0 + (j + 0.5) * step

        def yf(p):
            return py1 - (math.log(p) - lmin) / (lmax - lmin) * (py1 - py0)
        for k in range(6):   # siatka ceny (skala log.)
            p = math.exp(lmin + (lmax - lmin) * k / 5)
            cv.create_line(x0, yf(p), x1, yf(p), fill="#1c232c")
            cv.create_text(x1 + 6, yf(p), text=num(p), fill=MUTED, anchor="w", font=("TkDefaultFont", 8))
        for j, i in enumerate(idx):
            col = BAR if i < n_all - 1 else MUTED
            x = xf(j)
            cv.create_line(x, yf(D["h"][i]), x, yf(D["l"][i]), fill=col)
            cv.create_line(x - step * 0.35, yf(D["o"][i]), x, yf(D["o"][i]), fill=col)
            cv.create_line(x, yf(D["c"][i]), x + step * 0.35, yf(D["c"][i]), fill=col)
            if j % 12 == 0 or j == n - 1:
                cv.create_text(x, vy1 + 10, text=D["d"][i], fill=MUTED, font=("TkDefaultFont", 8))
        pts = [c for j, i in enumerate(idx) if sma[i] for c in (xf(j), yf(sma[i]))]
        if len(pts) >= 4:
            cv.create_line(*pts, fill=BLUE, width=2)
        for lvl, col, lab in ((self.entry, AMBER, "zakup"), (stop, RED, "stop −40 %")):
            if lvl:
                cv.create_line(x0, yf(lvl), x1, yf(lvl), fill=col, dash=(5, 3))
                cv.create_text(x1 + 6, yf(lvl), text=f"{lab} {num(lvl)}", fill=col, anchor="w", font=("TkDefaultFont", 8, "bold"))
        vmax = max(D["v"][i] for i in idx) or 1
        for j, i in enumerate(idx):
            up = D["c"][i] >= (D["c"][i - 1] if i > 0 else D["o"][i])
            cv.create_rectangle(xf(j) - step * 0.35, vy1 - D["v"][i] / vmax * (vy1 - vy0), xf(j) + step * 0.35, vy1, fill=GREEN if up else RED, outline="")
        vp = [c for j, i in enumerate(idx) if vsma[i] for c in (xf(j), vy1 - vsma[i] / vmax * (vy1 - vy0))]
        if len(vp) >= 4:
            cv.create_line(*vp, fill=AMBER, width=1.5)
        last_closed = n_all - 2
        c, s = D["c"][last_closed], sma[last_closed]
        state = "" if s is None else (" · NAD SMA 10 (trzymaj)" if c >= s else " · POD SMA 10 (sprzedaj)")
        self.head.config(text=f"{self.sym}: zamknięcie {D['d'][last_closed]} {num(c)}, SMA 10 {num(s)}{state}"
                              + (f" · zakup {num(self.entry)}, stop −40 % {num(stop)}" if self.entry else "") + " · ostatni słupek = miesiąc w toku")
        cv.create_text(x0 + 4, py0 - 14, anchor="nw", fill=MUTED, font=("TkDefaultFont", 8),
                       text="słupki miesięczne · niebieska = SMA 10 (zamknięcia) · wolumen: zielony = wzrost, czerwony = spadek, żółta = średnia 10 mies.")


class CEM10GpwDialog(tk.Toplevel):
    """Skład WIG20 i mWIG40 do listy CEM10: jeden ticker na wiersz (opcjonalnie z nazwą), zapis w data/cem10_gpw.json."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("CEM10 — skład GPW")
        self.configure(bg=PANEL)
        apply_dark(self)
        g = parent.gpw_members()
        tk.Label(self, text="Po każdej rewizji GPW (marzec, czerwiec, wrzesień, grudzień) dopisz nowe spółki i usuń te, które wypadły.\n"
                            "Jeden ticker GPW na wiersz (bez .WA), po spacji może być nazwa. Ceny pobierają się z Yahoo Finance jako TICKER.WA.",
                 bg=PANEL, anchor="w", justify="left").pack(fill="x", padx=10, pady=(10, 4))
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="x", padx=10)
        tk.Label(top, text="Data rewizji:", bg=PANEL).pack(side="left")
        self.rev = tk.StringVar(value=g.get("rewizja", ""))
        tk.Entry(top, textvariable=self.rev, width=12, relief="flat").pack(side="left", padx=6)
        boxes = tk.Frame(self, bg=PANEL)
        boxes.pack(fill="both", expand=True, padx=10, pady=6)
        self.txt = {}
        for col, key in enumerate(("WIG20", "mWIG40")):
            f = tk.Frame(boxes, bg=PANEL)
            f.grid(row=0, column=col, sticky="nsew", padx=4)
            boxes.grid_columnconfigure(col, weight=1)
            tk.Label(f, text=f"{key} ({len(g[key])})", bg=PANEL).pack(anchor="w")
            t = tk.Text(f, width=44, height=24, bg=BG, fg=FG, insertbackground=FG, relief="flat")
            t.pack(fill="both", expand=True)
            t.insert("1.0", "\n".join(f"{k} {v}" for k, v in g[key].items()))
            self.txt[key] = t
        row = tk.Frame(self, bg=PANEL)
        row.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(row, text="Zapisz", command=self.save, relief="flat").pack(side="left")
        tk.Button(row, text="Przywróć domyślny skład", command=self.reset, relief="flat").pack(side="left", padx=6)
        tk.Button(row, text="Anuluj", command=self.destroy, relief="flat").pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())

    @staticmethod
    def parse(text):
        out = {}
        for line in text.splitlines():
            parts = line.strip().split(None, 1)
            if parts:
                t = parts[0].upper().replace(".WA", "")
                out[t] = parts[1].strip() if len(parts) > 1 else t
        return out

    def save(self):
        g = {"rewizja": self.rev.get().strip(), "WIG20": self.parse(self.txt["WIG20"].get("1.0", "end")),
             "mWIG40": self.parse(self.txt["mWIG40"].get("1.0", "end"))}
        self.parent.app.store.save_cache("cem10_gpw", g)
        self.parent.plabel.config(text=f"✓ Zapisano skład GPW ({len(g['WIG20'])} + {len(g['mWIG40'])}); kliknij ⟳ Pobierz, żeby przeliczyć listę.")
        self.destroy()

    def reset(self):
        self.parent.app.store.save_cache("cem10_gpw", {})
        self.parent.plabel.config(text="✓ Przywrócono domyślny skład GPW; kliknij ⟳ Pobierz, żeby przeliczyć listę.")
        self.destroy()
