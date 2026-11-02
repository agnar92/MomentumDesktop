# CEM10 — strategia miesięczna z zarządzaniem portfelem

Mały program (Windows / Linux, bez instalacji). Uruchom `CEM10`, dane zapisują się w folderze `data/` obok programu.

## Co miesiąc (1.–3. dnia, po zamknięciu świecy miesięcznej)

Program otwiera się w swoim oknie (Windows: WebView2, wbudowany w Windows 10 / 11; bez niego — w domyślnej przeglądarce). Po lewej widoki, u góry stan rynku i dwa przyciski.

1. **Pobierz listę** (prawy górny róg) — skład S&P 500 i Nasdaq-100 (Wikipedia), sito Finviz, ceny miesięczne z Yahoo Finance, skład WIG20 / mWIG40. Liczy tylko z zamkniętych miesięcy. Postęp widać pod paskiem.
2. **Raport XTB** — w xStation: Historia konta → Eksport (zip z plikiem xlsx dla każdego konta). Program nie łączy się z XTB, czyta tylko plik.
3. **Ten miesiąc** — wartość konta, wynik, wpłaty, zajęte miejsca; **Co zrobić**: wpisz wpłatę, a program pokaże gotowe zlecenia (SPRZEDAJ / KUP / DOPŁAĆ) z kwotą i przybliżoną liczbą akcji; „Kopiuj plan” kopiuje je jako tekst. Obok: lider USA, filtry rynku i udziały koszyków (teraz / cel).
4. **Portfel** — każda pozycja: udział, wynik, cena zakupu, odległość od SMA 10 i od stopu −40 %, status CEM10.
5. **Lista USA / Lista GPW** — kandydaci z rankingu; zielony pasek = do kupienia (pierwsze 10 / 5), „masz” = już w portfelu; wyszukiwarka.
6. **Historia konta** — wartość konta i wpłaty w czasie, sprzedaże (zielona kropka = zysk); „Wyceń cenami dziennymi” pobiera ceny z Yahoo.
7. **Ustawienia** — udziały docelowe (USA / GPW / ETF), ticker ETF, wybór konta, trzymane spółki bez raportu XTB, **skład GPW** (popraw po każdej rewizji: marzec, czerwiec, wrzesień, grudzień), jasny / ciemny motyw.
8. Kliknięcie spółki = **wykres miesięczny**: słupki, SMA 10, wolumen (zielony = wzrost, czerwony = spadek) ze średnią 10 mies., linia zakupu i stop −40 %.

## Reguły

- **USA**: lider = SPY albo QQQ z wyższym zwrotem 5M; kandydaci z indeksu lidera: zwrot 6M > +30 % i zamknięcie miesiąca nad SMA 10; ranking po 6M; 10 pozycji.
- **GPW**: WIG20 + mWIG40 bez lidera; C-8 (3M > 0, 12M > +30 %, nad SMA 10); ranking po 6M; 5 pozycji.
- **Wyjście**: zamknięcie miesiąca pod SMA 10 (w USA też wypadnięcie z indeksów); stop awaryjny −40 % od ceny zakupu.
- **Wpłaty**: symulacja 2009–2026 (3 000 zł + 500 zł / mies. + 5 000 zł w styczniu): dopełnianie do wagi ≥ trzymania reszty w gotówce we wszystkich 5 datach startu (+1…8 % po 3–5 latach), dokładanie do wszystkich spółek gorzej (−13 % po 17 latach).

To wynik reguł z backtestu, nie rekomendacja inwestycyjna.
