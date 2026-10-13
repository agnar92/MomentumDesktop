"""Kreator własnych skanerów Finviz (filtry z listy wyboru albo wklejone z adresu Finviz, dodatkowe kolumny) i menedżer skanerów."""
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import finviz_catalog as fc
from . import finviz_codes, qm, scanners, sync
from .theme import BG, FG, PANEL, Flow, apply_dark, autowrap, fit_window

NONE = "—"


class ScannerEditor(tk.Toplevel):
    """Edytor skanera: nazwa, filtry Finviz (zakładki Opisowe / Fundamentalne / Techniczne), kody ręcznie, kolumny z Finviz, test liczby wyników."""

    def __init__(self, app, scanner=None, kind=None):
        super().__init__(app.root)
        self.app = app
        self.scanner = dict(scanner) if scanner else None   # None = nowy
        self.kind = (scanner or {}).get("kind") or kind or scanners.KIND_FINVIZ
        self.is_qm = self.kind == scanners.KIND_QM
        if scanner:
            cfg = scanners.load_config(scanners.scanner_dir(app.data_root, scanner["id"]))
        elif self.is_qm:
            cfg = {"filters": qm.suggest_filters(qm.DEFAULTS), "max_tickers": 3000, "qm": qm.normalize(None)}
        else:
            cfg = {"filters": "", "max_tickers": 300}
        self.title(("Edytor skanera" if scanner else "Nowy skaner") + (" skan Qullamaggie" if self.is_qm else " Finviz"))
        self.configure(bg=BG)
        apply_dark(self)
        self.q = queue.Queue()
        self.rest, self.lock = [], False
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="x")
        self.name = tk.StringVar(value=scanner["name"] if scanner else "Qullamaggie" if self.is_qm else "Nowy skaner")
        self.max_t = tk.StringVar(value=str(cfg["max_tickers"]))
        tk.Label(top, text="Nazwa:", bg=PANEL).pack(side="left", padx=(8, 2), pady=6)
        tk.Entry(top, textvariable=self.name, width=34).pack(side="left")
        tk.Label(top, text="max spółek:", bg=PANEL).pack(side="left", padx=(14, 2))
        tk.Entry(top, textvariable=self.max_t, width=6).pack(side="left")
        if self.is_qm:
            self.build_qm_frame(cfg.get("qm") or qm.normalize(None))
        imp = tk.Frame(self, bg=PANEL)
        imp.pack(fill="x")
        tk.Label(imp, text="Wklej adres skanera z finviz.com (lub same kody):", bg=PANEL).pack(side="left", padx=8, pady=4)
        self.url = tk.StringVar()
        tk.Entry(imp, textvariable=self.url).pack(side="left", fill="x", expand=True)
        tk.Button(imp, text="Importuj", command=self.import_url).pack(side="left", padx=6)
        # dolne paski pakujemy PRZED notatnikiem (side=bottom), żeby przy małym oknie to zakładki się kurczyły, a nie przyciski
        bar = Flow(self)
        bar.pack(fill="x", side="bottom")
        self.preview = autowrap(tk.Label(self, text="", bg=PANEL, fg="#8b95a3"))
        self.preview.pack(fill="x", padx=8, pady=(0, 4), side="bottom")
        raw = tk.Frame(self, bg=PANEL)
        raw.pack(fill="x", side="bottom")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=4, pady=4)
        self.combos, self.opts = {}, {}
        for tab, groups in fc.groups():
            frame = tk.Frame(nb, bg=PANEL)
            nb.add(frame, text=f"  {tab}  ")
            for n, (label, options) in enumerate(groups):
                r, c = n // 2, (n % 2) * 2
                tk.Label(frame, text=label, bg=PANEL, anchor="e").grid(row=r, column=c, sticky="e", padx=(10, 4), pady=3)
                cb = ttk.Combobox(frame, values=[NONE] + [t for t, _ in options], state="readonly", width=30)
                cb.set(NONE)
                cb.grid(row=r, column=c + 1, sticky="w", pady=3)
                cb.bind("<<ComboboxSelected>>", lambda e: self.from_combos())
                self.combos[label] = cb
                self.opts[label] = {t: code for t, code in options}
        ex = tk.Frame(nb, bg=PANEL)
        nb.add(ex, text="  Kolumny z Finviz  ")
        tk.Label(ex, text="Dodatkowe pola pobierane z Finviz przy Sync (poza tym, co liczy silnik). Pojawią się jako kolumny do wyboru w „Kolumny…”.",
                 bg=PANEL, fg="#8b95a3").grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=6)
        self.extra_vars = {}
        have = set((scanner or {}).get("extra") or [])
        for n, (key, spec) in enumerate(fc.EXTRA_COLUMNS.items()):
            v = tk.BooleanVar(value=key in have)
            self.extra_vars[key] = v
            tk.Checkbutton(ex, text=spec[1], variable=v, bg=PANEL, anchor="w").grid(row=1 + n // 3, column=n % 3, sticky="w", padx=10)
        tk.Label(raw, text="Kody filtrów (f=):", bg=PANEL).pack(side="left", padx=8, pady=4)
        self.raw = tk.StringVar(value=cfg["filters"])
        tk.Entry(raw, textvariable=self.raw).pack(side="left", fill="x", expand=True, padx=(0, 8))
        bar.add(tk.Button(bar, text="Zapisz", command=lambda: self.save(None)))
        bar.add(tk.Button(bar, text="⟳ Zapisz i pobierz ceny", command=lambda: self.save(sync.PRICES)))
        if not self.is_qm:
            bar.add(tk.Button(bar, text="⟳ Zapisz i pobierz fundamenty", command=lambda: self.save(sync.FUNDAMENTALS)))
        bar.add(tk.Button(bar, text="Anuluj", command=self.destroy))
        bar.add(tk.Button(bar, text="Sprawdź liczbę wyników (Finviz)", command=self.check_count))
        self.count_lbl = tk.Label(bar, text="", bg=PANEL)
        bar.add(self.count_lbl)
        self.raw.trace_add("write", lambda *_: self.from_raw())
        self.from_raw()
        self.after(150, self.poll)
        fit_window(self, 1040, 740)

    # --- Qullamaggie: progi listy (zmieniane na bieżąco) i progi pobierania (co zostaje na dysku)
    def build_qm_frame(self, q):
        outer = tk.Frame(self, bg=PANEL)
        outer.pack(fill="x", padx=6, pady=(4, 0))
        title = "Skan Qullamaggie: pobieranie danych (obrót = cena × wolumen, ADR, cena / min Low)"
        box = tk.Frame(outer, bg=PANEL, highlightthickness=1, highlightbackground="#27303a")
        shown = tk.BooleanVar(value=self.winfo_screenheight() >= 900)   # na małym ekranie sekcja startuje zwinięta, żeby zostało miejsce na filtry

        def toggle():
            if shown.get():
                box.pack_forget()
            else:
                box.pack(fill="x")
            shown.set(not shown.get())
            head.config(text=("▾ " if shown.get() else "▸ ") + title)
        head = tk.Button(outer, text=("▾ " if shown.get() else "▸ ") + title, command=toggle, relief="flat", anchor="w")
        head.pack(fill="x")
        if shown.get():
            box.pack(fill="x")
        self.qv = {k: tk.StringVar(value=f"{q[k]:g}") for k in ("top_pct", "keep_dollar_mln", "keep_adr")}
        rows = (("Pobieraj spółki z obrotem ≥ (mln $):", "keep_dollar_mln"), ("ADR ≥ (%):", "keep_adr"), ("Największe „górne %” w watchlistach:", "top_pct"))
        for n, (label, key) in enumerate(rows):
            tk.Label(box, text=label, bg=PANEL, anchor="e").grid(row=0, column=n * 2, sticky="e", padx=(10, 3), pady=3)
            tk.Entry(box, textvariable=self.qv[key], width=7).grid(row=0, column=n * 2 + 1, sticky="w")
        wf = tk.Frame(box, bg=PANEL)
        wf.grid(row=1, column=0, columnspan=6, sticky="w", padx=10, pady=3)
        tk.Button(wf, text="Dobierz filtry Finviz do tych progów", command=self.suggest_filters).pack(side="left")
        self.two_stage = tk.BooleanVar(value=q.get("two_stage", True))
        tk.Checkbutton(box, text="Szybki Sync (dwa etapy): najpierw tylko Finviz, ceny z yfinance tylko dla kandydatów z czołówki zwrotów 1M / 3M / 6M "
                                 "(ranking przybliżony; wyłącz, by pobrać ceny wszystkich spółek)", variable=self.two_stage, bg=PANEL, anchor="w",
                       justify="left", wraplength=860).grid(row=2, column=0, columnspan=6, sticky="w", padx=10)
        tk.Label(box, text="To jest skan: pobiera i zapisuje dane (okno z filtrami jak każdy skan). Krótką listę tickerów — górne X % w oknach 1M, 3M i 6M, "
                           "obrót, ADR — ustawiasz w WATCHLIŚCIE (Skanery → Nowa watchlista) i wskazujesz ten skan jako źródło.",
                 bg=PANEL, fg="#8b95a3", wraplength=860, justify="left").grid(row=3, column=0, columnspan=6, sticky="w", padx=10, pady=(2, 4))

    def qm_values(self):
        cfg = {k: v.get() for k, v in self.qv.items()}
        cfg["two_stage"] = self.two_stage.get()
        return qm.normalize(cfg)

    def suggest_filters(self):
        self.raw.set(qm.suggest_filters(self.qm_values()))   # tylko na jawne kliknięcie — nie nadpisujemy filtrów zmienionych ręcznie

    # --- synchronizacja pól: listy wyboru <-> ciąg kodów
    def from_combos(self):
        sel = {label: self.opts[label].get(cb.get()) for label, cb in self.combos.items() if cb.get() != NONE}
        self.lock = True
        self.raw.set(fc.filters_from_selection(sel, self.rest))
        self.lock = False
        self.show_preview()

    def from_raw(self):
        if self.lock:
            return
        sel, self.rest = fc.selection_from_filters(self.raw.get())
        by_code = {label: {code: t for t, code in opts.items()} for label, opts in self.opts.items()}
        for label, cb in self.combos.items():
            code = sel.get(label)
            cb.set(by_code[label].get(code, NONE) if code else NONE)
        self.show_preview()

    def show_preview(self):
        items = finviz_codes.describe(self.raw.get())
        self.preview.config(text=("Kryteria: " + "  •  ".join(t if k else f"⚠ {c}" for c, t, k in items)) if items else "Brak filtrów — Finviz zwróciłby wszystkie spółki (do limitu).")

    def import_url(self):
        codes = fc.parse_finviz_input(self.url.get())
        if not codes:
            messagebox.showinfo("Import", "Nie znalazłem kodów filtrów (parametr f= w adresie).", parent=self)
            return
        self.raw.set(codes)

    # --- test liczby wyników
    def check_count(self):
        filters = self.raw.get()
        self.count_lbl.config(text="Sprawdzam…", fg=FG)

        def work():
            try:
                sync._engine_path()
                import finviz
                import requests
                r = requests.get(finviz.BASE_URL, params={"v": "111", "f": filters}, headers=finviz.HEADERS, timeout=30)
                r.raise_for_status()
                _, total = finviz.parse_screener_page(r.text, "111")
                self.q.put(("ok", total))
            except Exception as e:
                self.q.put(("err", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "ok":
                    unknown = [c for c, _, k in finviz_codes.describe(self.raw.get()) if not k]
                    txt = f"Finviz: {val} spółek" if val is not None else "Finviz: brak wyników / zmieniony układ strony"
                    self.count_lbl.config(text=txt + (f"   ⚠ nieznane kody: {', '.join(unknown)}" if unknown else ""), fg="#ff9f43" if unknown or not val else "#3ddc84")
                else:
                    self.count_lbl.config(text=f"Błąd: {val}", fg="#ff5c5c")
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(150, self.poll)

    # --- zapis
    def save(self, then_sync):
        try:
            max_t = int(self.max_t.get() or 300)
        except ValueError:
            messagebox.showerror("Skaner", "Maksymalna liczba spółek musi być liczbą.", parent=self)
            return
        name = self.name.get().strip() or "Skaner"
        extra = [k for k, v in self.extra_vars.items() if v.get()]
        sc = {**(self.scanner or {}), "name": name, "extra": extra, "kind": self.kind}
        if self.is_qm and not sc.get("columns"):
            sc["columns"] = list(qm.DEFAULT_COLUMNS)
        saved = scanners.upsert(self.app.data_root, sc, self.raw.get(), max_t, self.qm_values() if self.is_qm else None)
        self.app.scanner_saved(saved, then_sync)
        self.destroy()


class ScannerManager(tk.Toplevel):
    """Lista własnych skanerów: otwórz w osobnym oknie, utwórz, edytuj, zduplikuj, usuń, synchronizuj."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Moje skanery")
        self.configure(bg=BG)
        apply_dark(self)
        bar = Flow(self)   # przyciski najpierw (na dole) i zawijane — nie giną w wąskim oknie
        bar.pack(fill="x", side="bottom")
        self.tree = ttk.Treeview(self, columns=("n", "filters", "prices", "fund"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Skaner")
        self.tree.heading("n", text="Spółek")
        self.tree.heading("filters", text="Filtry Finviz")
        self.tree.heading("prices", text="Ceny")
        self.tree.heading("fund", text="Fundamenty")
        self.tree.column("#0", width=230)
        self.tree.column("n", width=70, anchor="e")
        self.tree.column("filters", width=330)
        self.tree.column("prices", width=100)
        self.tree.column("fund", width=100)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.open())
        for text, cmd in (("Otwórz w oknie", self.open), ("Nowy skan Finviz…", self.new), ("Nowy skan Qullamaggie…", lambda: self.app.new_scanner(scanners.KIND_QM)),
                          ("Nowa watchlista…", lambda: self.app.new_scanner(scanners.KIND_WATCHLIST)), ("Edytuj…", self.edit), ("Duplikuj", self.duplicate), ("Usuń", self.delete),
                          ("⟳ Ceny", lambda: self.sync(sync.PRICES)), ("⟳ Fundamenty", lambda: self.sync(sync.FUNDAMENTALS))):
            bar.add(tk.Button(bar, text=text, command=cmd))
        self.refresh()
        fit_window(self, 900, 440)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        all_sc = scanners.load(self.app.data_root)
        for gid, title, kinds in (("grp:scans", "Skany (pobierają dane)", False), ("grp:wl", "Watchlisty (listy tickerów)", True)):
            members = [x for x in all_sc if (x.get("kind") == scanners.KIND_WATCHLIST) == kinds]
            if members:
                self.tree.insert("", "end", iid=gid, text=f"{title} — {len(members)}", open=True)
        for sc in all_sc:
            parent = "grp:wl" if sc.get("kind") == scanners.KIND_WATCHLIST else "grp:scans"
            d = scanners.scanner_dir(self.app.data_root, sc["id"])
            cfg = scanners.load_config(d)
            st = sync.read_state(d)
            n = (self.app.view_for(sc["id"]).store.watchlist.get("n_stocks") if self.app.view_for(sc["id"]) else None)
            if n is None:
                from . import store
                n = (store.read_json(d / "watchlist.json", {}) or {}).get("n_stocks")

            def ago(iso):
                a = sync.age_days(iso)
                return "—" if a is None else "dziś" if a < 1 else f"{int(a)} d temu"

            if sc.get("kind") == scanners.KIND_WATCHLIST:
                names = [x["name"] for x in (scanners.get(self.app.data_root, i["id"]) for i in sc.get("sources", [])) if x]
                desc = "watchlista ze skanów: " + ", ".join(names)
            else:
                desc = ("Qullamaggie · " if sc.get("kind") == scanners.KIND_QM else "") + f"{len(finviz_codes.describe(cfg['filters']))} filtrów: " + cfg["filters"][:70]
            self.tree.insert(parent, "end", iid=sc["id"], text=sc["name"], values=(n if n is not None else "—", desc,
                                                                          ago(st.get("prices")), ago(st.get("fundamentals"))))

    def current(self):
        sel = self.tree.selection()
        return sel[0] if sel and not sel[0].startswith("grp:") else None

    def open(self):
        if self.current():
            self.app.open_scanner_window(self.current())

    def new(self):
        ScannerEditor(self.app)

    def edit(self):
        if self.current():
            self.app.edit_scanner(self.current())

    def duplicate(self):
        sid = self.current()
        if sid:
            src = scanners.get(self.app.data_root, sid)
            scanners.duplicate(self.app.data_root, sid, f"{src['name']} (kopia)")
            self.refresh()

    def delete(self):
        sid = self.current()
        if not sid or sid == scanners.DEFAULT_ID:
            messagebox.showinfo("Skanery", "Skanera domyślnego nie można usunąć.", parent=self)
            return
        sc = scanners.get(self.app.data_root, sid)
        if messagebox.askyesno("Usuń skaner", f"Usunąć skaner „{sc['name']}” razem z jego pobranymi danymi?", parent=self):
            self.app.delete_scanner(sid)
            self.refresh()

    def sync(self, mode):
        sid = self.current()
        if sid:
            self.app.open_scanner_window(sid)
            view = self.app.view_for(sid)
            if view:
                self.app.start_sync(view, mode)


class WatchlistEditor(tk.Toplevel):
    """Watchlista = mała lista tickerów z kilku skanów wg kryteriów. Dla każdego skanu: pomijaj / wszystkie spółki / Qullamaggie (górne X % w oknach
    1M, 3M, 6M wśród płynnych) / CANSLIM ≥ n/7. Nic nie jest pobierane — watchlista składa się z już pobranych skanów."""

    RULES = {"pomiń": None, "wszystkie spółki skanu": scanners.RULE_ALL, "Qullamaggie: górne X % w oknach": scanners.RULE_QM, "CANSLIM ≥ n/7": scanners.RULE_CANSLIM}

    def __init__(self, app, scanner=None):
        super().__init__(app.root)
        self.app, self.scanner = app, dict(scanner) if scanner else None
        self.title("Watchlista" if scanner else "Nowa watchlista")
        self.configure(bg=BG)
        apply_dark(self)
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="x")
        tk.Label(top, text="Nazwa:", bg=PANEL).pack(side="left", padx=(8, 2), pady=6)
        self.name = tk.StringVar(value=scanner["name"] if scanner else "Watchlista")
        tk.Entry(top, textvariable=self.name, width=36).pack(side="left")
        bar = Flow(self)   # dolne paski pakujemy przed listą skanów, żeby przyciski były zawsze widoczne
        bar.pack(fill="x", side="bottom")
        self.count = autowrap(tk.Label(self, text="", bg=BG, fg="#8b95a3"))
        self.count.pack(fill="x", padx=10, side="bottom")
        autowrap(tk.Label(self, text="Z których skanów i po jakich kryteriach złożyć listę (zrób najpierw Sync tych skanów):", bg=BG)).pack(fill="x", padx=8, pady=(8, 2))
        body = tk.Frame(self, bg=PANEL)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        have = {x["id"]: x["rule"] for x in (scanner or {}).get("sources") or []}
        self.rows = {}
        for n, sc in enumerate(x for x in scanners.load(app.data_root) if x["kind"] != scanners.KIND_WATCHLIST):
            rule = have.get(sc["id"])
            default = scanners.RULE_QM if sc["kind"] == scanners.KIND_QM else scanners.RULE_ALL
            box = tk.LabelFrame(body, text=f" {sc['name']}{'  (Qullamaggie)' if sc['kind'] == scanners.KIND_QM else ''} ", bg=PANEL, fg=FG)
            box.grid(row=n, column=0, sticky="we", padx=4, pady=3)
            body.columnconfigure(0, weight=1)
            t = (rule or {}).get("type") or None
            kind = tk.StringVar(value=next((k for k, v in self.RULES.items() if v == t), "pomiń"))
            cb = ttk.Combobox(box, textvariable=kind, values=list(self.RULES), state="readonly", width=30)
            cb.grid(row=0, column=0, padx=6, pady=4, sticky="w")
            q = qm.normalize(rule if t == scanners.RULE_QM else None)
            vars_ = {"min_dollar_mln": tk.StringVar(value=f"{q['min_dollar_mln']:g}"), "min_adr": tk.StringVar(value=f"{q['min_adr']:g}"),
                     "top_pct": tk.StringVar(value=f"{q['top_pct']:g}"), "cs_min": tk.StringVar(value=str((rule or {}).get("cs_min") or 5))}
            wv = {w: tk.BooleanVar(value=w in q["windows"]) for w in qm.WINDOWS}
            core = tk.BooleanVar(value=bool((rule or {}).get("cs_core", True)))
            qf, cf = tk.Frame(box, bg=PANEL), tk.Frame(box, bg=PANEL)
            col = 0
            for label, key in (("obrót ≥ mln $", "min_dollar_mln"), ("ADR ≥ %", "min_adr"), ("górne % w oknie", "top_pct")):
                tk.Label(qf, text=label, bg=PANEL).grid(row=0, column=col, padx=(10, 2))
                tk.Entry(qf, textvariable=vars_[key], width=6).grid(row=0, column=col + 1)
                col += 2
            tk.Label(qf, text="okna:", bg=PANEL).grid(row=0, column=col, padx=(12, 2))
            wf = tk.Frame(qf, bg=PANEL)
            wf.grid(row=0, column=col + 1)
            for w, text in (("1m", "1M"), ("3m", "3M"), ("6m", "6M")):
                tk.Checkbutton(wf, text=text, variable=wv[w], bg=PANEL).pack(side="left")
            tk.Label(cf, text="CANSLIM ≥ n/7:", bg=PANEL).pack(side="left", padx=(10, 2))
            tk.Entry(cf, textvariable=vars_["cs_min"], width=4).pack(side="left")
            tk.Checkbutton(cf, text="C i A obowiązkowe", variable=core, bg=PANEL).pack(side="left", padx=6)
            self.rows[sc["id"]] = {"sc": sc, "kind": kind, "vars": vars_, "wv": wv, "core": core, "default": default, "qf": qf, "cf": cf}
            if t is None and not self.scanner and sc["kind"] == scanners.KIND_QM:
                kind.set("Qullamaggie: górne X % w oknach")
            cb.bind("<<ComboboxSelected>>", lambda e, sid=sc["id"]: self.show_params(sid))
            self.show_params(sc["id"])
        bar.add(tk.Button(bar, text="Zapisz i złóż listę", command=self.save))
        bar.add(tk.Button(bar, text="Anuluj", command=self.destroy))
        bar.add(tk.Button(bar, text="Podgląd liczby tickerów", command=self.preview))
        fit_window(self, 900, 520)

    def show_params(self, sid):
        """Pokazuje tylko pola kryterium wybranego dla skanu (Qullamaggie albo CANSLIM)."""
        r = self.rows[sid]
        t = self.RULES.get(r["kind"].get())
        for key, frame in (("qf", r["qf"]), ("cf", r["cf"])):
            frame.grid_forget()
        if t == scanners.RULE_QM:
            r["qf"].grid(row=1, column=0, sticky="w", pady=(0, 4))
        elif t == scanners.RULE_CANSLIM:
            r["cf"].grid(row=1, column=0, sticky="w", pady=(0, 4))

    def sources(self):
        out = []
        for sid, r in self.rows.items():
            t = self.RULES.get(r["kind"].get())
            if t is None:
                continue
            rule = {"type": t}
            if t == scanners.RULE_QM:
                rule.update({k: r["vars"][k].get() for k in ("min_dollar_mln", "min_adr", "top_pct")})
                rule["windows"] = [w for w, v in r["wv"].items() if v.get()]
                rule = {"type": t, **{k: v for k, v in qm.normalize(rule).items() if k in ("min_dollar_mln", "min_adr", "top_pct", "windows")}}
            elif t == scanners.RULE_CANSLIM:
                try:
                    rule["cs_min"] = int(r["vars"]["cs_min"].get())
                except ValueError:
                    rule["cs_min"] = 5
                rule["cs_core"] = r["core"].get()
            out.append({"id": sid, "rule": rule})
        return out

    def preview(self):
        from . import merge
        parts, seen = [], set()
        for src in self.sources():
            items = merge.select_source(self.app.data_root, self.rows[src["id"]]["sc"], src["rule"])[0]
            parts.append(f"{self.rows[src['id']]['sc']['name']}: {len(items)}")
            seen.update(s["ticker"] for s, _ in items)
        self.count.config(text=("Z kryteriów wychodzi: " + "  ·  ".join(parts) + f"   →   razem {len(seen)} tickerów (bez duplikatów)") if parts else "Wybierz co najmniej jeden skan.")

    def save(self):
        src = self.sources()
        if not src:
            messagebox.showinfo("Watchlista", "Wybierz co najmniej jeden skan (kryterium inne niż „pomiń”).", parent=self)
            return
        sc = {**(self.scanner or {}), "name": self.name.get().strip() or "Watchlista", "kind": scanners.KIND_WATCHLIST, "sources": src}
        saved = scanners.upsert(self.app.data_root, sc)
        self.app.scanner_saved(saved, sync.PRICES)
        self.destroy()
