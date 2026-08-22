# Media Web Downloader

Repozytorium zawiera dodatek **Media Web Downloader** dla Home Assistant Supervisor. Dodatek uruchamia panel webowy oparty o Flask, Bootstrap 5 i `yt-dlp`. Służy do analizy oraz pobierania publicznych materiałów z serwisów obsługiwanych przez extractory `yt-dlp` i bezpiecznie rozwiązywanych publicznych stron z osadzonym HLS/DASH, wyłącznie wtedy, gdy użytkownik ma do nich prawa lub może je legalnie pobrać.

Dodatek jest budowany dla oficjalnie wspieranych obecnie architektur Home Assistant: `amd64` oraz `aarch64`. Home Assistant wycofał wsparcie systemów 32-bitowych, w tym `armv7`.

## Dodanie repozytorium

1. Otwórz Home Assistant.
2. Przejdź do: **Ustawienia → Dodatki → Sklep z dodatkami → trzy kropki → Repozytoria**.
3. Dodaj adres tego repozytorium GitHub.
4. W sklepie znajdź **Media Web Downloader** i wybierz **Zainstaluj**.
5. Po instalacji uruchom dodatek i włącz widoczność w panelu bocznym, jeśli Home Assistant jej automatycznie nie aktywował.

Przed publikacją własnego forka zmień placeholder URL w `repository.yaml` oraz `youtube_downloader/config.yaml`.

## Przełączniki Home Assistant

Na karcie **Informacje** dodatku Home Assistant może wyświetlać systemowe etykiety po angielsku. Ich polskie znaczenie:

| Etykieta Home Assistant | Znaczenie po polsku | Zalecenie |
| --- | --- | --- |
| `Start on boot` | Uruchamiaj automatycznie przy starcie Home Assistant | Włącz |
| `Watchdog` | Automatycznie uruchom ponownie aplikację po awarii | Włącz |
| `Automatyczna aktualizacja` / `Auto update` | Aktualizuj dodatek automatycznie, gdy pojawi się nowa wersja | Opcjonalnie włącz |
| `Show in sidebar` | Pokaż skrót do panelu aplikacji w menu bocznym | Włącz |

Etykiety tych przełączników są dostarczane przez frontend Home Assistant, a nie przez repozytorium dodatku. Ich język zależy od ustawień języka profilu użytkownika i wersji Home Assistant.

## Panel i Ingress

Dodatek korzysta z natywnego Home Assistant Ingress. Panel **Media Web Downloader** z ikoną `mdi:download` jest dostępny w lewym menu Home Assistant i otwiera pełny interfejs aplikacji: analizę URL, formaty, pobieranie, historię, aktywne zadania oraz zapis transmisji live.

Port `8099/tcp` jest domyślnie niewystawiony na hosta. W typowej instalacji wystarcza bezpieczny dostęp przez Ingress.

## Dostęp bez Ingress

Opcja `allow_external_port` uruchamia dodatkowy listener, domyślnie na porcie `999`. Od wersji `1.3.101` ten listener działa w trybie fail-closed i wymaga `external_access_token` o długości co najmniej 20 znaków. Port zewnętrzny musi różnić się od portu Ingress `8099`.

Przeglądarka przekierowuje niezalogowanego użytkownika do prostego formularza tokenu. Klienci API mogą przesłać token jako `Authorization: Bearer <token>` albo nagłówek `X-API-Key`. Endpointy healthcheck pozostają dostępne bez uwierzytelniania dla watchdoga i systemów monitoringu.

## Kolejka i diagnostyka runtime

Nowe zwykłe pobrania można tymczasowo wstrzymać bez przerywania aktywnych transferów i nagrań live przez `POST /api/queue/pause`; `POST /api/queue/resume` ponownie dopuszcza start oczekujących workerów. `GET /api/runtime` pokazuje stan bramki kolejki oraz etap wykonywania zadań, retry, prędkość, ETA i PID aktywnych procesów live.

Opcja `resume_interrupted_downloads_on_startup` automatycznie wznawia po restarcie zwykłe zadania ze statusem `interrupted`. Nagrania live nie są automatycznie uruchamiane ponownie.

## Audio i playlisty

Panel obsługuje pobieranie samego audio w formatach `mp3`, `m4a` i `opus`. Dla plików audio można osadzić miniaturę jako okładkę oraz zapisać metadane z `yt-dlp`: tytuł, autora/kanał, datę publikacji i URL źródłowy.

Po analizie playlisty można wybrać zakres pozycji, ustawić limit elementów, pominąć już pobrane materiały po ID oraz uruchomić tryb **Pobierz tylko nowe**. Elementy playlisty mogą być zapisywane w osobnym podfolderze wewnątrz katalogu pobrań.

## Przykładowe adresy

```text
https://www.youtube.com/watch?v=VIDEO_ID
https://youtu.be/VIDEO_ID
https://www.youtube.com/shorts/VIDEO_ID
https://www.youtube.com/playlist?list=PLAYLIST_ID
https://www.youtube.com/live/VIDEO_ID
https://www.instagram.com/reel/POST_ID/
https://www.instagram.com/p/POST_ID/
https://kick.com/CHANNEL
https://kick.com/CHANNEL/videos/VOD_ID
https://vimeo.com/VIDEO_ID
https://soundcloud.com/ARTIST/TRACK
https://public.example/camera/embed.html
```

## Trwałe dane

Pobrane materiały trafiają domyślnie do:

```text
/share/youtube_downloader
```

Stan zadań, w tym historia pobrań i kolejka, jest przechowywany w bazie SQLite `/data/jobs/state.sqlite3`. Katalogi `/share` oraz `/data` zachowują dane po restarcie i aktualizacji kontenera dodatku.

## Magazyn NFS

Dodatek może zapisywać materiały na udziale NFS dodanym w Home Assistant. Skonfiguruj magazyn sieciowy typu **Media** w **Ustawienia → System → Pamięć masowa**, a następnie ustaw w opcjach dodatku:

```yaml
storage_mode: nfs
nfs_download_dir: /media/nas/youtube_downloader
```

`nas` zastąp nazwą magazynu podaną w Home Assistant. Dodatek sprawdza przy starcie obecność i możliwość zapisu na udziale. Nie montuje NFS samodzielnie i nie wymaga dodatkowych uprawnień kontenera.

## Aktualizacja yt-dlp

Obraz dodatku zawiera przypiętą, testowalną wersję bazową `yt-dlp` z lokalnego wheelhouse. W trybie `startup` kontener przed uruchomieniem aplikacji próbuje zaktualizować `yt-dlp`, weryfikuje extractory i w razie nieudanej weryfikacji przywraca poprzednią wersję. Stan aktualizacji jest zapisywany w `/data/jobs/ytdlp_update.json`. Chwilowy brak sieci nie blokuje uruchomienia dodatku.

## Powiadomienia Home Assistant

Dodatek wysyła trwałe powiadomienie Home Assistant po zakończeniu pobierania oraz po błędzie zadania. Powiadomienia używają usługi `persistent_notification.create` przez API Home Assistant Core udostępnione dodatkom.

## Ograniczenia

Dodatek nie omija DRM ani paywalli. Nie obsługuje cookies, logowania do kont, prywatnych materiałów ani mechanizmów obchodzenia zabezpieczeń. Użytkownik odpowiada za zgodność pobierania z prawem i warunkami korzystania z usług.

Szczegóły konfiguracji znajdują się w [README dodatku](youtube_downloader/README.md) oraz w [dokumentacji](youtube_downloader/DOCS.md).
