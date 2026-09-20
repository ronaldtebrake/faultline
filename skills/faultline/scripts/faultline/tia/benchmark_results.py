"""Assess frozen benchmark policies using explicitly imported full-suite outcomes."""
from pathlib import Path

from ..core import FaultlineError, digest, now, number, read_json, write_text
from .common import checked, save_frozen, seal
from .proposals import cell


def assess(store, benchmark_path, outcomes_path, output=None, *, policy_comparison=None):
    case = checked(Path(benchmark_path), 'benchmark')
    comparison = None
    if policy_comparison:
        from .benchmark_policies import compare
        from .benchmark_report import routing_data
        comparison = read_json(Path(policy_comparison))
        if not isinstance(comparison, dict) or comparison.get('benchmark_id') != case['integrity']:
            raise FaultlineError('Policy comparison must name this exact frozen benchmark')
        expected_comparison = compare(case, routing_data(case), thresholds=comparison.get('thresholds'), budgets=comparison.get('file_budgets'))
        if comparison != expected_comparison:
            raise FaultlineError('Policy comparison does not match the frozen evidence and parameters; regenerate before inspecting outcomes')
    data = read_json(Path(outcomes_path))
    if not isinstance(data, dict) or data.get('schema_version') != 2 or data.get('benchmark_id') != case['integrity']:
        raise FaultlineError('Outcomes must name this exact frozen benchmark_id and schema_version 2')
    if data.get('repository') != case['repository'] or any(data.get(k) != case['change'][k] for k in ('base', 'head')):
        raise FaultlineError('Outcome repository/base/tested-head mismatch')
    if not isinstance(data.get('attempt_id'), str) or not data['attempt_id'] or not isinstance(data.get('outcome_blind'), bool):
        raise FaultlineError('Outcomes require an attempt_id and an explicit outcome_blind declaration')
    if not isinstance(data.get('complete'), bool) or not isinstance(data.get('inventory'), dict) or not isinstance(data.get('tests'), list):
        raise FaultlineError('Outcomes require complete, inventory, and tests')
    ids = {u['id'] for s in case['inventory']['suites'] for u in s['units']}
    expected = set()
    for unit, members in data['inventory'].items():
        if not isinstance(members, list) or not members or not all(isinstance(m, str) and m for m in members) or len(members) != len(set(members)):
            raise FaultlineError('Outcome inventory must map each execution unit to unique native test IDs')
        expected.update((unit, m) for m in members)
    seen, tests = set(), []
    for row in data['tests']:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k] for k in ('unit_id', 'test_id')):
            raise FaultlineError('Each result requires exact unit_id and native test_id')
        key = (row['unit_id'], row['test_id'])
        if key in seen:
            raise FaultlineError('Duplicate result within one CI attempt')
        seen.add(key)
        if row.get('status') not in ('passed', 'failed', 'skipped', 'unknown'):
            raise FaultlineError('Unsupported outcome status')
        kind = row.get('failure_kind', 'unknown' if row['status'] == 'failed' else None)
        if row['status'] == 'failed' and kind not in ('regression', 'flake', 'infrastructure', 'baseline', 'unknown'):
            raise FaultlineError('Classify failures as regression, flake, infrastructure, baseline, or unknown')
        if row['status'] == 'failed' and kind != 'unknown' and not (isinstance(row.get('evidence'), str) and row['evidence'].strip()):
            raise FaultlineError('A classified failure requires supporting evidence')
        duration = row.get('duration_seconds')
        if duration is not None:
            number(duration, 'duration_seconds', allow_zero=True)
        tests.append({**row, 'failure_kind': kind, 'duration_seconds': duration})
    unmatched = sorted(({unit for unit, _ in expected | seen}) - ids)
    missing_units = sorted(ids - set(data['inventory']))
    outcomes_complete = (data['complete'] and bool(expected) and expected == seen and not unmatched and not missing_units
                         and all(t['status'] in ('passed', 'failed') for t in tests))
    regressions = [t for t in tests if t['status'] == 'failed' and t['failure_kind'] == 'regression']
    statuses = {status: sum(t['status'] == status for t in tests) for status in ('passed', 'failed', 'skipped', 'unknown')}
    failures = {kind: sum(t['status'] == 'failed' and t['failure_kind'] == kind for t in tests)
                for kind in ('regression', 'flake', 'infrastructure', 'baseline', 'unknown')}
    # Partial decisions keep unknown tests would-run, which must not inflate recall claims.
    eligible = outcomes_complete and case['complete'] and data['outcome_blind']
    policies = {}
    for name, policy in case['policies'].items():
        selected = set(policy['would_run'])
        caught = [t for t in regressions if t['unit_id'] in selected]
        ranking = policy['ranking']
        cuts = sorted({min(n, len(ranking)) for n in (1, 5, 10, 20, 50, 100, len(ranking)) if ranking})
        policies[name] = {'selected_units': len(selected), 'known_regression_tests': len(regressions),
                          'caught_regression_tests': len(caught),
                          'failing_change_recall': int(bool(caught)) if eligible and regressions else None,
                          'failing_test_recall': len(caught) / len(regressions) if eligible and regressions else None,
                          'potential_serial_test_seconds_avoided': sum(t['duration_seconds'] for t in tests if t['unit_id'] not in selected)
                              if outcomes_complete and all(t['duration_seconds'] is not None for t in tests) else None,
                          'raw_ranking_recall_at_units': {str(n): sum(t['unit_id'] in set(ranking[:n]) for t in regressions) / len(regressions)
                                                         if eligible and regressions else None for n in cuts}}
    alternatives = {}
    if comparison:
        for scenario in comparison['scenarios']:
            for arm, proposal in scenario['approaches'].items():
                selected = {id for id, action in proposal['actions'].items() if action == 'RUN'}
                caught = [t for t in regressions if t['unit_id'] in selected]
                key = scenario['id'] + ':' + arm
                alternatives[key] = {
                    'scenario': scenario['label'], 'approach': arm, 'selected_units': len(selected),
                    'known_regression_tests': len(regressions), 'caught_regression_tests': len(caught),
                    'missed_regression_tests': [{k:t[k] for k in ('unit_id','test_id','evidence')} for t in regressions if t['unit_id'] not in selected],
                    'failing_change_recall': int(bool(caught)) if eligible and regressions else None,
                    'failing_test_recall': len(caught)/len(regressions) if eligible and regressions else None,
                    'potential_serial_test_seconds_avoided': sum(t['duration_seconds'] for t in tests if t['unit_id'] not in selected)
                        if outcomes_complete and all(t['duration_seconds'] is not None for t in tests) else None}
    detections = [{k: t[k] for k in ('unit_id', 'test_id', 'evidence')} | {
        'caught_by': [name for name, p in case['policies'].items() if t['unit_id'] in p['would_run']]}
        for t in regressions]
    observed_failures = []
    for test in tests:
        if test['status'] != 'failed':
            continue
        unit = test['unit_id']
        observed_failures.append({
            'unit_id': unit, 'test_id': test['test_id'], 'failure_kind': test['failure_kind'],
            'evidence': test.get('evidence'),
            'actions': {name: ('UNMAPPED' if unit not in ids else 'RUN' if unit in p['would_run'] else 'OMIT')
                        for name, p in case['policies'].items()},
            'counterfactual_actions': {
                scenario['id'] + ':' + arm: proposal['actions'].get(unit, 'UNMAPPED')
                for scenario in comparison['scenarios'] for arm, proposal in scenario['approaches'].items()
            } if comparison else {}})
    document = seal({'schema_version': 2, 'kind': 'benchmark-assessment', 'created_at': now(),
                     'benchmark_id': case['integrity'], 'benchmark_contract': case['contract'],
                     'repository': case['repository'], 'change': {k:case['change'][k] for k in ('id', 'base', 'head')},
                     'attempt_id': data['attempt_id'], 'outcome_blind_declared': data['outcome_blind'],
                     'outcomes_hash': digest(data), 'outcomes': data, 'outcomes_complete': outcomes_complete,
                     'benchmark_complete': case['complete'], 'eligible_for_recall': eligible,
                     'unmatched_units': unmatched, 'missing_units': missing_units, 'policies': policies,
                     'regression_detections': detections, 'observed_failure_detections': observed_failures,
                     'status_counts': statuses, 'failure_counts': failures,
                     'unknown_failures': sum(t['status'] == 'failed' and t['failure_kind'] == 'unknown' for t in tests),
                     'policy_comparison_id': comparison['comparison_id'] if comparison else None, 'counterfactual_policies': alternatives,
                     'coverage': None, 'measured_ci_savings_seconds': None,
                     'limitations': ['Outcome blindness and native inventory completeness are producer declarations, not independently proven by this importer.',
                                     'A green run has no regression denominator. Unknown, skipped, or unexecuted tests are not passing tests.',
                                     'Repeated attempts of the same snapshot are related observations, not independent regression cases.',
                                     'Raw equal-unit ranking cuts are diagnostic, without mandatory execution or prerequisite scheduling.',
                                     'Serial test time sums exclude setup, parallel scheduling, indexing, inference, and audit overhead; they are not measured CI savings.',
                                     'Natural selections include shared mandatory rules. Keep tuning cases separate from later assessment cases.']})
    path = Path(output) if output else store.path / 'benchmark-assessments' / (document['integrity'] + '.json')
    save_frozen(path, document)
    lines = [f"# Faultline benchmark assessment: {cell(case['change']['id'])}", '',
             f"CI attempt: {cell(data['attempt_id'])}. Complete outcomes: {outcomes_complete}. Eligible for recall: {eligible}.", '',
             '| Policy | Selected units | Confirmed regressions caught | Failing-change recall | Failing-test recall |',
             '| --- | --- | --- | --- | --- |']
    for name, m in policies.items():
        lines.append(f"| {name} | {m['selected_units']} | {m['caught_regression_tests']}/{m['known_regression_tests']} | {m['failing_change_recall']} | {m['failing_test_recall']} |")
    lines += ['', '## Observed failed tests', '',
              'These actions describe observed failures, including unclassified failures. They do not establish which failures were caused by the change.', '',
              '| Unit | Native test | Classification | Jev |',
              '| --- | --- | --- | --- |']
    for failure in observed_failures:
        lines.append('| ' + ' | '.join(cell(value) for value in [failure['unit_id'], failure['test_id'], failure['failure_kind'],
                     *(failure['actions'][name] for name in ('jev',))]) + ' |')
    if not observed_failures:
        lines.append('No failed tests were supplied; this does not establish that unreported tests passed.')
    lines += ['', 'The assessment JSON retains evidence and per-policy actions for every supplied failed test. UNMAPPED means the result cannot be linked to a configured unit.', '']
    lines += ['', '## Confirmed regression detections', '', '| Unit | Native test | Caught by |', '| --- | --- | --- |']
    for t in detections:
        lines.append(f"| {cell(t['unit_id'])} | {cell(t['test_id'])} | {cell(', '.join(t['caught_by']) or 'none')} |")
    lines += ['', '## Equal-sized raw rankings', '', '| Top units | Jev recall |', '| --- | --- |']
    for cut in policies['jev']['raw_ranking_recall_at_units']:
        lines.append('| ' + ' | '.join([cut, *(str(policies[name]['raw_ranking_recall_at_units'][cut]) for name in ('jev',))]) + ' |')
    if alternatives:
        lines += ['', '## Previously frozen policy experiments', '',
                  '| Policy | Approach | RUN files | Known regression tests caught | Failing-test recall | Potential serial seconds avoided |',
                  '| --- | --- | ---: | ---: | --- | --- |']
        for metrics in alternatives.values():
            lines.append('| ' + ' | '.join(map(str, [metrics['scenario'], metrics['approach'], metrics['selected_units'],
                f"{metrics['caught_regression_tests']}/{metrics['known_regression_tests']}", metrics['failing_test_recall'], metrics['potential_serial_test_seconds_avoided']])) + ' |')
        lines += ['', 'Exact missed native tests and their evidence are retained in the assessment JSON. Missing/contaminated evidence suppresses recall for every policy; repeated thresholds are not independent cases.', '']
    lines += ['', '## Observed outcomes', '',
              'Native test statuses: ' + ', '.join(f'{name}: {count}' for name, count in statuses.items()) + '.',
              'Failed-test classifications: ' + ', '.join(f'{name}: {count}' for name, count in failures.items()) + '.', '',
              '## Potential serial test work avoided', '',
              '| Policy | Seconds |', '| --- | --- |']
    for name, metrics in policies.items():
        seconds = metrics['potential_serial_test_seconds_avoided']
        lines.append(f"| {name} | {seconds if seconds is not None else 'unknown'} |")
    lines += ['', 'These sums exclude analysis, setup, scheduling, and audit overhead. They are not measured CI savings.']
    if unmatched or missing_units:
        lines += ['', f'Unmatched units: {cell(unmatched)}. Missing units: {cell(missing_units)}.']
    lines += ['', *('- ' + t for t in document['limitations'])]
    write_text(path.with_suffix('.md'), '\n'.join(lines) + '\n')
    return {'json': str(path.resolve()), 'markdown': str(path.with_suffix('.md').resolve()),
            'complete': outcomes_complete, 'eligible_for_recall': eligible, 'policies': policies, 'counterfactual_policies': alternatives, 'execution': 'none'}
