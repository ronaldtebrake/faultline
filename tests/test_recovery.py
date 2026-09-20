import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from faultline.core import Store, FaultlineError
from faultline.network import InvalidResponse, InputTooLarge
from faultline.tia.batch import BatchedJev
from faultline.tia.benchmark_windows import RecoveryPlan, sha
from faultline.tia.benchmark_source import within_limits
from faultline.tia.config import DEFAULT_EVALUATOR
import test_source_pipeline as fixture
import test_benchmark as benchmark_fixture


def profile(id, text):
    return dict(id=id, source='tests/'+id+'.feature', source_text=text, source_sha256=sha(text), description='',
                execution_context={})


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name))
        self.config = {**DEFAULT_EVALUATOR, 'request_interval': 0, 'max_state_bytes': 24000, 'max_batch_bytes': 48000}

    def engine(self, responses, **config):
        ev = BatchedJev(self.store, {**self.config, **config})
        requests = []
        class Transport:
            def request(inner, url, payload, **kw):
                ev.budget.take()
                requests.append(copy.deepcopy(payload))
                value = responses[len(requests)-1]
                if isinstance(value, Exception):
                    raise value
                return value(payload) if callable(value) else value, {}
        ev.http = Transport()
        return ev, requests

    def test_invalid_answer_recovers_without_replacing_valid_sibling(self):
        def first(p):
            bad = fixture.answer('irrelevant')
            bad['probabilities']['irrelevant'] = .99
            return dict(model=p['model'], answers={'q0':fixture.answer('strong'), 'q1':bad}, usage={'input_tokens':100,'output_tokens':0})
        def second(p):
            return dict(model=p['model'], answers={'q0':fixture.answer('irrelevant'), 'q1':fixture.answer('weak')}, usage={'input_tokens':80,'output_tokens':0})
        ev, calls = self.engine([first,second])
        items=[profile('a','test a'),profile('b','test b')]
        result=ev.evaluate({'diff':'changed'},items)
        self.assertTrue(result['complete'])
        self.assertEqual(2,result['requests'])
        self.assertEqual(1,result['validation_retries'])
        self.assertEqual(1,len(result['invalid_answers']))
        self.assertEqual('strong',result['rows']['a']['choice'])
        self.assertEqual('weak',result['rows']['b']['choice'])
        self.assertEqual(calls[0],calls[1])
        self.assertEqual(180,sum(u['input_tokens'] for u in result['usage']))
        again=ev.evaluate({'diff':'changed'},items)
        self.assertEqual(0,again['requests'])
        self.assertEqual(2,again['cache_hits'])

    def test_provider_oversize_splits_questions_and_reuses_actual_child_inputs(self):
        from faultline.tia.benchmark_source import request
        good = lambda p: dict(model=p['model'], answers={q:fixture.answer() for q in p['questions']}, usage={'input_tokens':20,'output_tokens':0})
        ev, calls = self.engine([InputTooLarge('too large'), good, good])
        items = [profile('a', 'test a'), profile('b', 'test b')]
        payload = request({'diff': '+ changed'}, items, self.config, 'jev')
        result = ev.evaluate({}, [], prepared=([payload], []))
        self.assertTrue(result['complete'])
        self.assertEqual({'a','b'}, set(result['rows']))
        self.assertEqual(3, result['requests'])
        self.assertEqual([None, {'input_tokens':20,'output_tokens':0}, {'input_tokens':20,'output_tokens':0}], result['usage'])
        self.assertEqual([2,1,1], [len(p['questions']) for p in calls])
        self.assertTrue(all(p['state']['change']==payload['state']['change'] for p in calls))
        self.assertEqual(3, len(result['request_manifest']))
        again = ev.evaluate({}, [], prepared=([payload], []))
        self.assertTrue(again['complete'])
        self.assertEqual(0, again['requests'])
        self.assertEqual(result['rows'], again['rows'])
        capped, calls = self.engine([InputTooLarge('too large')], jev_requests=1)
        # Use a fresh request identity to avoid the accepted child cache above.
        fresh = request({'diff': '+ another'}, items, self.config, 'jev')
        partial = capped.evaluate({}, [], prepared=([fresh], []))
        self.assertEqual(1, partial['requests'])
        self.assertEqual({'a','b'}, set(partial['errors']))
        self.assertFalse(partial['complete'])

    def test_recovery_respects_request_and_judgment_caps(self):
        response=lambda p: dict(model=p['model'],answers={},usage={'input_tokens':20,'output_tokens':0})
        for cap in ({'jev_requests':1},{'max_evidence_pairs':1}):
            ev,calls=self.engine([response],**cap)
            result=ev.evaluate({'diff':'changed'},[profile('a','test a')])
            self.assertEqual(1,len(calls))
            self.assertFalse(result['complete'])
            self.assertIn('a',result['errors'])
        ev,calls=self.engine([response,response])
        result=ev.evaluate({'diff':'changed'},[profile('a','test a')])
        self.assertEqual(2,len(calls))
        self.assertFalse(result['complete'])

    def test_malformed_json_recovers_but_ambiguous_network_and_wrong_model_do_not(self):
        good=lambda p: dict(model=p['model'],answers={'q0':fixture.answer()},usage={'input_tokens':20,'output_tokens':0})
        ev,calls=self.engine([InvalidResponse('Jev returned malformed JSON'),good])
        r=ev.evaluate({'diff':'changed'},[profile('a','test a')])
        self.assertTrue(r['complete'])
        self.assertEqual([None,{'input_tokens':20,'output_tokens':0}],r['usage'])
        for response in (FaultlineError('Ambiguous timeout'),lambda p: dict(model='jev-wrong',answers={'q0':fixture.answer()})):
            ev,calls=self.engine([response])
            r=ev.evaluate({'diff':'other'},[profile('a','test a')])
            self.assertEqual(1,len(calls))
            self.assertFalse(r['complete'])

    def test_cache_failure_does_not_trigger_paid_retry(self):
        good=lambda p: dict(model=p['model'],answers={'q0':fixture.answer()},usage={'input_tokens':20,'output_tokens':0})
        ev,calls=self.engine([good])
        with patch.object(ev.cache,'put',side_effect=FaultlineError('Cannot persist')):
            r=ev.evaluate({'diff':'changed'},[profile('a','test a')])
        self.assertEqual(1,len(calls))
        self.assertFalse(r['complete'])

    def test_windows_cover_all_multilingual_source_and_change_ranges(self):
        source='Feature: accès\nScenario: données\n Given a value\n Then it is allowed\n' * 1500
        diff='diff --git a/config b/config\n@@ -1 +1 @@\n-old\n+new\n' * 800
        item=profile('a',source)
        plan=RecoveryPlan({'diff':diff},[item],{'jev':{'a'}},self.config)
        self.assertFalse(plan.rejected['jev'])
        parts=plan.parts['jev']['a']
        self.assertGreater(len(parts),1)
        xs=sorted({v for p in parts for v in p['source_range']})
        ys=sorted({v for p in parts for v in p['change_range']})
        self.assertEqual([0,len(source)],[xs[0],xs[-1]])
        self.assertEqual([0,len(diff)],[ys[0],ys[-1]])
        for x in xs[:-1]:
            for y in ys[:-1]:
                self.assertEqual(1,sum(p['source_range'][0]<=x<p['source_range'][1] and p['change_range'][0]<=y<p['change_range'][1] for p in parts))
        for group in plan.groups:
            request=group['jev']
            self.assertTrue(within_limits(request,self.config))
            for q in request['questions'].values():
                evidence=q['instructions']['test']['source_evidence']
                a,b=evidence['source_range']
                self.assertEqual(source[a:b],evidence['text'])
                self.assertEqual(sha(evidence['text']), next(p['source_part_sha256'] for p in parts if p['source_range']==[a,b] and p['change_range']==evidence['change_range']))
                self.assertTrue(a==0 or source[a-1]=='\n')
                self.assertTrue(b==len(source) or source[b-1]=='\n')

    def test_oversized_context_preserves_whole_fitting_test_and_all_change_ranges(self):
        source = 'Scenario: access\n Given a value\n Then it is allowed\n' * 110
        diff = 'diff --git a/config b/config\n@@ -1 +1 @@\n-old\n+new\n' * 2000
        context = {'diff': diff, 'context_evidence': {'contract': 'change-context-v1', 'blocks': []}}
        plan = RecoveryPlan(context, [profile('a', source)], {'jev': {'a'}}, self.config)
        self.assertFalse(plan.rejected['jev'])
        parts = sorted(plan.parts['jev']['a'], key=lambda p: p['change_range'])
        self.assertGreater(len(parts), 1)
        self.assertEqual({(0, len(source))}, {tuple(p['source_range']) for p in parts})
        self.assertEqual(0, parts[0]['change_range'][0])
        self.assertEqual(len(diff), parts[-1]['change_range'][1])
        for left, right in zip(parts, parts[1:]):
            self.assertEqual(left['change_range'][1], right['change_range'][0])
        for group in plan.groups:
            self.assertTrue(within_limits(group['jev'], self.config))

    def test_part_completion_and_minimum_irrelevance_are_explicit(self):
        item=profile('a','Scenario: access\n Given a value\n Then it is allowed\n'*900)
        plan=RecoveryPlan({'diff':'+change\n'},[item],{'jev':{'a'}},self.config)
        self.assertGreater(len(plan.parts['jev']['a']),1)
        def row(level):
            probabilities=fixture.answer(level)['probabilities']
            return dict(probabilities=probabilities, choice=level, model=self.config['model'], score=0 if level=='irrelevant' else 3)
        records={p['id']:row('irrelevant') for p in plan.parts['jev']['a']}
        first=plan.parts['jev']['a'][0]['id']
        records[first]=row('strong')
        result=plan.aggregate({'jev':{'rows':records,'errors':{}}})['jev']
        self.assertTrue(result['rows']['a']['evidence_complete'])
        self.assertEqual(0,result['rows']['a']['all_parts_irrelevant_probability'])
        self.assertEqual(1,result['rows']['a']['policy_relevance_probability'])
        records.pop(first)
        partial=plan.aggregate({'jev':{'rows':records,'errors':{first:'invalid'}}})['jev']
        self.assertFalse(partial['rows']['a']['evidence_complete'])
        self.assertIsNone(partial['rows']['a']['all_parts_irrelevant_probability'])
        self.assertIn('a',partial['errors'])

    def test_indivisible_line_is_explicitly_blocked_without_truncation(self):
        item=profile('a','x'*100000)
        plan=RecoveryPlan({'diff':'+change\n'},[item],{'jev':{'a'}},self.config)
        self.assertEqual([],plan.groups)
        self.assertIn('a',plan.rejected['jev'])


class RecoveryIntegrationTests(unittest.TestCase):
    setUp = fixture.SourcePipelineTests.setUp
    git = fixture.SourcePipelineTests.git
    commit = fixture.SourcePipelineTests.commit
    engine = benchmark_fixture.BenchmarkTests.engine
    run_benchmark = benchmark_fixture.BenchmarkTests.run_benchmark

    def test_recovery_retains_original_question_cohort_and_accepted_sibling(self):
        from faultline.tia.benchmark import benchmark
        from faultline.tia.benchmark_recovery import recover
        from faultline.tia.common import checked
        ev, _ = self.engine()
        class InitiallyInvalid:
            def request(inner, url, payload, **kw):
                ev.budget.take()
                return {'model': payload['model'], 'answers': {
                    q: fixture.answer('strong') for q in payload['questions'] if q != 'q0'
                }, 'usage': {'input_tokens': 20, 'output_tokens': 0}}, {}
        ev.http = InitiallyInvalid()
        result = benchmark(self.store, self.base, evaluator=ev)
        old = checked(Path(result['json']))
        self.assertEqual(1, len(old['policies']['jev']['unresolved']))
        accepted = next(id for id in old['policies']['jev']['judgments'] if id not in old['policies']['jev']['unresolved'])
        engine, calls = self.engine()
        result = recover(self.store, result['json'], evaluator=engine)
        new = checked(Path(result['json']))
        self.assertEqual(1, len(calls))
        self.assertEqual(2, len(calls[0]['questions']))
        self.assertEqual(old['policies']['jev']['judgments'][accepted], new['policies']['jev']['judgments'][accepted])
        self.assertTrue(new['policies']['jev']['complete'])

    def test_recovery_freezes_new_evidence_and_preserves_accepted_parent_judgments(self):
        from faultline.tia.benchmark_recovery import recover
        from faultline.tia.common import checked
        (self.root / 'tests/BTest.php').write_text('<?php\n' + '// complete source line\n' * 2000)
        self.commit()
        self.head = self.git('rev-parse', 'HEAD').strip()
        result,_ = self.run_benchmark(evidence_mode='source')
        before = Path(result['json']).read_bytes()
        original = checked(Path(result['json']))
        engine,calls = self.engine(100)
        fixed = recover(self.store, Path(result['json']), evaluator=engine)
        revised = checked(Path(fixed['json']))
        self.assertNotEqual(result['json'],fixed['json'])
        self.assertEqual(before,Path(result['json']).read_bytes())
        for arm in ('jev',):
            self.assertEqual([],revised['policies'][arm]['unresolved'])
            for id,row in original['policies'][arm]['judgments'].items():
                self.assertEqual(row,revised['policies'][arm]['judgments'][id])
        self.assertEqual(original['integrity'],revised['recovery']['parent_benchmark'])
        self.assertTrue(calls)
        self.assertFalse((self.store.path/'runs').exists())

    def test_adaptive_benchmark_scores_oversized_source_and_small_whole_targets(self):
        from faultline.tia.common import checked
        (self.root / 'tests/BTest.php').write_text('<?php\n' + '// complete source line\n' * 2000)
        self.commit()
        self.head=self.git('rev-parse','HEAD').strip()
        result,calls=self.run_benchmark(evidence_mode='adaptive')
        case=checked(Path(result['json']))
        self.assertEqual('reference-adaptive-source-v1',case['contract'])
        for arm in ('jev',):
            self.assertFalse(case['policies'][arm]['unresolved'])
        self.assertTrue(calls)
