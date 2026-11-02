# CEM10 — strategia miesięczna z zarządzaniem portfelem

Mały program (Windows / Linux, bez instalacji). Uruchom `CEM10`, dane zapisują się w folderze `data/` obok programu.

## Co miesiąc (1.–3. dnia, po zamknięciu świecy miesięcznej)

1. **⟳ Pobierz listę** — skład S&P 500 i Nasdaq-100 (Wikipedia), sito Finviz, ceny miesięczne z Yahoo Finance, skład WIG20 / mWIG40 (wbudowany, popraw przyciskiem **Skład GPW…** po każdej rewizji GPW: marzec, czerwiec, wrzesień, grudzień). Liczy tylko z zamkniętych miesięcy.
2. **📂 Wczytaj raport XTB…** — w xStation: Historia konta → Eksport (zip z plikiem xlsx dla każdego konta). Program nie łączy się z XTB, czyta tylko plik.
3. Zakładka **📊 Portfel**: wartość konta, wpłacono, wynik, udział każdej spółki (w koncie i w koszyku), cena zakupu, **stop −40 %**, status CEM10 (kandydat #, trzymaj, SPRZEDAJ pod SMA 10 / przy stopie).
4. **Plan**: wpisz wpłatę i udziały docelowe (USA / GPW / ETF). Program rozdziela gotówkę + wpłatę + sprzedaże na koszyki według niedoboru, kupuje nowe spółki z listy na wolne miejsca (USA 10, GPW 5) za wagę docelową, a resztę **dopełnia** trzymanym spółkom, które nadal są kandydatami, do tej wagi (dopłaty < 100 zł pomija). Przy filtrze rynku (SPY / indeks GPW pod SMA 12) nie kupuje.
5. Zakładka **📈 Krzywa kapitału**: wartość konta i wpłaty w czasie, ▲ wpłaty, ▼ sprzedaże (zielona = zysk). **⟳ Przelicz krzywą** wycenia pozycje cenami dziennymi z Yahoo.
6. Dwuklik na spółce = **wykres miesięczny**: słupki, SMA 10, wolumen (zielony = wzrost, czerwony = spadek) ze średnią 10 mies., linia zakupu i stop −40 %.

## Reguły

- **USA**: lider = SPY albo QQQ z wyższym zwrotem 5M; kandydaci z indeksu lidera: zwrot 6M > +30 % i zamknięcie miesiąca nad SMA 10; ranking po 6M; 10 pozycji.
- **GPW**: WIG20 + mWIG40 bez lidera; C-8 (3M > 0, 12M > +30 %, nad SMA 10); ranking po 6M; 5 pozycji.
- **Wyjście**: zamknięcie miesiąca pod SMA 10 (w USA też wypadnięcie z indeksów); stop awaryjny −40 % od ceny zakupu.
- **Wpłaty**: symulacja 2009–2026 (3 000 zł + 500 zł / mies. + 5 000 zł w styczniu): dopełnianie do wagi ≥ trzymania reszty w gotówce we wszystkich 5 datach startu (+1…8 % po 3–5 latach), dokładanie do wszystkich spółek gorzej (−13 % po 17 latach).

To wynik reguł z backtestu, nie rekomendacja inwestycyjna.
