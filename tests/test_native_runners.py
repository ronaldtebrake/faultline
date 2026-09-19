import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from faultline.core import FaultlineError
from faultline.tia.runners import phpunit_inventory, behat_inventory

FIXTURES = Path(__file__).parent / 'fixtures/native'


class NativeInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'tests').mkdir()
        (self.root / 'features').mkdir()
        (self.root / 'tests/NumbersTest.php').write_text('<?php class NumbersTest {}')
        (self.root / 'features/numbers.feature').write_text('Feature: numbers')
        self.suite = {'id': 'suite', 'cwd': '.', 'command': ['native-runner'], 'timeout_seconds': 5,
                      'sources': ['tests/*.php'], 'description_inputs': [], 'autoload': 'autoload.php', 'path_map': {}}
        self.variant = {'id': 'matrix', 'args': []}

    def phpunit_invoke(self, argv, cwd, timeout, **kwargs):
        if '--list-tests-xml' in argv:
            shutil.copyfile(FIXTURES / 'phpunit-9.6.xml', argv[argv.index('--list-tests-xml') + 1])
            return subprocess.CompletedProcess(argv, 0, '')
        return subprocess.CompletedProcess(argv, 0, json.dumps({'NumbersTest': str(self.root / 'tests/NumbersTest.php')}))

    def test_native_parameterized_inventory_uses_composer_map_and_keeps_all_datasets(self):
        with patch('faultline.tia.runners.invoke', side_effect=self.phpunit_invoke):
            units = phpunit_inventory(self.root, self.suite, self.variant, self.root / 'inventory.xml')
        self.assertEqual(1, len(units))
        self.assertEqual('suite:matrix:tests/NumbersTest.php', units[0]['id'])
        self.assertEqual(['NumbersTest::testPositive with data set "first"',
                          'NumbersTest::testPositive with data set "second"'], units[0]['members'])
        self.assertEqual({'classes': ['NumbersTest']}, units[0]['locator'])

    def test_class_mapping_failure_is_not_replaced_by_guessed_sources(self):
        def invoke(argv, cwd, timeout, **kwargs):
            if '--list-tests-xml' in argv:
                return self.phpunit_invoke(argv, cwd, timeout, **kwargs)
            return subprocess.CompletedProcess(argv, 0, '{}')
        with patch('faultline.tia.runners.invoke', side_effect=invoke), self.assertRaises(FaultlineError):
            phpunit_inventory(self.root, self.suite, self.variant, self.root / 'inventory.xml')

    def test_behat_outline_rows_and_duplicate_names_stay_in_one_feature_unit(self):
        def invoke(argv, cwd, timeout):
            output = Path(next(a.removeprefix('--out=') for a in argv if a.startswith('--out=')))
            shutil.copyfile(FIXTURES / 'behat-3.29.xml', output / 'default.xml')
        with patch('faultline.tia.runners.invoke', side_effect=invoke):
            units = behat_inventory(self.root, self.suite, self.variant, self.root / 'inventory')
        self.assertEqual(1, len(units))
        self.assertEqual('features/numbers.feature', units[0]['source'])
        self.assertEqual(['0:positive number #1', '1:positive number #2', '2:positive number'], units[0]['members'])

    def test_behat_missing_file_identity_requires_full_execution(self):
        def invoke(argv, cwd, timeout):
            output = Path(next(a.removeprefix('--out=') for a in argv if a.startswith('--out=')))
            output.joinpath('default.xml').write_text('<testsuites><testsuite name="duplicate"><testcase name="same"/></testsuite></testsuites>')
        with patch('faultline.tia.runners.invoke', side_effect=invoke), self.assertRaises(FaultlineError):
            behat_inventory(self.root, self.suite, self.variant, self.root / 'inventory')
