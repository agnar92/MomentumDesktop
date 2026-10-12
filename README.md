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
- **Równoległa synchronizacja i szybkie okno**: kilka skanerów może pobierać dane jednocześnie (każdy sync w osobnym procesie programu,
  własny dziennik w osobnym oknie; ten sam skaner naraz tylko raz). Zamknięcie głównego okna nie kończy programu, dopóki są inne okna (główne się chowa, wracasz z małego okna). Małe okno **Skanery** (menu *Skanery → Szybkie okno skanerów*) pokazuje skanery
  w kolejności ostatniego otwarcia (● otwarty, ⟳ trwa sync); program zapamiętuje, które okna były otwarte, i przy następnym starcie je odtwarza
  (`data/session.json`).
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

Workflow **Build portable** (`.github/workflows/build-portable.yml`) buduje jeden plik bez instalacji dla Windows (`.exe`),
Linuksa i macOS. Po każdym merge do `main` (albo ręcznie: *Actions → Build portable → Run workflow*) gotowe pliki pojawiają się na stronie **Releases → „Momentum Desktop (najnowszy build)”** — pobierasz zip dla swojego systemu bez logowania (tag `v*` tworzy osobne wydanie). Rozpakuj gdziekolwiek i uruchom `MomentumDesktop.exe` — dane i przypięte boxy leżą w folderze `data/` obok programu
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
  `desktop/builder.py` — kreator i menedżer skanerów; `desktop/finviz_catalog.py` — katalog filtrów i kolumn Finviz; `desktop/columns.py` — kolumny listy.
- `engine/` — kopia `watchlist.py` + `finviz.py` z Momentum (patrz `engine/README.md`); `seed_data/` — dane startowe.

## Czego (jeszcze) nie ma względem Momentum

„Co robić”, pozycje i kalkulator wielkości pozycji, własne rysowanie boxów / linii, boxy wzorców (cup, flat,
flaga) na Dar-Card. Dane tych wskaźników z silnika są już w pliku `watchlist.json` — można je dodać jako kolejne kolumny / filtry.
