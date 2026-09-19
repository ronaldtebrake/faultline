"""Import exact native outcomes after execution and report shadow measurements."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..core import FaultlineError, digest, now, number, read_json, write_json, write_text
from .common import checked, save_frozen, seal
from .runners import xml

STATUSES = {'passed', 'failed', 'error', 'skipped', 'unknown'}
CLASSES = {'confirmed_regression', 'flake', 'infrastructure', 'baseline', 'unknown'}


def junit(path, suite):
    if not Path(path).exists():
        return [], [{'reason': 'missing_junit_artifact'}]
    paths = sorted(Path(path).glob('*.xml')) if Path(path).is_dir() else [Path(path)]
    rows, unmatched = [], []
    members = {}
    for unit in suite['units']:
        for member in unit['members']:
            members.setdefault(member, []).append(unit['id'])
    for file in paths:
        try:
            tree = xml(file)
        except FaultlineError:
            unmatched.append({'file': file.name, 'reason': 'invalid_junit_artifact'})
            continue
        groups = [tree] if tree.tag == 'testsuite' else tree.findall('.//testsuite')
        for group in groups:
            for i, case in enumerate(group.findall('testcase')):
                name = case.get('name', '')
                if suite.get('runner') == 'behat':
                    source = group.get('file', '').replace('\\', '/')
                    member = f'{i}:{name}'
                    # Source suffix must match exactly one native unit; never fuzzy name-match.
                    ids = [u['id'] for u in suite['units'] if (source == u['source'] or source.endswith('/' + u['source'])) and member in u['members']]
                else:
                    member = case.get('classname', '') + '::' + name
                    ids = members.get(member, [])
                if len(ids) != 1:
                    unmatched.append({'name': name, 'classname': case.get('classname'), 'file': group.get('file')})
                    continue
                status = 'failed' if case.find('failure') is not None else ('error' if case.find('error') is not None else ('skipped' if case.find('skipped') is not None else 'passed'))
                try:
                    duration = float(case.get('time')) if case.get('time') is not None else None
                except ValueError:
                    raise FaultlineError('Invalid JUnit duration') from None
                rows.append({'id': ids[0], 'member': member, 'status': status, 'duration_seconds': duration,
                             'classification': 'unknown'})
    return rows, unmatched


def measure(selection, suite, receipt, tests, complete):
    selected = set(suite['proposed_selected'])
    failures = [t for t in tests if t['status'] in ('failed', 'error') and t['classification'] == 'confirmed_regression']
    caught = [t for t in failures if t['id'] in selected]
    timed = all(t['duration_seconds'] is not None for t in tests)
    avoided = sum(t['duration_seconds'] for t in tests if t['id'] not in selected) if timed and complete else None
    return {'inventory_units': len(suite['units']), 'proposed_selected_units': len(selected),
            'proposed_omitted_units': len(suite['proposed_omitted']), 'observed_members': len(tests),
            'expected_members': sum(len(u['members']) for u in suite['units']), 'outcomes_complete': complete,
            'confirmed_regression_members': len(failures), 'caught_regression_members': len(caught),
            'failing_test_recall': len(caught) / len(failures) if failures else None,
            'failing_change_recall': int(bool(caught)) if failures else None,
            'unknown_failures': sum(t['status'] in ('failed', 'error') and t['classification'] == 'unknown' for t in tests),
            'coverage': None, 'actual_execution_seconds': receipt['duration_seconds'],
            'actual_execution_avoided_seconds': 0, 'potential_serial_test_seconds_avoided': avoided,
            'selection_seconds': selection['selection_seconds'],
            'potential_serial_net_seconds': avoided - selection['selection_seconds'] if avoided is not None else None,
            'baselines': {name: {'selected_units': len(ids), 'caught_regression_members': sum(t['id'] in ids for t in failures),
                                  'failing_test_recall': sum(t['id'] in ids for t in failures) / len(failures) if failures else None}
                          for name, ids in suite.get('baselines', {}).items()}}


def record(store, selection_path, run_path, input_path=None, *, format=None, output=None):
    selection, receipt = checked(Path(selection_path), 'selection'), checked(Path(run_path), 'execution')
    if (receipt.get('selection_id') != selection['integrity'] or receipt.get('head') != selection['change']['head']
            or receipt.get('mode') != 'full_shadow'):
        raise FaultlineError('Outcomes must belong to a full shadow execution of this exact selection')
    suite = next((s for s in selection['suites'] if s['key'] == receipt['suite_key']), None)
    if suite is None:
        raise FaultlineError('Execution suite missing from selection')
    try:
        if not datetime.fromisoformat(selection['created_at']) <= datetime.fromisoformat(receipt['started_at']) <= datetime.fromisoformat(receipt['completed_at']):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise FaultlineError('Execution must start after the selection was frozen') from None
    native = next(s for s in selection['inventory']['suites'] if s['key'] == receipt['suite_key'])
    input_path = input_path or receipt.get('result_path')
    format = format or receipt.get('result_format') or 'json'
    if not input_path:
        raise FaultlineError('Provide --input or use run --junit-output to capture native results')
    if format == 'junit':
        rows, unmatched = junit(input_path, native)
        declared_complete = True
    else:
        data = read_json(Path(input_path))
        if not isinstance(data, dict) or data.get('selection_id') != selection['integrity'] or data.get('suite_key') != suite['key'] or not isinstance(data.get('tests'), list):
            raise FaultlineError('Results require selection_id, suite_key, and tests with exact native member IDs')
        rows, unmatched = data['tests'], []
        declared_complete = data.get('complete') is True
    expected = {(u['id'], member) for u in suite['units'] for member in u['members']}
    seen, tests = set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise FaultlineError('Invalid outcome record')
        if not all(isinstance(row.get(k), str) for k in ('id', 'member', 'status')):
            raise FaultlineError('Outcome identities and statuses must be strings')
        key = (row.get('id'), row.get('member'))
        if key not in expected or key in seen or row.get('status') not in STATUSES:
            raise FaultlineError('Unknown/duplicate native outcome or invalid status')
        seen.add(key)
        classification = row.get('classification', 'unknown')
        evidence = row.get('evidence', '')
        if not isinstance(classification, str) or not isinstance(evidence, str) or classification not in CLASSES or (classification != 'unknown' and (row['status'] not in ('failed', 'error') or not isinstance(evidence, str) or not evidence.strip())):
            raise FaultlineError('Failure classifications require a failed result and explicit evidence')
        duration = row.get('duration_seconds')
        if duration is not None:
            number(duration, 'duration_seconds', allow_zero=True)
        tests.append({'id': key[0], 'member': key[1], 'status': row['status'], 'classification': classification,
                      'evidence': evidence, 'duration_seconds': duration})
    tests.sort(key=lambda t: (t['id'], t['member']))
    complete = bool(expected) and declared_complete and expected == seen and not unmatched and native['complete'] and receipt['status'] == 'completed' and all(t['status'] != 'unknown' for t in tests)
    complete = complete and selection['workspace']['clean'] and selection['workspace']['head'] == selection['change']['head']
    # A crashed process with an all-passing partial report cannot claim full observations.
    if receipt['exit_code'] and not any(t['status'] in ('failed', 'error') for t in tests):
        complete = False
    policy_key = digest({'policy': selection['policy'], 'config': selection['config_hash'], 'evaluator': selection['evaluator']})
    record_key = receipt['integrity']
    input_hash = digest({'tests': tests, 'unmatched': unmatched, 'complete': complete})
    destination = store.path / 'observations' / (record_key + '.json')
    supersedes = None
    if destination.exists():
        revisions = [checked(p, 'observation') for p in destination.parent.glob(record_key + '*.json')]
        prior = max(revisions, key=lambda o: o['created_at'])
        if prior.get('input_hash') == input_hash:
            return write_report(store, prior, output=output)
        def raw_tests(values):
            return [{k: t[k] for k in ('id', 'member', 'status', 'duration_seconds')} for t in values]
        if raw_tests(prior['tests']) != raw_tests(tests) or prior['unmatched'] != unmatched or prior['metrics']['outcomes_complete'] != complete:
            raise FaultlineError('Raw execution outcomes are frozen; only evidence-based classifications can be revised')
        supersedes = prior['integrity']
        destination = store.path / 'observations' / (record_key + '.' + digest({'input': input_hash, 'supersedes': supersedes}) + '.json')
        if destination.exists():
            return write_report(store, checked(destination, 'observation'), output=output)
    observation = seal({'schema_version': 2, 'kind': 'observation', 'created_at': now(), 'input_hash': input_hash,
                        'selection_id': selection['integrity'], 'execution_id': receipt['integrity'], 'supersedes': supersedes,
                        'repository': selection['repository'], 'change': {k: selection['change'][k] for k in ('id', 'base', 'head')},
                        'policy_key': policy_key, 'policy': selection['policy'], 'suite_key': suite['key'],
                        'expected_suites': [s['key'] for s in selection['suites']],
                        'cost': selection['cost'], 'graph_seconds': selection['graph_seconds'],
                        'inference_seconds': selection['inference_seconds'],
                        'metrics': measure(selection, suite, receipt, tests, complete), 'tests': tests,
                        'units': [{'id': u['id'], 'source': u['source'], 'proposed_selected': u['id'] in suite['proposed_selected'],
                                   'reasons': suite['reasons'][u['id']], 'judgment': selection['judgments'].get(u['id']),
                                   'graph_paths': selection['graph']['paths'].get(u['source'], [])} for u in suite['units']],
                        'missing': [{'id': id, 'member': member} for id, member in sorted(expected - seen)],
                        'unmatched': unmatched, 'usage': selection['usage'], 'graph': selection['graph'],
                        'fallbacks': suite['fallbacks'], 'selection_seconds': selection['selection_seconds'],
                        'limitations': ['Static graph evidence and semantic relevance are not measured coverage.',
                                        'Shadow mode avoids no actual test execution.',
                                        'Potential timing assumes serial tests, unchanged durations, and zero setup savings; selection overhead is charged to this suite in full.',
                                        'Agent costs, setup/jobs avoided, parallel critical-path savings, and audit overhead are not measured.',
                                        'Recall is conditional on observed confirmed regressions; unexecuted tests are not passing.']})
    save_frozen(destination, observation)
    return write_report(store, observation, output=output)


def write_report(store, observation, *, output=None):
    m = observation['metrics']
    output = Path(output) if output else store.path / 'reports' / ('shadow-' + observation['execution_id'])
    def display(value):
        return 'unknown / not measured' if value is None else str(round(value, 4) if isinstance(value, float) else value)
    text = [f"# Faultline shadow report: {observation['suite_key']}", '',
            f"Revision: `{observation['change']['head']}`", '',
            '| Measurement | Value |', '| --- | --- |']
    text += [f'| {key.replace("_", " ")} | {display(value)} |' for key, value in m.items() if key != 'baselines']
    text += ['', '## Baselines at the same proposed unit count', '', '| Baseline | Selected units | Confirmed failures caught |', '| --- | --- | --- |']
    text += [f"| {name} | {v['selected_units']} | {v['caught_regression_members']} |" for name, v in m['baselines'].items()]
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    text += ['', '## Proposed execution units', '', '| Unit | Proposed | Jev relevance score | Reasons |', '| --- | --- | --- | --- |']
    for unit in sorted(observation['units'], key=lambda u: (-((u['judgment'] or {}).get('score', -1)), u['id'])):
        text.append(f"| {cell(unit['id'])} | {'run' if unit['proposed_selected'] else 'omit'} | {display((unit['judgment'] or {}).get('score'))} | {cell(', '.join(unit['reasons']))} |")
    omitted = {u['id'] for u in observation['units'] if not u['proposed_selected']}
    misses = [t for t in observation['tests'] if t['id'] in omitted and t['classification'] == 'confirmed_regression']
    text += ['', '## Observed missed regressions', '']
    text += [f"- {cell(t['id'])}: {cell(t['member'])}. Evidence: {cell(t['evidence'])}" for t in misses] or ['No confirmed missed regression observed; this is not evidence that selection is safe.']
    text += ['', '## Evidence and limits', '', f"Jev HTTP requests: {observation['usage']['requests']}; cached judgments: {observation['usage']['cache_hits']}.",
             '', f"Graph preparation: {observation['graph_seconds']:.3f}s; inference: {observation['inference_seconds']:.3f}s; input cost estimate: {observation['cost']['input_usd_estimate']}.", '', 'Fallbacks: ' + (', '.join(observation['fallbacks']) or 'none') + '.', '']
    text += ['- ' + item for item in observation['limitations']]
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output.with_suffix('.json'), observation)
    write_text(output.with_suffix('.md'), '\n'.join(text) + '\n')
    return {'json': str(output.with_suffix('.json').resolve()), 'markdown': str(output.with_suffix('.md').resolve()),
            'observation_id': observation['integrity'], 'metrics': m}


def report(store):
    observations = [checked(p, 'observation') for p in sorted((store.path / 'observations').glob('*.json'))]
    revision_count = len(observations)
    latest = {}
    for observation in observations:
        key = observation['execution_id']
        if key not in latest or observation['created_at'] > latest[key]['created_at']:
            latest[key] = observation
    observations = list(latest.values())
    groups = {}
    for o in observations:
        key = (o['repository'], o['change']['base'], o['change']['head'], o['policy_key'])
        groups.setdefault(key, []).append(o)
    cases = []
    for key, executions in groups.items():
        by_suite = {}
        for execution in executions:
            by_suite.setdefault(execution['suite_key'], []).append(execution)
        expected = set().union(*(set(a['expected_suites']) for a in executions))
        failed = {(t['id'], t['member']) for a in executions for t in a['tests'] if t['classification'] == 'confirmed_regression' and t['status'] in ('failed', 'error')}
        # Conservatively retain any observed miss across repeated attempts of a
        # suite. Detection in another suite can still catch this failing change.
        detected = []
        for attempts in by_suite.values():
            values = [a['metrics']['failing_change_recall'] for a in attempts if a['metrics']['failing_change_recall'] is not None]
            if values:
                detected.append(min(values))
        cases.append({'repository': key[0], 'base': key[1], 'head': key[2], 'policy_key': key[3],
                      'attempts': max(len(a) for a in by_suite.values()), 'executions': len(executions),
                      'suites': sorted(by_suite), 'missing_suites': sorted(expected - set(by_suite)),
                      'confirmed_regression_members': len(failed),
                      'failing_change_recall': int(any(detected)) if detected else None,
                      'complete': expected == set(by_suite) and all(a['metrics']['outcomes_complete'] for a in executions)})
    policies = {}
    for case in cases:
        p = policies.setdefault(case['policy_key'], {'cases': 0, 'eligible_regression_cases': 0, 'caught_cases': 0, 'incomplete_cases': 0})
        p['cases'] += 1
        p['incomplete_cases'] += int(not case['complete'])
        if case['complete'] and case['failing_change_recall'] is not None:
            p['eligible_regression_cases'] += 1
            p['caught_cases'] += case['failing_change_recall']
    for p in policies.values():
        n = p['eligible_regression_cases']
        p['failing_change_recall'] = p['caught_cases'] / n if n else None
        # Wilson interval: binomial descriptive uncertainty; cases may still be correlated.
        if n:
            z, rate = 1.96, p['failing_change_recall']
            center = (rate + z*z/(2*n))/(1+z*z/n)
            radius = z*((rate*(1-rate)/n + z*z/(4*n*n))**.5)/(1+z*z/n)
            p['wilson_95_interval'] = [max(0, center-radius), min(1, center+radius)]
        else:
            p['wilson_95_interval'] = None
    result = {'cases': cases, 'policies': policies, 'observations': len(observations), 'observation_revisions': revision_count,
              'limitations': ['Repeated attempts and suites are grouped by repository, PR snapshot, and compatible policy; each change counts once.',
                              'Recall uses complete cases with confirmed regressions; green cases do not establish recall.',
                              'Intervals are descriptive; changes from the same project can be correlated.']}
    write_json(store.path / 'reports/shadow-summary.json', result)
    lines = ['# Faultline shadow summary', '', f'{len(cases)} snapshot cases; {len(observations)} execution observations.', '',
             '| Policy | Eligible regression cases | Caught cases | Recall | 95% interval |', '| --- | --- | --- | --- | --- |']
    lines += [f"| {key[:12]} | {v['eligible_regression_cases']} | {v['caught_cases']} | {v['failing_change_recall']} | {v['wilson_95_interval']} |" for key, v in policies.items()]
    lines += ['', *('- ' + s for s in result['limitations'])]
    write_text(store.path / 'reports/shadow-summary.md', '\n'.join(lines) + '\n')
    return {**result, 'markdown': str(store.path / 'reports/shadow-summary.md')}
