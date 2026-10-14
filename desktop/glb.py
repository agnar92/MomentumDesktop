"""Green Line Breakout (dr Eric Wish) na wykresie MIESIĘCZNYM, na zamknięciach — w uproszczeniu to „top Darvasa” z wykresu miesięcznego.
Zielona linia = najwyższe zamknięcie miesięczne w całej historii (ATH), którego przez co najmniej `confirm_months` kolejnych miesięcy nikt nie pobił.
Wybicie = zamknięcie miesiąca (liczone też bieżący, jeszcze trwający miesiąc) powyżej tej linii, czyli nowy szczyt wszech czasów po konsolidacji.
Progi (3 miesiące, „za późno” +10 %) to moje przybliżenie reguł Wisha, trzymane w jednym miejscu (DEFAULTS) i zmieniane w edytorze skanu."""
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


def fetch_monthly(tickers, log=print, batch=50):
    """Miesięczne zamknięcia z całej historii z yfinance (interval 1mo, okres max): {ticker: {"d": [daty], "c": [zamknięcia]}}. Błędy partii nie przerywają."""
    import yfinance as yf
    out, tickers = {}, sorted(set(tickers))
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
            log(f"⚠️  Dane miesięczne (partia {i // batch + 1}) niedostępne: {e}")
    return out


def apply(data_dir, cfg, log=print, fetch=fetch_monthly):
    """Po Sync: pobiera dane miesięczne dla spółek skanera, liczy zieloną linię i dopisuje pola glb_* do watchlist.json (+ monthly.json)."""
    path = data_dir / "watchlist.json"
    wl = store.read_json(path, {}) or {}
    stocks = wl.get("stocks") or []
    if not stocks:
        return 0
    log(f"Green Line Breakout: pobieram miesięczne zamknięcia z całej historii dla {len(stocks)} spółek…")
    monthly = fetch([s["ticker"] for s in stocks], log)
    n = 0
    for s in stocks:
        m = monthly.get(s["ticker"])
        res = analyze(m["c"], cfg) if m else {"glb_state": "NONE", "glb_level": None, "glb_dist_pct": None, "glb_months": None, "glb_rank": 9}
        s.update(res)
        n += res["glb_state"] in ("BREAK", "AFTER", "LATE")
    store.write_json(path, wl)
    store.write_json(data_dir / "monthly.json", monthly)
    counts = {}
    for s in stocks:
        counts[s["glb_state"]] = counts.get(s["glb_state"], 0) + 1
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
