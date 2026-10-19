"""Reguły Darvasa na tygodniowych zamknięciach — port 1:1 z Momentum (docs/js/darvas.js).

Box = GÓRA (zamknięcie nieprzebite przez 3 kolejne tygodnie) + DÓŁ (najniższe zamknięcie po górze, niezłamane przez 3 tygodnie); rysujemy
tylko potwierdzone boxy, a sam top to przerywana linia (stop 8 %). Zamknięcie nad górą = próba przebicia (box nadal obowiązuje, aż powstanie
nowy wyżej); zejście pod dno anuluje box (przed wybiciem: odwrócony box). Strefa zagrożenia = 5 % pod dołem. Heurystyka, nie rekomendacja.
"""
import math

CONFIRM = 3            # góra / dół = zamknięcie, którego nie przebija (nie jest niższe od) kolejne 3 tygodnie
CONFIRM_DAILY = 3
LOCAL_PEAK = False      # jak Momentum: top = rosnące maksimum nieprzebite przez 3 kolejne zamknięcia, bez warunku lokalnego szczytu (True = stara reguła Desktopu)
MIN_HEIGHT_PCT = 0      # wg książki box nie ma minimalnej wysokości (jak w Momentum)
STOP_PCT = 5            # szerokość strefy zagrożenia pod dołem boxa
LINE_STOP_PCT = 8       # sam top (bez potwierdzonego dołu): stop 8 % pod topem
MAX_EXT_PCT = 10        # KUP tylko do 10 % nad górą boxa
BREAKOUT_VOL = 1.4      # wolumen wybicia >= 1,4x średniej z 10 tygodni
VOL_WEEKS = 10
START_STOP_PCT = 10     # stop początkowy przy pierwszym wybiciu
PURE = False            # „czysty Darvas” jak w PDF: KUP = samo przebicie góry (bez filtru wolumenu i limitu +10 % nad górą)
NEW_WEEKS = 4           # box jest „nowy”, gdy jego góra została potwierdzona w ostatnich tylu tygodniach
CARD_WEEKS = 104        # karta = boxy z ostatnich 2 lat (reguła „karta spadająca” porównuje z wyższymi boxami z tego okna), jak DARCARD_SESSIONS w Momentum


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
            if LOCAL_PEAK and not all(c[k] > c[m] for m in range(max(0, k - confirm), k) if _ok(c[m])):   # (wyłączone) top musi być lokalnym szczytem
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
        good = confirmed and math.isfinite(bottom) and top > bottom and (top - bottom) / top * 100 >= MIN_HEIGHT_PCT
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


def status(c, vol=None, zone_pct=STOP_PCT, max_ext_pct=MAX_EXT_PCT, vol_bars=VOL_WEEKS, pure=None, unit="tygodnia", confirm=None, lows=None):
    """Stan karty Darvasa na ostatnim zamknięciu (tydzień / sesja): BUY / NOVOL / LATE / READY / HOLD / SELL / WAIT / OUT / NONE (jak darCardAnalyze w Momentum,
    plus filtry wybicia Desktopu NOVOL / LATE, wyłączane „czystym Darvasem”). lows = dołki świec (wyjście po MACD: podnieś stop do dołka świecy przecięcia)."""
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
    # karta Darvasa jak w Momentum (darCardAnalyze / darvas_card_state): łańcuch kolejnych, coraz wyższych boxów (każdy wcześniejszy wybity w górę)
    chain = [last]
    for b in reversed(bx[:-1]):
        if b["top"] < chain[0]["top"] and not b.get("cancelled") and b["outcome"] == "up":
            chain.insert(0, b)
        else:
            break
    shown = [b for b in bx if b["end"] >= lr - CARD_WEEKS + 1]
    bottom, top = last["bottom"], last["top"]
    zone_low = bottom * (1 - zone_pct / 100)
    zone_from, stop = _r2(bottom), _r2(zone_low)
    base = {"top": _r2(top), "bottom": zone_from, "zone_from": zone_from, "stop": stop, "n_up": 0}
    max_top = max([b["top"] for b in shown if b is not last], default=-math.inf)
    step_down = top < max_top and px <= max_top           # karta spadająca: ostatni box niżej niż wcześniejszy, cena nie wyżej od niego
    two_up = len(chain) >= 2 and not step_down            # punkt kupna = wybicie z drugiego z dwóch kolejnych rosnących boxów (s. 139–140)
    live = not step_down and not last.get("cancelled") and last["outcome"] != "down"
    base["n_up"] = len(chain) if live else 0
    warn = []
    ml, md = macd_cross_low(c, lows) if lows else (None, None)
    nl = ln[-1] if ln else None
    if live and nl and nl["i0"] > last["i0"] and not nl["open"] and nl["i1"] == lr:   # wybity top nowego, jeszcze niepotwierdzonego boxa
        li = line_info(nl["top"])
        return _buy(c, lr, nl["top"], vol, vol_bars, pure, max_ext_pct, {**base, "top": li["entry"]}, li["stop"], f"sam top bez potwierdzonego dołu, stop {LINE_STOP_PCT} % pod topem ({li['stop']})")
    if step_down:
        return {**base, "state": "OUT", "text": f"POZA NAJWYŻSZYM BOXEM — ostatni box {zone_from}–{_r2(top)} leży niżej niż wcześniejszy ({_r2(max_top)}); karta spadająca: nie kupuj ani nie trzymaj"}
    if (last["outcome"] == "down" or last.get("cancelled")) and px >= bottom:
        return {**base, "state": "OUT", "text": f"POZA BOXEM — box {zone_from}–{_r2(top)} {'anulowany' if last.get('cancelled') else 'złamany w dół'}; powrót ceny go nie wskrzesza, czekamy na nowy box"}
    if px > top:
        if prev_px is not None and prev_px <= top:   # wybicie w tym tygodniu (pierwsze albo kolejne po powrocie do boxa)
            entry_stop = _r2(px * (1 - START_STOP_PCT / 100))
            if not two_up:
                warn.append("pierwszy box — książka (s. 139–140) kupuje po dwóch kolejnych rosnących boxach")
            if ml is not None:
                warn.append("tygodniowy MACD pod linią sygnału")
            res = _buy(c, lr, top, vol, vol_bars, pure, max_ext_pct, base, entry_stop,
                       f"{'po dwóch kolejnych rosnących boxach; ' if two_up else ''}stop {START_STOP_PCT} % pod wejściem ({entry_stop}), dalej nad strefą zagrożenia {stop}")
            return _warn(res, warn)
        txt = f"TRZYMAJ — cena nad górą boxa {_r2(top)}, czekamy na nowy wyższy box; ignoruj wahania, stop pod strefą zagrożenia {stop}"
        if (px / top - 1) * 100 > max_ext_pct:
            warn.append(f"cena {(px / top - 1) * 100:.1f} % nad górą — nie goń")
        return _warn({**base, "state": "HOLD", "text": txt}, _macd_warn(warn, ml, md))
    if px >= bottom:
        if last["outcome"] == "up":
            return _warn({**base, "state": "HOLD", "text": f"TRZYMAJ — cena w najwyższym boxie {zone_from}–{_r2(top)} (próba przebicia za nami, box obowiązuje); ignoruj wahania, stop pod strefą zagrożenia {stop}"},
                         _macd_warn(warn, ml, md))
        buy_stop = _r2(top * (1 - START_STOP_PCT / 100))
        if two_up:
            return {**base, "state": "READY", "stop": buy_stop,
                    "text": f"GOTOWY DO KUPNA — dwa kolejne rosnące boxy, cena w najwyższym {zone_from}–{_r2(top)}; kup po zamknięciu {unit} nad {_r2(top)}, stop {START_STOP_PCT} % ({buy_stop}); jeśli masz akcję — TRZYMAJ"}
        return {**base, "state": "WAIT", "stop": buy_stop,
                "text": f"CZEKAJ — pierwszy box {zone_from}–{_r2(top)}; punkt kupna pojawia się po dwóch kolejnych rosnących boxach; zamknięcie {unit} nad {_r2(top)} = wybicie"}
    if two_up or last["outcome"] == "up":
        where = "w strefie zagrożenia" if px >= zone_low else "pod strefą zagrożenia"
        return {**base, "state": "SELL", "text": f"SPRZEDAJ — {'po nowym, wyższym boxie ' if two_up else 'po wybiciu '}cena spadła pod dół boxa {zone_from} ({where} {stop}–{zone_from}); box anulowany, szukamy nowego"}
    return {**base, "state": "OUT", "text": f"POZA BOXEM — cena {_r2(px)} pod dołem {zone_from} (odwrócony box); nie kupuj ani nie trzymaj, szukamy nowego boxa"}


def _warn(res, warn):
    if warn:
        res = {**res, "warnings": list(warn), "text": res["text"] + "  ⚠ " + "; ".join(warn)}
    return res


def _macd_warn(warn, low, date_i):
    """Wyjście po MACD (jak Momentum): tygodniowy MACD pod sygnałem → podnieś stop pod dołek świecy, w której przeciął sygnał w dół."""
    if low is not None:
        warn = warn + [f"tygodniowy MACD pod sygnałem — podnieś stop do {low} (dołek świecy przecięcia)"]
    return warn


def _ema_tv(values, n):
    """EMA jak w TradingView (ziarno = SMA z pierwszych n wartości); None przed ziarnem."""
    out, k, prev, seed = [None] * len(values), 2 / (n + 1), None, []
    for i, v in enumerate(values):
        if v is None:
            continue
        if prev is None:
            seed.append(v)
            if len(seed) == n:
                prev = sum(seed) / n
                out[i] = prev
        else:
            prev = v * k + prev * (1 - k)
            out[i] = prev
    return out


def macd_cross_low(c, lows, fast=12, slow=26, sig=9):
    """Jeśli tygodniowy MACD (12, 26, 9) jest TERAZ pod sygnałem: (dołek świecy, w której przeciął sygnał w dół, jej indeks); inaczej (None, None).
    Kopia macd_cross_low z Momentum (przesuwanie stopu po MACD)."""
    vals = [float(v) if _ok(v) else None for v in c]
    first = next((i for i, v in enumerate(vals) if v is not None), None)
    if first is None:
        return None, None
    seg = vals[first:last_real(vals) + 1]
    if any(v is None for v in seg):
        return None, None
    f, sl = _ema_tv(seg, fast), _ema_tv(seg, slow)
    m = [a - b if a is not None and b is not None else None for a, b in zip(f, sl)]
    sg = _ema_tv(m, sig)
    hist = [a - b if a is not None and b is not None else None for a, b in zip(m, sg)]
    last = len(hist) - 1
    if last < 1 or hist[last] is None or hist[last] >= 0:
        return None, None
    for i in range(last, 0, -1):
        if hist[i - 1] is None:
            return None, None
        if hist[i] < 0 <= hist[i - 1]:
            j = first + i
            low = lows[j] if j < len(lows) else None
            return (_r2(float(low)) if _ok(low) else None), j
    return None, None


def card(c, vol=None, lows=None):
    """Karta Darvasa jak w książce / Momentum (darCardAnalyze): boxy z ostatnich CARD_WEEKS tygodni (wszystkie, także złamane),
    łańcuch kolejnych rosnących boxów i stan. -> {boxes: [{…, in_chain, rank (1, 2… w łańcuchu)}], topmost (indeks w boxes), n_up, status}."""
    bx = boxes(c)
    lr = last_real(c)
    st = status(c, vol, lows=lows, pure=True) if lr >= 0 else {"state": "NONE", "text": ""}
    if lr < 0 or not bx:
        return {"boxes": [], "topmost": None, "n_up": 0, "status": st}
    chain = [bx[-1]]
    for b in reversed(bx[:-1]):
        if b["top"] < chain[0]["top"] and not b.get("cancelled") and b["outcome"] == "up":
            chain.insert(0, b)
        else:
            break
    shown = [b for b in bx if b["end"] >= lr - CARD_WEEKS + 1]
    n_up = st.get("n_up", 0) or 0
    out = []
    for b in shown:
        k = next((i for i, x in enumerate(chain) if x is b), None)
        out.append({**b, "in_chain": k is not None and n_up >= 2, "rank": (k + 1) if k is not None and n_up >= 2 else None})
    return {"boxes": out, "topmost": len(out) - 1 if out and out[-1]["i0"] == bx[-1]["i0"] else None, "n_up": n_up, "status": st}


def past_range(weeks, c, years=3):
    """„Past Price Range” z dołu karty: [(rok, max, min)] zamknięć w ostatnich latach kalendarzowych."""
    by = {}
    for d, v in zip(weeks or [], c or []):
        if d and _ok(v):
            e = by.setdefault(d[:4], [v, v])
            e[0], e[1] = max(e[0], v), min(e[1], v)
    return [(y, _r2(by[y][0]), _r2(by[y][1])) for y in sorted(by)[-years:]]


def pin_status(box, price, zone_pct=STOP_PCT):
    """Status przypiętego (monitorowanego) boxa względem ceny: ABOVE / INSIDE / ZONE / EXIT."""
    if not box or not _ok(price) or not box["top"] > box["bottom"]:
        return {"state": "NONE", "rank": 9, "text": ""}
    top, bottom = box["top"], box["bottom"]
    if box.get("line"):   # przypięty sam top: bottom = stop 8 %, bez strefy zagrożenia
        if price > top:
            return {"state": "ABOVE", "rank": 1, "text": f"top {_r2(top)} przebity (+{(price / top - 1) * 100:.1f} %), stop {_r2(bottom)}"}
        if price >= bottom:
            return {"state": "INSIDE", "rank": 2, "text": f"pod topem {_r2(top)}, do wybicia {(top / price - 1) * 100:.1f} %, stop {_r2(bottom)}"}
        return {"state": "EXIT", "rank": 0, "text": f"EXIT — cena {_r2(price)} poniżej stopu {_r2(bottom)} (8 % pod topem {_r2(top)})"}
    zone = _r2(bottom * (1 - zone_pct / 100))
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
    out = {k: [] for k in ("pinned", "fresh", "buy", "ready", "check", "hold", "sell", "wait")}
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
        ds = status(c, it.get("v"), lows=it.get("l"), **(params or {}))
        conf = (params or {}).get("confirm") or CONFIRM
        bx = boxes(c, conf)
        last = bx[-1] if bx else None
        if ds["state"] == "NONE" or not last:
            continue
        box = {"top": _r2(last["top"]), "bottom": _r2(last["bottom"]), "start": (weeks[last["i0"]] if weeks and last["i0"] < len(weeks) else ""),
               "i0": last["i0"], "i1": last["i1"]}
        row = {"ticker": it["ticker"], "price": it.get("price"), "state": ds["state"], "text": ds["text"], "box": box}
        sect = {"BUY": "buy", "READY": "ready", "NOVOL": "check", "LATE": "check", "HOLD": "hold", "SELL": "sell", "WAIT": "wait"}.get(ds["state"])
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
    for k in ("fresh", "buy", "ready", "check", "hold", "sell", "wait"):
        out[k].sort(key=lambda r: r["ticker"])
    out["pinned"].sort(key=lambda r: (r["rank"], r["ticker"]))
    return out
