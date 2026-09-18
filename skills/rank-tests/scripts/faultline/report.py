"""Offline reports generated from persisted evidence, with explicit denominators."""
from __future__ import annotations

import html
import math
import statistics

from .core import FaultlineError, digest, read_json, write_json, write_text
from .evaluation import CUTOFFS


def md(value):
    return html.escape(str(value), quote=False).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ').replace('`', '&#96;')


def case_markdown(findings):
    lines = [f"# Faultline: {md(findings['change_id'])}", '',
             f"Repository: {md(findings['repository'])}",
             f"Snapshot: {md(findings['snapshot'])}",
             f"Prediction: {findings['prediction_id']}",
             f"Model: {md(findings['evaluator']['model'])}", '',
             'This is one exploratory case, not evidence of general regression-detection performance.', '',
             '## Assessment', '']
    selected = findings['selected_run']
    if not selected:
        lines += ['Regression-detection performance cannot be assessed from the supplied evidence.',
                  'Missing or unclassified evidence is not a passing result.']
    else:
        lines += [f"Selected run: {md(selected['id'])}, attempt {selected['attempt']}. Reruns do not count as additional regressions.", '',
                  '| Method | First failing rank | Hit @5 | Failing-test recall @10 | Serial seconds to first failure |',
                  '| --- | ---: | ---: | ---: | ---: |']
        for method, values in selected['metrics'].items():
            seconds = values['serial_seconds_to_failure']
            lines.append(f"| {md(method)} | {values['first_failure_rank']} | {values['hit_at']['5']} | {values['recall_at']['10']:.2%} | {f'{seconds:.2f}' if seconds is not None else 'unavailable'} |")
        lines += ['', 'Timing uses serial sums of available test durations. Queue delays and CI downtime are excluded.']
        if not selected['wall_clock_comparison_allowed']:
            lines.append('These estimates do not establish a wall-clock improvement over parallel or unknown CI scheduling.')
        if selected.get('historical_order_unavailable'):
            lines.append(selected['historical_order_unavailable'] + '.')
    lines += ['', '## Evidence coverage', '', '| Run / attempt | Status | Matched / reported | Included | Exclusions |',
              '| --- | --- | ---: | --- | --- |']
    for run in findings['runs']:
        lines.append(f"| {md(run['id'])} / {run['attempt']} | {md(run['status'])} | {run['matched_tests']} / {run['reported_tests']} | {'yes' if run['eligible'] else 'no'} | {md('; '.join(run['exclusions']))} |")
        if run['classification_counts']:
            lines.append('')
            lines.append(f"Classifications for {md(run['id'])}: {md(run['classification_counts'])}.")
            lines.append('')
    lines += ['', '## Worst misses', '']
    profiles = {p['id']: p for p in findings['profiles']}
    scores = {r['id']: r for r in findings['ranking']}
    misses = [(run, miss) for run in findings['runs'] if run['eligible'] for miss in run.get('worst_misses', [])]
    if not misses:
        lines.append('No eligible confirmed failures to inspect.')
    seen = set()
    for run, miss in sorted(misses, key=lambda pair: -pair[1]['rank']):
        if miss['id'] in seen:
            continue
        seen.add(miss['id'])
        row, profile = scores[miss['id']], profiles[miss['id']]
        lines += [f"- Rank {miss['rank']} / {len(profiles)}: **{md(miss['id'])}**. {md(profile['description'])}",
                  f"  Score {row['score']:.4f}; probabilities: {md(row['probabilities'])}."]
    lines += ['', '## Ranking', '', '| Rank | Score | Test |', '| ---: | ---: | --- |']
    lines += [f"| {i} | {row['score']:.4f} | {md(row['id'])} |" for i, row in enumerate(findings['ranking'], 1)]
    lines += ['', '## Provenance and limitations', '',
              f"Reviewed by: {md(findings['reviewer'])}.",
              f"Index hash: {findings['index_hash']}.",
              f"Jev requests during prediction: {findings['usage']['requests']}; cache hits: {findings['usage']['cache_hits']}. Cost is not estimated.",
              *[f"- {md(note)}" for note in findings['limitations']],
              '- Failure classification is supplied with evidence by the agent or reviewer, not inferred from red CI status.',
              '- Green runs can describe ranking selectivity but cannot establish regression recall.',
              '- The JSON contains full inputs, probabilities, classifications, and baseline orders. Agent commentary must not alter those measurements.']
    return '\n'.join(lines) + '\n'


def all_latest(store):
    findings = []
    for pointer in sorted((store.path / 'evaluations' / 'latest').glob('*.json')):
        value = read_json(pointer)
        item = read_json(store.path / 'evaluations' / value['evaluation_id'] / 'findings.json')
        if item:
            findings.append(item)
    return findings


def regenerate(store, prediction_id):
    pointer = read_json(store.path / 'evaluations' / 'latest' / (prediction_id + '.json'))
    if not pointer:
        raise FaultlineError('No saved evaluation. Run evaluate after freezing a prediction and collecting outcomes.')
    path = store.path / 'evaluations' / pointer['evaluation_id']
    findings = read_json(path / 'findings.json')
    write_text(path / 'report.md', case_markdown(findings))
    write_json(path / 'report.json', findings)
    return {'report': str(path / 'report.md'), 'json': str(path / 'report.json'),
            'note': 'Saved evidence only; source/index/classification changes require a new evaluation.'}


def aggregate(store):
    findings = all_latest(store)
    if not findings:
        raise FaultlineError('No saved evaluations to summarize')
    groups = {}
    for item in findings:
        key = digest([item['repository'], item['evaluator'], item['random_seed']])
        group = groups.setdefault(key, {'repository': item['repository'], 'evaluator': item['evaluator'], 'cases': {}})
        cases = group['cases'].setdefault(item['change_id'], [])
        cases.append(item)
    output = []
    for group in groups.values():
        chosen = []
        for cases in group.pop('cases').values():
            eligible = [c for c in cases if c['selected_run']]
            if eligible:
                chosen.append(min(eligible, key=lambda c: (c['selected_run'].get('started_at') or '', c['snapshot'], c['prediction_id'])))
            else:
                chosen.append(max(cases, key=lambda c: c['created_at']))
        valid = [c for c in chosen if c['selected_run']]
        methods = {}
        for method in ('semantic', 'historical', 'random', 'path', 'lexical'):
            values = [c['selected_run']['metrics'][method] for c in valid if method in c['selected_run']['metrics']]
            ranks = [v['first_failure_rank'] for v in values]
            n = len(ranks)
            methods[method] = {'cases': n, 'hit_at': {str(k): {'hits': sum(v['hit_at'][str(k)] for v in values), 'total': n} for k in CUTOFFS},
                'macro_recall_at': {str(k): statistics.mean(v['recall_at'][str(k)] for v in values) if values else None for k in CUTOFFS},
                'median_first_failure_rank': statistics.median(ranks) if n else None,
                'p90_first_failure_rank': sorted(ranks)[math.ceil(.9*n)-1] if n >= 10 else None,
                'worst_first_failure_rank': max(ranks) if n else None}
        output.append({**group, 'distinct_changes': len(chosen), 'eligible_changes': len(valid),
                       'excluded_changes': len(chosen)-len(valid), 'methods': methods,
                       'selected_evaluations': [c['evaluation_id'] for c in chosen],
                       'case_selection': 'Earliest eligible reported run per change; no selection by ranking score.'})
    result = {'schema_version': 1, 'groups': output,
              'limitations': ['Selected local cases are not a representative benchmark.',
                              'Different evaluator configurations and repositories are separated.',
                              'Historical-order comparisons use only cases with verified comparable orders.',
                              'p90 is omitted for fewer than ten eligible cases.']}
    lines = ['# Faultline saved evaluation summary', '', 'Offline summary; no API calls.', '']
    for group in output:
        lines += [f"## {md(group['repository'])} — {md(group['evaluator']['model'])}", '',
                  f"Distinct PRs/MRs: {group['distinct_changes']}; eligible: {group['eligible_changes']}; excluded: {group['excluded_changes']}.", '',
                  'Single-case evidence only.' if group['distinct_changes'] == 1 else 'Exploratory sample; review selection bias before drawing general conclusions.', '',
                  '| Method | Cases | Hit @1 | Hit @5 | Hit @10 | Median rank | p90 rank | Worst rank |',
                  '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
        for method, values in group['methods'].items():
            hits = [f"{values['hit_at'][str(k)]['hits']} / {values['cases']}" for k in (1, 5, 10)]
            lines.append(f"| {method} | {values['cases']} | {' | '.join(hits)} | {values['median_first_failure_rank']} | {values['p90_first_failure_rank']} | {values['worst_first_failure_rank']} |")
    lines += ['', *[f"- {note}" for note in result['limitations']]]
    path = store.path / 'reports'
    write_json(path / 'latest.json', result)
    write_text(path / 'latest.md', '\n'.join(lines) + '\n')
    return {'report': str(path / 'latest.md'), 'json': str(path / 'latest.json'), 'groups': len(output)}
