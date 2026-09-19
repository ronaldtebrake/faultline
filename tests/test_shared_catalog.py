import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from faultline.core import FaultlineError, write_json
from faultline.tia import catalog
from faultline.tia.config import load_config
from faultline.tia.runners import discover_suite, source_path, xml


class SharedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'one'
        self.root.mkdir()
        self.git('init')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '--allow-empty', '-m', 'Fixture')
        (self.root / 'test.txt').write_text('protects behavior\n')
        (self.root / 'helper.txt').write_text('setup\n')
        (self.root / 'production.txt').write_text('implementation\n')
        (self.root / 'discover.py').write_text('import pathlib\nprint(pathlib.Path("inventory.json").read_text())\n')
        self.native = {'schema_version': 2, 'complete': True, 'units': [
            {'source': 'test.txt', 'members': ['same title #1', 'same title #2'], 'locator': {'file': 'test.txt'}, 'title': 'Protect behavior'}]}
        write_json(self.root / 'inventory.json', self.native)
        self.raw = {'schema_version': 2, 'repository': 'fixture', 'suites': [{
            'id': 'unit', 'runner': 'generic', 'command': [sys.executable, 'test.txt'],
            'discovery_command': [sys.executable, 'discover.py'], 'description_inputs': ['helper.txt'],
            'variants': [{'id': 'a'}, {'id': 'b'}]}]}
        write_json(self.root / 'faultline.json', self.raw)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, text=True).stdout

    def inventory(self, root=None):
        root = root or self.root
        return catalog.discover(root, load_config(root))

    def review(self, inv):
        rows = [{'id': u['id'], 'description_hash': u['description_hash'], 'description': 'Protects behavior.',
                 'context_sources': ['helper.txt']} for s in inv['suites'] for u in s['units']]
        path = self.root / 'review.json'
        write_json(path, rows)
        return catalog.import_records(self.root, inv, path, 'maintainer')

    def test_reviewed_descriptions_reused_in_second_checkout_without_inference(self):
        inv = self.inventory()
        self.assertTrue(inv['complete'])
        self.assertEqual(2, len({u['id'] for s in inv['suites'] for u in s['units']}))
        self.assertEqual(2, catalog.sync(self.root, inv)['needs_review'])
        self.assertFalse(catalog.check(self.root, inv)['complete'])
        self.review(inv)
        self.assertTrue(catalog.check(self.root, inv)['complete'])
        other = self.root.parent / 'two'
        shutil.copytree(self.root, other)
        with patch('urllib.request.urlopen', side_effect=AssertionError('No AI/network during catalog reuse')):
            other_inv = self.inventory(other)
            self.assertTrue(catalog.check(other, other_inv)['complete'])
            self.assertEqual(2, catalog.sync(other, other_inv)['preserved'])
        self.assertEqual(inv['suites'], other_inv['suites'])

    def test_only_test_and_description_context_changes_invalidate_descriptions(self):
        self.review(self.inventory())
        (self.root / 'production.txt').write_text('new implementation\n')
        self.assertTrue(catalog.check(self.root, self.inventory())['complete'])
        (self.root / 'helper.txt').write_text('changed setup\n')
        self.assertFalse(catalog.check(self.root, self.inventory())['complete'])
        self.review(self.inventory())
        (self.root / 'test.txt').write_text('changed test\n')
        self.assertFalse(catalog.check(self.root, self.inventory())['complete'])

    def test_incomplete_discovery_does_not_erase_catalog(self):
        catalog.sync(self.root, self.inventory())
        before = sorted(p.read_bytes() for p in (self.root / 'faultline/catalog').glob('*.json'))
        self.native['complete'] = False
        write_json(self.root / 'inventory.json', self.native)
        inv = self.inventory()
        self.assertFalse(inv['complete'])
        with self.assertRaises(FaultlineError):
            catalog.sync(self.root, inv)
        self.assertEqual(before, sorted(p.read_bytes() for p in (self.root / 'faultline/catalog').glob('*.json')))

    def test_complete_inventory_handles_additions_removals_and_legacy_migration(self):
        catalog.sync(self.root, self.inventory())
        (self.root / 'new.txt').write_text('new test')
        self.native['units'][0]['source'] = 'new.txt'
        write_json(self.root / 'inventory.json', self.native)
        legacy = self.root / 'legacy.jsonl'
        legacy.write_text(json.dumps({'id': 'old', 'source': 'new.txt', 'description': 'Imported description'}) + '\n')
        inv = self.inventory()
        result = catalog.sync(self.root, inv, legacy=legacy)
        self.assertEqual({'preserved': 0, 'needs_review': 2, 'removed': 2}, result)
        record = catalog.load_record(self.root, inv['suites'][0]['units'][0])
        self.assertEqual('Imported description', record['description'])
        self.assertFalse(record['reviewed'])

    def test_duplicate_identities_missing_sources_and_runner_errors_are_visible(self):
        for mutate in ('duplicate', 'missing', 'empty', 'failed'):
            with self.subTest(mutate=mutate):
                native = copy.deepcopy(self.native)
                raw = copy.deepcopy(self.raw)
                if mutate == 'duplicate':
                    native['units'][0]['members'] = ['same', 'same']
                elif mutate == 'missing':
                    native['units'][0]['source'] = 'absent'
                elif mutate == 'empty':
                    native['units'] = []
                else:
                    raw['suites'][0]['discovery_command'] = [sys.executable, '-c', 'raise SystemExit(3)']
                write_json(self.root / 'inventory.json', native)
                write_json(self.root / 'faultline.json', raw)
                inv = self.inventory()
                self.assertFalse(inv['complete'])
                self.assertTrue(inv['suites'][0]['errors'])

    def test_unsupported_native_versions_never_claim_complete_inventory(self):
        self.raw['suites'][0].update(runner='phpunit', command=[sys.executable, '-c', 'print("PHPUnit 99.0.0")'])
        del self.raw['suites'][0]['discovery_command']
        write_json(self.root / 'faultline.json', self.raw)
        self.assertFalse(self.inventory()['complete'])

    def test_malformed_config_and_prerequisite_cycles_are_actionable(self):
        for field, value in (('id', None), ('cwd', None), ('variants', [{'id': []}]), ('sources', ['../*.php'])):
            raw = copy.deepcopy(self.raw)
            raw['suites'][0][field] = value
            write_json(self.root / 'faultline.json', raw)
            with self.subTest(field=field), self.assertRaises(FaultlineError):
                load_config(self.root)
        self.raw['suites'][0]['prerequisites'] = ['unit']
        write_json(self.root / 'faultline.json', self.raw)
        with self.assertRaises(FaultlineError):
            load_config(self.root)

    def test_path_mapping_respects_directory_boundaries_and_xml_is_data_only(self):
        suite = {'cwd': '.', 'path_map': {'/app': '.'}}
        self.assertEqual('test.txt', source_path(self.root, suite, '/app/test.txt'))
        with self.assertRaises(FaultlineError):
            source_path(self.root, suite, '/application/test.txt')
        bad = self.root / 'unsafe.xml'
        bad.write_text('<!DOCTYPE root [<!ENTITY x "expansion">]><root>&x;</root>')
        with self.assertRaises(FaultlineError):
            xml(bad)
        bad.write_bytes(bad.read_text().encode('utf-16'))
        with self.assertRaises(FaultlineError):
            xml(bad)
