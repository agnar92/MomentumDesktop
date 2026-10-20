# Momentum Desktop

Prosta aplikacja okienkowa (Python + Tkinter, ciemny motyw) z **jedną strategią**, wybraną w backteście na płynnym rynku USA w latach 2015–2026:

| Etap | Reguła |
|---|---|
| Lista do pobrania | **Skaner Finviz** do wyboru na pasku (*Skanery / ustawienia…*: własne skanery = nazwa + filtr + limit; domyślnie Bezpieczny (backtest), Trend 50/200, Blisko rekordu (ATH), CANSLIM). Pierwszy = bezpieczny filtr wstępny `ind_stocksonly,sh_price_o10,sh_avgvol_o300,fa_salesqoq_o15` (tylko akcje, cena > 10 $, śr. wolumen > 300 tys., przychody kw. > 15 % r/r). W teście nie odciął żadnego z dużych zwycięzców |
| Warunki | obrót dzienny **≥ 50 mln $**, przychody kw. **≥ +15 % r/r**, marża operacyjna **≥ +3 pp r/r** (fundamenty z SEC EDGAR) |
| Kolejność | od największej zmiany marży operacyjnej r/r |
| Wejście | **Green Line**: rekord wszech czasów **miesięcznego High** (jak w oryginale Dr. Wisha), który stoi **≥ 3 zamknięte miesiące** (po nowym rekordzie obowiązuje stara linia, dopóki nowy nie przestoi 3 miesięcy); kupno, gdy tydzień zamknie się **0–10 % nad linią** |
| Wyjście | **tygodniowy MACD (12, 26, 9)**: po przecięciu sygnału w dół stop pod Low tego tygodnia; do tego stop **10 %** pod wejściem |

Heurystyka z backtestu (spółki z dzisiejszej listy, bez spółek wycofanych z obrotu), nie porada inwestycyjna.

## Okno

- **Lista**: ticker, spółka, sektor, cena, Green Line, odległość od linii, stan GLB (*WYBICIE* = ten tydzień zamknął się nad linią, poprzedni nie;
  *SYGNAŁ* = 0–10 % nad linią; *NAD* = dalej; *POD*), MACD (nad / pod sygnałem) i stop z ostatniego przecięcia, zmiana marży operacyjnej i brutto r/r,
  przychody r/r, kwartał danych, obrót. Zielone wiersze = warunki spełnione i sygnał GLB. Domyślnie widać tylko spółki spełniające warunki (pole na pasku).
  Klik w nagłówek sortuje; Enter / dwuklik = wykres; zaznaczenie na liście przełącza otwarty wykres.
- **Filtry…** (pasek): kilka warunków naraz po kolumnach — stan GLB, MACD, warunki, sektor (zaznacz wartości), liczby od–do (np. do linii %, Δ marży,
  obrót w mln $). Gotowe zestawy, np. „Nad GLB + MACD dodatni”. Filtry zostają zapamiętane w ustawieniach.
- **Wykres** (jeden, tygodniowy, 3 lata): słupki High–Low z kreską zamknięcia, SMA 10 i 30 tyg., **Green Line** (z ceną i górną granicą kupna +10 %),
  stop z MACD (czerwona przerywana), wolumen ze średnią 10 tyg., MACD z ▼ w tygodniach przecięcia w dół. ↑ / ↓ = następna / poprzednia spółka, ruch myszy = dane tygodnia.
  **Suwak** nad wykresem (minimapa całej historii): przeciągnij ramkę = przesuń okno, krawędzie = zmień długość, klik obok ramki = skok, kółko myszy / + − = zoom, ← / → = przesuń o 4 tygodnie.
- **Linie trendu**: przeciągnij myszą po wykresie ceny = nowa linia (końce przyciągają się do High / Low tygodnia). Chwyć koniec = zmień punkt,
  chwyć środek = przesuń linię, klik = zaznacz (🗑 linia / 🔔 alert linii na górze okna), Delete albo prawy przycisk = usuń. Linia jest przedłużona
  (przerywana) do ostatniego tygodnia, z wartością przy prawej krawędzi.
- **🔔 Alerty** (pasek): zamknięcie tygodnia przecięło linię trendu oraz dla obserwowanych spółek (🔕 Obserwuj na wykresie): sygnał GLB, przecięcie MACD
  w dół, zamknięcie pod stopem MACD, spełnione warunki. Sprawdzane po starcie i po każdym Sync; zapis w `data/alerts.json`.
- **Mocne** (kolumna, ciemniejsza zieleń): warunki strategii ze zmianą marży oper. r/r ≥ 10 pp — w teście wszystkich sygnałów GLB 2015–2026 +5,1 % na
  transakcję (vs +2,9 %) i 22,7 % rocznie (vs 16,1 %). Takie spółki są na górze listy; liczy się poprawa marży, nie jej poziom.
- **Potencjał ★ (0–5) i Hamuje ⚠** (kolumny): cechy fundamentów, które w badaniu 2021–2026 (ceny bez korekty) podnosiły szansę na duży ruch — przychody ≥ 25 %,
  dwa kwartały z rzędu, marża oper. ↑ ≥ 3 pp dwa kwartały, marża brutto ↑ ≥ 2 pp, marża oper. < 10 % — i ostrzeżenie o hamowaniu przychodów (≥ 10 pp, ⚠⚠ z marżą
  brutto w dół). **📖 Poradnik**: zasady z badań i lista kontrolna spółki. **📌 Pozycja** na wykresie: 📌 i pomarańczowy wiersz przy hamowaniu / pod stopem, alerty.
  Wykres jak w IBD: S&P 500 (SPY, pobierany przy Sync) nad ceną, przychody kwartalne z r/r % pod wolumenem.
- **Okno wykresu** jest wyższe niż szersze; po prawej rozwijany panel **FUNDAMENTY** (pasek ze strzałką na całej wysokości): potencjał ★, wartości z ostatnich
  raportów, lista kontrolna i ostrzeżenie dla pozycji (stan panelu zostaje zapamiętany).
- **📅 Dzienny** (przycisk przełącza tygodniowy → dzienny → miesięczny; klawisze W / D / M): 2 lata świec dziennych z yfinance (raz na spółkę, w tle), RWB
  Guppy — 6 szybkich EMA (czerwone) i 6 wolnych (niebieskie), jaśniejsze tło = RWB — ● Blue Dot (Stochastic 10,1 ↑ 20 przy RWB nad Green Line) ze stopem
  pod Low kropki, Stochastic zamiast MACD. Tylko do podglądu: w teście RWB + Blue Dot dawało +1 % na transakcję (GLB tygodniowy +2,9 %, z Mocne +5,1 %).
- **📅 Tygodniowy / Miesięczny** (przycisk na wykresie albo klawisz M): wykres miesięczny z pełnej historii (yfinance, ceny bez korekty, pobierany raz na spółkę)
  do sprawdzenia Green Line — schodki = linia w czasie, kółko = miesiąc obecnego rekordu („stoi N mies.”), porównanie z linią z listy (⚠ przy różnicy).
  Linie trendu rysujemy na tygodniowym.
- **Ctrl+K**: dowolny symbol (np. SPY, ^GSPC, NVDA) — te same obliczenia i wykres; ostatnie symbole są zapamiętane.

## Dane (darmowe źródła, jak najmniej zapytań)

- **⟳ Sync (F5)**: Finviz (lista) → yfinance **tygodniowe 3 lata** (wykres, średnie, MACD, obrót) → dla spółek z obrotem ≥ 50 mln $:
  yfinance **miesięczne High z całej historii** (Green Line) i **SEC** (fundamenty; odświeżane co 7 dni). Bez danych dziennych.
- **Tylko nowe dane**: spółka już pobrana dostaje z yfinance tylko ostatnie tygodnie (doklejane do zapisanych), a historia miesięczna tylko nowe zamknięte
  miesiące. Całość pobieramy dla nowej spółki, po przerwie dłuższej niż ~5 miesięcy albo gdy ceny wstecz się zmieniły (split). Ceny są **nieskorygowane o dywidendy** (tylko o splity), jak na TradingView — inaczej dawne szczyty spółek z dużymi wypłatami (np. CLMT) wychodziły za nisko.
- **Pasek postępu** na dole okna w trakcie Sync: etap (1/4 Finviz, 2/4 tygodniowe, 3/4 miesięczne, 4/4 SEC), procent, czas od startu i szacowany czas do końca.
- Każdy skaner ma własną listę (Sync pobiera wybrany skaner); świece, historia miesięczna i fundamenty są wspólne, więc spółka z kilku skanerów pobiera się raz.
- Pliki w `data/` obok programu: `scans/<skaner>.json` (listy), `weekly.json` (świece), `monthly.json`, `sec.json`, `settings.json` (skanery i ustawienia).
- SEC prosi o User-Agent z kontaktem — wpisz swój w ustawieniach.
- Stan GLB liczony jest na ostatniej świecy tygodniowej; w trakcie tygodnia to jeszcze nie zamknięcie — sygnał obowiązuje po zamknięciu piątku.

## Uruchomienie

```bash
pip install -r requirements.txt
python main.py
```

Testy: `pip install -r requirements-dev.txt && python -m pytest -q` (GUI pod `xvfb-run` na Linuksie), `ruff check .`.
Wersja portable (Windows / Linux): workflow *Build portable* (Actions → Artifacts albo Releases → *latest*).
