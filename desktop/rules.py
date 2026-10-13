"""Reguły kolorów listy: „kolumna operator wartość -> kolor” (np. RS ≥ 90 na zielono). Kolorujemy tekst całego wiersza (Treeview nie koloruje pojedynczych komórek);
pierwsza pasująca reguła wygrywa i przesłania kolor stanu Darvasa."""
COLORS = {"zielony": "#3ddc84", "czerwony": "#ff5c5c", "żółty": "#ffd166", "niebieski": "#6ea8ff", "pomarańczowy": "#ff9f43", "fioletowy": "#c58bff", "szary": "#7d8590"}
OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, "<": lambda a, b: a < b, "=": lambda a, b: a == b}


def match(row, rule):
    """Czy wiersz spełnia regułę (brak wartości = nie)."""
    v = row.get(rule.get("col"))
    if isinstance(v, bool):
        v = 1 if v else 0
    if not isinstance(v, (int, float)):
        return False
    try:
        return bool(OPS[rule["op"]](v, float(rule["value"])))
    except (KeyError, ValueError, TypeError):
        return False


def rule_tag(rules, row):
    """Nazwa koloru pierwszej pasującej reguły albo None."""
    for r in rules or []:
        if match(row, r) and r.get("color") in COLORS:
            return r["color"]
    return None
