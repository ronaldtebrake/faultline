from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from ..core import FaultlineError, digest, read_json, write_json
from .config import SCHEMA, inside


def git(root, *args):
    p = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if p.returncode:
        raise FaultlineError('Git could not resolve the requested revision or change')
    return p.stdout.strip()


def revision(root, ref='HEAD'):
    return git(root, 'rev-parse', '--verify', ref + '^{commit}')


def file_hash(root, path):
    p = inside(root, path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def glob_files(root, patterns):
    files = set()
    for pattern in patterns:
        if Path(pattern).is_absolute() or '..' in Path(pattern).parts:
            raise FaultlineError('Source patterns must be repository-relative')
        for path in root.glob(pattern):
            if not path.resolve().is_relative_to(root):
                raise FaultlineError('Source pattern matches a path outside the repository')
            if path.is_file():
                files.add(path.relative_to(root).as_posix())
    return sorted(files)


def hashes(root, paths):
    return {p: file_hash(root, p) for p in sorted(set(paths))}


def seal(value):
    value = {k: v for k, v in value.items() if k != 'integrity'}
    return {**value, 'integrity': digest(value)}


def checked(path, kind=None):
    value = read_json(Path(path))
    if not isinstance(value, dict) or value.get('schema_version') != SCHEMA or value.get('integrity') != digest({k: v for k, v in value.items() if k != 'integrity'}):
        raise FaultlineError('Missing, unsupported, or modified Faultline document')
    if kind and value.get('kind') != kind:
        raise FaultlineError(f'Expected a {kind} document')
    return value


def save_frozen(path, value):
    value = seal(value)
    if path.exists():
        prior = checked(path)
        if prior != value:
            raise FaultlineError('Refusing to overwrite frozen evidence; use a new output path')
    else:
        write_json(path, value)
    return value

