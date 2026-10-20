# Momentum Desktop

Prosta aplikacja okienkowa (Python + Tkinter, ciemny motyw) z **jedną strategią**, wybraną w backteście na płynnym rynku USA w latach 2015–2026:

| Etap | Reguła |
|---|---|
| Lista do pobrania | **Finviz**, bezpieczny filtr wstępny `ind_stocksonly,sh_price_o10,sh_avgvol_o300,fa_salesqoq_o15` (tylko akcje, cena > 10 $, śr. wolumen > 300 tys., przychody kw. > 15 % r/r). W teście nie odciął żadnego z dużych zwycięzców; zmienisz go w *Filtr Finviz / ustawienia…* |
| Warunki | obrót dzienny **≥ 50 mln $**, przychody kw. **≥ +15 % r/r**, marża operacyjna **≥ +3 pp r/r** (fundamenty z SEC EDGAR) |
| Kolejność | od największej zmiany marży operacyjnej r/r |
| Wejście | **Green Line**: rekord wszech czasów na zamknięciach **miesięcznych**, który stoi **≥ 3 zamknięte miesiące** (po nowym rekordzie obowiązuje stara linia, dopóki nowy nie przestoi 3 miesięcy); kupno, gdy tydzień zamknie się **0–10 % nad linią** |
| Wyjście | **tygodniowy MACD (12, 26, 9)**: po przecięciu sygnału w dół stop pod Low tego tygodnia; do tego stop **10 %** pod wejściem |

Heurystyka z backtestu (spółki z dzisiejszej listy, bez spółek wycofanych z obrotu), nie porada inwestycyjna.

## Okno

- **Lista**: ticker, spółka, sektor, cena, Green Line, odległość od linii, stan GLB (*WYBICIE* = ten tydzień zamknął się nad linią, poprzedni nie;
  *SYGNAŁ* = 0–10 % nad linią; *NAD* = dalej; *POD*), MACD (nad / pod sygnałem) i stop z ostatniego przecięcia, zmiana marży operacyjnej i brutto r/r,
  przychody r/r, kwartał danych, obrót. Zielone wiersze = warunki spełnione i sygnał GLB. Domyślnie widać tylko spółki spełniające warunki (pole na pasku).
  Klik w nagłówek sortuje; Enter / dwuklik = wykres; zaznaczenie na liście przełącza otwarty wykres.
- **Wykres** (jeden, tygodniowy, 3 lata): słupki High–Low z kreską zamknięcia, SMA 10 i 40 tyg., **Green Line** (z ceną i górną granicą kupna +10 %),
  stop z MACD (czerwona przerywana), wolumen ze średnią 10 tyg., MACD z ▼ w tygodniach przecięcia w dół. ↑ / ↓ = następna / poprzednia spółka, ruch myszy = dane tygodnia.
- **Ctrl+K**: dowolny symbol (np. SPY, ^GSPC, NVDA) — te same obliczenia i wykres; ostatnie symbole są zapamiętane.

## Dane (darmowe źródła, jak najmniej zapytań)

- **⟳ Sync (F5)**: Finviz (lista) → yfinance **tygodniowe 3 lata** (wykres, średnie, MACD, obrót) → dla spółek z obrotem ≥ 50 mln $:
  yfinance **miesięczne z całej historii** (Green Line; zamknięte miesiące trzymamy w pamięci podręcznej i pobieramy ponownie dopiero po zamknięciu
  kolejnego miesiąca) i **SEC** (fundamenty; odświeżane co 7 dni). Bez danych dziennych.
- Pliki w `data/` obok programu: `scan.json` (lista i świece), `monthly.json`, `sec.json`, `settings.json`.
- SEC prosi o User-Agent z kontaktem — wpisz swój w ustawieniach.
- Stan GLB liczony jest na ostatniej świecy tygodniowej; w trakcie tygodnia to jeszcze nie zamknięcie — sygnał obowiązuje po zamknięciu piątku.

## Uruchomienie

```bash
pip install -r requirements.txt
python main.py
```

Testy: `pip install -r requirements-dev.txt && python -m pytest -q` (GUI pod `xvfb-run` na Linuksie), `ruff check .`.
Wersja portable (Windows / Linux): workflow *Build portable* (Actions → Artifacts albo Releases → *latest*).
