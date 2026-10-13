"""Synchronizacja (Finviz + yfinance) w dwóch trybach — jak w Momentum silnik liczy wszystko, ale tu można go odpalić szybciej:

- **ceny** (szybko, np. codziennie): lista z Finviz (razem z jej kolumnami) + ceny z yfinance + przeliczenie wszystkiego, co zależy od ceny
  (RS, bazy, Darvas, CANSLIM, wykresy tygodniowe i dzienne). EPS z Yahoo i estymaty analityków NIE są pobierane — bierzemy zapisane
  (data/eps_cache.json, estimates.json).
- **fundamenty** (raz w tygodniu): pełny przebieg silnika, w tym odświeżenie EPS z Yahoo i estymat analityków.

Silnik (engine/watchlist.py) jest niezmieniony; tryb „ceny” podmienia tylko dwa kroki sieciowe na odczyt zapisanych plików."""
import contextlib
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import daily, finviz_catalog, qm, scanners, store

PRICES, FUNDAMENTALS = "prices", "fundamentals"
FUNDAMENTALS_STALE_DAYS = 7


def _engine_path():
    p = str(store.resource_dir() / "engine")
    if p not in sys.path:
        sys.path.insert(0, p)


class _LogWriter:
    def __init__(self, log):
        self.log, self.buf = log, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.log(line)
        return len(s)

    def flush(self):
        if self.buf.strip():
            self.log(self.buf.strip())
        self.buf = ""


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_state(data_dir):
    """{prices: iso, fundamentals: iso}; bez pliku stanu — z daty wygenerowania danych (np. dane startowe)."""
    st = store.read_json(data_dir / "sync_state.json", {}) or {}
    if not st:
        gen = (store.read_json(data_dir / "watchlist.json", {}) or {}).get("generated_at")
        st = {"prices": gen, "fundamentals": gen}
    return st


def age_days(iso, now=None):
    if not iso:
        return None
    try:
        t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return ((now or datetime.now(timezone.utc)) - t).total_seconds() / 86400


FREE_LIMIT = 1000   # darmowy screener Finviz nie oddaje wierszy powyżej 1000 (r=1001 -> 403), więc większe zbiory dzielimy po sektorach
SECTORS = ("technology", "healthcare", "financial", "industrials", "consumercyclical", "communicationservices", "consumerdefensive",
           "energy", "basicmaterials", "realestate", "utilities")


def fetch_sliced(finviz, filters, max_tickers, log=print):
    """Lista z widoku Overview (111) bez limitu 1000 wierszy: gdy wyników jest więcej, pobiera osobno każdy sektor i skleja bez duplikatów.
    -> (wiersze, razem)."""
    _, total = finviz.fetch_view("111", filters, PAGE_PROBE)
    if total is None or total <= FREE_LIMIT or "sec_" in filters:
        rows, total2 = finviz.fetch_view("111", filters, min(max_tickers, FREE_LIMIT))
        if total2 and total2 > FREE_LIMIT:
            log(f"⚠️  Finviz ma {total2} wyników, a darmowy screener oddaje tylko {FREE_LIMIT} — zawęź filtry.")
        return rows, total2
    log(f"Finviz: {total} wyników (limit darmowego screenera to {FREE_LIMIT}) — pobieram sektor po sektorze…")
    out, seen = [], set()
    for sec in SECTORS:
        part, tot = finviz.fetch_view("111", f"{filters},sec_{sec}", FREE_LIMIT)
        if tot and tot > FREE_LIMIT:
            log(f"⚠️  Sektor {sec}: {tot} wyników > {FREE_LIMIT} — pobieram tylko pierwsze {FREE_LIMIT}; zawęź filtry.")
        for r in part:
            if r["ticker"] not in seen:
                seen.add(r["ticker"])
                out.append(r)
        log(f"  {sec}: {len(part)} (razem {len(out)})")
    return out[:max_tickers], len(out)


PAGE_PROBE = 20


def prune_to(data_dir, tickers, log=print):
    """Zostawia w watchlist.json / charts.json tylko podane tickery (zbiór pobrany z Finviz bywa wielokrotnie większy niż to, co zapisujemy)."""
    keep = set(tickers)
    wl = store.read_json(data_dir / "watchlist.json", {}) or {}
    before = len(wl.get("stocks", []))
    wl["stocks"] = [s for s in wl.get("stocks", []) if s["ticker"] in keep]
    wl["qm_universe"], wl["n_stocks"] = before, len(wl["stocks"])
    store.write_json(data_dir / "watchlist.json", wl)
    ch = store.read_json(data_dir / "charts.json", {}) or {}
    ch["stocks"] = {t: v for t, v in (ch.get("stocks") or {}).items() if t in keep}
    store.write_json(data_dir / "charts.json", ch)
    log(f"Zapisuję {len(wl['stocks'])} z {before} pobranych spółek (obrót i ADR powyżej progów pobierania).")


def build_daily_json(data_dir, log, only=None):
    """Dzienne wykresy z migawki cen zapisanej przez silnik (bez ostatniej, jeszcze trwającej sesji)."""
    import pandas as pd
    import watchlist
    raw = watchlist.load_raw(watchlist.RAW_PROFILE, data_dir / "raw")
    if raw is None:
        log("⚠️  Brak migawki cen — pomijam wykresy dzienne.")
        return
    now = pd.Timestamp(raw["fetched_at"])
    frames = {}
    for t, df in raw["frames"].items():
        if only is not None and t not in only:
            continue
        try:
            frames[t] = watchlist.drop_incomplete_bar(df, now)
        except Exception:
            frames[t] = df
    bench = raw.get("benchmark")
    if bench is not None and len(bench):
        bench = watchlist.drop_incomplete_bar(bench, now)
    store.write_json(data_dir / "charts_daily.json", daily.build_daily(frames, bench))
    log(f"💾 Zapisano charts_daily.json (wykresy dzienne {len(frames)} spółek).")


def sanitize_frames(frames, log=print):
    """Usuwa z notowań świece z zerową / ujemną / brakującą ceną (Yahoo zdarza się oddać Low = 0) — jedna taka świeca wywala silnik dzieleniem przez zero."""
    cols = ["Open", "High", "Low", "Close"]
    out, bad = {}, 0
    for t, df in frames.items():
        try:
            ok = (df[cols] > 0).all(axis=1)
            if not ok.all():
                bad += 1
                df = df[ok]
        except Exception:
            pass
        out[t] = df
    if bad:
        log(f"ℹ️  Usunięto błędne świece (cena ≤ 0) w {bad} spółkach.")
    return out


def safe_metrics(compute, log=print):
    """Opakowanie compute_metrics: błąd jednej spółki ją pomija, a nie przerywa całej synchronizacji."""
    def wrapped(df, *a, **k):
        try:
            return compute(df, *a, **k)
        except Exception as e:
            log(f"⚠️  Pominięto spółkę (błąd obliczeń: {type(e).__name__}: {e}).")
            return None
    return wrapped


def fetch_extra(finviz, filters, max_tickers, keys):
    """Dodatkowe kolumny Finviz (spoza tych, które bierze silnik): ten sam skaner, widok własny z zamówionymi kolumnami -> {ticker: {pole: wartość}}."""
    keys = [k for k in keys if k in finviz_catalog.EXTRA_COLUMNS]
    if not keys:
        return {}
    saved = (finviz.VIEW_COLUMNS.get("152"), finviz.VIEW_PARAMS.get("152"), set(finviz.TEXT_KEYS))
    finviz.VIEW_COLUMNS["152"] = {finviz_catalog.EXTRA_COLUMNS[k][3]: k for k in keys}
    finviz.VIEW_PARAMS["152"] = {"c": ",".join(str(i) for i in finviz_catalog.extra_ids(keys))}
    finviz.TEXT_KEYS.update(finviz_catalog.TEXT_FIELDS)
    try:
        rows, _ = finviz.fetch_view("152", filters, max_tickers)
    finally:
        finviz.VIEW_COLUMNS["152"], finviz.VIEW_PARAMS["152"] = saved[0], saved[1]
        finviz.TEXT_KEYS.clear()
        finviz.TEXT_KEYS.update(saved[2])
    return {r["ticker"]: {k: v for k, v in r.items() if k != "ticker"} for r in rows}


def run_sync(data_dir, log=print, mode=FUNDAMENTALS, skip_finviz=False, max_tickers=None, extra_keys=(), shared_root=None):
    """Zwraca 0 przy sukcesie. Pliki trafiają do data_dir; migawka surowych danych do data_dir/raw."""
    _engine_path()
    try:
        import finviz
        import watchlist
    except Exception as e:   # np. brak pakietu w buildzie
        log(f"❌ Nie można załadować silnika: {e}")
        return 1
    if shared_root is not None:   # wspólny cache EPS / estymat: nie pobieramy drugi raz tego, co zna inny skaner
        scanners.merge_cache(shared_root, data_dir)
    qm_cfg = scanners.load_config(data_dir).get("qm")   # skaner Qullamaggie: tylko ceny (bez fundamentów), lista z Overview dzielona po sektorach
    if qm_cfg:
        mode = PRICES
    prev_state = read_state(data_dir)   # przed uruchomieniem: bez pliku stanu daty biorą się z generated_at, które silnik zaraz nadpisze
    cfg_path = data_dir / "finviz_screen.json"
    orig_load = getattr(finviz, "_orig_load_config", None) or finviz.load_config
    finviz._orig_load_config = orig_load
    finviz.load_config = lambda *a, **k: orig_load(cfg_path)   # filtry z pliku użytkownika, nie z repozytorium
    orig_eps = getattr(watchlist, "_orig_update_eps_cache", None) or watchlist.update_eps_cache
    orig_est = getattr(watchlist, "_orig_update_estimates", None) or watchlist.update_estimates
    watchlist._orig_update_eps_cache, watchlist._orig_update_estimates = orig_eps, orig_est
    if mode == PRICES:   # bez sieci Yahoo dla EPS i estymat: czytamy to, co zapisał ostatni sync fundamentów
        watchlist.update_eps_cache = lambda tickers, cache_path=None, **k: store.read_json(cache_path, {}) or {}
        watchlist.update_estimates = lambda tickers, path=None, **k: (store.read_json(path, {}) or {}).get("stocks", {})
    else:
        watchlist.update_eps_cache, watchlist.update_estimates = orig_eps, orig_est
    orig_dl = getattr(watchlist, "_orig_download_prices", None) or getattr(watchlist, "download_prices", None)
    orig_cm = getattr(watchlist, "_orig_compute_metrics", None) or getattr(watchlist, "compute_metrics", None)
    watchlist._orig_download_prices, watchlist._orig_compute_metrics = orig_dl, orig_cm
    if orig_dl is not None:
        watchlist.download_prices = lambda *a, **k: sanitize_frames(orig_dl(*a, **k), log)
    if orig_cm is not None:
        watchlist.compute_metrics = safe_metrics(orig_cm, log)
    orig_fw = getattr(finviz, "_orig_fetch_watchlist", None) or getattr(finviz, "fetch_watchlist", None)
    finviz._orig_fetch_watchlist = orig_fw
    if qm_cfg and not skip_finviz:
        finviz.fetch_watchlist = lambda filters, max_t=300, *a, **k: fetch_sliced(finviz, filters, max_t, log)
    elif extra_keys and not skip_finviz and orig_fw is not None:
        def fetch_with_extra(filters, max_t=300, *a, **k):
            rows, total = orig_fw(filters, max_t, *a, **k)
            try:
                extra = fetch_extra(finviz, filters, max_t, extra_keys)
                store.write_json(data_dir / "finviz_extra.json", extra)
                log(f"✅ Finviz: dodatkowe kolumny ({len(extra_keys)}) dla {len(extra)} spółek.")
            except Exception as e:
                log(f"⚠️  Dodatkowe kolumny Finviz niedostępne ({e}) — zostają poprzednie.")
            return rows, total
        finviz.fetch_watchlist = fetch_with_extra
    elif orig_fw is not None:
        finviz.fetch_watchlist = orig_fw
    out = _LogWriter(log)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = watchlist.run(data_dir / "watchlist.json", skip_finviz=skip_finviz, max_tickers=max_tickers,
                                 stage="all", raw_dir=data_dir / "raw", save_snapshot=True)
            out.flush()
            if not code:
                if qm_cfg:
                    wl = store.read_json(data_dir / "watchlist.json", {}) or {}
                    kept = {r["ticker"] for r in qm.keep(wl.get("stocks", []), qm_cfg)}
                    prune_to(data_dir, kept, log)
                    build_daily_json(data_dir, log, only=kept)
                    shutil.rmtree(data_dir / "raw", ignore_errors=True)   # migawka całego zbioru jest duża, a desktop jej nie potrzebuje
                else:
                    build_daily_json(data_dir, log)
        if not code:
            st = prev_state
            st["prices"] = now_iso()
            if mode == FUNDAMENTALS:
                st["fundamentals"] = st["prices"]
            store.write_json(data_dir / "sync_state.json", st)
        return code or 0
    except Exception:
        log("❌ Błąd synchronizacji:\n" + traceback.format_exc())
        return 1
    finally:
        watchlist.update_eps_cache, watchlist.update_estimates = orig_eps, orig_est
        if orig_dl is not None:
            watchlist.download_prices = orig_dl
        if orig_cm is not None:
            watchlist.compute_metrics = orig_cm
        if orig_fw is not None:
            finviz.fetch_watchlist = orig_fw
        if shared_root is not None:
            scanners.merge_cache(data_dir, shared_root)


# ---------- synchronizacja w osobnym procesie (równoległe skanery) ----------
# Sync podmienia ustawienia silnika w całym procesie (filtry, kroki EPS, przekierowanie wyjścia), więc dwa naraz w jednym procesie
# by się mieszały. Każdy skaner synchronizuje się w osobnym procesie tego samego programu (main.py --sync …), a okno czyta jego dziennik.

def worker_command(data_dir, mode, skip_finviz=False, extra_keys=(), shared_root=None):
    base = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(store.app_dir() / "main.py")]
    cmd = base + ["--sync", str(data_dir), "--mode", mode]
    if skip_finviz:
        cmd.append("--skip-finviz")
    if extra_keys:
        cmd += ["--extra", ",".join(extra_keys)]
    if shared_root is not None:
        cmd += ["--shared", str(shared_root)]
    return cmd


def parse_worker_args(argv):
    import argparse
    p = argparse.ArgumentParser(prog="main.py --sync")
    p.add_argument("data_dir")
    p.add_argument("--mode", choices=[PRICES, FUNDAMENTALS], default=PRICES)
    p.add_argument("--skip-finviz", action="store_true")
    p.add_argument("--extra", default="")
    p.add_argument("--shared", default=None)
    ns = p.parse_args(argv)
    ns.extra = [k for k in ns.extra.split(",") if k]
    return ns


def worker_main(argv):
    """Punkt wejścia procesu pomocniczego: dziennik idzie linia po linii na stdout, kod wyjścia = wynik synchronizacji."""
    ns = parse_worker_args(argv)
    out = sys.__stdout__
    try:
        out.reconfigure(encoding="utf-8")
    except Exception:
        pass

    def emit(line):
        out.write(line + "\n")
        out.flush()

    return run_sync(Path(ns.data_dir), log=emit, mode=ns.mode, skip_finviz=ns.skip_finviz, extra_keys=ns.extra,
                    shared_root=Path(ns.shared) if ns.shared else None)


def run_in_subprocess(data_dir, log, mode=FUNDAMENTALS, skip_finviz=False, extra_keys=(), shared_root=None, popen=None):
    """Uruchamia synchronizację w osobnym procesie, przekazuje jego dziennik do `log`, zwraca kod wyjścia (0 = sukces)."""
    import os
    import subprocess
    popen = popen or subprocess.Popen
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    kw = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}   # CREATE_NO_WINDOW: bez migającej konsoli
    try:
        p = popen(worker_command(data_dir, mode, skip_finviz, extra_keys, shared_root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                  text=True, encoding="utf-8", errors="replace", env=env, **kw)
    except OSError as e:
        log(f"❌ Nie można uruchomić procesu synchronizacji: {e}")
        return 1
    for line in p.stdout:
        line = line.rstrip("\n")
        if line.strip():
            log(line)
    return p.wait()
