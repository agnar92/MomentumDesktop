"""🧭 Krok po kroku (jak strona krok.html w Momentum): rynek (indeksy na wykresach 10:30) → sektory (ETF SPDR wg Mansfield RS) → akcje z wybranych
sektorów wg Mansfield RS względem S&P 500. Czyste funkcje (trend 10:30, Mansfield RS, zmiany %) + pobieranie tygodniowych zamknięć indeksów i ETF.
Heurystyka do przeglądania, nie rekomendacja."""
import math
import time
from datetime import datetime, timezone

from . import darvas, glb, store

INDEXES = [("^GSPC", "S&P 500"), ("^NDX", "Nasdaq 100"), ("^DJI", "Dow Jones")]
SECTOR_ETFS = [   # ETF SPDR sektora, nazwa, sektor w Finvizie (pole `sector` spółek)
    ("XLK", "Technologia", "Technology"), ("XLF", "Finanse", "Financial"), ("XLV", "Ochrona zdrowia", "Healthcare"),
    ("XLE", "Energia", "Energy"), ("XLI", "Przemysł", "Industrials"), ("XLY", "Dobra cykliczne", "Consumer Cyclical"),
    ("XLP", "Dobra podstawowe", "Consumer Defensive"), ("XLU", "Użyteczność publiczna", "Utilities"),
    ("XLB", "Surowce", "Basic Materials"), ("XLRE", "Nieruchomości", "Real Estate"), ("XLC", "Komunikacja", "Communication Services"),
]
SLOPE_WEEKS = 4        # nachylenie SMA 30: porównanie z wartością sprzed 4 tygodni
MRS_WEEKS = 52         # Mansfield RS: (walor / S&P 500) względem swojej 52-tygodniowej średniej
MAX_AGE_H = 12         # dane indeksów / ETF odświeżamy, gdy są starsze niż tyle godzin
FILE = "overview.json"
TREND_LABELS = {"up": "📈 rośnie", "down": "📉 spada", "flat": "↔ bez trendu", "na": "—"}


def _ok(v):
    return isinstance(v, (int, float)) and math.isfinite(v)


def sma(c, n):
    """Średnia z n ostatnich zamknięć (None, gdy w oknie brakuje danych)."""
    out = [None] * len(c)
    for i in range(n - 1, len(c)):
        w = c[i - n + 1:i + 1]
        if all(_ok(v) for v in w):
            out[i] = sum(w) / n
    return out


def _last(c):
    return max((i for i, v in enumerate(c or []) if _ok(v)), default=-1)


def trend1030(c):
    """Wykres 10:30 (tygodniowy): rośnie = cena nad SMA 30, SMA 10 nad SMA 30 i SMA 30 nie spada (4 tyg.); spada = odwrotnie; inaczej bez trendu."""
    i = _last(c)
    if i < 0:
        return {"state": "na"}
    s10, s30 = sma(c, 10), sma(c, 30)
    close, a, b = c[i], s10[i], s30[i]
    if a is None or b is None:
        return {"state": "na", "close": close}
    b4 = s30[i - SLOPE_WEEKS] if i - SLOPE_WEEKS >= 0 else None
    slope = (b / b4 - 1) * 100 if b4 else None
    rising = slope is None or slope >= 0
    state = "up" if close > b and a > b and rising else "down" if close < b and a < b and not rising else "flat"
    return {"state": state, "close": close, "s10": a, "s30": b, "slope": slope, "pct30": (close / b - 1) * 100}


def mansfield(c, bench, n=MRS_WEEKS):
    """Mansfield RS = (walor / S&P 500) / swoja n-tygodniowa średnia − 1, w % (> 0 = silniejszy od rynku i coraz silniejszy). None przy za krótkiej historii."""
    if not c or not bench:
        return None
    rp = [v / b if _ok(v) and _ok(b) and b > 0 else None for v, b in zip(c, bench)]
    avg = sma(rp, n)
    i = _last(rp)
    return (rp[i] / avg[i] - 1) * 100 if i >= 0 and avg[i] else None


def perf(c):
    """Zmiany %: tydzień, 3 mies. (13 tyg.), rok (52 tyg.)."""
    i = _last(c)
    def ch(k):
        return (c[i] / c[i - k] - 1) * 100 if i >= k and _ok(c[i - k]) and c[i - k] > 0 else None
    return {"w": ch(1), "q": ch(13), "y": ch(52)} if i >= 0 else {}


def market_verdict(trends):
    """Werdykt kroku 1: wszystkie indeksy rosną / żaden / mieszany."""
    st = [t.get("state") for t in trends if t.get("state") != "na"]
    if not st:
        return "na", "brak danych"
    if all(s == "up" for s in st):
        return "up", "Rynek rośnie — wszystkie indeksy w trendzie 10:30. Szukamy akcji do kupna."
    if not any(s == "up" for s in st):
        return "down", "Rynek spada / bez trendu — żaden indeks nie jest w trendzie 10:30. Ostrożnie z kupnem."
    return "flat", "Rynek mieszany — część indeksów w trendzie. Kupujemy ostrożniej, tylko najsilniejsze."


def sector_rows(ov):
    """Krok 2: sektory ETF od najwyższego Mansfield RS."""
    items, bench = ov.get("items") or {}, (ov.get("items") or {}).get("^GSPC")
    rows = []
    for t, name, sec in SECTOR_ETFS:
        c = items.get(t)
        if not c:
            continue
        p = perf(c)
        rows.append({"ticker": t, "name": name, "sector": sec, "mrs": mansfield(c, bench), "trend": trend1030(c)["state"], "q": p.get("q"), "y": p.get("y")})
    rows.sort(key=lambda r: -(r["mrs"] if r["mrs"] is not None else -1e9))
    return rows


def stock_rows(directory, sectors=None):
    """Krok 3: akcje z zapisanego skanu / watchlisty (watchlist.json + charts.json katalogu) z wybranych sektorów, od najwyższego Mansfield RS
    względem S&P 500 (oś tygodni skanu). sectors = None / puste = wszystkie."""
    wl = store.read_json(directory / "watchlist.json", {}) or {}
    ch = store.read_json(directory / "charts.json", {}) or {}
    bench, data = ch.get("spx") or [], ch.get("stocks") or {}
    want = set(sectors or [])
    rows = []
    for s in wl.get("stocks") or []:
        if want and s.get("sector") not in want:
            continue
        d = data.get(s["ticker"]) or {}
        c = d.get("c") or []
        st = darvas.status(c, d.get("v"), lows=d.get("l")) if c else {"state": "NONE"}
        p = perf(c)
        rows.append({"ticker": s["ticker"], "company": s.get("company") or "", "sector": s.get("sector") or "", "price": s.get("price"),
                     "mrs": mansfield(c, bench), "trend": trend1030(c)["state"], "q": p.get("q"), "darvas": st.get("state", "NONE"),
                     "glb": glb.STATE_LABELS.get(s.get("glb_state"), "") if s.get("glb_state") else "", "rs": s.get("rs_rating")})
    rows.sort(key=lambda r: -(r["mrs"] if r["mrs"] is not None else -1e9))
    return rows


def load(root):
    return store.read_json(root / FILE, {}) or {}


def stale(ov, now=None):
    t = ov.get("fetched")
    if not t:
        return True
    try:
        age = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return True
    return age.total_seconds() > MAX_AGE_H * 3600


def fetch(root, log=print, period="4y"):
    """Tygodniowe zamknięcia indeksów i ETF sektorów z yfinance (jedno zapytanie) -> zapisane w overview.json katalogu danych."""
    import yfinance as yf
    tickers = [t for t, _ in INDEXES] + [t for t, _, _ in SECTOR_ETFS]
    t0 = time.time()
    df = yf.download(tickers, period=period, interval="1wk", auto_adjust=True, group_by="ticker", progress=False, threads=True)
    weeks = [d.strftime("%Y-%m-%d") for d in df.index]
    items = {}
    for t in tickers:
        try:
            ser = df[t]["Close"]
        except KeyError:
            continue
        vals = [round(float(v), 4) if v == v else None for v in ser.values]
        if any(v is not None for v in vals):
            items[t] = vals
    ov = {"fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "weeks": weeks, "items": items}
    store.write_json(root / FILE, ov)
    log(f"Rynek i sektory: {len(items)}/{len(tickers)} serii tygodniowych w {time.time() - t0:.0f} s")
    return ov
