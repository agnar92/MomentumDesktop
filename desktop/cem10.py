"""CEM10 — miesięczna lista zakupów (USA + GPW): ten sam moduł co momentum/cem10.py + cem10.py w Momentum (web).

Reguły (rekomendacja po badaniach, listopad 2026):
  USA: lider = SPY albo QQQ z wyższym zwrotem 5M; kandydaci z indeksu lidera (S&P 500 albo Nasdaq-100): zwrot 6M > +30 % i zamknięcie
       miesiąca nad SMA 10; ranking po 6M malejąco, 10 pozycji; brak zakupów, gdy SPY zamyka miesiąc pod SMA 12.
  GPW: bez lidera, pula WIG20 + mWIG40 razem; C-8: zwrot 3M > 0 %, 12M > +30 %, zamknięcie nad SMA 10; ranking po 6M, 5 pozycji;
       brak zakupów, gdy równo ważony indeks składników (średni miesięczny zwrot) jest pod SMA 12.
  Wyjście (oba rynki): zamknięcie miesiąca pod SMA 10 (w USA także wypadnięcie z S&P 500 i Nasdaq-100); awaryjny stop -40 %.
Dane: skład S&P 500 / Nasdaq-100 z Wikipedii, skład WIG20 / mWIG40 = GPW_DEFAULT albo data/cem10_gpw.json (edycja w oknie CEM10 po każdej
kwartalnej rewizji GPW), ceny = miesięczne świece yfinance (2 lata; GPW z końcówką .WA), tylko zamknięte miesiące.
Zwroty i SMA na zamknięciach skorygowanych o dywidendy; pokazywane ceny są surowe (jak w notowaniach)."""
import io

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

UA = {"User-Agent": "Mozilla/5.0 (Momentum Desktop CEM10)"}
WIKI = {"sp": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", ("Symbol",), ("Security",)),
        "nq": ("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies", ("Ticker", "Symbol"), ("Company", "Security"))}


def wiki_members(url, tcols, ncols):
    """Tabela składu z Wikipedii -> {ticker: nazwa} (pierwsza tabela z kolumną tickera, >= 90 wierszy)."""
    import pandas as pd
    import requests
    html = requests.get(url, headers=UA, timeout=30).text
    for t in pd.read_html(io.StringIO(html)):
        tc = next((c for c in tcols if c in t.columns), None)
        nc = next((c for c in ncols if c in t.columns), None)
        if tc and nc and len(t) >= 90:
            return {str(a).strip().replace(".", "-"): str(b).strip() for a, b in zip(t[tc], t[nc])}
    raise ValueError(f"brak tabeli składu: {url}")


def members(old=None, log=print):
    """{"sp": {...}, "nq": {...}}; przy błędzie Wikipedii skład z poprzedniego wyniku (old)."""
    out = {}
    for k, (url, tc, nc) in WIKI.items():
        try:
            out[k] = wiki_members(url, tc, nc)
            log(f"Skład {k}: {len(out[k])} spółek (Wikipedia)")
        except Exception as e:
            prev = {r["t"]: r["n"] for r in (old or {}).get("usa", {}).get("rows", []) if r.get(k)}
            if not prev:
                raise
            log(f"Skład {k}: błąd Wikipedii ({e}) — zostaje poprzedni skład ({len(prev)})")
            out[k] = prev
    return out


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


def build(mem, gpw, px, upto, today):
    """Lista CEM10 (ten sam format co docs/data/cem10.json w Momentum)."""
    m = monthly(px, upto)
    spy, qqq = m["SPY"][1], m["QQQ"][1]
    s5, q5 = ret(spy, LEAD_MONTHS), ret(qqq, LEAD_MONTHS)
    lead = "NDX" if q5 > s5 else "SP"
    spy12 = sma(spy, MKT_N)
    names = {**mem["nq"], **mem["sp"]}
    rows = []
    for t in sorted(set(mem["sp"]) | set(mem["nq"])):
        if t in m and len(m[t][1]) >= SMA_N:
            rows.append(stock_row(t, names[t][:40], m[t][1], m[t][2], sp=t in mem["sp"], nq=t in mem["nq"]))
    k = m["SPY"][2][-1] / spy[-1]
    usa = dict(lead=lead, spy5=round(s5, 4), qqq5=round(q5, 4), spy=round(m["SPY"][2][-1], 2), spy_sma12=round(spy12 * k, 2),
               bear=bool(spy[-1] < spy12), n=N_USA, rows=rows, missing=sorted((set(mem["sp"]) | set(mem["nq"])) - {r["t"] for r in rows}))
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


def fetch(gpw, old=None, today=None, log=print, progress=None):
    """Pełne odświeżenie: skład (Wikipedia + GPW), ceny yfinance, lista za ostatni zamknięty miesiąc. Za mało cen -> ValueError."""
    import datetime as dt
    from .prices import last_closed_month
    today = today or dt.date.today()
    upto = last_closed_month(today)
    mem = members(old, log)
    tickers = ["SPY", "QQQ"] + sorted(set(mem["sp"]) | set(mem["nq"])) + [t + ".WA" for t in sorted(set(gpw["WIG20"]) | set(gpw["mWIG40"]))]
    px = download(tickers, log, progress)
    have = sum(1 for t in tickers if t in px)
    if have < 0.9 * len(tickers) or "SPY" not in px or "QQQ" not in px:
        raise ValueError(f"za mało cen: {have}/{len(tickers)}")
    return build(mem, gpw, px, upto, today)


def parse_tickers(text):
    """"DELL, crwd;ALE.wa  pko" -> ["DELL", "CRWD", "ALE.WA", "PKO"] (bez powtórzeń, w kolejności; .WA = wymuś GPW)."""
    import re
    out = []
    for t in re.split(r"[\s,;]+", str(text or "").upper()):
        if t and t not in out:
            out.append(t)
    return out


def decide(row):
    """Decyzja dla trzymanej spółki: brak w indeksach -> sprawdź; zamknięcie pod SMA 10 -> sprzedaj."""
    if not row:
        return "sprawdź"
    return "trzymaj" if row.get("dist") is not None and row["dist"] >= 0 else "sprzedaj"
