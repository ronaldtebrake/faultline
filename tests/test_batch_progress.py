"""Bounded Jev requests must make completed, resumable scoring progress."""
import json
import math
import tempfile
import unittest
from pathlib import Path

from faultline.core import Store
from faultline.tia.batch import BatchedJev, identity
from faultline.tia.config import DEFAULT_EVALUATOR
from test_source_pipeline import answer


def profile(i, source='test("access", () => expect(allowed()).toBe(true));'):
    return {'id': str(i), 'source': f'tests/{i}.feature', 'description': '', 'source_text': source,
            'execution_context': {}}


class BatchProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name))
        self.requests = []

    def evaluator(self, **settings):
        ev = BatchedJev(self.store, {**DEFAULT_EVALUATOR, 'request_interval': 0, **settings})
        requests = self.requests
        class Transport:
            def request(inner, url, payload, **kw):
                ev.budget.take()
                requests.append(payload)
                return {'model': payload['model'], 'answers': {q: answer() for q in payload['questions']},
                        'usage': {'input_tokens': 100, 'output_tokens': 0}}, {}
        ev.http = Transport()
        return ev

    def test_complete_inputs_are_not_artificially_fragmented(self):
        ev = self.evaluator()
        context = {'diff': '+ policy changed\n' * 300, 'changed_files': ['policy.yml']}
        item = profile('a', 'Feature: access\n Scenario: allowed\n Then access succeeds\n' * 150)
        result = ev.evaluate_source(context, [item])
        self.assertTrue(result['complete'])
        self.assertEqual(1, result['evidence_pairs'])
        self.assertEqual(1, result['requests'])
        self.assertEqual(context['diff'], self.requests[0]['state']['change']['diff'])
        self.assertEqual(item['source_text'], self.requests[0]['state']['tests'][0]['source_evidence']['text'])

    def test_small_request_budget_finishes_cohort_and_resume_advances(self):
        context = {'diff': '+ policy changed\n' * 2600, 'changed_files': ['policy.yml']}
        items = [profile(i, 'Feature: access\n Scenario: allowed\n Then access succeeds\n' * 20) for i in range(25)]
        first = self.evaluator(jev_requests=8).evaluate_source(context, items)
        complete = sum(r['evidence_complete'] for r in first['rows'].values())
        self.assertGreater(complete, 0)
        self.assertLess(complete, len(items))
        self.assertEqual(8, first['requests'])
        self.assertGreater(first['remaining_requests'], 0)
        old_pairs = math.ceil(len(context['diff'].encode()) / 4000) * sum(math.ceil(len(p['source_text'].encode()) / 4000) for p in items)
        self.assertLess(first['evidence_pairs'], old_pairs)
        second = self.evaluator(jev_requests=8).evaluate_source(context, items)
        self.assertGreater(sum(r['evidence_complete'] for r in second['rows'].values()), complete)
        self.assertLess(second['remaining_requests'], first['remaining_requests'])
        self.assertEqual(len(self.requests), len({identity(r) for r in self.requests}))

    def test_judgment_ceiling_does_not_permanently_hide_later_tests(self):
        context = {'diff': '+ change', 'changed_files': ['src.js']}
        items = [profile(i) for i in range(5)]
        complete = 0
        for run in range(5):
            result = self.evaluator(jev_requests=1, max_evidence_pairs=1).evaluate_source(context, items)
            self.assertEqual(1, result['requests'])
            latest = sum(r['evidence_complete'] for r in result['rows'].values())
            self.assertGreater(latest, complete)
            complete = latest
        self.assertTrue(result['complete'])
        self.assertEqual(0, result['remaining_requests'])
        self.assertEqual(5, len({identity(r) for r in self.requests}))

    def test_preflight_is_offline_and_predicts_no_retry_request_ceiling(self):
        context = {'diff': '+ change', 'changed_files': ['src.js']}
        items = [profile(i) for i in range(40)]
        plan = self.evaluator(jev_requests=1).evaluate_source(context, items, dry_run=True)
        self.assertEqual([], self.requests)
        self.assertGreater(plan['uncached_requests'], 1)
        self.assertGreater(plan['target_completion_ceiling'], 0)
        self.assertLess(plan['target_completion_ceiling'], 40)
        actual = self.evaluator(jev_requests=1).evaluate_source(context, items)
        self.assertEqual(plan['target_completion_ceiling'], sum(r['evidence_complete'] for r in actual['rows'].values()))
        remaining = self.evaluator(jev_requests=1).evaluate_source(context, items, dry_run=True)
        self.assertEqual(plan['uncached_requests'] - 1, remaining['uncached_requests'])

    def test_adaptive_fragments_cover_all_bytes_and_obey_serialized_limits(self):
        context = {'diff': '+ "café" \\ changed\n' * 1800, 'changed_files': ['src.js']}
        item = profile('a', 'Feature: access 🧪\n Scenario: quote "\\"\n' * 1800)
        result = self.evaluator(jev_requests=100).evaluate_source(context, [item])
        self.assertTrue(result['complete'])
        rectangles = []
        for request in self.requests:
            self.assertLessEqual(len(json.dumps(request, ensure_ascii=False).encode()), DEFAULT_EVALUATOR['max_batch_bytes'])
            self.assertLessEqual(len(json.dumps(request['state'], ensure_ascii=False).encode()), DEFAULT_EVALUATOR['max_state_bytes'])
            diff = request['state']['change']['diff_evidence']
            for test in request['state']['tests']:
                source = test['source_evidence']
                self.assertEqual(item['source_text'].encode()[source['start_byte']:source['end_byte']].decode(), source['text'])
                rectangles.append((diff['start_byte'], diff['end_byte'], source['start_byte'], source['end_byte']))
        xs = sorted({x for a,b,c,d in rectangles for x in (a,b)})
        ys = sorted({y for a,b,c,d in rectangles for y in (c,d)})
        self.assertEqual((0, len(context['diff'].encode())), (xs[0], xs[-1]))
        self.assertEqual((0, len(item['source_text'].encode())), (ys[0], ys[-1]))
        for x in xs[:-1]:
            for y in ys[:-1]:
                self.assertEqual(1, sum(a <= x < b and c <= y < d for a,b,c,d in rectangles))
