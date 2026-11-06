"""Catalog boundary tests; no real SDK, credentials, or runtime process."""

import asyncio
import contextlib
import io
import logging
import importlib.util
import os
from pathlib import Path
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
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cli = Path(self.temp.name) / ("copilot.exe" if os.name == "nt" else "copilot")
        self.cli.write_bytes(b"synthetic executable; never invoked")
        self.cli.chmod(0o700)
        self.instances = []
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
                return options

        self.sdk = SimpleNamespace(CopilotClient=FakeClient, RuntimeConnection=FakeConnection)
        self.sdk_patch = mock.patch.dict(sys.modules, {"copilot": self.sdk})
        self.sdk_patch.start()
        self.addCleanup(self.sdk_patch.stop)

    def discover(self):
        return CATALOG.discover_models(str(self.cli))

    def test_fresh_client_filters_policy_and_cleans_temporary_directory(self):
        self.models = [model(), model("disabled", "disabled"), model("unset", "unconfigured"), model("unknown", None)]
        self.assertEqual(self.discover(), ["claude-sonnet-5.5"])
        self.models = [model("claude-sonnet-6")]
        self.assertEqual(self.discover(), ["claude-sonnet-6"])
        self.assertEqual(len(self.instances), 2)
        for client in self.instances:
            self.assertEqual(client.calls, ["start", "list", "stop"])
            self.assertEqual(client.options["connection"]["path"], str(self.cli))
            self.assertIn("--no-auto-update", client.options["connection"]["args"])
            self.assertIn("--no-custom-instructions", client.options["connection"]["args"])
            self.assertEqual(client.options["env"]["COPILOT_GITHUB_TELEMETRY_DISABLED"], "true")
            self.assertFalse(Path(client.options["working_directory"]).exists())

    def test_rejects_bad_paths_before_loading_sdk(self):
        for path in ("copilot", str(self.cli.parent), str(self.cli) + "-missing", "\\\\server\\share\\copilot.exe"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "absolute.*executable"):
                CATALOG.discover_models(path)
        if os.name != "nt":
            self.cli.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "absolute.*executable"):
                self.discover()
        self.assertEqual(self.instances, [])

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
