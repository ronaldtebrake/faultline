"""Report-only shadow analysis, optional native evidence, and explicit execution commands."""
from pathlib import Path

from ..core import FaultlineError
from . import catalog
from .common import revision, save_frozen
from .config import load_config
from .mapping import phpunit_xml


COMMANDS = {'discover', 'catalog', 'mapping', 'graph', 'select', 'run', 'record', 'shadow-report', 'execution-report'}


def add_commands(commands):
    graph = commands.add_parser('graph', help='Build or inspect immutable CodeGraph revision artifacts')
    actions = graph.add_subparsers(dest='graph_action', required=True)
    build = actions.add_parser('build', help='Index an exact Git revision; reuse a compatible artifact incrementally')
    build.add_argument('--revision', default='HEAD')
    build.add_argument('--reuse', type=Path)
    build.add_argument('--output', type=Path)
    for action in ('import', 'export'):
        transfer = actions.add_parser(action, help='Copy a trusted immutable graph baseline between checkouts/artifact storage')
        transfer.add_argument('artifact', type=Path)
        if action == 'export':
            transfer.add_argument('--output', type=Path, required=True)
    inspect = actions.add_parser('inspect')
    inspect.add_argument('artifact', type=Path)
    select = commands.add_parser('select', help='Save a CodeGraph + Jev would-run report without executing tests')
    select.add_argument('--base', required=True, help='Actual PR/MR diff base; use a merge-base if required by your host')
    select.add_argument('--head', default='HEAD')
    select.add_argument('--id', help='PR/MR identifier for reports, excluded from inference inputs')
    select.add_argument('--baseline', type=Path, help='Optional reusable graph artifact; never changes the actual PR diff base')
    select.add_argument('--base-graph', type=Path)
    select.add_argument('--head-graph', type=Path)
    select.add_argument('--no-build', action='store_true', help='Use restored artifacts only; missing indexes use an explicit Git source fallback')
    select.add_argument('--max-requests', type=int, help='Per-invocation Jev request cap including retries; does not edit configuration')
    select.add_argument('--selection-seconds', type=float, help='Per-invocation inference time limit')
    select.add_argument('--prepare', action='store_true', help='Build/reuse graphs and estimate Jev work without contacting Jev')
    select.add_argument('--dry-run', action='store_true', help='Inspect cached evidence and request estimates; no indexing or API calls')
    select.add_argument('--native', action='store_true', help='Opt into runner discovery in a prepared application environment')
    select.add_argument('--output', type=Path)
    run = commands.add_parser('run', help='Preview a frozen proposal; --execute opts into full-suite execution')
    run.add_argument('--execute', action='store_true', help='Explicitly validate and execute the full suite instead of reporting only')
    run.add_argument('--selection', type=Path, required=True)
    run.add_argument('--suite', required=True, help='suite:variant, or an unambiguous suite ID')
    run.add_argument('--prerequisite', action='append', default=[], type=Path, help='Successful prerequisite execution receipt')
    run.add_argument('--output', type=Path)
    run.add_argument('--junit-output', type=Path, help='Fresh JUnit path: file for PHPUnit, directory for Behat')
    record = commands.add_parser('record', help='Import exact outcomes and immediately save a shadow report')
    record.add_argument('--selection', type=Path, required=True)
    record.add_argument('--run', type=Path, required=True)
    record.add_argument('--input', type=Path)
    record.add_argument('--format', choices=['json', 'junit'])
    record.add_argument('--output', type=Path, help='Report basename (writes .json and .md)')
    shadow = commands.add_parser('shadow-report', help='Show saved would-run proposals without running tests')
    shadow.add_argument('--selection', type=Path, help='Regenerate one proposal; omit to aggregate saved PR/MR snapshots')
    commands.add_parser('execution-report', help='Aggregate outcomes from explicitly executed full-suite evaluations')
    discovery = commands.add_parser('discover', help='Query test targets from the current graph index without invoking runners')
    discovery.add_argument('--revision', default='HEAD')
    discovery.add_argument('--output', type=Path)
    discovery.add_argument('--native', action='store_true', help='Enrich source targets with native runner identities')
    shared = commands.add_parser('catalog', help='Legacy description maintenance; not used by graph indexing or select')
    actions = shared.add_subparsers(dest='catalog_action', required=True)
    actions.add_parser('check', help='Check reviewed descriptions against current sources and inventory')
    actions.add_parser('show', help='Show provisional source identities, descriptions, and freshness')
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
    # With --root, relative data paths belong to the analyzed checkout, including
    # when an installed skill is launched from an IDE's unrelated directory.
    for name in ('output', 'input', 'artifact', 'reuse', 'base_graph', 'head_graph', 'selection', 'run', 'junit_output', 'legacy', 'baseline'):
        value = getattr(args, name, None)
        if value is not None:
            setattr(args, name, (store.root / value).resolve())
    if hasattr(args, 'prerequisite'):
        args.prerequisite = [(store.root / p).resolve() for p in args.prerequisite]
    if args.command == 'graph':
        from . import graph
        if args.graph_action == 'inspect':
            path, value = graph.load(args.artifact)
            return {'path': str(path), **value}
        if args.graph_action in ('import', 'export'):
            return graph.transfer(store, load_config(store.root), args.artifact, output=getattr(args, 'output', None))
        return graph.build(store, load_config(store.root), args.revision, reuse=args.reuse, output=args.output)
    if args.command == 'select':
        from .selection import select
        return select(store, args.base, args.head, identifier=args.id, output=args.output, dry_run=args.dry_run,
                      base_graph=args.base_graph, head_graph=args.head_graph, build_graphs=not args.no_build, native=args.native, baseline=args.baseline, max_requests=args.max_requests, selection_seconds=args.selection_seconds, prepare=args.prepare)
    if args.command == 'run':
        from .execution import run_suite
        return run_suite(store, args.selection, args.suite, prerequisites=args.prerequisite, output=args.output, junit_output=args.junit_output, execute=args.execute)
    if args.command == 'record':
        from .results import record
        return record(store, args.selection, args.run, args.input, format=args.format, output=args.output)
    if args.command == 'shadow-report':
        from .proposals import aggregate, report_selection
        from .common import checked
        return report_selection(store, checked(args.selection, 'selection')) if args.selection else aggregate(store)
    if args.command == 'execution-report':
        from .results import report
        return report(store)
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
    if args.command == 'discover':
        from . import graph
        from .graph_index import open_index, enrich
        rev = revision(store.root, args.revision)
        source, inventory, provenance = open_index(store, config, rev)
        if args.native:
            from .selection import workspace
            if revision(store.root) != rev or not workspace(store.root)['clean']:
                raise FaultlineError('Native enrichment requires a clean checkout of the requested revision')
            inventory = enrich(store.root, config, inventory)
        store.initialize()
        output = args.output or store.path / 'inventories' / (inventory['integrity'] + '.json')
        save_frozen(output, inventory)
        return {'output': str(output.resolve()), **inventory, 'index': provenance}
    inventory = catalog.source_inventory(store.root, config)
    if args.catalog_action == 'check':
        return {**catalog.check(store.root, inventory), 'discovery': inventory['suites']}
    if args.catalog_action == 'show':
        return {'complete': inventory['complete'], 'suites': inventory['suites'],
                'records': [catalog.load_record(store.root, u) for s in inventory['suites'] for u in s['units']],
                'freshness': catalog.check(store.root, inventory)['units']}
    if args.catalog_action == 'sync':
        return catalog.sync(store.root, inventory, legacy=args.legacy)
    return catalog.import_records(store.root, inventory, args.input, args.reviewer)
