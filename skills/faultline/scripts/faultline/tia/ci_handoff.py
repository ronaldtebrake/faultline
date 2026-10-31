"""Snapshot identity and data-only publication envelopes (manifest v1 unchanged)."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from ..core import FaultlineError, digest
from .common import checked, git, revision, save_frozen
from .config import load_config
from .ci_manifest import encode, fingerprint, shape

META_BYTES = 8192
PUBLISHER = 'faultline-publish.yml'


def json_data(raw, limit):
    if len(raw) > limit:
        raise FaultlineError('Handoff data exceeds its size limit')
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise FaultlineError('Malformed handoff JSON') from None


def repository_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
        raise FaultlineError('Use a GitHub owner/repository')
    return value.lower()


def origin(root, *, push=False):
    args = ['remote', 'get-url', *(['--push', '--all'] if push else []), 'origin']
    remote = git(root, *args)
    if '\n' in remote:
        raise FaultlineError('Multiple push destinations cannot share a readiness check')
    if '://' in remote:
        parsed = urlsplit(remote)
        host, path = parsed.hostname, parsed.path.strip('/')
    elif re.fullmatch(r'git@github.com:.+', remote):
        host, path = 'github.com', remote.split(':', 1)[1]
    else:
        raise FaultlineError('Publication requires a github.com origin')
    if host != 'github.com':
        raise FaultlineError('Publication requires a github.com origin')
    return repository_name(path.removesuffix('.git'))


def branch_name(value):
    # Deliberately a conservative subset of Git refs, also safe in API paths.
    if (not isinstance(value, str) or len(value) > 200 or
            not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', value) or
            any(part in ('', '.', '..') or part.startswith('.') or part.endswith(('.', '.lock')) for part in value.split('/')) or '..' in value):
        raise FaultlineError('Use a target branch name, such as main or release/next')
    return value


def snapshot(root, repository, target_branch, *, head='HEAD', base_ref=None):
    repository = repository_name(repository)
    if origin(root) != repository:
        raise FaultlineError('Repository does not match this checkout origin')
    branch_name(target_branch)
    commit = revision(root, head)
    bases = git(root, 'merge-base', '--all', commit, revision(root, base_ref or 'refs/remotes/origin/' + target_branch)).splitlines()
    if len(bases) != 1:
        raise FaultlineError('Ambiguous merge base; use full execution after resolving the history')
    return {'repository': repository, 'target_branch': target_branch, 'base': bases[0],
            'revision': commit, 'config': fingerprint(load_config(root))}


def full_selection(identity, config):
    return shape({'version': 1, 'revision': identity['revision'], 'config': identity['config'],
                  'suites': {suite['id']: {'mode': 'all'} for suite in config['suites']}})


def metadata(identity, selection, *, reason='', submission):
    return validate_metadata({'version': 1, **identity, 'manifest_digest': digest(selection),
                              'submission': submission, 'reason': reason}, selection)


def validate_metadata(value, selection):
    keys = {'version', 'repository', 'target_branch', 'base', 'revision', 'config', 'manifest_digest', 'submission', 'reason'}
    if not isinstance(value, dict) or set(value) != keys or type(value['version']) is not int or value['version'] != 1:
        raise FaultlineError('Unsupported handoff metadata')
    if repository_name(value['repository']) != value['repository']:
        raise FaultlineError('Noncanonical handoff repository')
    branch_name(value['target_branch'])
    if not isinstance(value['base'], str) or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', value['base']):
        raise FaultlineError('Handoff needs an exact diff base')
    if (value['revision'] != selection['revision'] or value['config'] != selection['config'] or
            value['manifest_digest'] != digest(selection)):
        raise FaultlineError('Handoff does not identify this selection')
    if not isinstance(value['submission'], str) or not re.fullmatch(r'[a-f0-9]{32}', value['submission']):
        raise FaultlineError('Invalid publication identity')
    if not isinstance(value['reason'], str) or len(value['reason'].encode()) > 1000 or any(ord(c) < 32 for c in value['reason']):
        raise FaultlineError('Fallback reason must be a single line of at most 1000 bytes')
    if len(encode(value)) > META_BYTES:
        raise FaultlineError('Handoff metadata exceeds its size limit')
    return value


def identity_of(meta):
    return {k: meta[k] for k in ('repository', 'target_branch', 'base', 'revision', 'config')}


def artifact_name(identity):
    return 'faultline-selection-v1-' + digest(identity)


def clean_head(store, identity):
    if revision(store.root) != identity['revision'] or git(store.root, 'status', '--porcelain', '--untracked-files=no'):
        raise FaultlineError('Commit tracked changes first; publish for the clean checked-out HEAD')


def receipt_path(store, identity):
    return store.path / 'handoffs' / digest(identity) / 'published.json'


def remember(store, identity, publication):
    # A fresh receipt replaces only the local readiness pointer, not immutable
    # remote artifacts or assessment evidence. No receipt is written on failure.
    store.initialize()
    folder = receipt_path(store, identity).parent
    value = {'schema_version': 2, 'kind': 'published-selection', 'identity': identity, **publication}
    frozen = save_frozen(folder / (digest(value) + '.json'), value)
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / (publication['metadata']['submission'] + '.tmp')
    temporary.write_bytes(encode(frozen) + b'\n')
    temporary.replace(receipt_path(store, identity))


def ready(store, target_branch):
    identity = snapshot(store.root, origin(store.root), target_branch)
    clean_head(store, identity)
    receipt = checked(receipt_path(store, identity), 'published-selection')
    if receipt['identity'] != identity or identity_of(receipt['metadata']) != identity:
        raise FaultlineError('Published decision belongs to another cumulative diff')
    validate_metadata(receipt['metadata'], shape(receipt['selection']))
    expiry = datetime.fromisoformat(receipt['expires_at'].replace('Z', '+00:00'))
    if expiry <= datetime.now(timezone.utc):
        raise FaultlineError('Published decision has expired')
    return receipt


def receive_publication(root, event, output):
    try:
        return _receive_publication(root, event, output)
    except (KeyError, ValueError, TypeError, AttributeError, RecursionError):
        raise FaultlineError('Malformed publication event; no artifact may be published') from None


def _receive_publication(root, event, output):
    from .ci_github import unpack, MAX_INPUT
    with Path(event).open('rb') as stream:
        data = json_data(stream.read(262145), 262144)
    inputs = data['inputs']
    selection = unpack(inputs['selection'])
    meta = validate_metadata(json_data(inputs['handoff'].encode(), META_BYTES), selection)
    if len(inputs['selection'].encode()) + len(inputs['handoff'].encode()) > MAX_INPUT:
        raise FaultlineError('Combined dispatch payload exceeds its limit')
    repo = data['repository']
    if (meta['repository'] != repository_name(repo['full_name']) or
            data['ref'] != 'refs/heads/' + repo['default_branch'] or origin(root) != meta['repository']):
        raise FaultlineError('Publisher must run from this repository default branch')
    if selection['config'] != fingerprint(load_config(root)):
        raise FaultlineError('Publish only the reviewed default-branch execution configuration')
    path = Path(output)
    path.mkdir(parents=True, exist_ok=True)
    for name, value in [('selection.json', selection), ('handoff.json', meta)]:
        target = path / name
        if target.exists():
            raise FaultlineError('Publication output must be new')
        target.write_bytes(encode(value) + b'\n')
    return {'artifact_name': artifact_name(identity_of(meta)), 'revision': selection['revision'], 'jev_requests': 0}
