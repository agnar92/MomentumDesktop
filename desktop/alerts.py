"""Alerty cenowe: poziom na wykresie + kierunek (powyżej / poniżej). Sprawdzane po każdym Sync na dziennych (albo tygodniowych) świecach,
które zamknęły się PO zapisaniu alertu — ruch między synchronizacjami nie ucieknie (wystarczy High / Low sesji, nie tylko zamknięcie)."""
import time
import uuid
from pathlib import Path

from . import store

ABOVE, BELOW = "above", "below"


def infer_direction(level, ref_price):
    """Poziom nad bieżącą ceną = alert „powyżej”, pod nią = „poniżej”."""
    return ABOVE if level >= ref_price else BELOW


class Alerts:
    def __init__(self, root):
        self.path = Path(root) / "alerts.json"
        self.items = [a for a in (store.read_json(self.path, []) or []) if isinstance(a, dict) and a.get("ticker") and a.get("price")]

    def save(self):
        store.write_json(self.path, self.items)

    def add(self, ticker, price, direction, note="", ref_date=None):
        item = {"id": uuid.uuid4().hex[:8], "ticker": ticker.upper(), "price": float(price), "dir": direction if direction in (ABOVE, BELOW) else ABOVE,
                "note": note.strip(), "created": time.strftime("%Y-%m-%d %H:%M"), "ref_date": ref_date, "active": True, "triggered_on": None, "triggered_close": None}
        self.items.append(item)
        self.save()
        return item

    def remove(self, aid):
        self.items = [a for a in self.items if a["id"] != aid]
        self.save()

    def reactivate(self, aid):
        for a in self.items:
            if a["id"] == aid:
                a.update(active=True, triggered_on=None, triggered_close=None)
        self.save()

    def for_ticker(self, ticker, active_only=False):
        return [a for a in self.items if a["ticker"] == ticker and (a["active"] or not active_only)]

    def evaluate(self, series_fn, tickers=None):
        """Przebite alerty po Sync. series_fn(ticker) -> (daty, high, low, close) albo None; tickers = spółki aktualnego skanera (None = wszystkie).
        Zwraca listę świeżo przebitych alertów (są już oznaczone jako nieaktywne i zapisane)."""
        hit = []
        for a in self.items:
            if not a["active"] or (tickers is not None and a["ticker"] not in tickers):
                continue
            data = series_fn(a["ticker"])
            if not data:
                continue
            dates, hi, lo, cl = data
            ref = a.get("ref_date") or (a.get("created") or "")[:10]
            for j, d in enumerate(dates):
                if d <= ref or hi[j] is None or lo[j] is None:
                    continue
                if (a["dir"] == ABOVE and hi[j] >= a["price"]) or (a["dir"] == BELOW and lo[j] <= a["price"]):
                    a.update(active=False, triggered_on=d, triggered_close=cl[j])
                    hit.append(a)
                    break
        if hit:
            self.save()
        return hit

    def last_triggered(self, ticker):
        done = [a for a in self.items if a["ticker"] == ticker and a.get("triggered_on")]
        return max(done, key=lambda a: a["triggered_on"]) if done else None

    @staticmethod
    def describe(a):
        arrow = "↑ powyżej" if a["dir"] == ABOVE else "↓ poniżej"
        base = f"alert {a['price']:.2f} {arrow}"
        if a.get("triggered_on"):
            base += f" — przebity {a['triggered_on']}" + (f" (zamknięcie {a['triggered_close']:.2f})" if a.get("triggered_close") else "")
        return base + (f"   „{a['note']}”" if a.get("note") else "")
