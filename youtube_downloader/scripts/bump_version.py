"""Bump and validate every add-on version source."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
CONFIG_VERSION_RE = re.compile(r'(?m)^version:\s*"[^"]+"\s*$')
DOCKER_VERSION_RE = re.compile(r'(?m)^ARG BUILD_VERSION="[^"]+"\s*$')
CHANGELOG_VERSION_RE = re.compile(r"(?m)^##\s+([^\s]+)\s*$")
DOCKER_LABELS = (
    'io.hass.version="${BUILD_VERSION}"',
    'org.opencontainers.image.version="${BUILD_VERSION}"',
)


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


def read_required(pattern: re.Pattern[str], path: Path, label: str) -> str:
    match = pattern.search(path.read_text(encoding="utf-8"))
    if not match:
        raise VersionBumpError(f"Nie znaleziono wersji {label} w {path}.")
    return validate_version(match.group(1))


def check_version_consistency(root: Path, expected: str | None = None) -> str:
    """Validate every version source and return the canonical add-on version."""

    root = root.resolve()
    repository_root = root.parent
    config = root / "config.yaml"
    dockerfile = root / "Dockerfile"
    changelog = root / "CHANGELOG.md"
    release_workflow = repository_root / ".github" / "workflows" / "release.yml"
    required = (config, dockerfile, changelog, release_workflow)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise VersionBumpError("Brak wymaganych plików: " + ", ".join(missing))

    config_version = read_required(
        re.compile(r'(?m)^version:\s*"([^"]+)"\s*$'), config, "config.yaml"
    )
    docker_version = read_required(
        re.compile(r'(?m)^ARG BUILD_VERSION="([^"]+)"\s*$'), dockerfile, "Dockerfile"
    )
    changelog_version = read_required(CHANGELOG_VERSION_RE, changelog, "CHANGELOG.md")
    versions = {config_version, docker_version, changelog_version}
    if len(versions) != 1:
        raise VersionBumpError(
            "Niezgodne wersje: "
            f"config={config_version}, Dockerfile={docker_version}, changelog={changelog_version}."
        )
    if expected and config_version != validate_version(expected.removeprefix("v")):
        raise VersionBumpError(
            f"Wersja {config_version} nie odpowiada oczekiwanej {expected.removeprefix('v')}."
        )
    docker_text = dockerfile.read_text(encoding="utf-8")
    for label in DOCKER_LABELS:
        if label not in docker_text:
            raise VersionBumpError(f"Brak etykiety obrazu zależnej od BUILD_VERSION: {label}.")
    workflow_text = release_workflow.read_text(encoding="utf-8")
    workflow_markers = (
        "scripts/bump_version.py --check",
        "steps.version.outputs.version",
        "BUILD_VERSION=${{ steps.version.outputs.version }}",
    )
    for marker in workflow_markers:
        if marker not in workflow_text:
            raise VersionBumpError(f"Workflow release nie używa wersji kanonicznej: {marker}.")
    return config_version


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
    check_version_consistency(root, version)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Podbija lub sprawdza wersję dodatku we wszystkich źródłach."
    )
    parser.add_argument("version", nargs="?", help="Nowa wersja, np. 1.3.55.")
    parser.add_argument("--check", action="store_true", help="Tylko sprawdź zgodność wersji.")
    parser.add_argument("--expected", help="Oczekiwana wersja lub tag, np. v1.3.55.")
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
        if args.check:
            version = check_version_consistency(args.root, args.expected)
            print(f"Wersje są zgodne: {version}.")
            return 0
        if not args.version:
            raise VersionBumpError("Podaj wersję albo użyj --check.")
        bump_version(args.root, args.version, args.change)
    except VersionBumpError as error:
        print(f"Błąd: {error}")
        return 1
    print(f"Podbito wersję do {args.version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
