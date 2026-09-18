import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from faultline.core import DEFAULTS, FaultlineError, read_json, write_json
from faultline.evaluation import evaluate
from faultline.report import aggregate, regenerate
from faultline.workflow import rank
from helpers import FakeEvaluator, outcomes, setup_case


class EvaluationTests(unittest.TestCase):
    def prepare(self):
        root, store, change = setup_case(self)
        ranked = rank(store, change, evaluator=FakeEvaluator())
        evidence = outcomes(ranked['prediction_id'])
        return root, store, ranked, evidence

    def evaluate(self, root, store, ranked, evidence):
        path = root / 'outcomes.json'
        write_json(path, evidence)
        result = evaluate(store, Path(ranked['path']), path, DEFAULTS)
        return result, read_json(Path(result['json']))

    def test_single_command_evaluation_writes_reports_and_metrics(self):
        root, store, ranked, evidence = self.prepare()
        result, findings = self.evaluate(root, store, ranked, evidence)
        self.assertTrue(Path(result['report']).is_file())
        stats = findings['selected_run']['metrics']
        self.assertEqual(1, stats['semantic']['first_failure_rank'])
        self.assertEqual(2, stats['historical']['first_failure_rank'])
        self.assertEqual(5, stats['semantic']['serial_seconds_to_failure'])
        self.assertEqual(15, stats['historical']['serial_seconds_to_failure'])
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Offline report')):
            regenerated = regenerate(store, ranked['prediction_id'])
            summary = aggregate(store)
        self.assertTrue(Path(regenerated['report']).exists())
        group = read_json(Path(summary['json']))['groups'][0]
        self.assertEqual(1, group['distinct_changes'])
        self.assertIsNone(group['methods']['semantic']['p90_first_failure_rank'])

    def test_reruns_do_not_inflate_aggregate_denominator(self):
        root, store, ranked, evidence = self.prepare()
        repeated = copy.deepcopy(evidence['runs'][0])
        repeated['attempt'] = 2
        evidence['runs'].append(repeated)
        self.evaluate(root, store, ranked, evidence)
        self.evaluate(root, store, ranked, evidence)
        summary = read_json(Path(aggregate(store)['json']))
        self.assertEqual(1, summary['groups'][0]['eligible_changes'])

    def test_green_flaky_infrastructure_and_missing_failures_not_success(self):
        for label in ('likely_flake', 'infrastructure', 'unknown'):
            root, store, ranked, evidence = self.prepare()
            evidence['runs'][0]['tests'][1]['classification'] = label
            _, findings = self.evaluate(root, store, ranked, evidence)
            self.assertEqual('not_assessable', findings['assessment'])
        root, store, ranked, evidence = self.prepare()
        evidence['runs'][0]['tests'][1]['id'] = 'removed-test'
        _, findings = self.evaluate(root, store, ranked, evidence)
        self.assertEqual('not_assessable', findings['assessment'])
        self.assertEqual(['removed-test'], findings['runs'][0]['unmatched_tests'])

    def test_wrong_snapshot_and_missing_duration(self):
        root, store, ranked, evidence = self.prepare()
        evidence['runs'][0]['snapshot'] = 'later-fix'
        _, findings = self.evaluate(root, store, ranked, evidence)
        self.assertEqual('not_assessable', findings['assessment'])
        evidence['runs'][0]['snapshot'] = 'revision-1'
        evidence['runs'][0]['tests'][1].pop('duration_seconds')
        evidence['runs'][0]['order_verified'] = False
        _, findings = self.evaluate(root, store, ranked, evidence)
        self.assertNotIn('historical', findings['selected_run']['metrics'])
        self.assertIsNone(findings['selected_run']['metrics']['semantic']['serial_seconds_to_failure'])

    def test_outcomes_before_freeze_and_unsubstantiated_labels_rejected(self):
        root, store, ranked, evidence = self.prepare()
        evidence['collected_at'] = '2000-01-01T00:00:00+00:00'
        with self.assertRaises(FaultlineError):
            self.evaluate(root, store, ranked, evidence)
        evidence = outcomes(ranked['prediction_id'])
        evidence['runs'][0]['tests'][1]['evidence'] = ''
        with self.assertRaises(FaultlineError):
            self.evaluate(root, store, ranked, evidence)

    def test_multiple_prs_and_evaluator_versions_separate(self):
        root, store, ranked, evidence = self.prepare()
        self.evaluate(root, store, ranked, evidence)
        change = read_json(root / 'change.json')
        change['id'] = 'PR-2'
        write_json(root / 'change.json', change)
        second = rank(store, root / 'change.json', evaluator=FakeEvaluator())
        self.evaluate(root, store, second, outcomes(second['prediction_id']))
        summary = read_json(Path(aggregate(store)['json']))
        self.assertEqual(2, summary['groups'][0]['distinct_changes'])
        third = rank(store, root / 'change.json', evaluator=FakeEvaluator(), config={**DEFAULTS, 'model': 'other-version'})
        self.evaluate(root, store, third, outcomes(third['prediction_id']))
        summary = read_json(Path(aggregate(store)['json']))
        self.assertEqual(2, len(summary['groups']))
