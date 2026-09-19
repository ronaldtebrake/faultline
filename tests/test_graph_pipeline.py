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

    def test_graph_positive_match_is_mandatory_and_jev_gets_paths(self):
        evaluator = Evaluator()
        result = self.selection(evaluator)
        value = checked(Path(result['path']))
        suite = value['suites'][0]
        self.assertEqual(['unit:default:tests/ATest.php'], suite['proposed_selected'])
        self.assertEqual(['unit:default:tests/BTest.php'], suite['proposed_omitted'])
        self.assertEqual('full', suite['execution'])
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

    def test_missing_or_corrupt_graph_and_traversal_budget_fall_back(self):
        (self.artifacts[0] / 'graph.sqlite').write_bytes(b'corrupt')
        result = self.selection()
        self.assertEqual(0, result['proposed_omitted'])
        self.assertIn('missing_invalid_or_incompatible_base_graph', result['fallbacks']['unit:default'])
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
        self.assertIn('semantic_evaluation_incomplete', result['fallbacks']['unit:default'])
        receipt = run_suite(self.store, result['path'], 'unit')
        self.assertEqual(7, receipt['exit_code'])
        self.assertEqual('full_shadow', receipt['mode'])
        with patch('builtins.print'):
            self.assertEqual(7, main(['--root', str(self.root), 'run', '--selection', result['path'], '--suite', 'unit']))

    def test_stale_selection_rejected_before_runner(self):
        result = self.selection()
        (self.root / 'src/Policy.php').write_text('changed after selection')
        with self.assertRaisesRegex(FaultlineError, 'Checkout differs'):
            run_suite(self.store, result['path'], 'unit')

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
            receipt = run_suite(self.store, selection['path'], 'unit')
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
        receipt = run_suite(self.store, selection['path'], 'unit')
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
        receipt = run_suite(self.store, selection['path'], 'unit')
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
        receipt = run_suite(self.store, selection['path'], 'unit')
        missing = record(self.store, selection['path'], receipt['path'], self.store.path / 'absent.xml', format='junit')
        self.assertFalse(missing['metrics']['outcomes_complete'])
        self.assertEqual(0, missing['metrics']['observed_members'])
        receipt = run_suite(self.store, selection['path'], 'unit')
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
        receipts = [run_suite(self.store, selection['path'], name) for name in ['unit', 'other']]
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
            run_suite(self.store, selection['path'], 'other')
        first = run_suite(self.store, selection['path'], 'unit')
        second = run_suite(self.store, selection['path'], 'other', prerequisites=[first['path']])
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
