"""Read a bounded artifact from an explicitly trusted push workflow and branch."""
import hashlib
import io
import zipfile
from datetime import datetime, timezone

from ..core import FaultlineError
from .common import revision
from .ci_handoff import repository_name, branch_name, origin
from .ci_publication import GitHub, trusted_origin
from .dependency_baseline import require_ancestor
from .dependency_shared import MAX_BYTES, load, restore, NO_EXECUTION

ARTIFACT = 'faultline-baseline-v1'
MAX_ARCHIVE = MAX_BYTES + 65536


def unpack(raw, artifact):
    if len(raw) > MAX_ARCHIVE or artifact.get('digest') != 'sha256:' + hashlib.sha256(raw).hexdigest():
        raise FaultlineError('Baseline archive is oversized or has an invalid digest')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) != 1 or entries[0].filename != 'baseline.json':
                raise FaultlineError('Baseline archive must contain only baseline.json')
            item = entries[0]
            if item.file_size > MAX_BYTES or item.flag_bits & 1 or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise FaultlineError('Invalid baseline archive entry')
            with archive.open(item) as stream:
                result = stream.read(MAX_BYTES + 1)
            if len(result) > MAX_BYTES:
                raise FaultlineError('Baseline archive entry exceeds limit')
            return result
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, ValueError, EOFError):
        raise FaultlineError('Invalid baseline archive') from None


def fetch(store, output, *, repository, workflow, branch, api=None):
    """A missing or rejected baseline is an observable cold start, never a skip."""
    try:
        return _fetch(store, output, repository=repository, workflow=workflow, branch=branch, api=api)
    except (FaultlineError, OSError, KeyError, TypeError, ValueError, AttributeError, RecursionError):
        return {'restored': False, 'reason': 'baseline_lookup_or_validation_failed', **NO_EXECUTION}


def _fetch(store, output, *, repository, workflow, branch, api):
    repository = repository_name(repository)
    branch_name(branch)
    if origin(store.root) != repository:
        raise FaultlineError('Baseline repository does not match checkout origin')
    api = api or GitHub(55, max_archive=MAX_ARCHIVE)
    repo, definition = trusted_origin(api, repository, workflow)
    prefix = 'repos/' + repository + '/actions/'
    # One page and at most ten candidates; old artifacts outside this window are
    # a cold start. No polling or unbounded history scan on every PR.
    listing = api.request(prefix + 'artifacts?name=' + ARTIFACT + '&per_page=30')
    rejected = 0
    for artifact in listing['artifacts'][:10]:
        if artifact['name'] != ARTIFACT or artifact['expired'] is not False:
            continue
        if type(artifact['id']) is not int or type(artifact['size_in_bytes']) is not int or not 0 < artifact['size_in_bytes'] <= MAX_ARCHIVE:
            continue
        summary = artifact['workflow_run']
        if summary.get('repository_id') != repo['id'] or summary.get('head_repository_id') != repo['id']:
            continue
        if type(summary.get('id')) is not int:
            continue
        run = api.request(prefix + 'runs/' + str(summary['id']))
        if (run['id'] != summary['id'] or run['workflow_id'] != definition['id'] or
                run['path'] != '.github/workflows/' + workflow or run['event'] != 'push' or
                run['head_branch'] != branch or run['status'] != 'completed' or
                run['conclusion'] not in ('success', 'failure') or
                run['repository']['id'] != repo['id'] or run['head_repository']['id'] != repo['id'] or
                run['head_sha'] != summary['head_sha']):
            continue
        if datetime.fromisoformat(artifact['expires_at'].replace('Z', '+00:00')) <= datetime.now(timezone.utc):
            continue
        try:
            require_ancestor(store.root, run['head_sha'], revision(store.root))
            raw = api.request(prefix + 'artifacts/' + str(artifact['id']) + '/zip', binary=True)
            data = unpack(raw, artifact)
            output.parent.mkdir(parents=True, exist_ok=True)
            # Download is evidence only. Nothing enters the cache until producer
            # identity, compatibility and ancestry all pass.
            output.write_bytes(data)
            value = load(store, output)
            meta = value['producer']
            expected = {'repository': repository, 'repository_id': repo['id'], 'workflow': workflow,
                        'run_id': run['id'], 'run_attempt': run['run_attempt'], 'event': 'push',
                        'branch': branch, 'revision': run['head_sha']}
            if any(meta.get(k) != v for k, v in expected.items()):
                raise FaultlineError('Baseline producer differs from authenticated CI run')
            return {**restore(store, output), 'artifact_id': artifact['id'], 'run_conclusion': run['conclusion'],
                    'rejected_candidates': rejected}
        except (FaultlineError, OSError, KeyError, TypeError, ValueError):
            rejected += 1
    return {'restored': False, 'reason': 'no_eligible_ancestor_baseline', 'rejected_candidates': rejected, **NO_EXECUTION}
