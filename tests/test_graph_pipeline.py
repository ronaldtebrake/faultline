"""Behavioral tests for graph provenance, conservative decisions, and shadow reports."""
import copy
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from faultline.cli import main
from faultline.core import FaultlineError, Store, digest, write_json
from faultline.jev import LEVELS
from faultline.tia import catalog, graph
from faultline.tia.batch import BatchedJev, batches, identity
from faultline.tia.common import checked, save_frozen, seal
from faultline.tia.config import DEFAULT_EVALUATOR, load_config
from faultline.tia.execution import run_suite
from faultline.tia.results import record, report
from faultline.tia.selection import select


def answer(level='irrelevant'):
    return {'type': 'choice', 'choice': level, 'probabilities': {k: float(k == level) for k in LEVELS}}


class Evaluator:
    def __init__(self):
        self.profiles = []

    def evaluate(self, context, profiles, dry_run=False):
        self.profiles = profiles
        rows = {p['id']: {'probabilities': answer()['probabilities'], 'score': 0, 'model': DEFAULT_EVALUATOR['model']} for p in profiles}
        return {'rows': rows, 'errors': {}, 'requests': 0, 'cache_hits': 0, 'uncached_requests': 0,
                'batches': 0, 'usage': [], 'complete': True}


class GraphPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'repo'
        self.root.mkdir()
        self.store = Store(self.root)
        self.store.initialize()
        self.git('init', '-q')
        files = {'src/Policy.php': '<?php class Policy { function allows() { return true; } }',
                 'src/Service.php': '<?php class Service { function show() { return (new Policy())->allows(); } }',
                 'tests/ATest.php': '<?php class ATest { function testA() { return (new Service())->show(); } }',
                 'tests/BTest.php': '<?php class BTest { function testB() { return 2; } }',
                 'settings.yml': 'services: {}',
                 'runner.py': 'raise SystemExit(7)\n',
                 '.gitignore': '.faultline/\n'}
        for name, text in files.items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        native = {'schema_version': 2, 'complete': True, 'units': [
            {'source': f'tests/{name}Test.php', 'members': [f'{name}Test::test{name}'], 'locator': {'file': f'tests/{name}Test.php'}, 'title': f'Test {name}'} for name in ('A', 'B')]}
        (self.root / 'discover.py').write_text('print(' + repr(json.dumps(native)) + ')\n')
        self.raw = {'schema_version': 2, 'repository': 'fixture', 'scope': ['src/**', 'tests/**'],
                    'graph': {'command': [os.environ.get('FAULTLINE_CODEGRAPH', 'codegraph')]},
                    'suites': [{'id': 'unit', 'runner': 'generic', 'command': [sys.executable, 'runner.py'],
                                'discovery_command': [sys.executable, 'discover.py'], 'sources': ['tests/*.php']}]}
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        inv = catalog.discover(self.root, load_config(self.root))
        review = self.store.path / 'review.json'
        write_json(review, [{'id': u['id'], 'description_hash': u['description_hash'], 'description': u['title']} for s in inv['suites'] for u in s['units']])
        catalog.import_records(self.root, inv, review, 'fixture')
        self.commit()
        self.base = self.git('rev-parse', 'HEAD').strip()
        (self.root / 'src/Policy.php').write_text('<?php class Policy { function allows() { return false; } }')
        self.commit()
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.config = load_config(self.root)
        self.artifacts = [self.publish(self.base), self.publish(self.head)]

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True, check=True).stdout

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fixture')

    def publish(self, rev):
        path = graph.artifact_path(self.store, self.config, rev)
        path.mkdir(parents=True)
        db = sqlite3.connect(path / 'graph.sqlite')
        db.executescript('''CREATE TABLE files(path TEXT, language TEXT, errors TEXT, node_count INTEGER);
        CREATE TABLE nodes(id TEXT, kind TEXT, name TEXT, file_path TEXT, start_line INTEGER,end_line INTEGER);
        CREATE TABLE edges(source TEXT,target TEXT,kind TEXT,metadata TEXT,provenance TEXT);''')
        for name, source in [('policy', 'src/Policy.php'), ('service', 'src/Service.php'), ('a', 'tests/ATest.php'), ('b', 'tests/BTest.php')]:
            db.execute('INSERT INTO files VALUES(?,?,?,?)', (source, 'php', None, 1))
            db.execute('INSERT INTO nodes VALUES(?,?,?,?,?,?)', (name, 'method', name, source, 1, 1))
        for source, target in [('a', 'service'), ('service', 'policy')]:
            db.execute('INSERT INTO edges VALUES(?,?,?,?,?)', (source, target, 'calls', '{"resolvedBy":"fixture"}', None))
        db.commit()
        db.close()
        files, count = graph.inspect(path / 'graph.sqlite', 100)
        save_frozen(path / 'manifest.json', {'schema_version': 2, 'kind': 'codegraph', 'contract': graph.CONTRACT,
                     'producer_version': graph.VERSION, 'repository': 'fixture', 'revision': rev,
                     'settings_hash': graph.settings_hash(self.config['graph']), 'database_sha256': graph.sha(path / 'graph.sqlite'),
                     'sources': {p: 'fixture' for p in [*files, 'settings.yml']}, 'files': files,
                     'unsupported': [], 'edge_count': count})
        return path

    def selection(self, evaluator=None, **kw):
        return select(self.store, self.base, evaluator=evaluator or Evaluator(), build_graphs=False, **kw)


    def test_shadow_selection_saves_would_run_report_without_execution(self):
        with patch('faultline.tia.runners.invoke', side_effect=AssertionError('No native discovery')):
            result = self.selection(identifier='PR-123', output=self.store.path / 'custom.json')
        report_path = Path(result['report']['json'])
        value = json.loads(report_path.read_text())
        self.assertEqual('PR-123', value['change']['id'])
        self.assertEqual('none', value['execution'])
        self.assertEqual(0, value['metrics']['tests_executed_by_faultline'])
        self.assertEqual(1, value['metrics']['would_run'])
        self.assertEqual(1, value['metrics']['would_omit'])
        self.assertIsNone(value['metrics']['regression_recall'])
        self.assertIsNone(value['metrics']['measured_execution_savings_seconds'])
        self.assertTrue(Path(result['report']['markdown']).is_file())
        self.assertFalse((self.store.path / 'runs').exists())
        self.assertTrue((self.store.path / 'selections' / result['selection_id'] / 'selection.json').is_file())

    def test_run_defaults_to_offline_preview_even_with_unavailable_runtime(self):
        result = self.selection()
        # Previewing old proposals does not require the original checkout/runtime.
        (self.root / 'runner.py').unlink()
        with patch('subprocess.run', side_effect=AssertionError('No process in shadow preview')):
            preview = run_suite(self.store, result['path'], 'unit')
            self.assertEqual('none', preview['execution'])
            self.assertEqual(0, preview['exit_code'])
            with patch('builtins.print'), patch('faultline.cli.repo_root', return_value=self.root):
                self.assertEqual(0, main(['--root', str(self.root), 'run', '--selection', result['path'], '--suite', 'unit']))
                self.assertEqual(0, main(['--root', str(self.root), 'shadow-report', '--selection', result['path']]))
                self.assertEqual(0, main(['--root', str(self.root), 'shadow-report']))
        self.assertFalse((self.store.path / 'runs').exists())

    def test_shadow_summary_deduplicates_reanalysis_and_keeps_revision_snapshots(self):
        from faultline.tia.proposals import aggregate
        first = self.selection(identifier='PR-123')
        second = self.selection(identifier='PR-123')
        summary = aggregate(self.store)
        self.assertEqual(2, summary['analyses'])
        self.assertEqual(1, summary['snapshots'])
        self.assertEqual(second['selection_id'], summary['cases'][0]['selection_id'])
        (self.root / 'src/Policy.php').write_text('<?php class Policy { function allows() { return null; } }')
        self.commit()
        self.selection(identifier='PR-123')
        with patch('subprocess.run', side_effect=AssertionError('Aggregation must be offline')):
            summary = aggregate(self.store)
        self.assertEqual(2, summary['snapshots'])
        self.assertEqual(3, summary['analyses'])
        self.assertEqual(2, len({c['change']['head'] for c in summary['cases']}))

    def test_shadow_report_exposes_graph_warning_without_inventing_savings(self):
        from faultline.tia.proposals import aggregate
        (self.artifacts[0] / 'graph.sqlite').write_bytes(b'corrupt')
        result = self.selection()
        value = json.loads(Path(result['report']['json']).read_text())
        self.assertEqual(1, value['metrics']['would_omit'])
        self.assertFalse(value['suites'][0]['would_run_full_suite'])
        self.assertIn('missing_invalid_or_incompatible_base_graph', value['suites'][0]['warnings'])
        self.assertEqual('complete', value['semantic']['status'])
        self.assertIsNone(value['metrics']['measured_execution_savings_seconds'])
        self.assertEqual('none', aggregate(self.store)['execution'])

    def test_analysis_and_catalog_commands_never_invoke_runners(self):
        with patch('faultline.tia.runners.invoke', side_effect=AssertionError('Application must stay offline')):
            result = self.selection()
            frozen = checked(Path(result['path']))
            self.assertEqual('source', frozen['inventory']['basis'])
            self.assertFalse(frozen['inventory']['suites'][0]['native_complete'])
            self.assertTrue(all(not u['members'] for u in frozen['suites'][0]['units']))
            self.assertEqual(1, result['proposed_omitted'])
            self.selection(dry_run=True)
            with patch('builtins.print'):
                for arguments in (['discover'], ['catalog', 'show'], ['catalog', 'check'], ['catalog', 'sync'], ['select', '--base', self.base, '--no-build', '--dry-run']):
                    self.assertEqual(0, main(['--root', str(self.root), *arguments]))

    def test_source_analysis_does_not_require_php_or_a_bootstrapped_application(self):
        self.raw['suites'][0].update(runner='behat', command=['nonexistent-behat'])
        del self.raw['suites'][0]['discovery_command']
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        with patch('faultline.tia.runners.invoke', side_effect=AssertionError('No runtime allowed')):
            inventory = catalog.source_inventory(self.root, load_config(self.root))
            self.assertTrue(inventory['complete'])
            self.assertEqual(2, len(inventory['suites'][0]['units']))
            result = self.selection()
        self.assertEqual('none', result['execution'])

    def test_native_enrichment_is_explicit_and_failure_keeps_source_analysis(self):
        result = self.selection(native=True)
        frozen = checked(Path(result['path']))
        self.assertTrue(frozen['inventory']['suites'][0]['native_complete'])
        self.assertEqual(['ATest::testA'], frozen['suites'][0]['units'][0]['members'])
        with patch('faultline.tia.runners.invoke', side_effect=FaultlineError('Environment unavailable')):
            result = self.selection(native=True)
        frozen = checked(Path(result['path']))
        self.assertFalse(frozen['inventory']['suites'][0]['native_complete'])
        self.assertTrue(frozen['inventory']['suites'][0]['native_evidence']['errors'])
        self.assertEqual(1, result['proposed_omitted'])

    def test_execution_validates_only_requested_suite(self):
        other = copy.deepcopy(self.raw['suites'][0])
        other.update(id='unavailable', discovery_command=['absent-discovery'], command=['absent-runner'])
        self.raw['suites'].append(other)
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        result = self.selection()
        from faultline.tia.runners import discover_suite
        with patch('faultline.tia.execution.discover_suite', wraps=discover_suite) as discover:
            receipt = run_suite(self.store, result['path'], 'unit', execute=True)
        self.assertEqual(1, discover.call_count)
        self.assertEqual('unit', discover.call_args.args[1]['id'])
        self.assertTrue(receipt['proposal_validated'])
        self.assertEqual(7, receipt['exit_code'])

    def test_discovery_failure_during_execution_runs_full_and_reports_incomplete(self):
        result = self.selection()
        with patch('faultline.tia.runners.invoke', side_effect=FaultlineError('Environment unavailable')):
            receipt = run_suite(self.store, result['path'], 'unit', execute=True)
        self.assertEqual(7, receipt['exit_code'])
        self.assertFalse(receipt['proposal_validated'])
        self.assertIn('native_discovery_incomplete', receipt['validation_fallbacks'])
        self.assertEqual('full_evaluation', receipt['mode'])
        report_result = record(self.store, result['path'], receipt['path'], self.store.path / 'missing.xml', format='junit')
        self.assertFalse(report_result['metrics']['outcomes_complete'])
        self.assertIsNone(report_result['metrics']['potential_serial_test_seconds_avoided'])

    def test_runtime_inventory_does_not_rewrite_frozen_proposal(self):
        result = self.selection()
        from faultline.tia.runners import discover_suite
        native = discover_suite(self.root, self.config['suites'][0], self.config['suites'][0]['variants'][0])
        native['units'] = native['units'][:1]
        with patch('faultline.tia.execution.discover_suite', return_value=native):
            receipt = run_suite(self.store, result['path'], 'unit', execute=True)
        self.assertIn('source_targets_differ_from_native_inventory', receipt['validation_fallbacks'])
        self.assertFalse(receipt['proposal_validated'])
        self.assertEqual(['unit:default:tests/BTest.php'], checked(Path(result['path']))['suites'][0]['proposed_omitted'])

    def test_native_cross_test_dependencies_invalidate_omission_assessment(self):
        result = self.selection()
        from faultline.tia.runners import discover_suite
        native = discover_suite(self.root, self.config['suites'][0], self.config['suites'][0]['variants'][0])
        native['units'][0]['requires_full_suite'] = True
        with patch('faultline.tia.execution.discover_suite', return_value=native):
            receipt = run_suite(self.store, result['path'], 'unit', execute=True)
        self.assertFalse(receipt['proposal_validated'])
        self.assertIn('native_dependencies_require_full_suite', receipt['validation_fallbacks'])
        self.assertEqual(7, receipt['exit_code'])

    def test_whole_check_needs_no_test_inventory_and_preserves_exit_status(self):
        self.raw['suites'] = [{'id': 'static', 'kind': 'check', 'runner': 'generic',
                              'command': [sys.executable, 'runner.py']}]
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        with patch('faultline.tia.runners.invoke', side_effect=AssertionError('Checks have no test enumeration')):
            result = self.selection()
            receipt = run_suite(self.store, result['path'], 'static', execute=True)
        self.assertEqual(1, result['proposed_selected'])
        self.assertEqual(0, result['proposed_omitted'])
        self.assertEqual(7, receipt['exit_code'])
        failed = record(self.store, result['path'], receipt['path'])
        self.assertEqual(1, failed['metrics']['unknown_failures'])
        self.assertFalse(failed['metrics']['outcomes_complete'])
        self.assertIsNone(failed['metrics']['failing_test_recall'])

    def test_generic_without_native_discovery_never_uses_full_command_for_listing(self):
        suite = copy.deepcopy(self.config['suites'][0])
        del suite['discovery_command']
        from faultline.tia.runners import discover_suite
        with patch('faultline.tia.runners.invoke', side_effect=AssertionError('Must not run tests for discovery')):
            native = discover_suite(self.root, suite, suite['variants'][0])
        self.assertFalse(native['complete'])
        self.assertTrue(native['errors'])

    def test_graph_positive_match_is_mandatory_and_jev_gets_paths(self):
        evaluator = Evaluator()
        result = self.selection(evaluator)
        value = checked(Path(result['path']))
        suite = value['suites'][0]
        self.assertEqual(['unit:default:tests/ATest.php'], suite['proposed_selected'])
        self.assertEqual(['unit:default:tests/BTest.php'], suite['proposed_omitted'])
        self.assertEqual('none', suite['execution'])
        self.assertIn('positive_code_graph_match', suite['reasons'][suite['proposed_selected'][0]])
        self.assertEqual(2, len(evaluator.profiles))
        self.assertEqual(2, len(evaluator.profiles[0]['graph_evidence']['change_paths'][0]['edges']))
        self.assertTrue(all(len(ids) == 1 for ids in suite['baselines'].values()))

    def test_base_edges_survive_deletions_in_head_graph(self):
        path = self.artifacts[1]
        with sqlite3.connect(path / 'graph.sqlite') as db:
            db.execute('DELETE FROM edges')
        doc = checked(path / 'manifest.json')
        doc['database_sha256'] = graph.sha(path / 'graph.sqlite')
        write_json(path / 'manifest.json', seal(doc))
        value = checked(Path(self.selection()['path']))
        self.assertEqual('base', value['graph']['paths']['tests/ATest.php'][0]['snapshot'])
        self.assertIn('unit:default:tests/ATest.php', value['suites'][0]['proposed_selected'])

    def test_graph_gaps_remain_visible_without_blocking_source_scoring(self):
        (self.artifacts[0] / 'graph.sqlite').write_bytes(b'corrupt')
        result = self.selection()
        self.assertEqual(1, result['proposed_omitted'])
        frozen = checked(Path(result['path']))
        self.assertIn('missing_invalid_or_incompatible_base_graph', frozen['suites'][0]['warnings'])
        # Head-only evidence remains bounded; an unfinished traversal is not an empty impact set.
        conf = copy.deepcopy(self.config)
        conf['graph']['max_depth'] = 1
        evidence = graph.evidence(self.store, conf, {'base': self.base, 'head': self.head, 'changed_files': ['src/Policy.php']}, catalog.discover(self.root, conf))
        self.assertTrue(evidence['truncated'])
        self.assertIn('graph_traversal_budget_exhausted', evidence['fallbacks'])

    def test_unindexed_changed_configuration_is_visible(self):
        evidence = graph.evidence(self.store, self.config, {'base': self.base, 'head': self.head, 'changed_files': ['settings.yml']}, catalog.discover(self.root, self.config))
        self.assertEqual(['settings.yml'], evidence['unknown_changes'])
        self.assertIn('changed_files_without_usable_graph_evidence', evidence['fallbacks'])

    def test_missing_credentials_widen_proposal_and_run_preserves_failure_exit(self):
        with patch('faultline.tia.batch.api_key', side_effect=FaultlineError('No credential')):
            result = select(self.store, self.base, build_graphs=False)
        self.assertEqual(0, result['proposed_omitted'])
        self.assertEqual('not_evaluated', result['semantic']['status'])
        self.assertEqual(2, result['semantic']['unscored'])
        self.assertTrue(all('No credential' in e for e in result['semantic']['errors'].values()))
        receipt = run_suite(self.store, result['path'], 'unit', execute=True)
        self.assertEqual(7, receipt['exit_code'])
        self.assertEqual('full_evaluation', receipt['mode'])
        with patch('builtins.print'):
            self.assertEqual(7, main(['--root', str(self.root), 'run', '--execute', '--selection', result['path'], '--suite', 'unit']))

    def test_stale_selection_rejected_before_runner(self):
        result = self.selection()
        (self.root / 'src/Policy.php').write_text('changed after selection')
        with self.assertRaisesRegex(FaultlineError, 'Checkout differs'):
            run_suite(self.store, result['path'], 'unit', execute=True)

    def test_framework_neutral_source_scoring_with_dirty_checkout_and_no_catalog(self):
        samples = {'features/access.feature': 'Feature: access\n Scenario Outline: allowed\n Given a policy\n Then access is granted\n Examples:\n | role |\n | editor |',
                   'browser/access.spec.ts': 'test("access", async ({page}) => { await page.goto("/access"); });',
                   'js/access.test.js': 'test("access", () => expect(allowed()).toBe(true));'}
        for name, content in samples.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.commit()
        base = self.git('rev-parse', 'HEAD').strip()
        (self.root / 'settings.yml').write_text('services: {access: restricted}')
        self.commit()
        head = self.git('rev-parse', 'HEAD').strip()
        # Local setup is intentionally uncommitted. Analysis reads requested Git objects.
        write_json(self.root / 'faultline.json', {'schema_version': 2, 'suites': [
            {'id': 'all', 'sources': ['tests/*.php', 'features/**/*.feature', 'browser/**/*.spec.ts', 'js/**/*.test.js']},
            {'id': 'empty', 'sources': ['absent/**/*.feature']}]})
        (self.root / 'features/access.feature').write_text('UNCOMMITTED SOURCE MUST NOT BE SENT')
        evaluator = BatchedJev(self.store, DEFAULT_EVALUATOR)
        requests = []
        class Transport:
            def request(inner, url, payload, **kw):
                evaluator.budget.take()
                requests.append(payload)
                return {'model': payload['model'], 'answers': {q: answer('direct' if t['source'].endswith('.feature') else 'irrelevant')
                        for q, t in zip(payload['questions'], payload['state']['tests'])}}, {}
        evaluator.http = Transport()
        with patch('faultline.tia.runners.invoke', side_effect=AssertionError('No runner allowed')):
            result = select(self.store, base, head, evaluator=evaluator, build_graphs=False)
            config = load_config(self.root)
        self.assertEqual('complete', result['semantic']['status'])
        self.assertEqual(5, result['semantic']['fully_scored'])
        self.assertGreater(result['usage']['requests'], 0)
        sent = json.dumps(requests)
        self.assertIn('Scenario Outline', sent)
        self.assertNotIn('UNCOMMITTED SOURCE', sent)
        self.assertEqual(head, self.git('rev-parse', 'HEAD').strip())
        frozen = checked(Path(result['path']))
        self.assertIn('all:default:features/access.feature', frozen['suites'][0]['proposed_selected'])
        self.assertEqual(4, result['proposed_omitted'])
        self.assertIn('no_configured_source_targets', frozen['suites'][1]['fallbacks'])
        with self.assertRaisesRegex(FaultlineError, 'clean checkout'):
            run_suite(self.store, result['path'], 'all', execute=True)
        catalog.sync(self.root, catalog.source_inventory(self.root, config))

    def outcomes(self, selection, complete=True):
        rows = [{'id': 'unit:default:tests/ATest.php', 'member': 'ATest::testA', 'status': 'passed', 'duration_seconds': 3},
                {'id': 'unit:default:tests/BTest.php', 'member': 'BTest::testB', 'status': 'failed', 'duration_seconds': 5,
                 'classification': 'confirmed_regression', 'evidence': 'Controlled fixture regression'}]
        return {'selection_id': selection['selection_id'], 'suite_key': 'unit:default', 'complete': complete, 'tests': rows}

    def test_report_miss_and_group_repeated_attempts(self):
        selection = self.selection()
        path = self.store.path / 'outcomes.json'
        write_json(path, self.outcomes(selection))
        for _ in range(2):
            receipt = run_suite(self.store, selection['path'], 'unit', execute=True)
            result = record(self.store, selection['path'], receipt['path'], path)
            self.assertEqual(0, result['metrics']['failing_change_recall'])
            self.assertEqual(0, result['metrics']['failing_test_recall'])
            self.assertEqual(5, result['metrics']['potential_serial_test_seconds_avoided'])
            self.assertEqual(0, result['metrics']['actual_execution_avoided_seconds'])
            self.assertTrue(Path(result['markdown']).exists())
        aggregate = report(self.store)
        self.assertEqual(1, len(aggregate['cases']))
        self.assertEqual(2, aggregate['cases'][0]['attempts'])
        self.assertEqual(1, next(iter(aggregate['policies'].values()))['eligible_regression_cases'])

    def test_missing_members_never_pass_and_duplicate_results_rejected(self):
        selection = self.selection()
        receipt = run_suite(self.store, selection['path'], 'unit', execute=True)
        path = self.store.path / 'outcomes.json'
        data = self.outcomes(selection)
        data['tests'] = data['tests'][1:]
        write_json(path, data)
        result = record(self.store, selection['path'], receipt['path'], path)
        self.assertFalse(result['metrics']['outcomes_complete'])
        self.assertIsNone(result['metrics']['potential_serial_test_seconds_avoided'])
        data['tests'] *= 2
        write_json(path, data)
        with self.assertRaises(FaultlineError):
            record(self.store, selection['path'], receipt['path'], path)

    def test_restored_artifacts_work_without_executable_or_model(self):
        other = self.root.parent / 'other'
        shutil.copytree(self.root, other)
        with patch('faultline.tia.graph.run', side_effect=AssertionError('Indexing must be cached')):
            reused = graph.build(Store(other), load_config(other), self.base)
        self.assertTrue(reused['cache_hit'])
        result = select(Store(other), self.base, evaluator=Evaluator(), build_graphs=False)
        self.assertEqual(1, result['proposed_omitted'])

    def test_classification_revision_preserves_raw_evidence_without_another_run(self):
        selection = self.selection()
        receipt = run_suite(self.store, selection['path'], 'unit', execute=True)
        path = self.store.path / 'classified.json'
        data = self.outcomes(selection)
        write_json(path, data)
        before = record(self.store, selection['path'], receipt['path'], path)
        data['tests'][1]['classification'] = 'flake'
        data['tests'][1]['evidence'] = 'Additional reproduction evidence'
        write_json(path, data)
        after = record(self.store, selection['path'], receipt['path'], path)
        self.assertNotEqual(before['observation_id'], after['observation_id'])
        aggregate = report(self.store)
        self.assertEqual(1, aggregate['observations'])
        self.assertEqual(2, aggregate['observation_revisions'])
        self.assertIsNone(aggregate['cases'][0]['failing_change_recall'])
        # Reverting a reviewed classification is a new revision, not a cache hit.
        data = self.outcomes(selection)
        write_json(path, data)
        restored = record(self.store, selection['path'], receipt['path'], path)
        self.assertNotEqual(before['observation_id'], restored['observation_id'])
        aggregate = report(self.store)
        self.assertEqual(1, aggregate['observations'])
        self.assertEqual(3, aggregate['observation_revisions'])
        self.assertEqual(0, aggregate['cases'][0]['failing_change_recall'])
        data['tests'][1]['status'] = 'passed'
        data['tests'][1]['classification'] = 'unknown'
        write_json(path, data)
        with self.assertRaisesRegex(FaultlineError, 'Raw execution'):
            record(self.store, selection['path'], receipt['path'], path)

    def test_missing_junit_produces_incomplete_report_and_native_members_import_exactly(self):
        selection = self.selection()
        receipt = run_suite(self.store, selection['path'], 'unit', execute=True)
        missing = record(self.store, selection['path'], receipt['path'], self.store.path / 'absent.xml', format='junit')
        self.assertFalse(missing['metrics']['outcomes_complete'])
        self.assertEqual(0, missing['metrics']['observed_members'])
        receipt = run_suite(self.store, selection['path'], 'unit', execute=True)
        path = self.store.path / 'native.xml'
        path.write_text('<testsuites><testsuite><testcase classname="ATest" name="testA" time="3"/><testcase classname="BTest" name="testB" time="5"><failure/></testcase></testsuite></testsuites>')
        native = record(self.store, selection['path'], receipt['path'], path, format='junit')
        self.assertTrue(native['metrics']['outcomes_complete'])
        self.assertIsNone(native['metrics']['failing_test_recall'])
        self.assertEqual(1, native['metrics']['unknown_failures'])

    def test_aggregate_requires_all_suites_and_counts_change_once(self):
        self.raw['suites'].append({**self.raw['suites'][0], 'id': 'other'})
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        self.config = load_config(self.root)
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.publish(self.head)
        selection = self.selection()
        receipts = [run_suite(self.store, selection['path'], name, execute=True) for name in ['unit', 'other']]
        for i, receipt in enumerate(receipts):
            data = self.outcomes(selection)
            prefix = ['unit', 'other'][i]
            data['suite_key'] = prefix + ':default'
            for row in data['tests']:
                row['id'] = row['id'].replace('unit:', prefix + ':', 1)
            path = self.store.path / ('outcomes-' + prefix + '.json')
            write_json(path, data)
            record(self.store, selection['path'], receipt['path'], path)
            aggregate = report(self.store)
            self.assertEqual(1, len(aggregate['cases']))
            self.assertEqual(i == 1, aggregate['cases'][0]['complete'])
        self.assertEqual(1, next(iter(aggregate['policies'].values()))['eligible_regression_cases'])

    def test_prerequisites_require_success_for_exact_selection(self):
        self.raw['suites'][0]['command'] = [sys.executable, '-c', 'pass']
        self.raw['suites'].append({**self.raw['suites'][0], 'id': 'other', 'prerequisites': ['unit']})
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        self.config = load_config(self.root)
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.publish(self.head)
        selection = self.selection()
        with self.assertRaisesRegex(FaultlineError, 'prerequisite'):
            run_suite(self.store, selection['path'], 'other', execute=True)
        first = run_suite(self.store, selection['path'], 'unit', execute=True)
        second = run_suite(self.store, selection['path'], 'other', prerequisites=[first['path']], execute=True)
        self.assertEqual(0, second['exit_code'])

    @unittest.skipUnless(os.environ.get('FAULTLINE_CODEGRAPH'), 'Set FAULTLINE_CODEGRAPH to the pinned executable for real producer conformance')
    def test_real_codegraph_build_reuse_and_exact_test_identity_join(self):
        base = graph.build(self.store, self.config, self.base, output=self.store.path / 'real-base')
        head = graph.build(self.store, self.config, self.head, reuse=base['path'], output=self.store.path / 'real-head')
        self.assertEqual(base['integrity'], head['reused_from'])
        selected = self.selection(base_graph=base['path'], head_graph=head['path'])
        value = checked(Path(selected['path']))
        self.assertIn('unit:default:tests/ATest.php', value['suites'][0]['proposed_selected'])
        self.assertTrue(value['graph']['paths']['tests/ATest.php'])
        self.assertFalse(value['graph']['fallbacks'])


class BatchTests(unittest.TestCase):
    def test_partial_responses_cache_independently_and_graph_inputs_invalidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp));store.initialize()
            context = {'diff': '+ changed', 'changed_files': ['src/a'], 'id': 'PR-1'}
            profiles = [{'id': n, 'source': n, 'description': n, 'graph_evidence': {'paths': []}} for n in ['a', 'b']]
            class Transport:
                def __init__(self): self.calls = 0
                def request(self, url, payload, **kw):
                    self.calls += 1
                    return {'model': DEFAULT_EVALUATOR['model'], 'answers': {'q0': answer(), 'q1': answer() if self.calls > 1 else {}},
                            'usage': {'input_tokens': 20, 'output_tokens': 0}}, {}
            transport = Transport()
            ev = BatchedJev(store, DEFAULT_EVALUATOR, transport=transport)
            first = ev.evaluate(context, profiles)
            self.assertFalse(first['complete']);self.assertIn('a', first['rows']);self.assertIn('b', first['errors'])
            second = ev.evaluate({**context, 'id': 'PR-2'}, profiles)
            self.assertTrue(second['complete']);self.assertEqual(1, second['cache_hits'])
            third = ev.evaluate(context, profiles)
            self.assertEqual(2, third['cache_hits']);self.assertEqual(2, transport.calls)
            old = identity(batches(context, profiles, DEFAULT_EVALUATOR)[0][0])
            profiles[0]['graph_evidence']['paths'] = ['changed']
            self.assertNotEqual(old, identity(batches(context, profiles, DEFAULT_EVALUATOR)[0][0]))

    def test_oversized_context_is_not_silently_truncated(self):
        requests, rejected = batches({'diff': 'x' * 50000}, [{'id': 'a', 'source': 'a', 'description': 'a'}], DEFAULT_EVALUATOR)
        self.assertEqual([], requests);self.assertEqual(['a'], rejected)


class SourceBatchTests(unittest.TestCase):
    def test_source_globs_preserve_directory_boundaries(self):
        from faultline.tia.evidence import match
        self.assertTrue(match('features/a.feature', 'features/**/*.feature'))
        self.assertTrue(match('features/deep/a.feature', 'features/**/*.feature'))
        self.assertFalse(match('features/deep/a.feature', 'features/*.feature'))
        self.assertFalse(match('other/a.feature', 'features/**/*.feature'))

    def test_large_utf8_evidence_deduplicates_variants_and_resumes_cache(self):
        from faultline.tia.evidence import text_parts
        text = 'Scenario: café 🧪\n' * 450
        self.assertEqual(text, ''.join(p['text'] for p in text_parts(text, 100)))
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            config = {**DEFAULT_EVALUATOR, 'jev_requests': 100}
            context = {'diff': '+ policy changed\n' * 700, 'changed_files': ['policy.yml']}
            profile = {'id': 'a', 'source': 'access.feature', 'description': '', 'source_text': text,
                       'graph_evidence': {}, 'execution_context': {}}
            profiles = [profile, {**profile, 'id': 'b'}]
            ev = BatchedJev(store, config)
            requests = []
            class Transport:
                def request(inner, url, payload, **kw):
                    ev.budget.take()
                    requests.append(payload)
                    return {'model': payload['model'], 'answers': {q: answer() for q in payload['questions']}}, {}
            ev.http = Transport()
            result = ev.evaluate_source(context, profiles)
            self.assertTrue(result['complete'])
            self.assertEqual(1, result['unique_evidence_targets'])
            self.assertGreater(result['diff_fragments'], 1)
            self.assertEqual(result['evidence_pairs'], sum(len(r['questions']) for r in requests))
            for request in requests:
                self.assertLessEqual(len(json.dumps(request, ensure_ascii=False).encode()), config['max_batch_bytes'])
                self.assertLessEqual(len(json.dumps(request['state'], ensure_ascii=False).encode()), config['max_state_bytes'])
            again = ev.evaluate_source(context, profiles)
            self.assertEqual(0, again['requests'])
            self.assertTrue(again['complete'])
            changed = ev.evaluate_source(context, [profile, {**profile, 'id': 'b', 'execution_context': {'args': ['--tag', 'other']}}], dry_run=True)
            self.assertEqual(2, changed['unique_evidence_targets'])

    def test_partial_evidence_and_zero_budget_never_establish_irrelevance(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = {'id': 'a', 'source': 'test.js', 'description': '', 'source_text': 'test code ' * 2000,
                       'graph_evidence': {}, 'execution_context': {}}
            config = {**DEFAULT_EVALUATOR, 'max_evidence_pairs': 1}
            ev = BatchedJev(Store(Path(tmp)), config)
            class Transport:
                def request(inner, url, payload, **kw):
                    ev.budget.take()
                    return {'model': payload['model'], 'answers': {q: answer() for q in payload['questions']}}, {}
            ev.http = Transport()
            context = {'diff': '+ change', 'changed_files': ['a']}
            result = ev.evaluate_source(context, [profile])
            self.assertFalse(result['complete'])
            self.assertIsNone(result['rows']['a']['all_parts_irrelevant_probability'])
            self.assertIn('budget exhausted', result['errors']['a'])
            zero = BatchedJev(Store(Path(tmp) / 'fresh'), {**config, 'jev_requests': 0}).evaluate_source(context, [profile])
            self.assertEqual({}, zero['rows'])
            self.assertFalse(zero['complete'])
            self.assertIn('budget exhausted', zero['errors']['a'])
