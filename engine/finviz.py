"""Pobieranie listy spółek (i danych fundamentalnych) z darmowego screenera Finviz.

Finviz robi całą FILTRACJĘ WSTĘPNĄ listy obserwowanej (kapitalizacja, cena nad SMA50 i
SMA200, stabilny wzrost EPS i dodatnie prognozy EPS — kody filtrów w finviz_screen.json),
a do tego dostarcza wszystko, co da się z niego wziąć bez płacenia: sektor, branżę,
kapitalizację, wzrost EPS (ten rok / prognoza na przyszły rok / ostatnie 5 lat / prognoza 5 lat)
i datę najbliższych wyników. Ceny i wskaźniki techniczne (RS, ADR, EMA34...) liczy już
watchlist.py z yfinance.

Zapytania idą po 4 widokach screenera (Overview / Valuation / Financial / własny z rekomendacją i ceną celu) z tymi samymi
filtrami, a wiersze są scalane po tickerze. UWAGA: Finviz po cichu IGNORUJE nieznany kod
filtra (zamiast zwrócić błąd), więc literówka daje szerszą listę — po zmianie filtrów sprawdź
liczbę wyników.
"""
import json
import re
import time
from pathlib import Path

import requests
from lxml import html as lxml_html

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "finviz_screen.json"

DEFAULT_FILTERS = "cap_smallover,fa_epsqoq_high,fa_epsyoy_high,fa_epsyoy1_high,fa_salesqoq_high,geo_usa,ind_stocksonly,sh_avgvol_o300,sh_price_o1,ta_sma200_pa"
DEFAULT_MAX_TICKERS = 300
MIN_TICKERS = 15   # poniżej tego uznajemy odpowiedź za błędną (blokada/zmiana układu strony)
PAGE_SIZE = 20     # darmowy Finviz zwraca 20 wierszy na stronę
BASE_URL = "https://finviz.com/screener.ashx"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0 Safari/537.36"}

# widok -> {nagłówek kolumny Finviz: nasz klucz}
VIEW_COLUMNS = {
    "111": {"Company": "company", "Sector": "sector", "Industry": "industry", "Market Cap": "market_cap", "P/E": "pe"},
    "121": {"Forward P/E": "forward_pe", "EPS This Y": "eps_this_y", "EPS Next Y": "eps_next_y",
            "EPS Past 5Y": "eps_past_5y", "EPS Next 5Y": "eps_next_5y"},
    "161": {"ROE": "roe", "Earnings": "earnings"},
    "152": {"Recom": "recom", "Target Price": "finviz_target", "Inst Own": "inst_own", "Inst Trans": "inst_trans",   # widok własny (Custom): rekomendacja 1-5, cena celu, własność instytucji (%) i jej zmiana (%)
            "Sales Q/Q": "sales_qq", "Sales Past 5Y": "sales_past_5y", "Float": "shs_float", "Outstanding": "shs_outstanding",   # C: wzrost sprzedaży kwartał do kwartału r/r; S: podaż akcji
            "Insider Own": "insider_own", "Debt/Eq": "debt_eq"},   # S: udział zarządu i zadłużenie
}
VIEW_PARAMS = {"152": {"c": "0,1,62,69,28,29,21,23,24,25,26,38"}}   # kolumny widoku własnego: 0 = No., 1 = Ticker, 62 = Analyst Recom., 69 = Target Price, 28 = Inst Own, 29 = Inst Trans, 21 = Sales Past 5Y, 23 = Sales Q/Q, 24 = Outstanding, 25 = Float, 26 = Insider Own, 38 = Debt/Eq
TEXT_KEYS = {"company", "sector", "industry", "earnings"}
_SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def parse_number(text):
    """'10.93%' -> 10.93, '47.26B' -> 47.26e9, '-' / '' -> None."""
    t = (text or "").strip().replace(",", "").rstrip("%")
    if not t or t == "-":
        return None
    mult = 1.0
    if t[-1] in _SUFFIX:
        mult, t = _SUFFIX[t[-1]], t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        return None


def parse_screener_page(page_html, view="111"):
    """-> (lista słowników {ticker, ...pola widoku}, łączna liczba wyników wg strony lub None)."""
    total_match = re.search(r"#\d+\s*/\s*(\d+)\s*Total", page_html)
    total = int(total_match.group(1)) if total_match else None
    tree = lxml_html.fromstring(page_html)
    headers = [th.text_content().strip() for th in tree.xpath('//table[contains(@class, "screener_table")]//thead//th')]
    wanted = VIEW_COLUMNS.get(view, {})
    rows = []
    for tr in tree.xpath('//tr[contains(@class, "styled-row")]'):
        tds = tr.xpath("./td")
        if len(tds) != len(headers) or len(tds) < 2:
            continue
        ticker = (tds[1].get("data-boxover-ticker") or tds[1].text_content()).strip()
        if not ticker:
            continue
        row = {"ticker": ticker}
        for header, td in zip(headers, tds):
            key = wanted.get(header)
            if key is None:
                continue
            text = td.text_content().strip()
            row[key] = (text or None) if key in TEXT_KEYS else parse_number(text)
        rows.append(row)
    return rows, total


def fetch_view(view, filters, max_tickers=DEFAULT_MAX_TICKERS, pause_s=0.7, session=None):
    """Pobiera kolejne strony jednego widoku (po 20 wierszy) aż do końca listy albo max_tickers."""
    session = session or requests.Session()
    out, seen = [], set()
    offset, total = 1, None
    while len(out) < max_tickers:
        params = {"v": view, "f": filters, "r": offset, **VIEW_PARAMS.get(view, {})}
        resp = session.get(BASE_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        rows, page_total = parse_screener_page(resp.text, view)
        total = page_total if page_total is not None else total
        new = [r for r in rows if r["ticker"] not in seen]
        if not new:
            break
        for r in new:
            seen.add(r["ticker"])
            out.append(r)
        offset += PAGE_SIZE
        if total is not None and offset > total:
            break
        time.sleep(pause_s)
    return out[:max_tickers], total


def fetch_watchlist(filters, max_tickers=DEFAULT_MAX_TICKERS, pause_s=0.7, views=("121", "161", "152")):
    """Lista spółek z Finviz scalona z widoków Overview/Valuation/Financial po tickerze.
    Zwraca (lista słowników, łączna liczba wg Finviz). Widok pomocniczy, który się nie uda,
    nie przerywa całości — spółki zostają bez tych kolumn (None)."""
    session = requests.Session()
    base, total = fetch_view("111", filters, max_tickers, pause_s, session)
    by_ticker = {r["ticker"]: r for r in base}
    for view in views:
        try:
            extra, _ = fetch_view(view, filters, max_tickers, pause_s, session)
        except Exception as e:
            print(f"⚠️  Finviz: widok {view} niedostępny ({e}) — pomijam jego kolumny.")
            continue
        for r in extra:
            if r["ticker"] in by_ticker:
                by_ticker[r["ticker"]].update({k: v for k, v in r.items() if k != "ticker"})
    return list(by_ticker.values()), total


def load_config(path=CONFIG_PATH, filters=DEFAULT_FILTERS, max_tickers=DEFAULT_MAX_TICKERS):
    """Konfiguracja screenera z JSON-a; brakujące pola = wartości domyślne. Pola liczbowe spoza filtra
    przechodzą bez zmian."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        data = {}
    cfg = {k: v for k, v in data.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    cfg["filters"] = str(data.get("filters") or filters).strip()
    cfg["max_tickers"] = int(data.get("max_tickers") or max_tickers)
    return cfg
