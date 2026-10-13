"""„Co nowego od ostatniego Sync”: porównanie listy skanera przed i po synchronizacji (kto wszedł, kto wypadł, nowe KUP / SPRZEDAJ,
przypięte boxy w strefie zagrożenia, spółki, które weszły do CANSLIM ≥ 5/7). Wynik leży w changes.json skanera."""
from pathlib import Path

from . import store

CANSLIM_MIN = 5
LABELS = {"zone": "📌 Przypięty box w strefie zagrożenia / exit", "buy_w": "🟢 Nowe KUP — tydzień", "buy_d": "🟢 Nowe KUP — dzień",
          "sell": "🔴 Nowe SPRZEDAJ / poza (tydzień)", "canslim": f"🏆 Weszły do CANSLIM ≥ {CANSLIM_MIN}/7", "new": "★ Nowe w skanerze", "dropped": "Wypadły ze skanera"}
ORDER = ["zone", "buy_w", "buy_d", "sell", "canslim", "new", "dropped"]
MARKS = {"zone": "⚠ strefa", "buy_w": "▲ KUP tyg.", "buy_d": "▲ KUP dzień", "sell": "▼ sprzedaj", "canslim": "🏆 CANSLIM", "new": "★ nowa"}   # etykieta w kolumnie „Zmiana”


def snapshot(rows):
    return {r["ticker"]: {"name": r.get("company"), "price": r.get("price"), "w": r.get("darvas_w"), "d": r.get("darvas_d"),
                          "pbox": r.get("pbox"), "cs": r.get("cs")} for r in rows}


def diff(old, new):
    """{kategoria: [tickery]} — puste kategorie pomijamy. old/new = wyniki snapshot(); bez starego stanu (pierwszy sync) brak różnic."""
    if not old:
        return {}
    out = {k: [] for k in ORDER}
    for t, n in new.items():
        o = old.get(t)
        if o is None:
            out["new"].append(t)
            continue
        if n.get("w") == "BUY" and o.get("w") != "BUY":
            out["buy_w"].append(t)
        if n.get("d") == "BUY" and o.get("d") != "BUY":
            out["buy_d"].append(t)
        if n.get("w") in ("SELL", "OUT") and o.get("w") not in ("SELL", "OUT"):
            out["sell"].append(t)
        if n.get("pbox") in ("ZONE", "EXIT") and o.get("pbox") not in ("ZONE", "EXIT"):
            out["zone"].append(t)
        if (n.get("cs") or 0) >= CANSLIM_MIN and (o.get("cs") or 0) < CANSLIM_MIN:
            out["canslim"].append(t)
    out["dropped"] = [t for t in old if t not in new]
    return {k: sorted(v) for k, v in out.items() if v}


def merge(prev, new):
    """Zmiany z kilku synchronizacji bez „przeczytania” sumują się (suma list per kategoria); „Wyczyść” w oknie zeruje."""
    out = {}
    for k in ORDER:
        vals = sorted(set((prev or {}).get(k, [])) | set((new or {}).get(k, [])))
        if vals:
            out[k] = vals
    return out


def marks(d):
    """{ticker: etykieta} do kolumny „Zmiana” (najważniejsza zmiana wygrywa; wypadłe nie mają wiersza)."""
    out = {}
    for key in reversed(ORDER):
        for t in (d or {}).get(key, []):
            if key in MARKS:
                out[t] = MARKS[key]
    return out


def total(d):
    return sum(len(v) for k, v in (d or {}).items() if k in ORDER)


def save(directory, d, at, names=None):
    store.write_json(Path(directory) / "changes.json", {"at": at, "diff": d, "names": names or {}})


def load(directory):
    c = store.read_json(Path(directory) / "changes.json", {}) or {}
    return {"at": c.get("at"), "diff": c.get("diff") or {}, "names": c.get("names") or {}}
