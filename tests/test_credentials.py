import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from faultline.core import DEFAULTS, FaultlineError, Store
from faultline.credentials import api_key
from faultline.jev import LEVELS
from faultline.tia.batch import BatchedJev
from faultline.tia.config import DEFAULT_EVALUATOR


class CredentialTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name))
        self.store.initialize()
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_precedence_and_empty_fallback(self):
        (self.store.root / '.env').write_text('TYPESAFE_API_KEY=root-key\n')
        (self.store.path / '.env').write_text('TYPESAFE_API_KEY=local-key\n')
        self.assertEqual('local-key', api_key(self.store))
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'env-key'}):
            self.assertEqual('env-key', api_key(self.store))
        (self.store.path / '.env').write_text('TYPESAFE_API_KEY=""\n')
        self.assertEqual('root-key', api_key(self.store))

    def test_literal_values_comments_and_unrelated_entries(self):
        for value, expected in [('plain-key # comment', 'plain-key'),
                                ('"key#literal" # comment', 'key#literal'),
                                ("'${OTHER}$(command)'", '${OTHER}$(command)')]:
            (self.store.path / '.env').write_text('OTHER="unclosed\nexport TYPESAFE_API_KEY = ' + value + '\n')
            self.assertEqual(expected, api_key(self.store))
        self.assertNotIn('TYPESAFE_API_KEY', os.environ)

    def test_errors_never_expose_file_contents(self):
        with self.assertRaisesRegex(FaultlineError, r'\.faultline/\.env'):
            api_key(self.store)
        for value in ['"secret-unclosed', '"secret" trailing', 'secret with spaces']:
            (self.store.path / '.env').write_text('TYPESAFE_API_KEY=' + value)
            with self.assertRaises(FaultlineError) as caught:
                api_key(self.store)
            self.assertNotIn('secret', str(caught.exception))

    def test_live_evaluator_loads_from_analyzed_repository_lazily(self):
        evaluator = BatchedJev(self.store, DEFAULT_EVALUATOR)
        (self.store.path / '.env').write_text('TYPESAFE_API_KEY=local-secret\n')
        response = {'model': DEFAULTS['model'], 'answers': {'q0': {
            'type': 'choice', 'choice': 'direct',
            'probabilities': {level: float(level == 'direct') for level in LEVELS}}}}
        with patch('faultline.tia.batch.HTTP') as transport:
            transport.return_value.request.return_value = (response, {})
            result = evaluator.evaluate({'diff': 'change'}, [{'id': 'test', 'source': 'test.py', 'description': 'behavior'}])
            self.assertEqual('local-secret', transport.call_args.args[3])
            self.assertEqual(4, result['rows']['test']['score'])
            self.assertNotIn('local-secret', str(transport.return_value.request.call_args))
            self.assertNotIn('local-secret', str(result))
