"""Startup sanity checks for critical runtime dependencies."""

from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StartupCheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def run_startup_checks(settings: Any) -> StartupCheckResult:
    """Validate critical directories, binaries and option types before serving."""

    result = StartupCheckResult()
    _check_types(settings, result)
    _check_writable_dir("download_dir", Path(settings.download_dir), result)
    _check_writable_dir("jobs_dir", Path(settings.jobs_dir), result)
    _check_writable_dir("/data/jobs", Path("/data/jobs"), result)
    _check_ffmpeg(result)
    _check_ytdlp_import(result)
    _check_sqlite(Path(settings.history_file).parent / "state.sqlite3", result)
    return result


def assert_startup_ready(settings: Any) -> StartupCheckResult:
    result = run_startup_checks(settings)
    if result.errors:
        raise RuntimeError("Startup sanity-check failed: " + " | ".join(result.errors))
    return result


def _check_types(settings: Any, result: StartupCheckResult) -> None:
    expected = {
        "download_dir": Path,
        "jobs_dir": Path,
        "history_file": Path,
        "max_concurrent_jobs": int,
        "enable_ha_events": bool,
        "debug": bool,
        "preferred_format": str,
        "ui_language": str,
    }
    for name, expected_type in expected.items():
        value = getattr(settings, name, None)
        if not isinstance(value, expected_type):
            result.errors.append(f"{name} ma niepoprawny typ: {type(value).__name__}.")
    if isinstance(getattr(settings, "max_concurrent_jobs", None), int):
        if settings.max_concurrent_jobs < 1:
            result.errors.append("max_concurrent_jobs musi byc >= 1.")


def _check_writable_dir(label: str, path: Path, result: StartupCheckResult) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        result.errors.append(f"{label}: nie mozna utworzyc katalogu {path}: {error}.")
        return
    if not path.is_dir():
        result.errors.append(f"{label}: {path} nie jest katalogiem.")
        return
    if not os.access(path, os.W_OK):
        result.errors.append(f"{label}: {path} nie jest zapisywalny.")
        return
    try:
        with tempfile.NamedTemporaryFile(dir=str(path), prefix=".startup-", delete=True) as handle:
            handle.write(b"ok")
    except OSError as error:
        result.errors.append(f"{label}: test zapisu w {path} nie powiodl sie: {error}.")


def _check_ffmpeg(result: StartupCheckResult) -> None:
    try:
        completed = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        result.errors.append(f"ffmpeg nie uruchamia sie: {error}.")
        return
    if completed.returncode != 0:
        result.errors.append(f"ffmpeg zwrocil kod {completed.returncode}: {(completed.stderr or completed.stdout).strip()}.")


def _check_ytdlp_import(result: StartupCheckResult) -> None:
    try:
        importlib.import_module("yt_dlp")
    except Exception as error:
        result.errors.append(f"yt-dlp nie importuje sie w Pythonie: {error}.")


def _check_sqlite(db_path: Path, result: StartupCheckResult) -> None:
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path, timeout=5)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("CREATE TABLE IF NOT EXISTS startup_check (id INTEGER)")
            connection.execute("DROP TABLE startup_check")
            connection.commit()
        finally:
            connection.close()
    except sqlite3.Error as error:
        result.errors.append(f"SQLite nie moze otworzyc {db_path}: {error}.")
