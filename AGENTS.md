# Repository release instructions

- Before handing off any completed code change, bug fix, or user-facing behavior change, increment the add-on patch version.
- Keep the version identical in `youtube_downloader/config.yaml`, `youtube_downloader/Dockerfile`, and the newest heading in `youtube_downloader/CHANGELOG.md`.
- Add a concise Polish changelog entry describing every change included in the new version. Never bump the version without documenting the actual changes.
- Prefer `youtube_downloader/scripts/bump_version.py` when it can complete successfully; otherwise update all three canonical version sources and verify their consistency manually.
- Run relevant tests after the version and changelog update.
