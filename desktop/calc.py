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
DEFAULT_CONDITIONS = {
    "rev_growth": {"enabled": True, "threshold": MIN_REV_GROWTH},
    "op_margin": {"enabled": True, "threshold": MIN_DOPM},
    "ps": {"enabled": True, "threshold": MAX_PS},
    "rs": {"enabled": True, "threshold": MIN_RS},
    "beat2": {"enabled": True},
}
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


def normalize_conditions(conditions=None):
    """Wypełnia brakujące progi ustawieniami domyślnymi i odrzuca niepoprawne wartości."""
    source = conditions if isinstance(conditions, dict) else {}
    out = {}
    for key, default in DEFAULT_CONDITIONS.items():
        saved = source.get(key) if isinstance(source.get(key), dict) else {}
        enabled = saved.get("enabled", default["enabled"])
        if key == "beat2":
            out[key] = {"enabled": bool(enabled)}
            continue
        try:
            threshold = float(saved.get("threshold", default["threshold"]))
        except (TypeError, ValueError):
            threshold = default["threshold"]
        if not math.isfinite(threshold):
            threshold = default["threshold"]
        if key == "ps" and threshold <= 0:
            threshold = default["threshold"]
        out[key] = {"enabled": bool(enabled), "threshold": threshold}
    return out


def passes(row, conditions=None):
    """Sprawdza tylko włączone warunki konieczne; brak P/S nie blokuje, jeśli próg P/S jest włączony."""
    cfg = normalize_conditions(conditions)
    required = []
    if cfg["rev_growth"]["enabled"]:
        value = row.get("rev_rr")
        required.append(_ok(value) and value >= cfg["rev_growth"]["threshold"])
    if cfg["op_margin"]["enabled"]:
        value = row.get("dopm")
        required.append(_ok(value) and value >= cfg["op_margin"]["threshold"])
    if cfg["ps"]["enabled"]:
        value = row.get("ps")
        required.append(not _ok(value) or value < cfg["ps"]["threshold"])
    if cfg["rs"]["enabled"]:
        value = row.get("rs")
        required.append(_ok(value) and value >= cfg["rs"]["threshold"])
    if cfg["beat2"]["enabled"]:
        required.append(row.get("beat2") is True)
    return all(required)


def slowdown(row):
    """Hamowanie w ostatnim raporcie: None, 'HAMUJE' (tempo przychodów −10 pp lub więcej) albo 'HAMUJE+MB' (do tego marża brutto spada r/r:
    cena 3 i 6 mies. −1,8 %, spadek ≥ 20 % w 6 mies.: 50 %)."""
    a, g = row.get("accel"), row.get("dgm")
    if not (_ok(a) and a <= SLOW_ACCEL):
        return None
    return "HAMUJE+MB" if _ok(g) and g < 0 else "HAMUJE"


# Growth Score: siedem sygnałów wzrostu, niezależnych od wstępnego filtra Finviz.
GROWTH_SCORE_MIN_COVERAGE = 70.0
GROWTH_SCORE_WEIGHTS = {"revenue_growth": 25.0, "revenue_acceleration": 20.0, "eps_growth": 15.0,
    "eps_revision": 15.0, "op_margin_change": 10.0, "eps_surprise": 5.0, "revenue_surprise": 5.0, "durability": 5.0}
GROWTH_SCORE_GROUPS = {
    "growth": ("Wzrost i przyspieszenie", ("revenue_growth", "revenue_acceleration", "eps_growth")),
    "revision": ("Rewizje prognoz EPS", ("eps_revision",)),
    "margin": ("Zmiana marży operacyjnej", ("op_margin_change",)),
    "surprises": ("Niespodzianki wynikowe", ("eps_surprise", "revenue_surprise")),
    "durability": ("Trwałość wzrostu", ("durability",)),
}


def _growth_component_points(value, knots):
    """Interpoluje punkty między progami; skrajne wartości są ograniczone do końców skali."""
    if not _ok(value):
        return None
    value = float(value)
    if value <= knots[0][0]:
        return float(knots[0][1])
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if value <= x1:
            return float(y0 + (value - x0) * (y1 - y0) / (x1 - x0))
    return float(knots[-1][1])


def _latest_surprise(history, known_through):
    """Najnowsza procentowa niespodzianka z datą raportu nie późniejszą niż known_through."""
    values = [item for item in (history or [])
              if isinstance(item, (list, tuple)) and len(item) >= 2
              and isinstance(item[0], str) and item[0] <= known_through and _ok(item[1])]
    if not values:
        return None
    latest = max(values, key=lambda item: item[0])
    try:
        age = (dt.date.fromisoformat(known_through) - dt.date.fromisoformat(latest[0])).days
    except ValueError:
        return None
    return latest[1] if 0 <= age <= SURPRISE_DAYS else None


def growth_score(row, min_coverage=GROWTH_SCORE_MIN_COVERAGE):
    """Growth Score 0–100. Brakujące dane są pomijane, nie dostają automatycznie zera."""
    row = row or {}
    revenue_growth = row.get("rev_rr")
    eps_growth = None
    eps_history = row.get("eps_q") or []
    try:
        if eps_history:
            latest_day = dt.date.fromisoformat(eps_history[-1][0])
            latest_eps = eps_history[-1][1]
            prior_eps = next(
                (item[1] for item in reversed(eps_history[:-1])
                 if 330 <= (latest_day - dt.date.fromisoformat(item[0])).days <= 400),
                None,
            )
            if _ok(latest_eps) and _ok(prior_eps) and prior_eps > 0:
                eps_growth = (latest_eps / prior_eps - 1) * 100
    except (TypeError, ValueError, IndexError):
        eps_growth = None

    raw = {
        "revenue_growth": revenue_growth,
        "revenue_acceleration": row.get("accel"),
        "eps_growth": eps_growth,
        "eps_revision": row.get("eps_rev"),
        "op_margin_change": row.get("dopm"),
        "eps_surprise": row.get("surp"),
        "revenue_surprise": row.get("rev_surp"),
    }
    points = {
        "revenue_growth": _growth_component_points(raw["revenue_growth"], ((0, 0), (5, 5), (10, 10), (20, 18), (35, 23), (50, 25))),
        "revenue_acceleration": _growth_component_points(raw["revenue_acceleration"], ((-10, 0), (0, 6), (5, 14), (10, 20))),
        "eps_growth": _growth_component_points(raw["eps_growth"], ((-10, 0), (0, 2), (10, 6), (25, 12), (50, 15))),
        "eps_revision": _growth_component_points(raw["eps_revision"], ((-20, 0), (-5, 3), (0, 6), (10, 12), (20, 15))),
        "op_margin_change": _growth_component_points(raw["op_margin_change"], ((-5, 0), (0, 3), (3, 7), (6, 10))),
        "eps_surprise": _growth_component_points(raw["eps_surprise"], ((-20, 0), (0, 0), (5, 3), (15, 4.5), (30, 5))),
        "revenue_surprise": _growth_component_points(raw["revenue_surprise"], ((-20, 0), (0, 0), (5, 3), (15, 4.5), (30, 5))),
    }
    quarters = [item["rev_rr"] for item in (row.get("qs") or [])
                if isinstance(item, dict) and _ok(item.get("rev_rr"))][-4:]
    durability, durability_note = None, "Potrzeba co najmniej dwóch kwartałów historii."
    if len(quarters) >= 2:
        positive = sum(value > 0 for value in quarters)
        durability = positive / len(quarters) * 100
        points["durability"] = GROWTH_SCORE_WEIGHTS["durability"] * durability / 100
        durability_note = f"{positive}/{len(quarters)} dostępnych kwartałów miało dodatni wzrost przychodów r/r."
    else:
        points["durability"] = None

    labels = {
        "revenue_growth": ("Przychody r/r", "%"), "revenue_acceleration": ("Przyspieszenie przychodów", " pp"),
        "eps_growth": ("EPS r/r", "%"), "eps_revision": ("Rewizja EPS 90 dni", "%"),
        "op_margin_change": ("Zmiana marży operacyjnej", " pp"),
        "eps_surprise": ("EPS surprise — ostatni raport", "%"),
        "revenue_surprise": ("Revenue surprise — ostatni raport", "%"),
        "durability": ("Kwartały z dodatnim wzrostem przychodów r/r", "%"),
    }
    details = {key: {"label": labels[key][0], "unit": labels[key][1],
                     "value": durability if key == "durability" else raw.get(key),
                     "points": points.get(key), "weight": weight,
                     "note": durability_note if key == "durability" else None}
               for key, weight in GROWTH_SCORE_WEIGHTS.items()}
    categories, components, component_coverage = {}, {}, {}
    for group, (label, members) in GROWTH_SCORE_GROUPS.items():
        available = [key for key in members if points.get(key) is not None]
        earned = sum(points[key] for key in available) if available else None
        covered, weight = sum(GROWTH_SCORE_WEIGHTS[key] for key in available), sum(GROWTH_SCORE_WEIGHTS[key] for key in members)
        categories[group] = {"label": label, "points": round(earned, 2) if earned is not None else None,
                             "coverage": float(covered), "weight": float(weight)}
        components[group], component_coverage[group] = categories[group]["points"], float(covered)
    coverage = sum(GROWTH_SCORE_WEIGHTS[key] for key, value in points.items() if value is not None)
    earned = sum(value for value in points.values() if value is not None)
    score = earned / coverage * 100 if coverage >= float(min_coverage) and coverage else None
    return {"score": round(score, 1) if score is not None else None, "coverage": round(coverage, 1),
            "points": round(earned, 2), "components": components, "component_coverage": component_coverage,
            "categories": categories, "details": details}



# CAN SLIM–GLB proxy model based on all seven letters described by TraderLion.
# The article provides criteria/guideposts, not this exact composite-score weighting.
CANSLIM_GLB_MIN_COVERAGE = 70.0
CANSLIM_GLB_WEIGHTS = {
    # C — Current quarterly earnings (25)
    "eps_q_growth": 12.0, "sales_q_growth": 5.0, "eps_acceleration": 3.0,
    "margin_expansion": 2.0, "eps_surprise": 2.0, "revenue_surprise": 1.0,
    # A — Annual earnings (20)
    "annual_eps_cagr": 15.0, "annual_eps_consistency": 3.0, "annual_sales_growth": 1.0, "roe": 1.0,
    # N — New product/service/market/management catalyst, manually verified
    "new_catalyst": 10.0,
    # S — Supply and demand
    "breakout_rvol": 10.0, "dilution": 3.0, "float_scarcity": 2.0,
    # L — Leader or laggard
    "rs_percentile": 12.0, "industry_strength": 3.0,
    # I — Institutional sponsorship
    "institutional_ownership": 5.0, "institutional_transactions": 5.0,
    # M — Market direction
    "market_direction": 5.0,
}
CANSLIM_GLB_GROUPS = {
    "current_earnings": ("C — Current quarterly earnings", (
        "eps_q_growth", "sales_q_growth", "eps_acceleration", "margin_expansion", "eps_surprise", "revenue_surprise",
    )),
    "annual_earnings": ("A — Annual earnings growth", (
        "annual_eps_cagr", "annual_eps_consistency", "annual_sales_growth", "roe",
    )),
    "new_catalyst": ("N — New catalyst (≤6 months)", ("new_catalyst",)),
    "supply_demand": ("S — Supply and demand", ("breakout_rvol", "dilution", "float_scarcity")),
    "leadership": ("L — Leader / laggard", ("rs_percentile", "industry_strength")),
    "institutional": ("I — Institutional sponsorship", ("institutional_ownership", "institutional_transactions")),
    "market": ("M — Market direction", ("market_direction",)),
}


def _eps_observations(row):
    """Reported EPS history from estimates cache; only dated, finite values are kept."""
    out = []
    for item in (row or {}).get("eps_q") or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2 or not isinstance(item[0], str) or not _ok(item[1]):
            continue
        try:
            day = dt.date.fromisoformat(item[0])
        except ValueError:
            continue
        out.append((day, float(item[1])))
    return sorted(out, key=lambda item: item[0])


def _eps_growth_at(history, index):
    """Quarterly EPS YoY from the nearest reported quarter 330–400 days earlier."""
    if not history or index < 0 or index >= len(history):
        return None
    day, value = history[index]
    prior = next((previous for old_day, previous in reversed(history[:index])
                  if 330 <= (day - old_day).days <= 400), None)
    if prior is None or prior <= 0:
        return None
    return (value / prior - 1) * 100


def _eps_quarter_yoy(history):
    return _eps_growth_at(history, len(history) - 1)


def _eps_acceleration(history):
    if len(history) < 2:
        return None
    latest = _eps_growth_at(history, len(history) - 1)
    previous = _eps_growth_at(history, len(history) - 2)
    return latest - previous if latest is not None and previous is not None else None


def _annual_eps_stats(history):
    """Approximate yearly EPS from four reported quarters; requires 16 reasonably spaced reports."""
    if len(history) < 16:
        return None, None, None
    recent = history[-16:]
    gaps = [(recent[i][0] - recent[i - 1][0]).days for i in range(1, len(recent))]
    if any(gap < 45 or gap > 150 for gap in gaps):
        return None, None, None
    annuals = [
        sum(value for _, value in recent[-4:]),
        sum(value for _, value in recent[-8:-4]),
        sum(value for _, value in recent[-12:-8]),
        sum(value for _, value in recent[-16:-12]),
    ]
    if any(value <= 0 for value in annuals):
        return None, None, None
    cagr = ((annuals[0] / annuals[3]) ** (1 / 3) - 1) * 100
    yearly_growth = [(annuals[i] / annuals[i + 1] - 1) * 100 for i in range(3)]
    return cagr, sum(value >= 25 for value in yearly_growth), yearly_growth


def _annual_sales_growth(row):
    quarters = [q for q in (row or {}).get("qs") or [] if isinstance(q, dict) and _ok(q.get("rev"))]
    if len(quarters) < 8:
        return None
    current = sum(q["rev"] for q in quarters[-4:])
    previous = sum(q["rev"] for q in quarters[-8:-4])
    return (current / previous - 1) * 100 if previous > 0 else None


def _rank_percentiles(values):
    ordered = sorted((float(value), key) for key, value in values.items() if _ok(value))
    result, n, index = {}, len(ordered), 0
    while index < n:
        end = index + 1
        while end < n and ordered[end][0] == ordered[index][0]:
            end += 1
        percentile = 50.0 if n == 1 else ((index + end - 1) / 2) / (n - 1) * 100
        for _, key in ordered[index:end]:
            result[key] = percentile
        index = end
    return result


def _industry_percentiles(rows):
    """Industry strength proxy ranked only among industries/sectors represented by this scanner."""
    groups = {}
    for row in rows:
        group = (row.get("industry") or row.get("sector") or "").strip()
        if group and _ok(row.get("rs")):
            groups.setdefault(group, []).append(float(row["rs"]))
    medians = {}
    for group, values in groups.items():
        ordered = sorted(values)
        middle = len(ordered) // 2
        medians[group] = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    ranked = _rank_percentiles(medians)
    return {
        row["ticker"]: ranked.get((row.get("industry") or row.get("sector") or "").strip())
        for row in rows if row.get("ticker")
    }


def breakout_rel_volume(daily, level, max_age=10, lookback=50):
    """RVol on a recent daily close-cross above Green Line, compared with the prior 50 sessions."""
    closes = (daily or {}).get("c") or []
    volumes = (daily or {}).get("v") or []
    if not _ok(level) or level <= 0 or len(closes) != len(volumes) or len(closes) < lookback + 2:
        return None
    first = max(1, len(closes) - max(1, int(max_age)))
    for index in range(len(closes) - 1, first - 1, -1):
        if not (_ok(closes[index - 1]) and _ok(closes[index]) and _ok(volumes[index])):
            continue
        if closes[index - 1] < level <= closes[index]:
            prior = [value for value in volumes[index - lookback:index] if _ok(value)]
            if len(prior) < lookback * 0.8:
                return None
            average = sum(prior) / len(prior)
            return volumes[index] / average if average > 0 else None
    return None


def _market_direction(market_series, as_of):
    """Closed-week SPY trend proxy; it does not identify an official IBD Follow-Through Day."""
    dates = (market_series or {}).get("d") or []
    closes = (market_series or {}).get("c") or []
    if len(dates) != len(closes):
        return None, None, "Brak zgodnej historii tygodniowej indeksu."
    try:
        as_of_day = dt.date.fromisoformat(as_of)
    except (TypeError, ValueError):
        as_of_day = dt.date.today()
    known = []
    for date_text, close in zip(dates, closes):
        if not _ok(close):
            continue
        try:
            day = dt.date.fromisoformat(str(date_text)[:10])
        except ValueError:
            continue
        # Weekly bars are timestamped Monday; include only weeks that ended by as_of.
        if day + dt.timedelta(days=6) <= as_of_day:
            known.append((day, float(close)))
    if len(known) < 40:
        return None, None, "Potrzeba co najmniej 40 zamkniętych tygodni SPY."
    values = [value for _, value in known]
    close, sma10, sma40 = values[-1], sum(values[-10:]) / 10, sum(values[-40:]) / 40
    if close > sma10 > sma40:
        return 5.0, "WZROSTOWY", f"SPY powyżej SMA10 i SMA40 tygodniowej (close {close:.2f}, SMA10 {sma10:.2f}, SMA40 {sma40:.2f}); to proxy, nie oficjalny FTD."
    if close > sma40 and sma10 > sma40:
        return 3.5, "MIESZANY", f"SPY nad SMA40, ale nie pełny trend wzrostowy (SMA10 {sma10:.2f}, SMA40 {sma40:.2f})."
    if close > sma40:
        return 2.0, "MIESZANY", f"SPY nad SMA40, lecz SMA10 nie przewyższa SMA40 (SMA10 {sma10:.2f}, SMA40 {sma40:.2f})."
    return 0.0, "SPADKOWY", f"SPY pod SMA40 tygodniową ({close:.2f} vs SMA40 {sma40:.2f}); klasyczny CAN SLIM ogranicza nowe zakupy w słabym rynku."


def _valid_new_catalyst(entry, as_of):
    if not isinstance(entry, dict) or not entry.get("date") or not str(entry.get("note") or "").strip():
        return False, None
    try:
        event_day = dt.date.fromisoformat(str(entry["date"]))
        today = dt.date.fromisoformat(as_of)
    except (TypeError, ValueError):
        return False, None
    age = (today - event_day).days
    if age < 0 or age > 180:
        return False, None
    return True, f"{event_day.isoformat()} — {str(entry['note']).strip()}"


def _score_result(raw, points, notes, weights, groups, min_coverage):
    """Aggregate available component points and return category-level coverage/details."""
    details = {
        key: {
            "label": raw[key]["label"],
            "unit": raw[key]["unit"],
            "value": raw[key]["value"],
            "points": points.get(key),
            "weight": weights[key],
            "note": notes.get(key),
        }
        for key in weights
    }
    categories = {}
    for group_key, (label, members) in groups.items():
        available = [key for key in members if points.get(key) is not None]
        earned = sum(points[key] for key in available) if available else None
        covered = sum(weights[key] for key in available)
        category_weight = sum(weights[key] for key in members)
        categories[group_key] = {
            "label": label,
            "points": round(earned, 2) if earned is not None else None,
            "coverage": float(covered),
            "weight": float(category_weight),
        }
    coverage = sum(weights[key] for key in weights if points.get(key) is not None)
    earned_total = sum(points[key] for key in weights if points.get(key) is not None)
    score = earned_total / coverage * 100 if coverage >= float(min_coverage) and coverage else None
    return {
        "score": round(score, 1) if score is not None else None,
        "coverage": round(coverage, 1),
        "points": round(earned_total, 2),
        "categories": categories,
        "details": details,
        "groups": groups,
    }


def canslim_glb_scores(rows, market_series=None, n_confirmations=None,
                       min_coverage=CANSLIM_GLB_MIN_COVERAGE, as_of=None):
    """Article-aligned CAN SLIM–GLB score for the current scanner.

    C/A use reported quarterly and annual fundamentals; N is manually verified and date-limited;
    S uses RVol at a genuine recent GLB cross, dilution and float; L/I use Finviz/scanner proxies;
    M uses closed-week SPY trend and explicitly is not an official IBD FTD calculation.
    """
    rows = [row for row in (rows or []) if row.get("ticker")]
    n_confirmations = n_confirmations if isinstance(n_confirmations, dict) else {}
    as_of = as_of or dt.date.today().isoformat()
    rs_percentiles = _rank_percentiles({row["ticker"]: row.get("rs") for row in rows})
    industry_percentiles = _industry_percentiles(rows)
    market_points, market_state, market_note = _market_direction(market_series, as_of)

    out = {}
    for row in rows:
        ticker = row["ticker"]
        history = _eps_observations(row)
        q_growth = _eps_quarter_yoy(history)
        q_acceleration = _eps_acceleration(history)
        annual_cagr, years_25, _yearly_growth = _annual_eps_stats(history)
        sales_growth = row.get("rev_rr")
        annual_sales = _annual_sales_growth(row)
        op_margin_change = row.get("dopm")
        roe = row.get("roe")
        eps_surprise, revenue_surprise = row.get("surp"), row.get("rev_surp")
        n_ok, n_note = _valid_new_catalyst(n_confirmations.get(ticker), as_of)
        signal_active = row.get("glb_state") in ("WYBICIE", "SYGNAŁ", "BLUE DOT")
        breakout_rvol = row.get("glb_rvol") if signal_active else None
        dilution = row.get("dil")
        float_shares = row.get("shares_float")
        rs_percentile = rs_percentiles.get(ticker)
        industry_percentile = industry_percentiles.get(ticker)
        institutional_ownership = row.get("institutional_ownership")
        institutional_transactions = row.get("institutional_transactions")

        new_note = (
            f"Potwierdzono ręcznie: {n_note}. Zweryfikuj wiarygodny wpływ na przychody/zyski."
            if n_ok else
            "Wymaga ręcznego potwierdzenia: nowy produkt/usługa, nowy rynek, istotna zmiana kierownictwa, partnerstwo/akwizycja lub ważne ulepszenie z ostatnich 180 dni z wiarygodną ścieżką do wzrostu zysków."
        )
        breakout_note = (
            "RVol na dziennej świecy zamknięcia ponad bieżącą Green Line, jeśli przejście nastąpiło w ostatnich 10 sesjach; porównanie z 50 poprzednimi sesjami."
            if _ok(breakout_rvol) else
            "Brak przejścia dziennego close ponad bieżącą Green Line w ostatnich 10 sesjach lub brak 50 wcześniejszych sesji. Nie podstawiam dzisiejszego wolumenu jako wolumenu wybicia."
        )
        raw = {
            "eps_q_growth": {"label": "EPS kwartalny r/r", "unit": "%", "value": q_growth},
            "sales_q_growth": {"label": "Przychody kwartalne r/r", "unit": "%", "value": sales_growth},
            "eps_acceleration": {"label": "Przyspieszenie wzrostu EPS r/r", "unit": " pp", "value": q_acceleration},
            "margin_expansion": {"label": "Zmiana marży operacyjnej r/r", "unit": " pp", "value": op_margin_change},
            "eps_surprise": {"label": "Niespodzianka EPS", "unit": "%", "value": eps_surprise},
            "revenue_surprise": {"label": "Niespodzianka przychodów", "unit": "%", "value": revenue_surprise},
            "annual_eps_cagr": {"label": "EPS TTM CAGR (3 lata)", "unit": "%", "value": annual_cagr},
            "annual_eps_consistency": {"label": "Lata z wzrostem EPS ≥25%", "unit": " z 3 lat", "value": years_25},
            "annual_sales_growth": {"label": "Przychody TTM r/r", "unit": "%", "value": annual_sales},
            "roe": {"label": "ROE", "unit": "%", "value": roe},
            "new_catalyst": {"label": "Nowy katalizator (≤6 miesięcy)", "unit": "", "value": 100.0 if n_ok else None, "note": new_note},
            "breakout_rvol": {"label": "RVol na świecy wybicia GLB", "unit": "x", "value": breakout_rvol, "note": breakout_note},
            "dilution": {"label": "Zmiana rozwodnionej liczby akcji r/r", "unit": "%", "value": dilution},
            "float_scarcity": {"label": "Free float", "unit": " akcji", "value": float_shares},
            "rs_percentile": {"label": "RS percentyl aktywnego skanera", "unit": "/100", "value": rs_percentile},
            "industry_strength": {"label": "Siła grupy branżowej", "unit": "/100", "value": industry_percentile},
            "institutional_ownership": {"label": "Własność instytucji (Finviz)", "unit": "%", "value": institutional_ownership},
            "institutional_transactions": {"label": "Zmiana własności instytucji (Finviz)", "unit": "%", "value": institutional_transactions},
            "market_direction": {"label": "Kierunek rynku — SPY SMA10/40 tyg.", "unit": " pkt", "value": market_points},
        }
        notes = {
            "eps_q_growth": "TraderLion podaje ≥25% wzrostu kwartalnego EPS r/r jako guidepost; wyższa dynamika dostaje więcej punktów.",
            "sales_q_growth": "Przychody kwartalne r/r: artykuł wskazuje około 20%+ jako potwierdzenie popytu.",
            "eps_acceleration": "Zmiana tempa wzrostu EPS r/r względem poprzedniego raportu.",
            "margin_expansion": "Pomocniczy sygnał jakości wzrostu z części C, nie osobna litera CAN SLIM.",
            "eps_surprise": "Raportowany EPS względem konsensusu: historyczne potwierdzenie, nie sama prognoza.",
            "revenue_surprise": "Raportowane przychody względem konsensusu.",
            "annual_eps_cagr": "CAGR z sum czterech raportowanych EPS w czterech blokach rocznych; wymaga 16 raportów i dodatniej rocznej sumy.",
            "annual_eps_consistency": ("Liczba z trzech porównań rocznych, w których EPS wzrósł ≥25%."
                                      if years_25 is not None else "Potrzeba 16 raportowanych kwartałów i dodatnich rocznych sum."),
            "annual_sales_growth": "Wzrost przychodów TTM r/r z ostatnich ośmiu raportów kwartalnych.",
            "roe": "ROE ≥15% jest pomocniczym guidepostem z części A; bieżąca metryka Finviz.",
            "new_catalyst": new_note,
            "breakout_rvol": breakout_note,
            "dilution": ("Spadek liczby rozwodnionych akcji (wartość ujemna) wspiera kryterium podaży; silne rozwodnienie obniża punkty."
                         if _ok(dilution) else "Brak danych SEC o zmianie rozwodnionej liczby akcji."),
            "float_scarcity": "Mniejszy float może wzmacniać ruch przy popycie; to prosta heurystyka, nie samodzielna rekomendacja.",
            "rs_percentile": (f"Percentyl {rs_percentile:.0f}/100 wśród {len(rs_percentiles)} spółek aktywnego skanera; proxy, nie oficjalny IBD RS Rating względem całego rynku."
                              if rs_percentile is not None else "Brak 52-tygodniowego RS albo za krótka historia."),
            "industry_strength": (f"Percentyl mediany RS branży/sektora wśród {len(set((x.get('industry') or x.get('sector') or '').strip() for x in rows if (x.get('industry') or x.get('sector'))))} grup aktywnego skanera; proxy, nie oficjalny ranking grup IBD."
                                 if industry_percentile is not None else "Brak branży/sektora albo brak wartości RS."),
            "institutional_ownership": "Inst Own: premiowany umiarkowany udział; bardzo wysoka własność ma mniej punktów. To nie ocenia jakości konkretnych funduszy.",
            "institutional_transactions": "Inst Trans: dodatnia zmiana udziałów instytucji jest premiowana. To bieżący snapshot Finviz, nie historyczna seria.",
            "market_direction": market_note,
        }
        points = {
            "eps_q_growth": _growth_component_points(q_growth, ((-100, 0), (0, 0), (10, 4), (25, 9), (50, 11), (100, 12))) if q_growth is not None else None,
            "sales_q_growth": _growth_component_points(sales_growth, ((0, 0), (10, 2), (20, 4), (40, 5))) if _ok(sales_growth) else None,
            "eps_acceleration": _growth_component_points(q_acceleration, ((-20, 0), (0, 1), (10, 2), (25, 3))) if q_acceleration is not None else None,
            "margin_expansion": _growth_component_points(op_margin_change, ((-5, 0), (0, 0.5), (2, 1.5), (5, 2))) if _ok(op_margin_change) else None,
            "eps_surprise": _growth_component_points(eps_surprise, ((-20, 0), (0, 0), (5, 1), (20, 2))) if _ok(eps_surprise) else None,
            "revenue_surprise": _growth_component_points(revenue_surprise, ((-20, 0), (0, 0), (5, 0.5), (20, 1))) if _ok(revenue_surprise) else None,
            "annual_eps_cagr": _growth_component_points(annual_cagr, ((-100, 0), (0, 0), (10, 5), (25, 11), (40, 14), (60, 15))) if annual_cagr is not None else None,
            "annual_eps_consistency": float(years_25) if years_25 is not None else None,
            "annual_sales_growth": _growth_component_points(annual_sales, ((0, 0), (10, 0.5), (20, 0.9), (40, 1))) if annual_sales is not None else None,
            "roe": _growth_component_points(roe, ((0, 0), (7.5, 0.5), (15, 1))) if _ok(roe) else None,
            "new_catalyst": CANSLIM_GLB_WEIGHTS["new_catalyst"] if n_ok else None,
            "breakout_rvol": _growth_component_points(breakout_rvol, ((0, 0), (1, 0), (1.2, 5), (1.4, 8), (1.5, 10))) if _ok(breakout_rvol) else None,
            "dilution": _growth_component_points(dilution, ((-10, 3), (0, 3), (2, 2), (5, 0), (15, 0))) if _ok(dilution) else None,
            "float_scarcity": (
                2.0 if float_shares <= 50e6 else 1.5 if float_shares <= 100e6 else
                1.0 if float_shares <= 250e6 else 0.5 if float_shares <= 500e6 else 0.0
            ) if _ok(float_shares) and float_shares > 0 else None,
            "rs_percentile": CANSLIM_GLB_WEIGHTS["rs_percentile"] * rs_percentile / 100 if rs_percentile is not None else None,
            "industry_strength": CANSLIM_GLB_WEIGHTS["industry_strength"] * industry_percentile / 100 if industry_percentile is not None else None,
            "institutional_ownership": _growth_component_points(institutional_ownership, ((0, 0), (10, 1), (20, 3), (35, 5), (65, 5), (80, 4), (90, 2), (100, 0))) if _ok(institutional_ownership) else None,
            "institutional_transactions": _growth_component_points(institutional_transactions, ((-20, 0), (0, 0), (5, 3), (10, 4), (20, 5))) if _ok(institutional_transactions) else None,
            "market_direction": market_points,
        }
        result = _score_result(raw, points, notes, CANSLIM_GLB_WEIGHTS, CANSLIM_GLB_GROUPS, min_coverage)
        # N is a defining CAN SLIM criterion. Do not show a seemingly complete score before the user confirms it.
        if not n_ok:
            result["score"] = None
        result["market_state"] = market_state
        result["market_note"] = market_note
        out[ticker] = result
    return out



def pegy_ratio(peg, forward_pe, dividend_yield_pct):
    """PEGY = Forward P/E / (EPS growth % + dividend yield %).

    Finviz defines PEG as Forward P/E / annual EPS growth. We infer the growth
    rate from these two Finviz valuation fields and add the Finviz dividend yield.
    Dividend yield is in percentage points (e.g. 2.0 means 2%).
    """
    if not (_ok(peg) and _ok(forward_pe) and _ok(dividend_yield_pct)):
        return None
    if peg <= 0 or forward_pe <= 0 or dividend_yield_pct < 0:
        return None
    growth_pct = float(forward_pe) / float(peg)
    denominator = growth_pct + float(dividend_yield_pct)
    if not math.isfinite(denominator) or denominator <= 0:
        return None
    return round(float(forward_pe) / denominator, 2)


def build_row(base, weekly, months, fund, spy=None, est=None, conditions=None):
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
    row["pegy"] = pegy_ratio(row.get("peg"), row.get("forward_pe"), row.get("dividend_yield"))
    row["rs"] = rel_strength(weekly, spy)
    as_of = (weekly.get("d") or [""])[-1]
    # tydzień z danych zaczyna się w poniedziałek: raport z tego tygodnia (do piątku) też jest znany
    known_through = (dt.date.fromisoformat(as_of) + dt.timedelta(days=6)).isoformat() if as_of else ""
    row["surp"], row["surp_prev"], row["beat2"] = surprises(est, known_through) if known_through else (None, None, None)
    row["rev_surp"] = _latest_surprise((est or {}).get("revenue_surp"), known_through) if known_through else None
    row["eps_q"] = (est or {}).get("eps_q") or []
    row["eps_rev"] = (est or {}).get("rev90")
    row["upside"] = (est or {}).get("upside")
    row["ok"] = passes(row, conditions)
    row["slow"] = slowdown(row)
    return row
