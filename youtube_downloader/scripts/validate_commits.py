"""Reject vague commit subjects and enforce Conventional Commits."""

from __future__ import annotations

import argparse
import re
import subprocess

FORBIDDEN = {"x", "fix", "update"}
CONVENTIONAL_RE = re.compile(
    r"^(?:feat|fix|refactor|security|perf|test|docs|build|ci|chore|revert)"
    r"(?:\([a-z0-9][a-z0-9._/-]*\))?!?: .{3,}$"
)


def subjects(revision_range: str) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--format=%s", revision_range],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("revision_range")
    args = parser.parse_args()
    invalid = [
        subject
        for subject in subjects(args.revision_range)
        if not subject.startswith(("Merge ", "Revert \""))
        and (subject.casefold() in FORBIDDEN or not CONVENTIONAL_RE.fullmatch(subject))
    ]
    if invalid:
        print("Niepoprawne komunikaty commitów:")
        for subject in invalid:
            print(f"- {subject}")
        print("Użyj formatu Conventional Commits, np. fix(storage): honor selection")
        return 1
    print("Komunikaty commitów są zgodne z Conventional Commits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
