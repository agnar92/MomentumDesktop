"""Wspólne widżety: lista spółek z wybieranymi kolumnami i okno dziennika synchronizacji."""
import tkinter as tk
from tkinter import ttk

from . import columns as columns_mod
from . import flags as flags_mod
from . import store
from .theme import BG, FG, apply_dark

STATE_COLORS = {"BUY": "#3ddc84", "SELL": "#ff5c5c", "OUT": "#ff9f43", "NOVOL": "#ffd166", "LATE": "#ffd166", "HOLD": FG, "WAIT": "#6ea8ff"}


class StockTable(tk.Frame):
    """Lista spółek (Treeview) z wybieranymi kolumnami i sortowaniem po nagłówku; Enter / dwuklik = otwórz wykres."""

    def __init__(self, master, on_open, on_new_window=None, on_canslim=None, columns=None, flags=None, on_flag=None):
        super().__init__(master, bg=BG)
        self.on_open, self.on_new_window = on_open, on_new_window
        self.flags, self.on_flag = flags, on_flag
        self.rows, self.sort_col, self.sort_rev = [], None, False
        self.columns = list(columns or columns_mod.DEFAULT_COLUMNS)
        self.tf = "W"
        self.tree = ttk.Treeview(self, columns=self.columns, show="headings", selectmode="browse")
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb.set, xscrollcommand=hb.set)
        hb.pack(side="bottom", fill="x")
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        for st, col in STATE_COLORS.items():
            self.tree.tag_configure(st, foreground=col)
        self.tree.tag_configure("odd", background="#10141a")   # naprzemienne tło wierszy
        for lst in flags_mod.DEFAULT_LISTS:   # tło wiersza z flagą własnej listy
            self.tree.tag_configure(f"flag_{lst['id']}", background=lst["tint"])
        self._headings()
        self.tree.bind("<Double-1>", lambda e: self._open())
        self.tree.bind("<Return>", lambda e: self._open())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._selected())
        self.on_select = None
        menu = tk.Menu(self.tree, tearoff=0)
        menu.add_command(label="Wykres (okno połączone)", command=self._open)
        if on_new_window:
            menu.add_command(label="Wykres w nowym oknie", command=lambda: self.on_new_window(self.current()))
        if on_canslim:
            menu.add_command(label="CANSLIM — szczegóły…", command=lambda: on_canslim(self.current()))
        self.flag_menu = tk.Menu(menu, tearoff=0)
        if flags and on_flag:
            menu.add_cascade(label="Lista (klawisze 1–4, 0 = usuń)", menu=self.flag_menu)
            self.tree.bind("<Key>", self._key)

        def popup(e):
            self.tree.selection_set(self.tree.identify_row(e.y))
            self.flag_menu.delete(0, "end")
            if self.flags and self.on_flag:
                for n, lst in enumerate(self.flags.lists, 1):
                    self.flag_menu.add_command(label=f"{n}  {lst['icon']} {lst['name']}", command=lambda lid=lst["id"]: self.on_flag(self.current(), lid))
                self.flag_menu.add_separator()
                self.flag_menu.add_command(label="0  Usuń z listy", command=lambda: self.on_flag(self.current(), None))
            menu.tk_popup(e.x_root, e.y_root)

        self.tree.bind("<Button-3>", popup)

    def _headings(self):
        self.tree.configure(columns=self.columns, displaycolumns=self.columns)
        for cid in self.columns:
            label, w, anchor, _ = columns_mod.definition(cid)
            self.tree.heading(cid, text=label, command=lambda c=cid: self.sort_by(c))
            self.tree.column(cid, width=w, anchor=anchor, stretch=False)
        self.set_tf_label(self.tf)

    def _key(self, e):
        """Klawisze 1–4 = flaga listy, 0 = zdjęcie flagi (działa na zaznaczonej spółce)."""
        t = self.current()
        if not t or not self.on_flag:
            return
        if e.char == "0":
            self.on_flag(t, None)
        elif e.char in ("1", "2", "3", "4") and int(e.char) <= len(self.flags.lists):
            self.on_flag(t, self.flags.lists[int(e.char) - 1]["id"])

    def set_columns(self, cols):
        """Zmiana zestawu kolumn (wybór użytkownika); sortowanie po zniknęłej kolumnie jest kasowane."""
        self.columns = list(cols) or list(columns_mod.DEFAULT_COLUMNS)
        if self.sort_col not in self.columns:
            self.sort_col = None
        self._headings()
        self._fill(self.current())

    def set_rows(self, rows):
        keep = self.current()
        self.rows = list(rows)
        self._fill(keep)

    def _fill(self, keep=None):
        rows = self.rows
        if self.sort_col:
            rows = sorted(rows, key=lambda r: columns_mod.sort_value(r, self.sort_col))
            if self.sort_rev:   # malejąco, ale puste wartości zawsze na końcu
                full = [r for r in rows if not columns_mod.sort_value(r, self.sort_col)[0]]
                rows = full[::-1] + [r for r in rows if columns_mod.sort_value(r, self.sort_col)[0]]
        self.tree.delete(*self.tree.get_children())
        for n, r in enumerate(rows):
            self.tree.insert("", "end", iid=r["ticker"], values=[columns_mod.format_cell(r, c, store.STATE_LABELS) for c in self.columns],
                             tags=(r.get("darvas", ""), "odd" if n % 2 else "even") + ((f"flag_{r['flag']}",) if r.get("flag") else ()))
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)

    def set_tf_label(self, tf):
        self.tf = tf
        if "darvas" in self.columns:
            self.tree.heading("darvas", text="Darvas (dzień)" if tf == "D" else "Darvas (tydz.)")

    def sort_by(self, col):
        text_cols = {"ticker", "company", "sector", "industry", "base", "cs_letters", "accdis", "earnings", "pct_to_pivot"}
        self.sort_rev = (not self.sort_rev) if self.sort_col == col else col not in text_cols
        self.sort_col = col
        self._fill(self.current())

    def current(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def visible(self):
        return list(self.tree.get_children())

    def step(self, delta):
        ids = self.visible()
        if not ids:
            return None
        cur = self.current()
        i = ids.index(cur) + delta if cur in ids else 0
        i = max(0, min(len(ids) - 1, i))
        self.tree.selection_set(ids[i])
        self.tree.see(ids[i])
        return ids[i]

    def _open(self):
        t = self.current()
        if t:
            self.on_open(t)

    def _selected(self):
        if self.on_select and self.current():
            self.on_select(self.current())


class SyncWindow(tk.Toplevel):
    """Dziennik synchronizacji (Finviz + yfinance) z paskiem postępu."""

    def __init__(self, app, title="Synchronizacja danych"):
        super().__init__(app.root)
        self.title(title)
        self.geometry("760x420")
        self.configure(bg=BG)
        apply_dark(self)
        self.text = tk.Text(self, bg="#0f1318", fg=FG, wrap="word", state="disabled")
        self.text.pack(fill="both", expand=True)
        self.bar = ttk.Progressbar(self, mode="indeterminate")
        self.bar.pack(fill="x")
        self.bar.start(12)
        self.btn = tk.Button(self, text="Zamknij", state="disabled", command=self.destroy)
        self.btn.pack(pady=4)

    def log(self, line):
        self.text.config(state="normal")
        self.text.insert("end", line + "\n")
        self.text.see("end")
        self.text.config(state="disabled")

    def done(self, ok):
        self.bar.stop()
        self.bar.config(mode="determinate", value=100 if ok else 0)
        self.btn.config(state="normal")
        self.log("✅ Gotowe." if ok else "❌ Synchronizacja nie powiodła się — zostają poprzednie dane.")
