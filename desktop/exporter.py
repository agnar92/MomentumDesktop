"""Eksport listy: tickery do schowka / pliku (np. import do TradingView) i CSV z widocznymi kolumnami."""
import csv
import io

from . import columns

FORMATS = {
    "xl": {"delimiter": ";", "decimal": ",", "label": "CSV dla Excela PL (średnik, przecinek dziesiętny)"},
    "std": {"delimiter": ",", "decimal": ".", "label": "CSV standardowy (przecinek, kropka)"},
}


def tickers_text(rows, sep=","):
    """Same symbole w kolejności listy; sep: ',' (jedna linia) albo '\\n' (po jednym w linii)."""
    return sep.join(r["ticker"] for r in rows)


def _cell(row, key, fmt, decimal, state_labels):
    v = row.get(key)
    kind = columns.definition(key)[3]
    if kind in ("base", "state", "pbox", "cs", "bool") or key == "flag":
        return columns.format_cell(row, key, state_labels).replace("–", "")
    if isinstance(v, bool):
        return "1" if v else ""
    if isinstance(v, float):
        return (f"{v:.4f}".rstrip("0").rstrip(".")).replace(".", decimal)
    return "" if v is None else str(v)


def to_csv(rows, cols, fmt="xl", state_labels=None, flag_labels=None):
    """Tekst CSV (nagłówki = etykiety kolumn, liczby surowe); z BOM-em robi to zapis pliku (utf-8-sig), tu czysty tekst."""
    spec = FORMATS[fmt]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=spec["delimiter"], lineterminator="\r\n")
    w.writerow([columns.label(k) for k in cols])
    for r in rows:
        line = []
        for k in cols:
            if k == "flag":
                line.append((flag_labels or {}).get(r.get("flag"), ""))
            else:
                line.append(_cell(r, k, fmt, spec["decimal"], state_labels))
        w.writerow(line)
    return buf.getvalue()
