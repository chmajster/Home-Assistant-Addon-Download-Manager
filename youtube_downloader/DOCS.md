# Dokumentacja działania

## Analiza przez yt-dlp

Po przesłaniu URL aplikacja sprawdza schemat i domenę, a następnie uruchamia `yt-dlp` w trybie pobierania samych metadanych. Extractor zwraca tytuł, kanał, miniaturę, czas trwania, status transmisji i dostępne formaty. Dla playlist aplikacja pokazuje elementy zwrócone przez extractor.

Przy właściwym pobieraniu aplikacja nie przyjmuje ścieżki docelowej od użytkownika. Wybiera szablon nazwy wewnątrz skonfigurowanego katalogu trwałego i ogranicza nazwy plików do bezpiecznego zestawu znaków obsługiwanego przez `yt-dlp`.

Podstawowy formularz udostępnia prosty wybór jakości filmu: najlepsza dostępna, `1080p`, `720p` albo `360p`. Wybrana rozdzielczość jest limitem maksymalnym, więc przy braku dokładnego wariantu `yt-dlp` pobiera najlepszą dostępną niższą jakość. Nadal można pobrać samo audio MP3 albo wskazać konkretny format z tabeli.

Główne pole URL pozwala wkleić jeden link albo do 50 linków naraz, rozdzielonych nowymi liniami lub przecinkami. Jeden poprawny URL uruchamia standardową analizę. Wiele poprawnych URL-i tworzy osobne zadania `najlepsza`. Aplikacja usuwa powtórzenia z tej samej paczki, a jeśli choć jeden adres jest niepoprawny, pokazuje listę błędów i nie uruchamia żadnego zadania.

## Ingress i panel Home Assistant

W `config.yaml` aktywne są:

```yaml
ingress: true
ingress_port: 8099
panel_icon: mdi:download
panel_title: Media Web Downloader
```

Supervisor przekazuje ruch z panelu bocznego do wewnętrznego portu `8099`. Aplikacja uwzględnia nagłówek `X-Ingress-Path` przy generowaniu formularzy, linków do CSS i JavaScriptu, wywołań API oraz adresów pobieranych plików. Dzięki temu nie zakłada uruchomienia pod ścieżką `/`.

Jeżeli `allow_external_port` ma wartość `true`, skrypt startowy uruchamia dodatkowy bind Gunicorna na porcie z opcji `external_port`, domyślnie `999`. Ten adres omija Ingress i nie wymaga logowania do Home Assistant. W `config.yaml` zadeklarowano port `999/tcp`, więc domyślna konfiguracja może być wystawiona jako `http://<adres-home-assistant>:999`. Zmiana portu wymaga zgodnego mapowania w sekcji **Sieć** dodatku.

Standardowe przełączniki `Start on boot`, `Watchdog`, `Auto update` oraz `Show in sidebar` są renderowane i tłumaczone przez frontend Home Assistant. Dodatek może ustawić wartości wspierające te funkcje, takie jak `boot`, `watchdog`, `ingress`, `panel_title` i `panel_icon`, ale nie może nadpisać tekstów systemowego interfejsu. Polskie objaśnienia znajdują się w `README.md`.

## Zadania i historia

Zwykłe pobrania wykonują się w workerach tła. Liczba równoległych zadań jest ograniczona przez `max_concurrent_jobs`. Stan kolejki jest zapisywany w bazie SQLite `/data/jobs/state.sqlite3`. Po restarcie dodatku lista zostaje odtworzona, a zadania, które były aktywne, otrzymują status `przerwane`. Dodatek nie uruchamia ich automatycznie ponownie.

Na stronie **Zadania** zwykłe pobieranie można zatrzymać i wznowić. Zatrzymanie zachowuje pliki częściowe `yt-dlp`, a wznowienie uruchamia ten sam URL i wariant formatu z aktywną obsługą kontynuacji pobierania. Przy zadaniu można rozwinąć podgląd ostatnich linii logu `yt-dlp`, jeśli zadanie zdążyło je zapisać. Filtr **Błędy** pokazuje tylko nieudane zadania, a panel błędów podpowiada najczęstsze przyczyny. Błędne zadania są automatycznie ponawiane do 3 razy z opóźnieniem 5 minut, a termin następnej próby jest widoczny przy wpisie. Przy pojedynczym błędnym zadaniu można kliknąć **Ponów**, a przycisk **Ponów nieudane** uruchamia ponownie wszystkie zadania ze statusem `błąd`. Po analizie URL aplikacja ostrzega, jeśli ten sam URL albo podobny tytuł/plik jest już w historii lub aktywnej kolejce; ostrzeżenie nie blokuje świadomego ponownego pobrania.

Po zakończeniu operacji wynik jest zapisywany w historii w SQLite:

```text
/data/jobs/state.sqlite3
```

Schemat bazy ma jawnie zapisaną wersję w `schema_meta`. Migracje uruchamiają się przy starcie aplikacji, dodając nowe kolumny, indeksy i tabele bez kasowania istniejącej historii. Najważniejsze pola historii i kolejki są trzymane także w osobnych kolumnach, a pełne logi zadań są zapisywane w tabeli `job_log_lines`; rekord zadania przechowuje tylko krótki podgląd ostatnich linii.

Historia przetrwa restart kontenera. Przy pierwszym uruchomieniu po aktualizacji stare pliki `/data/jobs/history.json` i `/data/jobs/queue.json` są importowane do bazy SQLite, a dalsze zapisy korzystają już z bazy. Po skasowaniu materiału rekord pozostaje widoczny, ale panel oznacza brak pliku. Przycisk **Pobierz ponownie** uruchamia nowe zadanie z zapisanym URL i wariantem jakości również wtedy, gdy lokalny plik został już usunięty.

Osobna strona `/history` pokazuje pełną historię z wyszukiwarką po tytule, nazwie pliku, tagu, serwisie, URL, dacie, rozmiarze i długości. Wyniki można sortować po dacie, rozmiarze, długości, tytule i serwisie, rosnąco albo malejąco oraz przełączać między tabelą i galerią miniaturek. Dla lokalnych plików audio/wideo można rozwinąć mini odtwarzacz bez przechodzenia do osobnego podglądu. Wpisy można ręcznie tagować, na przykład jako `muzyka`, `tutoriale`, `live` albo `archiwum`. Aplikacja dodaje też automatyczne tagi, między innymi `youtube`, `twitch`, `kick`, `audio`, `video`, `live` i `1080p`; kliknięcie tagu od razu filtruje Historię po tej wartości. Zaznaczone wpisy można masowo usunąć z historii, usunąć ich pliki albo uruchomić ponowne pobieranie. Długość jest zapisywana dla nowych pobrań, jeśli `yt-dlp` zwrócił ją podczas analizy.

Po zakończeniu pobierania albo błędzie zadania dodatek wysyła trwałe powiadomienie Home Assistant przez usługę `persistent_notification.create`. Treść zawiera tytuł materiału, typ pobrania i nazwę pliku albo komunikat błędu. Dostęp do API Home Assistant Core jest deklarowany w `config.yaml` przez `homeassistant_api: true`.

## Zapis transmisji live

Aktywna transmisja live jest zapisywana przez osobny proces `yt-dlp`. Menedżer zadań przechowuje PID procesu, czyta jego postęp i pozwala wysłać bezpieczny sygnał przerwania z interfejsu. Jednoczesny drugi zapis tego samego URL jest odrzucany. Mechanizm działa dla publicznych transmisji zwracanych przez extractor jako aktywne live, w tym YouTube, Kick i Twitch.

Zaplanowana transmisja może zostać przeanalizowana, a przycisk **Oczekuj na live** uruchamia zadanie, które monitoruje start i rozpoczyna zapis automatycznie.

Formularze live mają domyślnie zaznaczoną opcję **Pobieraj od początku**, która przekazuje do `yt-dlp` argument `--live-from-start`. Opcję można odznaczyć, jeśli zapis ma ruszyć od bieżącego momentu.

Jeżeli `yt-dlp` zwróci status `was_live`, materiał jest traktowany jako zapis zakończonej transmisji i można pobrać go zwykłym formularzem filmu zamiast uruchamiać oczekiwanie na live.

Bieżący `yt-dlp` nie ma osobnego extractora Instagram live. Dodatek obsługuje publiczne posty, reels, stories, tagi i profile Instagram zwracane przez extractor, ale nie deklaruje zapisu Instagram live.

## Lokalizacja plików

Domyślny katalog:

```text
/share/youtube_downloader
```

Pliki są dostępne w udziale Home Assistant `/share`. Można przenieść je zwykłym narzędziem obsługującym udział Samba, dodatkiem File editor, SSH lub innym rozwiązaniem administracyjnym używanym w danej instalacji Home Assistant. Alternatywnie ustaw `download_dir` na katalog wewnątrz `/media`, aby udostępnić pliki w obszarze multimediów.

## Magazyn NFS zarządzany przez Home Assistant

NFS należy dodać po stronie Home Assistant w **Ustawienia → System → Pamięć masowa → Dodaj magazyn sieciowy**. Dla magazynu używanego na pobrania wybierz typ **Media**. Po zapisaniu udział jest dostępny dla dodatku jako `/media/<nazwa>`.

Przykładowa konfiguracja dodatku:

```yaml
storage_mode: nfs
nfs_server: 192.168.1.20
nfs_export_path: /volume1/media
nfs_username: ""
nfs_password: ""
nfs_mount_options: vers=4
nfs_download_dir: /media/nas/youtube_downloader
```

Po wyborze `nfs` karta **Konfiguracja** pokazuje dodatkowe pola na adres serwera, ścieżkę/export, opcjonalny login, opcjonalne hasło oraz opcje montowania. Hasło jest traktowane jako pole poufne i panel aplikacji pokazuje tylko informację, czy zostało ustawione. Klasyczny NFS zwykle nie używa loginu ani hasła; te pola są dostępne dla instalacji, w których konfiguracja magazynu sieciowego ich wymaga.

Przy trybie `nfs` dodatek sprawdza przed uruchomieniem, czy główny katalog udziału, na przykład `/media/nas`, istnieje oraz czy katalog docelowy jest zapisywalny. Brak udziału zatrzymuje start dodatku z błędem w logach. Zapobiega to niezauważonemu zapisowi na lokalnym dysku, gdy NFS jest niedostępny.

Dodatek korzysta wyłącznie z magazynu zamontowanego przez Home Assistant. Nie montuje NFS wewnątrz kontenera, nie wymaga `privileged: true` ani dodatkowych uprawnień systemowych.

## Zmiana limitu zadań

Na karcie **Konfiguracja** dodatku ustaw `max_concurrent_jobs` na wartość od `1` do `5`, zapisz opcje i uruchom dodatek ponownie. Większy limit zwiększa obciążenie CPU, pamięci, sieci i miejsca docelowego.

## Aktualizacja extractora

Przy każdym starcie skrypt usługi próbuje wykonać:

```sh
/venv/bin/python -m pip install --no-cache-dir --retries 3 --timeout 20 --upgrade yt-dlp
```

Niepowodzenie jest logowane, ale nie blokuje startu panelu. Aktualizowany jest extractor `yt-dlp`, nie serwisy źródłowe.

Wynik aktualizacji jest zapisywany w `/data/jobs/ytdlp_update.json`. Działająca aplikacja sprawdza ten stan co godzinę i wykonuje aktualizację, gdy ostatnia udana próba ma co najmniej 24 godziny. To samo sprawdzenie jest wykonywane przed analizą, zwykłym pobraniem, wznowieniem pobrania oraz startem zapisu live. Jeżeli poprzednia próba aktualizacji się nie powiodła, kolejne uruchomienie pobierania spróbuje zaktualizować `yt-dlp` ponownie.

## Komunikaty błędów

Panel rozpoznaje najczęstsze problemy operacyjne i pokazuje prostą wskazówkę zamiast surowego komunikatu narzędzia:

- problem z internetem lub połączeniem z serwisem źródłowym,
- brak wolnego miejsca w katalogu pobrań,
- błąd przetwarzania pliku przez `ffmpeg`.

Jeżeli `ffmpeg` nie wygeneruje samej miniatury, gotowy film pozostaje dostępny. Historia i widok zadań pokazują wtedy ostrzeżenie, a szczegóły techniczne pozostają w logach dodatku.

Strona **Diagnostyka** (`/diagnostics`) pokazuje wersję `yt-dlp`, datę ostatniej aktualizacji extractora, wersję `ffmpeg`, wolne miejsce, katalog pobrań, status połączenia z Home Assistant API oraz ostatni błąd diagnostyczny.

