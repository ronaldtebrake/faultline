"""Context is source evidence, not a candidate filter or mutable description store."""
import copy
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import test_benchmark as fixture
from faultline.cli import main
from faultline.core import FaultlineError, Store, write_json
from faultline.tia.benchmark import benchmark, render
from faultline.tia.benchmark_recovery import recover
from faultline.tia.benchmark_windows import RecoveryPlan
from faultline.tia.common import checked
from faultline.tia.context import assessment_context, build, sha
from faultline.tia.selection import change


class ContextTests(unittest.TestCase):
    setUp = fixture.BenchmarkTests.setUp
    git = fixture.BenchmarkTests.git
    commit = fixture.BenchmarkTests.commit
    engine = fixture.BenchmarkTests.engine

    def bundle(self, **extra):
        manifest = {'schema_version': 1, 'evidence': [
            {'kind': 'git_file', 'path': 'src/Service.php', 'revision': 'head'}], **extra}
        path = self.store.path / 'context-manifest.json'
        write_json(path, manifest)
        return build(self.store, self.base, self.head, path)

    def score(self, context_path=None, **kw):
        engine, calls = self.engine()
        with patch('faultline.tia.runners.invoke', side_effect=AssertionError('No execution')):
            result = benchmark(self.store, self.base, self.head, evaluator=engine, context_path=context_path, **kw)
        return checked(Path(result['json'])), calls, result

    def test_adds_pinned_product_source_without_filtering_and_preserves_baseline_cache(self):
        before, plain, _ = self.score()
        self.assertTrue(plain)
        self.assertNotIn('class Service', json.dumps(plain))
        frozen = self.bundle()
        (self.root / 'src/Service.php').write_text('DIRTY LOCAL SOURCE MUST NOT BE SENT')
        bundle = checked(Path(frozen['output']))
        self.assertIn('class Service', bundle['evidence'][0]['text'])
        after, enriched, result = self.score(frozen['output'])
        self.assertTrue(enriched)
        self.assertIn('class Service', json.dumps(enriched))
        self.assertNotIn('DIRTY LOCAL', json.dumps(enriched))
        self.assertEqual(before['policies']['jev']['ranking'], after['policies']['jev']['ranking'])
        self.assertEqual(before['change']['diff'], after['change']['diff'])
        self.assertEqual(2, len(after['policies']['jev']['judgments']))
        self.assertIn('context-v1', after['contract'])
        self.assertNotIn(str(self.root), json.dumps(bundle))
        report = Path(result['markdown']).read_text()
        self.assertIn('diff + collected context', report)
        self.assertIn('Combined collection and Jev cost: unknown', report)
        _, cached, _ = self.score()
        self.assertEqual([], cached)

    def test_pinning_ranges_artifacts_and_upstream_diffs(self):
        artifact = self.store.path / 'release.txt'
        artifact.write_text('Exact published source excerpt\n')
        output = self.bundle(repositories={'library': str(self.root)}, evidence=[
            {'kind': 'git_file', 'path': 'src/Service.php', 'revision': 'base', 'start_line': 1, 'end_line': 1},
            {'kind': 'git_diff', 'repository': 'library', 'base': self.base, 'head': self.head},
            {'kind': 'artifact', 'file': str(artifact), 'source': 'https://example.org/library/release/1.2', 'sha256': sha(artifact.read_bytes())}])
        data = checked(Path(output['output']))
        self.assertEqual(self.base, data['evidence'][0]['revision'])
        self.assertIn('-<?php class Policy', data['evidence'][1]['text'])
        self.assertIn('not independently verified', data['evidence'][2]['verification'])
        with self.assertRaisesRegex(FaultlineError, 'SHA-256'):
            self.bundle(evidence=[{'kind': 'artifact', 'file': str(artifact), 'source': 'https://example.org/release', 'sha256': 'wrong'}])
        with self.assertRaisesRegex(FaultlineError, 'line range'):
            self.bundle(evidence=[{'kind': 'git_file', 'path': 'src/Service.php', 'end_line': 500}])
        with self.assertRaisesRegex(FaultlineError, 'repository-relative'):
            self.bundle(evidence=[{'kind': 'git_file', 'path': '../secret'}])

    def test_rejects_wrong_snapshot_or_tampering_before_inference(self):
        output = self.bundle()['output']
        engine, calls = self.engine()
        with self.assertRaisesRegex(FaultlineError, 'exact change'):
            benchmark(self.store, self.head, self.base, evaluator=engine, context_path=output)
        self.assertEqual([], calls)
        p = Path(output)
        data = json.loads(p.read_text())
        data['evidence'][0]['text'] = 'replacement'
        write_json(p, data)
        with self.assertRaisesRegex(FaultlineError, 'modified'):
            benchmark(self.store, self.base, self.head, evaluator=engine, context_path=p)
        self.assertEqual([], calls)

    def test_known_gaps_retain_all_and_remain_incomplete_after_recovery(self):
        output = self.bundle(gaps=['Upstream revision source was unavailable'])
        self.assertFalse(output['complete'])
        case, calls, result = self.score(output['output'])
        self.assertTrue(calls)  # Diagnostic scores remain available for every target.
        self.assertFalse(case['complete'])
        self.assertEqual([], case['policies']['jev']['would_omit'])
        self.assertEqual(['unit:default'], case['policies']['jev']['full_suites'])
        engine, _ = self.engine()
        recovered = recover(self.store, result['json'], evaluator=engine)
        self.assertFalse(recovered['complete'])
        self.assertEqual(0, recovered['policies']['jev']['would_omit'])
        self.assertIn('Context gaps', Path(recovered['markdown']).read_text())

    def test_collection_metadata_not_part_of_inference_cache_and_actual_source_is(self):
        first, calls, _ = self.score(self.bundle()['output'])
        self.assertTrue(calls)
        second, calls, result = self.score(self.bundle(collector={'name': 'fixture-agent', 'cost_usd': .1, 'input_tokens': 200, 'output_tokens': 40})['output'])
        self.assertEqual([], calls)
        self.assertNotEqual(first['context_bundle']['integrity'], second['context_bundle']['integrity'])
        self.assertEqual(first['request_manifest'], second['request_manifest'])
        self.assertIn('$0.1000', Path(result['markdown']).read_text())
        third, calls, _ = self.score(self.bundle(evidence=[{'kind': 'git_file', 'path': 'src/Policy.php', 'revision': 'base'}])['output'])
        self.assertTrue(calls)
        self.assertNotEqual(second['request_manifest'], third['request_manifest'])

    def test_frozen_recovery_does_not_need_collector_checkout_or_sources(self):
        output = self.bundle(repositories={'library': str(self.root)}, evidence=[
            {'kind': 'git_diff', 'repository': 'library', 'base': self.base, 'head': self.head}])
        engine, calls = self.engine(limit=0)
        result = benchmark(self.store, self.base, self.head, evaluator=engine, context_path=output['output'])
        self.assertEqual([], calls)
        case = checked(Path(result['json']))
        shutil.rmtree(self.root / '.git')
        Path(output['output']).unlink()
        engine, calls = self.engine()
        with patch('subprocess.run', side_effect=AssertionError('Frozen recovery is offline')):
            recovered = recover(self.store, result['json'], evaluator=engine)
        self.assertTrue(calls)
        self.assertTrue(recovered['complete'])
        new = checked(Path(recovered['json']))
        self.assertEqual(case['context_bundle'], new['context_bundle'])
        self.assertEqual(case['change'], new['change'])
        self.assertTrue(all('context_evidence' in req['state']['change'] for req in calls))

    def test_large_context_windows_cover_all_source_and_keep_provenance(self):
        artifact = self.store.path / 'large.txt'
        artifact.write_text('public function integration() { /* exact source */ }\n' * 240)
        output = self.bundle(evidence=[{'kind': 'artifact', 'file': str(artifact), 'source': 'https://example.org/source/abc', 'sha256': sha(artifact.read_bytes())}])
        plain, _, _ = self.score()
        bundle = checked(Path(output['output']))
        context = assessment_context(plain['change'], bundle)
        settings = {**self.config['evaluator'], 'max_state_bytes': 6000, 'max_batch_bytes': 14000}
        ids = {p['id'] for p in plain['inputs']}
        plan = RecoveryPlan(context, plain['inputs'], {'jev': ids}, settings)
        self.assertFalse(plan.rejected['jev'])
        for id, parts in plan.parts['jev'].items():
            covered = [False] * len(context['diff'])
            for part in parts:
                a, b = part['change_range']
                covered[a:b] = [True] * (b-a)
            self.assertTrue(all(covered))
        self.assertGreater(len(plan.groups), 1)
        for group in plan.groups:
            request = group['jev']
            self.assertEqual(context['context_evidence'], request['state']['change']['context_evidence'])
            for q in request['questions'].values():
                self.assertIn('Supporting files are context', q['instructions']['task'])

    def test_context_cli_and_preparation_are_offline(self):
        path = self.store.path / 'manifest.json'
        output = self.store.path / 'context.json'
        (self.store.path / '.gitignore').unlink()
        write_json(path, {'schema_version': 1, 'evidence': [{'kind': 'git_file', 'path': 'src/Service.php'}]})
        with patch('builtins.print'), patch('faultline.tia.runners.invoke', side_effect=AssertionError('No runner')):
            self.assertEqual(0, main(['--root', str(self.root), 'context', '--base', self.base, '--input', str(path), '--output', str(output)]))
            self.assertEqual(0, main(['--root', str(self.root), 'benchmark', '--base', self.base, '--context', str(output), '--prepare']))
        self.assertTrue(output.is_file())
        self.assertEqual('*\n', (self.store.path / '.gitignore').read_text())
        self.assertFalse((self.store.path / 'runs').exists())

    def test_thresholds_and_comment_render_with_context_and_do_not_expose_source(self):
        output = self.bundle(collector={'cost_usd': .1})
        case, _, result = self.score(output['output'])
        report = render(result['json'], compare_policies=True)
        md = Path(report['markdown']).read_text()
        for percent in ('10%', '25%', '50%'):
            self.assertIn(percent, md)
        comment = render(result['json'], format='comment', compare_policies=True)
        content = Path(comment['markdown']).read_text()
        self.assertIn('diff + collected context', content)
        self.assertNotIn(str(self.root), content)
        self.assertNotIn('class Service', content)
        self.assertIn('Context collection (self-reported)', content)

    def test_enriched_whole_and_source_modes_and_unsupported_file_pairs(self):
        output = self.bundle()['output']
        for mode in ('whole', 'source'):
            case, calls, _ = self.score(output, evidence_mode=mode)
            self.assertTrue(case['complete'])
            self.assertIn('class Service', json.dumps(calls))
        with self.assertRaisesRegex(FaultlineError, 'require adaptive'):
            self.score(output, evidence_mode='file-pairs')

    def test_bundle_reuses_across_checkouts(self):
        output = self.bundle()['output']
        other = self.root.parent / 'second'
        subprocess.run(['git', 'clone', '-q', str(self.root), str(other)], check=True)
        engine, calls = self.engine()
        result = benchmark(Store(other), self.base, self.head, context_path=output, evaluator=engine)
        self.assertTrue(result['complete'])
        self.assertTrue(calls)
        self.assertNotIn(str(self.root), json.dumps(calls))


if __name__ == '__main__':
    unittest.main()
