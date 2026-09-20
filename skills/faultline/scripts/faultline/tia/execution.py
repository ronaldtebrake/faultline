"""Execute the configured full suite against a validated, frozen shadow proposal."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from ..core import FaultlineError, now
from .common import checked, save_frozen, seal
from .config import load_config, variants
from .runners import command, discover_suite
from .selection import POLICY, inventory_identity, workspace


def validate(store, path):
    selection = checked(Path(path), 'selection')
    config = load_config(store.root)
    if selection.get('policy') != POLICY or selection.get('config_hash') != config['config_hash']:
        raise FaultlineError('Selection policy/configuration mismatch; select again before execution')
    if workspace(store.root) != selection.get('workspace'):
        raise FaultlineError('Checkout differs from the frozen selection; select again before execution')
    current = workspace(store.root)
    if not current['clean'] or current['head'] != selection['change']['head']:
        raise FaultlineError('Execution requires a clean checkout of the selected head revision')
    from .source_index import open_index
    _, inventory, _ = open_index(store, config, selection['change']['head'])
    if inventory_identity(inventory) != selection.get('inventory_hash'):
        raise FaultlineError('Git source inventory changed; select again before execution')
    return selection, config


def run_suite(store, selection_path, suite_key, *, prerequisites=(), output=None, junit_output=None, execute=False):
    if not execute:
        selection = checked(Path(selection_path), 'selection')
        matching = [s for s in selection['suites'] if s['key'] == suite_key or s['suite'] == suite_key]
        if len(matching) != 1:
            raise FaultlineError('Choose an exact suite:variant from the selection')
        from .proposals import report_selection
        return {**report_selection(store, selection), 'suite_key': matching[0]['key'], 'exit_code': 0}
    selection, config = validate(store, selection_path)
    available = {key: (suite, variant) for suite, variant, key in variants(config)}
    if suite_key not in available:
        matches = [key for key, (suite, _) in available.items() if suite['id'] == suite_key]
        if len(matches) != 1:
            raise FaultlineError('Choose an exact suite:variant from the selection')
        suite_key = matches[0]
    suite, variant = available[suite_key]
    if not suite['command']:
        raise FaultlineError('Configure an execution command before using --execute')
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
    if not frozen or frozen.get('execution') != 'none':
        raise FaultlineError('Unsupported execution plan; select again')
    # Resolve only this requested suite, after checking its prerequisites. Native
    # discovery can bootstrap the application and belongs in the execution environment.
    validation_started = time.monotonic()
    native = ({'key': suite_key, 'runner': suite['runner'], 'kind': 'check',
               'complete': True, 'units': [], 'errors': []} if suite['kind'] == 'check'
              else discover_suite(store.root, suite, variant))
    proposed_ids = {u['id'] for u in frozen['units']}
    native_ids = {u['id'] for u in native['units']}
    validation_reasons = []
    if not native['complete']:
        validation_reasons.append('native_discovery_incomplete')
    if suite['kind'] != 'check' and proposed_ids != native_ids:
        validation_reasons.append('source_targets_differ_from_native_inventory')
    if any(u.get('requires_full_suite') for u in native['units']):
        validation_reasons.append('native_dependencies_require_full_suite')
    validation_seconds = time.monotonic() - validation_started
    if workspace(store.root) != selection['workspace']:
        raise FaultlineError('Checkout changed during runner validation; select again before execution')
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
                    'head': selection['change']['head'], 'suite_key': suite_key, 'mode': 'full_evaluation',
                    'started_at': started, 'completed_at': now(), 'duration_seconds': time.monotonic() - wall,
                    'status': status, 'exit_code': code,
                    'native_inventory': native, 'validation_seconds': validation_seconds, 'proposal_validated': not validation_reasons,
                    'validation_fallbacks': validation_reasons, 'prerequisites': sorted(supplied),
                    'result_path': str(result_path) if result_path else None, 'result_format': 'junit' if result_path else None})
    output = Path(output) if output else store.path / 'runs' / (receipt['integrity'] + '.json')
    save_frozen(output, receipt)
    return {'path': str(output.resolve()), **receipt}
