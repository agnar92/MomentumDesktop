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
RVOL_W = 10  # wolumen relatywny: tydzień vs średnia 10 poprzednich tygodni
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


def rwb_starts(closes, warmup=60):
    """Początki RWB: świece, na których szybkie EMA znów wszystkie nad wolnymi (poprzednia świeca bez RWB) — sygnał do dokupienia (po cofnięciu w trendzie)."""
    r = rwb(closes)
    return [i for i in range(max(1, warmup), len(r)) if r[i] and not r[i - 1]]


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


def fresh_blue_dot(weekly, level, weeks=2):
    """Blue Dot na TYGODNIOWYM w ostatnich `weeks` tygodniach (wejście, gdy cena jest > 10 % nad Green Line i to nie tydzień przebicia) -> data albo None."""
    if not weekly or not weekly.get("c") or not _ok(level):
        return None
    dots = blue_dots(weekly["h"], weekly["l"], weekly["c"], level)
    return weekly["d"][dots[-1]] if dots and dots[-1] >= len(weekly["c"]) - weeks else None


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
    po przebiciu od dołu, `glb_armed`), NAD (dalej albo linia wygasła po rajdzie; wejście tylko po Blue Dot na tygodniowym — stan „BLUE DOT”,
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


def price_ratio(closes, weeks=52):
    """C/C[52 tyg.]: aktualne zamknięcie tygodnia / zamknięcie sprzed 52 tygodni; przy krótszej historii najstarsze."""
    if len(closes or []) < 2:
        return None
    base = closes[max(0, len(closes) - (weeks + 1))]
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


# --- Wzorce Zangera (chartpattern.com), tygodniowe świece. Strona podaje liczby tylko dla Cup & Handle (spadek 20–35 % w 8–12 tyg., uchwyt 4 dni–3 tyg.
# ok. 5 % pod starym szczytem, kupno przy wyjściu nad górę uchwytu); reszta jest opisana słownie, więc progi poniżej to PRZYBLIŻENIE tych opisów
# (nie testowane na historii jako strategia). Wzorzec jest „aktywny”, gdy kończy się w ostatnich tygodniach: budowany (cena pod punktem kupna)
# albo świeże wybicie (do 10 % nad nim). Parabolic Curve to wzorzec końca trendu — służy do wyjścia, nie do kupna.
PATTERN_NAMES = ("Cup & Handle", "Flat Base", "Ascending Triangle", "Flaga/Proporzec", "Channel", "Symmetrical Triangle", "Descending Triangle", "Falling Wedge", "Inverted H&S")
SELL_PATTERNS = ("Head & Shoulders", "Rising Wedge")   # wzorce niedźwiedzie: ostrzeżenie / wyjście, nie kupno
CUP_DEPTH, CUP_WEEKS, HANDLE_WEEKS = (0.20, 0.35), (8, 30), (1, 3)
BREAKOUT_MAX_PCT = 10.0   # wybicie dalej niż 10 % nad punktem kupna nie jest już podpowiedzią
PATTERN_LOOKBACK = 4      # wzorzec musi kończyć się w jednym z tylu ostatnich tygodni
PARABOLA_MIN_GAIN = 1.0   # Parabolic Curve: min. +100 % od początku najflatszej linii


def _finish(name, buy, e, w, shapes, note, first_buy=None, near_high=0.85):
    """Stan wzorca kończącego się w tygodniu e: BUDUJE SIĘ (cena pod punktem kupna) albo WYBICIE (do BREAKOUT_MAX_PCT nad nim); inaczej None.
    buy = poziom kupna dziś (dla linii skośnej: wartość linii w ostatnim tygodniu), first_buy = poziom w pierwszym tygodniu po wzorcu."""
    c, v = w["c"], w.get("v") or []
    post = c[e + 1:]
    last = c[-1]
    fb = buy if first_buy is None else first_buy
    if len(post) > PATTERN_LOOKBACK - 1 or any(not _ok(x) for x in post):
        return None
    if post:
        if post[0] <= fb or last <= buy:   # wybicie musi trwać do dziś
            return None
        state = "WYBICIE"
        base_v = [x for x in v[e - 9:e + 1] if _ok(x)]
        volx = v[e + 1] / (sum(base_v) / len(base_v)) if base_v and _ok(v[e + 1]) and sum(base_v) > 0 else None
    else:
        state, volx = "BUDUJE SIĘ", None
    pct = (last / buy - 1) * 100
    if pct > BREAKOUT_MAX_PCT or pct < -8:
        return None
    if last < max(w['h'][-52:]) * near_high:   # liderzy: cena w 15 % od maksimum 52 tyg. (odwrócenia: 30 %)
        return None
    d = w["d"]
    return {"name": name, "side": "buy", "state": state, "buy": round(buy, 4), "pct": round(pct, 2), "start": shapes[0]["d1"], "end": d[e], "vol_x": None if volx is None else round(volx, 2),
            "shapes": shapes, "note": note}


def _cup(w, e):
    c, h, lo, d = w["c"], w["h"], w["l"], w["d"]
    for hl in range(HANDLE_WEEKS[0], HANDLE_WEEKS[1] + 1):
        r = e - hl                                   # prawa krawędź miseczki
        if r < CUP_WEEKS[0]:
            continue
        handle = range(r + 1, e + 1)
        top_h = max(h[i] for i in handle)
        for a in range(max(4, r - CUP_WEEKS[1]), r - CUP_WEEKS[0] + 1):   # lewy szczyt
            hi_a = h[a]
            if hi_a < max(h[max(0, a - 4):a + 5]) or max(h[a:r + 1]) > hi_a * 1.02 or h[r] < hi_a * 0.95 or h[r] > hi_a * 1.02:
                continue
            b = min(range(a, r + 1), key=lambda i: lo[i])
            depth = 1 - lo[b] / hi_a
            if not CUP_DEPTH[0] <= depth <= CUP_DEPTH[1] or b - a < 3 or r - b < 3:
                continue
            if min(lo[i] for i in handle) < hi_a * 0.90 or top_h > h[r] * 1.0001:   # uchwyt nie głębiej niż ok. 10 % pod starym szczytem
                continue
            run = min(c[max(0, a - 17):a] or [c[a]])
            if c[a] < run * 1.2:                     # miseczka po silnym wzroście (2–4 miesiące)
                continue
            la, lb, lr = math.log(hi_a), math.log(lo[b]), math.log(h[r])
            curve = []
            for i in range(a, r + 1):                # parabola przez lewy szczyt, dno i prawą krawędź (skala log)
                x = (i - a) / (r - a)
                xb = (b - a) / (r - a)
                y = la * (x - xb) * (x - 1) / ((0 - xb) * (0 - 1)) + lb * (x - 0) * (x - 1) / ((xb - 0) * (xb - 1)) + lr * (x - 0) * (x - xb) / ((1 - 0) * (1 - xb))
                curve.append([d[i], round(math.exp(y), 4)])
            shapes = [{"kind": "curve", "d1": d[a], "pts": curve},
                      {"kind": "box", "d1": d[r + 1], "d2": d[e], "lo": min(lo[i] for i in handle), "hi": top_h}]
            res = _finish("Cup & Handle", top_h, e, w, shapes, f"miseczka −{depth * 100:.0f} % w {r - a} tyg., uchwyt {hl} tyg.")
            if res:
                return res
    return None


def _flat_or_triangle(w, e, triangle):
    c, h, lo, v, d = w["c"], w["h"], w["l"], w.get("v") or [], w["d"]
    s30 = sma(c, 30)
    if s30[e] is None or c[e] < s30[e]:
        return None
    for n in range(30, 7, -1):
        s = e - n + 1
        if s < 27:
            continue
        top, bottom = max(h[s:e + 1]), min(lo[s:e + 1])
        if (top - bottom) / top > (0.25 if triangle else 0.12) or c[s - 1] < min(c[s - 27:s]) * 1.2:   # po wzroście ≥ 20 % w poprzednich 26 tyg.
            continue
        third = n // 3
        lows = [min(lo[s + k * third:s + (k + 1) * third]) for k in range(3)]
        rising = lows[0] < lows[1] < lows[2] and lows[2] >= lows[0] * 1.05
        if triangle:
            touches = [i for i in range(s, e + 1) if h[i] >= top * 0.98]
            if not rising or len(touches) < 3 or touches[-1] - touches[0] < 4 or lows[2] > top * 0.97:
                continue
        elif rising:
            continue
        else:
            pre = [x for x in v[s - 10:s] if _ok(x)]
            inside = [x for x in v[s + n // 2:e + 1] if _ok(x)]
            if pre and inside and sum(inside) / len(inside) >= sum(pre) / len(pre):   # wolumen ma wysychać
                continue
        shapes = [{"kind": "box", "d1": d[s], "d2": d[e], "lo": bottom, "hi": top}] if not triangle else [
            {"kind": "line", "d1": d[s], "d2": d[e], "p1": top, "p2": top},
            {"kind": "line", "d1": d[s + third // 2], "d2": d[e], "p1": lows[0], "p2": lows[2]}]
        return _finish("Ascending Triangle" if triangle else "Flat Base", top, e, w, shapes, f"{n} tyg., zakres {(top - bottom) / top * 100:.0f} %")
    return None


def _flag(w, e):
    h, lo, v, d = w["h"], w["l"], w.get("v") or [], w["d"]
    n = len(w["c"])
    for f in range(2, 7):
        t = e - f                                    # szczyt drążka
        if t < 6:
            continue
        for p in range(1, 6):
            pole_lo = min(lo[max(0, t - p):t + 1])
            if h[t] < pole_lo * 1.25 or h[t] < max(h[max(0, t - 4):t + 5]) * 0.999:
                continue
            flag = range(t + 1, e + 1)
            top_f, bot_f = max(h[i] for i in flag), min(lo[i] for i in flag)
            if top_f > h[t] or bot_f < h[t] - 0.5 * (h[t] - pole_lo) or bot_f < h[t] * 0.80:
                continue
            pole_v = [x for x in v[max(0, t - p):t + 1] if _ok(x)]
            flag_v = [v[i] for i in flag if _ok(v[i])]
            if pole_v and flag_v and sum(flag_v) / len(flag_v) >= sum(pole_v) / len(pole_v):   # wolumen kurczy się w pauzie
                continue
            shapes = [{"kind": "line", "d1": d[t - p], "d2": d[t], "p1": pole_lo, "p2": h[t]}, {"kind": "box", "d1": d[t + 1], "d2": d[e], "lo": bot_f, "hi": top_f}]
            buy, first_buy = top_f, None
            if h[e] < h[t + 1]:   # flaga: niższe szczyty -> kupno przy przebiciu opadającej linii (strona: „as the stock goes over the descending trend line”)
                slope = (h[e] - h[t + 1]) / (e - t - 1)
                top_line = lambda i: h[t + 1] + slope * (i - t - 1)   # noqa: E731
                if top_line(n - 1) > 0 and top_line(e + 1) > 0:
                    buy, first_buy = top_line(n - 1), top_line(e + 1)
                    shapes.append({"kind": "line", "d1": d[t + 1], "d2": d[n - 1], "p1": h[t + 1], "p2": buy})
            kind = "proporzec" if lo[e] > lo[t + 1] else "flaga"
            res = _finish("Flaga/Proporzec", buy, e, w, shapes, f"{kind}: drążek +{(h[t] / pole_lo - 1) * 100:.0f} % w {p} tyg., pauza {f} tyg.", first_buy=first_buy)
            if res:
                return res
    return None


def _pivots(vals, high, k=2):
    """Pivoty (lokalne szczyty / dołki ±k tygodni) w całej serii."""
    f = max if high else min
    return [i for i in range(k, len(vals) - k) if vals[i] == f(vals[i - k:i + k + 1])]


def _best_line(idx, lv, upper, s, e, tol=0.02):
    """Linia (w skali log.) przez parę pivotów z [s, e]: górna — żaden szczyt do e nie leży nad nią o więcej niż tol, dolna — żaden dołek pod nią.
    Wybór: najwięcej dotknięć, potem najdłuższy odcinek. -> {a, b, sl (log/tydz.), t (dotknięcia), p (log ceny w a)} albo None."""
    pts = [i for i in idx if s <= i <= e]
    best = None
    for x, a in enumerate(pts):
        for b in pts[x + 1:]:
            if b - a < 3:
                continue
            sl = (lv[b] - lv[a]) / (b - a)
            if upper:
                ok = all(lv[k] <= lv[a] + sl * (k - a) + tol for k in range(a, e + 1))
            else:
                ok = all(lv[k] >= lv[a] + sl * (k - a) - tol for k in range(a, e + 1))
            if not ok:
                continue
            t = sum(1 for q in pts if q >= a and abs(lv[q] - (lv[a] + sl * (q - a))) <= tol)
            if best is None or (t, b - a) > (best[0], best[1]):
                best = (t, b - a, {"a": a, "b": b, "sl": sl, "t": t, "p": lv[a]})
    return best and best[2]


def _at(ln, i):
    return math.exp(ln["p"] + ln["sl"] * (i - ln["a"]))


def _finish_sell(name, level, e, w, shapes, note, first_level=None):
    """Wzorzec niedźwiedzi (ostrzeżenie przy wyjściu): OSTRZEŻENIE (cena do 8 % nad linią) albo ZŁAMANA (zamknięcie pod linią w ostatnich tygodniach, do 10 % pod nią)."""
    c = w["c"]
    post = c[e + 1:]
    last = c[-1]
    fl = level if first_level is None else first_level
    if len(post) > PATTERN_LOOKBACK - 1 or last < max(w["h"][-52:]) * 0.75:
        return None
    state = "ZŁAMANA" if post and post[0] < fl and last < level else "OSTRZEŻENIE"
    pct = (last / level - 1) * 100
    if (state == "OSTRZEŻENIE" and not 0 <= pct <= 8) or (state == "ZŁAMANA" and not -10 <= pct < 0):
        return None
    return {"name": name, "side": "sell", "state": state, "buy": round(level, 4), "pct": round(pct, 2), "start": shapes[0].get("d1") or shapes[0].get("d"), "end": w["d"][e],
            "vol_x": None, "shapes": shapes, "note": note}


def _trend_patterns(w, e, ph, pl):
    """Wzorce z dwóch linii trendu w oknie kończącym się w tygodniu e: Channel, Symmetrical Triangle, Descending Triangle, Falling Wedge (kupno przy
    przebiciu górnej linii) i Rising Wedge (ostrzeżenie przy złamaniu dolnej). Linie z dotknięć pivotów (≥ 2 na stronę), zbieżność = zwężenie o ≥ 25 %."""
    c, h, lo, d = w["c"], w["h"], w["l"], w["d"]
    n_all = len(c)
    hv, lv = w["_lh"], w["_ll"]
    s30 = sma(c, 30)
    found = {}
    for n in (30, 24, 18, 14, 10):
        s = e - n + 1
        if s < 27:
            continue
        up, lw = _best_line(ph, hv, True, s, e), _best_line(pl, lv, False, s, e)
        if not up or not lw or up["t"] < 2 or lw["t"] < 2:
            continue
        s0 = max(up["a"], lw["a"])
        if e - s0 < 0.6 * n:
            continue
        wd0, wd1 = 1 - _at(lw, s0) / _at(up, s0), 1 - _at(lw, e) / _at(up, e)
        if wd1 < 0.02 or wd0 < 0.08:   # zbyt wąski „klin” to zwykła ciasna konsolidacja
            continue
        su, sl_ = up["sl"] * 100, lw["sl"] * 100
        flat = lambda x: abs(x) <= 0.15   # noqa: E731
        conv = wd1 <= 0.75 * wd0
        uptrend = s30[e] is not None and c[e] >= s30[e] and c[s - 1] >= min(c[max(0, s - 26):s]) * 1.15
        name = side = None
        if flat(su) and flat(sl_) and 0.10 <= wd1 <= 0.30 and wd1 >= 0.75 * wd0 and uptrend:
            name, side = "Channel", "buy"
        elif su < -0.15 and sl_ > 0.15 and conv and uptrend:
            name, side = "Symmetrical Triangle", "buy"
        elif flat(sl_) and su < -0.2 and conv and max(h[-52:]) >= min(lo[-52:]) * 1.5:
            name, side = "Descending Triangle", "buy"
        elif su < -0.15 and sl_ < -0.15 and su < sl_ - 0.1 and conv:
            name, side = "Falling Wedge", "buy"
        elif su > 0.15 and sl_ > 0.15 and sl_ > su + 0.1 and conv and uptrend:
            name, side = "Rising Wedge", "sell"
        if not name or name in found:
            continue
        upper = [{"kind": "line", "d1": d[up["a"]], "d2": d[n_all - 1], "p1": _at(up, up["a"]), "p2": _at(up, n_all - 1)}]
        lower = [{"kind": "line", "d1": d[lw["a"]], "d2": d[n_all - 1], "p1": _at(lw, lw["a"]), "p2": _at(lw, n_all - 1)}]
        note = f"{n} tyg., linie {su:+.2f} / {sl_:+.2f} % tygodniowo, zakres {wd1 * 100:.0f} %"
        if side == "buy":
            res = _finish(name, _at(up, n_all - 1), e, w, upper + lower, note, first_buy=_at(up, e + 1),
                          near_high=0.80 if name in ("Descending Triangle", "Falling Wedge") else 0.85)
        else:
            res = _finish_sell(name, _at(lw, n_all - 1), e, w, upper + lower, note, first_level=_at(lw, e + 1))
        if res:
            found[name] = res
    return list(found.values())


def _hs(w, e, ph, pl, inverted):
    """Head & Shoulders (niedźwiedzi, ostrzeżenie: złamanie linii szyi) i Inverted H&S (kupno przy przebiciu linii szyi): 3 kolejne pivoty, głowa o ≥ 5 % ponad / pod
    oboma ramionami, ramiona w 10 % od siebie, linia szyi przez dołki (szczyty) między nimi."""
    c, h, lo, v, d = w["c"], w["h"], w["l"], w.get("v") or [], w["d"]
    n_all = len(c)
    ex = pl if inverted else ph
    val, opp = (lo, h) if inverted else (h, lo)
    cand = [i for i in ex if e - 14 <= i <= e - 2]
    if not cand:
        return None
    p3 = cand[-1]
    prior = [i for i in ex if i < p3]
    if len(prior) < 2:
        return None
    p1, p2 = prior[-2], prior[-1]
    if p2 - p1 < 3 or p3 - p2 < 3 or p3 - p1 > 40 or p1 < 27:
        return None
    sh = (val[p1], val[p3])
    if inverted:
        if not (val[p2] <= min(sh) * 0.95 and abs(sh[0] - sh[1]) / max(sh) <= 0.10 and c[p1] <= max(c[max(0, p1 - 26):p1]) * 0.85):
            return None
        t1, t2 = max(range(p1, p2 + 1), key=lambda i: opp[i]), max(range(p2, p3 + 1), key=lambda i: opp[i])
    else:
        if not (val[p2] >= max(sh) * 1.05 and abs(sh[0] - sh[1]) / max(sh) <= 0.10 and c[p1] >= min(c[max(0, p1 - 26):p1]) * 1.15):
            return None
        t1, t2 = min(range(p1, p2 + 1), key=lambda i: opp[i]), min(range(p2, p3 + 1), key=lambda i: opp[i])
    if t2 == t1:
        return None
    sl = (math.log(opp[t2]) - math.log(opp[t1])) / (t2 - t1)
    neck = lambda i: math.exp(math.log(opp[t1]) + sl * (i - t1))   # noqa: E731
    marks = [{"kind": "mark", "d": d[i], "p": val[i], "text": t, "below": inverted} for i, t in ((p1, "LS"), (p2, "H"), (p3, "RS"))]
    shapes = [{"kind": "line", "d1": d[t1], "d2": d[n_all - 1], "p1": opp[t1], "p2": neck(n_all - 1)}] + marks
    vol = [v[i] for i in (p1, p2, p3)] if len(v) == n_all and all(_ok(x) for x in (v[p1], v[p2], v[p3])) else None
    vnote = (", wolumen głowy mniejszy niż lewego ramienia" if vol[1] < vol[0] else ", wolumen głowy NIE mniejszy") if vol else ""
    note = f"{p3 - p1} tyg., głowa {abs(val[p2] / (min(sh) if inverted else max(sh)) - 1) * 100:.0f} % od ramion{vnote}"
    if inverted:
        return _finish("Inverted H&S", neck(n_all - 1), e, w, shapes, note, first_buy=neck(e + 1), near_high=0.70)
    return _finish_sell("Head & Shoulders", neck(n_all - 1), e, w, shapes, note, first_level=neck(e + 1))


def find_patterns(w):
    """Aktywne wzorce Zangera z tygodniowych świec w: [{name, side (buy / sell), state, buy (poziom: kupna albo linii szyi / dolnej), pct, start, end, vol_x, shapes, note}]
    (kolejność: wybicia / złamania, potem budowane; wzorce kupna przed ostrzeżeniami)."""
    if not w or len(w.get("c") or []) < 40 or not all(_ok(x) and x > 0 for x in w["c"] + w["h"] + w["l"]):
        return []
    n = len(w["c"])
    w = {**w, "_lh": [math.log(x) for x in w["h"]], "_ll": [math.log(x) for x in w["l"]]}
    ph, pl = _pivots(w["h"], True), _pivots(w["l"], False)
    out = []

    def add(res):
        if res and not any(o["name"] == res["name"] or (o["side"] == res["side"] and abs(o["buy"] / res["buy"] - 1) < 0.01) for o in out):
            out.append(res)
    finders = [_cup, lambda w_, e_: _flat_or_triangle(w_, e_, True), lambda w_, e_: _flat_or_triangle(w_, e_, False), _flag,
               lambda w_, e_: _hs(w_, e_, ph, pl, True), lambda w_, e_: _hs(w_, e_, ph, pl, False)]
    for finder in finders:
        for e in range(n - 1, n - 1 - PATTERN_LOOKBACK, -1):
            res = finder(w, e)
            if res:
                add(res)
                break
    for e in range(n - 1, n - 1 - PATTERN_LOOKBACK, -1):
        for res in _trend_patterns(w, e, ph, pl):
            add(res)
    order = PATTERN_NAMES + SELL_PATTERNS
    return sorted(out, key=lambda x: (x["side"] == "sell", x["state"] not in ("WYBICIE", "ZŁAMANA"), order.index(x["name"])))


def _support_lines(lo, start, end):
    """Rosnące linie podparcia przez pary dołków (pivotów) tygodniowych Low w [start, end]: wszystkie Low między kotwicami a `end` leżą nad linią
    (tolerancja 2 %). -> [{a, b, slope (log/tydz.), touches}] — kotwice a < b, linia przedłużona do `end`."""
    piv = [i for i in range(start + 2, end - 1) if lo[i] == min(lo[i - 2:i + 3])]
    out = []
    for x, a in enumerate(piv):
        for b in piv[x + 1:]:
            if b - a < 4:
                continue
            slope = (math.log(lo[b]) - math.log(lo[a])) / (b - a)
            if slope <= 0:
                continue
            if all(math.log(lo[k]) >= math.log(lo[a]) + slope * (k - a) - 0.02 for k in range(a, end + 1)):
                touches = sum(1 for q in piv if q >= a and abs(math.log(lo[q]) - (math.log(lo[a]) + slope * (q - a))) <= 0.03)
                out.append({"a": a, "b": b, "slope": slope, "touches": touches})
    return out


PARABOLA_WEEKS, PARABOLA_MIN_LINES, PARABOLA_STEEPER = 60, 3, 1.15
PARABOLA_CONNECT, PARABOLA_MAX_ABOVE = 0.02, 0.20   # kolejna linia startuje na poprzedniej (±2 %); cena ≤ 20 % nad najbardziej stromą


def parabola(w):
    """Parabolic Curve (chartpattern.com: „schodkowa formacja” kilku baz, każda wyżej i bardziej stroma; ≥ +100 %; sprzedaż po złamaniu NAJBARDZIEJ stromej
    linii, na dużym wolumenie). Szukam łańcucha 3 rosnących linii podparcia na tygodniowych Low z nachyleniem rosnącym o ≥ 15 %, **połączonych** (kotwica każdej kolejnej leży na poprzedniej) i z ceną blisko najbardziej stromej.
    Ostrzeżenie przy wyjściu, nie sygnał kupna: stan TRWA (poziom wyjścia = najbardziej stroma linia dziś) albo ZŁAMANA (zamknięcie tygodnia pod nią w ostatnich 3 tyg.).
    -> {state, n, gain, exit, broken, vol_x, lines: [{d1, p1, d2, p2}], shapes, note} albo None. Progi to przybliżenie opisu (strona nie podaje liczb)."""
    c, h, lo, v, d = (w or {}).get("c") or [], (w or {}).get("h") or [], (w or {}).get("l") or [], (w or {}).get("v") or [], (w or {}).get("d") or []
    n = len(c)
    if n < 40 or not all(_ok(x) and x > 0 for x in c[-PARABOLA_WEEKS:] + lo[-PARABOLA_WEEKS:]):
        return None
    start = max(0, n - PARABOLA_WEEKS)
    cand = [ln for ln in _support_lines(lo[:n - 1], start, n - 2)]   # podparcie liczone do przedostatniego tygodnia; ostatni tydzień to test złamania
    if not cand:
        return None

    def at(ln, i):
        return math.exp(math.log(lo[ln["a"]]) + ln["slope"] * (i - ln["a"]))
    live = [ln for ln in cand if ln["b"] >= n - 22]            # najbardziej stroma musi być świeża (kotwica w ostatnich ~5 miesiącach)
    if not live:
        return None
    def starts_on(prev, ln):
        """Wachlarz jak na schemacie Zangera: kotwica bardziej stromej linii `prev` leży na wcześniejszej, mniej stromej linii `ln` (w granicach 2 %)."""
        return abs(math.log(lo[prev["a"]]) - math.log(at(ln, prev["a"]))) <= PARABOLA_CONNECT

    chain = [max(live, key=lambda ln: ln["slope"])]
    while len(chain) < 3:
        prev = chain[0]
        pool = [ln for ln in cand if ln["a"] < prev["a"] and ln["slope"] * PARABOLA_STEEPER <= prev["slope"] and starts_on(prev, ln)]
        if not pool:
            break
        chain.insert(0, max(pool, key=lambda ln: (ln["touches"], ln["slope"])))
    if len(chain) < PARABOLA_MIN_LINES:
        return None
    steep = chain[-1]
    gain = (max(h[chain[0]["a"]:]) / lo[chain[0]["a"]] - 1) * 100
    if gain < PARABOLA_MIN_GAIN * 100:
        return None
    broken = next((i for i in range(n - 3, n) if c[i] < at(steep, i)), None)
    if broken is None and c[-1] < max(h[-52:]) * 0.85:       # ani złamana, ani blisko szczytu -> to już nie jest końcówka wzrostu
        return None
    if broken is None and c[-1] > at(steep, n - 1) * (1 + PARABOLA_MAX_ABOVE):   # cena daleko nad najbardziej stromą linią (np. po luce) — poziom wyjścia bez sensu
        return None
    base_v = [x for x in v[(broken or n) - 10:(broken or n)] if _ok(x)]
    volx = round(v[broken] / (sum(base_v) / len(base_v)), 2) if broken is not None and base_v and _ok(v[broken]) and sum(base_v) > 0 else None
    lines = [{"d1": d[ln["a"]], "p1": round(lo[ln["a"]], 4), "d2": d[n - 1], "p2": round(at(ln, n - 1), 4)} for ln in chain]
    shapes = [{"kind": "line", "d1": ln["d1"], "d2": ln["d2"], "p1": ln["p1"], "p2": ln["p2"], "label": str(k + 1)} for k, ln in enumerate(lines)]
    exit_lvl = lines[-1]["p2"]
    state = "ZŁAMANA" if broken is not None else "TRWA"
    note = (f"{len(chain)} rosnące linie (każda bardziej stroma), +{gain:.0f} % od początku; " +
            (f"ZŁAMANA najbardziej stroma linia ({d[broken]}" + (f", wolumen {volx:.1f}×" if volx is not None else "") + ") — sprzedaż"
             if broken is not None else f"wyjście: zamknięcie tygodnia pod najbardziej stromą linią {exit_lvl:.2f}"))
    return {"state": state, "n": len(chain), "gain": round(gain, 1), "exit": exit_lvl, "broken": d[broken] if broken is not None else None, "vol_x": volx,
            "lines": lines, "shapes": shapes, "note": note}


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
    row["cc52w"] = price_ratio(c)
    bdot = fresh_blue_dot(weekly, level) if row["glb_state"] == "NAD" else None   # > 10 % nad linią, nie tydzień przebicia: wejście po Blue Dot na tygodniowym
    if bdot:
        row["glb_state"], row["bdot"] = "BLUE DOT", bdot
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
    pats = find_patterns(weekly)
    para = parabola(weekly)
    top = next((p for p in pats if p["side"] == "buy"), None)
    warn = next((p for p in pats if p["side"] == "sell"), None)
    row.update(pattern=top["name"] if top else None, pattern_state=top["state"] if top else None, pattern_buy=top["buy"] if top else None,
               pattern_pct=top["pct"] if top else None, pattern_exit=warn["name"] if warn else ("Parabolic Curve" if para else None),
               patterns=pats, parabola=para)   # wzorce Zangera: kolumny + rysunek na wykresie; pattern_exit = ostrzeżenie (H&S / Rising Wedge / parabola)
    row["ok"] = passes(row, conditions)
    row["slow"] = slowdown(row)
    return row
