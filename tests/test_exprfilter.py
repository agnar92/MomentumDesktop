import pytest

from desktop import exprfilter as ef

ROWS = [
    {"ticker": "AAA", "price": 50.0, "adr_pct": 5.2, "low_ratio_3m": 1.8, "sector": "Technology", "glb_state": "BREAK", "rs_rating": 90},
    {"ticker": "BBB", "price": 150.0, "adr_pct": 3.1, "low_ratio_3m": 1.2, "sector": "Healthcare", "glb_state": "WAIT", "rs_rating": None},
    {"ticker": "CCC", "price": 20.0, "adr_pct": 4.0, "low_ratio_3m": None, "sector": "Technology", "glb_state": "NONE", "rs_rating": 40},
]
KEYS = ["ticker", "price", "adr_pct", "low_ratio_3m", "sector", "glb_state", "rs_rating"]


def run(text):
    return [r["ticker"] for r in ef.apply(ROWS, text, KEYS)]


def test_basic_operators_and_lines():
    assert run("adr_pct >= 4") == ["AAA", "CCC"]
    assert run("adr_pct > 4") == ["AAA"]
    assert run("price < 100") == ["AAA", "CCC"]
    assert run("price <= 50") == ["AAA", "CCC"]
    assert run("price == 150") == ["BBB"] and run("price = 150") == ["BBB"]
    assert run("adr_pct >= 4\nprice < 100\n# komentarz\n") == ["AAA", "CCC"]      # linie łączone „and”
    assert run("") == ["AAA", "BBB", "CCC"] and run("   \n# tylko komentarz") == ["AAA", "BBB", "CCC"]
    assert run("adr_pct >= 4,5") == ["AAA"] and run("adr_pct >= 12%") == []        # przecinek dziesiętny, znak %


def test_and_or_parentheses_and_labels():
    assert run("adr_pct >= 4 and price < 100") == ["AAA", "CCC"]
    assert run("price > 100 or rs_rating >= 90") == ["AAA", "BBB"]
    assert run("sector == Technology and (price > 30 or adr_pct > 3.9)") == ["AAA", "CCC"]
    assert run('"Cena/min 3M" > 1.5') == ["AAA"] and run('"low_ratio_3m" > 1.5') == ["AAA"]   # etykieta w cudzysłowie albo klucz
    assert run("adr_pct >= 4 i price < 100 lub ticker == BBB") == ["AAA", "BBB", "CCC"]


def test_text_empty_and_missing_values():
    assert run("glb_state == wybicie") == ["AAA"]                  # etykieta wyświetlana (WYBICIE) bez rozróżniania wielkości liter
    assert run("glb_state == BREAK") == ["AAA"] and run("glb_state != WAIT") == ["AAA", "CCC"]
    assert run('sector == "technology"') == ["AAA", "CCC"]
    assert run("rs_rating == brak") == ["BBB"] and run("rs_rating != brak") == ["AAA", "CCC"]
    assert run("low_ratio_3m > 1") == ["AAA", "BBB"]                # brak wartości nie spełnia porównania liczbowego
    assert run("low_ratio_3m != 1.8") == ["BBB", "CCC"]
    assert run("ticker > B") == ["BBB", "CCC"]                      # porównanie tekstów


def test_errors_are_readable():
    for bad, part in (("nieznana > 3", "nieznana kolumna"), ("adr_pct >=", "oczekiwałem wartości"), ("adr_pct 4", "oczekiwałem operatora"),
                      ("(adr_pct > 3", "brakuje"), ("adr_pct > 3 and", "oczekiwałem nazwy kolumny"), ("adr_pct > 3 $", "nieoczekiwane")):
        with pytest.raises(ef.ExprError) as e:
            ef.compile_filter(bad, KEYS)
        assert part in str(e.value) and "linia 1" in str(e.value), (bad, str(e.value))
    with pytest.raises(ef.ExprError) as e:
        ef.compile_filter("price > 1\nzle > 2", KEYS)
    assert "linia 2" in str(e.value)
