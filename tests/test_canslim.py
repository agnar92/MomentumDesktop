"""CANSLIM: parytet z canslimInfo z Momentum (oczekiwane wartości policzone tamtym kodem na seed_data/watchlist.json)."""
import json
from pathlib import Path

from desktop import canslim

SEED = json.loads((Path(__file__).resolve().parent.parent / "seed_data" / "watchlist.json").read_text(encoding="utf-8"))
EXPECTED = {"PLTR": (5, "CANS-I-"), "ETON": (5, "CA-SLI-"), "NVDA": (4, "CAN--I-"), "SNOW": (3, "C-N--I-")}


def letters(c):
    return "".join(k if c["flags"][k] is True else "-" if c["flags"][k] is False else "?" for k in "CANSLIM")


def test_matches_js_on_seed_data():
    mkt = canslim.market(SEED)
    assert mkt["regime"] == "uptrend" and mkt["dist_days"] == 7   # >= 5 dni dystrybucji -> litera M czerwona
    by = {s["ticker"]: s for s in SEED["stocks"]}
    for t, (score, flags) in EXPECTED.items():
        c = canslim.info(by[t], mkt)
        assert (c["score"], letters(c)) == (score, flags), t


def test_unknown_does_not_lower_letter_and_cs_needs_4_known():
    s = {"eps_q0_yoy": 40, "pct_from_high_52w": -3}
    c = canslim.info(s, {"regime": "uptrend", "dist_days": 1})
    assert c["flags"]["C"] is True and c["flags"]["A"] is None and c["flags"]["M"] is True and c["known"] == 3
    canslim.tag(s, {"regime": "uptrend", "dist_days": 1})
    assert s["cs"] is None            # mniej niż 4 znane litery -> brak wyniku
    assert s["cs_letters"] == "C ? N ? ? ? M"


def test_market_correction_and_ftd_regime():
    assert canslim.info({}, {"regime": "correction"})["flags"]["M"] is False
    wl = {"market": {"regime": "correction", "m_regime": "uptrend", "sp500": {"m_dist_days": 2, "dist_days": 9, "m_via_ftd": True},
                     "nasdaq": {"dist_days": 4}}}
    assert canslim.market(wl) == {"regime": "uptrend", "dist_days": 4, "ftd": True}   # efektywne M: po korekcie liczy się FTD
    assert canslim.market({}) is None


def test_institutional_over_owned_is_unknown():
    assert canslim.institutional_flag({"inst_own": 130, "inst_trans": 1}) is None
    assert canslim.institutional_flag({"inst_own": 95, "inst_trans": 1}) is False
    assert canslim.institutional_flag({"inst_own": 50, "inst_trans": 0.5}) is True


def test_explain_has_seven_rows_and_same_score():
    mkt = canslim.market(SEED)
    s = next(x for x in SEED["stocks"] if x["ticker"] == "PLTR")
    e = canslim.explain(s, mkt)
    assert [r[0] for r in e["rows"]] == list("CANSLIM") and e["score"] == 5
