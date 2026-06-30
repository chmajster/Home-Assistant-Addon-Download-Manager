"""Compatibility module for the HTML blueprint.

Importing this module registers all route modules while preserving the public
``web_bp`` blueprint and helper imports used by tests.
"""

from __future__ import annotations

from .shared import socket, subprocess, web_bp, _automatic_download_type
from . import diagnostics as _diagnostics_routes  # noqa: F401
from . import downloads as _downloads_routes  # noqa: F401
from . import history as _history_routes  # noqa: F401
from . import jobs as _jobs_routes  # noqa: F401

__all__ = ["web_bp", "_automatic_download_type", "socket", "subprocess"]
