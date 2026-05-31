# Changelog

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
