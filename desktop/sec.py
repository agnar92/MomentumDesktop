"""Fundamenty z SEC EDGAR (darmowe API companyfacts, raporty 10-Q / 10-K): przychody, zysk operacyjny i brutto.
Z ostatniego kwartału liczymy: przychody r/r, marżę operacyjną i jej zmianę r/r oraz zmianę marży brutto r/r. (ROE i ROI sprawdzone w backteście
nie pomagały — duzi zwycięzcy mieli niskie ROE, bo dopiero przechodzili na zysk — więc ich nie liczymy.)
Pamięć podręczna: wynik spółki odświeżamy co FRESH_DAYS dni (raporty są kwartalne). SEC wymaga nagłówka User-Agent z kontaktem —
ustaw własny w Ustawieniach (domyślny jest ogólny)."""
import datetime as dt
import json
import time
import urllib.request

UA = "MomentumDesktop research@example.com"
FRESH_DAYS = 7
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json"
TAGS = {
    "rev": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenue"],
    "gp": ["GrossProfit"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfSales"],
    "op": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
}


def _get(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def cik_map(ua=UA):
    return {v["ticker"].upper(): int(v["cik_str"]) for v in _get(TICKERS_URL, ua).values()}


def _durations(facts, tags, unit="USD"):
    """Wartości okresowe: {koniec okresu: wartość} dla kwartałów (80–100 dni); Q4 = rok − 3 kwartały, gdy raport roczny nie podaje kwartału."""
    q, fy = {}, {}
    for tax in ("us-gaap", "ifrs-full"):
        for tag in tags:
            for x in (facts.get(tax, {}).get(tag) or {}).get("units", {}).get(unit, []):
                if "start" not in x:
                    continue
                s, e = dt.date.fromisoformat(x["start"]), dt.date.fromisoformat(x["end"])
                days = (e - s).days
                tgt = q if 80 <= days <= 100 else fy if 350 <= days <= 380 else None
                if tgt is not None and (s, e) not in tgt:
                    tgt[(s, e)] = float(x["val"])
    out = {e: v for (s, e), v in q.items()}
    for (s, e), v in fy.items():
        parts = [out[x] for x in out if s < x < e and (x - s).days > 60]
        if e not in out and len(parts) == 3:
            out[e] = v - sum(parts)
    return out


def metrics(facts):
    """Cechy z ostatniego kwartału (porównanie r/r z kwartałem ~rok wcześniej). Brak danych -> {}."""
    s = {k: _durations(facts, t) for k, t in TAGS.items()}
    rev = {e: v for e, v in s["rev"].items() if v > 0}
    ends = sorted(rev)
    if len(ends) < 5:
        return {}
    e0 = ends[-1]
    e4 = next((e for e in reversed(ends[:-1]) if 330 <= (e0 - e).days <= 400), None)
    if e4 is None:
        return {}
    gp = {e: s["gp"].get(e, rev[e] - s["cogs"][e] if e in s["cogs"] else None) for e in (e0, e4)}
    out = {"quarter": e0.isoformat(), "rev_rr": (rev[e0] / rev[e4] - 1) * 100}
    if e0 in s["op"] and e4 in s["op"]:
        out["opm"] = s["op"][e0] / rev[e0] * 100
        out["dopm"] = out["opm"] - s["op"][e4] / rev[e4] * 100
    if gp[e0] is not None and gp[e4] is not None:
        out["dgm"] = (gp[e0] / rev[e0] - gp[e4] / rev[e4]) * 100
    return out


def update(tickers, cache, ua=UA, log=print, today=None, pause=0.15):
    """Uzupełnia `cache` {ticker: {"at": data pobrania, ...metrics}} dla spółek bez świeżych danych. Spółki bez CIK (np. zagraniczne bez XBRL) pomijamy."""
    today = today or dt.date.today()
    todo = [t for t in tickers if not (cache.get(t) and (today - dt.date.fromisoformat(cache[t]["at"])).days < FRESH_DAYS)]
    if not todo:
        return []
    ciks = cik_map(ua)
    done = []
    for n, t in enumerate(todo, 1):
        cik = ciks.get(t.upper()) or ciks.get(t.upper().replace("-", "."))
        if cik is None:
            cache[t] = {"at": today.isoformat()}
            continue
        try:
            cache[t] = {"at": today.isoformat(), **metrics(_get(FACTS_URL.format(cik), ua)["facts"])}
            done.append(t)
        except Exception as e:   # pojedyncza spółka bez danych nie przerywa synchronizacji
            log(f"SEC: {t} — {e}")
        if n % 25 == 0 or n == len(todo):
            log(f"SEC (fundamenty): {n}/{len(todo)}")
        time.sleep(pause)
    return done
