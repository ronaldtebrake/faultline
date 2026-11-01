"""The public default is offline, including when credentials are present."""
import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from faultline.cli import main
from faultline.core import write_json
from faultline.tia.common import checked
from faultline.tia.graph_assessment import assess
from faultline.tia.workflow import saved_report
import test_source_pipeline as fixtures


class GraphAssessmentTests(unittest.TestCase):
    setUp = fixtures.SourcePipelineTests.setUp
    git = fixtures.SourcePipelineTests.git
    commit = fixtures.SourcePipelineTests.commit

    def cli(self, *args, expected=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = main(['--root', str(self.root), *args])
        self.assertEqual(expected, result, err.getvalue())
        return json.loads(out.getvalue()) if not expected else err.getvalue()

    def test_default_assess_and_select_never_use_provider_or_runner(self):
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'present-but-must-not-be-used'}), \
             patch('urllib.request.urlopen', side_effect=AssertionError('No HTTP')), \
             patch('http.client.HTTPSConnection.request', side_effect=AssertionError('No HTTP')), \
             patch('faultline.tia.runners.invoke', side_effect=AssertionError('No runner')):
            for command in ('assess', 'select'):
                result = self.cli(command, '--base', self.base)
                self.assertEqual('graph-v1', result['evaluator'])
                self.assertEqual(0, result['jev_requests'])
                self.assertEqual('full_suite', result['ci_policy'])
                self.assertFalse(result['omission_authorized'])
                self.assertFalse(result['coverage_complete'])
                self.assertEqual({'affected': 1, 'required': 0, 'unresolved': 1}, result['summary'])
                paths = [p['path'] for r in result['tests'] for p in r['paths']]
                self.assertIn(['tests/ATest.php', 'src/Service.php', 'src/Policy.php'], paths)
                self.assertEqual('graph-assessment', checked(result['path'])['kind'])

    def test_frozen_report_resume_does_not_rebuild_or_call_jev(self):
        original = assess(self.store, base=self.base, identifier='<script>')
        with patch('faultline.tia.graph_assessment.build', side_effect=AssertionError('Frozen only')):
            resumed = self.cli('assess', '--resume', original['run_id'])
            result = saved_report(self.store, run_id=original['run_id'])
        self.assertEqual(original['integrity'], resumed['integrity'])
        html = Path(result['html']).read_text()
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_warm_reuses_facts_and_deleted_links_survive(self):
        assess(self.store, base=self.base)
        warm = assess(self.store, base=self.base)
        self.assertEqual(0, warm['preparation']['parsed'])
        (self.root / 'src/Policy.php').unlink()
        (self.root / 'src/Service.php').write_text('<?php class Service {}')
        self.commit()
        result = assess(self.store, base=self.head)
        paths = [p for r in result['tests'] for p in r['paths']]
        self.assertTrue(any(p['snapshot'] == 'base' and p['input'] == 'src/Policy.php' for p in paths))

    def test_rules_and_unknown_changes_retain_tests(self):
        self.raw['suites'][0]['must_run'] = ['tests/BTest.php']
        write_json(self.root / 'faultline.json', self.raw)
        result = assess(self.store, base=self.base)
        self.assertEqual(1, result['summary']['required'])
        (self.root / 'unconfigured.txt').write_text('unknown dependency')
        self.commit()
        result = assess(self.store, base=self.head)
        self.assertIn('unconfigured.txt', result['unknown_paths'])
        self.assertTrue(all('change_outside_declared_scope' in r['reasons'] for r in result['tests']))

    def test_no_change_and_offline_prepare(self):
        result = self.cli('assess', '--base', 'HEAD', '--prepare')
        self.assertTrue(result['dry_run'])
        self.assertEqual({'affected': 0, 'required': 0, 'unresolved': 2}, result['summary'])
        self.assertFalse((self.store.path / 'runs').exists())

    def test_scoring_and_recovery_require_explicit_opt_in(self):
        for evaluator in ('noul-v1', 'choice-v1'):
            message = self.cli('assess', '--evaluator', evaluator, '--base', self.base, expected=1)
            self.assertIn('--jev', message)
        for command, arguments in [('benchmark', ['--base', self.base]),
                                   ('benchmark-recover', ['--benchmark', 'missing.json'])]:
            self.assertIn('--jev', self.cli(command, *arguments, expected=1))
        run_id = 'a' * 32
        write_json(self.store.path / 'runs' / run_id / 'run.json', {'evaluator': 'noul-v1'})
        self.assertIn('--jev', self.cli('assess', '--resume', run_id, expected=1))

    def test_explicit_jev_uses_noul_with_graph(self):
        with patch('faultline.tia.impact.assess', return_value={'complete': True}) as scoring:
            self.cli('assess', '--jev', '--base', self.base, '--max-cost', '0.05')
            self.assertTrue(scoring.call_args.kwargs['dependencies'])
            self.assertEqual(0.05, scoring.call_args.kwargs['max_cost'])
        run_id = 'b' * 32
        write_json(self.store.path / 'runs' / run_id / 'run.json', {'evaluator': 'noul-v1'})
        with patch('faultline.tia.impact.assess', return_value={'complete': True}) as scoring:
            self.cli('assess', '--jev', '--resume', run_id)
            self.assertFalse(scoring.call_args.kwargs['dependencies'])

    def test_graph_report_cannot_be_exported_as_selection(self):
        result = assess(self.store, base=self.base)
        error = self.cli('export-selection', '--run', result['run_id'], '--threshold', '0.5', '--output', '.faultline/selection.json', expected=1)
        self.assertIn('impact', error)

    def test_graph_options_cannot_silently_enable_jev(self):
        self.assertIn('--jev', self.cli('assess', '--base', self.base, '--max-cost', '0.5', expected=1))
        self.assertIn('--jev', self.cli('select', '--base', self.base, '--max-requests', '1', expected=1))
