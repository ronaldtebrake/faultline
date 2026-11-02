"""Task result reuse must be input-complete under the declared contract."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from faultline.core import FaultlineError, Store, write_json
from faultline.task_graph import snapshot
from faultline.task_cache import preview, run
from faultline.tia.common import checked, seal


class TaskTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.store = Store(self.root)
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        for name in ('app', 'other', 'shared'):
            (self.root / name).mkdir()
            (self.root / name / 'code.txt').write_text(name)
        (self.root / 'check.py').write_text('from pathlib import Path\np=Path(".faultline/count")\np.write_text(str(int(p.read_text())+1) if p.exists() else "1")\n')
        self.config = {'schema_version': 2, 'repository': 'fixture/tasks', 'task_graph': {
            'version': 1, 'context': {'python': sys.version, 'fixtures': 'none'},
            'global_inputs': ['check.py'], 'ignored_inputs': ['docs/**'], 'tasks': {
                'shared': {'inputs': ['shared/**']},
                'app': {'inputs': ['app/**'], 'depends_on': ['shared'], 'cache': True, 'env': [],
                        'command': [sys.executable, 'check.py']},
                'other': {'inputs': ['other/**'], 'cache': True, 'env': [],
                          'command': [sys.executable, 'check.py']}}}}
        self.commit_config()
        self.base = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL, text=True)

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')

    def commit_config(self):
        write_json(self.root / 'faultline.json', self.config)
        self.commit()

    def rows(self, value):
        return {r['task']: r for r in value['tasks']}

    def test_cold_shadow_warm_reuse_and_shared_cache_across_clone(self):
        self.assertEqual('run', self.rows(preview(self.store))['app']['decision'])
        cold = run(self.store)
        self.assertEqual(0, cold['exit_code'])
        warm = run(self.store)
        self.assertTrue(self.rows(warm)['app']['cache_match_before_run'])
        self.assertEqual('4', (self.store.path / 'count').read_text())
        reused = run(self.store, reuse=True)
        self.assertEqual('reused', self.rows(reused)['app']['status'])
        self.assertEqual('4', (self.store.path / 'count').read_text())
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(['git', 'clone', '-q', str(self.root), directory], check=True)
            other = Store(Path(directory))
            result = run(other, reuse=True, cache_dir=self.store.path / 'task-results')
            self.assertEqual('reused', self.rows(result)['app']['status'])
            self.assertFalse((other.path / 'count').exists())

    def test_new_changed_deleted_and_renamed_inputs_invalidate_transitively(self):
        run(self.store)
        (self.root / 'shared/new.txt').write_text('new dependency')
        self.commit()
        first = self.rows(preview(self.store, base=self.base))
        self.assertEqual('run', first['app']['decision'])
        self.assertEqual(['shared'], first['app']['changed_dependencies'])
        self.assertEqual('reuse', first['other']['decision'])
        run(self.store)
        (self.root / 'shared/new.txt').rename(self.root / 'shared/renamed.txt')
        self.commit()
        self.assertEqual('run', self.rows(preview(self.store))['app']['decision'])
        run(self.store)
        (self.root / 'shared/renamed.txt').unlink()
        (self.root / 'shared/code.txt').write_text('changed')
        self.commit()
        self.assertEqual('run', self.rows(preview(self.store))['app']['decision'])

    def test_unmapped_and_global_changes_invalidate_all_but_explicit_ignored_do_not(self):
        run(self.store)
        (self.root / 'docs').mkdir()
        (self.root / 'docs/readme.md').write_text('docs')
        self.commit()
        self.assertEqual('reuse', self.rows(preview(self.store))['app']['decision'])
        (self.root / 'unknown.config').write_text('new global config')
        self.commit()
        plan = preview(self.store)
        self.assertIn('unknown.config', plan['unmapped_files'])
        self.assertEqual('run', self.rows(plan)['other']['decision'])
        run(self.store)
        (self.root / 'check.py').write_text((self.root / 'check.py').read_text() + '\n# modified runner\n')
        self.commit()
        self.assertEqual('run', self.rows(preview(self.store))['other']['decision'])

    def test_environment_context_command_and_configuration_invalidate(self):
        self.config['task_graph']['tasks']['app']['env'] = ['TASK_FIXTURE_VERSION']
        self.commit_config()
        env = dict(os.environ, TASK_FIXTURE_VERSION='private-fixture-value')
        run(self.store, environ=env)
        first = preview(self.store, environ=env)
        self.assertNotIn('private-fixture-value', json.dumps(first))
        changed = self.rows(preview(self.store, environ=dict(env, TASK_FIXTURE_VERSION='v2')))
        self.assertEqual('run', changed['app']['decision'])
        self.assertEqual('reuse', changed['other']['decision'])
        with self.assertRaisesRegex(FaultlineError, 'Missing declared'):
            preview(self.store, environ={})
        self.config['task_graph']['context']['fixtures'] = 'v2'
        self.commit_config()
        self.assertEqual('run', self.rows(preview(self.store, environ=env))['other']['decision'])

    def test_failure_is_not_cached_and_blocks_dependents(self):
        graph = self.config['task_graph']['tasks']
        graph['shared'].update(command=[sys.executable, '-c', 'raise SystemExit(7)'], cache=True, env=[])
        self.commit_config()
        result = run(self.store)
        self.assertEqual(1, result['exit_code'])
        self.assertEqual('blocked', self.rows(result)['app']['status'])
        self.assertEqual('run', self.rows(preview(self.store))['shared']['decision'])
        self.assertEqual('passed', self.rows(result)['other']['status'])

    def test_shadow_failure_revokes_previously_matching_local_result(self):
        (self.root / 'check.py').write_text('from pathlib import Path\nraise SystemExit(int(Path(".faultline/fail").exists()))')
        self.commit()
        run(self.store)
        (self.store.path / 'fail').touch()
        result = run(self.store)
        self.assertTrue(self.rows(result)['app']['cache_match_before_run'])
        self.assertEqual('failed', self.rows(result)['app']['status'])
        self.assertEqual('run', self.rows(preview(self.store))['app']['decision'])

    def test_corrupt_incompatible_or_incomplete_results_are_misses(self):
        run(self.store)
        plan = self.rows(preview(self.store))['app']
        path = self.store.path / 'task-results' / (plan['fingerprint'] + '.json')
        original = checked(path)
        for field, value in [('repository', 'other/repository'), ('exit_code', 1), ('engine', 'old'), ('duration_seconds', None)]:
            data = dict(original, **{field: value})
            write_json(path, seal(data))
            self.assertEqual('invalid_result', self.rows(preview(self.store))['app']['reason'])
        path.write_text('{broken')
        self.assertEqual('run', self.rows(preview(self.store))['app']['decision'])

    def test_dirty_inputs_missing_inputs_and_mutating_commands_cannot_certify_success(self):
        (self.root / 'app/code.txt').write_text('dirty')
        with self.assertRaisesRegex(FaultlineError, 'clean committed'):
            run(self.store)
        self.git('checkout', '--', 'app/code.txt')
        self.config['task_graph']['tasks']['app']['command'] = [sys.executable, '-c',
            'from pathlib import Path; Path("app/code.txt").write_text("changed")']
        self.commit_config()
        result = run(self.store, tasks=['app'])
        self.assertEqual('inputs_changed_during_execution', self.rows(result)['app']['error'])
        self.assertTrue(all(checked(p)['kind'] == 'task-rejection' for p in (self.store.path / 'task-results').glob('*.json')))

    def test_graph_rejects_cycles_unknown_dependencies_and_unsafe_configuration(self):
        original = copy.deepcopy(self.config)
        cases = [({'depends_on': ['app']}, 'cycle'), ({'depends_on': ['missing']}, 'Unknown task dependency'),
                 ({'inputs': ['../outside/**']}, 'relative'), ({'cwd': '../'}, 'inside'),
                 ({'cache': 'yes'}, 'boolean'), ({'outputs': ['build/**']}, 'output-producing')]
        for changes, message in cases:
            self.config = copy.deepcopy(original)
            self.config['task_graph']['tasks']['app'].update(changes)
            self.commit_config()
            with self.assertRaisesRegex(FaultlineError, message):
                preview(self.store)

    def test_uncacheable_dependency_and_symlinks_propagate(self):
        self.config['task_graph']['tasks']['shared'].update(command=[sys.executable, '-c', 'pass'])
        self.commit_config()
        result = self.rows(preview(self.store))
        self.assertIn('uncacheable_dependency', result['app']['gaps'])
        del self.config['task_graph']['tasks']['shared']['command']
        (self.root / 'shared/link').symlink_to('../other/code.txt')
        self.commit_config()
        self.assertTrue(self.rows(preview(self.store))['app']['cacheable'])
        run(self.store)
        (self.root / 'other/code.txt').write_text('changed target in another component')
        self.commit()
        self.assertEqual('run', self.rows(preview(self.store))['app']['decision'])
        (self.root / 'shared/outside').symlink_to('/tmp/outside')
        self.commit()
        self.assertIn('uncacheable_dependency', self.rows(preview(self.store))['app']['gaps'])

    def test_symlink_directory_membership_and_cycles(self):
        (self.root / 'shared/link').symlink_to('../other', target_is_directory=True)
        self.commit()
        run(self.store)
        (self.root / 'other/new.txt').write_text('new linked directory member')
        self.commit()
        self.assertEqual('run', self.rows(preview(self.store))['app']['decision'])
        (self.root / 'shared/a').symlink_to('b')
        (self.root / 'shared/b').symlink_to('a')
        self.commit()
        self.assertIn('cyclic_symlink_input', self.rows(preview(self.store))['shared']['gaps'])

    def test_plan_never_executes_or_requires_complete_checkout(self):
        (self.root / 'app/code.txt').unlink()
        plan = preview(self.store, base='not-a-revision')
        self.assertEqual('base_task_graph_unavailable', plan['base_warning'])
        self.assertFalse((self.store.path / 'count').exists())
        self.assertEqual(0, plan['jev_requests'])

    def test_timeout_does_not_create_success(self):
        self.config['task_graph']['tasks']['app'].update(command=[sys.executable, '-c', 'import time; time.sleep(10)'], timeout_seconds=1)
        self.commit_config()
        result = run(self.store, tasks=['app'])
        self.assertEqual('timeout', self.rows(result)['app']['error'])
        self.assertEqual(124, self.rows(result)['app']['exit_code'])
