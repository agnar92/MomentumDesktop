"""Katalog filtrów i kolumn Finviz dla kreatora skanerów. Kody filtrów sprawdzone na żywo w skanerze Finviz (kod, który nie zmienia
liczby wyników względem pustego filtra, jest przez Finviz po cichu ignorowany — takich tu nie ma). Numery kolumn widoku własnego
(`v=152&c=`) odczytane z nagłówków odpowiedzi Finviz."""
import re
from urllib.parse import parse_qs, urlparse

_SEC = [("Technologia", "sec_technology"), ("Opieka zdrowotna", "sec_healthcare"), ("Finanse", "sec_financial"), ("Energia", "sec_energy"),
        ("Przemysł", "sec_industrials"), ("Dobra cykliczne", "sec_consumercyclical"), ("Dobra podstawowe", "sec_consumerdefensive"),
        ("Usługi komunalne", "sec_utilities"), ("Surowce", "sec_basicmaterials"), ("Nieruchomości", "sec_realestate"),
        ("Usługi telekomunikacyjne", "sec_communicationservices")]


def _grp(tab, label, options):
    return (tab, label, options)


def _levels(prefix, label_fmt, values):
    return [(label_fmt.format(v), f"{prefix}{v}") for v in values]


FILTERS = [
    # ----- opisowe -----
    _grp("Opisowe", "Giełda", [("Nasdaq", "exch_nasd"), ("NYSE", "exch_nyse"), ("AMEX", "exch_amex")]),
    _grp("Opisowe", "Indeks", [("S&P 500", "idx_sp500"), ("Nasdaq 100", "idx_ndx"), ("Dow Jones", "idx_dji"), ("Russell 2000", "idx_rut")]),
    _grp("Opisowe", "Sektor", _SEC),
    _grp("Opisowe", "Kraj", [("USA", "geo_usa"), ("Poza USA", "geo_notusa"), ("Chiny", "geo_china"), ("Izrael", "geo_israel"), ("Kanada", "geo_canada")]),
    _grp("Opisowe", "Kapitalizacja", [("Mega (> 200 mld $)", "cap_mega"), ("Large (10–200 mld $)", "cap_large"), ("Mid (2–10 mld $)", "cap_mid"),
                                      ("Small (300 mln – 2 mld $)", "cap_small"), ("Micro (50–300 mln $)", "cap_micro"), ("Nano (< 50 mln $)", "cap_nano"),
                                      ("Large i więcej (≥ 10 mld $)", "cap_largeover"), ("Mid i więcej (≥ 2 mld $)", "cap_midover"),
                                      ("Small i więcej (≥ 300 mln $)", "cap_smallover"), ("Micro i więcej (≥ 50 mln $)", "cap_microover"),
                                      ("Mid i mniej (≤ 10 mld $)", "cap_midunder"), ("Small i mniej (≤ 2 mld $)", "cap_smallunder"), ("Micro i mniej (≤ 300 mln $)", "cap_microunder")]),
    _grp("Opisowe", "Typ", [("Tylko akcje (bez ETF)", "ind_stocksonly")]),
    _grp("Opisowe", "Dywidenda", [("Brak", "fa_div_none"), ("Dodatnia", "fa_div_pos"), ("Wysoka (> 5 %)", "fa_div_high"), ("> 2 %", "fa_div_o2"), ("> 5 %", "fa_div_o5")]),
    _grp("Opisowe", "Short float", [("Niski (< 5 %)", "sh_short_low"), ("Wysoki (> 20 %)", "sh_short_high"), ("> 10 %", "sh_short_o10"), ("> 20 %", "sh_short_o20")]),
    _grp("Opisowe", "Rekomendacja analityków", [("Strong Buy", "an_recom_strongbuy"), ("Buy lub lepiej", "an_recom_buybetter"), ("Buy", "an_recom_buy"), ("Hold lub lepiej", "an_recom_holdbetter")]),
    _grp("Opisowe", "Średni wolumen", _levels("sh_avgvol_u", "< {} tys.", (100, 500, 1000)) + _levels("sh_avgvol_o", "> {} tys.", (100, 200, 300, 500, 1000, 2000))),
    _grp("Opisowe", "Wolumen względny", _levels("sh_relvol_o", "> {}×", ("1", "1.5", "2", "3", "5")) + [("< 0.5×", "sh_relvol_u0.5")]),
    _grp("Opisowe", "Wolumen bieżący", _levels("sh_curvol_o", "> {} tys.", (500, 1000))),
    _grp("Opisowe", "Cena", _levels("sh_price_u", "< {} $", (5, 10, 20)) + _levels("sh_price_o", "> {} $", (1, 5, 10, 15, 20, 30, 50, 100))),
    # ----- fundamentalne -----
    _grp("Fundamentalne", "P/E", [("Niskie (< 15)", "fa_pe_low"), ("Dodatnie (zyskowne)", "fa_pe_profitable"), ("Wysokie (> 50)", "fa_pe_high")] + _levels("fa_pe_u", "< {}", (15, 20, 30)) + _levels("fa_pe_o", "> {}", (30,))),
    _grp("Fundamentalne", "Forward P/E", [("Niskie (< 15)", "fa_fpe_low"), ("Dodatnie", "fa_fpe_profitable")] + _levels("fa_fpe_u", "< {}", (20,)) + _levels("fa_fpe_o", "> {}", (30,))),
    _grp("Fundamentalne", "PEG", [("Niski (< 1)", "fa_peg_low"), ("Wysoki (> 2)", "fa_peg_high")] + _levels("fa_peg_u", "< {}", (1, 2))),
    _grp("Fundamentalne", "P/S", [("Niskie (< 1)", "fa_ps_low")] + _levels("fa_ps_u", "< {}", (2,))),
    _grp("Fundamentalne", "P/B", [("Niskie (< 1)", "fa_pb_low")] + _levels("fa_pb_u", "< {}", (2,))),
    _grp("Fundamentalne", "Wzrost EPS w tym roku", [("Dodatni", "fa_epsyoy_pos"), ("Dodatni, niski (0–10 %)", "fa_epsyoy_poslow"), ("Wysoki (> 25 %)", "fa_epsyoy_high")] + _levels("fa_epsyoy_o", "> {} %", (10, 15, 20, 25, 30))),
    _grp("Fundamentalne", "Prognoza wzrostu EPS w przyszłym roku", [("Dodatni", "fa_epsyoy1_pos"), ("Wysoki (> 25 %)", "fa_epsyoy1_high")] + _levels("fa_epsyoy1_o", "> {} %", (10, 15, 20, 25))),
    _grp("Fundamentalne", "Wzrost EPS ostatnie 5 lat", [("Dodatni", "fa_eps5years_pos"), ("Wysoki (> 25 %)", "fa_eps5years_high")] + _levels("fa_eps5years_o", "> {} %", (10, 15, 20, 25))),
    _grp("Fundamentalne", "Prognoza wzrostu EPS 5 lat", [("Dodatni", "fa_estltgrowth_pos"), ("Wysoki (> 25 %)", "fa_estltgrowth_high")] + _levels("fa_estltgrowth_o", "> {} %", (10, 15, 20))),
    _grp("Fundamentalne", "Wzrost EPS kwartał do kwartału", [("Dodatni", "fa_epsqoq_pos"), ("Wysoki (> 25 %)", "fa_epsqoq_high")] + _levels("fa_epsqoq_o", "> {} %", (10, 15, 20, 25, 30))),
    _grp("Fundamentalne", "Wzrost sprzedaży kwartał do kwartału", [("Dodatni", "fa_salesqoq_pos"), ("Wysoki (> 25 %)", "fa_salesqoq_high")] + _levels("fa_salesqoq_o", "> {} %", (10, 15, 20, 25, 30))),
    _grp("Fundamentalne", "Wzrost sprzedaży ostatnie 5 lat", [("Dodatni", "fa_sales5years_pos"), ("Wysoki (> 25 %)", "fa_sales5years_high")] + _levels("fa_sales5years_o", "> {} %", (10, 15, 20, 25))),
    _grp("Fundamentalne", "ROE", [("Dodatnie", "fa_roe_pos"), ("Bardzo dobre (> 30 %)", "fa_roe_verypos")] + _levels("fa_roe_o", "> {} %", (10, 15, 20, 25, 30))),
    _grp("Fundamentalne", "ROA", [("Dodatnie", "fa_roa_pos")] + _levels("fa_roa_o", "> {} %", (10, 15))),
    _grp("Fundamentalne", "ROI", [("Dodatnie", "fa_roi_pos")] + _levels("fa_roi_o", "> {} %", (15, 20))),
    _grp("Fundamentalne", "Płynność bieżąca (current ratio)", [("Wysoka (> 3)", "fa_curratio_high")] + _levels("fa_curratio_o", "> {}", (1, 2))),
    _grp("Fundamentalne", "Dług / kapitał", [("Niski (< 0.1)", "fa_debteq_low"), ("Wysoki (> 1)", "fa_debteq_high")] + _levels("fa_debteq_u", "< {}", ("0.5", "1")) + _levels("fa_debteq_o", "> {}", (1,))),
    _grp("Fundamentalne", "Marża brutto", [("Dodatnia", "fa_grossmargin_pos")] + _levels("fa_grossmargin_o", "> {} %", (30, 50))),
    _grp("Fundamentalne", "Marża operacyjna", [("Dodatnia", "fa_opermargin_pos")] + _levels("fa_opermargin_o", "> {} %", (10, 20))),
    _grp("Fundamentalne", "Marża netto", [("Dodatnia", "fa_netmargin_pos")] + _levels("fa_netmargin_o", "> {} %", (10, 20))),
    _grp("Fundamentalne", "Udział insiderów", [("Wysoki (> 30 %)", "sh_insiderown_high")] + _levels("sh_insiderown_o", "> {} %", (10, 20))),
    _grp("Fundamentalne", "Zmiana udziału instytucji", [("Dodatnia", "sh_insttrans_pos")] + _levels("sh_insttrans_o", "> {} %", (5,))),
    _grp("Fundamentalne", "Udział instytucji", _levels("sh_instown_o", "> {} %", (20, 50)) + _levels("sh_instown_u", "< {} %", (50,))),
    # ----- techniczne -----
    _grp("Techniczne", "Wynik tygodnia", [("Dodatni", "ta_perf_1wup")]),
    _grp("Techniczne", "Wynik miesiąca", [("Dodatni", "ta_perf_4wup"), ("> 10 %", "ta_perf_4w10o")]),
    _grp("Techniczne", "Wynik kwartału", [("Dodatni", "ta_perf_13wup"), ("> 20 %", "ta_perf_13w20o")]),
    _grp("Techniczne", "Wynik roku", [("Dodatni", "ta_perf_52wup"), ("> 50 %", "ta_perf_52w50o")]),
    _grp("Techniczne", "Wynik od początku roku", [("Dodatni", "ta_perf_ytdup")]),
    _grp("Techniczne", "Cena vs SMA 20", [("Powyżej", "ta_sma20_pa"), ("Poniżej", "ta_sma20_pb")]),
    _grp("Techniczne", "Cena vs SMA 50", [("Powyżej", "ta_sma50_pa"), ("Poniżej", "ta_sma50_pb")]),
    _grp("Techniczne", "Cena vs SMA 200", [("Powyżej", "ta_sma200_pa"), ("Poniżej", "ta_sma200_pb")]),
    _grp("Techniczne", "SMA 50 vs SMA 200", [("SMA 50 powyżej SMA 200", "ta_sma50_sa200"), ("SMA 50 poniżej SMA 200", "ta_sma50_sb200")]),
    _grp("Techniczne", "SMA 20 vs SMA 50", [("SMA 20 powyżej SMA 50", "ta_sma20_sa50"), ("SMA 20 poniżej SMA 50", "ta_sma20_sb50")]),
    _grp("Techniczne", "Szczyt / dołek 52 tyg.", [("Nowy szczyt", "ta_highlow52w_nh"), ("Nowy dołek", "ta_highlow52w_nl"), ("0–3 % pod szczytem", "ta_highlow52w_b0to3h"),
                                                  ("0–5 % pod szczytem", "ta_highlow52w_b0to5h"), ("0–10 % pod szczytem", "ta_highlow52w_b0to10h"),
                                                  ("≥ 10 % pod szczytem", "ta_highlow52w_b10h"), ("≥ 20 % pod szczytem", "ta_highlow52w_b20h"), ("≥ 30 % pod szczytem", "ta_highlow52w_b30h")]),
    _grp("Techniczne", "Szczyt 50 dni", [("Nowy szczyt", "ta_highlow50d_nh"), ("0–5 % pod szczytem", "ta_highlow50d_b0to5h")]),
    _grp("Techniczne", "RSI (14)", [("Wykupiony (> 70)", "ta_rsi_ob70"), ("> 60", "ta_rsi_ob60"), ("Wyprzedany (< 30)", "ta_rsi_os30"), ("< 40", "ta_rsi_os40")]),
    _grp("Techniczne", "Beta", [("< 1", "ta_beta_u1"), ("> 1", "ta_beta_o1"), ("> 1.5", "ta_beta_o1.5")]),
    _grp("Techniczne", "ATR", _levels("ta_averagetruerange_o", "> {}", (1, 2, 3))),
    _grp("Techniczne", "Zmiana dnia", [("Wzrost", "ta_change_u"), ("Wzrost > 3 %", "ta_change_u3"), ("Wzrost > 5 %", "ta_change_u5"), ("Spadek", "ta_change_d"), ("Spadek > 3 %", "ta_change_d3")]),
    _grp("Techniczne", "Luka (gap)", [("W górę", "ta_gap_u"), ("W górę > 3 %", "ta_gap_u3"), ("W dół", "ta_gap_d")]),
]

# klucz pola: (numer kolumny widoku własnego Finviz `c=`, etykieta, format, nagłówek zwracany przez Finviz)
EXTRA_COLUMNS = {
    "fv_country": (5, "Kraj", "text", "Country"), "fv_dividend": (14, "Dywidenda %", "n2", "Dividend"), "fv_payout": (15, "Payout ratio %", "n1", "Payout Ratio"),
    "fv_eps_ttm": (16, "EPS (ttm)", "n2", "EPS"), "fv_peg": (9, "PEG", "n2", "PEG"), "fv_ps": (10, "P/S", "n2", "P/S"), "fv_pb": (11, "P/B", "n2", "P/B"),
    "fv_pfcf": (13, "P/FCF", "n1", "P/FCF"), "fv_short_float": (30, "Short float %", "n1", "Short Float"), "fv_short_ratio": (31, "Short ratio", "n2", "Short Ratio"),
    "fv_roa": (32, "ROA %", "n1", "ROA"), "fv_roic": (34, "ROIC %", "n1", "ROIC"), "fv_current_ratio": (35, "Current ratio", "n2", "Curr R"),
    "fv_quick_ratio": (36, "Quick ratio", "n2", "Quick R"), "fv_ltdebt_eq": (37, "Dług długoterm./kapitał", "n2", "LTDebt/Eq"),
    "fv_gross_margin": (39, "Marża brutto %", "n1", "Gross M"), "fv_oper_margin": (40, "Marża oper. %", "n1", "Oper M"), "fv_profit_margin": (41, "Marża netto %", "n1", "Profit M"),
    "fv_perf_week": (42, "Wynik tydzień %", "n1", "Perf Week"), "fv_perf_month": (43, "Wynik miesiąc %", "n1", "Perf Month"), "fv_perf_quarter": (44, "Wynik kwartał %", "n1", "Perf Quart"),
    "fv_perf_half": (45, "Wynik pół roku %", "n1", "Perf Half"), "fv_perf_year": (46, "Wynik rok %", "n1", "Perf Year"), "fv_perf_ytd": (47, "Wynik YTD %", "n1", "Perf YTD"),
    "fv_beta": (48, "Beta", "n2", "Beta"), "fv_atr": (49, "ATR", "n2", "ATR"), "fv_volatility_w": (50, "Zmienność tyg. %", "n1", "Volatility W"),
    "fv_volatility_m": (51, "Zmienność mies. %", "n1", "Volatility M"), "fv_sma20": (52, "SMA20 %", "n1", "SMA20"), "fv_sma50": (53, "SMA50 %", "n1", "SMA50"),
    "fv_sma200": (54, "SMA200 %", "n1", "SMA200"), "fv_high_50d": (55, "vs szczyt 50d %", "n1", "50D High"), "fv_low_50d": (56, "vs dołek 50d %", "n1", "50D Low"),
    "fv_high_52w": (57, "vs szczyt 52t %", "n1", "52W High"), "fv_low_52w": (58, "vs dołek 52t %", "n1", "52W Low"), "fv_rsi": (59, "RSI (14)", "n1", "RSI"),
    "fv_gap": (61, "Luka %", "n1", "Gap"), "fv_avg_volume": (63, "Śr. wolumen", "mcap", "Avg Volume"), "fv_rel_volume": (64, "Wol. względny ×", "n2", "Rel Volume"),
    "fv_change": (66, "Zmiana dnia %", "n2", "Change %"), "fv_volume": (67, "Wolumen", "mcap", "Volume"), "fv_ipo": (70, "Data IPO", "text", "IPO Date"),
    "fv_employees": (74, "Pracownicy", "int", "Employees"), "fv_income": (76, "Zysk netto", "mcap", "Income"), "fv_sales": (80, "Sprzedaż", "mcap", "Sales"),
    "fv_book_per_share": (71, "Wartość księgowa / akcję", "n2", "Book/sh"), "fv_cash_per_share": (72, "Gotówka / akcję", "n2", "Cash/sh"),
    "fv_short_interest": (82, "Short interest", "mcap", "Short Interest"),
}
TEXT_FIELDS = {k for k, v in EXTRA_COLUMNS.items() if v[2] == "text"}


def groups():
    """[(zakładka, [(grupa, [(napis, kod)])])] w kolejności katalogu."""
    out = {}
    for tab, label, opts in FILTERS:
        out.setdefault(tab, []).append((label, opts))
    return list(out.items())


def code_index():
    """kod -> (grupa, napis)"""
    return {code: (label, text) for _tab, label, opts in FILTERS for text, code in opts}


def selection_from_filters(filters):
    """Rozbija ciąg kodów na wybór per grupa katalogu i resztę (kody spoza katalogu zostają nietknięte): ({grupa: kod}, [reszta])."""
    idx, sel, rest = code_index(), {}, []
    for code in (c.strip() for c in (filters or "").split(",")):
        if not code:
            continue
        if code in idx and idx[code][0] not in sel:
            sel[idx[code][0]] = code
        else:
            rest.append(code)
    return sel, rest


def filters_from_selection(sel, rest=()):
    """Ciąg kodów: wybrane w kolejności katalogu + reszta."""
    ordered = [sel[label] for _tab, label, _opts in FILTERS if sel.get(label)]
    return ",".join(ordered + [c for c in rest if c and c not in ordered])


def parse_finviz_input(text):
    """Z wklejonego adresu skanera Finviz (…screener.ashx?v=111&f=a,b,c&ft=4) albo samej listy kodów -> ciąg kodów filtrów."""
    text = (text or "").strip()
    if not text:
        return ""
    if "f=" in text and ("?" in text or "&" in text or text.startswith("f=")):
        q = parse_qs(urlparse(text if "?" in text else "?" + text.lstrip("?")).query)
        text = (q.get("f") or [""])[0]
    return ",".join(c for c in re.split(r"[,\s]+", text) if c)


def extra_ids(keys):
    """Numery kolumn Finviz do zamówienia (Ticker zawsze)."""
    return [0, 1] + [EXTRA_COLUMNS[k][0] for k in keys if k in EXTRA_COLUMNS]
