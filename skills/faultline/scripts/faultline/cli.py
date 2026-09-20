"""CLI shared by the installed skill and standalone package."""
import argparse
import json
import sys

from . import __version__
from .core import FaultlineError, Store, repo_root
from .tia.cli import add_commands, dispatch


def parser():
    cli = argparse.ArgumentParser(prog='faultline', description='Assess test impact with Jev')
    cli.add_argument('--root', default='.', help='Target repository (defaults to the current Git root)')
    cli.add_argument('--version', action='version', version=f'faultline {__version__}')
    commands = cli.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='Initialize ignored storage and validate configured Git test sources')
    init.add_argument('--revision', default='HEAD', help='Git revision to inspect without executing tests')
    add_commands(commands)
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        store = Store(repo_root(args.root))
        if args.command == 'init':
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
        if args.command == 'run':
            return result['exit_code']
        if args.command == 'select' and not result.get('dry_run') and result.get('semantic', {}).get('targets', 0) and not result.get('semantic_complete'):
            return 2
        return 2 if result.get('complete') is False else 0
    except (FaultlineError, OSError) as exc:
        print(f'faultline: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('faultline: interrupted; completed cache entries are retained.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
