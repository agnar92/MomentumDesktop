"""Rysowanie wykresów na tk.Canvas: słupkowy tygodniowy (HLC jak w książce O'Neila) i Dar-Card (boxy Darvasa na zamknięciach).
Funkcje `draw_*` czyszczą canvas i zwracają słownik geometrii (do crosshaira i klikania w boxy)."""
import math
from tkinter import font as tkfont

from . import darvas
from . import glb as glb_mod
from .daily import sma as _sma

BG, GRID, PAPER = "#0b0d10", "#1a1f26", "#161b21"
TEXT, DIM = "#c9d1d9", "#6b7684"
UP, DOWN = "#d5d9e0", "#e5484d"
SMA10, SMA40, SPX, LINE = "#e5484d", "#f0b429", "#7d8590", "#4aa3ff"
SMA_COLORS = {10: SMA10, 40: SMA40, 50: SMA40, 200: "#e6e9ef"}
GREEN, RED, GOLD, WHITE = "#3ddc84", "#ff5c5c", "#ffd166", "#ffffff"
PIN_COLOR = "#c58bff"   # poziomy przypiętego boxa / linii na słupkowym: jeden fioletowy kolor, żeby nie mylić ich z zaznaczonym boxem (zielony / biały / czerwony)
BOX_FILL, BOX_PLAIN = "#c9ced8", "#e6e9ef"
TOPLINE = GREEN   # przerywana linia samego topu (bez potwierdzonego dołu) — zielona, bo niebieski to linia zamknięć
FONT = ("Consolas", 9)

LEFT, RIGHT, TOP, BOTTOM = 6, 62, 8, 18
FUTURE_SLOTS = 3


# ---------- czyste funkcje (testowane bez GUI) ----------

def nice_ticks(lo, hi, n=8):
    """Okrągłe wartości podziałki (1/2/5 × 10^k) między lo a hi."""
    if not (hi > lo):
        return [lo]
    raw = (hi - lo) / max(1, n)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    first = math.ceil(lo / step) * step
    out, v = [], first
    while v <= hi + 1e-9:
        out.append(round(v, 10))
        v += step
    return out


def make_scale(lo, hi, y0, y1, log=True):
    """Skala ceny: logarytmiczna (domyślnie) albo liniowa; wartości ≤ 0 są obcinane, żeby log nie wybuchał."""
    if log and lo > 0 and hi > lo:
        a, b = math.log(lo), math.log(hi)
        return lambda v: y1 - (math.log(max(v, lo * 0.01)) - a) / (b - a) * (y1 - y0)
    return _scale(lo, hi, y0, y1)


def inverse_scale(lo, hi, y0, y1, log=True):
    """Piksel y -> cena (odwrotność make_scale); do dodawania poziomów / alertów kliknięciem w wykres."""
    if log and lo > 0 and hi > lo:
        a, b = math.log(lo), math.log(hi)
        return lambda y: math.exp(a + (y1 - y) / (y1 - y0) * (b - a))
    return lambda y: lo + (y1 - y) / (y1 - y0) * (hi - lo)





_LOG_SETS = [(1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2, 2.2, 2.5, 2.8, 3, 3.5, 4, 4.5, 5, 5.5, 6, 7, 8, 9),
             (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8), (1, 1.5, 2, 3, 5, 7), (1, 2, 3, 5), (1, 2, 5), (1, 3), (1,)]


def price_ticks(lo, hi, n=8, log=True):
    """Podziałka osi ceny: na skali log równe ‑ procentowo okrągłe wartości (1, 1.5, 2, 3, 5, 7 × 10^k), na wąskim zakresie okrągłe liczby liniowe."""
    if not (hi > lo) or lo <= 0:
        return nice_ticks(lo, hi, n)
    if not log or hi / lo < 1.6:
        return nice_ticks(lo, hi, n)
    k0, k1 = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
    for mults in _LOG_SETS:
        vals = [round(m * 10 ** k, 10) for k in range(k0, k1 + 1) for m in mults]
        vals = [v for v in vals if lo <= v <= hi]
        if len(vals) <= n:
            return vals
    return vals[:1]


def fmt_price(v):
    return f"{v:.0f}" if abs(v) >= 1000 else f"{v:.2f}"


def fmt_macd(v):
    return f"{v:.2f}" if abs(v) >= 0.1 else f"{v:.3f}"


def fmt_vol(v):
    v = v * 1000   # charts.json trzyma wolumen w tysiącach
    return f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.0f}K"


def ema(values, n):
    """EMA zasiana średnią z pierwszych n wartości (jak w TradingView); None tam, gdzie brak danych."""
    out = [None] * len(values)
    clean = [v for v in values if v is not None]
    if len(clean) < n:
        return out
    k = 2 / (n + 1)
    start = next(i for i, v in enumerate(values) if v is not None)
    seed_i = start + n - 1
    prev = sum(values[start:seed_i + 1]) / n
    out[seed_i] = prev
    for i in range(seed_i + 1, len(values)):
        v = values[i]
        if v is None:
            continue
        prev = v * k + prev * (1 - k)
        out[i] = prev
    return out


def macd(closes, fast=12, slow=26, sig=9):
    """MACD tygodniowy (12, 26, 9): (macd, signal, histogram) — listy tej samej długości co closes."""
    ef, es = ema(closes, fast), ema(closes, slow)
    line = [a - b if a is not None and b is not None else None for a, b in zip(ef, es)]
    sg = ema(line, sig)
    hist = [a - b if a is not None and b is not None else None for a, b in zip(line, sg)]
    return line, sg, hist


def window(n_total, n_show, end=None):
    """Okno (i0, i1) o długości n_show kończące się na `end` (domyślnie: ostatni tydzień)."""
    n_show = max(12, min(n_show, n_total))
    end = n_total if end is None else max(n_show, min(end, n_total))
    return end - n_show, end


def box_focus_window(n_total, box, lead=14, trail=6):
    """Okno wykresu po kliknięciu boxa: `lead` słupków przed początkiem boxa do `trail` po nim (14 / 6 tygodni; dziennie 70 / 30 sesji)."""
    i0, i1 = max(0, box["i0"] - lead), min(n_total, box["i0"] + trail)
    i1 = max(i1, min(n_total, box.get("i1", box["i0"]) + 2))
    return i0, max(i1, i0 + 12)


def _scale(lo, hi, y0, y1):
    span = (hi - lo) or 1
    return lambda v: y1 - (v - lo) / span * (y1 - y0)


def _finite(seq):
    return [v for v in seq if isinstance(v, (int, float)) and math.isfinite(v)]


def _x_axis(cv, weeks, i0, i1, xf, y, W):
    months = {w[:7] for w in weeks[i0:i1]}
    show = {f"{m:02d}" for m in range(1, 13)} if len(months) <= 8 else {"01", "04", "07", "10"}   # krótkie okno: każdy miesiąc, długie: kwartały
    last_m = None
    for i in range(i0, min(i1, len(weeks))):
        m = weeks[i][:7]
        if m != last_m and m[5:7] in show:
            cv.create_text(xf(i), y, text=m, fill=DIM, font=FONT, anchor="n")
            cv.create_line(xf(i), TOP, xf(i), y - 2, fill=GRID)
        last_m = m


def hatch(cv, x0, y0, x1, y1, color="#8a929e", gap=7):
    """Ukośne kreski (strefa zagrożenia) wewnątrz prostokąta — zwykłe linie, bez rastra kropek."""
    h = y1 - y0
    if x1 - x0 < 2 or h < 2:
        return
    k = -h
    while k < x1 - x0:
        xa, ya, xb, yb = x0 + k, y1, x0 + k + h, y0   # od lewego dołu do prawej góry
        if xa < x0:
            ya, xa = y1 - (x0 - xa), x0
        if xb > x1:
            yb, xb = y0 + (xb - x1), x1
        if xb > xa and yb < ya + 0.1:
            cv.create_line(xa, ya, xb, yb, fill=color)
        k += gap


def _price_dot(cv, x, y, r=6):
    """Wyraźna kropka aktualnej ceny: czarna obwódka + biały pierścień + żółty środek — widoczna i na jasnym boxie, i na ciemnym tle."""
    cv.create_oval(x - r - 2, y - r - 2, x + r + 2, y + r + 2, fill="#000000", outline="")
    cv.create_oval(x - r, y - r, x + r, y + r, fill="#ffd166", outline=WHITE, width=2)


def _tag(cv, x, y, text, fill, fg="#000"):
    cv.create_rectangle(x, y - 7, x + RIGHT - 8, y + 7, fill=fill, outline="")
    cv.create_text(x + 3, y, text=text, fill=fg, font=FONT, anchor="w")


# ---------- wykres słupkowy ----------

def _glb_line(cv, y, level, x0, x1, W, right):
    """Zielona linia Wisha (Green Line): poziom z wykresu miesięcznego, przerywana zielona linia z ceną na osi."""
    yy = y(level)
    cv.create_line(x0, yy, x1, yy, fill=GREEN, width=2, dash=(8, 4))
    cv.create_text(x0 + 4, yy - 2, text=f"Green Line {fmt_price(level)}", fill=GREEN, font=FONT, anchor="sw")
    _tag(cv, W - right + 2, yy, fmt_price(level), GREEN)


def draw_bars(cv, full, weeks, spx, win, opts=None):
    opts = opts or {}
    cv.delete("all")
    W, H = cv.winfo_width(), cv.winfo_height()
    cv.configure(bg=BG)
    if not full or W < 80 or H < 80:
        return {}
    i0, i1 = win
    n = i1 - i0 + FUTURE_SLOTS
    log = opts.get("log", True)
    show_macd = opts.get("macd", True) and H > 330
    h_macd = max(86, int((H - TOP - BOTTOM) * 0.22)) if show_macd else 0
    h_vol = int((H - TOP - BOTTOM) * 0.13)
    p_top, p_bot = TOP, H - BOTTOM - h_vol - h_macd - 4
    v_top, v_bot = p_bot + 4, p_bot + 4 + h_vol
    m_top, m_bot = v_bot + 4, H - BOTTOM
    step = (W - LEFT - RIGHT) / n
    def xf(i):
        return LEFT + (i - i0 + 0.5) * step
    h, lows, c = full["h"], full["l"], full["c"]
    def seg(a):
        return a[i0:i1]
    hs, ls = _finite(seg(h)), _finite(seg(lows))
    if not hs:
        return {}
    extra = [v for v in (opts.get("levels") or []) if v] + ([opts["glb"]] if opts.get("glb") else [])
    lo, hi = min(ls + extra), max(hs + extra)
    smas = opts.get("smas") or [(full.get("sma10") or [], 10), (full.get("sma40") or [], 40)]
    band = 0.2 if opts.get("spx") and spx else 0.0   # S&P 500 jak w książce: cienka linia w górnym pasie wykresu, własna skala
    if log and lo > 0:
        pad = math.log(hi / lo) * 0.05 + 0.002   # margines w procentach, nie w dolarach
        span = math.log(hi / lo) + 2 * pad
        lo_s = math.exp(math.log(lo) - pad)
        hi_price = math.exp(math.log(hi) + pad)
        hi_s = math.exp(math.log(hi_price) + span * band / (1 - band)) if band else hi_price
    else:
        pad = (hi - lo) * 0.05
        lo_s, hi_price = lo - pad, hi + pad
        hi_s = hi_price + (hi - lo + 2 * pad) * band / (1 - band) if band else hi_price
    y = make_scale(lo_s, hi_s, p_top, p_bot, log)
    # siatka + oś ceny
    for t in price_ticks(lo_s, hi_price, max(4, (p_bot - p_top) // 38), log):   # podziałka tylko w zakresie cen (nie w pasie S&P)
        yy = y(t)
        cv.create_line(LEFT, yy, W - RIGHT, yy, fill=GRID)
        cv.create_text(W - RIGHT + 4, yy, text=fmt_price(t), fill=DIM, font=FONT, anchor="w")
    _x_axis(cv, weeks, i0, i1, xf, H - BOTTOM + 3, W)
    # S&P 500
    if band:
        sv = _finite(seg(spx))
        if sv:
            s_lo, s_hi = min(sv), max(sv)
            ys = make_scale(s_lo, s_hi, p_top + 2, p_top + (p_bot - p_top) * band - 6, log)
            pts = [(xf(i), ys(spx[i])) for i in range(i0, min(i1, len(spx))) if spx[i] is not None]
            if len(pts) > 1:
                cv.create_line(*[v for p in pts for v in p], fill=SPX)
                cv.create_text(LEFT + 4, p_top + 2, text=f"S&P 500 {spx[min(i1, len(spx)) - 1]:.0f}", fill=SPX, font=FONT, anchor="nw")
    # boxy (tło: biały box + szara strefa zagrożenia)
    for b in opts.get("boxes") or []:
        x0, x1 = xf(max(b["i0"], i0)) - step / 2, (W - RIGHT if b.get("extend") else xf(min(b["i1"], i1 - 1)) + step / 2)
        if x1 > x0:
            zb = b["bottom"] * (1 - darvas.STOP_PCT / 100)
            cv.create_rectangle(x0, y(b["bottom"]), x1, y(zb), fill="#2a1d24", outline="")   # strefa zagrożenia: spokojne, ciemnoczerwone tło
            cv.create_rectangle(x0, y(b["top"]), x1, y(b["bottom"]), fill="#243448", outline=b.get("color", "#8892a0"), width=2)   # zaznaczony box wyraźnie podświetlony
            if not b.get("confirmed", True):   # dół niepotwierdzony: czerwona przerywana linia
                cv.create_line(x0, y(b["bottom"]), x1, y(b["bottom"]), fill=RED, width=2, dash=(6, 3))
    # średnie
    for arr, n_ma in smas:
        col = SMA_COLORS.get(n_ma, SMA40)
        pts = [(xf(i), y(arr[i])) for i in range(i0, min(i1, len(arr))) if arr[i] is not None and lo_s <= arr[i] <= hi_s]
        if len(pts) > 1:
            cv.create_line(*[v for p in pts for v in p], fill=col, width=1)
    # legenda średnich (żeby było wiadomo, która linia to która)
    lx = LEFT + 4
    ly = p_top + (p_bot - p_top) * band + 6 if band else p_top + 6
    for arr, n_ma in smas:
        col = SMA_COLORS.get(n_ma, SMA40)
        label = f"SMA {n_ma}"
        cv.create_line(lx, ly + 6, lx + 16, ly + 6, fill=col, width=2)
        cv.create_text(lx + 20, ly + 6, text=label, fill=col, font=FONT, anchor="w")
        lx += 20 + 8 * len(label) + 12
    # słupki HLC (zamknięcie po obu stronach, bez open)
    half = max(1.0, step * 0.32)
    vol = full.get("v") or []
    vmax = max(_finite(seg(vol)) or [1])
    yv = _scale(0, vmax * 1.05, v_top, v_bot)
    vavg_n = 50 if opts.get("tf") == "D" else 10   # średnia wolumenu: SMA 10 tygodni / SMA 50 sesji
    vavg = _sma([x if x is not None else None for x in vol], vavg_n)
    for i in range(i0, min(i1, len(c))):
        if c[i] is None or h[i] is None:
            continue
        col = DOWN if i > 0 and c[i - 1] is not None and c[i] < c[i - 1] else UP
        x = xf(i)
        cv.create_line(x, y(h[i]), x, y(lows[i]), fill=col)
        cv.create_line(x - half, y(c[i]), x + half, y(c[i]), fill=col)
        if i < len(vol) and vol[i] is not None:
            big = i > 0 and i - 1 < len(vavg) and vavg[i - 1] and vol[i] >= darvas.BREAKOUT_VOL * vavg[i - 1]   # ≥ 1,4× poprzedniej średniej = wolumen wybicia (złota obwódka)
            cv.create_rectangle(x - half, yv(vol[i]), x + half, v_bot, fill=col, outline=GOLD if big else "")
    vpts = [(xf(i), yv(vavg[i])) for i in range(i0, min(i1, len(vavg))) if vavg[i] is not None]
    if len(vpts) > 1:
        cv.create_line(*[v for p in vpts for v in p], fill="#ff9f43", width=2)
    lastv = max((i for i in range(i0, min(i1, len(vavg))) if vavg[i] is not None), default=None)
    unit_v = "sesji" if opts.get("tf") == "D" else "tyg."
    cv.create_text(LEFT + 4, v_top, text="Wolumen   ", fill=DIM, font=FONT, anchor="nw")
    if lastv is not None:
        cv.create_text(LEFT + 74, v_top, text=f"— średnia {vavg_n} {unit_v}: {fmt_vol(vavg[lastv])}   ▯ złota obwódka = ≥ {darvas.BREAKOUT_VOL}× średniej", fill="#ff9f43", font=FONT, anchor="nw")
    # poziomy boxa na osi ceny (wejście / dół / exit)
    for price, col, *dash in opts.get("tags") or []:
        yy = y(price)
        cv.create_line(LEFT, yy, W - RIGHT, yy, fill=col, dash=dash[0] if dash else (4, 3))
        _tag(cv, W - RIGHT + 2, yy, fmt_price(price), col)
    if opts.get("glb"):
        _glb_line(cv, y, opts["glb"], LEFT, W - RIGHT, W, RIGHT)
    if opts.get("pivot"):
        yy = y(opts["pivot"])
        cv.create_line(LEFT, yy, W - RIGHT, yy, fill=WHITE, dash=(6, 4))
        cv.create_text(LEFT + 4, yy - 2, text=f"pivot {fmt_price(opts['pivot'])}", fill=WHITE, font=FONT, anchor="sw")
    # znacznik ostatniej ceny
    last = max((i for i in range(i0, min(i1, len(c))) if c[i] is not None), default=None)
    if last is not None:
        up = last == 0 or c[last - 1] is None or c[last] >= c[last - 1]
        yy = y(c[last])
        cv.create_line(LEFT, yy, W - RIGHT, yy, fill=GREEN if up else RED, dash=(1, 3))
        _tag(cv, W - RIGHT + 2, yy, fmt_price(c[last]), GREEN if up else RED)
        _price_dot(cv, xf(last), yy, 5)   # kropka na ostatnim zamknięciu (widać, gdzie cena jest względem boxa)
    # MACD (czytelny: tło panelu, 4-kolorowy histogram, grube linie, znaczniki przecięć, wartości na osi i w tytule)
    if show_macd:
        line, sg, hist = macd(c)
        vals = _finite(seg(line) + seg(sg) + seg(hist)) or [0.0]
        m = max(abs(min(vals)), abs(max(vals))) or 1
        top, bot = m_top + 16, m_bot - 3
        ym = _scale(-m, m, top, bot)
        cv.create_rectangle(LEFT, m_top - 2, W - RIGHT, m_bot, fill="#0f141a", outline=GRID)
        for v, lab in ((m, f"+{fmt_macd(m)}"), (0, "0"), (-m, f"−{fmt_macd(m)}")):
            cv.create_line(LEFT, ym(v), W - RIGHT, ym(v), fill="#2a313b" if v == 0 else GRID, dash=() if v == 0 else (2, 4))
            cv.create_text(W - RIGHT + 4, ym(v), text=lab, fill=DIM, font=FONT, anchor="w")
        bw = max(2, step * 0.62) / 2
        for i in range(i0, min(i1, len(hist))):
            hv = hist[i]
            if hv is None:
                continue
            prev = hist[i - 1] if i > 0 and hist[i - 1] is not None else hv
            rising = hv >= prev
            col = ("#2fbf71" if rising else "#1d7a49") if hv >= 0 else ("#9b3b3b" if rising else "#e5484d")   # jasny = narasta, ciemny = słabnie
            cv.create_rectangle(xf(i) - bw, ym(0), xf(i) + bw, ym(hv), fill=col, outline="")
        for arr, col in ((line, LINE), (sg, "#ff9f43")):
            pts = [(xf(i), ym(arr[i])) for i in range(i0, min(i1, len(arr))) if arr[i] is not None]
            if len(pts) > 1:
                cv.create_line(*[v for p in pts for v in p], fill=col, width=2)
        for i in range(max(i0, 1), min(i1, len(line))):   # przecięcia MACD z sygnałem: ▲ w górę (zielony), ▼ w dół (czerwony)
            if None in (line[i], sg[i], line[i - 1], sg[i - 1]):
                continue
            up = line[i - 1] <= sg[i - 1] and line[i] > sg[i]
            down = line[i - 1] >= sg[i - 1] and line[i] < sg[i]
            if up or down:
                x, yy = xf(i), ym(line[i])
                d = -9 if up else 9
                cv.create_polygon(x, yy + d, x - 5, yy + d * 1.9, x + 5, yy + d * 1.9, fill=GREEN if up else RED, outline="")
        li = max((i for i in range(i0, min(i1, len(line))) if line[i] is not None and sg[i] is not None), default=None)
        x = LEFT + 6
        for text, col in (("MACD 12·26·9 " + ("dzienny" if opts.get("tf") == "D" else "tygodniowy") + "   ", TEXT),
                          (f"MACD {fmt_macd(line[li])}   " if li is not None else "", LINE), (f"sygnał {fmt_macd(sg[li])}   " if li is not None else "", "#ff9f43"),
                          (f"hist {hist[li]:+.2f}" if li is not None and hist[li] is not None else "", GREEN if (hist[li] or 0) >= 0 else RED)):
            if text:
                t = cv.create_text(x, m_top + 3, text=text, fill=col, font=FONT, anchor="nw")
                x = cv.bbox(t)[2]
    return {"kind": "bars", "W": W, "H": H, "i0": i0, "i1": i1, "step": step, "xf": xf, "y": y, "p_top": p_top, "p_bot": p_bot, "m_bot": m_bot, "smas": smas,
            "price_at": inverse_scale(lo_s, hi_s, p_top, p_bot, log)}


# ---------- Dar-Card ----------

def draw_darcard(cv, full, weeks, win, opts=None):
    """Zamknięcia tygodniowe jako schodkowe pudełka Darvasa na „papierze w linie”. opts: pinned (box), selected (indeks boxa)."""
    opts = opts or {}
    cv.delete("all")
    W, H = cv.winfo_width(), cv.winfo_height()
    cv.configure(bg=BG)
    if not full or W < 80 or H < 80:
        return {}
    c = full["c"]
    i0, i1 = win
    n = i1 - i0 + FUTURE_SLOTS
    step = (W - LEFT - RIGHT) / n
    def xf(i):
        return LEFT + (i - i0 + 0.5) * step
    bx = darvas.boxes(c, darvas.confirm_for(opts.get("tf")))
    vis = [(k, b) for k, b in enumerate(bx) if b.get("end", b["i1"]) >= i0 and b["i0"] < i1]
    tls = [t for t in darvas.top_lines(c, darvas.confirm_for(opts.get("tf"))) if t["i1"] >= i0 and t["i0"] < i1]
    cs = _finite(c[i0:i1])
    if not cs:
        return {}
    pin = opts.get("pinned")
    glb_level = opts.get("glb")
    lo = min(cs + [b["bottom"] * (1 - darvas.STOP_PCT / 100) for _, b in vis] + ([pin["bottom"] * 0.95] if pin else []) + ([glb_level] if glb_level else []))
    hi = max(cs + [b["top"] for _, b in vis] + [t["top"] for t in tls] + ([pin["top"]] if pin else []) + ([glb_level] if glb_level else []))
    log = opts.get("log", True)
    if log and lo > 0:
        pad = math.log(hi / lo) * 0.06 + 0.002
        lo, hi = math.exp(math.log(lo) - pad), math.exp(math.log(hi) + pad)
    else:
        pad = (hi - lo) * 0.06
        lo, hi = lo - pad, hi + pad
    y = make_scale(lo, hi, TOP, H - BOTTOM, log)
    cv.create_rectangle(LEFT, TOP, W - RIGHT, H - BOTTOM, fill=PAPER, outline=GRID)
    for t in price_ticks(lo, hi, max(6, (H - TOP - BOTTOM) // 14), log):   # gęste linie jak na kartce w linie
        cv.create_line(LEFT, y(t), W - RIGHT, y(t), fill=GRID)
    for t in price_ticks(lo, hi, max(4, (H - TOP - BOTTOM) // 36), log):
        cv.create_text(W - RIGHT + 4, y(t), text=fmt_price(t), fill=DIM, font=FONT, anchor="w")
    _x_axis(cv, weeks, i0, i1, xf, H - BOTTOM + 3, W)
    # linia zamknięć z kropkami (boxy rysowane na wierzchu, więc linia widoczna tylko poza nimi)
    pts = [(xf(i), y(c[i])) for i in range(i0, min(i1, len(c))) if c[i] is not None]
    if len(pts) > 1:
        cv.create_line(*[v for p in pts for v in p], fill=LINE, width=1)
    for x, yy in pts[:-1]:
        cv.create_oval(x - 2, yy - 2, x + 2, yy + 2, fill=LINE, outline="")
    hits = []
    for k, b in vis:
        x0 = xf(max(b["i0"], i0)) - step / 2
        x1 = xf(min(b.get("end", b["i1"]), i1 - 1)) + step / 2
        if b["outcome"] == "open":
            x1 = W - RIGHT
        yt, yb, yz = y(b["top"]), y(b["bottom"]), y(b["bottom"] * (1 - darvas.STOP_PCT / 100))
        bad = b["outcome"] == "down"
        if bad:   # odwrócony box (dół przebity bez wybicia): strefa zagrożenia jest u góry
            yz = y(b["top"] * (1 + darvas.STOP_PCT / 100))
            hatch(cv, x0, yz, x1, yt, RED)
        else:
            hatch(cv, x0, yb, x1, yz)   # strefa zagrożenia 5 % pod dołem (ukośne kreski)
        cv.create_rectangle(x0, yt, x1, yb, fill="#7a2f2f" if bad else BOX_PLAIN, outline=RED if bad else DIM)
        hits.append({"rect": (x0, min(yt, yz), x1, max(yt, yz)), "box": {"top": b["top"], "bottom": b["bottom"], "i0": b["i0"], "i1": b["i1"], "kind": "darvas",
                                                       "outcome": b["outcome"], "confirmed": b["confirmed"], "start": weeks[b["i0"]] if b["i0"] < len(weeks) else ""}})
    for t in tls:   # sam top (dół niepotwierdzony): niebieska przerywana linia aż do przebicia; klik = stop 8 % i przybliżenie
        x0 = xf(max(t["i0"], i0)) - step / 2
        x1 = W - RIGHT if t["open"] else xf(min(t["i1"], i1 - 1)) + step / 2
        yy = y(t["top"])
        cv.create_line(x0, yy, x1, yy, fill=TOPLINE, width=2, dash=(6, 4))
        stop = darvas.line_info(t["top"])["stop"]
        hits.append({"rect": (x0, yy - 5, x1, yy + 5), "box": {"top": t["top"], "bottom": stop, "i0": t["i0"], "i1": t["i1"], "kind": "topline", "line": True,
                                                              "outcome": "open" if t["open"] else "up", "confirmed": False,
                                                              "start": weeks[t["i0"]] if t["i0"] < len(weeks) else ""}})
    if pin:   # przypięty (monitorowany) box — kontur w kolorze statusu od początku do prawej krawędzi
        st = darvas.pin_status(pin, c[last_idx(c)] if last_idx(c) >= 0 else None)
        col = {"ABOVE": GREEN, "INSIDE": GOLD, "ZONE": RED, "EXIT": RED}.get(st["state"], GOLD)
        start = next((i for i, w in enumerate(weeks) if w >= pin.get("start", "")), i0) if pin.get("start") else i0
        x0, x1 = xf(max(start, i0)) - step / 2, W - RIGHT
        if pin.get("line"):   # przypięty sam top: zielona przerywana linia + czerwony stop 8 %
            yt, ys_ = y(pin["top"]), y(pin["bottom"])
            cv.create_line(x0, yt, x1, yt, fill=TOPLINE, width=2, dash=(6, 4))
            cv.create_line(x0, ys_, x1, ys_, fill=RED, width=1, dash=(3, 3))
            hits.append({"rect": (x0, yt - 5, x1, ys_ + 5), "box": {"top": pin["top"], "bottom": pin["bottom"], "i0": start, "i1": last_idx(c), "kind": "pinned", "line": True,
                                                                  "outcome": "open", "start": pin.get("start", "")}})
        else:
            cv.create_rectangle(x0, y(pin["top"]), x1, y(pin["bottom"]), outline=col, width=2, dash=(5, 3))
            hatch(cv, x0, y(pin["bottom"]), x1, y(pin["bottom"] * (1 - darvas.STOP_PCT / 100)), col)
            cv.create_text(x0 + 4, y(pin["top"]) + 3, text=f"📌 {st['text']}", fill=col, font=FONT, anchor="nw")
            hits.append({"rect": (x0, y(pin["top"]), x1, y(pin["bottom"] * 0.95)), "box": {"top": pin["top"], "bottom": pin["bottom"], "i0": start,
                                                                                        "i1": last_idx(c), "kind": "pinned", "outcome": "open", "start": pin.get("start", "")}})
    if glb_level:
        _glb_line(cv, y, glb_level, LEFT, W - RIGHT, W, RIGHT)
    # ostatnia cena
    li = last_idx(c)
    if i0 <= li < i1:
        x, yy = xf(li), y(c[li])
        cv.create_line(x, yy, W - RIGHT, yy, fill="#ffd166", dash=(2, 3))   # kropkowana prowadnica do ceny na osi
        _price_dot(cv, x, yy, 6)
        _tag(cv, W - RIGHT + 2, yy, fmt_price(c[li]), "#ffd166")
    # zaznaczony box: trzy poziomy z cenami na osi
    sel = opts.get("selected")
    if sel is not None and 0 <= sel < len(hits):
        b = hits[sel]["box"]
        x0, y0, x1, y1 = hits[sel]["rect"]
        cv.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, outline=GOLD, width=2, dash=(4, 2))
        levels = ((b["top"], TOPLINE), (b["bottom"], RED)) if b.get("line") else \
            ((b["top"], GREEN), (b["bottom"], WHITE), (b["bottom"] * (1 - darvas.STOP_PCT / 100), RED))
        for price, col in levels:
            cv.create_line(LEFT, y(price), W - RIGHT, y(price), fill=col, width=2)
            _tag(cv, W - RIGHT + 2, y(price), fmt_price(price), col)
    return {"kind": "darcard", "W": W, "H": H, "i0": i0, "i1": i1, "step": step, "xf": xf, "y": y, "hits": hits, "p_top": TOP, "m_bot": H - BOTTOM,
            "price_at": inverse_scale(lo, hi, TOP, H - BOTTOM, log)}


def last_idx(c):
    return darvas.last_real(c)


def hit_boxes(geom, x, y):
    """Indeksy boxów (w geom["hits"]) pod punktem (x, y); najmniejsze pole pierwsze (najbardziej szczegółowy box na wierzchu)."""
    found = [(i, h) for i, h in enumerate((geom or {}).get("hits", [])) if h["rect"][0] <= x <= h["rect"][2] and h["rect"][1] <= y <= h["rect"][3]]
    found.sort(key=lambda t: (t[1]["rect"][2] - t[1]["rect"][0]) * (t[1]["rect"][3] - t[1]["rect"][1]))
    return [i for i, _ in found]


def week_at(geom, x):
    """Indeks tygodnia pod współrzędną x lub None."""
    if not geom:
        return None
    i = geom["i0"] + int((x - LEFT) // geom["step"])
    return i if geom["i0"] <= i < geom["i1"] else None


# ---------- pomiar zysku (przytrzymany lewy przycisk) ----------

MEASURE_MIN_PX = 6


def measure(geom, p0, p1):
    """Pomiar między dwoma punktami wykresu (piksele): {pct, bars, price0, price1, x0, y0, x1, y1} albo None.
    Cena z osi pod kursorem (swobodnie, nie tylko zamknięcia), czas = liczba słupków (tygodni / sesji) między najbliższymi słupkami."""
    if not geom or not geom.get("price_at"):
        return None
    top, bot = geom["p_top"], geom.get("p_bot", geom["m_bot"])
    pts = []
    for x, y in (p0, p1):
        y = min(max(y, top), bot)
        i = geom["i0"] + round((x - LEFT) / geom["step"] - 0.5)
        pts.append((i, geom["xf"](i), y, geom["price_at"](y)))
    (i0, x0, y0, a), (i1, x1, y1, b) = pts
    if not a or a <= 0 or not b or b <= 0:
        return None
    return {"pct": (b / a - 1) * 100, "bars": i1 - i0, "price0": a, "price1": b, "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def draw_measure(cv, m, unit="tyg."):
    """Przerywana linia pomiaru z etykietą „+37,2 % · 8 tyg.”; wszystko pod tagiem `measure` (znika po puszczeniu przycisku)."""
    cv.delete("measure")
    col = GREEN if m["pct"] >= 0 else RED
    cv.create_line(m["x0"], m["y0"], m["x1"], m["y1"], fill=col, width=2, dash=(6, 4), tags="measure")
    for x, y in ((m["x0"], m["y0"]), (m["x1"], m["y1"])):
        cv.create_oval(x - 4, y - 4, x + 4, y + 4, fill=col, outline="#000", tags="measure")
    n = abs(m["bars"])
    text = f"{m['pct']:+.1f} %  ·  {n} {unit}\n{fmt_price(m['price0'])} → {fmt_price(m['price1'])}"
    xm, ym = (m["x0"] + m["x1"]) / 2, min(m["y0"], m["y1"]) - 10
    t = cv.create_text(xm, max(ym, 24), text=text, fill=WHITE, font=FONT, anchor="s", justify="center", tags="measure")
    bb = cv.bbox(t)
    r = cv.create_rectangle(bb[0] - 5, bb[1] - 3, bb[2] + 5, bb[3] + 3, fill="#10151b", outline=col, tags="measure")
    cv.tag_lower(r, t)


# ---------- suwak okna czasu (minimapa) ----------

MIN_WEEKS = 12


def slider_rect(total, n_show, end, width, pad=4):
    """Prostokąt ramki okna na torze suwaka (x0, x1) w pikselach."""
    w = max(1, width - 2 * pad)
    n_show = max(MIN_WEEKS, min(n_show, total))
    end = total if end is None else max(n_show, min(end, total))
    return pad + (end - n_show) / total * w, pad + end / total * w


def slider_drag(mode, start, dx, total, width, pad=4):
    """Nowe (n_show, end) po przeciągnięciu o dx px; start = (n_show, end) z chwili chwycenia.
    mode: move (przesuwa ramkę) / left (zmienia początek) / right (zmienia koniec)."""
    per = total / max(1, width - 2 * pad)   # tygodni na piksel
    n0, e0 = start
    d = round(dx * per)
    i0, i1 = e0 - n0, e0
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


def slider_mode(x, x0, x1, edge=7):
    """Co chwycono: left / right (krawędzie), move (środek ramki) albo jump (tor poza ramką)."""
    if abs(x - x0) <= edge:
        return "left"
    if abs(x - x1) <= edge:
        return "right"
    return "move" if x0 < x < x1 else "jump"


def slider_jump(x, total, n_show, width, pad=4):
    """Klik na torze poza ramką: ramka wyśrodkowana na klikniętym tygodniu -> (n_show, end)."""
    centre = (x - pad) / max(1, width - 2 * pad) * total
    end = int(round(centre + n_show / 2))
    end = max(n_show, min(total, end))
    return n_show, end


def draw_slider(cv, closes, n_show, end, unit="tyg."):
    """Minimapa cen zamknięcia całej historii + ramka bieżącego okna."""
    cv.delete("all")
    W, H = cv.winfo_width(), cv.winfo_height()
    cv.configure(bg=BG)
    vals = _finite(closes)
    if W < 40 or not vals:
        return
    total = len(closes)
    lo, hi = min(vals), max(vals)
    y = make_scale(lo, hi, 6, H - 6, True)   # minimapa też na skali log
    x0, x1 = slider_rect(total, n_show, end, W)
    cv.create_rectangle(x0, 0, x1, H, fill="#16202c", outline="")   # tło wybranego okna jaśniejsze od reszty toru
    pts = [(4 + (i + 0.5) / total * (W - 8), y(v)) for i, v in enumerate(closes) if v is not None]
    if len(pts) > 1:
        cv.create_line(*[c for p in pts for c in p], fill="#8b95a3")
    cv.create_rectangle(x0, 1, x1, H - 1, outline=LINE, width=2)
    for x in (x0, x1):   # uchwyty krawędzi
        cv.create_rectangle(x - 3, H / 2 - 9, x + 3, H / 2 + 9, fill=LINE, outline="")
    cv.create_text(x1 - 6 if x1 - x0 > 90 else x1 + 6, 4, text=f"{n_show} {unit}", fill=TEXT, font=FONT,
                   anchor="ne" if x1 - x0 > 90 else "nw")


# ---------- dymek z danymi przy kursorze ----------

def _pct(a, b):
    return None if not (_ok_num(a) and _ok_num(b)) or b == 0 else (a / b - 1) * 100


def _ok_num(v):
    return isinstance(v, (int, float)) and math.isfinite(v)


def tooltip_bars(full, dates, i, smas, tf, hover=None):
    """Linie dymku dla słupka i: [(tekst, kolor)]. hover = n średniej, nad którą jest kursor (dostaje nagłówek i opis nachylenia)."""
    c, h, lo, v = full["c"], full["h"], full["l"], full.get("v") or []
    if i < 0 or i >= len(c) or c[i] is None:
        return []
    per = 252 if tf == "D" else 52          # okno „52 tygodni”
    avg_n = 50 if tf == "D" else 10         # średnia wolumenu: 50 sesji / 10 tygodni
    unit = "sesji" if tf == "D" else "tyg."
    out = []
    if hover is not None:
        arr = next((a for a, n in smas if n == hover), None)
        val = arr[i] if arr and i < len(arr) else None
        if _ok_num(val):
            back = arr[i - 10] if i >= 10 and arr[i - 10] is not None else None
            slope = _pct(val, back)
            out.append((f"SMA {hover} ({'dzienna' if tf == 'D' else 'tygodniowa'}) = {val:.2f}", SMA_COLORS.get(hover, SMA40)))
            out.append((f"cena {_pct(c[i], val):+.1f}% {'nad' if c[i] >= val else 'pod'} średnią", TEXT))
            if slope is not None:
                out.append((f"średnia {'rośnie' if slope >= 0 else 'spada'}: {slope:+.1f}% / 10 {unit}", GREEN if slope >= 0 else RED))
            out.append(("─" * 22, DIM))
    out.append((f"{dates[i] if i < len(dates) else ''}   ({'dzień' if tf == 'D' else 'tydzień'})", WHITE))
    out.append((f"H {h[i]:.2f}   L {lo[i]:.2f}   C {c[i]:.2f}", TEXT))
    prev = c[i - 1] if i > 0 else None
    chg = _pct(c[i], prev)
    if chg is not None:
        out.append((f"zmiana {chg:+.2f}% vs poprzedni", GREEN if chg >= 0 else RED))
    if i < len(v) and v[i] is not None:
        past = [x for x in v[max(0, i - avg_n):i] if x is not None]
        ratio = v[i] / (sum(past) / len(past)) if len(past) >= 3 and sum(past) > 0 else None
        out.append((f"wolumen {fmt_vol(v[i])}" + (f"  ({ratio:.2f}× średniej {avg_n})" if ratio else ""), GOLD if ratio and ratio >= darvas.BREAKOUT_VOL else TEXT))
        if len(past) >= 3 and sum(past) > 0:
            out.append((f"średnia wolumenu SMA {avg_n}: {fmt_vol(sum(past) / len(past))}", "#ff9f43"))
    for arr, n_ma in smas:
        if i < len(arr) and _ok_num(arr[i]):
            d = _pct(c[i], arr[i])
            out.append((f"SMA {n_ma}: {arr[i]:.2f}   cena {d:+.1f}%", SMA_COLORS.get(n_ma, SMA40)))
    hi52 = max(_finite(h[max(0, i - per + 1):i + 1]) or [None], default=None)
    lo52 = min(_finite(lo[max(0, i - per + 1):i + 1]) or [None], default=None)
    if hi52 and lo52:
        out.append((f"do szczytu 52t: {_pct(c[i], hi52):+.1f}%   od dołka: {_pct(c[i], lo52):+.0f}%", DIM if _pct(c[i], hi52) < -10 else GREEN))
    line, sg, hist = macd(c)
    if i < len(line) and line[i] is not None and sg[i] is not None:
        out.append((f"MACD {fmt_macd(line[i])}  sygnał {fmt_macd(sg[i])}  hist {hist[i]:+.2f}", LINE))
    return out


def tooltip_card(full, dates, i, tf):
    """Dymek na Dar-Card: zamknięcie, zmiana oraz odległość do góry / dołu / exitu boxa, w którym albo najbliżej którego jesteśmy."""
    c = full["c"]
    if i < 0 or i >= len(c) or c[i] is None:
        return []
    out = [(f"{dates[i] if i < len(dates) else ''}   ({'dzień' if tf == 'D' else 'tydzień'})", WHITE), (f"zamknięcie {c[i]:.2f}", TEXT)]
    chg = _pct(c[i], c[i - 1] if i > 0 else None)
    if chg is not None:
        out.append((f"zmiana {chg:+.2f}% vs poprzedni", GREEN if chg >= 0 else RED))
    boxes = [b for b in darvas.boxes(c, darvas.confirm_for(tf)) if b["i0"] <= i]
    if boxes:
        # box obowiązujący w tym tygodniu: zaczął się przed i, a nie skończył (otwarty) albo kończy się dopiero w i lub później
        active = [b for b in boxes if b["outcome"] == "open" or b.get("end", b["i1"]) >= i]
        broke = [x for x in active if x["outcome"] == "down" and x["i1"] == i]   # w tygodniu złamania pokazujemy złamany box (nowy box zaczyna się w tym samym tygodniu)
        b = (broke or active or boxes)[-1]
        stop = b["bottom"] * (1 - darvas.STOP_PCT / 100)
        out.append(("─" * 22, DIM))
        head = f"box {b['bottom']:.2f}–{b['top']:.2f}"
        if b["outcome"] == "down" and i >= b["i1"]:
            out.append((f"{head} — złamany w dół (stop)", RED))
            out.append((f"exit/stop ({stop:.2f}): {_pct(stop, c[i]):+.1f}% od zamknięcia", RED))
            out.append((f"od dołu boxa: {_pct(c[i], b['bottom']):+.1f}%", TEXT))
        elif b["outcome"] == "up" and i >= b["i1"]:
            out.append((f"{head} — wybity w górę", GREEN))
            out.append((f"nad górą boxa: {_pct(c[i], b['top']):+.1f}%", GREEN))
            out.append((f"do exitu ({stop:.2f}): {_pct(stop, c[i]):+.1f}%", RED))
        else:
            state = "w boxie" if b["bottom"] <= c[i] <= b["top"] else "nad boxem" if c[i] > b["top"] else "pod boxem"
            out.append((f"{head} ({state}, czeka na wybicie)" if b["outcome"] == "open" else f"{head} ({state})", WHITE))
            out.append((f"do wybicia (góra): {_pct(b['top'], c[i]):+.1f}%", GREEN))
            out.append((f"od dołu boxa: {_pct(c[i], b['bottom']):+.1f}%", TEXT))
            out.append((f"do exitu ({stop:.2f}): {_pct(stop, c[i]):+.1f}%", RED))
    return out


def draw_tooltip(cv, x, y, lines, tag="cross"):
    """Dymek przypięty do kursora z prawej strony (przeskakuje na lewą, gdy brakuje miejsca)."""
    if not lines:
        return
    W, H = cv.winfo_width(), cv.winfo_height()
    items = [cv.create_text(0, 0, text=t, fill=col, font=FONT, anchor="nw") for t, col in lines]
    lh = tkfont.Font(font=FONT).metrics("linespace") + 3   # wysokość wiersza z metryki czcionki (Windows / skalowanie DPI)
    wd = max(cv.bbox(i)[2] - cv.bbox(i)[0] for i in items) + 14
    ht = lh * len(lines) + 10
    bx = x + 18 if x + 18 + wd < W - 4 else x - 18 - wd
    by = max(4, min(y + 12, H - ht - 4))
    box = cv.create_rectangle(bx, by, bx + wd, by + ht, fill="#10151b", outline="#3a4350")
    cv.addtag_withtag(tag, box)
    for n, item in enumerate(items):
        cv.coords(item, bx + 7, by + 5 + n * lh)
        cv.addtag_withtag(tag, item)
        cv.tag_raise(item, box)


# ---------- oficjalna karta Darvasa i karta GLB (jak w książce / Momentum: darCardSvg, glbCardSvg) ----------

CARD_PAPER, CARD_RULE, CARD_TICK, CARD_INK = "#e9e4d2", "#b9b49f", "#8b8670", "#2b2a24"
CARD_FONT, CARD_FONT_B = ("Consolas", 9), ("Consolas", 9, "bold")
STATE_LINE = {"BUY": ("#0a8f3c", "Kup — wybicie"), "SELL": ("#c0262d", "Sprzedaj"), "HOLD": ("#1b5fbf", "Trzymaj"),
              "READY": ("#0a8f3c", "Gotowy do kupna"), "NOVOL": ("#1b5fbf", "Wybicie bez wolumenu"), "LATE": ("#1b5fbf", "Za daleko nad górą")}


def _card_paper(cv, W, H, L, lo, hi, title):
    """Kartka w linie (skala log), oś cen po lewej i tytuł w lewym górnym rogu."""
    cv.create_rectangle(0, 0, W, H, fill=CARD_PAPER, outline="")
    y = make_scale(lo, hi, L["top"], H - L["bottom"], True)
    q = math.exp(math.log(hi / lo) / 70)
    v = lo * q
    while v < hi:
        cv.create_line(L["left"], y(v), W - L["right"], y(v), fill=CARD_RULE)
        v *= q
    for t in price_ticks(lo, hi, 8, True):
        cv.create_line(L["left"], y(t), W - L["right"], y(t), fill=CARD_TICK)
        cv.create_text(L["left"] - 4, y(t), text=f"{t:g}", fill="#3a3730", font=CARD_FONT, anchor="e")
    cv.create_text(L["left"] + 2, 22, text=title, fill="#1b1a16", font=("Georgia", 22, "bold"), anchor="w")
    return y


def _card_dot(cv, x, y, px, W):
    cv.create_oval(x - 6, y - 6, x + 6, y + 6, fill="#ffd54a", outline="#111", width=2)
    left = x > W * 0.6
    cv.create_text(x - 10 if left else x + 10, y, text=f"{px:.2f}", fill=CARD_INK, font=CARD_FONT_B, anchor="e" if left else "w")


def draw_card(cv, full, weeks, opts=None):
    """Karta Darvasa jak w książce: boxy z ostatnich 2 lat OBOK SIEBIE od najstarszego (nie w skali czasu), biały box z czarną ramką
    i pasek strefy zagrożenia pod dołem, linia punktu kupna tuż nad najwyższym boxem, kolejne rosnące boxy podpisane ↑1, ↑2…,
    żółta kropka = ostatnie zamknięcie, u dołu spółka, okno dat i „Past Price Range”. opts: pinned, selected, title."""
    opts = opts or {}
    cv.delete("all")
    W, H = cv.winfo_width(), cv.winfo_height()
    if not full or W < 120 or H < 160:
        return {}
    c = full["c"]
    a = darvas.card(c, full.get("v"), full.get("l"))
    lr = darvas.last_real(c)
    if not a["boxes"] or lr < 0:
        cv.create_rectangle(0, 0, W, H, fill=CARD_PAPER, outline="")
        cv.create_text(20, 30, text="Brak boxów do narysowania na karcie Darvasa.", fill=CARD_INK, font=CARD_FONT, anchor="w")
        return {"kind": "kcard", "hits": []}
    px, st = c[lr], a["status"]
    rng = darvas.past_range(weeks, c)
    table_h = 14 * (len(rng) + 4) + 10
    L = {"left": 48, "right": 8, "top": 44, "bottom": table_h + 30}
    bxs = a["boxes"]
    lo0 = min([px] + [b["bottom"] * (1 - darvas.STOP_PCT / 100) for b in bxs])
    hi0 = max([px] + [b["top"] for b in bxs])
    span = math.log(hi0 / lo0) or 0.1
    lo, hi = lo0 * math.exp(-0.3 * span), hi0 * math.exp(0.3 * span)   # luźna skala jak w książce
    y = _card_paper(cv, W, H, L, lo, hi, "Dar•Card©")
    pw = W - L["left"] - L["right"]
    n = len(bxs)
    slot = pw / max(n, 3)
    bw = slot * 0.72
    pin = opts.get("pinned")
    hits = []
    for k, b in enumerate(bxs):
        x0 = L["left"] + slot * k + (slot - bw) / 2
        yt, yb, yz = y(b["top"]), y(b["bottom"]), y(b["bottom"] * (1 - darvas.STOP_PCT / 100))
        pinned = bool(pin and not pin.get("line") and abs(pin["top"] - b["top"]) < 0.005 and abs(pin["bottom"] - b["bottom"]) < 0.005)
        cv.create_rectangle(x0, yt, x0 + bw, max(yb, yt + 2), fill="#ffffff", outline="#d4a017" if pinned else "#111", width=3 if pinned else 2)
        hatch(cv, x0, yb, x0 + bw, yb + max(2, min(yz - yb, 9)), "#333333", gap=4)
        cv.create_rectangle(x0, yb, x0 + bw, yb + max(2, min(yz - yb, 9)), outline="#333")
        if b.get("rank"):   # kolejne rosnące boxy (łańcuch) — ↑1, ↑2… nad boxem
            cv.create_text(x0 + 4, yt + 3, text=f"↑{b['rank']}", fill="#0a8f3c", font=("Consolas", 10, "bold"), anchor="nw")
        if pinned:
            cv.create_text(x0 + bw - 3, yt + 10, text="📌", anchor="e")
        hits.append({"rect": (x0, yt, x0 + bw, yb + 9), "box": {"top": b["top"], "bottom": b["bottom"], "i0": b["i0"], "i1": b["i1"], "kind": "darvas",
                                                               "outcome": b["outcome"], "confirmed": True, "start": weeks[b["i0"]] if b["i0"] < len(weeks) else ""}})
        if k == a["topmost"] and st["state"] not in ("OUT", "NONE", "WAIT"):
            col, lbl = STATE_LINE.get(st["state"], ("#1b5fbf", "Kup nad górą"))
            yb_ = y(b["top"] * 1.007)
            cv.create_line(x0 + bw / 2, yb_, W - L["right"], yb_, fill=col, width=2)
            cv.create_oval(x0 + bw / 2 - 3, yb_ - 3, x0 + bw / 2 + 3, yb_ + 3, fill=col, outline="")
            cv.create_text(W - L["right"] - 2, yb_ - 8, text=lbl, fill=col, font=("Consolas", 10, "bold"), anchor="e")
        elif k == a["topmost"] and st["state"] == "WAIT":
            yb_ = y(b["top"] * 1.007)
            cv.create_line(x0 + bw / 2, yb_, W - L["right"], yb_, fill="#1b5fbf", width=1, dash=(4, 3))
            cv.create_text(W - L["right"] - 2, yb_ - 8, text="Kup nad górą (pierwszy box)", fill="#1b5fbf", font=CARD_FONT_B, anchor="e")
    _card_dot(cv, L["left"] + slot * (n - 1) + slot / 2, y(px), px, W)
    head = {"READY": "dwa rosnące boxy — gotowy do kupna", "BUY": "wybicie", "HOLD": "trzymaj", "SELL": "sprzedaj", "OUT": "poza boxem",
            "WAIT": "pierwszy box — czekaj", "NOVOL": "wybicie bez wolumenu", "LATE": "za daleko nad górą"}.get(st["state"], "")
    cv.create_text(W - L["right"] - 2, 22, text=f"Boxy ↑ {a['n_up']}  ·  {head}", fill=CARD_INK, font=("Consolas", 11, "bold"), anchor="e")
    # dół karty: spółka, okno dat, Past Price Range
    ty, tx = H - table_h - 4, L["left"] + 6
    d_end = weeks[lr] if lr < len(weeks) else ""
    d_beg = weeks[max(0, lr - darvas.CARD_WEEKS + 1)] if weeks else ""
    cv.create_text(tx, ty - 6, text=opts.get("title", ""), fill=CARD_INK, font=("Consolas", 10, "bold"), anchor="w")
    cv.create_text(tx, ty + 10, text=f"{d_beg} – {d_end}" if d_beg and d_end else "", fill=CARD_INK, font=CARD_FONT_B, anchor="w")
    ry = ty + 28
    cv.create_text(tx, ry, text="Past Price Range", fill=CARD_INK, font=CARD_FONT_B, anchor="w")
    cv.create_text(tx + 80, ry + 14, text="High", fill=CARD_INK, font=CARD_FONT, anchor="w")
    cv.create_text(tx + 150, ry + 14, text="Low", fill=CARD_INK, font=CARD_FONT, anchor="w")
    for i, (yr, h_, l_) in enumerate(rng):
        yy = ry + 14 * (i + 2)
        cv.create_text(tx, yy, text=yr, fill=CARD_INK, font=CARD_FONT, anchor="w")
        cv.create_text(tx + 80, yy, text=f"{h_:g}", fill=CARD_INK, font=CARD_FONT, anchor="w")
        cv.create_text(tx + 150, yy, text=f"{l_:g}", fill=CARD_INK, font=CARD_FONT, anchor="w")
    sel = opts.get("selected")
    if sel is not None and 0 <= sel < len(hits):
        x0, y0, x1, y1 = hits[sel]["rect"]
        cv.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y1 + 2, outline="#d4a017", width=2, dash=(4, 2))
    return {"kind": "kcard", "W": W, "H": H, "hits": hits, "status": st, "n_up": a["n_up"]}


GLB_COLORS = {"BREAK": "#0a8f3c", "AFTER": "#5c7a3a", "LATE": "#5c7a3a", "WAIT": "#0f8a3a"}


def draw_glb_card(cv, g, opts=None):
    """Karta GLB jak w Momentum: zamknięcia miesięczne (krótka kreska na miesiąc + cienka linia), gruba zielona green line od miesiąca rekordu
    do przebicia (dalej przerywana), stan w prawym górnym rogu, żółta kropka = cena, u dołu tabelka Rekord / Green line / Stop / Do linii."""
    opts = opts or {}
    cv.delete("all")
    W, H = cv.winfo_width(), cv.winfo_height()
    if W < 120 or H < 160:
        return {}
    if not g or not g.get("c"):
        cv.create_rectangle(0, 0, W, H, fill=CARD_PAPER, outline="")
        cv.create_text(20, 30, text="Brak danych miesięcznych do karty GLB.", fill=CARD_INK, font=CARD_FONT, anchor="w")
        return {"kind": "glb", "hits": []}
    table_h = 14 * 6 + 10
    L = {"left": 48, "right": 8, "top": 44, "bottom": table_h + 46}
    cs, px, lv = g["c"], g["px"], g.get("line")
    vals = [v for v in cs if v] + [px] + ([lv * 1.02, lv * (1 - glb_mod.STOP_PCT / 100)] if lv else [])
    lo0, hi0 = min(vals), max(vals)
    span = math.log(hi0 / lo0) or 0.1
    lo, hi = lo0 * math.exp(-0.12 * span), hi0 * math.exp(0.12 * span)
    y = _card_paper(cv, W, H, L, lo, hi, "GLB•Card")
    n = len(cs)
    pw, ph = W - L["left"] - L["right"], H - L["top"] - L["bottom"]
    slot = pw / (n + 1)
    def x(i):
        return L["left"] + slot * (i + 0.5)
    for i, m in enumerate(g["m"]):   # lata pod osią: przerywana kreska na styczniu
        if m.endswith("-01"):
            cv.create_line(x(i) - slot / 2, L["top"], x(i) - slot / 2, L["top"] + ph, fill="#a9a48e", dash=(2, 3))
            cv.create_text(x(i) - slot / 2 + 3, L["top"] + ph + 10, text=m[:4], fill="#3a3730", font=CARD_FONT, anchor="w")
    state = g.get("glb_state", "NONE")
    col = GLB_COLORS.get(state, "#0f8a3a")
    if lv:
        lm = g.get("lm")
        in_card = lm is not None and lm >= 0
        i_r = lm if in_card else 0
        i_b = next((i for i in range(i_r + 1, n) if cs[i] >= lv), n)
        yt = y(lv)
        xe = x(i_b) - slot * 0.5 if i_b < n else W - L["right"]
        cv.create_line(x(i_r) if in_card else L["left"], yt, xe, yt, fill=col, width=3)
        if i_b < n:   # przebita: obowiązuje do potwierdzenia nowego rekordu
            cv.create_line(xe, yt, W - L["right"], yt, fill=col, width=2, dash=(6, 4))
        if in_card:
            cv.create_oval(x(i_r) - 4, yt - 4, x(i_r) + 4, yt + 4, fill=col, outline="#111")
        else:
            cv.create_text(L["left"] + 4, yt - 8, text=f"rekord z {g.get('lm_label') or '?'} (poza kartą)", fill=CARD_INK, font=CARD_FONT, anchor="w")
        lbl = {"WAIT": f"Kup > {lv:.2f}", "BREAK": "Kup — wybicie", "AFTER": "Nad green line (≤ 5 %)", "LATE": "Za daleko nad linią"}.get(state, "")
        cv.create_text(W - L["right"] - 2, 22, text=lbl, fill=col, font=("Consolas", 12, "bold"), anchor="e")
    pts = [v for i, v in enumerate(cs) for v in (x(i), y(v))]
    if len(pts) >= 4:
        cv.create_line(*pts, fill="#8a8574")
    for i, v in enumerate(cs):
        partial = g.get("partial") and i == n - 1
        cv.create_line(x(i) - slot * 0.32, y(v), x(i) + slot * 0.32, y(v), fill="#111", width=1 if partial else 2, dash=(2, 2) if partial else ())
    _card_dot(cv, x(n - 1), y(px), px, W)
    ty, tx = H - table_h - 4, L["left"] + 6
    cv.create_text(tx, ty - 6, text=opts.get("title", ""), fill=CARD_INK, font=("Consolas", 10, "bold"), anchor="w")
    cv.create_text(tx, ty + 10, text=f"{g['m'][0]} – {g['m'][-1]} · zamknięcia miesięczne", fill=CARD_INK, font=CARD_FONT_B, anchor="w")
    ath = g.get("ath")
    rows = [("Rekord wszech czasów", f"{ath[0]:.2f} ({ath[1]})" + ("" if g.get("full") else " ¹") if ath else "—"),
            ("Green line", f"{lv:.2f} ({g.get('lm_label')})" if lv else "brak (rekord < 3 mies.)"),
            ("Stop (1 % pod linią)", f"{lv * (1 - glb_mod.STOP_PCT / 100):.2f}" if lv else "—"),
            ("Do linii", f"{g['glb_dist_pct']:+.1f} %" if lv and g.get("glb_dist_pct") is not None else "—")]
    for i, (k, v) in enumerate(rows):
        yy = ty + 30 + 14 * i
        cv.create_text(tx, yy, text=k, fill=CARD_INK, font=CARD_FONT, anchor="w")
        cv.create_text(tx + 190, yy, text=v, fill=CARD_INK, font=CARD_FONT_B, anchor="w")
    if not g.get("full"):
        cv.create_text(tx, ty + 30 + 14 * 4, text="¹ z ostatnich lat tygodniowych — pełna historia miesięczna po Sync skanu Wish", fill="#5a564a", font=("Consolas", 8), anchor="w")
    return {"kind": "glb", "hits": []}
