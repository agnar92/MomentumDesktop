"""yfinance dla CEM10: dostęp do biblioteki i ostatni zamknięty miesiąc (miesięczne świece pobiera desktop/cem10.py)."""
import datetime as dt


def _yf():
    import yfinance as yf
    return yf


def last_closed_month(today=None):
    today = today or dt.date.today()
    first = today.replace(day=1)
    return (first - dt.timedelta(days=1)).strftime("%Y-%m")
