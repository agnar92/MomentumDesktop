"""Obliczenia (czyste funkcje, bez sieci i GUI): Green Line z miesięcznych High (jak w oryginale Dr. Wisha), stan GLB na zamknięciu tygodnia, MACD tygodniowy,
średnie, obrót i warunki strategii z backtestu (płynny rynek USA 2015–2026):
  - obrót dzienny ≥ 50 mln $, przychody kw. ≥ +15 % r/r, marża operacyjna ≥ +3 pp r/r (z SEC),
  - wejście: zamknięcie tygodnia 0–10 % nad Green Line (rekord wszech czasów miesięcznego High, który stoi ≥ 3 zamknięte miesiące),
  - wyjście: tygodniowy MACD (12, 26, 9) — stop pod Low tygodnia, w którym MACD przeciął sygnał w dół, plus stop 10 % pod wejściem.
Heurystyka z backtestu, nie porada inwestycyjna."""
import math

CONFIRM_MONTHS = 3      # rekord musi stać co najmniej tyle zamkniętych miesięcy
ENTRY_MAX_PCT = 10.0    # wejście do 10 % nad linią
MIN_TURNOVER = 50e6     # obrót dzienny ($)
MIN_REV_GROWTH = 15.0   # przychody kw. r/r (%)
MIN_DOPM = 3.0          # zmiana marży operacyjnej r/r (pp)
STOP_PCT = 10.0         # stop początkowy pod wejściem
# Potencjał (badanie 2021–2026 na cenach bez korekty: wybicia z konsolidacji po +30–100 %, szansa na dalsze ≥ +100 % w 12 mies.; bez warunków 5,1 %).
# Tylko cechy, które rzeczywiście podnosiły szansę; przyspieszenie przychodów, EPS, marża brutto (poziom), marża oper. > 0, ROE, RS — bez wpływu.
POTENTIAL = (  # (klucz, opis, szansa na dalsze ≥ +100 % gdy spełnione)
    ("rev25", "przychody ≥ +25 % r/r", 7.9),
    ("rev25x2", "przychody ≥ +25 % r/r dwa kwartały z rzędu", 8.9),
    ("dopm3x2", "marża oper. ↑ ≥ +3 pp dwa kwartały z rzędu", 8.9),
    ("dgm2", "marża brutto ↑ ≥ +2 pp r/r", 8.0),
    ("lowopm", "marża oper. < 10 % (dźwignia operacyjna na starcie)", 8.6),
)
SLOW_ACCEL = -10.0      # hamowanie: tempo przychodów spadło o ≥ 10 pp względem kwartału wcześniej (cena 3 mies. −0,5 % vs +2,1 %, spadek ≥ 20 %: 44 % vs 33 %)


def _ok(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def green_line(months, confirm=CONFIRM_MONTHS):
    """months = High ZAMKNIĘTYCH miesięcy (od najstarszego). -> (poziom, indeks miesiąca rekordu) albo (None, None).
    Rekord wszech czasów jest linią, gdy stoi ≥ `confirm` miesięcy; nowszy rekord zastępuje ją dopiero po swoich `confirm` miesiącach."""
    level = at = None
    mx, mi = -math.inf, None
    for i, c in enumerate(months):
        if not _ok(c):
            continue
        if c > mx:
            mx, mi = c, i
        if i - mi >= confirm:
            level, at = mx, mi
    return level, at


def green_line_series(months, confirm=CONFIRM_MONTHS):
    """Green Line obowiązująca w każdym miesiącu: wartość i = linia z miesięcy zamkniętych przed miesiącem i (wykres miesięczny)."""
    out, level, mx, mi = [None], None, -math.inf, None
    for i, c in enumerate(months):
        if _ok(c) and c > mx:
            mx, mi = c, i
        if mi is not None and i - mi >= confirm:
            level = mx
        out.append(level)
    return out[:len(months)]


def glb_state(price, prev, level, max_pct=ENTRY_MAX_PCT):
    """Stan na zamknięciu tygodnia: SYGNAŁ (0–max_pct % nad linią; „WYBICIE”, gdy poprzedni tydzień był pod nią), NAD (dalej), POD, BRAK."""
    if not (_ok(price) and _ok(level) and level > 0):
        return "BRAK"
    if price < level:
        return "POD"
    if price > level * (1 + max_pct / 100):
        return "NAD"
    return "WYBICIE" if _ok(prev) and prev < level else "SYGNAŁ"


def sma(values, n):
    out, s, q = [], 0.0, []
    for v in values:
        q.append(v)
        s += v
        if len(q) > n:
            s -= q.pop(0)
        out.append(s / n if len(q) == n else None)
    return out


def ema(values, n):
    k, out, prev = 2 / (n + 1), [], None
    for v in values:
        prev = v if prev is None else prev + k * (v - prev)
        out.append(prev)
    return out


def macd(closes, fast=12, slow=26, sig=9):
    """-> (macd, sygnał, histogram) — listy tej samej długości co closes."""
    m = [a - b for a, b in zip(ema(closes, fast), ema(closes, slow))]
    s = ema(m, sig)
    return m, s, [a - b for a, b in zip(m, s)]


def macd_cross_down(hist):
    """Indeksy tygodni, w których histogram przeszedł z ≥ 0 na < 0 (MACD przeciął sygnał w dół)."""
    return [i for i in range(1, len(hist)) if hist[i] < 0 <= hist[i - 1]]


def macd_info(closes, lows):
    """-> {state: 'nad' / 'pod', stop: Low ostatniego tygodnia przecięcia w dół (albo None), cross_i}."""
    if len(closes) < 35:
        return {"state": None, "stop": None, "cross_i": None}
    _, _, h = macd(closes)
    crosses = macd_cross_down(h)
    i = crosses[-1] if crosses else None
    return {"state": "nad" if h[-1] >= 0 else "pod", "stop": lows[i] if i is not None else None, "cross_i": i}


def turnover(closes, volumes, weeks=4):
    """Średni obrót dzienny ($) z ostatnich `weeks` tygodni (obrót tygodniowy / 5)."""
    pairs = [(c, v) for c, v in zip(closes[-weeks:], volumes[-weeks:]) if _ok(c) and _ok(v)]
    return sum(c * v for c, v in pairs) / len(pairs) / 5 if pairs else None


def passes(row):
    """Warunki strategii (lista do sprawdzenia): obrót, przychody, zmiana marży operacyjnej."""
    t, r, d = row.get("turnover"), row.get("rev_rr"), row.get("dopm")
    return _ok(t) and t >= MIN_TURNOVER and _ok(r) and r >= MIN_REV_GROWTH and _ok(d) and d >= MIN_DOPM


def potential(row):
    """-> lista (klucz, opis, spełnione: True / False / None = brak danych) dla warunków POTENTIAL."""
    r, r1, d, d1, g, o = (row.get(k) for k in ("rev_rr", "rev_rr1", "dopm", "dopm1", "dgm", "opm"))
    val = {"rev25": r >= 25 if _ok(r) else None,
           "rev25x2": (r >= 25 and r1 >= 25) if _ok(r) and _ok(r1) else None,
           "dopm3x2": (d >= 3 and d1 >= 3) if _ok(d) and _ok(d1) else None,
           "dgm2": g >= 2 if _ok(g) else None,
           "lowopm": o < 10 if _ok(o) else None}
    return [(k, txt, val[k]) for k, txt, _ in POTENTIAL]


def slowdown(row):
    """Hamowanie w ostatnim raporcie: None, 'HAMUJE' (tempo przychodów −10 pp lub więcej) albo 'HAMUJE+MB' (do tego marża brutto spada r/r:
    cena 3 i 6 mies. −1,8 %, spadek ≥ 20 % w 6 mies.: 50 %)."""
    a, g = row.get("accel"), row.get("dgm")
    if not (_ok(a) and a <= SLOW_ACCEL):
        return None
    return "HAMUJE+MB" if _ok(g) and g < 0 else "HAMUJE"


def build_row(base, weekly, months, fund):
    """Wiersz listy: base (z Finviz), weekly {d, o, h, l, c, v}, months (High zamkniętych miesięcy), fund (z SEC albo None)."""
    c, lo, v = weekly.get("c") or [], weekly.get("l") or [], weekly.get("v") or []
    row = dict(base)
    price = c[-1] if c else None
    prev = c[-2] if len(c) > 1 else None
    level, _ = green_line(months)
    row.update(price=price, glb=level, glb_state=glb_state(price, prev, level),
               glb_pct=(price / level - 1) * 100 if _ok(price) and _ok(level) and level else None,
               turnover=turnover(c, v))
    m = macd_info(c, lo)
    row.update(macd=m["state"], macd_stop=m["stop"])
    row.update({k: (fund or {}).get(k) for k in ("rev_rr", "rev_rr1", "accel", "dopm", "dopm1", "opm", "dgm", "quarter", "qs")})
    row["ok"] = passes(row)
    pot = potential(row)
    row["pot"] = sum(1 for *_, v in pot if v)
    row["pot_ok"] = [v for *_, v in pot]
    row["slow"] = slowdown(row)
    return row
