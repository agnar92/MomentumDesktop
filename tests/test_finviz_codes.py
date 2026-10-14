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
