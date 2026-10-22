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
COLUMN_IDS = {"company": "company", "sector": "sector", "industry": "industry", "marketCap": "market_cap"}
HEADERS_OLD = {"Company": "company", "Sector": "sector", "Industry": "industry", "Market Cap": "market_cap"}
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
                row[key] = (txt or None) if key in TEXT else parse_number(txt)
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
                row[key] = (txt or None) if key in TEXT else parse_number(txt)
        rows.append(row)
    return rows, total


def fetch(filters, max_tickers=MAX_TICKERS, pause=0.7, log=print, get=None, progress=None):
    """Wszystkie strony screenera (po 20 wierszy). -> (wiersze, łączna liczba wg Finviz). progress(wiersze, oczekiwane) po każdej stronie."""
    get = get or requests.Session().get
    out, seen, offset, total = [], set(), 1, None
    while len(out) < max_tickers:
        r = get(URL, params={"v": "111", "f": filters, "r": offset}, headers=HEADERS, timeout=30)
        r.raise_for_status()
        rows, t = parse_page(r.text)
        total = t if t is not None else total
        new = [x for x in rows if x["ticker"] not in seen]
        if not new:
            break
        for x in new:
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


# Finviz screener view IDs: Overview, Valuation, Financial, Ownership, Performance, Technical.
# Fetch every view so fields not present in Overview (ROI, margins, estimates, performance, technicals, etc.) are retained.
ALL_VIEWS = (111, 121, 161, 131, 141, 171)
_FIELD_ALIASES = {
    "marketCap": "market_cap", "marketcap": "market_cap", "company": "company", "ticker": "ticker",
    "avgVolume": "avg_volume", "relVolume": "rel_volume", "currentRatio": "current_ratio",
    "quickRatio": "quick_ratio", "debtEq": "debt_equity", "ltDebtEq": "long_term_debt_equity",
    "grossMargin": "gross_margin", "operMargin": "opm", "profitMargin": "profit_margin",
    "epsQoq": "eps_qoq", "salesQoq": "sales_qoq", "epsYoyTtm": "eps_yoy_ttm",
    "salesYoyTtm": "sales_yoy_ttm", "epsThisY": "eps_this_year", "epsNextY": "eps_next_year",
    "epsNext5Y": "eps_next_5y", "salesPast5Y": "sales_past_5y", "epsPast5Y": "eps_past_5y",
    "roi": "roi", "roa": "roa", "roe": "roe", "targetPrice": "target_price",
    "epsSurprise": "eps_surprise_finviz", "salesSurprise": "revenue_surprise_finviz",
    "perfWeek": "perf_week", "perfMonth": "perf_month", "perfQuarter": "perf_quarter",
    "perfHalfY": "perf_half_year", "perfYear": "perf_year", "perfYtd": "perf_ytd",
    "perf3Year": "perf_3y", "perf5Year": "perf_5y", "sma20": "sma20", "sma50": "sma50",
    "sma200": "sma200", "rsi": "rsi", "beta": "beta", "atr": "atr", "change": "change",
    "price": "price", "volume": "volume", "avgVolume": "avg_volume", "shortFloat": "short_float",
    "shortRatio": "short_ratio", "instOwn": "institutional_ownership", "instTrans": "institutional_change",
    "insiderOwn": "insider_ownership", "insiderTrans": "insider_change", "high52": "high_52w",
    "low52": "low_52w", "forwardPE": "forward_pe", "peg": "peg", "ps": "ps", "pb": "pb",
    "pfcf": "pfcf", "pe": "pe", "evEbitda": "ev_ebitda", "evSales": "ev_sales",
    "grossMargin": "gross_margin", "dividend": "dividend", "payout": "payout",
    "sales": "sales", "income": "income", "bookSh": "book_value_share", "cashSh": "cash_share",
    "employees": "employees", "country": "country", "exchange": "exchange", "industry": "industry",
    "sector": "sector", "index": "index", "earnings": "earnings_date", "recom": "analyst_recommendation",
}
_TEXT_FIELDS = {"ticker", "company", "sector", "industry", "country", "exchange", "index", "earnings_date"}


def _field_name(name):
    if name in _FIELD_ALIASES:
        return _FIELD_ALIASES[name]
    # Keep unfamiliar Finviz columns too; snake_case is stable for storage and UI use.
    return re.sub(r"(?<!^)(?=[A-Z])", "_", str(name)).lower().replace("-", "_").replace(" ", "_")


def _field_value(name, value):
    key = _field_name(name)
    if value is None or value == "-":
        return None
    if key in _TEXT_FIELDS:
        return str(value).strip() or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        # Finviz SSR stores market capitalization in millions.
        return number * 1e6 if key == "market_cap" else number
    parsed = parse_number(str(value))
    return parsed if parsed is not None else str(value).strip()


def parse_data_page(page):
    """Parse every visible column in a Finviz screener view, retaining unknown fields too."""
    m = re.search(r"#\d+\s*/\s*(\d+)\s*Total", page)
    total = int(m.group(1)) if m else None
    json_match = re.search(r'<script type="application/json" data-ssr-props="[^"]*">(.*?)</script>', page, re.S)
    if json_match:
        try:
            data = json.loads(json_match.group(1)).get("data") or {}
            out = []
            for source in data.get("rows") or []:
                vals = {**(source.get("text") or {}), **(source.get("numbers") or {})}
                ticker = str(vals.get("ticker") or "").strip()
                if not ticker:
                    continue
                row = {"ticker": ticker}
                for name, value in vals.items():
                    if name == "ticker":
                        continue
                    row[_field_name(name)] = _field_value(name, value)
                out.append(row)
            count = data.get("totalCount")
            return out, int(count) if isinstance(count, (int, float)) else total
        except (ValueError, TypeError, AttributeError):
            pass
    tree = lxml_html.fromstring(page)
    rows = []
    for tr in tree.xpath("//div[contains(@class, 'fv-table_row') and @data-row-key]"):
        ticker = (tr.get("data-row-key") or "").strip()
        if not ticker:
            continue
        row = {"ticker": ticker}
        for cell in tr.xpath(".//div[@data-column-id]"):
            name = cell.get("data-column-id")
            if name:
                row[_field_name(name)] = _field_value(name, cell.text_content().strip())
        rows.append(row)
    if rows:
        return rows, total
    heads = [th.text_content().strip() for th in tree.xpath('//table[contains(@class, "screener_table")]//thead//th')]
    for tr in tree.xpath('//tr[contains(@class, "styled-row")]'):
        tds = tr.xpath("./td")
        if len(tds) != len(heads) or len(tds) < 2:
            continue
        ticker = (tds[1].get("data-boxover-ticker") or tds[1].text_content()).strip()
        if not ticker:
            continue
        row = {"ticker": ticker}
        for heading, cell in zip(heads, tds):
            name = HEADERS_OLD.get(heading) or _field_name(heading)
            if name in {"no", "ticker"}:
                continue
            row[name] = _field_value(name, cell.text_content().strip())
        rows.append(row)
    return rows, total


def fetch_all(filters, max_tickers=MAX_TICKERS, pause=0.25, log=print, get=None, progress=None, views=ALL_VIEWS):
    """Fetch and merge all Finviz screener tabs by ticker; Overview decides membership, other tabs enrich the same universe."""
    get = get or requests.Session().get
    merged, total = {}, None
    for view in views:
        view_rows, view_total, seen, offset = [], None, set(), 1
        log(f"Finviz: pobieram zakładkę v={view}")
        while len(seen) < max_tickers:
            response = get(URL, params={"v": str(view), "f": filters, "r": offset}, headers=HEADERS, timeout=30)
            response.raise_for_status()
            page_rows, page_total = parse_data_page(response.text)
            if page_total is not None:
                view_total = page_total
            fresh = [row for row in page_rows if row["ticker"] not in seen]
            if not fresh:
                break
            for row in fresh:
                seen.add(row["ticker"])
                if view == 111:
                    merged.setdefault(row["ticker"], {}).update(row)
                elif row["ticker"] in merged:
                    merged[row["ticker"]].update({k: v for k, v in row.items() if v is not None})
                else:
                    # If the provider sorts/views differ slightly, preserve the row but Overview remains authoritative below.
                    view_rows.append(row)
            if progress:
                progress(len(seen), min(view_total or len(seen), max_tickers))
            offset += PAGE
            if view_total is not None and offset > view_total:
                break
            time.sleep(pause)
        if view == 111:
            total = view_total
        elif view_rows:
            log(f"Finviz v={view}: {len(view_rows)} dodatkowych tickerów nieobecnych w Overview — pomijam")
        if view == 111 and not merged:
            raise RuntimeError("Finviz Overview nie zwrócił spółek; nie pobieram pozostałych zakładek.")
    out = list(merged.values())[:max_tickers]
    if out:
        log(f"Finviz: pobrano {len(out)} spółek i połączono zakładki {','.join(map(str, views))}")
    return out, total
