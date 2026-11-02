"""Public task CLI; no dependency on inference or test-runner adapters."""
import os
from pathlib import Path

from .core import write_json
from .task_cache import markdown, preview, run, run_markdown


def add_commands(commands):
    tasks = commands.add_parser('tasks', help='Plan task inputs and reuse successful deterministic checks')
    sub = tasks.add_subparsers(dest='task_command', required=True)
    plan = sub.add_parser('plan', help='Preview committed task fingerprints without executing commands')
    plan.add_argument('--base', help='Optional comparison revision (use the PR merge base)')
    plan.add_argument('--head', default='HEAD')
    execute = sub.add_parser('run', help='Run complete checks; collect results even when a cache match exists')
    execute.add_argument('--reuse', action='store_true', help='Explicitly reuse successful matching check results')
    for command in (plan, execute):
        command.add_argument('--task', action='append', default=[], help='Task name; repeatable, dependencies included')
        command.add_argument('--cache-dir', help='Trusted local/shared result directory')
        command.add_argument('--output', help='Plan JSON file or fresh execution report directory')
        command.add_argument('--github-summary', action='store_true', help='Append task decisions to GITHUB_STEP_SUMMARY')
    plan.add_argument('--github-output', action='store_true', help='Export cache-key/cache-namespace to GITHUB_OUTPUT')


def dispatch(store, args):
    store.initialize()
    if args.task_command == 'run':
        result = run(store, tasks=args.task, cache_dir=args.cache_dir, reuse=args.reuse, output=args.output)
        if args.github_summary and os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
                stream.write(run_markdown(result))
        return result
    result = preview(store, base=args.base, head=args.head, tasks=args.task, cache_dir=args.cache_dir)
    if args.output:
        write_json(Path(args.output), result)
    if args.github_summary and os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(markdown(result))
    if args.github_output and os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write(f"cache-key={result['cache_key']}\ncache-namespace={result['cache_namespace']}\n")
    return result
