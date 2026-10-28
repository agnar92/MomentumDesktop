"""Wykres tygodniowy (T, ostatnie 3 lata) i miesięczny (M, cała historia) w prostym układzie: szare słupki OHLC, niebieska SMA 10 interwału, zielona
kropkowana Green Line od świecy rekordu (z ceną nad świecą i na osi), zielone tło tam, gdzie SPY jest nad własną SMA 10 tego samego interwału,
wolumen (zielony / czerwony + średnia 10) i MACD (12, 26, 9). Skala ceny logarytmiczna. Dzienny (D) i widok Zangera (Z) mają własne, rozbudowane rysowanie.
↑/↓ przełącza spółki z listy, ruch myszy = dane świecy.
Suwak nad wykresem (minimapa całej historii): przeciągnij ramkę = przesuń okno, krawędzie = zmień długość, klik obok = skok, kółko = zoom.
Średnie i MACD liczymy na całej historii, więc okno nie zmienia ich wartości.
Linie trendu (lines.py): przeciągnij myszą po wykresie ceny = nowa linia (koniec przyciąga się do High / Low tygodnia), chwyć koniec = zmień punkt,
chwyć środek = przesuń, klik = zaznacz, Delete / prawy przycisk = usuń. 🔔 Obserwuj = alerty strategii dla spółki."""
import datetime as dt
import json
from bisect import bisect_left, bisect_right
import math
import threading
import time
import tkinter as tk
from tkinter import ttk

from . import calc, lines as L, prices
from .theme import BG, FG, PANEL, apply_dark

GRID, DIM = "#1a1f26", "#6b7684"
UP, DOWN = "#d5d9e0", "#e5484d"
SMA_COLORS = {4: "#22d3ee", 10: "#e5484d", 30: "#f0b429"}
DAILY_MA_COLORS = {"EMA 8": "#e5484d", "EMA 10": "#f0b429", "EMA 20": "#3b82f6", "SMA 50": "#22d3ee"}
TLINE = "#22d3ee"
GLB_COLOR, STOP_COLOR, MACD_C, SIG_C = "#3ddc84", "#ff5c5c", "#4aa3ff", "#f0b429"
FAST_C, SLOW_C, RWB_BG, BLUE_DOT = "#e5484d", "#3b82f6", "#232a33", "#4aa3ff"
RS_C = "#38bdf8"   # RS Line (akcja / SPY), jak w Deepvue
FONT = ("Consolas", 9)
RIGHT, LEFT, TOP = 64, 6, 22
ZONE_C = "#9aa3ad"   # strefa kupna 0–10 % nad GLB i przerywana na 5 %
BAR_C, SMA_C, REGIME_BG = "#a9b1bb", "#2f6bff", "#0f2a1c"   # wykres T / M: szare słupki, niebieska SMA 10, tło „SPY nad SMA 10”
VOL_UP, VOL_DOWN = "#1f7a6d", "#7d3c38"
HIST_C = {(True, True): "#00e676", (True, False): "#2e8b57", (False, False): "#ff5252", (False, True): "#8b8f98"}   # (hist ≥ 0, rośnie)
MACD_LINE, SIGNAL_LINE = "#2f6bff", "#c850e8"


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


def earnings_indices(dates, earnings_dates, period="W"):
    """Indeksy świec dla dat publikacji wyników: dokładna/następna sesja D, tydzień zawierający raport W."""
    if not dates or period not in ("D", "W"):
        return []
    found = set()
    for event in earnings_dates or ():
        event = str(event)[:10]
        if len(event) != 10:
            continue
        if period == "D":
            # get_earnings_dates może wskazać weekend; wówczas E trafia pod następną sesję.
            if event < dates[0] or event > dates[-1]:
                continue
            i = bisect_left(dates, event)
            if i < len(dates):
                found.add(i)
        else:
            # Tygodniowe świece są datowane początkiem tygodnia.
            i = bisect_right(dates, event) - 1
            if i >= 0:
                try:
                    offset = (dt.date.fromisoformat(event) - dt.date.fromisoformat(dates[i])).days
                except ValueError:
                    continue
                if 0 <= offset < 7:
                    found.add(i)
    return sorted(found)


def _surprise_map(rows):
    """Mapuje wiersze [data, niespodzianka %] na datę -> wartość liczbową."""
    out = {}
    for row in rows or ():
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        try:
            out[str(row[0])[:10]] = float(row[1]) if row[1] is not None else None
        except (TypeError, ValueError):
            continue
    return out


def earnings_tooltip_lines(data, index, entry, period):
    """Niespodzianki EPS i przychodów tylko dla świecy, pod którą rysowana jest litera E."""
    eps = _surprise_map((entry or {}).get("surp"))
    revenue = _surprise_map((entry or {}).get("revenue_surp"))
    events = set((entry or {}).get("earnings_dates") or ()) | set(eps) | set(revenue)
    dates = data.get("d") or []
    matched = sorted(
        (str(event)[:10] for event in events if index in earnings_indices(dates, [event], period)),
        reverse=True,
    )
    if not matched:
        return []

    def pct(value):
        return "N/D" if value is None else f"{value:+.1f}%"

    # Zwykle jedna publikacja na świecę. Przy kilku (np. zduplikowanych zdarzeniach) podajemy każdą.
    out = []
    for date in matched:
        out.extend([
            f"WYNIKI · {date}",
            f"Earnings Surprise: {pct(eps.get(date))}",
            f"Revenue Surprise: {pct(revenue.get(date))}",
        ])
    return out


def boxed(cv, x, y, text, fill, anchor="w", font=FONT, tags=""):
    """Napis na tle wykresu (prostokąt w kolorze tła pod spodem), żeby nie zlewał się ze świecami i liniami."""
    t = cv.create_text(x, y, text=text, anchor=anchor, fill=fill, font=font, tags=tags)
    b = cv.bbox(t)
    if b:
        r = cv.create_rectangle(b[0] - 2, b[1] - 1, b[2] + 2, b[3] + 1, fill=BG, outline="", tags=tags)
        cv.tag_lower(r, t)
    return t


def ruler_text(p1, p2, k1, k2, period="W"):
    """Miarka (prawy przycisk): zmiana ceny w % od punktu kliknięcia i liczba świec między punktami -> napis."""
    unit = "sesji" if period == "D" else "mies." if period == "M" else "tyg."
    pct = (p2 / p1 - 1) * 100 if p1 else 0.0
    return f"{pct:+.1f} % · {abs(k2 - k1)} {unit} · {fmt(p1)} → {fmt(p2)}"


def axis_spots(level_y, last_y, stop_y, gap=16):
    """Pozycje napisów na prawej osi: Green Line zostaje, ostatnia cena i stop odsuwają się, gdy nachodzą -> (last_y, stop_y)."""
    def away(y, ref):
        if y is None or ref is None or abs(y - ref) >= gap:
            return y
        return ref + gap if y >= ref else ref - gap
    last_y = away(last_y, level_y)
    return last_y, away(away(stop_y, level_y), last_y)


def fmt_vol(v):
    return "—" if v is None else f"{v / 1e9:.1f}B" if v >= 1e9 else f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.0f}K"


def geometry(w, h, period="W"):
    """Panele: RS Line jak w Deepvue (akcja / SPY + średnia, szczyty RS) 10 %, cena 50 %, wolumen 10 %, przychody kwartalne 11 %, MACD reszta
    (odstępy i oś czasu osobno); dzienny (D): RS Line, cena (linia zamknięć + RWB + Blue Dot + GLB) i wolumen — bez przychodów i Stochastic."""
    top = 8
    ph = h - top - 22
    s1 = top + ph * 0.10
    p0 = s1 + 8
    if period == "Z":   # widok Zangera: sama cena (log) i wolumen, bez RS / przychodów / MACD
        p0 = top
        p1 = p0 + ph * 0.80
        return {"rs": None, "price": (p0, p1), "vol": (p1 + 6, h - 22), "rev": None, "macd": (h - 22, h - 22), "x0": LEFT, "x1": w - RIGHT}
    if period == "D":
        p1 = p0 + ph * 0.74
        return {"rs": (top, s1), "price": (p0, p1), "vol": (p1 + 6, h - 22), "rev": None, "macd": (h - 22, h - 22), "x0": LEFT, "x1": w - RIGHT}
    p1 = p0 + ph * 0.50
    v0, v1 = p1 + 6, p1 + 6 + ph * 0.10
    r0, r1 = v1 + 8, v1 + 8 + ph * 0.11
    return {"rs": (top, s1), "price": (p0, p1), "vol": (v0, v1), "rev": (r0, r1), "macd": (r1 + 8, h - 22), "x0": LEFT, "x1": w - RIGHT}


def fmt_big(v):
    return f"{v / 1e9:.1f} mld" if v >= 1e9 else f"{v / 1e6:.0f} mln"


def rev_color(g):
    return DIM if g is None else GLB_COLOR if g >= 25 else SIG_C if g >= 15 else "#6b7684" if g >= 0 else DOWN


# ---------- suwak okna czasu (minimapa) ----------

MIN_WEEKS = 12


def window(total, n_show=None, end=None):
    """-> (i0, i1) okna: n_show tygodni (min. MIN_WEEKS, domyślnie wszystkie) kończące się na `end` (domyślnie ostatni tydzień)."""
    n = total if n_show is None else max(min(MIN_WEEKS, total), min(int(n_show), total))
    e = total if end is None else max(n, min(int(end), total))
    return e - n, e


def slider_rect(total, n_show, end, width, pad=4):
    """Ramka okna na torze suwaka -> (x0, x1) w pikselach."""
    i0, i1 = window(total, n_show, end)
    w = max(1, width - 2 * pad)
    return pad + i0 / total * w, pad + i1 / total * w


def slider_mode(x, x0, x1, edge=7):
    """Co chwycono: left / right (krawędzie), move (środek ramki) albo jump (tor poza ramką)."""
    if abs(x - x0) <= edge:
        return "left"
    if abs(x - x1) <= edge:
        return "right"
    return "move" if x0 < x < x1 else "jump"


def slider_drag(mode, start, dx, total, width, pad=4):
    """Nowe (n_show, end) po przeciągnięciu o dx px; start = (n_show, end) z chwili chwycenia."""
    i0, i1 = window(total, *start)
    n0 = i1 - i0
    d = round(dx * total / max(1, width - 2 * pad))
    if mode == "move":
        i0, i1 = i0 + d, i1 + d
        if i0 < 0:
            i0, i1 = 0, n0
        if i1 > total:
            i0, i1 = total - n0, total
    elif mode == "left":
        i0 = max(0, min(i0 + d, i1 - MIN_WEEKS))
    else:
        i1 = min(total, max(i1 + d, i0 + MIN_WEEKS))
    return i1 - i0, i1


def slider_jump(x, total, n_show, width, pad=4):
    """Klik na torze poza ramką: ramka wyśrodkowana na klikniętym tygodniu -> (n_show, end)."""
    i0, i1 = window(total, n_show)
    n = i1 - i0
    centre = (x - pad) / max(1, width - 2 * pad) * total
    return n, max(n, min(total, int(round(centre + n / 2))))


def zoom(total, n_show, end, factor):
    """Zoom kółkiem: długość okna × factor, prawy brzeg zostaje."""
    i0, i1 = window(total, n_show, end)
    return max(min(MIN_WEEKS, total), min(total, int(round((i1 - i0) * factor)))), i1


def draw_slider(cv, closes, n_show, end, unit="tyg."):
    """Minimapa zamknięć całej historii (skala log) + ramka bieżącego okna z uchwytami i długością."""
    cv.delete("all")
    W, H = cv.winfo_width(), cv.winfo_height()
    vals = [v for v in closes if v]
    if W < 40 or len(vals) < 2:
        return
    total = len(closes)
    lo, hi = math.log(min(vals)), math.log(max(vals))
    y = (lambda v: H / 2) if hi == lo else (lambda v: H - 6 - (math.log(v) - lo) / (hi - lo) * (H - 12))
    x0, x1 = slider_rect(total, n_show, end, W)
    cv.create_rectangle(x0, 0, x1, H, fill="#16202c", outline="")
    pts = [(4 + (i + 0.5) / total * (W - 8), y(v)) for i, v in enumerate(closes) if v]
    cv.create_line(*[c for p in pts for c in p], fill="#8b95a3")
    cv.create_rectangle(x0, 1, x1, H - 1, outline="#4aa3ff", width=2)
    for x in (x0, x1):
        cv.create_rectangle(x - 3, H / 2 - 9, x + 3, H / 2 + 9, fill="#4aa3ff", outline="")
    i0, i1 = window(total, n_show, end)
    right = x1 - x0 > 90
    cv.create_text(x1 - 6 if right else x1 + 6, 4, text=f"{i1 - i0} {unit}", fill=FG, font=FONT, anchor="ne" if right else "nw")


def simple_geometry(w, h):
    """Panele wykresu T / M: cena 64 %, wolumen 13 %, MACD reszta (odstęp na oś czasu na dole)."""
    top = 8
    ph = h - top - 22
    p1 = top + ph * 0.64
    v0 = p1 + 6
    v1 = v0 + ph * 0.13
    return {"rs": None, "price": (top, p1), "vol": (v0, v1), "rev": None, "macd": (v1 + 10, h - 22), "x0": LEFT, "x1": w - RIGHT}


def _near(a, b, period):
    """Czy data świecy SPY `b` jest tą samą świecą co `a` (ten sam miesiąc / ten sam tydzień)."""
    if period == "M":
        return a[:7] == b[:7]
    try:
        return abs((dt.date.fromisoformat(a[:10]) - dt.date.fromisoformat(b[:10])).days) < 7
    except ValueError:
        return False


def spy_regime(dates, spx, period="W", n=10):
    """Dla każdej świecy: True, gdy zamknięcie SPY jest nad SMA 10 tego samego interwału (tygodniowa na T, miesięczna na M); None = brak danych SPY."""
    if not spx or not spx.get("d") or not spx.get("c"):
        return [None] * len(dates)
    sma = calc.sma([v if v is not None else 0 for v in spx["c"]], n)
    out = []
    for d in dates:
        k = L.date_index(spx["d"], d)
        if k < 0 or not _near(d, spx["d"][k], period) or sma[k] is None or not spx["c"][k]:
            out.append(None)
        else:
            out.append(spx["c"][k] > sma[k])
    return out


def glb_peak(data, row, period):
    """Poziom Green Line i indeks świecy rekordu, z którego powstała (None, gdy go nie ma w serii). M: z zamkniętych miesięcy wykresu; T: poziom wiersza, świeca z takim High."""
    hs = data["h"]
    if period == "M":
        return calc.green_line(hs[:-1] if data.get("open_last") else hs)
    level = (row or {}).get("glb")
    if not level:
        return None, None
    return level, next((i for i in range(len(hs) - 1, -1, -1) if hs[i] and abs(hs[i] / level - 1) < 0.003), None)


def draw_simple(cv, data, row, w, h, n_show, end, tlines, sel, spx, period):
    """Prosty wykres T / M: szare słupki OHLC, niebieska SMA 10, kropkowana Green Line od świecy rekordu, tło zielone, gdy SPY > SMA 10 interwału,
    wolumen i MACD; linie trendu rysują się na cenie. -> geometria jak z `draw`."""
    total = len(data["c"])
    i0, i1 = window(total, n_show, end)
    cfull = [v if v is not None else 0 for v in data["c"]]
    sma10 = calc.sma(cfull, 10)[i0:i1]
    mac, sig, hist = (x[i0:i1] for x in calc.macd(cfull))
    vavg = calc.sma([x or 0 for x in data["v"]], calc.RVOL_W)[i0:i1]
    c, hi, lo, vol, dates = (data[k][i0:i1] for k in ("c", "h", "l", "v", "d"))
    op = (data.get("o") or [None] * total)[i0:i1]
    n = len(c)
    g = simple_geometry(w, h)
    x0, x1 = g["x0"], g["x1"]
    step = (x1 - x0) / n
    y0, y1 = g["price"]
    v0, v1 = g["vol"]
    m0, m1 = g["macd"]
    u = "mies." if period == "M" else "tyg."

    def xf(i):
        return x0 + (i + 0.5) * step

    level, at = glb_peak(data, row, period)
    vals = [v for v in hi + lo if v]
    if level and min(vals) * 0.5 < level < max(vals) * 2:
        vals += [level, level * 1.1]   # strefa kupna 0–10 % nad linią ma się zmieścić w skali
    pmin, pmax = min(vals) * 0.97, max(vals) * 1.03
    lmin, lmax = math.log(pmin), math.log(pmax)

    def yf(p):
        return y1 - (math.log(p) - lmin) / (lmax - lmin) * (y1 - y0)

    # tło: zielone, gdy SPY nad SMA 10 tego samego interwału (pod ceną i wolumenem)
    regime = spy_regime(dates, spx, period)
    a = None
    for i, on in enumerate([bool(x) for x in regime] + [False]):
        if on and a is None:
            a = i
        elif not on and a is not None:
            cv.create_rectangle(xf(a) - step / 2, y0, xf(i - 1) + step / 2, v1, fill=REGIME_BG, outline="")
            a = None
    ly = yf(level) if level and pmin < level < pmax else None
    xs = xf(at - i0) if at is not None and i0 <= at < i1 else x0   # Green Line i jej strefa zaczynają się na świecy rekordu
    last = c[-1]
    last_y, _ = axis_spots(ly, yf(last) if last else None, None)
    taken = [v for v in (ly, last_y) if v is not None]
    for t in ticks(pmin, pmax):
        y = yf(t)
        cv.create_line(x0, y, x1, y, fill=GRID)
        if all(abs(y - v) >= 13 for v in taken):
            cv.create_text(x1 + 4, y, text=fmt(t), anchor="w", fill=DIM, font=FONT)
    yrs = max(1, math.ceil(60 / max(1e-9, step * 12)))     # miesięczny: co ile lat podpis
    every = max(1, math.ceil(62 / max(1e-9, step * 13)))   # tygodniowy: co który kwartał podpis
    q_no = 0
    for i in range(n):   # oś czasu: początek kwartału (T) / styczeń co `yrs` lat (M)
        new_q = dates[i][5:7] in ("01", "04", "07", "10") and (i == 0 or dates[i - 1][5:7] != dates[i][5:7])
        if period == "M":
            new_q = dates[i][5:7] == "01" and int(dates[i][:4]) % yrs == 0
        if new_q:
            cv.create_line(xf(i), y0, xf(i), h - 22, fill=GRID)
            q_no += 1
            if xf(i) > x0 + 28 and (period == "M" or (q_no - 1) % every == 0):
                cv.create_text(xf(i), h - 10, text=dates[i][:4] if period == "M" else dates[i][:7], fill=DIM, font=FONT)
    if ly is not None:   # strefa kupna: 0–10 % nad Green Line (lekko przezroczysty szary pas) i przerywana na 5 %
        zt, y5 = max(y0, yf(level * 1.1)), yf(level * 1.05)
        if zt < ly:
            cv.create_rectangle(xs, zt, x1, min(ly, y1), fill=ZONE_C, stipple="gray12", outline="")
        if y0 < y5 < y1:
            cv.create_line(xs, y5, x1, y5, fill=ZONE_C, dash=(6, 4))
    # słupki OHLC: jeden szary kolor
    for i in range(n):
        if hi[i] is None or lo[i] is None or c[i] is None:
            continue
        x = xf(i)
        cv.create_line(x, yf(hi[i]), x, yf(lo[i]), fill=BAR_C, width=min(2.5, max(1, step * 0.2)))
        if op[i]:
            cv.create_line(x - step * 0.4, yf(op[i]), x, yf(op[i]), fill=BAR_C, width=min(2, max(1, step * 0.12)))
        cv.create_line(x, yf(c[i]), x + step * 0.4, yf(c[i]), fill=BAR_C, width=min(2, max(1, step * 0.12)))
    pts = [(xf(i), yf(v)) for i, v in enumerate(sma10) if v]
    if len(pts) > 1:
        cv.create_line(*[p for xy in pts for p in xy], fill=SMA_C, width=2.4)
    if ly is not None:   # Green Line: kropkowana od świecy rekordu, cena nad świecą i na osi
        cv.create_line(xs, ly, x1, ly, fill=GLB_COLOR, width=2, dash=(2, 4))
        if at is not None and i0 <= at < i1 and data["h"][at]:
            px, py = xf(at - i0), yf(data["h"][at])
            cv.create_oval(px - 3.5, py - 3.5, px + 3.5, py + 3.5, fill=GLB_COLOR, outline="")
        tx = min(max(xs, x0 + 24), x1 - 24)
        ty = max(y0 + 10, ly - 12)
        t = cv.create_text(tx, ty, text=fmt(level), fill="#06210f", font=("Consolas", 9, "bold"))
        bb = cv.bbox(t)
        if bb:
            r = cv.create_rectangle(bb[0] - 3, bb[1] - 1, bb[2] + 3, bb[3] + 1, fill=GLB_COLOR, outline="")
            cv.tag_lower(r, t)
        cv.create_rectangle(x1 + 1, ly - 9, w - 2, ly + 9, fill="#ffffff", outline="")
        cv.create_text(x1 + 4, ly, text=fmt(level), anchor="w", fill="#000", font=FONT)
        for k, lab in ((1.05, "+5 %"), (1.1, "+10 %")):   # opisy granic strefy kupna przy prawej krawędzi
            yy = yf(level * k)
            if y0 + 6 < yy < y1 - 4:
                cv.create_text(x1 - 4, yy - 6, text=lab, anchor="e", fill=ZONE_C, font=FONT)
    if last:   # ostatnia cena: cienka kropkowana + znacznik na osi
        cv.create_line(x0, yf(last), x1, yf(last), fill="#4b5563", dash=(1, 3))
        cv.create_rectangle(x1 + 1, last_y - 8, w - 2, last_y + 8, fill="#4b5563", outline="")
        cv.create_text(x1 + 4, last_y, text=fmt(last), anchor="w", fill="#ffffff", font=("Consolas", 9, "bold"))
    segs = draw_lines(cv, data, tlines, sel, i0, i1, xf, yf, g, step, w)
    # wolumen + średnia 10
    vv = [x or 0 for x in vol]
    vmax = max(vv) or 1
    for i in range(n):
        up = i == 0 or (c[i] or 0) >= (c[i - 1] or 0)
        cv.create_rectangle(xf(i) - step * 0.35, v1 - vv[i] / vmax * (v1 - v0) * 0.9, xf(i) + step * 0.35, v1, fill=VOL_UP if up else VOL_DOWN, outline="")
    pts = [(xf(i), v1 - a_ / vmax * (v1 - v0) * 0.9) for i, a_ in enumerate(vavg) if a_]
    if len(pts) > 1:
        cv.create_line(*[p for xy in pts for p in xy], fill=SMA_C, width=1.3)
    # MACD (12, 26, 9): histogram w 4 kolorach (znak × rośnie / maleje), linia MACD i sygnału
    rng = (max(abs(x) for x in mac + sig + hist) or 1) * 1.25
    mid = (m0 + m1) / 2

    def ym(v):
        return mid - v / rng * (m1 - m0) / 2

    cv.create_line(x0, mid, x1, mid, fill=GRID)
    for i in range(n):
        rising = i == 0 or hist[i] >= hist[i - 1]
        cv.create_rectangle(xf(i) - step * 0.3, ym(hist[i]), xf(i) + step * 0.3, mid, fill=HIST_C[(hist[i] >= 0, rising)], outline="")
    for s_, col in ((mac, MACD_LINE), (sig, SIGNAL_LINE)):
        cv.create_line(*[p for i, v in enumerate(s_) for p in (xf(i), ym(v))], fill=col, width=1.4)
    legend = f"SMA 10 {u}" + ("" if any(x is not None for x in regime) else " · brak danych SPY (zrób Sync)") + f" · zielone tło = SPY nad SMA 10 {u}" + (" · szary pas = 0–10 % nad GLB" if ly is not None else "")
    boxed(cv, x0 + 4, y0 + 10, legend, SMA_C)
    return {"g": g, "step": step, "n": n, "i0": i0, "lmin": lmin, "lmax": lmax, "segs": segs}


def draw(cv, data, row=None, w=None, h=None, n_show=None, end=None, tlines=(), sel=None, spx=None, period="W", daily_style="line", earnings_dates=(), zanger=False):
    """Rysuje wykres okna (n_show tygodni kończące się na `end`, domyślnie cała historia) na canvas `cv`; data = {d, o, h, l, c, v};
    tlines = linie trendu, sel = id zaznaczonej. -> geometria (do dymka i linii; `i0` = indeks pierwszego tygodnia okna w pełnej serii, segs = linie w px)."""
    cv.delete("all")
    w = w or cv.winfo_width()
    h = h or cv.winfo_height()
    total = len(data["c"])
    if total < 2:
        return None
    if period in ("W", "M") and not zanger:
        return draw_simple(cv, data, row, w, h, n_show, end, tlines, sel, spx, period)
    i0, i1 = window(total, n_show, end)
    earnings_local = {i - i0 for i in earnings_indices(data.get("d", []), earnings_dates, period) if i0 <= i < i1}
    cfull = [v if v is not None else 0 for v in data["c"]]
    smas = {} if period == "D" or zanger else {k: calc.sma(cfull, k)[i0:i1] for k in ((4, 10, 30) if period == "W" else (10, 30))}
    daily_mas = {}
    if period == "D" and daily_style == "bars":
        daily_mas = {name: (calc.ema(cfull, n) if name.startswith("EMA") else calc.sma(cfull, n))[i0:i1]
                     for name, n in (("EMA 8", 8), ("EMA 10", 10), ("EMA 20", 20), ("SMA 50", 50))}
    mac, sig, hist = (x[i0:i1] for x in calc.macd(cfull))
    crosses = [i - i0 for i in calc.macd_cross_down(calc.macd(cfull)[2]) if i0 <= i < i1]
    nv = calc.RVOL_D if period == "D" else calc.RVOL_W   # średnia wolumenu i wolumen relatywny: dzienny 50 sesji, tygodniowy 10 tygodni
    vavg = calc.sma([x or 0 for x in data["v"]], nv)[i0:i1]
    rv = calc.rel_volume(data["v"], nv)
    c, hi, lo, vol, dates = (data[k][i0:i1] for k in ("c", "h", "l", "v", "d"))
    n = len(c)
    g = geometry(w, h, "Z" if zanger else period)
    x0, x1 = g["x0"], g["x1"]
    step = (x1 - x0) / n

    def xf(i):
        return x0 + (i + 0.5) * step

    level = (row or {}).get("glb")
    vals = [v for v in hi + lo if v] + ([level] if level and min(x for x in lo if x) * 0.5 < level < max(x for x in hi if x) * 2 else [])
    if zanger:   # punkty kupna wzorców i poziom wyjścia z paraboli mają się zmieścić na wykresie
        top_px = max(x for x in hi if x)
        vals += [x for x in pattern_levels(row) if top_px * 0.6 < x < top_px * 1.25]
    # Dodatkowy margines pod ceną tylko wtedy, gdy trzeba narysować E poniżej Low świecy.
    pmin, pmax = min(vals) * (0.92 if earnings_local else 0.97), max(vals) * 1.03
    y0, y1 = g["price"]
    lmin, lmax = math.log(pmin), math.log(pmax)

    def yf(p):
        return y1 - (math.log(p) - lmin) / (lmax - lmin) * (y1 - y0)

    level0, last0 = (row or {}).get("glb"), c[-1] if c else None
    stop0 = _stop_level(row)
    ly = yf(level0) if level0 and pmin < level0 < pmax else None
    last_y, stop_y = axis_spots(ly, yf(last0) if last0 else None, yf(stop0) if stop0 and pmin < stop0 < pmax else None)
    taken = [v for v in (ly, last_y, stop_y) if v is not None]
    for t in ticks(pmin, pmax):
        y = yf(t)
        cv.create_line(x0, y, x1, y, fill=GRID)
        if all(abs(y - v) >= 13 for v in taken):   # podziałka ustępuje napisom Green Line / ceny / stopu
            cv.create_text(x1 + 4, y, text=fmt(t), anchor="w", fill=DIM, font=FONT)
    u = {"M": "mies.", "D": "sesji"}.get(period, "tyg.")
    blue_dot_indices = []
    if period == "D":
        if daily_style == "line":
            blue_dot_indices = draw_rwb(cv, data, row, i0, i1, xf, yf, g, step, cfull)
        else:
            blue_dot_indices = [
                i for i in calc.blue_dots(data["h"], data["l"], data["c"], level)
                if i0 <= i < i1
            ]
    yrs = max(1, math.ceil(60 / max(1e-9, step * 12)))     # wykres miesięczny: co ile lat podpis, żeby się nie nakładały
    every = max(1, math.ceil(62 / max(1e-9, step * 13)))   # tygodniowy: co który kwartał podpis (wąski wykres)
    q_no = 0
    for i in range(n):   # oś czasu: początek każdego kwartału (miesięczny: styczeń co `yrs` lat)
        new_q = dates[i][5:7] in ("01", "04", "07", "10") and (i == 0 or dates[i - 1][5:7] != dates[i][5:7])
        if period == "M":
            new_q = dates[i][5:7] == "01" and int(dates[i][:4]) % yrs == 0
        if new_q:
            cv.create_line(xf(i), y0, xf(i), h - 22, fill=GRID)
            q_no += 1
            if xf(i) > x0 + 28 and (period == "M" or (q_no - 1) % every == 0):   # przy samej krawędzi napis byłby ucięty
                cv.create_text(xf(i), h - 10, text=dates[i][:4] if period == "M" else dates[i][:7], fill=DIM, font=FONT)
    for k, s in smas.items():
        pts = [(xf(i), yf(v)) for i, v in enumerate(s) if v]
        if len(pts) > 1:
            cv.create_line(*[p for xy in pts for p in xy], fill=SMA_COLORS[k], width=1.5)
    for name, s in daily_mas.items():
        pts = [(xf(i), yf(v)) for i, v in enumerate(s) if v]
        if len(pts) > 1:
            cv.create_line(*[p for xy in pts for p in xy], fill=DAILY_MA_COLORS[name], width=1.5)
    pts = [(xf(i), yf(v)) for i, v in enumerate(c) if v] if period == "D" and daily_style == "line" else []
    if len(pts) > 1:
        cv.create_line(*[p for xy in pts for p in xy], fill=FG, width=1.6)
    for i in range(n if period != "D" or daily_style == "bars" else 0):
        if hi[i] is None or lo[i] is None or c[i] is None:
            continue
        col = FG if zanger else UP if i == 0 or c[i - 1] is None or c[i] >= c[i - 1] else DOWN   # widok Zangera: słupki jednokolorowe
        x = xf(i)
        cv.create_line(x, yf(hi[i]), x, yf(lo[i]), fill=col, width=max(1, step * 0.25))
        if period == "D" and daily_style == "bars":
            op = data["o"][i0 + i] if data.get("o") and i0 + i < len(data["o"]) else None
            if op:
                cv.create_line(x - step * 0.3, yf(op), x, yf(op), fill=col)
            cv.create_line(x, yf(c[i]), x + step * 0.3, yf(c[i]), fill=col)
        else:
            cv.create_line(x - step * 0.35, yf(c[i]), x + step * 0.35, yf(c[i]), fill=col)
    # Dzienny wykres słupkowy używa tego samego sygnału Blue Dot co tryb RWB.
    if period == "D" and daily_style == "bars":
        for i in blue_dot_indices:
            low = data["l"][i]
            if low:
                y = yf(low) + 9
                cv.create_oval(
                    xf(i - i0) - 4, y - 4, xf(i - i0) + 4, y + 4,
                    fill=BLUE_DOT, outline=""
                )
    # E = dzień publikacji wyników. E umieszczamy bezpośrednio pod Low świecy.
    for i in sorted(earnings_local):
        if i < len(lo) and lo[i] is not None:
            boxed(cv, xf(i), yf(lo[i]) + 5, "E", "#f0b429", anchor="n", font=("Segoe UI", 9, "bold"))
    if level and pmin < level < pmax:
        y = yf(level)
        cv.create_line(x0, y, x1, y, fill="#0a2e18", width=6)
        cv.create_line(x0, y, x1, y, fill=GLB_COLOR, width=3)
        cv.create_rectangle(x1 + 1, y - 9, w - 2, y + 9, fill=GLB_COLOR, outline="")
        cv.create_text(x1 + 4, y, text=fmt(level), anchor="w", fill="#000", font=FONT)
        # Zostaw wolny pas u góry na legendę SMA; etykietę Green Line umieszczaj niżej,
        # jeśli linia jest blisko górnej krawędzi.
        ty = max(y0 + 38, y - 11)
        boxed(cv, x0 + 4, ty, f"GREEN LINE {fmt(level)} · kupno do {fmt(level * 1.1)}" + (" · wyjście: zamknięcie tyg. pod linią" if (row or {}).get("exit") == "GLB" else ""),
              GLB_COLOR)
    stop = _stop_level(row)   # metoda GLB: wyjście = zamknięcie pod Green Line
    if stop and pmin < stop < pmax:
        y = yf(stop)
        cv.create_line(x0, y, x1, y, fill=STOP_COLOR, dash=(5, 4))
        cv.create_text(x1 + 4, stop_y, text=fmt(stop), anchor="w", fill=STOP_COLOR, font=FONT)
    pl = (row or {}).get("plan")   # 📌 pozycja: stop początkowy −10 % i „sprzedaj połowę” przy −20 % od szczytu
    # Opisy poziomów pozycji dostają osobne wiersze, gdy ich ceny są blisko siebie.
    position_labels = []
    for v, col, lab in (((pl["stop_init"], STOP_COLOR, f"stop −10 % {fmt(pl['stop_init'])}"),
                         (pl["half_at"], "#f0b429", f"½ przy {fmt(pl['half_at'])} (−20 % od szczytu {fmt(pl['peak'])})")) if pl else ()):
        if v and pmin < v < pmax:
            yy = yf(v)
            cv.create_line(x0, yy, x1, yy, fill=col, dash=(2, 3))
            label_y = yy - 8
            if any(abs(label_y - used_y) < 16 for used_y in position_labels):
                label_y = max(y0 + 38, min(y1 - 10, label_y + 17))
            position_labels.append(label_y)
            boxed(cv, x0 + 4, label_y, lab, col)
    if zanger:
        draw_patterns(cv, row, dates, xf, yf, g, step, pmin, pmax)
    segs = draw_lines(cv, data, tlines, sel, i0, i1, xf, yf, g, step, w)
    last = c[-1]
    if last:
        cv.create_text(x1 + 4, last_y, text=fmt(last), anchor="w", fill="#ffffff", font=("Consolas", 9, "bold"))
    # wolumen + średnia 10 tyg.
    v0, v1 = g["vol"]
    vv = [x or 0 for x in vol]
    vmax = max(vv) or 1
    for i in range(n):
        col = UP if i == 0 or (c[i] or 0) >= (c[i - 1] or 0) else DOWN
        cv.create_rectangle(xf(i) - step * 0.35, v1 - vv[i] / vmax * (v1 - v0) * 0.85, xf(i) + step * 0.35, v1, fill=col, outline="")
    pts = [(xf(i), v1 - a / vmax * (v1 - v0) * 0.85) for i, a in enumerate(vavg) if a]
    if len(pts) > 1:
        cv.create_line(*[p for xy in pts for p in xy], fill="#ff9f43", width=1.5)
    cv.create_text(x0 + 4, v0 + 6, text=f"Wolumen · śr. {nv} {u}" + (f" · RVol {rv:.1f}×" if rv is not None else ""), anchor="w",
                   fill=SIG_C if rv is not None and rv >= 1.5 else DIM, font=FONT)
    # MACD
    m0, m1 = g["macd"]
    rng = (max(abs(x) for x in mac + sig + hist) or 1) * 1.25
    mid = (m0 + m1) / 2

    def ym(v):
        return mid - v / rng * (m1 - m0) / 2

    if period != "D" and not zanger:   # dzienny i widok Zangera: bez dolnego panelu (wyjście i tak po tygodniowym MACD)
        cv.create_line(x0, mid, x1, mid, fill=GRID)
        for i in range(n):
            cv.create_rectangle(xf(i) - step * 0.3, ym(hist[i]), xf(i) + step * 0.3, mid, fill="#2f9e5a" if hist[i] >= 0 else "#a33a3e", outline="")
        for s, col in ((mac, MACD_C), (sig, SIG_C)):
            cv.create_line(*[p for i, v in enumerate(s) for p in (xf(i), ym(v))], fill=col, width=1.3)
        for i in crosses:
            cv.create_text(xf(i), m1 - 6, text="▼", fill=STOP_COLOR, font=FONT)
        cv.create_text(x0 + 4, m0 + 6, text=f"MACD (12, 26, 9) {u}" + (" · ▼ = stop pod Low tygodnia przecięcia" if period == "W" else ""),
                       anchor="w", fill=DIM, font=FONT)
    legend = (("  ".join(DAILY_MA_COLORS) + " · ● Blue Dot") if daily_style == "bars" else "GMMA: szybkie EMA (czerwone) / wolne (niebieskie) · jasne tło = RWB · ● Blue Dot") if period == "D" else "  ".join(f"SMA {k} {u}" for k in ((4, 10, 30) if period == "W" else (10, 30)))
    if zanger:
        legend = "Widok Zangera: cena (skala log.) + wolumen · wzorce: " + (", ".join(p["name"] for p in (row or {}).get("patterns") or []) or "brak")
    boxed(cv, x0 + 4, y1 - 10 if period == "D" else y0 + 10, legend, FG)
    # RS Line jak w Deepvue nad wykresem (zastępuje panel S&P 500)
    if not zanger:
        draw_rs_panel(cv, data, i0, i1, xf, g, spx, row, period)
    # przychody kwartalne (słupki w okresie kwartału) z dynamiką r/r: zielony ≥ +25 %, żółty ≥ +15 % (dzienny: bez)
    if period == "D" or zanger:
        return {"g": g, "step": step, "n": n, "i0": i0, "lmin": lmin, "lmax": lmax, "segs": segs}
    q0, q1 = g["rev"]
    qs = (row or {}).get("qs") or []
    shown = []
    for m, q in enumerate(qs):
        b = L.date_index(dates, q["quarter"])
        a = L.date_index(dates, qs[m - 1]["quarter"]) + 1 if m > 0 else b - 12
        if b >= 0 and a <= n - 1 and (q.get("rev") or 0) > 0:
            shown.append((max(0, a), b, q))
    rmax = max([q["rev"] for *_, q in shown] or [1])
    for a, b, q in shown:
        xa, xb = xf(a) - step * 0.45, xf(min(b, n - 1)) + step * 0.45
        ht = q["rev"] / rmax * (q1 - q0 - 26)
        col = rev_color(q.get("rev_rr"))
        cv.create_rectangle(xa + 1, q1 - ht, max(xa + 2, xb - 1), q1, fill=col, outline="", stipple="gray75")
        if xb - xa > 22 and q.get("rev_rr") is not None:
            cv.create_text((xa + xb) / 2, q1 - ht - 6, text=f"{q['rev_rr']:+.0f}%", fill=col, font=FONT)
    cv.create_text(x0 + 4, q0 + 4, text=(f"Przychody kw. · r/r % (zielony ≥ 25 %, żółty ≥ 15 %) · ostatni {fmt_big(qs[-1]['rev'])} $" if qs
                                         else "Przychody kw. — brak danych SEC"), anchor="w", fill=DIM, font=FONT)
    return {"g": g, "step": step, "n": n, "i0": i0, "lmin": lmin, "lmax": lmax, "segs": segs}


PATTERN_COLORS = {"Cup & Handle": "#4da3ff", "Flat Base": "#f0b429", "Ascending Triangle": "#b084f5", "Flaga/Proporzec": "#2ec4b6", "Channel": "#5fd0ff", "Symmetrical Triangle": "#e879f9",
                  "Descending Triangle": "#fb923c", "Falling Wedge": "#34d399", "Inverted H&S": "#a3e635", "Head & Shoulders": "#ff6b6b", "Rising Wedge": "#f87171"}
PARABOLA_COLOR = "#ff4d8d"


def pattern_levels(row):
    """Poziomy do uwzględnienia w skali ceny: punkty kupna wzorców i wyjście z paraboli."""
    r = row or {}
    return [p["buy"] for p in r.get("patterns") or []] + ([r["parabola"]["exit"]] if r.get("parabola") else [])


def draw_patterns(cv, row, dates, xf, yf, g, step, pmin, pmax):
    """Wzorce Zangera na wykresie tygodniowym: kontur (miseczka / uchwyt / baza / trójkąt / flaga), linia i podpis punktu kupna;
    Parabolic Curve = krzywa i poziom wyjścia (zamknięcie tygodnia pod SMA 10). Daty z `shapes` mapowane na tygodnie okna."""
    x0, x1 = g["x0"], g["x1"]

    def px(d):
        j = L.date_index(dates, d)
        return None if j < 0 else xf(min(j, len(dates) - 1))

    def shapes(items, col):
        for sh in items:
            if sh["kind"] == "curve":
                pts = [(px(d), yf(p)) for d, p in sh["pts"] if px(d) is not None and pmin < p < pmax]
                if len(pts) > 1:
                    cv.create_line(*[v for xy in pts for v in xy], fill=col, width=2, smooth=True)
            elif sh["kind"] == "box":
                a, b = px(sh["d1"]), px(sh["d2"])
                if a is not None and b is not None:
                    cv.create_rectangle(a - step * 0.45, yf(min(sh["hi"], pmax)), b + step * 0.45, yf(max(sh["lo"], pmin)), outline=col, width=2, dash=(4, 3))
            elif sh["kind"] == "mark":   # LS / H / RS przy szczytach (dołkach) Head & Shoulders
                a = px(sh["d"])
                if a is not None and pmin < sh["p"] < pmax:
                    boxed(cv, a, yf(sh["p"]) + (14 if sh.get("below") else -14), sh["text"], col, anchor="center", font=("Segoe UI", 10, "bold"))
            elif sh["kind"] == "line":
                a, b = px(sh["d1"]), px(sh["d2"])
                if a is not None and b is not None:
                    cv.create_line(a, yf(sh["p1"]), b, yf(sh["p2"]), fill=col, width=2)
                    if sh.get("label"):   # numer linii (1, 2, 3) przy lewym końcu, jak na schemacie Zangera
                        boxed(cv, a + 4, yf(sh["p1"]) + 10, sh["label"], col, font=("Segoe UI", 9, "bold"))

    used = []
    for p in (row or {}).get("patterns") or []:
        col = PATTERN_COLORS.get(p["name"], FG)
        shapes(p["shapes"], col)
        if pmin < p["buy"] < pmax:
            y = yf(p["buy"])
            a = px(p["end"])
            cv.create_line(a if a is not None else x0, y, x1, y, fill=col, dash=(6, 3), width=2)
            top = g["price"][0] + 32   # pod legendą u góry wykresu
            ly = max(y - 9, top)
            for t in range(6):   # podpisy kolejnych wzorców jeden pod drugim
                if all(abs(ly - u) >= 16 for u in used):
                    break
                ly = max(y + 9 + 16 * t, top)
            used.append(ly)
            what = f"linia {fmt(p['buy'])}" if p.get("side") == "sell" else f"kupno > {fmt(p['buy'])}"
            boxed(cv, x1 - 6, ly, f"{'⚠ ' if p.get('side') == 'sell' else ''}{p['name']} · {what} · {p['state']} ({p['pct']:+.1f} %)" + (f" · wol. {p['vol_x']:.1f}×" if p.get("vol_x") is not None else ""), col, anchor="e")
    para = (row or {}).get("parabola")
    if para:
        shapes(para["shapes"], PARABOLA_COLOR)
        if pmin < para["exit"] < pmax:
            y = yf(para["exit"])
            cv.create_line(x0, y, x1, y, fill=PARABOLA_COLOR, dash=(2, 3))
            boxed(cv, x0 + 4, y + 9, ("PARABOLA · ZŁAMANA najbardziej stroma linia — sprzedaż" + (f" · wol. {para['vol_x']:.1f}×" if para.get("vol_x") else "")
                                      if para.get("state") == "ZŁAMANA" else f"PARABOLA · wyjście: zamknięcie tyg. pod linią 3 ({fmt(para['exit'])})"), PARABOLA_COLOR)


def rs_line(closes, spx_closes):
    """RS Line: zamknięcie akcji / zamknięcie SPY w tym samym tygodniu (sesji) — None, gdy brak."""
    return [c / s if c and s else None for c, s in zip(closes, spx_closes)]


RS_HIGH_C, RS_EARLY_C, RS_MA_C = "#3ddc84", "#f472b6", "#f0b429"


def rs_markers(rs, highs, lookback):
    """Szczyty RS Line jak w Deepvue: {indeks: True (nowy szczyt RS i ceny) / False (RS przed ceną)} — RS powyżej maksimum z `lookback` poprzednich."""
    out = {}
    for i in range(lookback, len(rs)):
        v = rs[i]
        prior = [x for x in rs[i - lookback:i] if x]
        if not v or not prior or v <= max(prior):
            continue
        ph = [x for x in highs[i - lookback:i] if x]
        out[i] = not ph or (highs[i] or 0) > max(ph)
    return out


def draw_rs_panel(cv, data, i0, i1, xf, g, spx, row=None, period="W"):
    """Panel RS Line (Deepvue): akcja / SPY na skali log okna, średnia 52 tyg. (252 sesje na D, 12 mies. na M), ● zielony = nowy szczyt RS
    i ceny, ● różowy = szczyt RS przed ceną; RS 52 tyg. w pp na końcu linii."""
    s0, s1 = g["rs"]
    x0, x1 = g["x0"], g["x1"]
    dates, closes = data.get("d") or [], data.get("c") or []
    highs = data.get("h") or closes
    sv = []
    if spx and spx.get("d"):
        for d in dates:
            k = L.date_index(spx["d"], d)
            sv.append(spx["c"][k] if k >= 0 else None)
    rs_full = rs_line(closes, sv) if sv else []
    lookback = 252 if period == "D" else 12 if period == "M" else 52
    ma_full = [None] * len(rs_full)
    for i in range(lookback - 1, len(rs_full)):
        win = rs_full[i - lookback + 1:i + 1]
        if all(win):
            ma_full[i] = sum(win) / lookback
    rs, ma = rs_full[i0:i1], ma_full[i0:i1]
    ok = [v for v in rs if v]
    if len(ok) < 2:
        cv.create_text(x0 + 4, s0 + 6, text="RS Line — brak danych SPY (zrób Sync)", anchor="w", fill=DIM, font=FONT)
        cv.create_line(x0, s1 + 3, x1, s1 + 3, fill=GRID)
        return
    vals = ok + [v for v in ma if v]
    lo_, hi_ = math.log(min(vals)), math.log(max(vals))

    def yr(v):
        return s1 - (math.log(v) - lo_) / ((hi_ - lo_) or 1) * (s1 - s0 - 4) - 2
    pts = [(xf(i), yr(v)) for i, v in enumerate(rs) if v]
    cv.create_line(*[p for xy in pts for p in xy], fill=RS_C, width=1.6)
    mpts = [(xf(i), yr(v)) for i, v in enumerate(ma) if v]
    if len(mpts) > 1:
        cv.create_line(*[p for xy in mpts for p in xy], fill=RS_MA_C, width=1.3)
    for i, with_price in rs_markers(rs_full, highs, lookback).items():
        if i0 <= i < i1:
            x, y = xf(i - i0), yr(rs_full[i])
            cv.create_oval(x - 3.5, y - 3.5, x + 3.5, y + 3.5, fill=RS_HIGH_C if with_price else RS_EARLY_C, outline="")
    r = row or {}
    unit = "252 sesji" if period == "D" else "12 mies." if period == "M" else "52 tyg."
    full = f"RS Line (akcja / SPY) · średnia {unit} · ● zielony = nowy szczyt RS · ● różowy = RS przed ceną"
    boxed(cv, x0 + 4, s0 + 6, full if x1 - x0 > 7 * len(full) else f"RS / MA {unit}", RS_C)
    if r.get("rs") is not None:   # na końcu linii: siła względna 52 tyg. w pp vs SPY (jak kolumna RS)
        boxed(cv, x1 + 4, pts[-1][1], f"{r['rs']:+.0f} pp", RS_C)
    cv.create_line(x0, s1 + 3, x1, s1 + 3, fill=GRID)


def draw_lines(cv, data, tlines, sel, i0, i1, xf, yf, g, step, w):
    """Linie trendu: odcinek + (tylko z alarmem) przerywane przedłużenie do ostatniego tygodnia okna; Tk nie przycina, więc tniemy do panelu ceny. -> segs (px)."""
    x0, x1 = g["x0"], g["x1"]
    y0, y1 = g["price"]
    segs = []

    def clip(xa, ya, xb, yb):   # Liang–Barsky do prostokąta panelu ceny
        t0, t1, dx, dy = 0.0, 1.0, xb - xa, yb - ya
        for p, q in ((-dx, xa - x0), (dx, x1 - xa), (-dy, ya - y0), (dy, y1 - ya)):
            if p == 0:
                if q < 0:
                    return None
                continue
            r = q / p
            if p < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
            if t0 > t1:
                return None
        return xa + t0 * dx, ya + t0 * dy, xa + t1 * dx, ya + t1 * dy

    for ln in tlines:
        a, b = L.date_index(data["d"], ln["d1"]), L.date_index(data["d"], ln["d2"])
        if a < 0 or b < 0 or a == b:
            continue
        (ia, pa), (ib, pb) = sorted(((a, ln["p1"]), (b, ln["p2"])))
        ie = max(ib, i1 - 1) if ln.get("alert") is not False else ib   # przedłużenie tylko przy włączonym alarmie (to ono jest pilnowane)
        s = {"id": ln["id"], "x1": xf(a - i0), "y1": yf(ln["p1"]), "x2": xf(b - i0), "y2": yf(ln["p2"]), "xe": xf(ie - i0), "ye": yf(L.line_at(ln, data["d"], ie))}
        segs.append(s)
        on = ln["id"] == sel
        seg = clip(xf(ia - i0), yf(pa), xf(ib - i0), yf(pb))
        if seg:
            cv.create_line(*seg, fill=TLINE, width=2.5 if on else 1.6)
        ext = clip(xf(ib - i0), yf(pb), s["xe"], s["ye"]) if ie > ib else None
        if ext:
            cv.create_line(*ext, fill=TLINE, dash=(4, 4))
        if on:
            for x, y in ((s["x1"], s["y1"]), (s["x2"], s["y2"])):
                cv.create_oval(x - 5, y - 5, x + 5, y + 5, outline=TLINE, width=2, fill=BG)
        if ln.get("alert") is not False and s["xe"] >= x1 - step and y0 < s["ye"] < y1:
            cv.create_text(x1 + 4, s["ye"], text=f"🔔 {fmt(L.line_at(ln, data['d'], i1 - 1))}", anchor="w", fill=TLINE, font=FONT)
    return segs


def draw_rwb(cv, data, row, i0, i1, xf, yf, g, step, cfull):
    """Dzienny: jasne tło przy RWB, 6 szybkich (czerwone) i 6 wolnych (niebieskie) EMA, ● Blue Dot pod świecą i stop pod Low ostatniej kropki."""
    y0, y1 = g["price"]
    fast, slow = calc.gmma(cfull)
    r = calc.rwb(cfull)[i0:i1]
    a = None
    for i, on in enumerate(r + [False]):   # odcinki RWB = tło pod świecami
        if on and a is None:
            a = i
        elif not on and a is not None:
            cv.create_rectangle(xf(a) - step / 2, y0, xf(i - 1) + step / 2, y1, fill=RWB_BG, outline="")
            a = None
    for lines_, col in ((slow, SLOW_C), (fast, FAST_C)):
        for s in lines_:
            pts = [(xf(i), yf(v)) for i, v in enumerate(s[i0:i1]) if v]
            if len(pts) > 1:
                cv.create_line(*[p for xy in pts for p in xy], fill=col, width=1)
    dots = [i for i in calc.blue_dots(data["h"], data["l"], data["c"], (row or {}).get("glb")) if i0 <= i < i1]
    for i in dots:
        lo = data["l"][i]
        if lo:
            y = yf(lo) + 9
            cv.create_oval(xf(i - i0) - 4, y - 4, xf(i - i0) + 4, y + 4, fill=BLUE_DOT, outline="")
    return dots


def _stop_level(row):
    """Linia stopu na wykresie: dla 📌 pozycji max(−10 %, MACD od wejścia), bez pozycji stop MACD wiersza; metoda GLB — brak."""
    r = row or {}
    if r.get("exit") == "GLB":
        return None
    pl = r.get("plan")
    if pl:
        return max((v for v in (pl.get("macd_stop"), pl.get("stop_init")) if v), default=None)
    return r.get("macd_stop")


def fund_panel_lines(r, pos=None, plan=None, exit_method="MACD", conditions=None):
    """Treść panelu fundamentów -> [(tekst, tag)]; pokazuje progi strategii i warunki aktualnie włączone."""
    cfg = calc.normalize_conditions(conditions)
    def v(x, u, d=1):
        return "—" if x is None else f"{x:+.{d}f}{u}"
    if not r:
        return [("Brak danych spółki.", "dim")]
    out = [(r["ticker"], "h"), (r.get("company") or "", "dim"),
           (("✓ spełnia warunki" if r.get("ok") else "✗ nie spełnia warunków") + ("   ·   📌 masz pozycję" if pos else ""),
            "status_ok" if r.get("ok") else "status_no")]
    if r.get("slow"):
        out.append(("⚠⚠ hamuje + marża brutto spada" if r["slow"] == "HAMUJE+MB" else "⚠ hamuje (tempo przychodów −10 pp lub więcej)", "warn"))
    out += [(f"OSTATNI RAPORT · kwartał {r.get('quarter') or '—'}", "sec"),
            (f"Przychody r/r\t{v(r.get('rev_rr'), ' %')}", "val"), (f"  poprzedni kw.\t{v(r.get('rev_rr1'), ' %')}", "val"),
            (f"  zmiana tempa\t{v(r.get('accel'), ' pp')}", "val"), (f"Δ marży oper. r/r\t{v(r.get('dopm'), ' pp')}", "val"),
            (f"  poprzedni kw.\t{v(r.get('dopm1'), ' pp')}", "val"), (f"Marża oper.\t{v(r.get('opm'), ' %')}", "val"),
            (f"Δ marży brutto r/r\t{v(r.get('dgm'), ' pp')}", "val"),
            (f"Wycena P/S\t{r['ps']:.1f}" if r.get("ps") else "Wycena P/S\t—", "val"),
            (f"RS 52 tyg. vs S&P\t{v(r.get('rs'), ' pp')}", "val"),
            (f"RS sektora (ETF / SPY nad SMA 52)\t{v(r.get('sector_rs'), ' %')}", "val"),
            (f"Wzorzec Zangera\t{r['pattern'] + ' · ' + r['pattern_state'] + ' · ' + v(r.get('pattern_pct'), ' % do kupna') if r.get('pattern') else '—'}", "val"),
            (f"Ostrzeżenie wzorca\t{r['pattern_exit'] if r.get('pattern_exit') else '—'}", "val"),
            (f"Parabolic Curve (wyjście)\t{r['parabola']['note'] if r.get('parabola') else '—'}", "val"),
            (f"EPS Rating (1–99, przybliżenie IBD)\t{'—' if r.get('eps_rating') is None else r['eps_rating']}", "val"),
            (f"  wzrost EPS 2 ost. kw. r/r\t{v(r.get('eps_g2'), ' %', 0)}", "val"), (f"  EPS 3 lata (TTM, rocznie)\t{v(r.get('eps_cagr3'), ' %', 0)}", "val"),
            (f"  stabilność (kw. ze wzrostem r/r)\t{'—' if r.get('eps_stab') is None else format(r['eps_stab'], '.0%')}", "val"),
            (f"Niespodzianka EPS\t{v(r.get('surp'), ' %')}", "val"), (f"Rewizja EPS 90 dni\t{v(r.get('eps_rev'), ' %')}", "val"),
            (f"Obrót dzienny\t{r['turnover'] / 1e6:.0f} mln $" if r.get("turnover") else "Obrót dzienny\t—", "val"),
            (f"Do Green Line\t{v(r.get('glb_pct'), ' %')}", "val")]
    out.append(("LISTA KONTROLNA", "sec"))

    def item(ok, txt):
        out.append((("✓ " if ok is True else "✗ " if ok is False else "— ") + txt, "ok" if ok is True else "no" if ok is False else "na"))
    def cond(x, test):
        return None if x is None else test(x)
    if cfg["rev_growth"]["enabled"]:
        item(cond(r.get("rev_rr"), lambda x: x >= cfg["rev_growth"]["threshold"]),
             f"przychody kw. ≥ +{cfg['rev_growth']['threshold']:g} % r/r")
    else:
        item(None, f"przychody kw. — kryterium wyłączone (próg +{cfg['rev_growth']['threshold']:g} %)")
    if cfg["op_margin"]["enabled"]:
        item(cond(r.get("dopm"), lambda x: x >= cfg["op_margin"]["threshold"]),
             f"marża oper. ≥ +{cfg['op_margin']['threshold']:g} pp r/r")
    else:
        item(None, f"marża oper. — kryterium wyłączone (próg +{cfg['op_margin']['threshold']:g} pp)")
    if cfg["ps"]["enabled"]:
        item(cond(r.get("ps"), lambda x: x < cfg["ps"]["threshold"]),
             f"wycena P/S < {cfg['ps']['threshold']:g}")
    else:
        item(None, f"wycena P/S — kryterium wyłączone (próg {cfg['ps']['threshold']:g})")
    if cfg["rs"]["enabled"]:
        item(cond(r.get("rs"), lambda x: x >= cfg["rs"]["threshold"]),
             f"siła względna 52 tyg. ≥ +{cfg['rs']['threshold']:g} pp nad S&P 500")
    else:
        item(None, f"siła względna — kryterium wyłączone (próg +{cfg['rs']['threshold']:g} pp)")
    if cfg["beat2"]["enabled"]:
        item(r.get("beat2"), f"2 ostatnie raporty powyżej konsensusu EPS ({v(r.get('surp'), ' %')}, wcześniej {v(r.get('surp_prev'), ' %')})")
    else:
        item(None, "2 ostatnie raporty EPS — kryterium wyłączone")
    st = r.get("glb_state")
    pct = r.get("glb_pct")
    sig = st in ("WYBICIE", "SYGNAŁ") and (pct is None or pct <= 10)
    item(True if sig else None if st in ("NAD", "BLUE DOT", "WYBICIE") else False, f"Green Line: {st or '—'} (kupno: zamknięcie tygodnia 0–10 % nad linią po przebiciu od dołu)")
    item(r.get("macd") == "nad", f"MACD tyg. {r.get('macd') or '—'} sygnałem" + (f" · stop {r['macd_stop']:.2f}" if r.get("macd_stop") else ""))
    item(False if r.get("slow") else None if r.get("accel") is None else True, "brak hamowania przychodów")
    glb, price = r.get("glb"), r.get("price")
    item(None if glb is None or price is None else price >= glb, f"zamknięcie nad Green Line {fmt(glb)} (wyjście metodą GLB: zamknięcie tyg. pod linią)")
    if plan:
        ex = f"zamknięcie tyg. pod Green Line {fmt(glb)}" if exit_method == "GLB" else f"stop MACD od wejścia {fmt(plan.get('macd_stop'))}"
        out += [("PLAN WYJŚCIA · metoda " + ("pod GLB" if exit_method == "GLB" else "MACD"), "sec"),
                (f"Kupno\t{fmt(plan['entry'])}", "val"), (f"Stop −10 %\t{fmt(plan['stop_init'])}", "val"),
                (f"Szczyt od wejścia\t{fmt(plan['peak'])}", "val"), (f"½ przy (−20 %)\t{fmt(plan['half_at'])}", "val"), (f"Reszta\t{ex}", "val")]
        if plan["half"]:
            out.append((f"⚠ Zamknięcie {fmt(plan['last'])} jest ≥ 20 % pod szczytem {fmt(plan['peak'])} — sprzedaj połowę.", "warn"))
        if (plan["glb_exit"] if exit_method == "GLB" else (plan.get("macd_stop") and (price or 0) < plan["macd_stop"])):
            out.append(("⚠ Sygnał wyjścia (" + ("zamknięcie pod Green Line" if exit_method == "GLB" else "zamknięcie pod stopem MACD") + ").", "warn"))
    if pos and r.get("slow"):
        out.append((f"⚠ Masz pozycję, a raport pokazuje hamowanie{' i spadek marży brutto' if r['slow'] == 'HAMUJE+MB' else ''} — spadek ≥ 20 % w 6 mies. "
                    f"w {'50' if r['slow'] == 'HAMUJE+MB' else '44'} % przypadków (normalnie 33 %). Rozważ zacieśnienie stopu.", "warn"))
    return out


def info_lines(data, i):
    c, o, hi, lo, v, d = data["c"], data["o"], data["h"], data["l"], data["v"], data["d"]
    ch = (c[i] / c[i - 1] - 1) * 100 if i and c[i] and c[i - 1] else None
    return [f"{'mies.' if data.get('period') == 'M' else 'tydz.'} {d[i][:7] if data.get('period') == 'M' else d[i]}", f"O {fmt(o[i])}  H {fmt(hi[i])}", f"L {fmt(lo[i])}  C {fmt(c[i])}", f"zmiana {ch:+.1f} %" if ch is not None else "", f"wolumen {fmt_vol(v[i])}"]


def num(text):
    """Liczba z pola tekstowego (przecinek lub kropka, spacje jako separator tysięcy) albo None."""
    try:
        return float(str(text).replace(" ", "").replace("\u00a0", "").replace(",", "."))
    except ValueError:
        return None


def money(v, d=0):
    """1 234 567,89 — spacja tysięcy, przecinek dziesiętny."""
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",")


def size_lines(r, ticker=""):
    """Wynik `lines.position_size` -> teksty okna „Wielkość pozycji" (PLN i USD)."""
    if r is None:
        return ["Podaj kapitał, ryzyko, kurs, cenę wejścia i stop pod ceną wejścia."]
    shares = r["shares"]
    out = [f"Kapitał {money(r['capital_usd'])} USD · ryzyko {money(r['risk_pln'])} PLN ({money(r['risk_usd'])} USD)",
           f"Strata na akcję przy stopie: {money(r['per_share'], 2)} USD", ""]
    if shares:
        out += [f"POZYCJA {ticker}: {shares} akcji (ogranicza: {r['limited_by']})",
                f"Wartość: {money(r['value_usd'])} USD = {money(r['value_pln'])} PLN ({money(r['value_pct'], 1)} % kapitału)",
                f"Strata przy stopie: {money(r['loss_usd'])} USD = {money(r['loss_pln'])} PLN ({money(r['loss_pct'], 2)} % kapitału)"]
    else:
        out += ["POZYCJA: 0 akcji — ryzyko albo kapitał nie wystarczają na jedną akcję"]
    out += ["", f"Cały kapitał: {r['full_shares']} akcji → strata przy stopie {money(r['full_loss_usd'])} USD = {money(r['full_loss_pln'])} PLN "
                f"({money(r['full_loss_pct'], 2)} % kapitału)"]
    return out


class PositionSizeDialog(tk.Toplevel):
    """Wielkość pozycji: kapitał w PLN -> USD (kurs z yfinance, można poprawić), ryzyko = % kapitału, akcje = ryzyko / (wejście − stop).
    Przy 📌 pozycji wejście i stop biorą się z pozycji (stop = większy z −10 % i MACD od wejścia), bez pozycji: cena i Green Line (albo −10 %)."""

    def __init__(self, chart):
        super().__init__(chart)
        self.chart = chart
        self.title("Wielkość pozycji")
        self.configure(bg=BG)
        apply_dark(self)
        st = chart.app.store
        self.vars = {k: tk.StringVar() for k in ("capital", "risk", "fx", "entry", "stop")}
        self.vars["capital"].set(f"{st.settings.get('capital_pln', 10000):g}")
        self.vars["risk"].set(f"{st.settings.get('risk_pct', 1.0):g}")
        fx = (st.cache("fx") or {}).get("usdpln")
        self.vars["fx"].set(f"{fx:.4f}" if fx else "")
        body = tk.Frame(self, bg=PANEL)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        self.head = tk.Label(body, text="", bg=PANEL, fg=FG, font=("Consolas", 11, "bold"), anchor="w")
        self.head.grid(row=0, column=0, columnspan=2, sticky="we", padx=6, pady=(6, 2))
        for r, (key, lab) in enumerate((("capital", "Kapitał (PLN)"), ("risk", "Ryzyko (% kapitału)"), ("fx", "Kurs USD/PLN"),
                                        ("entry", "Wejście (USD)"), ("stop", "Stop (USD)")), start=1):
            tk.Label(body, text=lab, bg=PANEL, fg=FG, anchor="w").grid(row=r, column=0, sticky="w", padx=6, pady=2)
            e = tk.Entry(body, textvariable=self.vars[key], width=14, relief="flat", bg="#0f1318", fg="#f0f4f8", insertbackground="#f0f4f8",
                         font=("Consolas", 11), justify="right", highlightthickness=1, highlightbackground="#303a46", highlightcolor="#4da3ff")
            e.grid(row=r, column=1, sticky="e", padx=6, pady=2)
            self.vars[key].trace_add("write", lambda *a: self.recalc())
        self.note = tk.Label(body, text="", bg=PANEL, fg="#a1adbb", font=("Segoe UI", 9), anchor="w", justify="left", wraplength=360)
        self.note.grid(row=6, column=0, columnspan=2, sticky="we", padx=6, pady=(4, 2))
        tk.Button(body, text="⟳ Kurs USD/PLN", command=self.refresh_fx, relief="flat").grid(row=7, column=0, sticky="w", padx=6, pady=4)
        tk.Button(body, text="↺ Wejście i stop z wykresu", command=self.load_defaults, relief="flat").grid(row=7, column=1, sticky="e", padx=6, pady=4)
        self.out = tk.Label(body, text="", bg="#10151c", fg="#e5ebf2", font=("Consolas", 10), anchor="nw", justify="left", padx=10, pady=8)
        self.out.grid(row=8, column=0, columnspan=2, sticky="we", padx=6, pady=(4, 6))
        self.fx_busy = False
        self.load_defaults()
        if not fx or (st.cache("fx") or {}).get("date") != dt.date.today().isoformat():
            self.refresh_fx()

    def load_defaults(self):
        """Wejście i stop dla spółki z wykresu."""
        c = self.chart
        entry, stop, src = c.size_defaults()
        self.head.config(text=f"{c.ticker}")
        self._set("entry", entry)
        self._set("stop", stop)
        self.note.config(text=src)
        self.recalc()

    def _set(self, key, v):
        self.vars[key].set("" if v is None else f"{v:.2f}")

    def refresh_fx(self):
        """Kurs USD/PLN z yfinance w tle; przy braku sieci zostaje poprzedni (można wpisać ręcznie)."""
        if self.fx_busy:
            return
        self.fx_busy = True
        box = []

        def work():
            try:
                box.append(prices.usdpln())
            except Exception:
                box.append(None)
        threading.Thread(target=work, daemon=True).start()

        def poll():
            if not self.winfo_exists():
                return
            if not box:
                self.after(100, poll)
                return
            self.fx_busy = False
            if box[0]:
                self.vars["fx"].set(f"{box[0]:.4f}")
                self.chart.app.store.save_cache("fx", {"usdpln": box[0], "date": dt.date.today().isoformat()})
            elif not self.vars["fx"].get():
                self.note.config(text="Brak sieci — wpisz kurs USD/PLN ręcznie.")
        self.after(100, poll)

    def recalc(self):
        v = {k: num(x.get()) for k, x in self.vars.items()}
        st = self.chart.app.store
        if v["capital"] and v["capital"] > 0 and v["risk"] is not None and v["risk"] >= 0:   # zapamiętujemy kapitał i ryzyko
            if (st.settings.get("capital_pln"), st.settings.get("risk_pct")) != (v["capital"], v["risk"]):
                st.settings["capital_pln"], st.settings["risk_pct"] = v["capital"], v["risk"]
                st.save_settings()
        r = L.position_size(v["capital"], v["fx"], v["entry"], v["stop"], v["risk"])
        lines_ = size_lines(r, self.chart.ticker)
        if r is None and v["entry"] and v["stop"] and v["stop"] >= v["entry"]:
            lines_ = ["Stop jest na poziomie ceny wejścia albo nad nią — ryzyka nie da się policzyć (wpisz stop pod ceną wejścia)."]
        self.out.config(text="\n".join(lines_))


class ChartWindow(tk.Toplevel):
    def __init__(self, app, ticker):
        super().__init__(app.root)
        self.app, self.geom, self.drag, self.ruler = app, None, None, None
        self.n_show, self.end = None, None   # okno suwaka: długość zostaje między spółkami, koniec wraca do ostatniego tygodnia
        self.configure(bg=BG)
        hh = max(600, min(self.winfo_screenheight() - 90, 1150))   # okno wyższe niż szersze (użytkownik: „bardziej wysokie niż szerokie”)
        self.geometry(f"{int(hh * 0.92)}x{hh}+40+10")
        apply_dark(self)
        self.sel, self.gest = None, None   # zaznaczona linia trendu, gest myszy na wykresie
        self.period, self.other = "W", {"M": {}, "D": {}}   # W = tygodniowy, D = dzienny (2 lata), M = miesięczny (pełna historia) — w pamięci
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="x")
        self.daily_style = "bars"
        self.daily_style_btn = tk.Button(top, text="D: RWB", command=self.toggle_daily_style, relief="flat")
        self.daily_style_btn.pack(side="right", padx=2, pady=2)
        self.sync_btn = tk.Button(top, text="⟳ Sync", command=self.sync_current_ticker, relief="flat")
        self.sync_btn.pack(side="right", padx=2, pady=2)
        self.syncing_ticker = None
        self.watch_btn = tk.Button(top, text="🔕 Obserwuj", command=self.toggle_watch, relief="flat")
        self.watch_btn.pack(side="right", padx=4, pady=2)
        self.per_btns = {}   # osobne przyciski M / T / D (klawisze m / w / d)
        for per, lab in (("D", "D"), ("W", "T"), ("M", "M")):
            b = tk.Button(top, text=lab, width=2, command=lambda x=per: self.toggle_period(x), relief="flat")
            b.pack(side="right", padx=1, pady=2)
            self.per_btns[per] = b
        self.undo_stack = {}   # ticker -> poprzednie stany linii (JSON), do ↶ / Ctrl+Z
        self.undo_btn = tk.Button(top, text="↶", width=2, command=self.undo_line, relief="flat", state="disabled")
        self.undo_btn.pack(side="right", padx=1, pady=2)
        self.zanger = False
        self.zanger_btn = tk.Button(top, text="Z", width=2, command=self.toggle_zanger, relief="flat")
        self.zanger_btn.pack(side="right", padx=1, pady=2)
        self.pos_btn = tk.Button(top, text="📌 Pozycja", command=self.toggle_pos, relief="flat")
        self.pos_btn.pack(side="right", padx=2, pady=2)
        self.size_btn = tk.Button(top, text="💰 Wielkość", command=self.open_size, relief="flat")
        self.size_btn.pack(side="right", padx=2, pady=2)
        self.size_dialog = None
        self.exit_btn = tk.Button(top, text="🚪 Wyjście: MACD", command=self.toggle_exit, relief="flat")
        self.exit_btn.pack(side="right", padx=2, pady=2)
        self.del_btn = tk.Button(top, text="🗑 linia", command=self.delete_selected, relief="flat")
        self.alert_btn = tk.Button(top, text="🔔 alert linii", command=self.toggle_line_alert, relief="flat")
        self.symbol_var = tk.StringVar(value=ticker)
        self.symbol_entry = tk.Entry(
            top, textvariable=self.symbol_var, width=8, relief="flat",
            bg="#0f1318", fg="#f0f4f8", insertbackground="#f0f4f8",
            font=("Consolas", 11, "bold"), highlightthickness=1,
            highlightbackground="#303a46", highlightcolor="#4da3ff",
        )
        self.symbol_entry.pack(side="left", padx=(7, 0), pady=2)
        self.symbol_entry.bind("<Return>", self.submit_ticker)
        self.symbol_entry.bind("<Escape>", self.cancel_ticker_edit)
        self.head = tk.Label(top, text="", bg=PANEL, anchor="w", padx=5)
        self.head.pack(side="left", fill="x", expand=True)
        self.slider = tk.Canvas(self, height=46, bg=BG, highlightthickness=0, cursor="sb_h_double_arrow")
        self.slider.pack(fill="x", padx=2, pady=(2, 0))
        self.slider.bind("<Button-1>", self.slider_press)
        self.slider.bind("<B1-Motion>", self.slider_move)
        self.slider.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))
        self.slider.bind("<Configure>", lambda e: self.after_idle(self.draw_slider))
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        # panel fundamentów po prawej (rozwijany paskiem ze strzałką na całej wysokości wykresu)
        # Szerszy panel z wyraźną typografią i przewijaniem — metryki nie powinny
        # zawijać się przez zbyt wąską kolumnę ani ukrywać dalszej listy kontrolnej.
        self.panel = tk.Frame(body, bg=PANEL, width=380)
        self.panel.pack_propagate(False)
        self.ptext_frame = tk.Frame(self.panel, bg=PANEL)
        self.ptext_frame.pack(fill="both", expand=True)
        self.ptext = tk.Text(
            self.ptext_frame, bg="#10151c", fg="#e5ebf2", relief="flat", wrap="word",
            font=("Segoe UI", 12), padx=16, pady=14, spacing1=3, spacing3=4,
            cursor="arrow", highlightthickness=0, selectbackground="#29445f",
            selectforeground="#ffffff", borderwidth=0,
        )
        tag_styles = (
            ("h", {"font": ("Segoe UI", 16, "bold"), "foreground": "#f8fafc",
                   "spacing1": 2, "spacing3": 2}),
            ("sec", {"font": ("Segoe UI", 11, "bold"), "foreground": "#7cc4ff",
                     "background": "#1b2836", "spacing1": 14, "spacing3": 7,
                     "lmargin1": 6, "lmargin2": 6, "rmargin": 6}),
            ("status_ok", {"font": ("Segoe UI", 11, "bold"), "foreground": "#48e09b",
                           "background": "#13271f", "spacing1": 3, "spacing3": 6,
                           "lmargin1": 5, "rmargin": 5}),
            ("status_no", {"font": ("Segoe UI", 11, "bold"), "foreground": "#ff858b",
                           "background": "#2b1b20", "spacing1": 3, "spacing3": 6,
                           "lmargin1": 5, "rmargin": 5}),
            ("ok", {"foreground": "#48e09b", "font": ("Segoe UI", 11)}),
            ("no", {"foreground": "#ff777e", "font": ("Segoe UI", 11)}),
            ("na", {"foreground": "#a4afbc", "font": ("Segoe UI", 11)}),
            ("warn", {"foreground": "#ffc15a", "background": "#2a2418",
                      "font": ("Segoe UI", 11, "bold"), "spacing1": 10, "spacing3": 5,
                      "lmargin1": 5, "rmargin": 5}),
            ("val", {"font": ("Consolas", 12), "foreground": "#f3f6fa",
                     "spacing1": 1, "spacing3": 2}),
            ("dim", {"foreground": "#a1adbb", "font": ("Segoe UI", 10), "spacing3": 3}),
            ("component", {"foreground": "#c0cad6", "font": ("Segoe UI", 10),
                           "spacing1": 1, "spacing3": 4, "lmargin1": 12,
                           "lmargin2": 20, "rmargin": 7}),
        )
        for tag, kw in tag_styles:
            self.ptext.tag_configure(tag, **kw)
        self.p_scrollbar = ttk.Scrollbar(self.ptext_frame, orient="vertical", command=self.ptext.yview)
        self.ptext.configure(tabs=("205",), yscrollcommand=self.p_scrollbar.set)
        self.p_scrollbar.pack(side="right", fill="y")
        self.ptext.pack(side="left", fill="both", expand=True)
        self.ptext.bind("<MouseWheel>", lambda e: self.ptext.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.ptext.bind("<Button-4>", lambda e: self.ptext.yview_scroll(-1, "units"))
        self.ptext.bind("<Button-5>", lambda e: self.ptext.yview_scroll(1, "units"))
        tk.Button(self.panel, text="📖 Poradnik", command=self.guide, relief="flat").pack(fill="x", padx=8, pady=8)
        self.fund_btn = tk.Button(body, text="", command=self.toggle_panel, relief="flat", width=2, bg="#1b2129", fg="#c9d1d9",
                                  activebackground="#263040", font=("Segoe UI", 10))
        self.show_panel = bool(app.store.settings.get("fund_panel", True))
        if self.show_panel:
            self.panel.pack(side="right", fill="y")
        self.fund_btn.pack(side="right", fill="y")
        self.cv = tk.Canvas(body, bg=BG, highlightthickness=0)
        self.cv.pack(side="left", fill="both", expand=True)
        self.cv.bind("<Configure>", lambda e: self.redraw())
        self.cv.bind("<Motion>", self.on_motion)
        self.cv.bind("<ButtonPress-1>", self.press)
        self.cv.bind("<B1-Motion>", self.drag_line)
        self.cv.bind("<ButtonRelease-1>", self.release)
        self.cv.bind("<ButtonPress-3>", self.right_click)
        self.cv.bind("<B3-Motion>", self.ruler_move)
        self.cv.bind("<ButtonRelease-3>", self.ruler_end)
        self.bind("<Delete>", lambda e: self.delete_selected())
        self.bind("<Control-space>", self.focus_ticker_entry)
        self.bind("m", lambda e: self.toggle_period("M"))
        self.bind("d", lambda e: self.toggle_period("D"))
        self.bind("w", lambda e: self.toggle_period("W"))
        self.bind("z", lambda e: self.toggle_zanger())
        # R przełącza RWB/słupki tylko na wykresie dziennym.
        self.bind("r", lambda e: self.toggle_daily_style() if self.period == "D" else None)
        self.bind("R", lambda e: self.toggle_daily_style() if self.period == "D" else None)
        for w in (self.cv, self.slider):
            w.bind("<MouseWheel>", lambda e: self.zoom(0.85 if e.delta > 0 else 1.18))
            w.bind("<Button-4>", lambda e: self.zoom(0.85))
            w.bind("<Button-5>", lambda e: self.zoom(1.18))
        self.bind("<Up>", lambda e: self.step(-1))
        self.bind("<Down>", lambda e: self.step(1))
        self.bind("<Left>", lambda e: self.pan(-4))
        self.bind("<Right>", lambda e: self.pan(4))
        self.bind("<plus>", lambda e: self.zoom(0.85))
        self.bind("<minus>", lambda e: self.zoom(1.18))
        self.bind("<Escape>", lambda e: self.unselect() if self.sel else self.destroy())
        self.bind("<Control-z>", lambda e: self.undo_line())
        self.set_ticker(ticker)

    def submit_ticker(self, event=None):
        """Przełącza wykres na ticker wpisany bezpośrednio w nagłówku."""
        ticker = self.symbol_var.get().strip().upper()
        if ticker:
            self.app.open_symbol(ticker)
        else:
            self.symbol_var.set(self.ticker)
        return "break"

    def cancel_ticker_edit(self, event=None):
        self.symbol_var.set(self.ticker)
        return "break"

    def focus_ticker_entry(self, event=None):
        self.symbol_entry.focus_set()
        self.symbol_entry.selection_range(0, tk.END)
        return "break"

    def data(self):
        if self.period in ("M", "D"):
            return self.other[self.period].get(self.ticker)
        return self.app.store.weekly(self.ticker)

    def refresh_earnings_dates(self, ticker=None):
        """Bieżące daty wyników z cache; zgodność ze starszym cache przez daty niespodzianek EPS."""
        ticker = ticker or self.ticker
        entry = self.app.store.cache("estimates").get(ticker) or {}
        self.earnings_cache_entry = entry
        dates = entry.get("earnings_dates") or [x[0] for x in entry.get("surp", []) if x]
        self.earnings_dates = sorted({str(x)[:10] for x in dates if x and len(str(x)[:10]) == 10})

    def sync_current_ticker(self):
        """Odświeża wyłącznie spółkę aktualnie otwartą na wykresie."""
        self.app.start_symbol_sync(self.ticker)

    def set_sync_state(self, ticker, syncing):
        if syncing:
            self.syncing_ticker = ticker
            self.sync_btn.config(state="disabled", text="⟳ Pobieram…")
        elif self.syncing_ticker == ticker:
            self.syncing_ticker = None
            self.sync_btn.config(state="normal", text="⟳ Sync")

    def toggle_daily_style(self):
        self.daily_style = "bars" if self.daily_style == "line" else "line"
        self.redraw()

    def toggle_zanger(self):
        """Z: widok Zangera (tylko wykres tygodniowy) — cena, wolumen i wzorce kupna / parabola, bez wskaźników."""
        self.zanger = not self.zanger
        if self.zanger and self.period != "W":
            self.toggle_period("W")
        self.zanger_btn.config(bg="#1f3b5c" if self.zanger else self.del_btn.cget("bg"), fg="#ffffff" if self.zanger else FG)
        self.redraw()

    def toggle_period(self, to=None):
        """M / T / D (bez argumentu: tygodniowy → dzienny → miesięczny). Dzienny (2 lata) i miesięczny (pełna historia) z yfinance (ceny bez korekty),
        raz na spółkę w tle."""
        self.period = to or {"W": "D", "D": "M", "M": "W"}[self.period]
        if self.period != "W" and self.zanger:
            self.zanger = False
            self.zanger_btn.config(bg=self.del_btn.cget("bg"), fg=FG)
        self.n_show, self.end, self.sel = (260 if self.period == "D" else None), None, None   # dzienny: domyślnie ostatni rok
        self.mark_period()
        self.load_period()

    def mark_period(self):
        for per, b in self.per_btns.items():
            b.config(bg="#1f3b5c" if per == self.period else self.del_btn.cget("bg"), fg="#ffffff" if per == self.period else FG)

    def load_period(self):
        t, per = self.ticker, self.period
        self.refresh_earnings_dates(t)
        if per in ("M", "D") and t not in self.other[per]:
            # Dane dzienne są zapisywane do daily.json. Pełne OHLC miesięczne
            # przechowujemy osobno, bo monthly.json zawiera tylko High do Green Line.
            cached = self.app.store.daily(t) if per == "D" else self.app.store.cache("monthly_ohlc").get(t)
            if cached and cached.get("d"):
                self.other[per][t] = cached
            else:
                self.cv.delete("all")
                self.cv.create_text(20, 20, text=f"Pobieram {'historię miesięczną' if per == 'M' else 'świece dzienne'} {t}…", anchor="w", fill=FG)

                def work():
                    try:
                        m = prices.monthly_ohlc(t) if per == "M" else prices.daily_ohlc(t)
                    except Exception:   # brak sieci: komunikat na wykresie
                        m = None
                    if m:
                        m["period"] = per
                        m["open_last"] = per == "M" and m["d"][-1][:7] == dt.date.today().strftime("%Y-%m")
                    box.append(m)
                box = []   # wynik z wątku odbieramy w pętli Tk (Tk nie jest wielowątkowy)
                threading.Thread(target=work, daemon=True).start()

                def poll():
                    if box:
                        self._got(t, box[0], per)
                    elif self.winfo_exists():
                        self.after(100, poll)
                self.after(100, poll)
                return
        name = {"M": "miesięczny", "D": "dzienny"}.get(per, "tygodniowy")
        self.title(f"{t} — {name}")
        self.redraw()

    def _got(self, t, m, per="M"):
        if not m:   # nie zapamiętujemy porażki — kolejne przełączenie spróbuje ponownie
            if t == self.ticker and self.winfo_exists():
                self.cv.delete("all")
                self.cv.create_text(20, 20, text=f"Nie udało się pobrać danych {t} (sieć / yfinance) — 📅 przełącza dalej.", anchor="w", fill=FG)
            return
        self.other[per][t] = m
        if per == "D":
            self.app.store.save_daily_series(t, m)
            self.app.check_alerts(refresh_daily=False)
        elif per == "M":
            monthly_cache = self.app.store.cache("monthly_ohlc")
            monthly_cache[t] = m
            self.app.store.save_cache("monthly_ohlc", monthly_cache)
        if t == self.ticker and self.winfo_exists():
            self.load_period()

    def set_ticker(self, ticker):
        self.ticker, self.end, self.sel, self.gest = ticker, None, None, None
        self.symbol_var.set(ticker)
        if self.period != "W":
            self.n_show = 260 if self.period == "D" else None
        r = self.app.store.row(ticker) or {}
        company = r.get("company") or ""
        self.head.config(text=f"  ·  {company}" if company else "")
        self.tools()
        self.load_period()
        if self.size_dialog and self.size_dialog.winfo_exists():
            self.size_dialog.load_defaults()

    def step(self, d):
        t = self.app.step(self.ticker, d)
        if t:
            self.set_ticker(t)

    def redraw(self):
        data = self.data()
        self.draw_slider()
        if not data:
            self.cv.delete("all")
            message = (f"Pobieram dane {self.ticker}…" if self.ticker in getattr(self.app, "_symbol_openings", set())
                       else f"Brak danych dla {self.ticker} — wpisz ticker powyżej lub użyj Ctrl+Space.")
            self.cv.create_text(20, 20, text=message, anchor="w", fill=FG)
            return
        self.daily_style_btn.config(state="normal" if self.period == "D" else "disabled",
                                    text="D: RWB" if self.daily_style == "bars" else "D: słupki")
        spx = (self.period == "D" and self.app.store.daily("SPY")) or (self.spy_monthly() if self.period == "M" else self.app.store.weekly("SPY"))
        self.geom = draw(self.cv, data, self.row_for_chart(), n_show=self.n_show, end=self.end, tlines=self.lines(), sel=self.sel,
                         spx=spx, period=self.period, daily_style=self.daily_style,
                         earnings_dates=self.earnings_dates, zanger=self.zanger and self.period == "W")

    def spy_monthly(self):
        """SPY miesięczny do tła wykresu M (SPY nad SMA 10 mies.): z cache `monthly_ohlc`; brak albo starszy niż 2 miesiące -> pobranie w tle
        (nie częściej niż co 5 min) i ponowne rysowanie."""
        if getattr(self, "_spy_m", None) is None:
            self._spy_m = self.app.store.cache("monthly_ohlc").get("SPY")
        m = self._spy_m
        stale = not m or m["d"][-1] < (dt.date.today() - dt.timedelta(days=62)).isoformat()
        if stale and time.time() - getattr(self, "_spy_m_try", 0) > 300:
            self._spy_m_try = time.time()
            box = []

            def work():
                try:
                    box.append(prices.monthly_ohlc("SPY"))
                except Exception:   # brak sieci: tło po prostu się nie pojawi
                    box.append(None)
            threading.Thread(target=work, daemon=True).start()

            def poll():
                if not box:
                    if self.winfo_exists():
                        self.after(100, poll)
                    return
                if box[0]:
                    self._spy_m = {**box[0], "period": "M"}
                    cache = self.app.store.cache("monthly_ohlc")
                    cache["SPY"] = self._spy_m
                    self.app.store.save_cache("monthly_ohlc", cache)
                    if self.winfo_exists() and self.period == "M":
                        self.redraw()
            self.after(100, poll)
        return m

    def plan(self):
        st = self.app.store
        p = st.alerts["pos"].get(self.ticker)
        return L.position_plan(p, st.weekly(self.ticker), st.row(self.ticker)) if p else None

    def row_for_chart(self):
        return {**(self.app.store.row(self.ticker) or {}), "exit": self.app.store.settings.get("exit", "MACD"), "plan": self.plan()}

    def toggle_exit(self):
        st = self.app.store
        st.settings["exit"] = "MACD" if st.settings.get("exit", "MACD") == "GLB" else "GLB"
        st.save_settings()
        self.tools()
        self.redraw()
        self.app.refresh()

    def draw_slider(self):
        data = self.data()
        if data:
            draw_slider(self.slider, data["c"], self.n_show, self.end, {"M": "mies.", "D": "sesji"}.get(self.period, "tyg."))
        else:
            self.slider.delete("all")

    def _set(self, n_show, end):
        total = len(self.data()["c"])
        self.n_show = None if n_show >= total else n_show
        self.end = None if end >= total else end
        self.redraw()

    def slider_press(self, e):
        data = self.data()
        if not data:
            return
        total, W = len(data["c"]), self.slider.winfo_width()
        x0, x1 = slider_rect(total, self.n_show, self.end, W)
        mode = slider_mode(e.x, x0, x1)
        if mode == "jump":
            self._set(*slider_jump(e.x, total, self.n_show, W))
            mode = "move"
        self.drag = (mode, e.x, (self.n_show, self.end))

    def slider_move(self, e):
        data = self.data()
        if not data or not self.drag:
            return
        mode, x, start = self.drag
        self._set(*slider_drag(mode, start, e.x - x, len(data["c"]), self.slider.winfo_width()))

    def zoom(self, factor):
        data = self.data()
        if data:
            self._set(*zoom(len(data["c"]), self.n_show, self.end, factor))

    def pan(self, d):
        data = self.data()
        if data:
            total = len(data["c"])
            i0, i1 = window(total, self.n_show, self.end)
            self._set(i1 - i0, max(i1 - i0, min(total, i1 + d)))

    def on_motion(self, e):
        self.cv.delete("tip")
        data = self.data()
        if not self.geom or not data:
            return
        g = self.geom["g"]
        i = int((e.x - g["x0"]) / self.geom["step"])
        if not 0 <= i < self.geom["n"]:
            return
        self.cv.create_line(e.x, (g["rs"] or g["price"])[0], e.x, g["macd"][1], fill="#3a4654", tags="tip")
        index = self.geom["i0"] + i
        lines = [s for s in info_lines(data, index) if s]
        if self.period in ("D", "W"):
            cache = getattr(self, "earnings_cache_entry", None) or {}
            lines.extend(earnings_tooltip_lines(data, index, cache, self.period))
        # Blue Dot pokazujemy w dymku danych po najechaniu na świecę, w obu stylach dziennych.
        if self.period == "D":
            row = self.app.store.row(self.ticker) or {}
            dots = calc.blue_dots(data["h"], data["l"], data["c"], row.get("glb"))
            if index in dots:
                low = data["l"][index]
                lines.extend([f"BLUE DOT · {data['d'][index]}", f"Stop pod Low: {fmt(low)}"])
        tip_w = 252
        x = e.x + 14 if e.x < g["x1"] - tip_w - 14 else e.x - tip_w - 14
        self.cv.create_rectangle(x, e.y + 10, x + tip_w, e.y + 16 + 15 * len(lines), fill="#1b2027", outline="#3a4654", tags="tip")
        for k, s in enumerate(lines):
            self.cv.create_text(x + 6, e.y + 20 + 15 * k, text=s, anchor="w", fill=FG, font=FONT, tags="tip")

    # --- linie trendu
    def lines(self):
        if self.period not in ("W", "D"):
            return []
        return [ln for ln in self.app.store.alerts["lines"].get(self.ticker, [])
                if ln.get("period", "W") == self.period]

    def find(self, lid):
        return next((x for x in self.lines() if x["id"] == lid), None)

    def save_lines(self):
        st = self.app.store
        all_lines = st.alerts["lines"].get(self.ticker, [])
        other = [ln for ln in all_lines if ln.get("period", "W") != self.period]
        current = [ln for ln in self.lines() if ln["d1"] != ln["d2"]]
        merged = other + current
        if merged:
            st.alerts["lines"][self.ticker] = merged
        else:
            st.alerts["lines"].pop(self.ticker, None)
        st.save_alerts()

    def value(self, x, y):
        """Punkt wykresu -> (data tygodnia, cena z magnesem do High / Low, indeks)."""
        g, data = self.geom["g"], self.data()
        y0, y1 = g["price"]
        lmin, lmax = self.geom["lmin"], self.geom["lmax"]
        k = self.geom["i0"] + max(0, min(self.geom["n"] - 1, int((x - g["x0"]) / self.geom["step"])))
        p = math.exp(lmin + (y1 - y) / (y1 - y0) * (lmax - lmin))

        def yf(v):
            return y1 - (math.log(v) - lmin) / (lmax - lmin) * (y1 - y0)
        p = L.snap_price(p, data["h"][k], data["l"][k], yf, y, 8)
        return data["d"][k], float(f"{p:.6g}"), k

    def press(self, e):
        if not self.geom or not self.data() or self.period not in ("W", "D"):  # linie trendu: tygodniowy i dzienny
            return
        self.cv.focus_set()
        hit = L.hit_line(self.geom["segs"], e.x, e.y, 9)
        if hit:
            self.sel = hit[0]
            ln, d = self.find(hit[0]), self.data()["d"]
            self.gest = {"mode": hit[1], "x": e.x, "y": e.y, "orig": dict(ln), "ka": d.index(ln["d1"]) if ln["d1"] in d else -1,
                         "kb": d.index(ln["d2"]) if ln["d2"] in d else -1, "snap": self.lines_json()}
            self.tools()
            self.redraw()
        elif self.geom["g"]["price"][0] <= e.y <= self.geom["g"]["price"][1]:
            self.gest = {"mode": "pend", "x": e.x, "y": e.y}

    def drag_line(self, e):
        gs = self.gest
        if not gs:
            return
        if gs["mode"] == "pend":
            if math.hypot(e.x - gs["x"], e.y - gs["y"]) <= 4:
                return
            d, p, _ = self.value(gs["x"], gs["y"])
            gs["snap"] = self.lines_json()   # stan sprzed nowej linii (do ↶)
            lid = format(int(time.time() * 1000), "x")
            self.app.store.alerts["lines"][self.ticker] = self.app.store.alerts["lines"].get(self.ticker, []) + [
                {"id": lid, "period": self.period, "d1": d, "p1": p, "d2": d, "p2": p,
                 "alert": False}]   # nowa linia: bez alarmu i przedłużenia — alarm użytkownik włącza sam
            self.sel, gs["mode"] = lid, "p2"
            self.tools()
        ln = self.find(self.sel)
        if not ln:
            return
        hint = None
        if gs["mode"] in ("p1", "p2"):
            me = gs["mode"][1]
            other = "2" if me == "1" else "1"
            d, p, k = self.value(e.x, e.y)
            g, geo = self.geom["g"], self.geom
            y0, y1 = g["price"]

            def yf(v):
                return y1 - (math.log(v) - geo["lmin"]) / (geo["lmax"] - geo["lmin"]) * (y1 - y0)
            flat = L.snap_horizontal(p, ln["p" + other], yf, e.y, 5) == ln["p" + other] and ln["d" + other] != d   # blisko poziomu drugiego końca -> poziomo
            if flat:
                p = ln["p" + other]
            ln["d" + me], ln["p" + me] = d, p
            dates = self.data()["d"]
            k1 = dates.index(ln["d" + other]) if ln["d" + other] in dates else k
            hint = (g["x0"] + (k - geo["i0"] + 0.5) * geo["step"], yf(p), flat, ruler_text(ln["p" + other], p, k1, k, self.period) + (" · poziomo" if flat else ""))
        elif gs["mode"] == "body" and gs["ka"] >= 0 and gs["kb"] >= 0:
            dates, g = self.data()["d"], self.geom["g"]
            db = round((e.x - gs["x"]) / self.geom["step"])
            db = max(-min(gs["ka"], gs["kb"]), min(len(dates) - 1 - max(gs["ka"], gs["kb"]), db))
            ratio = math.exp(-(e.y - gs["y"]) / (g["price"][1] - g["price"][0]) * (self.geom["lmax"] - self.geom["lmin"]))
            ln.update(d1=dates[gs["ka"] + db], d2=dates[gs["kb"] + db], p1=float(f"{gs['orig']['p1'] * ratio:.6g}"), p2=float(f"{gs['orig']['p2'] * ratio:.6g}"))
        self.redraw()
        if hint:   # podgląd: kółko w punkcie + „% · tygodnie · cena"
            x, y, flat, txt = hint
            col = "#f0b429" if flat else "#4da3ff"
            self.cv.create_oval(x - 9, y - 9, x + 9, y + 9, outline=col, width=2, tags="hint")
            right = x < self.geom["g"]["x1"] - 240
            boxed(self.cv, x + 12 if right else x - 12, max(self.geom["g"]["price"][0] + 12, y - 14), txt, col, anchor="w" if right else "e", tags="hint")

    def release(self, e):
        gs, self.gest = self.gest, None
        if not gs:
            return
        self.cv.delete("hint")
        if gs["mode"] == "pend":   # klik obok linii = odznacz
            self.unselect()
            return
        self.save_lines()
        if gs.get("snap") is not None and gs["snap"] != self.lines_json():
            self.push_undo(gs["snap"])   # zmiana -> można cofnąć
        if not self.find(self.sel):
            self.sel = None
        self.tools()
        self.redraw()

    def point(self, x, y):
        """Punkt wykresu bez magnesu -> (cena, indeks świecy, x środka świecy)."""
        g = self.geom["g"]
        y0, y1 = g["price"]
        lmin, lmax = self.geom["lmin"], self.geom["lmax"]
        i = max(0, min(self.geom["n"] - 1, int((x - g["x0"]) / self.geom["step"])))
        return math.exp(lmin + (y1 - y) / (y1 - y0) * (lmax - lmin)), self.geom["i0"] + i, g["x0"] + (i + 0.5) * self.geom["step"]

    def ruler_move(self, e):
        """Miarka: przytrzymany prawy przycisk — od punktu kliknięcia % zmiany ceny i liczba tygodni (sesji / miesięcy)."""
        r = self.ruler
        self.cv.delete("ruler", "tip")
        if not r or not self.geom:
            return
        g = self.geom["g"]
        y = max(g["price"][0], min(g["price"][1], e.y))
        p, k, x = self.point(e.x, y)
        color = "#26a65b" if p >= r["p"] else "#e5534b"
        self.cv.create_rectangle(r["x"], r["y"], x, y, outline=color, dash=(3, 3), tags="ruler")
        self.cv.create_line(r["x"], r["y"], x, y, fill=color, width=1.5, arrow="last", tags="ruler")
        right = x < g["x1"] - 240
        boxed(self.cv, x + 10 if right else x - 10, y + 12 if y > r["y"] else y - 12,
              ruler_text(r["p"], p, r["k"], k, self.period), color, anchor="w" if right else "e", tags="ruler")

    def ruler_end(self, e):
        self.ruler = None
        self.cv.delete("ruler")

    def right_click(self, e):
        self.ruler = None
        hit = self.geom and L.hit_line(self.geom["segs"], e.x, e.y, 9)
        if not hit:
            if self.geom and self.data() and self.geom["g"]["price"][0] <= e.y <= self.geom["g"]["price"][1]:
                p, k, x = self.point(e.x, e.y)
                self.ruler = {"p": p, "k": k, "x": x, "y": e.y}
            return
        self.gest = None
        self.sel = hit[0]
        self.tools()
        self.redraw()
        ln = self.find(self.sel)
        if not ln:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="Wyłącz alert linii" if ln.get("alert") is not False else "Dodaj alert linii",
            command=self.toggle_line_alert,
        )
        menu.add_separator()
        menu.add_command(label="Usuń linię", command=self.delete_selected)
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def unselect(self):
        self.sel = None
        self.tools()
        self.redraw()

    def lines_json(self):
        return json.dumps(self.app.store.alerts["lines"].get(self.ticker, []), sort_keys=True)

    def push_undo(self, snap):
        st = self.undo_stack.setdefault(self.ticker, [])
        st.append(snap)
        del st[:-30]
        self.undo_btn.config(state="normal")

    def undo_line(self):
        st = self.undo_stack.get(self.ticker) or []
        if not st:
            return
        ls = json.loads(st.pop())
        if ls:
            self.app.store.alerts["lines"][self.ticker] = ls
        else:
            self.app.store.alerts["lines"].pop(self.ticker, None)
        self.sel = None
        self.app.store.save_alerts()
        self.undo_btn.config(state="normal" if st else "disabled")
        self.tools()
        self.redraw()

    def delete_selected(self):
        if not self.sel:
            return
        self.push_undo(self.lines_json())
        all_lines = self.app.store.alerts["lines"].get(self.ticker, [])
        self.app.store.alerts["lines"][self.ticker] = [x for x in all_lines if x["id"] != self.sel]
        self.sel = None
        self.save_lines()
        self.tools()
        self.redraw()

    def toggle_line_alert(self):
        ln = self.find(self.sel)
        if ln:
            ln["alert"] = ln.get("alert") is False
            self.save_lines()
            self.tools()
            self.redraw()
            if ln.get("alert") is not False and ln.get("period", "W") == "D":
                self.app.refresh_daily_alerts()

    def toggle_watch(self):
        st = self.app.store
        if self.ticker in st.alerts["watch"]:
            del st.alerts["watch"][self.ticker]
        else:
            st.alerts["watch"][self.ticker] = L.snapshot(st.row(self.ticker) or {})
        st.save_alerts()
        self.tools()

    def toggle_panel(self):
        self.show_panel = not self.show_panel
        if self.show_panel:
            self.panel.pack(side="right", fill="y", before=self.fund_btn)
        else:
            self.panel.pack_forget()
        self.app.store.settings["fund_panel"] = self.show_panel
        self.app.store.save_settings()
        self.render_panel()

    def render_panel(self):
        """Panel fundamentów: warunki, wartości raportowe i lista kontrolna."""
        r = self.app.store.row(self.ticker) or {}
        arrow = "▶" if self.show_panel else "◀"
        self.fund_btn.config(text="\n".join([arrow, ""] + list("FUNDAMENTY") + ["", arrow]), fg="#ffb020" if r.get("slow") else "#c9d1d9")
        t = self.ptext
        t.config(state="normal")
        t.delete("1.0", "end")
        for txt, tag in fund_panel_lines(
            r, self.app.store.alerts["pos"].get(self.ticker), self.plan(),
            self.app.store.settings.get("exit", "MACD"), self.app.store.settings.get("strategy_conditions"),
        ):
            t.insert("end", txt + "\n", tag)
        t.config(state="disabled")

    def guide(self):
        from .app import GuideDialog
        GuideDialog(self.app)

    def size_defaults(self):
        """Wejście, stop i opis źródła do okna wielkości pozycji: z 📌 pozycji (stop = większy z −10 % i MACD od wejścia) albo cena i Green Line / −10 %."""
        st = self.app.store
        r = st.row(self.ticker) or {}
        w = st.weekly(self.ticker) or {}
        pos = st.alerts["pos"].get(self.ticker)
        if pos and pos.get("price"):
            plan = self.plan() or {}
            stop = max((v for v in (plan.get("macd_stop"), plan.get("stop_init")) if v), default=None)
            return pos["price"], stop, "📌 pozycja: wejście z chwili kliknięcia, stop = większy z −10 % i stopu MACD od wejścia."
        last = next((x for x in reversed(w.get("c") or []) if x), None) or r.get("price")
        glb = r.get("glb")
        if last and glb and glb < last:
            return last, glb, "Bez pozycji: wejście = ostatnia cena, stop = Green Line."
        return last, last * 0.9 if last else None, "Bez pozycji: wejście = ostatnia cena, stop = −10 % (Green Line nie jest pod ceną)."

    def open_size(self):
        """💰 Wielkość: okno z kalkulatorem pozycji (kapitał w PLN, kurs USD/PLN, ryzyko, wejście, stop)."""
        if self.size_dialog and self.size_dialog.winfo_exists():
            self.size_dialog.load_defaults()
            self.size_dialog.lift()
            return
        self.size_dialog = PositionSizeDialog(self)

    def toggle_pos(self):
        st = self.app.store
        r = st.row(self.ticker) or {}
        if self.ticker in st.alerts["pos"]:
            del st.alerts["pos"][self.ticker]
        else:
            w = st.weekly(self.ticker)
            st.alerts["pos"][self.ticker] = {"since": w["d"][-1] if w and w.get("d") else "", "price": r.get("price")}
            st.alerts["watch"].setdefault(self.ticker, L.snapshot(r))   # pozycja = też alerty strategii (MACD, stop, hamowanie)
        st.save_alerts()
        self.tools()
        self.app.refresh()
        if self.size_dialog and self.size_dialog.winfo_exists():
            self.size_dialog.load_defaults()

    def tools(self):
        self.mark_period()
        self.undo_btn.config(state="normal" if self.undo_stack.get(self.ticker) else "disabled")
        held = self.ticker in self.app.store.alerts["pos"]
        self.pos_btn.config(text="📌 Mam pozycję" if held else "📌 Pozycja", bg="#1f3b5c" if held else self.del_btn.cget("bg"))
        self.exit_btn.config(text="🚪 Wyjście: pod GLB" if self.app.store.settings.get("exit", "MACD") == "GLB" else "🚪 Wyjście: MACD")
        self.render_panel()
        watched = self.ticker in self.app.store.alerts["watch"]
        self.watch_btn.config(text="🔔 Obserwujesz" if watched else "🔕 Obserwuj", bg="#1f3b5c" if watched else self.del_btn.cget("bg"))
        # Operacje na wybranej linii są dostępne z menu pod prawym przyciskiem myszy.
