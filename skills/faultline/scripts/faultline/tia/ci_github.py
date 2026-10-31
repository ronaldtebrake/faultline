"""Authenticated dispatch of data only; no source, scores, or commands uploaded."""
import base64
import gzip
import json
import re
import subprocess
import zlib
from pathlib import Path
from ..core import FaultlineError, digest
from .ci_manifest import MAX_BYTES, encode, read, shape

MAX_INPUT = 60000


def pack(value):
    raw = encode(shape(value))
    plain = 'json:' + raw.decode()
    payload = plain if len(plain.encode()) <= MAX_INPUT else 'gzip:' + base64.b64encode(gzip.compress(raw, mtime=0)).decode()
    if len(payload.encode()) > MAX_INPUT:
        raise FaultlineError('Selection exceeds dispatch input limit; use a repository-owned artifact transfer. No truncation allowed.')
    return payload


def unpack(payload):
    if not isinstance(payload, str) or len(payload.encode()) > MAX_INPUT:
        raise FaultlineError('Invalid dispatch payload size')
    try:
        if payload.startswith('json:'):
            raw = payload[5:].encode()
        elif payload.startswith('gzip:'):
            data = base64.b64decode(payload[5:], validate=True)
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            raw = decoder.decompress(data, MAX_BYTES + 1)
            if not decoder.eof or decoder.unused_data or len(raw) > MAX_BYTES:
                raise ValueError()
        else:
            raise ValueError()
        def unique(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        return shape(json.loads(raw, object_pairs_hook=unique))
    except (ValueError, TypeError, UnicodeError, zlib.error):
        raise FaultlineError('Invalid dispatch selection; refuse execution') from None


def receive(event, output):
    try:
        data = json.loads(Path(event).read_text())
        value = unpack(data['inputs']['selection'])
    except (KeyError, ValueError, TypeError):
        raise FaultlineError('Missing dispatch selection') from None
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode(value) + b'\n')
    return {'path': str(path), 'revision': value['revision'], 'manifest_digest': digest(value)}


def submit(store, path, *, repository, workflow='faultline-pilot.yml'):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.ya?ml', workflow):
        raise FaultlineError('Use an owner/repository and a workflow filename')
    value = read(path)
    # Export can be generated from another checkout. Only repository/config identity
    # is required locally; the trusted receiving job checks the exact tested checkout.
    from .config import load_config
    from .common import git
    from urllib.parse import urlsplit
    from .ci_manifest import fingerprint
    remote = git(store.root, 'remote', 'get-url', 'origin').strip()
    if '://' in remote:
        parsed = urlsplit(remote)
        identity = (parsed.hostname or '') + '/' + parsed.path.strip('/')
    elif re.fullmatch(r'[^/]+@[^:]+:.+', remote):
        identity = remote.split('@', 1)[1].replace(':', '/', 1)
    else:
        identity = ''
    if identity.removesuffix('.git').lower() != 'github.com/' + repository.lower():
        raise FaultlineError('Dispatch repository does not match this checkout origin')
    if value['config'] != fingerprint(load_config(store.root)):
        raise FaultlineError('Selection configuration differs from this repository')
    def gh(args, data=None):
        try:
            p = subprocess.run(['gh', *args], input=data, text=True, capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            raise FaultlineError('GitHub helper unavailable or timed out; check dispatch history before retrying') from None
        if p.returncode:
            raise FaultlineError('GitHub operation failed; verify gh authentication and repository access')
        return p.stdout
    try:
        target = json.loads(gh(['api', 'repos/' + repository]))
        if not isinstance(target['default_branch'], str) or not target['default_branch']:
            raise ValueError()
        full_name = target['full_name'].lower()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise FaultlineError('Invalid GitHub repository response') from None
    if full_name != repository.lower():
        raise FaultlineError('Unexpected GitHub repository identity')
    # Always dispatch reviewed code on the default branch; never a PR-owned workflow.
    body = json.dumps({'ref': target['default_branch'], 'inputs': {'selection': pack(value)}})
    gh(['api', '--method', 'POST', 'repos/' + repository + '/actions/workflows/' + workflow + '/dispatches', '--input', '-'], body)
    return {'submitted': True, 'repository': repository, 'workflow': workflow, 'revision': value['revision'],
            'manifest_digest': digest(value), 'jev_requests': 0}
