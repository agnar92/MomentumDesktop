"""Codzienna lista obserwowana: Finviz (lista spółek + fundamenty) -> yfinance (ceny) -> docs/data/watchlist.json.

Przepływ (odpalany raz w tygodniu, w sobotę rano, po piątkowej sesji USA — patrz
.github/workflows/daily_watchlist.yml; ręcznie: `python watchlist.py` albo "Run workflow" na GitHubie):
  1. finviz.py: spółki nad SMA50 i SMA200 z dodatnim, stabilnym wzrostem EPS i prognozami EPS
     + sektor/branża/kapitalizacja/wzrost EPS/data wyników (wszystko, co da się wziąć z Finviz).
  2. yfinance: dzienne ceny tych spółek (~15 mies.), z których liczymy:
       - RS Rating w stylu IBD (rs_score = 0,4·R3M + 0,2·R6M + 0,2·R9M + 0,2·R12M, potem percentyl 1-99
         względem listy),
       - dane do filtra w stylu Qullamaggie (ADR %, średni obrót dzienny, relacja ceny do minimum z 1/3/6 mies.),
  3. Zapis docs/data/watchlist.json (czytane przez docs/index.html).
Wszystko to informacja do przeglądania, nie rekomendacja inwestycyjna.
"""
import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import finviz

ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = ROOT / "docs" / "data" / "watchlist.json"
EPS_CACHE_PATH = ROOT / "docs" / "data" / "eps_cache.json"
ESTIMATES_PATH = ROOT / "docs" / "data" / "estimates.json"
QM_WINDOWS = ("low_ratio_1m", "low_ratio_3m", "low_ratio_6m")

HISTORY_PERIOD = "10y"       # wykres tygodniowy ~6 lat (CHART_WEEKS) + rozgrzanie SMA40 + historia baz (opisy z książki); RS Rating liczy tylko ostatnie 12M
DAILY_KEEP = 1700            # compute_metrics i bazy dzienne używają tylko ostatnich ~6,7 roku sesji (reszta historii tylko rozgrzewa średnie tygodniowe)
BATCH_SIZE = 50
MIN_COVERAGE = 0.7           # minimalny odsetek spółek z Finviz, dla których dostaliśmy ceny
AVG_SESSIONS = 20            # okno ADR% i średniego obrotu (~miesiąc sesji)
MIN_BARS_RS = 252            # tyle sesji potrzeba na 12M (IBD) — młodsze spółki bez RS Rating
SPARK_WEEKS = 26
EPS_WEIGHTS = {"q0": 0.35, "q1": 0.25, "y0": 0.15, "y5": 0.25}   # najnowszy kwartał r/r, poprzedni kwartał r/r, EPS bieżącego roku, EPS 5 lat
EPS_STABILITY_WEIGHT = 0.2   # EPS Rating = 80 % percentyl wzrostu + 20 % percentyl stabilności
EPS_STABILITY_QUARTERS = 8   # stabilność: odsetek ostatnich 8 kwartałów (r/r) z dodatnim wzrostem EPS
EPS_STABILITY_MIN = 4        # min. tyle porównań r/r, żeby liczyć stabilność
COMPOSITE_RS_WEIGHT = 0.5    # Composite = 50 % RS Rating + 50 % EPS Rating
CHART_WEEKS = 312            # ile tygodni mieści wykres w stylu książki O'Neila (6 lat; domyślnie widać 156 = 3 lata, resztę pokazuje suwak)
BENCHMARK = "^GSPC"          # benchmark na wykresie (S&P 500)
NASDAQ = "^IXIC"             # drugi indeks do oceny rynku (M z CANSLIM)
MARKET_EMA_FAST = 10         # rynek w uptrendzie = EMA10 tygodniowa > EMA20 tygodniowa indeksu
MARKET_EMA_SLOW = 20
INST_MIN_OWN = 20.0          # I z CANSLIM: własność instytucji >= 20 % (ktoś poważny już jest w spółce), ...
INST_MAX_OWN = 90.0          # ... ale <= 90 %: spółka przesadnie obłożona instytucjami jest już „wykupiona” (nie ma kto dokupić)
INST_DATA_MAX = 100.0        # Finviz bywa > 100 % (podwójne liczenie w 13F) — takiej wartości nie traktujemy jak danych

DIST_WINDOW = 25             # dni dystrybucji liczymy z ostatnich 25 sesji (jak IBD)
FTD_LOOKBACK = 120           # Follow-Through Day: szukamy ostatniej korekty w 120 sesjach (~6 miesięcy)
FTD_MIN_DRAWDOWN_PCT = 7.0   # spadek od szczytu do dołka o co najmniej tyle %, żeby mówić o korekcie wymagającej FTD
FTD_MIN_DAY = 4              # FTD najwcześniej w 4. dniu próby odbicia (dzień 1 = pierwsze zamknięcie w górę po dołku)
FTD_MAX_DIST = 5             # po FTD rynek zostaje otwarty, dopóki jest mniej niż 5 dni dystrybucji (liczonych od FTD)
FTD_MIN_GAIN_PCT = 1.25      # wzrost indeksu w FTD o co najmniej 1,25 % (IBD) na wolumenie wyższym niż dzień wcześniej
DIST_DROP_PCT = 0.2          # dzień dystrybucji: indeks spadł o >= 0,2 % przy WYŻSZYM wolumenie niż dzień wcześniej
GROUP_MIN_MEMBERS = 3        # grupa branżowa liczy się od 3 spółek w liście
LEADER_MIN_RS = 80           # lider (L z CANSLIM): RS Rating >= 80 ...
LEADER_MIN_GROUP = 60        # ... w grupie z oceną >= 60 ...
LEADER_MAX_BELOW_HIGH_PCT = 25.0   # ... i nie dalej niż 25 % pod szczytem 52 tyg.
TL_TOLERANCE = 0.015         # tyle (1,5%) cena może "przekłuć" linię trendu, żeby nadal była to ta sama linia
RS_HIGH_SESSIONS = 252         # "nowe maksimum RS/ceny" = wyższe niż w poprzednich ~52 tygodniach (jak niebieska kropka w MarketSmith)
RS_RECENT_BARS = 5           # sygnał z ostatnich 5 sesji
TL_VOLUME_MULT = 1.4         # wybicie potwierdzone, gdy wolumen >= 1,4x średniej z poprzednich 50 świec (O'Neil: +40–50 % ponad średnią)
TL_VOLUME_AVG_BARS = 50
TL_NEAR_PCT = 3.0            # cena do 3% pod oporem = "przy oporze"
BASE_MIN_WEEKS = 5           # minimalna długość bazy/korekty (tygodnie od szczytu)
BASE_MIN_DEPTH_PCT = 6       # płytsze konsolidacje nie są raportowane
BASE_MAX_DEPTH_PCT = 50      # głębsze to już nie baza, tylko załamanie
BASE_FLAT_MAX_DEPTH_PCT = 15
BASE_CUP_MAX_DEPTH_PCT = 35
BOB_MAX_GAP_WEEKS = 8        # baza na bazie: nowa baza zaczyna się najpóźniej tyle tygodni po końcu poprzedniej (po jej wybiciu)
BOB_MAX_RUN_PCT = 20         # ... cena nie uciekła od pivotu poprzedniej bazy o więcej niż tyle % (inaczej to nowy etap, nie baza na bazie)
BOB_MIN_LOW_FRAC = 0.90      # ... a dołek nowej bazy nie spadł głębiej niż 10 % pod pivot poprzedniej
BASE_MAX_SHOWN = 20          # ile ostatnich baz trafia na wykres (opisy z książki: ramki baz, punkty kupna)
# Cup (z rączką) wg kryteriów O'Neila — baza jest "cup" tylko, gdy spełnia je wszystkie (inaczej "korekta"):
CUP_MIN_DEPTH_PCT = 12       # głębokość od lewego szczytu do dołka (płytsze to raczej flat)
CUP_MAX_DEPTH_PCT = 33       # normalnie do ~33 %
CUP_MAX_DEPTH_BEAR_PCT = 50  # w silnej korekcie rynku (S&P >= CUP_BEAR_MKT_DD) dozwolone głębsze miseczki
CUP_BEAR_MKT_DD = 15.0
CUP_MIN_WEEKS = 7            # od lewego szczytu do prawego brzegu: 7–65 tygodni (O'Neil)
CUP_MAX_WEEKS = 65
CUP_MAX_RETRACE = 0.40       # w trakcie spadku/odbicia żaden ruch „pod prąd” nie może odrobić > 40 % głębokości (to W / zygzak)
CUP_MIN_FIT = 0.60           # dopasowanie paraboli do zamknięć (R²) — miseczka ma być gładką „U”
CUP_PRIOR_LOOKBACK = 52
CUP_RIM_RECOVERY = 0.80      # prawy brzeg musi odrobić >= 80 % głębokości miseczki ...
CUP_RIM_MAX_GAP_PCT = 10.0   # ... i być nie dalej niż 10 % pod lewym szczytem
CUP_BOTTOM_WEEKS = 3         # tyle tygodni (zamknięć) w dolnej 1/3 głębokości — to ma być "U", nie "V"
CUP_BOTTOM_FRAC = 0.38       # ... i co najmniej taka część długości miseczki (parabola ~58 %, ostre „V” ~33 %)
CUP_LOW_POS = (0.2, 0.8)     # dołek nie może leżeć tuż przy lewej ani prawej krawędzi
CUP_HANDLE_MIN_WEEKS = 1     # rączka: 1–4 tygodnie (na dziennym > 5 sesji, czyli min. 6 świec)
CUP_HANDLE_MAX_WEEKS = 4
CUP_HANDLE_MAX_DEPTH_PCT = 12.0   # głębokość rączki: do 8–12 % w hossie
CUP_HANDLE_MA_WEEKS = 10     # rączka musi leżeć nad 10-tygodniową (50-dniową) średnią
VOL_AVG_WEEKS = 10           # „średnia 50-dniowa” = 10 tygodni (na dziennym 50 sesji)
BREAKOUT_VOL_MULT = 1.4      # wolumen wybicia >= +40 % ponad średnią
BUY_ZONE_MAX_PCT = 5.0       # strefa zakupu: pivot ... pivot + 5 %
STOP_LOSS_PCT = 8.0          # sztywny stop: do 7–8 % poniżej ceny zakupu
BASE_PRIOR_GAIN_PCT = 30     # A: wcześniejszy trend wzrostowy >= +30 % przed każdą bazą (cup, double bottom, ascending)
FLAT_PRIOR_GAIN_PCT = 20     # D: flat base po wzroście >= +20 %
CUP_MKT_CONTEXT_DD = 7.0     # S&P spadł >= 7 % w trakcie tworzenia miseczki = „pod presją rynku”
ZIGZAG_PCT = 3.0             # minimalne odbicie, od którego liczymy kolejne "skurcze" (VCP)
EPS_CACHE_VERSION = 3        # v3 = dodatkowo zmiana liczby akcji r/r (skup akcji); v2 = historia raportów do 40 kwartałów (limit=40); starsze wpisy są pobierane ponownie
EPS_CACHE_MAX_AGE_DAYS = 6   # EPS zmienia się raz na kwartał; odświeżenie jest tygodniowe (sobota), więc wpis starszy niż 6 dni jest zawsze pobierany ponownie
EPS_ACCEL_PP = 5.0           # akceleracja C: wzrost EPS r/r z ostatniego kwartału wyższy od poprzedniego o >= tyle punktów procentowych
EPS_TIME_BUDGET_S = 600
EPS_WORKERS = 4
CACHE_KEEP_DAYS = 45         # eps_cache.json / estimates.json dzielą skaner CANSLIM i szeroki skaner: wpis spoza bieżącej listy znika dopiero po tylu dniach bez odświeżenia
EST_MAX_AGE_DAYS = 2         # estymaty analityków zmieniają się codziennie, ale pobranie to 4 zapytania na spółkę — co 2 dni wystarcza
EST_TIME_BUDGET_S = 700
EST_HISTORY_DAYS = 400       # ile dni historii konsensusu EPS trzymamy (dopisujemy przy każdym pobraniu)
EST_PERIODS = ("0y", "+1y")  # bieżący i następny rok obrachunkowy (Yahoo nie podaje dalszych)
EST_SEED_DAYS = {"90daysAgo": 90, "60daysAgo": 60, "30daysAgo": 30, "7daysAgo": 7}
FINVIZ_KEYS = ("company", "sector", "industry", "market_cap", "pe", "forward_pe",
               "eps_this_y", "eps_next_y", "eps_past_5y", "eps_next_5y", "roe", "earnings", "recom", "finviz_target", "inst_own", "inst_trans",
               "sales_qq", "sales_past_5y", "shs_float", "shs_outstanding", "insider_own", "debt_eq")


# ============================================================================
# POBIERANIE CEN
# ============================================================================
def _extract_frames(data, tickers):
    """yf.download(group_by="ticker") -> {ticker: DataFrame[Open,High,Low,Close,Volume]}."""
    frames = {}
    if data is None or data.empty:
        return frames
    for t in tickers:
        try:
            df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
            raw = df
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        except KeyError:
            continue
        if len(df):
            if "Stock Splits" in raw.columns:   # splity (do kółek „2/1” na wykresie) — ceny są już skorygowane (auto_adjust)
                sp = raw["Stock Splits"].dropna()
                df.attrs["splits"] = [[pd.Timestamp(d).strftime("%Y-%m-%d"), float(r)] for d, r in sp[sp > 0].items()]
            frames[t] = df
    return frames


def download_prices(tickers, period=HISTORY_PERIOD, batch_size=BATCH_SIZE):
    import yfinance as yf
    frames = {}
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        print(f"  Ceny — paczka {i // batch_size + 1}/{-(-len(tickers) // batch_size)} ({len(batch)} spółek)...")
        try:
            data = yf.download(batch, period=period, interval="1d", auto_adjust=True, group_by="ticker",
                               threads=True, progress=False, actions=True)
        except Exception as e:
            print(f"⚠️  Paczka nieudana ({e}).")
            continue
        frames.update(_extract_frames(data, batch))
    return frames


def fetch_usdpln():
    """Kurs USD/PLN (ostatnie zamknięcie z Yahoo, ticker PLN=X) do przeliczania kapitału z konta IKE (PLN) na liczbę akcji; None, gdy niedostępny."""
    try:
        df = download_prices(["PLN=X"], period="10d").get("PLN=X")
        if df is None or not len(df):
            return None
        rate = float(df["Close"].iloc[-1])
        return {"usdpln": round(rate, 4), "as_of": pd.Timestamp(df.index[-1]).strftime("%Y-%m-%d")} if 1.0 < rate < 20.0 else None
    except Exception as e:
        print(f"⚠️  Kurs USD/PLN niedostępny ({e}) — przeliczenie kapitału wpisze się ręcznie.")
        return None


def drop_incomplete_bar(df, now_utc=None):
    """Usuwa dzisiejszą (jeszcze trwającą) sesję USA — ręczne odpalenie w trakcie sesji nie może wciągnąć
    niepełnej świecy jako 'dzisiejszego zamknięcia'."""
    if df.empty:
        return df
    now = pd.Timestamp(now_utc if now_utc is not None else datetime.now(timezone.utc))
    now_et = now.tz_convert("America/New_York") if now.tzinfo else now.tz_localize("UTC").tz_convert("America/New_York")
    last = pd.Timestamp(df.index[-1]).tz_localize(None).normalize()
    session_open = now_et.hour * 60 + now_et.minute < 16 * 60 + 30
    if last == pd.Timestamp(now_et.date()) and session_open:
        return df.iloc[:-1]
    return df


# ============================================================================
# WSKAŹNIKI
# ============================================================================
def _num(v, digits=2):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, digits) if np.isfinite(f) else None


def _price_at_or_before(close, ts):
    s = close[close.index <= ts]
    return float(s.iloc[-1]) if len(s) else None


ACCDIS_SESSIONS = 65   # ~13 tygodni, jak w ocenie Acc/Dis IBD
CLIMAX_RECENT_WEEKS = 2      # sell climax top (O'Neil, tygodniówka): sygnał w jednym z ostatnich 2 tygodni
CLIMAX_RUN_WEEKS = 3         # wzrost >= 25 % w 1-3 tygodnie (od najniższego Low z 3 poprzednich tygodni) ...
CLIMAX_RUN_PCT = 25.0
CLIMAX_MIN_WEEK_GAIN_PCT = 8.0   # ... tydzień z NAJWIĘKSZYM zyskiem tygodniowym całego trendu (min. 8 %, żeby nie łapać szumu) ...
CLIMAX_TREND_WEEKS = 104     # trend = od najniższego Low z ostatnich 2 lat (min. 8 tygodni)
CLIMAX_TREND_MIN_WEEKS = 8
CLIMAX_VOL_MULT = 1.5        # ... najszerszy zakres i NAJWYŻSZY wolumen tygodniowy trendu (oraz >= 1,5x średnia z 10 tygodni)
CLIMAX_VOL_AVG_WEEKS = 10
CLIMAX_EXT200_PCT = 70.0     # potwierdzenie: cena >= 70 % nad 200-dniową (SMA 40 tyg.)
DISTR_RECENT_WEEKS = 2       # dystrybucja bez wzrostu ceny (O'Neil, tygodniówka): sygnał w jednym z ostatnich 2 tygodni
DISTR_TREND_WEEKS = 104      # trend = od najniższego Low z ostatnich 2 lat (min. 8 tygodni), jak przy climax top
DISTR_TREND_MIN_WEEKS = 8
DISTR_MIN_RALLY_PCT = 30.0   # cena min. +30 % nad dołkiem trendu (to ma być szczyt rajdu, nie zwykła baza)
DISTR_VOL_MULT = 1.5         # NAJWYŻSZY wolumen tygodniowy od dołka trendu i >= 1,5x średnia z 10 poprzednich tygodni
DISTR_FLAT_PCT = 1.5         # ... a cena zamyka się niemal bez zmian (<= +1,5 % do poprzedniego zamknięcia) albo w dolnej połowie zakresu tygodnia
DISTR_MAX_UP_PCT = 5.0       # (tydzień zamknięty w górę o więcej niż 5 % to wybicie / climax, nie „mielenie” — nawet przy słabym zamknięciu)
DISTR_NEAR_HIGH_PCT = 15.0   # i nadal blisko szczytu (<= 15 % pod maksimum z 52 tygodni)
CLIMAX_LATE_STAGE = 3        # potwierdzenie: 3. lub dalsza baza w trendzie


def accdis_score(df, sessions=ACCDIS_SESSIONS):
    """Akumulacja / dystrybucja z ostatnich ~13 tygodni: średnia ważona wolumenem pozycji zamknięcia w zakresie dnia
    ((C−L) − (H−C)) / (H−L) — wskaźnik Chaikina (CMF). Zakres −1…+1; > 0 = kupujący zamykają dni blisko maksimum przy dużym wolumenie."""
    tail = df.tail(sessions)
    rng = (tail["High"] - tail["Low"]).replace(0, np.nan)
    mfm = (((tail["Close"] - tail["Low"]) - (tail["High"] - tail["Close"])) / rng).fillna(0.0)
    vol = tail["Volume"].astype(float)
    total = float(vol.sum())
    return float((mfm * vol).sum() / total) if total > 0 and len(tail) >= 20 else None


def detect_climax_top(weekly, bases=None, recent=CLIMAX_RECENT_WEEKS):
    """Sell climax top wg O'Neila (How to Make Money in Stocks) na świecach TYGODNIOWYCH (kolumny Open/High/Low/Close/Volume).
    Rdzeń (wszystko naraz, w jednym z ostatnich `recent` tygodni): wzrost >= 25 % w 1-3 tygodnie, NAJWIĘKSZY zysk tygodniowy,
    NAJSZERSZY zakres i NAJWYŻSZY wolumen tygodniowy od dołka trendu (dołek z ostatnich 2 lat). Potwierdzenia (conf 0-4):
    luka wyczerpania (otwarcie nad maksimum poprzedniego tygodnia), zamknięcie w dolnej połowie zakresu, cena >= 70 % nad SMA 40 tyg.
    (~200 dni), późny etap trendu (>= 3 bazy typu flat/cup od dołka, `bases` z detect_bases). Zwraca opis najświeższego tygodnia albo None.
    Heurystyka (progi poza „25 % w 1-3 tygodnie” i „najszerszy / największy / najwyższy” są moje), nie sygnał sprzedaży."""
    d = weekly[["Open", "High", "Low", "Close", "Volume"]].astype(float).dropna()
    n = len(d)
    if n < 52:
        return None
    sma40 = d["Close"].rolling(40).mean()
    ret = d["Close"].pct_change() * 100
    spread = (d["High"] - d["Low"]) / d["Close"].shift(1)
    for i in range(n - 1, n - 1 - recent, -1):
        lo0 = max(0, i - CLIMAX_TREND_WEEKS)
        t0 = lo0 + int(np.argmin(d["Low"].iloc[lo0:i].to_numpy()))
        if i - t0 < CLIMAX_TREND_MIN_WEEKS:
            continue
        c, h, lo, o, v = (float(d[k].iloc[i]) for k in ("Close", "High", "Low", "Open", "Volume"))
        base = float(d["Low"].iloc[i - CLIMAX_RUN_WEEKS:i].min())
        run = (c / base - 1) * 100 if base > 0 else 0.0
        wk = float(ret.iloc[i])
        if run < CLIMAX_RUN_PCT or wk < CLIMAX_MIN_WEEK_GAIN_PCT or wk < float(ret.iloc[t0 + 1:i].max()):
            continue
        if float(spread.iloc[i]) < float(spread.iloc[t0 + 1:i].max()):
            continue
        avg_v = float(d["Volume"].iloc[i - CLIMAX_VOL_AVG_WEEKS:i].mean())
        if avg_v <= 0 or v < float(d["Volume"].iloc[t0:i].max()) or v < CLIMAX_VOL_MULT * avg_v:
            continue
        s40 = float(sma40.iloc[i]) if pd.notna(sma40.iloc[i]) else 0.0
        ext200 = (c / s40 - 1) * 100 if s40 > 0 else None
        t0_date = d.index[t0].strftime("%Y-%m-%d")
        stage = sum(1 for b in (bases or []) if b.get("type") in ("flat", "cup") and b["start"] >= t0_date) if bases is not None else None
        gap, reversal = bool(o > float(d["High"].iloc[i - 1])), bool(h > lo and (c - lo) / (h - lo) < 0.5)
        ext_ok = ext200 is not None and ext200 >= CLIMAX_EXT200_PCT
        late = stage is not None and stage >= CLIMAX_LATE_STAGE
        return {
            "date": d.index[i].strftime("%Y-%m-%d"), "runup_pct": round(run, 1), "week_gain_pct": round(wk, 1),
            "vol_ratio": round(v / avg_v, 1), "gap": gap, "reversal": reversal,
            "ext200_pct": round(ext200, 1) if ext200 is not None else None, "stage": stage, "late": late,
            "conf": int(gap) + int(reversal) + int(ext_ok) + int(late),
        }
    return None


def detect_distribution_week(weekly, recent=DISTR_RECENT_WEEKS):
    """Dystrybucja bez wzrostu ceny („mielenie”, O'Neil) na świecach TYGODNIOWYCH: w jednym z ostatnich `recent` tygodni NAJWYŻSZY wolumen
    tygodniowy od dołka trendu (i >= 1,5x średnia z 10 tygodni), a cena zamyka się niemal bez zmian (<= +1,5 % do poprzedniego zamknięcia)
    albo w dolnej połowie zakresu tygodnia — przy cenie >= +30 % nad dołkiem trendu i <= 15 % pod rocznym maksimum. Podaż tłumi popyt
    (instytucje sprzedają w siłę). Zwraca opis najświeższego takiego tygodnia albo None. Heurystyka, progi moje — ostrzeżenie, nie sygnał sprzedaży."""
    d = weekly[["Open", "High", "Low", "Close", "Volume"]].astype(float).dropna()
    n = len(d)
    if n < 52:
        return None
    for i in range(n - 1, n - 1 - recent, -1):
        lo0 = max(0, i - DISTR_TREND_WEEKS)
        t0 = lo0 + int(np.argmin(d["Low"].iloc[lo0:i].to_numpy()))
        if i - t0 < DISTR_TREND_MIN_WEEKS:
            continue
        c, h, lo, v = (float(d[k].iloc[i]) for k in ("Close", "High", "Low", "Volume"))
        prev_c = float(d["Close"].iloc[i - 1])
        trend_low = float(d["Low"].iloc[t0])
        if trend_low <= 0 or prev_c <= 0 or (c / trend_low - 1) * 100 < DISTR_MIN_RALLY_PCT:
            continue
        avg_v = float(d["Volume"].iloc[max(0, i - 10):i].mean())
        if avg_v <= 0 or v < float(d["Volume"].iloc[t0:i].max()) or v < DISTR_VOL_MULT * avg_v:
            continue
        chg = (c / prev_c - 1) * 100
        pos = (c - lo) / (h - lo) if h > lo else 0.5
        if chg > DISTR_MAX_UP_PCT or (chg > DISTR_FLAT_PCT and pos >= 0.5):
            continue   # tydzień zamknięty wyraźnie w górę i w górnej połowie to popyt (albo climax), nie dystrybucja
        hi52 = float(d["High"].iloc[max(0, i - 52):i + 1].max())
        if hi52 <= 0 or c < hi52 * (1 - DISTR_NEAR_HIGH_PCT / 100):
            continue
        return {"date": d.index[i].strftime("%Y-%m-%d"), "vol_ratio": round(v / avg_v, 1), "change_pct": round(chg, 1), "close_pos": round(pos, 2)}
    return None


def accdis_letter(rating):
    """Percentyl Acc/Dis -> litera A-E (A = najsilniejsza akumulacja)."""
    if rating is None:
        return None
    return "A" if rating >= 80 else "B" if rating >= 60 else "C" if rating >= 40 else "D" if rating >= 20 else "E"


def add_accdis_rating(stocks):
    """accdis_rating (percentyl 1-99 wśród listy) i accdis (litera A-E) z accdis_score."""
    percentile_rating(stocks, "accdis_score", "accdis_rating")
    for s in stocks:
        s["accdis"] = accdis_letter(s.get("accdis_rating"))
    return stocks


def fresh_breakout_base(bases, index, max_age_weeks=2):
    """Baza kupowalna, która zakończyła się wybiciem w ostatnich `max_age_weeks` tygodniach (świeca wybicia = tydzień po końcu bazy). Dla płaskiej bazy /
    kwadratowego pudełka / cupa bez rączki pivot = szczyt bazy, więc wybicie kończy bazę i nie ma już „otwartej” — bez tego świeże wybicie z pudełka
    nie miałoby pivotu, odległości ani stanu wybicia. None, gdy takiej bazy nie ma."""
    last = next((b for b in reversed(bases) if not b["open"]), None)
    if not last or last["type"] not in BASE_TYPES_BUYABLE or not last.get("pivot") or len(index) < 3:
        return None
    try:
        end_i = index.get_loc(pd.Timestamp(last["end"]))
    except KeyError:
        return None
    return last if end_i >= len(index) - 1 - max_age_weeks else None


def compute_metrics(df, bench_w=None):
    """Wskaźniki z dziennych świec jednej spółki (kolumny Open/High/Low/Close/Volume, rosnący indeks dat).
    bench_w = tygodniowe zamknięcia S&P 500 (kontekst rynku dla miseczek), opcjonalnie."""
    df = df.tail(DAILY_KEEP).copy()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None)
    close = df["Close"].astype(float)
    if len(close) < 30:
        return None
    asof = close.index[-1]
    price = float(close.iloc[-1])

    def back(months):
        return _price_at_or_before(close, asof - pd.DateOffset(months=months))

    p3, p6, p9, p12 = back(3), back(6), back(9), back(12)
    have_12m = len(close) >= MIN_BARS_RS and all(p and p > 0 for p in (p3, p6, p9, p12))
    rets = {m: (price / p - 1) if p and p > 0 else None for m, p in ((3, p3), (6, p6), (9, p9), (12, p12))}
    rs_score = (0.4 * rets[3] + 0.2 * rets[6] + 0.2 * rets[9] + 0.2 * rets[12]) if have_12m else None

    tail = df.tail(AVG_SESSIONS)
    ratio = (tail["High"] / tail["Low"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
    adr = (ratio.mean() - 1) * 100 if len(ratio) else None
    dollar_volume = float((tail["Close"] * tail["Volume"]).mean()) if len(tail) else None

    # Relacja ceny do najniższego Low z okna (bez odejmowania 1 — to i tak tylko ranking, wystarczy sortować malejąco).
    low_ratio = {}
    for months in (1, 3, 6):
        window = df[df.index > asof - pd.DateOffset(months=months)]["Low"]
        low = float(window.min()) if len(window) else None
        low_ratio[months] = price / low if low and low > 0 else None

    sma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
    sma200 = float(close.tail(200).mean()) if len(close) >= 200 else None

    high_52w = float(df["High"].tail(252).max())
    wk_ohlc = weekly_ohlcv(df, asof)
    wk_close = wk_ohlc["Close"].astype(float)   # średnie TYGODNIOWE (10 i 40 tyg.) — te same co na wykresie tygodniowym; ocena tygodniowa nie używa dziennej SMA50
    sma10w = float(wk_close.tail(10).mean()) if len(wk_close) >= 10 else None
    sma40w = float(wk_close.tail(40).mean()) if len(wk_close) >= 40 else None
    all_bases = detect_bases(wk_ohlc, bench_w, ipo=len(wk_ohlc) <= IPO_MAX_WEEKS)
    open_base = next((b for b in reversed(all_bases) if b["open"]), None) or fresh_breakout_base(all_bases, wk_ohlc.index)
    tlw = detect_consolidation(wk_ohlc, WEEKLY_FLAG) or {}
    tlw_level = next((ln["y1"] for ln in tlw.get("lines", []) if ln["kind"] == "res"), None)
    pivot_break = None
    if open_base and open_base.get("pivot"):
        pivot_break = detect_level_break(wk_ohlc, open_base["pivot"], 2, 10, "W")

    weekly = close.resample("W-FRI").last().dropna().tail(SPARK_WEEKS)
    spark = [round((v / weekly.iloc[0] - 1) * 100, 1) for v in weekly] if len(weekly) >= 5 else []

    climax = detect_climax_top(wk_ohlc, all_bases)
    distr = detect_distribution_week(wk_ohlc)
    return {
        "price": _num(price),
        "as_of": asof.strftime("%Y-%m-%d"),
        "ret_3m_pct": _num(rets[3] * 100, 1) if rets[3] is not None else None,
        "ret_6m_pct": _num(rets[6] * 100, 1) if rets[6] is not None else None,
        "ret_12m_pct": _num(rets[12] * 100, 1) if rets[12] is not None else None,
        "rs_score": _num(rs_score, 4),
        "adr_pct": _num(adr),
        "dollar_volume_avg": _num(dollar_volume, 0),
        "low_ratio_1m": _num(low_ratio[1], 3),
        "low_ratio_3m": _num(low_ratio[3], 3),
        "low_ratio_6m": _num(low_ratio[6], 3),
        "pct_above_sma50": _num((price / sma50 - 1) * 100) if sma50 else None,
        "pct_above_sma200": _num((price / sma200 - 1) * 100) if sma200 else None,
        "pct_above_sma10w": _num((price / sma10w - 1) * 100) if sma10w else None,
        "pct_above_sma40w": _num((price / sma40w - 1) * 100) if sma40w else None,
        "pct_from_high_52w": _num((price / high_52w - 1) * 100, 1) if high_52w > 0 else None,
        "base_type": open_base["type"] if open_base else None,
        "base_depth_pct": open_base["depth_pct"] if open_base else None,
        "base_weeks": open_base["weeks"] if open_base else None,
        "base_handle": bool(open_base["cup"]["handle"]) if open_base and open_base.get("cup") else None,
        "base_saucer": open_base.get("saucer") if open_base else None,
        "base_stage": open_base.get("stage") if open_base else None,
        "base_on_base": open_base.get("base_on_base") if open_base else None,
        "base_status": open_base.get("status") if open_base else None,
        "base_rejection": "; ".join(open_base.get("rejection_reasons") or []) or None if open_base else None,
        "base_buy_zone_max": open_base.get("buy_zone_max") if open_base else None,
        "box_low": open_base.get("low") if open_base and open_base.get("box_stop") is not None else None,   # pudełko bazy płaskiej / kwadratowej: dół, podział na 3 części, stop ze środka
        "box_t1": open_base["box_thirds"][0] if open_base and open_base.get("box_thirds") else None,
        "box_t2": open_base["box_thirds"][1] if open_base and open_base.get("box_thirds") else None,
        "box_stop": open_base.get("box_stop") if open_base else None,
        "box_stop_pct": open_base.get("box_stop_pct") if open_base else None,
        "box_brk_wick_pct": open_base.get("breakout_wick_pct") if open_base else None,
        "box_brk_vol_wow_pct": open_base.get("breakout_vol_wow_pct") if open_base else None,
        "box_brk_hi10": open_base.get("breakout_hi10") if open_base else None,
        "base_stop_8pct": open_base.get("stop_loss_8pct") if open_base else None,
        "base_prior_uptrend_pct": open_base.get("prior_uptrend_pct") if open_base else None,
        "base_rs_prior_up": (open_base.get("cup") or {}).get("rs_prior_up") if open_base else None,
        "base_rise_pct": open_base.get("rise_pct") if open_base else None,
        "base_mkt_dd_pct": open_base["cup"]["mkt_dd_pct"] if open_base and open_base.get("cup") else None,
        "pivot": open_base["pivot"] if open_base else None,
        "pct_to_pivot": _num((open_base["pivot"] / price - 1) * 100, 1) if open_base else None,
        "vcp": open_base["vcp"] if open_base else None,
        "tlw_state": tlw.get("state"),
        "tlw_pattern": tlw.get("pattern"),
        "tlw_vol_ratio": (tlw.get("breakout") or {}).get("vol_ratio"),
        "tlw_vol_ok": (tlw.get("breakout") or {}).get("confirmed"),
        "tlw_level": tlw_level,
        "tlw_dist_pct": _num((tlw_level / price - 1) * 100, 1) if tlw_level and price else None,
        "pivot_state": pivot_break["state"] if pivot_break else None,
        "pivot_vol_ratio": pivot_break["vol_ratio"] if pivot_break else None,
        "pivot_break_date": pivot_break["date"] if pivot_break else None,
        "pivot_tf": pivot_break["tf"] if pivot_break else None,
        "vol_surge_5d": volume_surge(df),
        "accdis_score": _num(accdis_score(df), 3),
        "climax_top": climax is not None,
        "climax_date": climax["date"] if climax else None,
        "climax_runup_pct": climax["runup_pct"] if climax else None,
        "climax_week_gain_pct": climax["week_gain_pct"] if climax else None,
        "climax_vol_ratio": climax["vol_ratio"] if climax else None,
        "climax_reversal": climax["reversal"] if climax else None,
        "climax_gap": climax["gap"] if climax else None,
        "climax_ext200_pct": climax["ext200_pct"] if climax else None,
        "climax_stage": climax["stage"] if climax else None,
        "climax_late": climax["late"] if climax else None,
        "climax_conf": climax["conf"] if climax else None,
        "dist_top": distr is not None,   # dystrybucja bez wzrostu ceny (tygodniówka)
        "dist_date": distr["date"] if distr else None,
        "dist_vol_ratio": distr["vol_ratio"] if distr else None,
        "dist_change_pct": distr["change_pct"] if distr else None,
        "spark": spark,
    }


def percentile_rating(stocks, score_key, rating_key):
    """Rating 1-99 = percentyl wyniku score_key wśród spółek listy (remisy: średnia ranga). Spółki bez wyniku -> None."""
    scored = [s for s in stocks if s.get(score_key) is not None]
    for s in stocks:
        s[rating_key] = None
    n = len(scored)
    if n == 0:
        return stocks
    if n == 1:
        scored[0][rating_key] = 50
        return stocks
    ranks = pd.Series([s[score_key] for s in scored]).rank(method="average")
    for s, r in zip(scored, ranks):
        s[rating_key] = int(round(1 + 98 * (r - 1) / (n - 1)))
    return stocks


def add_group_strength(stocks):
    """L z CANSLIM: siła grupy branżowej = średni RS Rating spółek z tej samej branży Finviz (min. GROUP_MIN_MEMBERS), przeliczona na
    percentyl 1-99 wśród branż (`industry_rating`); `leader` = RS >= 80, grupa >= 60 i nie dalej niż 25 % pod szczytem 52 tyg."""
    members = {}
    for s in stocks:
        if s.get("industry") and s.get("rs_rating") is not None:
            members.setdefault(s["industry"], []).append(s["rs_rating"])
    groups = [{"industry": k, "score": sum(v) / len(v)} for k, v in members.items() if len(v) >= GROUP_MIN_MEMBERS]
    percentile_rating(groups, "score", "rating")
    rating = {g["industry"]: g["rating"] for g in groups}
    for s in stocks:
        s["industry_rating"] = rating.get(s.get("industry"))
        below = s.get("pct_from_high_52w")
        s["leader"] = bool(s.get("rs_rating") is not None and s["rs_rating"] >= LEADER_MIN_RS and s["industry_rating"] is not None
                           and s["industry_rating"] >= LEADER_MIN_GROUP and below is not None and below >= -LEADER_MAX_BELOW_HIGH_PCT)
    return stocks


def add_rs_rating(stocks):
    """RS Rating 1-99 = percentyl rs_score wśród spółek listy (remisy: średnia ranga). Spółki bez rs_score -> None."""
    return percentile_rating(stocks, "rs_score", "rs_rating")


def eps_score(q0, q1, eps_this_y, eps_past_5y):
    """Wynik EPS w stylu IBD (przybliżenie): wzrost EPS r/r z dwóch ostatnich kwartałów + roczny wzrost EPS (bieżący rok
    i średnia z 5 lat, dane Finviz). Surowe procenty, bez obcinania (tak jak zwroty w rs_score) — skrajne wartości
    łagodzi dopiero ranking percentylowy; brakujące składniki pomijamy (wagi się renormalizują), ale najnowszy kwartał jest wymagany
    i potrzebne są min. 2 składniki. -> float albo None."""
    if q0 is None:
        return None
    parts = [(EPS_WEIGHTS["q0"], q0), (EPS_WEIGHTS["q1"], q1), (EPS_WEIGHTS["y0"], eps_this_y), (EPS_WEIGHTS["y5"], eps_past_5y)]
    parts = [(w, v) for w, v in parts if v is not None]
    if len(parts) < 2:
        return None
    total = sum(w for w, _ in parts)
    return _num(sum(w * v for w, v in parts) / total)


def eps_annual_growth(quarters, years=3):
    """A z CANSLIM (O'Neil: wzrost EPS >= 25 % w KAŻDYM z ostatnich 3 lat): wzrost sumy EPS z 4 kwartałów (TTM) względem sumy z 4 kwartałów
    wcześniej — dla ostatnich `years` okien: [najświeższy, rok wcześniej, 2 lata wcześniej]. Brak 4 kwartałów w oknie albo nieujemnej
    bazy (<= 0) = None (przy ujemnej bazie wzrost % nie ma sensu). `quarters` = lista z eps_quarters (z polem t = TTM)."""
    out = []
    for j in range(years):
        i = len(quarters) - 1 - 4 * j
        now = quarters[i]["t"] if 0 <= i < len(quarters) else None
        prev = quarters[i - 4]["t"] if i - 4 >= 0 else None
        out.append(_num((now - prev) / prev * 100, 1) if now is not None and prev is not None and prev > 0 else None)
    return out


def eps_stability(growths):
    """Stabilność wzrostu EPS (0-100 %) = odsetek ostatnich EPS_STABILITY_QUARTERS kwartałów, w których EPS r/r wzrósł (g > 0).
    Spółka z wyraźnym wzrostem co kwartał dostaje ~100, z zygzakiem (zysk, strata, zysk...) wyraźnie mniej. None przy < EPS_STABILITY_MIN
    porównaniach r/r."""
    g = [x for x in growths if x is not None][-EPS_STABILITY_QUARTERS:]
    if len(g) < EPS_STABILITY_MIN:
        return None
    return _num(100 * sum(1 for x in g if x > 0) / len(g), 0)


def add_eps_rating(stocks, eps_cache):
    """EPS Rating 1-99 = 80 % percentyl wzrostu (eps_score) + 20 % percentyl stabilności (eps_stability; bez stabilności — sam wzrost)
    + pola pomocnicze eps_q0_yoy / eps_q1_yoy (wzrost r/r dwóch ostatnich zrealizowanych kwartałów z cache Yahoo).
    Skumulowany Composite = średnia ważona RS Rating i EPS Rating (tylko gdy są oba)."""
    for s in stocks:
        rows = ((eps_cache or {}).get(s["ticker"]) or {}).get("rows") or []
        quarters = [q["g"] for q in eps_quarters(rows)[0]]
        q0 = quarters[-1] if quarters else None
        q1 = quarters[-2] if len(quarters) > 1 else None
        s["eps_q0_yoy"], s["eps_q1_yoy"] = q0, q1
        # akceleracja (C): tempo wzrostu zysków rośnie z kwartału na kwartał (np. +25 % -> +50 %); None, gdy brakuje któregoś kwartału
        s["eps_accel"] = (q0 - q1 >= EPS_ACCEL_PP) if q0 is not None and q1 is not None else None
        s["eps_yr0"], s["eps_yr1"], s["eps_yr2"] = eps_annual_growth(eps_quarters(rows)[0])   # roczny wzrost EPS (TTM) w 3 ostatnich latach — kryterium A
        shares = ((eps_cache or {}).get(s["ticker"]) or {}).get("shares_chg_pct")
        s["shares_chg_pct"] = shares if _is_num(shares) else None   # zmiana liczby akcji r/r (ujemna = skup akcji)
        s["eps_score"] = eps_score(q0, q1, s.get("eps_this_y"), s.get("eps_past_5y"))
        s["eps_stability"] = eps_stability(quarters)
    percentile_rating(stocks, "eps_score", "eps_growth_rating")
    percentile_rating(stocks, "eps_stability", "eps_stability_rating")
    for s in stocks:
        g, st = s.get("eps_growth_rating"), s.get("eps_stability_rating")
        if g is None:
            s["eps_rating"] = None
        elif st is None:
            s["eps_rating"] = g
        else:
            s["eps_rating"] = int(round((1 - EPS_STABILITY_WEIGHT) * g + EPS_STABILITY_WEIGHT * st))
    for s in stocks:
        rs, eps = s.get("rs_rating"), s.get("eps_rating")
        s["composite_rating"] = int(round(COMPOSITE_RS_WEIGHT * rs + (1 - COMPOSITE_RS_WEIGHT) * eps)) if rs is not None and eps is not None else None
    return stocks


# ============================================================================
# BAZY / KOREKTY (głębokość od szczytu, pivot, skurcze VCP) — heurystyka na świecach tygodniowych.
# NIE jest to rozpoznawanie formacji jak w MarketSmith (cup with handle, flagi...) — mierzy po prostu głębokość
# i długość każdej korekty od lokalnego szczytu do ponownego wybicia ponad ten szczyt; typ ("flat"/"cup"/"deep")
# to prosta klasyfikacja po głębokości i odbiciu, orientacyjna.
# ============================================================================
def distribution_days(df, window=DIST_WINDOW, drop_pct=DIST_DROP_PCT):
    """Liczba dni dystrybucji w ostatnich `window` sesjach: indeks spadł o >= drop_pct % przy większym wolumenie niż dzień wcześniej."""
    close, vol = df["Close"].astype(float), df["Volume"].astype(float)
    chg = close.pct_change() * 100
    dist = (chg <= -drop_pct) & (vol > vol.shift(1))
    return int(dist.tail(window).sum())


def follow_through_day(df, lookback=FTD_LOOKBACK):
    """Follow-Through Day (O'Neil / IBD): po korekcie (spadek >= FTD_MIN_DRAWDOWN_PCT od szczytu) próba odbicia zaczyna się pierwszym zamknięciem w górę po
    najniższym dołku (dzień 1). FTD = dzień >= 4 próby, w którym indeks zyskuje >= FTD_MIN_GAIN_PCT na wolumenie wyższym niż dzień wcześniej. Próba przepada,
    gdy indeks wybije dołek w dół — bierzemy więc zawsze NAJNIŻSZY dołek po szczycie, a FTD tylko po nim.
    Zwraca {state, ...}: "none" (brak korekty), "correction" (dołek jest świeży, brak próby), "attempt" (próba w toku, `day`), "ftd" (potwierdzony:
    `date`, `gain_pct`, `vol_ratio`, `day`, `low_date`, `drawdown_pct`, `dist_days` = dni dystrybucji PO FTD)."""
    d = df.tail(lookback)
    if len(d) < 30:
        return {"state": "none"}
    hi, lo, cl, vol = (d[c].astype(float).values for c in ("High", "Low", "Close", "Volume"))
    last = len(d) - 1
    peak = int(np.argmax(hi))
    if peak >= last - 1:
        return {"state": "none"}
    low_i = peak + 1 + int(np.argmin(lo[peak + 1:]))
    drawdown = (hi[peak] - lo[low_i]) / hi[peak] * 100
    if drawdown < FTD_MIN_DRAWDOWN_PCT:
        return {"state": "none"}
    base = {"low_date": pd.Timestamp(d.index[low_i]).strftime("%Y-%m-%d"), "drawdown_pct": _num(drawdown, 1)}
    day1 = next((j for j in range(low_i + 1, last + 1) if cl[j] > cl[j - 1]), None)
    if day1 is None:
        return {"state": "correction", **base}
    for k in range(day1 + FTD_MIN_DAY - 1, last + 1):
        gain = (cl[k] / cl[k - 1] - 1) * 100
        if gain >= FTD_MIN_GAIN_PCT and vol[k] > vol[k - 1]:
            chg = pd.Series(cl).pct_change().values * 100
            dist = int(sum(1 for j in range(k + 1, last + 1) if chg[j] <= -DIST_DROP_PCT and vol[j] > vol[j - 1]))
            return {"state": "ftd", "date": pd.Timestamp(d.index[k]).strftime("%Y-%m-%d"), "gain_pct": _num(gain, 2),
                    "vol_ratio": _num(vol[k] / vol[k - 1], 2), "day": k - day1 + 1, "dist_days": dist, **base}
    return {"state": "attempt", "day": last - day1 + 1, **base}


def index_state(df):
    """Stan indeksu. Reżim (M z CANSLIM) = EMA10 tygodniowa > EMA20 tygodniowa (uptrend) albo nie (korekta). Dodatkowo informacyjnie:
    cena vs SMA50/SMA200, kierunek SMA50, odległość od szczytu 52 tyg., dni dystrybucji. None, gdy za mało danych."""
    close = df["Close"].astype(float)
    weekly = weekly_close(df)
    if len(close) < 200 or weekly is None or len(weekly) < MARKET_EMA_SLOW + 5:
        return None
    ema_fast = float(weekly.ewm(span=MARKET_EMA_FAST, adjust=False).mean().iloc[-1])
    ema_slow = float(weekly.ewm(span=MARKET_EMA_SLOW, adjust=False).mean().iloc[-1])
    price = float(close.iloc[-1])
    sma50, sma200 = float(close.tail(50).mean()), float(close.tail(200).mean())
    sma50_prev = float(close.iloc[-60:-10].mean())
    high = float(df["High"].astype(float).tail(252).max())
    regime = "uptrend" if ema_fast > ema_slow else "correction"
    ftd = follow_through_day(df)
    dist = distribution_days(df)
    # M efektywne: tygodniowa EMA reaguje z opóźnieniem, więc po korekcie potwierdzony Follow-Through Day (z mniej niż 5 dniami dystrybucji PO nim) też otwiera rynek
    via_ftd = regime == "correction" and ftd["state"] == "ftd" and ftd["dist_days"] < FTD_MAX_DIST
    m_regime = "uptrend" if regime == "uptrend" or via_ftd else "correction"
    m_dist = ftd["dist_days"] if via_ftd else dist
    return {"close": _num(price), "ema10w": _num(ema_fast), "ema20w": _num(ema_slow), "ema_gap_pct": _num((ema_fast / ema_slow - 1) * 100, 2),
            "pct_vs_sma50": _num((price / sma50 - 1) * 100, 1), "pct_vs_sma200": _num((price / sma200 - 1) * 100, 1),
            "sma50_rising": sma50 > sma50_prev, "pct_from_high": _num((price / high - 1) * 100, 1), "dist_days": dist,
            "regime": regime, "ftd": ftd, "m_regime": m_regime, "m_dist_days": m_dist, "m_via_ftd": via_ftd, "as_of": pd.Timestamp(df.index[-1]).strftime("%Y-%m-%d")}


def market_state(sp_df, nq_df):
    """M z CANSLIM: stan S&P 500 i Nasdaq oraz łączny reżim = surowszy z dwóch. Uptrend = EMA10 > EMA20 tygodniowa indeksu (decyzja użytkownika),
    korekta = EMA10 <= EMA20; dni dystrybucji, SMA50/SMA200 i odległość od szczytu są tylko podglądem."""
    states = {"sp500": index_state(sp_df) if sp_df is not None and len(sp_df) else None,
              "nasdaq": index_state(nq_df) if nq_df is not None and len(nq_df) else None}
    order = {"uptrend": 0, "correction": 1}
    known = [s for s in states.values() if s]
    if not known:
        return None
    return {**states, "regime": max((s["regime"] for s in known), key=order.get),
            "m_regime": max((s["m_regime"] for s in known), key=order.get)}


def mkt_drawdown(bench_w, d0, d1):
    """Największy spadek (peak-to-trough, %) benchmarku (tygodniowe zamknięcia) w oknie dat d0..d1; None bez danych."""
    if bench_w is None or not len(bench_w):
        return None
    idx = pd.DatetimeIndex(bench_w.index)
    seg = bench_w[(idx >= pd.Timestamp(d0)) & (idx <= pd.Timestamp(d1))].astype(float).dropna()
    if len(seg) < 2:
        return None
    return float(((seg.cummax() - seg) / seg.cummax()).max() * 100)


def first_down_idx(cl, peak, end):
    """Liczenie czasu bazy: zaczyna się od pierwszego tygodnia po szczycie, w którym cena zamyka się ze spadkiem (O'Neil). Brak spadku = peak + 1."""
    for i in range(peak + 1, end + 1):
        if cl[i] < cl[i - 1]:
            return i
    return min(peak + 1, end)


def prior_gain_pct(hi, lo, peak, k=1, lookback=CUP_PRIOR_LOOKBACK):
    """Wzrost przed bazą (A): szczyt bazy / najniższy Low z poprzednich 52 tygodni, w %. None = za mało historii (< 13 tygodni przed szczytem)."""
    i0 = max(0, peak - lookback * k)
    if peak - i0 < 13 * k:
        return None
    return (float(hi[peak]) / float(lo[i0:peak].min()) - 1) * 100


def _vol_mean(vol, end, bars):
    """Średni wolumen z `bars` świec kończących się na `end` (włącznie); None bez danych."""
    if vol is None or end < 0:
        return None
    seg = vol[max(0, end - bars + 1):end + 1]
    seg = seg[np.isfinite(seg) & (seg > 0)]
    return float(seg.mean()) if len(seg) else None


def _rs_prior_up(cl, lo, peak, k, bench_w, dates):
    """A: linia RS (spółka / benchmark) rośnie w trakcie wcześniejszego wzrostu (RS w szczycie > RS w dołku sprzed szczytu). None bez benchmarku."""
    if bench_w is None or k != 1 or not len(bench_w):
        return None
    try:
        b = bench_w.astype(float).reindex(pd.DatetimeIndex(dates), method="ffill").values
        i0 = max(0, peak - CUP_PRIOR_LOOKBACK)
        il = i0 + int(np.argmin(lo[i0:peak + 1]))
        if not (np.isfinite(b[peak]) and np.isfinite(b[il]) and b[peak] > 0 and b[il] > 0):
            return None
        return bool(cl[peak] / b[peak] > cl[il] / b[il])
    except Exception:
        return None


def classify_cup(hi, lo, cl, peak, end, dates, bench_w=None, k=1, vol=None, is_open=True):
    """Czy baza (lewy szczyt `peak` .. `end`) jest miseczką z rączką wg O'Neila? Zwraca dict ze szczegółami albo None.
    Warunki: wcześniejszy trend (+30 % w poprzednich 52 tyg.), głębokość 12–33 % (do 50 % przy mocnej korekcie S&P 500),
    7–65 tygodni od szczytu do prawego brzegu, kształt „U” (kilka tygodni przy dnie, dołek nie przy krawędzi),
    prawy brzeg odrabia >= 80 % głębokości (<= 12 % pod szczytem), rączka (opcjonalna) 1–10 tyg., płytsza niż 15 %
    i w górnej połowie miseczki. Kontekst rynku (spadek S&P w tym czasie) jest informacją, nie warunkiem."""
    # k = świec na tydzień (1 = wykres tygodniowy, 5 = dzienny): wszystkie progi w tygodniach skalujemy do liczby świec
    start = first_down_idx(cl, peak, end)                          # czas bazy liczymy od pierwszego tygodnia ze spadkiem
    if end - start < CUP_MIN_WEEKS * k:
        return None
    low_i = peak + 1 + int(np.argmin(lo[peak + 1:end + 1]))
    if low_i >= end:
        return None                                               # brak prawej strony
    low = float(lo[low_i])
    top = float(hi[peak])
    depth_abs = top - low
    depth = depth_abs / top * 100
    # prawy brzeg = szczyt PRZED rączką: pierwszy kolejny rekord wysokości po dołku, który już odrobił >= 80 % głębokości, leży <= 10 % pod lewym szczytem
    # i po którym następuje krótka (1–4 tyg.) przerwa / cofnięcie, zanim cena go przebije. Wcześniej brzegiem był zawsze NAJWYŻSZY szczyt po dołku
    # (często ten z dnia wybicia nad lewy szczyt), więc rączka znikała, a prawdziwy cup z rączką wychodził jako „cup bez rączki”.
    rec_idx = [j for j in range(low_i + 1, end + 1) if hi[j] >= np.max(hi[low_i + 1:j + 1])]            # kolejne rekordy wysokości po dołku (strict > w praktyce)
    r, h_end = None, end
    for a, j in enumerate(rec_idx):
        nxt = rec_idx[a + 1] if a + 1 < len(rec_idx) else end + 1
        gap_w = nxt - 1 - j                                                                              # tygodnie (świece) cofnięcia po szczycie j przed kolejnym rekordem
        if (hi[j] - low) / depth_abs < CUP_RIM_RECOVERY or (top - hi[j]) / top * 100 > CUP_RIM_MAX_GAP_PCT or j - low_i < 2 * k:
            continue
        if (CUP_HANDLE_MIN_WEEKS if k == 1 else k + 1) <= gap_w <= CUP_HANDLE_MAX_WEEKS * k and nxt <= end:             # przerwa jak rączka i potem przebicie szczytu j
            r, h_end = j, nxt - 1
            break
    if r is None:
        r = low_i + 1 + int(np.argmax(hi[low_i + 1:end + 1]))    # brak rączki w tym kształcie: brzeg = najwyższy szczyt po dołku (cup bez rączki / wada rączki)
        h_end = end
    rim = float(hi[r])
    cup_weeks = r - start
    span = r - peak
    mkt_dd = mkt_drawdown(bench_w, dates[peak], dates[r]) if bench_w is not None else None
    max_depth = CUP_MAX_DEPTH_BEAR_PCT if mkt_dd is not None and mkt_dd >= CUP_BEAR_MKT_DD else CUP_MAX_DEPTH_PCT
    if not (CUP_MIN_DEPTH_PCT <= depth <= max_depth) or not (CUP_MIN_WEEKS * k <= cup_weeks <= CUP_MAX_WEEKS * k):
        return None
    # wcześniejszy trend wzrostowy (szczyt musi być efektem wzrostu, nie odbiciem po spadku)
    prior_gain = prior_gain_pct(hi, lo, peak, k)
    if prior_gain is None or prior_gain < BASE_PRIOR_GAIN_PCT:
        return None
    # kształt „U”: dołek nie przy krawędzi, kilka tygodni w dolnej 1/3, prawa strona nie jest jednym skokiem
    pos = (low_i - peak) / span
    bottom = int(np.sum(cl[peak + 1:r + 1] <= low + depth_abs / 3))
    if not (CUP_LOW_POS[0] <= pos <= CUP_LOW_POS[1]) or bottom < max(CUP_BOTTOM_WEEKS * k, CUP_BOTTOM_FRAC * span) or r - low_i < 2 * k:
        return None
    if (rim - low) / depth_abs < CUP_RIM_RECOVERY or (top - rim) / top * 100 > CUP_RIM_MAX_GAP_PCT:
        return None
    # gładkość: brak zygzaków (odbicie w trakcie spadku / cofnięcie w trakcie odbudowy większe niż 40 % głębokości) ...
    left, right = cl[peak:low_i + 1], cl[low_i:r + 1]
    bounce = float(np.max(left - np.minimum.accumulate(left)))                  # największy rajd w trakcie spadku
    dip = float(np.max(np.maximum.accumulate(right) - right))                    # największe cofnięcie w trakcie odbudowy
    if max(bounce, dip) > CUP_MAX_RETRACE * depth_abs:
        return None
    # ... i kształt zbliżony do paraboli o ramionach w górę
    xs = np.arange(peak, r + 1, dtype=float)
    ys = cl[peak:r + 1]
    coef = np.polyfit(xs, ys, 2)
    ss_tot = float(np.sum((ys - ys.mean()) ** 2))
    fit = 1 - float(np.sum((ys - np.polyval(coef, xs)) ** 2)) / ss_tot if ss_tot > 0 else 0.0
    if coef[0] <= 0 or fit < CUP_MIN_FIT:
        return None
    handle = None
    faults = []                                                    # wady rączki (B) — baza przestaje być „cup with handle” do kupna
    hw = h_end - r
    if r < h_end:
        h_lows = lo[r + 1:h_end + 1]
        h_low = float(h_lows.min())
        h_depth = (rim - h_low) / rim * 100
        hmin, hmax = (CUP_HANDLE_MIN_WEEKS if k == 1 else k + 1), CUP_HANDLE_MAX_WEEKS * k   # dziennie: rączka > 5 sesji (k + 1 świec), do 4 tygodni
        if not (hmin <= hw <= hmax):
            faults.append(f"rączka trwa {hw if k == 1 else round(hw / k, 1)} tyg. (wymagane 1–{CUP_HANDLE_MAX_WEEKS})")
        h_max = CUP_HANDLE_MAX_DEPTH_BEAR_PCT if mkt_dd is not None and mkt_dd >= CUP_BEAR_MKT_DD else CUP_HANDLE_MAX_DEPTH_PCT
        if h_depth > h_max:
            faults.append(f"rączka głębsza niż {h_max:.0f} % ({h_depth:.1f} %)")
        if h_low < low + 0.5 * depth_abs:
            faults.append("rączka w dolnej połowie miseczki")
        ma_n = CUP_HANDLE_MA_WEEKS * k
        below_ma = [j for j in range(r + 1, h_end + 1) if j + 1 >= ma_n and cl[j] < float(cl[j + 1 - ma_n:j + 1].mean())]
        if below_ma:
            faults.append("rączka poniżej 10-tygodniowej średniej")
        if hw >= 2 and float(np.polyfit(np.arange(hw, dtype=float), h_lows.astype(float), 1)[0]) > 0:
            faults.append("rączka rośnie wzdłuż dołków (wedging handle)")
        h_low_i = r + 1 + int(np.argmin(h_lows))
        v_avg = _vol_mean(vol, r, VOL_AVG_WEEKS * k)
        if v_avg is not None and vol is not None and np.isfinite(vol[h_low_i]) and vol[h_low_i] >= v_avg:
            faults.append("brak wyschnięcia wolumenu w rączce")
        handle = {"weeks": hw if k == 1 else round(hw / k, 1), "low": _num(h_low), "depth_pct": _num(h_depth, 1),
                  "low_date": dates[h_low_i].strftime("%Y-%m-%d"),
                  "end_date": dates[h_end].strftime("%Y-%m-%d"), "end_close": _num(cl[h_end])}
    # cup bez rączki jest wciąż bazą (pivot = lewy szczyt), ale RYZYKOWNĄ: O'Neil — z rączką szansa powodzenia jest większa (końcowe wytrząśnięcie słabych rąk); `risky` zaznaczamy na wykresie
    return {"rim": _num(rim), "rim_date": dates[r].strftime("%Y-%m-%d"), "cup_weeks": cup_weeks if k == 1 else round(cup_weeks / k, 1), "handle": handle,
            "prior_gain_pct": _num(prior_gain, 0), "fit": _num(fit, 2), "rim_gap_pct": _num((top - rim) / top * 100, 1),
            "mkt_dd_pct": _num(mkt_dd, 1) if mkt_dd is not None else None,
            "mkt_ctx": bool(mkt_dd is not None and mkt_dd >= CUP_MKT_CONTEXT_DD),
            "no_handle": handle is None, "faults": faults, "handle_upper_half": bool(handle is None or handle["low"] >= low + 0.5 * depth_abs),
            "rs_prior_up": _rs_prior_up(cl, lo, peak, k, bench_w, dates)}


def zigzag_contractions(closes, pct=ZIGZAG_PCT):
    """Kolejne spadki (w %) od lokalnego szczytu do następnego dołka, liczone na zamknięciach; zmiana kierunku
    dopiero po ruchu o >= pct % (drobny szum jest ignorowany)."""
    pivots, direction = [], 0     # direction: +1 w górę (szukamy szczytu), -1 w dół (szukamy dołka)
    hi = lo = (0, closes[0]) if len(closes) else None
    for i, c in enumerate(closes[1:], 1):
        if hi is None:
            break
        if c > hi[1]:
            hi = (i, c)
        if c < lo[1]:
            lo = (i, c)
        if direction >= 0 and hi[1] > 0 and (hi[1] - c) / hi[1] * 100 >= pct:      # zakończony szczyt -> zaczyna się spadek
            pivots.append(("H", hi[1]))
            direction, lo = -1, (i, c)
        elif direction == -1 and lo[1] > 0 and (c - lo[1]) / lo[1] * 100 >= pct:   # zakończony dołek -> zaczyna się wzrost
            pivots.append(("L", lo[1]))
            direction, hi = 1, (i, c)
    if pivots and pivots[-1][0] == "H" and direction == -1:
        pivots.append(("L", lo[1]))   # trwający, jeszcze niepotwierdzony spadek też jest skurczem (aktualny stan bazy)
    drops = []
    for k in range(len(pivots) - 1):
        if pivots[k][0] == "H" and pivots[k + 1][0] == "L":
            drops.append(round(float((pivots[k][1] - pivots[k + 1][1]) / pivots[k][1] * 100), 1))
    return drops


DB_MIN_DEPTH_PCT = 15        # double bottom (W): głębokość 15–33 %, długość 7–65 tygodni
DB_MAX_DEPTH_PCT = 33
DB_MIN_WEEKS = 7
DB_MAX_WEEKS = 65            # drugie dno MUSI podciąć pierwsze (Low2 < Low1) — inaczej to wadliwe „W”
DB_MIN_LEG_WEEKS = 2         # każde dno ma kilka tygodni „oddechu” od środkowego szczytu
SAUCER_MIN_WEEKS = 20        # saucer = płytka (12–20 %), długa (od ~20 tygodni) miseczka
SAUCER_MAX_DEPTH_PCT = 20
ASC_WEEKS = (9, 18)          # ascending base: 3 kolejne korekty 10–20 % z rosnącymi dołkami w ciągu 9–16 tygodni (z lekkim zapasem)
ASC_DEPTH_PCT = (10.0, 20.0)   # trzy cofnięcia po 10–20 %
ASC_SWING_PCT = 8.0
HTF_MIN_GAIN = 2.0           # high tight flag: +100 % (x2) w 4–8 tygodni, potem korekta 10–25 % przez 3–5 tygodni
HTF_RISE_WEEKS = (4, 8)      # +100 % w 4–8 tygodni
HTF_FLAG_WEEKS = (3, 5)      # flaga 3–5 tygodni
HTF_FLAG_DEPTH_PCT = (10.0, 25.0)
BOX_WEEKS = (4, 7)           # square box (kwadratowa baza): 4–7 tygodni konsolidacji po ruchu z wcześniejszej bazy, głębokość 10–15 %
BOX_DEPTH_PCT = (10.0, 15.0)
BASE_PEAK_WINDOW_WEEKS = 75     # szczyt odniesienia bazy nie może być starszy niż CUP_MAX_WEEKS + 10 tygodni (inaczej liczymy od najwyższego High z tego okna)
IPO_MAX_WEEKS = 52           # baza po debiucie (IPO base): spółka notowana nie dłużej niż ~rok; min. 3 tygodnie od szczytu po debiucie
IPO_MIN_WEEKS = 3
CUP_HANDLE_MAX_DEPTH_BEAR_PCT = 30.0   # rączka przy dnie bessy: wyjątkowo 20–30 %
HTF_DRYUP = 0.6              # średni wolumen we fladze <= 0,6x średniego wolumenu rajdu (drastyczny zanik)
CORRIDOR_DEPTH_PCT = (5.0, 20.0)   # korytarz: zmiana ceny w oknie 5–20 % = baza / flaga (znane kryterium konsolidacji; flat wg O'Neila ma do 15 %, korytarz toleruje do 20 %)
CORRIDOR_WEEKS = (5, 12)       # długość korytarza w tygodniach
CORRIDOR_MIN_POS = 0.4         # zamknięcie w górnych 60 % korytarza (nie przy dnie)
CORRIDOR_CLOSE_RANGE_PCT = 10.0   # same ZAMKNIĘCIA tygodni mieszczą się w 10 % (ciasna konsolidacja zamknięć odróżnia bazę od zwykłej huśtawki cen)
BOX_BASE_TYPES = ("flat", "square_box")   # bazy-pudełka: dzielimy je na 3 części (cup z rączką i flaga to inna bajka — bez tego podziału)
BRK_HIGH_WEEKS = 10          # zamknięcie wybicia = najwyższe zamknięcie od 10 tygodni
BASE_TYPES_BUYABLE = ("cup", "double_bottom", "flat", "square_box", "ascending", "htf", "ipo")


def _zigzag(values, pct):
    """Przełamania trendu o co najmniej pct %: lista (indeks, wartość, 'H'/'L') na przemian szczyt/dołek; ostatni punkt to bieżące, niepotwierdzone ekstremum."""
    pts, trend, hi_i, lo_i = [], 0, 0, 0
    for i in range(1, len(values)):
        v = values[i]
        if trend == 0:
            if v > values[hi_i]:
                hi_i = i
            if v < values[lo_i]:
                lo_i = i
            if v >= values[lo_i] * (1 + pct / 100) and lo_i < i:
                pts.append((lo_i, float(values[lo_i]), "L"))
                trend, hi_i = 1, i
            elif v <= values[hi_i] * (1 - pct / 100) and hi_i < i:
                pts.append((hi_i, float(values[hi_i]), "H"))
                trend, lo_i = -1, i
        elif trend == 1:
            if v > values[hi_i]:
                hi_i = i
            elif v <= values[hi_i] * (1 - pct / 100):
                pts.append((hi_i, float(values[hi_i]), "H"))
                trend, lo_i = -1, i
        else:
            if v < values[lo_i]:
                lo_i = i
            elif v >= values[lo_i] * (1 + pct / 100):
                pts.append((lo_i, float(values[lo_i]), "L"))
                trend, hi_i = 1, i
    if trend == 1:
        pts.append((hi_i, float(values[hi_i]), "H"))
    elif trend == -1:
        pts.append((lo_i, float(values[lo_i]), "L"))
    return pts


def classify_double_bottom(hi, lo, cl, peak, end, dates, k=1):
    """Double bottom (W) wg O'Neila: drugie dno PODCINA pierwsze (wytrząśnięcie), pivot = szczyt środkowy (nie szczyt całej bazy).
    Głębokość i długość jak miseczka. Zwraca dict albo None."""
    if not (DB_MIN_WEEKS * k <= end - first_down_idx(cl, peak, end) + 1 <= DB_MAX_WEEKS * k):
        return None
    pg = prior_gain_pct(hi, lo, peak, k)
    if pg is None or pg < BASE_PRIOR_GAIN_PCT:
        return None                                              # A: wcześniejszy wzrost >= +30 %
    seg = lo[peak + 1:end + 1]
    ib = peak + 1 + int(np.argmin(seg))                         # głębsze (drugie) dno
    top = float(hi[peak])
    depth = (top - float(lo[ib])) / top * 100
    if not (DB_MIN_DEPTH_PCT <= depth <= DB_MAX_DEPTH_PCT):
        return None
    left_end = ib - DB_MIN_LEG_WEEKS * k
    if left_end <= peak + 1 or end - ib < 1:
        return None
    ia = peak + 1 + int(np.argmin(lo[peak + 1:left_end + 1]))   # pierwsze dno: najniższy Low przed drugim
    if ib - ia < DB_MIN_LEG_WEEKS * k * 2:
        return None
    first, second = float(lo[ia]), float(lo[ib])
    if second >= first:
        return None                                              # drugie dno MUSI podciąć pierwsze (wytrząśnięcie)
    im = ia + int(np.argmax(hi[ia:ib + 1]))                      # środkowy szczyt
    mid = float(hi[im])
    if mid < first * 1.08 or im - peak < k:
        return None
    if end - ib < 2 * k or float(cl[end]) < second + 0.4 * (mid - second):
        return None                                              # po drugim dnie musi być widoczne odbicie ku środkowemu szczytowi
    r2 = ib + int(np.argmax(hi[ib:end + 1]))                     # ewentualne uszko po prawej (punkt E): szczyt po drugim dnie z cofnięciem po nim
    handle_e = bool(r2 > ib and r2 < end and float(hi[r2]) >= mid)
    pivot = float(hi[r2]) if handle_e else mid
    return {"pivot": _num(pivot), "mid_date": dates[im].strftime("%Y-%m-%d"), "low1": _num(first), "low2": _num(second), "handle": handle_e,
            "undercut_pct": _num((first - second) / first * 100, 1)}


def faulty_double_bottom(hi, lo, cl, peak, end, k=1):
    """Wadliwe „W”: wszystko jak w double bottom (długość 7–65 tyg., głębokość 15–33 %, wzrost przed bazą >= +30 %, widoczny środkowy szczyt),
    ale drugie dno leży NAD pierwszym (bez podcięcia / wytrząśnięcia). Zwraca True / False."""
    if not (DB_MIN_WEEKS * k <= end - first_down_idx(cl, peak, end) + 1 <= DB_MAX_WEEKS * k):
        return False
    pg = prior_gain_pct(hi, lo, peak, k)
    if pg is None or pg < BASE_PRIOR_GAIN_PCT:
        return False
    top = float(hi[peak])
    ia = peak + 1 + int(np.argmin(lo[peak + 1:end + 1]))        # najgłębsze dno = pierwsze (drugie jest wyżej)
    if not (DB_MIN_DEPTH_PCT <= (top - float(lo[ia])) / top * 100 <= DB_MAX_DEPTH_PCT):
        return False
    start2 = ia + DB_MIN_LEG_WEEKS * k * 2
    if start2 >= end:
        return False
    ib = start2 + int(np.argmin(lo[start2:end + 1]))
    first, second = float(lo[ia]), float(lo[ib])
    if second <= first or (second - first) / first * 100 > 8.0:
        return False                                             # drugie dno ma być tuż nad pierwszym (do 8 %), inaczej to zwykła korekta
    mid = float(hi[ia:ib + 1].max())
    return mid >= first * 1.08 and ib - ia >= DB_MIN_LEG_WEEKS * k * 2


def detect_ascending_base(hi, lo, cl, dates, k=1):
    """Ascending base: trzy kolejne korekty 10–20 % z coraz wyższymi dołkami (i szczytami) w ciągu 9–16 tygodni, cena blisko ostatniego szczytu."""
    n = len(cl)
    win = min(n, ASC_WEEKS[1] * k)
    if win < ASC_WEEKS[0] * k:
        return None
    off = n - win
    zz = _zigzag(list(cl[off:]), ASC_SWING_PCT)
    # szukamy ostatniego ciągu H L H L H L (trzy pary szczyt-dołek) i bieżącego wznoszenia
    pts = [(off + i, v, t) for i, v, t in zz]
    for start in range(len(pts)):
        seq = pts[start:]
        if not seq or seq[0][2] != "H" or len(seq) < 6:
            continue
        peaks, troughs = seq[0:6:2], seq[1:6:2]
        if any(p[2] != "H" for p in peaks) or any(t[2] != "L" for t in troughs):
            continue
        depths = [(p[1] - t[1]) / p[1] * 100 for p, t in zip(peaks, troughs)]
        if not all(ASC_DEPTH_PCT[0] <= d <= ASC_DEPTH_PCT[1] for d in depths):
            continue
        if not (troughs[0][1] < troughs[1][1] < troughs[2][1]) or not (peaks[0][1] <= peaks[1][1] * 1.02 and peaks[1][1] <= peaks[2][1] * 1.02):
            continue
        span = n - 1 - peaks[0][0]
        if not (ASC_WEEKS[0] * k <= span <= ASC_WEEKS[1] * k + 3 * k):
            continue
        pg = prior_gain_pct(hi, lo, peaks[0][0], k)
        if pg is not None and pg < BASE_PRIOR_GAIN_PCT:
            continue                                             # A: wcześniejszy wzrost >= +30 %
        top = max(float(hi[peaks[0][0]:].max()), peaks[2][1])
        if float(cl[-1]) < top * 0.90:
            continue
        low = min(float(lo[peaks[0][0]:].min()), troughs[0][1])
        return {"start": dates[peaks[0][0]].strftime("%Y-%m-%d"), "end": dates[n - 1].strftime("%Y-%m-%d"), "peak": _num(top), "low": _num(low),
                "depth_pct": _num(sum(depths) / 3, 1), "weeks": round(span / k, 1) if k > 1 else span, "type": "ascending", "open": True,
                "pivot": _num(top), "contractions": [round(d, 1) for d in depths], "vcp": False}
    return None


def detect_high_tight_flag(hi, lo, cl, dates, k=1, vol=None):
    """High tight flag: akcja zyskuje 100 %+ w 4–8 tygodni, potem korekta 10–25 % przez 3–5 tygodni (flaga tuż pod szczytem). Pivot = szczyt flagi."""
    n = len(cl)
    look = 24 * k
    if n < 12 * k:
        return None
    i0 = max(0, n - look)
    ip = i0 + int(np.argmax(hi[i0:]))                            # szczyt przed flagą
    flag_len = n - 1 - ip
    if not (HTF_FLAG_WEEKS[0] * k <= flag_len <= HTF_FLAG_WEEKS[1] * k):
        return None
    j0 = max(0, ip - HTF_RISE_WEEKS[1] * k)
    il = j0 + int(np.argmin(lo[j0:ip + 1]))                      # początek rajdu
    rise = ip - il
    if rise < HTF_RISE_WEEKS[0] * k or float(hi[ip]) / float(lo[il]) < HTF_MIN_GAIN:
        return None
    flag_low = float(lo[ip + 1:].min())
    depth = (float(hi[ip]) - flag_low) / float(hi[ip]) * 100
    if not (HTF_FLAG_DEPTH_PCT[0] <= depth <= HTF_FLAG_DEPTH_PCT[1]):
        return None
    if vol is not None:                                           # E: drastyczny zanik wolumenu we fladze
        run_v, flag_v = vol[il:ip + 1], vol[ip + 1:]
        run_v, flag_v = run_v[np.isfinite(run_v) & (run_v > 0)], flag_v[np.isfinite(flag_v) & (flag_v > 0)]
        if len(run_v) and len(flag_v) and float(flag_v.mean()) > HTF_DRYUP * float(run_v.mean()):
            return None
    return {"start": dates[ip].strftime("%Y-%m-%d"), "end": dates[n - 1].strftime("%Y-%m-%d"), "peak": _num(hi[ip]), "low": _num(flag_low),
            "depth_pct": _num(depth, 1), "weeks": round(flag_len / k, 1) if k > 1 else flag_len, "type": "htf", "open": True, "pivot": _num(hi[ip]),
            "rise_pct": _num((float(hi[ip]) / float(lo[il]) - 1) * 100, 0), "rise_weeks": round(rise / k, 1) if k > 1 else rise,
            "contractions": [], "vcp": False}


def detect_ipo_base(hi, lo, cl, dates, k=1):
    """Baza po debiucie (IPO base): w pierwszych tygodniach / miesiącach notowań spółka tworzy bazę pod absolutnym maksimum od debiutu (pivot = to maksimum);
    min. IPO_MIN_WEEKS tygodni od szczytu, korekta nie głębsza niż miseczka (35 %). Wywołujemy tylko dla spółek notowanych <= IPO_MAX_WEEKS tygodni."""
    n = len(cl)
    if k != 1 or n < IPO_MIN_WEEKS + 2 or n > IPO_MAX_WEEKS:
        return None
    ip = int(np.argmax(hi))
    length = n - 1 - ip
    if length < IPO_MIN_WEEKS:
        return None
    low = float(lo[ip + 1:].min())
    depth = (float(hi[ip]) - low) / float(hi[ip]) * 100
    if not (BASE_MIN_DEPTH_PCT <= depth <= BASE_CUP_MAX_DEPTH_PCT):
        return None
    return {"start": dates[ip].strftime("%Y-%m-%d"), "end": dates[n - 1].strftime("%Y-%m-%d"), "peak": _num(hi[ip]), "low": _num(low), "depth_pct": _num(depth, 1),
            "weeks": length, "type": "ipo", "open": True, "pivot": _num(hi[ip]), "contractions": [], "vcp": False,
            "low_date": dates[ip + 1 + int(np.argmin(lo[ip + 1:]))].strftime("%Y-%m-%d"), "end_close": _num(cl[-1]), "ipo_weeks": n}


def detect_bases(ohlc, bench_w=None, k=1, ipo=False):
    """Korekty od lokalnego szczytu (High) do ponownego wybicia ponad ten szczyt (lub do dziś — wtedy open=True).
    k = świec na tydzień (1 = wykres tygodniowy, 5 = dzienny): progi w tygodniach są skalowane. Dla k > 1 `bench_w` jest ignorowany.
    Zwraca listę {start, end, peak, low, depth_pct, weeks, type, open, pivot, contractions, vcp} (rosnąco po czasie).
    pivot = szczyt bazy (punkt zakupu w terminologii MarketSmith); vcp = co najmniej 2 kolejne, coraz płytsze skurcze,
    ostatni <= 10 %. Typy: "cup" (miseczka wg O'Neila, classify_cup; z flagą saucer = płytka i długa), "double_bottom" (W z podcięciem
    pierwszego dna, pivot = środkowy szczyt), "flat" (do 15 %), "correction"/"deep" (nie bazy do zakupu). Dodatkowo, gdy
    teraz formuje się ascending base albo high tight flag, są dopisane jako ostatni element (open=True)."""
    weekly = ohlc
    hi = weekly["High"].astype(float).values
    lo = weekly["Low"].astype(float).values
    cl = weekly["Close"].astype(float).values
    op = weekly["Open"].astype(float).values if "Open" in weekly.columns else None
    vol = weekly["Volume"].astype(float).values if "Volume" in weekly.columns else None
    dates = list(weekly.index)
    n = len(hi)
    bases = []
    zz_pct = ZIGZAG_PCT if k == 1 else ZIGZAG_PCT * 1.5

    def record(peak, end, is_open):
        if end <= peak:
            return
        weeks = end - first_down_idx(cl, peak, end) + 1              # czas bazy od pierwszego tygodnia ze spadkiem zamknięcia
        low_i = peak + 1 + int(np.argmin(lo[peak + 1:end + 1]))
        low = float(lo[low_i])
        depth = (hi[peak] - low) / hi[peak] * 100
        if weeks < BOX_WEEKS[0] * k or not (BASE_MIN_DEPTH_PCT <= depth <= BASE_MAX_DEPTH_PCT):
            return
        cup = classify_cup(hi, lo, cl, peak, end, dates, bench_w if k == 1 else None, k, vol, is_open)
        faults = []
        if cup and cup["faults"]:
            faults, cup = list(cup["faults"]), None                  # wadliwy cup (B): nie jest bazą do kupna, powody trafiają do `rejection_reasons`
            faults.insert(0, "cup z wadą rączki")
        dbl = None if cup or faults else classify_double_bottom(hi, lo, cl, peak, end, dates, k)
        if not cup and not dbl and not faults and faulty_double_bottom(hi, lo, cl, peak, end, k):
            faults.append("double bottom bez podcięcia pierwszego dna (wadliwe „W”)")
        pg = prior_gain_pct(hi, lo, peak, k)
        if cup:
            kind = "cup"
        elif dbl:
            kind = "double_bottom"
        elif depth <= BASE_FLAT_MAX_DEPTH_PCT:
            if pg is not None and pg < FLAT_PRIOR_GAIN_PCT:           # D: flat base po wzroście >= +20 %
                kind = "correction"
                faults.append(f"flat base bez wcześniejszego wzrostu ≥ {FLAT_PRIOR_GAIN_PCT} % ({pg:.0f} %)")
            elif BOX_DEPTH_PCT[0] <= depth <= BOX_DEPTH_PCT[1] and BOX_WEEKS[0] * k <= weeks <= BOX_WEEKS[1] * k:
                kind = "square_box"                                      # kwadratowa baza: 4–7 tygodni, głębokość 10–15 %, po wzroście z wcześniejszej bazy
            else:
                kind = "flat"
        elif depth <= BASE_CUP_MAX_DEPTH_PCT:
            kind = "correction"
        else:
            kind = "deep"
        if weeks < BASE_MIN_WEEKS * k and kind != "square_box":
            return
        drops = zigzag_contractions(list(cl[peak:end + 1]), zz_pct)
        vcp = len(drops) >= 2 and all(drops[j + 1] < drops[j] for j in range(len(drops) - 1)) and drops[-1] <= 10
        pivot = (cup["rim"] if cup["handle"] else hi[peak]) if cup else (dbl["pivot"] if dbl else hi[peak])   # cup z rączką: górka rączki; bez rączki (ryzykowny): lewy szczyt
        bases.append({
            "start": dates[peak].strftime("%Y-%m-%d"), "end": dates[end].strftime("%Y-%m-%d"),
            "peak": _num(hi[peak]), "low": _num(low), "depth_pct": _num(depth, 1), "weeks": weeks if k == 1 else round(weeks / k, 1), "type": kind,
            "low_date": dates[low_i].strftime("%Y-%m-%d"), "end_close": _num(cl[end]),
            "open": is_open, "pivot": _num(pivot), "contractions": drops, "vcp": bool(vcp),
            **({"cup": cup, "saucer": bool(depth <= SAUCER_MAX_DEPTH_PCT and cup["cup_weeks"] >= SAUCER_MIN_WEEKS)} if cup else {}),
            **({"double_bottom": dbl} if dbl else {}),
            "prior_uptrend_pct": _num(pg, 0) if pg is not None else None,
            **({"rejection_reasons": faults} if faults else {}),
            **({"risky": True, "notes": ["ryzykowny setup: cup bez rączki — mniejsza szansa powodzenia niż z rączką (brak końcowego wytrząśnięcia); bezpieczniej poczekać na rączkę"]} if cup and cup["no_handle"] else {}),
        })

    peak = 0
    window = BASE_PEAK_WINDOW_WEEKS * k
    for j in range(1, n):
        if hi[j] > hi[peak]:          # nowy szczyt: poprzednia korekta (jeśli była) właśnie się zakończyła
            record(peak, j - 1, False)
            peak = j
        elif lo[j] <= hi[peak] * (1 - BASE_MAX_DEPTH_PCT / 100):   # krach głębszy niż każda baza: dawny szczyt przestaje być punktem odniesienia — liczymy od dołka krachu
            low_i = peak + 1 + int(np.argmin(lo[peak + 1:j + 1]))
            peak = low_i + int(np.argmax(hi[low_i:j + 1]))
        elif j - peak > window:       # szczyt starszy niż najdłuższa baza: spółka jest wciąż pod dawnym rekordem (np. sprzed lat) —
            from_i = j - window       # szczytem odniesienia staje się najwyższy High z ostatniego okna, inaczej cała historia to jedna „głęboka korekta” i nie ma żadnej bazy
            peak = from_i + int(np.argmax(hi[from_i:j + 1]))
    record(peak, n - 1, True)
    # korytarz 5–20 % (stage 2 continuation), gdy żadna kupowalna baza nie obejmuje tego okresu; nakładające się „korekty” są zastępowane
    cor = detect_corridor_base(hi, lo, cl, vol, dates, k)
    if cor:
        overlap = [b for b in bases if b["end"] >= cor["start"] and b["start"] <= cor["end"]]
        if not any(b["type"] in BASE_TYPES_BUYABLE or b.get("rejection_reasons") for b in overlap):   # baza odrzucona z powodem (np. cup z wadą rączki) zostaje — nie nadpisujemy jej korytarzem
            bases = [b for b in bases if b not in overlap] + [cor]
    # formujące się teraz: high tight flag (ma pierwszeństwo — rzadki i najsilniejszy) albo ascending base; zastępują otwartą „korektę/flat”
    extra = detect_high_tight_flag(hi, lo, cl, dates, k, vol) or detect_ascending_base(hi, lo, cl, dates, k) or (detect_ipo_base(hi, lo, cl, dates, k) if ipo else None)
    if extra:
        if bases and bases[-1]["open"] and bases[-1]["type"] in ("flat", "square_box", "correction", "deep"):
            bases.pop()
        bases.append(extra)
    mark_base_on_base(bases, k)
    annotate_base_status(bases, hi, lo, cl, vol, dates, k, op)
    return bases


def detect_corridor_base(hi, lo, cl, vol, dates, k=1):
    """Korytarz konsolidacji (stage 2 continuation): ostatnie 5–12 tygodni mieszczą się w przedziale 5–20 % (od najwyższego High do najniższego Low)
    po wcześniejszym wzroście >= +20 %. Wykrywa to, co algorytm szczyt-do-szczytu (`detect_bases`) gubi, gdy górna krawędź pudełka lekko rośnie
    (kolejne szczyty +1 %) i baza rozpada się na krótkie kawałki. Okno szukane od NAJDŁUŻSZEGO. Jeśli ostatnia świeca zamknęła się nad szczytem
    korytarza, to ona jest wybiciem i do bazy nie należy (baza kończy się tydzień wcześniej — `fresh_breakout_base` znajdzie pivot).
    Zwraca słownik bazy (jak w `detect_bases`, typ flat / square_box, `corridor`=True) albo None."""
    n = len(hi)
    if k != 1 or n < 30:
        return None
    lo_w, hi_w = CORRIDOR_WEEKS
    for e in (n - 2, n - 1):
        if e < hi_w:
            continue
        for length in range(hi_w, lo_w - 1, -1):
            s_i = e - length + 1
            if s_i < 1:
                continue
            top = float(hi[s_i:e + 1].max())
            bottom = float(lo[s_i:e + 1].min())
            depth = (top - bottom) / top * 100
            if not (CORRIDOR_DEPTH_PCT[0] <= depth <= CORRIDOR_DEPTH_PCT[1]):
                continue
            broke = float(cl[n - 1]) > top
            if e == n - 2 and not broke:
                continue                      # wersja „bez ostatniej świecy” tylko, gdy ta świeca właśnie wybiła
            if e == n - 1 and broke:
                continue
            if (float(cl[e]) - bottom) / max(top - bottom, 1e-9) < CORRIDOR_MIN_POS:
                continue
            cmax, cmin = float(cl[s_i:e + 1].max()), float(cl[s_i:e + 1].min())
            if (cmax - cmin) / cmax * 100 > CORRIDOR_CLOSE_RANGE_PCT:
                continue
            pk = s_i + int(np.argmax(hi[s_i:e + 1]))
            pg = prior_gain_pct(hi, lo, pk, k)
            if pg is None or pg < FLAT_PRIOR_GAIN_PCT:
                continue
            low_i = s_i + int(np.argmin(lo[s_i:e + 1]))
            kind = "square_box" if BOX_DEPTH_PCT[0] <= depth <= BOX_DEPTH_PCT[1] and BOX_WEEKS[0] <= length <= BOX_WEEKS[1] else "flat"
            drops = zigzag_contractions(list(cl[s_i:e + 1]), ZIGZAG_PCT)
            return {
                "start": dates[s_i].strftime("%Y-%m-%d"), "end": dates[e].strftime("%Y-%m-%d"),
                "peak": _num(top), "low": _num(bottom), "depth_pct": _num(depth, 1), "weeks": length, "type": kind,
                "low_date": dates[low_i].strftime("%Y-%m-%d"), "end_close": _num(cl[e]),
                "open": e == n - 1, "pivot": _num(top), "contractions": drops,
                "vcp": bool(len(drops) >= 2 and all(drops[j + 1] < drops[j] for j in range(len(drops) - 1)) and drops[-1] <= 10),
                "prior_uptrend_pct": _num(pg, 0), "corridor": True,
            }
    return None


def annotate_base_status(bases, hi, lo, cl, vol, dates, k=1, op=None):
    """Status bazy jak w specyfikacji z książki: WATCHLIST (jeszcze pod pivotem) / VALID_BREAKOUT (wybicie na wolumenie >= +40 %, do +5 % nad pivotem) /
    EXTENDED (> +5 % nad pivotem — nie gonić) / FAULTY_REJECTED (wada bazy, 3.–4. etap, wybicie na słabym wolumenie). Dopisuje `status`,
    `rejection_reasons`, `buy_zone_max` (pivot +5 %) i `stop_loss_8pct` (pivot −8 %). Tylko bazy do kupna (BASE_TYPES_BUYABLE) i bazy odrzucone z powodów w `rejection_reasons`."""
    idx = {pd.Timestamp(d).strftime("%Y-%m-%d"): i for i, d in enumerate(dates)}
    n = len(cl)
    for b in bases:
        reasons = list(b.get("rejection_reasons") or [])
        buyable = b["type"] in BASE_TYPES_BUYABLE
        if not buyable and not reasons:
            continue
        pivot = b.get("pivot")
        if buyable and pivot:
            b["buy_zone_max"] = _num(pivot * (1 + BUY_ZONE_MAX_PCT / 100))
            b["stop_loss_8pct"] = _num(pivot * (1 - STOP_LOSS_PCT / 100))
        if b["type"] in BOX_BASE_TYPES and pivot and b.get("low") and b["low"] < pivot and (b.get("depth_pct") or 0) <= BASE_FLAT_MAX_DEPTH_PCT:   # korytarz głębszy niż 15 % ma stop ze środka > 10 % — zostaje ogólna reguła −8 %
            # pudełko bazy (od dołka do szczytu) dzielimy na 3 równe części: górna = za wcześnie, dolna = za późno (większa presja sprzedaży i luka w dół),
            # stop stawiamy w środkowej, najczęściej na jej dolnej krawędzi
            third = (pivot - b["low"]) / 3
            b["box_thirds"] = [_num(b["low"] + third), _num(b["low"] + 2 * third)]
            b["box_stop"] = b["box_thirds"][0]
            b["box_stop_pct"] = _num((pivot - b["box_stop"]) / pivot * 100, 1)
        if buyable and b.get("stage", 1) >= 3:
            reasons.append(f"baza {b['stage']}. etapu (późna — wysoki odsetek porażek)")
        j = idx.get(b["end"], n - 1) + (0 if b["open"] else 1)       # świeca wybicia: tuż po końcu zamkniętej bazy; dla otwartej — ostatnia
        j = min(j, n - 1)
        vr = None
        if pivot and vol is not None and j >= 1:
            avg = _vol_mean(vol, j - 1, VOL_AVG_WEEKS * k)
            vr = float(vol[j]) / avg if avg and np.isfinite(vol[j]) else None
        broke = bool(pivot) and float(cl[j]) > pivot and (not b["open"] or j == n - 1)
        if buyable and broke and vr is not None and vr < BREAKOUT_VOL_MULT:
            reasons.append(f"wybicie na wolumenie < +{(BREAKOUT_VOL_MULT - 1) * 100:.0f} % ponad średnią ({vr:.2f}×)")
        if reasons:
            b["status"] = "FAULTY_REJECTED"
        elif not buyable or not pivot:
            continue
        elif b["open"] and float(cl[-1]) > pivot * (1 + BUY_ZONE_MAX_PCT / 100):
            b["status"] = "EXTENDED"
        elif broke:
            b["status"] = "VALID_BREAKOUT"
        else:
            b["status"] = "WATCHLIST"
        b["rejection_reasons"] = reasons
        if broke and vr is not None:
            b["breakout_vol_ratio"] = _num(vr, 2)
        if broke and b["type"] in BOX_BASE_TYPES and op is not None and j >= 1:
            # jakość świecy wybicia z pudełka (blueprint): górny knot, wolumen vs poprzedni tydzień, zamknięcie na 10-tygodniowym maksimum
            rng = float(hi[j] - lo[j])
            b["breakout_wick_pct"] = _num((float(hi[j]) - max(float(op[j]), float(cl[j]))) / rng * 100, 0) if rng > 0 else None
            b["breakout_vol_wow_pct"] = _num((float(vol[j]) / float(vol[j - 1]) - 1) * 100, 0) if vol is not None and vol[j - 1] and np.isfinite(vol[j - 1]) and np.isfinite(vol[j]) else None
            b["breakout_hi10"] = bool(j >= 1 and float(cl[j]) >= float(np.max(cl[max(0, j - BRK_HIGH_WEEKS):j])))


def mark_base_on_base(bases, k=1):
    """Baza na bazie (O'Neil): nowa baza do kupna zaczyna się tuż po poprzedniej kupowalnej bazie, a cena nie odleciała od jej pivotu
    (<= BOB_MAX_RUN_PCT %) i dołek nowej bazy został nad nim (>= BOB_MIN_LOW_FRAC·pivot). Dopisuje `base_on_base` (bool) i `stage`
    (który kolejny etap w łańcuchu; 1 = pierwsza baza), modyfikuje listę w miejscu."""
    prev = None
    for b in bases:
        b["base_on_base"], b["stage"] = False, 1
        if prev is not None and b["type"] in BASE_TYPES_BUYABLE and prev.get("pivot") and b.get("peak") and b.get("low"):
            gap_weeks = (pd.Timestamp(b["start"]) - pd.Timestamp(prev["end"])).days / 7
            if (0 <= gap_weeks <= BOB_MAX_GAP_WEEKS
                    and b["peak"] <= prev["pivot"] * (1 + BOB_MAX_RUN_PCT / 100)
                    and b["low"] >= prev["pivot"] * BOB_MIN_LOW_FRAC):
                b["base_on_base"], b["stage"] = True, prev["stage"] + 1
        if b["type"] in BASE_TYPES_BUYABLE:
            prev = b


# ============================================================================
# WYKRES W STYLU MARKETSMITH (docs/data/charts.json): słupki tygodniowe OHLC + wolumen,
# SMA10/SMA40 tygodniowe, linia benchmarku (S&P 500) i linia EPS kwartalnego.
# ============================================================================
def _pivot_indices(values, k, highs):
    """Indeksy lokalnych ekstremów: wartość jest największa (highs) / najmniejsza w oknie ±k świec."""
    out = []
    for i in range(k, len(values) - k):
        window = values[i - k:i + k + 1]
        if (highs and values[i] == window.max()) or (not highs and values[i] == window.min()):
            out.append(i)
    return out


def _best_line(values, pivots, check_to, last, highs, min_span, tol=TL_TOLERANCE, slope_range=None):
    """Najdłuższa prosta przez dwa pivoty (indeksy w `values`), której żadna świeca do `check_to` nie przebija o więcej
    niż tol (od góry dla oporu, od dołu dla wsparcia). Kończy się na ostatniej świecy `last`.
    slope_range = (min, max) dozwolonego nachylenia w % na świecę (względem ceny) — odrzuca np. wsparcie opadające
    stromo, gdy opór jest płaski. Zwraca (i0, y0, i1, y1, touches) albo None."""
    best = None
    for ai, a in enumerate(pivots):
        for b in pivots[ai + 1:]:
            if b - a < min_span or b > check_to or values[a] <= 0:
                continue
            slope = (values[b] - values[a]) / (b - a)
            if slope_range and not (slope_range[0] <= slope / values[a] * 100 <= slope_range[1]):
                continue
            idx = np.arange(a, check_to + 1)
            line = values[a] + slope * (idx - a)
            seg = values[a:check_to + 1]
            bad = (seg > line * (1 + tol)) if highs else (seg < line * (1 - tol))
            if bad.any() or line.min() <= 0:
                continue
            touches = sum(1 for q in pivots if a <= q <= check_to and abs(values[q] - (values[a] + slope * (q - a))) <= tol * values[q])
            cand = (a, float(values[a]), last, float(values[a] + slope * (last - a)), touches)
            if best is None or (touches, last - a) > (best[4], last - best[0]):
                best = cand
        if best is not None and best[0] == a:
            break   # najwcześniejszy punkt startowy, który coś daje — dłuższych linii już nie będzie
    return best


# Parametry wykrywania konsolidacji (świece dzienne / tygodniowe): k = okno pivotu, min/max_len = długość flagi,
# recent = ile ostatnich świec może już być wybiciem, pole_* = maszt (wzrost przed flagą), max_depth = maks. głębokość flagi,
# box_* = korytarz bez masztu (płaska, ciasna konsolidacja).
WEEKLY_FLAG = dict(k=2, min_len=3, max_len=20, recent=2, pole_lookback=12, pole_min_gain=30.0, max_depth=25.0, box_depth=15.0, box_min_len=5, vol_avg=10)   # vol_avg = ile poprzednich świec daje średni wolumen (dzienne 50 sesji, tygodniowe 10 tygodni)
FLAG_PARALLEL_PCT = 0.3          # wsparcie może odbiegać nachyleniem od oporu o tyle (% na świecę)
FLAG_MAX_SLOPE_PCT = 0.15        # górna linia flagi może co najwyżej lekko rosnąć (% na świecę)


def _line_value(ln, i):
    return ln[1] + (ln[3] - ln[1]) * (i - ln[0]) / max(1, ln[2] - ln[0])


def volume_ratio(vol, i, avg_bars):
    """Wolumen świecy i / średnia z `avg_bars` poprzednich świec (None, gdy za mało historii)."""
    prev = vol[max(0, i - avg_bars):i]
    return float(vol[i] / prev.mean()) if len(prev) >= 10 and prev.mean() > 0 else None


def detect_level_break(ohlc, level, recent, avg_bars, tf):
    """Wybicie poziomu (np. pivotu bazy) wg O'Neila: zamknięcie nad `level` w jednej z ostatnich `recent` świec i nadal nad nim,
    na wolumenie >= 1,5x średniej z `avg_bars` poprzednich świec. Zwraca {state: "wybicie"|"bez wolumenu", date, vol_ratio, tf} albo None
    (cena pod poziomem, albo zamknięcia nad nim sprzed `recent` świec). Przebicie samego maksimum bez zamknięcia nie liczy się."""
    n = len(ohlc)
    if n < 12 or not level or level <= 0:
        return None
    cl, vol = ohlc["Close"].astype(float).values, ohlc["Volume"].astype(float).values
    dates = [d.strftime("%Y-%m-%d") for d in pd.DatetimeIndex(ohlc.index)]
    broke = [i for i in range(max(0, n - recent), n) if cl[i] > level]
    if not broke or cl[-1] <= level:
        return None
    ratios = [(i, volume_ratio(vol, i, avg_bars)) for i in broke]
    hit = next(((i, r) for i, r in ratios if r is not None and r >= TL_VOLUME_MULT), None)
    if hit:
        return {"state": "wybicie", "date": dates[hit[0]], "vol_ratio": _num(hit[1], 1), "tf": tf}
    r0 = ratios[0][1]
    return {"state": "bez wolumenu", "date": dates[broke[0]], "vol_ratio": _num(r0, 1) if r0 is not None else None, "tf": tf}


def volume_surge(df, recent=5, avg_bars=TL_VOLUME_AVG_BARS):
    """Najwyższy z ostatnich `recent` dziennych wolumenów względem średniej z `avg_bars` poprzednich sesji (None bez historii)."""
    vol = df["Volume"].astype(float).values
    ratios = [volume_ratio(vol, i, avg_bars) for i in range(max(0, len(vol) - recent), len(vol))]
    ratios = [r for r in ratios if r is not None]
    return _num(max(ratios), 1) if ratios else None


def detect_consolidation(ohlc, cfg):
    """Flaga (maszt + opadająca/płaska konsolidacja) albo korytarz poziomy z liniami oporu i wsparcia ograniczonymi do
    samej konsolidacji (nie przez cały wykres) oraz stanem wybicia. Zwraca None, gdy nie ma wzorca.
    Wynik: {lines, pattern, state, breakout, info}; info = {type, pole_gain, pole_start, pole_end, pole_low, pole_high,
    length, depth, vol_ratio (średni wolumen flagi / masztu), touches}. breakout = {date, vol_ratio, confirmed}
    (wolumen pierwszej świecy nad oporem / średnia z 50 poprzednich)."""
    n = len(ohlc)
    if n < cfg["min_len"] + cfg["recent"] + 5:
        return None
    dates = [d.strftime("%Y-%m-%d") for d in pd.DatetimeIndex(ohlc.index)]
    hi, lo, cl, vol = (ohlc[c].astype(float).values for c in ("High", "Low", "Close", "Volume"))
    last, recent = n - 1, cfg["recent"]
    end = last - recent                        # ostatnia świeca, która musi mieścić się w konsolidacji
    pivots_hi = _pivot_indices(hi, cfg["k"], True)
    pivots_lo = _pivot_indices(lo, cfg["k"], False)
    best = None
    for s in pivots_hi:
        length = end - s + 1
        if length < cfg["min_len"] or length > cfg["max_len"]:
            continue
        seg_hi, seg_lo = hi[s:end + 1], lo[s:end + 1]
        depth = (seg_hi.max() - seg_lo.min()) / seg_hi.max() * 100
        pole_from = max(0, s - cfg["pole_lookback"])
        pi = pole_from + int(np.argmin(lo[pole_from:s + 1]))
        pole_gain = (hi[s] / lo[pi] - 1) * 100 if lo[pi] > 0 else 0
        is_flag = s - pi >= 3 and pole_gain >= cfg["pole_min_gain"] and depth <= min(cfg["max_depth"], pole_gain * 0.6)
        is_box = depth <= cfg["box_depth"] and length >= cfg["box_min_len"]
        if not (is_flag or is_box):
            continue
        res = _best_line(hi, [q for q in pivots_hi if s <= q <= end], end, last, True, 2)
        if res is None:
            continue
        slope = (res[3] - res[1]) / res[1] / max(1, res[2] - res[0]) * 100
        if slope > FLAG_MAX_SLOPE_PCT or (is_flag and slope < -1.5):
            continue
        sup = _best_line(lo, [q for q in pivots_lo if s <= q <= end], end, last, False, 2,
                         slope_range=(slope - FLAG_PARALLEL_PCT, slope + FLAG_PARALLEL_PCT))   # wsparcie ~równoległe do oporu
        score = (is_flag, res[4] + (sup[4] if sup else 0), length)
        if best is None or score > best[0]:
            best = (score, s, pi, pole_gain, depth, length, res, sup, is_flag)
    if best is None:
        return None
    _, s, pi, pole_gain, depth, length, res, sup, is_flag = best

    lines = [{"kind": "res", "x0": dates[res[0]], "y0": _num(res[1]), "x1": dates[last], "y1": _num(res[3]), "touches": res[4]}]
    if sup:
        lines.append({"kind": "sup", "x0": dates[sup[0]], "y0": _num(sup[1]), "x1": dates[last], "y1": _num(sup[3]), "touches": sup[4]})

    # Wybicie wg O'Neila = ZAMKNIĘCIE (dzienne albo tygodniowe) nad linią oporu na podwyższonym wolumenie (>= 1,5x średniej).
    # Samo przebicie maksimum w trakcie świecy to nie wybicie; zamknięcie nad linią bez wolumenu to state "bez wolumenu";
    # a jeśli cena wróciła pod linię, wybicie się nie utrzymało.
    state, breakout = None, None
    avg_bars = cfg.get("vol_avg", TL_VOLUME_AVG_BARS)
    broke = [i for i in range(last - recent + 1, n) if cl[i] > _line_value(res, i)]
    if broke and cl[last] > _line_value(res, last):
        ratios = [(i, volume_ratio(vol, i, avg_bars)) for i in broke]
        hit = next(((i, r) for i, r in ratios if r is not None and r >= TL_VOLUME_MULT), None)
        if hit:
            state, breakout = "wybicie", {"date": dates[hit[0]], "vol_ratio": _num(hit[1], 1), "confirmed": True}
        else:
            r0 = ratios[0][1]
            state, breakout = "bez wolumenu", {"date": dates[broke[0]], "vol_ratio": _num(r0, 1) if r0 is not None else None, "confirmed": False}
    elif cl[-1] < res[3] and (res[3] / cl[-1] - 1) * 100 <= TL_NEAR_PCT:
        state = "przy oporze"

    pole_vol = vol[pi:s + 1].mean() if s >= pi else 0
    flag_vol = vol[s + 1:end + 1].mean() if end > s else 0
    info = {"type": "flaga" if is_flag else "korytarz", "pole_gain": _num(pole_gain, 0) if is_flag else None,
            "pole_start": dates[pi] if is_flag else None, "pole_end": dates[s],
            "pole_low": _num(lo[pi]) if is_flag else None, "pole_high": _num(hi[s]),
            "length": int(length), "depth": _num(depth, 1),
            "vol_ratio": _num(flag_vol / pole_vol, 1) if is_flag and pole_vol > 0 else None, "touches": res[4]}
    return {"lines": lines, "pattern": info["type"], "state": state, "breakout": breakout, "info": info}


def weekly_ohlcv(df, last_date=None):
    """Dzienne świece -> tygodniowe (piątek). Ostatni, niepełny tydzień dostaje datę ostatniej sesji."""
    df = df.copy()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    week = df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    week = week.dropna(subset=["Close"])
    last = pd.Timestamp(last_date) if last_date is not None else df.index[-1]
    week.index = pd.DatetimeIndex([min(d, last) for d in week.index])
    return week[~week.index.duplicated(keep="last")]


def _series(values, digits=2):
    return [_num(v, digits) for v in values]


def build_chart(weekly, weeks):
    """Tablice (wyrównane do wspólnej listy `weeks`, null dla brakujących tygodni) dla jednej spółki."""
    w = weekly.reindex(pd.DatetimeIndex(weeks))
    close_all = weekly["Close"]
    sma10 = close_all.rolling(10).mean().reindex(w.index)
    sma40 = close_all.rolling(40).mean().reindex(w.index)
    return {
        "o": _series(w["Open"]), "h": _series(w["High"]), "l": _series(w["Low"]), "c": _series(w["Close"]),
        "v": [None if pd.isna(x) else int(round(x / 1000)) for x in w["Volume"]],  # wolumen w tysiącach
        "sma10": _series(sma10), "sma40": _series(sma40),
    }


def rs_line_flags(close, bench_close, window=RS_HIGH_SESSIONS):
    """Linia RS (cena / S&P 500) i flagi: rs_hi = RS wyższe niż w poprzednich `window` świecach (cały dostępny zapis,
    nie tylko widoczne okno), px_hi = to samo dla ceny. Zwraca (rs, rs_hi, px_hi) jako serie."""
    c = close.astype(float)
    b = bench_close.astype(float).reindex(c.index).ffill()
    rs = (c / b).replace([np.inf, -np.inf], np.nan)
    need = int(window * 0.8)
    rs_prev = rs.shift(1).rolling(window, min_periods=need).max()
    px_prev = c.shift(1).rolling(window, min_periods=need).max()
    return rs, (rs >= rs_prev) & rs_prev.notna(), (c >= px_prev) & px_prev.notna()


def rs_line_summary(rs, rs_hi, px_hi, window=RS_HIGH_SESSIONS, recent=RS_RECENT_BARS):
    """Stan linii RS na dziś: 'przed ceną' (RS na maksimum 52 tyg., cena jeszcze nie), 'na szczycie' (oba) albo None;
    do tego odległość RS od jego maksimum (%)."""
    hi = bool(rs_hi.tail(recent).any())
    px = bool(px_hi.tail(recent).any())
    tail = rs.dropna().tail(window)
    dist = (tail.iloc[-1] / tail.max() - 1) * 100 if len(tail) else None
    state = ("przed ceną" if not px else "na szczycie") if hi else None
    return {"state": state, "dist_pct": _num(dist, 1)}


def eps_quarters(rows):
    """rows: [{'date','eps','est'}...] z Yahoo (eps=None dla przyszłych). -> (zrealizowane kwartały z YoY %, następna prognoza).
    YoY = (EPS − EPS rok wcześniej) / |EPS rok wcześniej| · 100; None, gdy brak/zero poprzedniego."""
    reported = sorted((r for r in rows if r.get("eps") is not None), key=lambda r: r["date"])
    out = []
    for r in reported:
        d = pd.Timestamp(r["date"])
        prev = next((p for p in reported if 330 <= (d - pd.Timestamp(p["date"])).days <= 400), None)
        yoy = None
        if prev and prev["eps"]:
            yoy = _num((r["eps"] - prev["eps"]) / abs(prev["eps"]) * 100, 0)
        out.append({"d": r["date"], "e": _num(r["eps"]), "g": yoy})
    # t = suma EPS z 4 ostatnich kwartałów (TTM) — "linia zysków" jak w MarketSmith/MarketSurge; None, gdy brakuje któregoś z 4 kwartałów
    for k, q in enumerate(out):
        window = out[k - 3:k + 1] if k >= 3 else []
        q["t"] = _num(sum(x["e"] for x in window)) if len(window) == 4 and all(x["e"] is not None for x in window) else None
    upcoming = sorted((r for r in rows if r.get("eps") is None and r.get("est") is not None), key=lambda r: r["date"])
    nxt = {"d": upcoming[0]["date"], "e": _num(upcoming[0]["est"])} if upcoming else None
    if nxt:
        last3 = out[-3:]
        nxt["t"] = _num(nxt["e"] + sum(x["e"] for x in last3)) if len(last3) == 3 and nxt["e"] is not None and all(x["e"] is not None for x in last3) else None
    return out, nxt


def shares_change_pct(shares):
    """Zmiana liczby akcji (%) między najnowszym odczytem a odczytem sprzed ok. roku; ujemna = skup akcji (buyback). shares = Series
    (indeks = daty) z yfinance get_shares_full. None, gdy historia jest krótsza niż ~10 miesięcy albo brak danych."""
    if shares is None or len(shares) < 2:
        return None
    ser = shares.dropna().astype(float)
    ser = ser[ser > 0]
    if len(ser) < 2:
        return None
    ser.index = pd.DatetimeIndex(ser.index).tz_localize(None)
    ser = ser.sort_index()
    last_d = ser.index[-1]
    old = ser[ser.index <= last_d - pd.Timedelta(days=300)]
    if not len(old):
        return None
    target = last_d - pd.Timedelta(days=365)
    base = float(old.iloc[int(np.argmin(np.abs((old.index - target).days)))])   # odczyt najbliższy sprzed roku
    return _num((float(ser.iloc[-1]) / base - 1) * 100, 1)


def fetch_eps_one(ticker):
    """-> {"rows": historia raportów EPS, "shares_chg_pct": zmiana liczby akcji r/r albo None} (jedno pobranie na spółkę)."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    rows = _fetch_eps_rows(t)
    try:
        shares = shares_change_pct(t.get_shares_full(start=(datetime.now(timezone.utc) - pd.Timedelta(days=430)).strftime("%Y-%m-%d")))
    except Exception:
        shares = None
    return {"rows": rows, "shares_chg_pct": shares}


def _fetch_eps_rows(t):
    ed = t.get_earnings_dates(limit=40)
    if ed is None or ed.empty:
        return []
    rows = []
    for ts, r in ed.iterrows():
        rep, est = r.get("Reported EPS"), r.get("EPS Estimate")
        rows.append({"date": pd.Timestamp(ts).strftime("%Y-%m-%d"),
                     "eps": None if pd.isna(rep) else float(rep), "est": None if pd.isna(est) else float(est)})
    return rows


def update_eps_cache(tickers, cache_path=EPS_CACHE_PATH, now=None, fetch=fetch_eps_one,
                     max_age_days=EPS_CACHE_MAX_AGE_DAYS, time_budget_s=EPS_TIME_BUDGET_S):
    """Cache {ticker: {fetched, rows}} w JSON (docs/data/eps_cache.json) — odświeża tylko wpisy starsze niż max_age_days.
    Błąd pojedynczego tickera albo limit czasu nigdy nie przerywa pipeline'u (brak EPS = wykres bez dolnego panelu)."""
    from concurrent.futures import ThreadPoolExecutor
    import time
    now = pd.Timestamp(now if now is not None else datetime.now(timezone.utc)).tz_localize(None)
    try:
        cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        cache = {}
    stale = [t for t in tickers
             if t not in cache or cache[t].get("v") != EPS_CACHE_VERSION or (now - pd.Timestamp(cache[t].get("fetched", "1970-01-01"))).days >= max_age_days]
    if stale:
        print(f"⏳ EPS: pobieram historię dla {len(stale)} spółek (limit {time_budget_s}s)...")
        started = time.time()

        def work(t):
            if time.time() - started > time_budget_s:
                return t, None
            try:
                return t, fetch(t)
            except Exception:
                return t, None
        with ThreadPoolExecutor(EPS_WORKERS) as pool:
            for t, res in pool.map(work, stale):
                if res is not None:
                    rows, extra = (res.get("rows", []), {k: v for k, v in res.items() if k != "rows"}) if isinstance(res, dict) else (res, {})
                    cache[t] = {"fetched": now.strftime("%Y-%m-%d"), "rows": rows, "v": EPS_CACHE_VERSION, **extra}
    cache = {t: v for t, v in cache.items() if t in set(tickers) or (now - pd.Timestamp(v.get("fetched", "1970-01-01"))).days <= CACHE_KEEP_DAYS}   # cache dzielą oba skanery — nie kasujemy cudzych wpisów
    out = Path(cache_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return cache


# ============================================================================
# ESTYMATY ANALITYKÓW (Yahoo przez yfinance): cena celu, konsensus EPS i jego rewizje — jak linie "EPS Consensus" na Zacks
# ============================================================================
def _clean(v, digits=4):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if (f != f) else round(f, digits)


def fetch_estimates_one(ticker):
    """Surowe dane Yahoo dla jednej spółki: {pt, trend, est, rev} (każde może być puste)."""
    import yfinance as yf
    t = yf.Ticker(ticker)

    def safe(fn):
        try:
            return fn()
        except Exception:
            return None

    def frame(df):
        if df is None or getattr(df, "empty", True):
            return {}
        return {str(k): {c: _clean(v) for c, v in row.items() if c != "currency"} for k, row in df.to_dict("index").items()}

    pt = safe(t.get_analyst_price_targets)
    return {
        "pt": {k: _clean(pt.get(k), 2) for k in ("low", "mean", "median", "high")} if isinstance(pt, dict) else None,
        "trend": frame(safe(t.get_eps_trend)),
        "est": frame(safe(t.get_earnings_estimate)),
        "rev": frame(safe(t.get_eps_revisions)),
    }


def build_estimate_entry(raw, prev, today):
    """Łączy surowe dane Yahoo z poprzednim wpisem: historia konsensusu EPS rośnie z każdym pobraniem (punkty sprzed 7/30/60/90 dni
    z `get_eps_trend` zasilają pierwszy przebieg). Wpis: {f: data pobrania, pt: {low, mean, median, high}, p: {okres: {...}}}."""
    today = pd.Timestamp(today).normalize()
    entry = {"f": today.strftime("%Y-%m-%d"), "pt": raw.get("pt") or None, "p": {}}
    for period in EST_PERIODS:
        tr, es, rv = (raw.get(k, {}).get(period) or {} for k in ("trend", "est", "rev"))
        if not tr and not es:
            continue
        old = ((prev or {}).get("p", {}).get(period) or {}).get("h") or []
        hist = {d: v for d, v in old}
        for key, days in EST_SEED_DAYS.items():                      # punkty wsteczne tylko, gdy ich jeszcze nie mamy
            v = tr.get(key)
            if v is not None:
                hist.setdefault((today - pd.Timedelta(days=days)).strftime("%Y-%m-%d"), v)
        cur = tr.get("current", es.get("avg"))
        if cur is not None:
            hist[today.strftime("%Y-%m-%d")] = cur                    # dzisiejsza wartość zawsze nadpisuje
        cutoff = (today - pd.Timedelta(days=EST_HISTORY_DAYS)).strftime("%Y-%m-%d")
        entry["p"][period] = {
            "avg": es.get("avg", cur), "low": es.get("low"), "high": es.get("high"), "n": es.get("numberOfAnalysts"),
            "g": es.get("growth"), "ya": es.get("yearAgoEps"),
            "u7": rv.get("upLast7days"), "u30": rv.get("upLast30days"), "d30": rv.get("downLast30days"), "d7": rv.get("downLast7Days"),
            "h": [[d, hist[d]] for d in sorted(hist) if d >= cutoff],
        }
    return entry


def _rev_pct(hist, days, today):
    """Zmiana konsensusu (%) względem punktu sprzed ~`days` dni (najbliższy wcześniejszy punkt historii)."""
    if not hist:
        return None
    last = hist[-1][1]
    target = (pd.Timestamp(today) - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    older = [v for d, v in hist if d <= target]
    base = older[-1] if older else None
    return _num((last - base) / abs(base) * 100, 1) if base else None


def estimate_fields(entry, price, today=None):
    """Płaskie pola do tabeli (watchlist.json): cena celu i upside, rewizje konsensusu EPS bieżącego/następnego roku, liczba rewizji."""
    out = {"pt_mean": None, "pt_low": None, "pt_high": None, "pt_upside_pct": None, "eps_rev30_pct": None, "eps_rev90_pct": None, "eps1_rev30_pct": None,
           "rev_up30": None, "rev_down30": None, "analysts": None}
    if not entry:
        return out
    today = today or entry.get("f")
    pt = entry.get("pt") or {}
    if pt.get("mean") and price:
        out["pt_mean"] = _num(pt["mean"])
        out["pt_upside_pct"] = _num((pt["mean"] / price - 1) * 100, 1)
        out["pt_low"], out["pt_high"] = _num(pt.get("low")), _num(pt.get("high"))
    fy0, fy1 = entry["p"].get("0y") or {}, entry["p"].get("+1y") or {}
    out["eps_rev30_pct"] = _rev_pct(fy0.get("h"), 30, today)
    out["eps_rev90_pct"] = _rev_pct(fy0.get("h"), 90, today)
    out["eps1_rev30_pct"] = _rev_pct(fy1.get("h"), 30, today)
    out["rev_up30"], out["rev_down30"], out["analysts"] = fy0.get("u30"), fy0.get("d30"), fy0.get("n")
    return out


def update_estimates(tickers, path=ESTIMATES_PATH, now=None, fetch=fetch_estimates_one, max_age_days=EST_MAX_AGE_DAYS,
                     time_budget_s=EST_TIME_BUDGET_S):
    """docs/data/estimates.json = {updated, stocks: {ticker: wpis}}; odświeża wpisy starsze niż max_age_days (limit czasu i błędy
    pojedynczych spółek nigdy nie przerywają pipeline'u — brak wpisu = brak estymat na wykresie)."""
    from concurrent.futures import ThreadPoolExecutor
    import time
    now = pd.Timestamp(now if now is not None else datetime.now(timezone.utc)).tz_localize(None)
    try:
        stocks = json.loads(Path(path).read_text(encoding="utf-8")).get("stocks", {})
    except (FileNotFoundError, ValueError):
        stocks = {}
    stale = [t for t in tickers if t not in stocks or (now - pd.Timestamp(stocks[t].get("f", "1970-01-01"))).days >= max_age_days]
    if stale:
        print(f"⏳ Estymaty analityków: pobieram {len(stale)} spółek (limit {time_budget_s}s)...")
        started = time.time()

        def work(t):
            if time.time() - started > time_budget_s:
                return t, None
            try:
                return t, fetch(t)
            except Exception:
                return t, None
        with ThreadPoolExecutor(EPS_WORKERS) as pool:
            for t, raw in pool.map(work, stale):
                if raw is not None:
                    stocks[t] = build_estimate_entry(raw, stocks.get(t), now)
    stocks = {t: v for t, v in stocks.items() if t in set(tickers) or (now - pd.Timestamp(v.get("f", "1970-01-01"))).days <= CACHE_KEEP_DAYS}
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"updated": now.strftime("%Y-%m-%d"), "stocks": stocks}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return stocks


def build_charts(tickers, frames, benchmark_df, eps_cache, now_utc=None, n_weeks=CHART_WEEKS):
    """Struktura docs/data/charts.json: wspólna lista tygodni + S&P 500 + wykres każdej spółki."""
    bench = drop_incomplete_bar(benchmark_df, now_utc) if benchmark_df is not None and len(benchmark_df) else None
    last_date = None
    cleaned = {}
    for t in tickers:
        if t in frames:
            cleaned[t] = drop_incomplete_bar(frames[t], now_utc)
    if bench is not None:
        last_date = pd.DatetimeIndex(bench.index).tz_localize(None).normalize()[-1]
    elif cleaned:
        last_date = max(pd.DatetimeIndex(df.index).tz_localize(None).normalize()[-1] for df in cleaned.values())
    if last_date is None:
        return None
    ref = weekly_ohlcv(bench, last_date) if bench is not None else weekly_ohlcv(next(iter(cleaned.values())), last_date)
    weeks = list(ref.index[-n_weeks:])
    payload = {
        "benchmark": BENCHMARK if bench is not None else None,
        "weeks": [d.strftime("%Y-%m-%d") for d in weeks],
        "spx": _series(ref["Close"].reindex(pd.DatetimeIndex(weeks))) if bench is not None else None,
        "stocks": {},
    }
    bench_w = ref["Close"].astype(float) if bench is not None else None
    bench_d = None
    if bench is not None:
        bench_d = bench["Close"].astype(float).set_axis(pd.DatetimeIndex(bench.index).tz_localize(None).normalize()).groupby(level=0).last()
    for t, df in cleaned.items():
        chart = build_chart(weekly_ohlcv(df, last_date).tail(n_weeks + 80), weeks)
        quarters, nxt = eps_quarters((eps_cache.get(t) or {}).get("rows", []))
        first = payload["weeks"][0]
        wk = weekly_ohlcv(df, last_date).tail(n_weeks + 80)   # +80 tygodni rozgrzewki średnich / historii baz
        all_bases = detect_bases(wk, bench_w, ipo=len(wk) <= IPO_MAX_WEEKS)
        chart["bases"] = [b for b in all_bases if b["end"] >= first][-BASE_MAX_SHOWN:]
        chart["splits"] = [{"d": d, "r": r} for d, r in (frames[t].attrs.get("splits") or []) if d >= first]
        chart["climax"] = detect_climax_top(wk, all_bases)
        chart["eps"] = [q for q in quarters if q["d"] >= first]
        chart["eps_next"] = nxt
        if bench_d is not None:
            dd = df.copy()
            dd.index = pd.DatetimeIndex(dd.index).tz_localize(None).normalize()
            dd = dd[~dd.index.duplicated(keep="last")]
            rs, rs_hi, px_hi = rs_line_flags(dd["Close"], bench_d)
            chart["rs_line"] = rs_line_summary(rs, rs_hi, px_hi)   # stan linii RS liczymy na dziennych zamknięciach (ostatnie 5 sesji), na wykresie rysujemy tygodniową
            wk_c = wk["Close"]
            wrs, wrs_hi, wpx_hi = rs_line_flags(wk_c, bench_d, window=52)
            widx = pd.DatetimeIndex(payload["weeks"])
            chart["rs_hi"] = [int(bool(v)) for v in wrs_hi.reindex(widx).fillna(False)]
            chart["px_hi"] = [int(bool(v)) for v in wpx_hi.reindex(widx).fillna(False)]
        chart["tl"] = detect_consolidation(wk, WEEKLY_FLAG)
        chart["distribution"] = detect_distribution_week(wk)
        payload["stocks"][t] = chart
    return payload


# ============================================================================
# SKŁADANIE I ZAPIS
# ============================================================================
def weekly_close(df):
    """Tygodniowe (piątek) zamknięcia z dziennych świec; None, gdy brak danych."""
    if df is None or not len(df):
        return None
    close = df["Close"].astype(float).copy()
    close.index = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
    return close.resample("W-FRI").last().dropna()


def finviz_upside(target, price):
    """Upside do średniej ceny celu z Finviz (%): (cel / cena − 1)·100; None bez ceny lub celu."""
    if not target or not price or target <= 0 or price <= 0:
        return None
    return _num((target / price - 1) * 100, 1)


def institutional_flag(own, trans):
    """I z CANSLIM (uproszczenie; O'Neil patrzy na liczbę i jakość funduszy, Finviz daje tylko % akcji i jego zmianę):
    True = własność instytucji w przedziale [INST_MIN_OWN, INST_MAX_OWN] % i dodatnia zmiana w ostatnim kwartale (napływ);
    False = za mało, odpływ albo przesadne obłożenie (> INST_MAX_OWN %); None = brak danych albo własność > 100 % (dane niewiarygodne)."""
    if own is None or trans is None or own > INST_DATA_MAX:
        return None
    return bool(INST_MIN_OWN <= own <= INST_MAX_OWN and trans > 0)


def build_stocks(finviz_rows, frames, now_utc=None, bench_df=None):
    stocks = []
    bench_w = weekly_close(drop_incomplete_bar(bench_df, now_utc)) if bench_df is not None and len(bench_df) else None
    for row in finviz_rows:
        df = frames.get(row["ticker"])
        if df is None:
            continue
        metrics = compute_metrics(drop_incomplete_bar(df, now_utc), bench_w)
        if metrics is None:
            continue
        stock = {"ticker": row["ticker"]}
        stock.update({k: row.get(k) for k in FINVIZ_KEYS})
        stock.update(metrics)
        stock["finviz_upside_pct"] = finviz_upside(stock.get("finviz_target"), stock.get("price"))
        stock["inst_sponsor"] = institutional_flag(stock.get("inst_own"), stock.get("inst_trans"))
        stocks.append(stock)
    add_rs_rating(stocks)
    add_accdis_rating(stocks)
    add_group_strength(stocks)
    return stocks


def load_previous(path=OUTPUT_PATH):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("stocks") else None


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


RAW_DIR = ROOT / "raw"       # migawka pobranych danych (Finviz, ceny, kurs) — krok „pobierz” zapisuje, krok „policz” czyta; poza gitem (workflow trzyma ją w gałęzi raw-data)
RAW_VERSION = 1
RAW_PROFILE = "canslim"      # nazwa migawki raw/canslim.pkl.gz (jedna lista)


def raw_path(profile, raw_dir=None):
    return Path(raw_dir or RAW_DIR) / f"{profile}.pkl.gz"


def save_raw(raw, profile, raw_dir=None):
    """Zapisuje migawkę pobranych danych (słownik z DataFrame'ami; pickle zachowuje też df.attrs[\"splits\"])."""
    import gzip
    import pickle
    path = raw_path(profile, raw_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb", compresslevel=6) as f:
        pickle.dump({"version": RAW_VERSION, **raw}, f, protocol=pickle.HIGHEST_PROTOCOL)
    return path


def load_raw(profile, raw_dir=None):
    """Wczytuje migawkę; None, gdy jej nie ma albo ma inną wersję. Plik pochodzi z własnego repozytorium (workflow zapisuje go sam)."""
    import gzip
    import pickle
    path = raw_path(profile, raw_dir)
    try:
        with gzip.open(path, "rb") as f:
            raw = pickle.load(f)
    except (FileNotFoundError, EOFError, OSError, pickle.UnpicklingError):
        return None
    return raw if isinstance(raw, dict) and raw.get("version") == RAW_VERSION else None


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def run(output_path=None, skip_finviz=False, max_tickers=None, charts_path=None, eps_cache_path=None, stage="all", raw_dir=None, save_snapshot=False):
    """Jedna lista: filtr CANSLIM z finviz_screen.json, ceny, EPS, estymaty, wykresy wszystkich spółek -> watchlist.json + charts.json.
    Zakładka Qullamaggie w aplikacji tylko inaczej filtruje i sortuje te same spółki (płynność, ADR, cena / minimum).
    stage: "all" (pobierz i policz — jak dotąd), "fetch" (tylko pobranie: Finviz, ceny, kurs, EPS, estymaty -> migawka w raw_dir),
    "compute" (tylko obliczenia z zapisanej migawki, bez sieci). save_snapshot (stage "all"): oprócz liczenia zapisuje też migawkę pobranych danych."""
    output_path = output_path or OUTPUT_PATH
    cfg = finviz.load_config()
    max_tickers = max_tickers or cfg["max_tickers"]
    eps_cache_path = eps_cache_path or Path(output_path).parent / "eps_cache.json"
    previous = load_previous(output_path)
    finviz_rows, finviz_total, finviz_stale = [], None, False
    frames, benchmark_df, nasdaq_df, fx, now_utc = None, None, None, None, None
    if stage == "compute":
        raw = load_raw(RAW_PROFILE, raw_dir)
        if raw is None:
            print(f"❌ Brak migawki danych ({raw_path(RAW_PROFILE, raw_dir)}) — najpierw krok pobierania (--fetch-only).")
            return 1
        finviz_rows, finviz_total, finviz_stale = raw["finviz_rows"], raw.get("finviz_total"), raw.get("finviz_stale", False)
        frames, benchmark_df, nasdaq_df, fx = raw["frames"], raw.get("benchmark"), raw.get("nasdaq"), raw.get("fx")
        now_utc = pd.Timestamp(raw["fetched_at"])        # „teraz” z chwili pobrania: wynik nie zależy od godziny liczenia
        print(f"ℹ️  Liczę z migawki z {raw['fetched_at']} ({len(frames)} spółek) — bez pobierania.")

    if stage != "compute" and not skip_finviz:
        try:
            finviz_rows, finviz_total = finviz.fetch_watchlist(cfg["filters"], max_tickers)   # oba skanery pobierają wszystkie widoki (fundamenty, wycena, analitycy)
        except Exception as e:
            print(f"⚠️  Finviz niedostępny ({e}).")
        if len(finviz_rows) < finviz.MIN_TICKERS:
            print(f"⚠️  Finviz zwrócił {len(finviz_rows)} spółek (<{finviz.MIN_TICKERS}) — wygląda na blokadę/zmianę strony.")
            finviz_rows = []
    if stage != "compute" and not finviz_rows:
        if previous is None:
            print("❌ Brak listy z Finviz i brak poprzedniego watchlist.json — nie ma co liczyć.")
            return 1
        print("ℹ️  Używam listy spółek (i danych Finviz) z poprzedniego watchlist.json.")
        finviz_rows = [{k: v for k, v in s.items() if k == "ticker" or k in FINVIZ_KEYS} for s in previous["stocks"]]
        finviz_total, finviz_stale = previous.get("finviz_total"), True
    elif stage != "compute":
        print(f"✅ Finviz: {len(finviz_rows)} spółek (filtry: {cfg['filters']}).")

    tickers = [r["ticker"] for r in finviz_rows]
    if stage != "compute":
        frames = download_prices(tickers)
    coverage = len(frames) / len(tickers) if tickers else 0
    print(f"ℹ️  Ceny dla {len(frames)}/{len(tickers)} spółek ({coverage:.0%}).")
    if coverage < MIN_COVERAGE:
        print(f"❌ Pokrycie cen poniżej {MIN_COVERAGE:.0%} — przerywam bez zapisu (zostaje poprzedni plik).")
        return 1

    if stage != "compute":
        try:
            bench_frames = download_prices([BENCHMARK])
            benchmark_df = bench_frames.get(BENCHMARK)
        except Exception as e:
            print(f"⚠️  Benchmark {BENCHMARK} niedostępny ({e}) — wykresy bez linii S&P 500.")
            benchmark_df = None
        try:
            nasdaq_df = download_prices([NASDAQ]).get(NASDAQ)
        except Exception as e:
            print(f"⚠️  {NASDAQ} niedostępny ({e}) — ocena rynku tylko z S&P 500.")
            nasdaq_df = None
    if stage == "all" and save_snapshot:   # liczymy jak dotąd, a przy okazji zapisujemy migawkę pobranych danych (deploy strony liczy z niej przy każdej zmianie kodu)
        fx = fetch_usdpln() or (previous or {}).get("fx")
        path = save_raw({"profile": RAW_PROFILE, "finviz_rows": finviz_rows, "finviz_total": finviz_total, "finviz_stale": finviz_stale,
                         "frames": frames, "benchmark": benchmark_df, "nasdaq": nasdaq_df, "fx": fx,
                         "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, RAW_PROFILE, raw_dir)
        print(f"💾 Zapisano migawkę {path} ({path.stat().st_size / 1e6:.1f} MB).")
    if stage == "fetch":
        # tylko pobranie: kurs, EPS i estymaty (sieć) oraz migawka cen / listy z Finviz do późniejszego liczenia
        fx = fetch_usdpln() or (previous or {}).get("fx")
        have = [t for t in tickers if t in frames]
        try:
            update_eps_cache(have, eps_cache_path)
        except Exception as e:
            print(f"⚠️  Krok EPS pominięty ({e}).")
        try:
            update_estimates(have, Path(output_path).parent / "estimates.json")
        except Exception as e:
            print(f"⚠️  Krok estymat analityków pominięty ({e}).")
        path = save_raw({"profile": RAW_PROFILE, "finviz_rows": finviz_rows, "finviz_total": finviz_total, "finviz_stale": finviz_stale,
                         "frames": frames, "benchmark": benchmark_df, "nasdaq": nasdaq_df, "fx": fx,
                         "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, RAW_PROFILE, raw_dir)
        print(f"💾 Zapisano migawkę {path} ({len(frames)} spółek, {path.stat().st_size / 1e6:.1f} MB). Obliczenia: python watchlist.py --compute-only")
        return 0
    try:
        market = market_state(drop_incomplete_bar(benchmark_df, now_utc) if benchmark_df is not None and len(benchmark_df) else None,
                              drop_incomplete_bar(nasdaq_df, now_utc) if nasdaq_df is not None and len(nasdaq_df) else None)
    except Exception as e:
        print(f"⚠️  Ocena rynku pominięta ({e}).")
        market = None
    stocks = build_stocks(finviz_rows, frames, now_utc, bench_df=benchmark_df)
    if stage == "compute":   # EPS i estymaty odświeża krok pobierania; tu tylko czytamy zapisane pliki
        eps_cache = _read_json(eps_cache_path, {})
        estimates = _read_json(Path(output_path).parent / "estimates.json", {}).get("stocks", {})
    else:
        try:
            eps_cache = update_eps_cache([s["ticker"] for s in stocks], eps_cache_path)
        except Exception as e:
            print(f"⚠️  Krok EPS pominięty ({e}).")
            eps_cache = {}
    add_eps_rating(stocks, eps_cache)
    if stage != "compute":
        try:
            estimates = update_estimates([s["ticker"] for s in stocks], Path(output_path).parent / "estimates.json")
        except Exception as e:
            print(f"⚠️  Krok estymat analityków pominięty ({e}).")
            estimates = {}
    for st in stocks:
        st.update(estimate_fields(estimates.get(st["ticker"]), st.get("price")))
    chart_tickers = [s["ticker"] for s in stocks]
    charts = build_charts(chart_tickers, frames, benchmark_df, eps_cache, now_utc)
    for st in stocks:
        summary = ((charts or {}).get("stocks", {}).get(st["ticker"]) or {}).get("rs_line") or {}
        st["rs_line_state"] = summary.get("state")
        st["rs_line_dist_pct"] = summary.get("dist_pct")
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_as_of": max((s["as_of"] for s in stocks), default=None),
        "finviz_filters": cfg["filters"] if not finviz_stale else (previous or {}).get("finviz_filters"),
        "finviz_total": finviz_total,
        "finviz_stale": finviz_stale,
        "n_stocks": len(stocks),
        "market": market,
        "fx": (fx if (stage == "compute" or fx is not None) else fetch_usdpln()) or (previous or {}).get("fx"),
        "stocks": stocks,
    }
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    charts_path = charts_path or out.parent / "charts.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"💾 Zapisano {out} ({len(stocks)} spółek, dane z sesji {payload['data_as_of']}).")
    if charts is not None:
        charts_out = Path(charts_path)
        charts_out.write_text(json.dumps(charts, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
        print(f"💾 Zapisano {charts_out} (wykresy tygodniowe {len(charts['stocks'])} spółek, {len(charts['weeks'])} tygodni).")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Odświeża listę obserwowaną (Finviz + yfinance) -> docs/data/watchlist.json")
    parser.add_argument("--skip-finviz", action="store_true",
                        help="Nie pytaj Finviz — użyj listy spółek z poprzedniego watchlist.json (tylko odśwież ceny).")
    parser.add_argument("--max-tickers", type=int, default=None, help="Limit liczby spółek (domyślnie z finviz_screen.json).")
    parser.add_argument("--output", type=str, default=None, help="Plik wyjściowy (domyślnie docs/data/watchlist.json).")
    stage_group = parser.add_mutually_exclusive_group()
    stage_group.add_argument("--fetch-only", action="store_true",
                             help="Tylko pobranie danych (Finviz, ceny, kurs, EPS, estymaty) -> migawka w --raw-dir; bez obliczeń i zapisu docs/data/*.json.")
    stage_group.add_argument("--compute-only", action="store_true",
                             help="Tylko obliczenia z zapisanej migawki (bez sieci) -> watchlist.json / charts.json.")
    parser.add_argument("--save-raw", action="store_true", help="Przy pełnym przebiegu (bez --fetch-only / --compute-only) zapisz też migawkę pobranych danych do --raw-dir.")
    parser.add_argument("--raw-dir", type=str, default=None, help="Katalog migawki danych (domyślnie raw/ w repozytorium, poza gitem).")
    args = parser.parse_args(argv)
    stage = "fetch" if args.fetch_only else "compute" if args.compute_only else "all"
    return run(args.output, args.skip_finviz, args.max_tickers, stage=stage, raw_dir=args.raw_dir, save_snapshot=args.save_raw)


if __name__ == "__main__":
    sys.exit(main())
