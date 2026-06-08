# Media Web Downloader

Repozytorium zawiera dodatek **Media Web Downloader** dla Home Assistant Supervisor. Dodatek uruchamia panel webowy oparty o Flask, Bootstrap 5 i `yt-dlp`. Służy do analizy oraz pobierania publicznych materiałów z YouTube, Instagram, Kick i Twitch wyłącznie wtedy, gdy użytkownik ma do nich prawa lub może je legalnie pobrać.

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
```

## Trwałe dane

Pobrane materiały trafiają domyślnie do:

```text
/share/youtube_downloader
```

Historia pobrań jest przechowywana w `/data/jobs/history.json`. Katalogi `/share` oraz `/data` zachowują dane po restarcie i aktualizacji kontenera dodatku.

## Magazyn NFS

Dodatek może zapisywać materiały na udziale NFS dodanym w Home Assistant. Skonfiguruj magazyn sieciowy typu **Media** w **Ustawienia → System → Pamięć masowa**, a następnie ustaw w opcjach dodatku:

```yaml
storage_mode: nfs
nfs_download_dir: /media/nas/youtube_downloader
```

`nas` zastąp nazwą magazynu podaną w Home Assistant. Dodatek sprawdza przy starcie obecność i możliwość zapisu na udziale. Nie montuje NFS samodzielnie i nie wymaga dodatkowych uprawnień kontenera.

## Aktualizacja yt-dlp

Przy każdym starcie kontenera dodatek próbuje zaktualizować `yt-dlp`, czyli backend i zestaw extractorów używanych do obsługi zmian po stronie serwisów. Nie są aktualizowane serwisy źródłowe. Chwilowy brak sieci nie blokuje uruchomienia dodatku.

## Ograniczenia

Dodatek nie omija DRM ani paywalli. Nie obsługuje cookies, logowania do kont, prywatnych materiałów ani mechanizmów obchodzenia zabezpieczeń. Użytkownik odpowiada za zgodność pobierania z prawem i warunkami korzystania z usług.

Szczegóły konfiguracji znajdują się w [README dodatku](youtube_downloader/README.md) oraz w [dokumentacji](youtube_downloader/DOCS.md).
