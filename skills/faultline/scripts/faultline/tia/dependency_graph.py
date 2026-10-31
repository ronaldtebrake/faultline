"""Versioned dependency snapshots and incremental, source-only impact queries.

The source graph supplies positive paths and explicitly unresolved targets. It
does not turn a missing static edge into an omission decision. Semantic and
runtime evidence can build on the same immutable node and target identities.
"""
from collections import defaultdict, deque
from pathlib import Path

from ..core import FaultlineError, digest
from .common import checked, revision, save_frozen, seal
from .config import load_config, variants
from .ci_manifest import fingerprint
from .evidence import GitSources
from .inventory import source_inventory
from . import dependency_sources as adapters

VERSION = 'dependency-graph-v8'


def closure(start, adjacency):
    seen, pending = set(), deque([start])
    while pending:
        node = pending.popleft()
        if node in seen:
            continue
        seen.add(node)
        pending.extend(adjacency.get(node, ()))
    return seen


def adjacency(graph, reverse=False):
    result = defaultdict(set)
    for edge in graph['edges']:
        left, right = (edge['to'], edge['from']) if reverse else (edge['from'], edge['to'])
        result[left].add(right)
    return result


def read(path):
    value = checked(path, 'dependency-graph')
    if value.get('version') != VERSION or value.get('adapter') != adapters.VERSION:
        raise FaultlineError('Dependency graph version changed; rebuild the snapshot')
    if not isinstance(value.get('nodes'), dict) or not isinstance(value.get('targets'), dict) or not isinstance(value.get('edges'), list):
        raise FaultlineError('Malformed dependency graph')
    for edge in value['edges']:
        if not isinstance(edge, dict) or edge.get('from') not in value['nodes'] or edge.get('to') not in value['nodes']:
            raise FaultlineError('Dependency edge refers to a missing node')
    for target in value['targets'].values():
        if not isinstance(target, dict) or target.get('source') not in value['nodes']:
            raise FaultlineError('Dependency target refers to a missing source')
    return value


def build(store, ref='HEAD', *, output=None, runtime_paths=()):
    store.initialize()
    config = load_config(store.root)
    commit = revision(store.root, ref)
    source = GitSources(store.root, commit, config['evaluator']['max_test_bytes'])
    runtime = [checked(path, 'dependency-runtime') for path in runtime_paths]
    runtime = sorted({item['integrity']: item for item in runtime}.values(), key=lambda item: item['integrity'])
    from .dependency_baseline import require_ancestor, overlay
    for item in runtime:
        if (item.get('version') != 1 or item['config'] != fingerprint(config) or
                item['repository'] != config['repository']):
            raise FaultlineError('Runtime dependencies must match the graph repository and configuration')
        require_ancestor(store.root, item['revision'], commit)
    # Unlike Git blobs, downloaded release catalogs can change at the same
    # revision. Recheck them before consulting the immutable snapshot cache.
    from .playwright_sources import validate_artifacts
    artifact_checks = {}
    checkout_revision = revision(store.root)
    for item in runtime:
        for record in item['records']:
            artifacts = record.get('generation', {}).get('artifacts')
            if not artifacts or digest(artifacts) in artifact_checks:
                continue
            state = 'historical'
            if checkout_revision == commit:
                try:
                    validate_artifacts(artifacts, store.root, source.files)
                    state = 'verified'
                except FaultlineError:
                    state = 'missing_or_changed'
            artifact_checks[digest(artifacts)] = state
    identity = digest({'version': VERSION, 'adapter': adapters.VERSION, 'repository': config['repository'],
                       'revision': commit, 'config': fingerprint(config),
                       'limits': {key: config['evaluator'][key] for key in ('max_test_bytes', 'max_evidence_pairs')},
                       'runtime': sorted(d['integrity'] for d in runtime), 'artifacts': artifact_checks})
    destination = store.path / 'dependency-graph' / 'snapshots' / (identity + '.json')
    if destination.exists():
        value = read(destination)
        if output:
            save_frozen(output, value)
        return {'path': str(output or destination), 'graph': value, 'parsed': 0,
                'reused': sum(node['language'] != 'data' for node in value['nodes'].values()),
                'snapshot_reused': True, 'jev_requests': 0}
    facts, nodes, parsed, reused = {}, {}, 0, 0
    cache = store.path / 'dependency-graph' / 'source-cache'
    code = [p for p in source.files if adapters.language(p) != 'data']
    # No silent truncation: an oversized repository remains explicitly unsupported.
    if len(code) > config['evaluator']['max_evidence_pairs']:
        raise FaultlineError('Dependency graph exceeds max_evidence_pairs source files')
    def source_key(path):
        entry = source.files[path]
        return digest({'adapter': adapters.VERSION, 'language': adapters.language(path),
                       'oid': entry['oid'], 'mode': entry['mode']})
    source.prefetch([path for path in code if not (cache / (source_key(path) + '.json')).exists()])
    pending, aliases = [], {}

    def remember(path, fact):
        facts[path] = fact
        nodes[path]['gaps'] = list(fact['gaps'])
        nodes[path]['bindings'] = digest({key: value for key, value in fact.items() if key not in ('language', 'gaps')})

    for path, entry in sorted(source.files.items()):
        node = {'oid': entry['oid'], 'mode': entry['mode'], 'language': adapters.language(path), 'gaps': [], 'bindings': None}
        nodes[path] = node
        if node['language'] == 'data':
            continue
        # These gaps are properties of this immutable tree and declared limit,
        # not transient I/O errors. They must not disable whole-snapshot reuse.
        gap = ('non_regular_dependency_source' if not entry['mode'].startswith('100') else
               'source_exceeds_max_test_bytes' if entry['size'] > source.max_bytes else None)
        if gap:
            remember(path, {'language': node['language'], 'gaps': [gap]})
            continue
        key = source_key(path)
        cached = cache / (key + '.json')
        try:
            saved = checked(cached, 'dependency-source') if cached.exists() else None
            if saved and saved.get('key') != key:
                raise FaultlineError('Dependency source cache identity mismatch')
            if saved:
                fact = saved['facts']
                reused += 1
            else:
                if key not in aliases:
                    pending.append((path, source.read(path)))
                    aliases[key] = []
                aliases[key].append(path)
                continue
        except (FaultlineError, KeyError, TypeError, OSError) as exc:
            fact = {'language': node['language'], 'gaps': ['unreadable_dependency_source:' + str(exc)]}
        remember(path, fact)
    for path, fact in adapters.parse_many(pending):
        parsed += 1
        key = source_key(path)
        try:
            # A temporary missing interpreter must not poison future builds.
            if not set(fact['gaps']) & {'php_tokenizer_unavailable', 'php_tokenization_failed'}:
                save_frozen(cache / (key + '.json'), {'schema_version': 2, 'kind': 'dependency-source', 'key': key, 'facts': fact})
        except (FaultlineError, OSError) as exc:
            fact = {'language': adapters.language(path), 'gaps': ['unreadable_dependency_source:' + str(exc)]}
        for duplicate in aliases[key]:
            remember(duplicate, fact)
        reused += len(aliases[key]) - 1
    edges = {}

    def link(consumer, dependency, kind, detail=''):
        if consumer == dependency:
            return
        item = {'from': consumer, 'to': dependency, 'kind': kind, 'detail': detail}
        edges[digest(item)] = item

    classes, definitions = defaultdict(set), []
    for path, fact in sorted(facts.items()):
        for name in fact.get('classes', []):
            classes[name.lower()].add(path)
        definitions.extend({'source': path, **d} for d in fact.get('definitions', []))
    files = set(source.files)
    # A repeated Gherkin phrase has the same candidate definitions everywhere.
    # Reuse matching within this tree and amortize interpreter startup across
    # features. Resolve again on the next tree, including newly added patterns.
    step_texts = sorted({step['text'] for fact in facts.values() for step in fact.get('steps', [])})
    step_matches = {}
    for offset in range(0, len(step_texts), 256):
        batch = step_texts[offset:offset + 256]
        step_matches.update(zip(batch, adapters.match_steps(batch, definitions)))
    for path, fact in facts.items():
        for specifier in fact.get('imports', []):
            resolved, gap = adapters.resolve_import(path, specifier, files)
            for dependency in resolved:
                link(path, dependency, 'module_import', specifier)
            if gap:
                nodes[path]['gaps'].append(gap)
        for name in fact.get('references', []):
            found = classes.get(name.lower(), set())
            for dependency in found:
                link(path, dependency, 'php_class_reference', name)
            if len(found) > 1:
                nodes[path]['gaps'].append('ambiguous_class:' + name)
        steps = fact.get('steps', [])
        for step in steps:
            matches = step_matches[step['text']]
            if isinstance(matches, list):  # No definitions were available.
                matches = {'matches': matches, 'unresolved_patterns': False}
            if matches is None:
                nodes[path]['gaps'].append('step_matcher_unavailable')
                continue
            found = matches['matches']
            if len(found) != 1 or matches['unresolved_patterns'] or '<' in step['text']:
                nodes[path]['gaps'].append('unresolved_step:' + str(step['line']))
            for index in found:
                definition = definitions[index]
                link(path, definition['source'], 'behat_step', definition['symbol'] + ':' + str(step['line']))
    inventory = source_inventory(store.root, config, snapshot=source)
    targets = {}
    suites = {key: suite for suite, _, key in variants(config)}
    for row in inventory['suites']:
        suite = suites[row['key']]
        for unit in row['units']:
            if unit['source'] not in nodes:
                raise FaultlineError('Configured target has no tracked source in this snapshot')
            targets[unit['id']] = {'source': unit['source'], 'suite': row['suite'], 'variant': row['variant'],
                                   'runner': row['runner'], 'kind': unit['kind']}
            for dependency in source.glob(['faultline.json', *suite['description_inputs'], *suite['shared_inputs']]):
                link(unit['source'], dependency, 'configured_setup')
    for node in nodes.values():
        node['gaps'] = sorted(set(node['gaps']))
    observations = defaultdict(list)
    invalidated, origins = [], {}
    source_graph = {'revision': commit, 'nodes': nodes, 'edges': list(edges.values()), 'targets': targets}
    for item in runtime:
        if item['revision'] not in origins:
            if item['revision'] == commit:
                origins[item['revision']] = source_graph
            else:
                built = build(store, item['revision'])
                origins[item['revision']] = built['graph']
                parsed += built['parsed']
                reused += built['reused']
        origin = origins[item['revision']]
        # Validate observations against their original tree before carrying them.
        for record in item['records']:
            key = item['suite'] + ':' + item['variant'] + ':' + record['test_source']
            if key not in origin['targets'] or any(path not in origin['nodes'] for path in record['files']):
                raise FaultlineError('Runtime observation is outside its original graph inventory')
        retained, stale = overlay(item, origin, source_graph, artifact_checks)
        invalidated.extend(stale)
        for observation in retained:
            record = observation['record']
            key = observation['provenance']['target']
            for dependency in record['files']:
                link(record['test_source'], dependency, 'runtime_observation', record['producer'])
            observations[key].append({'identity': record['test_identity'], 'status': record['status'],
                                      'files': record['files'],
                                      'resources': record['resources'], 'gaps': record['gaps'],
                                      'callables': record.get('callables', []),
                                      'source_hashes': record.get('source_hashes', {}),
                                      'generation': record.get('generation'),
                                      'retry': record['retry'], 'provenance': observation['provenance'],
                                      'freshness': observation['freshness']})
    value = seal({'schema_version': 2, 'kind': 'dependency-graph', 'version': VERSION, 'adapter': adapters.VERSION,
                  'repository': config['repository'], 'revision': commit, 'config': fingerprint(config),
                  'nodes': nodes, 'edges': sorted(edges.values(), key=lambda e: (e['from'], e['to'], e['kind'], e['detail'])),
                  'targets': targets, 'inventory_complete': inventory['complete'],
                  'runtime': sorted(d['integrity'] for d in runtime), 'observations': dict(observations),
                  'artifact_checks': artifact_checks,
                  'runtime_reuse': {'observed': sum(o['freshness'] == 'observed' for rows in observations.values() for o in rows),
                                   'carried': sum(o['freshness'] == 'carried' for rows in observations.values() for o in rows),
                                   'invalidated': invalidated},
                  'limitations': ['Static links are positive evidence only. Missing links cannot authorize omission.',
                                  'Behat context activation, hooks and transforms require native or semantic evidence.',
                                  'Browser and remote-server behavior is not described by JavaScript imports.']})
    # A dependency gap can disappear when tools become available. Keep that build
    # as immutable evidence without publishing it under the complete snapshot key.
    transient = any(any('unavailable' in gap or 'unreadable_dependency_source' in gap or 'tokenization_failed' in gap
                        for gap in node['gaps']) for node in nodes.values())
    if transient:
        destination = destination.with_name(identity + '-' + value['integrity'] + '.json')
    save_frozen(destination, value)
    if output:
        save_frozen(output, value)
    return {'path': str(output or destination), 'graph': value, 'parsed': parsed, 'reused': reused,
            'snapshot_reused': False, 'jev_requests': 0}


def compare(base, head):
    if base['repository'] != head['repository'] or base['config'] != head['config']:
        raise FaultlineError('Dependency snapshots need the same repository and configuration')
    changed = sorted(p for p in base['nodes'].keys() | head['nodes'].keys()
                     if {k: base['nodes'].get(p, {}).get(k) for k in ('oid', 'mode')} !=
                        {k: head['nodes'].get(p, {}).get(k) for k in ('oid', 'mode')})
    before, after = adjacency(base), adjacency(head)
    affected, unresolved, paths = [], [], {}
    for key, target in head['targets'].items():
        reachable = closure(target['source'], after)
        if key in base['targets']:
            reachable |= closure(base['targets'][key]['source'], before)
        touched = sorted(reachable & set(changed))
        if touched or key not in base['targets']:
            affected.append(key)
            paths[key] = touched or [target['source']]
        else:
            unresolved.append(key)
    old_edges = {digest(e) for e in base['edges']}
    new_edges = {digest(e) for e in head['edges']}
    return {'base': base['revision'], 'head': head['revision'], 'changed_files': changed,
            'affected': sorted(affected), 'unresolved': sorted(unresolved), 'affected_inputs': paths,
            'added_edges': len(new_edges - old_edges), 'removed_edges': len(old_edges - new_edges),
            'runtime_reuse': {'base': base['runtime_reuse'], 'head': head['runtime_reuse']},
            'execution': 'none', 'jev_requests': 0,
            'omission_authorized': False,
            'next': 'Retain affected tests; resolve remaining tests with semantic or complete dependency evidence.'}
