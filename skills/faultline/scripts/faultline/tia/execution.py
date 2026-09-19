"""Execute the configured full suite against a validated, frozen shadow proposal."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from ..core import FaultlineError, now
from . import catalog
from .common import checked, save_frozen, seal
from .config import load_config, variants
from .runners import command
from .selection import POLICY, inventory_identity, records, workspace


def validate(store, path):
    selection = checked(Path(path), 'selection')
    config = load_config(store.root)
    if selection.get('policy') != POLICY or selection.get('config_hash') != config['config_hash']:
        raise FaultlineError('Selection policy/configuration mismatch; select again before execution')
    if workspace(store.root) != selection.get('workspace'):
        raise FaultlineError('Checkout differs from the frozen selection; select again before execution')
    inventory = catalog.discover(store.root, config)
    if inventory_identity(inventory) != selection.get('inventory_hash') or records(store.root, inventory) != selection.get('catalog'):
        raise FaultlineError('Native inventory or catalog changed; select again before execution')
    return selection, config


def run_suite(store, selection_path, suite_key, *, prerequisites=(), output=None, junit_output=None):
    selection, config = validate(store, selection_path)
    available = {key: (suite, variant) for suite, variant, key in variants(config)}
    if suite_key not in available:
        matches = [key for key, (suite, _) in available.items() if suite['id'] == suite_key]
        if len(matches) != 1:
            raise FaultlineError('Choose an exact suite:variant from the selection')
        suite_key = matches[0]
    suite, variant = available[suite_key]
    # CI owns scheduling. Require successful receipts for every prerequisite variant.
    required = {key for key, (s, _) in available.items() if s['id'] in suite['prerequisites']}
    supplied = set()
    for path in prerequisites:
        receipt = checked(Path(path), 'execution')
        if receipt.get('selection_id') != selection['integrity'] or receipt.get('exit_code') != 0:
            raise FaultlineError('Prerequisite receipt must be successful for this exact selection')
        supplied.add(receipt['suite_key'])
    if required - supplied:
        raise FaultlineError('Missing successful prerequisite receipts: ' + ', '.join(sorted(required - supplied)))
    frozen = next((s for s in selection['suites'] if s['key'] == suite_key), None)
    if not frozen or frozen.get('execution') != 'full':
        raise FaultlineError('Unsupported execution plan; select again')
    argv = command(suite, variant)
    result_path = None
    if junit_output:
        result_path = Path(junit_output).resolve()
        if result_path.exists():
            raise FaultlineError('JUnit output already exists; use a fresh path for this execution')
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if suite['runner'] == 'phpunit':
            argv += ['--log-junit', str(result_path)]
        elif suite['runner'] == 'behat':
            result_path.mkdir()
            argv += ['--format=junit', '--out=' + str(result_path)]
        else:
            raise FaultlineError('Automatic JUnit capture supports PHPUnit and Behat; generic runners supply their own results')
    started, wall = now(), time.monotonic()
    status = 'completed'
    try:
        # Stream output; do not store runner logs or secrets in the receipt.
        p = subprocess.run(argv, cwd=store.root / suite['cwd'],
                           stdout=sys.stderr, stderr=sys.stderr, timeout=suite['timeout_seconds'])
        code = p.returncode if p.returncode >= 0 else 128 - p.returncode
    except subprocess.TimeoutExpired:
        code, status = 124, 'timed_out'
    except OSError:
        code, status = 127, 'unavailable'
    except KeyboardInterrupt:
        code, status = 130, 'interrupted'
    receipt = seal({'schema_version': 2, 'kind': 'execution', 'selection_id': selection['integrity'],
                    'head': selection['change']['head'], 'suite_key': suite_key, 'mode': 'full_shadow',
                    'started_at': started, 'completed_at': now(), 'duration_seconds': time.monotonic() - wall,
                    'status': status, 'exit_code': code, 'prerequisites': sorted(supplied),
                    'result_path': str(result_path) if result_path else None, 'result_format': 'junit' if result_path else None})
    output = Path(output) if output else store.path / 'runs' / (receipt['integrity'] + '.json')
    save_frozen(output, receipt)
    return {'path': str(output.resolve()), **receipt}
