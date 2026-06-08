# Media Web Downloader

Dodatek Home Assistant udostępnia przez Ingress panel do analizy i legalnego pobierania publicznych materiałów przez `yt-dlp`. Interfejs obsługuje YouTube, Instagram, Kick oraz Twitch zgodnie z możliwościami bieżących extractorów.

Obsługiwane są między innymi filmy, Shorts, playlisty, publiczne posty i reels Instagram oraz kanały live, VOD i klipy Kick oraz Twitch. W bieżącej wersji `yt-dlp` zapis publicznego live działa dla YouTube, Kick i Twitch. `yt-dlp` nie udostępnia osobnego extractora Instagram live, więc dodatek nie obiecuje zapisu transmisji Instagram.

Obraz korzysta z oficjalnego wieloplatformowego `ghcr.io/home-assistant/base-python:3.14-alpine3.23` i wspiera aktualne architektury Home Assistant: `amd64` oraz `aarch64`. Platforma `armv7` nie jest już wspierana przez Home Assistant.

## Konfiguracja

Opcje ustawia się na karcie **Konfiguracja** dodatku w Home Assistant:

| Opcja | Domyślnie | Znaczenie |
| --- | --- | --- |
| `storage_mode` | `local` | `local` zapisuje lokalnie, a `nfs` używa magazynu sieciowego zamontowanego przez Home Assistant |
| `download_dir` | `/share/youtube_downloader` | Docelowy katalog pobrań wewnątrz `/share` albo `/media` |
| `nfs_download_dir` | `/media/youtube_downloader_nfs` | Katalog pobrań wewnątrz udziału NFS dodanego w Home Assistant |
| `nfs_server` | pusty | Adres IP lub nazwa hosta serwera/NAS dla konfiguracji NFS |
| `nfs_export_path` | pusty | Ścieżka/export udziału na serwerze NFS, np. `/volume1/media` |
| `nfs_username` | pusty | Opcjonalny login, jeśli dana konfiguracja magazynu sieciowego go wymaga |
| `nfs_password` | pusty | Opcjonalne hasło, zapisywane jako pole typu password w opcjach dodatku |
| `nfs_mount_options` | `vers=4` | Opcje montowania NFS używane jako opis konfiguracji udziału |
| `max_concurrent_jobs` | `2` | Limit równoległych pobrań i zapisów live, od 1 do 5 |
| `allow_external_port` | `false` | Włącza dodatkowy dostęp do panelu bez Ingress i bez logowania do Home Assistant |
| `external_port` | `999` | Port dodatkowego dostępu bez Ingress; domyślnie mapowany jako `999/tcp` |
| `debug` | `false` | Rozszerzone logowanie aplikacji |
| `preferred_format` | `best` | Domyślna jakość: `best`, `video-1080`, `video-720`, `video-360` albo `audio` |

Przykład:

```yaml
storage_mode: local
download_dir: /share/youtube_downloader
nfs_download_dir: /media/youtube_downloader_nfs
nfs_server: ""
nfs_export_path: ""
nfs_username: ""
nfs_password: ""
nfs_mount_options: vers=4
max_concurrent_jobs: 2
allow_external_port: false
external_port: 999
debug: false
preferred_format: best
```

Supervisor zapisuje opcje w `/data/options.json`. Aplikacja odczytuje ten plik przy uruchomieniu i stosuje bezpieczne wartości domyślne dla błędnych danych. Po zmianie opcji uruchom dodatek ponownie.

## Dostęp bez Ingress

Domyślnie panel działa przez Home Assistant Ingress i wymaga zalogowania do Home Assistant. Jeżeli chcesz wejść na stronę bez logowania, ustaw:

```yaml
allow_external_port: true
external_port: 999
```

Dodatek uruchomi dodatkowy listener aplikacji na tym porcie. W konfiguracji dodatku zadeklarowany jest port `999/tcp`, więc przy domyślnym ustawieniu możesz wejść na stronę przez `http://<adres-home-assistant>:999`. Jeśli zmieniasz port, sprawdź też kartę **Sieć** dodatku i ustaw zgodne mapowanie portu.

Ten tryb nie dodaje osobnego logowania. Każdy, kto ma dostęp do tego adresu i portu, może korzystać z downloadera, dlatego używaj go tylko w zaufanej sieci lokalnej.

## Magazyn NFS z Home Assistant

Udział NFS dodaj najpierw w Home Assistant: **Ustawienia → System → Pamięć masowa → Dodaj magazyn sieciowy**. Wybierz użycie **Media**, podaj nazwę, serwer i ścieżkę udziału NFS. Home Assistant udostępni go dodatkom jako `/media/<nazwa>`.

Następnie ustaw opcje dodatku, na przykład:

```yaml
storage_mode: nfs
nfs_server: 192.168.1.20
nfs_export_path: /volume1/media
nfs_username: ""
nfs_password: ""
nfs_mount_options: vers=4
nfs_download_dir: /media/nas/youtube_downloader
```

Pola `nfs_server`, `nfs_export_path`, `nfs_username`, `nfs_password` i `nfs_mount_options` pomagają opisać udział w opcjach dodatku. Samo montowanie udziału nadal wykonuje Home Assistant, więc `nfs_download_dir` musi wskazywać gotowy katalog widoczny w dodatku, najczęściej `/media/<nazwa>/youtube_downloader`. Klasyczny NFS zwykle nie używa loginu ani hasła; jeżeli NAS ich wymaga, uzupełnij pola zgodnie z konfiguracją magazynu sieciowego.

Dodatek nie montuje NFS samodzielnie i nie wymaga dodatkowych uprawnień. Przy starcie sprawdza, czy udział istnieje i jest zapisywalny. Jeśli magazyn sieciowy jest odłączony, start zostanie przerwany z czytelnym komunikatem w logach, aby pliki nie trafiły przypadkiem na lokalny dysk.

## Przełączniki na karcie Informacje

Home Assistant zarządza czterema standardowymi przełącznikami dodatku. Repozytorium aplikacji nie może zmieniać ich etykiet, ponieważ pochodzą z systemowego frontendu Home Assistant.

| Etykieta widoczna w Home Assistant | Polskie znaczenie | Zalecenie |
| --- | --- | --- |
| `Start on boot` | Uruchamiaj automatycznie przy starcie Home Assistant | Włącz |
| `Watchdog` | Automatycznie uruchom ponownie aplikację po awarii | Włącz |
| `Automatyczna aktualizacja` / `Auto update` | Automatycznie instaluj nowsze wersje dodatku | Opcjonalnie włącz |
| `Show in sidebar` | Pokaż skrót do panelu Media Web Downloader w menu bocznym | Włącz |

Jeżeli Home Assistant pokazuje te etykiety po angielsku, sprawdź język ustawiony w profilu użytkownika oraz zaktualizuj Home Assistant. Własne opcje dodatku na karcie **Konfiguracja** mają tłumaczenia polskie w `translations/pl.yaml`.

## Katalogi

- `/data` zawiera trwałą historię w `/data/jobs/history.json`.
- `/share` jest zalecanym miejscem na pliki dostępne dla użytkownika; domyślnie używany jest `/share/youtube_downloader`.
- `/media` może być alternatywnym katalogiem pobrań.
- `/media/<nazwa>` zawiera magazyny sieciowe typu **Media** dodane w Home Assistant.
- `<katalog pobrań>/.thumbnails` zawiera generowane przez `ffmpeg` podglądy JPG pobranych filmów.

## Endpointy

| Metoda | Ścieżka | Opis |
| --- | --- | --- |
| `GET` | `/` | Panel główny |
| `POST` | `/analyze` | Analiza URL bez pobierania |
| `POST` | `/download` | Uruchomienie pobrania |
| `POST` | `/live/start` | Uruchomienie zapisu aktywnego live |
| `POST` | `/live/watch` | Oczekiwanie na start transmisji i automatyczny zapis |
| `POST` | `/live/stop/<job_id>` | Zatrzymanie zapisu live |
| `GET` | `/jobs` | Lista zadań |
| `GET` | `/api/jobs` | Lista zadań JSON |
| `GET` | `/api/jobs/<job_id>` | Stan zadania JSON |
| `GET` | `/downloaded/<filename>` | Pobranie gotowego pliku |
| `GET` | `/thumbnails/<filename>` | Podgląd wygenerowanej miniatury filmu |
| `POST` | `/delete/<filename>` | Usunięcie pliku |
| `GET` | `/health` | Healthcheck watchdoga |

## Diagnostyka

W Home Assistant otwórz kartę dodatku:

1. Karta **Logi** pokazuje stdout i stderr procesu Gunicorn oraz `yt-dlp`.
2. Przycisk **Uruchom ponownie** restartuje dodatek po zmianie opcji.
3. Karta **Konfiguracja** pokazuje opcje zapisane przez Supervisor.
4. Jeśli analiza przestaje działać po zmianach serwisu, sprawdź log startowy aktualizacji `yt-dlp`.

Panel pokazuje uproszczone komunikaty dla najczęstszych problemów: braku połączenia z internetem lub serwisem źródłowym, braku miejsca w katalogu pobrań oraz błędów `ffmpeg`. Nieudana miniatura nie blokuje gotowego filmu; w takim przypadku historia pokazuje ostrzeżenie.

Build obrazu nie pobiera już pakietów z serwerów Alpine ani PyPI wewnątrz kroków `RUN`. Statyczne binaria `ffmpeg` i `ffprobe` są kopiowane z wieloarchitekturowego obrazu, a zależności Python instalowane z lokalnego katalogu `wheels/`. Jeśli Docker nadal zgłasza błąd DNS podczas pobierania obrazu bazowego, sprawdź połączenie sieciowe i DNS hosta Home Assistant.

Przy każdym starcie aktualizowany jest `yt-dlp`, a nie serwisy źródłowe. Jeśli aktualizacja się nie uda, dodatek uruchamia poprzednią wersję extractora.

## Bezpieczeństwo

Dodatek akceptuje wyłącznie adresy HTTP i HTTPS z jawnie obsługiwanych domen YouTube, Instagram, Kick i Twitch. Nie implementuje logowania, cookies, dostępu do prywatnych materiałów, omijania DRM ani paywalli. Pliki trafiają wyłącznie do skonfigurowanego katalogu w `/share` lub `/media`.
