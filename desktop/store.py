"""Dane programu w katalogu data/ obok programu (wersja portable): scans/<skaner>.json (lista spółek skanera), weekly.json (tygodniowe świece
wszystkich skanerów — wspólne, aktualizowane tylko o nowe tygodnie), monthly.json i sec.json (pamięć podręczna), settings.json (skanery Finviz,
wybrany skaner, User-Agent dla SEC, ostatnie symbole, filtry listy), alerts.json (linie trendu, obserwowane spółki, dziennik alertów)."""
import json
import os
import re
import sys
from pathlib import Path

from . import calc, finviz, sec

# skanery do wyboru: każdy = nazwa + filtr Finviz (+ limit spółek); wszystkie liczą tę samą strategię
RULES_VERSION = 2   # podnieś, gdy zmienią się domyślne warunki strategii (stare zapisane ustawienia warunków są wtedy resetowane)
SECTOR_SCANNER = {"name": "Sektory top 3 (RS)", "filters": calc.SECTOR_FILTERS, "max_tickers": 500, "top_sectors": calc.TOP_SECTORS}
DEFAULT_SCANNERS = [
    SECTOR_SCANNER,   # podstawowy skaner: 3 sektory z najsilniejszym RS (ETF / SPY nad SMA 52 tyg.) × 3 zapytania Finviz (sektor + cena > 15 $ + przychody kw. > 15 %)
    {"name": "Bezpieczny (backtest)", "filters": finviz.DEFAULT_FILTERS, "max_tickers": 1500},
    {"name": "Trend 50/200", "filters": "ta_sma50_pa,ta_sma200_pa,cap_midover,sh_avgvol_o300", "max_tickers": 1500},
    {"name": "Blisko rekordu (ATH)", "filters": "cap_smallover,sh_avgvol_o100,ta_alltime_b0to10h", "max_tickers": 1500},
    {"name": "CANSLIM", "filters": "cap_smallover,fa_epsqoq_high,fa_epsyoyttm_high,fa_salesqoq_high,ind_stocksonly,sh_avgvol_o300,sh_price_o1,ta_sma200_pa",
     "max_tickers": 1500},
]
DEFAULT_SETTINGS = {"sec_ua": sec.UA, "symbols": []}
DEFAULT_WATCHLIST = "Moja watchlista"
VIEW_LIST, VIEW_WATCH = "list", "watch"   # widok główny: lista wybranego skanera albo watchlista (skany + dodane tickery)


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
    out, seen = [], set()
    for x in items:
        name = str(x.get("name") or "Skaner").strip() or "Skaner"
        while name in seen:
            name += " 2"
        seen.add(name)
        item = {"name": name, "filters": str(x["filters"]).strip(), "max_tickers": int(x.get("max_tickers") or finviz.MAX_TICKERS)}
        if x.get("top_sectors"):   # skaner sektorowy: 1 zapytanie Finviz na każdy z N najsilniejszych sektorów
            item["top_sectors"] = max(1, min(len(calc.SECTOR_ETFS), int(x["top_sectors"])))
        out.append(item)
    settings.pop("filters", None)
    settings["scanners"] = out
    if settings.get("scanner") not in seen:
        settings["scanner"] = out[0]["name"]
    return settings


def norm_ticker(t):
    """Ticker w formie zapisu: wielkie litery, bez spacji i przecinków (np. ' nvda,' -> 'NVDA')."""
    return re.sub(r"[\s,;]+", "", str(t or "")).upper()


def split_tickers(text):
    """Ticker-y z pola tekstowego (rozdzielone spacją, przecinkiem, średnikiem albo nową linią), bez powtórzeń, w kolejności wpisania."""
    out = []
    for part in re.split(r"[\s,;]+", str(text or "")):
        t = norm_ticker(part)
        if t and t not in out:
            out.append(t)
    return out


def normalize_watchlists(settings):
    """settings["watchlists"] = [{"name", "tickers", "sources"}] (tickers = dodane ręcznie, sources = nazwy skanerów, których listy wchodzą do watchlisty — dowolnie wiele): unikalne nazwy (bez względu na wielkość liter), unikalne tickery, min. jedna watchlista;
    settings["main_view"] = {"mode": list/watch, "watchlist": nazwa, "ask": czy pytać o widok przy starcie}."""
    out, seen = [], set()
    for x in settings.get("watchlists") or []:
        if not isinstance(x, dict):
            continue
        name = str(x.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        tickers = []
        for t in x.get("tickers") or []:
            t = norm_ticker(t)
            if t and t not in tickers:
                tickers.append(t)
        names = {sc["name"] for sc in settings.get("scanners") or []}
        sources = []
        for n in x.get("sources") or []:
            if n in names and n not in sources:
                sources.append(n)
        out.append({"name": name, "tickers": tickers, "sources": sources})
    if not out:
        out = [{"name": DEFAULT_WATCHLIST, "tickers": [], "sources": []}]
    settings["watchlists"] = out
    v = settings.get("main_view") if isinstance(settings.get("main_view"), dict) else {}
    mode = v.get("mode") if v.get("mode") in (VIEW_LIST, VIEW_WATCH) else VIEW_LIST
    name = v.get("watchlist") if any(w["name"] == v.get("watchlist") for w in out) else out[0]["name"]
    settings["main_view"] = {"mode": mode, "watchlist": name, "ask": bool(v.get("ask", True))}
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
        if self.settings.get("rules_version", 0) < RULES_VERSION:   # reguły z badania 2011–2025: tylko przychody + marża (RS, P/S, beat2 wyłączone)
            self.settings["strategy_conditions"] = calc.normalize_conditions(None)
            self.settings["rules_version"] = RULES_VERSION
        self.settings["strategy_conditions"] = calc.normalize_conditions(self.settings.get("strategy_conditions"))
        if not self.settings.get("sector_scanner_v1"):   # istniejące ustawienia: dołóż skaner sektorowy na początek i wybierz go (raz)
            if not any(x.get("top_sectors") for x in self.settings["scanners"]):
                self.settings["scanners"].insert(0, dict(SECTOR_SCANNER))
                self.settings["scanner"] = SECTOR_SCANNER["name"]
            self.settings["sector_scanner_v1"] = True
        normalize_watchlists(self.settings)
        (self.dir / "scans").mkdir(exist_ok=True)
        self.series = read(self.dir / "weekly.json", None)
        if self.series is None:   # dane sprzed skanerów: świece ze starego scan.json
            self.series = read(self.dir / "scan.json", {}).get("series", {})
        self.extra = {}   # symbole otwarte poza listą skanera: {ticker: (wiersz, świece)}
        a = read(self.dir / "alerts.json", {})
        self.alerts = {
            "lines": a.get("lines") or {},
            "watch": a.get("watch") or {},
            "pos": a.get("pos") or {},
            "log": a.get("log") or [],
            "seen": a.get("seen") or "",
        }
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
        self.sectors = scan.get("sectors") or []   # ranking RS sektorów z ostatniego Sync skanera sektorowego [{etf, sector, pct, selected}]
        # Indeks pozostałych skanerów pozwala otworzyć ticker z już zapisanymi danymi
        # bez ponownego pobierania tylko dlatego, że zmienił się aktywny skaner.
        self._other_rows = {}
        for scanner in self.settings["scanners"]:
            if scanner["name"] == self.settings["scanner"]:
                continue
            for row in read(self.scan_path(scanner["name"]), {}).get("rows", []):
                ticker = row.get("ticker")
                if ticker:
                    self._other_rows.setdefault(ticker, row)
        for row in self.rows:
            row["ok"] = calc.passes(row, self.settings.get("strategy_conditions"))
            if "cc52w" not in row and "cc250" in row:   # starsze zapisy: C/C250 -> C/C[52 tyg.]
                row["cc52w"] = row.pop("cc250")
            row.pop("rwb_days", None)
            if "rwb_weeks" not in row:   # starsze zapisy (sprzed kolumny RWB tyg.): liczone z zapisanych świec tygodniowych
                w = self.weekly(row.get("ticker", ""))
                row["rwb_weeks"] = calc.rwb_weeks([x or 0 for x in w["c"]]) if w and w.get("c") else None

    def add_scanner(self, name, filters=None):
        """Nowy skaner (lista) z filtrem Finviz. -> nazwa albo None, gdy pusta lub już taka istnieje (bez względu na wielkość liter)."""
        name = str(name or "").strip()
        if not name or any(x["name"].lower() == name.lower() for x in self.settings["scanners"]):
            return None
        self.settings["scanners"].append({"name": name, "filters": str(filters or "").strip() or finviz.DEFAULT_FILTERS, "max_tickers": finviz.MAX_TICKERS})
        normalize_scanners(self.settings)
        self.save_settings()
        return name

    def select(self, name):
        """Przełącza wybrany skaner (lista spółek z jego ostatniego Sync)."""
        if any(x["name"] == name for x in self.settings["scanners"]):
            self.settings["scanner"] = name
            self.save_settings()
            self.reload()

    # --- watchlisty: nazwane listy tickerów obserwowanych (widok = wyniki skanera + dodane tickery)
    def watchlists(self):
        return self.settings["watchlists"]

    def watchlist(self, name):
        return next((w for w in self.settings["watchlists"] if w["name"] == name), None)

    def add_watchlist(self, name):
        """Nowa pusta watchlista. -> nazwa albo None, gdy pusta lub już taka istnieje (bez względu na wielkość liter)."""
        name = str(name or "").strip()
        if not name or any(w["name"].lower() == name.lower() for w in self.settings["watchlists"]):
            return None
        self.settings["watchlists"].append({"name": name, "tickers": [], "sources": []})
        self.save_settings()
        return name

    def rename_watchlist(self, old, new):
        new = str(new or "").strip()
        w = self.watchlist(old)
        if w is None or not new or any(x["name"].lower() == new.lower() and x is not w for x in self.settings["watchlists"]):
            return False
        w["name"] = new
        if self.settings["main_view"]["watchlist"] == old:
            self.settings["main_view"]["watchlist"] = new
        self.save_settings()
        return True

    def delete_watchlist(self, name):
        """Usuwa watchlistę (zawsze zostaje co najmniej jedna); widok z usuniętej wraca do listy skanera."""
        if self.watchlist(name) is None or len(self.settings["watchlists"]) <= 1:
            return False
        self.settings["watchlists"] = [w for w in self.settings["watchlists"] if w["name"] != name]
        v = self.settings["main_view"]
        if v["watchlist"] == name:
            v["watchlist"] = self.settings["watchlists"][0]["name"]
            v["mode"] = VIEW_LIST
        self.save_settings()
        return True

    def add_to_watchlist(self, name, tickers):
        """Dodaje tickery (tekst z wieloma albo lista) do watchlisty `name`. -> lista nowo dodanych (bez już obecnych)."""
        w = self.watchlist(name)
        if w is None:
            return []
        items = split_tickers(tickers) if isinstance(tickers, str) else [t for t in (norm_ticker(x) for x in tickers) if t]
        added = []
        for t in items:
            if t not in w["tickers"] and t not in added:
                added.append(t)
        w["tickers"].extend(added)
        if added:
            self.save_settings()
        return added

    def remove_from_watchlist(self, name, tickers):
        w = self.watchlist(name)
        if w is None:
            return []
        drop = [norm_ticker(t) for t in (split_tickers(tickers) if isinstance(tickers, str) else tickers)]
        removed = [t for t in w["tickers"] if t in drop]
        w["tickers"] = [t for t in w["tickers"] if t not in drop]
        if removed:
            self.save_settings()
        return removed

    def set_watchlist_sources(self, name, sources):
        """Listy których skanerów wchodzą do watchlisty ."""
        w = self.watchlist(name)
        if w is not None:
            names = {sc["name"] for sc in self.settings["scanners"]}
            w["sources"] = [n for n in dict.fromkeys(sources) if n in names]
            self.save_settings()

    def watch_tickers(self):
        """Wszystkie tickery ze wszystkich watchlist (Sync odświeża je także poza listą skanera)."""
        return {t for w in self.settings["watchlists"] for t in w["tickers"]}

    def set_view(self, mode, name=None, ask=None):
        v = self.settings["main_view"]
        v["mode"] = mode if mode in (VIEW_LIST, VIEW_WATCH) and (mode == VIEW_LIST or self.watchlist(name or v["watchlist"])) else VIEW_LIST
        if name and self.watchlist(name):
            v["watchlist"] = name
        if ask is not None:
            v["ask"] = bool(ask)
        self.save_settings()

    def view_rows(self):
        """Wiersze widoku głównego i zbiór ticker-ów dodanych ręcznie: lista skanera, a w widoku watchlisty — listy dołączonych skanerów + dodane tickery (bez powtórzeń);
        ticker bez pobranych danych dostaje pusty wiersz, który wypełni się po Sync."""
        v = self.settings["main_view"]
        w = self.watchlist(v["watchlist"]) if v["mode"] == VIEW_WATCH else None
        if w is None:
            return self.rows, set()
        base, have = [], set()
        for name in w.get("sources", []):
            rows = self.rows if name == self.settings["scanner"] else read(self.scan_path(name), {}).get("rows", [])
            for r in rows:
                if r["ticker"] not in have:
                    have.add(r["ticker"])
                    base.append(r)
        for t in w["tickers"]:
            if t not in have:
                have.add(t)
                base.append(self.row(t) or {"ticker": t, "company": "(brak danych — ⟳ Sync)"})
        return base, set(w["tickers"])

    def save_scan(self, rows, series, at, sectors=None):
        """Lista wybranego skanera (+ ranking sektorów) i świece (dopisane do wspólnego weekly.json; zostają tylko spółki z list skanerów i symbole)."""
        write(self.scan_path(), {"at": at, "rows": rows, **({"sectors": sectors} if sectors else {})})
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
            write(self.scan_path(current), {"at": self.at, "rows": self.rows, **({"sectors": self.sectors} if self.sectors else {})})
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
        if ticker in self._other_rows:
            self._other_rows[ticker] = row


    def save_alerts(self):
        write(self.dir / "alerts.json", self.alerts)

    def save_settings(self):
        write(self.dir / "settings.json", self.settings)

    def cache(self, name):
        return read(self.dir / f"{name}.json", {})

    def save_cache(self, name, data):
        write(self.dir / f"{name}.json", data)

    def row(self, ticker):
        return (next((r for r in self.rows if r["ticker"] == ticker), None)
                or (self.extra.get(ticker) or (None,))[0]
                or self._other_rows.get(ticker))

    def weekly(self, ticker):
        return self.series.get(ticker) or (self.extra.get(ticker) or (None, None))[1]
