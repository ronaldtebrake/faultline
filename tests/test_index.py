import json
import tempfile
import unittest
from pathlib import Path

from faultline.core import FaultlineError, Store
from faultline.index import build_index, index_status, load_profiles


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = Store(self.root)
        (self.root / 'test.php').write_text('test first; test second;')
        (self.root / 'helper.php').write_text('fixture v1')
        self.draft = self.root / 'draft.jsonl'

    def write_draft(self, profiles):
        self.draft.write_text('\n'.join(json.dumps(p) for p in profiles))

    def profiles(self):
        return [{'id': 'test::first', 'source': 'test.php', 'description': 'First behavior', 'context_sources': ['helper.php']},
                {'id': 'test::second', 'source': 'test.php', 'description': 'Second behavior'}]

    def test_incremental_preservation_addition_and_removal(self):
        self.write_draft(self.profiles())
        self.assertEqual(2, build_index(self.store, self.draft, 'test')['added'])
        updated = self.profiles()
        updated[0]['description'] = 'Improvised replacement'
        self.write_draft(updated)
        self.assertEqual(2, build_index(self.store, self.draft, 'test')['unchanged'])
        self.assertEqual('First behavior', load_profiles(self.store.path / 'index.jsonl')[0]['description'])
        build_index(self.store, self.draft, 'test', rewrite=True)
        self.assertEqual('Improvised replacement', load_profiles(self.store.path / 'index.jsonl')[0]['description'])
        self.write_draft(updated[:1])
        self.assertEqual(1, build_index(self.store, self.draft, 'test')['removed'])

    def test_helper_change_invalidates_only_dependent_profiles(self):
        self.write_draft(self.profiles())
        build_index(self.store, self.draft, 'test')
        (self.root / 'helper.php').write_text('fixture v2')
        status = index_status(self.store)
        self.assertEqual(['test::first'], status['changed'])
        self.assertEqual(['test::second'], status['unchanged'])
        self.assertEqual(1, build_index(self.store, self.draft, 'test')['changed'])

    def test_stale_hash_rejected_without_modifying_index(self):
        self.write_draft(self.profiles())
        build_index(self.store, self.draft, 'test')
        previous = (self.store.path / 'index.jsonl').read_text()
        self.draft.write_text(previous)
        (self.root / 'test.php').write_text('changed')
        with self.assertRaises(FaultlineError):
            build_index(self.store, self.draft, 'test')
        self.assertEqual(previous, (self.store.path / 'index.jsonl').read_text())

    def test_duplicate_ids_and_external_paths_rejected(self):
        self.write_draft([self.profiles()[0]] * 2)
        with self.assertRaises(FaultlineError):
            build_index(self.store, self.draft, 'test')
        self.write_draft([{'id': 'a', 'source': '../outside.php', 'description': 'Unsafe source'}])
        with self.assertRaises(FaultlineError):
            build_index(self.store, self.draft, 'test')
