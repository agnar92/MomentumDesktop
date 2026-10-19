"""Green Line Breakout (dr Eric Wish) — logika jak w Momentum (watchlist.py: glb_line / glb_state, po backteście na S&P 500 2015–2026).
Zielona linia = rekord wszech czasów na ZAMKNIĘTYCH miesiącach, który stoi ≥ `confirm_months` (3) zamknięte miesiące. Po nowym rekordzie
obowiązuje stara (przebita) linia, dopóki nowy rekord nie przestoi 3 miesięcy — ponowne przebicie starej linii to ponowne wejście.
Wejście i wyjście są TYGODNIOWE: stan liczymy na zamknięciu tygodnia (kupno stop na linii, stop 1 % pod linią na zamknięciu tygodnia,
potem przesuwanie stopu po tygodniowym MACD). Kupujemy, gdy tydzień zamknął się nad linią najwyżej `late_pct` (5 %) nad nią."""
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone

from . import store

DEFAULTS = {"confirm_months": 3, "late_pct": 5.0, "recent_months": 6, "max_from_high_pct": 35.0}   # recent_months: już nieużywane (zgodność zapisanych skanów)
STOP_PCT = 1.0          # stop 1 % pod linią (sprawdzany na zamknięciu tygodnia)
STATE_LABELS = {"BREAK": "WYBICIE", "AFTER": "nad linią", "LATE": "za daleko", "WAIT": "czeka", "NONE": ""}
STATE_RANK = {"BREAK": 0, "AFTER": 1, "WAIT": 2, "LATE": 3, "NONE": 9}


def normalize(cfg):
    cfg = cfg if isinstance(cfg, dict) else {}
    out = dict(DEFAULTS)
    for k, kind in (("confirm_months", int), ("late_pct", float), ("recent_months", int), ("max_from_high_pct", float)):
        try:
            v = kind(cfg.get(k, DEFAULTS[k]))
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[k] = v
    return out


def line(months, confirm=DEFAULTS["confirm_months"]):
    """Green line z ZAMKNIĘTYCH miesięcy (lista zamknięć, kolejne miesiące): (poziom, indeks miesiąca rekordu) albo (None, None).
    Rekord wszech czasów staje się linią, gdy przestoi `confirm` miesięcy; nowszy rekord zastępuje ją dopiero po swoich `confirm` miesiącach."""
    level = at = None
    mx, mi = float("-inf"), None
    for i, c in enumerate(months):
        if c > mx:
            mx, mi = c, i
        if i - mi >= confirm:
            level, at = mx, mi
    return level, at


def analyze(closes, cfg=None, weekly=None, price=None):
    """closes = ZAMKNIĘTE miesiące (bez trwającego); weekly = zamknięcia tygodniowe (ostatnie = bieżący tydzień), price = cena, gdy brak tygodniowych.
    -> {glb_state, glb_level, glb_dist_pct (linia / cena − 1, minus = cena nad linią), glb_months (ile miesięcy stoi linia), glb_stop, glb_rank}.
    WAIT = cena pod linią (zlecenie kupna stop na linii), BREAK = ten tydzień zamknął się nad linią (poprzedni nie), AFTER = nad linią
    ≤ late_pct, LATE = dalej niż late_pct nad linią (nie gonimy), NONE = brak linii."""
    cfg = normalize(cfg)
    c = [float(x) for x in closes if isinstance(x, (int, float)) and x == x and x > 0]
    none = {"glb_state": "NONE", "glb_level": None, "glb_dist_pct": None, "glb_months": None, "glb_stop": None, "glb_rank": STATE_RANK["NONE"]}
    level, at = line(c, cfg["confirm_months"])
    w = [float(x) for x in (weekly or []) if isinstance(x, (int, float)) and x == x and x > 0]
    if not w and isinstance(price, (int, float)) and price > 0:
        w = ([c[-1]] if c else []) + [float(price)]   # bez tygodniowych: poprzednim punktem jest ostatni zamknięty miesiąc
    if level is None or not w:
        return none
    px, prev = w[-1], (w[-2] if len(w) > 1 else None)
    if px < level:
        state = "WAIT"
    elif prev is not None and prev <= level:
        state = "BREAK"
    else:
        state = "LATE" if (px / level - 1) * 100 > cfg["late_pct"] else "AFTER"
    return {"glb_state": state, "glb_level": round(level, 4), "glb_dist_pct": round((level / px - 1) * 100, 2), "glb_months": len(c) - 1 - at,
            "glb_stop": round(level * (1 - STOP_PCT / 100), 4), "glb_rank": STATE_RANK[state]}


CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
WORKERS = 16


def _fetch_one(session, ticker):
    """Miesięczne zamknięcia (skorygowane) jednej spółki prosto z API wykresów Yahoo: (daty, zamknięcia) albo None."""
    for attempt in (1, 2):
        r = session.get(CHART_URL.format(ticker), params={"range": "max", "interval": "1mo", "includeAdjustedClose": "true"}, timeout=15)
        if r.status_code == 429 and attempt == 1:   # limit zapytań: jedna krótka pauza i ponowna próba
            time.sleep(1.0)
            continue
        if r.status_code != 200:
            return None
        res = ((r.json().get("chart") or {}).get("result") or [None])[0]
        if not res or not res.get("timestamp"):
            return None
        ind = res.get("indicators") or {}
        closes = ((ind.get("adjclose") or [{}])[0].get("adjclose")) or ((ind.get("quote") or [{}])[0].get("close")) or []
        pairs = [(datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"), float(c)) for t, c in zip(res["timestamp"], closes) if c is not None]
        return ([d for d, _ in pairs], [round(c, 4) for _, c in pairs]) if pairs else None
    return None


BUDGET_S = 120        # twardy limit czasu pobierania danych miesięcznych — po nim liczymy z tego, co jest (Sync nigdy nie wisi)
FALLBACK_MAX = 100    # zapasowy, wolny yfinance tylko dla niewielu spółek; przy masowych błędach (limit zapytań) pomijamy go


def fetch_monthly(tickers, log=print, workers=WORKERS, budget=BUDGET_S):
    """Miesięczne zamknięcia z całej historii: {ticker: {"d": [daty], "c": [zamknięcia]}}. Równolegle (jedno lekkie zapytanie na spółkę, ~0,3 s,
    16 wątków), z twardym limitem czasu `budget`: spółki, które nie zdążą się pobrać, zostają bez linii (kolejny Sync je dociągnie z pamięci podręcznej).
    Niewielką liczbę spółek, których API nie zwróciło, dopobiera yfinance; przy masowych błędach (np. limit zapytań Yahoo) tego nie robimy."""
    import requests
    tickers = sorted(set(tickers))
    out, failed = {}, []
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    adapter = requests.adapters.HTTPAdapter(pool_connections=workers, pool_maxsize=workers)
    session.mount("https://", adapter)

    def work(t):
        try:
            return t, _fetch_one(session, t)
        except Exception:   # noqa: BLE001
            return t, None
    t0 = time.time()
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = [pool.submit(work, t) for t in tickers]
    pending, done_n = set(futures), 0
    while pending and time.time() - t0 < budget:
        done, pending = wait(pending, timeout=max(0.1, min(5, budget - (time.time() - t0))), return_when=FIRST_COMPLETED)
        for f in done:
            t, res = f.result()
            done_n += 1
            if res:
                out[t] = {"d": res[0], "c": res[1]}
            else:
                failed.append(t)
        if done_n and done_n % 250 < len(done) or (done and not pending):
            log(f"  dane miesięczne: {done_n}/{len(tickers)} ({time.time() - t0:.0f} s)")
    timed_out = len(pending)
    pool.shutdown(wait=False, cancel_futures=True)   # nie czekamy na wiszące zapytania
    if timed_out:
        log(f"⚠️  Dane miesięczne: limit czasu {budget} s — {timed_out} spółek bez danych (zostaną dociągnięte przy kolejnym Syncu).")
    if failed and len(failed) <= FALLBACK_MAX and time.time() - t0 < budget:
        out.update(_fetch_yfinance(failed, log))
    elif failed:
        log(f"⚠️  Dane miesięczne: {len(failed)} spółek bez odpowiedzi API (np. limit zapytań Yahoo) — pomijam wolną ścieżkę zapasową.")
    log(f"  dane miesięczne: {len(out)}/{len(tickers)} spółek w {time.time() - t0:.0f} s")
    return out


def _fetch_yfinance(tickers, log=print, batch=50):
    """Zapasowa ścieżka (wolniejsza): yfinance partiami."""
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), batch):
        part = tickers[i:i + batch]
        try:
            df = yf.download(part, period="max", interval="1mo", auto_adjust=True, group_by="ticker", progress=False, threads=True)
            for t in part:
                try:
                    s = (df[t] if len(part) > 1 else df)["Close"].dropna()
                except (KeyError, TypeError):
                    continue
                if len(s):
                    out[t] = {"d": [d.strftime("%Y-%m-%d") for d in s.index], "c": [round(float(x), 4) for x in s.values]}
        except Exception as e:   # noqa: BLE001 — jedna zła partia nie zatrzymuje reszty
            log(f"⚠️  Dane miesięczne (yfinance, partia {i // batch + 1}) niedostępne: {e}")
    return out


def _prev_month(cur):
    y, m = int(cur[:4]), int(cur[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def apply(data_dir, cfg, log=print, fetch=fetch_monthly, today=None):
    """Po Sync: dopisuje pola glb_* do watchlist.json. Historia miesięczna jest w pamięci podręcznej (monthly.json): zakończone miesiące się nie zmieniają,
    więc pobieramy tylko nowe spółki i te, którym brakuje ostatniego zakończonego miesiąca (raz na miesiąc). Linia = tylko zamknięte miesiące,
    stan = tygodniowe zamknięcia z charts.json (bez nich: cena z Sync wobec ostatniego zamkniętego miesiąca)."""
    path = data_dir / "watchlist.json"
    wl = store.read_json(path, {}) or {}
    stocks = wl.get("stocks") or []
    if not stocks:
        return 0
    cur = (today or datetime.now()).strftime("%Y-%m")
    prev = _prev_month(cur)
    cache = store.read_json(data_dir / "monthly.json", {}) or {}
    cfgn = normalize(cfg)

    def near_high(s):   # szczyt wszech czasów ≥ szczyt 52 tyg., więc spółka głęboko pod nim nie może być przy linii — nie pobieramy dla niej historii
        d = s.get("pct_from_high_52w")
        return not isinstance(d, (int, float)) or d >= -cfgn["max_from_high_pct"]
    cand = [s for s in stocks if near_high(s)]
    log(f"Green Line Breakout: {len(cand)} z {len(stocks)} spółek jest nie dalej niż {cfgn['max_from_high_pct']:g} % pod szczytem 52 tygodni — tylko one są analizowane.")
    need = [s["ticker"] for s in cand if s["ticker"] not in cache or (cache[s["ticker"]].get("through") or "") < prev]
    if need:
        log(f"Green Line Breakout: pobieram miesięczne zamknięcia z całej historii dla {len(need)} spółek (reszta z pamięci podręcznej; limit czasu {BUDGET_S} s)…")
        for t, m in fetch(need, log).items():
            d, c = m.get("d") or [], m.get("c") or []
            keep = [i for i, x in enumerate(d) if x[:7] < cur] if d else list(range(len(c)))   # bez trwającego miesiąca — jego cenę dajemy z Sync
            cache[t] = {"d": [d[i] for i in keep] if d else [], "c": [c[i] for i in keep], "through": (d[keep[-1]][:7] if d and keep else "9999-99")}
    else:
        log("Green Line Breakout: dane miesięczne w pamięci podręcznej są aktualne — liczę bez pobierania.")
    weekly = (store.read_json(data_dir / "charts.json", {}) or {}).get("stocks") or {}   # stan liczymy na zamknięciach TYGODNIOWYCH
    n, counts = 0, {}
    for s in stocks:
        m = cache.get(s["ticker"]) if near_high(s) else None
        wk = (weekly.get(s["ticker"]) or {}).get("c")
        res = analyze(m["c"], cfg, weekly=wk, price=s.get("price")) if m else analyze([], cfg)
        s.update(res)
        n += res["glb_state"] in ("BREAK", "AFTER", "LATE")
        counts[res["glb_state"]] = counts.get(res["glb_state"], 0) + 1
    store.write_json(path, wl)
    store.write_json(data_dir / "monthly.json", cache)
    log("✅ Green Line Breakout: " + ", ".join(f"{STATE_LABELS.get(k) or 'brak linii'} {v}" for k, v in sorted(counts.items(), key=lambda kv: STATE_RANK[kv[0]])))
    return n


def select(rows, rule):
    """Kryterium watchlisty „Wish GLB”: spółki w wybranych stanach (domyślnie wybicie, po wybiciu, czeka); stan „czeka” tylko do `max_dist_pct` pod linią."""
    states = [x for x in (rule or {}).get("states") or ("BREAK", "AFTER", "WAIT") if x in STATE_RANK and x != "NONE"]
    try:
        max_dist = float((rule or {}).get("max_dist_pct", 10))
    except (TypeError, ValueError):
        max_dist = 10.0
    out = []
    for r in rows:
        st = r.get("glb_state")
        if st not in states:
            continue
        if st == "WAIT" and not (isinstance(r.get("glb_dist_pct"), (int, float)) and r["glb_dist_pct"] <= max_dist):
            continue
        out.append(r)
    return out
