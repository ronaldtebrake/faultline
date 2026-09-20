import copy
import csv
import json
import os
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import test_source_pipeline as fixture
from faultline.cli import main
from faultline.core import FaultlineError, write_json
from faultline.tia.batch import BatchedJev
from faultline.tia.benchmark import benchmark, render
from faultline.tia.benchmark_results import assess
from faultline.tia.common import checked
from faultline.tia.config import load_config
from faultline.tia.selection import select


class BenchmarkTests(unittest.TestCase):
    setUp = fixture.SourcePipelineTests.setUp
    git = fixture.SourcePipelineTests.git
    commit = fixture.SourcePipelineTests.commit

    def engine(self, limit=100):
        config = {**self.config['evaluator'], 'jev_requests': limit}
        engine = BatchedJev(self.store, config)
        calls = []
        class Transport:
            def request(inner, url, payload, **kw):
                engine.budget.take()
                calls.append(payload)
                targets = [q['instructions']['test'] for q in payload['questions'].values()] if isinstance(next(iter(payload['questions'].values()))['instructions'], dict) else payload['state']['tests']
                answers = {}
                for i, t in enumerate(targets):
                    level = ('strong' if t['source'].endswith('BTest.php') else 'irrelevant')
                    answers[f'q{i}'] = fixture.answer(level)
                return {'model': config['model'], 'answers': answers, 'usage': {'input_tokens': 20, 'output_tokens': 0}}, {}
        engine.http = Transport()
        return engine, calls

    def run_benchmark(self, **kw):
        kw.setdefault('evidence_mode', 'whole')
        engine, calls = self.engine(kw.pop('limit', 100))
        with patch('faultline.tia.runners.invoke', side_effect=AssertionError('No runner in benchmark')):
            result = benchmark(self.store, self.base, evaluator=engine, **kw)
        return result, calls




    def test_reference_refuses_arbitrary_fragmentation(self):
        (self.root / 'tests/BTest.php').write_text('<?php /* ' + 'large test evidence ' * 4000 + ' */')
        self.commit()
        self.head = self.git('rev-parse', 'HEAD').strip()
        result, calls = self.run_benchmark()
        self.assertFalse(result['complete'])
        case = checked(Path(result['json']))
        for arm in ('jev',):
            self.assertIn('unit:default:tests/BTest.php', case['policies'][arm]['unresolved'])
            self.assertTrue(any('no truncation' in error for error in case['policies'][arm]['errors'].values()))
        self.assertEqual([], calls)  # The cumulative diff alone also exceeds this fixture's bound.


    def outcomes(self, case):
        ids = case['policies']['jev']['ranking']
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
        self.assertEqual(1, measured['policies']['jev']['failing_test_recall'])
        self.assertEqual(1, measured['policies']['jev']['failing_test_recall'])
        self.assertEqual(1, measured['policies']['jev']['raw_ranking_recall_at_units']['1'])
        assessment = checked(Path(measured['json']))
        self.assertEqual(['jev'], assessment['regression_detections'][0]['caught_by'])
        self.assertIsNone(assessment['measured_ci_savings_seconds'])
        self.assertEqual(1, assessment['failure_counts']['regression'])
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

    def test_unknown_failures_stay_visible_without_claiming_regression_recall(self):
        result, _ = self.run_benchmark()
        case = checked(Path(result['json']))
        data = self.outcomes(case)
        data['complete'] = False
        data['tests'] = [t for t in data['tests'] if t['status'] == 'failed']
        data['tests'][0]['failure_kind'] = 'unknown'
        data['tests'][0]['evidence'] = 'Assertion failed; cause not established'
        path = self.store.path / 'partial-outcomes.json'
        write_json(path, data)
        measured = assess(self.store, result['json'], path)
        assessment = checked(Path(measured['json']))
        self.assertFalse(measured['eligible_for_recall'])
        self.assertEqual([], assessment['regression_detections'])
        self.assertEqual(1, assessment['unknown_failures'])
        self.assertEqual({'jev': 'RUN'},
                         assessment['observed_failure_detections'][0]['actions'])
        self.assertIn('Observed failed tests', Path(measured['markdown']).read_text())
        self.assertTrue(all(p['failing_test_recall'] is None for p in measured['policies'].values()))
        data['tests'][0]['unit_id'] = 'unmapped-unit'
        write_json(path, data)
        unmapped = checked(Path(assess(self.store, result['json'], path)['json']))
        self.assertEqual({'UNMAPPED'}, set(unmapped['observed_failure_detections'][0]['actions'].values()))

    def test_jev_can_omit_all_nonmandatory_targets(self):
        engine, calls = self.engine()
        class Irrelevant:
            def request(inner, url, payload, **kw):
                engine.budget.take()
                return {'model': engine.config['model'], 'answers': {q: fixture.answer() for q in payload['questions']}}, {}
        engine.http = Irrelevant()
        result = benchmark(self.store, self.base, evaluator=engine)
        case = checked(Path(result['json']))
        self.assertEqual([], case['policies']['jev']['would_run'])
        self.assertEqual([], case['policies']['jev']['would_run'])

    def test_gherkin_source_is_assessed(self):
        path = self.root / 'features/access.feature'
        path.parent.mkdir()
        path.write_text('Feature: Access\n Scenario: Denied\n Then access is denied\n')
        self.raw['suites'].append({'id': 'behavior', 'sources': ['features/**/*.feature']})
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.config = load_config(self.root)
        result, calls = self.run_benchmark()
        case = checked(Path(result['json']))
        id = 'behavior:default:features/access.feature'
        for arm in ('jev',):
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
            self.assertEqual(0, main(['--root', str(self.root), 'benchmark', '--base', self.base, '--prepare']))
            self.assertEqual(2, main(['--root', str(self.root), 'benchmark', '--base', self.base, '--max-requests', '0', '--title', 'Pre-outcome intent']))
        case = checked(next((self.store.path / 'benchmarks').glob('*.json')))
        self.assertEqual('Pre-outcome intent', case['change']['title'])
        self.assertEqual(0, case['usage']['requests'])

    def test_empty_inventory_never_looks_like_permission_to_run_zero_tests(self):
        self.raw['suites'].append({'id': 'missing', 'sources': ['absent/**/*.feature']})
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.config = load_config(self.root)
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
            result = benchmark(self.store, self.base, prepare=True)
            self.assertFalse(result['complete'])
            self.assertFalse(result['preparation']['ready'])
            self.assertEqual({'jev': 0}, result['preparation']['eligible_targets'])
            self.assertGreater(result['preparation']['input_sizes']['diff_bytes'], 70000)
            with patch('builtins.print'):
                self.assertEqual(2, main(['--root', str(self.root), 'benchmark', '--base', self.base, '--prepare']))

    def test_file_pair_questions_share_only_change_and_keep_whole_tests(self):
        result, calls = self.run_benchmark(evidence_mode='file-pairs')
        case = checked(Path(result['json']))
        self.assertEqual('reference-file-pairs-v1', case['contract'])
        self.assertTrue(case['complete'])
        self.assertEqual(1, len(calls))
        for request in calls:
            self.assertTrue(all(set(t) == {'id', 'source'} for t in request['state']['tests']))
            for question in request['questions'].values():
                target = question['instructions']['test']
                self.assertEqual((self.root / target['source']).read_text(), target['source_evidence']['text'])
                self.assertFalse(target['execution_context']['setup_bodies_supplied'])
        for arm in ('jev',):
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
        for arm in ('jev',):
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



    def test_source_mode_sends_full_change_with_independent_whole_targets(self):
        result, calls = self.run_benchmark(evidence_mode='source')
        case = checked(Path(result['json']))
        self.assertEqual('reference-source-v1', case['contract'])
        self.assertEqual(1, len(calls))
        for request in calls:
            self.assertEqual(case['change']['diff'], request['state']['change']['diff'])
            self.assertTrue(request['state']['change']['diff_evidence']['is_whole'])
            self.assertNotIn('source_evidence', request['state']['tests'][0])
            for q in request['questions'].values():
                target = q['instructions']['test']
                self.assertEqual((self.root / target['source']).read_text(), target['source_evidence']['text'])
                self.assertFalse(target['execution_context']['setup_bodies_supplied'])
        again, requests = self.run_benchmark(evidence_mode='source')
        self.assertEqual([], requests)
        self.assertEqual(2, sum(p['cache_hits'] for a, p in checked(Path(again['json']))['policies'].items()))

    def test_source_byte_overrides_do_not_edit_configuration(self):
        before = (self.root / 'faultline.json').read_bytes()
        result, calls = self.run_benchmark(evidence_mode='source', max_state_bytes=100, max_batch_bytes=200)
        self.assertEqual([], calls)
        self.assertEqual('blocked', result['preparation']['status'])
        self.assertEqual(before, (self.root / 'faultline.json').read_bytes())
        for arm in ('jev',):
            self.assertEqual({'retained': 0, 'required': 0, 'unresolved': 2, 'omit': 0}, result['decisions'][arm])

    def test_unresolved_is_not_an_assessed_recommendation(self):
        result, calls = self.run_benchmark(evidence_mode='source', limit=0)
        case = checked(Path(result['json']))
        policy = case['policies']['jev']
        groups = [set(ids) for ids in policy['decision_groups'].values()]
        self.assertEqual(set(policy['ranking']), set.union(*groups))
        self.assertEqual(len(policy['ranking']), sum(map(len, groups)))
        self.assertEqual(2, len(policy['would_run']))
        self.assertEqual([], policy['retained'])
        self.assertEqual(2, result['decisions']['jev']['unresolved'])
        self.assertEqual([], calls)

    def test_source_mode_assesses_gherkin(self):
        feature = self.root / 'features/search.feature'
        feature.parent.mkdir()
        text = 'Feature: Search\n  Background:\n    Given a signed in reader\n  Scenario Outline: Find records\n    When I search for <query>\n    Then I see <result>\n    Examples:\n      | query | result |\n      | cats | pets |\n'
        feature.write_text(text)
        self.raw['suites'].append({'id': 'behavior', 'runner': 'behat', 'sources': ['features/**/*.feature']})
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.config = load_config(self.root)
        result, calls = self.run_benchmark(evidence_mode='source')
        supplied = [q['instructions']['test'] for r in calls for q in r['questions'].values() if q['instructions']['test']['source'].endswith('.feature')]
        self.assertEqual(1, len(supplied))
        self.assertTrue(all(t['source_evidence']['text'] == text for t in supplied))
        case = checked(Path(result['json']))
        for arm in ('jev',):
            self.assertIn(supplied[0]['id'], case['policies'][arm]['judgments'])
            self.assertIn(supplied[0]['id'], case['policies'][arm]['required'])


    def test_report_prices_each_arm_without_mutating_frozen_evidence(self):
        result, _ = self.run_benchmark()
        before = Path(result['json']).read_bytes()
        price = {'model': self.config['evaluator']['model'], 'as_of': '2026-09-20', 'input_usd_per_million': 1, 'source': 'https://example.org/pricing'}
        with patch('faultline.network.HTTP.request', side_effect=AssertionError('Offline report only')):
            report = render(result['json'], pricing=price, output=self.store.path / 'decision-review.md')
        self.assertEqual(before, Path(result['json']).read_bytes())
        for arm in ('jev',):
            m = report['routing']['policies'][arm]
            self.assertEqual(20, m['input_tokens'])
            self.assertAlmostEqual(.00002, m['input_usd_estimate'])
        text = Path(report['markdown']).read_text()
        self.assertNotIn('recommended', text)
        self.assertIn('Input tokens: **20**', text)
        self.assertIn('report override', text)
        self.assertTrue(Path(report['csv']).is_file())
        self.assertEqual(before, Path(result['json']).read_bytes())

    def test_missing_usage_and_retry_costs_remain_unknown(self):
        from faultline.tia.benchmark_report import usage_metrics
        price = {'input_usd_per_million': 1}
        for records in ([{'input_tokens': 100}], [{'input_tokens': 100}, None]):
            m = usage_metrics({'requests': 2, 'usage': records}, price)
            self.assertIsNone(m['input_tokens'])
            self.assertIsNone(m['input_usd_estimate'])
            self.assertEqual(100, m['reported_input_tokens'])
        m = usage_metrics({'requests': 0, 'usage': [], 'cache_hits': 5}, None)
        self.assertEqual(0, m['input_usd_estimate'])
        self.assertEqual(5, m['cache_hits'])

    def test_report_preserves_notes_for_exact_case_and_rejects_cross_case_reuse(self):
        result, _ = self.run_benchmark()
        path = Path(result['csv'])
        with path.open(newline='') as stream:
            reader = csv.DictReader(stream)
            fields, rows = reader.fieldnames, list(reader)
        rows[0]['review_notes'] = 'Needs review, with source evidence.'
        with path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fields)
            writer.writeheader()
            writer.writerows(rows)
        before = Path(result['json']).read_bytes()
        render(result['json'])
        with path.open(newline='') as stream:
            saved = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['review_notes'], saved[0]['review_notes'])
        self.assertEqual(before, Path(result['json']).read_bytes())
        another, _ = self.run_benchmark()
        with self.assertRaisesRegex(FaultlineError, 'review notes'):
            render(another['json'], output=path.with_suffix('.md'))

    def test_report_keeps_required_and_unassessed_counts_distinct(self):
        from faultline.tia.benchmark_report import routing_data
        result, _ = self.run_benchmark(limit=0)
        case = checked(Path(result['json']))
        id = case['policies']['jev']['ranking'][0]
        case['policies']['jev']['required'] = [id]
        data = routing_data(case)
        m = data['policies']['jev']
        self.assertEqual(2, m['would_run'])
        self.assertEqual(1, m['run_required'])
        self.assertEqual(1, m['run_unresolved'])
        self.assertEqual(2, m['unresolved_assessments'])
        self.assertEqual(0, m['valid_judgments'])
        self.assertTrue(all(r['jev_action'] == 'RUN' for r in data['targets']))

    def test_report_cli_supports_dated_pricing_and_output_without_inference(self):
        result, _ = self.run_benchmark()
        price = self.root / 'price.json'
        write_json(price, {'model': self.config['evaluator']['model'], 'as_of': '2026-09-20', 'input_usd_per_million': .042})
        before = Path(result['json']).read_bytes()
        with patch('faultline.network.HTTP.request', side_effect=AssertionError('Offline')), patch('builtins.print'):
            code = main(['--root', str(self.root), 'benchmark-report', '--benchmark', result['json'], '--pricing', 'price.json', '--output', '.faultline/report.md'])
        self.assertEqual(0, code)
        self.assertTrue((self.store.path / 'report.csv').is_file())
        self.assertEqual(before, Path(result['json']).read_bytes())
        from faultline.tia.benchmark_report import validate_pricing
        for bad in ({'as_of': 'yesterday', 'input_usd_per_million': .042},
                    {'as_of': '2026-09-20', 'input_usd_per_million': -1},
                    {'as_of': '2026-09-20', 'input_usd_per_million': .042, 'model': 'jev-0.0.0'}):
            with self.assertRaises(FaultlineError):
                validate_pricing(bad, self.config['evaluator']['model'])

    def test_pr_comment_reuses_decisions_without_source_or_local_paths(self):
        result, _ = self.run_benchmark(evidence_mode='source')
        before = Path(result['json']).read_bytes()
        output = self.store.path / 'pr-comment.md'
        files_before = set(self.store.path.iterdir())
        price = {'as_of': '2026-09-20', 'input_usd_per_million': .042}
        with patch('faultline.network.HTTP.request', side_effect=AssertionError('Offline preview')):
            comment = render(result['json'], format='comment', pricing=price, output=output,
                             report_url='https://ci.example.org/artifacts/routing')
        text = output.read_text()
        self.assertEqual(before, Path(result['json']).read_bytes())
        self.assertFalse(comment['published'])
        self.assertEqual('comment', comment['format'])
        self.assertEqual({output}, set(self.store.path.iterdir()) - files_before)
        self.assertTrue(text.startswith('<!-- faultline:benchmark-report -->'))
        self.assertIn('https://ci.example.org/artifacts/routing', text)
        self.assertIn('Shadow mode', text)
        self.assertIn('<details>', text)
        self.assertIn('1 RUN / 1 OMIT', text)
        self.assertIn('2/2', text)
        self.assertNotIn('recommended', text)
        self.assertNotIn('tests/ATest.php', text)
        self.assertNotIn(str(self.root), text)
        self.assertNotIn('\u200b', text)
        self.assertLess(len(text), 4500)
        self.assertEqual(result['routing']['policies']['jev']['would_run'], comment['routing']['policies']['jev']['would_run'])

    def test_pr_comment_marks_unassessed_and_unknown_costs(self):
        result, _ = self.run_benchmark(limit=0)
        case = checked(Path(result['json']))
        # A billed attempt with unavailable usage must remain unknown.
        case['policies']['jev'].update(requests=1, usage=[None])
        comment = render(result['json'], case, format='comment', pricing={'as_of': '2026-09-20', 'input_usd_per_million': .042})
        text = Path(comment['markdown']).read_text()
        self.assertIn('Incomplete assessment', text)
        self.assertIn('Valid judgments: **0/2**', text)
        self.assertIn('Unresolved targets stay RUN', text)
        self.assertIn('| Jev | 2 | 0 | 2 | unknown | unknown |', text)
        self.assertIn('Full report: not linked yet.', text)
        self.assertIsNone(comment['report_url'])

    def test_pr_comment_url_validation_and_cli(self):
        from faultline.tia.benchmark_report import comment_report_url
        for url in ('file:///tmp/report.md', '/tmp/report.md', 'http://ci.example.org/report',
                    'https://user:secret@ci.example.org/report', 'https://ci.example.org/a)\nInjected',
                    'https://', 'https://ci.example.org/[report]'):
            with self.assertRaises(FaultlineError):
                comment_report_url(url)
        result, _ = self.run_benchmark()
        before = Path(result['json']).read_bytes()
        with patch('faultline.network.HTTP.request', side_effect=AssertionError('No inference')), patch('builtins.print'):
            code = main(['--root', str(self.root), 'benchmark-report', '--benchmark', result['json'],
                         '--format', 'comment', '--report-url', 'https://ci.example.org/report', '--output', '.faultline/comment.md'])
        self.assertEqual(0, code)
        self.assertEqual(before, Path(result['json']).read_bytes())
        self.assertTrue((self.store.path / 'comment.md').is_file())
        self.assertFalse((self.store.path / 'comment.csv').exists())

    def test_offline_policy_report_preserves_evidence_notes_and_configuration(self):
        result, _ = self.run_benchmark(evidence_mode='source')
        evidence = Path(result['json']).read_bytes()
        config = (self.root / 'faultline.json').read_bytes()
        output = self.store.path / 'policies.md'
        with patch('faultline.network.HTTP.request', side_effect=AssertionError('No inference')), patch('subprocess.run', side_effect=AssertionError('No runner')):
            report = render(result['json'], output=output, compare_policies=True, file_budgets=[1])
            with Path(report['csv']).open(newline='') as stream:
                reader = csv.DictReader(stream)
                fields, rows = reader.fieldnames, list(reader)
            rows[0]['review_notes'] = 'Review without changing evidence'
            with Path(report['csv']).open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fields)
                writer.writeheader()
                writer.writerows(rows)
            render(result['json'], output=output, compare_policies=True, file_budgets=[1])
            with Path(report['csv']).open(newline='') as stream:
                again = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['review_notes'], again[0]['review_notes'])
        self.assertIn('relevance_0_1_jev_action', fields)
        self.assertIn('jev_p_meaningful_relevance', fields)
        comparison = json.loads(Path(report['policy_comparison']).read_text())
        self.assertEqual(0, comparison['new_input_tokens'])
        self.assertIn('Offline policy comparison', output.read_text())
        self.assertEqual(evidence, Path(result['json']).read_bytes())
        self.assertEqual(config, (self.root / 'faultline.json').read_bytes())
        self.assertFalse((self.store.path / 'runs').exists())

    def test_offline_policy_cli_comment_and_parameter_errors(self):
        result, _ = self.run_benchmark(evidence_mode='source')
        args = ['--root', str(self.root), 'benchmark-report', '--benchmark', result['json']]
        with patch('faultline.network.HTTP.request', side_effect=AssertionError('No inference')), patch('builtins.print'):
            self.assertEqual(0, main(args + ['--compare-policies', '--relevance-thresholds', '.1', '.25', '.5',
                                           '--file-budgets', '1', '--format', 'comment', '--output', '.faultline/compare-comment.md']))
            self.assertEqual(1, main(args + ['--file-budgets', '1']))
            self.assertEqual(1, main(args + ['--compare-policies', '--relevance-thresholds', 'nan']))
            self.assertEqual(1, main(args + ['--compare-policies', '--outcomes', 'missing.json']))
        text = (self.store.path / 'compare-comment.md').read_text()
        self.assertIn('Relevance >= 10%', text)
        self.assertIn('0 new tokens', text)
        self.assertNotIn(str(self.root), text)
        self.assertLess(len(text), 4500)
        self.assertFalse((self.store.path / 'compare-comment.csv').exists())

    def test_frozen_policy_comparison_can_be_assessed_but_not_modified(self):
        result, _ = self.run_benchmark(evidence_mode='source')
        report = render(result['json'], compare_policies=True)
        case = checked(Path(result['json']))
        outcomes = self.store.path / 'outcomes.json'
        write_json(outcomes, self.outcomes(case))
        comparison = Path(report['policy_comparison'])
        assessed = assess(self.store, result['json'], outcomes, policy_comparison=comparison)
        self.assertTrue(assessed['counterfactual_policies'])
        self.assertEqual(1, assessed['counterfactual_policies']['relevance_0_5:jev']['caught_regression_tests'])
        self.assertEqual(1, assessed['counterfactual_policies']['relevance_0_5:jev']['caught_regression_tests'])
        bad = json.loads(comparison.read_text())
        bad['scenarios'][1]['approaches']['jev']['would_run'] = 999
        write_json(comparison, bad)
        with self.assertRaisesRegex(FaultlineError, 'does not match'):
            assess(self.store, result['json'], outcomes, policy_comparison=comparison)


    def test_single_evaluator_scores_every_source_and_reuses_exact_inputs(self):
        result, calls = self.run_benchmark(evidence_mode='source')
        case = checked(Path(result['json']))
        self.assertEqual({'jev'}, set(case['policies']))
        self.assertEqual(1, len(calls))
        self.assertEqual(2, len(case['policies']['jev']['judgments']))
        self.assertTrue(case['complete'])
        self.assertEqual(case['change']['diff'], calls[0]['state']['change']['diff'])
        for q in calls[0]['questions'].values():
            target = q['instructions']['test']
            self.assertEqual((self.root / target['source']).read_text(), target['source_evidence']['text'])
        again, more = self.run_benchmark(evidence_mode='source')
        self.assertEqual([], more)
        self.assertEqual(0, again['usage']['requests'])
        self.assertEqual(2, again['routing']['policies']['jev']['cache_hits'])
        self.assertFalse((self.store.path / 'runs').exists())

    def test_budget_stops_and_resume_uses_answers_without_resetting_config(self):
        self.raw['evaluator'] = {'max_batch_units': 1}
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        # Separate local fixture setup from the assessed production change.
        base = self.git('rev-parse', 'HEAD').strip()
        (self.root / 'src/Policy.php').write_text('<?php return false;')
        self.commit()
        self.base, self.config = base, load_config(self.root)
        before = (self.root / 'faultline.json').read_bytes()
        result, calls = self.run_benchmark(limit=1)
        case = checked(Path(result['json']))
        self.assertFalse(result['complete'])
        self.assertEqual(1, len(calls))
        self.assertEqual(1, len(case['policies']['jev']['unresolved']))
        self.assertTrue(set(case['policies']['jev']['unresolved']) <= set(case['policies']['jev']['would_run']))
        resumed, calls = self.run_benchmark(limit=1)
        self.assertTrue(resumed['complete'])
        self.assertEqual(1, len(calls))
        self.assertEqual(before, (self.root / 'faultline.json').read_bytes())

    def test_prepare_has_no_credentials_network_or_runner_dependency(self):
        with patch('faultline.tia.batch.api_key', side_effect=AssertionError('No key')), patch('faultline.network.HTTP.request', side_effect=AssertionError('No API')), patch('faultline.tia.runners.invoke', side_effect=AssertionError('No runner')):
            result = benchmark(self.store, self.base, prepare=True, max_requests=1)
        self.assertEqual(1, result['total_uncached_requests'])
        self.assertEqual({'jev': 2}, result['preparation']['eligible_targets'])
        self.assertEqual('git', result['index']['basis'])
        self.assertTrue(result['complete'])
        self.assertFalse((self.store.path / 'jev-cache.sqlite').exists())

    def test_model_irrelevant_label_is_distinct_from_policy_cutoff(self):
        from faultline.tia.benchmark_report import routing_data
        result, _ = self.run_benchmark(evidence_mode='source')
        case = checked(Path(result['json']))
        id = case['policies']['jev']['would_run'][0]
        row = case['policies']['jev']['judgments'][id]
        row.update(choice='irrelevant', probabilities=dict(irrelevant=.93, weak=.06, plausible=.01, strong=0, direct=0))
        target = next(t for t in routing_data(case)['targets'] if t['target'] == id)
        self.assertEqual('RUN', target['jev_action'])
        self.assertEqual('irrelevant', target['jev_model_choice'])
        self.assertIn('93.0% irrelevant < 95.0%', target['jev_reason'])
