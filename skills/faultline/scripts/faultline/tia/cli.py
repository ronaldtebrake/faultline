"""Shared catalog and native evidence commands; no inference or test selection."""
from pathlib import Path

from ..core import FaultlineError
from . import catalog
from .common import revision, save_frozen
from .config import load_config
from .mapping import phpunit_xml


COMMANDS = {'discover', 'catalog', 'mapping'}


def add_commands(commands):
    discovery = commands.add_parser('discover', help='Discover native execution units; save an inventory')
    discovery.add_argument('--output', type=Path)
    shared = commands.add_parser('catalog', help='Maintain Git-shared test descriptions using fresh native discovery')
    actions = shared.add_subparsers(dest='catalog_action', required=True)
    actions.add_parser('check', help='Check reviewed descriptions against current sources and inventory')
    actions.add_parser('show', help='Show native identities, descriptions, and freshness')
    sync = actions.add_parser('sync', help='Draft new/changed descriptions and remove absent units')
    sync.add_argument('--legacy', type=Path, help='Migrate descriptions from a local index.jsonl; review is required')
    review = actions.add_parser('import', help='Import reviewed descriptions for discovered units')
    review.add_argument('--input', type=Path, required=True)
    review.add_argument('--reviewer', required=True)
    mapping = commands.add_parser('mapping', help='Import relationships produced by existing coverage tools')
    imports = mapping.add_subparsers(dest='mapping_action', required=True)
    phpunit = imports.add_parser('import-phpunit', help='Import test-attributed PHPUnit XML coverage, not Clover/JUnit')
    phpunit.add_argument('--input', type=Path, required=True, help='Directory containing index.xml')
    phpunit.add_argument('--source-prefix', required=True, help='Repository path corresponding to the coverage source root')
    phpunit.add_argument('--revision', required=True, help='Exact revision tested by the coverage producer')
    phpunit.add_argument('--suite', required=True)
    phpunit.add_argument('--variant', default='default')
    phpunit.add_argument('--output', type=Path)


def dispatch(store, args):
    if args.command == 'mapping':
        document = phpunit_xml(args.input, source_prefix=args.source_prefix,
                              revision=revision(store.root, args.revision), suite=args.suite, variant=args.variant)
        store.initialize()
        output = args.output or store.path / 'relationships' / (document['integrity'] + '.json')
        save_frozen(output, document)
        return {'output': str(output.resolve()), 'revision': document['revision'],
                'tests': len(document['tests']), 'files': len(document['files']),
                'relationships': len(document['edges']), 'limitations': document['limitations']}
    config = load_config(store.root)
    inventory = catalog.discover(store.root, config)
    if args.command == 'discover':
        store.initialize()
        output = args.output or store.path / 'inventories' / (inventory['integrity'] + '.json')
        save_frozen(output, inventory)
        return {'output': str(output.resolve()), **inventory}
    if args.catalog_action == 'check':
        return {**catalog.check(store.root, inventory), 'discovery': inventory['suites']}
    if args.catalog_action == 'show':
        return {'complete': inventory['complete'], 'suites': inventory['suites'],
                'records': [catalog.load_record(store.root, u) for s in inventory['suites'] for u in s['units']],
                'freshness': catalog.check(store.root, inventory)['units']}
    if not inventory['complete']:
        raise FaultlineError('Discovery incomplete; catalog was not changed. Inspect `faultline discover`.')
    if args.catalog_action == 'sync':
        return catalog.sync(store.root, inventory, legacy=args.legacy)
    return catalog.import_records(store.root, inventory, args.input, args.reviewer)
