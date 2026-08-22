# Offline Python wheelhouse

Ten katalog zawiera przypięte paczki Python wymagane podczas budowania dodatku.

Dockerfile instaluje zależności przez `pip --no-index`, aby sam krok instalacji nie
odpytywał PyPI. Wheel `MarkupSafe` jest dostarczony osobno dla `aarch64` oraz
`amd64`; pozostałe lokalne wheel'e są niezależne od architektury.

Bazowy `yt-dlp` jest wyjątkiem: Dockerfile pobiera przypięty wheel bezpośrednio z
PyPI przez `ADD` z wymaganym `--checksum=sha256:...`, a następnie umieszcza go w
`/tmp/wheels` przed instalacją offline. Pozwala to aktualizować podatną wersję bez
wyłączania `pip-audit`, przy zachowaniu weryfikacji integralności artefaktu.
