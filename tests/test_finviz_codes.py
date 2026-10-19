import json
from pathlib import Path

from desktop import finviz_codes as fc

SEED = json.loads((Path(__file__).resolve().parent.parent / "seed_data" / "finviz_screen.json").read_text(encoding="utf-8"))["filters"]


def test_all_seed_filters_are_known():
    items = fc.describe(SEED)
    assert len(items) == 8 and all(known for _, _, known in items)
    texts = [t for _, t, _ in items]
    assert "Kapitalizacja ≥ 300 mln USD (small i większe)" in texts and "Cena powyżej SMA 200" in texts and "Wzrost EPS TTM r/r: wysoki (> 25 %)" in texts


def test_pattern_decoding_and_unknown():
    assert fc.describe_code("sh_avgvol_o500") == ("Średni wolumen > 500 tys. akcji", True)
    assert fc.describe_code("fa_roe_o15") == ("ROE > 15 %", True)
    assert fc.describe_code("fa_epsqoq_o25") == ("Wzrost EPS kwartał do kwartału > 25 %", True)
    assert fc.describe_code("ta_sma50_pb")[0] == "Cena poniżej SMA 50"
    text, known = fc.describe_code("xx_literowka")   # poprawnie zbudowany, ale nieopisany kod: przekazujemy do Finviz bez ostrzeżenia
    assert known and "bez zmian" in text
    text, known = fc.describe_code("literowka")      # nie wygląda na kod Finviz — ostrzegamy
    assert not known and "nie wygląda" in text


def test_summary_lines():
    lines = fc.summary_lines("geo_usa,zlykod", 300)
    assert lines[0] == "Kryteria Finviz (2 filtrów, max 300 spółek):" and "⚠" in lines[2] and lines[1].endswith("[geo_usa]")


def test_every_catalog_code_is_described_as_known():
    from desktop import finviz_catalog as cat
    for _tab, label, opts in cat.FILTERS:
        for text, code in opts:
            desc, known = fc.describe_code(code)
            assert known and desc, code
    assert fc.describe_code("fa_div_pos") == ("Dywidenda: Dodatnia", True)


def test_pasted_filters_with_colons_and_spaces_are_normalized_and_not_flagged():
    from desktop import finviz_catalog as fc
    from desktop import finviz_codes as codes
    assert fc.normalize_codes("sh_price:o1 ta_alltime:nh") == "sh_price_o1,ta_alltime_nh"
    assert fc.normalize_codes("a_b:c, d_e;f_g\nsh_price_o1,sh_price:o1") == "a_b_c,d_e,f_g,sh_price_o1"
    assert fc.parse_finviz_input("sh_price:o1 ta_alltime:nh") == "sh_price_o1,ta_alltime_nh"
    assert fc.parse_finviz_input("https://finviz.com/screener.ashx?v=111&f=sh_price_o1,ta_alltime_nh&ft=4") == "sh_price_o1,ta_alltime_nh"
    items = codes.describe("sh_price:o1 ta_alltime:nh zzz_unknown_9")
    assert [c for c, _t, _k in items] == ["sh_price_o1", "ta_alltime_nh", "zzz_unknown_9"]
    assert all(k for _c, _t, k in items)   # poprawnie zbudowany, nieopisany kod jest przekazywany bez ostrzeżenia
    assert not codes.describe_code("hello")[1]   # coś, co nie wygląda na kod Finviz, nadal ostrzega


NEW_LAYOUT = """<html><body><p class="fv-table_toolbar-count">#1 / 2 Total</p><div class="fv-table">
<div class="fv-table_row" data-row-key="AA"><div data-column-id="row">1</div>
 <div data-column-id="ticker" data-ticker="AA"><a><span>A</span><span>AA</span></a></div>
 <div data-column-id="company">Alcoa Corp</div><div data-column-id="sector">Basic Materials</div><div data-column-id="industry">Aluminum</div>
 <div data-column-id="marketCap">12.5B</div><div data-column-id="PE">8.1</div><div data-column-id="price">48.2</div></div>
<div class="fv-table_row" data-row-key="BB"><div data-column-id="row">2</div><div data-column-id="ticker" data-ticker="BB"><a><span>B</span><span>BB</span></a></div>
 <div data-column-id="company">Beta Inc</div><div data-column-id="sector">Technology</div><div data-column-id="industry">Software</div>
 <div data-column-id="marketCap">900.5M</div><div data-column-id="PE">-</div></div></div></body></html>"""


def test_parse_new_finviz_layout_uses_row_key_and_column_ids():
    from engine import finviz
    rows, total = finviz.parse_screener_page(NEW_LAYOUT, "111")
    assert total == 2
    assert rows[0] == {"ticker": "AA", "company": "Alcoa Corp", "sector": "Basic Materials", "industry": "Aluminum", "market_cap": 12.5e9, "pe": 8.1}
    assert rows[1]["ticker"] == "BB" and rows[1]["pe"] is None and rows[1]["market_cap"] == 900.5e6
    # inne widoki: mapowanie po id kolumny
    fin = '<div class="fv-table_row" data-row-key="AA"><div data-column-id="roe">20.97%</div><div data-column-id="earningsDate">Aug 26/a</div></div>'
    assert finviz.parse_screener_page(fin, "161")[0] == [{"ticker": "AA", "roe": 20.97, "earnings": "Aug 26/a"}]
