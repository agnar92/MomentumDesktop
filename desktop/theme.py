"""Wygląd: ciemny motyw dla wszystkich widżetów (także ttk), własny pasek menu i ciemny pasek tytułu na Windowsie —
natywne menu systemowe Windows ignoruje kolory i jest białe, więc rysujemy własne."""
import sys
import tkinter as tk
from tkinter import ttk

BG, FG, PANEL, SEL = "#0b0d10", "#c9d1d9", "#12161b", "#1f3a5f"
BTN, ENTRY = "#222a33", "#0f1318"
MONO = ("Consolas", 11)


def setup_style(root):
    root.configure(bg=BG)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=PANEL, foreground=FG, fieldbackground=ENTRY, bordercolor="#1b2027", lightcolor=PANEL, darkcolor=PANEL)
    s.configure("TFrame", background=PANEL)
    s.configure("TLabel", background=PANEL, foreground=FG)
    s.configure("Treeview", background=BG, fieldbackground=BG, foreground=FG, rowheight=28, borderwidth=0, font=MONO)
    s.configure("Treeview.Heading", background="#1b2027", foreground=FG, relief="flat", font=("Consolas", 10, "bold"), padding=(4, 5))
    s.map("Treeview", background=[("selected", SEL)], foreground=[("selected", "#ffffff")])
    s.map("Treeview.Heading", background=[("active", "#27303a")])
    for orient in ("Vertical", "Horizontal"):
        s.configure(f"{orient}.TScrollbar", background="#27303a", troughcolor=BG, bordercolor=BG, arrowcolor=FG, lightcolor="#27303a", darkcolor="#27303a")
        s.map(f"{orient}.TScrollbar", background=[("active", "#3a4654")])
    s.configure("TCombobox", fieldbackground=ENTRY, background=BTN, foreground="#ffffff", arrowcolor=FG, bordercolor="#27303a",
                selectbackground=ENTRY, selectforeground="#ffffff")
    s.map("TCombobox", fieldbackground=[("readonly", ENTRY)], foreground=[("readonly", "#ffffff")], background=[("active", "#2d3744")])
    s.configure("TNotebook", background=BG, bordercolor="#1b2027", tabmargins=(4, 4, 4, 0))
    s.configure("TNotebook.Tab", background=BTN, foreground=FG, padding=(14, 6), bordercolor="#1b2027")
    s.map("TNotebook.Tab", background=[("selected", SEL), ("active", "#2d3744")], foreground=[("selected", "#ffffff")])
    s.configure("Horizontal.TProgressbar", background="#4aa3ff", troughcolor=ENTRY, bordercolor=PANEL)
    for opt, val in (("*Font", MONO), ("*Background", PANEL), ("*Foreground", FG), ("*Button.Background", BTN), ("*Button.Foreground", FG),
                     ("*Button.activeBackground", "#2d3744"), ("*Button.activeForeground", "#ffffff"), ("*Entry.Background", ENTRY),
                     ("*Entry.Foreground", "#ffffff"), ("*Entry.insertBackground", "#ffffff"), ("*Text.Background", ENTRY), ("*Text.Foreground", FG),
                     ("*Menu.Background", PANEL), ("*Menu.Foreground", FG), ("*Menu.activeBackground", SEL), ("*Menu.activeForeground", "#ffffff"),
                     ("*Menubutton.Background", PANEL), ("*Menubutton.Foreground", FG), ("*Menubutton.activeBackground", SEL),
                     ("*Checkbutton.selectColor", ENTRY), ("*Checkbutton.activeBackground", PANEL), ("*Checkbutton.activeForeground", "#ffffff"),
                     ("*Radiobutton.selectColor", SEL), ("*Radiobutton.activeBackground", "#2d3744"), ("*Radiobutton.activeForeground", "#ffffff"),
                     ("*TCombobox*Listbox.background", ENTRY), ("*TCombobox*Listbox.foreground", "#ffffff"),
                     ("*TCombobox*Listbox.selectBackground", SEL), ("*TCombobox*Listbox.selectForeground", "#ffffff"),
                     ("*Labelframe.Background", PANEL), ("*Labelframe.Foreground", FG)):
        root.option_add(opt, val)


def dark_titlebar(win):
    """Windows 10/11: ciemny pasek tytułu okna (DWM). Na innych systemach nic nie robi."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        val = ctypes.c_int(1)
        for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (nowe / starsze Windows 10)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def apply_dark(win):
    """Wołaj po zbudowaniu okna: ciemny pasek tytułu (po wyświetleniu okna)."""
    win.after(60, lambda: dark_titlebar(win))


def fit_window(win, w, h, min_w=520):
    """Rozmiar okna: żądany w×h, ale nie mniejszy niż potrzebuje zawartość (żeby przyciski nie były ucięte) i nie większy niż ekran.
    Wołaj na końcu budowania okna. Okno nie da się zmniejszyć poniżej wysokości potrzebnej na paski z przyciskami;
    szerokości pilnują paski `Flow` i zawijane etykiety."""
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    max_w, max_h = max(400, sw - 80), max(300, sh - 120)
    rw, rh = win.winfo_reqwidth(), win.winfo_reqheight()
    win.geometry(f"{min(w, max_w)}x{min(max(h, rh), max_h)}")   # szerokość: żądana (paski zawijają się same), wysokość: co najmniej tyle, ile trzeba
    win.minsize(min(rw, min_w, max_w), min(rh, max_h))


def place_left_of(win, anchor):
    """Ustawia okno tak, by jego prawa krawędź przylegała do lewej krawędzi okna `anchor` (skaner / watchlista), na tej samej wysokości.
    Gdy po lewej brakuje miejsca na ekranie — próbuje po prawej stronie, w ostateczności przy lewej krawędzi ekranu."""
    win.update_idletasks()
    anchor.update_idletasks()
    try:
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        border = max(0, anchor.winfo_rootx() - anchor.winfo_x())   # szerokość ramki okna (Windows ~8 px)
        w, h = win.winfo_width() if win.winfo_width() > 1 else win.winfo_reqwidth(), win.winfo_height() if win.winfo_height() > 1 else win.winfo_reqheight()
        outer_w = w + 2 * border
        x = anchor.winfo_x() - outer_w
        if x < 0:
            right = anchor.winfo_x() + anchor.winfo_width() + 2 * border
            x = right if right + outer_w <= sw else 0
        y = max(0, min(anchor.winfo_y(), sh - h - 70))
        win.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass


def autowrap(label, pad=24):
    """Etykieta z zawijaniem tekstu do szerokości okna (zamiast ucinania długiego opisu)."""
    label.configure(justify="left", anchor="w")
    label.bind("<Configure>", lambda e: label.configure(wraplength=max(160, e.width - pad)) if abs(label.cget("wraplength") - e.width + pad) > 4 else None)
    return label


class Flow(tk.Frame):
    """Pasek, który zawija elementy do kolejnych wierszy, gdy brakuje szerokości (zamiast ucinać przyciski).
    Elementy twórz z mistrzem = ten pasek, a potem `flow.add(widget)` (zamiast pack)."""

    def __init__(self, master, padx=4, pady=3, **kw):
        kw.setdefault("bg", PANEL)
        super().__init__(master, **kw)
        self.items, self.padx, self.pady, self._fw, self._busy = [], padx, pady, 0, False
        self.bind("<Configure>", self._conf)

    def add(self, widget, **_):
        self.items.append(widget)
        widget.bind("<Configure>", lambda e: self.after_idle(self.relayout), add="+")
        self.after_idle(self.relayout)
        return widget

    def _conf(self, e):
        if e.width != self._fw:
            self._fw = e.width
            self.relayout()

    def relayout(self):
        if self._busy or not self.winfo_exists():
            return
        self._busy = True
        try:
            width = self._fw if self._fw > 1 else 10 ** 6   # przed pierwszym wyświetleniem zakładamy jeden wiersz
            x = y = row_h = 0
            widest = 0
            for w in self.items:
                rw, rh = w.winfo_reqwidth(), w.winfo_reqheight()
                widest = max(widest, rw + 2 * self.padx)
                if x and x + rw + self.padx > width:
                    x, y, row_h = 0, y + row_h + self.pady, 0
                w.place(x=x + self.padx, y=y + self.pady, width=rw, height=rh)
                x += rw + self.padx
                row_h = max(row_h, rh)
            self.configure(height=y + row_h + 2 * self.pady, width=min(widest, 480))
        finally:
            self._busy = False


class MenuBar(tk.Frame):
    """Własny pasek menu: [(tytuł, [(napis, polecenie) | None (separator)])]. Rysujemy go sami, bo natywny pasek menu Windows jest biały."""

    def __init__(self, master, spec):
        super().__init__(master, bg=PANEL)
        for title, items in spec:
            mb = tk.Menubutton(self, text=title, bg=PANEL, fg=FG, activebackground=SEL, activeforeground="#ffffff", relief="flat", padx=10, pady=4, bd=0)
            menu = tk.Menu(mb, tearoff=0, bg=PANEL, fg=FG, activebackground=SEL, activeforeground="#ffffff", bd=0)
            for it in items:
                if it is None:
                    menu.add_separator()
                else:
                    menu.add_command(label=it[0], command=it[1])
            mb.config(menu=menu)
            mb.pack(side="left")
