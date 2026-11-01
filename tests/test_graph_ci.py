"""CI packaging, visible proposals and new-file updates use no consumer scripts."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from faultline.core import FaultlineError
from faultline.tia.common import checked
from faultline.tia.graph_ci import run, expectations
from faultline.tia.dependency_shared import restore
from faultline.tia.graph_assessment import markdown
import test_source_pipeline as fixtures


class GraphCITests(unittest.TestCase):
    setUp = fixtures.SourcePipelineTests.setUp
    git = fixtures.SourcePipelineTests.git
    commit = fixtures.SourcePipelineTests.commit

    def env(self, **changes):
        return dict(GITHUB_REPOSITORY='example/project', GITHUB_REPOSITORY_ID='42',
                    GITHUB_WORKFLOW_REF='example/project/.github/workflows/graph.yml@refs/heads/main',
                    GITHUB_RUN_ID='101', GITHUB_RUN_ATTEMPT='1', GITHUB_EVENT_NAME='push',
                    GITHUB_REF_NAME='main', GITHUB_SHA=self.git('rev-parse', 'HEAD').strip(),
                    GITHUB_STEP_SUMMARY=str(self.store.path / 'job-summary.md'), **changes)

    def test_cold_publish_then_new_files_restore_and_extend_graph(self):
        cold = self.store.path / 'cold'
        with patch('faultline.tia.runners.invoke', side_effect=AssertionError('No execution')):
            first = run(self.store, base=self.base, output=cold, publish_baseline=True, environ=self.env())
        self.assertTrue(first['validation']['passed'])
        self.assertTrue((cold / 'baseline.json').exists())
        doc = checked(cold / 'cumulative.json', 'graph-assessment')
        self.assertIn('tests/ATest.php', (cold / 'cumulative.md').read_text())
        self.assertIn('Would run: 1', (self.store.path / 'job-summary.md').read_text())
        self.assertIn('Unresolved: 1', (cold / 'summary.md').read_text())
        (self.root / 'src/NewPolicy.php').write_text('<?php class NewPolicy { function allows() { return true; } }')
        (self.root / 'tests/NewTest.php').write_text('<?php class NewTest { function testNew() { return (new NewPolicy())->allows(); } }')
        old = self.git('rev-parse', 'HEAD').strip()
        self.commit()
        def fetch(*args, **kwargs):
            self.assertEqual('main', kwargs['branch'])
            return restore(self.store, cold / 'baseline.json')
        expect = {'restored': True, 'parsed': 2, 'min_reused': 1,
                  'new_files': ['src/NewPolicy.php', 'tests/NewTest.php'], 'new_targets': ['tests/NewTest.php'],
                  'exact_affected': ['tests/NewTest.php'], 'unresolved': ['tests/BTest.php'],
                  'unchanged_tests': {'revision': self.base, 'sources': ['tests/ATest.php', 'tests/BTest.php']},
                  'affected': ['tests/NewTest.php'], 'paths': [{'source': 'tests/NewTest.php', 'input': 'src/NewPolicy.php'}]}
        with patch('faultline.tia.graph_ci.fetch', side_effect=fetch):
            result = run(self.store, base=self.base, compare_base=old, trusted_branch='main', output=self.store.path / 'warm',
                         publish_baseline=True, expected=json.dumps(expect), environ=self.env())
        self.assertTrue(result['validation']['passed'])
        self.assertEqual(2, result['build']['parsed'])
        updated = checked(self.store.path / 'warm' / 'baseline.json', 'dependency-shared-baseline')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), updated['revision'])
        self.assertGreater(len(updated['sources']), len(checked(cold / 'baseline.json')['sources']))
        self.assertFalse(result['omission_authorized'])
        self.assertEqual(0, result['jev_requests'])
        summary = (self.store.path / 'warm' / 'summary.md').read_text()
        self.assertLess(summary.index('### Stacked'), summary.index('### Cumulative'))
        self.assertIn('Experiment controls: **passed**', summary)
        with self.assertRaisesRegex(FaultlineError, 'already exists'):
            run(self.store, base=self.base, output=cold)

    def test_failed_assertions_save_evidence_but_do_not_publish(self):
        folder = self.store.path / 'bad'
        with self.assertRaisesRegex(FaultlineError, 'Expected restored=True'):
            run(self.store, base=self.base, output=folder, publish_baseline=True, expected={'restored': True}, environ=self.env())
        self.assertFalse((folder / 'baseline.json').exists())
        self.assertFalse(json.loads((folder / 'result.json').read_text())['validation']['passed'])
        self.assertTrue((folder / 'summary.md').exists())

    def test_pr_or_wrong_head_cannot_publish_baselines(self):
        env = self.env(); env['GITHUB_EVENT_NAME'] = 'pull_request'
        with self.assertRaisesRegex(FaultlineError, 'producer'):
            run(self.store, base=self.base, publish_baseline=True, environ=env)
        env = self.env(); env['GITHUB_SHA'] = self.base
        with self.assertRaisesRegex(FaultlineError, 'SHA'):
            run(self.store, base=self.base, publish_baseline=True, environ=env)

    def test_expectation_schema_and_bounded_summary(self):
        for value in ('not json', [], {'restored': 1}, {'parsed': -1}, {'min_reused': True},
                      {'affected': 'a'}, {'paths': [{'source': 'a'}]}, {'new_files': ['../secret']}, {'shell': 'true'}):
            with self.assertRaises(FaultlineError):
                expectations(value)
        for control in ({'revision': 'main', 'sources': ['tests/ATest.php']},
                        {'revision': self.base, 'sources': []}, {'revision': self.base, 'sources': 'test'}):
            with self.assertRaises(FaultlineError):
                expectations({'unchanged_tests': control})
        result = run(self.store, base=self.base, output=self.store.path / 'report', environ=self.env())
        doc = checked(result['reports']['cumulative']['json'])
        doc['tests'] = [dict(copy.deepcopy(doc['tests'][0]), id='<script>|' + str(i)) for i in range(200)]
        text = markdown(doc, limit=4096)
        self.assertLess(len(text.encode()), 4096)
        self.assertIn('more candidates', text)
        self.assertNotIn('<script>', text)

    def test_exact_and_negative_controls_reject_wrong_predictions(self):
        cases = [({'exact_affected': []}, 'extra='),
                 ({'exact_affected': ['tests/BTest.php']}, 'missing='),
                 ({'unresolved': ['tests/ATest.php']}, 'configured unresolved'),
                 ({'unresolved': ['tests/MissingTest.php']}, 'configured unresolved'),
                 ({'unchanged_tests': {'revision': self.base, 'sources': ['tests/MissingTest.php']}}, 'unchanged')]
        for index, (expected, message) in enumerate(cases):
            with self.subTest(expected=expected), self.assertRaisesRegex(FaultlineError, message):
                run(self.store, base=self.base, expected=expected, output=self.store.path / f'bad-{index}')

    def test_existing_test_control_rejects_modified_test(self):
        (self.root / 'tests/ATest.php').write_text('<?php class ATest { function testA() { return 1; } }')
        self.commit()
        with self.assertRaisesRegex(FaultlineError, 'unchanged'):
            run(self.store, base=self.base, expected={'unchanged_tests': {
                'revision': self.base, 'sources': ['tests/ATest.php']}}, output=self.store.path / 'modified')

    def test_missing_baseline_is_a_cold_report_not_an_omission(self):
        with patch('faultline.tia.graph_ci.fetch', return_value={'restored': False, 'reason': 'no_eligible_ancestor_baseline'}):
            result = run(self.store, base=self.base, trusted_branch='main', output=self.store.path / 'missing', environ=self.env())
        self.assertFalse(result['restore']['restored'])
        self.assertEqual('full_suite', result['ci_policy'])
        self.assertTrue(result['validation']['passed'])
