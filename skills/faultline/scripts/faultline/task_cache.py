"""Successful check-result reuse. Full execution is the default validation mode.

Cache directories are trusted inputs, not signatures. No build artifacts are
restored: only deterministic checks without required output side effects may opt in.
"""
import os
import hashlib
import signal
import subprocess
import time
from pathlib import Path

from .core import FaultlineError, now, write_json
from .task_graph import CONFIG, closure, git_bytes, snapshot
from .tia.common import checked, seal


def cache_directory(store, directory=None):
    return Path(directory).resolve() if directory else store.path / 'task-results'


def cached(directory, snap, task):
    if not task['cacheable']:
        return None, ','.join(task['gaps'])
    path = directory / (task['fingerprint'] + '.json')
    if not path.exists():
        return None, 'no_successful_result'
    try:
        record = checked(path, 'task-success')
        if (record.get('version') != 1 or record.get('repository') != snap['repository'] or
                record.get('engine') != snap['engine'] or record.get('task') != task['task'] or
                record.get('fingerprint') != task['fingerprint'] or record.get('exit_code') != 0 or
                record.get('status') != 'passed' or not isinstance(record.get('revision'), str) or
                not isinstance(record.get('created_at'), str) or
                type(record.get('duration_seconds')) not in (int, float) or record['duration_seconds'] < 0):
            raise FaultlineError('Incompatible result')
        return record, 'matching_successful_result'
    except (FaultlineError, OSError, ValueError):
        return None, 'invalid_result'


def preview(store, *, base=None, head='HEAD', tasks=(), cache_dir=None, environ=None):
    snap = snapshot(store.root, head, environ=environ)
    previous, base_warning = None, None
    if base:
        try:
            previous = snapshot(store.root, base, environ=environ)
        except FaultlineError:
            base_warning = 'base_task_graph_unavailable'
    directory = cache_directory(store, cache_dir)
    rows = []
    for name in closure(snap, tasks):
        task = snap['tasks'][name]
        prior = previous['tasks'].get(name) if previous else None
        record, reason = cached(directory, snap, task)
        changed_files = None
        if previous:
            old = {**previous['global_files'], **(prior['files'] if prior else {})}
            new = {**snap['global_files'], **task['files']}
            changed_files = sorted(p for p in old.keys() | new.keys() if old.get(p) != new.get(p))
        rows.append(dict(task=name, kind='check' if task['definition']['command'] else 'inputs',
            fingerprint=task['fingerprint'], input_count=len(task['files']),
            depends_on=list(task['dependencies']), cacheable=task['cacheable'], gaps=task['gaps'],
            changed=(prior is None or prior['fingerprint'] != task['fingerprint']) if previous else None,
            changed_inputs=changed_files, changed_dependencies=[d for d, key in task['dependencies'].items()
                if not prior or prior['dependencies'].get(d) != key] if previous else None,
            decision=('reuse' if record else 'run') if task['definition']['command'] else 'inputs',
            reason=reason if task['definition']['command'] else 'dependency_fingerprint',
            previous_result={k: record[k] for k in ('revision', 'created_at', 'duration_seconds')} if record else None))
    return seal(dict(schema_version=2, kind='task-plan', version=1, repository=snap['repository'],
        revision=snap['revision'], base_revision=previous['revision'] if previous else None,
        base_warning=base_warning, tasks=rows, unmapped_files=snap['unmapped_files'],
        cache_key=snap['engine'] + '-' + hashlib.sha256(
            ''.join(r['fingerprint'] for r in rows).encode()).hexdigest(),
        cache_namespace=hashlib.sha256((snap['repository'] + snap['engine'] + '\n'.join(r['task'] for r in rows)).encode()).hexdigest(),
        execution='none', omission_authorized=False, jev_requests=0))


def clean(root):
    if git_bytes(root, 'status', '--porcelain', '--untracked-files=normal').strip():
        raise FaultlineError('Task execution requires a clean committed checkout; ignore generated files explicitly')


def materialized(root, snap, names):
    files = dict(snap['global_files'])
    for name in names:
        files.update(snap['tasks'][name]['files'])
    if any(not (root / path).exists() for path in files):
        raise FaultlineError('Task execution requires materialized input files; a sparse checkout is insufficient')


def execute(command, cwd, env, log, timeout):
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=os.name == 'posix')
    try:
        return process.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()
        raise


def run(store, *, tasks=(), cache_dir=None, reuse=False, output=None, environ=None):
    store.initialize()
    clean(store.root)
    env = dict(os.environ if environ is None else environ)
    snap = snapshot(store.root, environ=env)
    names = closure(snap, tasks)
    materialized(store.root, snap, names)
    directory = cache_directory(store, cache_dir)
    folder = Path(output).resolve() if output else store.path / 'task-runs' / str(time.time_ns())
    if folder.exists():
        raise FaultlineError('Use a fresh task run output directory')
    folder.mkdir(parents=True)
    plan = preview(store, tasks=tasks, cache_dir=directory, environ=env)
    write_json(folder / 'plan.json', plan)
    results = []
    failed = set()
    for name in names:
        task = snap['tasks'][name]
        command = task['definition']['command']
        if any(d in failed for d in task['dependencies']):
            failed.add(name)
            results.append(dict(task=name, status='blocked', reason='dependency_failed'))
            continue
        if not command:
            results.append(dict(task=name, status='inputs'))
            continue
        clean(store.root)
        current = snapshot(store.root, environ=env)
        if current['revision'] != snap['revision']:
            raise FaultlineError('Checkout changed during task execution')
        record, reason = cached(directory, snap, task)
        if reuse and record:
            results.append(dict(task=name, status='reused', fingerprint=task['fingerprint'],
                                origin=record['revision'], duration_seconds=0))
            continue
        cwd = (store.root / task['definition']['cwd']).resolve()
        if not cwd.is_relative_to(store.root) or not cwd.is_dir():
            raise FaultlineError('Task working directory must exist inside the repository')
        started = time.monotonic()
        error = None
        try:
            with (folder / (name + '.log')).open('wb') as log:
                code = execute(command, cwd, env, log, task['definition']['timeout_seconds'])
        except subprocess.TimeoutExpired:
            code, error = 124, 'timeout'
        except OSError:
            code, error = 127, 'command_unavailable'
        duration = time.monotonic() - started
        # A successful command that changed tracked inputs cannot certify its
        # pre-execution fingerprint. Keep its result but never cache it.
        stable = True
        try:
            clean(store.root)
            current = snapshot(store.root, environ=env)
            stable = current['revision'] == snap['revision'] and current['tasks'][name]['fingerprint'] == task['fingerprint']
        except FaultlineError:
            stable = False
        if code or not stable:
            failed.add(name)
            if task['cacheable']:
                # Publish a rejection in newer shared snapshots as well. Removing
                # a file alone could leave an older success in a merged cache.
                write_json(directory / (task['fingerprint'] + '.json'), seal(dict(
                    schema_version=2, kind='task-rejection', fingerprint=task['fingerprint'],
                    task=name, revision=snap['revision'], status='failed', created_at=now())))
        row = dict(task=name, fingerprint=task['fingerprint'], status='passed' if code == 0 and stable else 'failed',
                   exit_code=code, duration_seconds=duration, cache_match_before_run=bool(record),
                   cache_reason=reason, error=error if stable else 'inputs_changed_during_execution')
        if code == 0 and stable and task['cacheable']:
            value = seal(dict(schema_version=2, kind='task-success', version=1, repository=snap['repository'],
                engine=snap['engine'], task=name, fingerprint=task['fingerprint'], revision=snap['revision'],
                status='passed', exit_code=0, created_at=now(), duration_seconds=duration,
                producer={k: env[k] for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB', 'GITHUB_SHA') if k in env}))
            write_json(directory / (task['fingerprint'] + '.json'), value)
        results.append(row)
        write_json(folder / 'progress.json', results)
    result = seal(dict(schema_version=2, kind='task-run', version=1, revision=snap['revision'],
        mode='reuse' if reuse else 'shadow', tasks=results, exit_code=1 if failed else 0,
        jev_requests=0, output=str(folder)))
    write_json(folder / 'result.json', result)
    return result


def markdown(plan):
    lines = ['# Faultline task inputs — full CI retained', '',
             '| Task | Would do with reuse enabled | Inputs changed | Reason |', '| --- | --- | --- | --- |']
    for row in plan['tasks']:
        lines.append(f"| {row['task']} | {row['decision']} | {row['changed']} | {row['reason']} |")
    lines += ['', f"Unmapped files treated as global inputs: {len(plan['unmapped_files'])}.",
              'Matching inputs rely on the declared dependency contract. No scenario coverage is inferred.']
    return '\n'.join(lines) + '\n'


def run_markdown(result):
    lines = ['# Faultline task execution', '', f"Mode: **{result['mode']}**", '',
             '| Task | Actual result | Cache matched before full run | Seconds |', '| --- | --- | --- | --- |']
    for row in result['tasks']:
        lines.append(f"| {row['task']} | {row['status']} | {row.get('cache_match_before_run', '')} | {row.get('duration_seconds', 0):.3f} |")
    return '\n'.join(lines) + '\n'
