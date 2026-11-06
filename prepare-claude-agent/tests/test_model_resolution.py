"""Live-catalog selection policy, with no network or inference."""
import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location('resolver_tests', ROOT / 'scripts' / 'prepare_agent.py')
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


class ModelResolution(unittest.TestCase):
    def test_alias_uses_numeric_latest_standard_model(self):
        catalog = ['claude-sonnet-5.9', 'claude-sonnet-5.10',
                   'claude-sonnet-6-preview', 'claude-sonnet-7-fast', 'claude-opus-9']
        self.assertEqual(PREPARE.resolve_model('sonnet', catalog), ('claude-sonnet-5.10', False))
        self.assertEqual(PREPARE.resolve_model('newfamily', ['claude-newfamily-2.1']),
                         ('claude-newfamily-2.1', False))

    def test_explicit_version_matches_equivalent_spelling(self):
        for requested in ['claude-sonnet-5-5', 'claude-sonnet-5.5']:
            self.assertEqual(PREPARE.resolve_model(requested, ['claude-sonnet-5.5', 'claude-sonnet-6']),
                             ('claude-sonnet-5.5', False))
        self.assertEqual(PREPARE.resolve_model('claude-sonnet-5', ['claude-sonnet-5.0']),
                         ('claude-sonnet-5.0', False))

    def test_nearest_prefers_same_major_then_distance_then_newer(self):
        for requested, catalog, expected in [
            ('claude-sonnet-5-5', ['claude-sonnet-5.4', 'claude-sonnet-5.6'], 'claude-sonnet-5.6'),
            ('claude-sonnet-5-5', ['claude-sonnet-5.1', 'claude-sonnet-6.5'], 'claude-sonnet-5.1'),
            ('claude-sonnet-5-5', ['claude-sonnet-4.5', 'claude-sonnet-6.5'], 'claude-sonnet-6.5'),
            ('claude-sonnet-5-5', ['claude-sonnet-4.4', 'claude-sonnet-4.8'], 'claude-sonnet-4.4'),
        ]:
            with self.subTest(requested=requested, catalog=catalog):
                self.assertEqual(PREPARE.resolve_model(requested, catalog), (expected, True))

    def test_missing_family_or_unsupported_semantics_reject(self):
        for requested in ['opus', 'claude-opus-5.5', 'inherit', 'default', 'best', 'opusplan',
                          'sonnet[1m]', 'claude-sonnet-5.5[1m]', 'claude-sonnet-5.5-fast',
                          'claude-sonnet-5-5-20261101', 'anthropic.claude-sonnet-5-5',
                          'custom-deployment', 'claude-sonnet-05.5']:
            with self.subTest(requested=requested):
                with self.assertRaises(ValueError):
                    PREPARE.resolve_model(requested, ['claude-sonnet-5.5'])

    def test_dynamic_selectors_cannot_become_family_aliases(self):
        for selector in ('inherit', 'default', 'best', 'opusplan', 'auto'):
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                PREPARE.resolve_model(selector, [f'claude-{selector}-5'])

    def test_special_id_requires_exact_catalog_membership(self):
        for model in ['claude-opus-4.8-fast', 'claude-mythos-preview', 'claude-sonnet-5-5-20261101']:
            self.assertEqual(PREPARE.resolve_model(model, [model]), (model, False))

    def test_ambiguous_numeric_versions_and_empty_catalog_reject(self):
        for catalog in [[], ['claude-sonnet-5', 'claude-sonnet-5.0'],
                        ['claude-sonnet-5.5', 'claude-sonnet-5-5']]:
            with self.subTest(catalog=catalog), self.assertRaises(ValueError):
                PREPARE.resolve_model('sonnet', catalog)

    def test_explicit_numeric_ids_also_reject_ambiguous_versions(self):
        for catalog in [['claude-sonnet-5.5', 'claude-sonnet-5-5'],
                        ['claude-sonnet-5', 'claude-sonnet-5.0']]:
            for requested in catalog:
                with self.subTest(requested=requested), self.assertRaisesRegex(ValueError, 'ambiguous'):
                    PREPARE.resolve_model(requested, catalog)

    def test_fresh_catalog_for_each_preview(self):
        with mock.patch.object(PREPARE, 'discover_models', side_effect=[
            ['claude-sonnet-5.5'], ['claude-sonnet-6']
        ]) as discover:
            first = PREPARE.preview('sonnet-alias.md', 'cli', '/approved/copilot')
            second = PREPARE.preview('sonnet-alias.md', 'cli', '/approved/copilot')
        self.assertIn(b'model: claude-sonnet-5.5\n', first)
        self.assertIn(b'model: claude-sonnet-6\n', second)
        self.assertEqual(discover.call_args_list, [mock.call('/approved/copilot')] * 2)

    def test_fallback_notice_preserves_preview_body(self):
        stderr = io.StringIO()
        with mock.patch.object(PREPARE, 'discover_models', return_value=['claude-sonnet-5.6']), \
                contextlib.redirect_stderr(stderr):
            output = PREPARE.preview('sonnet-pinned.md', 'cli', '/approved/copilot')
        self.assertIn('claude-sonnet-5-5', stderr.getvalue())
        self.assertIn('claude-sonnet-5.6', stderr.getvalue())
        self.assertIn('substitution', stderr.getvalue())
        original = (ROOT / 'fixtures' / 'claude-agents' / 'sonnet-pinned.md').read_bytes()
        self.assertEqual(output.split(b'---\n', 2)[2], original.split(b'---\n', 2)[2])

    def test_vscode_never_discovers(self):
        with mock.patch.object(PREPARE, 'discover_models', side_effect=AssertionError('network')):
            self.assertEqual(PREPARE.preview('sonnet-alias.md', 'vscode'),
                             (ROOT / 'fixtures' / 'claude-agents' / 'sonnet-alias.md').read_bytes())

    def test_invalid_input_rejected_before_discovery(self):
        with mock.patch.object(PREPARE, 'discover_models') as discover:
            with self.assertRaises(ValueError):
                PREPARE.preview('client-test-author.md', 'cli', '/approved/copilot')
        discover.assert_not_called()

    def test_cli_requires_explicit_runtime(self):
        with self.assertRaisesRegex(ValueError, 'copilot-path'):
            PREPARE.preview('sonnet-alias.md', 'cli')


if __name__ == '__main__':
    unittest.main()
