import json
import unittest
from pathlib import Path
from unittest.mock import patch

from faultline.core import DEFAULTS, FaultlineError, read_json, write_json
from faultline.index import build_index
from faultline.jev import LEVELS, inputs, validate_answer
from faultline.workflow import load_prediction, rank
from helpers import FakeEvaluator, setup_case


class RankingTests(unittest.TestCase):
    def test_fixed_question_distribution_validation(self):
        probabilities = dict(zip(LEVELS, [.02, .04, .14, .65, .15]))
        response = {'model': DEFAULTS['model'], 'answers': {'relevance': {'type': 'choice', 'choice': 'strong', 'probabilities': probabilities}}}
        self.assertAlmostEqual(2.87, validate_answer(response, DEFAULTS['model'])['score'])
        for bad in ({'direct': 1}, {**probabilities, 'weak': float('nan')}, {**probabilities, 'weak': -1}, {**probabilities, 'weak': True}):
            response['answers']['relevance']['probabilities'] = bad
            with self.assertRaises(FaultlineError):
                validate_answer(response, DEFAULTS['model'])

    def test_inputs_exclude_outcomes(self):
        state = inputs({'title': 'Intent', 'diff': 'patch', 'results': ['failure'], 'provenance': {'later_fix': 'x'}},
                       {'id': 'a', 'source': 'tests/a', 'description': 'behavior', 'metadata': {'status': 'failed'}})
        self.assertNotIn('failure', json.dumps(state))
        self.assertNotIn('later_fix', json.dumps(state))

    def test_full_rank_freeze_and_offline_cache(self):
        root, store, change = setup_case(self)
        fake = FakeEvaluator()
        estimate = rank(store, change, dry_run=True, evaluator=fake)
        self.assertEqual(2, estimate['uncached_requests'])
        self.assertEqual([], fake.calls)
        result = rank(store, change, evaluator=fake)
        self.assertTrue(result['complete'])
        prediction = load_prediction(Path(result['path']))
        self.assertEqual(['case-b', 'case-a'], [r['id'] for r in prediction['ranking']])
        original = Path(result['path']).read_bytes()
        with patch('faultline.jev.JevEvaluator.evaluate', side_effect=AssertionError('No network')):
            repeated = rank(store, change)
        self.assertTrue(repeated['frozen'])
        self.assertEqual(original, Path(result['path']).read_bytes())

    def test_partial_resumes_cached_pairs(self):
        root, store, change = setup_case(self)
        partial = rank(store, change, evaluator=FakeEvaluator(stop_after=1))
        self.assertFalse(partial['complete'])
        remaining = FakeEvaluator()
        completed = rank(store, change, evaluator=remaining)
        self.assertTrue(completed['complete'])
        self.assertEqual(1, len(remaining.calls))
        self.assertEqual(1, len(list((Path(completed['path']).parent / 'attempts').glob('*.json'))))

    def test_changed_description_invalidates_only_its_pair(self):
        root, store, change = setup_case(self)
        rank(store, change, evaluator=FakeEvaluator())
        draft = read_json(root / 'draft.json')
        draft[0]['description'] = 'Better evidenced access description'
        write_json(root / 'draft.json', draft)
        build_index(store, root / 'draft.json', 'test-agent', rewrite=True)
        fake = FakeEvaluator()
        rank(store, change, evaluator=fake)
        self.assertEqual(['case-a'], [p['id'] for c, p in fake.calls])

    def test_budget_blocks_calls_and_tampering_is_detected(self):
        root, store, change = setup_case(self)
        fake = FakeEvaluator()
        result = rank(store, change, evaluator=fake, config={**DEFAULTS, 'jev_requests': 1})
        self.assertFalse(result['complete'])
        self.assertEqual([], fake.calls)
        prediction = read_json(Path(result['path']))
        prediction['complete'] = True
        write_json(Path(result['path']), prediction)
        with self.assertRaises(FaultlineError):
            load_prediction(Path(result['path']))

    def test_contaminated_history_rejected(self):
        root, store, path = setup_case(self)
        change = read_json(path)
        change['provenance']['outcomes_seen'] = True
        write_json(path, change)
        with self.assertRaises(FaultlineError):
            rank(store, path, evaluator=FakeEvaluator())

    def test_collection_timestamp_does_not_repeat_inference(self):
        root, store, change = setup_case(self)
        rank(store, change, evaluator=FakeEvaluator())
        data = read_json(change)
        data['provenance']['collected_at'] = '2026-01-01T12:00:00+00:00'
        write_json(change, data)
        fake = FakeEvaluator()
        result = rank(store, change, evaluator=fake)
        self.assertTrue(result['complete'])
        self.assertEqual([], fake.calls)
