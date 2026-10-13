"""Scalanie skanerów w jedną listę: suma spółek z wybranych skanerów (bez duplikatów), z wykresami i danymi z tych skanerów.
Nic nie jest pobierane z sieci — scalony skaner składa swoje pliki z danych źródeł (przycisk Sync = odśwież scalenie).
Źródło typu Qullamaggie wnosi tylko spółki wybrane jego progami (to, co widać na jego liście), a nie cały zapisany zbiór."""
from pathlib import Path

from . import qm, scanners, store, sync


def _remap(val, src_axis, ref_axis):
    """Tablice wyrównane do osi źródła (długość = liczba punktów osi) przeliczone na oś wzorcową po datach; reszta bez zmian."""
    pos = {d: i for i, d in enumerate(src_axis)}
    idx = [pos.get(d) for d in ref_axis]
    n = len(src_axis)

    def conv(x):
        if isinstance(x, list) and len(x) == n:
            return [None if i is None else x[i] for i in idx]
        if isinstance(x, dict):
            return {k: conv(v) for k, v in x.items()}
        return x
    return conv(val)


def _pick_stocks(root, sc):
    """([(raw stock, windows|None)], watchlist, charts, charts_d) jednego źródła — tylko spółki, które to źródło faktycznie pokazuje."""
    d = scanners.scanner_dir(root, sc["id"])
    wl = store.read_json(d / "watchlist.json", {}) or {}
    stocks = wl.get("stocks", [])
    picks = None
    if sc.get("kind") == scanners.KIND_QM:
        cfg = scanners.load_config(d).get("qm")
        picks = qm.select(stocks, cfg)
        stocks = [s for s in stocks if s["ticker"] in picks]
    return [(s, picks.get(s["ticker"]) if picks else None) for s in stocks], wl, store.read_json(d / "charts.json", {}) or {}, store.read_json(d / "charts_daily.json", {}) or {}


def build(root, scanner, log=print):
    """Składa watchlist.json / charts.json / charts_daily.json scalonego skanera z jego źródeł. Zwraca liczbę spółek."""
    root = Path(root)
    out_dir = scanners.scanner_dir(root, scanner["id"])
    out_dir.mkdir(parents=True, exist_ok=True)
    srcs = [s for s in (scanners.get(root, sid) for sid in scanner.get("sources") or []) if s and s["id"] != scanner["id"] and s.get("kind") != scanners.KIND_MERGE]
    parts = [(s, *_pick_stocks(root, s)) for s in srcs]
    parts = [p for p in parts if p[1]]
    if not parts:
        log("⚠️  Brak spółek w źródłach (zrób najpierw Sync skanerów, które scalasz).")
        store.write_json(out_dir / "watchlist.json", {"generated_at": sync.now_iso(), "n_stocks": 0, "stocks": []})
        return 0
    merged, names = {}, {}
    for sc, items, _wl, _c, _cd in parts:
        for stock, windows in items:
            t = stock["ticker"]
            names.setdefault(t, []).append(sc["name"])
            if t not in merged:
                merged[t] = dict(stock)
            if windows:   # okna Qullamaggie z tego źródła (jeśli spółka wpadła w kilku źródłach, sumujemy okna)
                have = set(merged[t].get("_qm_w") or [])
                merged[t]["_qm_w"] = sorted(have | set(windows), key=list(qm.WINDOWS).index)
    for t, st in merged.items():
        if st.get("_qm_w"):
            qm.annotate(st, st.pop("_qm_w"))
        st["merge_src"] = ", ".join(names[t])
    ref = max(parts, key=lambda p: ((p[2].get("data_as_of") or ""), p[2].get("generated_at") or ""))
    meta = {k: v for k, v in ref[2].items() if k != "stocks"}
    meta.update(generated_at=sync.now_iso(), n_stocks=len(merged), finviz_total=len(merged), finviz_stale=False, merged_from=[p[0]["id"] for p in parts])
    store.write_json(out_dir / "watchlist.json", {**meta, "stocks": list(merged.values())})

    def combine(key, axis_key):
        ref_p = max((p for p in parts if p[3 if key == "charts" else 4].get(axis_key)), key=lambda p: (p[3 if key == "charts" else 4][axis_key] or [""])[-1], default=None)
        if ref_p is None:
            return None
        pos = 3 if key == "charts" else 4
        ref_doc = ref_p[pos]
        axis = ref_doc[axis_key]
        stocks = {}
        for p in parts:
            doc = p[pos]
            src_axis = doc.get(axis_key) or []
            for stock, _ in p[1]:
                t = stock["ticker"]
                if t in stocks or t not in (doc.get("stocks") or {}):
                    continue
                entry = doc["stocks"][t]
                stocks[t] = entry if src_axis == axis else _remap(entry, src_axis, axis)
        return {**{k: v for k, v in ref_doc.items() if k != "stocks"}, "stocks": stocks}

    for key, axis_key, fname in (("charts", "weeks", "charts.json"), ("daily", "dates", "charts_daily.json")):
        doc = combine(key, axis_key)
        if doc is not None:
            store.write_json(out_dir / fname, doc)
    st = sync.read_state(out_dir) if (out_dir / "sync_state.json").exists() else {}
    st["prices"] = st["fundamentals"] = sync.now_iso()
    store.write_json(out_dir / "sync_state.json", st)
    log(f"✅ Scalono {len(merged)} spółek z {len(parts)} skanerów: {', '.join(p[0]['name'] for p in parts)}.")
    return len(merged)
