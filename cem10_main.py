"""CEM10 — osobny program (portfel z raportu XTB, plan wpłat, krzywa kapitału, lista miesięczna USA / GPW, wykres miesięczny).
Uruchomienie: python cem10_main.py  (--selftest: sprawdza, czy biblioteki się ładują). Dane: folder data/ obok programu."""
import sys


class Host:
    """To, czego okno CEM10 potrzebuje od programu: główne okno Tk i magazyn danych (data/)."""

    def __init__(self, base=None):
        import tkinter as tk

        from desktop.store import Store
        from desktop.theme import apply_dark, setup_style
        self.root = tk.Tk()
        setup_style(self.root)
        apply_dark(self.root)
        self.root.withdraw()
        self.store = Store(base)


def main(base=None):
    from desktop.cem10_ui import CEM10Dialog
    host = Host(base)
    d = CEM10Dialog(host)
    d.title("CEM10 — portfel i lista miesięczna")
    d.bind("<Destroy>", lambda e: host.root.destroy() if e.widget is d else None)   # zamknięcie okna = koniec programu
    host.root.mainloop()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import lxml  # noqa: F401
        import openpyxl  # noqa: F401
        import yfinance  # noqa: F401

        from desktop import cem10_ui  # noqa: F401
        print("selftest ok")
    else:
        main()
