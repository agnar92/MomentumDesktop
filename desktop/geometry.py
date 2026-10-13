"""Zapamiętywanie położenia i rozmiaru okien (data/session.json): odczyt z walidacją, żeby okno nie wylądowało poza ekranem."""
import re

_RE = re.compile(r"^(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)$")


def sanitize(geom, screen_w, screen_h, min_visible=80):
    """'1200x700+50+40' -> ten sam tekst, jeśli okno choć trochę mieści się na ekranie; w przeciwnym razie sam rozmiar bez położenia; zły format -> None."""
    m = _RE.match(geom or "")
    if not m:
        return None
    w, h = int(m[1]), int(m[2])
    x, y = int(m[3].replace("+", "")), int(m[4].replace("+", ""))
    w, h = min(w, screen_w), min(h, screen_h)
    if w < 100 or h < 80:
        return None
    if x + w < min_visible or x > screen_w - min_visible or y < -20 or y > screen_h - min_visible:
        return f"{w}x{h}"
    return f"{w}x{h}+{x}+{y}"
