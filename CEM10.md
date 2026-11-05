# CEM10 — strategia miesięczna z zarządzaniem portfelem

Mały program (Windows / Linux, bez instalacji). Uruchom `CEM10`, dane zapisują się w folderze `data/` obok programu.

## Co miesiąc (1.–3. dnia, po zamknięciu świecy miesięcznej)

Program otwiera się w swoim oknie (Windows: WebView2, wbudowany w Windows 10 / 11; bez niego — w domyślnej przeglądarce). Po lewej widoki, u góry stan rynku i dwa przyciski.

1. **Pobierz listę** (prawy górny róg) — lider (SPY / QQQ), potem lista tickerów indeksu lidera z Finviz, ceny miesięczne z Yahoo Finance, skład WIG20 / mWIG40. Liczy tylko z zamkniętych miesięcy. Postęp widać pod paskiem.
2. **Konto**: albo **Raport XTB** (xStation: Historia konta → Eksport, zip z plikiem xlsx dla każdego konta; program nie łączy się z XTB), albo **konto ręczne** (Portfel → „＋ Konto ręczne”): wpisujesz gotówkę, „wpłacono netto” i pozycje (ticker, rynek USA / GPW / ETF, liczba akcji, średnia cena zakupu). Ceny i kurs USD/PLN program pobiera z Yahoo po zapisie albo przyciskiem „Odśwież ceny”, a wpisana „Cena teraz” zostaje na stałe. „＋ Wpłać” dopisuje wpłatę do gotówki i do „wpłacono netto”. Konta można przełączać; konto ręczne nie ma historii (tylko raport XTB ma daty transakcji). **Dzisiejszy zakup na koncie z raportu XTB**: Portfel → „＋ Dopisz zakup” (ticker, rynek, liczba akcji, cena, opcjonalnie kwota z konta w zł). Program dolicza pozycję, średnią cenę zakupu, stop i gotówkę od razu; wpisy znikają po wczytaniu nowszego raportu XTB (raport już je zawiera). Konto ręczne i konto z raportu są osobne, więc na koncie ręcznym transakcje wpisujesz bezpośrednio w tabeli pozycji.
3. **Ten miesiąc** — wartość konta, wynik, wpłaty, zajęte miejsca; **Co zrobić**: wpisz wpłatę, a program pokaże gotowe zlecenia (SPRZEDAJ / KUP / DOPŁAĆ) z kwotą i przybliżoną liczbą akcji; „Kopiuj plan” kopiuje je jako tekst. Obok: lider USA, filtry rynku i **Udziały**.
4. **Baza: ETF S&P 500** — w karcie „Udziały” (i w Ustawieniach, suwak + pole) ustawiasz, jaką część całego kapitału ma stanowić ETF jako baza. Reszta idzie w CEM10, a nowe wpłaty dzielą się według tych udziałów; podział części CEM10 na USA i GPW (domyślnie 2 : 1, jak miejsca 10 : 5) też zmienisz w Ustawieniach. Karta pokazuje „do uzupełnienia” w zł dla każdego koszyka.
5. **Portfel** — każda pozycja: udział, wynik, cena zakupu, odległość od SMA 10 i od stopu −40 %, status CEM10.
6. **Lista USA / Lista GPW** — kandydaci z rankingu; zielony pasek = do kupienia (pierwsze 10 / 5), „masz” = już w portfelu; wyszukiwarka.
7. **Historia konta** — krzywa kapitału: wartość konta, wpłaty netto (schodki), zielony obszar = zysk, czerwony = strata; zakres 6 mies. / 1 rok / 3 lata / całość, najechanie myszą pokazuje datę, wartość, wpłaty i wynik; „pokaż sprzedaże” dokłada kropki. „Wyceń cenami dziennymi” pobiera ceny z Yahoo.
8. **Ustawienia** — baza ETF, ticker ETF, konto, trzymane spółki (szybka kontrola), **skład GPW** (popraw po każdej rewizji: marzec, czerwiec, wrzesień, grudzień), jasny / ciemny motyw.
9. **Wykres miesięczny po prawej** (okno szersze niż ok. 1320 px; przycisk „Wykres” u góry pokazuje / ukrywa panel): kliknij spółkę na liście, w portfelu albo w planie, a wykres przełączy się bez zamykania; strzałki ↑ ↓ przechodzą po spółkach. Słupki OHLC, SMA 10, wolumen (zielony = wzrost, czerwony = spadek) ze średnią 10 mies., linia zakupu i stop −40 %; zakres 3 / 5 / 10 lat, skala log / lin, podpowiedź z OHLC, SMA i wolumenem przy najechaniu. Świece są pobierane raz i zapisywane w `data/charts/` (ważne 6 godzin, potem odświeżają się same albo przyciskiem „↻ Odśwież”; bez sieci pokazują się ostatnie zapisane dane), a sąsiednie spółki z listy dociągają się w tle, więc przełączanie strzałkami jest natychmiastowe. W polu nad wykresem sprawdzisz **dowolny ticker** (np. NVDA albo ALE.WA). Na węższym oknie wykres otwiera się w szufladzie.

## Reguły

- **USA**: lider = SPY albo QQQ z wyższym zwrotem 5M; kandydaci z indeksu lidera: zwrot 6M > +30 % i zamknięcie miesiąca nad SMA 10; ranking po 6M; 10 pozycji.
- **GPW**: WIG20 + mWIG40 bez lidera; C-8 (3M > 0, 12M > +30 %, nad SMA 10); ranking po 6M; 5 pozycji.
- **Wyjście**: zamknięcie miesiąca pod SMA 10 ; stop awaryjny −40 % od ceny zakupu.
- **Wpłaty**: symulacja 2009–2026 (3 000 zł + 500 zł / mies. + 5 000 zł w styczniu): dopełnianie do wagi ≥ trzymania reszty w gotówce we wszystkich 5 datach startu (+1…8 % po 3–5 latach), dokładanie do wszystkich spółek gorzej (−13 % po 17 latach).

To wynik reguł z backtestu, nie rekomendacja inwestycyjna.
