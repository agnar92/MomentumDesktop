"""Własne skanery Finviz: każdy skaner = osobny katalog danych (data/scanners/<id>/) z własnym finviz_screen.json, watchlist.json,
wykresami itd. Skaner „default” to dotychczasowy (dane w głównym katalogu data/). Lista skanerów: data/scanners.json
([{id, name, columns, extra}]); filtry i limit spółek leżą w finviz_screen.json skanera (tak czyta je silnik)."""
import re
import shutil
from pathlib import Path

from . import store

DEFAULT_ID = "default"
DEFAULT_NAME = "CANSLIM (domyślny)"


def scanner_dir(root, sid):
    root = Path(root)
    return root if sid == DEFAULT_ID else root / "scanners" / sid


def load_config(directory):
    cfg = store.read_json(Path(directory) / "finviz_screen.json", {}) or {}
    return {"filters": str(cfg.get("filters") or "").strip(), "max_tickers": int(cfg.get("max_tickers") or 300)}


def save_config(directory, filters, max_tickers):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cfg = store.read_json(directory / "finviz_screen.json", {}) or {}
    cfg["filters"], cfg["max_tickers"] = ",".join(c.strip() for c in filters.split(",") if c.strip()), int(max_tickers)
    store.write_json(directory / "finviz_screen.json", cfg)


def load(root):
    """Lista skanerów; domyślny zawsze pierwszy."""
    items = store.read_json(Path(root) / "scanners.json", []) or []
    items = [{"id": s["id"], "name": s.get("name") or s["id"], "columns": s.get("columns"), "extra": list(s.get("extra") or [])}
             for s in items if isinstance(s, dict) and s.get("id")]
    if not any(s["id"] == DEFAULT_ID for s in items):
        items.insert(0, {"id": DEFAULT_ID, "name": DEFAULT_NAME, "columns": None, "extra": []})
    items.sort(key=lambda s: s["id"] != DEFAULT_ID)
    return items


def save(root, items):
    store.write_json(Path(root) / "scanners.json", items)


def slug(name, existing):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower().translate(str.maketrans("ąćęłńóśźż", "acelnoszz"))).strip("-") or "skaner"
    sid, n = base, 2
    while sid in existing or sid == DEFAULT_ID:
        sid, n = f"{base}-{n}", n + 1
    return sid


def get(root, sid):
    return next((s for s in load(root) if s["id"] == sid), None)


def upsert(root, scanner, filters=None, max_tickers=None):
    """Zapisuje skaner (nowy dostaje id z nazwy) i jego filtry; zwraca zapisany słownik."""
    items = load(root)
    scanner = dict(scanner)
    if not scanner.get("id"):
        scanner["id"] = slug(scanner.get("name") or "skaner", {s["id"] for s in items})
    scanner.setdefault("columns", None)
    scanner["extra"] = list(scanner.get("extra") or [])
    items = [s for s in items if s["id"] != scanner["id"]] + [scanner]
    items.sort(key=lambda s: s["id"] != DEFAULT_ID)
    save(root, items)
    if filters is not None:
        save_config(scanner_dir(root, scanner["id"]), filters, max_tickers or 300)
    return scanner


def duplicate(root, sid, new_name):
    src = get(root, sid)
    cfg = load_config(scanner_dir(root, sid))
    new = upsert(root, {"name": new_name, "columns": src.get("columns"), "extra": src.get("extra")}, cfg["filters"], cfg["max_tickers"])
    return new


def delete(root, sid):
    """Usuwa skaner razem z jego danymi (domyślnego nie można usunąć)."""
    if sid == DEFAULT_ID:
        return False
    save(root, [s for s in load(root) if s["id"] != sid])
    shutil.rmtree(scanner_dir(root, sid), ignore_errors=True)
    return True


# ---------- wspólny cache fundamentów (EPS z Yahoo, estymaty): skanery nie pobierają drugi raz tych samych spółek ----------

def _stamp(entry):
    return str((entry or {}).get("fetched") or (entry or {}).get("f") or (entry or {}).get("updated") or "")


def merge_cache(src, dst):
    """Dopisuje do dst wpisy z src, których dst nie ma albo ma starsze (eps_cache.json: {T: wpis}, estimates.json: {stocks: {T: wpis}})."""
    src, dst = Path(src), Path(dst)
    if src.resolve() == dst.resolve():
        return
    for name, nested in (("eps_cache.json", False), ("estimates.json", True)):
        a, b = store.read_json(src / name, None), store.read_json(dst / name, None)
        if not a:
            continue
        pa, pb = (a.get("stocks", {}) if nested else a), ((b or {}).get("stocks", {}) if nested else (b or {}))
        merged = dict(pb)
        for t, e in pa.items():
            if t not in merged or _stamp(e) > _stamp(merged[t]):
                merged[t] = e
        if merged == pb and b is not None:
            continue
        out = {**(b or {}), **({"stocks": merged, "updated": (a.get("updated") or (b or {}).get("updated"))} if nested else {})}
        store.write_json(dst / name, out if nested else merged)
