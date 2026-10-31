"""Bind generated-test judgments to the source and external inputs they saw."""
import hashlib
import json

from ..core import FaultlineError, digest
from .playwright_sources import artifact_file, validate

MAX_EVIDENCE_BYTES = 96000


def signature(mapping):
    # The execution manifest separately binds the destination revision. An
    # unchanged baseline may have been observed at an earlier ancestor.
    return digest({'contract': 'generation-decision-v1', 'source': mapping['source'],
                   'inputs': mapping['inputs'], 'artifacts': mapping.get('artifacts', {})})


def collect(source, graph, wanted):
    bindings, evidence, errors = {}, {}, {}
    verified, texts, artifacts = {}, {}, {}
    for target, observations in graph['observations'].items():
        mappings = {signature(row['generation']): row['generation'] for row in observations if row.get('generation')}
        if not mappings:
            continue
        try:
            for key, mapping in mappings.items():
                if key not in verified:
                    validate({**mapping, 'revision': source.revision}, source, mapping['source'])
                    verified[key] = mapping
            bindings[target] = sorted(mappings)
            if target not in wanted:
                continue
            names = sorted({name for mapping in mappings.values() for name in mapping['inputs']})
            files = {name: value for mapping in mappings.values() for name, value in mapping.get('artifacts', {}).items()}
            source.prefetch(names)
            used = 0
            for name in names:
                if name not in texts:
                    texts[name] = source.read(name).decode('utf-8')
                used += len(texts[name].encode('utf-8'))
                if used > MAX_EVIDENCE_BYTES:
                    raise FaultlineError('Generation evidence exceeds the assessment limit; no content was dropped')
            for name, expected in files.items():
                key = (name, expected)
                if key not in artifacts:
                    data = artifact_file(source.root, name).read_bytes()
                    if hashlib.sha256(data).hexdigest() != expected:
                        raise FaultlineError('Generation artifact changed while preparing assessment')
                    if used + len(data) > MAX_EVIDENCE_BYTES:
                        raise FaultlineError('Generation evidence exceeds the assessment limit; no content was dropped')
                    artifacts[key] = data.decode('utf-8')
                used += len(artifacts[key].encode('utf-8'))
                if used > MAX_EVIDENCE_BYTES:
                    raise FaultlineError('Generation evidence exceeds the assessment limit; no content was dropped')
            item = {'bindings': sorted(mappings), 'source': {name: texts[name] for name in names},
                    'artifacts': {name: artifacts[(name, files[name])] for name in sorted(files)},
                    'limitation': 'Declared generation inputs are not observed application-server coverage.'}
            if any('\0' in text for group in ('source', 'artifacts') for text in item[group].values()):
                raise FaultlineError('Binary generation evidence')
            if len(json.dumps(item, ensure_ascii=False).encode()) > MAX_EVIDENCE_BYTES:
                raise FaultlineError('Generation evidence exceeds the assessment limit; no content was dropped')
            evidence[target] = item
        except (FaultlineError, OSError, UnicodeError, ValueError, KeyError) as exc:
            errors[target] = str(exc)
    for row in graph['runtime_reuse']['invalidated']:
        if row.get('artifact_state') in ('missing_or_changed', 'historical', 'unverified'):
            errors[row['target']] = 'Generation artifact baseline needs fresh verified evidence'
    return {'bindings': bindings, 'evidence': evidence, 'errors': errors}


def check_native(units, expected):
    """Require exact declaration sets for artifact-dependent or bound targets."""
    actual, required = {}, set(expected)
    for unit in units.values():
        source = unit['source']
        for case in unit.get('locator', {}).get('native_cases', {}).values():
            mapping = case.get('generation')
            if mapping:
                actual.setdefault(source, set()).add(signature(mapping))
                if mapping.get('artifacts'):
                    required.add(source)
            elif source in expected:
                # A stamped test cannot become an unstamped case at execution.
                raise FaultlineError('Generated source declaration disappeared since assessment; keeping the full variant')
    if any(sorted(actual.get(source, ())) != expected.get(source) for source in required):
        raise FaultlineError('Generation inputs differ from the assessment-bound execution decision; keeping the full variant')
