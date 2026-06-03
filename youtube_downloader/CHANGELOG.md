# Changelog

## 1.3.16

- Dodano przycisk `Usuń wpis` obok `Pobierz ponownie` w historii pobrań.
- Usunięcie wpisu z historii nie kasuje pobranego pliku z dysku.
- Dotychczasową akcję zwalniania miejsca opisano wyraźniej jako `Usuń plik`.

## 1.3.15

- Historia pobrań w sekcji `Biblioteka` wykorzystuje pełną szerokość widoku na komputerze.
- Panele ustawień i miejsca na dysku są wyświetlane poniżej biblioteki w dwóch równych kolumnach.

## 1.3.14

- Dodano usuwanie pojedynczych zakończonych zadań z widoku `Zadania`.
- Dodano zaznaczanie wielu rekordów i przycisk `Usuń zaznaczone`.
- Dodano czyszczenie listy zadań z zachowaniem aktywnych pobrań i zapisów live.

## 1.3.13

- Widok `Zadania` odświeża postęp pobierania na żywo co `500 ms` i synchronizuje się natychmiast po powrocie do karty.
- Wyłączono cache odpowiedzi API zadań, aby Home Assistant Ingress nie pokazywał nieaktualnego postępu.

## 1.3.12

- Ukryto storyboardy YouTube `sb*` w formacie `mhtml` na liście plików do pobrania.
- Zablokowano ręczne uruchamianie pobierania storyboardów przez pole ID konkretnego formatu.

## 1.3.11

- Dodano proste komunikaty błędów dla problemów z internetem, braku miejsca na dysku oraz błędów `ffmpeg`.
- Nieudane generowanie miniatury nie przerywa poprawnego pobrania filmu: panel pokazuje ostrzeżenie w historii i przy zadaniu.

## 1.3.10

- Dodano przycisk `Pobierz ponownie` przy rekordach historii zwykłych pobrań, także po usunięciu lokalnego pliku.
- Historia zachowuje ID konkretnego formatu, aby ponowne pobranie odtwarzało również wybór z tabeli formatów.

## 1.3.17

- Dodano tryb oczekiwania na transmisje live i automatyczny start nagrywania po rozpoczęciu.

## 1.3.16

- Dodano przycisk `Usuń wpis` obok `Pobierz ponownie` w historii pobrań.
- Usunięcie wpisu z historii nie kasuje pobranego pliku z dysku.
- Dotychczasową akcję zwalniania miejsca opisano wyraźniej jako `Usuń plik`.
- Dodano podgląd miniaturek w historii pobrań oraz automatyczne usuwanie miniatury razem z plikiem wideo.

## 1.3.7

- Dodano rozmiar pobierania w widoku `Zadania`, w tym bieżącą i całkowitą liczbę bajtów, gdy `yt-dlp` ją udostępnia.

## 1.3.6

- Dodano zatrzymywanie i wznawianie zwykłych pobrań z zachowaniem częściowych plików `yt-dlp`.
- Zapamiętywany jest wybrany identyfikator formatu, aby wznowienie używało tego samego wariantu.

## 1.3.5

- Zastąpiono nazwę pliku przy zadaniu czytelnym przyciskiem `Pobierz`.

## 1.3.4

- Dodano przycisk `Pobierz` przy każdym formacie zwróconym przez analizę materiału.

## 1.3.3

- Dodano trwałą kolejkę zadań w `/data/jobs/queue.json` oraz status `przerwane` dla operacji aktywnych podczas restartu.
- Przeniesiono listę obsługiwanych domen i aktywnych statusów do backendu, który przekazuje je frontendowi jako JSON.
- Dodano filtrowanie, sortowanie i paginację historii pobrań.

## 1.3.2

- Dodano czytelny komunikat błędu pollingu zadań bez usuwania ostatniego poprawnego stanu listy.
- Dodano licznik aktywnych zadań w nagłówku oraz walidację pola identyfikatora konkretnego formatu.

## 1.3.1

- Ujednolicono nazwę dodatku, repozytorium, obrazu i logów startowych na `Media Web Downloader`.

## 1.3.0

- Dodano jawny tryb magazynu `nfs` dla udziałów zamontowanych przez Home Assistant.
- Dodano opcję `nfs_download_dir` oraz kontrolę obecności i zapisywalności udziału przy starcie.
- Wykres miejsca na dysku automatycznie pokazuje pojemność wybranego udziału NFS.

## 1.2.1

- Potwierdzenie usuwania pliku pokazuje teraz nazwę oraz rozmiar wybranego pliku.

## 1.2.0

## 1.3.17

- Dodano tryb oczekiwania na transmisje live i automatyczny start nagrywania po rozpoczęciu.

## 1.1.2


## 1.1.1

- Dodano polskie objaśnienia standardowych przełączników Home Assistant: `Start on boot`, `Watchdog`, `Auto update` oraz `Show in sidebar`.
- Wyjaśniono, że etykiety tych przełączników są tłumaczone przez frontend Home Assistant, a nie przez pliki tłumaczeń dodatku.

## 1.1.0

- Dodano publiczne materiały Instagram obsługiwane przez `yt-dlp`: posty, reels, stories, tagi i profile.
- Dodano publiczne kanały live, VOD i klipy Kick obsługiwane przez `yt-dlp`.
- Uogólniono mechanizm zapisu aktywnego live i dodano nazwę rozpoznanego serwisu w wyniku analizy.
- Zachowano dotychczasowy slug oraz katalog pobrań, aby aktualizacja nie zmieniała lokalizacji danych.

## 1.0.5

- Dodano rozmiar pliku w historii pobrań na komputerze i telefonie.
- Rozmiar jest utrwalany w historii i pozostaje widoczny po usunięciu pliku.

## 1.0.4

- Dodano spinner, blokadę przycisku i komunikat oczekiwania po uruchomieniu analizy URL.

## 1.0.3

- Poprawiono katalog roboczy i ścieżkę importu Gunicorna dla aplikacji skopiowanej do `/app`.

## 1.0.2

- Usunięto zależność buildu od serwerów pakietów Alpine.
- Dodano statyczne wieloarchitekturowe binaria `ffmpeg` i `ffprobe`.
- Dodano lokalny wheelhouse Pythona instalowany offline podczas budowania obrazu.

## 1.0.1

- Dodano ponawianie instalacji pakietów Alpine podczas budowania obrazu po chwilowych błędach DNS.
- Dodano jawne limity czasu i ponawianie pobierania zależności Python.

## 1.0.0

- Pierwsze wydanie dodatku Home Assistant.
- Panel Ingress z analizą filmów, Shorts, playlist i transmisji live.
- Pobieranie w tle z postępem, prędkością i ETA.
- Kontrolowane uruchamianie i zatrzymywanie zapisu live.
- Trwała historia JSON oraz pliki w `/share` lub `/media`.
- Wieloarchitekturowe budowanie dla aktualnie wspieranych platform `amd64` i `aarch64`.
- Opcjonalna aktualizacja `yt-dlp` przy każdym starcie dodatku.
