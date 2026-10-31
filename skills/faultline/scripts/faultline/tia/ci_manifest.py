"""Small execution instructions; assessment evidence never travels to runners."""
import json
import math
import re
from pathlib import Path, PurePosixPath

from ..core import FaultlineError, digest
from .common import checked, revision, save_frozen, seal
from .config import load_config
from .evidence import GitSources

MAX_BYTES = 2 * 1024 * 1024
SUPPORTED = {'phpunit', 'behat', 'playwright'}


def fingerprint(config):
    # Inference tuning and local evaluator budgets do not change execution.
    return digest({k: config[k] for k in ('repository', 'scope', 'suites')})


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()


def shape(value):
    version = value.get('version') if isinstance(value, dict) else None
    fields = {'version', 'revision', 'config', 'suites'} | ({'generation'} if version == 2 else set())
    if not isinstance(value, dict) or set(value) != fields or type(version) is not int or version not in (1, 2):
        raise FaultlineError('Unsupported execution manifest')
    if not isinstance(value['revision'], str) or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', value['revision']):
        raise FaultlineError('Manifest needs an exact revision')
    if not isinstance(value['config'], str) or not re.fullmatch(r'[a-f0-9]{64}', value['config']) or not isinstance(value['suites'], dict):
        raise FaultlineError('Invalid manifest configuration or suites')
    for name, entry in value['suites'].items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or not isinstance(entry, dict):
            raise FaultlineError('Invalid suite entry')
        mode = entry.get('mode')
        if mode not in ('all', 'none', 'selected') or set(entry) != ({'mode', 'files'} if mode == 'selected' else {'mode'}):
            raise FaultlineError('Invalid suite mode')
        if mode == 'selected':
            files = entry['files']
            if not isinstance(files, list) or not files or not all(isinstance(p, str) for p in files) or files != sorted(set(files)):
                raise FaultlineError('Selected files must be nonempty, sorted and unique')
            for path in files:
                if (not path or path.startswith('/') or '\\' in path or ':' in path or
                        any(ord(c) < 32 for c in path) or any(x in ('', '.', '..') for x in path.split('/')) or
                        str(PurePosixPath(path)) != path):
                    raise FaultlineError('Manifest files must be canonical repository-relative paths')
    if version == 2:
        generation = value['generation']
        if not isinstance(generation, dict) or not generation:
            raise FaultlineError('Generation-bound decisions need suite bindings')
        for name, variants in generation.items():
            if name not in value['suites'] or not isinstance(variants, dict) or not variants:
                raise FaultlineError('Invalid generation suite bindings')
            for variant, sources in variants.items():
                if not isinstance(variant, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', variant) or not isinstance(sources, dict) or not sources:
                    raise FaultlineError('Invalid generation variant bindings')
                for path, signatures in sources.items():
                    if (not isinstance(path, str) or not path or path.startswith('/') or re.search(r'[\\:\x00-\x1f]', path) or
                            any(part in ('', '.', '..') for part in path.split('/')) or str(PurePosixPath(path)) != path or
                            not isinstance(signatures, list) or not signatures or
                            not all(isinstance(item, str) and re.fullmatch(r'[a-f0-9]{64}', item) for item in signatures) or
                            signatures != sorted(set(signatures))):
                        raise FaultlineError('Invalid generation source paths or signatures')
    if len(encode(value)) > MAX_BYTES:
        raise FaultlineError('Execution manifest exceeds size limit; no truncation allowed')
    return value


def read(path):
    try:
        with Path(path).open('rb') as f:
            raw = f.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError()
        def unique(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError('Duplicate JSON key')
                result[key] = value
            return result
        return shape(json.loads(raw, object_pairs_hook=unique))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise FaultlineError('Invalid execution manifest JSON') from None


def expand_prerequisites(entries, config):
    entries = {s['id']: dict(entries.get(s['id'], {'mode': 'all'})) for s in config['suites']}
    pending = [s['id'] for s in config['suites'] if entries[s['id']]['mode'] != 'none']
    configs = {s['id']: s for s in config['suites']}
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        for parent in configs[name]['prerequisites']:
            entries[parent] = {'mode': 'all'}
            pending.append(parent)
    return entries


def from_assessment(document, config, threshold):
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise FaultlineError('Threshold must be in (0, 1]')
    if document.get('kind') != 'impact-assessment' or document.get('evaluator') != 'noul-v1':
        raise FaultlineError('Export requires a noul-v1 assessment; Choice thresholds are a different policy')
    if document.get('execution_config') != fingerprint(config):
        raise FaultlineError('Execution configuration changed since assessment')
    entries, explanations = {}, {}
    from .dependency_semantics import actions as relationship_actions
    relationships = relationship_actions(document.get('relationship_evidence'))
    for suite in config['suites']:
        name = suite['id']
        snapshots = [s for s in document['suites'] if s['suite'] == name]
        reasons, files = [], set()
        if {s['variant'] for s in snapshots} != {v['id'] for v in suite['variants']}:
            reasons.append('missing_variant_evidence')
        if suite['runner'] not in SUPPORTED or suite['kind'] == 'check':
            reasons.append('runner_not_enabled_for_selection')
        for snapshot in snapshots:
            reasons.extend(snapshot['fallbacks'])
            if not snapshot['units']:
                reasons.append('empty_source_inventory')
            for unit in snapshot['units']:
                if unit['id'] in (document.get('dependency_evidence') or {}).get('selected', {}):
                    files.add(unit['source'])
                    continue
                action = relationships.get(unit['id'])
                if action:
                    if action == 'selected' or snapshot['reasons'].get(unit['id']):
                        files.add(unit['source'])
                    continue
                value = document['scores'].get(unit['id'])
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                    reasons.append('unresolved_assessment')
                elif value >= threshold or snapshot['reasons'].get(unit['id']):
                    files.add(unit['source'])
        entries[name] = ({'mode': 'all'} if reasons else
                         {'mode': 'selected', 'files': sorted(files)} if files else {'mode': 'none'})
        explanations[name] = sorted(set(reasons))
    before = entries
    entries = expand_prerequisites(entries, config)
    for name, entry in entries.items():
        if entry != before[name]:
            explanations[name].append('execution_prerequisite')
    generation = {}
    targets = {unit['id'] for snapshot in document['suites'] for unit in snapshot['units']}
    for target, signatures in (document.get('dependency_evidence') or {}).get('generation_bindings', {}).items():
        if target not in targets:
            raise FaultlineError('Generation binding is outside the assessed inventory')
        name, variant, source = target.split(':', 2)
        if entries[name]['mode'] != 'all':
            generation.setdefault(name, {}).setdefault(variant, {})[source] = signatures
    result = shape({'version': 2 if generation else 1, 'revision': document['revision'], 'config': fingerprint(config), 'suites': entries,
                    **({'generation': generation} if generation else {})})
    return result, explanations


def export(store, run_id, threshold, output):
    from .impact import assessment_path
    document = checked(assessment_path(store, run_id), 'impact-assessment')
    config = load_config(store.root)
    result, reasons = from_assessment(document, config, threshold)
    raw = encode(result)
    path = Path(output)
    if path.exists() and path.read_bytes().rstrip() != raw:
        raise FaultlineError('Refusing to replace an existing different execution manifest')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw + b'\n')
    evidence_path = record_export(store, document, threshold, result, reasons)
    return {'evidence': str(evidence_path), 'path': str(path), 'manifest_digest': digest(result), 'bytes': len(raw), 'suites': result['suites'], 'jev_requests': 0}


def record_export(store, document, threshold, result, reasons):
    identity = digest(result)
    explanation = seal({'schema_version': 2, 'kind': 'selection-export', 'manifest_digest': identity,
                        'assessment': document['integrity'], 'threshold': threshold, 'fallbacks': reasons})
    evidence_path = store.path / 'exports' / identity / (explanation['integrity'] + '.json')
    save_frozen(evidence_path, explanation)
    return evidence_path


def validate(store, path, *, clean=True):
    config = load_config(store.root)
    value = read(path)
    if value['config'] != fingerprint(config) or value['revision'] != revision(store.root):
        raise FaultlineError('Manifest revision/configuration differs from this checkout')
    if clean:
        from .common import git
        if git(store.root, 'status', '--porcelain', '--untracked-files=no'):
            raise FaultlineError('Tracked files differ from the tested revision')
    known = {s['id']: s for s in config['suites']}
    if set(value['suites']) - known.keys():
        raise FaultlineError('Unknown suite in execution manifest')
    source = GitSources(store.root, value['revision'])
    for name, entry in value['suites'].items():
        if entry['mode'] == 'selected':
            allowed = set(source.glob(known[name]['sources']))
            if set(entry['files']) - allowed:
                raise FaultlineError('Selected file is not a tracked configured source')
    for name, bindings in value.get('generation', {}).items():
        suite = known[name]
        if suite['runner'] != 'playwright' or set(bindings) - {variant['id'] for variant in suite['variants']}:
            raise FaultlineError('Generation bindings do not match configured Playwright variants')
        allowed = set(source.glob(suite['sources']))
        if any(set(paths) - allowed for paths in bindings.values()):
            raise FaultlineError('Generation binding is not a tracked configured source')
    return value, config


def resolve(store, path):
    config = load_config(store.root)
    try:
        value, config = validate(store, path)
        entries = expand_prerequisites(value['suites'], config)
        for suite in config['suites']:
            if suite['runner'] not in SUPPORTED or suite['kind'] == 'check':
                entries[suite['id']] = {'mode': 'all'}
        entries = expand_prerequisites(entries, config)
        return value, entries, []
    except (FaultlineError, OSError) as exc:
        return None, {s['id']: {'mode': 'all'} for s in config['suites']}, [str(exc)]
