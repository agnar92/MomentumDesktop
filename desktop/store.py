"""Dane programu w katalogu data/ obok programu (wersja portable): scan.json (lista + tygodniowe świece), monthly.json i sec.json
(pamięć podręczna), settings.json (filtr Finviz, User-Agent dla SEC, ostatnie symbole)."""
import json
import os
import sys
from pathlib import Path

from . import finviz, sec

DEFAULT_SETTINGS = {"filters": finviz.DEFAULT_FILTERS, "sec_ua": sec.UA, "symbols": []}


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
        self.settings = {**DEFAULT_SETTINGS, **read(self.dir / "settings.json", {})}
        self.reload()

    def reload(self):
        scan = read(self.dir / "scan.json", {})
        self.rows, self.series, self.at = scan.get("rows", []), scan.get("series", {}), scan.get("at")
        self.extra = {}   # symbole otwarte przez Ctrl+K (tylko w pamięci): {ticker: (wiersz, świece)}

    def save_scan(self, rows, series, at):
        write(self.dir / "scan.json", {"at": at, "rows": rows, "series": series})
        self.reload()

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
