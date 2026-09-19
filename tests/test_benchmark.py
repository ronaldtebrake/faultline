import copy
import json
import os
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import test_graph_pipeline as fixture
from faultline.cli import main
from faultline.core import FaultlineError, write_json
from faultline.tia.batch import BatchedJev
from faultline.tia.benchmark import benchmark, render
from faultline.tia.benchmark_results import assess
from faultline.tia.common import checked
from faultline.tia.config import load_config
from faultline.tia.selection import select
from faultline.tia import graph


class BenchmarkTests(unittest.TestCase):
    setUp = fixture.GraphPipelineTests.setUp
    git = fixture.GraphPipelineTests.git
    commit = fixture.GraphPipelineTests.commit
    publish = fixture.GraphPipelineTests.publish

    def engine(self, limit=100):
        config = {**self.config['evaluator'], 'jev_requests': limit}
        engine = BatchedJev(self.store, config)
        calls = []
        class Transport:
            def request(inner, url, payload, **kw):
                engine.budget.take()
                calls.append(payload)
                targets = [q['instructions']['test'] for q in payload['questions'].values()] if isinstance(next(iter(payload['questions'].values()))['instructions'], dict) else payload['state']['tests']
                hybrid = any(t.get('graph_evidence') for t in targets)
                answers = {}
                for i, t in enumerate(targets):
                    level = ('strong' if t['source'].endswith('ATest.php') else 'weak') if hybrid else ('strong' if t['source'].endswith('BTest.php') else 'irrelevant')
                    answers[f'q{i}'] = fixture.answer(level)
                return {'model': config['model'], 'answers': answers, 'usage': {'input_tokens': 20, 'output_tokens': 0}}, {}
        engine.http = Transport()
        return engine, calls

    def run_benchmark(self, **kw):
        engine, calls = self.engine(kw.pop('limit', 100))
        with patch('faultline.tia.runners.invoke', side_effect=AssertionError('No runner in benchmark')):
            result = benchmark(self.store, self.base, build_graphs=False, evaluator=engine, **kw)
        return result, calls

    def test_three_policies_share_population_and_score_graph_disconnected_targets(self):
        result, calls = self.run_benchmark()
        case = checked(Path(result['json']), 'benchmark')
        self.assertTrue(case['complete'])
        self.assertEqual(2, result['usage']['requests'])
        a, b = ('unit:default:tests/' + n + 'Test.php' for n in ('A', 'B'))
        self.assertEqual([a], case['policies']['codegraph']['would_run'])
        self.assertEqual([b], case['policies']['jev']['would_run'])
        self.assertEqual([a, b], case['policies']['hybrid']['would_run'])
        self.assertEqual(2, len(calls))
        self.assertEqual([t['id'] for t in calls[0]['state']['tests']], [t['id'] for t in calls[1]['state']['tests']])
        self.assertTrue(all(not t['graph_evidence'] for t in calls[0]['state']['tests']))
        self.assertTrue(all(t['graph_evidence'] for t in calls[1]['state']['tests']))
        for request in calls:
            self.assertEqual(case['change']['diff'], request['state']['change']['diff'])
            for test in request['state']['tests']:
                self.assertEqual((self.root / test['source']).read_text(), test['source_evidence']['text'])
        self.assertFalse((self.store.path / 'batch-cache').exists())
        self.assertTrue((self.store.path / 'jev-cache.sqlite').is_file())
        self.assertEqual(2, len(list((self.store.path / 'benchmarks').iterdir())))
        self.assertFalse((self.store.path / 'runs').exists())
        again, more_calls = self.run_benchmark()
        self.assertTrue(again['complete'])
        self.assertEqual([], more_calls)
        self.assertEqual(0, again['usage']['requests'])
        with patch('subprocess.run', side_effect=AssertionError('Regeneration is offline')):
            render(result['json'])

    def test_both_arms_share_one_request_limit_and_keep_pending_would_run(self):
        before = (self.root / 'faultline.json').read_bytes()
        result, calls = self.run_benchmark(limit=1)
        case = checked(Path(result['json']))
        self.assertEqual(1, len(calls))
        self.assertEqual(1, result['usage']['requests'])
        self.assertFalse(result['complete'])
        self.assertEqual(2, len(case['policies']['hybrid']['unresolved']))
        self.assertEqual(2, len(case['policies']['hybrid']['would_run']))
        self.assertEqual(before, (self.root / 'faultline.json').read_bytes())
        resumed, more = self.run_benchmark(limit=1)
        self.assertEqual(1, len(more))
        self.assertTrue(resumed['complete'])

    def test_prepare_and_graph_only_need_no_jev_or_native_runtime(self):
        with patch('faultline.tia.batch.api_key', side_effect=AssertionError('No key needed')), patch('faultline.network.HTTP.request', side_effect=AssertionError('No API')), patch('faultline.tia.runners.invoke', side_effect=AssertionError('No runners')):
            plan = benchmark(self.store, self.base, build_graphs=False, prepare=True, max_requests=1)
            self.assertEqual(2, plan['total_uncached_requests'])
            self.assertEqual(1, plan['shared_request_ceiling'])
            with patch('faultline.tia.selection.test_profile', side_effect=AssertionError('No Jev evidence construction')):
                result = select(self.store, self.base, build_graphs=False, graph_only=True)
                self.assertEqual('codegraph_only', result['analysis_mode'])
                self.assertEqual(0, result['usage']['requests'])
                self.assertEqual(1, result['proposed_selected'])
                report = checked(Path(result['report']['json']))
                self.assertFalse(report['graph_comparison']['available'])
            with patch('builtins.print'):
                self.assertEqual(0, main(['--root', str(self.root), 'select', '--base', self.base, '--no-build', '--graph-only']))
        self.assertFalse((self.store.path / 'jev-cache.sqlite').exists())

    def test_reference_refuses_arbitrary_fragmentation(self):
        (self.root / 'tests/BTest.php').write_text('<?php /* ' + 'large test evidence ' * 4000 + ' */')
        self.commit()
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.publish(self.head)
        result, calls = self.run_benchmark()
        self.assertFalse(result['complete'])
        case = checked(Path(result['json']))
        for arm in ('jev', 'hybrid'):
            self.assertIn('unit:default:tests/BTest.php', case['policies'][arm]['unresolved'])
            self.assertTrue(any('no truncation' in error for error in case['policies'][arm]['errors'].values()))
        self.assertEqual([], calls)  # The cumulative diff alone also exceeds this fixture's bound.

    def test_graph_failure_is_visible_but_does_not_hide_jev_candidates(self):
        (self.artifacts[0] / 'graph.sqlite').write_bytes(b'corrupt')
        result, calls = self.run_benchmark()
        case = checked(Path(result['json']))
        self.assertFalse(result['complete'])
        self.assertEqual(2, len(case['policies']['codegraph']['would_run']))
        self.assertEqual(2, len(case['policies']['jev']['judgments']))
        self.assertEqual(2, len(case['policies']['hybrid']['judgments']))

    def outcomes(self, case):
        ids = case['policies']['codegraph']['ranking']
        return {'schema_version': 2, 'benchmark_id': case['integrity'], 'repository': case['repository'],
                'base': case['change']['base'], 'head': case['change']['head'], 'attempt_id': 'ci-attempt-1',
                'outcome_blind': True, 'complete': True, 'inventory': {id: [id + '::test'] for id in ids},
                'tests': [{'unit_id': id, 'test_id': id + '::test', 'status': 'failed' if id.endswith('BTest.php') else 'passed',
                           'failure_kind': 'regression' if id.endswith('BTest.php') else None,
                           'evidence': 'Confirmed application assertion regression', 'duration_seconds': 3} for id in ids]}

    def test_outcomes_measure_jev_incremental_detection_and_equal_unit_rankings(self):
        result, _ = self.run_benchmark()
        case = checked(Path(result['json']))
        path = self.store.path / 'ci-outcomes.json'
        write_json(path, self.outcomes(case))
        with patch('subprocess.run', side_effect=AssertionError('Outcome import must stay offline')):
            measured = assess(self.store, result['json'], path)
        self.assertTrue(measured['eligible_for_recall'])
        self.assertEqual(0, measured['policies']['codegraph']['failing_test_recall'])
        self.assertEqual(1, measured['policies']['jev']['failing_test_recall'])
        self.assertEqual(1, measured['policies']['hybrid']['failing_test_recall'])
        self.assertEqual(1, measured['policies']['jev']['raw_ranking_recall_at_units']['1'])
        assessment = checked(Path(measured['json']))
        self.assertEqual(['jev', 'hybrid'], assessment['regression_detections'][0]['caught_by'])
        self.assertIsNone(assessment['measured_ci_savings_seconds'])
        self.assertEqual(1, assessment['failure_counts']['regression'])
        self.assertEqual(3, measured['policies']['codegraph']['potential_serial_test_seconds_avoided'])
        markdown = Path(measured['markdown']).read_text()
        self.assertIn('infrastructure: 0', markdown)
        self.assertIn('Potential serial test work avoided', markdown)
        data = self.outcomes(case)
        data['head'] = self.base
        write_json(path, data)
        with self.assertRaisesRegex(FaultlineError, 'mismatch'):
            assess(self.store, result['json'], path)

    def test_incomplete_outcomes_and_contaminated_cases_do_not_claim_recall(self):
        result, _ = self.run_benchmark()
        case = checked(Path(result['json']))
        path = self.store.path / 'ci-outcomes.json'
        for variant in ('missing', 'unmatched', 'contaminated', 'green'):
            data = self.outcomes(case)
            if variant == 'missing':
                data['tests'].pop()
            elif variant == 'unmatched':
                data['tests'][-1]['unit_id'] = 'missing-unit'
            elif variant == 'contaminated':
                data['outcome_blind'] = False
            else:
                for row in data['tests']:
                    row.update(status='passed', failure_kind=None)
            write_json(path, data)
            observed = assess(self.store, result['json'], path)
            self.assertTrue(all(p['failing_test_recall'] is None for p in observed['policies'].values()))

    def test_semantic_policies_can_narrow_a_graph_hint(self):
        engine, calls = self.engine()
        class Irrelevant:
            def request(inner, url, payload, **kw):
                engine.budget.take()
                return {'model': engine.config['model'], 'answers': {q: fixture.answer() for q in payload['questions']}}, {}
        engine.http = Irrelevant()
        result = benchmark(self.store, self.base, build_graphs=False, evaluator=engine)
        case = checked(Path(result['json']))
        self.assertEqual(1, len(case['policies']['codegraph']['would_run']))
        self.assertEqual([], case['policies']['jev']['would_run'])
        self.assertEqual([], case['policies']['hybrid']['would_run'])

    def test_gherkin_source_without_graph_nodes_is_assessed_in_both_arms(self):
        path = self.root / 'features/access.feature'
        path.parent.mkdir()
        path.write_text('Feature: Access\n Scenario: Denied\n Then access is denied\n')
        self.raw['suites'].append({'id': 'behavior', 'sources': ['features/**/*.feature']})
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.config = load_config(self.root)
        self.publish(self.head)
        result, calls = self.run_benchmark()
        case = checked(Path(result['json']))
        id = 'behavior:default:features/access.feature'
        for arm in ('jev', 'hybrid'):
            self.assertIn(id, case['policies'][arm]['judgments'])
        self.assertTrue(all(any(t['source_evidence']['text'] == path.read_text() for t in request['state']['tests']) for request in calls))

    def test_compaction_preserves_answers_and_leaves_unknown_files(self):
        from faultline.tia.cache import AnswerCache
        from faultline.tia.common import save_frozen
        cache = AnswerCache(self.store)
        key = 'a' * 64
        value = {'schema_version': 2, 'kind': 'jev-answer', 'request_key': key, 'question_id': 'q0',
                 'model': self.config['evaluator']['model'], 'answer': fixture.answer(), 'created_at': 'fixture'}
        old = cache.legacy / key / 'q0.json'
        save_frozen(old, value)
        unknown = cache.legacy / ('b' * 64) / 'notes.txt'
        unknown.parent.mkdir(parents=True)
        unknown.write_text('unrecognized content')
        before = cache.get(key, 'q0')
        result = cache.compact()
        self.assertEqual(1, result['imported_answers'])
        self.assertEqual(1, result['removed_files'])
        self.assertEqual(1, result['skipped_batches'])
        self.assertFalse(old.exists())
        self.assertTrue(unknown.exists())
        self.assertEqual(before, cache.get(key, 'q0'))
        with self.assertRaisesRegex(FaultlineError, 'replace'):
            cache.put({**value, 'answer': fixture.answer('strong')})

    def test_cli_reference_preflight_and_partial_exit_codes(self):
        with patch('builtins.print'), patch('faultline.tia.batch.api_key', side_effect=AssertionError('No inference allowed')):
            self.assertEqual(0, main(['--root', str(self.root), 'benchmark', '--base', self.base, '--no-build', '--prepare']))
            self.assertEqual(2, main(['--root', str(self.root), 'benchmark', '--base', self.base, '--no-build', '--max-requests', '0', '--title', 'Pre-outcome intent']))
        case = checked(next((self.store.path / 'benchmarks').glob('*.json')))
        self.assertEqual('Pre-outcome intent', case['change']['title'])
        self.assertEqual(0, case['usage']['requests'])

    def test_empty_inventory_never_looks_like_permission_to_run_zero_tests(self):
        self.raw['suites'].append({'id': 'missing', 'sources': ['absent/**/*.feature']})
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.config = load_config(self.root)
        self.publish(self.head)
        result, calls = self.run_benchmark()
        case = checked(Path(result['json']))
        self.assertFalse(case['complete'])
        for policy in case['policies'].values():
            self.assertIn('missing:default', policy['full_suites'])
        self.assertIn('missing:default', Path(result['markdown']).read_text())

    def test_cache_corruption_cannot_become_an_irrelevance_judgment(self):
        self.run_benchmark()
        with sqlite3.connect(self.store.path / 'jev-cache.sqlite') as db:
            db.execute("UPDATE answers SET value='{}'")
        result, calls = self.run_benchmark()
        self.assertFalse(result['complete'])
        self.assertEqual([], calls)
        case = checked(Path(result['json']))
        self.assertEqual(2, len(case['policies']['jev']['would_run']))


    def test_blocked_preparation_exits_nonzero_and_exposes_input_sizes(self):
        from faultline.tia.selection import change
        context = change(self.root, self.base, self.head)
        context['diff'] = 'diff --git a/large.txt b/large.txt\n' + '+' + 'x' * 70000
        with patch('faultline.tia.benchmark.change', return_value=context), patch('faultline.tia.batch.api_key', side_effect=AssertionError('No API')):
            result = benchmark(self.store, self.base, build_graphs=False, prepare=True)
            self.assertFalse(result['complete'])
            self.assertFalse(result['preparation']['ready'])
            self.assertEqual({'jev': 0, 'hybrid': 0}, result['preparation']['eligible_targets'])
            self.assertGreater(result['preparation']['input_sizes']['diff_bytes'], 70000)
            with patch('builtins.print'):
                self.assertEqual(2, main(['--root', str(self.root), 'benchmark', '--base', self.base, '--no-build', '--prepare']))

    def test_file_pair_questions_share_only_change_and_keep_whole_tests(self):
        result, calls = self.run_benchmark(evidence_mode='file-pairs')
        case = checked(Path(result['json']))
        self.assertEqual('reference-file-pairs-v1', case['contract'])
        self.assertTrue(case['complete'])
        self.assertEqual(2, len(calls))
        for request in calls:
            self.assertTrue(all(set(t) == {'id', 'source'} for t in request['state']['tests']))
            for question in request['questions'].values():
                target = question['instructions']['test']
                self.assertEqual((self.root / target['source']).read_text(), target['source_evidence']['text'])
                self.assertFalse(target['execution_context']['setup_bodies_supplied'])
        for arm in ('jev', 'hybrid'):
            self.assertEqual(2, len(case['policies'][arm]['judgments']))
            self.assertTrue(all(row['evidence_complete'] for row in case['policies'][arm]['judgments'].values()))

    def test_file_pairs_keep_every_changed_section_and_resume_exact_inputs(self):
        from faultline.tia.selection import change
        context = change(self.root, self.base, self.head)
        sections = [f'diff --git a/src/Part{i}.php b/src/Part{i}.php\n@@ -1 +1 @@\n-' + 'a' * 1800 + '\n+' + 'b' * 1800 + '\n' for i in range(20)]
        context['diff'] = ''.join(sections)
        with patch('faultline.tia.benchmark.change', return_value=context):
            first, calls = self.run_benchmark(evidence_mode='file-pairs', limit=1)
            partial = checked(Path(first['json']))
            self.assertFalse(first['complete'])
            self.assertEqual(1, len(calls))
            self.assertEqual(2, len(partial['policies']['jev']['would_run']))
            result, resumed_calls = self.run_benchmark(evidence_mode='file-pairs')
        case = checked(Path(result['json']))
        self.assertTrue(result['complete'])
        self.assertGreater(len(resumed_calls), 0)
        for arm in ('jev', 'hybrid'):
            for row in case['policies'][arm]['judgments'].values():
                spans = sorted((part['change_window']['start_char'], part['change_window']['end_char']) for part in row['parts'])
                self.assertEqual(0, spans[0][0])
                self.assertEqual(len(context['diff']), spans[-1][1])
                self.assertTrue(all(a[1] == b[0] for a, b in zip(spans, spans[1:])))
                self.assertEqual(context['diff'], ''.join(context['diff'][start:end] for start, end in spans))
                self.assertTrue(all(context['diff'][start:end].startswith('diff --git ') for start, end in spans))
        for request in calls + resumed_calls:
            self.assertLessEqual(len(json.dumps(request, ensure_ascii=False).encode()), self.config['evaluator']['max_batch_bytes'])
            state = len(json.dumps(request['state'], ensure_ascii=False).encode())
            longest = max(len(json.dumps(q, ensure_ascii=False).encode()) for q in request['questions'].values())
            self.assertLessEqual(state + longest, self.config['evaluator']['max_state_bytes'])

    def test_file_pairs_do_not_read_bulk_setup_implementations(self):
        (self.root / 'setup.php').write_text('<?php /*' + 'setup content ' * 25000 + '*/')
        self.raw['suites'][0]['description_inputs'] = ['setup.php']
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.config = load_config(self.root)
        self.publish(self.head)
        result, calls = self.run_benchmark(evidence_mode='file-pairs')
        # The large setup addition is a single oversized changed-file section:
        # it must stay blocked rather than being silently excluded from the diff.
        self.assertFalse(result['complete'])
        self.assertEqual([], calls)
        with patch('faultline.tia.benchmark.change', return_value={
                'id': 'fixture', 'base': self.base, 'head': self.head, 'changed_files': ['src/Policy.php'],
                'diff': 'diff --git a/src/Policy.php b/src/Policy.php\n@@ -1 +1 @@\n-true\n+false\n', 'title': '', 'description': ''}):
            result, calls = self.run_benchmark(evidence_mode='file-pairs')
        self.assertGreater(len(calls), 0)
        self.assertTrue(all('setup content ' not in json.dumps(request) for request in calls))
        self.assertTrue(all(q['instructions']['test']['execution_context']['setup_source_count'] == 1 for request in calls for q in request['questions'].values()))

    def test_graph_budget_is_checked_before_archive_export(self):
        from faultline.tia.graph import extract
        settings = {**self.config['graph'], 'max_source_bytes': 1}
        with patch('faultline.tia.graph.subprocess.run', wraps=__import__('subprocess').run) as invoked:
            with self.assertRaisesRegex(FaultlineError, 'no archive was exported'):
                extract(self.root, self.head, self.root / 'snapshot', settings)
        self.assertFalse(any('archive' in call.args[0] for call in invoked.call_args_list))
        self.assertFalse((self.root / 'source.tar').exists())

    @unittest.skipUnless(os.environ.get('FAULTLINE_CODEGRAPH'), 'Requires the pinned CodeGraph executable')
    def test_fresh_baselines_do_not_seed_from_an_existing_graph(self):
        fresh = graph.build(self.store, self.config, self.base, fresh=True)
        self.assertEqual('fresh', fresh['build_mode'])
        self.assertIsNone(fresh['reused_from'])
        self.assertNotEqual(self.artifacts[0], Path(fresh['path']))
        restored = graph.build(self.store, self.config, self.base, fresh=True)
        self.assertTrue(restored['cache_hit'])
        with self.assertRaisesRegex(FaultlineError, 'cannot reuse'):
            graph.build(self.store, self.config, self.head, fresh=True, reuse=fresh['path'])
