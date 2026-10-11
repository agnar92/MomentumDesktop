"""Momentum Desktop — uruchomienie: python main.py  (--selftest: sprawdza tylko, czy silnik Finviz / yfinance się ładuje)"""
import sys

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        from desktop import sync

        sync._engine_path()
        import finviz  # noqa: F401
        import watchlist  # noqa: F401
        import yfinance  # noqa: F401

        print("selftest ok")
    else:
        from desktop.app import main

        main()
