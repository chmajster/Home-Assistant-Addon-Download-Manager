"""Bump the add-on version in manifest, Dockerfile, and changelog."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
CONFIG_VERSION_RE = re.compile(r'(?m)^version:\s*"[^"]+"\s*$')
DOCKER_VERSION_RE = re.compile(r'(?m)^ARG BUILD_VERSION="[^"]+"\s*$')


class VersionBumpError(RuntimeError):
    """Raised when a version bump cannot be applied safely."""


def validate_version(version: str) -> str:
    """Return a normalized version string or raise for invalid input."""

    normalized = version.strip()
    if not VERSION_RE.fullmatch(normalized):
        raise VersionBumpError(
            "Podaj wersję w formacie MAJOR.MINOR.PATCH, np. 1.3.55."
        )
    return normalized


def replace_required(pattern: re.Pattern[str], text: str, replacement: str, path: Path) -> str:
    """Replace one required pattern occurrence."""

    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise VersionBumpError(f"Nie znaleziono pola wersji w {path}.")
    return updated


def update_config(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(
        replace_required(CONFIG_VERSION_RE, text, f'version: "{version}"', path),
        encoding="utf-8",
    )


def update_dockerfile(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(
        replace_required(DOCKER_VERSION_RE, text, f'ARG BUILD_VERSION="{version}"', path),
        encoding="utf-8",
    )


def changelog_entry(version: str, changes: list[str]) -> str:
    cleaned_changes = [" ".join(change.strip().split()) for change in changes]
    cleaned_changes = [change for change in cleaned_changes if change]
    if not cleaned_changes:
        raise VersionBumpError("Dodaj co najmniej jedną zmianę przez --change.")
    lines = [f"## {version}", ""]
    lines.extend(f"- {change}" for change in cleaned_changes)
    return "\n".join(lines) + "\n\n"


def update_changelog(path: Path, version: str, changes: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    if re.search(rf"(?m)^##\s+{re.escape(version)}\s*$", text):
        raise VersionBumpError(f"Wersja {version} już istnieje w {path}.")
    if not text.startswith("# Changelog"):
        raise VersionBumpError(f"{path} nie zaczyna się od nagłówka '# Changelog'.")
    marker = "# Changelog\n\n"
    if marker not in text:
        raise VersionBumpError(f"Nie znaleziono miejsca na nowy wpis w {path}.")
    updated = text.replace(marker, marker + changelog_entry(version, changes), 1)
    path.write_text(updated, encoding="utf-8")


def bump_version(root: Path, version: str, changes: list[str]) -> None:
    """Update all versioned files for the Home Assistant add-on."""

    version = validate_version(version)
    root = root.resolve()
    files = {
        "config": root / "config.yaml",
        "dockerfile": root / "Dockerfile",
        "changelog": root / "CHANGELOG.md",
    }
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise VersionBumpError("Brak wymaganych plików: " + ", ".join(missing))
    update_config(files["config"], version)
    update_dockerfile(files["dockerfile"], version)
    update_changelog(files["changelog"], version, changes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Podbija wersję dodatku w config.yaml, Dockerfile i CHANGELOG.md."
    )
    parser.add_argument("version", help="Nowa wersja, np. 1.3.55.")
    parser.add_argument(
        "-c",
        "--change",
        action="append",
        default=[],
        help="Punkt changeloga. Można podać wiele razy.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Katalog dodatku. Domyślnie katalog nadrzędny skryptu.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        bump_version(args.root, args.version, args.change)
    except VersionBumpError as error:
        print(f"Błąd: {error}")
        return 1
    print(f"Podbito wersję do {args.version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
