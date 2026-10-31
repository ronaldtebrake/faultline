"""Dependency graph inspection without inference or application execution."""
from pathlib import Path


def add_commands(commands):
    graph = commands.add_parser('graph', help='Maintain reusable test dependency evidence')
    actions = graph.add_subparsers(dest='graph_action', required=True)
    build = actions.add_parser('build', help='Index immutable source and resolve test dependencies; no application or Jev calls')
    build.add_argument('--revision', default='HEAD')
    build.add_argument('--output', type=Path)
    build.add_argument('--runtime', action='append', default=[], type=Path, help='Validated runtime dependencies from this revision or an available ancestor')
    build.add_argument('--catalog', help='Inspect a tracked application-surface catalog without inference')
    compare = actions.add_parser('compare', help='Compare dependency snapshots, including old and newly introduced paths')
    compare.add_argument('--base', required=True)
    compare.add_argument('--head', default='HEAD')
    compare.add_argument('--runtime', action='append', default=[], type=Path, help='Validated runtime dependencies from the base or an available ancestor')
    compare.add_argument('--catalog', help='Show affected surfaces and uncovered changes without inference')
    context = actions.add_parser('context', help='Bind a runtime collector to a clean revision and configured suite variant')
    context.add_argument('--suite', required=True)
    context.add_argument('--output', required=True, type=Path)
    context.add_argument('--mount', action='append', default=[], help='Behat container directory mapping: /app=repository/subdirectory or /workspace=.')
    ingest = actions.add_parser('import', help='Validate test-attributed observations from an existing CI run')
    ingest.add_argument('--context', required=True, type=Path)
    ingest.add_argument('--input', required=True, action='append', type=Path)
    ingest.add_argument('--output', type=Path)
    baseline = actions.add_parser('baseline', help='Share CI dependency evidence while retaining full test execution')
    operations = baseline.add_subparsers(dest='baseline_action', required=True)
    pack = operations.add_parser('pack', help='Package fresh CI observations and immutable parser facts')
    pack.add_argument('--producer', required=True, type=Path)
    pack.add_argument('--runtime', action='append', default=[], type=Path)
    pack.add_argument('--output', required=True, type=Path)
    restore = operations.add_parser('restore', help='Restore an explicitly trusted local baseline; no test selection')
    restore.add_argument('--input', required=True, type=Path)
    fetch = operations.add_parser('fetch', help='Restore a baseline from an authenticated trusted GitHub push workflow')
    fetch.add_argument('--repository', required=True)
    fetch.add_argument('--workflow', required=True)
    fetch.add_argument('--branch', required=True, help='Explicit trusted producer branch; normally the default branch')
    fetch.add_argument('--output', required=True, type=Path)


def dispatch(store, args):
    from .dependency_graph import build, compare
    def path(value):
        return (store.root / value).resolve() if value else None
    if args.graph_action == 'baseline':
        from . import dependency_shared as shared
        if args.baseline_action == 'restore':
            return shared.restore(store, path(args.input))
        if args.baseline_action == 'fetch':
            from .dependency_shared_github import fetch
            return fetch(store, path(args.output), repository=args.repository, workflow=args.workflow, branch=args.branch)
        from .ci_handoff import json_data
        with path(args.producer).open('rb') as stream:
            meta = json_data(stream.read(1024 * 1024 + 1), 1024 * 1024)
        return shared.pack(store, path(args.output), producer_data=meta, runtime_paths=[path(p) for p in args.runtime])
    if args.graph_action == 'context':
        from .dependency_runtime import capture_context
        return capture_context(store, args.suite, path(args.output), mounts=args.mount)
    if args.graph_action == 'import':
        from .dependency_runtime import import_records
        return import_records(store, path(args.context), [path(p) for p in args.input], output=path(args.output))
    if args.graph_action == 'build':
        result = build(store, args.revision, output=path(args.output), runtime_paths=[path(p) for p in args.runtime])
        graph = result.pop('graph')
        surfaces = None
        if args.catalog:
            from .dependency_semantics import catalog, resolve
            from .evidence import GitSources
            from .config import load_config
            source = GitSources(store.root, graph['revision'], load_config(store.root)['evaluator']['max_test_bytes'])
            surfaces = resolve(source, graph, catalog(source, args.catalog))
        return {**result, 'revision': graph['revision'], 'nodes': len(graph['nodes']), 'edges': len(graph['edges']),
                'targets': len(graph['targets']), 'gaps': {p: n['gaps'] for p, n in graph['nodes'].items() if n['gaps']},
                'runtime_reuse': graph['runtime_reuse'],
                'surfaces': surfaces,
                'execution': 'none', 'omission_authorized': False}
    runtime = [path(p) for p in args.runtime]
    base, head = build(store, args.base, runtime_paths=runtime), build(store, args.head, runtime_paths=runtime)
    surfaces = None
    if args.catalog:
        from .dependency_semantics import inspect
        from .config import load_config
        surfaces = inspect(store, load_config(store.root), base['graph'], head['graph'], args.catalog)[0]
    return {**compare(base['graph'], head['graph']), 'surfaces': surfaces,
            'snapshots': {'base': base['path'], 'head': head['path']},
            'preparation': {'parsed': base['parsed'] + head['parsed'], 'reused': base['reused'] + head['reused']}}
