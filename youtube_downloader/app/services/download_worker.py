"""Isolated yt-dlp worker used by ProcessJobManager."""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from .media_service import MediaService, MediaServiceError

PROTOCOL_STDOUT = sys.stdout

INFO_KEYS = (
    "id",
    "title",
    "fulltitle",
    "platform",
    "extractor_key",
    "webpage_url",
    "thumbnail",
    "duration",
    "height",
    "resolution",
    "vcodec",
    "upload_date",
    "release_date",
    "release_year",
    "live_status",
    "is_live",
    "content_type",
)


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _number(value: Any) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def _info_payload(info: Any) -> dict[str, Any]:
    if not isinstance(info, dict):
        return {}

    payload: dict[str, Any] = {}
    for key in INFO_KEYS:
        value = info.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            payload[key] = value

    for key in ("filepath", "_filename"):
        value = _text(info.get(key))
        if value:
            payload[key] = value

    files_to_move = info.get("__files_to_move")
    if isinstance(files_to_move, dict):
        payload["__files_to_move"] = {
            str(source): str(destination)
            for source, destination in files_to_move.items()
            if source and destination
        }

    requested = info.get("requested_downloads")
    if isinstance(requested, list):
        payload["requested_downloads"] = [
            {
                key: item.get(key)
                for key in ("height", "resolution", "vcodec", "acodec")
                if isinstance(item.get(key), (str, int, float, bool))
            }
            for item in requested
            if isinstance(item, dict)
        ]
    return payload


def _hook_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": _text(data.get("status")),
        "filename": _text(data.get("filename")),
        "downloaded_bytes": _number(data.get("downloaded_bytes")),
        "total_bytes": _number(data.get("total_bytes")),
        "total_bytes_estimate": _number(data.get("total_bytes_estimate")),
        "speed": _number(data.get("speed")),
        "eta": _number(data.get("eta")),
        "postprocessor": _text(data.get("postprocessor")),
        "postprocessor_key": _text(data.get("postprocessor_key")),
        "info_dict": _info_payload(data.get("info_dict")),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _emit(payload: dict[str, Any]) -> None:
    PROTOCOL_STDOUT.write(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    PROTOCOL_STDOUT.flush()


def _read_request() -> dict[str, Any]:
    raw = sys.stdin.readline()
    if not raw:
        raise ValueError("Brak danych wejściowych procesu pobierania.")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Niepoprawny format danych wejściowych procesu pobierania.")
    return payload


class WorkerMediaService(MediaService):
    """Silence yt-dlp console progress; structured hooks carry progress to the parent."""

    def effective_download_options(
        self,
        url: str,
        download_type: str,
        format_id: str | None = None,
        download_options: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        validated_url, options = super().effective_download_options(
            url,
            download_type,
            format_id,
            download_options,
        )
        options["quiet"] = True
        options["no_warnings"] = True
        options["noprogress"] = True
        return validated_url, options


def main() -> int:
    try:
        request = _read_request()
        download_dir = Path(str(request["download_dir"])).resolve()
        media_service = WorkerMediaService(download_dir)

        def progress_hook(data: dict[str, Any]) -> None:
            _emit({"event": "progress", "data": _hook_payload(data)})

        def postprocessor_hook(data: dict[str, Any]) -> None:
            _emit({"event": "postprocessor", "data": _hook_payload(data)})

        with redirect_stdout(sys.stderr):
            paths = media_service.download(
                url=str(request["url"]),
                download_type=str(request["download_type"]),
                format_id=(
                    str(request["format_id"])
                    if request.get("format_id") not in (None, "")
                    else None
                ),
                download_options=(
                    dict(request["download_options"])
                    if isinstance(request.get("download_options"), dict)
                    else {}
                ),
                progress_hook=progress_hook,
                postprocessor_hook=postprocessor_hook,
            )
        _emit({"event": "completed", "paths": [str(path) for path in paths]})
        return 0
    except KeyboardInterrupt:
        return 130
    except (KeyError, TypeError, ValueError, MediaServiceError) as error:
        _emit({"event": "error", "message": str(error)})
        return 1
    except Exception as error:
        _emit({"event": "error", "message": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
