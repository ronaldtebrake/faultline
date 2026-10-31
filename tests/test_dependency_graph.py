"""Incremental dependencies across Behat, browser tests, and Git histories."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from faultline.cli import main
from faultline.core import Store, FaultlineError, write_json
from faultline.tia.dependency_graph import build, compare, read
from faultline.tia.dependency_sources import php, javascript, gherkin, match_steps, parse_many
from faultline.tia.dependency_runtime import capture_context, import_records
from faultline.tia.impact import assess, assessment_path
from faultline.tia.impact_transport import MODEL
from faultline.tia.ci_manifest import from_assessment
from faultline.tia.config import load_config
from faultline.tia.common import checked


class DependencyGraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git('init', '-q', '-b', 'main')
        self.write('.gitignore', '.faultline/\n')
        self.raw = {'schema_version': 2, 'repository': 'dependency-fixture', 'scope': ['src/**'], 'suites': [
            {'id': 'browser', 'runner': 'playwright', 'sources': ['e2e/**/*.spec.ts'], 'shared_inputs': ['playwright.config.ts']},
            {'id': 'acceptance', 'runner': 'behat', 'sources': ['features/**/*.feature']}]}
        write_json(self.root / 'faultline.json', self.raw)
        self.write('playwright.config.ts', 'export default {};')
        self.write('e2e/checkout.spec.ts', "import {checkout} from './pages/checkout'; test('checkout', checkout);")
        self.write('e2e/pages/checkout.ts', "import {price} from '../../src/price.js'; export const checkout = () => price();")
        self.write('e2e/profile.spec.ts', "test('profile', async ({page}) => page.goto('/profile'));")
        self.write('src/price.ts', 'export const price = () => 12;')
        self.write('features/checkout.feature', 'Feature: checkout\n Scenario: total\n  Given a basket\n  Then the total is 12\n')
        self.write('features/profile.feature', 'Feature: profile\n Scenario: name\n  Given I view my profile\n')
        self.write('features/bootstrap/CheckoutContext.php', """<?php
namespace Test;
use App\\Calculator;
class CheckoutContext {
    #[Given('a basket')]
    public function basket() { return new Calculator(); }
    /** @Then /^the total is (\\d+)$/ */
    public function total($n) { return Calculator::total(); }
}
""")
        self.write('src/Calculator.php', '<?php namespace App; class Calculator { public static function total() { return 12; } }')
        self.commit()
        self.base = self.git('rev-parse', 'HEAD').strip()
        self.store = Store(self.root)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, text=True).stdout

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')

    def test_browser_import_closure_and_incremental_blob_cache(self):
        first = build(self.store)
        self.write('src/price.ts', 'export const price = () => 13;')
        self.commit()
        from faultline.tia.evidence import GitSources
        fetched = []
        prefetch = GitSources.prefetch
        def track(source, paths):
            fetched.extend(paths)
            return prefetch(source, paths)
        with patch('faultline.tia.dependency_sources.parse', wraps=__import__('faultline.tia.dependency_sources', fromlist=['parse']).parse) as parse, patch.object(GitSources, 'prefetch', track):
            second = build(self.store)
            self.assertEqual(['src/price.ts'], [c.args[0] for c in parse.call_args_list])
            self.assertEqual(['src/price.ts'], fetched)
        result = compare(first['graph'], second['graph'])
        self.assertEqual(['browser:default:e2e/checkout.spec.ts'], result['affected'])
        self.assertIn('browser:default:e2e/profile.spec.ts', result['unresolved'])
        self.assertFalse(result['omission_authorized'])
        self.assertEqual(0, result['jev_requests'])
        self.assertEqual(1, second['parsed'])
        with patch('faultline.tia.dependency_sources.parse', side_effect=AssertionError('No reparsing')):
            self.assertTrue(build(self.store)['snapshot_reused'])

    def test_size_limit_gap_reuses_snapshot_and_limit_changes_rebuild_bindings(self):
        self.write('src/large.js', ' ' * 2048 + "export {price} from './price.js';")
        self.raw['evaluator'] = {'max_test_bytes': 1024}
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        first = build(self.store)
        self.assertEqual(['source_exceeds_max_test_bytes'], first['graph']['nodes']['src/large.js']['gaps'])
        self.assertTrue(build(self.store)['snapshot_reused'])
        # Evaluator limits are not execution config. They must nevertheless be
        # part of graph identity, even with an unchanged Git revision.
        self.raw['evaluator']['max_test_bytes'] = 4096
        write_json(self.root / 'faultline.json', self.raw)
        expanded = build(self.store)
        self.assertNotEqual(first['path'], expanded['path'])
        self.assertTrue(any(e['from'] == 'src/large.js' and e['to'] == 'src/price.ts' for e in expanded['graph']['edges']))
        # Lowering the limit cannot bypass it through an existing blob cache.
        self.raw['evaluator']['max_test_bytes'] = 1536
        write_json(self.root / 'faultline.json', self.raw)
        reduced = build(self.store)
        self.assertEqual(['source_exceeds_max_test_bytes'], reduced['graph']['nodes']['src/large.js']['gaps'])
        self.assertFalse(any(e['from'] == 'src/large.js' for e in reduced['graph']['edges']))

    @unittest.skipUnless(shutil.which('php'), 'PHP source tokenizer')
    def test_php_batches_preserve_per_file_scope_and_do_not_execute_source(self):
        marker = self.root / 'must-not-exist'
        first = "<?php namespace A; use Other\\Thing; class Context { /** @Given a basket */ public function step() { return new Thing(); } }"
        second = "<?php namespace B; file_put_contents(" + json.dumps(str(marker)) + ", 'bad'); class Context { public function step(Thing $thing) {} }"
        entries = [('a.php', first.encode()), ('b.php', second.encode()), ('binary.php', b'<?php\0'), ('utf8.php', b'\xff')]
        import faultline.tia.dependency_sources as adapters
        with patch.object(adapters, 'php_batch', wraps=adapters.php_batch) as calls:
            actual = dict(parse_many(entries))
        self.assertEqual(1, calls.call_count)
        self.assertEqual({'language': 'php', **php(first)}, actual['a.php'])
        self.assertEqual({'language': 'php', **php(second)}, actual['b.php'])
        self.assertIn('B\\Thing', actual['b.php']['references'])
        self.assertEqual(['binary_source'], actual['binary.php']['gaps'])
        self.assertEqual(['non_utf8_source'], actual['utf8.php']['gaps'])
        self.assertFalse(marker.exists())
        with patch.object(adapters, 'PHP_BATCH_FILES', 1), patch.object(adapters, 'php_batch', wraps=adapters.php_batch) as calls:
            self.assertEqual(actual, dict(parse_many(entries)))
        self.assertEqual(2, calls.call_count)

    @unittest.skipUnless(shutil.which('php'), 'PHP source tokenizer')
    def test_missing_tokenizer_has_explicit_unavailable_status(self):
        import faultline.tia.dependency_sources as adapters
        script = Path(adapters.__file__).with_name('dependency_php.php')
        result = subprocess.run(['php', '-n', '-d', 'disable_functions=token_get_all', str(script), '--batch'],
                                input='["<?php class Example {}"]', text=True, capture_output=True)
        self.assertEqual(78, result.returncode)
        self.assertEqual('', result.stdout)
        self.assertIn('requires the PHP tokenizer extension', result.stderr)
        with patch.object(adapters.subprocess, 'run', return_value=result):
            self.assertEqual(['php_tokenizer_unavailable'], adapters.php('<?php')['gaps'])

    @unittest.skipUnless(shutil.which('php'), 'PHP source tokenizer')
    def test_transient_php_failure_is_retried_and_duplicate_blobs_are_parsed_once(self):
        self.write('src/CalculatorCopy.php', (self.root / 'src/Calculator.php').read_text())
        self.commit()
        import faultline.tia.dependency_sources as adapters
        def unavailable(texts):
            return [{'gaps': ['php_tokenizer_unavailable']} for _ in texts]
        with patch.object(adapters, 'php_batch', side_effect=unavailable):
            failed = build(self.store)
        self.assertIn('php_tokenizer_unavailable', failed['graph']['nodes']['src/Calculator.php']['gaps'])
        with patch.object(adapters, 'php_batch', wraps=adapters.php_batch) as calls:
            repaired = build(self.store)
        self.assertEqual(2, sum(len(call.args[0]) for call in calls.call_args_list))
        self.assertNotIn('php_tokenizer_unavailable', repaired['graph']['nodes']['src/Calculator.php']['gaps'])
        self.assertFalse(repaired['snapshot_reused'])
        self.assertTrue(build(self.store)['snapshot_reused'])

    @unittest.skipUnless(shutil.which('php'), 'PHP source tokenizer')
    def test_repeated_steps_are_matched_once_per_tree(self):
        self.write('features/another.feature', 'Feature: another\n Scenario: total\n  Given a basket\n')
        self.commit()
        import faultline.tia.dependency_sources as adapters
        with patch.object(adapters, 'match_steps', wraps=adapters.match_steps) as calls:
            first = build(self.store)
        texts = [text for call in calls.call_args_list for text in call.args[0]]
        self.assertEqual(1, texts.count('a basket'))
        for feature in ('features/checkout.feature', 'features/another.feature'):
            self.assertTrue(any(e['from'] == feature and e['to'] == 'features/bootstrap/CheckoutContext.php' for e in first['graph']['edges']))

    @unittest.skipUnless(shutil.which('php'), 'PHP source tokenizer')
    def test_behat_steps_reach_php_code_without_loading_contexts(self):
        first = build(self.store)
        edges = first['graph']['edges']
        self.assertTrue(any(e['from'] == 'features/checkout.feature' and e['kind'] == 'behat_step' for e in edges))
        self.write('src/Calculator.php', '<?php namespace App; class Calculator { public static function total() { return 13; } }')
        self.commit()
        result = compare(first['graph'], build(self.store)['graph'])
        self.assertIn('acceptance:default:features/checkout.feature', result['affected'])
        self.assertNotIn('acceptance:default:features/profile.feature', result['affected'])
        self.assertIn('acceptance:default:features/profile.feature', result['unresolved'])

    @unittest.skipUnless(shutil.which('php'), 'PHP source tokenizer')
    def test_new_definition_reresolves_unchanged_feature(self):
        first = build(self.store)
        self.write('features/bootstrap/ProfileContext.php', "<?php class ProfileContext { #[Given('I view my profile')] public function profile() {} }")
        self.commit()
        result = compare(first['graph'], build(self.store)['graph'])
        self.assertIn('acceptance:default:features/profile.feature', result['affected'])
        self.assertGreater(result['added_edges'], 0)

    def test_removed_dependency_uses_base_graph(self):
        first = build(self.store)
        (self.root / 'src/price.ts').unlink()
        self.commit()
        second = build(self.store)
        result = compare(first['graph'], second['graph'])
        self.assertIn('browser:default:e2e/checkout.spec.ts', result['affected'])
        self.assertGreater(result['removed_edges'], 0)
        self.assertIn('unresolved_import:../../src/price.js', second['graph']['nodes']['e2e/pages/checkout.ts']['gaps'])

    def test_historical_build_ignores_worktree_and_preserves_branches(self):
        first = build(self.store)
        self.write('src/price.ts', 'export const price = () => 999;')
        old = build(self.store, self.base)
        self.assertEqual(first['graph'], old['graph'])
        self.assertEqual('export const price = () => 999;', (self.root / 'src/price.ts').read_text())

    def test_shared_config_selects_all_browser_variants(self):
        self.raw['suites'][0]['variants'] = [{'id': 'chromium'}, {'id': 'firefox'}]
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        first = build(self.store)
        self.write('playwright.config.ts', 'export default { retries: 2 };')
        self.commit()
        result = compare(first['graph'], build(self.store)['graph'])
        self.assertEqual(4, len(result['affected']))
        self.assertTrue(all(t.startswith('browser:') for t in result['affected']))

    def test_snapshots_validate_repository_config_and_integrity(self):
        first = build(self.store)
        self.assertEqual(first['graph'], read(first['path']))
        other = {**first['graph'], 'repository': 'different'}
        with self.assertRaises(FaultlineError):
            compare(first['graph'], other)
        value = json.loads(Path(first['path']).read_text())
        value['edges'] = []
        write_json(Path(first['path']), value)
        with self.assertRaises(FaultlineError):
            read(first['path'])

    def test_cli_build_and_compare_are_offline(self):
        with patch('builtins.print') as output, patch('faultline.tia.runners.invoke', side_effect=AssertionError('No runner')):
            self.assertEqual(0, main(['--root', str(self.root), 'graph', 'build']))
            result = json.loads(output.call_args.args[0])
            self.assertEqual(4, result['targets'])
            self.assertEqual(0, result['jev_requests'])
            self.assertEqual(0, main(['--root', str(self.root), 'graph', 'compare', '--base', self.base]))
            self.assertFalse(json.loads(output.call_args.args[0])['omission_authorized'])

    def runtime(self, runner='behat', test='features/profile.feature', files=None):
        suite = 'acceptance:default' if runner == 'behat' else 'browser:default'
        context = self.store.path / 'runtime-context.json'
        captured = capture_context(self.store, suite, context)
        raw = {'version': 1, 'context': captured['context'], 'producer': runner, 'test_source': test,
               'test_identity': test + ':3', 'status': 'passed', 'files': files or [], 'resources': [], 'gaps': []}
        path = self.store.path / 'runtime-raw.json'
        write_json(path, raw)
        return context, path, raw

    def test_runtime_baseline_attributes_unmatched_feature_and_retains_old_paths(self):
        context, path, raw = self.runtime(files=['src/Calculator.php'])
        evidence = import_records(self.store, context, [path])
        first = build(self.store, runtime_paths=[evidence['path']])
        self.write('src/Calculator.php', '<?php namespace App; class Calculator {}')
        self.commit()
        result = compare(first['graph'], build(self.store)['graph'])
        self.assertIn('acceptance:default:features/profile.feature', result['affected'])
        later = build(self.store, runtime_paths=[evidence['path']])['graph']
        self.assertEqual(0, later['runtime_reuse']['carried'])
        self.assertEqual(['src/Calculator.php'], later['runtime_reuse']['invalidated'][0]['changed_inputs'])
        self.assertIn('acceptance:default:features/profile.feature', compare(first['graph'], later)['affected'])

    def test_runtime_baseline_survives_unrelated_commits_and_preserves_provenance(self):
        context, path, raw = self.runtime(files=['src/Calculator.php'])
        evidence = import_records(self.store, context, [path])
        first = build(self.store, runtime_paths=[evidence['path']])
        self.write('src/price.ts', 'export const price = () => 14;')
        self.commit()
        self.write('docs/readme.txt', 'Unrelated new file')
        self.commit()
        second = build(self.store, runtime_paths=[evidence['path']])
        self.assertEqual(1, second['graph']['runtime_reuse']['carried'])
        self.assertEqual([], second['graph']['runtime_reuse']['invalidated'])
        observation = second['graph']['observations']['acceptance:default:features/profile.feature'][0]
        self.assertEqual(self.base, observation['provenance']['revision'])
        self.assertEqual('carried', observation['freshness'])
        self.assertEqual(first['graph'], read(first['path']))
        base = self.git('rev-parse', 'HEAD').strip()
        self.write('src/Calculator.php', '<?php namespace App; class Calculator {}')
        self.commit()
        prepared = assess(self.store, base=base, dependencies=True, runtime_paths=[evidence['path']], prepare=True)
        # Both the statically linked checkout feature and the CI-linked profile
        # feature are retained, even though the old CI run predates this PR.
        self.assertEqual(2, prepared['dependency_selected'])

    def test_runtime_baseline_invalidates_changed_test_setup_and_transitive_source(self):
        context, path, raw = self.runtime('playwright', 'e2e/profile.spec.ts', ['e2e/pages/checkout.ts'])
        evidence = import_records(self.store, context, [path])
        for source, replacement in [('src/price.ts', 'export const price = () => 15;'),
                                    ('playwright.config.ts', 'export default {retries: 2};'),
                                    ('e2e/profile.spec.ts', "test('different', async () => {});")]:
            previous = (self.root / source).read_text()
            self.write(source, replacement)
            self.commit()
            graph = build(self.store, runtime_paths=[evidence['path']])['graph']
            self.assertEqual(0, graph['runtime_reuse']['carried'])
            self.assertIn(source, graph['runtime_reuse']['invalidated'][0]['changed_inputs'])
            self.write(source, previous)
            self.commit()
        self.assertEqual(1, build(self.store, runtime_paths=[evidence['path']])['graph']['runtime_reuse']['carried'])

    @unittest.skipUnless(shutil.which('php'), 'PHP source tokenizer')
    def test_new_step_resolution_invalidates_unchanged_runtime_test(self):
        context, path, raw = self.runtime(files=['src/Calculator.php'])
        evidence = import_records(self.store, context, [path])
        self.write('features/bootstrap/ProfileContext.php', "<?php class ProfileContext { #[Given('I view my profile')] public function profile() {} }")
        self.commit()
        graph = build(self.store, runtime_paths=[evidence['path']])['graph']
        self.assertEqual(0, graph['runtime_reuse']['carried'])
        self.assertTrue(graph['runtime_reuse']['invalidated'][0]['resolution_changed'])

    def test_runtime_baseline_rejects_sibling_branch_and_missing_history(self):
        self.git('checkout', '-qb', 'observed')
        self.write('branch.txt', 'observed branch')
        self.commit()
        context, path, raw = self.runtime()
        evidence = import_records(self.store, context, [path])
        self.git('checkout', '-q', 'main')
        self.write('sibling.txt', 'separate branch')
        self.commit()
        with self.assertRaisesRegex(FaultlineError, 'ancestor'):
            build(self.store, runtime_paths=[evidence['path']])
        from faultline.tia.common import save_frozen
        missing = checked(evidence['path'])
        missing['revision'] = 'f' * 40
        missing_path = self.store.path / 'missing-history.json'
        save_frozen(missing_path, missing)
        with self.assertRaisesRegex(FaultlineError, 'ancestor'):
            build(self.store, runtime_paths=[missing_path])

    def test_runtime_rejects_wrong_revision_dirty_sources_unknown_tests_and_escaping_paths(self):
        context, path, raw = self.runtime()
        for field, value in [('context', 'wrong'), ('test_source', 'features/missing.feature'), ('files', ['../outside.php']), ('files', ['vendor/missing.php'])]:
            write_json(path, {**raw, field: value})
            with self.assertRaises(FaultlineError):
                import_records(self.store, context, [path])
        write_json(path, raw)
        self.write('src/price.ts', 'dirty')
        with self.assertRaises(FaultlineError):
            import_records(self.store, context, [path])
        self.commit()
        with self.assertRaises(FaultlineError):
            import_records(self.store, context, [path])

    def test_runtime_browser_requests_remain_observations_and_retry_union(self):
        context, path, raw = self.runtime('playwright', 'e2e/profile.spec.ts')
        raw['resources'] = [{'kind': 'http_request', 'method': 'GET', 'path': '/profile'}]
        write_json(path, [raw, {**raw, 'retry': 1, 'files': ['src/price.ts']}])
        evidence = import_records(self.store, context, [path])
        result = build(self.store, runtime_paths=[evidence['path']])
        row = result['graph']['observations']['browser:default:e2e/profile.spec.ts']
        self.assertEqual(2, len(row))
        self.assertEqual('/profile', row[0]['resources'][0]['path'])
        self.assertTrue(any(e['kind'] == 'runtime_observation' for e in result['graph']['edges']))
        self.assertFalse(evidence['coverage_complete'])

    def test_runtime_generation_validates_exact_source_and_keeps_declared_inputs(self):
        import hashlib
        context, path, raw = self.runtime('playwright', 'e2e/profile.spec.ts')
        names = ['e2e/profile.spec.ts', 'src/price.ts']
        generation = {'version': 1, 'revision': self.git('rev-parse', 'HEAD').strip(),
                      'source': raw['test_source'],
                      'inputs': {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest() for name in names}}
        raw = {**raw, 'files': [], 'generation': generation}
        write_json(path, raw)
        imported = import_records(self.store, context, [path])
        record = checked(imported['path'])['records'][0]
        self.assertEqual(names, record['files'])
        self.assertEqual(generation, record['generation'])
        invalid = [
            {**generation, 'revision': 'a' * 40},
            {**generation, 'source': 'e2e/checkout.spec.ts'},
            {**generation, 'inputs': {**generation['inputs'], 'src/price.ts': '0' * 64}},
            {**generation, 'inputs': {'src/price.ts': generation['inputs']['src/price.ts']}},
            {**generation, 'inputs': {**generation['inputs'], '../outside.ts': '0' * 64}},
            {**generation, 'inputs': {**generation['inputs'], 'untracked.ts': '0' * 64}},
            {**generation, 'extra': 'unsupported'},
        ]
        for mapping in invalid:
            write_json(path, {**raw, 'generation': mapping})
            with self.assertRaises(FaultlineError):
                import_records(self.store, context, [path])

    def test_runtime_generation_artifacts_require_explicit_bounded_local_bytes(self):
        import hashlib
        context, path, raw = self.runtime('playwright', 'e2e/profile.spec.ts')
        artifact = '.faultline/catalog.json'
        self.write(artifact, '{"release":"standard"}')
        digest = hashlib.sha256((self.root / artifact).read_bytes()).hexdigest()
        generation = {'version': 2, 'revision': self.git('rev-parse', 'HEAD').strip(),
                      'source': raw['test_source'],
                      'inputs': {raw['test_source']: hashlib.sha256((self.root / raw['test_source']).read_bytes()).hexdigest()},
                      'artifacts': {artifact: digest}}
        raw = {**raw, 'files': [], 'generation': generation}
        write_json(path, raw)
        imported = import_records(self.store, context, [path])
        self.assertEqual(generation, checked(imported['path'])['records'][0]['generation'])
        symlink = self.root / '.faultline/alias.json'
        symlink.symlink_to(self.root / artifact)
        for artifacts in ({}, [], {artifact: True}, {artifact: '0' * 64},
                          {'../catalog.json': digest}, {'/catalog.json': digest},
                          {'.faultline/alias.json': digest}, {'missing.json': digest},
                          {raw['test_source']: generation['inputs'][raw['test_source']]}):
            with self.subTest(artifacts=artifacts), self.assertRaises(FaultlineError):
                write_json(path, {**raw, 'generation': {**generation, 'artifacts': artifacts}})
                import_records(self.store, context, [path])
        write_json(path, raw)
        with (self.root / artifact).open('wb') as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(FaultlineError, 'generation artifact'):
            import_records(self.store, context, [path])
        self.write('unrelated.txt', 'next revision')
        self.commit()
        destination = self.git('rev-parse', 'HEAD').strip()
        self.write('unrelated.txt', 'later checkout')
        self.commit()
        historical = build(self.store, generation['revision'], runtime_paths=[imported['path']])['graph']
        self.assertEqual(1, historical['runtime_reuse']['observed'])
        unverified = build(self.store, destination, runtime_paths=[imported['path']])['graph']
        self.assertEqual(0, unverified['runtime_reuse']['carried'])
        self.assertEqual('historical', unverified['runtime_reuse']['invalidated'][0]['artifact_state'])

    @unittest.skipUnless(shutil.which('php'), 'PHP source tokenizer')
    def test_dependency_assessment_scores_only_unresolved_and_exports_without_fake_probabilities(self):
        self.write('src/Calculator.php', '<?php namespace App; class Calculator { public static function total() { return 13; } }')
        self.commit()
        scored = []
        def sender(payload, timeout):
            for q in payload['questions'].values():
                scored.append(q['instructions'].get('test', q['instructions'].get('test_identity'))['id'])
            return 200, {}, {'model': MODEL, 'answers': {q: {'type': 'noul', 'noul': .01} for q in payload['questions']},
                             'usage': {'input_tokens': 100, 'output_tokens': 1}}
        result = assess(self.store, base=self.base, dependencies=True, transport=sender)
        doc = checked(assessment_path(self.store, result['run_id']))
        target = 'acceptance:default:features/checkout.feature'
        self.assertNotIn(target, scored)
        self.assertEqual(3, len(scored))
        self.assertNotIn(target, doc['scores'])
        self.assertIn(target, doc['dependency_evidence']['selected'])
        self.assertTrue(doc['complete'])
        manifest, _ = from_assessment(doc, load_config(self.root), .5)
        self.assertEqual({'mode': 'selected', 'files': ['features/checkout.feature']}, manifest['suites']['acceptance'])
        resumed = assess(self.store, resume=result['run_id'], transport=lambda *a: self.fail('No new calls on resume'))
        self.assertTrue(resumed['complete'])

    def test_known_browser_dependency_needs_no_jev_or_credentials(self):
        self.raw['suites'] = [{**self.raw['suites'][0], 'sources': ['e2e/checkout.spec.ts']}]
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        base = self.git('rev-parse', 'HEAD').strip()
        self.write('src/price.ts', 'export const price = () => 14;')
        self.commit()
        with patch('faultline.tia.impact.api_key', side_effect=AssertionError('No credentials')), patch('faultline.tia.impact.Pool', side_effect=AssertionError('No API')):
            prepared = assess(self.store, base=base, dependencies=True, prepare=True)
            result = assess(self.store, base=base, dependencies=True)
        self.assertEqual(0, prepared['requests'])
        self.assertEqual(1, prepared['dependency_selected'])
        self.assertEqual(0, result['usage']['requests'])
        self.assertTrue(result['complete'])

    @unittest.skipUnless(os.getenv('FAULTLINE_PLAYWRIGHT_PACKAGE'), 'Set FAULTLINE_PLAYWRIGHT_PACKAGE for real Playwright integration')
    def test_native_playwright_fixture_records_test_identity_retries_and_sanitized_requests(self):
        package = Path(os.environ['FAULTLINE_PLAYWRIGHT_PACKAGE']).resolve()
        asset = Path(__file__).resolve().parents[1] / 'skills/faultline/assets/playwright-dependencies.mjs'
        shutil.copyfile(asset, self.root / 'e2e/dependencies.mjs')
        helper = asset.parent.parent / 'scripts/faultline/tia/playwright_source.mjs'
        shutil.copyfile(helper, self.root / 'e2e/playwright_source.mjs')
        self.raw['suites'][0]['sources'] = ['e2e/**/*.spec.mjs']
        write_json(self.root / 'faultline.json', self.raw)
        self.write('playwright.config.mjs', "export default {testDir: './e2e', testMatch: '*.spec.mjs', retries: 1, workers: 1};")
        self.write('e2e/runtime.spec.mjs', "import {test as base, expect} from " + json.dumps((package / 'index.mjs').as_uri()) + ";\n" + """
import {withFaultline} from './dependencies.mjs';
const test = withFaultline(base);
test('observations survive a retry', async ({faultlineDependencies}, testInfo) => {
  faultlineDependencies.file('src/price.ts');
  faultlineDependencies.request('GET', 'https://user:password@example.invalid/profile?token=secret#private');
  expect(testInfo.retry).toBe(1);
});
""")
        self.commit()
        context = self.store.path / 'native-browser-context.json'
        capture_context(self.store, 'browser:default', context)
        output = self.store.path / 'browser-records'
        result = subprocess.run(['node', str(package / 'cli.js'), 'test', '--config=playwright.config.mjs', '--reporter=line'], cwd=self.root,
                                env={**os.environ, 'FAULTLINE_DEPENDENCY_CONTEXT': str(context), 'FAULTLINE_DEPENDENCY_OUTPUT': str(output)},
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        evidence = import_records(self.store, context, sorted(output.glob('*.json')))
        records = json.loads(Path(evidence['path']).read_text())['records']
        self.assertEqual(2, len(records))
        self.assertEqual({'passed', 'failed'}, {r['status'] for r in records})
        self.assertEqual({0, 1}, {r['retry'] for r in records})
        self.assertEqual(['src/price.ts'], records[0]['files'])
        self.assertEqual([{'kind': 'http_request', 'method': 'GET', 'path': '/profile'}], records[0]['resources'])
        self.assertNotIn('secret', Path(evidence['path']).read_text())

    @unittest.skipUnless(os.getenv('FAULTLINE_BEHAT_BINARY'), 'Set FAULTLINE_BEHAT_BINARY for real Behat integration')
    def test_native_behat_scenario_outline_records_actual_definition(self):
        asset = Path(__file__).resolve().parents[1] / 'skills/faultline/assets/FaultlineDependencyContext.php'
        shutil.copyfile(asset, self.root / 'features/bootstrap/FaultlineDependencyContext.php')
        self.write('features/bootstrap/CheckoutContext.php', """<?php
use Behat\\Behat\\Context\\Context;
class CheckoutContext implements Context {
    /** @Given a basket */
    public function basket() {}
    /** @Then /^the total is (\\d+)$/ */
    public function total($n) { if ((int)$n !== 12) throw new RuntimeException('wrong total'); }
}
""")
        self.write('features/checkout.feature', 'Feature: checkout\n Scenario Outline: total\n  Given a basket\n  Then the total is <total>\n Examples:\n  | total |\n  | 12 |\n')
        self.write('behat.yml', 'default:\n  suites:\n    fixture:\n      paths: [features/checkout.feature]\n      contexts: [CheckoutContext, FaultlineDependencyContext]\n')
        self.commit()
        context = self.store.path / 'native-context.json'
        capture_context(self.store, 'acceptance:default', context)
        output = self.store.path / 'native-records'
        result = subprocess.run([os.environ['FAULTLINE_BEHAT_BINARY'], '--no-colors', '--format=progress'], cwd=self.root,
                                env={**os.environ, 'FAULTLINE_DEPENDENCY_CONTEXT': str(context), 'FAULTLINE_DEPENDENCY_OUTPUT': str(output)},
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        evidence = import_records(self.store, context, sorted(output.glob('*.json')))
        records = json.loads(Path(evidence['path']).read_text())['records']
        self.assertEqual(1, len(records))
        self.assertEqual(['features/bootstrap/CheckoutContext.php'], records[0]['files'])
        self.assertEqual('passed', records[0]['status'])


class AdapterTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('php'), 'PHP source tokenizer')
    def test_php_binding_fingerprint_preserves_headers_and_ignores_ordinary_bodies(self):
        original = '''<?php
use function Other\\run;
#[Route('/checkout')]
class Controller {
    public const ROUTE = '/checkout';
    /** @route GET /checkout */
    public function handle(string $name): string {
        $read = function () use ($name) { return "{$name}"; };
        return $read();
    }
    abstract public function other(string $value): string;
}
'''
        baseline = php(original)['declaration_hash']
        self.assertEqual(baseline, php(original.replace('return $read();', 'return "different";'))['declaration_hash'])
        self.assertEqual(baseline, php(original.replace('return "{$name}";', 'return "other {$name}";'))['declaration_hash'])
        for before, after in [("Route('/checkout')", "Route('/profile')"),
                              ('@route GET /checkout', '@route GET /profile'),
                              ('const ROUTE = \'/checkout\'', 'const ROUTE = \'/profile\''),
                              ('handle(string $name)', 'renamed(string $name)'),
                              ('other(string $value)', 'other(int $value)'),
                              ('use function Other\\run;', 'use function Other\\changed;')]:
            with self.subTest(before=before):
                self.assertNotEqual(baseline, php(original.replace(before, after))['declaration_hash'])
        nested = '<?php function register() { function &named() { static $x = 1; return $x; } }'
        self.assertNotEqual(php(nested)['declaration_hash'], php(nested.replace('$x = 1', '$x = 2'))['declaration_hash'])

    @unittest.skipUnless(shutil.which('php'), 'PHP source tokenizer')
    def test_php_does_not_execute_and_does_not_link_method_name_collision(self):
        with tempfile.TemporaryDirectory() as folder:
            sentinel = Path(folder) / 'executed'
            facts = php("<?php namespace App; use Domain\\Actual; file_put_contents('" + str(sentinel) + "', 'bad'); class Example { public function run(Actual $a) { $this->Unrelated(); return new Actual(); } }")
            self.assertFalse(sentinel.exists())
            self.assertEqual(['App\\Example'], facts['classes'])
            self.assertIn('Domain\\Actual', facts['references'])
            self.assertNotIn('App\\Unrelated', facts['references'])

    @unittest.skipUnless(shutil.which('php'), 'PHP source tokenizer')
    def test_pcre_matching_and_unsupported_patterns_are_visible(self):
        definitions = [{'pattern': '/^the total is (\\d+)$/'}]
        self.assertEqual([0], match_steps(['the total is 12'], definitions)[0]['matches'])
        self.assertTrue(match_steps(['I have 12 apples'], [{'pattern': 'I have :count apples'}])[0]['unresolved_patterns'])

    def test_gherkin_docstrings_and_outlines(self):
        facts = gherkin('Feature: api\n Scenario Outline: input\n  Given <value>\n  Then text\n   """\n   Given this is a payload, not a step\n   """')
        self.assertEqual(['<value>', 'text'], [s['text'] for s in facts['steps']])
        self.assertIn('scenario_outline_requires_native_expansion', facts['gaps'])

    def test_javascript_reexports_dynamic_imports_and_gaps(self):
        facts = javascript("// import 'not-real';\n export {x} from './x'; const y = require('./y'); import(name);")
        self.assertEqual(['./x', './y'], facts['imports'])
        self.assertIn('dynamic_module_reference', facts['gaps'])


if __name__ == '__main__':
    unittest.main()
