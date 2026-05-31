# YouTube Web Downloader

Dodatek Home Assistant udostępnia przez Ingress panel do analizy i legalnego pobierania obsługiwanych materiałów YouTube przez `yt-dlp`. Interfejs rozpoznaje filmy, Shorts, playlisty, aktywne transmisje live oraz zaplanowane transmisje, jeśli extractor zwraca ich metadane.

Obraz korzysta z oficjalnego wieloplatformowego `ghcr.io/home-assistant/base-python:3.14-alpine3.23` i wspiera aktualne architektury Home Assistant: `amd64` oraz `aarch64`. Platforma `armv7` nie jest już wspierana przez Home Assistant.

## Konfiguracja

Opcje ustawia się na karcie **Konfiguracja** dodatku w Home Assistant:

| Opcja | Domyślnie | Znaczenie |
| --- | --- | --- |
| `download_dir` | `/share/youtube_downloader` | Docelowy katalog pobrań wewnątrz `/share` albo `/media` |
| `max_concurrent_jobs` | `2` | Limit równoległych pobrań i zapisów live, od 1 do 5 |
| `update_ytdlp_on_start` | `true` | Próba aktualizacji `yt-dlp` przed startem aplikacji |
| `allow_external_port` | `false` | Informacyjna zgoda na planowane użycie zewnętrznego portu |
| `external_port` | `8099` | Preferowany port dostępu zewnętrznego |
| `debug` | `false` | Rozszerzone logowanie aplikacji |
| `preferred_format` | `best` | Preferencja prezentowana przez aplikację: `best`, `audio` albo `video` |

Przykład:

```yaml
download_dir: /share/youtube_downloader
max_concurrent_jobs: 2
update_ytdlp_on_start: true
allow_external_port: false
external_port: 8099
debug: false
preferred_format: best
```

Supervisor zapisuje opcje w `/data/options.json`. Aplikacja odczytuje ten plik przy uruchomieniu i stosuje bezpieczne wartości domyślne dla błędnych danych. Po zmianie opcji uruchom dodatek ponownie.

## Katalogi

- `/data` zawiera trwałą historię w `/data/jobs/history.json`.
- `/share` jest zalecanym miejscem na pliki dostępne dla użytkownika; domyślnie używany jest `/share/youtube_downloader`.
- `/media` może być alternatywnym katalogiem pobrań.

## Endpointy

| Metoda | Ścieżka | Opis |
| --- | --- | --- |
| `GET` | `/` | Panel główny |
| `POST` | `/analyze` | Analiza URL bez pobierania |
| `POST` | `/download` | Uruchomienie pobrania |
| `POST` | `/live/start` | Uruchomienie zapisu aktywnego live |
| `POST` | `/live/stop/<job_id>` | Zatrzymanie zapisu live |
| `GET` | `/jobs` | Lista zadań |
| `GET` | `/api/jobs` | Lista zadań JSON |
| `GET` | `/api/jobs/<job_id>` | Stan zadania JSON |
| `GET` | `/downloaded/<filename>` | Pobranie gotowego pliku |
| `POST` | `/delete/<filename>` | Usunięcie pliku |
| `GET` | `/health` | Healthcheck watchdoga |

## Diagnostyka

W Home Assistant otwórz kartę dodatku:

1. Karta **Logi** pokazuje stdout i stderr procesu Gunicorn oraz `yt-dlp`.
2. Przycisk **Uruchom ponownie** restartuje dodatek po zmianie opcji.
3. Karta **Konfiguracja** pokazuje opcje zapisane przez Supervisor.
4. Jeśli analiza przestaje działać po zmianach serwisu, sprawdź log startowy aktualizacji `yt-dlp`.

Build obrazu nie pobiera już pakietów z serwerów Alpine ani PyPI wewnątrz kroków `RUN`. Statyczne binaria `ffmpeg` i `ffprobe` są kopiowane z wieloarchitekturowego obrazu, a zależności Python instalowane z lokalnego katalogu `wheels/`. Jeśli Docker nadal zgłasza błąd DNS podczas pobierania obrazu bazowego, sprawdź połączenie sieciowe i DNS hosta Home Assistant.

Przy starcie aktualizowany jest `yt-dlp`, a nie YouTube. Jeśli aktualizacja się nie uda, dodatek uruchamia poprzednią wersję extractora.

## Bezpieczeństwo

Dodatek akceptuje wyłącznie adresy HTTP i HTTPS z obsługiwanych domen YouTube. Nie implementuje logowania, cookies, dostępu do filmów prywatnych, omijania DRM ani paywalli. Pliki trafiają wyłącznie do skonfigurowanego katalogu w `/share` lub `/media`.
