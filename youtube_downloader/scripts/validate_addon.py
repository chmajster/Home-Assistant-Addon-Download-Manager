"""Validate the Home Assistant add-on manifest and translations."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    required = {"name", "slug", "version", "arch", "startup", "boot", "options", "schema"}
    missing = sorted(required - set(config or {}))
    if missing:
        raise SystemExit("Missing add-on keys: " + ", ".join(missing))
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", str(config["version"])):
        raise SystemExit("config.yaml contains an invalid semantic version")
    if not set(config["arch"]).issubset({"amd64", "aarch64", "armhf", "armv7", "i386"}):
        raise SystemExit("config.yaml contains an unsupported architecture")
    if set(config["options"]) != set(config["schema"]):
        missing_schema = sorted(set(config["options"]) - set(config["schema"]))
        extra_schema = sorted(set(config["schema"]) - set(config["options"]))
        raise SystemExit(f"options/schema mismatch: missing={missing_schema}, extra={extra_schema}")
    for translation in (root / "translations").glob("*.yaml"):
        payload = yaml.safe_load(translation.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SystemExit(f"Invalid translation mapping: {translation}")
    print(f"Validated add-on {config['slug']} {config['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
