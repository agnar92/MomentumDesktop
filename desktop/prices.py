"""Ceny z yfinance — tylko dwa rodzaje zapytań i tylko o to, czego jeszcze nie mamy:
  - tygodniowe świece z ostatnich 3 lat (wykres, średnie, MACD, wolumen, obrót): spółka już pobrana dostaje tylko ostatnie tygodnie
    (doklejane do zapisanych), pełne 3 lata pobieramy dla nowej spółki, po długiej przerwie albo gdy ceny wstecz się zmieniły (split / dywidenda),
  - miesięczne HIGH z całej historii (Green Line jak w oryginale Dr. Wisha): zamknięte miesiące się nie zmieniają, więc po zamknięciu
    kolejnego miesiąca dociągamy tylko ostatnie miesiące; całą historię tylko dla nowej spółki albo gdy ceny wstecz się zmieniły.
Ceny NIESKORYGOWANE o dywidendy (tylko o splity, auto_adjust=False) — jak na TradingView. Z korektą o dywidendy dawne szczyty spółek
z dużymi wypłatami (np. MLP: CLMT, szczyt 55,26 z 04.2007 -> ~20) spadały i Green Line wychodziła za nisko. Serie / wpisy bez znacznika
"raw" (pobrane jeszcze ze skorygowanymi cenami) pobieramy raz od nowa w całości.
`progress(zrobione, wszystkie)` (opcjonalnie) dostaje postęp po każdej paczce."""
import datetime as dt
import math

WEEKLY_PERIOD = "3y"
KEEP_WEEKS = 157          # ~3 lata świec tygodniowych
BATCH = 100
AUTO_ADJUST = False       # True = ceny skorygowane o dywidendy (Yahoo „Adj”), False = tylko splity (jak TradingView)
ADJ_TOL = 0.015           # różnica cen na wspólnej dacie > 1,5 % = ceny wstecz zmienione (split / dywidenda) -> pełne pobranie


def _yf():
    import yfinance as yf
    return yf


def _frames(df, tickers):
    """Wynik yf.download (jeden albo wiele tickerów) -> {ticker: DataFrame}."""
    if df is None or getattr(df, "empty", True):
        return {}
    if len(tickers) == 1 and "Close" in df.columns:
        return {tickers[0]: df}
    out = {}
    for t in tickers:
        try:
            out[t] = df[t]
        except KeyError:
            continue
    return out


def _clean(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 4)


def _series(f):
    f = f.dropna(subset=["Close"])
    return {"raw": 1, "d": [d.strftime("%Y-%m-%d") for d in f.index], **{k: [_clean(x) for x in f[col]] for k, col in
                                                              (("o", "Open"), ("h", "High"), ("l", "Low"), ("c", "Close"), ("v", "Volume"))}}


def _same(a, b):
    return a and b and abs(a / b - 1) <= ADJ_TOL


def merge_weekly(old, new, keep=KEEP_WEEKS):
    """Dokleja nowe tygodnie do zapisanych (nowe nadpisują od swojej pierwszej daty). -> seria albo None, gdy ceny na wspólnej dacie
    się różnią (zmienione wstecz — trzeba pobrać całość)."""
    if not new["d"]:
        return old
    first = new["d"][0]
    if first in old["d"] and not _same(old["c"][old["d"].index(first)], new["c"][0]):
        return None
    cut = next((i for i, d in enumerate(old["d"]) if d >= first), len(old["d"]))
    return {"raw": 1, **{k: (old[k][:cut] + new[k])[-keep:] for k in ("d", "o", "h", "l", "c", "v")}}


def _recent_period(last, today):
    """Ile dociągnąć do zapisanej serii: '1mo' / '6mo', albo None = za długa przerwa, całe 3 lata."""
    gap = (today - dt.date.fromisoformat(last)).days
    return "1mo" if gap <= 21 else "6mo" if gap <= 150 else None


def weekly(tickers, log=print, period=WEEKLY_PERIOD, cache=None, today=None, progress=None):
    """-> {ticker: {d: [daty], o, h, l, c, v}} (tydzień = data poniedziałku jak w Yahoo; ostatni tydzień może być w toku).
    cache = zapisane serie {ticker: seria}: dla nich pobieramy tylko ostatnie tygodnie i doklejamy."""
    cache, today = cache or {}, today or dt.date.today()
    update, full = {}, []
    for t in tickers:
        old = cache.get(t) if (cache.get(t) or {}).get("raw") else None   # seria ze skorygowanymi cenami -> pełne pobranie
        p = _recent_period(old["d"][-1], today) if old and old.get("d") else None
        (update.setdefault(p, []) if p else full).append(t)
    total, done, out = len(tickers), 0, {}

    def fetch(part, per):
        nonlocal done
        df = _yf().download(part, period=per, interval="1wk", auto_adjust=AUTO_ADJUST, group_by="ticker", progress=False, threads=True)
        done += len(part)
        if progress:
            progress(done, total)
        log(f"yfinance tygodniowe ({'3 lata' if per == period else 'aktualizacja'}): {done}/{total}")
        return {t: _series(f) for t, f in _frames(df, part).items()}

    for per, ts in update.items():
        for i in range(0, len(ts), BATCH):
            part = ts[i:i + BATCH]
            got = fetch(part, per)
            for t in part:
                m = merge_weekly(cache[t], got[t]) if t in got else cache[t]   # brak nowych danych: zostaje zapisana seria
                if m is None:   # ceny wstecz zmienione — ta spółka w pełnym pobraniu
                    full.append(t)
                    total += 1
                else:
                    out[t] = m
    for i in range(0, len(full), BATCH):
        for t, s in fetch(full[i:i + BATCH], period).items():
            if len(s["d"]) >= 10:
                out[t] = {"raw": 1, **{k: s[k][-KEEP_WEEKS:] for k in ("d", "o", "h", "l", "c", "v")}}
    return out


def last_closed_month(today=None):
    today = today or dt.date.today()
    first = today.replace(day=1)
    return (first - dt.timedelta(days=1)).strftime("%Y-%m")


def _months(f, upto):
    s = f["High"].dropna()
    return [[d.strftime("%Y-%m"), round(float(v), 4)] for d, v in s.items() if d.strftime("%Y-%m") <= upto]


def merge_monthly(old, new):
    """Dokleja nowe zamknięte miesiące. -> lista albo None, gdy High na wspólnym miesiącu się różni (ceny zmienione wstecz)."""
    known = dict(old)
    for ym, v in new:
        if ym in known and not _same(known[ym], v):
            return None
    last = old[-1][0] if old else ""
    return old + [x for x in new if x[0] > last]


def monthly(tickers, cache, log=print, today=None, progress=None):
    """Uzupełnia `cache` {ticker: {"h": [[YYYY-MM, high]...], "upto": YYYY-MM}} o miesięczne High z całej historii (tylko ZAMKNIĘTE miesiące).
    Spółka z zapisem sprzed ostatniego zamkniętego miesiąca dostaje tylko ostatnie miesiące; całą historię — nowa spółka albo zmienione ceny.
    Stare wpisy z zamknięciami ("m") albo bez "raw" (ceny skorygowane o dywidendy) traktujemy jak brak. -> lista pobranych tickerów."""
    need = last_closed_month(today)
    def fresh(t):
        e = cache.get(t) or {}
        return "h" in e and e.get("raw")

    todo = [t for t in tickers if not fresh(t) or cache[t].get("upto") != need]
    update = [t for t in todo if fresh(t) and cache[t].get("h")]
    full = [t for t in todo if t not in update]
    total, done = len(todo), 0

    def step(part, per, label):
        nonlocal done
        df = _yf().download(part, period=per, interval="1mo", auto_adjust=AUTO_ADJUST, group_by="ticker", progress=False, threads=True)
        redo = []
        for t, f in _frames(df, part).items():
            rows = _months(f, need)
            if per == "max":
                if rows:
                    cache[t] = {"h": rows, "upto": need, "raw": 1}
                continue
            m = merge_monthly(cache[t]["h"], rows)
            if m is None:
                redo.append(t)
            else:
                cache[t] = {"h": m, "upto": need, "raw": 1}
        done += len(part)
        if progress:
            progress(min(done, total), total)
        log(f"yfinance miesięczne ({label}): {min(done, total)}/{total}")
        return redo

    for i in range(0, len(update), BATCH):
        redo = step(update[i:i + BATCH], "6mo", "aktualizacja")
        full += redo
        total += len(redo)
    for i in range(0, len(full), BATCH):
        step(full[i:i + BATCH], "max", "cała historia")
    return todo


def monthly_highs(entry):
    """High zamkniętych miesięcy; wpis bez "raw" (stare ceny skorygowane o dywidendy, np. spółka, która od tamtej pory nie przeszła progu obrotu
    i nie była odświeżana) traktujemy jak brak — inaczej w tabeli zostawałaby za niska Green Line."""
    e = entry or {}
    return [h for _, h in e.get("h", [])] if e.get("raw") else []


def monthly_ohlc(ticker):
    """Pełna historia miesięczna {d, o, h, l, c, v} jednej spółki (wykres miesięczny w desktopie; ostatni miesiąc może być w toku). -> seria albo None."""
    df = _yf().download([ticker], period="max", interval="1mo", auto_adjust=AUTO_ADJUST, group_by="ticker", progress=False, threads=False)
    f = _frames(df, [ticker]).get(ticker)
    if f is None:
        return None
    s = _series(f)
    return s if len(s["d"]) >= 2 else None


def daily_ohlc(ticker, period="2y"):
    """Świece dzienne {d, o, h, l, c, v} jednej spółki z ostatnich `period` (wykres dzienny w desktopie). -> seria albo None."""
    df = _yf().download([ticker], period=period, interval="1d", auto_adjust=AUTO_ADJUST, group_by="ticker", progress=False, threads=False)
    f = _frames(df, [ticker]).get(ticker)
    if f is None:
        return None
    s = _series(f)
    return s if len(s["d"]) >= 30 else None
