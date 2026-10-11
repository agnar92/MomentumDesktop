"""Rysowanie wykresów na tk.Canvas: słupkowy tygodniowy (HLC jak w książce O'Neila) i Dar-Card (boxy Darvasa na zamknięciach).
Funkcje `draw_*` czyszczą canvas i zwracają słownik geometrii (do crosshaira i klikania w boxy)."""
import math

from . import darvas

BG, GRID, PAPER = "#0b0d10", "#1a1f26", "#161b21"
TEXT, DIM = "#c9d1d9", "#6b7684"
UP, DOWN = "#d5d9e0", "#e5484d"
SMA10, SMA40, SPX, LINE = "#e5484d", "#f0b429", "#7d8590", "#4aa3ff"
GREEN, RED, GOLD, WHITE = "#3ddc84", "#ff5c5c", "#ffd166", "#ffffff"
BOX_FILL, BOX_PLAIN = "#c9ced8", "#e6e9ef"
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


def fmt_price(v):
    return f"{v:.0f}" if abs(v) >= 1000 else f"{v:.2f}"


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
    """Okno wykresu po kliknięciu boxa: 14 tygodni przed początkiem boxa do 6 tygodni po nim."""
    i0, i1 = max(0, box["i0"] - lead), min(n_total, box["i0"] + trail + max(1, 0))
    i1 = max(i1, min(n_total, box.get("i1", box["i0"]) + 2))
    return i0, max(i1, i0 + 12)


def _scale(lo, hi, y0, y1):
    span = (hi - lo) or 1
    return lambda v: y1 - (v - lo) / span * (y1 - y0)


def _finite(seq):
    return [v for v in seq if isinstance(v, (int, float)) and math.isfinite(v)]


def _x_axis(cv, weeks, i0, i1, xf, y, W):
    last_m = None
    for i in range(i0, min(i1, len(weeks))):
        m = weeks[i][:7]
        if m != last_m and m[5:7] in ("01", "04", "07", "10"):
            cv.create_text(xf(i), y, text=m, fill=DIM, font=FONT, anchor="n")
            cv.create_line(xf(i), TOP, xf(i), y - 2, fill=GRID)
        last_m = m


def _tag(cv, x, y, text, fill, fg="#000"):
    cv.create_rectangle(x, y - 7, x + RIGHT - 8, y + 7, fill=fill, outline="")
    cv.create_text(x + 3, y, text=text, fill=fg, font=FONT, anchor="w")


# ---------- wykres słupkowy ----------

def draw_bars(cv, full, weeks, spx, win, opts=None):
    opts = opts or {}
    cv.delete("all")
    W, H = cv.winfo_width(), cv.winfo_height()
    cv.configure(bg=BG)
    if not full or W < 80 or H < 80:
        return {}
    i0, i1 = win
    n = i1 - i0 + FUTURE_SLOTS
    show_macd = opts.get("macd", True) and H > 330
    h_macd = int((H - TOP - BOTTOM) * 0.17) if show_macd else 0
    h_vol = int((H - TOP - BOTTOM) * 0.15)
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
    extra = [v for v in (opts.get("levels") or []) if v]
    lo, hi = min(ls + extra), max(hs + extra)
    sm10, sm40 = full.get("sma10") or [], full.get("sma40") or []
    pad = (hi - lo) * 0.05
    band = 0.0
    if opts.get("spx") and spx:
        band = 0.2   # S&P 500 jak w książce: cienka linia w górnym pasie wykresu, własna skala
    hi_s = hi + pad + (hi - lo + 2 * pad) * band / (1 - band) if band else hi + pad
    lo_s = lo - pad
    y = _scale(lo_s, hi_s, p_top, p_bot)
    # siatka + oś ceny
    for t in nice_ticks(lo_s, hi + pad, max(4, (p_bot - p_top) // 38)):   # podziałka tylko w zakresie cen (nie w pasie S&P)
        yy = y(t)
        cv.create_line(LEFT, yy, W - RIGHT, yy, fill=GRID)
        cv.create_text(W - RIGHT + 4, yy, text=fmt_price(t), fill=DIM, font=FONT, anchor="w")
    _x_axis(cv, weeks, i0, i1, xf, H - BOTTOM + 3, W)
    # S&P 500
    if band:
        sv = _finite(seg(spx))
        if sv:
            s_lo, s_hi = min(sv), max(sv)
            ys = _scale(s_lo, s_hi, p_top + 2, p_top + (p_bot - p_top) * band - 6)
            pts = [(xf(i), ys(spx[i])) for i in range(i0, min(i1, len(spx))) if spx[i] is not None]
            if len(pts) > 1:
                cv.create_line(*[v for p in pts for v in p], fill=SPX)
                cv.create_text(LEFT + 4, p_top + 2, text=f"S&P 500 {spx[min(i1, len(spx)) - 1]:.0f}", fill=SPX, font=FONT, anchor="nw")
    # boxy (tło: biały box + szara strefa zagrożenia)
    for b in opts.get("boxes") or []:
        x0, x1 = xf(max(b["i0"], i0)) - step / 2, (W - RIGHT if b.get("extend") else xf(min(b["i1"], i1 - 1)) + step / 2)
        if x1 > x0:
            cv.create_rectangle(x0, y(b["top"]), x1, y(b["bottom"]), fill="#ffffff", stipple="gray12", outline=b.get("color", "#8892a0"), dash=(3, 3))
            zb = b["bottom"] * (1 - darvas.STOP_PCT / 100)
            cv.create_rectangle(x0, y(b["bottom"]), x1, y(zb), fill="#ffffff", stipple="gray25", outline="")
    # średnie
    for arr, col in ((sm10, SMA10), (sm40, SMA40)):
        pts = [(xf(i), y(arr[i])) for i in range(i0, min(i1, len(arr))) if arr[i] is not None and lo_s <= arr[i] <= hi_s]
        if len(pts) > 1:
            cv.create_line(*[v for p in pts for v in p], fill=col, width=1)
    # słupki HLC (zamknięcie po obu stronach, bez open)
    half = max(1.0, step * 0.32)
    vol = full.get("v") or []
    vmax = max(_finite(seg(vol)) or [1])
    yv = _scale(0, vmax * 1.05, v_top, v_bot)
    for i in range(i0, min(i1, len(c))):
        if c[i] is None or h[i] is None:
            continue
        col = DOWN if i > 0 and c[i - 1] is not None and c[i] < c[i - 1] else UP
        x = xf(i)
        cv.create_line(x, y(h[i]), x, y(lows[i]), fill=col)
        cv.create_line(x - half, y(c[i]), x + half, y(c[i]), fill=col)
        if i < len(vol) and vol[i] is not None:
            cv.create_rectangle(x - half, yv(vol[i]), x + half, v_bot, fill=col, outline="")
    cv.create_text(LEFT + 4, v_top, text="Wolumen", fill=DIM, font=FONT, anchor="nw")
    # poziomy boxa na osi ceny (wejście / dół / exit)
    for price, col in opts.get("tags") or []:
        yy = y(price)
        cv.create_line(LEFT, yy, W - RIGHT, yy, fill=col, dash=(4, 3))
        _tag(cv, W - RIGHT + 2, yy, fmt_price(price), col)
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
    # MACD
    if show_macd:
        line, sg, hist = macd(c)
        vals = _finite(seg(line) + seg(sg) + seg(hist)) or [0.0]
        m = max(abs(min(vals)), abs(max(vals))) or 1
        ym = _scale(-m, m, m_top + 2, m_bot - 2)
        cv.create_line(LEFT, ym(0), W - RIGHT, ym(0), fill=GRID, dash=(2, 3))
        for i in range(i0, min(i1, len(hist))):
            if hist[i] is not None:
                cv.create_line(xf(i), ym(0), xf(i), ym(hist[i]), fill="#2f9e5f" if hist[i] >= 0 else "#b03a3a", width=max(1, int(step * 0.5)))
        for arr, col in ((line, LINE), (sg, "#ff9f43")):
            pts = [(xf(i), ym(arr[i])) for i in range(i0, min(i1, len(arr))) if arr[i] is not None]
            if len(pts) > 1:
                cv.create_line(*[v for p in pts for v in p], fill=col)
        for i in range(max(i0, 1), min(i1, len(line))):   # czerwony ▼ przy przecięciu sygnału w dół
            if None not in (line[i], sg[i], line[i - 1], sg[i - 1]) and line[i - 1] >= sg[i - 1] and line[i] < sg[i]:
                cv.create_text(xf(i), m_top + 2, text="▼", fill=RED, font=FONT, anchor="n")
        cv.create_text(LEFT + 4, m_top, text="MACD (12, 26, 9) tygodniowy", fill=DIM, font=FONT, anchor="nw")
    return {"kind": "bars", "W": W, "H": H, "i0": i0, "i1": i1, "step": step, "xf": xf, "y": y, "p_top": p_top, "m_bot": m_bot}


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
    bx = darvas.boxes(c)
    vis = [(k, b) for k, b in enumerate(bx) if b["i1"] >= i0 and b["i0"] < i1]
    cs = _finite(c[i0:i1])
    if not cs:
        return {}
    pin = opts.get("pinned")
    lo = min(cs + [b["bottom"] * (1 - darvas.STOP_PCT / 100) for _, b in vis] + ([pin["bottom"] * 0.95] if pin else []))
    hi = max(cs + [b["top"] for _, b in vis] + ([pin["top"]] if pin else []))
    pad = (hi - lo) * 0.06
    lo, hi = lo - pad, hi + pad
    y = _scale(lo, hi, TOP, H - BOTTOM)
    cv.create_rectangle(LEFT, TOP, W - RIGHT, H - BOTTOM, fill=PAPER, outline=GRID)
    ticks = nice_ticks(lo, hi, max(6, (H - TOP - BOTTOM) // 14))   # gęste linie jak na kartce w linie
    for k, t in enumerate(ticks):
        cv.create_line(LEFT, y(t), W - RIGHT, y(t), fill=GRID)
    for t in nice_ticks(lo, hi, max(4, (H - TOP - BOTTOM) // 36)):
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
        x1 = xf(min(b["i1"], i1 - 1)) + step / 2
        if b["outcome"] == "open":
            x1 = W - RIGHT
        yt, yb, yz = y(b["top"]), y(b["bottom"]), y(b["bottom"] * (1 - darvas.STOP_PCT / 100))
        bad = b["outcome"] == "down"
        cv.create_rectangle(x0, yb, x1, yz, fill=WHITE, stipple="gray25", outline="")   # strefa zagrożenia 5 % pod dołem
        cv.create_rectangle(x0, yt, x1, yb, fill="#7a2f2f" if bad else (BOX_PLAIN if b["confirmed"] else BOX_FILL),
                            outline=RED if bad else DIM, dash=() if b["confirmed"] else (3, 2))
        hits.append({"rect": (x0, yt, x1, yz), "box": {"top": b["top"], "bottom": b["bottom"], "i0": b["i0"], "i1": b["i1"], "kind": "darvas",
                                                       "outcome": b["outcome"], "start": weeks[b["i0"]] if b["i0"] < len(weeks) else ""}})
    if pin:   # przypięty (monitorowany) box — kontur w kolorze statusu od początku do prawej krawędzi
        st = darvas.pin_status(pin, c[last_idx(c)] if last_idx(c) >= 0 else None)
        col = {"ABOVE": GREEN, "INSIDE": GOLD, "ZONE": RED, "EXIT": RED}.get(st["state"], GOLD)
        start = next((i for i, w in enumerate(weeks) if w >= pin.get("start", "")), i0) if pin.get("start") else i0
        x0, x1 = xf(max(start, i0)) - step / 2, W - RIGHT
        cv.create_rectangle(x0, y(pin["top"]), x1, y(pin["bottom"]), outline=col, width=2, dash=(5, 3))
        cv.create_rectangle(x0, y(pin["bottom"]), x1, y(pin["bottom"] * (1 - darvas.STOP_PCT / 100)), fill=WHITE, stipple="gray25", outline=col)
        cv.create_text(x0 + 4, y(pin["top"]) + 3, text=f"📌 {st['text']}", fill=col, font=FONT, anchor="nw")
        hits.append({"rect": (x0, y(pin["top"]), x1, y(pin["bottom"] * 0.95)), "box": {"top": pin["top"], "bottom": pin["bottom"], "i0": start,
                                                                                    "i1": last_idx(c), "kind": "pinned", "outcome": "open", "start": pin.get("start", "")}})
    # ostatnia cena
    li = last_idx(c)
    if i0 <= li < i1:
        x, yy = xf(li), y(c[li])
        cv.create_oval(x - 5, yy - 5, x + 5, yy + 5, fill=LINE, outline=WHITE, width=2)
        _tag(cv, W - RIGHT + 2, yy, fmt_price(c[li]), LINE, "#fff")
    # zaznaczony box: trzy poziomy z cenami na osi
    sel = opts.get("selected")
    if sel is not None and 0 <= sel < len(hits):
        b = hits[sel]["box"]
        x0, y0, x1, y1 = hits[sel]["rect"]
        cv.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, outline=GOLD, width=2, dash=(4, 2))
        for price, col in ((b["top"], GREEN), (b["bottom"], WHITE), (b["bottom"] * (1 - darvas.STOP_PCT / 100), RED)):
            cv.create_line(LEFT, y(price), W - RIGHT, y(price), fill=col, width=2)
            _tag(cv, W - RIGHT + 2, y(price), fmt_price(price), col)
    return {"kind": "darcard", "W": W, "H": H, "i0": i0, "i1": i1, "step": step, "xf": xf, "y": y, "hits": hits, "p_top": TOP, "m_bot": H - BOTTOM}


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
