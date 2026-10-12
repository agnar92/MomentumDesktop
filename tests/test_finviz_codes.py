import json
from pathlib import Path

from desktop import finviz_codes as fc

SEED = json.loads((Path(__file__).resolve().parent.parent / "seed_data" / "finviz_screen.json").read_text(encoding="utf-8"))["filters"]


def test_all_seed_filters_are_known():
    items = fc.describe(SEED)
    assert len(items) == 10 and all(known for _, _, known in items)
    texts = [t for _, t, _ in items]
    assert "Kapitalizacja ≥ 300 mln USD (small i większe)" in texts and "Cena powyżej SMA 200" in texts and "Kraj: USA" in texts


def test_pattern_decoding_and_unknown():
    assert fc.describe_code("sh_avgvol_o500") == ("Średni wolumen > 500 tys. akcji", True)
    assert fc.describe_code("fa_roe_o15") == ("ROE > 15 %", True)
    assert fc.describe_code("fa_epsqoq_o25") == ("Wzrost EPS kwartał do kwartału > 25 %", True)
    assert fc.describe_code("ta_sma50_pb")[0] == "Cena poniżej SMA 50"
    text, known = fc.describe_code("xx_literowka")
    assert not known and "nieznany kod" in text


def test_summary_lines():
    lines = fc.summary_lines("geo_usa,zly_kod", 300)
    assert lines[0] == "Kryteria Finviz (2 filtrów, max 300 spółek):" and "⚠" in lines[2] and lines[1].endswith("[geo_usa]")


def test_every_catalog_code_is_described_as_known():
    from desktop import finviz_catalog as cat
    for _tab, label, opts in cat.FILTERS:
        for text, code in opts:
            desc, known = fc.describe_code(code)
            assert known and desc, code
    assert fc.describe_code("fa_div_pos") == ("Dywidenda: Dodatnia", True)
