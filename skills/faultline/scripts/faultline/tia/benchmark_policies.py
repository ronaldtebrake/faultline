"""Offline, outcome-blind routing experiments over a frozen whole-change benchmark."""
import math

from ..core import FaultlineError, digest
from ..jev import validate_answer

ARMS = ('jev',)
VERSION = 'offline-routing-policies-v2'
DEFAULT_THRESHOLDS = (.10, .25, .50)


def options(total, thresholds=None, budgets=None):
    thresholds = list(DEFAULT_THRESHOLDS if thresholds is None else thresholds)
    if not thresholds or len(thresholds) > 10 or any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 < t <= 1 for t in thresholds):
        raise FaultlineError('Supply 1 to 10 finite relevance thresholds in (0, 1]')
    budgets = list(sorted({max(1, math.ceil(total * f)) for f in (.10, .25, .50)})) if budgets is None else list(budgets)
    if not budgets or len(budgets) > 10 or any(isinstance(b, bool) or not isinstance(b, int) or b < 1 for b in budgets):
        raise FaultlineError('Supply 1 to 10 positive integer file budgets')
    return sorted(set(thresholds)), sorted(set(budgets))


def compare(document, routing, *, thresholds=None, budgets=None):
    if document['contract'].removesuffix('+context-v1') not in ('reference-source-v1', 'reference-whole-inputs-v1', 'reference-source-recovery-v1', 'reference-adaptive-source-v1'):
        raise FaultlineError('Policy comparison requires whole-change source or whole-input evidence; windowed file-pairs probabilities are not cumulative relevance probabilities')
    rows = {r['target']: r for r in routing['targets']}
    ids = set(rows)
    thresholds, budgets = options(len(ids), thresholds, budgets)
    suites = document['inventory']['suites']
    suite_units = {s['key']: {u['id'] for u in s['units']} for s in suites}
    config = {s['id']: s for s in document['config']['suites']}
    evidence, missing = {}, {}
    for arm in ARMS:
        evidence[arm], missing[arm] = {}, set(document['policies'][arm]['unresolved'])
        for id, row in rows.items():
            judgment = document['policies'][arm].get('judgments', {}).get(id)
            try:
                if not row[arm + '_assessed'] or id in missing[arm]:
                    raise FaultlineError('Unassessed')
                answer = validate_answer({'model': judgment.get('model'), 'answers': {'relevance': {
                    'type': 'choice', 'choice': judgment.get('choice'), 'probabilities': judgment.get('probabilities'),
                    'confidence': judgment.get('confidence')}}}, document['evaluator']['model'])
                if judgment.get('score_scope') == 'source-window-recovery-v1':
                    parts = judgment.get('parts', [])
                    if not parts or len(parts) != judgment.get('expected_parts'):
                        raise FaultlineError('Incomplete source windows')
                    values = []
                    for part in parts:
                        validated = validate_answer({'model': part.get('model'), 'answers': {'relevance': {
                            'type': 'choice', 'choice': part.get('choice'), 'probabilities': part.get('probabilities'),
                            'confidence': part.get('confidence')}}}, document['evaluator']['model'])
                        values.append(math.fsum(validated['probabilities'][k] for k in ('plausible', 'strong', 'direct')))
                    evidence[arm][id] = max(values)
                else:
                    evidence[arm][id] = math.fsum(answer['probabilities'][k] for k in ('plausible', 'strong', 'direct'))
            except FaultlineError:
                missing[arm].add(id)

    def closure(arm, initial):
        # Frozen requirements are a conservative lower bound. Never release a
        # prerequisite or full-suite obligation merely by changing a threshold.
        p = document['policies'][arm]
        mandatory = {id for id, row in rows.items() if row[arm + '_group'] == 'required'}
        full = set(p.get('full_suites', []))
        unknown_suites = full - set(suite_units)
        if unknown_suites:
            raise FaultlineError('Frozen full-suite requirement is absent from inventory')
        for name in full:
            mandatory.update(suite_units[name])
        selected = set(initial) | mandatory
        while True:
            before = (set(selected), set(full))
            for suite in suites:
                if suite['key'] not in full and not (selected & suite_units[suite['key']]):
                    continue
                prerequisites = config[suite['suite']].get('prerequisites', [])
                for name in prerequisites:
                    matches = [s for s in suites if s['suite'] == name]
                    if not matches:
                        raise FaultlineError('Frozen prerequisite suite is absent from inventory')
                    for target in matches:
                        full.add(target['key'])
                        mandatory.update(suite_units[target['key']])
                        selected.update(suite_units[target['key']])
            if before == (selected, full):
                return selected, mandatory, full

    def result(arm, selected, reasons, full, *, budget=None, floor=None, tie_split=False):
        p = document['policies'][arm]
        old = set(p['would_run'])
        actions = {id: 'RUN' if id in selected else 'OMIT' for id in sorted(ids)}
        groups = {name: sum(reason['group'] == name and id in selected for id, reason in reasons.items()) for name in ('required', 'unresolved', 'policy')}
        return {'would_run': len(selected), 'would_omit': len(ids - selected),
                'run_required': groups['required'], 'run_unresolved': groups['unresolved'], 'run_policy': groups['policy'],
                'unresolved_assessments': len(missing[arm]),
                'run_to_omit': sorted(old - selected), 'omit_to_run': sorted(selected - old),
                'full_suites': sorted(full), 'budget': budget, 'minimum_run_files': floor,
                'budget_met': len(selected) <= budget if budget is not None else None,
                'budget_excess_files': max(0, len(selected) - budget) if budget is not None else None,
                'budget_tie_split': tie_split, 'actions': actions, 'reasons': reasons}

    def alternative(arm, threshold=None, budget=None):
        floor, _, _ = closure(arm, missing[arm])
        selected, tie_split = set(floor), False
        if threshold is not None:
            selected.update(id for id, value in evidence[arm].items()
                            if value >= threshold or math.isclose(value, threshold, rel_tol=0, abs_tol=1e-12))
        else:
            # Ties have no predictive ordering; the report discloses the stable
            # identity tie-break and whether it crosses this particular budget.
            candidates = sorted(ids - floor, key=lambda id: (-evidence[arm][id], id))
            taken, skipped = set(), set()
            for id in candidates:
                if id in selected:
                    continue
                proposal, _, _ = closure(arm, selected | {id})
                if len(proposal) <= budget:
                    selected = proposal
                    taken.add(evidence[arm][id])
                else:
                    skipped.add(evidence[arm][id])
            tie_split = bool(taken & skipped)
        selected, mandatory, full = closure(arm, selected)
        reasons = {}
        explicit = {id for id, row in rows.items() if row[arm + '_group'] == 'required'}
        for id in sorted(ids):
            value = evidence[arm].get(id)
            if id in explicit:
                group, reason = 'required', 'Frozen mandatory rule or prerequisite'
            elif id in missing[arm]:
                group, reason = 'unresolved', 'Unresolved evidence; execution fallback'
            elif id in mandatory:
                group, reason = 'required', 'Preserved full-suite requirement or prerequisite'
            elif threshold is not None:
                group = 'policy' if id in selected else 'omit'
                reason = f"P(plausible + strong + direct) = {value:.1%} {'>=' if id in selected else '<'} {threshold:.1%} relevance threshold"
            else:
                group = 'policy' if id in selected else 'omit'
                reason = f"{'Within' if id in selected else 'Outside'} {budget}-file budget after mandatory rules and fallbacks"
            reasons[id] = {'group': group, 'reason': reason}
        return result(arm, selected, reasons, full, budget=budget, floor=len(floor), tie_split=tie_split)

    current = {}
    for arm in ARMS:
        reasons = {id: {'group': 'policy' if r[arm + '_group'] == 'retained' else r[arm + '_group'], 'reason': r[arm + '_reason']} for id, r in rows.items()}
        current[arm] = result(arm, set(document['policies'][arm]['would_run']), reasons, document['policies'][arm]['full_suites'])
    scenarios = [{'id': 'current', 'label': 'Saved omission policy', 'kind': 'current', 'approaches': current}]
    for threshold in thresholds:
        key = 'relevance_' + str(threshold).replace('.', '_')
        scenarios.append({'id': key, 'label': f'Relevance >= {threshold * 100:g}%', 'kind': 'relevance', 'threshold': threshold,
                          'approaches': {a: alternative(a, threshold=threshold) for a in ARMS}})
    for budget in budgets:
        scenarios.append({'id': f'files_{budget}', 'label': f'Budget {budget} files', 'kind': 'file_budget', 'file_budget': budget,
                          'approaches': {a: alternative(a, budget=budget) for a in ARMS}})
    return {'schema_version': 1, 'kind': 'benchmark-policy-comparison', 'comparison_version': VERSION,
            'comparison_id': digest({'benchmark': document['integrity'], 'version': VERSION, 'thresholds': thresholds, 'file_budgets': budgets}),
            'benchmark_id': document['integrity'], 'contract': document['contract'], 'target_count': len(ids),
            'thresholds': thresholds, 'file_budgets': budgets, 'scenarios': scenarios,
            'relevance_probabilities': {a: evidence[a] for a in ('jev',)}, 'unresolved': {a: sorted(v) for a, v in missing.items()},
            'new_jev_requests': 0, 'new_input_tokens': 0, 'execution': 'none', 'configuration_changed': False,
            'benchmark_complete': document['complete'], 'observed_regression_recall': None,
            'duration_basis': 'No execution durations supplied; budgets count source-file targets, not time or individual tests.',
            'limitations': [
                'Windowed source targets use maximum part relevance; this is not a calibrated cumulative-change probability and does not assess cross-window interactions.',
                'Exploratory policies, not calibrated failure probabilities or permission to skip tests. No winner is selected.',
                'Mandatory and full-suite requirements frozen in the saved case remain required; additional prerequisites are expanded.',
                'Unresolved evidence always stays RUN; it never becomes a positive model judgment.',
                'Relevance thresholds use P(plausible) + P(strong) + P(direct); weak relevance alone does not require execution.',
                'Budgets rank by Jev relevance probability. Ties use stable target IDs, not predictive evidence.',
                'A budget below the mandatory/fallback floor is exceeded visibly. Prerequisite bundles can leave a budget underfilled.',
                'Counts cover enumerated targets only; incomplete or empty full-suite inventories can require additional work.',
                'API usage is the original inference cost; changing a routing policy makes no new inference calls.',
                'Observed regression recall, measured coverage and execution savings remain unknown. Validate on separate later cases before choosing a policy.']}


def summary_lines(comparison, *, compact=False):
    lines = ['## Offline policy comparison' if not compact else '**Offline policy comparison (exploratory)**', '',
             'Same saved probabilities; **0 new Jev requests and 0 new tokens**. Execution defaults are unchanged.', '',
             '| Policy | Jev RUN / OMIT |',
             '| --- | ---: |']
    for scenario in comparison['scenarios']:
        values = []
        for arm in ARMS:
            m = scenario['approaches'][arm]
            values.append(f"{m['would_run']:,} / {m['would_omit']:,}" + (' (over budget)' if m['budget_met'] is False else ''))
        lines.append('| ' + ' | '.join([scenario['label'], *values]) + ' |')
    lines += ['', 'Relevance = P(plausible) + P(strong) + P(direct), not failure probability. Mandatory tests and unresolved fallbacks remain RUN.', '', comparison['duration_basis']]
    if compact:
        lines += ['Thresholds are experiments, not a chosen default. Recall and CI savings are unverified.']
        return lines
    lines += ['', '### Why these files would run', '',
              '| Policy | Approach | Required | Unresolved fallback | Policy choice | RUN → OMIT vs saved | OMIT → RUN vs saved |',
              '| --- | --- | ---: | ---: | ---: |']
    from .benchmark_report import LABELS
    for scenario in comparison['scenarios']:
        for arm, m in scenario['approaches'].items():
            lines.append('| ' + ' | '.join([scenario['label'], LABELS[arm], *(str(m[k]) for k in ('run_required', 'run_unresolved', 'run_policy')),
                                           str(len(m['run_to_omit'])), str(len(m['omit_to_run']))]) + ' |')
    lines += ['', '### Budget feasibility', '',
              '| File budget | Approach | Mandatory/fallback minimum | Actual RUN | Excess files | Ranking tie split |',
              '| ---: | --- | ---: | ---: | ---: | --- |']
    for scenario in comparison['scenarios']:
        if scenario['kind'] != 'file_budget':
            continue
        for arm, m in scenario['approaches'].items():
            lines.append(f"| {m['budget']} | {LABELS[arm]} | {m['minimum_run_files']} | {m['would_run']} | {m['budget_excess_files']} | {'yes; stable ID tie-break' if m['budget_tie_split'] else 'no'} |")
    lines += ['', 'A mandatory or unresolved fallback can exceed the requested budget. Stable identity tie-breaks do not supply predictive evidence.', '',
              'Each comparison column in the CSV gives an exact RUN/OMIT action and reason. The policy JSON includes exact additions and removals against the saved policy. Model probabilities are independent of these policy decisions.', '',
              *('- ' + text for text in comparison['limitations']), '']
    return lines
