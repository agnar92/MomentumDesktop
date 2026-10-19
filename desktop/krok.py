"""🧭 Krok po kroku — jedna informacja na ekran (jak krok.html w Momentum):
1 · Rynek — S&P 500, Nasdaq 100 i Dow Jones na tygodniowych wykresach 10:30 (cena, SMA 10, SMA 30) + werdykt;
2 · Sektory — 11 ETF SPDR od najwyższego Mansfield RS względem S&P 500 (zaznacz sektory, z których szukasz akcji);
3 · Akcje — WSZYSTKIE spółki tych sektorów z Finviz, od najwyższego Mansfield RS względem ETF ich sektora; zaznaczone (klik ☑) → nowy skan z GLB i boxami."""
import queue
import threading
import tkinter as tk
from datetime import date
from tkinter import messagebox, simpledialog, ttk

from . import charts, glb, overview, scanners, store, sync
from .theme import BG, PANEL, Flow, apply_dark, fit_window
from .widgets import STATE_COLORS

STEPS = (("rynek", "1 · Rynek"), ("sektory", "2 · Sektory"), ("akcje", "3 · Akcje"))
VERDICT_COLORS = {"up": "#3ddc84", "flat": "#ffd166", "down": "#ff5c5c", "na": "#8b95a3"}


def _f(v, nd=1, suffix=" %"):
    return "" if v is None else f"{v:+.{nd}f}{suffix}"


class KrokWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        from .app import ChartHost
        self.app = app
        self.host = ChartHost(app, self)
        self.title("🧭 Krok po kroku — rynek → sektory → akcje")
        self.configure(bg=BG)
        apply_dark(self)
        ses = app.session.setdefault("krok", {})
        self.step_var = tk.StringVar(value=ses.get("step") if ses.get("step") in dict(STEPS) else "rynek")
        self.sectors = list(ses.get("sectors") or [])
        self.source = ses.get("source") or scanners.DEFAULT_ID
        self.ov = overview.load(app.data_root)
        self.q = queue.Queue()
        head = Flow(self)
        head.pack(fill="x")
        for key, text in STEPS:
            head.add(tk.Radiobutton(head, text=text, value=key, variable=self.step_var, command=self.show, bg=PANEL, indicatoron=False, padx=14, pady=4,
                                    font=("Consolas", 11, "bold")))
        head.add(tk.Button(head, text="⟳ Odśwież rynek i sektory", command=self.refresh_data, relief="flat"))
        self.info = tk.Label(head, text="", bg=PANEL, fg="#8b95a3")
        head.add(self.info)
        foot = tk.Frame(self, bg=PANEL)
        foot.pack(fill="x", side="bottom")
        self.btn_back = tk.Button(foot, text="‹ Wstecz", command=lambda: self.go(-1))
        self.btn_next = tk.Button(foot, text="Dalej ›", command=lambda: self.go(1))
        self.btn_back.pack(side="left", padx=8, pady=4)
        self.btn_next.pack(side="right", padx=8, pady=4)
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True)
        self.rows = {}
        fit_window(self, 1180, 860)
        if overview.stale(self.ov):
            self.refresh_data()
        self.show()

    # --- dane rynku i sektorów (yfinance w tle)
    def refresh_data(self):
        self.info.config(text="⏳ pobieram tygodniowe zamknięcia indeksów i ETF sektorów (yfinance)…")

        def work():
            try:
                self.q.put(("ok", overview.fetch(self.app.data_root, log=lambda s: None)))
            except Exception as e:   # noqa: BLE001 — brak sieci nie może zamknąć okna; zostają ostatnie dane z dysku
                self.q.put(("err", str(e)))
        threading.Thread(target=work, daemon=True).start()
        self.after(300, self._poll)

    def _poll(self):
        try:
            kind, val = self.q.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self.after(300, self._poll)
            return
        if kind == "ok":
            self.ov = val
            self.info.config(text=f"dane z {val.get('fetched', '')[:16].replace('T', ' ')} UTC")
            if self.step_var.get() != "akcje":
                self.show()
        else:
            self.info.config(text=f"⚠️ nie udało się pobrać danych ({val[:80]}) — pokazuję ostatnie zapisane")

    def save_state(self):
        self.app.session["krok"] = {"step": self.step_var.get(), "sectors": self.sectors, "source": self.source}
        self.app.save_session()

    def go(self, delta):
        keys = [k for k, _ in STEPS]
        i = keys.index(self.step_var.get()) + delta
        if 0 <= i < len(keys):
            self.step_var.set(keys[i])
            self.show()

    def show(self):
        for w in self.body.winfo_children():
            w.destroy()
        step = self.step_var.get()
        self.btn_back.config(state="normal" if step != "rynek" else "disabled")
        self.btn_next.config(state="normal" if step != "akcje" else "disabled",
                             text={"rynek": "Dalej: 2 · Sektory ›", "sektory": "Dalej: 3 · Akcje ›"}.get(step, "Dalej ›"))
        if self.ov.get("fetched") and not self.info.cget("text"):
            self.info.config(text=f"dane z {self.ov['fetched'][:16].replace('T', ' ')} UTC")
        {"rynek": self.show_market, "sektory": self.show_sectors, "akcje": self.show_stocks}[step]()
        self.save_state()

    def _header(self, question, explain):
        tk.Label(self.body, text=question, bg=BG, fg="#ffffff", font=("Consolas", 15, "bold"), anchor="w").pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(self.body, text=explain, bg=BG, fg="#8b95a3", anchor="w", justify="left", wraplength=1100).pack(fill="x", padx=12, pady=(2, 6))

    def _verdict(self, state, text):
        tk.Label(self.body, text=text, bg=VERDICT_COLORS.get(state, "#8b95a3"), fg="#000000", font=("Consolas", 11, "bold"), anchor="w", padx=10, pady=4
                 ).pack(fill="x", padx=12, pady=(0, 6))

    def _chart(self, parent, c, weeks, title, stats, height=None):
        cv = tk.Canvas(parent, bg=BG, highlightthickness=0, height=height or 200)
        cv.pack(fill="both", expand=True, padx=12, pady=3)
        cv.bind("<Configure>", lambda e: charts.draw_1030(cv, c, weeks, {"title": title, "stats": stats}))
        return cv

    def _stats(self, c, bench=None):
        p, tr = overview.perf(c), overview.trend1030(c)
        st = [("Kurs", f"{tr.get('close', 0):.2f}" if tr.get("close") else "—", None), ("Tydzień", charts.pct_txt(p.get("w")), charts.pct_col(p.get("w"))),
              ("3 mies.", charts.pct_txt(p.get("q")), charts.pct_col(p.get("q"))), ("Rok", charts.pct_txt(p.get("y")), charts.pct_col(p.get("y"))),
              ("vs SMA 30", charts.pct_txt(tr.get("pct30")), charts.pct_col(tr.get("pct30")))]
        if bench is not None:
            m = overview.mansfield(c, bench)
            st.append(("Mansfield RS (vs S&P)", charts.pct_txt(m), charts.pct_col(m)))
        return st

    # --- krok 1: rynek
    def show_market(self):
        self._header("Gdzie jest rynek?", "Tygodniowe wykresy 10:30: szara linia = cena, niebieska = SMA 10 tyg., żółta = SMA 30 tyg. Trend rośnie, gdy cena i SMA 10 są nad "
                     "rosnącą SMA 30.")
        items, weeks = self.ov.get("items") or {}, self.ov.get("weeks") or []
        if not items:
            self._verdict("na", "Brak danych — kliknij „⟳ Odśwież rynek i sektory” (potrzebny internet).")
            return
        trends = [overview.trend1030(items[t]) for t, _ in overview.INDEXES if t in items]
        self._verdict(*overview.market_verdict(trends))
        for t, name in overview.INDEXES:
            if t in items:
                self._chart(self.body, items[t], weeks, f"{name} ({t})", self._stats(items[t], items.get("^GSPC") if t != "^GSPC" else None))

    # --- krok 2: sektory
    def show_sectors(self):
        self._header("Które sektory są silne?", "Mansfield RS = siła ETF sektora względem S&P 500 wobec jej średniej z 52 tygodni (> 0 = silniejszy od rynku). "
                     "Zaznacz sektory (Ctrl / Shift + klik), z których chcesz szukać akcji w kroku 3.")
        rows = overview.sector_rows(self.ov)
        if not rows:
            self._verdict("na", "Brak danych — kliknij „⟳ Odśwież rynek i sektory”.")
            return
        strong = [r for r in rows if (r["mrs"] or 0) > 0]
        self._verdict("up" if len(strong) >= 4 else "flat" if strong else "down",
                      f"Silniejsze od S&P 500: {len(strong)} z {len(rows)} sektorów" + (f" — najsilniejszy {rows[0]['name']} ({rows[0]['ticker']}, Mansfield {rows[0]['mrs']:+.1f} %)" if rows[0]["mrs"] is not None else ""))
        frame = tk.Frame(self.body, bg=BG)
        frame.pack(fill="x", padx=12)
        cols = (("name", "Sektor", 200, "w"), ("mrs", "Mansfield RS", 110, "e"), ("trend", "10:30", 120, "w"), ("q", "3 mies.", 90, "e"), ("y", "Rok", 90, "e"))
        tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="tree headings", selectmode="extended", height=11)
        tree.heading("#0", text="ETF")
        tree.column("#0", width=80)
        for key, text, w, anchor in cols:
            tree.heading(key, text=text)
            tree.column(key, width=w, anchor=anchor)
        tree.tag_configure("pos", foreground="#3ddc84")
        tree.tag_configure("neg", foreground="#ff6b6b")
        for r in rows:
            tree.insert("", "end", iid=r["ticker"], text=r["ticker"], values=(r["name"], _f(r["mrs"]), overview.TREND_LABELS[r["trend"]], _f(r["q"]), _f(r["y"])),
                        tags=("pos" if (r["mrs"] or 0) > 0 else "neg",))
        tree.pack(fill="x")
        pick = [r["ticker"] for r in rows if r["sector"] in self.sectors] or [r["ticker"] for r in strong]   # domyślnie wszystkie sektory z dodatnim RS
        if pick:
            tree.selection_set(pick)
        holder = tk.Frame(self.body, bg=BG)
        holder.pack(fill="both", expand=True)
        by = {r["ticker"]: r for r in rows}
        items, weeks = self.ov.get("items") or {}, self.ov.get("weeks") or []

        def on_sel(_e=None):
            sel = tree.selection()
            self.sectors = [by[t]["sector"] for t in sel]
            self.save_state()
            focus = tree.focus() or (sel[0] if sel else rows[0]["ticker"])
            for w in holder.winfo_children():
                w.destroy()
            self._chart(holder, items[focus], weeks, f"{by[focus]['name']} ({focus})", self._stats(items[focus], items.get("^GSPC")))
        tree.bind("<<TreeviewSelect>>", on_sel)
        on_sel()

    # --- krok 3: akcje
    def show_stocks(self):
        secs = ", ".join(self.sectors) if self.sectors else "(brak — zaznacz w kroku 2)"
        self._header("Które akcje kupić?", f"WSZYSTKIE spółki z sektorów: {secs} (prosto z Finviz, filtr sec_*), od najwyższego Mansfield RS względem ETF ich sektora "
                     "— najsilniejsze spółki w sektorze. Kliknięcie w pole ☐ przy tickerze zaznacza, ponowne odznacza (klik w resztę wiersza tylko pokazuje wykres); zaznaczone → watchlista z GLB i boxami.")
        bar = Flow(self.body)
        bar.pack(fill="x", padx=12)
        extra_var = tk.StringVar(value=self.app.session.get("krok", {}).get("extra", ""))
        bar.add(tk.Label(bar, text="Dodatkowe filtry Finviz (opcjonalnie, np. sh_avgvol_o300):", bg=PANEL))
        bar.add(tk.Entry(bar, textvariable=extra_var, width=28))
        bar.add(tk.Button(bar, text="⟳ Pobierz z Finviz", command=lambda: fetch(force=True)))
        count = tk.Label(bar, text="", bg=PANEL, fg="#8b95a3")
        frame = tk.Frame(self.body, bg=BG)
        frame.pack(fill="both", expand=True, padx=12, pady=(4, 0))
        cols = (("company", "Spółka", 230, "w"), ("sector", "Sektor", 140, "w"), ("industry", "Branża", 170, "w"), ("mrs", "Mansfield RS", 120, "e"),
                ("trend", "10:30", 110, "w"), ("q", "3 mies.", 80, "e"), ("darvas", "Darvas", 100, "w"))
        tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="tree headings", selectmode="none", height=12)
        tree.heading("#0", text="☑ Ticker")
        tree.column("#0", width=100)
        for key, text, w, anchor in cols:
            tree.heading(key, text=text)
            tree.column(key, width=w, anchor=anchor)
        for st, col in STATE_COLORS.items():
            tree.tag_configure(st, foreground=col)
        tree.tag_configure("checked", background="#1f3a5f")
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        holder = tk.Frame(self.body, bg=BG, height=250)
        holder.pack(fill="x")
        holder.pack_propagate(False)
        state = {"rows": [], "by": {}, "checked": set(), "u": None}
        self.rows = state
        btn = tk.Button(bar, text="📌 Utwórz watchlistę z zaznaczonych (0)", command=lambda: self.make_watchlist(
            [state["by"][t] for t in tree.get_children() if t in state["checked"]]))

        def label(t):
            return ("☑ " if t in state["checked"] else "☐ ") + t

        def refresh_btn():
            btn.config(text=f"📌 Utwórz watchlistę z zaznaczonych ({len(state['checked'])})")

        def fill(u):
            state["u"] = u
            state["rows"] = overview.universe_rows(u)
            state["by"] = {r["ticker"]: r for r in state["rows"]}
            state["checked"] &= set(state["by"])
            tree.delete(*tree.get_children())
            for r in state["rows"]:
                tree.insert("", "end", iid=r["ticker"], text=label(r["ticker"]),
                            values=((r.get("company") or "")[:36], r.get("sector") or "", (r.get("industry") or "")[:26], _f(r["mrs"]),
                                    overview.TREND_LABELS[r["trend"]], _f(r["q"]), store.STATE_LABELS.get(r["darvas"], "")),
                            tags=(r["darvas"],) + (("checked",) if r["ticker"] in state["checked"] else ()))
            count.config(text=f"{len(state['rows'])} spółek · dane z {u.get('fetched', '')[:16].replace('T', ' ')} UTC")
            refresh_btn()

        def show_chart(t):
            for w in holder.winfo_children():
                w.destroy()
            u, r = state["u"], state["by"].get(t)
            c = (u or {}).get("closes", {}).get(t)
            if c and r:
                bench = u["etf"].get(overview.SECTOR_ETF.get(r.get("sector")))
                st = self._stats(c)
                st.append((f"Mansfield RS (vs {overview.SECTOR_ETF.get(r.get('sector'), 'ETF')})", charts.pct_txt(overview.mansfield(c, bench)),
                           charts.pct_col(overview.mansfield(c, bench))))
                self._chart(holder, c, u["weeks"], f"{t} — {r.get('company') or ''}", st)

        def toggle(e):
            t = tree.identify_row(e.y)
            if not t:
                return
            on_box = getattr(e, "x", None) is None or tree.identify_column(e.x) == "#0"   # ☑ zmienia tylko kliknięcie w kolumnę z polem wyboru
            if on_box:
                state["checked"].symmetric_difference_update({t})
                tree.item(t, text=label(t), tags=(state["by"][t]["darvas"],) + (("checked",) if t in state["checked"] else ()))
            tree.focus(t)   # kliknięcie w resztę wiersza tylko pokazuje wykres spółki
            refresh_btn()
            show_chart(t)

        def top10():
            state["checked"] |= set(tree.get_children()[:10])
            fill(state["u"])

        def clear():
            state["checked"].clear()
            fill(state["u"])

        def fetch(force=False):
            sectors = list(self.sectors)
            extra = extra_var.get().strip()
            ses = self.app.session.setdefault("krok", {})
            ses["extra"] = extra
            self.app.save_session()
            if not sectors:
                count.config(text="Zaznacz sektory w kroku 2.")
                return
            u = overview.load_universe(self.app.data_root)
            if not force and u.get("key") == overview.universe_key(sectors, extra) and not overview.stale(u):
                fill(u)
                return
            count.config(text="⏳ pobieram spółki z Finviz i notowania z yfinance (duże sektory ~1 min)…")
            q = queue.Queue()

            def work():
                try:
                    q.put(("ok", overview.fetch_universe(self.app.data_root, sectors, extra, log=lambda m: q.put(("log", m)))))
                except Exception as e:   # noqa: BLE001 — blokada Finviz / brak sieci: komunikat zamiast zamknięcia okna
                    q.put(("err", str(e)))

            def poll():
                if not tree.winfo_exists():
                    return
                try:
                    while True:
                        kind, val = q.get_nowait()
                        if kind == "log":
                            count.config(text=f"⏳ {val}")
                        elif kind == "ok":
                            fill(val)
                            return
                        else:
                            count.config(text=f"⚠️ nie udało się pobrać: {val[:100]}")
                            return
                except queue.Empty:
                    self.after(300, poll)
            threading.Thread(target=work, daemon=True).start()
            self.after(300, poll)

        bar.add(tk.Button(bar, text="Zaznacz 10 najlepszych", command=top10))
        bar.add(tk.Button(bar, text="Odznacz wszystkie", command=clear))
        bar.add(btn)
        bar.add(count)
        tree.bind("<ButtonRelease-1>", toggle)
        self.tree = tree
        self.toggle = toggle
        fetch()

    def make_watchlist(self, rows, name=None):
        """Nowy skan z zaznaczonych spółek (stała lista tickerów, bez zapytań do Finviz): Sync pobiera ceny, boxy Darvasa i miesięczne
        zamknięcia z całej historii (GLB) — od razu po utworzeniu."""
        if not rows:
            messagebox.showinfo("Watchlista", "Zaznacz najpierw spółki kliknięciem (☑) albo „Zaznacz 10 najlepszych”.", parent=self)
            return None
        if name is None:
            secs = "+".join(self.sectors[:3]) if self.sectors else "wszystkie"
            name = simpledialog.askstring("Nowa watchlista", f"Nazwa watchlisty ({len(rows)} spółek):", initialvalue=f"Krok {date.today():%d.%m} — {secs}", parent=self)
            if not name:
                return None
        sc = {"name": name.strip() or "Krok po kroku", "kind": scanners.KIND_FINVIZ, "columns": None, "extra": [], "filter": "", "sources": []}
        saved = scanners.upsert(self.app.data_root, sc, "", max(len(rows), 1), None, glb.DEFAULTS)
        d = scanners.scanner_dir(self.app.data_root, saved["id"])
        cfg = store.read_json(d / "finviz_screen.json", {}) or {}
        cfg["tickers"] = [{k: r.get(k) for k in ("ticker", "company", "sector", "industry", "market_cap", "pe")} for r in rows]
        store.write_json(d / "finviz_screen.json", cfg)
        self.app.scanner_saved(saved, sync.PRICES)
        return saved

    # --- wymagane przez ChartHost (↑/↓ w oknie wykresu, odświeżenie po przypięciu)
    def step(self, delta):
        """↑/↓ z okna wykresu — w kroku 3 lista nie otwiera pełnego wykresu (spółki spoza skanów), więc nic nie robimy."""
        return

    def refresh(self, keep=False):
        pass
