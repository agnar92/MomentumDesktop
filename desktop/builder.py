"""Kreator własnych skanerów Finviz (filtry z listy wyboru albo wklejone z adresu Finviz, dodatkowe kolumny) i menedżer skanerów."""
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import finviz_catalog as fc
from . import finviz_codes, scanners, sync
from .theme import BG, FG, PANEL, apply_dark

NONE = "—"


class ScannerEditor(tk.Toplevel):
    """Edytor skanera: nazwa, filtry Finviz (zakładki Opisowe / Fundamentalne / Techniczne), kody ręcznie, kolumny z Finviz, test liczby wyników."""

    def __init__(self, app, scanner=None):
        super().__init__(app.root)
        self.app = app
        self.scanner = dict(scanner) if scanner else None   # None = nowy
        cfg = scanners.load_config(scanners.scanner_dir(app.data_root, scanner["id"])) if scanner else {"filters": "", "max_tickers": 300}
        self.title("Edytor skanera Finviz" if scanner else "Nowy skaner Finviz")
        self.geometry("1040x740")
        self.configure(bg=BG)
        apply_dark(self)
        self.q = queue.Queue()
        self.rest, self.lock = [], False
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="x")
        self.name = tk.StringVar(value=scanner["name"] if scanner else "Nowy skaner")
        self.max_t = tk.StringVar(value=str(cfg["max_tickers"]))
        tk.Label(top, text="Nazwa:", bg=PANEL).pack(side="left", padx=(8, 2), pady=6)
        tk.Entry(top, textvariable=self.name, width=34).pack(side="left")
        tk.Label(top, text="max spółek:", bg=PANEL).pack(side="left", padx=(14, 2))
        tk.Entry(top, textvariable=self.max_t, width=6).pack(side="left")
        imp = tk.Frame(self, bg=PANEL)
        imp.pack(fill="x")
        tk.Label(imp, text="Wklej adres skanera z finviz.com (lub same kody):", bg=PANEL).pack(side="left", padx=8, pady=4)
        self.url = tk.StringVar()
        tk.Entry(imp, textvariable=self.url).pack(side="left", fill="x", expand=True)
        tk.Button(imp, text="Importuj", command=self.import_url).pack(side="left", padx=6)
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
        raw = tk.Frame(self, bg=PANEL)
        raw.pack(fill="x")
        tk.Label(raw, text="Kody filtrów (f=):", bg=PANEL).pack(side="left", padx=8, pady=4)
        self.raw = tk.StringVar(value=cfg["filters"])
        tk.Entry(raw, textvariable=self.raw).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.preview = tk.Label(self, text="", bg=PANEL, fg="#8b95a3", justify="left", anchor="w", wraplength=1000)
        self.preview.pack(fill="x", padx=8, pady=(0, 4))
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x")
        tk.Button(bar, text="Sprawdź liczbę wyników (Finviz)", command=self.check_count).pack(side="left", padx=8, pady=6)
        self.count_lbl = tk.Label(bar, text="", bg=PANEL)
        self.count_lbl.pack(side="left")
        tk.Button(bar, text="Anuluj", command=self.destroy).pack(side="right", padx=6)
        tk.Button(bar, text="⟳ Zapisz i pobierz fundamenty", command=lambda: self.save(sync.FUNDAMENTALS)).pack(side="right", padx=2)
        tk.Button(bar, text="⟳ Zapisz i pobierz ceny", command=lambda: self.save(sync.PRICES)).pack(side="right", padx=2)
        tk.Button(bar, text="Zapisz", command=lambda: self.save(None)).pack(side="right", padx=2)
        self.raw.trace_add("write", lambda *_: self.from_raw())
        self.from_raw()
        self.after(150, self.poll)

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
        sc = {**(self.scanner or {}), "name": name, "extra": extra}
        saved = scanners.upsert(self.app.data_root, sc, self.raw.get(), max_t)
        self.app.scanner_saved(saved, then_sync)
        self.destroy()


class ScannerManager(tk.Toplevel):
    """Lista własnych skanerów: otwórz w osobnym oknie, utwórz, edytuj, zduplikuj, usuń, synchronizuj."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Moje skanery")
        self.geometry("900x440")
        self.configure(bg=BG)
        apply_dark(self)
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
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x")
        for text, cmd in (("Otwórz w oknie", self.open), ("Nowy…", self.new), ("Edytuj…", self.edit), ("Duplikuj", self.duplicate), ("Usuń", self.delete),
                          ("⟳ Ceny", lambda: self.sync(sync.PRICES)), ("⟳ Fundamenty", lambda: self.sync(sync.FUNDAMENTALS))):
            tk.Button(bar, text=text, command=cmd).pack(side="left", padx=4, pady=6)
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for sc in scanners.load(self.app.data_root):
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

            self.tree.insert("", "end", iid=sc["id"], text=sc["name"], values=(n if n is not None else "—", f"{len(finviz_codes.describe(cfg['filters']))} filtrów: " + cfg["filters"][:70],
                                                                          ago(st.get("prices")), ago(st.get("fundamentals"))))

    def current(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

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
