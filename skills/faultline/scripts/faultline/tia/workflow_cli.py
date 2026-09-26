"""Small public command surface; advanced research commands remain available."""
from pathlib import Path


def add_commands(commands):
    setup = commands.add_parser('setup', help='Find test-source candidates or validate reviewed configuration; no API calls or tests')
    setup.add_argument('--source', action='append', help='Reviewed test-source glob; repeat for more patterns')
    setup.add_argument('--scope', action='append', help='Reviewed production-source scope; repeat as needed')
    setup.add_argument('--revision', default='HEAD')
    assess = commands.add_parser('assess', help='Assess a cumulative diff and save a shareable HTML report; runs no tests')
    assess.add_argument('--base', help='Exact cumulative diff base, resolved by your Git host or agent')
    assess.add_argument('--head', default='HEAD')
    assess.add_argument('--id', help='Display identifier, excluded from inference inputs')
    assess.add_argument('--title', default='')
    assess.add_argument('--description', default='')
    assess.add_argument('--context', type=Path, help='Verified context bundle for this change, only when needed')
    assess.add_argument('--prepare', action='store_true', help='Estimate the work offline without spending or reusing answers')
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
        return assess(store, base=args.base, head=args.head, identifier=args.id, title=args.title,
                      description=args.description, context_path=(store.root / args.context).resolve() if args.context else None,
                      prepare=args.prepare, resume=args.resume, reuse_cache=args.reuse_cache, fresh=args.fresh,
                      max_requests=args.max_requests, selection_seconds=args.selection_seconds)
    store.initialize()
    return saved_report(store, path=(store.root / args.benchmark).resolve() if args.benchmark else None,
                        run_id=args.run, output=(store.root / args.output).resolve() if args.output else None, demo=args.demo)
