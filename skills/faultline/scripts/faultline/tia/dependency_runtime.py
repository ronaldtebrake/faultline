"""Validate test-attributed runtime evidence from existing CI runs.

Collectors do not claim complete coverage. Records bind to a clean, exact Git
snapshot and one configured suite variant. URLs remain observations, not proof
that a particular server implementation executed (a response may be mocked).
"""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from ..core import FaultlineError, digest
from .common import checked, git, revision, save_frozen, seal
from .config import load_config, variants
from .ci_manifest import fingerprint
from .source_index import open_index

VERSION = 1
MAX_BYTES = 16 * 1024 * 1024
CALLABLE_ROLES = {'step', 'before_step', 'after_step', 'before_scenario', 'after_scenario',
                  'before_feature', 'after_feature', 'before_suite', 'after_suite'}


def native_callables(raw, source, verified):
    """Check native reflection labels and exact source ranges, not call-graph completeness."""
    entries = raw.get('callables', [])
    if not isinstance(entries, list) or len(entries) > 4096:
        raise FaultlineError('Runtime callables must be an array of at most 4096 entries')
    if 'callables' in raw and raw['producer'] != 'behat':
        raise FaultlineError('Native callable evidence requires Behat records')
    result = {}
    for item in entries:
        if not isinstance(item, dict) or set(item) != {'source', 'symbol', 'start_line', 'end_line', 'sha256', 'role', 'execution'}:
            raise FaultlineError('Malformed native callable evidence')
        path = relative(item['source'])
        symbol = item['symbol']
        start, end = item['start_line'], item['end_line']
        if (not isinstance(symbol, str) or not symbol or len(symbol) > 1024 or
                any(ord(char) < 32 for char in symbol) or
                type(start) is not int or type(end) is not int or start < 1 or end < start or
                not isinstance(item['role'], str) or item['role'] not in CALLABLE_ROLES or
                item['execution'] not in ('called', 'resolved') or
                (item['role'] != 'step' and item['execution'] != 'called') or
                not isinstance(item['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', item['sha256'])):
            raise FaultlineError('Invalid native callable identity, range, role, execution or hash')
        key = digest(item)
        if key not in verified:
            data = source.read(path)
            # PHP file() and Reflection use LF line boundaries, preserving CR bytes.
            lines = data.split(b'\n')
            if end > len(lines) - int(lines[-1] == b''):
                raise FaultlineError('Native callable range is outside its tracked source')
            span = b'\n'.join(lines[start - 1:end]) + (b'\n' if end < len(lines) else b'')
            if hashlib.sha256(span).hexdigest() != item['sha256']:
                raise FaultlineError('Native callable source does not match the Git snapshot')
            verified.add(key)
        result[key] = item
    return sorted(result.values(), key=lambda r: (r['source'], r['start_line'], r['end_line'], r['symbol'], r['role'], r['execution']))


def relative(path):
    if (not isinstance(path, str) or not path or '\\' in path or '\0' in path or
            PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts or
            str(PurePosixPath(path)) != path):
        raise FaultlineError('Runtime dependencies require normalized repository-relative paths')
    return path


def clean(store):
    if git(store.root, 'status', '--porcelain', '--untracked-files=no'):
        raise FaultlineError('Runtime evidence requires an unchanged tracked checkout')


def runtime_mounts(values, host_root, source):
    """Declare container directories without assuming they exist on the host."""
    result = []
    roots = [str(host_root)]
    if len(values) > 32:
        raise FaultlineError('At most 32 runtime mounts can be declared')
    for value in values:
        if not isinstance(value, str) or '=' not in value:
            raise FaultlineError('Use --mount /runtime/directory=repository/subdirectory (or =. for the repository root)')
        root, prefix = value.split('=', 1)
        path = PurePosixPath(root)
        if (not path.is_absolute() or str(path) != root or '..' in path.parts or '\\' in root or
                any(ord(char) < 32 for char in root) or root == '/'):
            raise FaultlineError('Runtime mount roots must be normalized absolute POSIX directories')
        prefix = '' if prefix == '.' else relative(prefix)
        if prefix and not any(name.startswith(prefix + '/') for name in source.files):
            raise FaultlineError('Runtime mount prefix must name a tracked repository directory')
        if any(root == old or root.startswith(old.rstrip('/') + '/') or old.startswith(root + '/') for old in roots):
            raise FaultlineError('Runtime mount roots must not overlap each other or the host checkout')
        roots.append(root)
        result.append({'root': root, 'prefix': prefix})
    return sorted(result, key=lambda item: item['root'])


def capture_context(store, suite_key, output, *, mounts=()):
    clean(store)
    config = load_config(store.root)
    available = {key: (suite, variant) for suite, variant, key in variants(config)}
    if suite_key not in available:
        raise FaultlineError('Choose an exact configured suite:variant for runtime collection')
    suite, variant = available[suite_key]
    if mounts and suite['runner'] != 'behat':
        raise FaultlineError('Runtime mount mapping currently requires the Behat event collector')
    source, inventory, _ = open_index(store, config)
    row = next(s for s in inventory['suites'] if s['key'] == suite_key)
    if not row['complete']:
        raise FaultlineError('Cannot collect a baseline for an empty configured inventory')
    value = seal({'schema_version': 2, 'kind': 'dependency-runtime-context', 'version': VERSION,
                  'repository': config['repository'], 'revision': source.revision,
                  'config': fingerprint(config), 'suite': suite['id'], 'variant': variant['id'],
                  'runner': suite['runner'], 'sources': sorted(u['source'] for u in row['units']),
                  'tree': source.hashes(source.files), 'root': str(store.root.resolve()),
                  'mounts': runtime_mounts(mounts, store.root.resolve(), source)})
    save_frozen(output, value)
    return {'path': str(output), 'context': value['integrity'], 'revision': value['revision'],
            'suite': suite_key, 'mounts': value['mounts'], 'jev_requests': 0, 'execution': 'none'}


def runtime_source_hashes(raw, context, source, expected, verified):
    hashes = raw.get('source_hashes')
    if hashes is None:
        if context.get('mounts'):
            raise FaultlineError('Mapped runtime evidence requires hashes for every observed source and test file')
        return None
    if not isinstance(hashes, dict) or set(hashes) != expected:
        raise FaultlineError('Runtime source hashes must cover exactly the test and dependency files')
    for name, value in hashes.items():
        relative(name)
        if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
            raise FaultlineError('Runtime source hashes must be SHA-256 values')
    source.prefetch(hashes)
    for name, value in hashes.items():
        if name not in verified:
            verified[name] = hashlib.sha256(source.read(name)).hexdigest()
        if value != verified[name]:
            raise FaultlineError('Runtime file content does not match the Git snapshot')
    return dict(sorted(hashes.items()))


def json_records(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise FaultlineError('Runtime dependency evidence exceeds the size limit')
    def unique(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError('Duplicate runtime JSON key')
            result[name] = value
        return result
    try:
        value = json.loads(path.read_text(), object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise FaultlineError('Malformed runtime dependency JSON') from None
    records = value if isinstance(value, list) else [value]
    if not records or not all(isinstance(r, dict) for r in records):
        raise FaultlineError('Runtime dependency evidence must contain records')
    return records


def import_records(store, context_path, paths, *, output=None):
    store.initialize()
    clean(store)
    context = checked(context_path, 'dependency-runtime-context')
    config = load_config(store.root)
    source, _, _ = open_index(store, config)
    if (context.get('version') != VERSION or context['revision'] != revision(store.root) or
            context['repository'] != config['repository'] or context['config'] != fingerprint(config) or
            context['tree'] != source.hashes(source.files)):
        raise FaultlineError('Runtime context does not match this repository, revision, or configuration')
    records, verified_callables, verified_sources = {}, set(), {}
    for path in paths:
        for raw in json_records(path):
            if (type(raw.get('version')) is not int or raw['version'] != VERSION or raw.get('context') != context['integrity'] or
                    raw.get('producer') not in ('behat', 'playwright') or raw['producer'] != context['runner']):
                raise FaultlineError('Runtime record has a different context or unsupported producer')
            test = relative(raw.get('test_source'))
            if test not in context['sources']:
                raise FaultlineError('Runtime test is outside the configured source inventory')
            if not isinstance(raw.get('test_identity'), str) or not raw['test_identity']:
                raise FaultlineError('Runtime record needs a native test identity')
            if raw.get('status') not in ('passed', 'failed', 'skipped', 'timedOut', 'interrupted', 'unknown'):
                raise FaultlineError('Invalid runtime test status')
            files = raw.get('files')
            if not isinstance(files, list):
                raise FaultlineError('Runtime files must be an array')
            generation = raw.get('generation')
            if generation is not None:
                from .playwright_sources import validate
                if raw['producer'] != 'playwright':
                    raise FaultlineError('Generation declarations require Playwright records')
                validate(generation, source, test)
                files = [*files, *generation['inputs']]
            callables = native_callables(raw, source, verified_callables)
            files = [*files, *(item['source'] for item in callables)]
            for name in files:
                relative(name)
                if name not in source.files or not source.files[name]['mode'].startswith('100'):
                    raise FaultlineError('Runtime dependency is not a tracked regular source')
            source_hashes = runtime_source_hashes(raw, context, source, {test, *files}, verified_sources)
            resources = raw.get('resources', [])
            if not isinstance(resources, list):
                raise FaultlineError('Runtime resources must be an array')
            for resource in resources:
                if (not isinstance(resource, dict) or set(resource) != {'kind', 'method', 'path'} or
                        resource['kind'] != 'http_request' or not isinstance(resource['method'], str) or
                        not resource['method'].isalpha() or not isinstance(resource['path'], str) or
                        not resource['path'].startswith('/') or '?' in resource['path'] or '#' in resource['path']):
                    raise FaultlineError('Runtime HTTP observations require a method and path without query or fragment')
            gaps = raw.get('gaps', [])
            if not isinstance(gaps, list) or not all(isinstance(g, str) and g for g in gaps):
                raise FaultlineError('Runtime gaps must be strings')
            record = {'test_source': test, 'test_identity': raw['test_identity'], 'producer': raw['producer'],
                      'status': raw['status'], 'files': sorted(set(files)),
                      'resources': sorted({digest(r): r for r in resources}.values(), key=lambda r: (r['method'], r['path'])),
                      'gaps': sorted(set(gaps)), 'retry': raw.get('retry', 0)}
            if generation is not None:
                record['generation'] = generation
            if 'callables' in raw:
                record['callables'] = callables
            if source_hashes is not None:
                record['source_hashes'] = source_hashes
            if type(record['retry']) is not int or record['retry'] < 0:
                raise FaultlineError('Invalid runtime retry index')
            records[digest(record)] = record
            if len(records) > config['evaluator']['max_evidence_pairs']:
                raise FaultlineError('Runtime records exceed max_evidence_pairs; no evidence was truncated')
    if not records:
        raise FaultlineError('No runtime dependency evidence was supplied')
    value = seal({'schema_version': 2, 'kind': 'dependency-runtime', 'version': VERSION,
                  'repository': context['repository'], 'revision': context['revision'], 'config': context['config'],
                  'suite': context['suite'], 'variant': context['variant'], 'context': context['integrity'],
                  'records': sorted(records.values(), key=lambda r: (r['test_source'], r['test_identity'], r['retry'], digest(r))),
                  'complete': False, 'limitations': ['Observed dependencies only; missing paths cannot authorize omission.',
                                                   'HTTP requests may be mocked and do not prove server-side execution.']})
    destination = Path(output) if output else store.path / 'dependency-graph' / 'runtime' / (value['integrity'] + '.json')
    save_frozen(destination, value)
    return {'path': str(destination), 'records': len(records), 'revision': value['revision'],
            'coverage_complete': False, 'omission_authorized': False, 'jev_requests': 0}
