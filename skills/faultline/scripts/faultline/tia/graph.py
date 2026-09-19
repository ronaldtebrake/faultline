"""Pinned CodeGraph snapshots and conservative reverse dependency evidence.

CodeGraph owns parsing/resolution. This module reads its versioned SQLite contract;
it does not infer language relationships or use CodeGraph's test-name heuristics.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from collections import deque
from pathlib import Path

from ..core import FaultlineError, digest, now, read_json, write_json
from .common import checked, revision, seal

VERSION = '1.6.0'
CONTRACT = 'codegraph-sqlite-1.6-index-v2'
DEFAULTS = {'command': ['codegraph'], 'version': VERSION, 'timeout_seconds': 300,
            'max_files': 100000, 'max_source_bytes': 500000000,
            'max_edges': 2000000, 'max_depth': 16, 'max_visited': 50000,
            'context_paths': 6, 'extensions': {'.module': 'php', '.inc': 'php', '.install': 'php'}}
# Containment is not an execution dependency. All other producer relationship
# kinds remain positive evidence (including explicitly tagged heuristic edges).
CONTAINMENT = {'contains', 'defines'}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def run(argv, cwd, timeout):
    env = {**os.environ, 'CODEGRAPH_TELEMETRY': '0', 'DO_NOT_TRACK': '1', 'CODEGRAPH_NO_DAEMON': '1'}
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise FaultlineError('CodeGraph is unavailable or exceeded its time limit') from None
    if p.returncode:
        raise FaultlineError(f'CodeGraph command failed with exit {p.returncode}; no graph was published')
    return p.stdout.strip()


def connect(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA trusted_schema=OFF')
    return db


def inspect(path, limit):
    try:
        with connect(path) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise FaultlineError('CodeGraph SQLite integrity check failed')
            count = db.execute('SELECT count(*) FROM edges').fetchone()[0]
            if count > limit:
                raise FaultlineError('CodeGraph edge budget exceeded; widen the budget or run fully')
            files = {r['path']: {'language': r['language'], 'errors': r['errors'], 'nodes': r['node_count']}
                     for r in db.execute('SELECT path,language,errors,node_count FROM files')}
            # Validate columns at publication, even for an empty graph.
            db.execute('SELECT id,kind,name,file_path,start_line,end_line FROM nodes LIMIT 0')
            db.execute('SELECT source,target,kind,metadata,provenance FROM edges LIMIT 0')
            return files, count
    except sqlite3.Error:
        raise FaultlineError('Unsupported or damaged CodeGraph SQLite schema') from None


def load(path, *, expected_revision=None, config=None, repository=None):
    path = Path(path).resolve()
    manifest = checked(path / 'manifest.json', 'codegraph')
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', str(manifest.get('revision', ''))):
        raise FaultlineError('Graph revision must be an exact Git object ID')
    if (manifest.get('contract') != CONTRACT or manifest.get('producer_version') != VERSION
            or not (path / 'graph.sqlite').is_file() or sha(path / 'graph.sqlite') != manifest.get('database_sha256')):
        raise FaultlineError('CodeGraph artifact version or database hash mismatch')
    if expected_revision and manifest['revision'] != expected_revision:
        raise FaultlineError('CodeGraph artifact revision mismatch')
    if repository and manifest.get('repository') != repository:
        raise FaultlineError('CodeGraph artifact repository mismatch')
    if config and manifest.get('settings_hash') != settings_hash(config):
        raise FaultlineError('CodeGraph artifact configuration mismatch')
    return path, manifest


def settings_hash(config):
    # Executable location and query budgets do not affect the parsed graph.
    return digest({'version': config['version'], 'extensions': config['extensions'], 'contract': CONTRACT})


def artifact_path(store, config, rev):
    from .graph_index import settings_hash as index_settings_hash
    key = digest({'repository': config['repository'], 'revision': rev, 'settings': settings_hash(config['graph']),
                  'index': index_settings_hash(config)})
    return store.path / 'graphs' / key


def snapshot_size(root, rev, settings):
    """Check tracked regular-file sizes before exporting an expensive archive."""
    from .evidence import GitSources
    entries = GitSources(root, rev).files
    regular = [entry for entry in entries.values() if entry['mode'].startswith('100')]
    total = sum(entry['size'] for entry in regular)
    count = len(regular)
    if total > settings['max_source_bytes'] or count > settings['max_files']:
        raise FaultlineError(
            f"Graph snapshot needs {total:,} source bytes and {count:,} files; configured limits are "
            f"{settings['max_source_bytes']:,} bytes and {settings['max_files']:,} files. "
            "Review graph.max_source_bytes/max_files in faultline.json before retrying; no archive was exported.")
    return {'source_bytes': total, 'source_files': count}


def extract(root, rev, target, settings):
    snapshot_size(root, rev, settings)
    archive = target.parent / 'source.tar'
    with archive.open('wb') as out:
        p = subprocess.run(['git', '-C', str(root), 'archive', '--format=tar', rev], stdout=out, stderr=subprocess.PIPE)
    if p.returncode:
        raise FaultlineError('Could not export the exact Git revision')
    manifest, unsupported, total = {}, [], 0
    with tarfile.open(archive) as tar:
        for member in tar:
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts:
                raise FaultlineError('Unsafe path in Git snapshot')
            if member.isdir():
                continue
            if not member.isfile():
                unsupported.append(member.name)
                continue
            if path.parts[0] in ('.git', '.faultline', '.codegraph'):
                raise FaultlineError('Generated Faultline/CodeGraph state must not be committed')
            total += member.size
            if total > settings['max_source_bytes'] or len(manifest) >= settings['max_files']:
                raise FaultlineError(f"Extracted graph snapshot exceeds graph.max_source_bytes={settings['max_source_bytes']} or graph.max_files={settings['max_files']}")
            dest = target / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as inp, dest.open('wb') as out:
                shutil.copyfileobj(inp, out)
            dest.chmod(member.mode & 0o777)
            manifest[member.name] = sha(dest)
    # Git archive does not include submodule contents.
    tree = subprocess.run(['git', '-C', str(root), 'ls-tree', '-rz', rev], capture_output=True, check=True).stdout
    for entry in tree.split(b'\0'):
        if entry.startswith(b'160000 '):
            unsupported.append(entry.split(b'\t', 1)[1].decode())
    return manifest, sorted(set(unsupported))


def build(store, config, ref='HEAD', *, reuse=None, output=None, fresh=False):
    started = time.monotonic()
    rev = revision(store.root, ref)
    settings = config['graph']
    if fresh and reuse:
        raise FaultlineError('A fresh graph build cannot reuse another graph')
    default = artifact_path(store, config, rev)
    output = Path(output) if output else (default.with_name('fresh-' + default.name) if fresh else default)
    if output.exists():
        _, saved = load(output, expected_revision=rev, config=settings, repository=config['repository'])
        if fresh and saved.get('build_mode') != 'fresh':
            raise FaultlineError('The output contains an incremental graph; use a fresh output directory')
        from .graph_index import settings_hash as index_settings_hash
        if saved.get('index_settings_hash') != index_settings_hash(config):
            raise FaultlineError('Existing graph uses different test-source configuration; use a fresh output path')
        return {'path': str(output.resolve()), 'cache_hit': True, **saved}
    store.initialize()
    reuse = None if fresh else (Path(reuse) if reuse else find_baseline(store, config, rev))
    if run([*settings['command'], '--version'], store.root, 15).removeprefix('codegraph ').strip() != VERSION:
        raise FaultlineError(f'Faultline requires CodeGraph {VERSION}')
    with tempfile.TemporaryDirectory(prefix='faultline-graph-') as temporary:
        temp = Path(temporary)
        source = temp / 'source'
        source.mkdir()
        sources, unsupported = extract(store.root, rev, source, settings)
        upstream = read_json(source / 'codegraph.json', {})
        if not isinstance(upstream, dict) or not isinstance(upstream.get('extensions', {}), dict):
            raise FaultlineError('Invalid committed codegraph.json')
        upstream['extensions'] = {**upstream.get('extensions', {}), **settings['extensions']}
        write_json(source / 'codegraph.json', upstream)
        reused = None
        if reuse:
            prior, reused = load(reuse, config=settings, repository=config['repository'])
            # Extension/exclusion changes require a full rebuild; source changes can sync.
            if reused.get('upstream_config_hash') == digest(upstream):
                (source / '.codegraph').mkdir()
                shutil.copyfile(prior / 'graph.sqlite', source / '.codegraph/codegraph.db')
            else:
                reused = None
        run([*settings['command'], 'sync' if reused else 'init', str(source), *([] if reused else ['--yes'])], source, settings['timeout_seconds'])
        database = source / '.codegraph/codegraph.db'
        files, edge_count = inspect(database, settings['max_edges'])
        # Copy through SQLite backup, including any committed WAL, into a closed artifact.
        target = temp / 'artifact'
        target.mkdir()
        with connect(database) as original, sqlite3.connect(target / 'graph.sqlite') as dest:
            original.backup(dest)
        from .graph_index import populate
        index = populate(target / 'graph.sqlite', store.root, config, rev)
        value = seal({**index, 'schema_version': 2, 'kind': 'codegraph', 'created_at': now(),
                      'contract': CONTRACT, 'producer_version': VERSION, 'repository': config['repository'],
                      'revision': rev, 'settings_hash': settings_hash(settings), 'upstream_config_hash': digest(upstream),
                      'database_sha256': sha(target / 'graph.sqlite'), 'sources': sources, 'files': files,
                      'unsupported': unsupported, 'unindexed': sorted(set(sources) - set(files)),
                      'edge_count': edge_count, 'reused_from': reused['integrity'] if reused else None,
                      'build_mode': 'incremental' if reused else 'fresh',
                      'build_seconds': time.monotonic() - started})
        write_json(target / 'manifest.json', value)
        publish(target, output, config, rev)
        _, value = load(output, expected_revision=rev, config=settings, repository=config['repository'])
    return {'path': str(output.resolve()), 'cache_hit': False, **value}


def evidence(store, config, context, inventory, base_graph=None, head_graph=None):
    settings = config['graph']
    unit_sources = {u['source'] for s in inventory['suites'] for u in s['units'] if u.get('kind') != 'check'}
    result = {'snapshots': {}, 'paths': {p: [] for p in unit_sources}, 'dependencies': {},
              'unknown_changes': [], 'unmapped_tests': [], 'fallbacks': [], 'truncated': False}
    for side, explicit in [('base', base_graph), ('head', head_graph)]:
        try:
            path, manifest = load(explicit or artifact_path(store, config, context[side]),
                                  expected_revision=context[side], config=settings, repository=config['repository'])
            files, count = inspect(path / 'graph.sqlite', settings['max_edges'])
            if files != manifest['files']:
                raise FaultlineError('Graph manifest does not describe its database')
            result['snapshots'][side] = {k: manifest[k] for k in ('integrity', 'revision', 'database_sha256', 'producer_version')}
            result['snapshots'][side]['build_mode'] = manifest.get('build_mode', 'unknown')
            changed = set(context['changed_files']).intersection(manifest['sources']) | set(context['changed_files']).intersection(manifest['unsupported'])
            # Catalog prose affects inference but is not application code.
            changed = {p for p in changed if not p.startswith('faultline/catalog/')}
            gaps = {p for p in changed if p not in files or files[p]['errors'] not in (None, '', '[]') or not files[p]['nodes']}
            result['unknown_changes'].extend(sorted(gaps))
            if side == 'head':
                result['unmapped_tests'] = sorted(p for p in unit_sources if p not in files or not files[p]['nodes'] or files[p]['errors'] not in (None, '', '[]'))
            with connect(path / 'graph.sqlite') as db:
                adjacency, outgoing = {}, {}
                query = '''SELECT s.file_path AS caller, t.file_path AS callee,
                           s.name AS caller_symbol,t.name AS callee_symbol,e.kind,e.metadata,e.provenance
                           FROM edges e JOIN nodes s ON s.id=e.source JOIN nodes t ON t.id=e.target
                           WHERE s.file_path != t.file_path ORDER BY s.file_path,t.file_path,e.kind,s.id,t.id'''
                for row in db.execute(query):
                    if row['kind'] in CONTAINMENT:
                        continue
                    edge = dict(row)
                    edge['metadata'] = json.loads(edge['metadata']) if edge['metadata'] else {}
                    adjacency.setdefault(edge['callee'], []).append(edge)
                    if side == 'head' and edge['caller'] in unit_sources:
                        outgoing.setdefault(edge['caller'], []).append(edge)
                if side == 'head':
                    result['dependencies'] = {p: rows[:settings['context_paths']] for p, rows in outgoing.items()}
                # File-level seeding conservatively includes declarations/setup around changed symbols.
                queue = deque((p, []) for p in sorted(changed - gaps))
                visited = set(changed - gaps)
                while queue:
                    file, trail = queue.popleft()
                    if file in unit_sources:
                        result['paths'][file].append({'snapshot': side, 'changed_source': trail[-1]['callee'] if trail else file,
                                                      'edges': trail})
                    for edge in adjacency.get(file, []):
                        parent = edge['caller']
                        if parent in visited:
                            continue
                        if len(trail) >= settings['max_depth'] or len(visited) >= settings['max_visited']:
                            result['truncated'] = True
                            continue
                        visited.add(parent)
                        queue.append((parent, [edge, *trail]))
        except (FaultlineError, OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            result['fallbacks'].append('missing_invalid_or_incompatible_' + side + '_graph')
    result['unknown_changes'] = sorted(set(result['unknown_changes']))
    if result['unknown_changes']:
        result['fallbacks'].append('changed_files_without_usable_graph_evidence')
    if result['truncated']:
        result['fallbacks'].append('graph_traversal_budget_exhausted')
    return result


def publish(source, output, config, rev):
    """Atomic create: a concurrent valid publisher wins; never mutate its snapshot."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix='.graph-', dir=output.parent))
    try:
        for name in ('graph.sqlite', 'manifest.json'):
            shutil.copyfile(Path(source) / name, staged / name)
        try:
            staged.rename(output)
        except OSError:
            if not output.exists():
                raise
            _, saved = load(output, expected_revision=rev, config=config['graph'], repository=config['repository'])
            incoming = checked(staged / 'manifest.json', 'codegraph')
            if saved.get('index_settings_hash') != incoming.get('index_settings_hash'):
                raise FaultlineError('Concurrent artifact uses incompatible index settings') from None
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def find_baseline(store, config, rev):
    """Choose the nearest compatible ancestor; branch names never identify artifacts."""
    candidates = []
    for path in sorted((store.path / 'graphs').glob('*/manifest.json')):
        if path.parent.name.startswith('.'):
            continue  # Unpublished staging directories are never reusable baselines.
        try:
            value = checked(path, 'codegraph')
            if (value.get('contract') != CONTRACT or value.get('repository') != config['repository']
                    or value.get('settings_hash') != settings_hash(config['graph'])):
                continue
            prior = value['revision']
            if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', str(prior)):
                continue
            ancestor = subprocess.run(['git', '-C', str(store.root), 'merge-base', '--is-ancestor', prior, rev], capture_output=True)
            if ancestor.returncode:
                continue
            distance = subprocess.run(['git', '-C', str(store.root), 'rev-list', '--count', prior + '..' + rev], capture_output=True, text=True)
            if distance.returncode == 0:
                candidates.append((int(distance.stdout), str(path.parent)))
        except (FaultlineError, OSError, KeyError, ValueError):
            continue
    for _, candidate in sorted(candidates):
        try:
            load(candidate, config=config['graph'], repository=config['repository'])
            return Path(candidate)
        except (FaultlineError, OSError):
            continue
    return None


def transfer(store, config, artifact, *, output=None):
    """Import/export a trusted artifact directory, without indexing or network calls."""
    path, manifest = load(artifact, config=config['graph'], repository=config['repository'])
    from .evidence import GitSources
    from .graph_index import CONTRACT as INDEX_CONTRACT
    if manifest.get('index_contract') != INDEX_CONTRACT:
        raise FaultlineError('Artifact has no supported source index; rebuild it before sharing')
    rev = revision(store.root, manifest['revision'])
    expected = GitSources(store.root, rev).files
    try:
        with connect(path / 'graph.sqlite') as db:
            actual = {row['path']: {k: row[k] for k in ('mode', 'oid', 'size')}
                      for row in db.execute('SELECT path,mode,oid,size FROM faultline_sources')}
        if actual != expected:
            raise FaultlineError('Artifact source identities do not match the local Git revision')
    except sqlite3.Error as exc:
        raise FaultlineError('Invalid source index in shared artifact') from exc
    # Preserve the imported target configuration identity. It may differ from the
    # branch configuration and still seed a freshly classified branch snapshot.
    key = digest({'repository': config['repository'], 'revision': rev, 'settings': settings_hash(config['graph']),
                  'index': manifest['index_settings_hash']})
    destination = Path(output) if output else store.path / 'graphs' / key
    publish(path, destination, config, rev)
    _, saved = load(destination)
    return {'path': str(destination.resolve()), **saved}
