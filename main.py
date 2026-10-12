"""Momentum Desktop — uruchomienie: python main.py
  --selftest: sprawdza tylko, czy silnik Finviz / yfinance się ładuje; --sync <katalog> …: proces pomocniczy jednej synchronizacji (używany przez program)."""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sync":
        from desktop import sync

        sys.exit(sync.worker_main(sys.argv[2:]))
    elif "--selftest" in sys.argv:
        from desktop import sync

        sync._engine_path()
        import finviz  # noqa: F401
        import watchlist  # noqa: F401
        import yfinance  # noqa: F401

        print("selftest ok")
    else:
        from desktop.app import main

        main()
