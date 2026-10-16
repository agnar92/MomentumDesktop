"""Kolumny listy: definicje (etykieta, szerokość, format) wszystkich pól, jakie mamy w danych, oraz wybór kolumn skanera.
Dostępne kolumny = pola, które faktycznie występują w pobranych danych (+ policzone lokalnie: CANSLIM, Darvas, baza)."""
from . import finviz_catalog as fc
from . import flags as flags_mod
from . import glb as glb_mod

# klucz: (etykieta, szerokość, wyrównanie, format) — format: text / int / n1 / n2 / price / pct / mcap / bool / state / base / cs
DEFS = {
    "ticker": ("Symbol", 78, "w", "text"), "flag": ("Lista", 56, "w", "flag"), "change": ("Zmiana", 112, "w", "text"), "company": ("Spółka", 190, "w", "text"), "sector": ("Sektor", 130, "w", "text"),
    "industry": ("Branża", 170, "w", "text"), "market_cap": ("Kapitalizacja", 104, "e", "mcap"), "price": ("Cena", 86, "e", "price"),
    "rs_rating": ("RS", 50, "e", "int"), "eps_rating": ("EPS", 54, "e", "int"), "composite_rating": ("Comp", 60, "e", "int"),
    "industry_rating": ("Grupa", 64, "e", "int"), "accdis": ("Acc/Dis", 72, "w", "text"), "leader": ("Lider", 60, "w", "bool"),
    "cs": ("CANSLIM", 84, "e", "cs"), "cs_letters": ("C A N S L I M", 150, "w", "text"),
    "pct_from_high_52w": ("% od szczytu", 114, "e", "n1"), "base": ("Baza", 130, "w", "base"), "base_depth_pct": ("Głęb. bazy %", 108, "e", "n1"),
    "base_weeks": ("Tyg. bazy", 86, "e", "int"), "pivot": ("Pivot", 80, "e", "price"), "pct_to_pivot": ("Do pivotu %", 108, "e", "n1"),
    "vcp": ("VCP", 54, "w", "bool"), "darvas": ("Darvas", 140, "w", "state"), "pbox": ("Box 📌", 84, "w", "pbox"), "macd_up": ("MACD > sygnał", 108, "w", "bool"),
    "adr_pct": ("ADR %", 70, "e", "n1"), "dollar_volume_avg": ("Obrót dzienny", 110, "e", "mcap"),
    "pct_above_sma50": ("% nad SMA50", 104, "e", "n1"), "pct_above_sma200": ("% nad SMA200", 110, "e", "n1"),
    "ret_3m_pct": ("Zwrot 3M %", 92, "e", "n1"), "ret_6m_pct": ("Zwrot 6M %", 92, "e", "n1"), "ret_12m_pct": ("Zwrot 12M %", 98, "e", "n1"),
    "pe": ("P/E", 64, "e", "n1"), "forward_pe": ("Fwd P/E", 74, "e", "n1"), "eps_this_y": ("EPS ten rok %", 100, "e", "n1"),
    "eps_next_y": ("EPS przyszły %", 106, "e", "n1"), "eps_past_5y": ("EPS 5 lat %", 96, "e", "n1"), "eps_next_5y": ("EPS prog. 5 lat %", 120, "e", "n1"),
    "roe": ("ROE %", 66, "e", "n1"), "sales_qq": ("Sprzedaż q/q %", 108, "e", "n1"), "sales_past_5y": ("Sprzedaż 5 lat %", 120, "e", "n1"),
    "debt_eq": ("Dług/Kapitał", 100, "e", "n2"), "inst_own": ("Instytucje %", 100, "e", "n1"), "inst_trans": ("Zmiana inst. %", 108, "e", "n1"),
    "recom": ("Rekomendacja", 100, "e", "n1"), "finviz_target": ("Cena docelowa", 104, "e", "price"), "finviz_upside_pct": ("Upside %", 80, "e", "n1"),
    "pt_mean": ("Cel (średnia)", 100, "e", "price"), "pt_upside_pct": ("Upside do celu %", 112, "e", "n1"), "analysts": ("Analitycy", 82, "e", "int"),
    "earnings": ("Wyniki", 90, "w", "text"), "eps_q0_yoy": ("EPS ost. kw. r/r %", 124, "e", "n1"), "eps_q1_yoy": ("EPS poprz. kw. r/r %", 134, "e", "n1"),
    "eps_yr0": ("EPS rok 0 %", 92, "e", "n1"), "eps_yr1": ("EPS rok −1 %", 98, "e", "n1"), "eps_yr2": ("EPS rok −2 %", 98, "e", "n1"),
    "eps_accel": ("Akceleracja", 92, "w", "bool"), "shares_chg_pct": ("Zmiana liczby akcji %", 140, "e", "n1"), "inst_sponsor": ("Sponsor inst.", 100, "w", "bool"),
    "base_status": ("Status bazy", 110, "w", "text"), "climax_top": ("Climax", 64, "w", "bool"), "dist_top": ("Dystrybucja", 92, "w", "bool"),
    "low_ratio_1m": ("Cena/min 1M", 96, "e", "n2"), "low_ratio_3m": ("Cena/min 3M", 96, "e", "n2"), "low_ratio_6m": ("Cena/min 6M", 96, "e", "n2"),
    "qm_windows": ("Okna QM", 84, "w", "text"), "qm_max_ratio": ("Max cena/min", 104, "e", "n2"), "merge_src": ("Źródła", 170, "w", "text"),
    "glb_state": ("GLB", 96, "w", "glb"), "glb_dist_pct": ("Do linii %", 90, "e", "n1"), "glb_level": ("Zielona linia", 104, "e", "price"),
    "glb_months": ("Mies. linii", 86, "e", "int"),
    "rs_line_state": ("Linia RS", 90, "w", "text"), "vol_surge_5d": ("Skok wol. 5d ×", 100, "e", "n2"),
}
DEFAULT_COLUMNS = ["ticker", "flag", "company", "price", "rs_rating", "eps_rating", "composite_rating", "cs", "cs_letters", "pct_from_high_52w", "base",
                   "pct_to_pivot", "darvas", "pbox", "change", "sector"]
# pola policzone lokalnie — są zawsze (nawet przed pierwszym Sync)
COMPUTED = {"cs", "cs_letters", "base", "darvas", "pbox", "flag", "change", "macd_up"}
_SKIP = {"canslim", "spark", "darvas_w", "darvas_d", "macd_up_w", "macd_up_d", "darvas_text", "darvas_text_w", "darvas_text_d", "pbox_text", "pbox_rank", "as_of",
         "pivot_break_date", "rs_score", "accdis_score", "eps_score", "glb_rank"}
PBOX_LABELS = {"NONE": "", "ABOVE": "wybity", "INSIDE": "w boxie", "ZONE": "STREFA!", "EXIT": "EXIT!"}


def definition(key):
    """(etykieta, szerokość, wyrównanie, format) — dla pól Finviz-extra z katalogu, dla nieznanych pól zgadujemy z klucza."""
    if key in DEFS:
        return DEFS[key]
    if key in fc.EXTRA_COLUMNS:
        label, fmt = fc.EXTRA_COLUMNS[key][1], fc.EXTRA_COLUMNS[key][2]
        return (label, max(70, 9 * len(label)), "w" if fmt == "text" else "e", fmt)
    return (key, max(70, 9 * len(key)), "w", "auto")


def available(rows, extra_keys=()):
    """Klucze kolumn, które da się pokazać: policzone lokalnie + pola o niepustych wartościach w danych + zamówione z Finviz (po Sync)."""
    seen = set(COMPUTED)
    for r in rows:
        for k, v in r.items():
            if k not in _SKIP and isinstance(v, (int, float, str, bool)) and v not in ("", None):
                seen.add(k)
    seen.update(extra_keys)
    known = [k for k in DEFS if k in seen]
    known += sorted(k for k in seen if k not in DEFS and k not in fc.EXTRA_COLUMNS and not k.startswith("_"))
    known += [k for k in fc.EXTRA_COLUMNS if k in seen]
    return known


def label(key):
    return definition(key)[0]


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def format_cell(row, key, state_labels=None):
    """Tekst komórki dla klucza kolumny."""
    fmt = definition(key)[3]
    v = row.get(key)
    if fmt == "base":
        return row.get("_base_label") or ""
    if fmt == "flag":
        return next((x["icon"] for x in flags_mod.DEFAULT_LISTS if x["id"] == row.get("flag")), "")
    if fmt == "state":
        return (state_labels or {}).get(v, "")
    if fmt == "pbox":
        return PBOX_LABELS.get(v, "")
    if fmt == "glb":
        return glb_mod.STATE_LABELS.get(v, "")
    if fmt == "cs":
        return "–" if v is None else f"{v}/7"
    if fmt == "bool":
        return "✓" if v is True else ""
    if v is None or v == "":
        return "–" if fmt in ("price", "int", "n1", "n2", "pct", "mcap") else ""
    if fmt == "auto":
        fmt = "n2" if isinstance(v, float) else "text"
    if fmt in ("n1", "n2", "price", "pct", "int") and _num(v):
        return f"{v:.0f}" if fmt == "int" else f"{v:.2f}" if fmt in ("n2", "price") else f"{v:.1f}"
    if fmt == "mcap" and _num(v):
        a = abs(v)
        return f"{v / 1e12:.2f}T" if a >= 1e12 else f"{v / 1e9:.2f}B" if a >= 1e9 else f"{v / 1e6:.0f}M" if a >= 1e6 else f"{v / 1e3:.0f}K" if a >= 1e3 else f"{v:.0f}"
    return str(v)


def sort_value(row, key):
    """Klucz sortowania: (brak wartości, wartość) — puste zawsze na końcu."""
    fmt = definition(key)[3]
    if fmt == "pbox":
        return (False, row.get("pbox_rank", 9))
    if fmt == "glb":   # najpierw wybicia, potem czekające (najbliżej linii pierwsze), na końcu „za późno” i brak linii
        d = row.get("glb_dist_pct")
        return (row.get("glb_state") in (None, "", "NONE"), row.get("glb_rank", 9) * 1000 + abs(d if isinstance(d, (int, float)) else 0))
    if fmt == "flag":
        return (False, flags_mod.IDS.index(row["flag"]) if row.get("flag") in flags_mod.IDS else 99)
    if fmt == "base":
        v = row.get("_base_label")
    else:
        v = row.get(key)
    if isinstance(v, str):
        v = v.lower()
    return (v is None or v == "", v if v not in (None, "") else 0)
