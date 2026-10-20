"""Jeden wykres: tygodniowy słupkowy (High–Low, kreska zamknięcia) z ostatnich 3 lat, SMA 10 i 40 tyg., Green Line, wolumen ze średnią 10 tyg.
i MACD (12, 26, 9) ze znacznikiem przecięcia w dół. Skala ceny logarytmiczna. ↑/↓ przełącza spółki z listy, ruch myszy = dane tygodnia."""
import math
import tkinter as tk

from . import calc
from .theme import BG, FG, PANEL, apply_dark

GRID, DIM = "#1a1f26", "#6b7684"
UP, DOWN = "#d5d9e0", "#e5484d"
SMA_COLORS = {10: "#e5484d", 40: "#f0b429"}
GLB_COLOR, STOP_COLOR, MACD_C, SIG_C = "#3ddc84", "#ff5c5c", "#4aa3ff", "#f0b429"
FONT = ("Consolas", 9)
RIGHT, LEFT, TOP = 64, 6, 22


def ticks(lo, hi, n=7, log=True):
    """Podziałka ceny: okrągłe wartości 1/2/5 × 10^k w zakresie."""
    if not (hi > lo > 0):
        return []
    step = 10 ** math.floor(math.log10((hi - lo) / n or 1))
    for m in (1, 2, 5, 10):
        if (hi - lo) / (step * m) <= n:
            step *= m
            break
    v, out = math.ceil(lo / step) * step, []
    while v <= hi:
        out.append(v)
        v += step
    return out


def fmt(v):
    return "—" if v is None else f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}"


def fmt_vol(v):
    return "—" if v is None else f"{v / 1e9:.1f}B" if v >= 1e9 else f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.0f}K"


def geometry(w, h):
    """Panele: cena 62 %, wolumen 14 %, MACD 18 % wysokości (reszta na odstępy i oś czasu)."""
    ph = h - TOP - 22
    p1 = TOP + ph * 0.62
    v0, v1 = p1 + 6, p1 + 6 + ph * 0.14
    m0, m1 = v1 + 8, h - 22
    return {"price": (TOP, p1), "vol": (v0, v1), "macd": (m0, m1), "x0": LEFT, "x1": w - RIGHT}


def draw(cv, data, row=None, w=None, h=None):
    """Rysuje cały wykres na canvas `cv`; data = {d, o, h, l, c, v}. -> geometria (do dymka przy kursorze)."""
    cv.delete("all")
    w = w or cv.winfo_width()
    h = h or cv.winfo_height()
    c, hi, lo, vol, dates = data["c"], data["h"], data["l"], data["v"], data["d"]
    n = len(c)
    if n < 2:
        return None
    g = geometry(w, h)
    x0, x1 = g["x0"], g["x1"]
    step = (x1 - x0) / n

    def xf(i):
        return x0 + (i + 0.5) * step

    smas = {k: calc.sma([v if v is not None else 0 for v in c], k) for k in SMA_COLORS}
    level = (row or {}).get("glb")
    vals = [v for v in hi + lo if v] + ([level] if level and min(x for x in lo if x) * 0.5 < level < max(x for x in hi if x) * 2 else [])
    pmin, pmax = min(vals) * 0.97, max(vals) * 1.03
    y0, y1 = g["price"]
    lmin, lmax = math.log(pmin), math.log(pmax)

    def yf(p):
        return y1 - (math.log(p) - lmin) / (lmax - lmin) * (y1 - y0)

    for t in ticks(pmin, pmax):
        y = yf(t)
        cv.create_line(x0, y, x1, y, fill=GRID)
        cv.create_text(x1 + 4, y, text=fmt(t), anchor="w", fill=DIM, font=FONT)
    for i in range(n):   # oś czasu: początek każdego kwartału
        if dates[i][5:7] in ("01", "04", "07", "10") and (i == 0 or dates[i - 1][5:7] != dates[i][5:7]):
            cv.create_line(xf(i), y0, xf(i), h - 22, fill=GRID)
            cv.create_text(xf(i), h - 10, text=dates[i][:7], fill=DIM, font=FONT)
    for k, s in smas.items():
        pts = [(xf(i), yf(v)) for i, v in enumerate(s) if v]
        if len(pts) > 1:
            cv.create_line(*[p for xy in pts for p in xy], fill=SMA_COLORS[k], width=1.5)
    for i in range(n):
        if hi[i] is None or lo[i] is None or c[i] is None:
            continue
        col = UP if i == 0 or c[i - 1] is None or c[i] >= c[i - 1] else DOWN
        x = xf(i)
        cv.create_line(x, yf(hi[i]), x, yf(lo[i]), fill=col, width=max(1, step * 0.25))
        cv.create_line(x - step * 0.35, yf(c[i]), x + step * 0.35, yf(c[i]), fill=col)
    if level and pmin < level < pmax:
        y = yf(level)
        cv.create_line(x0, y, x1, y, fill="#0a2e18", width=6)
        cv.create_line(x0, y, x1, y, fill=GLB_COLOR, width=3)
        cv.create_rectangle(x1 + 1, y - 9, w - 2, y + 9, fill=GLB_COLOR, outline="")
        cv.create_text(x1 + 4, y, text=fmt(level), anchor="w", fill="#000", font=FONT)
        cv.create_text(x0 + 4, y - 9, text=f"GREEN LINE {fmt(level)} · kupno do {fmt(level * 1.1)}", anchor="w", fill=GLB_COLOR, font=FONT)
    stop = (row or {}).get("macd_stop")
    if stop and pmin < stop < pmax:
        y = yf(stop)
        cv.create_line(x0, y, x1, y, fill=STOP_COLOR, dash=(5, 4))
        cv.create_text(x1 + 4, y, text=fmt(stop), anchor="w", fill=STOP_COLOR, font=FONT)
    last = c[-1]
    if last:
        cv.create_text(x1 + 4, yf(last), text=fmt(last), anchor="w", fill="#ffffff", font=("Consolas", 9, "bold"))
    # wolumen + średnia 10 tyg.
    v0, v1 = g["vol"]
    vv = [x or 0 for x in vol]
    vmax = max(vv) or 1
    for i in range(n):
        col = UP if i == 0 or (c[i] or 0) >= (c[i - 1] or 0) else DOWN
        cv.create_rectangle(xf(i) - step * 0.35, v1 - vv[i] / vmax * (v1 - v0) * 0.85, xf(i) + step * 0.35, v1, fill=col, outline="")
    va = calc.sma(vv, 10)
    pts = [(xf(i), v1 - a / vmax * (v1 - v0) * 0.85) for i, a in enumerate(va) if a]
    if len(pts) > 1:
        cv.create_line(*[p for xy in pts for p in xy], fill="#ff9f43", width=1.5)
    cv.create_text(x0 + 4, v0 + 6, text="Wolumen · śr. 10 tyg.", anchor="w", fill=DIM, font=FONT)
    # MACD
    m0, m1 = g["macd"]
    cc = [x if x is not None else 0 for x in c]
    mac, sig, hist = calc.macd(cc)
    rng = (max(abs(x) for x in mac + sig + hist) or 1) * 1.25
    mid = (m0 + m1) / 2

    def ym(v):
        return mid - v / rng * (m1 - m0) / 2

    cv.create_line(x0, mid, x1, mid, fill=GRID)
    for i in range(n):
        cv.create_rectangle(xf(i) - step * 0.3, ym(hist[i]), xf(i) + step * 0.3, mid, fill="#2f9e5a" if hist[i] >= 0 else "#a33a3e", outline="")
    for s, col in ((mac, MACD_C), (sig, SIG_C)):
        cv.create_line(*[p for i, v in enumerate(s) for p in (xf(i), ym(v))], fill=col, width=1.3)
    for i in calc.macd_cross_down(hist):
        cv.create_text(xf(i), m1 - 6, text="▼", fill=STOP_COLOR, font=FONT)
    cv.create_text(x0 + 4, m0 + 6, text="MACD (12, 26, 9) tyg. · ▼ przecięcie w dół = stop pod Low tego tygodnia", anchor="w", fill=DIM, font=FONT)
    legend = "  ".join(f"SMA {k} tyg." for k in SMA_COLORS)
    cv.create_text(x0 + 4, 10, text=legend, anchor="w", fill=FG, font=FONT)
    return {"g": g, "step": step, "n": n}


def info_lines(data, i):
    c, o, hi, lo, v, d = data["c"], data["o"], data["h"], data["l"], data["v"], data["d"]
    ch = (c[i] / c[i - 1] - 1) * 100 if i and c[i] and c[i - 1] else None
    return [f"tydz. {d[i]}", f"O {fmt(o[i])}  H {fmt(hi[i])}", f"L {fmt(lo[i])}  C {fmt(c[i])}", f"zmiana {ch:+.1f} %" if ch is not None else "", f"wolumen {fmt_vol(v[i])}"]


def title_text(t, row):
    if not row:
        return t
    parts = [t, row.get("company") or ""]
    for key, lab, unit in (("glb_pct", "do linii", "%"), ("dopm", "Δ marża oper.", " pp"), ("rev_rr", "przychody r/r", "%")):
        v = row.get(key)
        if v is not None:
            parts.append(f"{lab} {v:+.1f}{unit}")
    if row.get("turnover"):
        parts.append(f"obrót {row['turnover'] / 1e6:.0f} mln $/dzień")
    return "  ·  ".join(p for p in parts if p)


class ChartWindow(tk.Toplevel):
    def __init__(self, app, ticker):
        super().__init__(app.root)
        self.app, self.geom = app, None
        self.configure(bg=BG)
        self.geometry("1200x760")
        apply_dark(self)
        self.head = tk.Label(self, text="", bg=PANEL, anchor="w", padx=8)
        self.head.pack(fill="x")
        self.cv = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Configure>", lambda e: self.redraw())
        self.cv.bind("<Motion>", self.on_motion)
        self.bind("<Up>", lambda e: self.step(-1))
        self.bind("<Down>", lambda e: self.step(1))
        self.bind("<Escape>", lambda e: self.destroy())
        self.set_ticker(ticker)

    def set_ticker(self, ticker):
        self.ticker = ticker
        self.title(f"{ticker} — tygodniowy")
        self.head.config(text=title_text(ticker, self.app.store.row(ticker)))
        self.redraw()

    def step(self, d):
        t = self.app.step(self.ticker, d)
        if t:
            self.set_ticker(t)

    def redraw(self):
        data = self.app.store.weekly(self.ticker)
        if not data:
            self.cv.delete("all")
            self.cv.create_text(20, 20, text="Brak danych — zrób Sync albo Ctrl+K.", anchor="w", fill=FG)
            return
        self.geom = draw(self.cv, data, self.app.store.row(self.ticker))

    def on_motion(self, e):
        self.cv.delete("tip")
        data = self.app.store.weekly(self.ticker)
        if not self.geom or not data:
            return
        g = self.geom["g"]
        i = int((e.x - g["x0"]) / self.geom["step"])
        if not 0 <= i < self.geom["n"]:
            return
        self.cv.create_line(e.x, g["price"][0], e.x, g["macd"][1], fill="#3a4654", tags="tip")
        lines = [s for s in info_lines(data, i) if s]
        x = e.x + 14 if e.x < g["x1"] - 200 else e.x - 190
        self.cv.create_rectangle(x, e.y + 10, x + 176, e.y + 16 + 15 * len(lines), fill="#1b2027", outline="#3a4654", tags="tip")
        for k, s in enumerate(lines):
            self.cv.create_text(x + 6, e.y + 20 + 15 * k, text=s, anchor="w", fill=FG, font=FONT, tags="tip")
