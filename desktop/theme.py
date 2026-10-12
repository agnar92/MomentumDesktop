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
