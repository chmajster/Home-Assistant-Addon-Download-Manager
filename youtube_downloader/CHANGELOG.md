# Changelog

## 1.3.59

- Dodano jawne migracje schematu SQLite do wersji 2.
- Znormalizowano kluczowe pola historii i kolejki w osobnych kolumnach z indeksami.
- Przeniesiono pełne logi zadań do osobnej tabeli, zostawiając w zadaniu krótki podgląd.

## 1.3.58

- Przeniesiono historię i kolejkę z plików JSON do bazy SQLite z migracją istniejących danych.

## 1.3.57

- Poprawiono panel diagnostyczny: pokazuje kluczowe informacje techniczne w kartach i tabeli statusów OK, ostrzeżenie lub błąd.

## 1.3.56

- Dodano tagi w widoku `Podgląd`, z linkami do filtrowanej historii.
- Zmieniono `Panel diagnostyczny` na poziomy panel sekcji.
- Dodano linkowanie tytułu i miniatury zadań do podglądu.
- Naprawiono widok `Pełny log`, aby pokazywał log od początku zadania.
- Ustawiono `Najlepsza jakość` jako domyślny profil pobierania.

## 1.3.55

- Dodano skrypt do automatycznego podbijania wersji w config.yaml, Dockerfile i CHANGELOG.md.

## 1.3.54

- Dodano panel diagnostyczny z wersją `yt-dlp`, stanem aktualizacji, wersją `ffmpeg`, miejscem na dysku, ścieżkami i statusem Home Assistant API.

## 1.3.53

- Dodano profile pobierania: `Audio MP3`, `1080p`, `Archiwum live` i `Tylko Twitch`.
- Po analizie playlisty można zaznaczyć konkretne elementy i uruchomić je jako osobne zadania.
- Ujednolicono przyciski akcji w historii dla tabeli, widoku mobilnego i galerii.

## 1.3.52

- Poprawiono przewijanie podglądu logu zadań, aby ukryty widok mobilny/desktopowy nie resetował pozycji do góry.
- Dodano przycisk `Pełny log`, który otwiera cały log zadania na osobnej stronie.

## 1.3.51

- Naprawiono odświeżanie podstron: po F5 na `Historia` aplikacja przywraca ostatnią wewnętrzną ścieżkę zamiast zostawać na stronie głównej.

## 1.3.50

- Naprawiono przewijanie podglądu logu zadań: automatyczne odświeżanie kolejki nie resetuje już pozycji logu do góry.

## 1.3.49

- Usunięto kolumny `Serwis` i `Plik` z tabeli pełnej historii pobrań.
- Naprawiono zwijanie logu zadań: otwarty podgląd logu pozostaje otwarty po automatycznym odświeżeniu kolejki.

## 1.3.48

- Scalono pojedynczą analizę URL i import listy URL w jedno główne pole z przyciskiem `Analizuj`.
- Pole obsługuje wiele linków rozdzielonych nowymi liniami lub przecinkami, usuwa duplikaty i blokuje start zadań, jeśli którykolwiek URL jest niepoprawny.

## 1.3.47

- Dodano przełącznik motywu jasny/ciemny w navbarze z ikoną słońca/księżyca.
- Wybrany motyw jest zapisywany w przeglądarce i ustawiany przed załadowaniem widoku.

## 1.3.46

- W `Wyniku analizy` dodano klikalny link `Źródło` z analizowanym adresem URL.

## 1.3.45

- Zakończone transmisje ze statusem `was_live` są traktowane jak zapisane filmy i można je pobrać zwykłym formularzem.
- W wyniku analizy dodano informację, że `was_live` to zapis zakończonego live, a nie aktywna transmisja do oczekiwania.

## 1.3.44

- Dodano `Import listy URL` na stronie głównej: wklejenie wielu linków tworzy osobne zadania pobierania.
- Import usuwa powtórzenia z jednej paczki i pomija niepoprawne lub nieobsługiwane adresy.

## 1.3.43

- Usunięto kolumnę `Plik` z krótkiej tabeli `Historia pobrań` na stronie głównej.
- Dodano pojedynczy przycisk `Usuń plik` w pełnej historii, także w widoku galerii i na telefonie.

## 1.3.42

- Dodano w widoku `Podgląd` przycisk `Usuń nagranie`, który usuwa aktualnie oglądany plik i aktualizuje historię.

## 1.3.41

- Dodano domyślnie zaznaczoną opcję `Pobieraj od początku` dla zapisu live i oczekiwania na live.
- Włączona opcja przekazuje do `yt-dlp` argument `--live-from-start`; ustawienie jest zapisywane w zadaniu live.

## 1.3.40

- Dodano automatyczne ponawianie błędnych zadań: do 3 prób z opóźnieniem 5 minut.
- Harmonogram automatycznego ponowienia jest zapisywany w trwałej kolejce i odtwarzany po restarcie.

## 1.3.39

- Dodano ostrzeżenia o możliwych duplikatach po analizie URL, gdy ten sam URL albo podobny tytuł/plik jest już w historii lub kolejce.
- Bezpośredni start pobierania pokazuje ostrzeżenie o duplikacie, ale nie blokuje świadomego ponownego pobrania.

## 1.3.38

- Dodano zwijany podgląd ostatnich linii logu `yt-dlp` przy zadaniach.
- Log zadań jest zapisywany w trwałej kolejce i widoczny przez odświeżane API.

## 1.3.37

- Dodano przycisk `Kopiuj błąd` przy nieudanych zadaniach, kopiujący komunikat błędu do schowka.

## 1.3.36

- Dodano filtr `Błędy` w widoku `Zadania`, panel z krótkim wyjaśnieniem oraz szybkie akcje dla nieudanych zadań.
- Dodano ponawianie pojedynczego błędnego zadania z listy zadań.

## 1.3.35

- Dodano mini odtwarzacz audio/wideo bezpośrednio w Historii, bez przechodzenia do osobnego podglądu.

## 1.3.34

- Dodano przycisk `Ponów nieudane` w widoku `Zadania`, który ponawia wszystkie zadania ze statusem błędu.

## 1.3.33

- Dodano przełącznik widoku Historii: tabela albo galeria miniaturek.
- Widok galerii obsługuje zaznaczanie wpisów, masowe akcje, tagi i pobieranie plików.
- Domknięto wyścig przy zatrzymaniu transmisji live oczekującej na wolny slot.

## 1.3.32

- Tagi w Historii są teraz klikalne i od razu filtrują widok po wybranym tagu.

## 1.3.31

- Dodano automatyczne tagi historii, m.in. `youtube`, `twitch`, `kick`, `audio`, `video`, `live` i `1080p`.
- Wyszukiwarka historii uwzględnia tagi automatyczne razem z ręcznymi.

## 1.3.30

- Dodano ręczne tagowanie wpisów na stronie `Historia`, np. `muzyka`, `tutoriale`, `live` albo `archiwum`.
- Wyszukiwarka historii uwzględnia zapisane tagi.

## 1.3.29

- Dodano masowe akcje na stronie `Historia`: usuwanie wpisów, usuwanie plików oraz ponowne pobieranie zaznaczonych pozycji.

## 1.3.28

- Dodano sortowanie osobnej strony `Historia` po dacie, rozmiarze, długości, tytule i serwisie.

## 1.3.27

- Dodano osobną stronę `Historia` z wyszukiwarką po tytule, nazwie pliku, serwisie, URL, dacie, rozmiarze i długości.
- Nowe rekordy historii zapisują długość materiału, jeśli była dostępna w analizie.

## 1.3.26

- Dodano powiadomienia Home Assistant po zakończeniu pobierania i po błędzie zadania.

## 1.3.25

- Usunięto sztywny pin `yt-dlp` z `requirements.txt`, aby build instalował najnowszą dostępną wersję.

## 1.3.24

- Dodano stan aktualizacji `yt-dlp` w `/data/jobs/ytdlp_update.json`.
- Aplikacja ponawia aktualizację `yt-dlp` co 24 godziny oraz przed analizą lub pobieraniem, jeśli ostatnia aktualizacja jest nieaktualna albo nieudana.

## 1.3.23

- `yt-dlp` jest teraz zawsze aktualizowany przy starcie dodatku, bez osobnego przełącznika w konfiguracji.

## 1.3.22

- Dodano obsługę publicznych kanałów, VOD i klipów Twitch obsługiwanych przez `yt-dlp`.

## 1.3.21

- Kliknięcie miniatury lub tytułu w historii pobrań otwiera podgląd filmu.
- Dodano przycisk `Pobierz plik` w historii pobrań i na ekranie podglądu.

## 1.3.20

- Dodano kolumnę `Tytuł` obok `Miniatura` w tabeli historii pobrań.

## 1.3.19

- Dodano opcję uruchomienia panelu na osobnym porcie bez Home Assistant Ingress.
- Dodano domyślne mapowanie portu `999/tcp` dla publicznego dostępu w zaufanej sieci.

## 1.3.18

- Dodano miniatury w widoku `Zadania`.
- Rozszerzono opcje NFS o adres serwera, export, login, hasło i opcje montowania.
- Dodano nową ikonę aplikacji.

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
