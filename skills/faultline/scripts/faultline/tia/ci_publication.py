"""Bounded GitHub publication and one-shot retrieval. No inference or runners."""
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from ..core import FaultlineError, digest
from .common import checked
from .config import load_config
from .ci_manifest import MAX_BYTES, encode, fingerprint, from_assessment, record_export, shape
from .ci_github import MAX_INPUT, pack
from . import ci_handoff as handoff

MAX_ARCHIVE = MAX_BYTES + 65536
LOOKUP_SECONDS = 25
MAX_CANDIDATES = 10


class GitHub:
    """gh supplies authentication, including host-scoped redirect handling.

    Output goes to bounded temporary files rather than unbounded capture_output.
    Every request shares a wall-clock deadline; API responses are never logged.
    """
    def __init__(self, seconds, *, max_bytes=MAX_BYTES, max_archive=MAX_ARCHIVE):
        self.deadline = time.monotonic() + seconds
        self.max_bytes, self.max_archive = max_bytes, max_archive

    def request(self, endpoint, *, body=None, binary=False):
        if time.monotonic() >= self.deadline:
            raise FaultlineError('GitHub deadline exceeded')
        command = ['gh', 'api', '--hostname', 'github.com', '--method', 'POST' if body is not None else 'GET', endpoint]
        limit = self.max_archive if binary else self.max_bytes
        env = {k: v for k, v in os.environ.items() if k not in ('GH_DEBUG', 'DEBUG', 'GH_FORCE_TTY')}
        with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            if body is not None:
                stdin.write(encode(body)); stdin.seek(0)
                command += ['--input', '-']
            try:
                process = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr, env=env)
            except OSError:
                raise FaultlineError('GitHub CLI unavailable; authenticate gh before publication') from None
            try:
                deadline = min(self.deadline, time.monotonic() + 15)
                while process.poll() is None:
                    if time.monotonic() >= deadline or os.fstat(stdout.fileno()).st_size > limit or os.fstat(stderr.fileno()).st_size > 65536:
                        raise FaultlineError('GitHub response exceeded time or size bounds')
                    time.sleep(.02)
                stdout.seek(0)
                raw = stdout.read(limit + 1)
                if process.returncode or len(raw) > limit:
                    raise FaultlineError('GitHub operation failed or exceeded its response limit')
                return raw if binary else handoff.json_data(raw, limit) if raw.strip() else None
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()


def workflow_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.ya?ml', value):
        raise FaultlineError('Use a reviewed publisher workflow filename')
    return value


def trusted_origin(api, repository, workflow):
    repo = api.request('repos/' + repository)
    definition = api.request('repos/' + repository + '/actions/workflows/' + workflow_name(workflow))
    if (handoff.repository_name(repo['full_name']) != repository or type(repo['id']) is not int or
            definition['path'] != '.github/workflows/' + workflow or definition['state'] != 'active' or type(definition['id']) is not int):
        raise FaultlineError('Invalid repository or publisher workflow identity')
    handoff.branch_name(repo['default_branch'])
    return repo, definition


def unpack_artifact(raw, artifact):
    if len(raw) > MAX_ARCHIVE:
        raise FaultlineError('Artifact archive exceeds limit')
    expected = artifact.get('digest')
    if not isinstance(expected, str) or expected != 'sha256:' + hashlib.sha256(raw).hexdigest():
        raise FaultlineError('Artifact archive digest is unavailable or invalid')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            items = archive.infolist()
            if len(items) != 2 or {i.filename for i in items} != {'selection.json', 'handoff.json'}:
                raise FaultlineError('Artifact must contain only selection.json and handoff.json')
            content = {}
            for item in items:
                limit = MAX_BYTES + 1 if item.filename == 'selection.json' else handoff.META_BYTES + 1
                if item.file_size > limit or item.is_dir() or item.flag_bits & 1 or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise FaultlineError('Invalid artifact entry')
                with archive.open(item) as stream:
                    content[item.filename] = handoff.json_data(stream.read(limit + 1), limit)
        selection = shape(content['selection.json'])
        meta = handoff.validate_metadata(content['handoff.json'], selection)
        return selection, meta
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, ValueError, EOFError):
        raise FaultlineError('Invalid artifact archive') from None


def lookup(api, identity, workflow=handoff.PUBLISHER, *, submission=None, trust=None):
    """One list call, up to ten candidates. No polling for a missing assessment."""
    repository = identity['repository']
    repo, definition = trust or trusted_origin(api, repository, workflow)
    prefix = 'repos/' + repository + '/actions/'
    name = handoff.artifact_name(identity)
    listing = api.request(prefix + 'artifacts?name=' + name + '&per_page=100')
    if (type(listing['total_count']) is not int or not isinstance(listing['artifacts'], list) or
            listing['total_count'] > 100 or len(listing['artifacts']) != listing['total_count']):
        raise FaultlineError('Artifact inventory exceeds lookup bounds or is incomplete')
    candidates = sorted(listing['artifacts'], key=lambda a: a['id'], reverse=True)
    for artifact in candidates[:MAX_CANDIDATES]:
        if artifact['name'] != name or artifact['expired'] is not False:
            continue
        if type(artifact['id']) is not int or type(artifact['size_in_bytes']) is not int or not 0 < artifact['size_in_bytes'] <= MAX_ARCHIVE:
            raise FaultlineError('Artifact exceeds size bounds')
        summary = artifact['workflow_run']
        if summary.get('repository_id') != repo['id'] or summary.get('head_repository_id') != repo['id']:
            continue
        if type(summary.get('id')) is not int:
            raise FaultlineError('Invalid artifact run ID')
        run = api.request(prefix + 'runs/' + str(summary['id']))
        if (run['id'] != summary['id'] or run['workflow_id'] != definition['id'] or
                run['path'] != definition['path'] or run['event'] != 'workflow_dispatch' or
                run['status'] != 'completed' or run['conclusion'] != 'success' or
                run['head_branch'] != repo['default_branch'] or summary['head_branch'] != repo['default_branch'] or
                run['repository']['id'] != repo['id'] or run['head_repository']['id'] != repo['id'] or
                handoff.repository_name(run['repository']['full_name']) != repository or
                handoff.repository_name(run['head_repository']['full_name']) != repository or
                not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', run['head_sha']) or run['head_sha'] != summary['head_sha']):
            continue
        expiry = datetime.fromisoformat(artifact['expires_at'].replace('Z', '+00:00'))
        if expiry <= datetime.now(timezone.utc):
            continue
        raw = api.request(prefix + 'artifacts/' + str(artifact['id']) + '/zip', binary=True)
        selection, meta = unpack_artifact(raw, artifact)
        if handoff.identity_of(meta) != identity:
            raise FaultlineError('Artifact belongs to a different PR snapshot')
        if submission and meta['submission'] != submission:
            continue
        return {'selection': selection, 'metadata': meta, 'artifact_id': artifact['id'],
                'run_id': run['id'], 'expires_at': artifact['expires_at'], 'publisher': workflow}
    return None


def publish(store, **kwargs):
    try:
        return _publish(store, **kwargs)
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        raise FaultlineError('Malformed publication response; no new readiness receipt created') from None


def _publish(store, *, repository, target_branch, run_id=None, threshold=None, full=False, head=None,
            reason=None, workflow=handoff.PUBLISHER, api=None, sleep=time.sleep):
    """Successful remote publication is required before recording readiness."""
    repository = handoff.repository_name(repository)
    handoff.branch_name(target_branch)
    workflow_name(workflow)
    if (bool(run_id) == bool(full) or (full and (not head or not reason or threshold is not None)) or
            (run_id and (threshold is None or head is not None or reason is not None))):
        raise FaultlineError('Use --run/--threshold or --full/--head/--reason, with --target-branch')
    api = api or GitHub(120)
    if handoff.origin(store.root) != repository:
        raise FaultlineError('Repository does not match this checkout origin')
    trust = trusted_origin(api, repository, workflow)
    # Read current target tip without requiring the unpublished head on GitHub.
    remote = api.request('repos/' + repository + '/git/ref/heads/' + quote(target_branch, safe='/'))
    if remote['ref'] != 'refs/heads/' + target_branch or remote['object']['type'] != 'commit' or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', remote['object']['sha']):
        raise FaultlineError('Invalid target branch response')
    target_tip = remote['object']['sha']
    if handoff.revision(store.root, 'refs/remotes/origin/' + target_branch) != target_tip:
        raise FaultlineError('Target branch changed; fetch origin and reassess the cumulative merge-base diff')
    config = load_config(store.root)
    if full:
        identity = handoff.snapshot(store.root, repository, target_branch, head=head, base_ref=target_tip)
        selection = handoff.full_selection(identity, config)
    else:
        from .impact import assessment_path
        document = checked(assessment_path(store, run_id), 'impact-assessment')
        identity = handoff.snapshot(store.root, repository, target_branch, head=document['revision'], base_ref=target_tip)
        if document['base'] != identity['base']:
            raise FaultlineError('Assessment is not the complete cumulative PR diff; reassess from its merge base')
        selection, reasons = from_assessment(document, config, threshold)
        record_export(store, document, threshold, selection, reasons)
    handoff.clean_head(store, identity)
    # Successful repeated submissions can reuse a trusted immutable decision.
    existing = lookup(api, identity, workflow, trust=trust)
    if existing and digest(existing['selection']) == digest(selection):
        handoff.remember(store, identity, existing)
        return {'published': True, 'reused': True, 'revision': identity['revision'], 'artifact_id': existing['artifact_id'], 'jev_requests': 0}
    meta = handoff.metadata(identity, selection, reason=reason or '', submission=uuid.uuid4().hex)
    inputs = {'selection': pack(selection), 'handoff': encode(meta).decode()}
    if sum(len(v.encode()) for v in inputs.values()) > MAX_INPUT:
        raise FaultlineError('Combined dispatch input exceeds limit; no truncation allowed')
    api.request('repos/' + repository + '/actions/workflows/' + workflow + '/dispatches',
                body={'ref': trust[0]['default_branch'], 'inputs': inputs})
    # Poll only the publisher, locally and before pushing. CI never uses this loop.
    while time.monotonic() < api.deadline:
        publication = lookup(api, identity, workflow, submission=meta['submission'], trust=trust)
        if publication:
            handoff.clean_head(store, identity)
            if fingerprint(load_config(store.root)) != identity['config']:
                raise FaultlineError('Execution configuration changed during publication')
            handoff.remember(store, identity, publication)
            return {'published': True, 'reused': False, 'revision': identity['revision'], 'base': identity['base'],
                    'artifact_id': publication['artifact_id'], 'manifest_digest': digest(selection), 'jev_requests': 0}
        sleep(min(5, max(0, api.deadline - time.monotonic())))
    raise FaultlineError('Publication not confirmed within two minutes; no readiness receipt created. Check publisher status before retrying.')


def fetch(store, *, repository, target_branch, base_ref, output, workflow=handoff.PUBLISHER, api=None):
    # Configuration/runtime errors remain fatal. Retrieval/identity failures alone
    # become a full manifest, including when an older output file already exists.
    config = load_config(store.root)
    head = handoff.revision(store.root)
    fallback = handoff.full_selection({'revision': head, 'config': fingerprint(config)}, config)
    selection, publication, reason = fallback, None, 'no_matching_publication'
    try:
        identity = handoff.snapshot(store.root, repository, target_branch, base_ref=base_ref)
        publication = lookup(api or GitHub(LOOKUP_SECONDS), identity, workflow)
        if publication:
            selection, reason = publication['selection'], 'matching_publication'
    except (FaultlineError, OSError, KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        reason = 'retrieval_or_validation_failed'
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_bytes(encode(selection) + b'\n')
    temporary.replace(path)
    return {'path': str(path), 'source': 'publication' if reason == 'matching_publication' else 'full_fallback',
            'reason': reason, 'artifact_id': publication['artifact_id'] if reason == 'matching_publication' else None,
            'suites': selection['suites'], 'revision': head, 'jev_requests': 0}
