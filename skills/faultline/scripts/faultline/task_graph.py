"""Framework-independent task input contracts over immutable Git trees."""
import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path, PurePosixPath

from .core import FaultlineError, digest
from .tia.common import revision
from .tia.config import matches, repository_identity

VERSION = 1
CONFIG = 'faultline.json'


def git_bytes(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
    if result.returncode:
        raise FaultlineError('Cannot read the task graph Git snapshot')
    return result.stdout


def tree(root, ref):
    files = {}
    for entry in git_bytes(root, 'ls-tree', '-rz', '--full-tree', ref).split(b'\0'):
        if entry:
            meta, path = entry.split(b'\t', 1)
            mode, kind, oid = meta.decode().split()
            files[path.decode('utf-8')] = {'mode': mode, 'oid': oid}
    return files


def strings(value, label):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x or '\0' in x for x in value):
        raise FaultlineError(f'{label} must be an array of nonempty strings')
    return value


def patterns(value, label):
    result = strings(value, label)
    for pattern in result:
        if (pattern.startswith(('!', '/')) or '\\' in pattern or
                '..' in PurePosixPath(pattern).parts or any(ord(c) < 32 for c in pattern)):
            raise FaultlineError(f'{label} needs positive repository-relative patterns')
    return sorted(set(result))


def load(root, ref):
    try:
        raw = json.loads(git_bytes(root, 'show', f'{ref}:{CONFIG}'))
    except (ValueError, UnicodeError):
        raise FaultlineError('Invalid committed faultline.json') from None
    if not isinstance(raw, dict) or raw.get('schema_version') != 2:
        raise FaultlineError('Tasks require faultline.json schema_version 2')
    graph = raw.get('task_graph')
    if not isinstance(graph, dict) or graph.get('version') != VERSION:
        raise FaultlineError('Configure task_graph version 1 in faultline.json and commit it')
    if set(graph) - {'version', 'tasks', 'global_inputs', 'ignored_inputs', 'env', 'context'}:
        raise FaultlineError('Unknown task_graph field')
    tasks = graph.get('tasks')
    if not isinstance(tasks, dict) or not tasks:
        raise FaultlineError('task_graph.tasks must be a nonempty object')
    context = graph.get('context', {})
    if (not isinstance(context, dict) or
            any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in context.items())):
        raise FaultlineError('task_graph.context must map names to nonempty runtime/fixture identity strings')
    normalized = {}
    for name, task in tasks.items():
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', name) or not isinstance(task, dict):
            raise FaultlineError('Invalid task name or definition')
        if set(task) - {'inputs', 'depends_on', 'command', 'cwd', 'env', 'cache', 'timeout_seconds', 'description'}:
            raise FaultlineError(f'Unknown task field: {name}; output-producing task reuse is not supported')
        command = strings(task.get('command', []), 'command')
        cwd = task.get('cwd', '.')
        if (not isinstance(cwd, str) or not cwd or '\\' in cwd or '\0' in cwd or
                PurePosixPath(cwd).is_absolute() or '..' in PurePosixPath(cwd).parts):
            raise FaultlineError('Task cwd must stay inside the repository')
        cache = task.get('cache', False) if command else True
        if type(cache) is not bool:
            raise FaultlineError('Task cache must be a boolean')
        if command and cache and (not context or 'env' not in task):
            raise FaultlineError('Cacheable checks need a nonempty runtime context and an explicit env list')
        timeout = task.get('timeout_seconds', 3600)
        if type(timeout) is not int or not 1 <= timeout <= 86400:
            raise FaultlineError('Task timeout_seconds must be between 1 and 86400')
        normalized[name] = dict(inputs=patterns(task.get('inputs', ['**']), 'inputs'),
            depends_on=sorted(set(strings(task.get('depends_on', []), 'depends_on'))),
            command=command, cwd=cwd, env=strings(task.get('env', []), 'env'),
            cache=cache, timeout_seconds=timeout)
    order = []
    def visit(name, active):
        if name not in normalized:
            raise FaultlineError(f'Unknown task dependency: {name}')
        if name in active:
            raise FaultlineError('Task dependency cycle')
        if name in order:
            return
        for dependency in normalized[name]['depends_on']:
            visit(dependency, active | {name})
        order.append(name)
    for name in sorted(normalized):
        visit(name, set())
    env = strings(graph.get('env', []), 'env')
    for key in [*env, *(key for task in normalized.values() for key in task['env'])]:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise FaultlineError('Invalid environment variable name')
    repo = raw.get('repository') or repository_identity(root)
    if not isinstance(repo, str) or not repo:
        raise FaultlineError('repository must be a nonempty string')
    return dict(tasks=normalized, order=order, context=context, env=env, repository=repo,
        global_inputs=patterns(graph.get('global_inputs', []), 'global_inputs'),
        ignored_inputs=patterns(graph.get('ignored_inputs', []), 'ignored_inputs'))


def engine_identity():
    # Changes to this execution/cache contract invalidate results, independently
    # of source analysis and optional evaluator code.
    return digest({name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                   for name in ('task_graph.py', 'task_cache.py', 'core.py', 'tia/common.py', 'tia/config.py')})


def snapshot(root, ref='HEAD', *, environ=None):
    env = os.environ if environ is None else environ
    commit = revision(root, ref)
    config = load(root, commit)
    files = tree(root, commit)
    owned = {p for p in files if any(matches(p, t['inputs']) for t in config['tasks'].values())}
    globals_ = {p: v for p, v in files.items() if p == CONFIG or matches(p, config['global_inputs']) or
                (p not in owned and not matches(p, config['ignored_inputs']))}
    unmapped = sorted(p for p in globals_ if p != CONFIG and p not in owned and not matches(p, config['global_inputs']))
    def environment(names):
        missing = sorted(set(names) - env.keys())
        if missing:
            raise FaultlineError('Missing declared task environment: ' + ', '.join(missing))
        # Reports and cache records contain no environment values.
        return digest({name: env[name] for name in sorted(set(names))})
    engine = engine_identity()
    global_key = digest(dict(files=globals_, context=config['context'], env=environment(config['env']),
                            platform=[platform.system(), platform.machine()]))
    tasks = {}
    for name in config['order']:
        task = config['tasks'][name]
        inputs = {p: v for p, v in files.items() if matches(p, task['inputs'])}
        deps = {d: tasks[d]['fingerprint'] for d in task['depends_on']}
        gaps = []
        if task['command'] and not task['cache']:
            gaps.append('cache_disabled')
        if any(v['mode'] not in ('100644', '100755') for v in {**globals_, **inputs}.values()):
            gaps.append('symlink_or_submodule_input')
        if any(tasks[d]['gaps'] for d in deps):
            gaps.append('uncacheable_dependency')
        key = digest(dict(version=VERSION, engine=engine, repository=config['repository'], task=name,
                          definition=task, inputs=inputs, dependencies=deps, global_key=global_key,
                          environment=environment(task['env'])))
        tasks[name] = dict(task=name, fingerprint=key, definition=task, files=inputs,
                           dependencies=deps, gaps=gaps, cacheable=not gaps)
    return dict(repository=config['repository'], revision=commit, engine=engine, tasks=tasks,
                order=config['order'], global_files=globals_, unmapped_files=unmapped)


def closure(snapshot_, requested=()):
    chosen = set()
    def visit(name):
        if name not in snapshot_['tasks']:
            raise FaultlineError(f'Unknown task: {name}')
        if name in chosen:
            return
        chosen.add(name)
        for dep in snapshot_['tasks'][name]['dependencies']:
            visit(dep)
    for name in requested or snapshot_['order']:
        visit(name)
    return [name for name in snapshot_['order'] if name in chosen]
