import tempfile
import unittest
from pathlib import Path

from faultline.core import DEFAULTS, FaultlineError, Store, write_json
from faultline.index import build_index

FEATURE = '''Feature: Access
  Background:
    Given a private document
  Scenario: Anonymous visitor
    When a visitor opens it
    Then access is denied
  Scenario Outline: Membership
    Given a <role> user
    Then access is <result>
    Examples:
      | role | result |
      | member | allowed |
      | guest | denied |
'''


class IndexTests(unittest.TestCase):
    def test_outline_background_and_incremental_updates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'access.feature').write_text(FEATURE)
            store = Store(root)
            first = build_index(store, DEFAULTS)
            self.assertEqual(3, len(first['tests']))
            self.assertTrue(all('private document' in t['description'] for t in first['tests']))
            self.assertEqual(3, build_index(store, DEFAULTS)['statistics']['unchanged'])
            (root / 'access.feature').write_text('\n' + FEATURE)
            moved = build_index(store, DEFAULTS)
            self.assertEqual([p['id'] for p in first['tests']], [p['id'] for p in moved['tests']])
            (root / 'access.feature').unlink()
            self.assertEqual(3, build_index(store, DEFAULTS)['statistics']['removed'])

    def test_import_and_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            test = {'id': 'a', 'source': 'tests/a', 'description': 'protects access'}
            write_json(root / 'profiles.json', [test, test])
            with self.assertRaises(FaultlineError):
                build_index(Store(root), {**DEFAULTS, 'profiles_file': 'profiles.json'})

    def test_disabled_tag(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'test.feature').write_text('@disabled\n' + FEATURE)
            self.assertEqual([], build_index(Store(root), DEFAULTS)['tests'])
