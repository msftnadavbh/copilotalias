"""Subprocess converter checks with a mocked catalog I/O boundary; no live agents."""

import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import yaml


ROOT = Path(__file__).absolute().parent.parent
FIXTURES = ROOT / "fixtures" / "claude-agents"
SCRIPT = ROOT / "scripts" / "prepare_agent.py"
VALID = b"name: synthetic\ndescription: Sanitized fixture.\nmodel: sonnet\ntools: []\n"
SPEC = importlib.util.spec_from_file_location("prepare_guard_tests", SCRIPT)
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)
CATALOG = json.loads((ROOT / "tests" / "model_cases.json").read_text())["test_catalog"]
# Patch only metadata discovery in the subprocess; execute real parsing and main().
TEST_DRIVER = """
import json, runpy, sys
from unittest import mock
catalog = json.loads(sys.argv.pop(1))
sys.argv = sys.argv[1:]
module = runpy.run_path(sys.argv[0])
with mock.patch.dict(module['main'].__globals__, discover_models=lambda path: catalog):
    raise SystemExit(module['main']())
"""


def snapshot():
    return {str(path.relative_to(ROOT)): path.read_bytes() for path in ROOT.rglob("*") if path.is_file()}


def body(data):
    lines = data.splitlines(keepends=True)
    end = next(i for i in range(1, len(lines)) if lines[i] in (b"---\n", b"---\r\n", b"---"))
    return b"".join(lines[end + 1:])


class ConversionE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = snapshot()
        cls.before_dirs = {path for path in ROOT.rglob("*") if path.is_dir()}

    @classmethod
    def tearDownClass(cls):
        if snapshot() != cls.before:
            raise AssertionError("source changed or temporary/output artifacts remain")
        if {path for path in ROOT.rglob("*") if path.is_dir()} != cls.before_dirs:
            raise AssertionError("temporary/output directories remain")
        for path in ROOT.rglob("*"):
            if path.name in ("__pycache__", ".claude") or path.name.endswith(".agent.md"):
                raise AssertionError(f"unexpected runtime artifact: {path}")
        for directory in (ROOT / ".github" / "agents", ROOT / ".claude" / "agents"):
            if directory.exists():
                raise AssertionError(f"active agent directory: {directory}")

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix=".test-", dir=ROOT)
        self.addCleanup(self.scratch.cleanup)
        self.cwd = Path(self.scratch.name) / "arbitrary cwd with spaces"
        self.cwd.mkdir()
        self.fixture = FIXTURES / ("case-" + Path(self.scratch.name).name.lstrip(".") + ".md")
        self.addCleanup(self.fixture.unlink, missing_ok=True)

    def invoke(self, fixture, target="cli", extra=()):
        source = FIXTURES / fixture
        before = None
        try:
            PREPARE.check_component(fixture)
            if source.parent == FIXTURES:
                info = PREPARE.checked_stat(source)
                if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    before = source.read_bytes()
        except (OSError, ValueError):
            pass
        env = dict(os.environ, TMPDIR=self.scratch.name,
                   TMP=self.scratch.name, TEMP=self.scratch.name)
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-X", "utf8", "-c", TEST_DRIVER, json.dumps(CATALOG),
             str(SCRIPT), fixture, "--target", target, "--copilot-path", "/approved/copilot", *extra],
            cwd=self.cwd, env=env, capture_output=True, timeout=10, shell=False,
        )
        if before is not None:
            self.assertEqual(source.read_bytes(), before, "source bytes changed")
        return result

    def invoke_main(self, target, tty=False, newline=None):
        before = self.fixture.read_bytes()
        stdout = SimpleNamespace(buffer=io.BytesIO(), isatty=mock.Mock(return_value=tty))
        raw_stderr = io.BytesIO()
        with io.TextIOWrapper(raw_stderr, encoding="utf-8", newline=newline) as stderr:
            with mock.patch.multiple(PREPARE.sys, stdout=stdout, stderr=stderr,
                                     argv=[str(SCRIPT), self.fixture.name, "--target", target,
                                           "--copilot-path", "/approved/copilot"]):
                with mock.patch.object(PREPARE, "discover_models", return_value=CATALOG):
                    code = PREPARE.main()
            stderr.flush()
            diagnostic = raw_stderr.getvalue()
        stdout.isatty.assert_not_called()
        self.assertEqual(self.fixture.read_bytes(), before)
        return SimpleNamespace(returncode=code, stdout=stdout.buffer.getvalue(), stderr=diagnostic)

    def link_or_skip(self, create, *args, **kwargs):
        try:
            create(*args, **kwargs)
        except (OSError, NotImplementedError) as error:
            if (isinstance(error, NotImplementedError)
                    or error.errno in (errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.ENOSYS)
                    or getattr(error, "winerror", None) == 1314):
                self.skipTest(f"OS privilege/filesystem cannot create this link: {error}")
            raise

    def reject(self, data=None, fixture=None, target="cli", extra=(), expected_code=1):
        if data is not None:
            self.fixture.write_bytes(data)
        result = self.invoke(fixture or self.fixture.name, target, extra)
        self.assertEqual(result.returncode, expected_code, result.stderr)
        self.assertEqual(result.stdout, b"", "failure leaked a partial preview")
        self.assertTrue(result.stderr)
        if expected_code == 1:
            self.assertTrue(result.stderr.startswith(b"preview rejected: "), result.stderr)
        return result

    def test_cli_fixture_mappings_and_candidate_fields(self):
        for fixture, model in (
            ("sonnet-alias.md", "claude-sonnet-5.5"),
            ("opus-alias.md", "claude-opus-5.5"),
            ("haiku-alias.md", "claude-haiku-5.5"),
            ("fable-alias.md", "claude-fable-5.1"),
            ("sonnet-pinned.md", "claude-sonnet-5.5"),
            ("opus-pinned.md", "claude-opus-5.5"),
        ):
            with self.subTest(fixture=fixture):
                original = (FIXTURES / fixture).read_bytes()
                result = self.invoke(fixture)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, b"")
                fields = yaml.safe_load(result.stdout.split(b"---\n")[1])
                source_fields = yaml.safe_load(original.split(b"---\n")[1])
                self.assertEqual(fields, {
                    "name": source_fields["name"], "description": source_fields["description"],
                    "model": model, "model-policy": "required", "strict-tools-list": True, "tools": [],
                })
                self.assertEqual(body(result.stdout), body(original))

    def test_cli_dotted_ids_are_idempotent(self):
        for model in (b"claude-sonnet-5.5", b"claude-opus-5.5"):
            with self.subTest(model=model):
                self.fixture.write_bytes(b"---\n" + VALID.replace(b"sonnet", model) + b"---\nBody\n")
                result = self.invoke(self.fixture.name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(b"model: " + model + b"\n", result.stdout)

    def test_vscode_aliases_pass_through_entire_source(self):
        for fixture in ("sonnet-alias.md", "opus-alias.md", "haiku-alias.md"):
            with self.subTest(fixture=fixture):
                result = self.invoke(fixture, "vscode")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, b"")
                self.assertEqual(result.stdout, (FIXTURES / fixture).read_bytes())

    def test_vscode_rejects_all_explicit_versions(self):
        for fixture in ("sonnet-pinned.md", "opus-pinned.md"):
            self.reject(fixture=fixture, target="vscode")
        for model in (b"claude-sonnet-5.5", b"claude-opus-5.5"):
            self.reject(b"---\n" + VALID.replace(b"sonnet", model) + b"---\n", target="vscode")

    def test_preserves_accepted_utf8_body_bytes_and_crlf(self):
        original = (b"---\r\n" + VALID.replace(b"\n", b"\r\n") + b"---\r\n"
                    + "# Body\r\n\tEuro € emoji 😀\r\n---\nno final newline".encode("utf-8"))
        self.fixture.write_bytes(original)
        for target in ("cli", "vscode"):
            with self.subTest(target=target):
                result = self.invoke(self.fixture.name, target)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(body(result.stdout), body(original))
                if target == "vscode":
                    self.assertEqual(result.stdout, original)
                else:
                    self.assertTrue(result.stdout.startswith(b"---\r\nname:"))

    def test_repeat_is_deterministic_for_both_targets(self):
        for target in ("cli", "vscode"):
            first = self.invoke("sonnet-alias.md", target)
            second = self.invoke("sonnet-alias.md", target)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual((first.returncode, first.stdout, first.stderr),
                             (second.returncode, second.stdout, second.stderr))

    def test_model_inventory_coverage(self):
        inventory = json.loads((ROOT / "tests" / "model_cases.json").read_text())
        cases = inventory["cases"]
        inputs = {case["input"] for case in cases}
        self.assertEqual(inventory["as_of"], "2026-11-04")
        self.assertEqual(len(cases), 51)
        self.assertEqual(len(inputs), 51, "duplicate model inputs")
        expected_groups = {
            "selector-table": {"default", "best", "fable", "sonnet", "opus", "haiku",
                               "sonnet[1m]", "opus[1m]", "opusplan"},
            "context-example": {"fable[1m]", "opusplan[1m]", "claude-fable-5[1m]",
                                "claude-opus-4-6[1m]", "claude-sonnet-4-6[1m]"},
            "subagent-inherit": {"inherit"},
            "subagent-family": {"fable", "sonnet", "opus", "haiku"},
            "api-enum": {
                "claude-haiku-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-opus-5-5",
                "claude-mythos-5-1", "claude-sonnet-5", "claude-fable-5", "claude-mythos-5",
                "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
                "claude-sonnet-4-6", "claude-haiku-4-5", "claude-haiku-4-5-20251001",
                "claude-opus-4-5", "claude-opus-4-5-20251101", "claude-mythos-preview", "claude-sonnet-4-5",
            },
            "model-overview": {
                "claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5",
                "claude-fable-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
                "claude-opus-4-6", "claude-opus-4-5", "claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-4-5",
            },
            "api-primer-date": {"claude-sonnet-4-5-20250929"},
            "copilot-catalog": {
                "claude-sonnet-5.5", "claude-sonnet-5", "claude-fable-5.1", "claude-fable-5",
                "claude-opus-5.5", "claude-opus-5", "claude-opus-4.8", "claude-opus-4.8-fast",
                "claude-sonnet-4.6", "claude-haiku-5.5", "claude-haiku-4.5",
            },
            "provider-sample": {
                "anthropic.claude-fable-5-1", "anthropic.claude-opus-5-5",
                "anthropic.claude-sonnet-5-5", "anthropic.claude-haiku-5-5", "claude-haiku-4-5@20251001",
                "arn:aws:bedrock:us-east-1:000000000000:application-inference-profile/sanitized",
                "sanitized-foundry-deployment", "my-gateway-opus",
            },
            "vscode-native": {"sonnet", "opus", "haiku", "inherit"},
        }
        self.assertEqual(inputs, set().union(*expected_groups.values()))
        for category, expected in expected_groups.items():
            with self.subTest(category=category):
                self.assertEqual({case["input"] for case in cases if category in case["categories"]}, expected)
        catalog = inventory["sources"]["copilot-catalog"]
        self.assertEqual(catalog["version"], "1.0.105")
        self.assertEqual(catalog["command"], "copilot --no-auto-update completion bash")
        self.assertEqual(catalog["as_of"], inventory["as_of"])
        for case in cases:
            self.assertTrue(case["categories"])
            self.assertLessEqual(set(case["categories"]), expected_groups.keys())
            self.assertTrue(case["sources"])
            for source in case["sources"]:
                self.assertTrue(inventory["sources"][source]["url"].startswith("https://"))
            for target in ("cli", "vscode"):
                self.assertIn(set(case[target]), ({"model"}, {"model", "substitution"}, {"reject"}))
                self.assertIsInstance(next(iter(case[target].values())), str)
                self.assertTrue(next(iter(case[target].values())).strip())

    def test_model_matrix_both_targets(self):
        cases = json.loads((ROOT / "tests" / "model_cases.json").read_text())["cases"]
        mapped = {"cli": 0, "vscode": 0}
        rejected = {"cli": 0, "vscode": 0}
        for case in cases:
            header = VALID.replace(b"model: sonnet", b"model: " + json.dumps(case["input"]).encode())
            original = (b"---\n" + header + b"---\n"
                        + "# Matrix marker\r\n€ 😀\t\r\nno final newline".encode("utf-8"))
            self.fixture.write_bytes(original)
            for target in ("cli", "vscode"):
                with self.subTest(model=case["input"], target=target):
                    expected = case[target]
                    if "reject" in expected:
                        result = self.reject(fixture=self.fixture.name, target=target)
                        self.assertIn(expected["reject"].encode(), result.stderr)
                        self.assertIn(repr(case["input"]).encode(), result.stderr)
                        rejected[target] += 1
                    else:
                        result = self.invoke(self.fixture.name, target)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        if expected.get("substitution"):
                            self.assertIn(b"model substitution:", result.stderr)
                            self.assertIn(case["input"].encode(), result.stderr)
                            self.assertIn(expected["model"].encode(), result.stderr)
                        else:
                            self.assertEqual(result.stderr, b"")
                        fields = yaml.safe_load(result.stdout.split(b"---\n")[1])
                        self.assertEqual(fields["model"], expected["model"])
                        self.assertEqual(body(result.stdout), body(original))
                        if target == "cli":
                            self.assertEqual(fields, {
                                "name": "synthetic", "description": "Sanitized fixture.",
                                "model": expected["model"], "model-policy": "required",
                                "strict-tools-list": True, "tools": [],
                            })
                        else:
                            self.assertEqual(result.stdout, original)
                        mapped[target] += 1
        print(f"\nCLI matrix: {mapped['cli']} mapped; {rejected['cli']} expected rejection passes; {len(cases)} inputs", flush=True)
        print(f"VS Code native matrix: {mapped['vscode']} passthrough; {rejected['vscode']} expected rejection passes; {len(cases)} inputs", flush=True)
        self.assertEqual(mapped, {"cli": 26, "vscode": 4})
        self.assertEqual(rejected, {"cli": 25, "vscode": 47})

    def test_missing_fields(self):
        for line in VALID.splitlines(keepends=True):
            with self.subTest(line=line):
                self.reject(b"---\n" + VALID.replace(line, b"") + b"---\n")

    def test_invalid_string_types_and_empty_values(self):
        for key in (b"name", b"description", b"model"):
            original_line = next(line for line in VALID.splitlines() if line.startswith(key + b":"))
            for value in (b"null", b"true", b"123", b"[]", b"{}", b"''", b"'   '"):
                with self.subTest(key=key, value=value):
                    header = VALID.replace(original_line, key + b": " + value)
                    self.reject(b"---\n" + header + b"---\n")

    def test_unknown_fields_refused_individually(self):
        for field in (b"effort: high", b"maxTurns: 450", b"skills: []", b"hooks: {}",
                      b"disallowedTools: []", b"target: vscode", b"extra: ignored"):
            with self.subTest(field=field):
                for target in ("cli", "vscode"):
                    self.reject(b"---\n" + VALID + field + b"\n---\n", target=target)

    def test_tools_must_be_an_empty_list(self):
        for value in (b"[Read]", b"[Bash]", b"null", b"'[]'", b"{}", b"false"):
            with self.subTest(value=value):
                for target in ("cli", "vscode"):
                    self.reject(b"---\n" + VALID.replace(b"tools: []", b"tools: " + value) + b"---\n", target=target)

    def test_duplicate_fields_rejected(self):
        for line in VALID.splitlines(keepends=True):
            self.reject(b"---\n" + VALID + line + b"---\n")
        self.reject(b"---\n" + VALID + b"'model': opus\n---\n")

    def test_duplicate_key_diagnostic_escapes_decoded_terminal_controls(self):
        duplicate = b'"unsafe\\u001b\\u0007": value\n'
        for target in ("cli", "vscode"):
            with self.subTest(target=target):
                result = self.reject(b"---\n" + VALID + duplicate * 2 + b"---\n", target=target)
                self.assertEqual(result.stderr.replace(b"\r\n", b"\n"),
                                 b"preview rejected: duplicate field: 'unsafe\\x1b\\x07'\n")

    def test_duplicate_key_diagnostic_with_explicit_crlf_stream(self):
        duplicate = b'"unsafe\\u001b\\u0007": value\n'
        self.fixture.write_bytes(b"---\n" + VALID + duplicate * 2 + b"---\n")
        for target in ("cli", "vscode"):
            result = self.invoke_main(target, newline="\r\n")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(result.stderr, b"preview rejected: duplicate field: 'unsafe\\x1b\\x07'\r\n")
            self.assertEqual(result.stderr.replace(b"\r\n", b"\n"),
                             b"preview rejected: duplicate field: 'unsafe\\x1b\\x07'\n")

    def test_invalid_utf8_previews_rejected(self):
        for bad in (b"\xff", b"\x80", b"\xc2", b"\xed\xa0\x80"):
            for target in ("cli", "vscode"):
                with self.subTest(bad=bad, target=target):
                    result = self.reject(b"---\n" + VALID + b"---\nbody " + bad, target=target)
                    self.assertEqual(result.stderr.replace(b"\r\n", b"\n"),
                                     b"preview rejected: preview must be valid UTF-8\n")

    def test_disallowed_unicode_controls_rejected(self):
        for code in (*range(32), *range(127, 160)):
            if code in (9, 10, 13):
                continue
            for target in ("cli", "vscode"):
                with self.subTest(code=code, target=target):
                    data = b"---\n" + VALID + b"---\nbefore " + chr(code).encode("utf-8") + b" after"
                    result = self.reject(data, target=target)
                    self.assertEqual(result.stderr.replace(b"\r\n", b"\n"),
                                     b"preview rejected: preview contains unsupported control characters\n")

    def test_output_policy_is_independent_of_tty(self):
        for bad, expected_error in (
            (b"body\x1b[2J\x07", b"preview contains unsupported control characters"),
            (b"body\xff", b"preview must be valid UTF-8"),
            ("€ 😀\t\r\nno final newline".encode("utf-8"), None),
        ):
            original = b"---\n" + VALID + b"---\n" + bad
            self.fixture.write_bytes(original)
            for target in ("cli", "vscode"):
                for tty in (True, False):
                    with self.subTest(target=target, tty=tty, expected_error=expected_error):
                        result = self.invoke_main(target, tty=tty)
                        if expected_error is not None:
                            self.assertEqual(result.returncode, 1)
                            self.assertEqual(result.stdout, b"")
                            self.assertEqual(result.stderr.replace(b"\r\n", b"\n"),
                                             b"preview rejected: " + expected_error + b"\n")
                        else:
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(result.stderr, b"")
                            self.assertEqual(body(result.stdout), bad)
                            if target == "vscode":
                                self.assertEqual(result.stdout, original)

    def test_vscode_conservative_name_subset_cli_unchanged(self):
        for name in ("Synthetic", "with space", "synthetic1", "under_score", "-leading",
                     "trailing-", "two--hyphens", "a\nb", "café"):
            with self.subTest(name=name):
                header = VALID.replace(b"name: synthetic", b"name: " + json.dumps(name).encode())
                self.fixture.write_bytes(b"---\n" + header + b"---\nBody\n")
                result = self.reject(target="vscode")
                self.assertIn(b"VS Code native name must match [a-z]+(?:-[a-z]+)*", result.stderr)
                cli = self.invoke(self.fixture.name, "cli")
                self.assertEqual(cli.returncode, 0, cli.stderr)
                self.assertEqual(cli.stderr, b"")
                self.assertEqual(yaml.safe_load(cli.stdout.split(b"---\n")[1])["name"], name)
        for name in (b"synthetic", b"synthetic-sonnet", b"a", b"a-b"):
            original = b"---\n" + VALID.replace(b"name: synthetic", b"name: " + name) + b"---\nBody\n"
            self.fixture.write_bytes(original)
            result = self.invoke(self.fixture.name, "vscode")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, original)

    def test_leading_utf8_bom_has_specific_diagnostic(self):
        for target in ("cli", "vscode"):
            with self.subTest(target=target):
                result = self.reject(b"\xef\xbb\xbf---\n" + VALID + b"---\nBody\n", target=target)
                self.assertEqual(result.stderr.replace(b"\r\n", b"\n"),
                                 b"preview rejected: UTF-8 BOM is unsupported; use UTF-8 without BOM\n")

    def test_native_command_sentinel_examples(self):
        count = 0
        for name in ("README.md", "SKILL.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for block in re.findall(r"```powershell\n(.*?)```", text, flags=re.S):
                self.assertNotRegex(block, r"\$(?!global:)LASTEXITCODE\b")
                lines = block.splitlines()
                for index, line in enumerate(lines):
                    if not line.startswith("& "):
                        continue
                    count += 1
                    self.assertGreater(index, 0)
                    self.assertEqual(lines[index - 1], "$global:LASTEXITCODE = $null")
                    expected = 1 if any(f"'{fixture}'" in line for fixture in (
                        "client-test-author.md", "fable-alias.md")) else 0
                    self.assertTrue(lines[index + 1].startswith(
                        f"if ($null -eq $global:LASTEXITCODE -or $global:LASTEXITCODE -ne {expected}) {{ throw "),
                        (name, line, lines[index + 1]))
                    self.assertIn("'-I' '-B' '-X' 'utf8'", line)
        self.assertEqual(count, 8)

    def test_unsafe_yaml_aliases_anchors_and_merges_rejected(self):
        for header in (
            VALID.replace(b"sonnet", b"!!str sonnet"),
            VALID.replace(b"sonnet", b"!custom sonnet"),
            VALID.replace(b"sonnet", b"!!python/object/apply:os.system ['SANITIZED_HOOK_DO_NOT_EXECUTE']"),
            VALID.replace(b"sonnet", b"&model sonnet"),
            VALID.replace(b"sonnet", b"*model"),
            VALID + b"<<: {name: replacement}\n",
            VALID + b"'<<': {}\n",
        ):
            with self.subTest(header=header):
                self.reject(b"---\n" + header + b"---\n")

    def test_unknown_models_and_no_general_normalization(self):
        for model in (b"latest", b"Sonnet", b"claude-opus-4-8-fast",
                      b"claude_opus_5_5", b" sonnet "):
            for target in ("cli", "vscode"):
                self.reject(b"---\n" + VALID.replace(b"sonnet", b"'" + model + b"'") + b"---\n", target=target)

    def test_malformed_frontmatter_rejected(self):
        for data in (
            b"", b"Body only",
            b" ---\n" + VALID + b"---\n", b"---\n" + VALID,
            b"---\n---\n", b"---\n[]\n---\n", b"---\nscalar\n---\n",
            b"---\n" + VALID.replace(b"model: sonnet", b"model:sonnet") + b"---\n",
            b"---\n" + VALID.replace(b"tools: []", b"tools: [") + b"---\n",
            b"---\n" + VALID + b"...\nname: second document\n---\n",
            b"---\n" + VALID + b"? [complex, key]\n: value\n---\n",
            b"---\n" + VALID.replace(b"sonnet", b"\xff") + b"---\n",
        ):
            with self.subTest(data=data):
                self.reject(data)

    def test_original_shaped_fixtures_reject_unsupported_semantics(self):
        for fixture in ("smc-scanner.md", "client-test-author.md"):
            for target in ("cli", "vscode"):
                with self.subTest(fixture=fixture, target=target):
                    result = self.reject(fixture=fixture, target=target)
                    self.assertIn(b"unknown=", result.stderr)
                    self.assertIn(b"skills", result.stderr)
                    if fixture == "client-test-author.md":
                        self.assertIn(b"hooks", result.stderr)

    def test_traversal_outside_paths_and_missing_files_rejected(self):
        for fixture in ("../sonnet-alias.md", "../../README.md", str(FIXTURES / "sonnet-alias.md"),
                        "nested/sonnet-alias.md", "..\\sonnet-alias.md", "missing.md", "README", ".", ".."):
            with self.subTest(fixture=fixture):
                self.reject(fixture=fixture)

    def test_symlinks_rejected_even_to_allowed_fixtures(self):
        for destination in (FIXTURES / "sonnet-alias.md", ROOT / "README.md", Path(self.scratch.name)):
            with self.subTest(destination=destination):
                self.link_or_skip(self.fixture.symlink_to, destination,
                                  target_is_directory=destination.is_dir())
                self.reject()
                self.fixture.unlink()

    def test_no_destination_option_or_unknown_target(self):
        self.reject(fixture="sonnet-alias.md", target="other", expected_code=2)
        self.reject(fixture="sonnet-alias.md", extra=("--output", str(Path(self.scratch.name) / "output.md")), expected_code=2)
        self.assertEqual(list(self.cwd.iterdir()), [])
        self.assertEqual(list(Path(self.scratch.name).iterdir()), [self.cwd])

    def test_reserved_windows_basenames_rejected_before_io(self):
        for fixture in ("CON.md", "con.extra.md", "PrN.MD", "AUX..md", "NUL.notes.md",
                        "COM1.md", "com9.extra.MD", "LPT1.md", "lpt9.more.md"):
            with self.subTest(fixture=fixture):
                result = self.reject(fixture=fixture)
                self.assertIn(b"Windows-reserved", result.stderr)

    def test_windows_location_forms_synthetic_not_windows_certification(self):
        for location in (r"\\server\share\skill", r"\\?\C:\skill", r"\\.\CON",
                         "C:relative", "C:", r"\rooted", "//server/share/skill"):
            with self.subTest(location=location):
                with self.assertRaisesRegex(ValueError, "locations are unsupported"):
                    PREPARE.check_location(location)
        PREPARE.check_location(r"C:\Approved Local\skill")

    def test_synthetic_reparse_attribute_guard_and_root_to_leaf_order(self):
        source = Path(self.scratch.name) / "ancestor" / "file.md"
        visited = []

        def fake_lstat(path):
            visited.append(path)
            self.assertNotEqual(path, source, "must stop before inspecting the leaf")
            attributes = stat.FILE_ATTRIBUTE_REPARSE_POINT if path == source.parent else 0
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=attributes)

        with mock.patch.object(Path, "lstat", fake_lstat):
            with self.assertRaisesRegex(ValueError, "reparse"):
                PREPARE.checked_stat(source)
        self.assertEqual(visited, list(reversed(source.parents)))
        with self.assertRaisesRegex(ValueError, "symlink/reparse"):
            PREPARE.reject_link(SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0))

    def test_real_ancestor_symlink_guard(self):
        actual = Path(self.scratch.name) / "actual"
        actual.mkdir()
        (actual / "file.md").write_bytes(b"---\n" + VALID + b"---\n")
        linked = Path(self.scratch.name) / "linked"
        self.link_or_skip(linked.symlink_to, actual, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink/reparse"):
            PREPARE.read_source(linked / "file.md")

    def test_hardlinked_source_rejected(self):
        actual = Path(self.scratch.name) / "original.md"
        actual.write_bytes(b"---\n" + VALID + b"---\n")
        self.link_or_skip(os.link, actual, self.fixture)
        for target in ("cli", "vscode"):
            result = self.reject(target=target)
            self.assertIn(b"exactly one hard link", result.stderr)

    def test_nonregular_source_rejected(self):
        self.fixture.mkdir()
        try:
            self.reject()
        finally:
            self.fixture.rmdir()

    def test_one_mib_boundary_and_oversize(self):
        prefix = b"---\n" + VALID + b"---\n"
        limit = 1024 * 1024
        for delta in (0, 1):
            self.fixture.write_bytes(prefix + b"x" * (limit - len(prefix) + delta))
            for target in ("cli", "vscode"):
                with self.subTest(delta=delta, target=target):
                    if delta:
                        result = self.reject(target=target)
                        self.assertIn(b"1 MiB", result.stderr)
                    else:
                        result = self.invoke(self.fixture.name, target)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(body(result.stdout), b"x" * (limit - len(prefix)))

    def test_bounded_read_rejects_growth_after_lstat(self):
        self.fixture.write_bytes(b"small")
        stream = mock.MagicMock()
        stream.__enter__.return_value = stream
        stream.read.return_value = b"x" * (1024 * 1024 + 1)
        with mock.patch.object(Path, "open", return_value=stream):
            with self.assertRaisesRegex(ValueError, "1 MiB"):
                PREPARE.read_source(self.fixture)
        stream.read.assert_called_once_with(1024 * 1024 + 1)


if __name__ == "__main__":
    unittest.main()
