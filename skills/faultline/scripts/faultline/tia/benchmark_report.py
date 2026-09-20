"""Offline routing and cost reports from immutable benchmark evidence."""
import csv
import io
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from .. import __version__
from ..core import FaultlineError, number, write_text, write_json
from .common import checked
from .proposals import cell

ARMS = ('jev',)
LABELS = {'jev': 'Jev'}


def validate_pricing(value, model):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise FaultlineError('Report pricing must be an object')
    try:
        date.fromisoformat(value['as_of'])
    except (KeyError, ValueError, TypeError):
        raise FaultlineError('Report pricing requires as_of as YYYY-MM-DD') from None
    rate = number(value.get('input_usd_per_million'), 'input_usd_per_million', allow_zero=True)
    if value.get('model', model) != model:
        raise FaultlineError('Report pricing model differs from the benchmark model')
    source = value.get('source')
    if source is not None and (not isinstance(source, str) or not source.startswith('https://') or any(c in source for c in '\n\r()<>')):
        raise FaultlineError('Report pricing source must be an HTTPS URL')
    return {**value, 'model': model, 'input_usd_per_million': rate}


def usage_metrics(policy, price):
    requests = policy['requests']
    records = policy.get('usage', [])
    def valid(record):
        return (isinstance(record, dict) and isinstance(record.get('input_tokens'), int)
                and not isinstance(record['input_tokens'], bool) and record['input_tokens'] >= 0)
    known = sum(r['input_tokens'] for r in records if valid(r))
    complete = len(records) == requests and all(valid(r) for r in records)
    tokens = known if complete else None
    cost = (0.0 if tokens == 0 else tokens * price['input_usd_per_million'] / 1_000_000
            if tokens is not None and price else None)
    return {'requests': requests, 'input_tokens': tokens, 'reported_input_tokens': known,
            'usage_complete': complete, 'input_usd_estimate': cost, 'cache_hits': policy.get('cache_hits', 0)}


def routing_data(document, *, pricing=None):
    d = document
    if set(d['policies']) != {'jev'}:
        raise FaultlineError('This snapshot uses a retired comparison contract; keep its archived report or create a new Jev-only benchmark')
    price = validate_pricing(pricing if pricing is not None else d['evaluator']['settings'].get('pricing'), d['evaluator']['model'])
    policies = d['policies']
    config = {s['id']: s for s in d['config']['suites']}
    units = {u['id']: (s, u) for s in d['inventory']['suites'] for u in s['units']}
    ids = sorted(set(units) | set().union(*(set(p['ranking']) for p in policies.values())))
    sets = {a: {k: set(p.get(k, [])) for k in ('would_run', 'would_omit', 'unresolved', 'required')}
            for a, p in policies.items()}
    rows = []
    for id in ids:
        suite, unit = units.get(id, ({}, {}))
        threshold = config.get(suite.get('suite'), {}).get('irrelevant_threshold')
        if threshold is None:
            threshold = config.get(suite.get('key', '').split(':')[0], {}).get('irrelevant_threshold')
        row = {'target': id, 'suite': suite.get('key', ''), 'source': unit.get('source', ''),
               'review_notes': ''}
        for arm in ARMS:
            p, memberships = policies[arm], sets[arm]
            action = 'RUN' if id in memberships['would_run'] else 'OMIT' if id in memberships['would_omit'] else None
            if action is None:
                raise FaultlineError('Frozen benchmark lacks a routing decision for a target')
            if id in memberships['would_run'] & memberships['would_omit']:
                raise FaultlineError('Frozen benchmark contains contradictory routing decisions')
            judgment = p.get('judgments', {}).get(id, {})
            assessed = bool(judgment) and id not in p.get('errors', {}) and judgment.get('evidence_complete', True)
            probability = judgment.get('all_parts_irrelevant_probability', judgment.get('probabilities', {}).get('irrelevant')) if assessed else None
            required = id in memberships['required']
            if required:
                reason, group = 'Required by rules or prerequisites', 'required'
                if id in memberships['unresolved']:
                    reason += '; assessment incomplete'
            elif id in memberships['unresolved']:
                reason, group = 'Unassessed; fallback', 'unresolved'
            else:
                group = 'retained' if action == 'RUN' else 'omit'
                if probability is None or threshold is None:
                    reason = 'Stored policy decision; inspect evidence'
                else:
                    comparison = '<' if action == 'RUN' else '>='
                    reason = f'{probability:.1%} irrelevant {comparison} {threshold:.1%} omission cutoff'
                    if judgment.get('all_parts_irrelevant_probability') is not None:
                        reason += ' (minimum over windows)'
                if assessed:
                    reason += '; model: ' + judgment.get('choice', 'unknown')
            row.update({arm + '_action': action, arm + '_reason': reason, arm + '_group': group,
                        arm + '_assessed': assessed})
            row.update({arm + '_model_choice': judgment.get('choice') if assessed else None,
                        arm + '_p_irrelevant': probability, arm + '_threshold': threshold,
                        arm + '_score': judgment.get('score') if assessed else None,
                        arm + '_error': p.get('errors', {}).get(id, '')})
            for level in ('irrelevant', 'weak', 'plausible', 'strong', 'direct'):
                row[f'{arm}_p_{level}'] = judgment.get('probabilities', {}).get(level) if assessed else None
            # The policy can use the minimum across windows, separately from
            # the strongest window's distribution in legacy bounded cases.
            row[arm + '_policy_p_irrelevant'] = probability
        rows.append(row)
    summaries = {}
    for arm in ARMS:
        groups = Counter(r[arm + '_group'] for r in rows)
        summaries[arm] = {'would_run': sum(r[arm + '_action'] == 'RUN' for r in rows),
                          'would_omit': sum(r[arm + '_action'] == 'OMIT' for r in rows),
                          'run_required': groups['required'], 'run_unresolved': groups['unresolved'],
                          'run_policy': groups['retained'], 'unresolved_assessments': len(sets[arm]['unresolved']),
                          'valid_judgments': sum(r[arm + '_assessed'] is True for r in rows),
                          **usage_metrics(d.get('recovery', {}).get('cumulative_policy_usage', {}).get(arm, policies[arm]), price),
                          'invocation_usage': usage_metrics(policies[arm], price)}
    return {'target_count': len(rows), 'policies': summaries, 'targets': rows, 'pricing': price,
            'pricing_basis': 'report override' if pricing is not None else 'frozen benchmark settings',
            'cost_scope': ('Cumulative original and recovery inference; new recovery usage is shown separately.' if d.get('recovery') else 'HTTP attempts in this invocation; cached judgments are not billed again. Completing unassessed targets is extra work.'),
            'complete': d['complete']}


def number_text(value):
    return 'unknown' if value is None else f'{value:,}'


def money(value):
    if value is None:
        return 'unknown'
    return '$0' if value == 0 else f'${value:.6f}' if value < .0001 else f'${value:.4f}'


def save_csv(path, rows, benchmark_id, comparison=None):
    notes = {}
    if path.exists():
        with path.open(newline='') as stream:
            for row in csv.DictReader(stream):
                if row.get('review_notes') and row.get('benchmark_id') != benchmark_id:
                    raise FaultlineError('Existing review notes belong to another or unidentified benchmark; use a different report output')
                if row.get('target'):
                    notes[row['target']] = row.get('review_notes', '')
    stream = io.StringIO(newline='')
    fields = ['benchmark_id', 'target', 'suite', 'source']
    for arm in ARMS:
        fields += [arm + '_action', arm + '_reason']
        fields += [arm + '_assessed', arm + '_model_choice', arm + '_score', arm + '_threshold', arm + '_policy_p_irrelevant']
        fields += [arm + '_p_' + level for level in ('irrelevant', 'weak', 'plausible', 'strong', 'direct')]
        fields += [arm + '_error']
    if comparison:
        for arm in ('jev',):
            fields += [arm + '_p_meaningful_relevance']
        for scenario in comparison['scenarios']:
            if scenario['kind'] == 'current':
                continue
            for arm in ARMS:
                fields += [scenario['id'] + '_' + arm + suffix for suffix in ('_action', '_reason')]
    fields += ['review_notes']
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        value = {**row, 'benchmark_id': benchmark_id, 'review_notes': notes.get(row['target'], '')}
        for arm in ('jev',):
            if value[arm + '_score'] is not None:
                value[arm + '_score'] = f"{value[arm + '_score']:.3f}"
        if comparison:
            for arm in ('jev',):
                value[arm + '_p_meaningful_relevance'] = comparison['relevance_probabilities'][arm].get(row['target'])
            for scenario in comparison['scenarios']:
                if scenario['kind'] == 'current':
                    continue
                for arm, policy in scenario['approaches'].items():
                    prefix = scenario['id'] + '_' + arm
                    value[prefix + '_action'] = policy['actions'][row['target']]
                    value[prefix + '_reason'] = policy['reasons'][row['target']]['reason']
        writer.writerow(value)
    write_text(path, stream.getvalue())


COMMENT_MARKER = '<!-- faultline:benchmark-report -->'


def comment_report_url(value):
    if value is None:
        return None
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == 'https' and bool(parsed.hostname)
                 and parsed.username is None and parsed.password is None
                 and not any(c.isspace() or c in '<>()[]`\\' for c in value))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise FaultlineError('A PR comment report link must be an absolute HTTPS URL without credentials or Markdown delimiters')
    return value


def render(path, document=None, *, pricing=None, output=None, format='full', report_url=None, compare_policies=False, relevance_thresholds=None, file_budgets=None):
    """Regenerate routing and cost summaries offline; never post a PR comment."""
    if (relevance_thresholds is not None or file_budgets is not None) and not compare_policies:
        raise FaultlineError('--relevance-thresholds and --file-budgets require --compare-policies')
    if format not in ('full', 'comment'):
        raise FaultlineError('Unknown report format')
    if report_url and format != 'comment':
        raise FaultlineError('--report-url applies to comment format')
    report_url = comment_report_url(report_url)
    path = Path(path)
    d = document or checked(path, 'benchmark')
    data = routing_data(d, pricing=pricing)
    m, rows, price = data['policies']['jev'], data['targets'], data['pricing']
    total = data['target_count']
    compact = format == 'comment'
    destination = Path(output).with_suffix('.md') if output else path.with_suffix('.comment.md' if compact else '.md')
    csv_path = destination.with_suffix('.csv')
    comparison_path = destination.with_suffix('.policies.json') if compare_policies and not compact else None
    if any(p.resolve() == path.resolve() for p in (destination, csv_path, comparison_path) if p):
        raise FaultlineError('Report output would overwrite frozen evidence; choose another output')
    comparison = None
    if compare_policies:
        from .benchmark_policies import compare, summary_lines
        comparison = compare(d, data, thresholds=relevance_thresholds, budgets=file_budgets)
    lines = ([COMMENT_MARKER, '### Faultline test routing'] if compact else
             [f"# Faultline benchmark: {cell(d['change']['id'])}"]) + ['',
             f"**{'Complete' if d['complete'] else 'Incomplete'} assessment · Shadow mode.** Faultline did not execute tests.", '',
             f"Jev proposes **{m['would_run']:,} RUN / {m['would_omit']:,} OMIT** out of {total:,} configured file targets.", '',
             '| Approach | Would run | Would omit | Kept unresolved | Input tokens | Estimated input cost (USD) |',
             '| --- | ---: | ---: | ---: | ---: | ---: |',
             f"| Full configured suite | {total:,} | 0 | — | 0 | $0 |",
             f"| Jev | {m['would_run']:,} | {m['would_omit']:,} | {m['run_unresolved']:,} | {number_text(m['input_tokens'])} | {money(m['input_usd_estimate'])} |", '',
             f"Valid judgments: **{m['valid_judgments']:,}/{total:,}**. RUN reasons: {m['run_policy']:,} policy choices, {m['run_required']:,} required by rules or prerequisites, {m['run_unresolved']:,} unresolved fallbacks.", '',
             '**Unresolved targets stay RUN.** Counts describe files and whole checks, not individual test cases. No confirmed regression recall, measured coverage, or CI savings are established by this proposal.']
    from .context import summary as context_summary
    context = context_summary(d.get('context_bundle'))
    if context['mode'] == 'enriched':
        lines += ['', f"Inputs: **diff + collected context** ({context['evidence_items']} source items, {context['evidence_bytes']:,} bytes). Source identity is verified; collection is not proven exhaustive."]
        if context['gaps']:
            lines += ['**Context gaps:** full-suite fallback applies.']
            if not compact:
                lines += ['- ' + cell(gap) for gap in context['gaps']]
    else:
        lines += ['', 'Inputs: **diff + test source**; no additional agent-collected product integration context was supplied.']
    if not d['inventory']['complete']:
        lines += ['', '**Inventory incomplete:** full-suite obligations can include additional, unenumerated tests.']
    if d['policies']['jev']['full_suites']:
        lines += ['', 'Full-suite requirements: ' + cell(', '.join(d['policies']['jev']['full_suites'])) + '.']
    cutoffs = sorted({r['jev_threshold'] for r in rows if r['jev_threshold'] is not None})
    lines += ['', (f"The saved policy omits a non-required target only at **P(irrelevant) ≥ {cutoffs[0]:.0%}**. RUN below this cutoff does not mean strong relevance." if len(cutoffs) == 1 else
                   'The saved policy applies each suite’s configured irrelevant-probability cutoff. RUN does not necessarily mean strong relevance.'),
              'Relevance is not predicted failure probability. Offline relevance thresholds use P(plausible + strong + direct), excluding weak relevance.']
    if comparison:
        lines += ['', *summary_lines(comparison, compact=compact)]
    if compact:
        lines += ['', f'[Full report and per-test decisions]({report_url})' if report_url else 'Full report: not linked yet.', '',
                  '<details>', '<summary>Assessment and cost details</summary>', '']
    else:
        lines += ['', '## Usage and evidence', '']
    lines += [f"HTTP attempts: **{m['requests']:,}**. Input tokens: **{number_text(m['input_tokens'])}**. Cached judgments reused: **{m['cache_hits']:,}**.", '', data['cost_scope']]
    if price:
        source = f" ([source]({price['source']}))" if price.get('source') else ''
        lines += [f"Input price: ${price['input_usd_per_million']:g}/million tokens, dated {price['as_of']}{source}; {data['pricing_basis']}. Output and external agent costs are not included."]
    else:
        lines += ['No dated input price supplied; dollar cost is unknown unless zero new inference was performed.']
    lines += ['A cached rerun does not establish the cost of a new PR. Missing token usage remains unknown.']
    if context['mode'] == 'enriched':
        collection = context['collector']
        lines += [f"Context collection (self-reported): {number_text(collection['input_tokens'])} input tokens, {number_text(collection['output_tokens'])} output tokens; cost {money(collection['cost_usd'])}. This is separate from Jev and is not inferred from its usage."]
        if collection['cost_usd'] is not None and m['input_usd_estimate'] is not None:
            lines += [f"Collection + estimated Jev input cost: {money(collection['cost_usd'] + m['input_usd_estimate'])}; any unpriced Jev output remains excluded."]
        else:
            lines += ['Combined collection and Jev cost: unknown.']
        if not compact:
            lines += ['', f"Context bundle: `{context['integrity']}`. Exact excerpts and revision provenance are retained in the frozen JSON."]
    p = d['policies']['jev']
    windowed = sum(j.get('score_scope') == 'source-window-recovery-v1' for j in p['judgments'].values())
    lines += ['', f"Windowed targets: **{windowed}**. Every source/change range must be assessed. Cross-window interactions and unsupplied external setup bodies are not assessed in adaptive/source mode; maximum part relevance is not a calibrated whole-change probability.",
              f"Validation retries: {p.get('validation_retries', 0)}. Analysis: {d['selection_seconds']:.1f}s; inference: {d['inference_seconds']:.1f}s."]
    if d.get('recovery'):
        current = m['invocation_usage']
        lines += [f"This recovery alone: {current['requests']} HTTP attempts, {number_text(current['input_tokens'])} input tokens, {money(current['input_usd_estimate'])}. The main table includes parent inference."]
    if compact:
        lines += ['', f"Tested head: `{cell(d['change']['head'][:12])}`. Model: `{cell(d['evaluator']['model'])}`.", '', '</details>']
    else:
        lines += ['', '## By suite', '', '| Suite | RUN | OMIT | Unresolved assessments |', '| --- | ---: | ---: | ---: |']
        for suite in d['inventory']['suites']:
            subset = [r for r in rows if r['suite'] == suite['key']]
            lines += [f"| {cell(suite['key'])} | {sum(r['jev_action'] == 'RUN' for r in subset)} | {sum(r['jev_action'] == 'OMIT' for r in subset)} | {sum(r['target'] in p['unresolved'] for r in subset)} |"]
        lines += ['', '## Per-target decisions', '', '| Target | Jev action and reason |', '| --- | --- |']
        lines += [f"| {cell(r['target'])} | {r['jev_action']}: {cell(r['jev_reason'])} |" for r in rows]
        lines += ['', '## Unresolved evidence', '']
        lines += [f"- {cell(id)}: {cell(error)}" for id, error in sorted(p['errors'].items())] or ['None.']
        lines += ['', '## Provenance', '', f"Frozen case: `{d['integrity']}`. Scoring engine: `{d['engine_version']}`. Report generator: `{__version__}`. Contract: `{d['contract']}`.",
                  f"Base: `{d['change']['base']}`. Tested head: `{d['change']['head']}`. Model: `{d['evaluator']['model']}`.", '',
                  f'[Frozen evidence and probabilities]({path.resolve()}). Rendering makes no inference calls.', '',
                  *('- ' + cell(text) for text in d['limitations'])]
        # Validate existing notes before writing any output.
        save_csv(csv_path, rows, d['integrity'], comparison)
        if comparison_path:
            write_json(comparison_path, comparison)
    write_text(destination, '\n'.join(lines) + '\n')
    return {'json': str(path.resolve()), 'markdown': str(destination.resolve()), 'csv': str(csv_path.resolve()) if not compact else None,
            'policy_comparison': str(comparison_path.resolve()) if comparison_path else None,
            'format': format, 'published': False, 'report_url': report_url,
            'benchmark_id': d['integrity'], 'complete': d['complete'], 'execution': 'none', 'usage': d['usage'],
            'preparation': d.get('preparation'), 'routing': {k: v for k, v in data.items() if k != 'targets'},
            'decisions': {'jev': {'retained': m['run_policy'], 'required': m['run_required'], 'unresolved': m['run_unresolved'], 'omit': m['would_omit']}},
            'policies': {'jev': {k: m[k] for k in ('would_run', 'would_omit')} | {'unresolved': m['unresolved_assessments']}}}
