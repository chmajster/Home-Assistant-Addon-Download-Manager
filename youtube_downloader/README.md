# Media Web Downloader

Dodatek Home Assistant udostÄ™pnia przez Ingress panel do analizy i legalnego pobierania publicznych materiaĹ‚Ăłw przez `yt-dlp`. Interfejs obsĹ‚uguje YouTube, Instagram, Kick oraz Twitch zgodnie z moĹĽliwoĹ›ciami bieĹĽÄ…cych extractorĂłw.

ObsĹ‚ugiwane sÄ… miÄ™dzy innymi filmy, Shorts, playlisty, publiczne posty i reels Instagram oraz kanaĹ‚y live, VOD i klipy Kick oraz Twitch. W bieĹĽÄ…cej wersji `yt-dlp` zapis publicznego live dziaĹ‚a dla YouTube, Kick i Twitch. `yt-dlp` nie udostÄ™pnia osobnego extractora Instagram live, wiÄ™c dodatek nie obiecuje zapisu transmisji Instagram.

Obraz korzysta z oficjalnego wieloplatformowego `ghcr.io/home-assistant/base-python:3.14-alpine3.23` i wspiera aktualne architektury Home Assistant: `amd64` oraz `aarch64`. Platforma `armv7` nie jest juĹĽ wspierana przez Home Assistant.

## Konfiguracja

Opcje ustawia siÄ™ na karcie **Konfiguracja** dodatku w Home Assistant:

| Opcja | DomyĹ›lnie | Znaczenie |
| --- | --- | --- |
| `storage_mode` | `local` | `local` zapisuje lokalnie, a `nfs` uĹĽywa magazynu sieciowego zamontowanego przez Home Assistant |
| `download_dir` | `/share/youtube_downloader` | Docelowy katalog pobraĹ„ wewnÄ…trz `/share` albo `/media` |
| `nfs_download_dir` | `/media/youtube_downloader_nfs` | Katalog pobraĹ„ wewnÄ…trz udziaĹ‚u NFS dodanego w Home Assistant |
| `nfs_server` | pusty | Adres IP lub nazwa hosta serwera/NAS dla konfiguracji NFS |
| `nfs_export_path` | pusty | ĹšcieĹĽka/export udziaĹ‚u na serwerze NFS, np. `/volume1/media` |
| `nfs_username` | pusty | Opcjonalny login, jeĹ›li dana konfiguracja magazynu sieciowego go wymaga |
| `nfs_password` | pusty | Opcjonalne hasĹ‚o, zapisywane jako pole typu password w opcjach dodatku |
| `nfs_mount_options` | `vers=4` | Opcje montowania NFS uĹĽywane jako opis konfiguracji udziaĹ‚u |
| `max_concurrent_jobs` | `2` | Limit rĂłwnolegĹ‚ych pobraĹ„ i zapisĂłw live, od 1 do 5 |
| `allow_external_port` | `false` | WĹ‚Ä…cza dodatkowy dostÄ™p do panelu bez Ingress i bez logowania do Home Assistant |
| `external_port` | `999` | Port dodatkowego dostÄ™pu bez Ingress; domyĹ›lnie mapowany jako `999/tcp` |
| `debug` | `false` | Rozszerzone logowanie aplikacji |
| `preferred_format` | `best` | DomyĹ›lna jakoĹ›Ä‡: `best`, `video-1080`, `video-720`, `video-360` albo `audio` |

PrzykĹ‚ad:

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

Supervisor zapisuje opcje w `/data/options.json`. Aplikacja odczytuje ten plik przy uruchomieniu i stosuje bezpieczne wartoĹ›ci domyĹ›lne dla bĹ‚Ä™dnych danych. Po zmianie opcji uruchom dodatek ponownie.

## DostÄ™p bez Ingress

DomyĹ›lnie panel dziaĹ‚a przez Home Assistant Ingress i wymaga zalogowania do Home Assistant. JeĹĽeli chcesz wejĹ›Ä‡ na stronÄ™ bez logowania, ustaw:

```yaml
allow_external_port: true
external_port: 999
```

Dodatek uruchomi dodatkowy listener aplikacji na tym porcie. W konfiguracji dodatku zadeklarowany jest port `999/tcp`, wiÄ™c przy domyĹ›lnym ustawieniu moĹĽesz wejĹ›Ä‡ na stronÄ™ przez `http://<adres-home-assistant>:999`. JeĹ›li zmieniasz port, sprawdĹş teĹĽ kartÄ™ **SieÄ‡** dodatku i ustaw zgodne mapowanie portu.

Ten tryb nie dodaje osobnego logowania. KaĹĽdy, kto ma dostÄ™p do tego adresu i portu, moĹĽe korzystaÄ‡ z downloadera, dlatego uĹĽywaj go tylko w zaufanej sieci lokalnej.

## Magazyn NFS z Home Assistant

UdziaĹ‚ NFS dodaj najpierw w Home Assistant: **Ustawienia â†’ System â†’ PamiÄ™Ä‡ masowa â†’ Dodaj magazyn sieciowy**. Wybierz uĹĽycie **Media**, podaj nazwÄ™, serwer i Ĺ›cieĹĽkÄ™ udziaĹ‚u NFS. Home Assistant udostÄ™pni go dodatkom jako `/media/<nazwa>`.

NastÄ™pnie ustaw opcje dodatku, na przykĹ‚ad:

```yaml
storage_mode: nfs
nfs_server: 192.168.1.20
nfs_export_path: /volume1/media
nfs_username: ""
nfs_password: ""
nfs_mount_options: vers=4
nfs_download_dir: /media/nas/youtube_downloader
```

Pola `nfs_server`, `nfs_export_path`, `nfs_username`, `nfs_password` i `nfs_mount_options` pomagajÄ… opisaÄ‡ udziaĹ‚ w opcjach dodatku. Samo montowanie udziaĹ‚u nadal wykonuje Home Assistant, wiÄ™c `nfs_download_dir` musi wskazywaÄ‡ gotowy katalog widoczny w dodatku, najczÄ™Ĺ›ciej `/media/<nazwa>/youtube_downloader`. Klasyczny NFS zwykle nie uĹĽywa loginu ani hasĹ‚a; jeĹĽeli NAS ich wymaga, uzupeĹ‚nij pola zgodnie z konfiguracjÄ… magazynu sieciowego.

Dodatek nie montuje NFS samodzielnie i nie wymaga dodatkowych uprawnieĹ„. Przy starcie sprawdza, czy udziaĹ‚ istnieje i jest zapisywalny. JeĹ›li magazyn sieciowy jest odĹ‚Ä…czony, start zostanie przerwany z czytelnym komunikatem w logach, aby pliki nie trafiĹ‚y przypadkiem na lokalny dysk.

## PrzeĹ‚Ä…czniki na karcie Informacje

Home Assistant zarzÄ…dza czterema standardowymi przeĹ‚Ä…cznikami dodatku. Repozytorium aplikacji nie moĹĽe zmieniaÄ‡ ich etykiet, poniewaĹĽ pochodzÄ… z systemowego frontendu Home Assistant.

| Etykieta widoczna w Home Assistant | Polskie znaczenie | Zalecenie |
| --- | --- | --- |
| `Start on boot` | Uruchamiaj automatycznie przy starcie Home Assistant | WĹ‚Ä…cz |
| `Watchdog` | Automatycznie uruchom ponownie aplikacjÄ™ po awarii | WĹ‚Ä…cz |
| `Automatyczna aktualizacja` / `Auto update` | Automatycznie instaluj nowsze wersje dodatku | Opcjonalnie wĹ‚Ä…cz |
| `Show in sidebar` | PokaĹĽ skrĂłt do panelu Media Web Downloader w menu bocznym | WĹ‚Ä…cz |

JeĹĽeli Home Assistant pokazuje te etykiety po angielsku, sprawdĹş jÄ™zyk ustawiony w profilu uĹĽytkownika oraz zaktualizuj Home Assistant. WĹ‚asne opcje dodatku na karcie **Konfiguracja** majÄ… tĹ‚umaczenia polskie w `translations/pl.yaml`.

## Katalogi

- `/data` zawiera trwaĹ‚Ä… historiÄ™ i kolejkÄ™ w bazie SQLite `/data/jobs/state.sqlite3`.
- Baza SQLite ma wersjonowane migracje schematu, indeksowane kolumny historii i kolejki oraz osobną tabelę pełnych logów zadań.
- `/share` jest zalecanym miejscem na pliki dostÄ™pne dla uĹĽytkownika; domyĹ›lnie uĹĽywany jest `/share/youtube_downloader`.
- `/media` moĹĽe byÄ‡ alternatywnym katalogiem pobraĹ„.
- `/media/<nazwa>` zawiera magazyny sieciowe typu **Media** dodane w Home Assistant.
- `<katalog pobraĹ„>/.thumbnails` zawiera generowane przez `ffmpeg` podglÄ…dy JPG pobranych filmĂłw.

## Endpointy

| Metoda | ĹšcieĹĽka | Opis |
| --- | --- | --- |
| `GET` | `/` | Panel gĹ‚Ăłwny |
| `GET` | `/history` | PeĹ‚na historia pobraĹ„ z wyszukiwarkÄ…, sortowaniem, widokiem tabeli lub galerii, tagami, mini odtwarzaczem oraz masowymi akcjami |
| `POST` | `/history/bulk` | Masowe usuwanie wpisĂłw, usuwanie plikĂłw i ponowne pobieranie z Historii |
| `POST` | `/history/tags` | Zapis rÄ™cznych tagĂłw dla wpisu historii |
| `POST` | `/analyze` | Analiza pojedynczego URL albo import wielu URL-i do kolejki |
| `POST` | `/download` | Uruchomienie pobrania |
| `POST` | `/live/start` | Uruchomienie zapisu aktywnego live |
| `POST` | `/live/watch` | Oczekiwanie na start transmisji i automatyczny zapis |
| `POST` | `/live/stop/<job_id>` | Zatrzymanie zapisu live |
| `GET` | `/jobs` | Lista zadaĹ„ |
| `GET` | `/diagnostics` | Panel diagnostyczny z wersjami narzÄ™dzi, ostatniÄ… aktualizacjÄ…, wolnym miejscem, katalogiem pobraĹ„, statusem Home Assistant API i ostatnim bĹ‚Ä™dem |
| `POST` | `/jobs/retry/<job_id>` | Ponowienie jednego nieudanego zadania |
| `POST` | `/jobs/retry-failed` | Ponowienie wszystkich nieudanych zadaĹ„ |
| `GET` | `/api/jobs` | Lista zadaĹ„ JSON |
| `GET` | `/api/jobs/<job_id>` | Stan zadania JSON |
| `GET` | `/downloaded/<filename>` | Pobranie gotowego pliku |
| `GET` | `/thumbnails/<filename>` | PodglÄ…d wygenerowanej miniatury filmu |
| `POST` | `/delete/<filename>` | UsuniÄ™cie pliku |
| `GET` | `/health` | Healthcheck watchdoga |

## Podbijanie wersji

WersjÄ™ dodatku podbijaj skryptem, aby jednoczeĹ›nie zaktualizowaÄ‡ `config.yaml`, `Dockerfile` i `CHANGELOG.md`:

```sh
python scripts/bump_version.py 1.3.55 --change "Dodano opis zmiany."
```

JeĹ›li lokalny system nie udostÄ™pnia komendy `python`, uĹĽyj:

```sh
uv run python scripts/bump_version.py 1.3.55 --change "Dodano opis zmiany."
```

Parametr `--change` moĹĽna podaÄ‡ kilka razy, aby dopisaÄ‡ wiele punktĂłw changeloga.

## Diagnostyka

W Home Assistant otwĂłrz kartÄ™ dodatku:

1. Karta **Logi** pokazuje stdout i stderr procesu Gunicorn oraz `yt-dlp`.
2. Przycisk **Uruchom ponownie** restartuje dodatek po zmianie opcji.
3. Karta **Konfiguracja** pokazuje opcje zapisane przez Supervisor.
4. JeĹ›li analiza przestaje dziaĹ‚aÄ‡ po zmianach serwisu, sprawdĹş log startowy aktualizacji `yt-dlp`.

Panel pokazuje uproszczone komunikaty dla najczÄ™stszych problemĂłw: braku poĹ‚Ä…czenia z internetem lub serwisem ĹşrĂłdĹ‚owym, braku miejsca w katalogu pobraĹ„ oraz bĹ‚Ä™dĂłw `ffmpeg`. Nieudana miniatura nie blokuje gotowego filmu; w takim przypadku historia pokazuje ostrzeĹĽenie.

Build obrazu nie pobiera juĹĽ pakietĂłw z serwerĂłw Alpine ani PyPI wewnÄ…trz krokĂłw `RUN`. Statyczne binaria `ffmpeg` i `ffprobe` sÄ… kopiowane z wieloarchitekturowego obrazu, a zaleĹĽnoĹ›ci Python instalowane z lokalnego katalogu `wheels/`. JeĹ›li Docker nadal zgĹ‚asza bĹ‚Ä…d DNS podczas pobierania obrazu bazowego, sprawdĹş poĹ‚Ä…czenie sieciowe i DNS hosta Home Assistant.

Przy kaĹĽdym starcie aktualizowany jest `yt-dlp`, a nie serwisy ĹşrĂłdĹ‚owe. Aplikacja zapisuje stan aktualizacji w `/data/jobs/ytdlp_update.json`, ponawia sprawdzenie co 24 godziny oraz przed analizÄ… lub pobieraniem, jeĹ›li ostatnia udana aktualizacja jest za stara albo wczeĹ›niejsza prĂłba siÄ™ nie powiodĹ‚a. JeĹ›li aktualizacja siÄ™ nie uda, dodatek uruchamia poprzedniÄ… wersjÄ™ extractora i sprĂłbuje ponownie przy kolejnym sprawdzeniu.

Dodatek wysyĹ‚a trwaĹ‚e powiadomienia Home Assistant po zakoĹ„czeniu pobierania oraz po bĹ‚Ä™dzie zadania. UĹĽywa do tego `persistent_notification.create` przez API Home Assistant Core.

## BezpieczeĹ„stwo

Dodatek akceptuje wyĹ‚Ä…cznie adresy HTTP i HTTPS z jawnie obsĹ‚ugiwanych domen YouTube, Instagram, Kick i Twitch. Nie implementuje logowania, cookies, dostÄ™pu do prywatnych materiaĹ‚Ăłw, omijania DRM ani paywalli. Pliki trafiajÄ… wyĹ‚Ä…cznie do skonfigurowanego katalogu w `/share` lub `/media`.

