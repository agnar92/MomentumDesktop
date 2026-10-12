"""Własne listy z kolorowymi flagami (jak flagi kolorów w TC2000): jedna flaga na spółkę, wspólna dla wszystkich skanerów (data/flags.json)."""
from pathlib import Path

from . import store

DEFAULT_LISTS = [
    {"id": "watch", "name": "Obserwuję", "icon": "⭐", "tint": "#2a2610"},
    {"id": "bought", "name": "Kupione", "icon": "🛒", "tint": "#10281a"},
    {"id": "check", "name": "Do sprawdzenia", "icon": "❗", "tint": "#2b1d10"},
    {"id": "rejected", "name": "Odrzucone", "icon": "🚫", "tint": "#1b1b1f"},
]
IDS = [lst["id"] for lst in DEFAULT_LISTS]


class Flags:
    def __init__(self, root):
        self.path = Path(root) / "flags.json"
        d = store.read_json(self.path, {}) or {}
        names = d.get("names") or {}
        self.lists = [{**lst, "name": names.get(lst["id"]) or lst["name"]} for lst in DEFAULT_LISTS]
        self.tickers = {t: lid for t, lid in (d.get("tickers") or {}).items() if lid in IDS}

    def save(self):
        store.write_json(self.path, {"tickers": self.tickers, "names": {lst["id"]: lst["name"] for lst in self.lists if lst["name"]}})

    def get(self, ticker):
        return self.tickers.get(ticker)

    def set(self, ticker, lid):
        """lid None / '' = usuń z listy; ta sama flaga drugi raz = też usuwa (przełącznik)."""
        if not lid or self.tickers.get(ticker) == lid:
            self.tickers.pop(ticker, None)
        elif lid in IDS:
            self.tickers[ticker] = lid
        self.save()

    def rename(self, lid, name):
        for lst in self.lists:
            if lst["id"] == lid and name.strip():
                lst["name"] = name.strip()
        self.save()

    def icon(self, lid):
        return next((lst["icon"] for lst in self.lists if lst["id"] == lid), "")

    def name(self, lid):
        return next((lst["name"] for lst in self.lists if lst["id"] == lid), "")

    def tag(self, rows):
        """Dopisuje do wierszy pole flag (id listy albo None)."""
        for r in rows:
            lid = self.tickers.get(r["ticker"])
            r["flag"] = lid
        return rows
