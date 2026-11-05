"""CEM10 — miesięczna lista zakupów (USA + GPW): ten sam moduł co momentum/cem10.py + cem10.py w Momentum (web).

Reguły (rekomendacja po badaniach, listopad 2026):
  USA: lider = SPY albo QQQ z wyższym zwrotem 5M; kandydaci z indeksu lidera (S&P 500 albo Nasdaq-100): zwrot 6M > +30 % i zamknięcie
       miesiąca nad SMA 10; ranking po 6M malejąco, 10 pozycji; brak zakupów, gdy SPY zamyka miesiąc pod SMA 12.
  GPW: bez lidera, pula WIG20 + mWIG40 razem; C-8: zwrot 3M > 0 %, 12M > +30 %, zamknięcie nad SMA 10; ranking po 6M, 5 pozycji;
       brak zakupów, gdy równo ważony indeks składników (średni miesięczny zwrot) jest pod SMA 12.
  Wyjście (oba rynki): zamknięcie miesiąca pod SMA 10; awaryjny stop -40 %. Przynależność do indeksu nie jest warunkiem wyjścia.
Dane USA: najpierw lider (SPY / QQQ), potem z Finviz lista tickerów indeksu lidera (idx_sp500 ALBO idx_ndx, bez filtrów; bez Wikipedii), ceny z yfinance na koniec miesiąca i ranking po 6M liczone tu; skład WIG20 / mWIG40 =
GPW_DEFAULT albo data/cem10_gpw.json (edycja w oknie CEM10 po każdej kwartalnej rewizji GPW), ceny = miesięczne świece yfinance
(2 lata; GPW z końcówką .WA), tylko zamknięte miesiące.
Zwroty i SMA na zamknięciach skorygowanych o dywidendy; pokazywane ceny są surowe (jak w notowaniach)."""
N_USA = 10
N_GPW = 5
THR_USA = 0.30          # zwrot 6M
THR_GPW_12M = 0.30      # C-8: 12M
LEAD_MONTHS = 5         # okno lidera SPY / QQQ
SMA_N = 10
MKT_N = 12


def month_closes(dates, values, upto):
    """(data 'YYYY-MM-DD', wartość) -> {YYYY-MM: ostatnia wartość miesiąca} dla zamkniętych miesięcy <= upto (świece miesięczne albo dzienne)."""
    out = {}
    for d, v in zip(dates, values):
        if v is None or v != v:
            continue
        ym = d[:7]
        if ym <= upto:
            out[ym] = float(v)
    return out


def ret(closes, k):
    """Zwrot z k miesięcy z listy zamknięć miesięcznych (najstarsze pierwsze); None, gdy za krótko."""
    if len(closes) <= k or not closes[-1 - k]:
        return None
    return closes[-1] / closes[-1 - k] - 1


def sma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def ew_level(series_by_ticker, months):
    """Równo ważony indeks koszyka: średni miesięczny zwrot składników (|r| < 150 %, błędne skoki pomijane) -> poziomy od 1,0."""
    lv, cur = [1.0], 1.0
    for a, b in zip(months, months[1:]):
        rs = []
        for s in series_by_ticker.values():
            if a in s and b in s and s[a]:
                r = s[b] / s[a] - 1
                if abs(r) < 1.5:
                    rs.append(r)
        cur *= 1 + (sum(rs) / len(rs) if rs else 0.0)
        lv.append(cur)
    return lv


def _rnd(x, n=4):
    return None if x is None else round(x, n)


def stock_row(ticker, name, adj, raw, **flags):
    """Wiersz spółki z zamknięć miesięcznych (adj = skorygowane, raw = surowe; ta sama długość, najstarsze pierwsze)."""
    s = sma(adj, SMA_N)
    k = raw[-1] / adj[-1] if adj and adj[-1] else 1.0
    return dict(t=ticker, n=name, c=_rnd(raw[-1], 2), sma=_rnd(None if s is None else s * k, 2),
                dist=_rnd(None if s is None else adj[-1] / s - 1), r3=_rnd(ret(adj, 3)), r6=_rnd(ret(adj, 6)), r12=_rnd(ret(adj, 12)), **flags)


def usa_candidates(rows, lead):
    """Kandydaci USA: indeks lidera ('SP' / 'NDX'), 6M > +30 %, nad SMA 10; sortowanie po 6M malejąco."""
    key = "nq" if lead == "NDX" else "sp"
    c = [r for r in rows if r.get(key) and r["r6"] is not None and r["r6"] > THR_USA and r["dist"] is not None and r["dist"] > 0]
    return sorted(c, key=lambda r: -r["r6"])


def gpw_candidates(rows):
    """Kandydaci GPW (C-8, WIG20 + mWIG40 razem): 3M > 0, 12M > +30 %, nad SMA 10; sortowanie po 6M malejąco."""
    c = [r for r in rows if r["r3"] is not None and r["r12"] is not None and r["r3"] > 0 and r["r12"] > THR_GPW_12M
         and r["dist"] is not None and r["dist"] > 0]
    return sorted(c, key=lambda r: -(r["r6"] if r["r6"] is not None else -9))


# ---- skład GPW (rewizja 2026-09-18); użytkownik nadpisuje go w oknie CEM10 -> data/cem10_gpw.json
GPW_DEFAULT = {
 "rewizja": "2026-09-18",
 "WIG20": {
  "ALE": "Allegro.eu S.A.",
  "ALR": "Alior Bank S.A.",
  "BDX": "Budimex S.A.",
  "CDR": "CD PROJEKT SA",
  "DNP": "Dino Polska SA",
  "EBP": "Erste Bank Polska S.A.",
  "KGH": "KGHM Polska Miedz S.A.",
  "KRU": "Kruk SA",
  "KTY": "Grupa KĘTY SA",
  "LPP": "LPP S.A.",
  "MBK": "mBank SA",
  "MDV": "Modivo S.A.",
  "PCO": "Pepco Group B.V.",
  "PEO": "Bank Polska Kasa Opieki SA",
  "PGE": "PGE Polska Grupa Energetyczna SA",
  "PKN": "Polski Koncern Naftowy ORLEN SA",
  "PKO": "Powszechna Kasa Oszczednosci Bank Polski SA",
  "PZU": "Powszechny Zaklad Ubezpieczen SA",
  "TPE": "Tauron Polska Energia S.A.",
  "ZAB": "Zabka Group S.A."
 },
 "mWIG40": {
  "ABE": "AB S.A.",
  "ACP": "Asseco Poland S.A.",
  "APR": "Auto Partner SA",
  "ASB": "ASBISc Enterprises PLC",
  "ASE": "Asseco South Eastern Europe S.A.",
  "ATT": "Grupa Azoty S.A.",
  "BFT": "Benefit Systems SA",
  "BHW": "Bank Handlowy w Warszawie SA",
  "BNP": "BNP Paribas Bank Polska S.A.",
  "CAR": "Inter Cars S.A.",
  "CBF": "Cyber_Folks S.A.",
  "CPS": "Cyfrowy Polsat SA",
  "CRI": "Creotech Instruments S.A.",
  "DIA": "Diagnostyka S.A.",
  "DOM": "Dom Development S.A.",
  "DVL": "Develia S.A",
  "EAT": "AmRest Holdings SE",
  "ENA": "Enea S.A.",
  "GPP": "Grupa Pracuj S.A.",
  "GPW": "Gielda Papierow Wartosciowych w Warszawie SA",
  "ING": "ING Bank Śląski SA",
  "JSW": "Jastrzebska Spotka Weglowa SA",
  "LBW": "LUBAWA SA",
  "MBR": "Mo-Bruk SA",
  "MIL": "Bank Millennium S.A.",
  "MRB": "Mirbud SA",
  "MUR": "Murapol S.A.",
  "NEU": "Neuca S.A.",
  "NWG": "Newag S.A.",
  "OPL": "OrangePL",
  "PEP": "PolEnergia S.A.",
  "PXM": "Polimex-Mostostal S.A.",
  "RBW": "Rainbow Tours SA",
  "SNT": "Synektik S.A.",
  "TEN": "TEN SQUARE GAMES SA",
  "TXT": "Text S.A.",
  "VOX": "Voxel S.A.",
  "VRC": "Vercom SA",
  "WPL": "Wirtualna Polska Holding SA",
  "XTB": "X Trade Brokers Dom Maklerski SA"
 }
}

def download(tickers, log=print, progress=None):
    """Miesięczne świece yfinance (2 lata, ceny surowe + skorygowane) -> {ticker: (daty, adj, raw)}."""
    from .prices import _yf
    yf = _yf()
    out = {}
    for i in range(0, len(tickers), 100):
        part = tickers[i:i + 100]
        df = yf.download(part, period="2y", interval="1mo", auto_adjust=False, group_by="ticker", progress=False, threads=True)
        for t in part:
            try:
                f = df[t] if len(part) > 1 else df
                f = f.dropna(subset=["Close"])
            except KeyError:
                continue
            if len(f):
                out[t] = ([d.strftime("%Y-%m-%d") for d in f.index], list(f["Adj Close"]), list(f["Close"]))
        done = min(i + 100, len(tickers))
        log(f"Ceny: {done}/{len(tickers)}")
        if progress:
            progress(done / len(tickers))
    return out


def monthly(px, upto):
    """{ticker: (daty, adj, raw)} -> {ticker: (miesiące, adj, raw)} dla zamkniętych miesięcy; ostatni miesiąc musi być = upto."""
    out = {}
    for t, (d, a, r) in px.items():
        ma, mr = month_closes(d, a, upto), month_closes(d, r, upto)
        ms = sorted(set(ma) & set(mr))
        if ms and ms[-1] == upto:
            out[t] = (ms, [ma[m] for m in ms], [mr[m] for m in ms])
    return out


def leader(m):
    """Lider USA z miesięcznych serii {ticker: (miesiące, adj, raw)}: QQQ, gdy jego zwrot 5M jest wyższy niż SPY -> ("NDX" | "SP", spy5, qqq5)."""
    s5, q5 = ret(m["SPY"][1], LEAD_MONTHS), ret(m["QQQ"][1], LEAD_MONTHS)
    return ("NDX" if q5 > s5 else "SP"), s5, q5


def build(mem, gpw, px, upto, today, held=()):
    """Lista CEM10 (ten sam format co docs/data/cem10.json w Momentum). mem = {"sp": {ticker: nazwa}, "nq": {...}} z Finviz (indeks lidera);
    held = trzymane spółki USA (dostają wiersz niezależnie od sita, bez flagi indeksu — decyzja tylko po SMA 10)."""
    m = monthly(px, upto)
    spy = m["SPY"][1]
    lead, s5, q5 = leader(m)
    spy12 = sma(spy, MKT_N)
    names = {**mem["nq"], **mem["sp"]}
    want = sorted(set(mem["sp"]) | set(mem["nq"]) | {t.replace(".", "-") for t in held})
    rows = []
    for t in want:
        if t in m and len(m[t][1]) >= SMA_N:
            rows.append(stock_row(t, (names.get(t) or t)[:40], m[t][1], m[t][2], sp=t in mem["sp"], nq=t in mem["nq"]))
    k = m["SPY"][2][-1] / spy[-1]
    usa = dict(lead=lead, spy5=round(s5, 4), qqq5=round(q5, 4), spy=round(m["SPY"][2][-1], 2), spy_sma12=round(spy12 * k, 2),
               bear=bool(spy[-1] < spy12), n=N_USA, rows=rows, missing=sorted(set(want) - {r["t"] for r in rows}))
    w20, w40 = gpw["WIG20"], gpw["mWIG40"]
    grows, ser = [], {}
    for t in sorted(set(w20) | set(w40)):
        y = t + ".WA"
        if y in m and len(m[y][1]) >= SMA_N:
            grows.append(stock_row(t, (w20.get(t) or w40.get(t) or t)[:40], m[y][1], m[y][2], w20=t in w20, w40=t in w40))
            ser[t] = dict(zip(m[y][0], m[y][1]))
    months = sorted({x for s in ser.values() for x in s})[-25:]
    lv = ew_level(ser, months)
    lv12 = sum(lv[-MKT_N:]) / MKT_N

    def avg6(ix):
        v = [r["r6"] for r in grows if r[ix] and r["r6"] is not None]
        return round(sum(v) / len(v), 4) if v else None
    gpw_out = dict(w20_6=avg6("w20"), w40_6=avg6("w40"), lv=round(lv[-1], 4), lv12=round(lv12, 4), bear=bool(lv[-1] < lv12),
                   n=N_GPW, rows=grows, rewizja=gpw.get("rewizja"), missing=sorted((set(w20) | set(w40)) - {r["t"] for r in grows}))
    return dict(generated_at=today.isoformat(), month=upto, usa=usa, gpw=gpw_out)


# Finviz daje TYLKO skład indeksu (dzisiejszy; bez filtrów zwrotu — Finviz liczy od dzisiejszej ceny, a reguła od zamknięcia miesiąca).
# Zwrot 6M, SMA 10 i ranking liczy aplikacja z miesięcznych zamknięć yfinance.
INDEX_FILTERS = ("idx_sp500", "idx_ndx")


def finviz_members(filters, get=None, pause=0.7, log=None, progress=None):
    """Skan Finviz (widok Overview, 20 wierszy na stronę) -> {ticker: nazwa} (BRK.B -> BRK-B).
    Strona bez liczby wyników (blokada albo zmieniony układ) = ValueError, żeby pusty wynik nie udawał braku kandydatów."""
    import time

    import requests
    from .finviz import HEADERS, PAGE, URL, parse_page
    get = get or requests.get
    out, offset, total = {}, 1, None
    while total is None or offset <= total:
        r = get(URL, params={"v": "111", "f": filters, "r": offset}, headers=HEADERS, timeout=30)
        r.raise_for_status()
        rows, t = parse_page(r.text)
        if t is None:
            raise ValueError("Finviz: brak liczby wyników na stronie (blokada albo zmieniony układ)")
        total = t
        if not rows:
            break
        for x in rows:
            out[x["ticker"].replace(".", "-")] = x.get("company") or x["ticker"]
        offset += PAGE
        if log:
            log(f"Finviz: pobrano {len(out)} z {total} spółek…")
        if progress:
            progress(min(1.0, len(out) / max(total, 1)))
        if offset <= total:
            time.sleep(pause)
    return out


def index_members(lead, get=None, log=print, progress=None):
    """Skład indeksu lidera z Finviz: {"sp": {ticker: nazwa}, "nq": {...}} (drugi indeks zostaje pusty — kandydaci pochodzą tylko z indeksu lidera).
    Bez zapasowego źródła: błąd Finviz albo podejrzana liczba spółek = błąd odświeżenia."""
    k, name, lo, hi = ("nq", "Nasdaq-100", 80, 120) if lead == "NDX" else ("sp", "S&P 500", 400, 600)
    out = {"sp": {}, "nq": {}}
    out[k] = finviz_members(INDEX_FILTERS[1 if k == "nq" else 0], get=get, log=log, progress=progress)
    log(f"Finviz ({name}, lider {lead}): {len(out[k])} spółek w indeksie")
    if not lo <= len(out[k]) <= hi:
        raise ValueError(f"Finviz: {len(out[k])} spółek w {name} (oczekiwano {lo}–{hi}) — zmieniony układ strony albo blokada")
    return out


def fetch(gpw, old=None, today=None, log=print, progress=None, held=()):
    """Odświeżenie: najpierw lider (SPY i QQQ), potem skład indeksu lidera z Finviz, ceny miesięczne całego indeksu + trzymanych + GPW (yfinance).
    Finviz niedostępny albo za mało cen -> ValueError (bez zapasowego źródła składu)."""
    import datetime as dt
    from .prices import last_closed_month
    today = today or dt.date.today()
    upto = last_closed_month(today)
    def stage(a, b):   # pasek postępu: etap zajmuje przedział [a, b] całości
        return (lambda f: progress(a + (b - a) * f)) if progress else None
    log("Sprawdzam lidera (SPY / QQQ)…")
    px = download(["SPY", "QQQ"], log)
    if progress:
        progress(0.05)
    m0 = monthly(px, upto)
    if "SPY" not in m0 or "QQQ" not in m0:
        raise ValueError(f"brak cen SPY / QQQ za {upto}")
    lead, s5, q5 = leader(m0)
    log(f"Lider: {'Nasdaq-100 (QQQ)' if lead == 'NDX' else 'S&P 500 (SPY)'} — zwrot 5M SPY {s5:+.1%}, QQQ {q5:+.1%}. Pobieram skład indeksu z Finviz…")
    mem = index_members(lead, log=log, progress=stage(0.05, 0.2))
    heldu = sorted({t.replace(".", "-") for t in held if not str(t).upper().endswith(".WA")})
    usa = sorted((set(mem["sp"]) | set(mem["nq"]) | set(heldu)) - {"SPY", "QQQ"})
    tickers = usa + [t + ".WA" for t in sorted(set(gpw["WIG20"]) | set(gpw["mWIG40"]))]
    px.update(download(tickers, log, stage(0.2, 1.0)))
    have = sum(1 for t in tickers if t in px)
    if have < 0.9 * len(tickers):
        raise ValueError(f"za mało cen: {have}/{len(tickers)}")
    out = build(mem, gpw, px, upto, today, held=heldu)
    out["usa"]["index"] = {"lead": lead, "n": len(mem["nq"] if lead == "NDX" else mem["sp"])}
    return out


def parse_tickers(text):
    """"DELL, crwd;ALE.wa  pko" -> ["DELL", "CRWD", "ALE.WA", "PKO"] (bez powtórzeń, w kolejności; .WA = wymuś GPW)."""
    import re
    out = []
    for t in re.split(r"[\s,;]+", str(text or "").upper()):
        if t and t not in out:
            out.append(t)
    return out


def decide(row):
    """Decyzja dla trzymanej spółki: brak danych -> sprawdź; zamknięcie miesiąca pod SMA 10 -> sprzedaj."""
    if not row:
        return "sprawdź"
    return "trzymaj" if row.get("dist") is not None and row["dist"] >= 0 else "sprzedaj"
