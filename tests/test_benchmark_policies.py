"""Counterfactual policies never turn missing evidence or requirements into omissions."""
import copy
import unittest

from faultline.core import FaultlineError
from faultline.tia.benchmark_policies import compare, options
from faultline.tia.benchmark_report import routing_data


def judgment(irrelevant, weak, plausible, strong=0, direct=0):
    probabilities = dict(irrelevant=irrelevant, weak=weak, plausible=plausible, strong=strong, direct=direct)
    return dict(model='jev-test', probabilities=probabilities, choice=max(probabilities, key=probabilities.get),
                score=sum(i * v for i, v in enumerate(probabilities.values())))


def case():
    values = {'a': judgment(.93, .06, .01), 'b': judgment(.8, .1, .1),
              'c': judgment(.1, .1, .8), 'required': judgment(1, 0, 0), 'unknown': None}
    ids = list(values)
    semantic = dict(would_run=list(ids), would_omit=[], unresolved=['unknown'], required=['required'], full_suites=[],
                    ranking=list(ids), requests=1, usage=[{'input_tokens': 100}], errors={'unknown': 'Oversized'},
                    judgments={id: j for id, j in values.items() if j is not None})
    return dict(integrity='frozen-id', contract='reference-source-v1', complete=False,
                inventory={'suites': [dict(key='unit:default', suite='unit', units=[dict(id=id, source=id) for id in ids])]},
                config={'suites': [dict(id='unit', irrelevant_threshold=.95, prerequisites=[])]},
                evaluator={'model': 'jev-test', 'settings': {}},
                policies={'jev': copy.deepcopy(semantic)})


def run(d, **kw):
    return compare(d, routing_data(d), **kw)


class PolicyTests(unittest.TestCase):
    def test_relevance_sum_boundary_required_missing_and_no_mutation(self):
        d = case()
        original = copy.deepcopy(d)
        comparison = run(d, thresholds=[.1, .5], budgets=[1, 3])
        self.assertEqual(original, d)
        threshold = comparison['scenarios'][1]['approaches']['jev']
        self.assertEqual({'a': 'OMIT', 'b': 'RUN', 'c': 'RUN', 'required': 'RUN', 'unknown': 'RUN'}, threshold['actions'])
        self.assertEqual(['a'], threshold['run_to_omit'])
        self.assertEqual(1, threshold['run_required'])
        self.assertEqual(1, threshold['run_unresolved'])
        self.assertEqual(2, threshold['run_policy'])
        self.assertEqual(0, comparison['new_jev_requests'])
        self.assertEqual(0, comparison['new_input_tokens'])
        self.assertIsNone(comparison['observed_regression_recall'])
        for scenario in comparison['scenarios']:
            for m in scenario['approaches'].values():
                self.assertEqual(5, m['would_run'] + m['would_omit'])
                self.assertEqual(m['would_run'], m['run_required'] + m['run_unresolved'] + m['run_policy'])
                self.assertEqual('RUN', m['actions']['required'])
                self.assertEqual('RUN', m['actions']['unknown'])

    def test_budget_floor_and_deterministic_ties_are_visible(self):
        comparison = run(case(), thresholds=[.1], budgets=[1, 3])
        below = comparison['scenarios'][2]['approaches']['jev']
        self.assertEqual(2, below['would_run'])
        self.assertEqual(2, below['minimum_run_files'])
        self.assertEqual(1, below['budget_excess_files'])
        self.assertFalse(below['budget_met'])
        jev = comparison['scenarios'][3]['approaches']['jev']
        self.assertTrue(jev['budget_met'])
        self.assertEqual('RUN', jev['actions']['c'])
        self.assertEqual('OMIT', jev['actions']['a'])
        self.assertFalse(jev['budget_tie_split'])
        tied_case = case()
        tied_case['policies']['jev']['judgments']['a'] = judgment(.1, .1, .8)
        tied = run(tied_case, thresholds=[.1], budgets=[3])['scenarios'][2]['approaches']['jev']
        self.assertTrue(tied['budget_tie_split'])
        self.assertEqual('RUN', tied['actions']['a'])
        self.assertEqual('OMIT', tied['actions']['c'])
        d = case()
        d['inventory']['suites'][0]['units'].reverse()
        self.assertEqual(comparison, run(d, thresholds=[.1], budgets=[1, 3]))

    def test_invalid_or_partial_distributions_cannot_authorize_omissions(self):
        d = case()
        d['policies']['jev']['judgments']['a']['probabilities'] = dict(irrelevant=.99, weak=0, plausible=0, strong=0, direct=0)
        d['policies']['jev']['judgments']['b']['evidence_complete'] = False
        comparison = run(d, thresholds=[.5], budgets=[1])
        for scenario in comparison['scenarios'][1:]:
            self.assertEqual('RUN', scenario['approaches']['jev']['actions']['a'])
            self.assertEqual('unresolved', scenario['approaches']['jev']['reasons']['a']['group'])
            self.assertEqual('RUN', scenario['approaches']['jev']['actions']['b'])

    def test_full_suites_prerequisites_variants_and_cycles_remain_required(self):
        d = case()
        d['config']['suites'][0]['prerequisites'] = ['setup']
        d['config']['suites'].append(dict(id='setup', irrelevant_threshold=.95, prerequisites=['unit']))
        for variant in ('one', 'two'):
            id = 'setup:' + variant
            d['inventory']['suites'].append(dict(key=id, suite='setup', units=[dict(id=id, source=id)]))
            for arm, p in d['policies'].items():
                p['ranking'].append(id)
                p['would_omit'].append(id)
                p['judgments'][id] = judgment(1, 0, 0)
        comparison = run(d, thresholds=[.5], budgets=[1])
        for scenario in comparison['scenarios'][1:]:
            arms = ('jev',) if scenario['kind'] == 'relevance' else ('jev',)
            for arm in arms:
                m = scenario['approaches'][arm]
                self.assertEqual(7, m['would_run'])
                self.assertEqual(['setup:one', 'setup:two', 'unit:default'], m['full_suites'])
                self.assertEqual(['setup:one', 'setup:two'], m['omit_to_run'])
        d = case()
        for p in d['policies'].values():
            p['full_suites'] = ['unit:default']
        self.assertEqual(5, run(d)['scenarios'][1]['approaches']['jev']['would_run'])

    def test_reject_windowed_evidence_and_invalid_parameters(self):
        d = case()
        d['contract'] = 'reference-file-pairs-v1'
        with self.assertRaisesRegex(FaultlineError, 'windowed'):
            run(d)
        for thresholds in ([], [0], [-.1], [1.1], [float('nan')], [float('inf')], [True]):
            with self.assertRaises(FaultlineError):
                options(5, thresholds=thresholds)
        for budgets in ([], [0], [-1], [1.5], [True]):
            with self.assertRaises(FaultlineError):
                options(5, budgets=budgets)
        self.assertEqual(([.1, .5], [1, 10]), options(5, [.5, .1, .1], [10, 1, 10]))
