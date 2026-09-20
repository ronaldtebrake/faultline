import json
import unittest

from faultline.core import DEFAULTS, FaultlineError
from faultline.jev import LEVELS, validate_answer
from faultline.tia.batch import payload
from faultline.tia.config import DEFAULT_EVALUATOR


class RelevanceTests(unittest.TestCase):
    def test_fixed_question_distribution_validation(self):
        probabilities = dict(zip(LEVELS, [.02, .04, .14, .65, .15]))
        response = {'model': DEFAULTS['model'], 'answers': {'relevance': {'type': 'choice', 'choice': 'strong', 'probabilities': probabilities}}}
        self.assertAlmostEqual(2.87, validate_answer(response, DEFAULTS['model'])['score'])
        for bad in ({'direct': 1}, {**probabilities, 'weak': float('nan')}, {**probabilities, 'weak': -1}, {**probabilities, 'weak': True}):
            response['answers']['relevance']['probabilities'] = bad
            with self.assertRaises(FaultlineError):
                validate_answer(response, DEFAULTS['model'])

    def test_inputs_exclude_outcomes(self):
        state = payload({'title': 'Intent', 'diff': 'patch', 'results': ['failure'], 'provenance': {'later_fix': 'x'}},
                       [{'id': 'a', 'source': 'tests/a', 'description': 'behavior', 'metadata': {'status': 'failed'}}], DEFAULT_EVALUATOR)
        self.assertNotIn('failure', json.dumps(state['state']))
        self.assertNotIn('later_fix', json.dumps(state['state']))
