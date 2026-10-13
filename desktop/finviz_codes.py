"""Czytelny opis kodów filtrów Finviz (`f=` z adresu skanera), żeby było widać, CO dokładnie synchronizujemy.
Znane kody mają ręczne opisy, reszta jest dekodowana wzorcami (próg liczbowy, SMA, grupy High / Low); nieznany kod zostaje
surowy z ostrzeżeniem — Finviz po cichu ignoruje kody, których nie zna."""
import re

from . import finviz_catalog

KNOWN = {
    "cap_smallover": "Kapitalizacja ≥ 300 mln USD (small i większe)", "cap_midover": "Kapitalizacja ≥ 2 mld USD (mid i większe)",
    "cap_largeover": "Kapitalizacja ≥ 10 mld USD (large i większe)", "cap_micro": "Kapitalizacja 50–300 mln USD (micro)",
    "cap_small": "Kapitalizacja 300 mln – 2 mld USD (small)", "cap_mid": "Kapitalizacja 2–10 mld USD (mid)", "cap_large": "Kapitalizacja 10–200 mld USD (large)",
    "cap_mega": "Kapitalizacja > 200 mld USD (mega)",
    "fa_epsqoq_high": "Wzrost EPS kwartał do kwartału (r/r): wysoki (> 25 %)", "fa_epsyoy_high": "Wzrost EPS w tym roku: wysoki (> 25 %)",
    "fa_epsyoyttm_high": "Wzrost EPS TTM r/r: wysoki (> 25 %)", "fa_epsyoy1_high": "Prognozowany wzrost EPS w przyszłym roku: wysoki (> 25 %)", "fa_salesqoq_high": "Wzrost sprzedaży kwartał do kwartału: wysoki (> 25 %)",
    "fa_epsqoq_pos": "Wzrost EPS kwartał do kwartału: dodatni", "fa_epsyoy_pos": "Wzrost EPS w tym roku: dodatni",
    "fa_epsyoy1_pos": "Prognozowany wzrost EPS w przyszłym roku: dodatni", "fa_salesqoq_pos": "Wzrost sprzedaży kwartał do kwartału: dodatni",
    "geo_usa": "Kraj: USA", "ind_stocksonly": "Tylko akcje (bez funduszy ETF)", "idx_sp500": "Indeks: S&P 500", "idx_ndx": "Indeks: Nasdaq 100",
    "exch_nasd": "Giełda: Nasdaq", "exch_nyse": "Giełda: NYSE", "sh_avgvol_o300": "Średni wolumen > 300 tys. akcji", "sh_price_o1": "Cena > 1 USD",
    "ta_sma200_pa": "Cena powyżej SMA 200", "ta_sma50_pa": "Cena powyżej SMA 50", "ta_sma20_pa": "Cena powyżej SMA 20",
    "ta_sma200_pb": "Cena poniżej SMA 200", "ta_sma50_pb": "Cena poniżej SMA 50", "ta_sma20_pb": "Cena poniżej SMA 20",
    "ta_highlow52w_nh": "Nowy szczyt 52 tygodni", "ta_highlow52w_b0to10h": "0–10 % poniżej szczytu 52 tygodni",
}
_UNITS = {"o": ">", "u": "<"}


def describe_code(code):
    """Opis jednego kodu; (tekst, znany: bool)."""
    code = code.strip()
    if code in KNOWN:
        return KNOWN[code], True
    m = re.fullmatch(r"sh_avgvol_([ou])(\d+)", code)
    if m:
        return f"Średni wolumen {_UNITS[m[1]]} {m[2]} tys. akcji", True
    m = re.fullmatch(r"sh_relvol_([ou])([\d.]+)", code)
    if m:
        return f"Względny wolumen {_UNITS[m[1]]} {m[2]}×", True
    m = re.fullmatch(r"sh_price_([ou])(\d+)", code)
    if m:
        return f"Cena {_UNITS[m[1]]} {m[2]} USD", True
    m = re.fullmatch(r"fa_(epsqoq|epsyoy|epsyoyttm|epsyoy1|salesqoq)_([ou])(\d+)", code)
    if m:
        name = {"epsqoq": "Wzrost EPS kwartał do kwartału", "epsyoy": "Wzrost EPS w tym roku", "epsyoyttm": "Wzrost EPS TTM r/r", "epsyoy1": "Prognozowany wzrost EPS w przyszłym roku",
                "salesqoq": "Wzrost sprzedaży kwartał do kwartału"}[m[1]]
        return f"{name} {_UNITS[m[2]]} {m[3]} %", True
    m = re.fullmatch(r"ta_volatility_(mo|wo)(\d+)", code)
    if m:
        return f"Zmienność {'miesiąca' if m[1] == 'mo' else 'tygodnia'} > {m[2]} %", True
    m = re.fullmatch(r"fa_(roe|roa|roi)_([ou])(\d+)", code)
    if m:
        return f"{m[1].upper()} {_UNITS[m[2]]} {m[3]} %", True
    m = re.fullmatch(r"fa_(pe|fpe|peg|ps|pb)_([ou])(\d+)", code)
    if m:
        return f"{m[1].upper()} {_UNITS[m[2]]} {m[3]}", True
    m = re.fullmatch(r"ta_sma(\d+)_(pa|pb)", code)
    if m:
        return f"Cena {'powyżej' if m[2] == 'pa' else 'poniżej'} SMA {m[1]}", True
    hit = finviz_catalog.code_index().get(code)   # każdy kod z katalogu kreatora (zweryfikowany na żywo)
    if hit:
        return f"{hit[0]}: {hit[1]}", True
    return f"{code} — nieznany kod (Finviz może go po cichu zignorować)", False


def describe(filters):
    """[(kod, opis, znany)] dla ciągu filtrów rozdzielonych przecinkami."""
    return [(c.strip(), *describe_code(c)) for c in (filters or "").split(",") if c.strip()]


def summary_lines(filters, max_tickers=None):
    """Linie tekstu „Kryteria Finviz” (do dziennika synchronizacji i okna z kryteriami)."""
    items = describe(filters)
    lines = [f"Kryteria Finviz ({len(items)} filtrów{f', max {max_tickers} spółek' if max_tickers else ''}):"]
    lines += [f"  • {text}" + ("" if known else "  ⚠") + f"   [{code}]" for code, text, known in items]
    return lines
