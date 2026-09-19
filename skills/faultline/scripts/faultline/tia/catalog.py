"""Reviewed, Git-shared descriptions keyed to native execution units."""
from __future__ import annotations

from ..core import FaultlineError, digest, now, read_json, write_json
from .common import hashes, glob_files, revision, seal
from .config import SCHEMA, inside, variants
from .runners import discover_suite


def discover(root, config):
    suites = [discover_suite(root, suite, variant) for suite, variant, _ in variants(config)]
    inputs = ['faultline.json', *glob_files(root, [p for s in config['suites'] for p in s['shared_inputs']])]
    return seal({'schema_version': SCHEMA, 'kind': 'inventory', 'created_at': now(),
                 'head': revision(root), 'config_hash': config['config_hash'], 'suites': suites,
                 'execution_inputs': hashes(root, inputs), 'complete': all(s['complete'] for s in suites)})


def source_inventory(root, config, *, native=False):
    """Enumerate configured source targets without loading the application.

    complete describes enumeration of configured paths, never native completeness.
    Optional native evidence enriches matching files without narrowing the universe.
    """
    suites, files_cache, hashes_cache = [], {}, {}
    for suite, variant, key in variants(config):
        patterns = tuple(suite['sources'])
        if patterns not in files_cache:
            files_cache[patterns] = glob_files(root, patterns)
        sources = files_cache[patterns]
        whole = suite['kind'] == 'check'
        if whole:
            sources = ['faultline.json']
        units = []
        for source in sources:
            identity = (source, tuple(suite['description_inputs']))
            if identity not in hashes_cache:
                hashes_cache[identity] = hashes(root, [source, *glob_files(root, suite['description_inputs'])])
            fingerprint = hashes_cache[identity]
            units.append({'id': key + ':' + ('__suite__' if whole else source),
                          'source': source, 'members': [], 'locator': {'file': source},
                          'title': suite['id'] if whole else source,
                          'kind': 'check' if whole else 'source',
                          'description_hash': digest({'sources': fingerprint}),
                          'source_hashes': fingerprint})
        row = {'key': key, 'suite': suite['id'], 'variant': variant['id'], 'runner': suite['runner'],
               'kind': suite['kind'], 'complete': bool(units), 'units': units,
               'errors': [] if units else ['no_configured_source_targets'], 'native_complete': False}
        if native and not whole:
            evidence = discover_suite(root, suite, variant)
            row['native_evidence'] = evidence
            row['native_complete'] = evidence['complete']
            by_source = {u['source']: u for u in evidence['units']}
            for unit in units:
                if unit['source'] in by_source:
                    found = by_source[unit['source']]
                    for field in ('members', 'locator', 'title', 'requires_full_suite'):
                        if field in found:
                            unit[field] = found[field]
        suites.append(row)
    inputs = ['faultline.json', *glob_files(root, [p for s in config['suites'] for p in s['shared_inputs']])]
    return seal({'schema_version': SCHEMA, 'kind': 'inventory', 'basis': 'source',
                 'native_enrichment': native, 'created_at': now(), 'head': revision(root),
                 'config_hash': config['config_hash'], 'suites': suites,
                 'execution_inputs': hashes(root, inputs), 'complete': all(s['complete'] for s in suites)})


def path_for(root, unit):
    return root / 'faultline' / 'catalog' / (digest(unit['id']) + '.json')


def load_record(root, unit):
    p = path_for(root, unit)
    try:
        row = read_json(p)
        if not isinstance(row, dict) or row.get('schema_version') != SCHEMA or row.get('id') != unit['id']:
            return None
        if not isinstance(row.get('description'), str) or not row['description'].strip():
            return None
        return row
    except FaultlineError:
        return None


def fresh(root, unit, record):
    if not record or record.get('reviewed') is not True or record.get('description_hash') != unit['description_hash']:
        return False
    contexts = record.get('context_hashes', {})
    try:
        return (isinstance(contexts, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in contexts.items())
                and hashes(root, contexts) == contexts)
    except FaultlineError:
        return False


def check(root, inventory):
    rows = []
    for suite in inventory['suites']:
        for u in suite['units']:
            record = load_record(root, u)
            rows.append({'id': u['id'], 'status': 'not_required' if u.get('kind') == 'check' else 'current' if fresh(root, u, record) else ('missing' if not record else 'stale_or_unreviewed')})
    return {'complete': inventory['complete'] and all(r['status'] in ('current', 'not_required') for r in rows), 'units': rows}


def sync(root, inventory, *, legacy=None):
    if not inventory['complete']:
        raise FaultlineError('Do not replace a catalog from incomplete discovery')
    old = {}
    if legacy:
        from ..index import load_profiles
        for p in load_profiles(legacy):
            old.setdefault(p['source'], []).append(p['description'])
    kept, drafted = 0, 0
    expected = set()
    for suite in inventory['suites']:
        for u in suite['units']:
            if u.get('kind') == 'check':
                continue
            path = path_for(root, u)
            expected.add(path)
            prior = load_record(root, u)
            if fresh(root, u, prior):
                kept += 1
                continue
            description = '\n'.join(old.get(u['source'], [])) or (prior or {}).get('description') or u['title']
            write_json(path, {'schema_version': SCHEMA, 'id': u['id'], 'source': u['source'],
                             'description': description, 'description_hash': u['description_hash'],
                             'context_hashes': (prior or {}).get('context_hashes', {}), 'reviewed': False,
                             'provenance': {'method': 'legacy-migration' if old else 'source-inventory-draft'}})
            drafted += 1
    removed = 0
    for path in (root / 'faultline/catalog').glob('*.json'):
        if path not in expected:
            path.unlink()
            removed += 1
    return {'preserved': kept, 'needs_review': drafted, 'removed': removed}


def import_records(root, inventory, input_path, reviewer):
    if not inventory['complete']:
        raise FaultlineError('Catalog review requires complete discovery')
    rows = read_json(input_path)
    if not isinstance(rows, list) or not reviewer.strip():
        raise FaultlineError('Catalog import needs an array and a reviewer')
    units = {u['id']: u for s in inventory['suites'] for u in s['units']}
    pending = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get('id') not in units or row['id'] in seen:
            raise FaultlineError('Unknown or duplicate native unit in catalog import')
        seen.add(row['id'])
        u = units[row['id']]
        if row.get('description_hash') != u['description_hash'] or not isinstance(row.get('description'), str) or not row['description'].strip():
            raise FaultlineError('Descriptions need the current discovered hash and nonempty evidence-based text')
        contexts = row.get('context_sources', [])
        if not isinstance(contexts, list) or not all(isinstance(p, str) and inside(root, p).is_file() for p in contexts):
            raise FaultlineError('Invalid description context sources')
        pending.append((path_for(root, u), {'schema_version': SCHEMA, 'id': u['id'], 'source': u['source'],
                        'description': row['description'], 'description_hash': u['description_hash'],
                        'context_hashes': hashes(root, contexts), 'reviewed': True,
                        'provenance': {'reviewer': reviewer, 'method': 'reviewed-source'}}))
    for path, value in pending:
        write_json(path, value)
    return {'reviewed': len(pending)}
