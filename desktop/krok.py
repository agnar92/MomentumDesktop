"""🧭 Krok po kroku — jedna informacja na ekran (jak krok.html w Momentum):
1 · Rynek — S&P 500, Nasdaq 100 i Dow Jones na tygodniowych wykresach 10:30 (cena, SMA 10, SMA 30) + werdykt;
2 · Sektory — 11 ETF SPDR od najwyższego Mansfield RS względem S&P 500 (zaznacz sektory, z których szukasz akcji);
3 · Akcje — spółki z wybranego skanu / watchlisty z tych sektorów, od najwyższego Mansfield RS; zaznaczone → nowa watchlista."""
import queue
import threading
import tkinter as tk
from datetime import date
from tkinter import messagebox, simpledialog, ttk

from . import charts, overview, scanners, store, sync
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
        pick = [r["ticker"] for r in rows if r["sector"] in self.sectors] or [r["ticker"] for r in strong[:3]]
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
        secs = ", ".join(self.sectors) if self.sectors else "wszystkie"
        self._header("Które akcje kupić?", f"Spółki z wybranego skanu / watchlisty z sektorów: {secs} (zmień w kroku 2), od najwyższego Mansfield RS względem S&P 500. "
                     "Zaznacz spółki (Ctrl / Shift + klik) i utwórz z nich watchlistę. Dwuklik = pełny wykres.")
        bar = Flow(self.body)
        bar.pack(fill="x", padx=12)
        srcs = [s for s in scanners.load(self.app.data_root) if (scanners.scanner_dir(self.app.data_root, s["id"]) / "watchlist.json").exists()]
        names = {s["name"]: s["id"] for s in srcs}
        cur = next((s["name"] for s in srcs if s["id"] == self.source), srcs[0]["name"] if srcs else "")
        src_var, all_var = tk.StringVar(value=cur), tk.BooleanVar(value=not self.sectors)
        bar.add(tk.Label(bar, text="Skąd:", bg=PANEL))
        cb = ttk.Combobox(bar, textvariable=src_var, values=list(names), state="readonly", width=34)
        bar.add(cb)
        bar.add(tk.Checkbutton(bar, text="wszystkie sektory", variable=all_var, bg=PANEL))
        count = tk.Label(bar, text="", bg=PANEL, fg="#8b95a3")
        frame = tk.Frame(self.body, bg=BG)
        frame.pack(fill="both", expand=True, padx=12, pady=(4, 0))
        cols = (("company", "Spółka", 220, "w"), ("sector", "Sektor", 150, "w"), ("mrs", "Mansfield RS", 100, "e"), ("trend", "10:30", 110, "w"),
                ("q", "3 mies.", 80, "e"), ("darvas", "Darvas", 110, "w"), ("glb", "GLB", 80, "w"), ("rs", "RS", 50, "e"))
        tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="tree headings", selectmode="extended", height=12)
        tree.heading("#0", text="Ticker")
        tree.column("#0", width=80)
        for key, text, w, anchor in cols:
            tree.heading(key, text=text)
            tree.column(key, width=w, anchor=anchor)
        for st, col in STATE_COLORS.items():
            tree.tag_configure(st, foreground=col)
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        holder = tk.Frame(self.body, bg=BG, height=240)
        holder.pack(fill="x")
        holder.pack_propagate(False)
        state = {"rows": [], "dir": None}

        def load(_e=None):
            sid = names.get(src_var.get())
            if not sid:
                return
            self.source = sid
            self.save_state()
            d = scanners.scanner_dir(self.app.data_root, sid)
            state["rows"], state["dir"] = overview.stock_rows(d, None if all_var.get() else self.sectors), d
            tree.delete(*tree.get_children())
            for r in state["rows"]:
                tree.insert("", "end", iid=r["ticker"], text=r["ticker"],
                            values=(r["company"][:34], r["sector"], _f(r["mrs"]), overview.TREND_LABELS[r["trend"]], _f(r["q"]),
                                    store.STATE_LABELS.get(r["darvas"], ""), r["glb"], r["rs"] if r["rs"] is not None else ""), tags=(r["darvas"],))
            count.config(text=f"{len(state['rows'])} spółek")
        self.rows = state

        def on_sel(_e=None):
            sel = tree.selection()
            btn.config(text=f"📌 Utwórz watchlistę z zaznaczonych ({len(sel)})")
            focus = tree.focus() or (sel[0] if sel else None)
            for w in holder.winfo_children():
                w.destroy()
            if not focus or not state["dir"]:
                return
            ch = store.read_json(state["dir"] / "charts.json", {}) or {}
            d = (ch.get("stocks") or {}).get(focus) or {}
            if d.get("c"):
                self._chart(holder, d["c"], ch.get("weeks") or [], focus, self._stats(d["c"], ch.get("spx") or []))

        def top10():
            ids = tree.get_children()[:10]
            tree.selection_set(ids)

        def open_chart(_e=None):
            t = tree.focus()
            if t:
                self.host.use(scanners.get(self.app.data_root, self.source))
                self.host.open_chart(t)
        btn = tk.Button(bar, text="📌 Utwórz watchlistę z zaznaczonych (0)", command=lambda: self.make_watchlist(list(tree.selection())))
        bar.add(tk.Button(bar, text="Zaznacz 10 najlepszych", command=top10))
        bar.add(btn)
        bar.add(count)
        cb.bind("<<ComboboxSelected>>", load)
        all_var.trace_add("write", lambda *_: load())
        tree.bind("<<TreeviewSelect>>", on_sel)
        tree.bind("<Double-1>", open_chart)
        tree.bind("<Return>", open_chart)
        self.tree = tree
        load()

    def make_watchlist(self, tickers, name=None):
        """Nowa watchlista z zaznaczonych spółek (reguła „wybrane tickery” na skanie źródłowym) — od razu złożona i otwarta."""
        if not tickers:
            messagebox.showinfo("Watchlista", "Zaznacz najpierw spółki na liście (Ctrl / Shift + klik albo „Zaznacz 10 najlepszych”).", parent=self)
            return None
        if name is None:
            secs = "+".join(self.sectors[:3]) if self.sectors else "wszystkie"
            name = simpledialog.askstring("Nowa watchlista", f"Nazwa watchlisty ({len(tickers)} spółek):", initialvalue=f"Krok {date.today():%d.%m} — {secs}", parent=self)
            if not name:
                return None
        sc = {"name": name.strip() or "Krok po kroku", "kind": scanners.KIND_WATCHLIST, "columns": None, "extra": [], "filter": "",
              "sources": [{"id": self.source, "rule": {"type": scanners.RULE_TICKERS, "tickers": list(tickers)}}]}
        saved = scanners.upsert(self.app.data_root, sc)
        self.app.scanner_saved(saved, sync.PRICES)
        return saved

    # --- wymagane przez ChartHost (↑/↓ w oknie wykresu, odświeżenie po przypięciu)
    def step(self, delta):
        tree = getattr(self, "tree", None)
        if tree is None or not tree.winfo_exists():
            return
        ids = list(tree.get_children())
        if not ids:
            return
        cur = tree.focus()
        i = max(0, min(len(ids) - 1, (ids.index(cur) + delta) if cur in ids else 0))
        tree.focus(ids[i])
        tree.see(ids[i])
        self.host.open_chart(ids[i])

    def refresh(self, keep=False):
        pass
