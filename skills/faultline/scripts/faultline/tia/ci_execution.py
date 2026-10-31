"""Opt-in execution of a portable file selection, with native validation in CI."""
import copy
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
import xml.etree.ElementTree as ET

from ..core import FaultlineError, digest, now
from .ci_manifest import resolve, fingerprint, SUPPORTED
from .evidence import GitSources
from .common import checked, revision, save_frozen, seal
from .config import load_config, variants, inside
from .runners import command, discover_suite, xml
from .results import junit


def ordered(config):
    by_name = {s['id']: s for s in config['suites']}
    result, active = [], set()
    def visit(name):
        if name in active:
            raise FaultlineError('Cyclic suite prerequisites')
        if name in result:
            return
        active.add(name)
        for parent in by_name[name]['prerequisites']:
            visit(parent)
        active.remove(name)
        result.append(name)
    for name in by_name:
        visit(name)
    return result


def plan(store, path):
    value, entries, errors = resolve(store, path)
    config = load_config(store.root)
    return {'revision': revision(store.root), 'manifest_digest': digest(value) if value else None,
            'fallbacks': errors, 'suites': entries, 'order': ordered(config),
            'matrix': {'include': [{'suite': key, 'mode': entries[s['id']]['mode']} for s, v, key in variants(config)]},
            'native_validation': 'Required in each prepared execution environment, including explicit none', 'jev_requests': 0}


def selector(root, suite, source):
    # Reverse configured runner->repository path translations for container selectors.
    for external, local in sorted(suite['path_map'].items(), key=lambda p: -len(p[1])):
        if source == local.rstrip('/') or source.startswith(local.rstrip('/') + '/'):
            return external.rstrip('/') + source[len(local.rstrip('/')):]
    return './' + os.path.relpath(root / source, root / suite['cwd'])


def phpunit_configuration(root, suite, variant):
    argv = command(suite, variant)
    if '--no-configuration' in argv:
        raise FaultlineError('PHPUnit configuration disabled; selective filtering unavailable')
    if any(a.startswith('-c') and a != '-c' and not a.startswith('--') for a in argv):
        raise FaultlineError('Use a separate -c argument or --configuration for selective PHPUnit')
    configured, position, width = None, None, 0
    for i, arg in enumerate(argv):
        if arg in ('-c', '--configuration'):
            if configured is not None or i + 1 >= len(argv):
                raise FaultlineError('Ambiguous PHPUnit configuration')
            configured, position, width = argv[i + 1], i, 2
        elif arg.startswith('--configuration='):
            if configured is not None:
                raise FaultlineError('Ambiguous PHPUnit configuration')
            configured, position, width = arg.split('=', 1)[1], i, 1
    cwd = inside(root, suite['cwd'])
    if configured is None:
        candidates = [cwd / 'phpunit.xml', cwd / 'phpunit.xml.dist']
        path = next((p for p in candidates if p.is_file()), None)
    else:
        path = inside(root, str(Path(suite['cwd']) / configured))
    if path is None or suite['path_map']:
        raise FaultlineError('Selective PHPUnit needs a locally readable configuration; run the helper inside its execution environment')
    return argv, path, position, width


def filtered_phpunit_inventory(root, suite, variant):
    """PHPUnit 9.6 lists tests before applying runtime name/group filters."""
    if 'discovery_command' in suite:
        return None  # Reviewed bridge explicitly promises the variant's exact cases.
    try:
        argv, path, _, _ = phpunit_configuration(root, suite, variant)
        unsupported = {'--filter', '--group', '--exclude-group', '--covers', '--uses', '--repeat'}
        if any(a.split('=', 1)[0] in unsupported for a in argv) or xml(path).find('groups') is not None:
            return 'PHPUnit test-list output does not verify runtime filters; retaining the full configured shard'
    except FaultlineError as exc:
        return str(exc)
    return None


@contextmanager
def phpunit_config(root, suite, variant, files):
    argv, path, position, width = phpunit_configuration(root, suite, variant)
    tree = copy.deepcopy(xml(path))
    suites = tree.find('testsuites')
    if tree.tag != 'phpunit' or suites is None:
        raise FaultlineError('Unsupported PHPUnit XML configuration')
    for node in list(suites):
        suites.remove(node)
    # Native enumeration resolves --testsuite and file exclusions. Runtime
    # group/name filters require a reviewed inventory bridge before selection.
    # Replace the selected suite contents, retaining every other configuration setting.
    names = []
    for i, arg in enumerate(argv):
        if arg == '--testsuite' and i + 1 < len(argv):
            names.extend(argv[i + 1].split(','))
        elif arg.startswith('--testsuite='):
            names.extend(arg.split('=', 1)[1].split(','))
    if len(set(names)) > 1:
        raise FaultlineError('Multiple PHPUnit suites need separate configured variants')
    node = ET.SubElement(suites, 'testsuite', {'name': names[0] if names else 'faultline'})
    for source in files:
        ET.SubElement(node, 'file').text = str(root / source)
    # Same directory preserves bootstrap, extension, coverage and other relative paths.
    fd, temporary = tempfile.mkstemp(prefix='.faultline-', suffix='.xml', dir=path.parent)
    os.close(fd)
    try:
        ET.ElementTree(tree).write(temporary, encoding='utf-8', xml_declaration=True)
        if position is not None:
            argv[position:position + width] = ['--configuration', temporary]
        else:
            argv += ['--configuration', temporary]
        yield argv
    finally:
        Path(temporary).unlink(missing_ok=True)


def process(argv, cwd, timeout):
    try:
        p = subprocess.run(argv, cwd=cwd, timeout=timeout, stdout=sys.stderr, stderr=sys.stderr)
        return p.returncode if p.returncode >= 0 else 128 - p.returncode
    except subprocess.TimeoutExpired:
        return 124
    except OSError:
        return 127
    except KeyboardInterrupt:
        return 130


def run(store, path, *, suite_key=None, execute=False, output=None, prerequisites=(), runners=None):
    proposed = plan(store, path)
    if not execute:
        return {**proposed, 'execution': 'none', 'exit_code': 0}
    config = load_config(store.root)
    from .common import git
    if git(store.root, 'status', '--porcelain', '--untracked-files=no'):
        raise FaultlineError('Execution needs an unchanged tracked checkout')
    available = {key: (s, v) for s, v, key in variants(config)}
    if suite_key and suite_key not in available:
        matches = [key for key, (s, _) in available.items() if s['id'] == suite_key]
        if len(matches) != 1:
            raise FaultlineError('Choose an exact suite:variant')
        suite_key = matches[0]
    keys = [suite_key] if suite_key else [key for name in proposed['order'] for key, (s, _) in available.items() if s['id'] == name]
    if runners and not suite_key:
        names = {s['id'] for s in config['suites'] if s['runner'] in runners}
        pending = list(names)
        by_name = {s['id']: s for s in config['suites']}
        while pending:
            for parent in by_name[pending.pop()]['prerequisites']:
                if parent not in names:
                    names.add(parent)
                    pending.append(parent)
        keys = [k for k in keys if available[k][0]['id'] in names]
        if not keys:
            raise FaultlineError('No suites configured for the requested runners')
    folder = store.path / 'executions' / (str(time.time_ns()))
    folder.mkdir(parents=True)
    completed = {}
    for supplied in prerequisites:
        receipt = checked(Path(supplied), 'ci-execution')
        if (receipt['revision'] != proposed['revision'] or receipt['config'] != fingerprint(config) or
                receipt['manifest_digest'] != proposed['manifest_digest'] or receipt['exit_code'] != 0):
            raise FaultlineError('Prerequisite receipt does not match this execution')
        completed.update({r['suite']: r for r in receipt['runs'] if r['exit_code'] == 0 and r['status'] != 'not_selected'})
    rows = []
    for key in keys:
        suite, variant = available[key]
        required = {k for k, (s, _) in available.items() if s['id'] in suite['prerequisites']}
        row = run_variant(store, path, suite, variant, folder, missing_prerequisites=required - completed.keys())
        rows.append(row)
        if row['exit_code'] == 0 and row['status'] != 'not_selected':
            completed[key] = row
        if row['exit_code']:
            break
    result = seal({'schema_version': 2, 'kind': 'ci-execution', 'created_at': now(),
                   'revision': proposed['revision'], 'config': fingerprint(config), 'manifest_digest': proposed['manifest_digest'],
                   'runs': rows, 'exit_code': next((r['exit_code'] for r in rows if r['exit_code']), 0),
                   'duration_seconds': sum(r['duration_seconds'] for r in rows), 'jev_requests': 0})
    destination = Path(output) if output else folder / 'execution.json'
    save_frozen(destination, result)
    return {**result, 'path': str(destination)}


def run_variant(store, manifest, suite, variant, folder, *, missing_prerequisites=()):
    root = store.root
    key = suite['id'] + ':' + variant['id']
    value, entries, errors = resolve(store, manifest)
    entry = entries[suite['id']]
    mode, requested = entry['mode'], entry.get('files', [])
    start = time.monotonic()
    tested_revision = revision(root)
    if not suite['command']:
        raise FaultlineError('Configure the full execution command before running CI')
    native = discover_suite(root, suite, variant) if suite['kind'] != 'check' else {'complete': True, 'units': [], 'errors': []}
    if suite['runner'] == 'phpunit' and native['complete']:
        limitation = filtered_phpunit_inventory(root, suite, variant)
        if limitation:
            native = {**native, 'complete': False, 'units': [], 'errors': [limitation]}
    units = {u['source']: u for u in native['units']}
    native_fingerprint = (digest({u['id']: u['locator']['native_cases'] for u in units.values()})
                          if suite['runner'] == 'playwright' and native['complete'] and 'discovery_command' not in suite else None)
    if not native['complete'] or any(u.get('requires_full_suite') for u in units.values()):
        errors += native.get('errors', []) or ['native_dependencies_require_full_suite']
        mode = 'all'
    if mode != 'all' and suite['runner'] == 'playwright':
        from .generation_evidence import check_native
        expected_generation = (value or {}).get('generation', {}).get(suite['id'], {}).get(variant['id'], {})
        try:
            check_native(units, expected_generation)
        except FaultlineError as exc:
            errors.append(str(exc))
            mode = 'all'
    allowed = set(GitSources(root, tested_revision).glob(suite['sources']))
    native_support = {u['source'] for u in units.values() if u.get('native_support')} if suite['runner'] == 'playwright' and 'discovery_command' not in suite else set()
    if units.keys() - allowed - native_support:
        errors.append('Native discovery includes sources outside the assessed tracked inventory')
        mode = 'all'
    if set(requested) - units.keys():
        errors.append('Selected source is not executable in this variant; keeping the full variant')
        mode = 'all'
    if suite['runner'] not in SUPPORTED:
        mode = 'all'
    selected_units = None
    if suite['runner'] == 'playwright' and mode == 'selected':
        from .playwright_runner import inventory as playwright_inventory
        try:
            with tempfile.TemporaryDirectory(prefix='faultline-select-', dir=root / suite['cwd']) as temporary:
                selected_units = playwright_inventory(root, suite, variant, Path(temporary) / 'inventory.json', requested)
            all_members = {(u['id'], m) for u in units.values() for m in u['members']}
            requested_members = {(units[p]['id'], m) for p in requested for m in units[p]['members']}
            selected_members = {(u['id'], m) for u in selected_units for m in u['members']}
            if not requested_members.issubset(selected_members) or not selected_members.issubset(all_members):
                raise FaultlineError('Playwright filtering changed the configured variant or shard inventory')
            if any(case != units[u['source']]['locator']['native_cases'].get(member)
                   for u in selected_units for member, case in u['locator']['native_cases'].items()):
                raise FaultlineError('Playwright source or generation changed during discovery')
        except FaultlineError as exc:
            errors.append(str(exc))
            mode, selected_units = 'all', None
    # A bootstrap must not change tracked sources while validating selectors.
    from .common import git
    if revision(root) != tested_revision or git(root, 'status', '--porcelain', '--untracked-files=no'):
        raise FaultlineError('Runner discovery changed the tested checkout; refusing execution')
    current, _, validation = resolve(store, manifest)
    if validation or (value and current != value):
        errors += validation or ['Manifest changed during discovery']
        mode = 'all'
    validation_seconds = time.monotonic() - start
    if mode == 'none':
        return {'suite': key, 'mode': mode, 'status': 'not_selected', 'exit_code': 0, 'files': [],
                'native_inventory_fingerprint': native_fingerprint,
                'fallbacks': errors, 'validation_seconds': validation_seconds, 'duration_seconds': time.monotonic() - start, 'outcomes': []}
    if missing_prerequisites:
        raise FaultlineError('Missing successful prerequisite variants: ' + ', '.join(sorted(missing_prerequisites)))
    paths = sorted(units if mode == 'all' else requested)
    artifacts = folder / key.replace(':', '-')
    artifacts.mkdir()
    observed, unmatched, codes = [], [], []

    def launch(argv, result_path, expected):
        codes.append(process(argv, root / suite['cwd'], suite['timeout_seconds']))
        if result_path is not None:
            try:
                data, missing = junit(result_path, {'runner': suite['runner'], 'units': expected}, root=root, config=suite)
            except FaultlineError:
                data, missing = [], [{'reason': 'Invalid native results'}]
            observed.extend(data)
            unmatched.extend(missing)
            expected_ids = {(u['id'], member) for u in expected for member in u['members']}
            actual = {(row['id'], row['member']) for row in data}
            if not expected_ids.issubset(actual):
                unmatched.append({'reason': 'Expected native cases missing from results'})
            if len(actual) != len(data):
                unmatched.append({'reason': 'Duplicate native cases in results'})
            if not data:
                unmatched.append({'reason': 'No matched native cases in results'})
    argv = command(suite, variant)
    if suite['runner'] == 'phpunit':
        result_path = artifacts / 'junit.xml'
        if mode == 'selected':
            try:
                with phpunit_config(root, suite, variant, paths) as selected:
                    launch([*selected, '--log-junit', str(result_path)], result_path, [units[p] for p in paths])
            except FaultlineError as exc:
                errors.append(str(exc))
                mode, paths = 'all', sorted(units)
        if mode == 'all':
            launch([*argv, '--log-junit', str(result_path)], result_path, list(units.values()))
    elif suite['runner'] == 'behat' and mode == 'selected':
        # One native invocation per feature preserves hooks and existing reset wrappers.
        for i, source in enumerate(paths):
            result_path = artifacts / str(i)
            result_path.mkdir()
            launch([*argv, '--format=junit', '--out=' + str(result_path), selector(root, suite, source)], result_path, [units[source]])
    elif suite['runner'] == 'behat':
        result_path = artifacts / 'junit'
        result_path.mkdir()
        launch([*argv, '--format=junit', '--out=' + str(result_path)], result_path, list(units.values()))
    elif suite['runner'] == 'playwright' and native['complete']:
        from .playwright_runner import configuration, results as playwright_results
        result_path = artifacts / 'playwright.json'
        expected = selected_units if mode == 'selected' else list(units.values())
        try:
            with configuration(root, suite, variant, result_path, requested if mode == 'selected' else None) as selected:
                codes.append(process(selected, root / suite['cwd'], suite['timeout_seconds']))
            data, missing = playwright_results(result_path, expected, root, suite)
            observed.extend(data)
            unmatched.extend(missing)
            if any(row['status'] == 'failed' for row in data) and not any(codes):
                codes.append(1)
            paths = sorted(u['source'] for u in expected)
        except FaultlineError as exc:
            unmatched.append({'reason': str(exc)})
    else:
        launch(argv, None, [])
    code = next((c for c in codes if c), 0)
    if unmatched and not code:
        # Selective execution must account for every expected native case. A full
        # fallback may have no usable identity map, but still must produce cases.
        counts = 0
        for artifact in artifacts.rglob('*.xml'):
            try:
                counts += len(xml(artifact).findall('.//testcase'))
            except FaultlineError:
                pass
        if mode == 'selected' or native['complete'] or not counts:
            code = 2
    return {'suite': key, 'mode': mode, 'status': 'completed' if not code else 'failed_or_incomplete',
            'native_inventory_fingerprint': native_fingerprint,
            'exit_code': code, 'files': paths, 'fallbacks': errors, 'validation_seconds': validation_seconds,
            'duration_seconds': time.monotonic() - start, 'outcomes': observed, 'unmatched_results': unmatched,
            'result_directory': str(artifacts)}


def compare(selected_path, full_path):
    selected, full = checked(Path(selected_path), 'ci-execution'), checked(Path(full_path), 'ci-execution')
    if any(selected[k] != full[k] for k in ('revision', 'config')):
        raise FaultlineError('Compare executions of the same revision and configuration')
    if any(r.get('unmatched_results') for r in selected['runs']):
        raise FaultlineError('Selected execution has incomplete or unmatched results')
    full_suites = {r['suite'] for r in full['runs'] if r['mode'] == 'all' and r.get('outcomes') and not r.get('unmatched_results')}
    if {r['suite'] for r in selected['runs']} != full_suites:
        raise FaultlineError('Full execution must cover every compared suite with matched results')
    full_inventory = {r['suite']: r.get('native_inventory_fingerprint') for r in full['runs']}
    if any(r.get('native_inventory_fingerprint') != full_inventory[r['suite']] for r in selected['runs']):
        raise FaultlineError('Native test source or generation differs between selected and full executions')
    identities = lambda doc: {(r['suite'], t['id'], t['member']): t for r in doc['runs'] for t in r['outcomes']}
    selected_cases, full_cases = identities(selected), identities(full)
    if selected_cases.keys() - full_cases.keys():
        raise FaultlineError('Selected cases are outside the full execution inventory')
    if any(case.get('native_source_fingerprint') != full_cases[key].get('native_source_fingerprint')
           for key, case in selected_cases.items()):
        raise FaultlineError('Native test source or generation differs between selected and full executions')
    failures = lambda doc: {(r['suite'], t['id'], t['member']) for r in doc['runs'] for t in r['outcomes'] if t['status'] in ('failed', 'error')}
    return {'revision': full['revision'], 'selected_seconds': selected['duration_seconds'],
            'full_seconds': full['duration_seconds'], 'observed_seconds_difference': full['duration_seconds'] - selected['duration_seconds'],
            'failures_only_in_full': sorted(failures(full) - failures(selected)),
            'limitation': 'Observed failures are unclassified. Infrastructure, flakes and regressions require review; serial durations are not CI wall-clock savings.'}
