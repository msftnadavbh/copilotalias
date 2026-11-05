"""Stdlib-only builder checks; all scratch data stays under the build root."""

import errno
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location("package_builder_tests", ROOT / "build_package.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
EXPECTED = {
    "LICENSE",
    "requirements-test.txt",
    "README.md", "SKILL.md", "scripts/prepare_agent.py", "tests/test_prepare_agent.py", "tests/model_cases.json",
    "fixtures/claude-agents/client-test-author.md", "fixtures/claude-agents/fable-alias.md",
    "fixtures/claude-agents/haiku-alias.md", "fixtures/claude-agents/opus-alias.md",
    "fixtures/claude-agents/opus-pinned.md", "fixtures/claude-agents/smc-scanner.md",
    "fixtures/claude-agents/sonnet-alias.md", "fixtures/claude-agents/sonnet-pinned.md",
}


class BuilderChecks(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix=".build-test-", dir=ROOT)
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.payload = self.root / "prepare-claude-agent"
        for name in EXPECTED:
            target = self.payload / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / "prepare-claude-agent" / name).read_bytes())

    def test_build_entries_bytes_manifest_and_fixed_metadata(self):
        self.assertEqual(set(BUILDER.PAYLOAD_PATHS), EXPECTED)
        digest = BUILDER.build(self.root)
        archive_path = self.root / "prepare-claude-agent.zip"
        self.assertEqual(hashlib.sha256(archive_path.read_bytes()).hexdigest(), digest)
        self.assertEqual((self.root / "prepare-claude-agent.zip.sha256").read_text(),
                         f"{digest}  prepare-claude-agent.zip\n")
        with zipfile.ZipFile(archive_path) as archive:
            self.assertEqual(archive.namelist(), ["prepare-claude-agent/" + name for name in sorted(EXPECTED)])
            manifest = []
            for entry in archive.infolist():
                self.assertEqual(entry.date_time, (2020, 1, 1, 0, 0, 0))
                self.assertEqual(entry.create_system, 3)
                self.assertEqual(entry.external_attr, (stat.S_IFREG | 0o644) << 16)
                self.assertEqual(entry.compress_type, zipfile.ZIP_STORED)
                data = archive.read(entry)
                self.assertEqual(data, (self.root / entry.filename).read_bytes())
                manifest.append(f"{hashlib.sha256(data).hexdigest()}  {entry.filename}\n")
        self.assertEqual((self.root / "payload-manifest.sha256").read_bytes(), "".join(manifest).encode())

    def test_unexpected_files_and_directories_reject_before_outputs(self):
        for name, is_dir in ((".hidden-config", False), ("staged-user.md", False), ("extra", True)):
            path = self.payload / name
            path.mkdir() if is_dir else path.write_bytes(b"not a release input")
            try:
                with self.assertRaisesRegex(ValueError, "unexpected payload"):
                    BUILDER.build(self.root)
                self.assertFalse((self.root / "prepare-claude-agent.zip").exists())
            finally:
                path.rmdir() if is_dir else path.unlink()

    def test_missing_payload_rejects(self):
        (self.payload / "README.md").unlink()
        with self.assertRaisesRegex(ValueError, "missing payload"):
            BUILDER.build(self.root)

    def test_hardlinked_output_cannot_overwrite_other_file(self):
        original = self.root / "keep.txt"
        original.write_bytes(b"do not overwrite")
        try:
            os.link(original, self.root / "prepare-claude-agent.zip")
        except (OSError, NotImplementedError) as error:
            if (isinstance(error, NotImplementedError)
                    or error.errno in (errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.ENOSYS)
                    or getattr(error, "winerror", None) == 1314):
                self.skipTest(f"OS privilege/filesystem cannot create a hard link: {error}")
            raise
        with self.assertRaisesRegex(ValueError, "single-link"):
            BUILDER.build(self.root)
        self.assertEqual(original.read_bytes(), b"do not overwrite")

    def test_unsafe_archive_spellings(self):
        for name in ("../escape", "/absolute", "C:/drive", "a\\b", "CON.extra.md",
                     "com9.md", "a/../b", "a//b", "trailing.", "a/PRN.md"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    BUILDER.check_entry(name)

    def test_synthetic_reparse_guard_not_windows_certification(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        with mock.patch.object(Path, "lstat", return_value=info):
            with self.assertRaisesRegex(ValueError, "reparse"):
                BUILDER.checked_stat(self.root)


if __name__ == "__main__":
    unittest.main()
