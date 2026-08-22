"""Regression tests for storage free-space reservation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.error_messages import NO_DISK_SPACE
from app.services.storage import GIB, StorageError, StorageManager


class StorageReserveTestCase(unittest.TestCase):
    def test_startup_validation_does_not_require_reserved_space(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = StorageManager(
                {"local": Path(temp_dir)},
                "local",
                min_free_space_bytes=2 * GIB,
            )
            with patch(
                "app.services.storage.shutil.disk_usage",
                return_value=SimpleNamespace(total=GIB, used=GIB, free=0),
            ):
                target = manager.validate("local")
            self.assertEqual(target.name, "local")

    def test_download_capacity_blocks_below_reserved_space(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = StorageManager(
                {"local": Path(temp_dir)},
                "local",
                min_free_space_bytes=2 * GIB,
            )
            with patch(
                "app.services.storage.shutil.disk_usage",
                return_value=SimpleNamespace(total=10 * GIB, used=9 * GIB, free=GIB),
            ):
                with self.assertRaises(StorageError) as raised:
                    manager.ensure_capacity("local")
            self.assertEqual(raised.exception.error_code, NO_DISK_SPACE)

    def test_download_capacity_allows_space_above_reserve(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = StorageManager(
                {"local": Path(temp_dir)},
                "local",
                min_free_space_bytes=GIB,
            )
            with patch(
                "app.services.storage.shutil.disk_usage",
                return_value=SimpleNamespace(total=10 * GIB, used=5 * GIB, free=5 * GIB),
            ):
                target = manager.ensure_capacity("local")
            self.assertEqual(target.name, "local")


if __name__ == "__main__":
    unittest.main()
