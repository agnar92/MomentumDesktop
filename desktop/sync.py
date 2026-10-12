"""Synchronizacja (Finviz + yfinance) w dwóch trybach — jak w Momentum silnik liczy wszystko, ale tu można go odpalić szybciej:

- **ceny** (szybko, np. codziennie): lista z Finviz (razem z jej kolumnami) + ceny z yfinance + przeliczenie wszystkiego, co zależy od ceny
  (RS, bazy, Darvas, CANSLIM, wykresy tygodniowe i dzienne). EPS z Yahoo i estymaty analityków NIE są pobierane — bierzemy zapisane
  (data/eps_cache.json, estimates.json).
- **fundamenty** (raz w tygodniu): pełny przebieg silnika, w tym odświeżenie EPS z Yahoo i estymat analityków.

Silnik (engine/watchlist.py) jest niezmieniony; tryb „ceny” podmienia tylko dwa kroki sieciowe na odczyt zapisanych plików."""
import contextlib
import sys
import traceback
from datetime import datetime, timezone

from . import daily, store

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


def build_daily_json(data_dir, log):
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
        try:
            frames[t] = watchlist.drop_incomplete_bar(df, now)
        except Exception:
            frames[t] = df
    bench = raw.get("benchmark")
    if bench is not None and len(bench):
        bench = watchlist.drop_incomplete_bar(bench, now)
    store.write_json(data_dir / "charts_daily.json", daily.build_daily(frames, bench))
    log(f"💾 Zapisano charts_daily.json (wykresy dzienne {len(frames)} spółek).")


def run_sync(data_dir, log=print, mode=FUNDAMENTALS, skip_finviz=False, max_tickers=None):
    """Zwraca 0 przy sukcesie. Pliki trafiają do data_dir; migawka surowych danych do data_dir/raw."""
    _engine_path()
    try:
        import finviz
        import watchlist
    except Exception as e:   # np. brak pakietu w buildzie
        log(f"❌ Nie można załadować silnika: {e}")
        return 1
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
    out = _LogWriter(log)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = watchlist.run(data_dir / "watchlist.json", skip_finviz=skip_finviz, max_tickers=max_tickers,
                                 stage="all", raw_dir=data_dir / "raw", save_snapshot=True)
            out.flush()
            if not code:
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
