"""Review hypothetical file impact using positive paths in immutable snapshots."""
import posixpath
from collections import defaultdict, deque

from ..core import FaultlineError


def file_names(values):
    result = set()
    for value in values:
        if (not isinstance(value, str) or not value or '\\' in value or
                any(ord(c) < 32 for c in value) or value.startswith('/') or
                '..' in value.split('/') or (len(value) > 1 and value[1] == ':')):
            raise FaultlineError('Impact files must be literal repository-relative paths, without parent traversal')
        path = posixpath.normpath(value)
        if path == '.':
            raise FaultlineError('Specify a file, not the repository directory')
        result.add(path)
    if not result:
        raise FaultlineError('Specify at least one impact file')
    return sorted(result)


def routes(graph, dependency):
    """One deterministic shortest explanation per reachable consumer; cycles terminate."""
    reverse = defaultdict(list)
    for edge in sorted(graph['edges'], key=lambda e: (e['to'], e['from'], e['kind'], e['detail'])):
        reverse[edge['to']].append(edge)
    next_edge, pending = {dependency: None}, deque([dependency])
    while pending:
        node = pending.popleft()
        for edge in reverse.get(node, ()):
            consumer = edge['from']
            if consumer not in next_edge:
                next_edge[consumer] = edge
                pending.append(consumer)
    return next_edge


def affected(graph, files, *, base=None):
    files = file_names(files)
    if base and (base['repository'] != graph['repository'] or base['config'] != graph['config']):
        raise FaultlineError('Dependency snapshots need the same repository and configuration')
    snapshots = [('head', graph)] + ([('base', base)] if base else [])
    reasons, known = defaultdict(list), set()
    for label, snapshot in snapshots:
        for dependency in files:
            if dependency not in snapshot['nodes']:
                continue
            known.add(dependency)
            next_edge = routes(snapshot, dependency)
            for key, target in sorted(snapshot['targets'].items()):
                # Removed tests are reported separately, never proposed as executable targets.
                if key not in graph['targets'] or target['source'] not in next_edge:
                    continue
                node, path, edges = target['source'], [target['source']], []
                while next_edge[node] is not None:
                    edge = next_edge[node]
                    edges.append(edge)
                    node = edge['to']
                    path.append(node)
                reasons[key].append({'input': dependency, 'snapshot': label,
                                     'revision': snapshot['revision'], 'path': path, 'edges': edges})
    return {'schema_version': 1, 'kind': 'dependency-impact', 'repository': graph['repository'],
            'revision': graph['revision'], 'base_revision': base['revision'] if base else None,
            'files': files, 'unknown_files': sorted(set(files) - known),
            'affected': sorted(reasons), 'unresolved': sorted(graph['targets'].keys() - reasons.keys()),
            'removed_targets': sorted(base['targets'].keys() - graph['targets'].keys()) if base else [],
            'explanations': dict(sorted(reasons.items())),
            'inventory_complete': graph['inventory_complete'],
            'coverage_complete': False, 'execution': 'none', 'jev_requests': 0, 'omission_authorized': False,
            'limitations': ['Paths describe the requested Git snapshots, not uncommitted edits or future source contents.',
                            'Unknown files need a new snapshot; adding a file can create links from unchanged consumers.',
                            'Unresolved tests have no known path for these inputs; this does not establish independence.']}
