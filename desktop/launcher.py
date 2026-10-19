"""Małe okno szybkiego startu: skanery w kolejności ostatniego otwarcia (● = otwarty teraz, ⟳ = trwa synchronizacja)."""
import tkinter as tk

from . import scanners, session, store
from .theme import BG, FG, MONO, PANEL, SEL, Flow, apply_dark


class LauncherWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Skanery")
        self.configure(bg=BG)
        w, h = 340, 340
        self.geometry(f"{w}x{h}+{max(0, app.root.winfo_screenwidth() - w - 24)}+80")   # z prawej strony, nie zasłania listy
        apply_dark(self)
        self.ids = []
        self.box = tk.Listbox(self, bg="#0f1318", fg=FG, selectbackground=SEL, selectforeground="#ffffff", font=MONO, activestyle="none",
                              exportselection=False, relief="flat", highlightthickness=0)
        self.box.pack(fill="both", expand=True, padx=2, pady=2)
        self.box.bind("<Double-1>", lambda e: self.open())
        self.box.bind("<Return>", lambda e: self.open())
        bar = Flow(self)
        bar.pack(fill="x", side="bottom")
        self.box.pack_forget()
        self.box.pack(fill="both", expand=True, padx=2, pady=2)
        bar.add(tk.Button(bar, text="Otwórz", command=self.open, relief="flat"))
        new = tk.Menubutton(bar, text="＋ Nowy ▾", relief="flat", bg=PANEL, fg=FG, activebackground="#2d3744")
        menu = tk.Menu(new, tearoff=0)
        menu.add_command(label="Skan Finviz…", command=app.new_scanner)
        menu.add_command(label="Skan Qullamaggie (dane do watchlisty)…", command=lambda: app.new_scanner(scanners.KIND_QM))
        menu.add_command(label="Skan Wish (Green Line Breakout)…", command=lambda: app.new_scanner(preset="wish"))
        menu.add_command(label="Watchlista (lista tickerów z kilku skanów)…", command=lambda: app.new_scanner(scanners.KIND_WATCHLIST))
        new["menu"] = menu
        bar.add(new)
        bar.add(tk.Button(bar, text="☰ Zarządzaj", command=app.open_manager, relief="flat"))
        bar.add(tk.Button(bar, text="🧭 Krok po kroku", command=app.open_krok, relief="flat"))
        bar.add(tk.Button(bar, text="📌 Przypięte boxy", command=app.open_pinned, relief="flat"))
        self.bind("<Escape>", lambda e: self.destroy())
        self.refresh()

    def refresh(self):
        keep = self.current_id()
        root = self.app.data_root
        items = session.order(scanners.load(root), self.app.session)
        groups = (("Skany (pobierają dane)", [s for s in items if s.get("kind") != scanners.KIND_WATCHLIST]),
                  ("Watchlisty (listy tickerów)", [s for s in items if s.get("kind") == scanners.KIND_WATCHLIST]))
        self.ids = []   # równolegle do wierszy listy; None = nagłówek grupy
        self.box.delete(0, "end")
        for title, group in groups:
            if not group:
                continue
            self.box.insert("end", f"── {title} ──")
            self.box.itemconfig("end", fg="#8b95a3", selectforeground="#8b95a3", selectbackground="#0f1318")
            self.ids.append(None)
            for sc in group:
                sid = sc["id"]
                opened = sid == scanners.DEFAULT_ID or self.app.view_for(sid) is not None
                n = (store.read_json(scanners.scanner_dir(root, sid) / "watchlist.json", {}) or {}).get("n_stocks")
                self.box.insert("end", f"{'●' if opened else '○'} {sc['name']}{' ⟳' if sid in self.app.syncing else ''}   {n if n is not None else '—'}")
                self.ids.append(sid)
        if keep and keep in self.ids:
            self.box.selection_set(self.ids.index(keep))
        else:
            first = next((i for i, x in enumerate(self.ids) if x), None)
            if first is not None:
                self.box.selection_set(first)

    def current_id(self):
        sel = self.box.curselection() if hasattr(self, "box") else ()
        return self.ids[sel[0]] if sel and sel[0] < len(self.ids) else None

    def open(self):
        sid = self.current_id()
        if sid:
            self.app.open_scanner_window(sid)
