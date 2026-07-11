"""SQLite-backed persistent state for history and job queue records."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 5
JOB_PAYLOAD_LOG_LINE_LIMIT = 40
JOB_LOG_LINE_LIMIT = 5000
WAL_CHECKPOINT_INTERVAL_SECONDS = 300


class SQLiteStateStore:
    """Store mutable application state in a small SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._log_connection: sqlite3.Connection | None = None
        self._last_checkpoint = time.monotonic()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = self.db_path.with_suffix(self.db_path.suffix + ".pre-migration.bak")
        had_database = self.db_path.exists()
        if had_database:
            self._backup_database(self.db_path, backup_path)
        try:
            with self._connection() as connection:
                self._initialize(connection)
                if self.quick_check(connection) != "ok":
                    raise sqlite3.DatabaseError("PRAGMA quick_check failed after migration")
        except Exception:
            self.close()
            if had_database and backup_path.exists():
                self._backup_database(backup_path, self.db_path)
            raise
        else:
            backup_path.unlink(missing_ok=True)

    @staticmethod
    def _backup_database(source: Path, destination: Path) -> None:
        """Create a consistent SQLite backup, including committed WAL pages."""
        source_connection = sqlite3.connect(source)
        destination_connection = sqlite3.connect(destination)
        try:
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
            source_connection.close()

    def close(self) -> None:
        """Close long-lived SQLite handles held for append-heavy log writes."""

        with self._lock:
            if self._log_connection is not None:
                self._log_connection.close()
                self._log_connection = None

    def migrate_history_json(self, history_file: Path) -> None:
        """Import legacy history.json records when the SQLite table is still empty."""

        with self._lock:
            if self._table_count("history_records") > 0:
                return
            records = self._read_legacy_json_list(history_file, "historii")
            if not records:
                return
            self.history_replace(records)
            LOGGER.info(
                "Przeniesiono %s wpisów historii z %s do %s",
                len(records),
                history_file,
                self.db_path,
            )

    def migrate_jobs_json(self, jobs_file: Path) -> None:
        """Import legacy queue.json records when the SQLite table is still empty."""

        with self._lock:
            if self._table_count("jobs") > 0:
                return
            records = self._read_legacy_json_list(jobs_file, "kolejki zadań")
            if not records:
                return
            self.jobs_replace(records, replace_logs=True)
            LOGGER.info(
                "Przeniesiono %s zadań z %s do %s",
                len(records),
                jobs_file,
                self.db_path,
            )

    def history_all(self) -> list[dict[str, Any]]:
        """Return history records in the same newest-first order used by the UI."""

        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM history_records ORDER BY position ASC"
            ).fetchall()
        return [self._decode_payload(row["payload"], "historii") for row in rows]

    def history_replace(self, records: list[dict[str, Any]]) -> None:
        """Replace the complete history snapshot atomically."""

        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM history_records")
            connection.executemany(
                """
                INSERT INTO history_records (
                    position, downloaded_at, filename, title, url, source,
                    download_type, status, size, duration, tags, error_code,
                    storage_name, source_thumbnail_filename, auto_tags, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    self._history_row(position, record)
                    for position, record in enumerate(records)
                ],
            )

    def history_clear(self) -> None:
        """Delete legacy history records after they have been folded into jobs."""

        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM history_records")

    def jobs_all(self) -> list[dict[str, Any]]:
        """Return persisted job snapshots."""

        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM jobs ORDER BY created_at DESC, job_id ASC"
            ).fetchall()
        return [self._decode_payload(row["payload"], "kolejki zadań") for row in rows]

    def jobs_replace(
        self, records: list[dict[str, Any]], replace_logs: bool = False
    ) -> None:
        """Replace the complete job queue snapshot atomically."""

        rows = [row for row in (self._job_row(record) for record in records) if row]
        job_ids = [str(row[0]) for row in rows]
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM jobs")
            connection.executemany(
                """
                INSERT INTO jobs (
                    job_id, created_at, status, title, url, download_type, is_live,
                    finished_at, error_message, error_code, storage_name,
                    source_thumbnail_filename, auto_tags, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._delete_removed_job_logs(connection, job_ids)
            if replace_logs:
                for record in records:
                    job_id = self._text_or_none(record.get("job_id"))
                    if job_id:
                        self._replace_job_logs_connection(
                            connection, job_id, record.get("log_lines")
                        )

    def upsert_job(self, record: dict[str, Any]) -> None:
        """Insert or update exactly one job without touching other jobs or logs."""

        row = self._job_row(record)
        if not row:
            return
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, created_at, status, title, url, download_type, is_live,
                    finished_at, error_message, error_code, storage_name,
                    source_thumbnail_filename, auto_tags, updated_at, payload, source_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    created_at=excluded.created_at, status=excluded.status,
                    title=excluded.title, url=excluded.url,
                    download_type=excluded.download_type, is_live=excluded.is_live,
                    finished_at=excluded.finished_at, error_message=excluded.error_message,
                    error_code=excluded.error_code, storage_name=excluded.storage_name,
                    source_thumbnail_filename=excluded.source_thumbnail_filename,
                    auto_tags=excluded.auto_tags, updated_at=excluded.updated_at,
                    payload=excluded.payload, source_id=excluded.source_id
                """,
                (*row, self._text_or_none(record.get("source_id"))),
            )

    def delete_job(self, job_id: str) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM job_log_lines WHERE job_id = ?", (job_id,))
            connection.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))

    def update_job_progress(self, job_id: str, record: dict[str, Any]) -> None:
        """Persist one job's throttled progress snapshot."""
        self.upsert_job(record)

    def update_job_status(self, job_id: str, record: dict[str, Any]) -> None:
        """Persist a status transition immediately."""
        self.upsert_job(record)

    def remember_download_identity(self, identity: dict[str, Any]) -> None:
        """Keep durable duplicate keys independently from jobs and files."""
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO download_identities
                   (job_id, source_id, extractor_key, canonical_url, title_key,
                    filename_key, sha256, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(job_id) DO UPDATE SET
                     source_id=excluded.source_id, extractor_key=excluded.extractor_key,
                     canonical_url=excluded.canonical_url, title_key=excluded.title_key,
                     filename_key=excluded.filename_key, sha256=excluded.sha256""",
                tuple(identity.get(key) for key in (
                    "job_id", "source_id", "extractor_key", "canonical_url",
                    "title_key", "filename_key", "sha256",
                )),
            )

    def download_identities(self) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute("SELECT * FROM download_identities").fetchall()
        return [dict(row) for row in rows]

    def job_logs(self, job_id: str, limit: int | None = None) -> list[str]:
        """Return persisted log lines for one job."""

        with self._lock, self._connection() as connection:
            if limit is None:
                rows = connection.execute(
                    """
                    SELECT message FROM job_log_lines
                    WHERE job_id = ?
                    ORDER BY line_number ASC
                    """,
                    (job_id,),
                ).fetchall()
                return [str(row["message"]) for row in rows]
            rows = connection.execute(
                """
                SELECT message FROM job_log_lines
                WHERE job_id = ?
                ORDER BY line_number DESC
                LIMIT ?
                """,
                (job_id, limit),
            ).fetchall()
        return [str(row["message"]) for row in reversed(rows)]

    def append_job_log(self, job_id: str, message: str) -> None:
        """Append one log line using the transactional batch implementation."""
        self.append_job_logs(job_id, [message])

    def append_job_logs(self, job_id: str, messages: list[str]) -> None:
        """Append a batch of log lines in one transaction and enforce retention."""
        if not messages:
            return
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(line_number), -1) + 1 AS n FROM job_log_lines WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            start = int(row["n"] if row else 0)
            connection.executemany(
                "INSERT INTO job_log_lines (job_id, line_number, message) VALUES (?, ?, ?)",
                [(job_id, start + index, message) for index, message in enumerate(messages)],
            )
            self._trim_job_logs_connection(connection, job_id)

    @staticmethod
    def _trim_job_logs_connection(connection: sqlite3.Connection, job_id: str) -> None:
        connection.execute(
            """DELETE FROM job_log_lines WHERE job_id = ? AND line_number NOT IN
               (SELECT line_number FROM job_log_lines WHERE job_id = ?
                ORDER BY line_number DESC LIMIT ?)""",
            (job_id, job_id, JOB_LOG_LINE_LIMIT),
        )

    def quick_check(self, connection: sqlite3.Connection | None = None) -> str:
        """Return SQLite's lightweight integrity-check result."""
        if connection is not None:
            row = connection.execute("PRAGMA quick_check").fetchone()
            return str(row[0] if row else "unknown")
        with self._lock, self._connection() as own_connection:
            row = own_connection.execute("PRAGMA quick_check").fetchone()
        return str(row[0] if row else "unknown")

    def checkpoint(self, mode: str = "PASSIVE") -> None:
        if mode not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
            raise ValueError("Unsupported WAL checkpoint mode")
        with self._lock, self._connection() as connection:
            connection.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        self._last_checkpoint = time.monotonic()

    def replace_job_logs(self, job_id: str, lines: object) -> None:
        """Replace the durable full job log for one job."""

        with self._lock, self._connection() as connection:
            self._replace_job_logs_connection(connection, job_id, lines)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _append_connection(self) -> sqlite3.Connection:
        if self._log_connection is None:
            self._log_connection = self._connect()
        return self._log_connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()
            if time.monotonic() - self._last_checkpoint >= WAL_CHECKPOINT_INTERVAL_SECONDS:
                try:
                    with self._lock:
                        checkpoint_connection = self._connect()
                        checkpoint_connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
                        checkpoint_connection.close()
                        self._last_checkpoint = time.monotonic()
                except sqlite3.Error:
                    LOGGER.warning("Nie udało się wykonać okresowego checkpointu WAL.", exc_info=True)

    def _initialize(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        previous_version = self._schema_version(connection)
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS history_records (
                position INTEGER PRIMARY KEY,
                downloaded_at TEXT,
                filename TEXT,
                title TEXT,
                url TEXT,
                source TEXT,
                download_type TEXT,
                status TEXT,
                size INTEGER,
                duration INTEGER,
                tags TEXT,
                error_code TEXT,
                storage_name TEXT,
                source_thumbnail_filename TEXT,
                auto_tags TEXT,
                payload TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                created_at TEXT,
                status TEXT,
                title TEXT,
                url TEXT,
                download_type TEXT,
                is_live INTEGER,
                finished_at TEXT,
                error_message TEXT,
                error_code TEXT,
                storage_name TEXT,
                source_thumbnail_filename TEXT,
                auto_tags TEXT,
                updated_at TEXT,
                payload TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_log_lines (
                job_id TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (job_id, line_number)
            );

            CREATE TABLE IF NOT EXISTS download_identities (
                job_id TEXT PRIMARY KEY,
                source_id TEXT,
                extractor_key TEXT,
                canonical_url TEXT,
                title_key TEXT,
                filename_key TEXT,
                sha256 TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self._migrate_schema(connection, previous_version)
        self._create_indexes(connection)
        connection.execute(
            """
            INSERT OR REPLACE INTO schema_meta (key, value)
            VALUES ('schema_version', ?)
            """,
            (str(SCHEMA_VERSION),),
        )

    def _create_indexes(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_history_downloaded_at
                ON history_records(downloaded_at);
            CREATE INDEX IF NOT EXISTS idx_history_filename
                ON history_records(filename);
            CREATE INDEX IF NOT EXISTS idx_history_url
                ON history_records(url);
            CREATE INDEX IF NOT EXISTS idx_history_source
                ON history_records(source);
            CREATE INDEX IF NOT EXISTS idx_history_status
                ON history_records(status);
            CREATE INDEX IF NOT EXISTS idx_history_size
                ON history_records(size);
            CREATE INDEX IF NOT EXISTS idx_history_duration
                ON history_records(duration);
            CREATE INDEX IF NOT EXISTS idx_jobs_status
                ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_created_at
                ON jobs(created_at);
            CREATE INDEX IF NOT EXISTS idx_jobs_url
                ON jobs(url);
            CREATE INDEX IF NOT EXISTS idx_jobs_download_type
                ON jobs(download_type);
            CREATE INDEX IF NOT EXISTS idx_jobs_is_live
                ON jobs(is_live);
            CREATE INDEX IF NOT EXISTS idx_jobs_finished_at ON jobs(finished_at);
            CREATE INDEX IF NOT EXISTS idx_jobs_storage_name ON jobs(storage_name);
            CREATE INDEX IF NOT EXISTS idx_jobs_source_id ON jobs(source_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at);
            CREATE INDEX IF NOT EXISTS idx_job_log_lines_job_id
                ON job_log_lines(job_id);
            CREATE INDEX IF NOT EXISTS idx_identity_source_id ON download_identities(source_id);
            CREATE INDEX IF NOT EXISTS idx_identity_extractor ON download_identities(extractor_key);
            CREATE INDEX IF NOT EXISTS idx_identity_url ON download_identities(canonical_url);
            CREATE INDEX IF NOT EXISTS idx_identity_title ON download_identities(title_key);
            CREATE INDEX IF NOT EXISTS idx_identity_filename ON download_identities(filename_key);
            CREATE INDEX IF NOT EXISTS idx_identity_sha256 ON download_identities(sha256);
            """
        )

    def _schema_version(self, connection: sqlite3.Connection) -> int:
        try:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.Error:
            return 0
        if not row:
            return 0
        try:
            return int(str(row["value"]))
        except (TypeError, ValueError):
            return 0

    def _migrate_schema(
        self, connection: sqlite3.Connection, previous_version: int
    ) -> None:
        if previous_version < 2:
            self._migrate_to_v2(connection)
        if previous_version < 3:
            self._migrate_to_v3(connection)
        if previous_version < 4:
            self._migrate_to_v4(connection)
        if previous_version < 5:
            self._migrate_to_v5(connection)

    def _migrate_to_v5(self, connection: sqlite3.Connection) -> None:
        for row in connection.execute("SELECT job_id, payload FROM jobs").fetchall():
            record = self._decode_payload(row["payload"], "kolejki zadań")
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            filename = record.get("output_file") or ""
            connection.execute(
                """INSERT OR IGNORE INTO download_identities
                   (job_id, source_id, extractor_key, canonical_url, title_key, filename_key, sha256)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (row["job_id"], record.get("source_id"), metadata.get("extractor_key"),
                 record.get("url"), str(record.get("title") or "").casefold(),
                 str(filename).casefold(), metadata.get("sha256")),
            )

    def _migrate_to_v4(self, connection: sqlite3.Connection) -> None:
        columns = self._table_columns(connection, "jobs")
        self._add_column_if_missing(connection, "jobs", columns, "source_id", "TEXT")
        for row in connection.execute("SELECT job_id, payload FROM jobs").fetchall():
            record = self._decode_payload(row["payload"], "kolejki zadań")
            connection.execute(
                "UPDATE jobs SET source_id = ? WHERE job_id = ?",
                (self._text_or_none(record.get("source_id")), row["job_id"]),
            )

    def _migrate_to_v2(self, connection: sqlite3.Connection) -> None:
        history_columns = self._table_columns(connection, "history_records")
        self._add_column_if_missing(
            connection, "history_records", history_columns, "source", "TEXT"
        )
        self._add_column_if_missing(
            connection, "history_records", history_columns, "tags", "TEXT"
        )
        job_columns = self._table_columns(connection, "jobs")
        for column_name, column_type in {
            "title": "TEXT",
            "url": "TEXT",
            "download_type": "TEXT",
            "is_live": "INTEGER",
            "finished_at": "TEXT",
            "error_message": "TEXT",
            "updated_at": "TEXT",
        }.items():
            self._add_column_if_missing(
                connection, "jobs", job_columns, column_name, column_type
            )
        self._backfill_normalized_columns(connection)
        self._backfill_job_logs(connection)

    def _migrate_to_v3(self, connection: sqlite3.Connection) -> None:
        history_columns = self._table_columns(connection, "history_records")
        for column_name in (
            "error_code",
            "storage_name",
            "source_thumbnail_filename",
            "auto_tags",
        ):
            self._add_column_if_missing(
                connection, "history_records", history_columns, column_name, "TEXT"
            )
        job_columns = self._table_columns(connection, "jobs")
        for column_name in (
            "error_code",
            "storage_name",
            "source_thumbnail_filename",
            "auto_tags",
        ):
            self._add_column_if_missing(
                connection, "jobs", job_columns, column_name, "TEXT"
            )
        self._backfill_v3_columns(connection)

    @staticmethod
    def _table_columns(
        connection: sqlite3.Connection, table_name: str
    ) -> set[str]:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row["name"]) for row in rows}

    @staticmethod
    def _add_column_if_missing(
        connection: sqlite3.Connection,
        table_name: str,
        columns: set[str],
        column_name: str,
        column_type: str,
    ) -> None:
        if column_name in columns:
            return
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )
        columns.add(column_name)

    def _backfill_normalized_columns(self, connection: sqlite3.Connection) -> None:
        for row in connection.execute(
            "SELECT position, payload FROM history_records"
        ).fetchall():
            record = self._decode_payload(row["payload"], "historii")
            connection.execute(
                """
                UPDATE history_records
                SET source = ?, tags = ?
                WHERE position = ?
                """,
                (
                    self._history_source(record),
                    self._tags_text(record.get("tags")),
                    row["position"],
                ),
            )
        for row in connection.execute("SELECT job_id, payload FROM jobs").fetchall():
            record = self._decode_payload(row["payload"], "kolejki zadań")
            connection.execute(
                """
                UPDATE jobs
                SET title = ?, url = ?, download_type = ?, is_live = ?,
                    finished_at = ?, error_message = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    self._text_or_none(record.get("title")),
                    self._text_or_none(record.get("url")),
                    self._text_or_none(record.get("download_type")),
                    self._bool_int(record.get("is_live")),
                    self._text_or_none(record.get("finished_at")),
                    self._text_or_none(record.get("error_message")),
                    self._text_or_none(record.get("finished_at"))
                    or self._text_or_none(record.get("started_at"))
                    or self._text_or_none(record.get("created_at")),
                    row["job_id"],
                ),
            )

    def _backfill_job_logs(self, connection: sqlite3.Connection) -> None:
        existing = connection.execute(
            "SELECT COUNT(*) AS total FROM job_log_lines"
        ).fetchone()
        if existing and int(existing["total"]) > 0:
            return
        for row in connection.execute("SELECT job_id, payload FROM jobs").fetchall():
            record = self._decode_payload(row["payload"], "kolejki zadań")
            self._replace_job_logs_connection(
                connection, str(row["job_id"]), record.get("log_lines")
            )

    def _backfill_v3_columns(self, connection: sqlite3.Connection) -> None:
        for row in connection.execute(
            "SELECT position, payload FROM history_records"
        ).fetchall():
            record = self._decode_payload(row["payload"], "historii")
            connection.execute(
                """
                UPDATE history_records
                SET error_code = ?, storage_name = ?, source_thumbnail_filename = ?,
                    auto_tags = ?
                WHERE position = ?
                """,
                (
                    self._text_or_none(record.get("error_code")),
                    self._text_or_none(record.get("storage_name")) or "local",
                    self._text_or_none(record.get("source_thumbnail_filename")),
                    self._tags_text(record.get("auto_tags")),
                    row["position"],
                ),
            )
        for row in connection.execute("SELECT job_id, payload FROM jobs").fetchall():
            record = self._decode_payload(row["payload"], "kolejki zadań")
            connection.execute(
                """
                UPDATE jobs
                SET error_code = ?, storage_name = ?, source_thumbnail_filename = ?,
                    auto_tags = ?
                WHERE job_id = ?
                """,
                (
                    self._text_or_none(record.get("error_code")),
                    self._text_or_none(record.get("storage_name")) or "local",
                    self._text_or_none(record.get("source_thumbnail_filename")),
                    self._tags_text(record.get("auto_tags")),
                    row["job_id"],
                ),
            )
            record["log_lines"] = self._recent_log_lines(record.get("log_lines"))
            connection.execute(
                "UPDATE jobs SET payload = ? WHERE job_id = ?",
                (
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                    row["job_id"],
                ),
            )

    def _table_count(self, table_name: str) -> int:
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS total FROM {table_name}"
            ).fetchone()
        return int(row["total"] if row else 0)

    @staticmethod
    def _read_legacy_json_list(path: Path, label: str) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
        except (OSError, json.JSONDecodeError) as error:
            LOGGER.error("Nie można odczytać starego pliku %s: %s", label, error)
            return []
        if not isinstance(payload, list):
            LOGGER.error("Stary plik %s nie zawiera listy rekordow.", label)
            return []
        return [record for record in payload if isinstance(record, dict)]

    @staticmethod
    def _decode_payload(payload: str, label: str) -> dict[str, Any]:
        try:
            record = json.loads(payload)
        except json.JSONDecodeError as error:
            LOGGER.error("Nie można odczytać rekordu %s z SQLite: %s", label, error)
            return {}
        return record if isinstance(record, dict) else {}

    @staticmethod
    def _history_row(position: int, record: dict[str, Any]) -> tuple[Any, ...]:
        return (
            position,
            SQLiteStateStore._text_or_none(record.get("downloaded_at")),
            SQLiteStateStore._text_or_none(record.get("filename")),
            SQLiteStateStore._text_or_none(record.get("title")),
            SQLiteStateStore._text_or_none(record.get("url")),
            SQLiteStateStore._history_source(record),
            SQLiteStateStore._text_or_none(record.get("type")),
            SQLiteStateStore._text_or_none(record.get("status")),
            SQLiteStateStore._int_or_none(record.get("size")),
            SQLiteStateStore._int_or_none(record.get("duration")),
            SQLiteStateStore._tags_text(record.get("tags")),
            SQLiteStateStore._text_or_none(record.get("error_code")),
            SQLiteStateStore._text_or_none(record.get("storage_name")) or "local",
            SQLiteStateStore._text_or_none(record.get("source_thumbnail_filename")),
            SQLiteStateStore._tags_text(record.get("auto_tags")),
            json.dumps(record, ensure_ascii=False, separators=(",", ":")),
        )

    @staticmethod
    def _job_row(record: dict[str, Any]) -> tuple[Any, ...] | None:
        job_id = SQLiteStateStore._text_or_none(record.get("job_id"))
        if not job_id:
            job_id = SQLiteStateStore._text_or_none(record.get("id")) or ""
        if not job_id:
            LOGGER.warning("Pominięto rekord kolejki bez identyfikatora zadania.")
            return None
        payload = dict(record)
        payload["log_lines"] = SQLiteStateStore._recent_log_lines(
            payload.get("log_lines")
        )
        return (
            job_id,
            SQLiteStateStore._text_or_none(record.get("created_at")),
            SQLiteStateStore._text_or_none(record.get("status")),
            SQLiteStateStore._text_or_none(record.get("title")),
            SQLiteStateStore._text_or_none(record.get("url")),
            SQLiteStateStore._text_or_none(record.get("download_type")),
            SQLiteStateStore._bool_int(record.get("is_live")),
            SQLiteStateStore._text_or_none(record.get("finished_at")),
            SQLiteStateStore._text_or_none(record.get("error_message")),
            SQLiteStateStore._text_or_none(record.get("error_code")),
            SQLiteStateStore._text_or_none(record.get("storage_name")) or "local",
            SQLiteStateStore._text_or_none(record.get("source_thumbnail_filename")),
            SQLiteStateStore._tags_text(record.get("auto_tags")),
            SQLiteStateStore._text_or_none(record.get("finished_at"))
            or SQLiteStateStore._text_or_none(record.get("started_at"))
            or SQLiteStateStore._text_or_none(record.get("created_at")),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )

    @staticmethod
    def _recent_log_lines(lines: object) -> list[str]:
        if not isinstance(lines, list):
            return []
        return [str(line) for line in lines[-JOB_PAYLOAD_LOG_LINE_LIMIT:]]

    @staticmethod
    def _history_source(record: dict[str, Any]) -> str | None:
        explicit = SQLiteStateStore._text_or_none(record.get("source"))
        if explicit:
            return explicit
        url = SQLiteStateStore._text_or_none(record.get("url")) or ""
        host = url.lower()
        for source in ("youtube", "twitch", "kick", "instagram"):
            if source in host:
                return source
        return None

    @staticmethod
    def _tags_text(value: object) -> str | None:
        if isinstance(value, list):
            tags = [str(tag).strip() for tag in value if str(tag).strip()]
            return ",".join(tags) if tags else None
        return None

    @staticmethod
    def _bool_int(value: object) -> int:
        return 1 if bool(value) else 0

    def _delete_removed_job_logs(
        self, connection: sqlite3.Connection, job_ids: list[str]
    ) -> None:
        if not job_ids:
            connection.execute("DELETE FROM job_log_lines")
            return
        placeholders = ",".join("?" for _ in job_ids)
        connection.execute(
            f"DELETE FROM job_log_lines WHERE job_id NOT IN ({placeholders})",
            job_ids,
        )

    def _replace_job_logs_connection(
        self, connection: sqlite3.Connection, job_id: str, lines: object
    ) -> None:
        connection.execute("DELETE FROM job_log_lines WHERE job_id = ?", (job_id,))
        if not isinstance(lines, list):
            return
        connection.executemany(
            """
            INSERT INTO job_log_lines (job_id, line_number, message)
            VALUES (?, ?, ?)
            """,
            [(job_id, index, str(line)) for index, line in enumerate(lines)],
        )

    @staticmethod
    def _text_or_none(value: object) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
