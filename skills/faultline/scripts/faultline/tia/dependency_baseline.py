"""Carry positive CI observations through an unchanged dependency boundary.

An overlay keeps the original observation's revision and identity. It never
claims that a test ran at the destination or that unobserved paths are absent.
"""
import subprocess
from collections import defaultdict

from ..core import FaultlineError, digest


def require_ancestor(root, origin, destination):
    try:
        result = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', origin, destination],
                                capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise FaultlineError('Could not verify runtime baseline ancestry') from None
    if result.returncode:
        raise FaultlineError('Runtime baseline must be an available ancestor of the graph revision; fetch its history or collect a new baseline')


def overlay(item, origin, current, artifact_checks=None):
    from .dependency_graph import adjacency, closure
    before, after = adjacency(origin), adjacency(current)
    def edge_index(graph):
        result = defaultdict(set)
        for edge in graph['edges']:
            result[edge['from']].add(digest(edge))
        return result
    old_edges, new_edges = edge_index(origin), edge_index(current)
    boundaries = {}
    retained, invalidated = [], []
    for record in item['records']:
        target = item['suite'] + ':' + item['variant'] + ':' + record['test_source']
        roots = frozenset({record['test_source'], *record['files']})
        if roots not in boundaries:
            old_paths = set().union(*(closure(path, before) for path in roots))
            new_paths = set().union(*(closure(path, after) for path in roots))
            boundary = old_paths | new_paths
            changed = sorted(path for path in boundary
                             if origin['nodes'].get(path) != current['nodes'].get(path))
            # Resolve all source candidates again, including additions outside
            # the old graph. Compare only edges in this observation's boundary.
            rebound = old_paths != new_paths or any(old_edges[p] != new_edges[p] for p in boundary)
            boundaries[roots] = changed, rebound
        changed, rebound = boundaries[roots]
        provenance = {'baseline': item['integrity'], 'revision': item['revision'],
                      'record': digest(record), 'target': target,
                      'identity': record['test_identity'], 'retry': record['retry']}
        artifacts = record.get('generation', {}).get('artifacts')
        artifact_state = (artifact_checks or {}).get(digest(artifacts), 'unverified') if artifacts else 'verified'
        # An original historical observation remains evidence of what ran there.
        # Carrying it forward requires the destination's external inputs too.
        artifact_stale = artifact_state != 'verified' and not (
            artifact_state == 'historical' and origin['revision'] == current['revision'])
        if target not in current['targets'] or changed or rebound or artifact_stale:
            invalidated.append({**provenance, 'changed_inputs': changed,
                                'resolution_changed': rebound,
                                'artifact_state': artifact_state,
                                'target_removed': target not in current['targets']})
        else:
            retained.append({'record': record, 'provenance': provenance,
                             'freshness': 'observed' if origin['revision'] == current['revision'] else 'carried'})
    return retained, invalidated
