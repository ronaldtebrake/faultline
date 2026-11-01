"""CLI shared by the installed skill and standalone package."""
import argparse
import json
import sys

from . import __version__
from .core import FaultlineError, Store, repo_root
from .tia.cli import add_commands, dispatch


def parser():
    cli = argparse.ArgumentParser(prog='faultline', description='Assess test impact with an offline dependency graph; Jev is optional and off by default')
    cli.add_argument('--root', default='.', help='Target repository (defaults to the current Git root)')
    cli.add_argument('--version', action='version', version=f'faultline {__version__}')
    commands = cli.add_subparsers(dest='command', required=True)
    from .tia.workflow_cli import add_commands as add_workflow
    add_workflow(commands)
    from .tia.ci_cli import add_commands as add_ci
    add_ci(commands)
    from .tia.dependency_cli import add_commands as add_graph
    add_graph(commands)
    init = commands.add_parser('init', help='Initialize ignored storage and validate configured Git test sources')
    init.add_argument('--revision', default='HEAD', help='Git revision to inspect without executing tests')
    add_commands(commands)
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        store = Store(repo_root(args.root))
        if args.command in ('setup', 'assess', 'report'):
            from .tia.workflow_cli import dispatch as workflow
            result = workflow(store, args)
        elif args.command == 'graph':
            from .tia.dependency_cli import dispatch as graph
            result = graph(store, args)
        elif args.command.startswith('ci-') or args.command == 'export-selection':
            from .tia.ci_cli import dispatch as ci
            result = ci(store, args)
        elif args.command == 'init':
            store.initialize()
            result = {'storage': str(store.path), 'status': 'Create faultline.json, then run init to validate sources',
                      'execution': 'none', 'jev_requests': 0}
            if (store.root / 'faultline.json').exists():
                from .tia.config import load_config
                from .tia.source_index import open_index
                _, inventory, provenance = open_index(store, load_config(store.root), args.revision)
                result.update(index=provenance, complete=inventory['complete'], status='source inventory inspected')
        else:
            result = dispatch(store, args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if args.command in ('run', 'ci-run'):
            return result['exit_code']
        if args.command == 'select' and not result.get('dry_run') and result.get('semantic', {}).get('targets', 0) and not result.get('semantic_complete'):
            return 2
        return 2 if result.get('complete') is False else 0
    except (FaultlineError, OSError) as exc:
        print(f'faultline: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('faultline: interrupted; completed evidence is retained. Resume an assessment by its run ID.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
