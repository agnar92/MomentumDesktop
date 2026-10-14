"""Okna pomocnicze widoku skanera: filtr lokalny, boxy Darvasa, kryteria Finviz, CANSLIM, wybór kolumn."""
import queue
import threading
import tkinter as tk
from tkinter import ttk

from . import adhoc, canslim, changes, finviz_codes, store
from . import columns as columns_mod
from .theme import BG, FG, MONO, PANEL, SEL, Flow, apply_dark, autowrap, fit_window
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
        form.columnconfigure(0, weight=1)
        sf = Flow(form)   # wiersze zawijają się w wąskim oknie
        sf.grid(row=3, column=0, columnspan=6, sticky="we", padx=4)
        sf.add(tk.Label(sf, text="Darvas:", bg=PANEL))
        for st in ("BUY", "NOVOL", "LATE", "HOLD", "WAIT", "SELL", "OUT"):
            v = tk.BooleanVar()
            self.state_vars[st] = v
            sf.add(tk.Checkbutton(sf, text=store.STATE_LABELS[st], variable=v, bg=PANEL, command=self.run))
        self.sector = tk.StringVar()
        row3 = Flow(form)
        row3.grid(row=4, column=0, columnspan=6, sticky="we", padx=4)
        row3.add(tk.Label(row3, text="Sektor:", bg=PANEL))
        self.sector_box = ttk.Combobox(row3, textvariable=self.sector, state="readonly", width=24)
        row3.add(self.sector_box)
        self.sector_box.bind("<<ComboboxSelected>>", lambda e: self.run())
        self.base_only, self.pinned_only, self.cs_core = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
        row3.add(tk.Checkbutton(row3, text="CANSLIM: C i A obowiązkowe", variable=self.cs_core, bg=PANEL, command=self.run))
        row3.add(tk.Checkbutton(row3, text="tylko z bazą do kupienia", variable=self.base_only, bg=PANEL, command=self.run))
        row3.add(tk.Checkbutton(row3, text="tylko przypięte boxy", variable=self.pinned_only, bg=PANEL, command=self.run))
        row4 = Flow(form)
        row4.grid(row=5, column=0, columnspan=6, sticky="we", padx=4, pady=2)
        row4.add(tk.Label(row4, text="Gotowe skany:", bg=PANEL))
        self.preset = ttk.Combobox(row4, values=list(store.PRESETS), state="readonly", width=38)
        row4.add(self.preset)
        self.preset.bind("<<ComboboxSelected>>", lambda e: self.load_preset())
        row4.add(tk.Button(row4, text="Skanuj", command=self.run))
        row4.add(tk.Button(row4, text="Reset", command=self.reset))
        row4.add(tk.Button(row4, text="Zastosuj na liście", command=lambda: app.apply_main_filter(self.collect())))
        row4.add(tk.Button(row4, text="✎ Edytuj skaner Finviz…", command=app.edit_scanner))
        self.count = tk.Label(row4, text="", bg=PANEL)
        row4.add(self.count)
        self.table = StockTable(self, app.open_chart, app.open_chart_new, app.open_canslim, columns=app.columns())
        self.table.pack(fill="both", expand=True)
        self.table.set_tf_label(app.store.tf)
        self.refresh()
        fit_window(self, 1100, 760)

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
        fit_window(self, 900, 620)

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

class PinnedWindow(tk.Toplevel):
    """Szybki przegląd przypiętych (monitorowanych) boxów ze WSZYSTKICH skanerów i watchlist: najgorsze (strefa zagrożenia / exit) na górze.
    Dwuklik otwiera skaner i wykres z tym boxem."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Przypięte boxy — wszystkie skanery")
        self.configure(bg=BG)
        apply_dark(self)
        bar = Flow(self)
        bar.pack(fill="x", side="bottom")
        self.tree = ttk.Treeview(self, columns=("scanner", "price", "text"), show="tree headings")
        for col, text, width, anchor in (("#0", "Spółka", 110, "w"), ("scanner", "Skaner / watchlista", 190, "w"), ("price", "Cena", 80, "e"), ("text", "Status", 520, "w")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.pack(fill="both", expand=True)
        for st, col in STATE_COLORS.items():
            self.tree.tag_configure(st, foreground=col)
        self.tree.bind("<Double-1>", self.open_row)
        self.tree.bind("<Return>", self.open_row)
        bar.add(tk.Button(bar, text="⟳ Odśwież", command=self.refresh))
        bar.add(tk.Button(bar, text="Zamknij", command=self.destroy))
        self.info = tk.Label(bar, text="Dwuklik = otwórz skaner i wykres z boxem", bg=PANEL, fg="#8b95a3")
        bar.add(self.info)
        self.rows = {}
        self.refresh()
        fit_window(self, 960, 420)

    def refresh(self):
        from . import scanners
        from . import store as store_mod
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        found = []
        for sc in scanners.load(self.app.data_root):
            d = scanners.scanner_dir(self.app.data_root, sc["id"])
            if not (store_mod.read_json(d / "pinned.json", {}) or {}):
                continue
            view = self.app.view_for(sc["id"])
            st = view.store if view is not None else store_mod.Store(d, seed=False)
            for r in st.overview().get("pinned", []):
                found.append((r["rank"], r["ticker"], sc, r))
        for n, (_rank, ticker, sc, r) in enumerate(sorted(found, key=lambda x: (x[0], x[1]))):
            iid = f"{sc['id']}:{n}:{ticker}"
            self.rows[iid] = (sc["id"], r)
            self.tree.insert("", "end", iid=iid, text=ticker, values=(sc["name"], f"{r['price']:.2f}" if r.get("price") else "", r["text"]), tags=(r["state"],))
        self.info.config(text=f"{len(found)} przypiętych boxów · dwuklik = otwórz skaner i wykres" if found else "Brak przypiętych boxów — przypnij box na wykresie (Dar-Card: klik w box → 📌 Przypnij)")

    def open_row(self, _e=None):
        sel = self.tree.selection()
        item = self.rows.get(sel[0]) if sel else None
        if not item:
            return
        sid, r = item
        view = self.app.view_for(sid) or self.app.chart_host(sid, self)   # nie otwieramy okna skanera / watchlisty — tylko wykres
        box = dict(r["box"])
        _, dates, _, _ = view.store.series(r["ticker"], view.store.tf)
        if box.get("i0", -1) < 0:   # przypięty: indeks z daty startu
            box["i0"] = next((i for i, w in enumerate(dates) if w >= box.get("start", "")), max(0, len(dates) - 20))
            box["i1"] = len(dates) - 1
            box["outcome"] = "open"
        view.open_chart(r["ticker"], focus=box)


class FinvizCriteriaWindow(tk.Toplevel):
    """Co synchronizujemy: kryteria skanera Finviz (kody filtrów z data/finviz_screen.json) po ludzku."""

    def __init__(self, app):
        super().__init__(app.root)
        cfg = app.store.finviz_config()
        self.title("Kryteria Finviz — co synchronizujemy")
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
        fit_window(self, 760, 470)

class CanslimWindow(tk.Toplevel):
    """CANSLIM litera po literze: werdykt, liczby, które mamy, i reguła (te same dane, na których liczy się n/7)."""

    def __init__(self, app, ticker):
        super().__init__(app.root)
        row = app.store.row(ticker) or {}
        e = canslim.explain(row, app.store.mkt)
        self.title(f"{ticker} — CANSLIM {e['score']}/7")
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
        fit_window(self, 820, 640)

class ColumnsWindow(tk.Toplevel):
    """Wybór kolumn listy z dostępnych danych (lewa lista = co mamy, prawa = co pokazujemy, ▲▼ zmienia kolejność)."""

    def __init__(self, view):
        super().__init__(view.root)
        self.view = view
        self.title(f"Kolumny — {view.scanner['name']}")
        self.configure(bg=BG)
        apply_dark(self)
        bar = Flow(self)   # przyciski na dole pakujemy przed listami — zawsze widoczne
        bar.pack(fill="x", side="bottom")
        self.avail = columns_mod.available(view.store.rows, view.scanner.get("extra") or [])
        tk.Label(self, text="Dostępne dane (dwuklik = dodaj)                        Widoczne kolumny", bg=PANEL, anchor="w").pack(fill="x", side="top")
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
        bar.add(tk.Button(bar, text="Zastosuj", command=self.apply))
        bar.add(tk.Button(bar, text="Anuluj", command=self.destroy))
        bar.add(tk.Label(bar, text="Pola z Finviz: zamów w edytorze skanera (Kolumny z Finviz) i zrób Sync.", bg=PANEL, fg="#6b7684"))
        self.cols = [c for c in view.columns() if c in self.avail or c in columns_mod.DEFS]
        self.fill()
        fit_window(self, 720, 520)

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
        self.configure(bg=BG)
        apply_dark(self)
        bar = Flow(self)   # przyciski na dole pakujemy przed listą
        bar.pack(fill="x", side="bottom")
        self.head = autowrap(tk.Label(self, text="", bg=PANEL))
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
        bar.add(tk.Button(bar, text="Oznacz jako przeczytane (wyczyść)", command=self.clear))
        bar.add(tk.Button(bar, text="Zamknij", command=self.destroy))
        self.fill(ch)
        fit_window(self, 760, 520)

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
        fit_window(self, 300, 200, min_w=300)

    def save(self):
        for lid, v in self.vars.items():
            self.app.flags.rename(lid, v.get())
        self.app.refresh_flag_views()
        self.destroy()


class SymbolDialog(tk.Toplevel):
    """Szybkie wyszukiwanie dowolnego symbolu (Ctrl+K lub /): spółka ze skanera otwiera się od razu, inna jest pobierana z yfinance na żądanie."""

    def __init__(self, view):
        super().__init__(view.root)
        self.view = view
        self.title("Szukaj symbolu")
        self.configure(bg=BG)
        apply_dark(self)
        self.geometry("+%d+%d" % (view.root.winfo_rootx() + 80, view.root.winfo_rooty() + 80))
        tk.Label(self, text="Wpisz symbol (np. NVDA, BRK-B, ^GSPC) i Enter:", bg=PANEL).pack(padx=12, pady=(10, 4))
        self.var = tk.StringVar()
        self.box = ttk.Combobox(self, textvariable=self.var, values=view.app.session.get("symbols", []), width=24)
        self.box.pack(padx=12)
        self.box.focus_set()
        self.msg = tk.Label(self, text="", bg=PANEL, fg="#8b95a3", wraplength=300, justify="left")
        self.msg.pack(padx=12, pady=8)
        self.q = queue.Queue()
        self.busy = False
        self.box.bind("<Return>", lambda e: self.go())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        self.after(150, self.poll)

    def go(self):
        sym = adhoc.normalize(self.var.get())
        if not sym:
            self.msg.config(text="To nie wygląda na symbol giełdowy.", fg="#ff5c5c")
            return
        if self.busy:
            return
        if self.view.store.row(sym) or sym in self.view.store.adhoc:
            self.done(sym)
            return
        self.busy = True
        self.msg.config(text=f"Pobieram {sym} z yfinance… (kilka sekund)", fg="#8b95a3")
        store_ = self.view.store

        def work():
            try:
                self.q.put(("ok", sym, adhoc.fetch(sym, store_.weeks or None, store_.charts_d.get("dates") or None)))
            except Exception as e:
                self.q.put(("err", sym, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, sym, val = self.q.get_nowait()
                self.busy = False
                if kind == "ok":
                    data, name = val
                    self.view.store.add_adhoc(sym, data, name)
                    self.done(sym)
                    return
                self.msg.config(text=val, fg="#ff5c5c")
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(150, self.poll)

    def done(self, sym):
        self.view.app.remember_symbol(sym)
        self.view.open_chart(sym)
        self.destroy()
