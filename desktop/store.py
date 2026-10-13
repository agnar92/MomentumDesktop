"""Dane aplikacji: katalog `data/` obok programu (wersja portable), wczytywanie JSON-ów, przypięte boxy, filtry skanera."""
import json
import os
import shutil
import sys
import threading
from pathlib import Path

from . import canslim, changes, darvas, daily

STATE_LABELS = {"BUY": "KUP", "NOVOL": "bez wolumenu", "LATE": "za późno", "HOLD": "trzymaj", "SELL": "SPRZEDAJ",
                "OUT": "poza", "WAIT": "czekaj", "NONE": ""}
BASE_LABELS = {"cup": "cup", "double_bottom": "double bottom", "flat": "flat", "square_box": "square box", "ascending": "ascending",
               "htf": "high tight flag", "ipo": "ipo", "correction": "korekta", "deep": "głęboka"}
BUYABLE_BASES = {"cup", "double_bottom", "flat", "square_box", "ascending", "htf", "ipo"}


OLD_DEFAULT_FILTERS = "cap_smallover,fa_epsqoq_high,fa_epsyoy_high,fa_epsyoy1_high,fa_salesqoq_high,geo_usa,ind_stocksonly,sh_avgvol_o300,sh_price_o1,ta_sma200_pa"
NEW_DEFAULT_FILTERS = "cap_smallover,fa_epsqoq_high,fa_epsyoyttm_high,fa_salesqoq_high,ind_stocksonly,sh_avgvol_o300,sh_price_o1,ta_sma200_pa"


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


def data_dir(base=None, seed=True):
    d = Path(base) if base else app_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    seed_dir = resource_dir() / "seed_data"
    if seed and seed_dir.is_dir():   # pierwsze uruchomienie: przykładowe dane, żeby okno nie było puste przed pierwszym Sync
        for f in seed_dir.glob("*.json"):
            if not (d / f.name).exists():
                shutil.copy(f, d / f.name)
        fs = d / "finviz_screen.json"   # dawny domyślny filtr CANSLIM -> aktualny (tylko gdy użytkownik go nie zmieniał)
        cfg = read_json(fs, None)
        if isinstance(cfg, dict) and cfg.get("filters") == OLD_DEFAULT_FILTERS:
            cfg["filters"] = NEW_DEFAULT_FILTERS
            write_json(fs, cfg)
    return d


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    tmp = Path(f"{path}.{os.getpid()}.{threading.get_ident()}.tmp")   # unikalny plik tymczasowy: równoległe synchronizacje nie nadpisują sobie zapisu
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def base_label(s):
    t = s.get("base_type")
    return BASE_LABELS.get(t, t or "")


def darvas_state(full, tf):
    c = (full or {}).get("c") or []
    if not c:
        return {"state": "NONE", "text": ""}
    return darvas.status(c, full.get("v"), **(darvas.DAILY if tf == "D" else {}))


def enrich(stock, full, pin, weeks, tf="W", full_d=None):
    """Dopisuje do spółki pola liczone lokalnie: stan Darvasa (tygodniowy i dzienny) i status przypiętego boxa."""
    sw, sd = darvas_state(full, "W"), darvas_state(full_d, "D")
    stock["_base_label"] = base_label(stock)
    stock["darvas_w"], stock["darvas_d"] = sw["state"], sd["state"]
    stock["darvas_text_w"], stock["darvas_text_d"] = sw.get("text", ""), sd.get("text", "")
    st = sd if tf == "D" and full_d else sw
    stock["darvas"] = st["state"]
    stock["darvas_text"] = st.get("text", "")
    ps = darvas.pin_status(pin, stock.get("price")) if pin else {"state": "NONE", "rank": 9, "text": ""}
    stock["pbox"] = ps["state"]
    stock["pbox_text"] = ps["text"]
    stock["pbox_rank"] = ps["rank"]
    return stock


class Store:
    def __init__(self, base=None, seed=True):
        self.dir = data_dir(base, seed)
        self.watchlist, self.charts, self.charts_d, self.pinned = {}, {}, {}, {}
        self.rows = []
        self.tf = "W"   # „W” tygodniowy / „D” dzienny — wpływa na stan Darvasa w liście
        self._sma = {}
        self.adhoc = {}   # tickery spoza skanera pobrane na żądanie (Ctrl+K): {T: {weekly, weeks, daily, dates, row}}
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
        self.charts_d = read_json(self.dir / "charts_daily.json", {}) or {}
        self.pinned = read_json(self.dir / "pinned.json", {}) or {}
        self._sma = {}
        mkt = canslim.market(self.watchlist)
        self.mkt = mkt
        extra = read_json(self.dir / "finviz_extra.json", {}) or {}   # dodatkowe kolumny zamówione w skanerze (tylko z Finviz)
        self.rows = [canslim.tag(self._enrich({**s, **extra.get(s["ticker"], {})}), mkt) for s in self.watchlist.get("stocks", [])]
        self.changes = changes.load(self.dir)   # co się zmieniło przy ostatnim Sync
        self._mark_changes()

    def _mark_changes(self):
        marks = changes.marks(self.changes["diff"])
        for r in self.rows:
            r["change"] = marks.get(r["ticker"], "")

    def set_changes(self, diff, at, names=None):
        """Zapisuje wynik porównania po Sync i oznacza wiersze w kolumnie „Zmiana”."""
        changes.save(self.dir, diff, at, names)
        self.changes = {"at": at, "diff": diff, "names": names or {}}
        self._mark_changes()

    def _enrich(self, s):
        t = s["ticker"]
        return enrich(s, self.stocks_full.get(t), self.pinned.get(t), self.weeks, self.tf, self.charts_d.get("stocks", {}).get(t))

    def set_tf(self, tf):
        """Przełącznik listy: tygodniowy / dzienny stan Darvasa (kolumna Darvas i filtry skanera)."""
        self.tf = "D" if tf == "D" and self.charts_d.get("stocks") else "W"
        for r in self.rows + [x["row"] for x in self.adhoc.values()]:
            r["darvas"] = r["darvas_d"] if self.tf == "D" else r["darvas_w"]
            r["darvas_text"] = r["darvas_text_d"] if self.tf == "D" else r["darvas_text_w"]

    def series(self, ticker, tf):
        """(dane OHLCV, lista dat, S&P 500, średnie [(tablica, nazwa)]) dla wykresu w danej skali czasu; dane dzienne mają SMA 10 / 50 / 200."""
        ad = self.adhoc.get(ticker) if ticker not in self.stocks_full else None
        if ad is not None:   # ticker spoza skanera: własne serie, oś S&P tylko gdy zgadza się z osią skanera
            if tf == "D":
                key = ("AD", ticker)
                if key not in self._sma:
                    self._sma[key] = [(daily.sma(ad["daily"]["c"], n), n) for n in (10, 50, 200)]
                same = ad["dates"] == self.charts_d.get("dates")
                return ad["daily"], ad["dates"], self.charts_d.get("spx") if same else None, self._sma[key]
            w = ad["weekly"]
            same = ad["weeks"] == self.weeks
            return w, ad["weeks"], self.charts.get("spx") if same else None, [((w or {}).get("sma10") or [], 10), ((w or {}).get("sma40") or [], 40)]
        if tf == "D":
            full = (self.charts_d.get("stocks") or {}).get(ticker)
            if not full:
                return None, [], [], []
            key = ("D", ticker)
            if key not in self._sma:
                self._sma[key] = [(daily.sma(full["c"], n), n) for n in (10, 50, 200)]
            return full, self.charts_d.get("dates", []), self.charts_d.get("spx"), self._sma[key]
        full = self.stocks_full.get(ticker)
        return full, self.weeks, self.charts.get("spx"), [((full or {}).get("sma10") or [], 10), ((full or {}).get("sma40") or [], 40)]

    def row(self, ticker):
        return next((r for r in self.rows if r["ticker"] == ticker), None) or (self.adhoc.get(ticker) or {}).get("row")

    def add_adhoc(self, symbol, data, company=None):
        """Dodaje dane dowolnego tickera (adhoc.build): wiersz z Darvasem i CANSLIM (bez fundamentów) + serie do wykresów."""
        stock = {"ticker": symbol, "company": company or symbol, "price": round(data["price"], 2), "as_of": data["last_date"], "_adhoc": True}
        stock = canslim.tag(enrich(stock, data["weekly"], self.pinned.get(symbol), data["weeks"], self.tf, data["daily"]), self.mkt)
        stock["flag"] = None
        self.adhoc[symbol] = {**data, "row": stock}
        return stock

    def pin(self, ticker, box):
        """box = {top, bottom, start} albo None (odepnij)."""
        if box:
            self.pinned[ticker] = {"top": box["top"], "bottom": box["bottom"], "start": box.get("start", "")}
        else:
            self.pinned.pop(ticker, None)
        write_json(self.dir / "pinned.json", self.pinned)
        r = self.row(ticker)
        if r:
            ps = darvas.pin_status(self.pinned.get(ticker), r.get("price")) if ticker in self.pinned else {"state": "NONE", "rank": 9, "text": ""}
            r["pbox"], r["pbox_text"], r["pbox_rank"] = ps["state"], ps["text"], ps["rank"]

    def overview(self):
        daily_on = self.tf == "D"
        src = (self.charts_d.get("stocks") or {}) if daily_on else self.stocks_full
        items = [{"ticker": r["ticker"], "price": r.get("price"), "c": src.get(r["ticker"], {}).get("c"),
                  "v": src.get(r["ticker"], {}).get("v")} for r in self.rows]
        return darvas.overview(items, self.charts_d.get("dates", []) if daily_on else self.weeks, self.pinned, params=darvas.DAILY if daily_on else None)

    def finviz_config(self):
        return read_json(self.dir / "finviz_screen.json", {}) or {}


# ---------- skaner (filtry po danych już pobranych) ----------

DEFAULT_FILTERS = {"rs_min": None, "eps_min": None, "comp_min": None, "max_to_pivot": None, "max_from_high": None,
                   "states": [], "sector": "", "base_only": False, "min_adr": None, "pinned_only": False, "text": "", "cs_min": None, "cs_core": False, "flag": ""}


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
        if f["cs_min"] is not None and (_num(r.get("cs")) is None or r["cs"] < f["cs_min"]):
            continue
        if f["cs_core"] and not (r.get("canslim") and canslim.core_ok(r)):
            continue
        if f["flag"]:   # lista własna: id listy / "any" (dowolna) / "none" (bez flagi)
            fl = r.get("flag")
            if (f["flag"] == "any" and not fl) or (f["flag"] == "none" and fl) or (f["flag"] not in ("any", "none") and fl != f["flag"]):
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
    "CANSLIM ≥ 5/7 (C i A obowiązkowe)": {"cs_min": 5, "cs_core": True},
    "Box czeka na wybicie": {"states": ["WAIT"]},
}
