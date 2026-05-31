# Offline Python wheelhouse

Ten katalog zawiera przypięte paczki Python wymagane podczas budowania dodatku.

Dockerfile instaluje je przez `pip --no-index`, aby budowanie obrazu nie zależało
od działania DNS wewnątrz kroków `RUN`. Wheel `MarkupSafe` jest dostarczony
osobno dla `aarch64` oraz `amd64`; pozostałe wheel'e są niezależne od
architektury.
