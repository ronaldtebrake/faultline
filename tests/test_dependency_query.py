"""File-impact explanations across committed trees, cycles and incomplete evidence."""
import json
import unittest
from unittest.mock import patch

from faultline.cli import main
from faultline.core import FaultlineError
from faultline.tia.dependency_graph import build
from faultline.tia.dependency_query import affected
import test_dependency_graph as fixtures


class DependencyQueryTests(unittest.TestCase):
    setUp = fixtures.DependencyGraphTests.setUp
    git = fixtures.DependencyGraphTests.git
    write = fixtures.DependencyGraphTests.write
    commit = fixtures.DependencyGraphTests.commit

    def test_cli_reports_transitive_paths_without_editing_or_running_tests(self):
        self.write('e2e/pages/checkout.ts', 'export const checkout = () => 0;')
        status = self.git('status', '--porcelain')
        with patch('builtins.print') as output, patch('faultline.tia.runners.invoke', side_effect=AssertionError('No tests')):
            code = main(['--root', str(self.root), 'graph', 'affected', '--file', './src/price.ts',
                         '--output', '.faultline/impact.json'])
        self.assertEqual(0, code)
        result = json.loads(output.call_args.args[0])
        key = 'browser:default:e2e/checkout.spec.ts'
        self.assertEqual([key], result['affected'])
        explanation = result['explanations'][key][0]
        self.assertEqual(['e2e/checkout.spec.ts', 'e2e/pages/checkout.ts', 'src/price.ts'], explanation['path'])
        self.assertEqual(['module_import', 'module_import'], [e['kind'] for e in explanation['edges']])
        self.assertEqual(self.base, explanation['revision'])
        self.assertIn('browser:default:e2e/profile.spec.ts', result['unresolved'])
        self.assertFalse(result['omission_authorized'])
        self.assertEqual(0, result['jev_requests'])
        self.assertEqual(result, json.loads((self.root / '.faultline/impact.json').read_text()))
        self.assertEqual(status, self.git('status', '--porcelain'))

    def test_deleted_dependency_uses_base_and_removed_tests_are_separate(self):
        base = build(self.store)['graph']
        (self.root / 'src/price.ts').unlink()
        (self.root / 'e2e/profile.spec.ts').unlink()
        self.commit()
        head = build(self.store)['graph']
        self.assertEqual(['src/price.ts'], affected(head, ['src/price.ts'])['unknown_files'])
        result = affected(head, ['src/price.ts'], base=base)
        key = 'browser:default:e2e/checkout.spec.ts'
        self.assertEqual([key], result['affected'])
        self.assertEqual('base', result['explanations'][key][0]['snapshot'])
        self.assertEqual([], result['unknown_files'])
        self.assertEqual(['browser:default:e2e/profile.spec.ts'], result['removed_targets'])

    def test_new_file_reresolves_existing_import_and_cycles_terminate(self):
        self.write('src/price.ts', "export {value} from './new';")
        self.commit()
        before = build(self.store)['graph']
        self.assertEqual(['src/new.ts'], affected(before, ['src/new.ts'])['unknown_files'])
        self.write('src/new.ts', "import './price'; export const value = 2;")
        self.commit()
        after = build(self.store)['graph']
        result = affected(after, ['src/new.ts', './src/new.ts'])
        key = 'browser:default:e2e/checkout.spec.ts'
        self.assertEqual([key], result['affected'])
        self.assertEqual(['src/new.ts'], result['files'])
        self.assertEqual(['e2e/checkout.spec.ts', 'e2e/pages/checkout.ts', 'src/price.ts', 'src/new.ts'],
                         result['explanations'][key][0]['path'])

    def test_multiple_inputs_include_self_changes_and_setup(self):
        graph = build(self.store)['graph']
        result = affected(graph, ['playwright.config.ts', 'e2e/profile.spec.ts'])
        key = 'browser:default:e2e/profile.spec.ts'
        explanations = {r['input']: r for r in result['explanations'][key]}
        self.assertEqual([graph['targets'][key]['source']], explanations['e2e/profile.spec.ts']['path'])
        self.assertEqual([], explanations['e2e/profile.spec.ts']['edges'])
        self.assertEqual('configured_setup', explanations['playwright.config.ts']['edges'][0]['kind'])
        for path in ('../secret', '/tmp/secret', 'C:/secret', '.', 'src\\price.ts'):
            with self.assertRaises(FaultlineError):
                affected(graph, [path])
