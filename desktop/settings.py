"""Ustawienia programu (data/settings.json): harmonogram synchronizacji, konto do kalkulatora pozycji, reguły kolorów listy."""
import copy
from pathlib import Path

from . import store

DEFAULTS = {
    "schedule": {"prices": {"enabled": False, "time": "23:30", "days": [0, 1, 2, 3, 4]},          # po zamknięciu sesji USA (czas lokalny), pn–pt
                 "fundamentals": {"enabled": False, "time": "07:00", "days": [5]}},                 # sobota rano
    "account": {"capital_pln": None, "risk_pct": 0.5, "pos_pct": 10.0, "fx": None},
    "rules": [],
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    def __init__(self, root):
        self.path = Path(root) / "settings.json"
        self.data = _merge(DEFAULTS, store.read_json(self.path, {}) or {})

    def save(self):
        store.write_json(self.path, self.data)

    def __getitem__(self, key):
        return self.data[key]
