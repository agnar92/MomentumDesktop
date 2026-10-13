"""Skaner „Qullamaggie”: prosty filtr po cenie — obrót dzienny (cena × wolumen), ADR i relacja ceny do najniższego Low z okna (1 / 3 / 6 miesięcy
≈ 22 / 66 / 132 sesje). Ta sama reguła co w Momentum (qullamaggieRows): z płynnych spółek (obrót ≥ próg, ADR ≥ próg) bierzemy górne X % rankingu
cena / min Low osobno dla każdego okna, wynik to suma (unikalne spółki) — spółka pamięta, w których oknach się załapała.

Dwa poziomy progów:
- „pobieranie” (keep_*): co zostaje na dysku po Sync — szerokie, żeby progi na liście można było zmieniać BEZ ponownego pobierania;
- „lista” (min_*, top_pct, windows): co widać na liście; zmieniane na bieżąco (Qullamaggie…).
"""
import math

WINDOWS = {"1m": ("low_ratio_1m", "1M"), "3m": ("low_ratio_3m", "3M"), "6m": ("low_ratio_6m", "6M")}
DEFAULTS = {"min_dollar_mln": 50.0, "min_adr": 3.0, "top_pct": 10.0, "windows": ["1m", "3m", "6m"], "keep_dollar_mln": 25.0, "keep_adr": 2.0, "two_stage": True}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _f(v, default):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return default


def normalize(cfg):
    cfg = cfg or {}
    out = {k: _f(cfg.get(k), DEFAULTS[k]) for k in ("min_dollar_mln", "min_adr", "top_pct", "keep_dollar_mln", "keep_adr")}
    wins = [w for w in (cfg.get("windows") or DEFAULTS["windows"]) if w in WINDOWS]
    out["windows"] = wins or list(DEFAULTS["windows"])
    out["top_pct"] = min(100.0, max(0.0, out["top_pct"]))
    out["two_stage"] = DEFAULTS["two_stage"] if cfg.get("two_stage") is None else bool(cfg["two_stage"])
    return out


def below_keep(cfg):
    """True, gdy progi listy są niższe niż progi pobierania — wtedy część spółek nie została zapisana (trzeba obniżyć próg pobierania i zrobić Sync)."""
    c = normalize(cfg)
    return c["min_dollar_mln"] < c["keep_dollar_mln"] or c["min_adr"] < c["keep_adr"]


def liquid(rows, cfg):
    return [r for r in rows if _num(r.get("dollar_volume_avg")) is not None and _num(r.get("adr_pct")) is not None
            and r["dollar_volume_avg"] >= cfg["min_dollar_mln"] * 1e6 and r["adr_pct"] >= cfg["min_adr"]]


def select(rows, cfg, universe_pool=None):
    """{ticker: [okna]} — płynne spółki, które są w górnych top_pct % rankingu cena / min Low w co najmniej jednym wybranym oknie.
    universe_pool (szybki Sync dwuetapowy): górne X % liczone od WIELKOŚCI CAŁEGO płynnego zbioru z Finviz, a nie od zapisanych kandydatów
    (inaczej ranking byłby zawyżony, bo kandydaci to już sama czołówka)."""
    cfg = normalize(cfg)
    pool = liquid(rows, cfg)
    picked = {}
    if cfg["top_pct"] <= 0:
        return picked
    n_pool = pool_size(universe_pool, cfg) if universe_pool else None
    for w in cfg["windows"]:
        key = WINDOWS[w][0]
        ranked = sorted((r for r in pool if _num(r.get(key)) is not None), key=lambda r: r[key], reverse=True)
        base = n_pool if n_pool else len(ranked)
        take = min(len(ranked), max(1, math.ceil(base * cfg["top_pct"] / 100))) if ranked else 0
        for r in ranked[:take]:
            picked.setdefault(r["ticker"], []).append(w)
    return picked


def annotate(row, windows):
    """Pola do kolumn: w których oknach spółka jest w górnych X % i największa z ich relacji cena / min Low."""
    row["qm_windows"] = " ".join(WINDOWS[w][1] for w in WINDOWS if w in windows)
    ratios = [row[WINDOWS[w][0]] for w in windows if _num(row.get(WINDOWS[w][0])) is not None]
    row["qm_max_ratio"] = max(ratios) if ratios else None


def keep(rows, cfg):
    """Spółki zostające na dysku po Sync (próg pobierania)."""
    cfg = normalize(cfg)
    k = {**cfg, "min_dollar_mln": cfg["keep_dollar_mln"], "min_adr": cfg["keep_adr"]}
    return liquid(rows, k)


DEFAULT_COLUMNS = ["ticker", "flag", "company", "price", "dollar_volume_avg", "adr_pct", "low_ratio_1m", "low_ratio_3m", "low_ratio_6m", "qm_windows", "qm_max_ratio",
                   "darvas", "pbox", "change", "sector"]
AVGVOL_LEVELS = (100, 200, 300, 500, 1000)   # progi średniego wolumenu (tys.), które ma Finviz
MAX_SAFE_PRICE = 150.0                        # do tej ceny filtr wolumenu Finviz niczego nie obcina: cena × wolumen ≥ próg pobierania


def suggest_filters(cfg):
    """Wstępny filtr Finviz dla progów pobierania: tnie tylko to, co na pewno nie przejdzie obrotu / ADR, więc nie ogranicza wyniku.
    Średni wolumen: najwyższy próg Finviz, przy którym spółki do ceny MAX_SAFE_PRICE z wymaganym obrotem go przekraczają
    (obrót 25 mln $ przy cenie 150 $ = 167 tys. akcji, więc próg 100 tys.). Zmienność miesiąca Finviz ≈ ADR; próg filtra bierzemy o 1 pkt niżej dla zapasu."""
    c = normalize(cfg)
    need_k = c["keep_dollar_mln"] * 1e6 / MAX_SAFE_PRICE / 1000   # wymagany wolumen (tys. akcji) dla spółki po MAX_SAFE_PRICE
    level = max([lv for lv in AVGVOL_LEVELS if lv <= need_k] or [AVGVOL_LEVELS[0]])
    codes = ["cap_smallover", "ind_stocksonly", f"sh_avgvol_o{level}", "sh_price_o10"]
    vol = int(math.floor(c["keep_adr"] - 1))
    if vol >= 2:
        codes.append(f"ta_volatility_mo{min(vol, 5)}")
    return ",".join(codes)


# ---------- szybki Sync dwuetapowy: etap 1 = tylko Finviz (przybliżenia), etap 2 = ceny tylko kandydatów ----------
# Pomiar na sektorze Technology (380 spółek): Finviz „Volatility M” ≈ ADR (różnica mediana −0,02), obrót cena × „Avg Volume” ≈ obrót z 20 sesji
# (mediana 0,97×), więc wielkość płynnego zbioru liczymy wprost; zapas stosujemy tylko przy wyborze kandydatów.
PROXY_ADR_OFFSET = 0.5    # zapas przy wyborze kandydatów
PROXY_DOLLAR_SLACK = 0.7
CAND_FACTOR = 2.0         # z każdego rankingu bierzemy 2× więcej, niż wynika z górnych X % (ranking z Finviz tylko przybliża cena / min Low)
CAND_MIN = 60             # co najmniej tyle kandydatów z jednego rankingu
CAND_MIN_PCT = 10.0       # liczone dla co najmniej tylu % (żeby podniesienie „górnych %” na liście miało z czego brać)
# rankingi przybliżające cena / min Low: zwrot 1M; zwrot 3M i odległość od minimum 50 dni; zwrot 6M i odległość od minimum 52 tygodni
PROXY_KEYS = ("p1m", "p3m", "d50low", "p6m", "w52low")
UNIVERSE_COLUMNS = {"Company": "company", "Sector": "sector", "Industry": "industry", "Market Cap": "market_cap", "Price": "price",
                    "Perf Month": "p1m", "Perf Quart": "p3m", "Perf Half": "p6m", "Volatility M": "vol_m", "Avg Volume": "avgvol",
                    "50D Low": "d50low", "52W Low": "w52low"}
UNIVERSE_IDS = "0,1,2,3,4,6,43,44,45,51,63,65,56,58"   # numery kolumn widoku własnego Finviz (Company, Sector, Industry, Market Cap, Perf M/Q/H, Volatility M, Avg Volume, Price, 50D Low, 52W Low)


def _proxy_liquid(u, dollar_mln, adr):
    price, vol, vm = _num(u.get("price")), _num(u.get("avgvol")), _num(u.get("vol_m"))
    return None not in (price, vol, vm) and price * vol >= dollar_mln * 1e6 * PROXY_DOLLAR_SLACK and vm >= adr - PROXY_ADR_OFFSET


def pool_pairs(universe):
    """Zwięzły zapis całego zbioru z Finviz do pliku: [[przybliżony obrót, zmienność mies.]] — służy do policzenia, ile spółek jest „płynnych”."""
    return [[round(u["price"] * u["avgvol"]), u["vol_m"]] for u in universe if None not in (_num(u.get("price")), _num(u.get("avgvol")), _num(u.get("vol_m")))]


def pool_size(pairs, cfg):
    c = normalize(cfg)
    return sum(1 for dv, vm in pairs or [] if dv >= c["min_dollar_mln"] * 1e6 and vm >= c["min_adr"])


def candidates(universe, cfg):
    """Etap 1: z całego zbioru Finviz wybiera kandydatów do pobrania cen — płynne (w przybliżeniu) spółki z czołówki rankingu zwrotów
    (zwroty i odległości od minimów ≈ cena / min Low) w którymkolwiek z pięciu rankingów. -> lista wierszy Finviz."""
    c = normalize(cfg)
    pool = [u for u in universe if _proxy_liquid(u, c["keep_dollar_mln"], c["keep_adr"])]
    pct = max(c["top_pct"], CAND_MIN_PCT)
    n = max(CAND_MIN, math.ceil(len(pool) * pct / 100 * CAND_FACTOR))
    chosen = set()
    for key in PROXY_KEYS:
        ranked = sorted((u for u in pool if _num(u.get(key)) is not None), key=lambda u: u[key], reverse=True)
        chosen.update(u["ticker"] for u in ranked[:n])
    return [u for u in pool if u["ticker"] in chosen]
