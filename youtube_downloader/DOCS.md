# Dokumentacja działania

## Analiza przez yt-dlp

Po przesłaniu URL aplikacja sprawdza schemat i domenę, a następnie uruchamia `yt-dlp` w trybie pobierania samych metadanych. Extractor zwraca tytuł, kanał, miniaturę, czas trwania, status transmisji i dostępne formaty. Dla playlist aplikacja pokazuje elementy zwrócone przez extractor.

Przy właściwym pobieraniu aplikacja nie przyjmuje ścieżki docelowej od użytkownika. Wybiera szablon nazwy wewnątrz skonfigurowanego katalogu trwałego i ogranicza nazwy plików do bezpiecznego zestawu znaków obsługiwanego przez `yt-dlp`.

Podstawowy formularz udostępnia prosty wybór jakości filmu: najlepsza dostępna, `1080p`, `720p` albo `360p`. Wybrana rozdzielczość jest limitem maksymalnym, więc przy braku dokładnego wariantu `yt-dlp` pobiera najlepszą dostępną niższą jakość. Nadal można pobrać samo audio MP3 albo wskazać konkretny format z tabeli.

## Ingress i panel Home Assistant

W `config.yaml` aktywne są:

```yaml
ingress: true
ingress_port: 8099
panel_icon: mdi:download
panel_title: Media Web Downloader
```

Supervisor przekazuje ruch z panelu bocznego do wewnętrznego portu `8099`. Aplikacja uwzględnia nagłówek `X-Ingress-Path` przy generowaniu formularzy, linków do CSS i JavaScriptu, wywołań API oraz adresów pobieranych plików. Dzięki temu nie zakłada uruchomienia pod ścieżką `/`.

Standardowe przełączniki `Start on boot`, `Watchdog`, `Auto update` oraz `Show in sidebar` są renderowane i tłumaczone przez frontend Home Assistant. Dodatek może ustawić wartości wspierające te funkcje, takie jak `boot`, `watchdog`, `ingress`, `panel_title` i `panel_icon`, ale nie może nadpisać tekstów systemowego interfejsu. Polskie objaśnienia znajdują się w `README.md`.

## Zadania i historia

Zwykłe pobrania wykonują się w workerach tła. Liczba równoległych zadań jest ograniczona przez `max_concurrent_jobs`. Stan kolejki jest zapisywany w `/data/jobs/queue.json`. Po restarcie dodatku lista zostaje odtworzona, a zadania, które były aktywne, otrzymują status `przerwane`. Dodatek nie uruchamia ich automatycznie ponownie.

Na stronie **Zadania** zwykłe pobieranie można zatrzymać i wznowić. Zatrzymanie zachowuje pliki częściowe `yt-dlp`, a wznowienie uruchamia ten sam URL i wariant formatu z aktywną obsługą kontynuacji pobierania.

Po zakończeniu operacji wynik jest zapisywany w historii JSON:

```text
/data/jobs/history.json
```

Historia przetrwa restart kontenera. Po skasowaniu materiału rekord pozostaje widoczny, ale panel oznacza brak pliku. Przycisk **Pobierz ponownie** uruchamia nowe zadanie z zapisanym URL i wariantem jakości również wtedy, gdy lokalny plik został już usunięty.

## Zapis transmisji live

Aktywna transmisja live jest zapisywana przez osobny proces `yt-dlp`. Menedżer zadań przechowuje PID procesu, czyta jego postęp i pozwala wysłać bezpieczny sygnał przerwania z interfejsu. Jednoczesny drugi zapis tego samego URL jest odrzucany. Mechanizm działa dla publicznych transmisji zwracanych przez extractor jako aktywne live, w tym YouTube i Kick.

Zaplanowana transmisja może zostać przeanalizowana, ale przycisk nagrywania pozostaje niedostępny do chwili rozpoczęcia transmisji.

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
nfs_download_dir: /media/nas/youtube_downloader
```

Przy trybie `nfs` dodatek sprawdza przed uruchomieniem, czy główny katalog udziału, na przykład `/media/nas`, istnieje oraz czy katalog docelowy jest zapisywalny. Brak udziału zatrzymuje start dodatku z błędem w logach. Zapobiega to niezauważonemu zapisowi na lokalnym dysku, gdy NFS jest niedostępny.

Dodatek korzysta wyłącznie z magazynu zamontowanego przez Home Assistant. Nie montuje NFS wewnątrz kontenera, nie wymaga `privileged: true` ani dodatkowych uprawnień systemowych.

## Zmiana limitu zadań

Na karcie **Konfiguracja** dodatku ustaw `max_concurrent_jobs` na wartość od `1` do `5`, zapisz opcje i uruchom dodatek ponownie. Większy limit zwiększa obciążenie CPU, pamięci, sieci i miejsca docelowego.

## Aktualizacja extractora

Gdy `update_ytdlp_on_start` ma wartość `true`, skrypt usługi próbuje wykonać:

```sh
/venv/bin/python -m pip install --no-cache-dir --upgrade yt-dlp
```

Niepowodzenie jest logowane, ale nie blokuje startu panelu. Aktualizowany jest extractor `yt-dlp`, nie serwisy źródłowe.
