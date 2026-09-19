import tempfile
import unittest
from pathlib import Path

from faultline.core import FaultlineError
from faultline.tia.mapping import phpunit_xml, covered_units


class NativeMappingTests(unittest.TestCase):
    def fixture(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        root.joinpath('index.xml').write_text('''<phpunit xmlns="https://schema.phpunit.de/coverage/1.0"><build coverage="9.2.32"/><project source="/container/src"><tests><test name="CounterTest::testIncrement"/><test name="CounterTest::testDecrement"/></tests><directory name="/"><file name="Counter.php" href="Counter.php.xml"/></directory></project></phpunit>''')
        root.joinpath('Counter.php.xml').write_text('''<phpunit xmlns="https://schema.phpunit.de/coverage/1.0"><file name="Counter.php" path="/"><coverage><line nr="3"><covered by="CounterTest::testIncrement"/></line><line nr="4"><covered by="CounterTest::testDecrement"/></line></coverage></file></phpunit>''')
        return root

    def test_native_per_test_attribution_and_positive_only_mapping(self):
        mapping = phpunit_xml(self.fixture(), source_prefix='app/src', revision='abc', suite='unit')
        self.assertEqual([3], mapping['edges'][1]['lines'])
        self.assertEqual('app/src/Counter.php', mapping['edges'][0]['source'])
        units = [{'id': 'counter', 'members': ['CounterTest::testIncrement', 'CounterTest::testDecrement']}]
        self.assertEqual(['counter'], covered_units(mapping, units, ['app/src/Counter.php'])['required'])
        self.assertEqual([], covered_units(mapping, units, ['app/src/New.php'])['required'])
        self.assertEqual(2, len(covered_units(mapping, [], ['app/src/Counter.php'])['unmatched']))

    def test_summary_xml_and_external_references_are_rejected(self):
        root = self.fixture()
        index = root / 'index.xml'
        index.write_text(index.read_text().replace('Counter.php.xml', '../outside.xml'))
        with self.assertRaises(FaultlineError):
            phpunit_xml(root, source_prefix='src', revision='abc', suite='unit')
        index.write_text('<testsuites/>')
        with self.assertRaises(FaultlineError):
            phpunit_xml(root, source_prefix='src', revision='abc', suite='unit')

    def test_unattributed_or_malformed_lines_are_not_silently_used(self):
        root = self.fixture()
        path = root / 'Counter.php.xml'
        path.write_text(path.read_text().replace('CounterTest::testIncrement', 'UnknownTest'))
        with self.assertRaises(FaultlineError):
            phpunit_xml(root, source_prefix='src', revision='abc', suite='unit')
