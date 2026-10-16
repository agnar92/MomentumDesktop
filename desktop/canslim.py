"""CANSLIM — port canslimInfo / canslimMarket / canslimExplain z Momentum (docs/js/watchlist.js). Heurystyka wg O'Neila,
progi nie były testowane historycznie; informacyjnie, nie jest to porada inwestycyjna."""

KEYS = "CANSLIM"
T = {"epsQ": 25, "sales": 25, "epsYear": 25, "roe": 17, "nearHigh": -10, "debtEq": 1, "rs": 80, "group": 60,
     "instMin": 20, "instMax": 90, "instData": 100, "distDays": 5}
NAMES = {"C": "Current earnings — bieżące zyski", "A": "Annual earnings — roczne zyski", "N": "New — blisko szczytu",
         "S": "Supply & demand — popyt i podaż", "L": "Leader — lider czy maruda", "I": "Institutional sponsorship — instytucje",
         "M": "Market direction — kierunek rynku"}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def institutional_flag(s):
    """I: własność instytucji 20–90 % i napływ w ostatnim kwartale; > 100 % = dane niewiarygodne (None)."""
    if _num(s.get("inst_own")) and _num(s.get("inst_trans")):
        if s["inst_own"] > T["instData"]:
            return None
        return T["instMin"] <= s["inst_own"] <= T["instMax"] and s["inst_trans"] > 0
    v = s.get("inst_sponsor")
    return v if isinstance(v, bool) else None


def market(watchlist):
    """{regime, dist_days, ftd} z watchlist.json["market"] (efektywne M: po korekcie liczy się potwierdzony Follow-Through Day)."""
    m = (watchlist or {}).get("market")
    if not m:
        return None
    idx = [m.get("sp500"), m.get("nasdaq")]
    days = []
    for x in idx:
        if x:
            d = x.get("m_dist_days") if _num(x.get("m_dist_days")) else x.get("dist_days")
            if _num(d):
                days.append(d)
    return {"regime": m.get("m_regime") or m.get("regime"), "dist_days": max(days) if days else None,
            "ftd": any(x and x.get("m_via_ftd") for x in idx)}


def ema_market(watchlist):
    """Rynek wg tygodniowych EMA 10 / 20 (S&P 500 i Nasdaq osobno): {"sp500": {up, gap}, "nasdaq": {...}, "up": bool|None}.
    Tylko informacja (jak baner rynku w Momentum): up = wszystkie znane indeksy mają EMA10 > EMA20."""
    m = (watchlist or {}).get("market") or {}
    out, flags = {}, []
    for key in ("sp500", "nasdaq"):
        x = m.get(key)
        if x and _num(x.get("ema10w")) and _num(x.get("ema20w")):
            up = x["ema10w"] > x["ema20w"]
            out[key] = {"up": up, "gap": (x["ema10w"] / x["ema20w"] - 1) * 100}
            flags.append(up)
    out["up"] = all(flags) if flags else None
    return out


def market_line(watchlist):
    """Krótki opis rynku do paska statusu: „S&P 500 ✅ +1,6 %  Nasdaq ✅ +2,0 % (EMA10/20 tyg.)”."""
    e = ema_market(watchlist)
    parts = [f"{name} {'✅' if e[k]['up'] else '🛑'} {e[k]['gap']:+.1f} %" for k, name in (("sp500", "S&P 500"), ("nasdaq", "Nasdaq")) if k in e]
    return "  ".join(parts) + " (EMA10/20 tyg.)" if parts else "—"


def info(s, mkt=None):
    """{flags: {C..M: True/False/None}, score, known}; None = brak danych (nie obniża litery)."""
    regime = mkt.get("regime") if isinstance(mkt, dict) else mkt
    dist = mkt.get("dist_days") if isinstance(mkt, dict) else None
    C = None
    if _num(s.get("eps_q0_yoy")):
        C = s["eps_q0_yoy"] >= T["epsQ"] and (not _num(s.get("sales_qq")) or s["sales_qq"] >= T["sales"])
    parts = [s["eps_this_y"] >= T["epsYear"] if _num(s.get("eps_this_y")) else None,
             s["roe"] >= T["roe"] if _num(s.get("roe")) else None]
    parts += [s[k] >= T["epsYear"] if _num(s.get(k)) else None for k in ("eps_yr0", "eps_yr1", "eps_yr2")]
    parts = [p for p in parts if p is not None]
    A = all(parts) if parts else None
    N = s["pct_from_high_52w"] >= T["nearHigh"] if _num(s.get("pct_from_high_52w")) else None
    S = None
    if s.get("accdis"):
        S = s["accdis"] in ("A", "B") and (not _num(s.get("debt_eq")) or s["debt_eq"] <= T["debtEq"])
    L = None
    if _num(s.get("rs_rating")):
        L = s["rs_rating"] >= T["rs"] and (not _num(s.get("industry_rating")) or s["industry_rating"] >= T["group"])
    if regime == "uptrend":
        M = not (_num(dist) and dist >= T["distDays"])
    else:
        M = False if regime == "correction" else None
    flags = {"C": C, "A": A, "N": N, "S": S, "L": L, "I": institutional_flag(s), "M": M}
    return {"flags": flags, "score": sum(1 for k in KEYS if flags[k] is True), "known": sum(1 for k in KEYS if flags[k] is not None)}


def tag(stock, mkt):
    """Dopisuje do spółki: canslim (info), cs (n/7 albo None przy < 4 znanych), cs_letters ("C A N · L ? M")."""
    c = info(stock, mkt)
    stock["canslim"] = c
    stock["cs"] = c["score"] if c["known"] >= 4 else None
    stock["cs_letters"] = " ".join(k if c["flags"][k] is True else "·" if c["flags"][k] is False else "?" for k in KEYS)
    return stock


def core_ok(stock):
    f = stock["canslim"]["flags"]
    return f["C"] is True and f["A"] is True


def explain(s, mkt=None):
    """[(litera, nazwa, ok, 'Mamy', 'Reguła')] — te same liczby, na których opiera się info()."""
    c = info(s, mkt)
    regime = mkt.get("regime") if isinstance(mkt, dict) else mkt
    dist = mkt.get("dist_days") if isinstance(mkt, dict) else None

    def pct(v):
        return f"{'+' if v > 0 else ''}{v}%"

    def yrs():
        return " / ".join(pct(s[k]) if _num(s.get(k)) else "—" for k in ("eps_yr0", "eps_yr1", "eps_yr2"))

    rows = []

    def add(key, rule, have):
        rows.append((key, NAMES[key], c["flags"][key], have, rule))

    add("C", f"EPS ostatniego kwartału r/r ≥ {T['epsQ']} % i sprzedaż r/r ≥ {T['sales']} % (gdy znana)",
        (f"EPS ostatniego kwartału {pct(s['eps_q0_yoy'])} r/r" + (f", poprzedniego {pct(s['eps_q1_yoy'])}" if _num(s.get("eps_q1_yoy")) else "")
         + "; sprzedaż " + (f"{pct(s['sales_qq'])} r/r" if _num(s.get("sales_qq")) else "— brak danych (oceniamy tylko EPS)"))
        if _num(s.get("eps_q0_yoy")) else "brak danych o EPS z ostatniego kwartału")
    have_a = "; ".join(x for x in (f"EPS w tym roku {pct(s['eps_this_y'])}" if _num(s.get("eps_this_y")) else None,
                                   f"EPS rok do roku (ost. 4 kw. / rok wcześniej / 2 lata wcześniej): {yrs()}" if any(_num(s.get(k)) for k in ("eps_yr0", "eps_yr1", "eps_yr2")) else None,
                                   f"ROE {s['roe']}%" if _num(s.get("roe")) else None) if x) or "brak danych o rocznych zyskach i ROE"
    add("A", f"EPS w tym roku ≥ {T['epsYear']} %, wzrost ≥ {T['epsYear']} % w każdym z 3 ostatnich lat, ROE ≥ {T['roe']} % (każdy znany składnik musi przejść)", have_a)
    pf = s.get("pct_from_high_52w")
    add("N", f"cena nie dalej niż {abs(T['nearHigh'])} % pod szczytem 52 tygodni",
        ("cena na szczycie 52 tygodni" if pf >= 0 else f"{abs(pf)}% poniżej szczytu 52 tyg.") if _num(pf) else "brak danych o szczycie 52 tyg.")
    ad = f"Acc/Dis {s['accdis']}" if s.get("accdis") else "Acc/Dis — brak oceny"
    de = f"zadłużenie D/E {s['debt_eq']}" if _num(s.get("debt_eq")) else "zadłużenie — brak danych"
    sh = f"liczba akcji {pct(s['shares_chg_pct'])} r/r" + (" — skup akcji ✓" if s["shares_chg_pct"] <= -5 else "") if _num(s.get("shares_chg_pct")) else "skup akcji — brak danych"
    add("S", f"popyt: Acc/Dis A lub B; podaż: zadłużenie D/E ≤ {T['debtEq']} (gdy znane); skup akcji ≥ 5 % r/r to dodatkowy plus", f"{ad}; {de}; {sh}")
    rs = s.get("rs_rating")
    add("L", f"RS Rating ≥ {T['rs']} i silna grupa branżowa (≥ {T['group']}, gdy znana); RS to percentyl wśród spółek listy",
        (f"RS Rating {rs}" + (f", grupa branżowa {s['industry_rating']}" if _num(s.get("industry_rating")) else ", grupa — brak danych")
         + (", ★ lider" if s.get("leader") else "")) if _num(rs) else "brak RS Rating (zbyt krótka historia)")
    io = s.get("inst_own")
    have_i = "brak danych o instytucjach"
    if _num(io):
        have_i = f"instytucje {io}%" + (f", zmiana w ostatnim kwartale {pct(s['inst_trans'])}" if _num(s.get("inst_trans")) else "")
        have_i += " — Finviz podaje > 100 %, dane niewiarygodne" if io > T["instData"] else " — przesadne obłożenie" if io > T["instMax"] else ""
    add("I", f"instytucje posiadają {T['instMin']}–{T['instMax']} % akcji i ich udział rośnie", have_i)
    ftd = isinstance(mkt, dict) and mkt.get("ftd")
    have_m = ("rynek w trendzie wzrostowym" + (" (przez potwierdzony Follow-Through Day)" if ftd else "") + (f", dni dystrybucji (max z indeksów): {dist}" if _num(dist) else "")) \
        if regime == "uptrend" else "rynek w korekcie (brak potwierdzonego Follow-Through Day)" if regime == "correction" else "brak danych o rynku"
    add("M", f"S&P 500 i Nasdaq w trendzie wzrostowym (EMA10 > EMA20 tyg.) albo po korekcie z potwierdzonym FTD, i mniej niż {T['distDays']} dni dystrybucji", have_m)
    return {"score": c["score"], "known": c["known"], "rows": rows}
