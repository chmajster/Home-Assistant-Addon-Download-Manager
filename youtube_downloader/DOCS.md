# Dokumentacja dziaĹ‚ania

## Analiza przez yt-dlp

Po przesĹ‚aniu URL aplikacja sprawdza schemat i domenÄ™, a nastÄ™pnie uruchamia `yt-dlp` w trybie pobierania samych metadanych. Extractor zwraca tytuĹ‚, kanaĹ‚, miniaturÄ™, czas trwania, status transmisji i dostÄ™pne formaty. Dla playlist aplikacja pokazuje elementy zwrĂłcone przez extractor.

Przy wĹ‚aĹ›ciwym pobieraniu aplikacja nie przyjmuje Ĺ›cieĹĽki docelowej od uĹĽytkownika. Wybiera szablon nazwy wewnÄ…trz skonfigurowanego katalogu trwaĹ‚ego i ogranicza nazwy plikĂłw do bezpiecznego zestawu znakĂłw obsĹ‚ugiwanego przez `yt-dlp`.

Podstawowy formularz udostÄ™pnia prosty wybĂłr jakoĹ›ci filmu: najlepsza dostÄ™pna, `1080p`, `720p` albo `360p`. Wybrana rozdzielczoĹ›Ä‡ jest limitem maksymalnym, wiÄ™c przy braku dokĹ‚adnego wariantu `yt-dlp` pobiera najlepszÄ… dostÄ™pnÄ… niĹĽszÄ… jakoĹ›Ä‡. Nadal moĹĽna pobraÄ‡ samo audio MP3 albo wskazaÄ‡ konkretny format z tabeli.

GĹ‚Ăłwne pole URL pozwala wkleiÄ‡ jeden link albo do 50 linkĂłw naraz, rozdzielonych nowymi liniami lub przecinkami. Jeden poprawny URL uruchamia standardowÄ… analizÄ™. Wiele poprawnych URL-i tworzy osobne zadania `najlepsza`. Aplikacja usuwa powtĂłrzenia z tej samej paczki, a jeĹ›li choÄ‡ jeden adres jest niepoprawny, pokazuje listÄ™ bĹ‚Ä™dĂłw i nie uruchamia ĹĽadnego zadania.

## Ingress i panel Home Assistant

W `config.yaml` aktywne sÄ…:

```yaml
ingress: true
ingress_port: 8099
panel_icon: mdi:download
panel_title: Media Web Downloader
```

Supervisor przekazuje ruch z panelu bocznego do wewnÄ™trznego portu `8099`. Aplikacja uwzglÄ™dnia nagĹ‚Ăłwek `X-Ingress-Path` przy generowaniu formularzy, linkĂłw do CSS i JavaScriptu, wywoĹ‚aĹ„ API oraz adresĂłw pobieranych plikĂłw. DziÄ™ki temu nie zakĹ‚ada uruchomienia pod Ĺ›cieĹĽkÄ… `/`.

JeĹĽeli `allow_external_port` ma wartoĹ›Ä‡ `true`, skrypt startowy uruchamia dodatkowy bind Gunicorna na porcie z opcji `external_port`, domyĹ›lnie `999`. Ten adres omija Ingress i nie wymaga logowania do Home Assistant. W `config.yaml` zadeklarowano port `999/tcp`, wiÄ™c domyĹ›lna konfiguracja moĹĽe byÄ‡ wystawiona jako `http://<adres-home-assistant>:999`. Zmiana portu wymaga zgodnego mapowania w sekcji **SieÄ‡** dodatku.

Standardowe przeĹ‚Ä…czniki `Start on boot`, `Watchdog`, `Auto update` oraz `Show in sidebar` sÄ… renderowane i tĹ‚umaczone przez frontend Home Assistant. Dodatek moĹĽe ustawiÄ‡ wartoĹ›ci wspierajÄ…ce te funkcje, takie jak `boot`, `watchdog`, `ingress`, `panel_title` i `panel_icon`, ale nie moĹĽe nadpisaÄ‡ tekstĂłw systemowego interfejsu. Polskie objaĹ›nienia znajdujÄ… siÄ™ w `README.md`.

## Zadania i historia

ZwykĹ‚e pobrania wykonujÄ… siÄ™ w workerach tĹ‚a. Liczba rĂłwnolegĹ‚ych zadaĹ„ jest ograniczona przez `max_concurrent_jobs`. Stan kolejki jest zapisywany w bazie SQLite `/data/jobs/state.sqlite3`. Po restarcie dodatku lista zostaje odtworzona, a zadania, ktĂłre byĹ‚y aktywne, otrzymujÄ… status `przerwane`. Dodatek nie uruchamia ich automatycznie ponownie.

Na stronie **Zadania** zwykĹ‚e pobieranie moĹĽna zatrzymaÄ‡ i wznowiÄ‡. Zatrzymanie zachowuje pliki czÄ™Ĺ›ciowe `yt-dlp`, a wznowienie uruchamia ten sam URL i wariant formatu z aktywnÄ… obsĹ‚ugÄ… kontynuacji pobierania. Przy zadaniu moĹĽna rozwinÄ…Ä‡ podglÄ…d ostatnich linii logu `yt-dlp`, jeĹ›li zadanie zdÄ…ĹĽyĹ‚o je zapisaÄ‡. Filtr **BĹ‚Ä™dy** pokazuje tylko nieudane zadania, a panel bĹ‚Ä™dĂłw podpowiada najczÄ™stsze przyczyny. BĹ‚Ä™dne zadania sÄ… automatycznie ponawiane do 3 razy z opĂłĹşnieniem 5 minut, a termin nastÄ™pnej prĂłby jest widoczny przy wpisie. Przy pojedynczym bĹ‚Ä™dnym zadaniu moĹĽna kliknÄ…Ä‡ **PonĂłw**, a przycisk **PonĂłw nieudane** uruchamia ponownie wszystkie zadania ze statusem `bĹ‚Ä…d`. Po analizie URL aplikacja ostrzega, jeĹ›li ten sam URL albo podobny tytuĹ‚/plik jest juĹĽ w historii lub aktywnej kolejce; ostrzeĹĽenie nie blokuje Ĺ›wiadomego ponownego pobrania.

Po zakoĹ„czeniu operacji wynik jest zapisywany w historii w SQLite:

```text
/data/jobs/state.sqlite3
```

Schemat bazy ma jawnie zapisaną wersję w `schema_meta`. Migracje uruchamiają się przy starcie aplikacji, dodając nowe kolumny, indeksy i tabele bez kasowania istniejącej historii. Najważniejsze pola historii i kolejki są trzymane także w osobnych kolumnach, a pełne logi zadań są zapisywane w tabeli `job_log_lines`; rekord zadania przechowuje tylko krótki podgląd ostatnich linii.

Historia przetrwa restart kontenera. Przy pierwszym uruchomieniu po aktualizacji stare pliki `/data/jobs/history.json` i `/data/jobs/queue.json` sÄ… importowane do bazy SQLite, a dalsze zapisy korzystajÄ… juĹĽ z bazy. Po skasowaniu materiaĹ‚u rekord pozostaje widoczny, ale panel oznacza brak pliku. Przycisk **Pobierz ponownie** uruchamia nowe zadanie z zapisanym URL i wariantem jakoĹ›ci rĂłwnieĹĽ wtedy, gdy lokalny plik zostaĹ‚ juĹĽ usuniÄ™ty.

Osobna strona `/history` pokazuje peĹ‚nÄ… historiÄ™ z wyszukiwarkÄ… po tytule, nazwie pliku, tagu, serwisie, URL, dacie, rozmiarze i dĹ‚ugoĹ›ci. Wyniki moĹĽna sortowaÄ‡ po dacie, rozmiarze, dĹ‚ugoĹ›ci, tytule i serwisie, rosnÄ…co albo malejÄ…co oraz przeĹ‚Ä…czaÄ‡ miÄ™dzy tabelÄ… i galeriÄ… miniaturek. Dla lokalnych plikĂłw audio/wideo moĹĽna rozwinÄ…Ä‡ mini odtwarzacz bez przechodzenia do osobnego podglÄ…du. Wpisy moĹĽna rÄ™cznie tagowaÄ‡, na przykĹ‚ad jako `muzyka`, `tutoriale`, `live` albo `archiwum`. Aplikacja dodaje teĹĽ automatyczne tagi, miÄ™dzy innymi `youtube`, `twitch`, `kick`, `audio`, `video`, `live` i `1080p`; klikniÄ™cie tagu od razu filtruje HistoriÄ™ po tej wartoĹ›ci. Zaznaczone wpisy moĹĽna masowo usunÄ…Ä‡ z historii, usunÄ…Ä‡ ich pliki albo uruchomiÄ‡ ponowne pobieranie. DĹ‚ugoĹ›Ä‡ jest zapisywana dla nowych pobraĹ„, jeĹ›li `yt-dlp` zwrĂłciĹ‚ jÄ… podczas analizy.

Po zakoĹ„czeniu pobierania albo bĹ‚Ä™dzie zadania dodatek wysyĹ‚a trwaĹ‚e powiadomienie Home Assistant przez usĹ‚ugÄ™ `persistent_notification.create`. TreĹ›Ä‡ zawiera tytuĹ‚ materiaĹ‚u, typ pobrania i nazwÄ™ pliku albo komunikat bĹ‚Ä™du. DostÄ™p do API Home Assistant Core jest deklarowany w `config.yaml` przez `homeassistant_api: true`.

## Zapis transmisji live

Aktywna transmisja live jest zapisywana przez osobny proces `yt-dlp`. MenedĹĽer zadaĹ„ przechowuje PID procesu, czyta jego postÄ™p i pozwala wysĹ‚aÄ‡ bezpieczny sygnaĹ‚ przerwania z interfejsu. Jednoczesny drugi zapis tego samego URL jest odrzucany. Mechanizm dziaĹ‚a dla publicznych transmisji zwracanych przez extractor jako aktywne live, w tym YouTube, Kick i Twitch.

Zaplanowana transmisja moĹĽe zostaÄ‡ przeanalizowana, a przycisk **Oczekuj na live** uruchamia zadanie, ktĂłre monitoruje start i rozpoczyna zapis automatycznie.

Formularze live majÄ… domyĹ›lnie zaznaczonÄ… opcjÄ™ **Pobieraj od poczÄ…tku**, ktĂłra przekazuje do `yt-dlp` argument `--live-from-start`. OpcjÄ™ moĹĽna odznaczyÄ‡, jeĹ›li zapis ma ruszyÄ‡ od bieĹĽÄ…cego momentu.

JeĹĽeli `yt-dlp` zwrĂłci status `was_live`, materiaĹ‚ jest traktowany jako zapis zakoĹ„czonej transmisji i moĹĽna pobraÄ‡ go zwykĹ‚ym formularzem filmu zamiast uruchamiaÄ‡ oczekiwanie na live.

BieĹĽÄ…cy `yt-dlp` nie ma osobnego extractora Instagram live. Dodatek obsĹ‚uguje publiczne posty, reels, stories, tagi i profile Instagram zwracane przez extractor, ale nie deklaruje zapisu Instagram live.

## Lokalizacja plikĂłw

DomyĹ›lny katalog:

```text
/share/youtube_downloader
```

Pliki sÄ… dostÄ™pne w udziale Home Assistant `/share`. MoĹĽna przenieĹ›Ä‡ je zwykĹ‚ym narzÄ™dziem obsĹ‚ugujÄ…cym udziaĹ‚ Samba, dodatkiem File editor, SSH lub innym rozwiÄ…zaniem administracyjnym uĹĽywanym w danej instalacji Home Assistant. Alternatywnie ustaw `download_dir` na katalog wewnÄ…trz `/media`, aby udostÄ™pniÄ‡ pliki w obszarze multimediĂłw.

## Magazyn NFS zarzÄ…dzany przez Home Assistant

NFS naleĹĽy dodaÄ‡ po stronie Home Assistant w **Ustawienia â†’ System â†’ PamiÄ™Ä‡ masowa â†’ Dodaj magazyn sieciowy**. Dla magazynu uĹĽywanego na pobrania wybierz typ **Media**. Po zapisaniu udziaĹ‚ jest dostÄ™pny dla dodatku jako `/media/<nazwa>`.

PrzykĹ‚adowa konfiguracja dodatku:

```yaml
storage_mode: nfs
nfs_server: 192.168.1.20
nfs_export_path: /volume1/media
nfs_username: ""
nfs_password: ""
nfs_mount_options: vers=4
nfs_download_dir: /media/nas/youtube_downloader
```

Po wyborze `nfs` karta **Konfiguracja** pokazuje dodatkowe pola na adres serwera, Ĺ›cieĹĽkÄ™/export, opcjonalny login, opcjonalne hasĹ‚o oraz opcje montowania. HasĹ‚o jest traktowane jako pole poufne i panel aplikacji pokazuje tylko informacjÄ™, czy zostaĹ‚o ustawione. Klasyczny NFS zwykle nie uĹĽywa loginu ani hasĹ‚a; te pola sÄ… dostÄ™pne dla instalacji, w ktĂłrych konfiguracja magazynu sieciowego ich wymaga.

Przy trybie `nfs` dodatek sprawdza przed uruchomieniem, czy gĹ‚Ăłwny katalog udziaĹ‚u, na przykĹ‚ad `/media/nas`, istnieje oraz czy katalog docelowy jest zapisywalny. Brak udziaĹ‚u zatrzymuje start dodatku z bĹ‚Ä™dem w logach. Zapobiega to niezauwaĹĽonemu zapisowi na lokalnym dysku, gdy NFS jest niedostÄ™pny.

Dodatek korzysta wyĹ‚Ä…cznie z magazynu zamontowanego przez Home Assistant. Nie montuje NFS wewnÄ…trz kontenera, nie wymaga `privileged: true` ani dodatkowych uprawnieĹ„ systemowych.

## Zmiana limitu zadaĹ„

Na karcie **Konfiguracja** dodatku ustaw `max_concurrent_jobs` na wartoĹ›Ä‡ od `1` do `5`, zapisz opcje i uruchom dodatek ponownie. WiÄ™kszy limit zwiÄ™ksza obciÄ…ĹĽenie CPU, pamiÄ™ci, sieci i miejsca docelowego.

## Aktualizacja extractora

Przy kaĹĽdym starcie skrypt usĹ‚ugi prĂłbuje wykonaÄ‡:

```sh
/venv/bin/python -m pip install --no-cache-dir --retries 3 --timeout 20 --upgrade yt-dlp
```

Niepowodzenie jest logowane, ale nie blokuje startu panelu. Aktualizowany jest extractor `yt-dlp`, nie serwisy ĹşrĂłdĹ‚owe.

Wynik aktualizacji jest zapisywany w `/data/jobs/ytdlp_update.json`. DziaĹ‚ajÄ…ca aplikacja sprawdza ten stan co godzinÄ™ i wykonuje aktualizacjÄ™, gdy ostatnia udana prĂłba ma co najmniej 24 godziny. To samo sprawdzenie jest wykonywane przed analizÄ…, zwykĹ‚ym pobraniem, wznowieniem pobrania oraz startem zapisu live. JeĹĽeli poprzednia prĂłba aktualizacji siÄ™ nie powiodĹ‚a, kolejne uruchomienie pobierania sprĂłbuje zaktualizowaÄ‡ `yt-dlp` ponownie.

## Komunikaty bĹ‚Ä™dĂłw

Panel rozpoznaje najczÄ™stsze problemy operacyjne i pokazuje prostÄ… wskazĂłwkÄ™ zamiast surowego komunikatu narzÄ™dzia:

- problem z internetem lub poĹ‚Ä…czeniem z serwisem ĹşrĂłdĹ‚owym,
- brak wolnego miejsca w katalogu pobraĹ„,
- bĹ‚Ä…d przetwarzania pliku przez `ffmpeg`.

JeĹĽeli `ffmpeg` nie wygeneruje samej miniatury, gotowy film pozostaje dostÄ™pny. Historia i widok zadaĹ„ pokazujÄ… wtedy ostrzeĹĽenie, a szczegĂłĹ‚y techniczne pozostajÄ… w logach dodatku.

Strona **Diagnostyka** (`/diagnostics`) pokazuje wersjÄ™ `yt-dlp`, datÄ™ ostatniej aktualizacji extractora, wersjÄ™ `ffmpeg`, wolne miejsce, katalog pobraĹ„, status poĹ‚Ä…czenia z Home Assistant API oraz ostatni bĹ‚Ä…d diagnostyczny.

