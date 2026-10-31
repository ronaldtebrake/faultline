"""Portable CI parser facts and observations. Never an execution decision.

Checksums detect corruption, not producer identity. Remote callers must validate
the CI producer before calling restore; local callers explicitly trust the input.
Only immutable source facts are restored into the cache. Resolution and runtime
invalidation run again against the destination tree.
"""
import hashlib
import json
import re
import time
from pathlib import Path

from ..core import FaultlineError, digest
from .common import checked, revision, save_frozen
from .config import load_config
from .ci_manifest import fingerprint
from .ci_handoff import json_data, repository_name, branch_name
from .dependency_graph import build, VERSION
from .dependency_baseline import require_ancestor
from .evidence import GitSources
from . import dependency_sources as adapters

MAX_BYTES = 64 * 1024 * 1024
FORMAT = 1
NO_EXECUTION = {'execution': 'none', 'omission_authorized': False, 'jev_requests': 0}


def engine_identity():
    root = Path(__file__).parent.parent
    return digest({p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(root.rglob('*')) if p.suffix in ('.py', '.php', '.mjs')})


def compatibility(store):
    config = load_config(store.root)
    return {'repository': config['repository'], 'config': fingerprint(config),
            'graph_version': VERSION, 'adapter': adapters.VERSION, 'engine': engine_identity(),
            'limits': {k: config['evaluator'][k] for k in ('max_test_bytes', 'max_evidence_pairs')}}


def document(value, kind):
    try:
        valid = (isinstance(value, dict) and value.get('schema_version') == 2 and value.get('kind') == kind and
                 value.get('integrity') == digest({k: v for k, v in value.items() if k != 'integrity'}))
    except (ValueError, TypeError, RecursionError):
        valid = False
    if not valid:
        raise FaultlineError('Corrupt or unsupported shared baseline document')
    return value


def producer(value):
    keys = {'repository', 'repository_id', 'workflow', 'run_id', 'run_attempt', 'event', 'branch', 'revision', 'collections'}
    if not isinstance(value, dict) or set(value) != keys:
        raise FaultlineError('Baseline needs exact CI producer provenance')
    repository_name(value['repository'])
    branch_name(value['branch'])
    if (any(type(value[k]) is not int or value[k] < 1 for k in ('repository_id', 'run_id', 'run_attempt')) or
            not isinstance(value['workflow'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.ya?ml', value['workflow']) or
            value['event'] != 'push' or not isinstance(value['revision'], str) or
            not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', value['revision']) or not isinstance(value['collections'], list)):
        raise FaultlineError('Invalid CI baseline producer')
    for row in value['collections']:
        if (not isinstance(row, dict) or set(row) != {'job_key', 'runtime'} or
                not isinstance(row['job_key'], str) or not re.fullmatch(r'[A-Za-z0-9_-]+', row['job_key']) or
                not isinstance(row['runtime'], str) or not re.fullmatch(r'[a-f0-9]{64}', row['runtime'])):
            raise FaultlineError('Invalid baseline job or shard provenance')
    if len({row['job_key'] for row in value['collections']}) != len(value['collections']):
        raise FaultlineError('Duplicate collection job key')
    return value


def source_keys(store, commit, limits):
    source = GitSources(store.root, commit, limits['max_test_bytes'])
    return {digest({'adapter': adapters.VERSION, 'language': adapters.language(path),
                    'oid': entry['oid'], 'mode': entry['mode']}): adapters.language(path)
            for path, entry in source.files.items() if adapters.language(path) != 'data'
            and entry['mode'].startswith('100') and entry['size'] <= source.max_bytes}


def pack(store, output, *, producer_data, runtime_paths=()):
    started = time.monotonic()
    meta = producer(producer_data)
    commit = revision(store.root)
    if meta['revision'] != commit:
        raise FaultlineError('Producer revision differs from the checked-out commit')
    runtime = {item['integrity']: item for item in (checked(p, 'dependency-runtime') for p in runtime_paths)}
    if {row['runtime'] for row in meta['collections']} != set(runtime):
        raise FaultlineError('Every runtime artifact needs producer job provenance')
    if any(item['revision'] != commit for item in runtime.values()):
        raise FaultlineError('Publish fresh observations only; never relabel carried observations')
    result = build(store, runtime_paths=runtime_paths)
    identity = compatibility(store)
    cache = store.path / 'dependency-graph' / 'source-cache'
    facts = {}
    for key in sorted(source_keys(store, commit, identity['limits'])):
        path = cache / (key + '.json')
        if path.exists():
            facts[key] = checked(path, 'dependency-source')
    value = {'schema_version': 2, 'kind': 'dependency-shared-baseline', 'version': FORMAT,
             **identity, 'revision': commit, 'producer': meta, 'sources': facts,
             'runtime': list(runtime.values()), 'coverage_complete': False, **NO_EXECUTION}
    if len(json.dumps(value, indent=2, ensure_ascii=False).encode()) > MAX_BYTES - 256:
        raise FaultlineError('Shared baseline exceeds size limit; nothing was truncated')
    save_frozen(output, value)
    return {'path': str(output), 'revision': commit, 'source_facts': len(facts), 'runtime_artifacts': len(runtime),
            **metrics(result), 'seconds': round(time.monotonic() - started, 3), **NO_EXECUTION}


def load(store, path):
    with Path(path).open('rb') as stream:
        value = document(json_data(stream.read(MAX_BYTES + 1), MAX_BYTES), 'dependency-shared-baseline')
    if value.get('version') != FORMAT or any(value.get(k) != v for k, v in compatibility(store).items()):
        raise FaultlineError('Shared baseline is incompatible with this repository, configuration or engine')
    meta = producer(value.get('producer'))
    if meta['revision'] != value.get('revision'):
        raise FaultlineError('Baseline revision differs from its producer')
    require_ancestor(store.root, value['revision'], revision(store.root))
    keys = source_keys(store, value['revision'], value['limits'])
    if not isinstance(value.get('sources'), dict) or set(value['sources']) - set(keys):
        raise FaultlineError('Baseline contains source facts outside its origin tree')
    for key, item in value['sources'].items():
        document(item, 'dependency-source')
        if (item.get('key') != key or not isinstance(item.get('facts'), dict) or
                item['facts'].get('language') != keys[key] or not isinstance(item['facts'].get('gaps'), list)):
            raise FaultlineError('Invalid shared source facts')
    if not isinstance(value.get('runtime'), list):
        raise FaultlineError('Invalid shared observations')
    for item in value['runtime']:
        document(item, 'dependency-runtime')
        if (item.get('version') != 1 or any(item.get(k) != value[k] for k in ('repository', 'config', 'revision')) or
                not isinstance(item.get('records'), list) or item.get('complete') is not False):
            raise FaultlineError('Shared observations have incompatible provenance')
    if {row['runtime'] for row in meta['collections']} != {item['integrity'] for item in value['runtime']}:
        raise FaultlineError('Shared observation job provenance differs')
    return value


def restore(store, path):
    """Caller has authenticated the producer; validate all entries before writing."""
    value = load(store, path)
    cache = store.path / 'dependency-graph' / 'source-cache'
    destinations = [(cache / (key + '.json'), item) for key, item in value['sources'].items()]
    folder = store.path / 'dependency-graph' / 'shared' / value['integrity']
    runtime = [folder / (item['integrity'] + '.json') for item in value['runtime']]
    destinations.extend(zip(runtime, value['runtime']))
    for destination, item in destinations:
        if destination.exists() and checked(destination) != item:
            raise FaultlineError('Shared baseline conflicts with existing immutable evidence')
    for destination, item in destinations:
        save_frozen(destination, item)
    return {'restored': True, 'origin_revision': value['revision'], 'source_facts': len(value['sources']),
            'runtime_paths': [str(p) for p in runtime], 'producer': value['producer'], **NO_EXECUTION}


def metrics(result):
    graph = result['graph']
    return {k: result[k] for k in ('parsed', 'reused', 'snapshot_reused')} | {
        'nodes': len(graph['nodes']), 'edges': len(graph['edges']), 'targets': len(graph['targets']),
        'nodes_with_gaps': sum(bool(n['gaps']) for n in graph['nodes'].values()),
        'runtime_reuse': graph['runtime_reuse'], 'coverage_complete': False}


def correspondence(carried, fresh):
    """Compare positive observations, including absent fresh records as unknown."""
    def records(graph):
        result = {}
        for target, observations in graph['observations'].items():
            for row in observations:
                key = (target, row['identity'])
                entry = result.setdefault(key, {'resources': set(), 'callables': set(), 'files': set()})
                entry['files'].update(row['files'])
                entry['resources'].update(digest(r) for r in row['resources'])
                entry['callables'].update(digest(r) for r in row['callables'])
        return result
    before, after = records(carried), records(fresh)
    common = before.keys() & after.keys()
    return {'comparable_tests': len(common), 'matching_observations': sum(before[k] == after[k] for k in common),
            'changed_observations': sum(before[k] != after[k] for k in common),
            'missing_fresh_observations': len(before.keys() - after.keys()),
            'new_observed_tests': len(after.keys() - before.keys()),
            'coverage_complete': False, 'omission_authorized': False}
