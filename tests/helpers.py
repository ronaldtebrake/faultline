import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from faultline.core import DEFAULTS, FaultlineError, Store, write_json
from faultline.index import build_index
from faultline.jev import LEVELS


class FakeEvaluator:
    def __init__(self, stop_after=None):
        self.calls = []
        self.stop_after = stop_after

    def evaluate(self, change, profile):
        if self.stop_after is not None and len(self.calls) >= self.stop_after:
            raise FaultlineError('Simulated interruption')
        self.calls.append((change, profile))
        value = 4 if profile['id'] == 'case-b' else 1
        probabilities = {level: float(i == value) for i, level in enumerate(LEVELS)}
        return {'score': value, 'probabilities': probabilities, 'choice': list(LEVELS)[value],
                'model': DEFAULTS['model'], 'confidence': 1.0, 'usage': {'input_tokens': 10, 'output_tokens': 5}}


def setup_case(test):
    temporary = tempfile.TemporaryDirectory()
    test.addCleanup(temporary.cleanup)
    root = Path(temporary.name).resolve()
    store = Store(root)
    (root / 'test.txt').write_text('Checks read access. Checks membership updates.')
    draft = root / 'draft.json'
    write_json(draft, [{'id': 'case-a', 'source': 'test.txt', 'description': 'Read access is denied'},
                       {'id': 'case-b', 'source': 'test.txt', 'description': 'Membership updates clear cached access'}])
    build_index(store, draft, 'test-agent')
    change = root / 'change.json'
    write_json(change, {'repository': 'example/repo', 'id': 'PR-1', 'snapshot': 'revision-1',
                       'title': 'Fix membership access cache', 'description': '',
                       'diff': '- retain cached access\n+ invalidate on membership change', 'changed_files': ['src/access'],
                       'provenance': {'historical': True, 'outcomes_seen': False, 'context_verified': True}})
    return root, store, change


def outcomes(identifier):
    return {'schema_version': 1, 'prediction_id': identifier, 'collected_at': datetime.now(timezone.utc).isoformat(),
            'reviewer': 'human', 'runs': [{'id': 'run-1', 'attempt': 1, 'snapshot': 'revision-1',
            'status': 'completed', 'started_at': '2026-01-01T10:00:00+00:00',
            'execution': 'serial', 'order_verified': True, 'execution_order': ['case-a', 'case-b'],
            'tests': [{'id': 'case-a', 'status': 'passed', 'duration_seconds': 10},
                      {'id': 'case-b', 'status': 'failed', 'duration_seconds': 5,
                       'classification': 'confirmed_regression', 'evidence': 'Reproduced only after change; artifact X'}]}]}
