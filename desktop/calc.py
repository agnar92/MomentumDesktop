"""Obliczenia (czyste funkcje, bez sieci i GUI): Green Line z miesięcznych High (jak w oryginale Dr. Wisha), stan GLB na zamknięciu tygodnia, MACD tygodniowy,
średnie, obrót i warunki strategii z backtestu (płynny rynek USA 2015–2026):
  - przychody kw. ≥ +15 % r/r, marża operacyjna ≥ +3 pp r/r (z SEC), P/S < 20,
  - siła względna: akcja przez 52 tyg. ≥ 50 pp lepiej od S&P 500 (SPY),
  - wejście: zamknięcie tygodnia 0–10 % nad Green Line (rekord wszech czasów miesięcznego High, który stoi ≥ 3 zamknięte miesiące),
  - wyjście: tygodniowy MACD (12, 26, 9) — stop pod Low tygodnia, w którym MACD przeciął sygnał w dół, plus stop 10 % pod wejściem.
Heurystyka z backtestu, nie porada inwestycyjna."""
import bisect
import datetime as dt
import math

CONFIRM_MONTHS = 3      # rekord musi stać co najmniej tyle zamkniętych miesięcy
ENTRY_MAX_PCT = 10.0    # wejście do 10 % nad linią
# Warunki = tylko te, które w strategii (GLB 0–10 %, stop 10 % + MACD tyg., wszystkie sygnały 2015–2026, ceny bez korekty) mają największy wpływ.
# Razem: +15,6 % na transakcję, portfel wszystkich 36,6 % rocznie (2015–20 43,9 / 2021–26 29,6; 2020–26 46,5 %), DD −55 %, mało sygnałów naraz.
# Usunięte, bo przy tych warunkach nic nie zmieniały: przychody kw. ≥ 25 mln $, zysk oper. w $ ↑, „Mocne” (Δ marży ≥ 10 pp), rozwodnienie, Potencjał.
# Obrót nie jest warunkiem (użytkownik: „usuń limit obrotu w ogóle, sam będę filtrował w Finviz po wolumenie”); backtest liczono na obrocie ≥ 100 mln $.
MIN_REV_GROWTH = 15.0   # przychody kw. r/r (%) — bez niego 34,9 % rocznie
MIN_DOPM = 3.0          # zmiana marży operacyjnej r/r (pp) — bez niej 28,9 %
MAX_PS = 20.0           # wycena P/S < 20 (kapitalizacja / przychody TTM) — bez niej 31,5 % (drogie spółki tracą); odcina też RGTI (P/S 200)
MIN_RS = 50.0           # siła względna: zmiana ceny z 52 tyg. minus zmiana SPY ≥ 50 pp — bez niej 21,4 %; próg 40 pp: 31,3 %
RS_WEEKS = 52
STOP_PCT = 10.0         # stop początkowy pod wejściem
SURPRISE_DAYS = 120     # niespodzianka EPS: ostatni raport nie starszy niż 120 dni (jak w backteście)
RVOL_W, RVOL_D = 10, 50  # wolumen relatywny: tydzień vs średnia 10 poprzednich tygodni, sesja vs średnia 50 poprzednich sesji
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


GMMA_FAST = (3, 5, 8, 10, 12, 15)     # RWB (Guppy, Dr Wish): szybkie EMA — czerwone
GMMA_SLOW = (30, 35, 40, 45, 50, 60)  # wolne EMA — niebieskie


def gmma(closes):
    """-> (6 szybkich EMA, 6 wolnych EMA) — listy tej samej długości co closes."""
    return [ema(closes, n) for n in GMMA_FAST], [ema(closes, n) for n in GMMA_SLOW]


def rwb(closes):
    """RWB: najniższa szybka EMA nad najwyższą wolną (przerwa między wstęgami) -> lista bool."""
    f, s = gmma(closes)
    return [min(x[i] for x in f) > max(x[i] for x in s) for i in range(len(closes))]


def stoch_k(highs, lows, closes, n=10):
    """Stochastic (n, 1) %K -> lista (None, gdy brak n świec albo zerowy zakres)."""
    out = []
    for i in range(len(closes)):
        if i < n - 1:
            out.append(None)
            continue
        hh = max(h for h in highs[i - n + 1:i + 1] if _ok(h)) if any(_ok(h) for h in highs[i - n + 1:i + 1]) else None
        ll = min(x for x in lows[i - n + 1:i + 1] if _ok(x)) if any(_ok(x) for x in lows[i - n + 1:i + 1]) else None
        c = closes[i]
        out.append((c - ll) / (hh - ll) * 100 if _ok(c) and hh is not None and ll is not None and hh > ll else None)
    return out


def blue_dots(highs, lows, closes, level, lvl=20):
    """Blue Dot (Dr Wish): %K Stochastic (10, 1) przecina `lvl` od dołu, gdy jest RWB i zamknięcie nad Green Line `level` -> indeksy świec.
    Kupno na zamknięciu kropki, stop pod jej Low; dalej wyjście po MACD."""
    k, r = stoch_k(highs, lows, closes), rwb([c if _ok(c) else 0 for c in closes])
    return [i for i in range(1, len(closes)) if k[i] is not None and k[i - 1] is not None and k[i - 1] < lvl <= k[i] and r[i]
            and _ok(level) and _ok(closes[i]) and closes[i] >= level]


def fresh_blue_dot(daily, level, sessions=5):
    """Blue Dot na dziennym w ostatnich `sessions` sesjach (wejście, gdy cena jest > 10 % nad Green Line i to nie tydzień przebicia) -> data albo None."""
    if not daily or not daily.get("c") or not _ok(level):
        return None
    dots = blue_dots(daily["h"], daily["l"], daily["c"], level)
    return daily["d"][dots[-1]] if dots and dots[-1] >= len(daily["c"]) - sessions else None


def glb_state(price, prev, level, max_pct=ENTRY_MAX_PCT):
    """Stan na zamknięciu tygodnia: WYBICIE (tydzień przebicia — poprzedni pod linią — przy dowolnej wysokości), SYGNAŁ (0–max_pct % nad linią),
    NAD (dalej; wejście dopiero po Blue Dot na dziennym — stan „BLUE DOT”, `fresh_blue_dot`), POD, BRAK."""
    if not (_ok(price) and _ok(level) and level > 0):
        return "BRAK"
    if price < level:
        return "POD"
    if _ok(prev) and prev < level:   # tydzień przebicia: mocne wybicie przy dowolnej wysokości nad linią
        return "WYBICIE"
    return "NAD" if price > level * (1 + max_pct / 100) else "SYGNAŁ"


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


def rel_strength(weekly, spy, weeks=RS_WEEKS):
    """Siła względna (pp): zmiana zamknięcia z `weeks` tygodni minus zmiana SPY w tych samych tygodniach (SPY = {d, c}, daty dopasowane:
    ostatni tydzień SPY nie późniejszy niż tydzień akcji). None, gdy za krótka historia albo brak SPY."""
    d, c = (weekly or {}).get("d") or [], (weekly or {}).get("c") or []
    sd, sc = (spy or {}).get("d") or [], (spy or {}).get("c") or []
    if len(c) <= weeks or not sd or not (_ok(c[-1]) and _ok(c[-1 - weeks])) or c[-1 - weeks] <= 0:
        return None

    def at(day):
        i = bisect.bisect_right(sd, day) - 1
        return sc[i] if i >= 0 and _ok(sc[i]) and sc[i] > 0 else None
    a, b = at(d[-1 - weeks]), at(d[-1])
    if a is None or b is None:
        return None
    return ((c[-1] / c[-1 - weeks]) - (b / a)) * 100


def rel_volume(vols, n):
    """Wolumen relatywny: ostatni wolumen / średnia z `n` poprzednich (bez ostatniego); None, gdy za mało danych. 2.0 = dwa razy więcej niż zwykle."""
    if len(vols) < n + 1 or not _ok(vols[-1]):
        return None
    prev = [x for x in vols[-1 - n:-1] if _ok(x)]
    avg = sum(prev) / len(prev) if len(prev) >= n * 0.8 else 0
    return vols[-1] / avg if avg > 0 else None


def surprises(est, as_of):
    """Niespodzianki EPS z prognoz (estimates.fetch) znane na `as_of` (YYYY-MM-DD) -> (ostatnia %, poprzednia %, 2 z rzędu > 0: True / False / None).
    None = brak danych albo ostatni raport starszy niż SURPRISE_DAYS."""
    s = [x for x in (est or {}).get("surp") or [] if x[0] <= as_of]
    if not s or (dt.date.fromisoformat(as_of) - dt.date.fromisoformat(s[-1][0])).days > SURPRISE_DAYS:
        return None, None, None
    last, prev = s[-1][1], (s[-2][1] if len(s) > 1 else None)
    return last, prev, bool(last > 0 and prev is not None and prev > 0)


def passes(row):
    """Warunki strategii: przychody kw. ≥ +15 % r/r, marża oper. ≥ +3 pp r/r, P/S < 20 (brak P/S nie blokuje),
    siła względna 52 tyg. ≥ 50 pp nad SPY, 2 ostatnie raporty powyżej konsensusu EPS (brak historii / niespodzianek blokuje — tak było w backteście:
    bez niespodzianek 36,6 % rocznie, z nimi 42,4 %, oba okresy lepiej)."""
    r, d, ps, rs = (row.get(k) for k in ("rev_rr", "dopm", "ps", "rs"))
    return (_ok(r) and r >= MIN_REV_GROWTH and _ok(d) and d >= MIN_DOPM
            and not (_ok(ps) and ps >= MAX_PS) and _ok(rs) and rs >= MIN_RS and row.get("beat2") is True)


def slowdown(row):
    """Hamowanie w ostatnim raporcie: None, 'HAMUJE' (tempo przychodów −10 pp lub więcej) albo 'HAMUJE+MB' (do tego marża brutto spada r/r:
    cena 3 i 6 mies. −1,8 %, spadek ≥ 20 % w 6 mies.: 50 %)."""
    a, g = row.get("accel"), row.get("dgm")
    if not (_ok(a) and a <= SLOW_ACCEL):
        return None
    return "HAMUJE+MB" if _ok(g) and g < 0 else "HAMUJE"


def build_row(base, weekly, months, fund, spy=None, est=None):
    """Wiersz listy: base (z Finviz), weekly {d, o, h, l, c, v}, months (High zamkniętych miesięcy), fund (z SEC albo None), spy (tygodniowe {d, c}),
    est (prognozy z yfinance: niespodzianki EPS i rewizja 90 dni)."""
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
    s10, s30 = sma(c, 10)[-1] if len(c) >= 10 else None, sma(c, 30)[-1] if len(c) >= 30 else None
    row["trend"] = s10 > s30 if s10 is not None and s30 is not None else None   # trend tygodniowy: SMA 10 > SMA 30 (filtr listy)
    row["rvol_w"] = rel_volume(v, RVOL_W)
    row["rvol_d"] = None   # dzienny: uzupełnia odświeżenie ze świec dziennych (rel_volume(v_dzienne, RVOL_D))
    row.update({k: (fund or {}).get(k) for k in ("rev_rr", "rev_rr1", "accel", "dopm", "dopm1", "opm", "dgm", "quarter", "qs", "op_d", "rev_q", "ttm_rev", "dil")})
    f = fund or {}
    mcap = row.get("market_cap") or (price * f["shares"] if _ok(price) and _ok(f.get("shares")) else None)
    row["ps"] = mcap / f["ttm_rev"] if _ok(mcap) and _ok(f.get("ttm_rev")) and f["ttm_rev"] > 0 else None
    row["rs"] = rel_strength(weekly, spy)
    as_of = (weekly.get("d") or [""])[-1]
    # tydzień z danych zaczyna się w poniedziałek: raport z tego tygodnia (do piątku) też jest znany
    row["surp"], row["surp_prev"], row["beat2"] = surprises(est, (dt.date.fromisoformat(as_of) + dt.timedelta(days=6)).isoformat()) if as_of else (None, None, None)
    row["eps_rev"] = (est or {}).get("rev90")
    row["ok"] = passes(row)
    row["slow"] = slowdown(row)
    return row
