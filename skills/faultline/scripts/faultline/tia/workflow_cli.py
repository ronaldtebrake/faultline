"""Small public command surface; advanced research commands remain available."""
from pathlib import Path


def add_commands(commands):
    setup = commands.add_parser('setup', help='Find test-source candidates or validate reviewed configuration; no API calls or tests')
    setup.add_argument('--source', action='append', help='Reviewed test-source glob; repeat for more patterns')
    setup.add_argument('--scope', action='append', help='Reviewed production-source scope; repeat as needed')
    setup.add_argument('--revision', default='HEAD')
    assess = commands.add_parser('assess', help='Assess a cumulative diff and save a shareable HTML report; runs no tests')
    assess.add_argument('--evaluator', choices=['choice-v1', 'noul-v1'], help='Explicit scoring contract; default remains choice-v1')
    assess.add_argument('--max-cost', type=float, help='Noul run-wide USD ceiling, including unknown attempts; default $0.50')
    assess.add_argument('--base', help='Exact cumulative diff base, resolved by your Git host or agent')
    assess.add_argument('--head', default='HEAD')
    assess.add_argument('--id', help='Display identifier, excluded from inference inputs')
    assess.add_argument('--title', default='')
    assess.add_argument('--description', default='')
    assess.add_argument('--context', type=Path, help='Verified context bundle for this change, only when needed')
    assess.add_argument('--dependencies', action='store_true', help='Noul: retain tests with dependency paths without scoring them; assess all unresolved tests')
    assess.add_argument('--runtime', action='append', default=[], type=Path, help='Validated runtime evidence from the diff base or an available ancestor; requires --dependencies')
    assess.add_argument('--dependency-catalog', help='Tracked application-surface catalog; opts into reusable relationship judgments')
    assess.add_argument('--relationship-threshold', type=float, help='Explicit experimental surface-membership retention cutoff in (0, 0.5]')
    assess.add_argument('--prepare', action='store_true', help='Estimate work offline without spending; opt-in relationship plans report available cache hits')
    assess.add_argument('--resume', help='Continue a saved run ID; preserves accepted answers and attempted requests')
    cache = assess.add_mutually_exclusive_group()
    cache.add_argument('--fresh', action='store_true', help='Explicit fresh assessment (the default); no cross-run cache reads or writes')
    cache.add_argument('--reuse-cache', action='store_true', help='Opt into the disposable exact-input answer cache')
    assess.add_argument('--max-requests', type=int, help='Run-wide request ceiling, including retries and earlier attempts on resume')
    assess.add_argument('--selection-seconds', type=float, help='Inference time budget for this invocation; excludes source preparation')
    report = commands.add_parser('report', help='Create offline HTML, Markdown and CSV with 10/25/50 percent comparisons')
    source = report.add_mutually_exclusive_group(required=True)
    source.add_argument('--run', help='Saved assessment run ID')
    source.add_argument('--benchmark', type=Path, help='Any compatible frozen benchmark')
    source.add_argument('--demo', action='store_true', help='Generate a synthetic sample report without credentials or inference')
    report.add_argument('--output', type=Path, help='Output basename; the HTML is one shareable file')


def dispatch(store, args):
    from .workflow import assess, saved_report, setup
    if args.command == 'setup':
        return setup(store, sources=args.source, scope=args.scope, ref=args.revision)
    if args.command == 'assess':
        from ..core import read_json, FaultlineError
        import re
        if args.resume and not re.fullmatch(r'[a-f0-9]{32}', args.resume):
            raise FaultlineError('Invalid assessment run ID')
        saved = read_json(store.path / 'runs' / args.resume / 'run.json', {}) if args.resume else {}
        evaluator = args.evaluator or saved.get('evaluator', 'choice-v1')
        if evaluator == 'noul-v1':
            if args.reuse_cache or (args.fresh and args.resume):
                raise FaultlineError('Noul impact scores use fresh runs or explicit resume; use --dependency-catalog for separate reusable relationships')
            from .impact import assess as noul_assess
            return noul_assess(store, base=args.base, head=args.head, identifier=args.id, title=args.title,
                               description=args.description, context_path=(store.root / args.context).resolve() if args.context else None,
                               prepare=args.prepare, resume=args.resume, max_requests=args.max_requests,
                               selection_seconds=args.selection_seconds, max_cost=args.max_cost,
                               dependencies=args.dependencies, runtime_paths=[(store.root / p).resolve() for p in args.runtime],
                               dependency_catalog=args.dependency_catalog, relationship_threshold=args.relationship_threshold,
                               relationship_fresh=args.fresh)
        if args.dependencies or args.runtime or args.dependency_catalog or args.relationship_threshold is not None:
            raise FaultlineError('Dependency planning currently requires --evaluator noul-v1')
        if args.max_cost is not None:
            raise FaultlineError('--max-cost applies to noul-v1; Choice uses --max-requests')
        return assess(store, base=args.base, head=args.head, identifier=args.id, title=args.title,
                      description=args.description, context_path=(store.root / args.context).resolve() if args.context else None,
                      prepare=args.prepare, resume=args.resume, reuse_cache=args.reuse_cache, fresh=args.fresh,
                      max_requests=args.max_requests, selection_seconds=args.selection_seconds)
    store.initialize()
    return saved_report(store, path=(store.root / args.benchmark).resolve() if args.benchmark else None,
                        run_id=args.run, output=(store.root / args.output).resolve() if args.output else None, demo=args.demo)
