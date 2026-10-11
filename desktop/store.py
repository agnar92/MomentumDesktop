"""Dane aplikacji: katalog `data/` obok programu (wersja portable), wczytywanie JSON-ów, przypięte boxy, filtry skanera."""
import json
import shutil
import sys
from pathlib import Path

from . import darvas

STATE_LABELS = {"BUY": "KUP", "NOVOL": "bez wolumenu", "LATE": "za późno", "HOLD": "trzymaj", "SELL": "SPRZEDAJ",
                "OUT": "poza", "WAIT": "czekaj", "NONE": ""}
BASE_LABELS = {"cup": "cup", "double_bottom": "double bottom", "flat": "flat", "square_box": "square box", "ascending": "ascending",
               "htf": "high tight flag", "ipo": "ipo", "correction": "korekta", "deep": "głęboka"}
BUYABLE_BASES = {"cup", "double_bottom", "flat", "square_box", "ascending", "htf", "ipo"}


def app_dir():
    """Katalog programu: obok .exe (portable) albo korzeń repozytorium przy uruchomieniu ze źródeł."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir():
    """Zasoby spakowane z programem (seed_data/, engine/)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return Path(__file__).resolve().parent.parent


def data_dir(base=None):
    d = Path(base) if base else app_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    seed = resource_dir() / "seed_data"
    if seed.is_dir():   # pierwsze uruchomienie: przykładowe dane, żeby okno nie było puste przed pierwszym Sync
        for f in seed.glob("*.json"):
            if not (d / f.name).exists():
                shutil.copy(f, d / f.name)
    return d


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def base_label(s):
    t = s.get("base_type")
    return BASE_LABELS.get(t, t or "")


def enrich(stock, full, pin, weeks):
    """Dopisuje do spółki pola liczone lokalnie: stan Darvasa i status przypiętego boxa."""
    c = (full or {}).get("c") or []
    st = darvas.status(c, (full or {}).get("v")) if c else {"state": "NONE", "text": ""}
    stock["darvas"] = st["state"]
    stock["darvas_text"] = st.get("text", "")
    ps = darvas.pin_status(pin, stock.get("price")) if pin else {"state": "NONE", "rank": 9, "text": ""}
    stock["pbox"] = ps["state"]
    stock["pbox_text"] = ps["text"]
    stock["pbox_rank"] = ps["rank"]
    return stock


class Store:
    def __init__(self, base=None):
        self.dir = data_dir(base)
        self.watchlist, self.charts, self.pinned = {}, {}, {}
        self.rows = []
        self.reload()

    @property
    def stocks_full(self):
        return self.charts.get("stocks", {})

    @property
    def weeks(self):
        return self.charts.get("weeks", [])

    def reload(self):
        self.watchlist = read_json(self.dir / "watchlist.json", {}) or {}
        self.charts = read_json(self.dir / "charts.json", {}) or {}
        self.pinned = read_json(self.dir / "pinned.json", {}) or {}
        self.rows = [enrich(dict(s), self.stocks_full.get(s["ticker"]), self.pinned.get(s["ticker"]), self.weeks)
                     for s in self.watchlist.get("stocks", [])]

    def row(self, ticker):
        return next((r for r in self.rows if r["ticker"] == ticker), None)

    def pin(self, ticker, box):
        """box = {top, bottom, start} albo None (odepnij)."""
        if box:
            self.pinned[ticker] = {"top": box["top"], "bottom": box["bottom"], "start": box.get("start", "")}
        else:
            self.pinned.pop(ticker, None)
        write_json(self.dir / "pinned.json", self.pinned)
        r = self.row(ticker)
        if r:
            enrich(r, self.stocks_full.get(ticker), self.pinned.get(ticker), self.weeks)

    def overview(self):
        items = [{"ticker": r["ticker"], "price": r.get("price"), "c": self.stocks_full.get(r["ticker"], {}).get("c"),
                  "v": self.stocks_full.get(r["ticker"], {}).get("v")} for r in self.rows]
        return darvas.overview(items, self.weeks, self.pinned)

    def finviz_config(self):
        return read_json(self.dir / "finviz_screen.json", {}) or {}

    def save_finviz_config(self, filters, max_tickers):
        cfg = self.finviz_config()
        cfg["filters"], cfg["max_tickers"] = filters.strip(), int(max_tickers)
        write_json(self.dir / "finviz_screen.json", cfg)


# ---------- skaner (filtry po danych już pobranych) ----------

DEFAULT_FILTERS = {"rs_min": None, "eps_min": None, "comp_min": None, "max_to_pivot": None, "max_from_high": None,
                   "states": [], "sector": "", "base_only": False, "min_adr": None, "pinned_only": False, "text": ""}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def scan(rows, f):
    """Zwraca wiersze spełniające filtry skanera (puste/None = filtr wyłączony)."""
    f = {**DEFAULT_FILTERS, **(f or {})}
    out = []
    text = (f["text"] or "").strip().lower()
    for r in rows:
        if f["rs_min"] is not None and (_num(r.get("rs_rating")) is None or r["rs_rating"] < f["rs_min"]):
            continue
        if f["eps_min"] is not None and (_num(r.get("eps_rating")) is None or r["eps_rating"] < f["eps_min"]):
            continue
        if f["comp_min"] is not None and (_num(r.get("composite_rating")) is None or r["composite_rating"] < f["comp_min"]):
            continue
        if f["min_adr"] is not None and (_num(r.get("adr_pct")) is None or r["adr_pct"] < f["min_adr"]):
            continue
        if f["max_to_pivot"] is not None:   # odległość do pivotu: od -3 % (świeże wybicie) do limitu
            d = _num(r.get("pct_to_pivot"))
            if d is None or not (-3 <= d <= f["max_to_pivot"]):
                continue
        if f["max_from_high"] is not None:   # max odległość pod 52-tygodniowym szczytem (w % — liczba dodatnia)
            d = _num(r.get("pct_from_high_52w"))
            if d is None or d < -abs(f["max_from_high"]):
                continue
        if f["states"] and r.get("darvas") not in f["states"]:
            continue
        if f["sector"] and r.get("sector") != f["sector"]:
            continue
        if f["base_only"] and r.get("base_type") not in BUYABLE_BASES:
            continue
        if f["pinned_only"] and r.get("pbox") == "NONE":
            continue
        if text and text not in (r["ticker"] + " " + (r.get("company") or "")).lower():
            continue
        out.append(r)
    return out


PRESETS = {
    "Darvas: KUP (wybicie na wolumenie)": {"states": ["BUY"]},
    "Liderzy RS ≥ 80 blisko szczytu": {"rs_min": 80, "max_from_high": 10},
    "Blisko pivotu (≤ 5 %)": {"max_to_pivot": 5, "base_only": True},
    "Silne fundamenty: Composite ≥ 80": {"comp_min": 80},
    "Box czeka na wybicie": {"states": ["WAIT"]},
}
