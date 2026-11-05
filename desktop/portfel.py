"""Portfel CEM10 z raportu XTB (zip albo xlsx „Closed Positions / Cash Operations / Open Positions”): pozycje, udziały, stop −40 %,
plan wpłat (nowe spółki na wolne miejsca, dopełnianie do wagi tylko pozycji na plusie) i krzywa kapitału. Czyste funkcje; sieć tylko w `curve_prices` (yfinance)."""
import datetime as dt
import io
import math
import zipfile

STOP = 0.40              # awaryjny stop od średniej ceny zakupu
MIN_TOPUP = 100.0        # dopłaty poniżej tej kwoty (zł) pomijamy
SLOTS = {"usa": 10, "gpw": 5}
FLOW_TYPES = ("deposit", "withdraw", "transfer")   # wpłaty / wypłaty (zewnętrzne przepływy konta)
BENCH = "SPY"            # indeks odniesienia (w zł: cena × kurs USD/PLN)
CCY = {"PLN": 1.0, "USD": 3.8, "EUR": 4.3, "GBP": 5.0, "GBX": 0.05}   # przybliżone kursy do rozpoznania waluty instrumentu


# ---------------------------------------------------------------- import raportu
def _sheets(blob):
    """Bajty xlsx -> {nazwa arkusza: [wiersze bez pustych]}."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(blob), data_only=True)
    return {ws.title: [r for r in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in r)] for ws in wb.worksheets}


def _table(rows, first, must=None):
    """Wiersze arkusza -> lista słowników od wiersza nagłówka zaczynającego się od `first` (i zawierającego kolumnę `must`)."""
    for i, r in enumerate(rows):
        if r and r[0] == first and (must is None or must in r):
            hdr = [str(c) if c is not None else "" for c in r]
            return [dict(zip(hdr, x)) for x in rows[i + 1:]]
    return []


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _iso(x):
    return x.isoformat(timespec="seconds") if isinstance(x, dt.datetime) else (str(x) if x else None)


def parse_account(blob, name=""):
    """Jeden plik xlsx z XTB -> konto: pozycje (zbiorczo i loty), operacje gotówkowe, zamknięte pozycje."""
    sh = _sheets(blob)
    op_rows = sh.get("Open Positions", [])
    acc = {"file": name, "label": name.split("_")[0] if "_" in name else name, "account": None, "generated": None, "open_value": 0.0, "positions": [], "lots": [], "cash_ops": [], "closed": []}
    for r in op_rows[:4]:
        if r[0] == "Account number":
            acc["account"] = str(r[1])
        if r[0] == "Data as of report generated":
            acc["generated"] = _iso(r[1])
    for r in op_rows:
        if len(r) > 2 and r[1] == "Open position value":
            acc["open_value"] += _num(r[2]) or 0.0
    cur = {}
    for d in _table(op_rows, "Product", "Instrument/Position"):
        if d.get("Instrument/Position") is None or not d.get("Ticker"):
            continue
        if d.get("Type") in ("", None):
            acc["positions"].append({"ticker": d["Ticker"], "name": str(d["Instrument/Position"]), "category": d.get("Category") or "",
                                     "volume": _num(d.get("Volume")) or 0.0, "value": _num(d.get("Value")) or 0.0,
                                     "open_price": _num(d.get("Open price")), "profit": _num(d.get("Net Profit")), "profit_pct": _num(d.get("Net Profit %"))})
        else:
            lot = {"ticker": d["Ticker"], "volume": _num(d.get("Volume")) or 0.0, "value": _num(d.get("Value")) or 0.0,
                   "price": _num(d.get("Current price")), "open_price": _num(d.get("Open price")), "open": _iso(d.get("Open time (UTC)"))}
            acc["lots"].append(lot)
            cur[d["Ticker"]] = lot["price"]
    for p in acc["positions"]:
        p["price"] = cur.get(p["ticker"])
        p["fx"] = p["value"] / (p["volume"] * p["price"]) if p["price"] and p["volume"] else None
    for d in _table(sh.get("Cash Operations", []), "Type", "Amount"):
        if d.get("Type") in (None, "Total") or _num(d.get("Amount")) is None:
            continue
        acc["cash_ops"].append({"type": str(d["Type"]), "ticker": d.get("Ticker") or "", "time": _iso(d.get("Time")), "amount": _num(d["Amount"]),
                                "comment": str(d.get("Comment") or "")})
    for d in _table(sh.get("Closed Positions", []), "Instrument", "Ticker"):
        if not d.get("Ticker") or _num(d.get("Volume")) is None:
            continue
        acc["closed"].append({"ticker": d["Ticker"], "name": str(d.get("Instrument") or ""), "category": d.get("Category") or "", "volume": _num(d["Volume"]),
                              "open_price": _num(d.get("Open Price")), "open": _iso(d.get("Open Time (UTC)")), "close_price": _num(d.get("Close Price")),
                              "close": _iso(d.get("Close Time (UTC)")), "profit": _num(d.get("Profit/Loss")), "buy": _num(d.get("Purchase Value")),
                              "sell": _num(d.get("Sale Value"))})
    acc["cash"] = round(sum(o["amount"] for o in acc["cash_ops"]), 2)
    return acc


def load_report(path_or_bytes, name=""):
    """Zip z raportami XTB albo pojedynczy xlsx -> lista kont (najpierw konto z największą wartością pozycji)."""
    blob = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else open(path_or_bytes, "rb").read()
    accs = []
    if blob[:2] == b"PK" and zipfile.is_zipfile(io.BytesIO(blob)):
        z = zipfile.ZipFile(io.BytesIO(blob))
        xl = [n for n in z.namelist() if n.lower().endswith(".xlsx")]
        if xl:
            for n in xl:
                accs.append(parse_account(z.read(n), n.rsplit("/", 1)[-1]))
        else:   # sam plik xlsx też jest zipem
            accs.append(parse_account(blob, name))
    else:
        raise ValueError("to nie jest raport XTB (zip albo xlsx)")
    return sorted(accs, key=lambda a: -(a["open_value"] + a["cash"]))


# ---------------------------------------------------------------- pozycje i koszyki
def base_ticker(xtb):
    """'MRNA.US' -> 'MRNA', 'BRK.B.US' -> 'BRK-B', 'ALE.PL' -> 'ALE' (klucz listy CEM10)."""
    t, _, suf = xtb.rpartition(".")
    return (t.replace(".", "-") if suf == "US" else t) if t else xtb


def yahoo(xtb):
    """Ticker XTB -> symbol Yahoo Finance."""
    t, _, suf = xtb.rpartition(".")
    if not t:
        return xtb
    return {"US": t.replace(".", "-"), "PL": t + ".WA", "UK": t + ".L", "DE": t + ".DE", "FR": t + ".PA", "NL": t + ".AS", "IT": t + ".MI",
            "ES": t + ".MC", "CH": t + ".SW", "DK": t + ".CO", "SE": t + ".ST", "NO": t + ".OL", "BE": t + ".BR", "PT": t + ".LS", "FI": t + ".HE"}.get(suf, xtb)


def currency(ratio):
    """Wartość w zł / (wolumen × cena) -> waluta instrumentu (najbliższy przybliżony kurs)."""
    if not ratio or ratio <= 0:
        return "PLN"
    return min(CCY, key=lambda k: abs(math.log(ratio / CCY[k])))


def bucket(p):
    """Koszyk pozycji: ETF / fundusze -> 'etf', akcje z USA -> 'usa', z GPW -> 'gpw', reszta -> 'inne'."""
    if str(p.get("category", "")).upper() in ("ETF", "ETC", "FUND"):
        return "etf"
    suf = p["ticker"].rpartition(".")[2]
    return {"US": "usa", "PL": "gpw"}.get(suf, "inne")


def holdings(acc, cem=None):
    """Pozycje konta z koszykiem, udziałem w koncie i w koszyku, średnią ceną zakupu, stopem −40 % i statusem CEM10.
    cem = lista CEM10 (data/cem10.json) albo None."""
    total = acc["open_value"] + acc["cash"]
    rows = []
    usa = {r["t"]: r for r in (cem or {}).get("usa", {}).get("rows", [])}
    gpw = {r["t"]: r for r in (cem or {}).get("gpw", {}).get("rows", [])}
    rank = {}
    if cem:
        from . import cem10
        rank.update({("usa", r["t"]): i + 1 for i, r in enumerate(cem10.usa_candidates(cem["usa"]["rows"], cem["usa"]["lead"]))})
        rank.update({("gpw", r["t"]): i + 1 for i, r in enumerate(cem10.gpw_candidates(cem["gpw"]["rows"]))})
    for p in acc["positions"]:
        b, t = bucket(p), base_ticker(p["ticker"])
        r = (usa if b == "usa" else gpw if b == "gpw" else {}).get(t)
        stop = p["open_price"] * (1 - STOP) if p.get("open_price") else None
        if b not in ("usa", "gpw"):
            status = "poza CEM10"
        elif not cem:
            status = "brak listy"
        elif r is None:   # brak wiersza (USA: nie przeszła sita i nie była pobrana; GPW: spoza WIG20 / mWIG40) — pobierz listę jeszcze raz
            b, status = "inne", "poza CEM10 (brak na liście)"
        elif r["dist"] is None or r["dist"] < 0:
            status = "SPRZEDAJ (pod SMA 10)"
        elif (b, t) in rank:
            status = f"kandydat #{rank[(b, t)]}"
        else:
            status = "trzymaj (poza listą zakupów)"
        rows.append({**p, "bucket": b, "t": t, "share": p["value"] / total if total else 0.0, "stop": stop,
                     "stop_dist": (p["price"] / stop - 1) if stop and p.get("price") else None, "status": status, "rank": rank.get((b, t)),
                     "sma": r.get("sma") if r else None, "dist": r.get("dist") if r else None, "ccy": currency(p.get("fx"))})
    buckets = {}
    for h in rows:
        buckets[h["bucket"]] = buckets.get(h["bucket"], 0.0) + h["value"]
    for h in rows:
        h["bucket_share"] = h["value"] / buckets[h["bucket"]] if buckets.get(h["bucket"]) else 0.0
    return sorted(rows, key=lambda h: ("usa gpw etf inne".split().index(h["bucket"]), -h["value"])), buckets, total


# ---------------------------------------------------------------- plan wpłaty
def _in_profit(h):
    """Czy pozycja jest na plusie względem ceny zakupu (brak ceny zakupu albo bieżącej = nie dokładamy)."""
    return bool(h.get("open_price") and h.get("price") and h["price"] >= h["open_price"])


def plan(acc, cem, deposit=0.0, targets=None, etf_ticker="CSPX.UK", slots=None, topup="plus"):
    """Plan na zamknięcie miesiąca: 1) sprzedaj pozycje CEM10 ze statusem SPRZEDAJ, 2) gotówka + wpłata + sprzedaż rozdzielona na koszyki
    wg niedoboru do udziałów docelowych (targets = {'usa': %, 'gpw': %, 'etf': %}), 3) w koszyku CEM10: waga docelowa = (wartość koszyka po planie) / liczba miejsc,
    nowe spółki z listy na wolne miejsca, potem dopełnienie do wagi trzymanych KANDYDATÓW, które są na plusie względem ceny zakupu (od najmniejszej, min. 100 zł; do spadających spółek NIE dokładamy — user: „Dell spadł o 20 % i każe mi dopłacać”); filtr rynku = brak zakupów.
    topup: "plus" (domyślnie) = dopełnianie tylko pozycji na plusie, "all" = także tych na minusie (świadoma decyzja), "off" (albo False) = bez DOPŁAĆ — nowe spółki na wolne miejsca zostają; powody braku zakupów trafiają do summary['notes'].
    -> (akcje [{akcja, ticker, koszyk, kwota, uwagi}], podsumowanie)."""
    from . import cem10
    slots = {**SLOTS, **(slots or {})}
    targets = targets or {"usa": 50.0, "gpw": 50.0, "etf": 0.0}
    hold, buckets, total = holdings(acc, cem)
    actions = []
    free = acc["cash"] + max(deposit, 0.0)
    sold = {}   # wpływy ze sprzedaży pozycji CEM10 według koszyka
    for h in hold:
        if h["status"].startswith("SPRZEDAJ"):
            actions.append({"akcja": "SPRZEDAJ", "ticker": h["t"], "koszyk": h["bucket"], "kwota": h["value"], "uwagi": h["status"][9:].strip(" ()")})
            buckets[h["bucket"]] -= h["value"]
            free += h["value"]
            sold[h["bucket"]] = sold.get(h["bucket"], 0.0) + h["value"]
    kept = [h for h in hold if not h["status"].startswith("SPRZEDAJ")]
    grand = total + max(deposit, 0.0)
    tsum = sum(max(v, 0.0) for v in targets.values()) or 1.0
    need = {b: max(grand * max(targets.get(b, 0.0), 0.0) / tsum - buckets.get(b, 0.0), 0.0) for b in ("usa", "gpw", "etf")}
    blocked = {"usa": bool(cem and cem["usa"]["bear"]), "gpw": bool(cem and cem["gpw"]["bear"]), "etf": False}
    # sprzedane miejsce wraca do tego samego koszyka (kolejny kandydat z listy) — to nie jest „wpłata do rozdzielenia wg udziałów”;
    # inaczej zwycięzcy, którzy urośli ponad udział docelowy, zostawiali koszyk bez zakupów, a całość szła w ETF
    reserve = {b: sold.get(b, 0.0) for b in ("usa", "gpw") if not blocked[b]}
    pool = free - sum(reserve.values())
    need = {b: max(need[b] - reserve.get(b, 0.0), 0.0) for b in need}
    want = sum(v for b, v in need.items() if not blocked[b])
    alloc = {b: (pool * need[b] / want if want > pool else need[b]) if not blocked[b] and want else 0.0 for b in need}
    left = pool - sum(alloc.values())
    if left > 1 and want and any(not blocked[b] and targets.get(b, 0) > 0 for b in alloc):   # nadwyżka ponad niedobory: wg udziałów docelowych
        live = {b: targets.get(b, 0.0) for b in alloc if not blocked[b] and targets.get(b, 0) > 0}
        for b, w in live.items():
            alloc[b] += left * w / sum(live.values())
        left = 0.0
    for b, v in reserve.items():
        alloc[b] += v
    summary = {"free": free, "grand": grand, "alloc": dict(alloc), "need": need, "blocked": blocked, "cash_left": 0.0, "notes": []}
    if alloc["etf"] >= MIN_TOPUP:
        actions.append({"akcja": "KUP", "ticker": base_ticker(etf_ticker), "koszyk": "etf", "kwota": alloc["etf"], "uwagi": "ETF"})
    else:
        left += alloc["etf"]
    for b in ("usa", "gpw"):
        money = alloc[b]
        if blocked[b]:
            summary["notes"].append(f"{b.upper()}: filtr rynku — brak zakupów, gotówka czeka")
            continue
        if not cem or money < MIN_TOPUP:
            if cem and money > 0:
                summary["notes"].append(f"{b.upper()}: do rozdysponowania tylko {money:,.0f} zł (min. {MIN_TOPUP:,.0f} zł) — gotówka czeka".replace(",", " "))
            left += money
            continue
        held = [h for h in kept if h["bucket"] == b]
        tgt = (buckets.get(b, 0.0) + money) / slots[b]
        cands = cem10.usa_candidates(cem["usa"]["rows"], cem["usa"]["lead"]) if b == "usa" else cem10.gpw_candidates(cem["gpw"]["rows"])
        have = {h["t"] for h in held}
        for r in [r for r in cands if r["t"] not in have][:max(slots[b] - len(held), 0)]:
            amt = min(tgt, money)
            if amt < MIN_TOPUP:
                break
            actions.append({"akcja": "KUP", "ticker": r["t"], "koszyk": b, "kwota": amt, "uwagi": f"nowa pozycja, #{cands.index(r) + 1} na liście"})
            money -= amt
        mode = "off" if topup is False else "plus" if topup in (True, None) else topup
        ups = [h for h in held if h["rank"]]
        if mode == "off":
            if ups:
                summary["notes"].append(f"{b.upper()}: dopłaty do trzymanych wyłączone")
            ups = []
        elif mode == "plus" and any(not _in_profit(h) for h in ups):
            summary["notes"].append(f"{b.upper()}: bez dopłaty do spółek na minusie ({', '.join(h['t'] for h in ups if not _in_profit(h))})")
        if len(held) >= slots[b] and money >= MIN_TOPUP and not any(h["rank"] and (mode == "all" or _in_profit(h)) for h in held):
            summary["notes"].append(f"{b.upper()}: brak wolnych miejsc ({len(held)} z {slots[b]})")
        for h in sorted([h for h in ups if mode == "all" or _in_profit(h)], key=lambda h: h["value"]):
            add = min(tgt - h["value"], money)
            if add >= MIN_TOPUP:
                actions.append({"akcja": "DOPŁAĆ", "ticker": h["t"], "koszyk": b, "kwota": add, "uwagi": f"do wagi {tgt:,.0f} zł".replace(",", " ")})
                money -= add
        if len(held) > slots[b]:
            summary["notes"].append(f"{b.upper()}: {len(held)} spółek na {slots[b]} miejsc — nowych nie kupuję")
        left += money
    summary["cash_left"] = left
    return actions, summary


# ---------------------------------------------------------------- krzywa kapitału
def flows(acc):
    """Wpłaty / wypłaty konta: [(data, kwota)] (typy z 'deposit' / 'withdraw' / 'transfer')."""
    return sorted((o["time"][:10], o["amount"]) for o in acc["cash_ops"] if any(k in o["type"].lower() for k in FLOW_TYPES))


def exits(acc):
    """Sprzedaże zgrupowane po dniu i tickerze: [(data, ticker, wynik zł, wynik %)]."""
    g = {}
    for c in acc["closed"]:
        if not c.get("close"):
            continue
        k = (c["close"][:10], base_ticker(c["ticker"]))
        x = g.setdefault(k, [0.0, 0.0])
        x[0] += c.get("profit") or 0.0
        x[1] += c.get("buy") or 0.0
    return sorted((d, t, p, p / b if b else None) for (d, t), (p, b) in g.items())


def lots_all(acc, today=None):
    """Wszystkie loty (zamknięte i otwarte): ticker, wolumen, od, do, cena otwarcia / zamknięcia, waluta."""
    today = today or (acc.get("generated") or dt.date.today().isoformat())[:10]
    out = []
    for c in acc["closed"]:
        if c.get("open") and c.get("close") and c["volume"]:
            fx = (c["buy"] / (c["volume"] * c["open_price"])) if c.get("buy") and c.get("open_price") else None
            out.append({"ticker": c["ticker"], "vol": c["volume"], "start": c["open"][:10], "end": c["close"][:10], "p0": c["open_price"], "p1": c["close_price"],
                        "ccy": currency(fx)})
    pos = {p["ticker"]: p for p in acc["positions"]}
    for lot in acc["lots"]:
        if lot.get("open") and lot["volume"]:
            fx = pos.get(lot["ticker"], {}).get("fx")
            out.append({"ticker": lot["ticker"], "vol": lot["volume"], "start": lot["open"][:10], "end": None, "p0": lot.get("open_price"), "p1": lot.get("price"),
                        "ccy": currency(fx)})
    return out


def curve(acc, px=None, fxs=None, days=None):
    """Dzienna wartość konta w zł: gotówka (suma operacji do dnia) + loty × cena zamknięcia dnia × kurs waluty.
    px = {symbol Yahoo: {data: cena}}, fxs = {'USD': {data: kurs}, ...}; brak ceny -> interpolacja liniowa ceny otwarcia i zamknięcia lotu.
    -> [(data, wartość, wpłacono netto)]."""
    px, fxs = px or {}, fxs or {}
    lots = lots_all(acc)
    ops = sorted((o["time"][:10], o["amount"], any(k in o["type"].lower() for k in FLOW_TYPES)) for o in acc["cash_ops"])
    if not ops:
        return []
    start = min([o[0] for o in ops] + [lot["start"] for lot in lots])
    end = (acc.get("generated") or dt.date.today().isoformat())[:10]
    if days is None:
        d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        days = [(d0 + dt.timedelta(k)).isoformat() for k in range((d1 - d0).days + 1)]
        days = [d for d in days if dt.date.fromisoformat(d).weekday() < 5] or days

    def last_before(series, d):
        if not series:
            return None
        keys = series.get("_k")
        if keys is None:
            keys = series["_k"] = sorted(k for k in series if k != "_k")
        from bisect import bisect_right
        i = bisect_right(keys, d)
        return series[keys[i - 1]] if i else None

    out, cash, dep, oi = [], 0.0, 0.0, 0
    for d in days:
        while oi < len(ops) and ops[oi][0] <= d:
            cash += ops[oi][1]
            if ops[oi][2]:
                dep += ops[oi][1]
            oi += 1
        val = cash
        for lot in lots:
            if lot["start"] > d or (lot["end"] and lot["end"] <= d):
                continue
            p = last_before(px.get(yahoo(lot["ticker"])), d)
            if p is None:
                a, b = lot["p0"] or 0.0, lot["p1"] or lot["p0"] or 0.0
                e = lot["end"] or end
                span = max((dt.date.fromisoformat(e) - dt.date.fromisoformat(lot["start"])).days, 1)
                p = a + (b - a) * (dt.date.fromisoformat(d) - dt.date.fromisoformat(lot["start"])).days / span
            if lot["ccy"] == "PLN":
                k = 1.0
            elif lot["ccy"] == "GBX":
                k = (last_before(fxs.get("GBP"), d) or CCY["GBP"]) / 100
            else:
                k = last_before(fxs.get(lot["ccy"]), d) or CCY[lot["ccy"]]
            val += lot["vol"] * p * k
        out.append((d, round(val, 2), round(dep, 2)))
    return out


def bench_series(days, px, fx):
    """Indeks odniesienia w zł na dni krzywej: [(data, cena × kurs USD/PLN)] (ostatnia znana cena z dnia lub wcześniej); brak danych -> []."""
    if not px or not fx:
        return []
    from bisect import bisect_right
    kp, kf = sorted(px), sorted(fx)
    out = []
    for d in days:
        i, j = bisect_right(kp, d), bisect_right(kf, d)
        if i and j:
            out.append((d, round(px[kp[i - 1]] * fx[kf[j - 1]], 4)))
    return out


def curve_prices(acc, log=print):
    """Dzienne ceny zamknięcia (yfinance) dla wszystkich instrumentów konta i kursy walut -> (px, fxs)."""
    from .prices import _yf
    lots = lots_all(acc)
    if not lots:
        return {}, {}
    start = min(lot["start"] for lot in lots)
    syms = sorted({yahoo(lot["ticker"]) for lot in lots} | {BENCH})   # SPY jako punkt odniesienia dla wskaźników
    ccys = sorted({lot["ccy"] for lot in lots} - {"PLN"} | {"USD"})
    fx_sym = {c: ("GBPPLN=X" if c == "GBX" else f"{c}PLN=X") for c in ccys}
    want = syms + sorted(set(fx_sym.values()))
    log(f"Ceny dzienne: {len(syms)} instrumentów + kursy {', '.join(ccys) or '—'}")
    df = _yf().download(want, start=start, interval="1d", auto_adjust=False, group_by="ticker", progress=False, threads=True)
    series = {}
    for s in want:
        try:
            f = (df[s] if len(want) > 1 else df)["Close"].dropna()
        except KeyError:
            continue
        series[s] = {d.strftime("%Y-%m-%d"): float(v) for d, v in f.items()}
    fxs = {("GBP" if c == "GBX" else c): series.get(fx_sym[c], {}) for c in ccys}
    return {s: series[s] for s in syms if s in series}, fxs


# ---------------------------------------------------------------- wskaźniki jakości
# Odniesienie z badania historycznego strategii CEM10 USA (1999–2026, szeroki rynek, miesięcznie, w USD; dane z błędem przeżywalności, więc
# prawdziwe wyniki mogą być niższe). Konto to całość (baza ETF + CEM10 USA + GPW + gotówka), więc porównanie jest orientacyjne.
REF = {"cagr": 0.179, "vol": 0.259, "sharpe": 0.77, "pos_months": 0.554, "worst_month": -0.255, "max_dd": -0.335, "worst_year": -0.192,
       "p10_12m": -0.103, "neg_12m": 0.254, "median_12m": 0.172, "under_water_months": 42, "time_below_10": 0.395, "time_below_20": 0.177}
EARLY_MONTHS = 24        # krócej niż 2 lata: za wcześnie na ocenę (25 % rocznych okien w historii jest ujemnych)


def trades(acc):
    """Zamknięte pozycje zgrupowane po dniu i tickerze: [{d, t, profit (zł), buy (zł), pct, hold (dni)}]."""
    g = {}
    for c in acc["closed"]:
        if not c.get("close"):
            continue
        k = (c["close"][:10], base_ticker(c["ticker"]))
        x = g.setdefault(k, {"profit": 0.0, "buy": 0.0, "hw": 0.0})
        x["profit"] += c.get("profit") or 0.0
        buy = c.get("buy") or 0.0
        x["buy"] += buy
        if c.get("open"):
            x["hw"] += buy * max((dt.date.fromisoformat(c["close"][:10]) - dt.date.fromisoformat(c["open"][:10])).days, 0)
    return sorted(({"d": d, "t": t, "profit": x["profit"], "buy": x["buy"], "pct": x["profit"] / x["buy"] if x["buy"] else None,
                    "hold": x["hw"] / x["buy"] if x["buy"] else None} for (d, t), x in g.items()), key=lambda r: (r["d"], r["t"]))


def trade_stats(tr):
    """Statystyki transakcji: liczba, trafność, średni zysk / strata, payoff, profit factor, oczekiwana wartość (% na transakcję), czas trzymania."""
    tr = [t for t in tr if t.get("pct") is not None]
    if not tr:
        return None
    win, los = [t for t in tr if t["pct"] > 0], [t for t in tr if t["pct"] <= 0]
    aw = sum(t["pct"] for t in win) / len(win) if win else 0.0
    al = sum(t["pct"] for t in los) / len(los) if los else 0.0
    gl = -sum(t["profit"] for t in los)
    holds = [t["hold"] for t in tr if t.get("hold") is not None]
    return {"n": len(tr), "wins": len(win), "win_rate": len(win) / len(tr), "avg_win": aw, "avg_loss": al, "payoff": (aw / -al) if al < 0 else None,
            "profit_factor": (sum(t["profit"] for t in win) / gl) if gl > 0 else None, "expectancy": sum(t["pct"] for t in tr) / len(tr),
            "best": max(t["pct"] for t in tr), "worst": min(t["pct"] for t in tr), "avg_hold": sum(holds) / len(holds) if holds else None,
            "total": sum(t["profit"] for t in tr)}


def _xirr(cfs):
    """Roczna stopa zwrotu ważona przepływami: cfs = [(data iso, kwota)] (wpłata ujemna, wartość końcowa dodatnia); bisekcja."""
    if len(cfs) < 2:
        return None
    t0 = dt.date.fromisoformat(cfs[0][0])
    pts = [((dt.date.fromisoformat(d) - t0).days / 365.0, a) for d, a in cfs]
    f = lambda r: sum(a / (1 + r) ** t for t, a in pts)   # noqa: E731
    lo, hi = -0.95, 10.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def performance(points, tr=None, bench=None):
    """Wskaźniki konta z krzywej [(data, wartość, wpłacono netto)] — na indeksie zwrotu (wpłaty nie są zyskiem): zwrot, ryzyko, jakość, miesiące,
    transakcje, porównanie z indeksem (`bench` = [(data, wartość zł)]) i z historią CEM10 (`REF`). Zwraca None, gdy za mało danych."""
    pts = [p for p in points if p[1] > 1]
    if len(pts) < 20:
        return None
    idx, rets, prev, peak, pk_d = [], [], None, 1.0, pts[0][0]
    cur = 1.0
    under_since, longest = None, 0
    for d, v, dep in pts:
        r = 0.0
        if prev is not None:
            base = prev[1] + (dep - prev[2])
            if base > 1:
                r = v / base - 1
                rets.append(r)
        cur *= 1 + r
        if cur >= peak - 1e-12:
            peak, pk_d = max(peak, cur), d
            if under_since is not None:
                longest = max(longest, (dt.date.fromisoformat(d) - dt.date.fromisoformat(under_since)).days)
                under_since = None
        elif under_since is None:
            under_since = pk_d
        idx.append((d, cur, cur / peak - 1))
        prev = (d, v, dep)
    d0, d1 = pts[0][0], pts[-1][0]
    days = max((dt.date.fromisoformat(d1) - dt.date.fromisoformat(d0)).days, 1)
    years = days / 365.25
    total = cur - 1
    if under_since is not None:
        longest = max(longest, (dt.date.fromisoformat(d1) - dt.date.fromisoformat(under_since)).days)
    n = len(rets)
    mean = sum(rets) / n if n else 0.0
    sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / (n - 1)) if n > 2 else None
    down = math.sqrt(sum(min(x, 0.0) ** 2 for x in rets) / n) if n else None
    vol = sd * math.sqrt(252) if sd else None
    max_dd = min(i[2] for i in idx)
    worst_d = next(i[0] for i in idx if i[2] == max_dd)
    cagr = cur ** (1 / years) - 1 if years >= 1 else None
    # miesiące kalendarzowe (indeks na koniec miesiąca)
    me = {}
    for d, c, _ in idx:
        me[d[:7]] = c
    keys = sorted(me)
    mrets = [me[keys[i]] / me[keys[i - 1]] - 1 for i in range(1, len(keys))]
    months = {"n": len(mrets), "pos": sum(1 for x in mrets if x > 0) / len(mrets) if mrets else None, "best": max(mrets) if mrets else None,
              "worst": min(mrets) if mrets else None}
    # ostatnie 12 miesięcy
    r12 = None
    if days >= 365:
        c12 = next((c for d, c, _ in reversed(idx) if (dt.date.fromisoformat(d1) - dt.date.fromisoformat(d)).days >= 365), None)
        r12 = cur / c12 - 1 if c12 else None
    flows_, prevdep = [], 0.0
    for d, v, dep in pts:
        if dep != prevdep:
            flows_.append((d, -(dep - prevdep)))
            prevdep = dep
    xirr = _xirr(flows_ + [(d1, pts[-1][1])]) if days >= 90 else None
    out = {"from": d0, "to": d1, "years": years, "months_n": months["n"], "twr": total, "cagr": cagr, "xirr": xirr, "r12": r12, "vol": vol,
           "sharpe": (mean * 252 / vol) if vol else None, "sortino": (mean * 252 / (down * math.sqrt(252))) if down else None,
           "max_dd": max_dd, "max_dd_date": worst_d, "dd": idx[-1][2], "under_days": longest,
           "since_peak_days": (dt.date.fromisoformat(d1) - dt.date.fromisoformat(pk_d)).days, "calmar": (cagr / -max_dd) if cagr is not None and max_dd < -0.005 else None,
           "months": months, "se_annual": (vol / math.sqrt(years)) if vol and years > 0 else None, "ref": REF}
    # indeks odniesienia: ten sam okres
    if bench:
        b = [(d, v) for d, v in bench if d0 <= d <= d1 and v]
        if len(b) > 20:
            bpk, bdd = 0.0, 0.0
            for _, v in b:
                bpk = max(bpk, v)
                bdd = min(bdd, v / bpk - 1)
            btot = b[-1][1] / b[0][1] - 1
            out["bench"] = {"name": BENCH, "total": btot, "cagr": (1 + btot) ** (1 / years) - 1 if years >= 1 else None, "max_dd": bdd, "diff": total - btot}
    out["trades"] = trade_stats(tr or [])
    out["verdict"] = assess(out)
    return out


def assess(m):
    """Czy strategia sprawuje się zgodnie z historią? Lista kontroli (ok / warn / bad / info) i werdykt; przed 24 miesiącami tylko „za wcześnie”."""
    ref, checks = m["ref"], []

    def add(name, now, hist, level, note=""):
        checks.append({"name": name, "now": now, "hist": hist, "level": level, "note": note})
    dd = m["dd"]
    add("Obsunięcie od szczytu teraz", dd, f"w historii maks. {ref['max_dd']:.0%}, głębiej niż −10 % przez {ref['time_below_10']:.0%} czasu",
        "bad" if dd < ref["max_dd"] else "warn" if dd < -0.2 else "ok", "głębsze niż najgorsze w historii" if dd < ref["max_dd"] else "")
    add("Największe obsunięcie na koncie", m["max_dd"], f"w historii {ref['max_dd']:.0%}", "bad" if m["max_dd"] < ref["max_dd"] - 0.03 else "warn" if m["max_dd"] < -0.25 else "ok")
    if m["r12"] is not None:
        add("Ostatnie 12 miesięcy", m["r12"], f"10 % najgorszych okien: poniżej {ref['p10_12m']:.0%}; mediana {ref['median_12m']:.0%}",
            "warn" if m["r12"] < ref["p10_12m"] else "ok", f"{ref['neg_12m']:.0%} rocznych okien w historii było ujemnych")
    if m["vol"] is not None and m["years"] >= 0.5:
        add("Zmienność roczna", m["vol"], f"w historii {ref['vol']:.0%}", "warn" if m["vol"] > ref["vol"] * 1.3 else "info", "konto z bazą ETF i gotówką ma być spokojniejsze")
    if m["under_days"] / 30.4 > ref["under_water_months"] * 0.85:
        add("Najdłuższy czas pod szczytem", m["under_days"] / 30.4, f"w historii do {ref['under_water_months']} mies.", "warn")
    b = m.get("bench")
    if b and m["years"] >= 1:
        add(f"Wynik względem {b['name']} (w zł)", b["diff"], f"{b['name']}: {b['total']:+.0%}, obsunięcie {b['max_dd']:.0%}", "ok" if b["diff"] >= 0 else "info",
            "przewaga ma sens dopiero po kilku latach")
    if m["months_n"] < EARLY_MONTHS:
        return {"level": "early", "checks": checks, "text": f"Za wcześnie na ocenę: {m['months_n']} mies. historii (potrzeba min. {EARLY_MONTHS}). W badaniu {ref['neg_12m']:.0%} "
                f"rocznych okien było ujemnych, a obsunięcie powyżej 10 % trwało {ref['time_below_10']:.0%} czasu, więc słaby rok nie świadczy o błędzie strategii."}
    lv = [c["level"] for c in checks]
    level = "bad" if "bad" in lv else "warn" if "warn" in lv else "ok"
    return {"level": level, "checks": checks, "text": {"ok": "Wskaźniki mieszczą się w zakresie z badania historycznego.", "warn": "Część wskaźników jest słabsza niż zwykle w historii, ale nie przekracza jej skrajności. Obserwuj.",
                                                         "bad": "Co najmniej jeden wskaźnik jest gorszy niż najgorszy przypadek z badania. Sprawdź, czy reguły są wykonywane zgodnie z planem."}[level]}
