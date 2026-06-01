# Changelog

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

- Przebudowano interfejs na nowoczesny panel z wyraźnym hero, kartami, nową paletą kolorów i sygnetem aplikacji.
- Dodano chipy obsługiwanych serwisów, czytelniejsze stany puste oraz spójny wygląd widoków analizy i zadań.
- Ulepszono responsywny układ na telefonach.

## 1.1.2

- Dodano panel miejsca na dysku dla skonfigurowanego katalogu pobrań.
- Dodano wykres zajętości oraz wartości: wolne, zajęte i łączne miejsce.

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
