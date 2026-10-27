"""Obliczenia (czyste funkcje, bez sieci i GUI): Green Line z miesięcznych High (jak w oryginale Dr. Wisha), stan GLB na zamknięciu tygodnia, MACD tygodniowy,
średnie, obrót i warunki strategii (badanie 2011–2025, szeroki rynek USA, portfel 10 pozycji — jak w aplikacji webowej Momentum):
  - przychody kw. ≥ +15 % r/r i marża operacyjna ≥ +3 pp r/r (z SEC); skaner Finviz: cena > 10, śr. wolumen > 300 tys., Sales Q/Q > 15 %,
  - wejście: zamknięcie tygodnia 0–10 % nad Green Line (rekord wszech czasów miesięcznego High, który stoi 3 miesiące łącznie: miesiąc szczytu + 2 zamknięte kolejne),
  - wyjście: stop 10 % pod wejściem i tygodniowy MACD (12, 26, 9) — stop pod Low tygodnia przecięcia w dół PO wejściu (lines.position_plan).
Heurystyka z backtestu, nie porada inwestycyjna."""
import bisect
import datetime as dt
import math

CONFIRM_MONTHS = 2      # zamknięte miesiące PO miesiącu szczytu; razem ze szczytem 3 miesiące (Dr Wish: „at least 3 months”, użytkownik: „dwie świeczki po szczycie”)
ENTRY_MAX_PCT = 10.0    # wejście do 10 % nad linią
# Badanie 2011–2025 (≈5600 spółek, fundamenty SEC znane 50/80 dni po kwartale, portfel 10 pozycji, koszt 0,1 %/stronę): GLB bez warunków ≈ 12 % rocznie,
# z przychodami ≥ 15 % i Δ marży ≥ 3 pp, sygnał po przebiciu od dołu i linia potwierdzana po szczycie + 2 miesiące: ≈ 9 % rocznie (2011–17 ≈ 10 %, 2018–25 ≈ 8 %), DD ≈ −40 %; z wolną gotówką w SPY ≈ 16 %
# (poprzednio, bez reguły przebicia i z 3 zamkniętymi miesiącami: ≈ 21 % / 25 %). RS ≥ 50 pp jako warunek obniżał
# wynik (za mało sygnałów), P/S i beat2 nie dało się sprawdzić historycznie — domyślnie wyłączone (można włączyć w ustawieniach warunków).
# Usunięte, bo przy tych warunkach nic nie zmieniały: przychody kw. ≥ 25 mln $, zysk oper. w $ ↑, „Mocne” (Δ marży ≥ 10 pp), rozwodnienie, Potencjał.
# Obrót nie jest warunkiem (użytkownik: „usuń limit obrotu w ogóle, sam będę filtrował w Finviz po wolumenie”); backtest liczono na obrocie ≥ 100 mln $.
MIN_REV_GROWTH = 15.0   # przychody kw. r/r (%) — bez niego 34,9 % rocznie
MIN_DOPM = 3.0          # zmiana marży operacyjnej r/r (pp) — bez niej 28,9 %
MAX_PS = 20.0           # wycena P/S < 20 (kapitalizacja / przychody TTM) — bez niej 31,5 % (drogie spółki tracą); odcina też RGTI (P/S 200)
MIN_RS = 50.0           # siła względna: zmiana ceny z 52 tyg. minus zmiana SPY ≥ 50 pp — bez niej 21,4 %; próg 40 pp: 31,3 %
DEFAULT_CONDITIONS = {
    "rev_growth": {"enabled": True, "threshold": MIN_REV_GROWTH},
    "op_margin": {"enabled": True, "threshold": MIN_DOPM},
    "ps": {"enabled": False, "threshold": MAX_PS},
    "rs": {"enabled": False, "threshold": MIN_RS},
    "beat2": {"enabled": False},
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
    Rekord wszech czasów jest linią, gdy po jego miesiącu zamknęły się ≥ `confirm` miesięcy (domyślnie 2 = 3 świece łącznie ze szczytem); nowszy rekord zastępuje ją dopiero po swoich `confirm` miesiącach."""
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


def glb_armed(closes, level, max_pct=ENTRY_MAX_PCT):
    """Czy ta linia nadal daje sygnał: zamknięcie pod linią uzbraja (przebicie OD DOŁU), ale gdy cena zamknęła się > max_pct % nad linią,
    linia WYGASA aż do powstania nowej Green Line — powrót do niej po dużym rajdzie to kupowanie spadku po wyższym rekordzie
    (cena nad linią o ≤ max_pct % nie bywa pod SMA 200 / 50, bo linia jest wtedy aktualnym ATH). `closes` = zamknięcia tygodni BEZ bieżącego."""
    armed = retired = False
    if not (_ok(level) and level > 0):
        return armed
    for x in closes:
        if not _ok(x):
            continue
        if x < level:
            armed = not retired
        elif x > level * (1 + max_pct / 100):
            armed, retired = False, True
    return armed


def glb_state(price, prev, level, max_pct=ENTRY_MAX_PCT, armed=True):
    """Stan na zamknięciu tygodnia: WYBICIE (tydzień przebicia — poprzedni pod linią — przy dowolnej wysokości), SYGNAŁ (0–max_pct % nad linią
    po przebiciu od dołu, `glb_armed`), NAD (dalej albo linia wygasła po rajdzie; wejście tylko po Blue Dot na dziennym — stan „BLUE DOT”,
    `fresh_blue_dot`), POD, BRAK. `armed` liczone z zamknięć sprzed bieżącego tygodnia."""
    if not (_ok(price) and _ok(level) and level > 0):
        return "BRAK"
    if price < level:
        return "POD"
    if _ok(prev) and prev < level:   # tydzień przebicia: mocne wybicie przy dowolnej wysokości nad linią
        return "WYBICIE" if armed else "NAD"
    return "NAD" if price > level * (1 + max_pct / 100) or not armed else "SYGNAŁ"


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


def price_ratio(closes, sessions=252):
    """C/C[52 tyg.]: aktualne zamknięcie / zamknięcie sprzed 252 sesji; przy krótszej historii najstarsze (jak w webowym Momentum)."""
    if len(closes or []) < 2:
        return None
    base = closes[max(0, len(closes) - (sessions + 1))]
    return closes[-1] / base if base else None


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


# --- Sektory (skaner „Sektory top 3”): RS sektora = cena ETF sektora / SPY (tygodniowo); sektor jest „dodatni”, gdy RS leży nad własną SMA 52 tyg.;
# ranking po % RS nad tą średnią, bierzemy 3 najsilniejsze (użytkownik: „weź sektory i ten RS co wcześniej i weź top 3 sektory”).
# Badanie 2011–2025 (GLB bez fundamentów, 10 pozycji, wolne miejsca SPY/QQQ): top 3 sektory ≈ 11–12 % rocznie, DD ≈ −28 % vs wszystkie sektory ≈ 9 %, DD ≈ −38 %.
SECTOR_ETFS = [   # (ETF SPDR, sektor w Finviz, kod filtra Finviz `sec_...`)
    ("XLB", "Basic Materials", "basicmaterials"), ("XLC", "Communication Services", "communicationservices"), ("XLY", "Consumer Cyclical", "consumercyclical"),
    ("XLP", "Consumer Defensive", "consumerdefensive"), ("XLE", "Energy", "energy"), ("XLF", "Financial", "financial"), ("XLV", "Healthcare", "healthcare"),
    ("XLI", "Industrials", "industrials"), ("XLRE", "Real Estate", "realestate"), ("XLK", "Technology", "technology"), ("XLU", "Utilities", "utilities"),
]
SECTOR_MA = 52
TOP_SECTORS = 3
# filtr Finviz dla każdego z trzech zapytań (obok `sec_<sektor>`): tylko akcje, cena > 15 $, śr. wolumen > 300 tys. i przychody kw. > 15 % r/r
# (jedyny fundament z istotnym efektem w badaniu: +1,8 pp na transakcję, przedział [0,2; 3,4]; marża, EPS, ROE, wycena — bez wykrywalnego efektu)
SECTOR_FILTERS = "ind_stocksonly,sh_price_o15,sh_avgvol_o300,fa_salesqoq_o15"


def sector_rs(sectors, bench, ma=SECTOR_MA):
    """sectors {ETF: tygodniowe {d, c}}, bench = SPY -> [{etf, sector, code, rs, ma, pct}] malejąco po pct (% RS nad własną SMA `ma` tygodni).
    ETF bez `ma` wspólnych tygodni z benchmarkiem pomijamy."""
    bc = dict(zip(bench.get("d") or [], bench.get("c") or []))
    out = []
    for etf, name, code in SECTOR_ETFS:
        s = sectors.get(etf)
        if not s:
            continue
        rs = [c / bc[d] for d, c in zip(s.get("d") or [], s.get("c") or []) if _ok(c) and _ok(bc.get(d)) and bc[d] > 0]
        if len(rs) < ma:
            continue
        avg = sum(rs[-ma:]) / ma
        out.append({"etf": etf, "sector": name, "code": code, "rs": rs[-1], "ma": avg, "pct": (rs[-1] / avg - 1) * 100})
    return sorted(out, key=lambda x: -x["pct"])


def top_sectors(ranked, n=TOP_SECTORS):
    """n najsilniejszych sektorów z RS nad SMA (pct > 0); mniej, gdy tyle dodatnich nie ma."""
    return [x for x in ranked if x["pct"] > 0][:n]


def sector_filter(base_filters, sector):
    """Filtr Finviz jednego zapytania: sektor + wspólne warunki."""
    return f"sec_{sector['code']},{base_filters}"


# --- EPS Rating w stylu IBD (przybliżenie): IBD podaje tylko, że łączy wzrost EPS z 2 ostatnich kwartałów z 3-letnim wzrostem (z naciskiem na ostatnie wyniki)
# i porównuje z innymi spółkami (1–99); dokładnej formuły nie publikuje. Tu: wzrost r/r EPS ostatnich 2 kwartałów (waga 0,5), 3-letni wzrost EPS TTM (0,3),
# stabilność = odsetek ostatnich 8 kwartałów z dodatnim wzrostem r/r (0,2); wynik to percentyl 1–99 wśród spółek w skanerach (nie wszystkich akcji USA).
EPS_WEIGHTS = (0.5, 0.3, 0.2)


def _eps_growth(now, then):
    """Wzrost % względem |bazy| (też przy ujemnej bazie: z −1 do +1 = +200 %); baza 0 -> None; obcięcie −300…+1000 %."""
    if not (_ok(now) and _ok(then)) or then == 0:
        return None
    return max(-300.0, min(1000.0, (now - then) / abs(then) * 100))


def eps_features(eps_q):
    """eps_q = [[data, EPS kwartału], …] (yfinance) -> {g2, cagr3, stab, raw} albo None (brak 2 kwartałów r/r)."""
    q = sorted((dt.date.fromisoformat(str(d)[:10]), float(v)) for d, v in eps_q or [] if _ok(v))
    gs = []
    for i in range(len(q) - 1, -1, -1):
        j = next((k for k in range(i - 1, -1, -1) if 330 <= (q[i][0] - q[k][0]).days <= 400), None)
        if j is None:
            continue
        gs.append(_eps_growth(q[i][1], q[j][1]))
        if len(gs) >= 8:
            break
    recent = [g for g in gs[:2] if g is not None]
    if not recent:
        return None
    g2 = sum(recent) / len(recent)
    ok = [g for g in gs if g is not None]
    stab = sum(1 for g in ok if g > 0) / len(ok) if len(ok) >= 4 else None
    cagr3 = None
    if len(q) >= 16 and 1000 <= (q[-1][0] - q[-13][0]).days <= 1190:
        now, then = sum(v for _, v in q[-4:]), sum(v for _, v in q[-16:-12])
        cagr3 = ((now / then) ** (1 / 3) - 1) * 100 if now > 0 and then > 0 else 100.0 if now > 0 else -100.0
    parts = [(EPS_WEIGHTS[0], max(-100.0, min(200.0, g2)) / 200),
             (EPS_WEIGHTS[1], None if cagr3 is None else max(-50.0, min(100.0, cagr3)) / 100),
             (EPS_WEIGHTS[2], stab)]
    parts = [(w, x) for w, x in parts if x is not None]
    raw = sum(w * x for w, x in parts) / sum(w for w, _ in parts)
    return {"g2": round(g2, 1), "cagr3": None if cagr3 is None else round(cagr3, 1), "stab": None if stab is None else round(stab, 2), "raw": round(raw, 4)}


def assign_eps_rating(rows, pool=None):
    """Ustawia row["eps_rating"] (1–99) = percentyl `eps_raw` wiersza wśród wierszy `pool` (domyślnie `rows`); bez danych EPS -> None."""
    raws = sorted(r["eps_raw"] for r in (rows if pool is None else pool) if _ok(r.get("eps_raw")))
    for r in rows:
        x = r.get("eps_raw")
        if not raws or not _ok(x):
            r["eps_rating"] = None
            continue
        pct = (bisect.bisect_left(raws, x) + bisect.bisect_right(raws, x)) / 2 / len(raws)
        r["eps_rating"] = max(1, min(99, round(1 + 98 * pct)))


def build_row(base, weekly, months, fund, spy=None, est=None, conditions=None):
    """Wiersz listy: base (z Finviz), weekly {d, o, h, l, c, v}, months (High zamkniętych miesięcy), fund (z SEC albo None), spy (tygodniowe {d, c}),
    est (prognozy z yfinance: niespodzianki EPS i rewizja 90 dni)."""
    c, lo, v = weekly.get("c") or [], weekly.get("l") or [], weekly.get("v") or []
    row = dict(base)
    price = c[-1] if c else None
    prev = c[-2] if len(c) > 1 else None
    level, _ = green_line(months)
    row.update(price=price, glb=level, glb_state=glb_state(price, prev, level, armed=glb_armed(c[:-1], level)),
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
    ef = eps_features(row["eps_q"]) or {}
    row.update(eps_g2=ef.get("g2"), eps_cagr3=ef.get("cagr3"), eps_stab=ef.get("stab"), eps_raw=ef.get("raw"), eps_rating=None)   # ocena 1–99: assign_eps_rating po zbudowaniu listy
    row["ok"] = passes(row, conditions)
    row["slow"] = slowdown(row)
    return row
