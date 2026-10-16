# Momentum Desktop

Prosta, „retro” aplikacja okienkowa (Python + Tkinter, styl TC2000) oparta na logice i strategii z **Momentum**:

- **Dwa osobne synchronizacje** (bo fundamenty zmieniają się raz na tydzień, a ceny chcesz mieć szybciej):
  - **⟳ Ceny** (`F5`, ok. minuty) — lista z Finviz + ceny z yfinance + przeliczenie wszystkiego, co zależy od ceny (RS, bazy, Darvas,
    CANSLIM, wykresy tygodniowe i dzienne). EPS z Yahoo i estymaty analityków **nie** są pobierane — używane są zapisane.
  - **⟳ Fundamenty** (`Shift+F5`, kilka–kilkanaście minut) — pełny przebieg silnika Momentum, razem z odświeżeniem EPS i estymat.
    Program podpowiada (⚠ na pasku), gdy fundamenty mają ponad 7 dni.
- **Lista** (okno główne) — wszystkie spółki z kolorami wg stanu Darvasa (KUP / trzymaj / czekaj / SPRZEDAJ), kolumny **CANSLIM** (n/7 i
  litery C A N S L I M), przełącznik skali **Tydzień / Dzień** (stan Darvasa liczony na tygodniowych albo dziennych zamknięciach), sortowanie
  po nagłówku, wyszukiwarka. Prawy klik → „CANSLIM — szczegóły” (litera po literze: werdykt, liczby, reguła). Dwuklik / Enter = wykres, ↑/↓ przełącza spółki w otwartym wykresie.
- **Własne skanery Finviz** (menu *Skanery* → *Moje skanery…* / *Nowy skaner Finviz…*): każdy skaner to osobne okno z własną listą, danymi,
  kolumnami i synchronizacją (dane w `data/scanners/<nazwa>/`; skaner domyślny to główne okno). **Kreator**: filtry Finviz z list wyboru
  (zakładki Opisowe / Fundamentalne / Techniczne — ponad 200 kodów sprawdzonych na żywo w Finviz), wklejenie adresu skanera z finviz.com albo
  samych kodów (`f=`), podgląd kryteriów po polsku, **test liczby wyników** w Finviz, limit spółek. Kolumny ustawiasz przyciskiem **Kolumny…**
  z danych, które faktycznie mamy (pola Finviz, ratingi, CANSLIM, Darvas, bazy…); dodatkowe pola tylko z Finviz (dywidenda, beta, RSI, short
  float, wyniki tygodnia/miesiąca…) zamawiasz w kreatorze (zakładka *Kolumny z Finviz*) i pojawiają się po Sync. Przyciski robią dokładnie to, co mówią: **Zapisz i pobierz ceny** pobiera same ceny (zamknięcia, High, Low), a **Zapisz i pobierz fundamenty** — ceny i fundamenty;
  nic nie dociąga się po cichu. EPS i estymaty są wspólne dla wszystkich skanerów (spółka znana innemu skanerowi nie jest pobierana drugi raz).
- **Skany i watchlisty — dwie różne rzeczy.** **Skan** (Finviz / Qullamaggie) pobiera i zapisuje dane: pełne okno z kolumnami, filtrami (*Filtr…*), boxami i Sync.
  **Watchlista** to tylko małe, wąskie okno z listą tickerów z kilku skanów wg kryteriów — kliknięcie tickera (albo ↑ / ↓) otwiera lub przełącza Dar-Card
  i wykres słupkowy. Bez filtrów i paska skanera; nic nie pobiera, tylko składa listę z już pobranych skanów (*Skanery → Nowa watchlista…*, przycisk
  *⟳ Odśwież*, odświeża się też sama po Sync skanu). Dla każdego skanu wybierasz kryterium: **wszystkie spółki**, **Qullamaggie**, **CANSLIM ≥ n/7** albo **Wish: Green Line Breakout**.
- **Filtr po kolumnach w skanach i watchlistach** (*⚗ Filtr kolumn…*): mały skrypt na dowolnych kolumnach, także tych, których nie pokazujesz w tabeli (kolumny dodajesz przyciskiem *▤ Kolumny…*). Jeden warunek w linii
  (linie łączone `and`), albo `and` / `or` i nawiasy: `adr_pct >= 4`, `"Cena/min 3M" > 1.5 and price < 100`, `glb_state == WYBICIE`, `rs_rating != brak`. Operatory `> < >= <= == !=`; kolumna = klucz
  (`adr_pct`) albo etykieta w cudzysłowie; tekst bez rozróżniania wielkości liter, także w postaci wyświetlanej (`darvas == KUP`). Lewa lista pokazuje dostępne kolumny (dwuklik wstawia nazwę), a podgląd na
  żywo mówi, ile spółek pasuje albo gdzie jest błąd. Filtr zapisuje się razem z watchlistą; błędny skrypt nie ukrywa listy, tylko pokazuje komunikat w pasku statusu.
- **Skan Wish — Green Line Breakout** (*Skanery → Nowy skan Wish (Green Line Breakout)…*): zwykły skan Finviz (domyślnie tylko `ind_stocksonly,sh_avgvol_o300,sh_price_o1` — Finviz odsiewa śmieci, a szczyty wszech czasów i zieloną linię liczy aplikacja sama, bez filtra ATH z Finviz), a po Sync aplikacja pobiera **miesięczne zamknięcia z całej historii** (yfinance, ok. 120 liczb na 10 lat) i liczy **zieloną linię**: najwyższe zamknięcie miesięczne (ATH), którego
  przez ≥ 3 miesiące nikt nie pobił — to „top Darvasa” z wykresu miesięcznego, na zamknięciach. Kolumna **GLB**: *WYBICIE* (miesiąc zamknął się nad linią, liczony też bieżący), *po wybiciu*,
  *czeka* (cena pod potwierdzoną linią; kolumna „Do linii %”), *za późno* (> 10 % nad linią). Linia jest rysowana na Dar-Card i na wykresie słupkowym. Progi (3 miesiące, 10 %) są w edytorze skanu —
  to moje przybliżenie reguł Wisha, nie sprawdzona wersja. Watchlista może wybrać spółki wg GLB (stany + maks. odległość pod linią).
- **Skan Qullamaggie** (*Skanery → Nowy skan Qullamaggie…*) pobiera dane pod strategię: **obrót dzienny** (cena × wolumen), **ADR** i **cena / min Low**
  z okien 1M (~22 sesji), 3M (~66), 6M (~132). Zapisuje spółki powyżej *progów pobierania* (domyślnie obrót 25 mln $, ADR 2 %), a kryteria wyboru ustawiasz
  w watchliście: obrót, ADR i **górne X % z KAŻDEGO okna osobno** (top 10 % z 1M, potem top 10 % z 3M, potem z 6M), wynik to suma bez duplikatów
  (kolumna *Okna QM* mówi, w których oknach spółka się załapała). Można zmieniać progi (obrót 50–100 mln, ADR 2–4) bez ponownego pobierania — przycisk
  *Podgląd liczby tickerów* w edytorze pokazuje, ile spółek wychodzi (cel 30–50). **Co robi Finviz:** kreator dobiera filtr wstępny (`cap_smallover`,
  `ind_stocksonly`, średni wolumen, cena > 10 $, a przy ADR ≥ 3 zmienność miesiąca — Finviz liczy ją niemal tak samo jak ADR, próg filtra jest o 1 pkt
  niższy dla zapasu); dokładny obrót i ADR liczy program. Darmowy screener Finviz oddaje maksymalnie 1000 wierszy — większy zbiór program pobiera sektor
  po sektorze i skleja. **Szybki Sync (dwa etapy, domyślny):** etap 1 pobiera z Finviz cały zbiór jednym widokiem (cena, średni wolumen, zmienność,
  zwroty 1M / 3M / 6M, odległość od minimum 50 dni i 52 tygodni) i wybiera kandydatów — czołówkę pięciu rankingów przybliżających cena / min Low;
  etap 2 pobiera ceny z yfinance tylko dla nich i liczy dokładny obrót, ADR i cena / min Low. Na sektorze Technology (380 spółek) kandydatów było
  149–220 zamiast 380, a wszystkie 43 spółki z pełnego Syncu trafiły do wyniku. Górne X % liczone jest od wielkości całego płynnego zbioru z Finviz
  (nie od kandydatów). Ranking z Finviz jest przybliżony — odznaczenie „Szybki Sync” w edytorze skanu pobiera ceny wszystkich spółek.
- **Równoległa synchronizacja i szybkie okno**: kilka skanerów może pobierać dane jednocześnie (każdy sync w osobnym procesie programu,
  własny dziennik w osobnym oknie; ten sam skaner naraz tylko raz). Zamknięcie głównego okna nie kończy programu, dopóki są inne okna (główne się chowa, wracasz z małego okna). Małe okno **Skanery** (menu *Skanery → Szybkie okno skanerów*) pokazuje skanery
  w kolejności ostatniego otwarcia (● otwarty, ⟳ trwa sync); program zapamiętuje, które okna były otwarte, i przy następnym starcie je odtwarza
  (`data/session.json`).
- **Co nowego od ostatniego Sync**: po każdej synchronizacji program porównuje listę skanera z poprzednią i pokazuje, kto wszedł (★) i wypadł, nowe
  KUP (tydzień / dzień), nowe SPRZEDAJ, przypięte boxy w strefie zagrożenia i spółki, które weszły do CANSLIM ≥ 5/7. Okno otwiera się samo,
  przycisk „Co nowego (n)” pokazuje liczbę zmian (sumują się do wyczyszczenia), a kolumna „Zmiana” oznacza spółki na liście.
- **Własne listy z kolorowymi flagami** (jak flagi w TC2000): klawisze `1–4` na liście nadają zaznaczonej spółce flagę (⭐ Obserwuję, 🛒 Kupione,
  ❗ Do sprawdzenia, 🚫 Odrzucone), `0` ją zdejmuje; wiersz dostaje kolor tła, flagi są wspólne dla wszystkich skanerów, nazwy zmienisz w Narzędzia →
  Nazwy list, filtr „Lista” na pasku (dowolna / bez listy / konkretna).
- **Eksport** (Narzędzia): kopiuj tickery do schowka (przecinki — np. do TradingView, albo po jednym w linii), zapisz tickery do .txt, zapisz CSV
  z widocznymi kolumnami (wariant dla Excela PL: średnik i przecinek dziesiętny, albo standardowy).
- **Średnia wolumenu** na wykresie: SMA 10 tygodni (tygodniowy) i SMA 50 sesji (dzienny) jako pomarańczowa linia w panelu wolumenu; słupki z wolumenem
  ≥ 1,4× poprzedniej średniej (wolumen wybicia wg reguły Darvasa) mają złotą obwódkę.
- **Szukaj dowolnego symbolu** (`Ctrl+K` lub `/`): spółka ze skanera otwiera się od razu, każda inna (np. NVDA, BRK-B, ^GSPC) jest pobierana z yfinance
  na żądanie i dostaje te same wykresy, boxy i flagi (bez fundamentów, więc CANSLIM będzie niepełny); ostatnie symbole zapamiętane.
- **Filtr…** (osobne okno, na skaner) — filtry po już pobranych danych: RS, EPS Rating, Composite, CANSLIM (≥ n/7, opcjonalnie C i A
  obowiązkowe), odległość do pivotu, od szczytu 52 tyg., ADR, stan Darvasa, sektor, baza, przypięte boxy; gotowe skany; „Zastosuj na liście”.
- **Pomiar zysku**: przytrzymaj lewy przycisk myszy na wykresie i przeciągnij — przerywana linia pokazuje, o ile % cena wzrosła (lub spadła) i ile tygodni (sesji) to zajęło; po puszczeniu przycisku znika. Zwykłe kliknięcie nadal zaznacza box.
- **Schodek**: gdy cena po wybiciu wraca pod dół poprzedniego boxa, nowy box jest anulowany (nieudane wybicie). **Głębokość boxa**: box nie może być głębszy niż 25 % (`MAX_DEPTH_PCT`) — zamknięcie > 25 % pod górą łamie box, zanim dół zdążył się potwierdzić; po złamaniu liczą się kolejne, mniejsze boxy (dawniej jeden box pochłaniał całą korektę).
- **Boxy…** (osobne okno) — przegląd boxów Darvasa w sekcjach: monitorowane, nowe, KUP, do sprawdzenia, trzymaj, sprzedaj, czekaj.
- **Darvas wg PDF „Teoria pudełek”**: Box wybity w górę nadal obowiązuje (śledzimy jego górę, dół i strefę zagrożenia), aż powstanie nowy box albo cena zamknie się pod poziomem wyjścia: 5 % pod dołem boxa, a dla dużego boxa (głębszego niż 10 %) 10 % pod jego górą. Wahania w boxie i w strefie zagrożenia (także podwójne wybicie) tylko obserwujemy; dopiero zamknięcie pod poziomem wyjścia = SPRZEDAJ i szukanie nowego boxa (góra = lokalny szczyt, dół musi się ustalić). Opcja **czysty Darvas** (okno *Filtr…*): KUP = samo przebicie góry, bez filtru wolumenu (1,4×) i limitu +10 % nad górą; ustawienie pamiętane. W skali **Tydzień** góra i dół boxa to zamknięcie + 2 kolejne bez przebicia (boxy krótkich konsolidacji w silnym trendzie, część niepotwierdzona); w skali **Dzień** reguły liczą się na sesjach (3 sesje potwierdzenia jak w PDF). **Rynek** w pasku statusu = S&P 500 i Nasdaq wg tygodniowych EMA 10 / 20 (✅/🛑 + odstęp %); przy korekcie sygnał KUP dostaje ostrzeżenie (tylko informacja, nie filtr). Kolumna i filtr **MACD > sygnał** (12·26·9, w skali listy: tydzień / dzień).
- **Wykres** (osobne okno, można otworzyć kilka) — **Dar-Card** (schodkowe boxy Darvasa na tygodniowych zamknięciach, strefa
  zagrożenia 5 % pod dołem boxa) i **wykres słupkowy** HLC jak w książce O'Neila (SMA 10 / 40 tyg. albo 10 / 50 / 200 sesji, wolumen, MACD 12-26-9,
  linia S&P 500, pivot). Klik w box na Dar-Card = zaznaczenie (wejście / dół / exit na osi ceny), `🔍 Przybliż` = wykres słupkowy
  zawężony do boxa z jego poziomami, `📌 Przypnij` = monitorowanie boxa (status: wybił / w boxie / STREFA / EXIT, widoczny na liście).
    **Dymek przy kursorze**: dane słupka / boxa (zmiana %, wolumen vs średnia, odległość ceny od każdej SMA, od szczytu 52 tyg., MACD; na Dar-Card
  odległość do wybicia, dołu i exitu boxa); najechanie na linię SMA podświetla ją i pokazuje jej nazwę, wartość i nachylenie. Legenda średnich na
  wykresie, skala **logarytmiczna** ceny wszędzie (także Dar-Card i minimapa; pole „log” / klawisz `L`), czytelniejszy MACD (pole „MACD” / klawisz `M`).
Przełącznik **Tydz. / Dzień** w oknie wykresu (domyślnie jak na liście); suwak czasu nad wykresem, kółko myszy lub `+`/`-` — zoom, `←`/`→` — przewijanie, spacja — Dar-Card ↔ słupkowy.

Dzienny Darvas: te same reguły na dziennych zamknięciach (potwierdzenie 3 sesje, wybicie na wolumenie ≥ 1,4× średniej z 50 sesji, nie dalej niż 5 % nad górą) — to moja adaptacja, nie port.
Reguły Darvasa (box, KUP z wolumenem ≥ 1,4×, nie dalej niż 10 % nad górą, stop pod strefą zagrożenia) są portem 1:1 z Momentum
(`desktop/darvas.py`, test parytetu z kodem JS w `tests/`). Heurystyka — **informacyjnie, nie jest to porada inwestycyjna**.

## Wersja portable (GitHub Actions)

Workflow **Build portable** (`.github/workflows/build-portable.yml`) buduje jeden plik bez instalacji dla Windows (`.exe`)
i Linuksa (macOS chwilowo pominięty — build się zawieszał). Po każdym merge do `main` (albo ręcznie: *Actions → Build portable → Run workflow*) gotowe pliki pojawiają się na stronie **Releases → „Momentum Desktop (najnowszy build)”** — pobierasz zip dla swojego systemu bez logowania (tag `v*` tworzy osobne wydanie). Rozpakuj gdziekolwiek i uruchom `MomentumDesktop.exe` — dane i przypięte boxy leżą w folderze `data/` obok programu
(przenosisz cały folder, np. na pendrive). Przy pierwszym starcie są dane przykładowe; **kliknij ⟳ Sync**, żeby pobrać świeże.

## Uruchomienie ze źródeł

```bash
pip install -r requirements.txt
python main.py            # na Linuksie: sudo apt install python3-tk
pip install -r requirements-dev.txt && ruff check . && pytest
```

## Struktura

- `main.py` — start; `desktop/app.py` — okna; `desktop/charts.py` — rysowanie (Canvas); `desktop/darvas.py` — reguły Darvasa;
  `desktop/store.py` — dane, przypięte boxy, filtr lokalny; `desktop/sync.py` — Sync w tle; `desktop/scanners.py` — własne skanery;
  `desktop/builder.py` — kreator i menedżer skanerów; `desktop/qm.py` — skaner Qullamaggie; `desktop/merge.py` — składanie watchlist ze skanów; `desktop/finviz_catalog.py` — katalog filtrów i kolumn Finviz; `desktop/columns.py` — kolumny listy.
- `engine/` — kopia `watchlist.py` + `finviz.py` z Momentum (patrz `engine/README.md`); `seed_data/` — dane startowe.

## Czego (jeszcze) nie ma względem Momentum

„Co robić”, pozycje i kalkulator wielkości pozycji, własne rysowanie boxów / linii, boxy wzorców (cup, flat,
flaga) na Dar-Card. Dane tych wskaźników z silnika są już w pliku `watchlist.json` — można je dodać jako kolejne kolumny / filtry.
