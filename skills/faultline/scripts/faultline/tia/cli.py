"""Report-only shadow analysis, optional native evidence, and explicit execution commands."""
from pathlib import Path

from ..core import FaultlineError, read_json
from .common import revision, save_frozen
from .config import load_config
from .mapping import phpunit_xml


def add_commands(commands):
    context = commands.add_parser('context', help='Verify and freeze agent-selected source context; no network or test execution')
    context.add_argument('--base', required=True)
    context.add_argument('--head', default='HEAD')
    context.add_argument('--input', type=Path, required=True, help='Version 1 context manifest')
    context.add_argument('--output', type=Path)
    cache = commands.add_parser('cache', help='Maintain local Jev answer storage')
    cache.add_argument('cache_action', choices=['compact'], help='Migrate verified legacy JSON answers to SQLite and remove their old cache files')
    select = commands.add_parser('select', help='Save a Jev would-run report without executing tests')
    select.add_argument('--base', required=True, help='Actual PR/MR diff base; use a merge-base if required by your host')
    select.add_argument('--head', default='HEAD')
    select.add_argument('--id', help='PR/MR identifier for reports, excluded from inference inputs')
    select.add_argument('--max-requests', type=int, help='Per-invocation Jev request cap including retries; does not edit configuration')
    select.add_argument('--selection-seconds', type=float, help='Per-invocation inference time limit')
    select.add_argument('--prepare', action='store_true', help='Read exact Git sources and estimate Jev work without contacting Jev')
    select.add_argument('--dry-run', action='store_true', help='Inspect cached evidence and request estimates; no indexing or API calls')
    select.add_argument('--native', action='store_true', help='Opt into runner discovery in a prepared application environment')
    select.add_argument('--output', type=Path)
    benchmark = commands.add_parser('benchmark', help='Freeze Jev proposals without running tests')
    benchmark.add_argument('--evidence-mode', choices=['adaptive', 'source', 'whole', 'file-pairs'], default='adaptive', help='Whole inputs with explicit lossless window fallback (default), strict source reference, full setup, or changed-file windows')
    benchmark.add_argument('--base', required=True)
    benchmark.add_argument('--head', default='HEAD')
    benchmark.add_argument('--id')
    benchmark.add_argument('--title', default='', help='Optional outcome-blind PR/MR title')
    benchmark.add_argument('--description', default='', help='Optional outcome-blind PR/MR description')
    benchmark.add_argument('--context', type=Path, help='Frozen context bundle matching this exact change; omit for diff-only baseline')
    benchmark.add_argument('--prepare', action='store_true', help='Read exact sources and estimate Jev requests without calling the API')
    benchmark.add_argument('--max-requests', type=int, help='Total HTTP attempts including retries')
    benchmark.add_argument('--selection-seconds', type=float, help='Shared inference deadline for all judgments')
    benchmark.add_argument('--max-state-bytes', type=int, help='Local byte guard for shared state plus longest question; not an exact token count')
    benchmark.add_argument('--max-batch-bytes', type=int, help='Local byte guard for the complete request')
    benchmark.add_argument('--output', type=Path)
    recovery = commands.add_parser('benchmark-recover', help='Reassess only unresolved source targets; preserve accepted judgments and freeze a new case')
    recovery.add_argument('--benchmark', type=Path, required=True)
    recovery.add_argument('--prepare', action='store_true', help='Plan bounded evidence windows and cached work without API calls')
    recovery.add_argument('--max-requests', type=int, help='Total new HTTP attempts including retries')
    recovery.add_argument('--selection-seconds', type=float)
    recovery.add_argument('--output', type=Path)
    assessment = commands.add_parser('benchmark-report', help='Regenerate a benchmark report or assess exact imported CI outcomes offline')
    assessment.add_argument('--benchmark', type=Path, required=True)
    assessment.add_argument('--outcomes', type=Path)
    assessment.add_argument('--policy-comparison', type=Path, help='Previously frozen .policies.json to assess against --outcomes')
    assessment.add_argument('--output', type=Path, help='Report basename for Markdown/CSV, or fresh assessment JSON when importing outcomes')
    assessment.add_argument('--pricing', type=Path, help='Dated input-token pricing JSON for offline report estimates; does not change frozen evidence')
    assessment.add_argument('--format', choices=['full', 'comment'], default='full', help='Detailed Markdown/CSV or a compact PR comment preview; never posts a comment')
    assessment.add_argument('--compare-policies', action='store_true', help='Compare saved decisions with offline relevance thresholds and file budgets; no inference or execution changes')
    assessment.add_argument('--relevance-thresholds', nargs='+', type=float, help='Exploratory P(plausible+strong+direct) thresholds; default: 0.10 0.25 0.50')
    assessment.add_argument('--file-budgets', nargs='+', type=int, help='Exploratory source-file budgets; default: 10%%, 25%%, 50%% of inventory rounded up')
    assessment.add_argument('--report-url', help='HTTPS link to a published report or CI artifact, for --format comment')
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
    discovery = commands.add_parser('discover', help='Query test targets from the exact Git revision without invoking runners')
    discovery.add_argument('--revision', default='HEAD')
    discovery.add_argument('--output', type=Path)
    discovery.add_argument('--native', action='store_true', help='Enrich source targets with native runner identities')
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
    for name in ('output', 'input', 'selection', 'run', 'junit_output', 'benchmark', 'outcomes', 'pricing', 'policy_comparison', 'context'):
        value = getattr(args, name, None)
        if value is not None:
            setattr(args, name, (store.root / value).resolve())
    if hasattr(args, 'prerequisite'):
        args.prerequisite = [(store.root / p).resolve() for p in args.prerequisite]
    if args.command == 'cache':
        from .cache import AnswerCache
        return AnswerCache(store).compact()
    if args.command == 'context':
        from .context import build
        return build(store, args.base, args.head, args.input, args.output)
    if args.command == 'benchmark':
        from .benchmark import benchmark
        return benchmark(store, args.base, args.head, identifier=args.id, prepare=args.prepare, output=args.output,
                         max_requests=args.max_requests, selection_seconds=args.selection_seconds, title=args.title, description=args.description, evidence_mode=args.evidence_mode, max_state_bytes=args.max_state_bytes, max_batch_bytes=args.max_batch_bytes, context_path=args.context)
    if args.command == 'benchmark-recover':
        from .benchmark_recovery import recover
        return recover(store, args.benchmark, prepare=args.prepare, max_requests=args.max_requests,
                       selection_seconds=args.selection_seconds, output=args.output)
    if args.command == 'benchmark-report':
        if args.outcomes:
            if args.pricing or args.format != 'full' or args.report_url or args.compare_policies or args.relevance_thresholds is not None or args.file_budgets is not None:
                raise FaultlineError('Pricing, comment format and policy comparisons apply to routing reports; omit --outcomes')
            from .benchmark_results import assess
            return assess(store, args.benchmark, args.outcomes, args.output, policy_comparison=args.policy_comparison)
        if args.policy_comparison:
            raise FaultlineError('--policy-comparison requires --outcomes')
        from .benchmark import render
        return render(args.benchmark, pricing=read_json(args.pricing) if args.pricing else None, output=args.output, format=args.format, report_url=args.report_url, compare_policies=args.compare_policies, relevance_thresholds=args.relevance_thresholds, file_budgets=args.file_budgets)
    if args.command == 'select':
        from .selection import select
        return select(store, args.base, args.head, identifier=args.id, output=args.output, dry_run=args.dry_run,
                      native=args.native, max_requests=args.max_requests, selection_seconds=args.selection_seconds, prepare=args.prepare)
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
        from .source_index import open_index
        rev = revision(store.root, args.revision)
        source, inventory, provenance = open_index(store, config, rev)
        if args.native:
            from .selection import workspace
            if revision(store.root) != rev or not workspace(store.root)['clean']:
                raise FaultlineError('Native enrichment requires a clean checkout of the requested revision')
            inventory = open_index(store, config, rev, native=True)[1]
        store.initialize()
        output = args.output or store.path / 'inventories' / (inventory['integrity'] + '.json')
        save_frozen(output, inventory)
        return {'output': str(output.resolve()), **inventory, 'index': provenance}
    raise FaultlineError(f'Unknown command: {args.command}')
