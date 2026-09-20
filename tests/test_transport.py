import io
import json
import ssl
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from faultline.core import DEFAULTS, FaultlineError, Store, read_json
from faultline.network import Budget, HTTP, NoRedirect, InputTooLarge
from faultline.jev import LEVELS
from faultline.tia.batch import BatchedJev
from faultline.tia.config import DEFAULT_EVALUATOR


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

    def test_token_limit_error_is_classified_without_exposing_provider_body(self):
        for detail, expected in (({'error_type': 'max_tokens_exceeded', 'message': 'test-secret'}, InputTooLarge),
                                 ({'error_type': 'other', 'message': 'test-secret'}, FaultlineError)):
            transport = self.transport()
            transport.opener.open.side_effect = urllib.error.HTTPError('url', 400, 'bad request', {}, io.BytesIO(json.dumps({'detail': detail}).encode()))
            with self.assertRaises(expected) as caught:
                transport.request('https://api.typesafe.ai/v1/systemone', payload={})
            self.assertNotIn('test-secret', str(caught.exception))
            self.assertEqual(1, transport.budget.used)

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
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        evaluator = BatchedJev(Store(Path(temp.name)), DEFAULT_EVALUATOR)
        evaluator.http = Mock()
        response = {'model': DEFAULTS['model'], 'answers': {'q0': {
            'type': 'choice', 'choice': 'direct', 'confidence': 1,
            'probabilities': {level: float(level == 'direct') for level in LEVELS}}}}
        evaluator.http.request.return_value = (response, {})
        profile = {'id': 'test', 'source': 'tests/a.py', 'description': ''}
        result = evaluator.evaluate({'diff': 'change', 'provenance': {'outcomes': 'private'}}, [profile])
        self.assertEqual(4, result['rows']['test']['score'])
        payload = evaluator.http.request.call_args.kwargs['payload']
        self.assertEqual(set(LEVELS), set(payload['questions']['q0']['criteria']))
        self.assertNotIn('provenance', payload['state']['change'])
        response['model'] = 'another-version'
        result = evaluator.evaluate({'diff': 'different inputs'}, [profile])
        self.assertFalse(result['complete'])
        self.assertIn('test', result['errors'])



class TLSTests(unittest.TestCase):
    def test_optional_certifi_supplements_default_roots(self):
        from faultline.network import tls_context
        context = Mock()
        certifi = Mock()
        certifi.where.return_value = '/trusted/test-ca.pem'
        with patch.dict('os.environ', {}, clear=True), patch.dict(sys.modules, {'certifi': certifi}),              patch('faultline.network.ssl.create_default_context', return_value=context):
            self.assertIs(context, tls_context())
        context.load_verify_locations.assert_called_once_with(cafile='/trusted/test-ca.pem')

    def test_explicit_trust_configuration_is_respected_and_verification_stays_enabled(self):
        from faultline.network import tls_context
        with patch.dict('os.environ', {'SSL_CERT_FILE': '/unused-test-path'}),              patch.dict(sys.modules, {'certifi': None}):
            context = tls_context()
        self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
        self.assertTrue(context.check_hostname)

    def test_certificate_failure_is_actionable_without_exposing_error_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = HTTP(Path(tmp), 'jev', {**DEFAULTS, 'request_interval': 0}, 'secret-token', Budget(2))
            http.opener = Mock()
            http.opener.open.side_effect = urllib.error.URLError(ssl.SSLCertVerificationError(1, 'private-path secret-token'))
            with self.assertRaises(FaultlineError) as caught:
                http.request('https://api.typesafe.ai/v1/systemone', payload={})
            self.assertIn('certificate verification failed', str(caught.exception))
            self.assertIn('SSL_CERT_FILE', str(caught.exception))
            self.assertNotIn('secret-token', str(caught.exception))
            self.assertNotIn('private-path', str(caught.exception))
            self.assertEqual(1, http.budget.used)
            self.assertEqual(1, http.opener.open.call_count)
