#!/usr/bin/env python3
"""Install both local Faultline skills without overwriting existing skills."""
import argparse
import shutil
from pathlib import Path


def install(target, copy=False):
    source = Path(__file__).resolve().parents[1] / 'skills'
    names = ('index-tests', 'rank-tests')
    target = target.expanduser().resolve()
    # Check both destinations before changing either one.
    for name in names:
        destination = target / name
        if destination.is_symlink() and destination.resolve() == (source / name).resolve() and not copy:
            continue
        if destination.exists() or destination.is_symlink():
            raise ValueError(f'{destination} already exists; inspect it before replacing it.')
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        destination = target / name
        if destination.is_symlink():
            continue
        if copy:
            shutil.copytree(source / name, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.egg-info'))
        else:
            destination.symlink_to(source / name, target_is_directory=True)
        print(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, type=Path, help="Agent's skill directory, e.g. /path/to/repo/.agents/skills")
    parser.add_argument('--copy', action='store_true', help='Copy instead of linking the local checkout')
    args = parser.parse_args()
    try:
        install(args.target, args.copy)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
