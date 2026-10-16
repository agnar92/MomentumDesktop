"""Reguły Darvasa na tygodniowych zamknięciach — port 1:1 z Momentum (docs/js/darvas.js).

Box = GÓRA (zamknięcie nieprzebite przez `confirm` kolejnych tygodni) + DÓŁ (najniższe zamknięcie po górze, niezłamane przez
`confirm` tygodni). Zamknięcie nad górą = punkt kupna i nowy, wyższy box; zamknięcie pod potwierdzonym dołem = box złamany.
Strefa zagrożenia = 5 % pod dołem boxa (jej dolna krawędź = exit). Heurystyka, nie rekomendacja.
"""
import math

CONFIRM = 2            # tygodniowo: góra / dół = zamknięcie + 2 kolejne bez przebicia (na dziennym wg PDF: 3 sesje — CONFIRM_DAILY)
CONFIRM_DAILY = 3
MIN_HEIGHT_PCT = 1.5
MAX_DEPTH_PCT = 25      # box nie może być głębszy: zamknięcie > 25 % pod górą kończy (łamie) box, zanim dół zdążył się potwierdzić
STOP_PCT = 5            # szerokość strefy zagrożenia pod dołem boxa
MAX_EXT_PCT = 10        # KUP tylko do 10 % nad górą boxa
BREAKOUT_VOL = 1.4      # wolumen wybicia >= 1,4x średniej z 10 tygodni
VOL_WEEKS = 10
START_STOP_PCT = 10     # stop początkowy przy pierwszym wybiciu
PURE = False            # „czysty Darvas” jak w PDF: KUP = samo przebicie góry (bez filtru wolumenu i limitu +10 % nad górą)
NEW_WEEKS = 4           # box jest „nowy”, gdy jego góra została potwierdzona w ostatnich tylu tygodniach


def _ok(v):
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


def _r2(v):
    """Zaokrąglenie do 2 miejsc; liczby całkowite bez „.0” (tak samo jak liczby w JS)."""
    r = round(v * 100) / 100
    return int(r) if r == int(r) else r


def last_real(c):
    n = len(c)
    while n > 0 and not _ok(c[n - 1]):
        n -= 1
    return n - 1


def confirm_for(tf):
    return CONFIRM_DAILY if tf == "D" else CONFIRM


def boxes(c, confirm=None, bottom_confirm=None):
    """[{i0, i1, top, bottom, confirmed, outcome: up|down|open}] rosnąco po czasie. confirm: ile kolejnych zamknięć nie może przebić góry / dołu."""
    confirm = CONFIRM if confirm is None else confirm
    bottom_confirm = confirm if bottom_confirm is None else bottom_confirm
    n = last_real(c) + 1
    out = []
    i = 0
    while i < n:
        floor = out[-1]["bottom"] if out and out[-1]["outcome"] == "up" else None   # schodek: powrót pod dół poprzedniego boxa = nieudane wybicie
        top, t, run_max = None, -1, -math.inf
        for k in range(i, n):
            if not _ok(c[k]) or c[k] < run_max:
                continue
            run_max = c[k]
            if k + confirm < n and all(_ok(v) and v <= c[k] for v in c[k + 1:k + confirm + 1]):   # luka w danych (None) nie potwierdza szczytu — jak NaN w JS
                t, top = k, c[k]
                break
        if t < 0:
            break
        bottom, bi, confirmed, end, outcome = math.inf, -1, False, -1, "open"
        for j in range(t + 1, n):
            v, ok = c[j], _ok(c[j])   # tydzień bez notowania (None) nie zmienia boxa, ale upływ czasu liczy się do potwierdzenia dołu
            if ok and v > top:
                outcome, end = "up", j
                break
            if ok and floor is not None and v < floor:   # cena wróciła pod dół boxa, z którego wybiła: schodek się zawalił, nowy box jest anulowany
                outcome, end = "down", j
                break
            if ok and v < top * (1 - MAX_DEPTH_PCT / 100):   # spadek jak z klifu: dół nie zdążył się utworzyć, box jest złamany (inaczej jeden „box” pochłaniał całą korektę)
                outcome, end = "down", j
                break
            if confirmed and ok and v < bottom:
                outcome, end = "down", j
                break
            if not confirmed and ok and v < bottom:
                bottom, bi = v, j
            if not confirmed and bi >= 0 and j - bi >= bottom_confirm:
                confirmed = True
        if end < 0:
            end = n - 1
        if math.isfinite(bottom) and (top - bottom) / top * 100 >= MIN_HEIGHT_PCT:
            out.append({"i0": t, "i1": end, "top": top, "bottom": bottom, "confirmed": confirmed, "outcome": outcome})
        i = n if outcome == "open" else end
    return out


def box_info(top, bottom, zone_pct=STOP_PCT):
    """Ceny boxa: wejście = góra, anulowanie = dół, exit = dół strefy zagrożenia."""
    stop = _r2(bottom * (1 - zone_pct / 100))
    return {"entry": _r2(top), "cancel": _r2(bottom), "stop": stop, "stop_pct": _r2((1 - stop / top) * 100),
            "zone_pct": zone_pct, "depth_pct": _r2((top - bottom) / top * 100)}


def status(c, vol=None, zone_pct=STOP_PCT, max_ext_pct=MAX_EXT_PCT, vol_bars=VOL_WEEKS, pure=None, unit="tygodnia", confirm=None):
    """Stan na ostatnim zamknięciu (tydzień / sesja): BUY / NOVOL / LATE / HOLD / SELL / WAIT / NONE. pure (domyślnie `PURE`): bez NOVOL i LATE."""
    pure = PURE if pure is None else pure
    bx = boxes(c, confirm)
    lr = last_real(c)
    if not bx or lr < 0:
        return {"state": "NONE", "text": "brak boxa Darvasa (za mało danych)"}
    last, prev = bx[-1], (bx[-2] if len(bx) > 1 else None)
    had_up = bool(prev and prev["outcome"] == "up")
    zone_from = _r2(last["bottom"])
    stop = _r2(last["bottom"] * (1 - zone_pct / 100))
    base = {"top": _r2(last["top"]), "bottom": zone_from, "zone_from": zone_from, "stop": stop}
    if last["outcome"] == "up" and last["i1"] == lr:
        over = c[lr] / last["top"] - 1
        vr = None
        if vol and lr < len(vol) and _ok(vol[lr]):
            pv = [v for v in vol[max(0, lr - vol_bars):lr] if _ok(v)]
            if len(pv) >= 4:
                vr = vol[lr] / (sum(pv) / len(pv))
        if not pure and vr is not None and vr < BREAKOUT_VOL:
            return {**base, "state": "NOVOL", "vol_ratio": round(vr, 2),
                    "text": f"BEZ WOLUMENU — zamknięcie nad górą boxa {_r2(last['top'])}, ale wolumen tylko {vr:.2f}× średniej (wymagane {BREAKOUT_VOL}×); niepotwierdzone"}
        if not pure and over > max_ext_pct / 100:
            return {**base, "state": "LATE",
                    "text": f"ZA PÓŹNO — zamknięcie {over * 100:.1f} % nad górą boxa {_r2(last['top'])} (limit {max_ext_pct} %), nie goń"}
        vtxt = "" if vr is None else f" na wolumenie {vr:.2f}×"
        return {**base, "state": "BUY", "stop": _r2(last["top"] * (1 - START_STOP_PCT / 100)),
                "vol_ratio": None if vr is None else round(vr, 2),
                "text": f"KUP — zamknięcie nad górą boxa {_r2(last['top'])}{vtxt}; stop początkowy ok. {START_STOP_PCT} % pod wejściem ({_r2(last['top'] * (1 - START_STOP_PCT / 100))}), potem pod dnem kolejnych boxów"}
    # zamknięcie pod dnem boxa = od razu SPRZEDAJ (wchodzimy w 5 % strefę zagrożenia); sygnał trwa, dopóki cena
    # nie wróci nad złamane dno (nowy box tworzy się już pod nim)
    broken = next((b for b in (last, prev) if b and b["outcome"] == "down" and c[lr] < b["bottom"]), None)
    if broken:
        zb = _r2(broken["bottom"])
        zs = _r2(broken["bottom"] * (1 - zone_pct / 100))
        return {**base, "state": "SELL", "bottom": zb, "zone_from": zb, "stop": zs,
                "text": f"SPRZEDAJ — cena zeszła pod dno boxa {zb} (strefa zagrożenia {zs}–{zb}, exit pod {zs})"}
    if last["outcome"] == "up":
        return {**base, "state": "HOLD", "text": f"TRZYMAJ — wybicie nad {_r2(last['top'])} jest za nami, czekamy na nowy, wyższy box; stop pod dnem ostatniego boxa {stop}"}
    if had_up:
        return {**base, "state": "HOLD", "text": f"TRZYMAJ — cena w najwyższym boxie {zone_from}–{_r2(last['top'])}, wahania w nim ignorujemy; stop pod strefą zagrożenia {stop}"}
    return {**base, "state": "WAIT", "text": f"CZEKAJ — pierwszy box {zone_from}–{_r2(last['top'])}; kup po zamknięciu {unit} nad {_r2(last['top'])}"}


def pin_status(box, price, zone_pct=STOP_PCT):
    """Status przypiętego (monitorowanego) boxa względem ceny: ABOVE / INSIDE / ZONE / EXIT."""
    if not box or not _ok(price) or not box["top"] > box["bottom"]:
        return {"state": "NONE", "rank": 9, "text": ""}
    zone = _r2(box["bottom"] * (1 - zone_pct / 100))
    top, bottom = box["top"], box["bottom"]
    if price > top:
        return {"state": "ABOVE", "rank": 1, "text": f"wybił nad {_r2(top)} (+{(price / top - 1) * 100:.1f} %)"}
    if price >= bottom:
        return {"state": "INSIDE", "rank": 2, "text": f"w boxie {_r2(bottom)}–{_r2(top)}, do wybicia {(top / price - 1) * 100:.1f} %"}
    if price >= zone:
        return {"state": "ZONE", "rank": 0, "text": f"W STREFIE ZAGROŻENIA {zone}–{_r2(bottom)} — potencjalny exit"}
    return {"state": "EXIT", "rank": 0, "text": f"EXIT — cena {_r2(price)} poniżej strefy zagrożenia ({zone})"}


DAILY = {"max_ext_pct": 5, "vol_bars": 50, "unit": "sesji", "confirm": CONFIRM_DAILY}   # wykres dzienny: wybicie nie dalej niż 5 % nad górą, wolumen vs średnia z 50 sesji


def overview(items, weeks, pinned=None, new_weeks=NEW_WEEKS, params=None):
    """Podział spółek na sekcje: pinned, fresh, buy, check, hold, sell, wait.
    items = [{ticker, price, c, v}]; zwraca {sekcja: [{ticker, price, state, text, box}]}."""
    pinned = pinned or {}
    out = {k: [] for k in ("pinned", "fresh", "buy", "check", "hold", "sell", "wait")}
    for it in items:
        c = it.get("c") or []
        lr = last_real(c)
        if lr < 0:
            continue
        pin = pinned.get(it["ticker"])
        if pin:
            st = pin_status(pin, it.get("price"))
            if st["state"] != "NONE":
                out["pinned"].append({"ticker": it["ticker"], "price": it.get("price"), "state": st["state"], "rank": st["rank"],
                                      "text": st["text"], "box": dict(pin)})
        ds = status(c, it.get("v"), **(params or {}))
        conf = (params or {}).get("confirm") or CONFIRM
        bx = boxes(c, conf)
        last = bx[-1] if bx else None
        if ds["state"] == "NONE" or not last:
            continue
        box = {"top": _r2(last["top"]), "bottom": _r2(last["bottom"]), "start": (weeks[last["i0"]] if weeks and last["i0"] < len(weeks) else ""),
               "i0": last["i0"], "i1": last["i1"]}
        row = {"ticker": it["ticker"], "price": it.get("price"), "state": ds["state"], "text": ds["text"], "box": box}
        sect = {"BUY": "buy", "NOVOL": "check", "LATE": "check", "HOLD": "hold", "SELL": "sell", "OUT": "sell", "WAIT": "wait"}.get(ds["state"])
        if sect:
            out[sect].append(row)
        # nowe boxy: góra potwierdzona (i0 + potwierdzenie) w ostatnich `new_weeks` tygodniach
        fresh = [b for b in bx if lr - (new_weeks - 1) <= b["i0"] + conf <= lr]
        if fresh:
            f = fresh[-1]
            st = "ABOVE" if f["outcome"] == "up" else "EXIT" if f["outcome"] == "down" else "INSIDE"
            wk = weeks[f["i0"]] if weeks and f["i0"] < len(weeks) else "?"
            out["fresh"].append({"ticker": it["ticker"], "price": it.get("price"), "state": st,
                                 "text": f"box {_r2(f['bottom'])}–{_r2(f['top'])} od {wk}", "box": {**box, "top": _r2(f["top"]), "bottom": _r2(f["bottom"]), "i0": f["i0"], "i1": f["i1"], "start": wk}})
    for k in ("fresh", "buy", "check", "hold", "sell", "wait"):
        out[k].sort(key=lambda r: r["ticker"])
    out["pinned"].sort(key=lambda r: (r["rank"], r["ticker"]))
    return out
