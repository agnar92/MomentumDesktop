"""Własne skanery Finviz: każdy skaner = osobny katalog danych (data/scanners/<id>/) z własnym finviz_screen.json, watchlist.json,
wykresami itd. Skaner „default” to dotychczasowy (dane w głównym katalogu data/). Lista skanerów: data/scanners.json
([{id, name, columns, extra}]); filtry i limit spółek leżą w finviz_screen.json skanera (tak czyta je silnik)."""
import contextlib
import os
import re
import shutil
import time
from pathlib import Path

from . import qm, store

DEFAULT_ID = "default"
DEFAULT_NAME = "CANSLIM (domyślny)"
KIND_FINVIZ, KIND_QM, KIND_MERGE = "finviz", "qm", "merge"   # zwykły skaner Finviz / Qullamaggie (cena × ADR × cena/min Low) / scalenie kilku skanerów w jedną listę


def scanner_dir(root, sid):
    root = Path(root)
    return root if sid == DEFAULT_ID else root / "scanners" / sid


def load_config(directory):
    cfg = store.read_json(Path(directory) / "finviz_screen.json", {}) or {}
    out = {"filters": str(cfg.get("filters") or "").strip(), "max_tickers": int(cfg.get("max_tickers") or 300)}
    if isinstance(cfg.get("qm"), dict):   # skaner Qullamaggie: progi w tym samym pliku (czyta je też proces synchronizacji)
        out["qm"] = qm.normalize(cfg["qm"])
    return out


def save_config(directory, filters, max_tickers, qm_cfg=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cfg = store.read_json(directory / "finviz_screen.json", {}) or {}
    cfg["filters"], cfg["max_tickers"] = ",".join(c.strip() for c in filters.split(",") if c.strip()), int(max_tickers)
    if qm_cfg is not None:
        cfg["qm"] = qm.normalize(qm_cfg)
    store.write_json(directory / "finviz_screen.json", cfg)


def save_qm(directory, qm_cfg):
    """Zapisuje same progi Qullamaggie (bez ruszania filtrów Finviz)."""
    cfg = load_config(directory)
    save_config(directory, cfg["filters"], cfg["max_tickers"], qm_cfg)


def load(root):
    """Lista skanerów; domyślny zawsze pierwszy."""
    items = store.read_json(Path(root) / "scanners.json", []) or []
    items = [{"id": s["id"], "name": s.get("name") or s["id"], "columns": s.get("columns"), "extra": list(s.get("extra") or []),
              "kind": s.get("kind") if s.get("kind") in (KIND_QM, KIND_MERGE) else KIND_FINVIZ, "sources": list(s.get("sources") or [])}
             for s in items if isinstance(s, dict) and s.get("id")]
    if not any(s["id"] == DEFAULT_ID for s in items):
        items.insert(0, {"id": DEFAULT_ID, "name": DEFAULT_NAME, "columns": None, "extra": [], "kind": KIND_FINVIZ, "sources": []})
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


def upsert(root, scanner, filters=None, max_tickers=None, qm_cfg=None):
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
        save_config(scanner_dir(root, scanner["id"]), filters, max_tickers or 300, qm_cfg)
    return scanner


def duplicate(root, sid, new_name):
    src = get(root, sid)
    cfg = load_config(scanner_dir(root, sid))
    new = upsert(root, {"name": new_name, "columns": src.get("columns"), "extra": src.get("extra"), "kind": src.get("kind"), "sources": src.get("sources")},
                 cfg["filters"], cfg["max_tickers"], cfg.get("qm"))
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


@contextlib.contextmanager
def cache_lock(directory, timeout=30.0):
    """Prosta blokada plikowa na czas scalania wspólnego cache (równoległe synchronizacje); przeterminowaną (martwy proces) zrywamy."""
    path = Path(directory) / ".cache.lock"
    start = time.time()
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > timeout:
                    path.unlink()
                    continue
            except OSError:
                pass
            if time.time() - start > timeout:
                break   # nie blokujemy synchronizacji w nieskończoność
            time.sleep(0.05)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            path.unlink()


def merge_cache(src, dst):
    """Dopisuje do dst wpisy z src, których dst nie ma albo ma starsze (eps_cache.json: {T: wpis}, estimates.json: {stocks: {T: wpis}})."""
    src, dst = Path(src), Path(dst)
    if src.resolve() == dst.resolve():
        return
    with cache_lock(dst if dst.exists() else src):
        _merge_cache(src, dst)


def _merge_cache(src, dst):
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
