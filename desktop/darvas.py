"""Reguły Darvasa na tygodniowych zamknięciach — port 1:1 z Momentum (docs/js/darvas.js).

Box = GÓRA (zamknięcie nieprzebite przez 3 kolejne tygodnie) + DÓŁ (najniższe zamknięcie po górze, niezłamane przez 3 tygodnie); rysujemy
tylko potwierdzone boxy, a sam top to przerywana linia (stop 8 %). Zamknięcie nad górą = próba przebicia (box nadal obowiązuje, aż powstanie
nowy wyżej); zejście pod dno anuluje box (przed wybiciem: odwrócony box). Strefa zagrożenia = 5 % pod dołem. Heurystyka, nie rekomendacja.
"""
import math

CONFIRM = 3            # góra / dół = zamknięcie, którego nie przebija (nie jest niższe od) kolejne 3 tygodnie
CONFIRM_DAILY = 3
MIN_HEIGHT_PCT = 1.5
STOP_PCT = 5            # szerokość strefy zagrożenia pod dołem boxa
LINE_STOP_PCT = 8       # sam top (bez potwierdzonego dołu): stop 8 % pod topem
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


def _scan(c, confirm, bottom_confirm):
    """(boxy potwierdzone, linie samego topu). Box: góra (zamknięcie nieprzebite przez `confirm` kolejnych zamknięć, lokalny szczyt) + dół
    (najniższe zamknięcie po górze, niezłamane przez `confirm` kolejnych zamknięć). Dopóki dół się nie potwierdzi, jest tylko linia topu."""
    n = last_real(c) + 1
    bxs, lines = [], []
    i = 0
    ref = None      # indeks wybitego boxa, który nadal obowiązuje (do utworzenia nowego boxa wyżej)
    while i < n:
        ref_top = bxs[ref]["top"] if ref is not None else None
        ref_bot = bxs[ref]["bottom"] if ref is not None else None
        top, t, run_max = None, -1, -math.inf
        for k in range(i, n):
            if not _ok(c[k]) or c[k] < run_max or (ref_top is not None and c[k] <= ref_top):
                continue
            prev = [c[m] for m in range(max(0, k - confirm), k) if _ok(c[m])]
            if not all(c[k] > p for p in prev):    # nie jest lokalnym szczytem (cena nie rosła do niego) — nie podnosi też run_max
                continue
            run_max = c[k]
            if k + confirm < n and all(_ok(v) and v <= c[k] for v in c[k + 1:k + confirm + 1]):   # luka w danych (None) nie potwierdza szczytu — jak NaN w JS
                t, top = k, c[k]
                break
        if ref is not None:    # cena zeszła w strefę zagrożenia wybitego boxa, zanim powstał nowy box nad nim: box anulowany, szukamy od nowa
            hit = next((k for k in range(i, (t if t >= 0 else n - 1) + 1) if _ok(c[k]) and c[k] < ref_bot), None)
            if hit is not None:
                bxs[ref]["end"], bxs[ref]["cancelled"] = hit, True
                ref, i = None, hit
                continue
        if t < 0:
            break
        bottom, bi, confirmed, end, outcome = math.inf, -1, False, -1, "open"
        cancel = None
        for j in range(t + 1, n):
            v, ok = c[j], _ok(c[j])   # tydzień bez notowania (None) nie zmienia boxa, ale upływ czasu liczy się do potwierdzenia dołu
            if ok and v > top:
                outcome, end = "up", j
                break
            if ok and ref is not None and not confirmed and v < ref_bot:
                cancel = j
                break
            if confirmed and ok and v < bottom:     # box nie wybity, a jego dół przebity: anulowany (odwrócony box, strefa zagrożenia u góry)
                outcome, end = "down", j
                break
            if not confirmed and ok and v < bottom:
                bottom, bi = v, j
            if not confirmed and bi >= 0 and j - bi >= bottom_confirm:
                confirmed = True
        if cancel is not None:
            bxs[ref]["end"], bxs[ref]["cancelled"] = cancel, True
            ref, i = None, cancel
            continue
        if end < 0:
            end = n - 1
        good = confirmed and math.isfinite(bottom) and (top - bottom) / top * 100 >= MIN_HEIGHT_PCT
        if not confirmed:
            lines.append({"i0": t, "i1": end, "top": top, "open": outcome == "open"})
        elif good:
            if ref is not None:
                bxs[ref]["end"] = t     # nowy box (nad starym) przejmuje obowiązywanie
            bxs.append({"i0": t, "i1": end, "end": end, "top": top, "bottom": bottom, "confirmed": True, "outcome": outcome})
            ref = len(bxs) - 1 if outcome == "up" else None
        if outcome == "open":
            break
        i = end
    if ref is not None:
        bxs[ref].setdefault("end", n - 1)
        if not bxs[ref].get("cancelled"):
            bxs[ref]["end"] = n - 1
    return bxs, lines


def boxes(c, confirm=None, bottom_confirm=None):
    """Potwierdzone boxy [{i0, i1, end, top, bottom, confirmed: True, outcome: up|down|open, cancelled?}] rosnąco po czasie.

    outcome up = próba przebicia (zamknięcie nad górą): box nadal obowiązuje (`end` = dokąd), nawet gdy cena wróci do boxa, aż powstanie
    nowy box nad nim; zejście pod dół wybitego boxa (strefa zagrożenia) anuluje go (`cancelled`). down = box nie wybity, a jego dół przebity
    (odwrócony box). Po anulowaniu szukamy nowego boxa."""
    confirm = CONFIRM if confirm is None else confirm
    return _scan(c, confirm, confirm if bottom_confirm is None else bottom_confirm)[0]


def top_lines(c, confirm=None, bottom_confirm=None):
    """Same topy bez potwierdzonego dołu [{i0, i1, top, open}]: linia przerywana od topu do wybicia (open = jeszcze nie przebity). Stop 8 % pod topem."""
    confirm = CONFIRM if confirm is None else confirm
    return _scan(c, confirm, confirm if bottom_confirm is None else bottom_confirm)[1]


def line_info(top, stop_pct=LINE_STOP_PCT):
    """Sam top: wejście = zamknięcie nad topem, stop = 8 % pod topem."""
    return {"entry": _r2(top), "stop": _r2(top * (1 - stop_pct / 100)), "stop_pct": stop_pct}


def box_info(top, bottom, zone_pct=STOP_PCT):
    """Ceny boxa: wejście = góra, anulowanie = dół, exit = dół strefy zagrożenia."""
    stop = _r2(bottom * (1 - zone_pct / 100))
    return {"entry": _r2(top), "cancel": _r2(bottom), "stop": stop, "stop_pct": _r2((1 - stop / top) * 100),
            "zone_pct": zone_pct, "depth_pct": _r2((top - bottom) / top * 100)}


def _buy(c, lr, top, vol, vol_bars, pure, max_ext_pct, base, stop, stop_txt):
    """Wybicie nad `top` w ostatnim tygodniu: KUP / BEZ WOLUMENU / ZA PÓŹNO."""
    over = c[lr] / top - 1
    vr = None
    if vol and lr < len(vol) and _ok(vol[lr]):
        pv = [v for v in vol[max(0, lr - vol_bars):lr] if _ok(v)]
        if len(pv) >= 4:
            vr = vol[lr] / (sum(pv) / len(pv))
    if not pure and vr is not None and vr < BREAKOUT_VOL:
        return {**base, "state": "NOVOL", "vol_ratio": round(vr, 2),
                "text": f"BEZ WOLUMENU — zamknięcie nad górą {_r2(top)}, ale wolumen tylko {vr:.2f}× średniej (wymagane {BREAKOUT_VOL}×); niepotwierdzone"}
    if not pure and over > max_ext_pct / 100:
        return {**base, "state": "LATE", "text": f"ZA PÓŹNO — zamknięcie {over * 100:.1f} % nad górą {_r2(top)} (limit {max_ext_pct} %), nie goń"}
    vtxt = "" if vr is None else f" na wolumenie {vr:.2f}×"
    return {**base, "state": "BUY", "stop": stop, "vol_ratio": None if vr is None else round(vr, 2),
            "text": f"KUP — zamknięcie nad górą {_r2(top)}{vtxt}; {stop_txt}"}


def status(c, vol=None, zone_pct=STOP_PCT, max_ext_pct=MAX_EXT_PCT, vol_bars=VOL_WEEKS, pure=None, unit="tygodnia", confirm=None):
    """Stan na ostatnim zamknięciu (tydzień / sesja): BUY / NOVOL / LATE / HOLD / SELL / WAIT / NONE. pure (domyślnie `PURE`): bez NOVOL i LATE."""
    pure = PURE if pure is None else pure
    confirm = CONFIRM if confirm is None else confirm
    bx, ln = _scan(c, confirm, confirm)
    lr = last_real(c)
    if lr < 0 or (not bx and not ln):
        return {"state": "NONE", "text": "brak boxa Darvasa (za mało danych)"}
    px = c[lr]
    prev_px = c[lr - 1] if lr > 0 and _ok(c[lr - 1]) else None
    last = bx[-1] if bx else None
    if last is None:    # jest tylko top, bez potwierdzonego dołu
        tl = ln[-1]
        li = line_info(tl["top"])
        base = {"top": li["entry"], "stop": li["stop"]}
        if not tl["open"] and tl["i1"] == lr:
            return _buy(c, lr, tl["top"], vol, vol_bars, pure, max_ext_pct, base, li["stop"], f"sam top bez potwierdzonego dołu, stop {LINE_STOP_PCT} % pod topem ({li['stop']})")
        if tl["open"]:
            return {**base, "state": "WAIT", "text": f"CZEKAJ — jest tylko top {li['entry']} (dół jeszcze niepotwierdzony); kup po zamknięciu {unit} nad nim, stop {LINE_STOP_PCT} % ({li['stop']})"}
        return {**base, "state": "HOLD", "text": f"TRZYMAJ — top {li['entry']} przebity, czekamy na potwierdzony box; stop {LINE_STOP_PCT} % pod topem ({li['stop']})"}
    bottom, top = last["bottom"], last["top"]
    zone_from = _r2(bottom)
    stop = _r2(bottom * (1 - zone_pct / 100))
    base = {"top": _r2(top), "bottom": zone_from, "zone_from": zone_from, "stop": stop}
    tracked = last["outcome"] == "up" and not last.get("cancelled") and last["end"] >= lr    # wybity box nadal obowiązuje
    nl = ln[-1] if ln else None
    if nl and nl["i0"] > last["i0"] and not nl["open"] and nl["i1"] == lr and not last.get("cancelled"):   # wybity top nowego, jeszcze niepotwierdzonego boxa
        li = line_info(nl["top"])
        return _buy(c, lr, nl["top"], vol, vol_bars, pure, max_ext_pct, {**base, "top": li["entry"]}, li["stop"], f"sam top bez potwierdzonego dołu, stop {LINE_STOP_PCT} % pod topem ({li['stop']})")
    if last["outcome"] == "up" and (last["i1"] == lr or (tracked and px > top and prev_px is not None and prev_px <= top)):   # próba przebicia: pierwsza albo kolejna
        return _buy(c, lr, top, vol, vol_bars, pure, max_ext_pct, base, _r2(top * (1 - START_STOP_PCT / 100)),
                    f"stop początkowy ok. {START_STOP_PCT} % pod wejściem ({_r2(top * (1 - START_STOP_PCT / 100))}), potem pod dnem kolejnych boxów")
    if last["outcome"] == "down" or last.get("cancelled") or (last["outcome"] == "up" and not tracked):
        if px < bottom:
            return {**base, "state": "SELL", "text": f"SPRZEDAJ — box {zone_from}–{_r2(top)} anulowany (cena pod jego dnem, strefa zagrożenia {stop}–{zone_from}); szukamy nowego boxa"}
        return {**base, "state": "WAIT", "text": f"CZEKAJ — box {zone_from}–{_r2(top)} anulowany, czekamy na nowy"}
    if tracked:
        where = "nad górą boxa" if px > top else "w boxie"
        return {**base, "state": "HOLD", "text": f"TRZYMAJ — cena {where} {zone_from}–{_r2(top)}; box obowiązuje do utworzenia nowego wyżej, anuluje go zejście pod dno {zone_from} (strefa zagrożenia {stop}–{zone_from})"}
    had_up = len(bx) > 1 and bx[-2]["outcome"] == "up"
    if had_up:
        return {**base, "state": "HOLD", "text": f"TRZYMAJ — cena w nowym boxie {zone_from}–{_r2(top)}; stop pod strefą zagrożenia {stop}"}
    return {**base, "state": "WAIT", "text": f"CZEKAJ — box {zone_from}–{_r2(top)}; kup po zamknięciu {unit} nad {_r2(top)}"}


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
