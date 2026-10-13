"""Małe okno szybkiego startu: skanery w kolejności ostatniego otwarcia (● = otwarty teraz, ⟳ = trwa synchronizacja)."""
import tkinter as tk

from . import scanners, session, store
from .theme import BG, FG, MONO, PANEL, SEL, apply_dark


class LauncherWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Skanery")
        self.configure(bg=BG)
        w, h = 310, 340
        self.geometry(f"{w}x{h}+{max(0, app.root.winfo_screenwidth() - w - 24)}+80")   # z prawej strony, nie zasłania listy
        apply_dark(self)
        self.ids = []
        self.box = tk.Listbox(self, bg="#0f1318", fg=FG, selectbackground=SEL, selectforeground="#ffffff", font=MONO, activestyle="none",
                              exportselection=False, relief="flat", highlightthickness=0)
        self.box.pack(fill="both", expand=True, padx=2, pady=2)
        self.box.bind("<Double-1>", lambda e: self.open())
        self.box.bind("<Return>", lambda e: self.open())
        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x")
        tk.Button(bar, text="Otwórz", command=self.open, relief="flat").pack(side="left", padx=4, pady=5)
        new = tk.Menubutton(bar, text="＋ Nowy ▾", relief="flat", bg=PANEL, fg=FG, activebackground="#2d3744")
        menu = tk.Menu(new, tearoff=0)
        menu.add_command(label="Skan Finviz…", command=app.new_scanner)
        menu.add_command(label="Skan Qullamaggie (dane do watchlisty)…", command=lambda: app.new_scanner(scanners.KIND_QM))
        menu.add_command(label="Watchlista (lista tickerów z kilku skanów)…", command=lambda: app.new_scanner(scanners.KIND_WATCHLIST))
        new["menu"] = menu
        new.pack(side="left", padx=2)
        tk.Button(bar, text="☰ Zarządzaj", command=app.open_manager, relief="flat").pack(side="left", padx=2)
        self.bind("<Escape>", lambda e: self.destroy())
        self.refresh()

    def refresh(self):
        keep = self.current_id()
        root = self.app.data_root
        items = session.order(scanners.load(root), self.app.session)
        self.ids = [s["id"] for s in items]
        self.box.delete(0, "end")
        for sc in items:
            sid = sc["id"]
            opened = sid == scanners.DEFAULT_ID or self.app.view_for(sid) is not None
            n = (store.read_json(scanners.scanner_dir(root, sid) / "watchlist.json", {}) or {}).get("n_stocks")
            self.box.insert("end", f"{'●' if opened else '○'} {sc['name']}{' ⟳' if sid in self.app.syncing else ''}   {n if n is not None else '—'}")
        if keep in self.ids:
            self.box.selection_set(self.ids.index(keep))
        elif self.ids:
            self.box.selection_set(0)

    def current_id(self):
        sel = self.box.curselection() if hasattr(self, "box") else ()
        return self.ids[sel[0]] if sel and sel[0] < len(self.ids) else None

    def open(self):
        sid = self.current_id()
        if sid:
            self.app.open_scanner_window(sid)
