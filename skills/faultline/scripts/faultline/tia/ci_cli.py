"""Explicit CI commands; analysis remains report-only by default."""
from pathlib import Path


def add_commands(commands):
    export = commands.add_parser('export-selection', help='Export a compact CI manifest offline from a Noul run')
    export.add_argument('--run', required=True)
    export.add_argument('--threshold', type=float, required=True)
    export.add_argument('--output', type=Path, required=True)
    plan = commands.add_parser('ci-plan', help='Validate a compact manifest and preview execution; no runners or API calls')
    plan.add_argument('--selection', type=Path, required=True)
    run = commands.add_parser('ci-run', help='Preview or explicitly execute selected files; native validation runs only with --execute')
    run.add_argument('--selection', type=Path, required=True)
    run.add_argument('--suite', help='Suite:variant; omit to execute configured prerequisites and variants in order')
    run.add_argument('--runners', nargs='+', help='Limit a pilot to named runners, including their prerequisites')
    run.add_argument('--execute', action='store_true')
    run.add_argument('--output', type=Path)
    run.add_argument('--prerequisite', type=Path, action='append', default=[])
    compare = commands.add_parser('ci-compare', help='Compare selected and full execution receipts for the same revision')
    compare.add_argument('--selected', type=Path, required=True)
    compare.add_argument('--full', type=Path, required=True)
    submit = commands.add_parser('ci-submit', help='Explicitly dispatch a selection to a trusted GitHub pilot workflow')
    modes = submit.add_mutually_exclusive_group(required=True)
    modes.add_argument('--selection', type=Path, help='Existing manual comparison pilot')
    modes.add_argument('--run', help='Saved noul-v1 assessment to publish before pushing')
    modes.add_argument('--full', action='store_true', help='Publish explicit full execution without scoring')
    submit.add_argument('--threshold', type=float)
    submit.add_argument('--target-branch')
    submit.add_argument('--head')
    submit.add_argument('--reason')
    submit.add_argument('--repository', required=True)
    submit.add_argument('--workflow', help='Default: faultline-publish.yml, or faultline-pilot.yml with --selection')
    receive = commands.add_parser('ci-receive', help='Decode a GitHub dispatch event into a bounded execution manifest')
    receive.add_argument('--event', type=Path, required=True)
    receive.add_argument('--output', type=Path, required=True)
    receive.add_argument('--publication', action='store_true', help='Validate publisher metadata and write the artifact directory')
    fetch = commands.add_parser('ci-fetch', help='One bounded trusted-publication lookup; missing/invalid data produces full execution')
    fetch.add_argument('--repository', required=True)
    fetch.add_argument('--target-branch', required=True)
    fetch.add_argument('--base-ref', required=True, help='Fetched exact PR target tip; computes merge base with HEAD')
    fetch.add_argument('--output', type=Path, required=True)
    fetch.add_argument('--workflow', default='faultline-publish.yml')


def dispatch(store, args):
    from . import ci_manifest, ci_execution, ci_github
    def path(p):
        return (store.root / p).resolve() if p else None
    if args.command == 'export-selection':
        return ci_manifest.export(store, args.run, args.threshold, path(args.output))
    if args.command == 'ci-plan':
        return ci_execution.plan(store, path(args.selection))
    if args.command == 'ci-run':
        return ci_execution.run(store, path(args.selection), suite_key=args.suite, execute=args.execute,
                                output=path(args.output), prerequisites=[path(p) for p in args.prerequisite], runners=args.runners)
    if args.command == 'ci-compare':
        return ci_execution.compare(path(args.selected), path(args.full))
    if args.command == 'ci-submit':
        from ..core import FaultlineError
        if args.selection:
            if args.target_branch or args.run or args.full or args.head or args.reason or args.threshold is not None:
                raise FaultlineError('Manual --selection dispatch cannot be combined with publication options')
            return ci_github.submit(store, path(args.selection), repository=args.repository, workflow=args.workflow or 'faultline-pilot.yml')
        from .ci_publication import publish
        return publish(store, repository=args.repository, target_branch=args.target_branch, run_id=args.run,
                       threshold=args.threshold, full=args.full, head=args.head, reason=args.reason,
                       workflow=args.workflow or 'faultline-publish.yml')
    if args.command == 'ci-fetch':
        from .ci_publication import fetch
        return fetch(store, repository=args.repository, target_branch=args.target_branch, base_ref=args.base_ref,
                     output=path(args.output), workflow=args.workflow)
    if args.publication:
        from .ci_handoff import receive_publication
        return receive_publication(store.root, path(args.event), path(args.output))
    return ci_github.receive(path(args.event), path(args.output))
