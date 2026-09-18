"""Outcome comparison and baselines: deterministic evidence, separate from Jev."""
from __future__ import annotations

import math
import random
import re
from collections import Counter
from pathlib import PurePosixPath

from .core import SCHEMA, FaultlineError, digest, now, number, read_json, required_string, write_json, write_text
from .workflow import load_prediction

CLASSIFICATIONS = ("confirmed_regression", "likely_flake", "infrastructure", "baseline", "unknown")
STATUSES = ("passed", "failed", "error", "skipped", "unknown")
CUTOFFS = (1, 5, 10, 20, 50)


def tokens(text):
    return Counter(re.findall(r"[a-z0-9_]+", text.lower()))


def cosine(a, b):
    norm = math.sqrt(sum(v*v for v in a.values()) * sum(v*v for v in b.values()))
    return sum(v*b.get(k, 0) for k, v in a.items()) / norm if norm else 0


def baselines(prediction, seed):
    profiles = prediction['profiles']
    change = prediction['change']
    words = tokens(change['title'] + '\n' + change['description'] + '\n' + change['diff'])
    lexical = sorted(profiles, key=lambda p: (-cosine(words, tokens(p['description'])), p['id']))
    def proximity(profile):
        parent = PurePosixPath(profile['source']).parts[:-1]
        best = 0
        for file in change['changed_files']:
            shared = 0
            for a, b in zip(parent, PurePosixPath(file).parts[:-1]):
                if a != b:
                    break
                shared += 1
            best = max(best, shared)
        return best
    paths = sorted(profiles, key=lambda p: (-proximity(p), p['id']))
    randomized = sorted(p['id'] for p in profiles)
    random.Random(seed).shuffle(randomized)
    return {"semantic": [r['id'] for r in prediction['ranking']],
            "lexical": [p['id'] for p in lexical], "path": [p['id'] for p in paths], "random": randomized}


def validate_outcomes(data, prediction):
    if not isinstance(data, dict) or data.get('schema_version') != SCHEMA:
        raise FaultlineError('Outcomes require schema_version: 1')
    if data.get('prediction_id') != prediction['prediction_id']:
        raise FaultlineError('Outcomes refer to a different prediction')
    required_string(data, 'collected_at')
    from datetime import datetime
    try:
        collected = datetime.fromisoformat(data['collected_at'].replace('Z', '+00:00'))
        frozen = datetime.fromisoformat(prediction['created_at'])
        if collected.tzinfo is None or collected < frozen:
            raise ValueError()
    except (ValueError, TypeError):
        raise FaultlineError('Outcome collection must be timestamped after the frozen prediction (include timezone)') from None
    required_string(data, 'reviewer')
    if not isinstance(data.get('runs'), list):
        raise FaultlineError('Outcomes require a runs array')
    seen = set()
    for run in data['runs']:
        for key in ('id', 'snapshot', 'status'):
            required_string(run, key)
        attempt = run.get('attempt', 1)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise FaultlineError('Run attempt must be a positive integer')
        key = (run['id'], attempt)
        if key in seen:
            raise FaultlineError('Duplicate run/attempt in outcomes')
        seen.add(key)
        if not isinstance(run.get('tests'), list):
            raise FaultlineError('Each run needs a tests array (empty when results are unavailable)')
        if run.get('execution', 'unknown') not in ('serial', 'parallel', 'unknown'):
            raise FaultlineError('execution must be serial, parallel, or unknown')
        ids = set()
        for test in run['tests']:
            required_string(test, 'id')
            if test['id'] in ids:
                raise FaultlineError('Duplicate test ID within run; use distinct runner identities or separate job IDs')
            ids.add(test['id'])
            if test.get('status') not in STATUSES:
                raise FaultlineError('Unknown test outcome status')
            label = test.get('classification', 'unknown')
            if label not in CLASSIFICATIONS:
                raise FaultlineError('Unknown failure classification')
            if label != 'unknown':
                required_string(test, 'evidence')
                if test['status'] not in ('failed', 'error'):
                    raise FaultlineError('Failure classifications only apply to failed/error tests')
            if test.get('duration_seconds') is not None:
                number(test['duration_seconds'], 'duration_seconds', allow_zero=True)
        if 'execution_order' in run:
            order = run['execution_order']
            if not isinstance(order, list) or not all(isinstance(i, str) for i in order) or len(order) != len(set(order)):
                raise FaultlineError('execution_order must contain unique test IDs')
    return data


def metrics(order, failures, durations=None):
    positions = {test: i for i, test in enumerate(order, 1)}
    known = [positions[f] for f in failures if f in positions]
    first = min(known) if known else None
    values = {"first_failure_rank": first, "known_failures": len(failures),
              "hit_at": {str(k): int(any(p <= k for p in known)) for k in CUTOFFS},
              "recall_at": {str(k): sum(p <= k for p in known) / len(failures) if failures else None for k in CUTOFFS},
              "serial_seconds_to_failure": None}
    if first and durations is not None and all(durations.get(i) is not None for i in order[:first]):
        values['serial_seconds_to_failure'] = sum(durations[i] for i in order[:first])
    return values


def compare_run(run, prediction, orders, eligible_prediction):
    catalog = {p['id'] for p in prediction['profiles']}
    unknown_ids = sorted({t['id'] for t in run['tests']} - catalog)
    labels = Counter(t.get('classification', 'unknown') for t in run['tests'] if t['status'] in ('failed', 'error'))
    failures = sorted({t['id'] for t in run['tests'] if t['status'] in ('failed', 'error') and t.get('classification') == 'confirmed_regression'})
    exclusions = []
    if not eligible_prediction:
        exclusions.append('Prediction is partial or lacks outcome-blind historical provenance')
    if run['snapshot'] != prediction['change']['snapshot']:
        exclusions.append('Tested snapshot does not match prediction')
    if run.get('status') != 'completed':
        exclusions.append('Run did not complete; retained as incomplete evidence')
    if not failures:
        exclusions.append('No confirmed regression to assess')
    if any(f not in catalog for f in failures):
        exclusions.append('Confirmed failing tests are missing from the catalog; excluded to avoid optimistic recall')
    eligible = not exclusions
    result = {'id': run['id'], 'attempt': run.get('attempt', 1), 'snapshot': run['snapshot'],
              'status': run['status'], 'eligible': eligible, 'exclusions': exclusions,
              'classification_counts': dict(labels), 'unmatched_tests': unknown_ids,
              'matched_tests': sum(t['id'] in catalog for t in run['tests']), 'reported_tests': len(run['tests']),
              'failures': failures, 'metrics': {}, 'started_at': run.get('started_at'),
              'notes': run.get('notes', []), 'timing_assumption': 'Serial cumulative durations; not observed CI wall-clock time.'}
    if not eligible:
        return result
    durations = {t['id']: t.get('duration_seconds') for t in run['tests'] if t['status'] != 'skipped'}
    execution_order = run.get('execution_order', [])
    local_orders = dict(orders)
    if run.get('order_verified') is True and set(execution_order) == catalog:
        local_orders['historical'] = execution_order
    else:
        result['historical_order_unavailable'] = 'A verified execution order covering the same catalog was not supplied'
    for method, order in local_orders.items():
        result['metrics'][method] = metrics(order, failures, durations)
    # Comparing serial sums is useful; calling that a speedup of a parallel CI run is not.
    result['wall_clock_comparison_allowed'] = run.get('execution') == 'serial' and 'historical' in local_orders
    result['worst_misses'] = sorted([{'id': f, 'rank': orders['semantic'].index(f) + 1} for f in failures], key=lambda r: -r['rank'])
    return result


def evaluate(store, prediction_file, outcomes_file, config):
    prediction = load_prediction(prediction_file)
    if not prediction['complete']:
        raise FaultlineError('Finish the prediction before revealing historical outcomes; partial rankings cannot be evaluated')
    outcomes = validate_outcomes(read_json(outcomes_file), prediction)
    provenance = prediction['change']['provenance']
    eligible = provenance.get('historical') is True and provenance.get('outcomes_seen') is False and provenance.get('context_verified') is True
    orders = baselines(prediction, config['random_seed'])
    runs = [compare_run(run, prediction, orders, eligible) for run in outcomes['runs']]
    usable = [run for run in runs if run['eligible']]
    # Selection uses evidence timing, never a favorable semantic score; reruns count once.
    selected = min(usable, key=lambda r: (r['started_at'] or '', r['id'], r['attempt'])) if usable else None
    identifier = digest({'prediction': prediction['integrity'], 'outcomes': outcomes,
                         'seed': config['random_seed'], 'evaluation_schema': SCHEMA})
    path = store.path / 'evaluations' / identifier
    findings = {'schema_version': SCHEMA, 'evaluation_id': identifier, 'prediction_id': prediction['prediction_id'],
                'prediction_integrity': prediction['integrity'], 'repository': prediction['change']['repository'],
                'change_id': prediction['change']['id'], 'snapshot': prediction['change']['snapshot'],
                'evaluator': prediction['evaluator'], 'index_hash': prediction['index_hash'],
                'created_at': now(), 'reviewer': outcomes['reviewer'], 'runs': runs, 'selected_run': selected,
                'assessment': 'exploratory_case' if selected else 'not_assessable',
                'baseline_orders': orders, 'random_seed': config['random_seed'],
                'ranking': prediction['ranking'], 'profiles': prediction['profiles'],
                'change': prediction['change'], 'limitations': prediction['limitations'],
                'usage': {'requests': prediction['requests_this_run'], 'cache_hits': prediction['cache_hits'],
                          'cost': None, 'model_usage': [r.get('usage') for r in prediction['ranking']]}}
    if not (path / 'findings.json').exists():
        write_json(path / 'outcomes.json', outcomes)
        write_json(path / 'findings.json', findings)
    else:
        findings = read_json(path / 'findings.json')
    from .report import case_markdown
    write_json(path / 'report.json', findings)
    write_text(path / 'report.md', case_markdown(findings))
    write_json(store.path / 'evaluations' / 'latest' / (prediction['prediction_id'] + '.json'), {'evaluation_id': identifier})
    return {'evaluation_id': identifier, 'assessment': findings['assessment'], 'report': str(path / 'report.md'),
            'json': str(path / 'report.json')}
