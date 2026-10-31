"""Validate generator declarations against immutable tracked source, not annotations alone."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from ..core import FaultlineError

MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


def artifact_file(root, name):
    if (not isinstance(name, str) or not name or any(part in ('', '.', '..') for part in name.split('/')) or
            re.search(r'[\\:\x00-\x1f]', name)):
        raise ValueError('Noncanonical artifact path')
    root = Path(root).resolve()
    path = root / name
    if not path.is_file() or path.is_symlink() or path.resolve().relative_to(root).as_posix() != name:
        raise ValueError('Artifact is not a regular file within the repository')
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError('Artifact exceeds the size limit')
    return path


def validate_artifacts(artifacts, root, tracked):
    """Bind external catalogs to local bytes without calling them Git source."""
    try:
        if not isinstance(artifacts, dict) or not artifacts or len(artifacts) > 512:
            raise ValueError()
        for name, expected in artifacts.items():
            if (name in tracked or not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected) or
                    hashlib.sha256(artifact_file(root, name).read_bytes()).hexdigest() != expected):
                raise ValueError()
    except (ValueError, OSError, TypeError):
        raise FaultlineError('Invalid, missing or changed Playwright generation artifact; restore the exact artifact or regenerate tests') from None


def validate(mapping, source, test_source):
    try:
        version = mapping.get('version') if isinstance(mapping, dict) else None
        artifacts = mapping.get('artifacts', {}) if isinstance(mapping, dict) else {}
        fields = {'version', 'revision', 'source', 'inputs'} | ({'artifacts'} if version == 2 else set())
        if (not isinstance(mapping, dict) or set(mapping) != fields or
                type(version) is not int or version not in (1, 2) or
                mapping['revision'] != source.revision or mapping['source'] != test_source or
                not isinstance(mapping['inputs'], dict) or test_source not in mapping['inputs'] or
                not isinstance(artifacts, dict) or set(artifacts) & set(mapping['inputs']) or
                len(mapping['inputs']) + len(artifacts) > 512 or len(json.dumps(mapping).encode()) > 128 * 1024):
            raise ValueError()
        for name, expected in mapping['inputs'].items():
            if (not name or any(part in ('', '.', '..') for part in name.split('/')) or
                    re.search(r'[\\:\x00-\x1f]', name) or str(PurePosixPath(name)) != name or
                    name not in source.files or not source.files[name]['mode'].startswith('100') or
                    not isinstance(expected, str) or not re.fullmatch(r'[a-f0-9]{64}', expected) or
                    hashlib.sha256(source.read(name)).hexdigest() != expected):
                raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise FaultlineError('Invalid, untracked or stale Playwright generation inputs; regenerate tests') from None
    if version == 2:
        validate_artifacts(artifacts, source.root, source.files)
    return mapping
