"""Dane programu w katalogu data/ obok programu (wersja portable): scans/<skaner>.json (lista spółek skanera), weekly.json (tygodniowe świece
wszystkich skanerów — wspólne, aktualizowane tylko o nowe tygodnie), monthly.json i sec.json (pamięć podręczna), settings.json (skanery Finviz,
wybrany skaner, User-Agent dla SEC, ostatnie symbole, filtry listy), daily.json (cache świec dziennych), alerts.json (linie trendu, obserwowane spółki, dziennik alertów)."""
import json
import os
import re
import sys
from pathlib import Path

from . import calc, finviz, sec

# skanery do wyboru: każdy = nazwa + filtr Finviz (+ limit spółek); wszystkie liczą tę samą strategię
DEFAULT_SCANNERS = [
    {"name": "Bezpieczny (backtest)", "filters": finviz.DEFAULT_FILTERS, "max_tickers": 1500},
    {"name": "Trend 50/200", "filters": "ta_sma50_pa,ta_sma200_pa,cap_midover,sh_avgvol_o300", "max_tickers": 1500},
    {"name": "Blisko rekordu (ATH)", "filters": "cap_smallover,sh_avgvol_o100,ta_alltime_b0to10h", "max_tickers": 1500},
    {"name": "CANSLIM", "filters": "cap_smallover,fa_epsqoq_high,fa_epsyoyttm_high,fa_salesqoq_high,ind_stocksonly,sh_avgvol_o300,sh_price_o1,ta_sma200_pa",
     "max_tickers": 1500},
    {"name": "Grow", "filters": "fa_opermargin_pos,fa_roa_o15,fa_roi_o15,sh_avgvol_o300,sh_price_o10,fa_epsrev_bp,fa_epsqoq_o10,fa_salesqoq_o10,fa_grossmargin_pos,fa_epsyoyttm_o10,fa_salesyoyttm_o10", "max_tickers": 1500},
]
DEFAULT_SETTINGS = {"sec_ua": sec.UA, "symbols": []}


def slug(name):
    t = name.lower().translate(str.maketrans("ąćęłńóśźż", "acelnoszz"))
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "skaner"


def normalize_scanners(settings):
    """settings["scanners"] (stary zapis: samo "filters" -> skaner „Mój filtr” przed domyślnymi). Unikalne nazwy, min. jeden skaner."""
    items = [dict(x) for x in settings.get("scanners") or [] if isinstance(x, dict) and x.get("filters")]
    if not items:
        items = [dict(x) for x in DEFAULT_SCANNERS]
        old = (settings.get("filters") or "").strip()
        if old and old != finviz.DEFAULT_FILTERS:
            items.insert(0, {"name": "Mój filtr", "filters": old, "max_tickers": finviz.MAX_TICKERS})
    # Dodaj nazwany Growth filter także do istniejących ustawień z własną listą skanerów.
    if not any(str(x.get("name", "")).strip() == "Grow" for x in items):
        grow = next((x for x in DEFAULT_SCANNERS if x["name"] == "Grow"), None)
        if grow:
            items.append(dict(grow))
    out, seen = [], set()
    for x in items:
        name = str(x.get("name") or "Skaner").strip() or "Skaner"
        while name in seen:
            name += " 2"
        seen.add(name)
        out.append({"name": name, "filters": str(x["filters"]).strip(), "max_tickers": int(x.get("max_tickers") or finviz.MAX_TICKERS)})
    settings.pop("filters", None)
    settings["scanners"] = out
    if settings.get("scanner") not in seen:
        settings["scanner"] = out[0]["name"]
    return settings


def app_dir():
    """Katalog programu: obok .exe (portable) albo korzeń repozytorium przy uruchomieniu ze źródeł."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir(base=None):
    d = Path(base) if base else app_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def write(path, data):
    """Zapis atomowy (plik tymczasowy + zamiana), żeby przerwany zapis nie zostawił uszkodzonego JSON-a."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


class Store:
    def __init__(self, base=None):
        self.dir = data_dir(base)
        self.settings = normalize_scanners({**DEFAULT_SETTINGS, **read(self.dir / "settings.json", {})})
        self.settings["strategy_conditions"] = calc.normalize_conditions(self.settings.get("strategy_conditions"))
        (self.dir / "scans").mkdir(exist_ok=True)
        self.series = read(self.dir / "weekly.json", None)
        if self.series is None:   # dane sprzed skanerów: świece ze starego scan.json
            self.series = read(self.dir / "scan.json", {}).get("series", {})
        self.daily_series = read(self.dir / "daily.json", {})
        self.extra = {}   # symbole otwarte przez Ctrl+K (tylko w pamięci): {ticker: (wiersz, świece)}
        a = read(self.dir / "alerts.json", {})
        self.alerts = {"lines": a.get("lines") or {}, "watch": a.get("watch") or {}, "pos": a.get("pos") or {}, "log": a.get("log") or [], "seen": a.get("seen") or ""}
        self.reload()

    @property
    def scanner(self):
        return next(x for x in self.settings["scanners"] if x["name"] == self.settings["scanner"])

    def scan_path(self, name=None):
        return self.dir / "scans" / f"{slug(name or self.settings['scanner'])}.json"

    def reload(self):
        scan = read(self.scan_path(), {})
        if not scan and self.settings["scanner"] == self.settings["scanners"][0]["name"]:
            scan = read(self.dir / "scan.json", {})   # stara lista (jeden skaner) jako pierwszy skaner
        self.rows, self.at = scan.get("rows", []), scan.get("at")
        for row in self.rows:
            row["ok"] = calc.passes(row, self.settings.get("strategy_conditions"))

    def select(self, name):
        """Przełącza wybrany skaner (lista spółek z jego ostatniego Sync)."""
        if any(x["name"] == name for x in self.settings["scanners"]):
            self.settings["scanner"] = name
            self.save_settings()
            self.reload()

    def save_scan(self, rows, series, at):
        """Lista wybranego skanera + świece (dopisane do wspólnego weekly.json; zostają tylko spółki z list skanerów i symbole)."""
        write(self.scan_path(), {"at": at, "rows": rows})
        keep = set(series)
        for sc in self.settings["scanners"]:
            keep.update(r["ticker"] for r in read(self.scan_path(sc["name"]), {}).get("rows", []))
        self.series = {t: s for t, s in {**self.series, **series}.items() if t in keep}
        write(self.dir / "weekly.json", self.series)
        self.reload()

    def save_symbol(self, ticker, row, series):
        """Zapisuje odświeżone dane jednego symbolu, nie zmieniając czasu pełnego skanu."""
        row = dict(row)
        if series:
            self.series[ticker] = series
            write(self.dir / "weekly.json", self.series)
        current = self.settings["scanner"]
        found_current = any(r.get("ticker") == ticker for r in self.rows)
        if found_current:
            self.rows = [row if r.get("ticker") == ticker else r for r in self.rows]
            write(self.scan_path(current), {"at": self.at, "rows": self.rows})
        for scanner in self.settings["scanners"]:
            if scanner["name"] == current:
                continue
            path = self.scan_path(scanner["name"])
            saved = read(path, {})
            rows = saved.get("rows", [])
            if any(r.get("ticker") == ticker for r in rows):
                saved["rows"] = [row if r.get("ticker") == ticker else r for r in rows]
                write(path, saved)
        self.extra[ticker] = (row, series)


    def daily(self, ticker):
        return self.daily_series.get(ticker)

    def save_daily_series(self, ticker, series):
        """Zapisuje pobrane świece dzienne, aby alerty linii działały także po ponownym uruchomieniu."""
        if series and series.get("d"):
            self.daily_series[ticker] = series
            write(self.dir / "daily.json", self.daily_series)

    def save_alerts(self):
        write(self.dir / "alerts.json", self.alerts)

    def save_settings(self):
        write(self.dir / "settings.json", self.settings)

    def cache(self, name):
        return read(self.dir / f"{name}.json", {})

    def save_cache(self, name, data):
        write(self.dir / f"{name}.json", data)

    def row(self, ticker):
        return next((r for r in self.rows if r["ticker"] == ticker), None) or (self.extra.get(ticker) or (None,))[0]

    def weekly(self, ticker):
        return self.series.get(ticker) or (self.extra.get(ticker) or (None, None))[1]
