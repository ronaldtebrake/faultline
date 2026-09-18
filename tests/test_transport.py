import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from faultline.core import DEFAULTS, FaultlineError, read_json
from faultline.network import Budget, HTTP, NoRedirect
from faultline.jev import JevEvaluator, LEVELS
from helpers import setup_case


class Response:
    def __init__(self, data):
        self.raw = json.dumps(data).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, size):
        return self.raw[:size]


class TransportTests(unittest.TestCase):
    def transport(self, **overrides):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        transport = HTTP(Path(temp.name), 'jev', {**DEFAULTS, 'request_interval': 0, **overrides}, 'test-secret', Budget(3))
        transport.opener = Mock()
        return transport

    def test_retry_after_persists_without_early_retry(self):
        transport = self.transport(max_wait=0)
        transport.opener.open.side_effect = urllib.error.HTTPError('https://api.typesafe.ai/v1/systemone', 429, 'limited', {'Retry-After': '120'}, io.BytesIO())
        with self.assertRaises(FaultlineError):
            transport.request('https://api.typesafe.ai/v1/systemone', payload={})
        self.assertEqual(1, transport.budget.used)
        self.assertIn('until', read_json(transport.cache / 'cooldown.json'))
        with self.assertRaises(FaultlineError):
            transport.request('https://api.typesafe.ai/v1/systemone', payload={})
        self.assertEqual(1, transport.budget.used)
        self.assertNotIn('test-secret', (transport.cache / 'cooldown.json').read_text())

    def test_transient_retry_counts_against_ceiling(self):
        transport = self.transport()
        error = urllib.error.HTTPError('https://api.typesafe.ai/v1/systemone', 529, 'overloaded', {}, io.BytesIO())
        transport.opener.open.side_effect = [error, Response({'ok': True})]
        with patch('faultline.network.time.sleep'):
            result, _ = transport.request('https://api.typesafe.ai/v1/systemone', payload={})
        self.assertTrue(result['ok'])
        self.assertEqual(2, transport.budget.used)

    def test_auth_and_ambiguous_errors_do_not_retry(self):
        for error in [urllib.error.HTTPError('url', 401, 'bad key', {}, io.BytesIO(b'test-secret')),
                      urllib.error.URLError('test-secret')]:
            transport = self.transport()
            transport.opener.open.side_effect = error
            with self.assertRaises(FaultlineError) as caught:
                transport.request('https://api.typesafe.ai/v1/systemone', payload={})
            self.assertEqual(1, transport.budget.used)
            self.assertNotIn('test-secret', str(caught.exception))

    def test_budget_and_foreign_origin_rejected(self):
        transport = self.transport()
        transport.budget.limit = 0
        with self.assertRaises(FaultlineError):
            transport.request('https://api.typesafe.ai/v1/systemone', payload={})
        with self.assertRaises(FaultlineError):
            transport.request('https://other.example/', payload={})
        transport.opener.open.assert_not_called()
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))

    def test_jev_request_contract_and_model_mismatch(self):
        root, store, path = setup_case(self)
        evaluator = JevEvaluator(store, DEFAULTS, Budget(10))
        evaluator.http = Mock()
        response = {'model': DEFAULTS['model'], 'answers': {'relevance': {
            'type': 'choice', 'choice': 'direct', 'confidence': 1,
            'probabilities': {level: float(level == 'direct') for level in LEVELS}}}}
        evaluator.http.request.return_value = (response, {})
        from faultline.index import load_profiles
        profile = load_profiles(store.path / 'index.jsonl')[0]
        result = evaluator.evaluate(read_json(path), profile)
        self.assertEqual(4, result['score'])
        payload = evaluator.http.request.call_args.kwargs['payload']
        self.assertEqual(set(LEVELS), set(payload['questions']['relevance']['criteria']))
        self.assertNotIn('provenance', payload['state']['change'])
        response['model'] = 'another-version'
        with self.assertRaises(FaultlineError):
            evaluator.evaluate(read_json(path), profile)
