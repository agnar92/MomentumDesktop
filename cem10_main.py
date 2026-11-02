"""CEM10 — osobny program (portfel z raportu XTB, plan wpłat, krzywa kapitału, lista miesięczna USA / GPW, wykres miesięczny).
Interfejs: lokalna strona w oknie programu (pywebview / WebView2), a bez niego w domyślnej przeglądarce (desktop/cem10_web.py).
Uruchomienie: python cem10_main.py  (--selftest: sprawdza, czy biblioteki i strona są w paczce; --browser: zawsze w przeglądarce). Dane: folder data/ obok programu."""
import sys


def main(base=None, window=True):
    from desktop import cem10_web
    from desktop.store import Store
    cem10_web.run(Store(base), window=window)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import lxml  # noqa: F401
        import openpyxl  # noqa: F401
        import yfinance  # noqa: F401

        from desktop import cem10_web
        assert (cem10_web.static_dir() / "index.html").is_file(), "brak strony desktop/cem10_web w paczce"
        if sys.platform == "win32":
            import webview  # noqa: F401
        print("selftest ok")
    else:
        main(window="--browser" not in sys.argv)
