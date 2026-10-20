"""Linie trendu i alerty (ta sama logika co docs/js/lines.js w wersji webowej). Linia = dwa punkty {d1, p1, d2, p2} (data tygodnia + cena), prosta na
skali logarytmicznej, przedłużona w prawo do ostatniego tygodnia. Alert linii: zamknięcie tygodnia przecięło linię. Obserwowana spółka (🔔): sygnał GLB,
przecięcie MACD w dół, zamknięcie pod stopem MACD, spełnione warunki. Zapis: data/alerts.json {lines, watch, log, seen}."""
import bisect
import math

SIGNAL_STATES = ("WYBICIE", "SYGNAŁ")
MAX_LOG = 200


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
    if row.get("ok") and not prev.get("ok"):
        out.append("spełnia warunki strategii")
    return out


def snapshot(r):
    return {"glb_state": r.get("glb_state"), "macd": r.get("macd"), "macd_stop": r.get("macd_stop"), "price": r.get("price"), "ok": bool(r.get("ok"))}


def eval_alerts(st, row_for, series_for, now, as_of=""):
    """st = {lines: {ticker: [linia]}, watch: {ticker: stan}, log: [...]} -> nowe wpisy (st['log'] i st['watch'] są aktualizowane).
    Klucz zawiera tydzień, więc ten sam alert nie wraca przy następnym sprawdzeniu."""
    seen, fresh = {a["key"] for a in st["log"]}, []

    def add(key, t, week, msg):
        if key not in seen:
            seen.add(key)
            fresh.append({"key": key, "t": t, "week": week, "msg": msg, "at": now})

    for t, lines in st.get("lines", {}).items():
        data = series_for(t)
        if not data or len(data.get("c") or []) < 2:
            continue
        week = data["d"][-1]
        for ln in lines:
            if ln.get("alert") is False:
                continue
            x = line_cross(ln, data)
            if x:
                v = line_at(ln, data["d"], len(data["c"]) - 1)
                add(f"L:{t}:{ln['id']}:{week}:{x}", t, week, f"zamknięcie {'nad linią' if x == 'up' else 'pod linią'} trendu ({v:.2f})")
    for t in list(st.get("watch", {})):
        row = row_for(t)
        if not row:
            continue
        for msg in state_alerts(st["watch"][t], row):
            add(f"W:{t}:{msg}:{as_of}", t, as_of, msg)
        st["watch"][t] = snapshot(row)
    st["log"] = (fresh[::-1] + st["log"])[:MAX_LOG]
    return fresh
