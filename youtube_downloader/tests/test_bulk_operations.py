"""Regression coverage for multi-file operations (no network or downloader needed)."""

from __future__ import annotations

import ast
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bulk_operations_under_test", ROOT / "app/services/bulk_operations.py"
)
assert SPEC is not None and SPEC.loader is not None
bulk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bulk)


class BulkOperationsTestCase(unittest.TestCase):
    def test_includes_primary_and_all_outputs_once(self):
        job = SimpleNamespace(output_files=["a.mp4", "b.mp4", "a.mp4"], output_file="c.mp4")
        self.assertEqual(bulk.output_filenames(job), ["a.mp4", "b.mp4", "c.mp4"])

    def test_ignores_corrupt_output_values(self):
        job = SimpleNamespace(output_files=[None, "", 8, "a.mp4"], output_file="a.mp4")
        self.assertEqual(bulk.output_filenames(job), ["a.mp4"])
        self.assertEqual(bulk.output_filenames(SimpleNamespace(output_files="bad")), [])

    def test_handles_legacy_primary_only(self):
        self.assertEqual(bulk.output_filenames(SimpleNamespace(output_file="old.mp4")), ["old.mp4"])

    def test_repeat_preserves_nested_options_without_sharing(self):
        job = SimpleNamespace(download_options={"subtitles": ["pl"]}, storage_name="nfs")
        options = bulk.repeat_download_options(job)
        self.assertEqual(options, {"subtitles": ["pl"], "storage_name": "nfs"})
        options["subtitles"].append("en")
        self.assertEqual(job.download_options, {"subtitles": ["pl"]})

    def test_repeat_preserves_explicit_storage(self):
        job = SimpleNamespace(download_options={"storage_name": "media"}, storage_name="local")
        self.assertEqual(bulk.repeat_download_options(job)["storage_name"], "media")

    def test_repeat_defaults_legacy_storage(self):
        self.assertEqual(bulk.repeat_download_options(SimpleNamespace()), {"storage_name": "local"})

    def test_archive_rejects_unsafe_names(self):
        for value in ("", ".", "/etc/passwd", "../x", "x/../y", "C:\\x", "x\x00.mp4"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bulk.archive_member_name(value, set())

    def test_archive_keeps_unicode_and_nested_directories(self):
        self.assertEqual(bulk.archive_member_name("Muzyka\\Łódź.mp4", set()), "Muzyka/Łódź.mp4")

    def test_archive_disambiguates_case_insensitive_collisions(self):
        used = set()
        self.assertEqual(bulk.archive_member_name("Film.mp4", used), "Film.mp4")
        self.assertEqual(bulk.archive_member_name("film.mp4", used), "film-2.mp4")
        self.assertEqual(bulk.archive_member_name("film.mp4", used), "film-3.mp4")

    def test_zip_contains_all_data_and_can_be_removed_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "film.mp4"
            source.write_bytes(b"media-fixture")
            archive = bulk.create_download_archive([("a.mp4", source), ("b.mp4", source)])
            try:
                with zipfile.ZipFile(archive) as handle:
                    self.assertEqual(handle.namelist(), ["a.mp4", "b.mp4"])
                    self.assertEqual(handle.read("b.mp4"), b"media-fixture")
            finally:
                bulk.remove_archive(archive)
                bulk.remove_archive(archive)
            self.assertFalse(archive.exists())

    def test_failed_zip_creation_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(tempfile, "tempdir", directory), self.assertRaises(FileNotFoundError):
                bulk.create_download_archive([("missing.mp4", Path(directory) / "missing")])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_bad_member_name_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(tempfile, "tempdir", directory), self.assertRaises(ValueError):
                bulk.create_download_archive([("../unsafe", Path(directory) / "missing")])
            self.assertEqual(list(Path(directory).iterdir()), [])


class BulkRouteTestCase(unittest.TestCase):
    """Execute the production handler with isolated request/service doubles."""

    def setUp(self):
        source = (ROOT / "app/routes/jobs.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body if getattr(node, "name", "") == "bulk_history_jobs"
        )
        function.decorator_list = []
        self.manager = Mock()
        self.files = Mock()
        self.form = Mock()
        self.form.get.side_effect = lambda key: {
            "action": self.action,
            "return_to": "jobs",
        }.get(key)
        self.form.getlist.return_value = ["one", "two"]
        self.jobs = [
            SimpleNamespace(
                job_id=name,
                status="completed",
                output_files=["a.mp4", "b.mp4"],
                output_file="a.mp4",
                url="https://example.com/video",
                is_live=False,
                download_type="best",
                format_id=None,
                duration=50,
                title="Title",
                source_id="source",
                download_options={"subtitles": ["pl"]},
                storage_name="nfs",
            )
            for name in ("one", "two")
        ]
        self.manager.list_jobs.return_value = self.jobs
        self.namespace = {
            "request": SimpleNamespace(form=self.form),
            "_valid_form": lambda: True,
            "_job_manager": lambda: self.manager,
            "_file_service": lambda: self.files,
            "_ensure_ytdlp_recent": Mock(),
            "flash": Mock(),
            "LOGGER": Mock(),
            "redirect": lambda path: path,
            "ingress_url": lambda endpoint: endpoint,
            "_flash_bulk_history_result": Mock(),
            "_flash_deleted_jobs": Mock(),
            "output_filenames": bulk.output_filenames,
            "repeat_download_options": bulk.repeat_download_options,
            "MediaServiceError": RuntimeError,
            "UnsafeFilenameError": ValueError,
            "Path": Path,
        }
        code = compile(ast.Module(body=[function], type_ignores=[]), "jobs.py", "exec")
        exec(code, self.namespace)

    def run_action(self, action):
        self.action = action
        return self.namespace["bulk_history_jobs"]()

    def test_delete_visits_all_outputs_and_deduplicates_across_jobs(self):
        self.run_action("delete_files")
        self.assertEqual(
            [call.args[0] for call in self.files.delete_file.call_args_list], ["a.mp4", "b.mp4"]
        )
        self.namespace["_flash_bulk_history_result"].assert_called_once_with("delete_files", 2, 0)

    def test_permission_error_does_not_abort_remaining_files(self):
        self.files.delete_file.side_effect = [PermissionError("read-only"), None]
        self.run_action("delete_files")
        self.namespace["_flash_bulk_history_result"].assert_called_once_with("delete_files", 1, 1)

    def test_repeat_keeps_source_storage_and_options(self):
        self.run_action("repeat")
        kwargs = self.manager.start_download.call_args.kwargs
        self.assertEqual(kwargs["source_id"], "source")
        self.assertEqual(kwargs["download_options"], {"subtitles": ["pl"], "storage_name": "nfs"})

    def test_non_completed_jobs_are_not_changed(self):
        for job in self.jobs:
            job.status = "downloading"
        self.run_action("delete_files")
        self.files.delete_file.assert_not_called()

    def test_invalid_csrf_does_not_touch_services(self):
        self.namespace["_valid_form"] = lambda: False
        self.run_action("delete_files")
        self.manager.list_jobs.assert_not_called()
        self.files.delete_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
