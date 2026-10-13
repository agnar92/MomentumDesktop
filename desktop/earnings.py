"""Data najbliższych wyników z Finviz ('Oct 22/a' = 22 października przed otwarciem / po zamknięciu) — port earningsInDays z Momentum."""
import re
from datetime import date

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SOON_DAYS = 7


def days_until(text, today=None):
    """Liczba dni do raportu (ujemna = już był w ostatnich 30 dniach); None, gdy nie umiemy odczytać daty."""
    m = re.match(r"^([A-Z][a-z]{2}) (\d{1,2})", text or "")
    if not m or m.group(1) not in MONTHS:
        return None
    today = today or date.today()
    month, day = MONTHS.index(m.group(1)) + 1, int(m.group(2))
    try:
        t = date(today.year, month, day)
        if (t - today).days < -30:
            t = date(today.year + 1, month, day)
    except ValueError:
        return None
    return (t - today).days


def label(days):
    """Tekst do kolumny: ⚠ przy raporcie w ciągu tygodnia."""
    if days is None or days < 0:
        return ""
    return f"⚠ {days} dn." if days <= SOON_DAYS else f"{days} dn."
