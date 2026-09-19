"""Source-target projection shared by graph publication and explicit native enrichment."""
from ..core import digest, now
from .common import glob_files, hashes, revision, seal
from .config import SCHEMA, variants
from .runners import discover_suite


def source_inventory(root, config, *, native=False, snapshot=None):
    """Enumerate configured source targets without loading the application.

    complete describes enumeration of configured paths, never native completeness.
    Optional native evidence enriches matching files without narrowing the universe.
    """
    suites, files_cache, hashes_cache = [], {}, {}
    for suite, variant, key in variants(config):
        patterns = tuple(suite['sources'])
        if patterns not in files_cache:
            files_cache[patterns] = snapshot.glob(patterns) if snapshot else glob_files(root, patterns)
        sources = files_cache[patterns]
        whole = suite['kind'] == 'check'
        if whole:
            sources = ['faultline.json']
        units = []
        for source in sources:
            identity = (source, tuple(suite['description_inputs']))
            if identity not in hashes_cache:
                paths = [source, *(snapshot.glob(suite['description_inputs']) if snapshot else glob_files(root, suite['description_inputs']))]
                hashes_cache[identity] = snapshot.hashes(paths) if snapshot else hashes(root, paths)
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
    shared_patterns = [p for s in config['suites'] for p in s['shared_inputs']]
    inputs = ['faultline.json', *(snapshot.glob(shared_patterns) if snapshot else glob_files(root, shared_patterns))]
    return seal({'schema_version': SCHEMA, 'kind': 'inventory', 'basis': 'source',
                 'native_enrichment': native, 'created_at': now(), 'head': snapshot.revision if snapshot else revision(root),
                 'config_hash': config['config_hash'], 'suites': suites,
                 'execution_inputs': snapshot.hashes(inputs) if snapshot else hashes(root, inputs), 'complete': all(s['complete'] for s in suites)})

