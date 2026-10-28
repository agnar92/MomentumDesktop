"""Linie trendu i alerty (ta sama logika co docs/js/lines.js w wersji webowej). Linia = dwa punkty {d1, p1, d2, p2} (data tygodnia + cena), prosta na
skali logarytmicznej, przedłużona w prawo do ostatniego tygodnia. Alert linii: zamknięcie tygodnia przecięło linię. Obserwowana spółka (🔔): sygnał GLB,
przecięcie MACD w dół, zamknięcie pod stopem MACD, zamknięcie pod Green Line, spełnione warunki; pozycja (📌): spadek 20 % od szczytu = sprzedaj
połowę. Zapis: data/alerts.json {lines, watch, pos, log, seen}."""
import bisect
import math

SIGNAL_STATES = ("WYBICIE", "SYGNAŁ", "BLUE DOT")
MAX_LOG = 200
STOP_PCT = 10.0    # stop początkowy pod ceną kupna
HALF_DROP = 20.0   # spadek od szczytu (zamknięcia tygodnia od wejścia), przy którym można sprzedać połowę (wynik bez zmian, opcja)
MAX_POSITIONS = 10   # portfel: 10 pozycji po równo; wolne miejsca = gotówka w SPY do nowego sygnału


def date_index(dates, d):
    """Indeks tygodnia daty: dokładny albo ostatni wcześniejszy; -1, gdy data przed historią."""
    return bisect.bisect_right(dates, d) - 1


def line_at(line, dates, j):
    """Wartość linii w tygodniu j (interpolacja na log ceny); None, gdy punkty nie leżą w historii albo w tym samym tygodniu."""
    a, b = date_index(dates, line["d1"]), date_index(dates, line["d2"])
    if a < 0 or b < 0 or a == b:
        return None
    la, lb = math.log(line["p1"]), math.log(line["p2"])
    return math.exp(la + (lb - la) * (j - a) / (b - a))


def line_cross(line, data):
    """Przecięcie zamknięciem w ostatnim tygodniu: 'up' / 'down' / None (tylko po pierwszym punkcie linii)."""
    c = data["c"]
    j = len(c) - 1
    if j < 1 or c[j] is None or c[j - 1] is None:
        return None
    if j - 1 < min(date_index(data["d"], line["d1"]), date_index(data["d"], line["d2"])):
        return None
    v0, v1 = line_at(line, data["d"], j - 1), line_at(line, data["d"], j)
    if v0 is None or v1 is None:
        return None
    if c[j - 1] < v0 and c[j] >= v1:
        return "up"
    if c[j - 1] >= v0 and c[j] < v1:
        return "down"
    return None


def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L)) if L else 0.0
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def hit_line(segs, x, y, tol):
    """segs = [{id, x1, y1, x2, y2, xe, ye}] (xe/ye = koniec przedłużenia) -> (id, 'p1' | 'p2' | 'body') albo None; uchwyt końca ma pierwszeństwo."""
    best = None
    for s in segs:
        for part in ("p1", "p2"):
            d = math.hypot(x - s["x" + part[1]], y - s["y" + part[1]])
            if d <= tol * 1.4 and (best is None or d - tol < best[0]):
                best = (d - tol, s["id"], part)
        d = min(seg_dist(x, y, s["x1"], s["y1"], s["x2"], s["y2"]), seg_dist(x, y, s["x2"], s["y2"], s["xe"], s["ye"]))
        if d <= tol and (best is None or d < best[0]):
            best = (d, s["id"], "body")
    return best and (best[1], best[2])


def snap_price(price, hi, lo, yf, y, tol):
    """Magnes: cena przyciągana do High / Low tygodnia, gdy kursor jest bliżej niż tol px."""
    best, bd = price, tol
    for v in (hi, lo):
        if v is None:
            continue
        d = abs(yf(v) - y)
        if d <= bd:
            best, bd = v, d
    return best


def snap_horizontal(price, other, yf, y, tol):
    """Magnes poziomy: cena przyciągana do ceny drugiego końca linii, gdy kursor jest bliżej niż tol px od jej poziomu (-> linia dokładnie pozioma)."""
    return other if other is not None and abs(yf(other) - y) <= tol else price


def state_alerts(prev, row):
    """Zmiany stanu obserwowanej spółki (prev = stan z poprzedniego sprawdzenia) -> lista komunikatów."""
    out = []
    if not prev or not row:
        return out
    if row.get("glb_state") in SIGNAL_STATES and prev.get("glb_state") not in SIGNAL_STATES:
        out.append(f"sygnał GLB: {row['glb_state']} (Green Line {row.get('glb')})")
    if prev.get("macd") == "nad" and row.get("macd") == "pod":
        out.append(f"MACD tyg. przeciął sygnał w dół — stop pod Low {row.get('macd_stop')}")
    stop, price = row.get("macd_stop"), row.get("price")
    was = prev.get("price") is not None and prev.get("macd_stop") and prev["price"] < prev["macd_stop"]
    if stop and price is not None and price < stop and not was:
        out.append(f"zamknięcie {price} pod stopem MACD {stop}")
    if row.get("glb_state") == "POD" and prev.get("glb_state") not in (None, "POD", "BRAK"):
        out.append(f"zamknięcie tygodnia pod Green Line {row.get('glb')} — wyjście (metoda GLB)")
    if row.get("ok") and not prev.get("ok"):
        out.append("spełnia warunki strategii")
    if row.get("slow") and row.get("slow") != prev.get("slow"):
        a = f"{row['accel']:.0f}" if row.get("accel") is not None else ""
        out.append(f"⚠ hamowanie: tempo przychodów {a} pp i marża brutto spada r/r — zacieśnij stop" if row["slow"] == "HAMUJE+MB"
                   else f"⚠ hamowanie: tempo przychodów {a} pp względem kwartału wcześniej")
    return out


def _ema(values, n):
    k, out, prev = 2 / (n + 1), [], None
    for v in values:
        prev = v if prev is None else prev + k * (v - prev)
        out.append(prev)
    return out


def macd_stop_since(data, since):
    """Stop MACD pozycji: Low ostatniego tygodnia, w którym MACD (12, 26, 9) przeciął sygnał w dół PO tygodniu wejścia; None = jeszcze nie było
    (badanie 2011–2025: przecięcia sprzed wejścia obniżały wynik z ≈ 21 % do ≈ 13 % rocznie)."""
    c, lo, d = (data or {}).get("c") or [], (data or {}).get("l") or [], (data or {}).get("d") or []
    if len(c) < 35 or not lo:
        return None
    m = [a - b for a, b in zip(_ema(c, 12), _ema(c, 26))]
    h = [a - b for a, b in zip(m, _ema(m, 9))]
    out = None
    for i in range(max(1, date_index(d, since or "") + 1), len(c)):
        if h[i] < 0 <= h[i - 1] and lo[i] is not None:
            out = lo[i]
    return out


def position_plan(pos, data, row):
    """Plan wyjścia pozycji: pos = {since, price}, data = tygodniowe {d, c, l}, row = wiersz (glb) -> {entry, stop_init (−10 %), macd_stop (MACD od
    wejścia), peak (najwyższe zamknięcie tygodnia od wejścia), half_at (−20 % od szczytu), half (ostatnie zamknięcie ≤ half_at), last, glb_exit}."""
    c, d = (data or {}).get("c") or [], (data or {}).get("d") or []
    entry = (pos or {}).get("price")
    peak = entry
    for x, day in zip(c, d):
        if x is not None and day >= ((pos or {}).get("since") or "") and (peak is None or x > peak):
            peak = x
    last = c[-1] if c else None
    half_at = peak * (1 - HALF_DROP / 100) if peak is not None else None
    glb = (row or {}).get("glb")
    return {"entry": entry, "stop_init": entry * (1 - STOP_PCT / 100) if entry is not None else None,
            "macd_stop": macd_stop_since(data, (pos or {}).get("since")), "peak": peak, "half_at": half_at, "last": last,
            "half": last is not None and half_at is not None and last <= half_at, "glb_exit": bool(last is not None and glb and last < glb)}


def position_size(capital_pln, usdpln, entry, stop, risk_pct):
    """Wielkość pozycji w USD z kapitału w PLN: kapitał / kurs (usdpln = PLN za 1 USD); ryzyko = risk_pct % kapitału; akcje = ryzyko / (wejście − stop),
    nie więcej niż za cały kapitał (całe akcje, w dół). -> dict albo None (brak danych, kurs ≤ 0 albo stop nie jest pod ceną wejścia)."""
    try:
        capital_pln, usdpln, entry, stop, risk_pct = (float(x) for x in (capital_pln, usdpln, entry, stop, risk_pct))
    except (TypeError, ValueError):
        return None
    if min(capital_pln, usdpln, entry) <= 0 or risk_pct < 0 or not 0 < stop < entry:
        return None
    capital_usd = capital_pln / usdpln
    risk_usd = capital_usd * risk_pct / 100
    per_share = entry - stop
    by_risk, by_capital = int(risk_usd // per_share), int(capital_usd // entry)
    shares = min(by_risk, by_capital)
    value_usd, loss_usd = shares * entry, shares * per_share
    return {"capital_usd": capital_usd, "risk_usd": risk_usd, "risk_pln": risk_usd * usdpln, "per_share": per_share, "shares": shares,
            "limited_by": "kapitał" if by_capital < by_risk else "ryzyko", "value_usd": value_usd, "value_pln": value_usd * usdpln,
            "value_pct": value_usd / capital_usd * 100, "loss_usd": loss_usd, "loss_pln": loss_usd * usdpln, "loss_pct": loss_usd / capital_usd * 100,
            "full_shares": by_capital, "full_loss_usd": by_capital * per_share, "full_loss_pln": by_capital * per_share * usdpln,
            "full_loss_pct": by_capital * per_share / capital_usd * 100}


def position_status(plan, row, exit_method="MACD"):
    """Co zrobić z pozycją teraz -> lista komunikatów (pusta = trzymaj): stop −10 %, ½ przy −20 % od szczytu, wyjście wg metody, hamowanie."""
    out, r, pl = [], row or {}, plan or {}
    last = pl.get("last")
    if last is not None and pl.get("stop_init") is not None and last <= pl["stop_init"]:
        out.append("STOP −10 %")
    if exit_method == "GLB" and pl.get("glb_exit"):
        out.append("WYJŚCIE: zamknięcie pod GLB")
    ms = pl["macd_stop"] if "macd_stop" in pl else r.get("macd_stop")   # plan pozycji: MACD od wejścia
    if exit_method != "GLB" and ms and last is not None and last < ms:
        out.append("WYJŚCIE: pod stopem MACD")
    if pl.get("half"):
        out.append("SPRZEDAJ ½ (−20 % od szczytu)")
    for p in r.get("patterns") or []:   # wzorce niedźwiedzie (Head & Shoulders, Rising Wedge): ostrzeżenie przy wyjściu
        if p.get("side") == "sell":
            out.append(f"⚠ {p['name']}: " + ("złamana linia — sprzedaż" if p["state"] == "ZŁAMANA" else f"uwaga na linię {p['buy']:.2f}"))
    if r.get("parabola"):
        out.append("⚠ PARABOLA: złamana najbardziej stroma linia — sprzedaż" if r["parabola"].get("state") == "ZŁAMANA"
                   else "⚠ PARABOLA: wyjście przy zamknięciu tygodnia pod najbardziej stromą linią")
    if r.get("slow"):
        out.append("⚠ hamuje" + (" + marża brutto" if r["slow"] == "HAMUJE+MB" else ""))
    return out


def snapshot(r):
    return {"glb_state": r.get("glb_state"), "macd": r.get("macd"), "macd_stop": r.get("macd_stop"), "price": r.get("price"), "ok": bool(r.get("ok")), "slow": r.get("slow")}


def eval_alerts(st, row_for, series_for, now, as_of="", daily_for=None):
    """Sprawdza linie tygodniowe i dzienne oraz alerty pozycji/obserwowanych spółek.
    daily_for(t) zwraca cache świec dziennych; stare linie bez period traktowane są jako tygodniowe."""
    seen, fresh = {a["key"] for a in st["log"]}, []

    def add(key, t, day, msg):
        if key not in seen:
            seen.add(key)
            fresh.append({"key": key, "t": t, "week": day, "msg": msg, "at": now})

    for t, ticker_lines in st.get("lines", {}).items():
        for ln in ticker_lines:
            period = ln.get("period", "W")
            data = daily_for(t) if period == "D" and daily_for else None if period == "D" else series_for(t)
            if not data or len(data.get("c") or []) < 2:
                continue
            day = data["d"][-1]
            if ln.get("alert") is False:
                continue
            cross = line_cross(ln, data)
            if cross:
                v = line_at(ln, data["d"], len(data["c"]) - 1)
                if period == "D":
                    key = f"L:{t}:D:{ln['id']}:{day}:{cross}"
                    label = "zamknięcie dzienne"
                else:
                    key = f"L:{t}:{ln['id']}:{day}:{cross}"
                    label = "zamknięcie"
                add(key, t, day, f"{label} {'nad linią' if cross == 'up' else 'pod linią'} trendu ({v:.2f})")
    for t, p in (st.get("pos") or {}).items():   # pozycja: spadek 20 % od szczytu -> sprzedaj połowę (raz na szczyt)
        data = series_for(t)
        if not data or not data.get("c"):
            continue
        pl = position_plan(p, data, row_for(t))
        if pl["half"]:
            add(f"H:{t}:{pl['peak']}", t, data["d"][-1], f"spadek {HALF_DROP:.0f} % od szczytu {pl['peak']:.2f} (zamknięcie {pl['last']:.2f}) — sprzedaj połowę")
    for t in list(st.get("watch", {})):
        row = row_for(t)
        if not row:
            continue
        for msg in state_alerts(st["watch"][t], row):
            add(f"W:{t}:{msg}:{as_of}", t, as_of, msg)
        st["watch"][t] = snapshot(row)
    st["log"] = (fresh[::-1] + st["log"])[:MAX_LOG]
    return fresh
