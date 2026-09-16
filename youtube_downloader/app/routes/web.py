"""Compatibility module for the HTML blueprint.

Importing this module registers all route modules while preserving the public
``web_bp`` blueprint and helper imports used by tests.
"""

from __future__ import annotations

from importlib import import_module

from . import shared as _shared
from .request_parsing import _bulk_url_candidates
from .shared import _automatic_download_type, socket, subprocess, web_bp

# Keep the shared compatibility layer and route modules on the same
# newline-only URL parser. Commas and semicolons may be valid URL characters.
_shared._bulk_url_candidates = _bulk_url_candidates

for _route_module in ("diagnostics", "downloads", "history", "jobs", "system"):
    import_module(f"{__package__}.{_route_module}")

__all__ = ["web_bp", "_automatic_download_type", "socket", "subprocess"]
