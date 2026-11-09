"""Catalog boundary tests; no real SDK, credentials, or runtime process."""

import asyncio
import contextlib
import errno
import io
import logging
import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


SCRIPT = Path(__file__).absolute().parent.parent / "scripts" / "copilot_catalog.py"
SPEC = importlib.util.spec_from_file_location("catalog_under_test", SCRIPT)
CATALOG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CATALOG)


def model(identifier="claude-sonnet-5.5", policy="enabled"):
    return SimpleNamespace(id=identifier, policy=None if policy is None else SimpleNamespace(state=policy))


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".test-", dir=SCRIPT.parent.parent)
        self.addCleanup(self.temp.cleanup)
        self.cli = Path(self.temp.name) / ("copilot.exe" if os.name == "nt" else "copilot")
        self.cli.write_bytes(b"synthetic executable; never invoked")
        self.cli.chmod(0o700)
        self.instances = []
        self.connections = []
        self.models = [model()]
        self.error = None
        self.hang = None
        self.force_error = False
        owner = self

        class FakeClient:
            def __init__(self, **options):
                self.options = options
                self.calls = []
                owner.instances.append(self)

            async def step(self, name):
                self.calls.append(name)
                if owner.hang == name:
                    await asyncio.Event().wait()
                if owner.error == name:
                    raise RuntimeError("SECRET SDK diagnostic")

            async def start(self):
                await self.step("start")

            async def list_models(self):
                await self.step("list")
                return owner.models

            async def stop(self):
                await self.step("stop")

            async def force_stop(self):
                await self.step("force")
                if owner.force_error:
                    raise RuntimeError("SECRET cleanup diagnostic")

        class FakeConnection:
            @staticmethod
            def for_stdio(**options):
                owner.connections.append(options)
                return options

        self.sdk = SimpleNamespace(CopilotClient=FakeClient, RuntimeConnection=FakeConnection)
        self.sdk_patch = mock.patch.dict(sys.modules, {"copilot": self.sdk})
        self.sdk_patch.start()
        self.addCleanup(self.sdk_patch.stop)

    def discover(self):
        return CATALOG.discover_models(str(self.cli))

    def reject_path(self, path):
        real_import = __import__

        def guarded_import(name, *args, **kwargs):
            if name == "copilot":
                raise AssertionError("rejected paths must not import the SDK")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=guarded_import) as imports:
            with self.assertRaises(ValueError) as caught:
                CATALOG.discover_models(str(path))
        self.assertEqual(str(caught.exception),
                         "choose an approved absolute local executable Copilot path (.exe on Windows)")
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertFalse(any(call.args[0] == "copilot" for call in imports.call_args_list))
        self.assertEqual(self.instances, [])
        self.assertEqual(self.connections, [])

    def link_or_skip(self, link, destination, **options):
        try:
            link.symlink_to(destination, **options)
        except (OSError, NotImplementedError) as error:
            if (isinstance(error, NotImplementedError)
                    or error.errno in (errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.ENOSYS)
                    or getattr(error, "winerror", None) == 1314):
                self.skipTest(f"OS privilege/filesystem cannot create a symlink: {error}")
            raise

    def test_fresh_client_filters_policy_and_cleans_temporary_directory(self):
        self.models = [model(), model("disabled", "disabled"), model("unset", "unconfigured"), model("unknown", None)]
        self.assertEqual(self.discover(), ["claude-sonnet-5.5"])
        self.models = [model("claude-sonnet-6")]
        self.assertEqual(self.discover(), ["claude-sonnet-6"])
        self.assertEqual(len(self.instances), 2)
        for client in self.instances:
            self.assertEqual(client.calls, ["start", "list", "stop"])
            self.assertEqual(client.options["connection"]["path"], str(self.cli))
            directory = client.options["working_directory"]
            self.assertEqual(client.options["connection"]["args"], (
                "--no-auto-update", "--no-custom-instructions", "--disable-builtin-mcps",
                "--no-bash-env", "--no-remote", "--log-dir", directory,
            ))
            self.assertEqual(client.options["log_level"], "none")
            self.assertEqual(client.options["env"], {**os.environ, "COPILOT_GITHUB_TELEMETRY_DISABLED": "true"})
            self.assertFalse(Path(directory).exists())

    def test_fixture_setup_works_with_symlinked_default_temp_directory(self):
        actual = Path(self.temp.name) / "system-temp"
        actual.mkdir()
        alias = Path(self.temp.name) / "system temp alias"
        self.link_or_skip(alias, actual, target_is_directory=True)
        fixture = CatalogTests("test_fresh_client_filters_policy_and_cleans_temporary_directory")
        try:
            with mock.patch.object(tempfile, "tempdir", str(alias)):
                fixture.setUp()
                fixture.test_fresh_client_filters_policy_and_cleans_temporary_directory()
                self.assertEqual(Path(fixture.temp.name).parent, SCRIPT.parent.parent)
        finally:
            fixture.doCleanups()

    def test_rejects_bad_paths_before_loading_sdk(self):
        for path in ("copilot", str(self.cli.parent), str(self.cli) + "-missing",
                     r"\\server\share\copilot.exe", r"\\?\C:\copilot.exe", r"\\.\CON",
                     r"\rooted\copilot.exe", "//server/share/copilot.exe", "C:copilot.exe", "C:"):
            with self.subTest(path=path):
                self.reject_path(path)
        if os.name != "nt":
            self.cli.chmod(0o600)
            self.reject_path(self.cli)
        else:
            other = self.cli.with_suffix(".cmd")
            other.write_bytes(self.cli.read_bytes())
            self.reject_path(other)

    def test_real_leaf_and_ancestor_symlinks_rejected_before_sdk(self):
        leaf = self.cli.with_name("linked" + self.cli.suffix)
        self.link_or_skip(leaf, self.cli)
        actual = self.cli.parent / "actual"
        actual.mkdir()
        executable = actual / self.cli.name
        executable.write_bytes(self.cli.read_bytes())
        executable.chmod(0o700)
        ancestor = self.cli.parent / "linked-directory"
        self.link_or_skip(ancestor, actual, target_is_directory=True)
        for path in (leaf, ancestor / self.cli.name, ancestor / ".." / self.cli.name):
            with self.subTest(path=path), mock.patch.object(CATALOG.os, "access", return_value=True) as access:
                self.reject_path(path)
                access.assert_not_called()

    def test_synthetic_guards_stop_root_to_leaf_before_access_or_sdk(self):
        scan = [*reversed(self.cli.parents), self.cli]
        for kind in ("symlink", "reparse", "wrong-type"):
            for index, rejected in enumerate(scan):
                visited = []

                def fake_lstat(path):
                    visited.append(path)
                    self.assertLessEqual(len(visited), index + 1, "must not inspect descendants")
                    mode = stat.S_IFREG if path == self.cli else stat.S_IFDIR
                    attributes = 0
                    if path == rejected:
                        if kind == "symlink":
                            mode = stat.S_IFLNK
                        elif kind == "reparse":
                            attributes = stat.FILE_ATTRIBUTE_REPARSE_POINT
                        else:
                            mode = stat.S_IFDIR if path == self.cli else stat.S_IFREG
                    return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)

                with self.subTest(kind=kind, rejected=rejected), \
                        mock.patch.object(Path, "lstat", fake_lstat), \
                        mock.patch.object(CATALOG.os, "access", return_value=True) as access:
                    self.reject_path(self.cli)
                    self.assertEqual(visited, scan[:index + 1])
                    access.assert_not_called()

    def test_traversal_and_ambiguous_components_rejected_without_normalizing(self):
        for name in ("..", "trailing.", "trailing ", "CON.exe", "com9.extra.exe", "LPT1.exe",
                     "file:stream", "wild?card", "wild*card", "pipe|name", 'quote"name', "angle<name", "angle>name"):
            for path in (self.cli.parent / name, self.cli.parent / name / self.cli.name):
                scan = [*reversed(path.parents), path]
                bad_index = next(index for index, component in enumerate(scan) if component.name == name)
                visited = []

                def fake_lstat(component):
                    visited.append(component)
                    return SimpleNamespace(st_mode=stat.S_IFREG if component == path else stat.S_IFDIR)

                with self.subTest(path=path), mock.patch.object(Path, "lstat", fake_lstat), \
                        mock.patch.object(CATALOG.os, "access", return_value=True) as access:
                    self.reject_path(path)
                    self.assertEqual(visited, scan[:bad_index])
                    access.assert_not_called()

    def test_filesystem_errors_do_not_leak_paths_or_control_characters(self):
        for operation in (mock.patch.object(Path, "lstat"), mock.patch.object(CATALOG.os, "access")):
            with operation as check:
                check.side_effect = OSError("SECRET filesystem diagnostic\n\x1b[31m", str(self.cli))
                self.reject_path(self.cli)
                check.assert_called_once()

    def test_missing_sdk_has_actionable_sanitized_error(self):
        with mock.patch.dict(sys.modules, {"copilot": None}), self.assertRaisesRegex(ValueError, "approved.*github-copilot-sdk"):
            self.discover()

    def test_rejects_empty_malformed_duplicate_and_unknown_policy_catalogs(self):
        bad = ([], None, [model(policy="disabled")], [model(), model()], [model("bad\nmodel")],
               [SimpleNamespace(policy=None)], [model(policy="new-policy-state")], [model(123)])
        for models in bad:
            self.models = models
            with self.subTest(models=models), self.assertRaises(ValueError):
                self.discover()
            self.assertEqual(self.instances[-1].calls[-1], "stop")

    def test_start_and_list_failures_are_sanitized_and_stopped(self):
        for name in ("start", "list"):
            self.error = name
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "catalog discovery failed") as caught:
                self.discover()
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertEqual(self.instances[-1].calls[-1], "stop")

    def test_discovery_timeout_stops_runtime(self):
        for name in ("start", "list"):
            self.hang = name
            with self.subTest(name=name), mock.patch.object(CATALOG, "DISCOVERY_TIMEOUT", 0.01):
                with self.assertRaisesRegex(ValueError, "catalog discovery timed out"):
                    self.discover()
                self.assertEqual(self.instances[-1].calls[-1], "stop")

    def test_stop_error_or_timeout_uses_force_stop(self):
        for mode in ("error", "hang"):
            self.error = "stop" if mode == "error" else None
            self.hang = "stop" if mode == "hang" else None
            with self.subTest(mode=mode), mock.patch.object(CATALOG, "CLEANUP_TIMEOUT", 0.01):
                self.assertEqual(self.discover(), ["claude-sonnet-5.5"])
            self.assertEqual(self.instances[-1].calls[-2:], ["stop", "force"])

    def test_sdk_logged_startup_failure_is_suppressed_and_logging_restored(self):
        stderr = io.StringIO()
        logger = logging.getLogger('copilot.client')
        handler = logging.StreamHandler(stderr)
        before = (logger.handlers[:], logger.propagate, logger.disabled, logger.level)
        logger.handlers = [handler]
        logger.propagate = False
        logger.disabled = False
        logger.setLevel(logging.WARNING)

        async def fail_start():
            try:
                raise RuntimeError('SECRET startup diagnostic')
            except RuntimeError:
                logger.warning('SDK startup failed', exc_info=True)
                raise

        try:
            with mock.patch.object(self.sdk.CopilotClient, 'start', side_effect=fail_start), \
                    contextlib.redirect_stderr(stderr):
                with self.assertRaisesRegex(ValueError, 'catalog discovery failed'):
                    self.discover()
            self.assertEqual(stderr.getvalue(), '')
            self.assertEqual(logger.handlers, [handler])
            self.assertFalse(logger.propagate)
            self.assertFalse(logger.disabled)
            self.assertEqual(logger.level, logging.WARNING)
            logger.warning('caller logging restored')
            self.assertIn('caller logging restored', stderr.getvalue())
        finally:
            logger.handlers, logger.propagate, logger.disabled, logger.level = before
            handler.close()

    def test_constructor_errors_are_sanitized(self):
        with mock.patch.object(self.sdk, "CopilotClient", side_effect=ValueError("SECRET constructor diagnostic")):
            with self.assertRaisesRegex(ValueError, "catalog discovery failed") as caught:
                self.discover()
        self.assertNotIn("SECRET", str(caught.exception))

    def test_failed_force_stop_refuses_success(self):
        self.error = "stop"
        self.force_error = True
        with self.assertRaisesRegex(ValueError, "cleanup failed") as caught:
            self.discover()
        self.assertNotIn("SECRET", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
