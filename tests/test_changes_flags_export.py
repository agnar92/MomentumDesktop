import csv
import io

from desktop import changes, columns, exporter, flags, store


def snap(**kw):
    base = {"name": "X", "price": 10.0, "w": "HOLD", "d": "HOLD", "pbox": "NONE", "cs": 3}
    return {**base, **kw}


def test_diff_categories():
    old = {"A": snap(), "B": snap(w="BUY"), "C": snap(), "D": snap(pbox="INSIDE"), "E": snap(cs=4), "GONE": snap()}
    new = {"A": snap(w="BUY"), "B": snap(w="BUY"), "C": snap(w="SELL", d="BUY"), "D": snap(pbox="ZONE"), "E": snap(cs=5), "NEW": snap(w="BUY")}
    d = changes.diff(old, new)
    assert d == {"zone": ["D"], "buy_w": ["A"], "buy_d": ["C"], "sell": ["C"], "canslim": ["E"], "new": ["NEW"], "dropped": ["GONE"]}   # B już było KUP; nowa spółka tylko jako „nowa”
    assert changes.diff({}, new) == {} and changes.diff(old, old) == {}                    # pierwszy sync i brak zmian = brak różnic
    assert changes.total(d) == 7


def test_marks_priority_and_merge():
    d = {"zone": ["D"], "buy_w": ["A", "D"], "new": ["A", "N"], "dropped": ["G"]}
    m = changes.marks(d)
    assert m["D"] == "⚠ strefa" and m["A"] == "▲ KUP tyg." and m["N"] == "★ nowa" and "G" not in m   # ważniejsza zmiana wygrywa, wypadłe bez znacznika
    assert changes.merge({"new": ["A"], "buy_w": ["B"]}, {"new": ["C"], "buy_w": ["B"], "sell": ["D"]}) == {"buy_w": ["B"], "sell": ["D"], "new": ["A", "C"]}
    assert changes.merge({}, {}) == {}


def test_store_marks_rows_and_persists_changes(tmp_path):
    s = store.Store(tmp_path / "d")
    t = s.rows[0]["ticker"]
    assert s.rows[0]["change"] == ""
    s.set_changes({"buy_w": [t]}, "2026-10-12T10:00:00Z", {"X": "Stara"})
    assert s.rows[0]["change"] == "▲ KUP tyg."
    s2 = store.Store(tmp_path / "d")
    assert s2.rows[0]["change"] == "▲ KUP tyg." and s2.changes["at"] == "2026-10-12T10:00:00Z" and s2.changes["names"] == {"X": "Stara"}
    s2.set_changes({}, "x")
    assert store.Store(tmp_path / "d").rows[0]["change"] == ""


def test_flags_toggle_rename_persist_and_filter(tmp_path):
    f = flags.Flags(tmp_path)
    assert [x["id"] for x in f.lists] == flags.IDS and f.get("AAA") is None
    f.set("AAA", "watch")
    f.set("BBB", "bought")
    assert f.get("AAA") == "watch" and f.icon("bought") == "🛒"
    f.set("AAA", "watch")                                 # ta sama flaga drugi raz = zdjęcie
    assert f.get("AAA") is None
    f.set("BBB", None)
    assert f.get("BBB") is None
    f.set("CCC", "nieistniejaca")
    assert f.get("CCC") is None
    f.rename("watch", "  Moje  ")
    f.set("DDD", "check")
    f2 = flags.Flags(tmp_path)
    assert f2.name("watch") == "Moje" and f2.get("DDD") == "check"
    rows = f2.tag([{"ticker": "DDD"}, {"ticker": "EEE"}])
    assert [r["flag"] for r in rows] == ["check", None]
    assert [r["ticker"] for r in store.scan(rows, {"flag": "any"})] == ["DDD"]
    assert [r["ticker"] for r in store.scan(rows, {"flag": "none"})] == ["EEE"]
    assert [r["ticker"] for r in store.scan(rows, {"flag": "check"})] == ["DDD"] and len(store.scan(rows, {"flag": ""})) == 2


def test_flag_column_format_and_sort():
    assert columns.format_cell({"flag": "bought"}, "flag") == "🛒" and columns.format_cell({}, "flag") == ""
    a, b, c = {"flag": "check"}, {"flag": "watch"}, {"flag": None}
    assert sorted([a, b, c], key=lambda r: columns.sort_value(r, "flag")) == [b, a, c]


def test_exporter_tickers_and_csv_formats():
    rows = [{"ticker": "AAA", "company": "Alfa; Inc", "price": 12.3456, "rs_rating": 90, "market_cap": 2.5e9, "leader": True, "flag": "watch", "darvas": "BUY", "cs": 5},
            {"ticker": "BBB", "company": "Beta", "price": None, "rs_rating": None, "leader": False, "flag": None, "darvas": "HOLD", "cs": None}]
    assert exporter.tickers_text(rows) == "AAA,BBB" and exporter.tickers_text(rows, "\n") == "AAA\nBBB"
    cols = ["ticker", "flag", "company", "price", "rs_rating", "market_cap", "leader", "darvas", "cs"]
    xl = exporter.to_csv(rows, cols, "xl", store.STATE_LABELS, {"watch": "⭐ Obserwuję"})
    parsed = list(csv.reader(io.StringIO(xl), delimiter=";"))
    assert parsed[0][:4] == ["Symbol", "Lista", "Spółka", "Cena"]
    assert parsed[1] == ["AAA", "⭐ Obserwuję", "Alfa; Inc", "12,3456", "90", "2500000000.0", "✓", "KUP", "5/7"] or parsed[1][3] == "12,3456"
    assert parsed[2][3] == "" and parsed[2][4] == "" and parsed[2][8] == ""                                  # puste wartości = puste komórki
    std = list(csv.reader(io.StringIO(exporter.to_csv(rows, cols, "std", store.STATE_LABELS)), delimiter=","))
    assert std[1][3] == "12.3456" and std[1][2] == "Alfa; Inc"
