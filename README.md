# Momentum Desktop

Prosta aplikacja okienkowa (Python + Tkinter, ciemny motyw) z **jedną strategią**, wybraną w backteście na płynnym rynku USA w latach 2015–2026:

| Etap | Reguła |
|---|---|
| Skaner sektorowy (podstawowy) | RS sektora = cena ETF sektora (XLB, XLC, XLY, XLP, XLE, XLF, XLV, XLI, XLRE, XLK, XLU) / SPY, tygodniowo; sektor jest dodatni, gdy RS jest nad własną SMA 52 tyg.; ranking po % nad SMA. 3 najsilniejsze dodatnie sektory = 3 zapytania Finviz (`sec_<sektor>` + `ind_stocksonly,sh_price_o15,sh_avgvol_o300,fa_salesqoq_o15`), wyniki bez powtórzeń. Kolumna *RS sektora %*, ranking w pasku statusu. Test 2011–25 (bez fundamentów): top 3 sektory ≈ 11,8 %/rok, DD −28 % wobec ≈ 9,3 % / −38 % bez sektorów — bez walidacji statystycznej |
| Wzorce Zangera | Przycisk **Z** (klawisz z) na wykresie tygodniowym: widok jak u Zangera — cena (skala log.) i wolumen, bez RS / MACD / przychodów — z konturem wzorca i poziomem kupna. Wykrywane: Cup & Handle (miseczka −20…−35 %, uchwyt 1–3 tyg.), Flat Base, Ascending Triangle, Flaga/Proporzec; kolumny *Wzorzec Zangera* i *Do kupna wzorca %*, presety filtra. Strona chartpattern.com podaje liczby tylko dla Cup & Handle, reszta to **moje przybliżenie opisów**; niesprawdzone jako strategia |
| Linie trendu | Przeciągnij po wykresie = nowa linia (też dziennym); **nowa linia jest bez alarmu i bez przedłużenia** — alarm włączasz sam (prawy przycisk → „Dodaj alert linii”), wtedy linia przedłuża się do ostatniego tygodnia; blisko poziomu drugiego końca linia sama się prostuje („poziomo”); w trakcie rysowania podgląd % · tygodnie · cena; **↶ / Ctrl+Z** cofa (zmiana, usunięcie); w widoku Z słupki są jednokolorowe |
| Parabolic Curve | Ostrzeżenie przy wyjściu (nie sygnał kupna): log-cena w 12–30 tyg. pasuje do paraboli wypukłej w górę (R² ≥ 0,9), zysk ≥ +100 %; wyjście przy zamknięciu tygodnia pod SMA 10. Pojawia się w panelu pozycji |
| EPS Rating | Przybliżenie IBD (formuła IBD nie jest publiczna): 0,5 × średni wzrost EPS r/r z 2 ostatnich kwartałów + 0,3 × 3-letni wzrost EPS TTM + 0,2 × stabilność (udział z 8 kwartałów ze wzrostem r/r); wynik = percentyl 1–99 **wśród spółek aktualnej listy** (nie wszystkich akcji USA). Kolumna informacyjna, nie warunek |
| Lista do pobrania | **Skaner Finviz** do wyboru na pasku (*Skanery / ustawienia…*: własne skanery = nazwa + filtr + limit; domyślnie **Sektory top 3 (RS)**, Bezpieczny (backtest), Trend 50/200, Blisko rekordu (ATH), CANSLIM). Pierwszy = bezpieczny filtr wstępny `ind_stocksonly,sh_price_o10,sh_avgvol_o300,fa_salesqoq_o15` (tylko akcje, cena > 10 $, śr. wolumen > 300 tys., przychody kw. > 15 % r/r). W teście nie odciął żadnego z dużych zwycięzców |
| Warunki | przychody kw. **≥ +15 % r/r** i marża operacyjna **≥ +3 pp r/r** (SEC EDGAR); P/S, RS i niespodzianki EPS domyślnie wyłączone (badanie 2011–2025: RS ≥ 50 pp obniżał wynik — za mało sygnałów) |
| Kolejność | warunki + sygnał, potem **najbliżej Green Line** (przy nadmiarze sygnałów: ten sam wynik, mniejsze obsunięcie) |
| Wejście | **Green Line**: rekord wszech czasów **miesięcznego High** (jak w oryginale Dr. Wisha), który stoi **3 miesiące łącznie** (szczyt + 2 zamknięte kolejne; po nowym rekordzie obowiązuje stara linia, dopóki nowy nie przestoi tyle samo); kupno, gdy tydzień zamknie się **0–10 % nad linią po przebiciu od dołu** (cena zeszła pod linię i wróciła; po rajdzie > 10 % nad linią ta linia wygasa do powstania nowej — powrót w strefę to kupowanie spadku, nie sygnał) |
| Wyjście | stop **10 %** pod wejściem i **tygodniowy MACD (12, 26, 9)**: stop pod Low tygodnia przecięcia w dół **po wejściu** (zamknięcie tygodnia) |
| Portfel | 8–10 pozycji po równo; najpierw wyjścia, potem wejścia; nie sprzedawaj pozycji dla nowego sygnału; bez dokładek, trailing stopów i stopu czasowego; wolne miejsca = gotówka w SPY. Badanie 2011–2025 (≈5600 spółek, bez zdelistowanych): ≈ 21 % rocznie, DD ≈ −37 %; z gotówką w SPY ≈ 25 % |

Heurystyka z backtestu (spółki z dzisiejszej listy, bez spółek wycofanych z obrotu), nie porada inwestycyjna.

## Okno

- **Lista**: ticker, spółka, sektor, cena, Green Line, odległość od linii, stan GLB (*WYBICIE* = ten tydzień zamknął się nad linią, poprzedni nie;
  *SYGNAŁ* = 0–10 % nad linią po przebiciu od dołu; *NAD* = dalej albo linia wygasła po rajdzie; *POD*), MACD (nad / pod sygnałem) i stop z ostatniego przecięcia, zmiana marży operacyjnej i brutto r/r,
  przychody r/r, kwartał danych, obrót. Zielone wiersze = warunki spełnione i sygnał GLB. Domyślnie widać wszystkie spółki; filtr „tylko spełniające warunki” jest wyłączony i można go włączyć na pasku.
  Klik w nagłówek sortuje; Enter / dwuklik = wykres; zaznaczenie na liście przełącza otwarty wykres.
- **Warunki…** (obok checkboxa „tylko spełniające warunki”): wybór, które kryteria są obowiązkowe, i edycja progów dla przychodów kw. r/r, zmiany marży operacyjnej,
  P/S oraz RS 52 tyg. vs S&P 500; można też wyłączyć wymóg dwóch kolejnych niespodzianek EPS. Zmiany są zapisywane, działają od razu i obowiązują przy następnym Sync.
  Brak danych P/S nie odrzuca spółki, zgodnie z dotychczasową regułą.
- **Filtry…** (pasek): kilka warunków naraz po kolumnach — stan GLB, MACD, warunki, sektor (zaznacz wartości), liczby od–do (np. do linii %, Δ marży,
  obrót w mln $). Gotowe zestawy, np. „Nad GLB + MACD dodatni”. Filtry zostają zapamiętane w ustawieniach.
- **Wykres** (jeden, tygodniowy, 3 lata): słupki High–Low z kreską zamknięcia, SMA 10 i 30 tyg., **Green Line** (z ceną i górną granicą kupna +10 %),
  stop z MACD (czerwona przerywana), wolumen ze średnią 10 tyg., MACD z ▼ w tygodniach przecięcia w dół. ↑ / ↓ = następna / poprzednia spółka, ruch myszy = dane tygodnia.
  **E pod Low świecy** oznacza dzień publikacji wyników finansowych (dzienny: sesja raportu, tygodniowy: tydzień raportu). Po najechaniu na świecę E dymek podaje **Earnings Surprise** i **Revenue Surprise** w %; jeśli źródło nie udostępnia historycznego konsensusu przychodów, pokazuje N/D zamiast szacować wartość.
  **Suwak** nad wykresem (minimapa całej historii): przeciągnij ramkę = przesuń okno, krawędzie = zmień długość, klik obok ramki = skok, kółko myszy / + − = zoom, ← / → = przesuń o 4 tygodnie.
  Przycisk **⟳ Sync** w oknie wykresu odświeża tylko aktualną spółkę (świece tygodniowe, fundamenty oraz dane dzienne i miesięczne) w tle, bez ponownego skanowania całego Finviz.
- **Linie trendu**: na wykresie tygodniowym i dziennym przeciągnij myszą po panelu ceny, aby narysować linię (punkty przyciągają się do High / Low świecy).
  Chwyć koniec, aby zmienić punkt; chwyć środek, aby przesunąć. Prawy klik na linii otwiera menu **Dodaj/wyłącz alert linii** lub **Usuń linię**; Delete usuwa zaznaczoną linię.
  **Miarka**: przytrzymaj prawy przycisk myszy na panelu ceny (poza linią) i przesuwaj — od punktu kliknięcia widać zmianę ceny w % i liczbę tygodni (sesji na D, miesięcy na M); puszczenie przycisku chowa miarkę.
  Linia jest przedłużona przerywaną kreską do ostatniej świecy. Linie dzienne i tygodniowe są przechowywane osobno; alert na linii dziennej sprawdza dzienne zamknięcia.
- **🔔 Alerty** (pasek): zamknięcie tygodnia przecięło linię trendu oraz dla obserwowanych spółek (🔕 Obserwuj na wykresie): sygnał GLB, przecięcie MACD
  w dół, zamknięcie pod stopem MACD, spełnione warunki. Sprawdzane po starcie i po każdym Sync; zapis w `data/alerts.json`.
- **Warunki domyślne** (zmieniane przyciskiem **Warunki…**; bez progu obrotu — płynność ustawiasz filtrem w Finviz): przychody kw. ≥ +15 % r/r i marża oper. ≥ +3 pp r/r; P/S < 20, siła
  względna (RS ≥ 50 pp nad SPY) i 2 raporty EPS powyżej konsensusu można włączyć ręcznie. Starsze zapisane ustawienia warunków są raz resetowane do nowych domyślnych. Wcześniejszy backtest (płynny rynek): Backtest 2015–2026: +15,6 % na transakcję, portfel wszystkich sygnałów
  36,6 % rocznie (S&P 500 13,6 %), ale mało sygnałów naraz i spadek portfela do −55 %. **Hamuje ⚠**: tempo przychodów spadło o ≥ 10 pp (⚠⚠ z marżą brutto
  w dół). Liczby w 📖 Poradniku.
- **RS jak w Deepvue** (zamiast panelu S&P 500): nad ceną RS Line = akcja / SPY ze średnią 52 tyg. (252 sesje na D), ● zielony = nowy szczyt RS i ceny, ● różowy = szczyt RS przed ceną;
  na końcu linii „+x pp” (RS 52 tyg.). Kolumna **C/C[52 tyg.]** = zamknięcie / zamknięcie sprzed 252 sesji.
- **Wejście:** zamknięcie tygodnia **0–10 % nad Green Line** po przebiciu od dołu (WYBICIE = tydzień przebicia, SYGNAŁ = kolejny tydzień w strefie; po rajdzie > 10 % nad linią kolejne wejście dopiero na nowej Green Line). Dalej niż 10 % (także BLUE DOT)
  i Blue Line — tylko informacyjnie (w badaniu 2011–2025 dawały mniej).
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
- **Ticker na pasku wykresu**: wpisz symbol w lewym górnym polu i naciśnij Enter. Jeśli dane są w cache, wykres otworzy je od razu; w przeciwnym razie pobieranie odbędzie się w tle. Ostatnie symbole są zapamiętywane. **Ctrl+Space** na liście otwiera okno dowolnego symbolu; w oknie wykresu ten skrót przenosi kursor do pola tickera.

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
