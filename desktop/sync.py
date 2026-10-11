"""Ręczna synchronizacja: Finviz (lista spółek) + yfinance (ceny, EPS, estymaty) -> data/*.json.
Cała logika liczenia (RS, EPS Rating, bazy, wykresy) to niezmieniony silnik z Momentum (engine/watchlist.py)."""
import contextlib
import sys
import traceback

from . import store


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


def run_sync(data_dir, log=print, skip_finviz=False, max_tickers=None):
    """Zwraca 0 przy sukcesie. Pliki trafiają do data_dir; migawka surowych danych do data_dir/raw."""
    _engine_path()
    try:
        import finviz
        import watchlist
    except Exception as e:   # np. brak pakietu w buildzie
        log(f"❌ Nie można załadować silnika: {e}")
        return 1
    cfg_path = data_dir / "finviz_screen.json"
    orig = getattr(finviz, "_orig_load_config", None) or finviz.load_config
    finviz._orig_load_config = orig
    finviz.load_config = lambda *a, **k: orig(cfg_path)   # filtry z pliku użytkownika, nie z repozytorium
    out = _LogWriter(log)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = watchlist.run(data_dir / "watchlist.json", skip_finviz=skip_finviz, max_tickers=max_tickers,
                                 stage="all", raw_dir=data_dir / "raw", save_snapshot=True)
        out.flush()
        return code or 0
    except Exception:
        log("❌ Błąd synchronizacji:\n" + traceback.format_exc())
        return 1
