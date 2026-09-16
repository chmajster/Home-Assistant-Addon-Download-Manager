"""Request/form parsing helpers exported from the shared route layer."""

from __future__ import annotations

from .shared import (
    BULK_URL_IMPORT_LIMIT,
    _download_options_from_form,
    _duration_value,
    _form_bool,
    _positive_int,
    _selected_download_profile,
    _selected_history_records,
    _selected_playlist_entries,
    _valid_form,
    _validated_url_candidates,
)


def _bulk_url_candidates(value: object) -> list[str]:
    """Return unique URLs separated only by line boundaries.

    Commas and semicolons are valid URL characters and may occur in signed
    paths or query strings, so they must not be treated as bulk separators.
    """

    candidates = [item.strip() for item in str(value or "").splitlines() if item.strip()]
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
        if len(unique) >= BULK_URL_IMPORT_LIMIT:
            break
    return unique


__all__ = [
    "_bulk_url_candidates",
    "_download_options_from_form",
    "_duration_value",
    "_form_bool",
    "_positive_int",
    "_selected_download_profile",
    "_selected_history_records",
    "_selected_playlist_entries",
    "_valid_form",
    "_validated_url_candidates",
]
