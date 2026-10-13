"""Kalkulator wielkości pozycji i dziennik otwartych pozycji (port positionSize / positionMetrics z Momentum). Konto w PLN, ceny w USD, kurs USD/PLN z danych."""
import math
import time
from pathlib import Path

from . import store


def position_size(capital_pln, fx, risk_pct, pos_pct, entry, stop):
    """Ile akcji kupić: pozycja nie przekracza pos_pct % konta ORAZ strata przy stopie nie przekracza risk_pct % konta (akcje ułamkowe, w dół do 0,01).
    Zwraca None, gdy brakuje danych."""
    ok = lambda v: isinstance(v, (int, float)) and math.isfinite(v)   # noqa: E731
    ok_pos, ok_risk = ok(pos_pct) and pos_pct > 0, ok(risk_pct) and risk_pct > 0
    if not all(ok(v) for v in (capital_pln, fx, entry)) or capital_pln <= 0 or fx <= 0 or entry <= 0 or not (ok_pos or ok_risk):
        return None
    per_share = entry - stop if ok(stop) and 0 < stop < entry else None
    if ok_risk and not ok_pos and per_share is None:
        return None
    cap_usd = capital_pln / fx
    by_pos = cap_usd * pos_pct / 100 / entry if ok_pos else math.inf
    by_risk = cap_usd * risk_pct / 100 / per_share if ok_risk and per_share is not None else math.inf
    shares = math.floor(min(by_pos, by_risk) * 100 + 1e-6) / 100
    if not math.isfinite(shares):
        return None
    return {"shares": shares, "limited_by": "risk" if by_risk < by_pos else "pos", "value_usd": shares * entry, "value_pln": shares * entry * fx,
            "pct_of_capital": shares * entry / cap_usd * 100,
            "risk_usd": shares * per_share if per_share is not None else None, "risk_pln": shares * per_share * fx if per_share is not None else None,
            "risk_pct": shares * per_share / cap_usd * 100 if per_share is not None else None}


def metrics(pos, price):
    """Zysk (%, $), wielokrotność ryzyka R, odległość do stopu, wartość — względem bieżącej ceny."""
    if not pos or not pos.get("entry") or pos["entry"] <= 0 or price is None:
        return None
    per = pos["entry"] - pos["stop"] if pos.get("stop") and pos["stop"] < pos["entry"] else None
    shares = pos.get("shares") or 0
    return {"pl_pct": (price / pos["entry"] - 1) * 100, "pl_usd": (price - pos["entry"]) * shares, "r": (price - pos["entry"]) / per if per else None,
            "to_stop_pct": (price / pos["stop"] - 1) * 100 if pos.get("stop") else None, "value_usd": price * shares,
            "stop_hit": bool(pos.get("stop") and price <= pos["stop"])}


class Positions:
    """Otwarte pozycje (data/positions.json): {ticker: {entry, stop, shares, date, note, ref_date, stop_hit_on}}."""

    def __init__(self, root):
        self.path = Path(root) / "positions.json"
        self.items = {t: p for t, p in (store.read_json(self.path, {}) or {}).items() if isinstance(p, dict) and p.get("entry")}

    def save(self):
        store.write_json(self.path, self.items)

    def set(self, ticker, entry, stop, shares, note="", ref_date=None):
        self.items[ticker.upper()] = {"entry": float(entry), "stop": float(stop) if stop else None, "shares": float(shares) if shares else None,
                                      "date": time.strftime("%Y-%m-%d"), "note": note.strip(), "ref_date": ref_date, "stop_hit_on": None}
        self.save()

    def remove(self, ticker):
        self.items.pop(ticker, None)
        self.save()

    def get(self, ticker):
        return self.items.get(ticker)

    def check_stops(self, series_fn, tickers=None):
        """Pozycje, których stop został dotknięty (Low sesji ≤ stop) po dacie danych z chwili otwarcia pozycji; oznacza je i zapisuje.
        series_fn(ticker) -> (daty, high, low, close) albo None."""
        hit = []
        for t, p in self.items.items():
            if p.get("stop_hit_on") or not p.get("stop") or (tickers is not None and t not in tickers):
                continue
            data = series_fn(t)
            if not data:
                continue
            dates, _hi, lo, _cl = data
            ref = p.get("ref_date") or p.get("date") or ""
            for j, d in enumerate(dates):
                if d > ref and lo[j] is not None and lo[j] <= p["stop"]:
                    p["stop_hit_on"] = d
                    hit.append(t)
                    break
        if hit:
            self.save()
        return sorted(hit)
