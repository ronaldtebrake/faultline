"""Faultline source/target records inside immutable CodeGraph SQLite artifacts.

CodeGraph owns symbols and relationships. These namespaced tables retain all Git
source identities, including languages the producer does not parse, and classify
configured file targets without pretending they are runtime test identities.
"""
import json
import sqlite3

from ..core import FaultlineError, digest
from .common import seal
from .evidence import GitSources
from .inventory import source_inventory

CONTRACT = 'faultline-source-index-v1'


def settings_hash(config):
    return digest({'contract': CONTRACT, 'suites': config['suites']})


def populate(database, root, config, rev):
    source = GitSources(root, rev)
    if len(source.files) > config['graph']['max_files']:
        raise FaultlineError('Source index exceeds the configured graph file budget')
    inventory = source_inventory(root, config, snapshot=source)
    with sqlite3.connect(database) as db:
        db.executescript("""DROP TABLE IF EXISTS faultline_sources;
        DROP TABLE IF EXISTS faultline_targets;
        DROP TABLE IF EXISTS faultline_index;
        CREATE TABLE faultline_sources(path TEXT PRIMARY KEY, mode TEXT NOT NULL, oid TEXT NOT NULL, size INTEGER NOT NULL);
        CREATE TABLE faultline_targets(id TEXT PRIMARY KEY, source TEXT NOT NULL, suite_key TEXT NOT NULL, evidence TEXT NOT NULL);
        CREATE INDEX faultline_targets_source ON faultline_targets(source);
        CREATE TABLE faultline_index(key TEXT PRIMARY KEY, value TEXT NOT NULL);""")
        db.executemany('INSERT INTO faultline_sources VALUES(?,?,?,?)',
                       [(p, v['mode'], v['oid'], v['size']) for p, v in sorted(source.files.items())])
        for suite in inventory['suites']:
            for unit in suite['units']:
                db.execute('INSERT INTO faultline_targets VALUES(?,?,?,?)',
                           (unit['id'], unit['source'], suite['key'], json.dumps(unit, sort_keys=True)))
        header = {**inventory, 'suites': [{**s, 'units': []} for s in inventory['suites']]}
        db.execute('INSERT INTO faultline_index VALUES(?,?)', ('inventory', json.dumps(header, sort_keys=True)))
        db.execute('INSERT INTO faultline_index VALUES(?,?)', ('contract', CONTRACT))
    return {'index_contract': CONTRACT, 'index_settings_hash': settings_hash(config),
            'source_count': len(source.files), 'target_count': sum(len(s['units']) for s in inventory['suites'])}


class GraphSources(GitSources):
    def __init__(self, root, config, artifact, rev):
        from .graph import connect, load
        path, manifest = load(artifact, expected_revision=rev, repository=config['repository'], config=config['graph'])
        if manifest.get('index_settings_hash') != settings_hash(config):
            raise FaultlineError('Graph test-source configuration mismatch; rebuild the revision index')
        self.root, self.revision = root, rev
        self.max_bytes, self.cache = config['evaluator']['max_test_bytes'], {}
        try:
            with connect(path / 'graph.sqlite') as db:
                if db.execute("SELECT value FROM faultline_index WHERE key='contract'").fetchone()[0] != CONTRACT:
                    raise FaultlineError('Unsupported graph source index')
                self.files = {row['path']: {k: row[k] for k in ('mode', 'oid', 'size')}
                              for row in db.execute('SELECT path,mode,oid,size FROM faultline_sources ORDER BY path')}
                header = json.loads(db.execute("SELECT value FROM faultline_index WHERE key='inventory'").fetchone()[0])
                if header.get('head') != rev:
                    raise FaultlineError('Graph source index revision mismatch')
                units = {}
                for row in db.execute('SELECT suite_key,evidence FROM faultline_targets ORDER BY id'):
                    units.setdefault(row['suite_key'], []).append(json.loads(row['evidence']))
                self.inventory = seal({**header, 'config_hash': config['config_hash'], 'basis': 'graph',
                                       'suites': [{**s, 'units': units.get(s['key'], [])} for s in header['suites']]})
        except (sqlite3.Error, ValueError, TypeError, KeyError, IndexError) as exc:
            raise FaultlineError('Missing or invalid graph source/target index') from exc
        self.provenance = {'basis': 'graph', 'artifact': str(path), 'integrity': manifest['integrity'],
                           'revision': rev, 'index_settings_hash': manifest['index_settings_hash'],
                           'source_count': len(self.files), 'target_count': sum(len(s['units']) for s in self.inventory['suites'])}


def open_index(store, config, rev, artifact=None):
    from .graph import artifact_path
    try:
        source = GraphSources(store.root, config, artifact or artifact_path(store, config, rev), rev)
        return source, source.inventory, source.provenance
    except (FaultlineError, OSError) as exc:
        # A damaged/unavailable graph must not prevent Jev from seeing test source.
        # This fallback is explicit and never replaces an immutable shared baseline.
        source = GitSources(store.root, rev, config['evaluator']['max_test_bytes'])
        inventory = source_inventory(store.root, config, snapshot=source)
        return source, inventory, {'basis': 'git_fallback', 'revision': rev, 'warning': str(exc)}


def enrich(root, config, inventory):
    from .config import variants
    from .runners import discover_suite
    by_key = {key: (suite, variant) for suite, variant, key in variants(config)}
    rows = []
    for row in inventory['suites']:
        suite, variant = by_key[row['key']]
        if row['kind'] == 'check':
            rows.append(row)
            continue
        native = discover_suite(root, suite, variant)
        by_source = {u['source']: u for u in native['units']}
        units = [{**u, **{k: v for k, v in by_source.get(u['source'], {}).items()
                          if k in ('members', 'locator', 'title', 'requires_full_suite')}} for u in row['units']]
        rows.append({**row, 'units': units, 'native_evidence': native, 'native_complete': native['complete']})
    return seal({**inventory, 'suites': rows, 'native_enrichment': True})
