# Momentum Desktop

Prosta aplikacja okienkowa (Python + Tkinter, ciemny motyw) z **jedną strategią**, wybraną w backteście na płynnym rynku USA w latach 2015–2026:

| Etap | Reguła |
|---|---|
| Lista do pobrania | **Skaner Finviz** do wyboru na pasku (*Skanery / ustawienia…*: własne skanery = nazwa + filtr + limit; domyślnie Bezpieczny (backtest), Trend 50/200, Blisko rekordu (ATH), CANSLIM). Pierwszy = bezpieczny filtr wstępny `ind_stocksonly,sh_price_o10,sh_avgvol_o300,fa_salesqoq_o15` (tylko akcje, cena > 10 $, śr. wolumen > 300 tys., przychody kw. > 15 % r/r). W teście nie odciął żadnego z dużych zwycięzców |
| Warunki | przychody kw. **≥ +15 % r/r**, marża operacyjna **≥ +3 pp r/r** (SEC EDGAR), **P/S < 20**, siła względna 52 tyg. **≥ +50 pp nad S&P 500** |
| Kolejność | od największej zmiany marży operacyjnej r/r |
| Wejście | **Green Line**: rekord wszech czasów **miesięcznego High** (jak w oryginale Dr. Wisha), który stoi **≥ 3 zamknięte miesiące** (po nowym rekordzie obowiązuje stara linia, dopóki nowy nie przestoi 3 miesięcy); kupno, gdy tydzień zamknie się **0–10 % nad linią** |
| Wyjście | **tygodniowy MACD (12, 26, 9)**: po przecięciu sygnału w dół stop pod Low tego tygodnia; do tego stop **10 %** pod wejściem |

Heurystyka z backtestu (spółki z dzisiejszej listy, bez spółek wycofanych z obrotu), nie porada inwestycyjna.

## Okno

- **Lista**: ticker, spółka, sektor, cena, Green Line, odległość od linii, stan GLB (*WYBICIE* = ten tydzień zamknął się nad linią, poprzedni nie;
  *SYGNAŁ* = 0–10 % nad linią; *NAD* = dalej; *POD*), MACD (nad / pod sygnałem) i stop z ostatniego przecięcia, zmiana marży operacyjnej i brutto r/r,
  przychody r/r, kwartał danych, obrót. Zielone wiersze = warunki spełnione i sygnał GLB. Domyślnie widać wszystkie spółki; filtr „tylko spełniające warunki” jest wyłączony i można go włączyć na pasku.
  Klik w nagłówek sortuje; Enter / dwuklik = wykres; zaznaczenie na liście przełącza otwarty wykres.
- **Filtry…** (pasek): kilka warunków naraz po kolumnach — stan GLB, MACD, warunki, sektor (zaznacz wartości), liczby od–do (np. do linii %, Δ marży,
  obrót w mln $). Gotowe zestawy, np. „Nad GLB + MACD dodatni”. Filtry zostają zapamiętane w ustawieniach.
- **Wykres** (jeden, tygodniowy, 3 lata): słupki High–Low z kreską zamknięcia, SMA 10 i 30 tyg., **Green Line** (z ceną i górną granicą kupna +10 %),
  stop z MACD (czerwona przerywana), wolumen ze średnią 10 tyg., MACD z ▼ w tygodniach przecięcia w dół. ↑ / ↓ = następna / poprzednia spółka, ruch myszy = dane tygodnia.
  **Suwak** nad wykresem (minimapa całej historii): przeciągnij ramkę = przesuń okno, krawędzie = zmień długość, klik obok ramki = skok, kółko myszy / + − = zoom, ← / → = przesuń o 4 tygodnie.
- **Linie trendu**: na wykresie tygodniowym i dziennym przeciągnij myszą po panelu ceny, aby narysować linię (punkty przyciągają się do High / Low świecy).
  Chwyć koniec, aby zmienić punkt; chwyć środek, aby przesunąć. Prawy klik na linii otwiera menu **Dodaj/wyłącz alert linii** lub **Usuń linię**; Delete usuwa zaznaczoną linię.
  Linia jest przedłużona przerywaną kreską do ostatniej świecy. Linie dzienne i tygodniowe są przechowywane osobno; alert na linii dziennej sprawdza dzienne zamknięcia.
- **🔔 Alerty** (pasek): zamknięcie tygodnia przecięło linię trendu oraz dla obserwowanych spółek (🔕 Obserwuj na wykresie): sygnał GLB, przecięcie MACD
  w dół, zamknięcie pod stopem MACD, spełnione warunki. Sprawdzane po starcie i po każdym Sync; zapis w `data/alerts.json`.
- **Warunki** (tylko te o największym wpływie w backteście; bez progu obrotu — płynność ustawiasz filtrem w Finviz): przychody kw. ≥ +15 % r/r, marża oper. ≥ +3 pp r/r, P/S < 20 i siła
  względna (kolumna RS): zmiana ceny z 52 tyg. ≥ 50 pp lepsza od S&P 500 (SPY). Backtest 2015–2026: +15,6 % na transakcję, portfel wszystkich sygnałów
  36,6 % rocznie (S&P 500 13,6 %), ale mało sygnałów naraz i spadek portfela do −55 %. **Hamuje ⚠**: tempo przychodów spadło o ≥ 10 pp (⚠⚠ z marżą brutto
  w dół). Liczby w 📖 Poradniku.
- **Linia siły relatywnej (RS) jak w IBD** na wykresie tygodniowym: cena / S&P 500 na dole panelu ceny, na końcu linii liczba „+x pp” (RS 52 tyg.), ● gdy RS jest na szczycie 52 tyg.
- **Wejście:** WYBICIE = tydzień przebicia Green Line przy dowolnej wysokości (mocne wybicie), SYGNAŁ = 0–10 % nad linią, **BLUE DOT** = kolejny tydzień
  > 10 % nad linią i Blue Dot na dziennym w ostatnich 5 sesjach (wejście; bez kropki stan NAD = czekaj).
- **Niespodzianki EPS** (warunek „2× nad konsensus”: 2 ostatnie raporty powyżej konsensusu EPS; kolumny Niesp. EPS % i Rewizja EPS 90 dni %, z yfinance,
  co 7 dni). W backteście warunek podniósł wynik z 36,6 do 42,4 % rocznie. Rewizja prognozy na przyszły rok (dziś vs 90 dni temu) to podgląd — bez historii do testu.
- **Wolumen relatywny** (kolumny RVol tyg. / RVol dz. i opis panelu wolumenu): wolumen ostatniego tygodnia / średnia 10 poprzednich tygodni oraz
  ostatniej sesji / średnia 50 sesji — 2,0 = dwa razy więcej niż zwykle; gotowy filtr „Aktywne: RVol tyg. ≥ 1,5 + nad GLB”.
- **📌 Pozycje** (pasek narzędzi): pozycje z planem wyjścia i kolumną „Co teraz” (trzymaj / stop −10 % / wyjście / sprzedaj ½ / hamuje) oraz obserwowane spółki;
  klik = wykres, usuwanie pozycji i obserwowanych.
- **🚪 Wyjście** (przycisk na wykresie, zapamiętany): **MACD** (stop pod Low tygodnia przecięcia w dół) albo **pod GLB** (zamknięcie tygodnia pod Green Line,
  jak u Dr Wisha — trzyma największe ruchy, np. SNDK, MU, NVDA 2023). Zawsze: stop 10 % pod kupnem i **spadek 20 % od szczytu = sprzedaj połowę**. Przy 📌 pozycji
  wykres pokazuje „stop −10 %” i „½ przy”, panel / lista kontrolna plan wyjścia, a alerty: zamknięcie pod Green Line i spadek 20 % od szczytu. Liczby w 📖 Poradniku.
- **Okno wykresu** jest wyższe niż szersze; po prawej rozwijany panel **FUNDAMENTY** (pasek ze strzałką na całej wysokości): warunki, wartości z ostatnich
  raportów, lista kontrolna i ostrzeżenie dla pozycji (stan panelu zostaje zapamiętany).
- **M / T / D** (osobne przyciski na wykresie; klawisze m / w / d) — dzienny: 2 lata świec z yfinance, domyślnie słupkowy High–Low z kreskami otwarcia/zamknięcia i średnimi EMA 8/10/20 oraz SMA 50.
  Można przełączyć go na **RWB / GMMA**: 6 szybkich EMA (czerwone) i 6 wolnych (niebieskie), jaśniejsze tło = RWB — ● Blue Dot (Stochastic 10,1 ↑ 20 przy RWB nad Green Line).
  Stop pod Low kropki i Green Line; bez MACD, przychodów i panelu Stochastic. Tylko do podglądu: w teście RWB + Blue Dot dawało +1 % na transakcję.
- **M — miesięczny** (przycisk M na wykresie albo klawisz m): wykres miesięczny z pełnej historii (yfinance, ceny bez korekty, pobierany raz na spółkę)
  do sprawdzenia Green Line — schodki = linia w czasie, kółko = miesiąc obecnego rekordu („stoi N mies.”), porównanie z linią z listy (⚠ przy różnicy).
  Linie trendu można rysować na wykresie tygodniowym i dziennym; linie dla obu interwałów są przechowywane osobno.
- **Ctrl+K**: dowolny symbol (np. SPY, ^GSPC, NVDA) — te same obliczenia i wykres; ostatnie symbole są zapamiętane.

## Dane (darmowe źródła, jak najmniej zapytań)

- **⟳ Sync (F5)**: Finviz (lista) → yfinance **tygodniowe 3 lata** (wykres, średnie, MACD, obrót) → dla wszystkich spółek ze skanera:
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
