"""Central validation for background job state transitions."""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    """Canonical persisted job states."""

    PENDING = "pending"
    WAITING = "waiting"
    DOWNLOADING = "downloading"
    STOPPING = "stopping"
    COMPLETED = "completed"
    ERROR = "error"
    STOPPED = "stopped"
    INTERRUPTED = "interrupted"


class InvalidJobTransition(RuntimeError):
    """Raised when runtime code attempts an unsupported state transition."""


ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset(
        {
            JobStatus.WAITING,
            JobStatus.DOWNLOADING,
            JobStatus.STOPPED,
            JobStatus.INTERRUPTED,
            JobStatus.ERROR,
        }
    ),
    JobStatus.WAITING: frozenset(
        {
            JobStatus.DOWNLOADING,
            JobStatus.STOPPED,
            JobStatus.INTERRUPTED,
            JobStatus.ERROR,
        }
    ),
    JobStatus.DOWNLOADING: frozenset(
        {
            JobStatus.STOPPING,
            JobStatus.COMPLETED,
            JobStatus.ERROR,
            JobStatus.STOPPED,
            JobStatus.INTERRUPTED,
        }
    ),
    # Completion can win a race with a Stop click after yt-dlp has already
    # produced a valid final file. Treat that transition as valid.
    JobStatus.STOPPING: frozenset(
        {
            JobStatus.COMPLETED,
            JobStatus.ERROR,
            JobStatus.STOPPED,
            JobStatus.INTERRUPTED,
        }
    ),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.ERROR: frozenset({JobStatus.PENDING}),
    JobStatus.STOPPED: frozenset({JobStatus.PENDING}),
    JobStatus.INTERRUPTED: frozenset({JobStatus.PENDING}),
}


def ensure_job_transition(current: str, target: str) -> None:
    """Validate a state transition while allowing idempotent writes."""

    try:
        current_status = JobStatus(current)
        target_status = JobStatus(target)
    except ValueError as error:
        raise InvalidJobTransition(
            f"Nieznany status zadania: {current!r} -> {target!r}."
        ) from error

    if current_status == target_status:
        return
    if target_status not in ALLOWED_TRANSITIONS[current_status]:
        raise InvalidJobTransition(
            f"Niedozwolone przejście statusu: {current_status.value} -> {target_status.value}."
        )
