"""Green Line Breakout (dr Eric Wish) na wykresie MIESIĘCZNYM, na zamknięciach — w uproszczeniu to „top Darvasa” z wykresu miesięcznego.
Zielona linia = najwyższe zamknięcie miesięczne w całej historii (ATH), którego przez co najmniej `confirm_months` kolejnych miesięcy nikt nie pobił.
Wybicie = zamknięcie miesiąca (liczone też bieżący, jeszcze trwający miesiąc) powyżej tej linii, czyli nowy szczyt wszech czasów po konsolidacji.
Progi (3 miesiące, „za późno” +10 %) to moje przybliżenie reguł Wisha, trzymane w jednym miejscu (DEFAULTS) i zmieniane w edytorze skanu."""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import store

DEFAULTS = {"confirm_months": 3, "late_pct": 10.0, "recent_months": 6}
STATE_LABELS = {"BREAK": "WYBICIE", "AFTER": "po wybiciu", "LATE": "za późno", "WAIT": "czeka", "NONE": ""}
STATE_RANK = {"BREAK": 0, "AFTER": 1, "WAIT": 2, "LATE": 3, "NONE": 9}


def normalize(cfg):
    cfg = cfg if isinstance(cfg, dict) else {}
    out = dict(DEFAULTS)
    for k, kind in (("confirm_months", int), ("late_pct", float), ("recent_months", int)):
        try:
            v = kind(cfg.get(k, DEFAULTS[k]))
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[k] = v
    return out


def _argmax(values):
    """Indeks największej wartości (przy remisie — najpóźniejszy)."""
    return max(range(len(values)), key=lambda i: (values[i], i))


def analyze(closes, cfg=None):
    """Zielona linia i stan ostatniego miesiąca: {glb_state, glb_level, glb_dist_pct (linia / cena − 1, minus = cena nad linią), glb_months, glb_rank}.
    BREAK = wybicie w tym miesiącu, AFTER = wybicie w ostatnich miesiącach i cena nadal nad linią, LATE = jak AFTER, ale > late_pct nad linią,
    WAIT = linia jest potwierdzona, cena pod nią (albo wróciła pod nią), NONE = brak linii (ciągłe nowe szczyty albo za mało danych)."""
    cfg = normalize(cfg)
    confirm, late, recent = cfg["confirm_months"], cfg["late_pct"], cfg["recent_months"]
    c = [float(x) for x in closes if isinstance(x, (int, float)) and x == x and x > 0]
    n = len(c)
    none = {"glb_state": "NONE", "glb_level": None, "glb_dist_pct": None, "glb_months": None, "glb_rank": STATE_RANK["NONE"]}
    if n < confirm + 2:
        return none
    last = c[-1]
    state = level = months = None
    for j in range(n - 1, max(0, n - 1 - recent) - 1, -1):   # najświeższe wybicie z ostatnich miesięcy
        prev = c[:j]
        if not prev:
            break
        p = _argmax(prev)
        if c[j] > prev[p] and j - p - 1 >= confirm:   # nowy szczyt po ≥ confirm miesiącach, w których poprzedni nie został pobity
            level, months = prev[p], n - 1 - j
            if j == n - 1:
                state = "BREAK"
            elif last > level:
                state = "LATE" if (last / level - 1) * 100 > late else "AFTER"
            else:
                state = "WAIT"   # po wybiciu cena wróciła pod linię
            break
    if state is None:
        p = _argmax(c)
        if n - 1 - p >= confirm:   # szczyt wszech czasów sprzed ≥ confirm miesięcy: linia potwierdzona, czekamy na jej przebicie
            state, level, months = "WAIT", c[p], n - 1 - p
        else:
            return none
    return {"glb_state": state, "glb_level": round(level, 4), "glb_dist_pct": round((level / last - 1) * 100, 2), "glb_months": months,
            "glb_rank": STATE_RANK[state]}


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


def fetch_monthly(tickers, log=print, workers=WORKERS):
    """Miesięczne zamknięcia z całej historii: {ticker: {"d": [daty], "c": [zamknięcia]}}. Równolegle (jedno lekkie zapytanie na spółkę, ~0,3 s,
    16 wątków ⇒ ok. 20 s na 1000 spółek); spółki, których nie udało się pobrać, dopobiera yfinance partiami. Błędy pojedynczych spółek nie przerywają."""
    import requests
    tickers = sorted(set(tickers))
    out, failed, done = {}, [], [0]
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"

    def work(t):
        try:
            return t, _fetch_one(session, t)
        except Exception:   # noqa: BLE001
            return t, None
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for t, res in pool.map(work, tickers):
            done[0] += 1
            if res:
                out[t] = {"d": res[0], "c": res[1]}
            else:
                failed.append(t)
            if done[0] % 250 == 0:
                log(f"  dane miesięczne: {done[0]}/{len(tickers)} ({time.time() - t0:.0f} s)")
    if failed:
        out.update(_fetch_yfinance(failed, log))
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
    więc pobieramy tylko nowe spółki i te, którym brakuje ostatniego zakończonego miesiąca (raz na miesiąc); bieżący miesiąc = aktualna cena z Sync."""
    path = data_dir / "watchlist.json"
    wl = store.read_json(path, {}) or {}
    stocks = wl.get("stocks") or []
    if not stocks:
        return 0
    cur = (today or datetime.now()).strftime("%Y-%m")
    prev = _prev_month(cur)
    cache = store.read_json(data_dir / "monthly.json", {}) or {}
    need = [s["ticker"] for s in stocks if s["ticker"] not in cache or (cache[s["ticker"]].get("through") or "") < prev]
    if need:
        log(f"Green Line Breakout: pobieram miesięczne zamknięcia z całej historii dla {len(need)} spółek (z {len(stocks)}; reszta z pamięci podręcznej)…")
        for t, m in fetch(need, log).items():
            d, c = m.get("d") or [], m.get("c") or []
            keep = [i for i, x in enumerate(d) if x[:7] < cur] if d else list(range(len(c)))   # bez trwającego miesiąca — jego cenę dajemy z Sync
            cache[t] = {"d": [d[i] for i in keep] if d else [], "c": [c[i] for i in keep], "through": (d[keep[-1]][:7] if d and keep else "9999-99")}
    else:
        log("Green Line Breakout: dane miesięczne w pamięci podręcznej są aktualne — liczę bez pobierania.")
    n, counts = 0, {}
    for s in stocks:
        m = cache.get(s["ticker"])
        price = s.get("price")
        closes = (m["c"] + ([price] if isinstance(price, (int, float)) and price > 0 else [])) if m else []
        res = analyze(closes, cfg) if closes else {"glb_state": "NONE", "glb_level": None, "glb_dist_pct": None, "glb_months": None, "glb_rank": 9}
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
