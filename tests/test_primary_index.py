"""Graph-primary indexing, portable baselines, and branch isolation."""
import copy
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from faultline.cli import main
from faultline.core import FaultlineError, Store, write_json
from faultline.tia import graph
from faultline.tia.common import checked, seal
from faultline.tia.config import load_config, repository_identity
from faultline.tia.graph_index import GraphSources, open_index
from faultline.tia.selection import select
from test_graph_pipeline import Evaluator


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
        self.producer_calls = []
        self.real_producer = graph.run
        self.producer = patch('faultline.tia.graph.run', side_effect=self.fake_producer)
        self.producer.start()
        self.addCleanup(self.producer.stop)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, text=True).stdout

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Fixture')

    def fake_producer(self, argv, cwd, timeout):
        if '--version' in argv:
            return graph.VERSION
        self.producer_calls.append(argv[1])
        database = Path(cwd) / '.codegraph/codegraph.db'
        database.parent.mkdir(exist_ok=True)
        with sqlite3.connect(database) as db:
            db.executescript("""DROP TABLE IF EXISTS files; DROP TABLE IF EXISTS nodes; DROP TABLE IF EXISTS edges;
            CREATE TABLE files(path TEXT, language TEXT, errors TEXT, node_count INTEGER);
            CREATE TABLE nodes(id TEXT,kind TEXT,name TEXT,file_path TEXT,start_line INTEGER,end_line INTEGER);
            CREATE TABLE edges(source TEXT,target TEXT,kind TEXT,metadata TEXT,provenance TEXT);""")
            for path in sorted(Path(cwd).rglob('*.php')):
                name = path.relative_to(cwd).as_posix()
                db.execute('INSERT INTO files VALUES(?,?,?,?)', (name, 'php', None, 1))
                db.execute('INSERT INTO nodes VALUES(?,?,?,?,?,?)', (name, 'function', name, name, 1, 1))
            if (Path(cwd) / 'tests/Test.php').exists():
                db.execute('INSERT INTO edges VALUES(?,?,?,?,?)', ('tests/Test.php', 'src.php', 'calls', '{}', None))
        return ''

    def test_init_builds_primary_index_and_jev_receives_tests_without_paths(self):
        with patch('builtins.print') as output, patch('faultline.tia.batch.api_key', side_effect=AssertionError('Init must not call Jev')):
            self.assertEqual(0, main(['--root', str(self.root), 'init', '--baseline', 'main']))
        initialized = json.loads(output.call_args.args[0])
        baseline = initialized['graph']
        self.assertEqual(3, baseline['target_count'])
        self.assertFalse((self.root / 'faultline/catalog').exists())
        with graph.connect(Path(baseline['path']) / 'graph.sqlite') as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM faultline_targets WHERE source='features/access.feature'").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT count(*) FROM nodes WHERE file_path='features/access.feature'").fetchone()[0])
        (self.root / 'src.php').write_text('<?php function access() { return false; }')
        self.commit()
        head = graph.build(self.store, self.config)
        evaluator = Evaluator()
        with patch('faultline.tia.evidence.GitSources.__init__', side_effect=AssertionError('Use saved graph index')),             patch('faultline.tia.catalog.load_record', side_effect=AssertionError('No catalog reads')),             patch('faultline.tia.runners.invoke', side_effect=AssertionError('No native runners')):
            result = select(self.store, self.base, evaluator=evaluator, build_graphs=False)
        self.assertEqual('graph', result['index']['basis'])
        self.assertEqual(3, result['semantic']['fully_scored'])
        self.assertEqual(3, len(evaluator.profiles))
        feature = next(p for p in evaluator.profiles if p['source'].endswith('.feature'))
        self.assertIn('Scenario: login', feature['source_text'])
        self.assertFalse(feature['graph_evidence']['structural_match'])
        self.assertEqual(baseline['integrity'], head['reused_from'])
        self.assertEqual(['init', 'sync'], self.producer_calls)

    def test_multiple_branches_derive_immutable_baseline_and_remove_stale_targets(self):
        baseline = graph.build(self.store, self.config, self.base)
        checksum = graph.sha(Path(baseline['path']) / 'graph.sqlite')
        self.git('checkout', '-qb', 'branch-a')
        self.git('mv', 'features/access.feature', 'features/renamed.feature')
        (self.root / 'tests/New.php').write_text('<?php access();')
        self.commit()
        branch_a = graph.build(self.store, self.config)
        sources_a = GraphSources(self.root, self.config, branch_a['path'], branch_a['revision'])
        self.assertIn('features/renamed.feature', sources_a.files)
        self.assertNotIn('features/access.feature', sources_a.files)
        self.git('checkout', '-qb', 'branch-b', self.base)
        (self.root / 'web/access.spec.ts').unlink()
        self.commit()
        branch_b = graph.build(self.store, self.config)
        sources_b = GraphSources(self.root, self.config, branch_b['path'], branch_b['revision'])
        self.assertNotIn('web/access.spec.ts', sources_b.files)
        self.assertNotIn('tests/New.php', sources_b.files)
        self.assertEqual(baseline['integrity'], branch_a['reused_from'])
        self.assertEqual(baseline['integrity'], branch_b['reused_from'])
        self.assertEqual(checksum, graph.sha(Path(baseline['path']) / 'graph.sqlite'))
        self.assertNotEqual(branch_a['path'], branch_b['path'])
        # Reading a graph for another branch uses that graph's exact blobs, not checkout files.
        self.assertIn('access()', sources_a.read('tests/New.php').decode())

    def test_portable_baseline_import_and_cache_hit_in_renamed_checkout(self):
        baseline = graph.build(self.store, self.config)
        exported = graph.transfer(self.store, self.config, baseline['path'], output=Path(self.tmp.name) / 'shared')
        other = Path(self.tmp.name) / 'different-name'
        subprocess.run(['git', 'clone', '-q', str(self.root), str(other)], check=True)
        store = Store(other)
        config = load_config(other)
        with patch('faultline.tia.graph.run', side_effect=AssertionError('Import/cache reuse must be offline')):
            imported = graph.transfer(store, config, exported['path'])
            reused = graph.build(store, config, self.base)
        self.assertTrue(reused['cache_hit'])
        self.assertEqual(baseline['integrity'], reused['integrity'])
        self.assertEqual(imported['path'], reused['path'])
        source, inventory, provenance = open_index(store, config, self.base)
        self.assertEqual('graph', provenance['basis'])
        self.assertEqual(3, len(inventory['suites'][0]['units']))
        self.assertIn('Scenario', source.read('features/access.feature').decode())
        self.assertEqual(repository_identity(self.root), repository_identity(other))

    def test_wrong_repository_corruption_and_mismatched_index_are_rejected(self):
        baseline = graph.build(self.store, self.config)
        other = copy.deepcopy(self.config)
        other['repository'] = 'unrelated'
        with self.assertRaisesRegex(FaultlineError, 'repository mismatch'):
            graph.transfer(self.store, other, baseline['path'])
        changed = copy.deepcopy(self.config)
        changed['suites'][0]['sources'] = ['features/**/*.feature']
        self.assertNotEqual(graph.artifact_path(self.store, changed, self.base), Path(baseline['path']))
        with self.assertRaisesRegex(FaultlineError, 'configuration mismatch'):
            GraphSources(self.root, changed, baseline['path'], self.base)
        database = Path(baseline['path']) / 'graph.sqlite'
        with sqlite3.connect(database) as db:
            db.execute("UPDATE faultline_sources SET oid='0000000000000000000000000000000000000000' WHERE path='src.php'")
        with self.assertRaisesRegex(FaultlineError, 'hash mismatch'):
            graph.transfer(self.store, self.config, baseline['path'])
        # A resealed but unrelated source index is also rejected against Git.
        manifest = checked(Path(baseline['path']) / 'manifest.json')
        manifest['database_sha256'] = graph.sha(database)
        write_json(Path(baseline['path']) / 'manifest.json', seal(manifest))
        with self.assertRaisesRegex(FaultlineError, 'source identities'):
            graph.transfer(self.store, self.config, baseline['path'])

    def test_concurrent_publication_cannot_overwrite_baseline(self):
        baseline = graph.build(self.store, self.config)
        output = Path(self.tmp.name) / 'concurrent'
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(graph.transfer, self.store, self.config, baseline['path'], output=output) for _ in range(2)]
            values = [f.result() for f in futures]
        self.assertEqual(values[0]['integrity'], values[1]['integrity'])
        self.assertEqual(baseline['database_sha256'], graph.sha(output / 'graph.sqlite'))

    def test_repository_identity_ignores_remote_transport_and_credentials(self):
        self.git('remote', 'add', 'origin', 'git@example.invalid:team/project.git')
        identity = repository_identity(self.root)
        self.git('remote', 'set-url', 'origin', 'https://user:secret@example.invalid/team/project.git')
        self.assertEqual(identity, repository_identity(self.root))
        self.assertNotIn('secret', identity)

    @unittest.skipUnless(os.environ.get('FAULTLINE_CODEGRAPH'), 'Set FAULTLINE_CODEGRAPH for producer conformance')
    def test_real_producer_reuses_index_with_gherkin_and_deleted_sources(self):
        self.config['graph']['command'] = [os.environ['FAULTLINE_CODEGRAPH']]
        with patch('faultline.tia.graph.run', side_effect=self.real_producer):
            baseline = graph.build(self.store, self.config)
            self.git('mv', 'features/access.feature', 'features/renamed.feature')
            (self.root / 'tests/New.php').write_text('<?php access();')
            self.commit()
            branch = graph.build(self.store, self.config)
        self.assertEqual(baseline['integrity'], branch['reused_from'])
        indexed = GraphSources(self.root, self.config, branch['path'], branch['revision'])
        targets = {u['source'] for s in indexed.inventory['suites'] for u in s['units']}
        self.assertIn('features/renamed.feature', targets)
        self.assertNotIn('features/access.feature', targets)
        self.assertIn('tests/New.php', targets)
        with graph.connect(Path(branch['path']) / 'graph.sqlite') as db:
            self.assertGreater(db.execute("SELECT count(*) FROM nodes WHERE file_path='tests/New.php'").fetchone()[0], 0)

    def test_changed_target_configuration_reuses_structure_and_reclassifies(self):
        baseline = graph.build(self.store, self.config)
        config = copy.deepcopy(self.config)
        config['suites'][0]['sources'] = ['features/**/*.feature']
        derived = graph.build(self.store, config)
        self.assertEqual(baseline['integrity'], derived['reused_from'])
        self.assertNotEqual(baseline['path'], derived['path'])
        source = GraphSources(self.root, config, derived['path'], self.base)
        self.assertEqual(['features/access.feature'], [u['source'] for u in source.inventory['suites'][0]['units']])
        self.assertEqual(['init', 'sync'], self.producer_calls)
