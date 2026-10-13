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
  float, wyniki tygodnia/miesiąca…) zamawiasz w kreatorze (zakładka *Kolumny z Finviz*) i pojawiają się po Sync. Pierwszy Sync nowego skanera
  pobiera też fundamenty; EPS i estymaty są wspólne dla wszystkich skanerów (spółka znana innemu skanerowi nie jest pobierana drugi raz).
- **Skaner Qullamaggie** (*Skanery → Nowy skaner Qullamaggie…*): prosty skaner po cenie — **obrót dzienny** (cena × wolumen), **ADR** i **cena / min Low** z okna
  1M (~22 sesji), 3M (~66), 6M (~132). Reguła jak w Momentum: z płynnych spółek (obrót ≥ próg, ADR ≥ próg) bierze górne X % rankingu cena / min Low
  osobno dla każdego okna, a wynik to suma (kolumna *Okna QM* mówi, w których oknach spółka się załapała). Progi (obrót 50–100 mln, ADR 2–4, górne 10 %)
  zmieniasz na bieżąco przyciskiem **Qullamaggie…** w oknie skanera — licznik pokazuje, ile spółek zostanie (cel 30–50), **bez ponownego pobierania**.
  Sync pobiera tylko ceny (bez EPS) i zapisuje spółki powyżej *progów pobierania* (domyślnie obrót 25 mln, ADR 2 — obniż je w edytorze, jeśli chcesz
  schodzić niżej na liście). **Co robi Finviz:** kreator dobiera filtr wstępny (`cap_smallover`, `ind_stocksonly`, średni wolumen, cena > 10 $, a przy ADR ≥ 3
  zmienność miesiąca — Finviz liczy ją niemal tak samo jak ADR, próg filtra jest o 1 pkt niższy dla zapasu); dokładny obrót i ADR liczy program.
  **Szybki Sync (dwa etapy, domyślny):** etap 1 pobiera z Finviz cały zbiór jednym widokiem (cena, średni wolumen, zmienność, zwroty 1M / 3M / 6M, odległość od
  minimum 50 dni i 52 tygodni) i wybiera kandydatów — czołówkę pięciu rankingów przybliżających cena / min Low (2× więcej, niż wynika z górnych X %);
  etap 2 pobiera ceny z yfinance tylko dla nich i liczy dokładny obrót, ADR i cena / min Low. Na sektorze Technology (380 spółek) kandydatów było
  155–220 zamiast 380, a wszystkie 43 spółki z pełnego Syncu trafiły do wyniku. Górne X % liczone jest od wielkości całego płynnego zbioru z Finviz
  (nie od kandydatów). Ranking z Finviz jest przybliżony — odznaczenie „Szybki Sync” w edytorze skanera pobiera ceny wszystkich spółek. Darmowy screener
  Finviz oddaje maksymalnie 1000 wierszy — większy zbiór program pobiera sektor po sektorze i skleja.
- **Scalanie skanerów** (*Skanery → Scal skanery w jedną listę…*): jedna lista = suma spółek z wybranych skanerów (bez duplikatów, kolumna *Źródła*), z ich
  wykresami i danymi; źródło Qullamaggie wnosi tylko spółki wybrane jego progami. Nic nie jest pobierane — lista odświeża się sama po Sync źródła
  (albo przyciskiem *Scal ponownie*). Np. trzy skanery cena/min Low 1M, 3M i 6M scalisz w jedną watchlistę (to samo daje jeden skaner z trzema oknami).
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
- **Boxy…** (osobne okno) — przegląd boxów Darvasa w sekcjach: monitorowane, nowe, KUP, do sprawdzenia, trzymaj, sprzedaj, czekaj.
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
  `desktop/builder.py` — kreator i menedżer skanerów; `desktop/qm.py` — skaner Qullamaggie; `desktop/merge.py` — scalanie skanerów; `desktop/finviz_catalog.py` — katalog filtrów i kolumn Finviz; `desktop/columns.py` — kolumny listy.
- `engine/` — kopia `watchlist.py` + `finviz.py` z Momentum (patrz `engine/README.md`); `seed_data/` — dane startowe.

## Czego (jeszcze) nie ma względem Momentum

„Co robić”, pozycje i kalkulator wielkości pozycji, własne rysowanie boxów / linii, boxy wzorców (cup, flat,
flaga) na Dar-Card. Dane tych wskaźników z silnika są już w pliku `watchlist.json` — można je dodać jako kolejne kolumny / filtry.
