"""Parser strony screenera Finviz (widok Overview) — CEM10 bierze z niego tylko skład indeksu (ticker i nazwa spółki).
UWAGA: Finviz po cichu ignoruje nieznany kod filtra (lista robi się szersza zamiast błędu) — dlatego desktop/cem10.py sprawdza liczbę spółek."""
import re

from lxml import html as lxml_html

PAGE = 20
URL = "https://finviz.com/screener/stocks"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
COLUMN_IDS = {
    "company": "company", "sector": "sector", "industry": "industry", "marketCap": "market_cap",
    "pe": "pe", "forwardPE": "forward_pe", "forwardPe": "forward_pe", "fwdPE": "forward_pe",
    "peg": "peg", "dividend": "dividend_yield", "dividendYield": "dividend_yield",
    "roe": "roe", "sharesOutstanding": "shares_outstanding", "outstanding": "shares_outstanding",
    "float": "shares_float", "instOwn": "institutional_ownership", "instTrans": "institutional_transactions",
    "shortFloat": "short_float", "shortRatio": "short_ratio",
}
HEADERS_OLD = {
    "Company": "company", "Sector": "sector", "Industry": "industry", "Market Cap": "market_cap",
    "P/E": "pe", "Forward P/E": "forward_pe", "Fwd P/E": "forward_pe", "PEG": "peg",
    "Dividend": "dividend_yield", "Div": "dividend_yield", "Dividend Yield": "dividend_yield",
    "ROE": "roe", "Outstanding": "shares_outstanding", "Shares Outstanding": "shares_outstanding",
    "Float": "shares_float", "Inst Own": "institutional_ownership", "Inst Trans": "institutional_transactions",
    "Short Float": "short_float", "Short Ratio": "short_ratio",
}
TEXT = {"company", "sector", "industry"}
_SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}

# Finviz column IDs vary in capitalization and naming between table views and UI versions.
_COLUMN_ALIASES = {
    "company": "company", "sector": "sector", "industry": "industry",
    "marketcap": "market_cap", "mktcap": "market_cap",
    "pe": "pe", "forwardpe": "forward_pe", "fwdpe": "forward_pe",
    "forwardperatio": "forward_pe", "fwdperatio": "forward_pe",
    "peg": "peg", "pegratio": "peg", "priceearningsgrowth": "peg",
    "dividend": "dividend_yield", "div": "dividend_yield",
    "dividendyield": "dividend_yield", "dividendyieldttm": "dividend_yield",
    "roe": "roe", "sharesoutstanding": "shares_outstanding", "outstanding": "shares_outstanding",
    "sharesfloat": "shares_float", "float": "shares_float",
    "instown": "institutional_ownership", "institutionalownership": "institutional_ownership",
    "insttrans": "institutional_transactions", "institutionaltransactions": "institutional_transactions",
    "shortfloat": "short_float", "shortratio": "short_ratio",
}


def _normalised_name(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _column_key(value):
    """Map current Finviz data-column-id variants to stable internal fields."""
    return _COLUMN_ALIASES.get(_normalised_name(value)) or COLUMN_IDS.get(value)


def _header_key(value):
    """Map old table headers (including abbreviated Finviz labels) to fields."""
    return HEADERS_OLD.get(value) or _COLUMN_ALIASES.get(_normalised_name(value))


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
            key = _column_key(cell.get("data-column-id"))
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
            key = _header_key(h)
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
