"""Okna pomocnicze widoku skanera: filtr lokalny, boxy Darvasa, kryteria Finviz, CANSLIM, wybór kolumn."""
import tkinter as tk
from tkinter import ttk

from . import canslim, changes, finviz_codes, store
from . import columns as columns_mod
from .theme import BG, FG, MONO, PANEL, SEL, apply_dark
from .widgets import STATE_COLORS, StockTable

SECTIONS = [("pinned", "📌 Monitorowane (przypięte)"), ("fresh", "🆕 Nowe boxy"), ("buy", "🟢 KUP — wybicie na wolumenie"),
            ("check", "🟡 Do sprawdzenia (bez wolumenu / za późno)"), ("hold", "Trzymaj"), ("sell", "🔴 Sprzedaj / poza"), ("wait", "Czekaj na wybicie")]


class FilterWindow(tk.Toplevel):
    """Filtr lokalny listy: RS, EPS Rating, CANSLIM, odległość do pivotu, stan Darvasa… po już pobranych danych (bez sieci)."""

    FIELDS = [("rs_min", "RS ≥"), ("eps_min", "EPS Rating ≥"), ("comp_min", "Composite ≥"), ("max_to_pivot", "Do pivotu ≤ %"),
              ("max_from_high", "Pod szczytem 52t ≤ %"), ("min_adr", "ADR ≥ %"), ("cs_min", "CANSLIM ≥ (n/7)")]

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title(f"Filtr listy — {app.scanner['name']}")
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
        tk.Button(row4, text="Zastosuj na liście", command=lambda: app.apply_main_filter(self.collect())).pack(side="left", padx=8)
        tk.Button(row4, text="✎ Edytuj skaner Finviz…", command=app.edit_scanner).pack(side="left", padx=4)
        self.count = tk.Label(row4, text="", bg=PANEL)
        self.count.pack(side="right")
        self.table = StockTable(self, app.open_chart, app.open_chart_new, app.open_canslim, columns=app.columns())
        self.table.pack(fill="both", expand=True)
        self.table.set_tf_label(app.store.tf)
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

class ColumnsWindow(tk.Toplevel):
    """Wybór kolumn listy z dostępnych danych (lewa lista = co mamy, prawa = co pokazujemy, ▲▼ zmienia kolejność)."""

    def __init__(self, view):
        super().__init__(view.root)
        self.view = view
        self.title(f"Kolumny — {view.scanner['name']}")
        self.geometry("720x520")
        self.configure(bg=BG)
        apply_dark(self)
        self.avail = columns_mod.available(view.store.rows, view.scanner.get("extra") or [])
        tk.Label(self, text="Dostępne dane (dwuklik = dodaj)                        Widoczne kolumny", bg=PANEL, anchor="w").pack(fill="x")
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        self.left = tk.Listbox(body, selectmode="browse", bg="#0f1318", fg=FG, selectbackground=SEL, exportselection=False, activestyle="none")
        self.right = tk.Listbox(body, selectmode="browse", bg="#0f1318", fg=FG, selectbackground=SEL, exportselection=False, activestyle="none")
        mid = tk.Frame(body, bg=PANEL)
        self.left.pack(side="left", fill="both", expand=True)
        mid.pack(side="left", fill="y")
        self.right.pack(side="left", fill="both", expand=True)
        for text, cmd in (("→ dodaj", self.add), ("← usuń", self.remove), ("▲ wyżej", lambda: self.move(-1)), ("▼ niżej", lambda: self.move(1)),
                          ("Domyślne", self.defaults)):
            tk.Button(mid, text=text, command=cmd, width=9).pack(padx=6, pady=4)
        self.left.bind("<Double-1>", lambda e: self.add())
        self.right.bind("<Double-1>", lambda e: self.remove())
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x")
        tk.Button(bar, text="Zastosuj", command=self.apply).pack(side="right", padx=6, pady=5)
        tk.Button(bar, text="Anuluj", command=self.destroy).pack(side="right")
        tk.Label(bar, text="Pola z Finviz: zamów w edytorze skanera (Kolumny z Finviz) i zrób Sync.",
                 bg=PANEL, fg="#6b7684").pack(side="left", padx=8)
        self.cols = [c for c in view.columns() if c in self.avail or c in columns_mod.DEFS]
        self.fill()

    def fill(self):
        self.left.delete(0, "end")
        self.right.delete(0, "end")
        for k in self.avail:
            if k not in self.cols:
                self.left.insert("end", f"{columns_mod.label(k)}   [{k}]")
        for k in self.cols:
            self.right.insert("end", f"{columns_mod.label(k)}   [{k}]")

    @staticmethod
    def _key(listbox):
        sel = listbox.curselection()
        return listbox.get(sel[0]).rsplit("[", 1)[1].rstrip("]") if sel else None

    def add(self):
        k = self._key(self.left)
        if k and k not in self.cols:
            self.cols.append(k)
            self.fill()

    def remove(self):
        k = self._key(self.right)
        if k and k != "ticker":
            self.cols.remove(k)
            self.fill()

    def move(self, d):
        k = self._key(self.right)
        if k is None:
            return
        i = self.cols.index(k)
        j = max(0, min(len(self.cols) - 1, i + d))
        self.cols[i], self.cols[j] = self.cols[j], self.cols[i]
        self.fill()
        self.right.selection_set(j)

    def defaults(self):
        self.cols = [c for c in columns_mod.DEFAULT_COLUMNS if c in self.avail]
        self.fill()

    def apply(self):
        self.view.set_columns(self.cols if "ticker" in self.cols else ["ticker"] + self.cols)
        self.destroy()



class WhatsNewWindow(tk.Toplevel):
    """„Co nowego od ostatniego Sync”: kto wszedł do skanera i wypadł, nowe KUP / SPRZEDAJ, przypięte boxy w strefie zagrożenia, nowe CANSLIM ≥ 5."""

    def __init__(self, view):
        super().__init__(view.root)
        self.view = view
        ch = view.store.changes
        self.title(f"Co nowego — {view.scanner['name']}")
        self.geometry("760x520")
        self.configure(bg=BG)
        apply_dark(self)
        self.head = tk.Label(self, text="", bg=PANEL, anchor="w", justify="left")
        self.head.pack(fill="x")
        self.tree = ttk.Treeview(self, columns=("price", "text"), show="tree headings")
        self.tree.heading("#0", text="Spółka")
        self.tree.heading("price", text="Cena")
        self.tree.heading("text", text="Stan teraz")
        self.tree.column("#0", width=230)
        self.tree.column("price", width=90, anchor="e")
        self.tree.column("text", width=400)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self.open_row)
        for st, col in STATE_COLORS.items():
            self.tree.tag_configure(st, foreground=col)
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x")
        tk.Button(bar, text="Oznacz jako przeczytane (wyczyść)", command=self.clear).pack(side="left", padx=6, pady=5)
        tk.Button(bar, text="Zamknij", command=self.destroy).pack(side="right", padx=6)
        self.fill(ch)

    def fill(self, ch):
        self.tree.delete(*self.tree.get_children())
        d = ch["diff"]
        self.head.config(text=f"  Zmiany od synchronizacji z {ch['at'] or '—'} (sumują się, dopóki ich nie wyczyścisz): {changes.total(d)}" if d
                         else "  Brak zmian od ostatniej synchronizacji (albo to pierwsza synchronizacja tego skanera).")
        for key in changes.ORDER:
            items = d.get(key, [])
            if not items:
                continue
            sec = self.tree.insert("", "end", iid=f"sec:{key}", text=f"{changes.LABELS[key]} ({len(items)})", open=True)
            for t in items:
                r = self.view.store.row(t)
                if r:
                    state = r.get("darvas_text_d") if key == "buy_d" else r.get("pbox_text") if key == "zone" else r.get("darvas_text") if key in ("buy_w", "sell") else \
                        f"CANSLIM {r.get('cs')}/7  {r.get('cs_letters', '')}" if key == "canslim" else (r.get("company") or "")
                    self.tree.insert(sec, "end", iid=f"{key}:{t}", text=t, values=(f"{r['price']:.2f}" if r.get("price") else "", state or ""),
                                     tags=(r.get("darvas_d" if key == "buy_d" else "darvas_w", ""),))
                else:
                    self.tree.insert(sec, "end", iid=f"{key}:{t}", text=t, values=("", ch["names"].get(t) or "wypadła z listy skanera"))

    def open_row(self, _e):
        sel = self.tree.selection()
        if sel and ":" in sel[0] and not sel[0].startswith("sec:"):
            t = sel[0].split(":", 1)[1]
            if self.view.store.row(t):
                self.view.open_chart(t)

    def clear(self):
        self.view.clear_changes()
        self.fill(self.view.store.changes)


class ListNamesWindow(tk.Toplevel):
    """Nazwy własnych list (flagi 1–4)."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Nazwy list")
        self.configure(bg=BG)
        apply_dark(self)
        self.vars = {}
        for n, lst in enumerate(app.flags.lists, 1):
            tk.Label(self, text=f"{n}  {lst['icon']}", bg=PANEL).grid(row=n, column=0, padx=8, pady=4)
            v = tk.StringVar(value=lst["name"])
            self.vars[lst["id"]] = v
            tk.Entry(self, textvariable=v, width=28).grid(row=n, column=1, padx=8, pady=4)
        tk.Label(self, text="Klawisze 1–4 na liście nadają flagę zaznaczonej spółce, 0 ją zdejmuje.", bg=PANEL, fg="#8b95a3").grid(row=0, column=0, columnspan=2, padx=8, pady=6)
        tk.Button(self, text="Zapisz", command=self.save).grid(row=6, column=1, sticky="e", padx=8, pady=8)

    def save(self):
        for lid, v in self.vars.items():
            self.app.flags.rename(lid, v.get())
        self.app.refresh_flag_views()
        self.destroy()
