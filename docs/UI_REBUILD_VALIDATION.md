# UI i operacje zbiorcze — 1.3.106

## Zmiany

Boczna nawigacja na komputerze, rozwijane menu na telefonie, formularz z czytelnymi
komunikatami i osobny panel magazynu. Motywy jasny/ciemny, widoczny fokus, skrót
Ctrl+Enter i wyłączenie przesunięcia nawigacji w trybie kinowym.

Nowy `workspace.js` obsługuje tylko nawigację i formularz. Dotychczasowy `app.js`
nadal odpowiada za kolejkę, bibliotekę oraz odtwarzacz. Nowy formularz nie ma klasy
`.url-form`, co zapobiega podwójnemu przypięciu starego i nowego handlera.

Poprawki obejmują przywracanie formularza po błędzie w tle/BFCache, blokadę
podwójnego wysłania, limit czasu bez automatycznego ponowienia, zachowanie wyboru
adresów, wszystkie pliki zadania w akcjach zbiorczych, kopiowanie opcji i magazynu
przy ponawianiu oraz sprzątanie ZIP-ów po błędzie i zamknięciu odpowiedzi WSGI.

## Weryfikacja wykonana lokalnie

- 17 testów Pythona: pomocnicze operacje plikowe oraz rzeczywisty handler operacji
  zbiorczych uruchamiany z atrapami żądania/usług. To nie są testy pełnego Flask.
- 6 testów Node: parser adresów, walidacja, tłumaczenia i stała limitu czasu.
- 11 kontroli komponentu w Chromium: układ 320–1920 px, menu i fokus, ciemny motyw,
  walidacja, zachowanie odznaczeń, pojedyncze wysłanie/CSRF/Ingress, błąd sieci
  w ukrytej karcie, odpowiedź HTML, BFCache, margines trybu kinowego i błędy JS.
  Backend i stary bundle były zastąpione atrapami; podgląd używał lokalnego CSS
  Bootstrap 5.3.6. Aplikacja nadal ładuje dotychczasowy Bootstrap 5.3.3 z CDN.
- Sprawdzono składnię nowych modułów oraz zgodność wersji manifestu, Dockerfile
  i najnowszego wpisu changelogu. Starsza zawartość changelogu zachowana bez zmian.

Polecenia z katalogu repozytorium:

```sh
python -m unittest discover -s youtube_downloader/tests -p 'test_bulk_operations.py' -v
node --test youtube_downloader/tests/test_workspace.js
node --check youtube_downloader/app/static/js/workspace.js
python youtube_downloader/scripts/bump_version.py --check
```

`test_workspace_javascript.py` uruchamia testy Node w ramach unittest, gdy Node
jest dostępny; w przeciwnym razie jawnie oznacza ten test jako pominięty.

## Granice weryfikacji

Nie wykonano lokalnie pełnego zestawu istniejących testów, Ruff, buildów Docker,
rzeczywistych pobrań, testów NFS ani wdrożenia w Home Assistant. Wynik CI należy
odczytać z PR; powyższe wyniki nie oznaczają przejścia całego CI ani braku wszystkich
błędów w aplikacji. Parser listy adresów zachowuje istniejący kontrakt separatorów
(nowe linie, przecinki, średniki); rozdzielanie separatorów wewnątrz URL pozostaje
ograniczeniem istniejącego backendu.
