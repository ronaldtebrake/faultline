"""Offline proposal reports. This module never discovers or executes native tests."""
from ..core import digest, write_json, write_text
from .common import checked, save_frozen, seal


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def report_selection(store, selection):
    store.initialize()
    suites = []
    for suite in selection['suites']:
        selected = set(suite['proposed_selected'])
        suites.append({'key': suite['key'], 'kind': suite['kind'],
                       'would_run': suite['proposed_selected'], 'would_omit': suite['proposed_omitted'],
                       'would_run_full_suite': bool(suite['fallbacks']) or suite['kind'] == 'check',
                       'warnings': suite.get('warnings', []), 'fallbacks': suite['fallbacks'], 'prerequisites': suite['prerequisites'],
                       'targets': [{'id': u['id'], 'source': u['source'],
                                    'decision': 'would_run' if u['id'] in selected else 'would_omit',
                                    'reasons': suite['reasons'][u['id']],
                                    'judgment': selection['judgments'].get(u['id'])}
                                   for u in suite['units']]})
    total = sum(len(s['targets']) for s in suites)
    omitted = sum(len(s['would_omit']) for s in suites)
    value = seal({'schema_version': 2, 'kind': 'proposal', 'mode': 'shadow', 'execution': 'none',
                  'engine_version': selection.get('engine_version', 'unknown'), 'created_at': selection['created_at'], 'selection_id': selection['integrity'],
                  'repository': selection['repository'],
                  'change': {k: selection['change'][k] for k in ('id', 'base', 'head')},
                  'policy_key': digest({'policy': selection['policy'], 'config': selection['config_hash'],
                                        'evaluator': selection['evaluator']}),
                  'index': selection.get('index', {}), 'suites': suites,
                  'metrics': {'known_targets': total, 'would_run': total - omitted, 'would_omit': omitted,
                              'proposed_omission_fraction': omitted / total if total and selection['inventory']['complete'] else None,
                              'suites_requiring_full_run': sum(s['would_run_full_suite'] for s in suites),
                              'tests_executed_by_faultline': 0, 'regression_recall': None,
                              'measured_execution_savings_seconds': None, 'measured_coverage': None},
                  'semantic': selection.get('semantic', {}), 'semantic_complete': selection['semantic_complete'], 'usage': selection['usage'],
                  'cost': selection['cost'], 'selection_seconds': selection['selection_seconds'],
                  'limitations': ['Shadow mode only records what Faultline would run; it does not execute tests or alter CI.',
                                  'Counts describe provisional file targets and whole checks, not individual test cases.',
                                  'A full-suite fallback applies even when no source targets could be enumerated.',
                                  'Proposed omissions are not measured time savings or proof of regression detection.']})
    frozen = store.path / 'proposals' / (selection['integrity'] + '.json')
    save_frozen(frozen, value)
    output = store.path / 'reports' / 'proposals' / selection['integrity']
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output.with_suffix('.json'), value)
    lines = [f"# Faultline shadow proposal: {cell(value['change']['id'])}", '',
             '**Report only. Faultline did not execute tests. Existing CI is unchanged.**', '',
             f"Base: `{value['change']['base']}` · Head: `{value['change']['head']}`", '',
             f"Known targets: {total}. Would run: {total - omitted}. Would omit: {omitted}.", '',
             'These counts describe source files and whole checks. Regression recall, coverage, and execution-time savings are not measured.']
    lines += ['', f"Engine: Faultline {value['engine_version']}. Index: {cell(value['index'].get('basis', 'unknown'))}."]
    if value['index'].get('warning'):
        lines += ['Index warning: ' + cell(value['index']['warning'])]
    semantic = value['semantic']
    lines += ['', f"Jev status: **{semantic.get('status', 'unknown')}**. Fully scored: {semantic.get('fully_scored', 'unknown')}; partially scored: {semantic.get('partial', 'unknown')}; unscored: {semantic.get('unscored', 'unknown')}.", '',
              'Scores use the strongest observed fragment judgment. P(irrelevant) below is the minimum across all evaluated fragment pairs, available only for complete evidence; it is not a calibrated whole-test failure probability.']
    for target, error in sorted(semantic.get('errors', {}).items()):
        lines += [f'- {cell(target)}: {cell(error)}']
    for suite in suites:
        lines += ['', f"## {cell(suite['key'])}", '']
        if suite['would_run_full_suite']:
            lines += ['**Would run the full suite/check.** ' + cell(', '.join(suite['fallbacks']) or 'Whole check policy') + '.', '']
        if suite['warnings']:
            lines += ['Evidence limitations: ' + cell(', '.join(suite['warnings'])) + '.', '']
        if suite['prerequisites']:
            lines += ['Prerequisites: ' + cell(', '.join(suite['prerequisites'])) + '.', '']
        lines += ['| Target | Would | Jev score | P(irrelevant) | Reasons |', '| --- | --- | --- | --- | --- |']
        for target in sorted(suite['targets'], key=lambda t: (-((t['judgment'] or {}).get('score', -1)), t['id'])):
            judgment = target['judgment'] or {}
            lines.append(f"| {cell(target['id'])} | {target['decision'].removeprefix('would_')} | {judgment.get('score', 'unscored')} | {judgment.get('all_parts_irrelevant_probability', judgment.get('probabilities', {}).get('irrelevant', 'unknown'))} | {cell(', '.join(target['reasons']))} |")
        if not suite['targets']:
            lines += ['', 'No source targets enumerated. This does not mean the suite has no tests.']
    pending = value['usage'].get('remaining_requests', 'unknown')
    lines += ['', f"Remaining Jev batches: {pending}. Re-run the same base/head and input settings to resume from cache within another explicit request cap. No budget is raised automatically."]
    lines += ['', '## Analysis effort', '',
              f"Jev requests: {value['usage']['requests']}; cached fragment judgments: {value['usage']['cache_hits']}; analysis: {value['selection_seconds']:.3f}s.",
              f"Estimated input cost: {value['cost']['input_usd_estimate']} (unknown when no applicable price or usage is available).", '',
              *('- ' + item for item in value['limitations'])]
    write_text(output.with_suffix('.md'), '\n'.join(lines) + '\n')
    return {'json': str(output.with_suffix('.json').resolve()), 'markdown': str(output.with_suffix('.md').resolve()),
            'selection_id': value['selection_id'], 'mode': 'shadow', 'execution': 'none', 'metrics': value['metrics']}


def aggregate(store):
    # Re-analysis of one revision/policy is not another independent PR case.
    proposals = [checked(p, 'proposal') for p in sorted((store.path / 'proposals').glob('*.json'))]
    latest = {}
    for proposal in proposals:
        c = proposal['change']
        key = (proposal['repository'], c['base'], c['head'], proposal['policy_key'])
        if key not in latest or proposal['created_at'] > latest[key]['created_at']:
            latest[key] = proposal
    cases = [{'repository': p['repository'], 'change': p['change'], 'policy_key': p['policy_key'],
              'selection_id': p['selection_id'], 'metrics': p['metrics'], 'usage': p['usage'],
              'semantic': p.get('semantic', {}), 'semantic_complete': p['semantic_complete'], 'cost': p['cost'],
              'markdown': str((store.path / 'reports/proposals' / (p['selection_id'] + '.md')).resolve())}
             for _, p in sorted(latest.items())]
    result = {'mode': 'shadow', 'execution': 'none', 'snapshots': len(cases),
              'analyses': len(proposals), 'cases': cases,
              'limitations': ['Repeated analyses of the same revision and policy count as one snapshot.',
                              'Different revisions of one PR are related snapshots, not independent regression cases.',
                              'These are proposals only; no observed recall, coverage, or execution savings are claimed.']}
    store.initialize()
    write_json(store.path / 'reports/shadow-summary.json', result)
    lines = ['# Faultline shadow proposals', '', 'Report only: no tests executed by this workflow.', '',
             f"{len(cases)} snapshot cases from {len(proposals)} saved analyses.", '',
             '| PR/MR | Head | Policy | Would run | Would omit | Full-suite fallbacks/checks |',
             '| --- | --- | --- | --- | --- | --- |']
    for case in cases:
        m = case['metrics']
        lines.append(f"| {cell(case['change']['id'])} | {case['change']['head'][:12]} | {case['policy_key'][:12]} | {m['would_run']} | {m['would_omit']} | {m['suites_requiring_full_run']} |")
    lines += ['', *('- ' + item for item in result['limitations'])]
    write_text(store.path / 'reports/shadow-summary.md', '\n'.join(lines) + '\n')
    return {**result, 'json': str((store.path / 'reports/shadow-summary.json').resolve()),
            'markdown': str((store.path / 'reports/shadow-summary.md').resolve())}
