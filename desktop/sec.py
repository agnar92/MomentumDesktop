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
SEC_VERSION = 4     # 4 = przychody TTM i liczba akcji (rozwodnienie, P/S); 3 = zmiana zysku oper. w $; 2 = 8 kwartałów
FRESH_DAYS = 7
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json"
TAGS = {
    "rev": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenue"],
    "gp": ["GrossProfit"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfSales"],
    "op": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
}
SHARE_TAGS = ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
              "WeightedAverageNumberOfSharesOutstandingBasic"]


def _get(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def cik_map(ua=UA):
    return {v["ticker"].upper(): int(v["cik_str"]) for v in _get(TICKERS_URL, ua).values()}


def _durations(facts, tags, unit="USD", derive_q4=True):
    """Wartości okresowe: {koniec okresu: wartość} dla kwartałów (80–100 dni); Q4 = rok − 3 kwartały, gdy raport roczny nie podaje kwartału
    (nie dla średnich, np. liczby akcji: derive_q4=False)."""
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
    for (s, e), v in (fy.items() if derive_q4 else ()):
        parts = [out[x] for x in out if s < x < e and (x - s).days > 60]
        if e not in out and len(parts) == 3:
            out[e] = v - sum(parts)
    return out


def _quarter(s, rev, e0, ends):
    """Cechy kwartału e0 względem kwartału ~rok wcześniej -> dict albo None."""
    e4 = next((e for e in reversed([x for x in ends if x < e0]) if 330 <= (e0 - e).days <= 400), None)
    if e4 is None:
        return None
    gp = {e: s["gp"].get(e, rev[e] - s["cogs"][e] if e in s["cogs"] else None) for e in (e0, e4)}
    out = {"quarter": e0.isoformat(), "rev": rev[e0], "rev_rr": (rev[e0] / rev[e4] - 1) * 100}
    if e0 in s["op"] and e4 in s["op"]:
        out["opm"] = s["op"][e0] / rev[e0] * 100
        out["dopm"] = out["opm"] - s["op"][e4] / rev[e4] * 100
        out["op_d"] = s["op"][e0] - s["op"][e4]          # zmiana zysku operacyjnego w $ r/r (zabezpieczenie: RGTI)
    if gp[e0] is not None and gp[e4] is not None:
        out["dgm"] = (gp[e0] / rev[e0] - gp[e4] / rev[e4]) * 100
    return out


def metrics(facts):
    """Cechy z ostatniego kwartału (porównanie r/r z kwartałem ~rok wcześniej), poprzedniego kwartału (rev_rr1, dopm1, accel = zmiana tempa
    przychodów) i historia 8 kwartałów `qs` [{quarter, rev, rev_rr}] do wykresu przychodów. Brak danych -> {}."""
    s = {k: _durations(facts, t) for k, t in TAGS.items()}
    rev = {e: v for e, v in s["rev"].items() if v > 0}
    ends = sorted(rev)
    if len(ends) < 5:
        return {}
    last = _quarter(s, rev, ends[-1], ends)
    if last is None:
        return {}
    out = {k: v for k, v in last.items() if k != "rev"}
    out["rev_q"] = last["rev"]                             # przychody ostatniego kwartału ($)
    if len(ends) >= 4 and (ends[-1] - ends[-4]).days <= 300:   # 4 kolejne kwartały -> przychody TTM (do wyceny P/S)
        out["ttm_rev"] = sum(rev[e] for e in ends[-4:])
    sh = _durations(facts, SHARE_TAGS, "shares", derive_q4=False)   # średnia rozwodniona liczba akcji w kwartale
    e0 = ends[-1]
    e4 = next((e for e in reversed(sorted(sh)) if 330 <= (e0 - e).days <= 400), None)
    if e0 in sh and e4 is not None and sh[e4] > 0:
        out["shares"], out["dil"] = sh[e0], (sh[e0] / sh[e4] - 1) * 100       # rozwodnienie r/r (%)
    prev = _quarter(s, rev, ends[-2], ends) if len(ends) > 5 else None
    if prev:
        out["rev_rr1"], out["dopm1"] = prev["rev_rr"], prev.get("dopm")
        out["accel"] = last["rev_rr"] - prev["rev_rr"]
    qs = [_quarter(s, rev, e, ends) or {"quarter": e.isoformat(), "rev": rev[e]} for e in ends[-8:]]
    out["qs"] = [{"quarter": q["quarter"], "rev": q["rev"], "rev_rr": q.get("rev_rr")} for q in qs]
    out["v"] = SEC_VERSION
    return out


def update(tickers, cache, ua=UA, log=print, today=None, pause=0.15, progress=None):
    """Uzupełnia `cache` {ticker: {"at": data pobrania, ...metrics}} dla spółek bez świeżych danych. Spółki bez CIK (np. zagraniczne bez XBRL) pomijamy. progress(n, wszystkie) po każdej spółce."""
    today = today or dt.date.today()
    def fresh(e):   # wpis sprzed historii kwartałów (bez "v") z danymi pobieramy ponownie
        return e and (today - dt.date.fromisoformat(e["at"])).days < FRESH_DAYS and (e.get("v") == SEC_VERSION or "rev_rr" not in e)

    todo = [t for t in tickers if not fresh(cache.get(t))]
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
        if progress:
            progress(n, len(todo))
        if n % 25 == 0 or n == len(todo):
            log(f"SEC (fundamenty): {n}/{len(todo)}")
        time.sleep(pause)
    return done
