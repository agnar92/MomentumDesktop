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
- **Skaner…** (osobne okno) — filtry po RS, EPS Rating, Composite, CANSLIM (≥ n/7, opcjonalnie C i A obowiązkowe), odległości do pivotu, odległości od szczytu 52 tyg., ADR, stanie
  Darvasa, sektorze, bazie, przypiętych boxach; gotowe skany; „Pokaż na liście głównej”. W tym samym oknie edytujesz **filtry
  Finviz** (kody `f=` z adresu skanera) i pobierasz dane od razu przyciskiem.
- **Boxy…** (osobne okno) — przegląd boxów Darvasa w sekcjach: monitorowane, nowe, KUP, do sprawdzenia, trzymaj, sprzedaj, czekaj.
- **Wykres** (osobne okno, można otworzyć kilka) — **Dar-Card** (schodkowe boxy Darvasa na tygodniowych zamknięciach, strefa
  zagrożenia 5 % pod dołem boxa) i **wykres słupkowy** HLC jak w książce O'Neila (SMA 10 / 40 tyg. albo 10 / 50 / 200 sesji, wolumen, MACD 12-26-9,
  linia S&P 500, pivot). Klik w box na Dar-Card = zaznaczenie (wejście / dół / exit na osi ceny), `🔍 Przybliż` = wykres słupkowy
  zawężony do boxa z jego poziomami, `📌 Przypnij` = monitorowanie boxa (status: wybił / w boxie / STREFA / EXIT, widoczny na liście).
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
  `desktop/store.py` — dane, przypięte boxy, filtry skanera; `desktop/sync.py` — Sync w tle.
- `engine/` — kopia `watchlist.py` + `finviz.py` z Momentum (patrz `engine/README.md`); `seed_data/` — dane startowe.

## Czego (jeszcze) nie ma względem Momentum

„Co robić”, pozycje i kalkulator wielkości pozycji, własne rysowanie boxów / linii, boxy wzorców (cup, flat,
flaga) na Dar-Card. Dane tych wskaźników z silnika są już w pliku `watchlist.json` — można je dodać jako kolejne kolumny / filtry.
