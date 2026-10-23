"""Lista spółek z darmowego screenera Finviz (widok Overview: ticker, spółka, sektor, branża, kapitalizacja).
Finviz robi tylko wstępne cięcie listy do pobrania; dokładne warunki liczy aplikacja. UWAGA: Finviz po cichu ignoruje nieznany kod
filtra (lista robi się szersza zamiast błędu) — po zmianie filtra sprawdź liczbę spółek."""
import re
import time

import requests
from lxml import html as lxml_html

# Bezpieczny filtr z backtestu: nie odcina żadnego z dużych zwycięzców (tylko akcje, cena > 10 $, śr. wolumen > 300 tys., przychody kw. > 15 % r/r)
DEFAULT_FILTERS = "ind_stocksonly,sh_price_o10,sh_avgvol_o300,fa_salesqoq_o15"
MAX_TICKERS = 1500
PAGE = 20
URL = "https://finviz.com/screener/stocks"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
COLUMN_IDS = {
    "company": "company", "sector": "sector", "industry": "industry", "marketCap": "market_cap",
    "pe": "pe", "forwardPE": "forward_pe", "forwardPe": "forward_pe", "fwdPE": "forward_pe",
    "peg": "peg", "dividend": "dividend_yield", "dividendYield": "dividend_yield",
}
HEADERS_OLD = {
    "Company": "company", "Sector": "sector", "Industry": "industry", "Market Cap": "market_cap",
    "P/E": "pe", "Forward P/E": "forward_pe", "Fwd P/E": "forward_pe", "PEG": "peg",
    "Dividend": "dividend_yield", "Div": "dividend_yield", "Dividend Yield": "dividend_yield",
}
TEXT = {"company", "sector", "industry"}
_SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def parse_number(text):
    """'47.26B' -> 47.26e9, '10.9%' -> 10.9, '-' -> None."""
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


def parse_page(page):
    """-> (wiersze, łączna liczba wg strony albo None). Obsługuje nowy układ (div.fv-table_row) i stary (tabela)."""
    m = re.search(r"#\d+\s*/\s*(\d+)\s*Total", page)
    total = int(m.group(1)) if m else None
    tree = lxml_html.fromstring(page)
    rows = []
    for tr in tree.xpath("//div[contains(@class, 'fv-table_row') and @data-row-key]"):
        row = {"ticker": tr.get("data-row-key").strip()}
        for cell in tr.xpath(".//div[@data-column-id]"):
            key = COLUMN_IDS.get(cell.get("data-column-id"))
            if key:
                txt = cell.text_content().strip()
                if key in TEXT:
                    row[key] = txt or None
                elif key == "dividend_yield" and txt in ("", "-", "—"):
                    # Finviz wyświetla brak wypłaty dywidendy jako „-”; dla PEGY to 0%.
                    row[key] = 0.0
                else:
                    row[key] = parse_number(txt)
        rows.append(row)
    if rows:
        return rows, total
    heads = [th.text_content().strip() for th in tree.xpath('//table[contains(@class, "screener_table")]//thead//th')]
    for tr in tree.xpath('//tr[contains(@class, "styled-row")]'):
        tds = tr.xpath("./td")
        if len(tds) != len(heads) or len(tds) < 2:
            continue
        row = {"ticker": (tds[1].get("data-boxover-ticker") or tds[1].text_content()).strip()}
        for h, td in zip(heads, tds):
            key = HEADERS_OLD.get(h)
            if key:
                txt = td.text_content().strip()
                if key in TEXT:
                    row[key] = txt or None
                elif key == "dividend_yield" and txt in ("", "-", "—"):
                    row[key] = 0.0
                else:
                    row[key] = parse_number(txt)
        rows.append(row)
    return rows, total


def fetch(filters, max_tickers=MAX_TICKERS, pause=0.7, log=print, get=None, progress=None):
    """Wszystkie strony screenera (po 20 wierszy). -> (wiersze, łączna liczba wg Finviz). progress(wiersze, oczekiwane) po każdej stronie."""
    get = get or requests.Session().get
    out, seen, offset, total = [], set(), 1, None
    failed_views = set()
    while len(out) < max_tickers:
        r = get(URL, params={"v": "111", "f": filters, "r": offset}, headers=HEADERS, timeout=30)
        r.raise_for_status()
        rows, t = parse_page(r.text)
        total = t if t is not None else total
        new = [x for x in rows if x["ticker"] not in seen]
        if not new:
            break

        # PEG i Forward P/E pochodzą z widoku Valuation (v=121), a stopa dywidendy
        # z Financial (v=161). Dopasowujemy po tickerze, nie po pozycji w tabeli.
        page_metrics = {}
        for view in ("121", "161"):
            if view in failed_views:
                continue
            try:
                vr = get(URL, params={"v": view, "f": filters, "r": offset}, headers=HEADERS, timeout=30)
                vr.raise_for_status()
                view_rows, _ = parse_page(vr.text)
                page_metrics[view] = {item["ticker"]: item for item in view_rows}
            except Exception as exc:  # brak wskaźników nie może przerwać całego skanu
                failed_views.add(view)
                log(f"Finviz widok {view} niedostępny — odpowiednie kolumny pozostaną puste ({exc})")
                page_metrics[view] = {}
        for x in new:
            for view, keys in (("121", ("forward_pe", "peg")), ("161", ("dividend_yield",))):
                metrics = page_metrics.get(view, {}).get(x["ticker"], {})
                for key in keys:
                    if key in metrics:
                        x[key] = metrics[key]
            seen.add(x["ticker"])
            out.append(x)
        if progress:
            progress(len(out), min(total or len(out), max_tickers))
        if offset == 1 and total:
            log(f"Finviz: {total} spółek z filtrem")
        offset += PAGE
        if total is not None and offset > total:
            break
        time.sleep(pause)
    return out[:max_tickers], total
