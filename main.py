"""Momentum Desktop — uruchomienie: python main.py  (--selftest: sprawdza, czy biblioteki się ładują)."""
import sys

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import lxml  # noqa: F401
        import yfinance  # noqa: F401

        from desktop import app  # noqa: F401
        print("selftest ok")
    else:
        from desktop.app import main

        main()
