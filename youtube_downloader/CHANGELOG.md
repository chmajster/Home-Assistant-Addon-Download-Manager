# Changelog

## 1.3.105

- Zaktualizowano statyczny FFmpeg z `8.1.1` do `8.1.2` przez scalenie aktualizacji Dependabot.
- Dostosowano aktualizację GitHub Actions z konfliktującego PR-a Dependabot do bieżącego `main`: `docker/setup-qemu-action` i `docker/setup-buildx-action` podniesiono z `v3` do `v4`, a `docker/build-push-action` z `v6` do `v7`.
- Zachowano nowsze wersje `actions/checkout@v7` i `actions/setup-python@v7` obecne już w repozytorium, bez cofania ich do wersji z nieaktualnego PR-a.

## 1.3.104

- Dodano uniwersalny fallback dla publicznych odtwarzaczy XFileSharing/JWPlayer, obejmujący formularz `/dl` z `op=embed` i `file_code`, dzięki czemu obsługiwane są m.in. linki LuluVDO bez twardego przypisywania domeny.
- Dodano bezpieczne, statyczne rozpakowywanie Dean Edwards P.A.C.K.E.R. oraz wykrywanie podpisanych źródeł HLS i bezpośrednich plików wideo bez wykonywania kodu JavaScript.
- Zachowano walidację publicznych adresów i przekierowań oraz blokadę DRM; dodano testy regresyjne dla spakowanych playerów, formularza embed i wykrywania źródeł.

## 1.3.102

- Przeniesiono walidację przejść stanów z monkey-patchingu do `ProcessJobManager` i dodano trwałą pauzę kolejki przechowywaną w `/data/jobs/runtime.json`.
- Dodano wersjonowane endpointy `/api/v1`, strumień Server-Sent Events dla zadań i kolejki oraz zgodność wsteczną z dotychczasowymi ścieżkami `/api`.
- Dodano konfigurowalną rezerwę wolnego miejsca `min_free_space_gb`, sprawdzaną przed uruchomieniem nowego zwykłego pobrania.
- Wzmocniono dostęp bez Ingress o 12-godzinną sesję, wylogowanie i ograniczenie błędnych prób logowania; ujednolicono dokumentację z wymaganiem tokenu.
- Rozszerzono CI o `yamllint`, `pip-audit`, dodatkowe kontrole runtime hardeningu oraz dynamiczne pobieranie wersji obrazu zamiast twardego `BUILD_VERSION`.
- Dodano testy regresyjne trwałości pauzy kolejki, polityki wolnego miejsca oraz zewnętrznej sesji.

## 1.3.101

- Zabezpieczono dostęp bez Ingress osobnym tokenem, trybem fail-closed i blokadą współdzielenia portu 8099 z listenerem zewnętrznym.
- Dodano walidację przejść stanów zadań, pauzę i wznowienie startu nowych pobrań, diagnostykę runtime oraz opcjonalne automatyczne wznawianie przerwanych zwykłych zadań po restarcie.
- Odtworzono CI i walidację release z testami jakości, pełnym zestawem testów oraz buildami `amd64` i `aarch64`; dodano osobny moduł testów hardeningu.
- Przypięto bazową wersję `yt-dlp` do wheelhouse dla odtwarzalnych buildów oraz usunięto śledzony plik `.test-output.txt` z artefaktami testów.

## 1.3.100

- Naprawiono zatrzymywanie zwykłych pobrań przez uruchamianie `yt-dlp` i jego procesów `ffmpeg` w osobnej grupie procesów, którą można przerwać natychmiast po użyciu akcji Stop.
- Zatrzymane ręcznie pobrania kończą się statusem `stopped`, zachowując częściowe pliki do późniejszego wznowienia.

## 1.3.99

- Usunięto pionowy pasek po prawej stronie trybu kinowego przez rozciągnięcie sekcji odtwarzacza na pełną szerokość viewportu.

## 1.3.98

- Podniesiono wersję dodatku po wdrożeniu blokowania duplikatów istniejących plików.

## 1.3.97

- Domyślnie blokowane są duplikaty istniejących plików i aktywnych zadań, natomiast wpisy po usunięciu pliku pozwalają pobrać materiał ponownie.

## 1.3.96

- Szybkie pobieranie pozostaje teraz na stronie startowej, po poprawnym dodaniu pokazuje powiadomienie i czyści pole URL.
- Dodano przycisk do ręcznego czyszczenia pola URL wraz ze stanem walidacji i listą wykrytych linków.

## 1.3.95

- Usunięto czarny pasek wychodzący poza prawą krawędź odtwarzacza przez ograniczenie szerokości podglądu i kontrolek.

## 1.3.94

- Dodano w widoku Podgląd przyciski oraz skróty klawiaturowe do przechodzenia do poprzedniej i następnej klatki filmu.

## 1.3.93

- Poprawiono powrót z trybu kinowego, aby strona nie zachowywała poziomego przesunięcia ani czarnego pasa po prawej stronie.

## 1.3.92

- Usunięto ograniczenie rozmiaru odtwarzacza w pełnym ekranie, eliminując czarny pas po prawej stronie i rozciągając pasek sterowania na całą szerokość.

## 1.3.91

- Poprawiono opcję „Wypełnij ekran” w ustawieniu dopasowania odtwarzacza, aby obraz rzeczywiście zajmował cały obszar odtwarzania.

## 1.3.90

- Wyłączono zapamiętywanie prędkości odtwarzania i dodano natychmiastowe przełączanie tempa przyciskami presetów od 0,25× do 3×.

## 1.3.89

- Dodano repozytoryjną instrukcję automatycznego tworzenia osobnego, odpowiednio opisanego commita po każdej zweryfikowanej zmianie.

## 1.3.88

- Dodano sekcję „Miniatury” w szczegółach ukończonego zadania, obejmującą miniaturę z filmu i miniaturę źródłową.

## 1.3.87
