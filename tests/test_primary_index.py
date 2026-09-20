"""Exact Git source enumeration across revisions, branches, and checkouts."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from faultline.cli import main
from faultline.core import FaultlineError, Store, write_json
from faultline.tia.config import load_config, repository_identity
from faultline.tia.source_index import open_index
from faultline.tia.selection import select
from test_source_pipeline import Evaluator


class PrimaryIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'checkout'
        self.root.mkdir()
        self.git('init', '-q', '-b', 'main')
        for name, text in {'src.php': '<?php function access() { return true; }',
                           'tests/Test.php': '<?php access();',
                           'features/access.feature': 'Feature: access\n Scenario: login\n Then access is granted',
                           'web/access.spec.ts': 'test("access", () => expect(access()).toBe(true));',
                           '.gitignore': '.faultline/\n'}.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.raw = {'schema_version': 2, 'repository': 'shared-fixture', 'suites': [
            {'id': 'tests', 'sources': ['tests/**', 'features/**/*.feature', 'web/**/*.spec.ts']}]}
        write_json(self.root / 'faultline.json', self.raw)
        self.commit()
        self.base = self.git('rev-parse', 'HEAD').strip()
        self.store = Store(self.root)
        self.config = load_config(self.root)
    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, text=True).stdout

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Fixture')

    def test_repository_identity_ignores_remote_transport_and_credentials(self):
        self.git('remote', 'add', 'origin', 'git@example.invalid:team/project.git')
        identity = repository_identity(self.root)
        self.git('remote', 'set-url', 'origin', 'https://user:secret@example.invalid/team/project.git')
        self.assertEqual(identity, repository_identity(self.root))
        self.assertNotIn('secret', identity)


    def test_init_and_all_languages_need_only_git(self):
        with patch('builtins.print') as output, patch('faultline.tia.batch.api_key', side_effect=AssertionError('No key')), patch('faultline.tia.runners.invoke', side_effect=AssertionError('No runner')):
            self.assertEqual(0, main(['--root', str(self.root), 'init', '--revision', 'main']))
            self.assertEqual(3, json.loads(output.call_args.args[0])['index']['target_count'])
            result = select(self.store, self.base, evaluator=Evaluator())
        self.assertEqual('git', result['index']['basis'])
        self.assertEqual(3, result['semantic']['fully_scored'])
        self.assertFalse((self.root / 'faultline/catalog').exists())
        self.assertFalse((self.store.path / 'graphs').exists())

    def test_snapshots_ignore_worktree_changes_and_preserve_removed_sources(self):
        source, inventory, _ = open_index(self.store, self.config, self.base)
        original = source.read('tests/Test.php')
        (self.root / 'tests/Test.php').unlink()
        (self.root / 'web/access.spec.ts').write_text('COMMITTED NEW SOURCE')
        self.commit()
        head = self.git('rev-parse', 'HEAD').strip()
        (self.root / 'web/access.spec.ts').write_text('DIRTY SOURCE MUST NOT BE READ')
        newer, targets, _ = open_index(self.store, self.config, head)
        self.assertEqual(original, source.read('tests/Test.php'))
        self.assertEqual(3, len(inventory['suites'][0]['units']))
        self.assertEqual(2, len(targets['suites'][0]['units']))
        self.assertEqual(b'COMMITTED NEW SOURCE', newer.read('web/access.spec.ts'))
        with self.assertRaises(FaultlineError):
            newer.read('tests/Test.php')
        self.assertEqual(head, self.git('rev-parse', 'HEAD').strip())

    def test_second_checkout_reuses_git_without_an_index_or_agent(self):
        other = self.root.parent / 'other'
        subprocess.run(['git', 'clone', '-q', str(self.root), str(other)], check=True)
        a, inventory, provenance = open_index(self.store, self.config, self.base)
        b, copied, reused = open_index(Store(other), load_config(other), self.base)
        self.assertEqual(inventory['suites'], copied['suites'])
        self.assertEqual(provenance, reused)
        self.assertEqual(a.read('features/access.feature'), b.read('features/access.feature'))
        self.assertFalse((other / '.faultline').exists())

    def test_configuration_reclassifies_targets_without_reindexing(self):
        self.raw['suites'][0]['sources'] = ['features/**/*.feature']
        write_json(self.root / 'faultline.json', self.raw)
        source, inventory, _ = open_index(self.store, load_config(self.root), self.base)
        self.assertEqual(['features/access.feature'], [u['source'] for u in inventory['suites'][0]['units']])

    def test_prepare_is_offline_and_request_cap_does_not_edit_configuration(self):
        before = (self.root / 'faultline.json').read_bytes()
        with patch('faultline.tia.batch.api_key', side_effect=AssertionError('No key')), patch('faultline.network.HTTP.request', side_effect=AssertionError('No API')):
            result = select(self.store, self.base, prepare=True, max_requests=2)
        self.assertTrue(result['dry_run'])
        self.assertEqual(3, result['candidate_units'])
        self.assertEqual(before, (self.root / 'faultline.json').read_bytes())
