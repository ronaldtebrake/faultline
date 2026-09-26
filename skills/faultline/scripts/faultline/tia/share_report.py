"""Standalone, script-free HTML. Threshold comparisons reuse frozen judgments."""
from html import escape
from pathlib import Path

from ..core import FaultlineError, write_text
from .common import checked
from .benchmark_policies import compare
from .benchmark_report import render, routing_data


def money(value):
    return 'Unknown' if value is None else f'${value:.6f}' if 0 < value < .0001 else f'${value:.4f}'


def page(title, data, comparison, *, assessment=None, inference=None, analysis=None, demo=False):
    e = lambda value: escape(str(value), quote=True)
    m = data['policies']['jev']
    total = data['target_count']
    assessment = assessment or {}
    timing = assessment.get('invocation_seconds')
    cost = m['input_usd_estimate']
    cards = [('Files assessed', f"{m['valid_judgments']:,} / {total:,}"),
             ('Jev input estimate', money(cost)),
             ('Average per configured file', money(cost / total) if cost is not None and total else 'Unknown'),
             ('Engine to report', f'{timing:.1f}s' if timing is not None else 'Not measured')]
    panes, tabs = [], []
    for i, scenario in enumerate(s for s in comparison['scenarios'] if s['kind'] == 'relevance'):
        name = f'threshold-{i}'
        p = scenario['approaches']['jev']
        tabs.append(f'<input type="radio" name="threshold" id="{name}" {"checked" if i == 1 else ""}><label for="{name}">{e(scenario["label"])}</label>')
        rows = []
        scores = comparison['relevance_probabilities']['jev']
        for row in sorted(data['targets'], key=lambda r: (p['actions'][r['target']] != 'RUN', -scores.get(r['target'], 1), r['target'])):
            target = row['target']
            action = p['actions'][target]
            value = scores.get(target)
            rows.append(f'<tr class="{action.lower()}"><td>{e(target)}</td><td>{"Unassessed" if value is None else f"{value:.1%}"}</td><td><b>{action}</b></td><td>{e(p["reasons"][target]["reason"])}</td></tr>')
        percentage = 100 * p['would_run'] / total if total else 100
        full = ', '.join(p['full_suites']) or 'None'
        panes.append(f'''<section class="pane pane-{i}"><h2>{e(scenario['label'])}</h2>
<p class="decision"><strong>{p['would_run']:,}</strong> would run <span> / {p['would_omit']:,} would omit</span></p>
<div class="bar" aria-label="{p['would_run']} files would run"><i style="width:{percentage}%"></i></div>
<p>{p['run_policy']} selected by relevance · {p['run_required']} required · {p['run_unresolved']} unresolved fallbacks</p>
<p>Full-suite obligations: {e(full)}. Counts cover configured file targets; an incomplete inventory can require additional tests.</p>
<details open><summary>All test-file decisions</summary><div class="scroll"><table><thead><tr><th>Test file / variant</th><th>Relevance</th><th>Would</th><th>Reason</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></details></section>''')
    css = '\n'.join(f'#threshold-{i}:checked ~ .panes .pane-{i}{{display:block}}' for i in range(len(panes)))
    price = data.get('pricing')
    pricing = f"${price['input_usd_per_million']:g} per million input tokens, dated {price['as_of']}" if price else 'No dated price supplied'
    tokens = 'Unknown' if m['input_tokens'] is None else f"{m['input_tokens']:,}"
    fresh = assessment.get('new_answers', 'Not recorded')
    resumed = assessment.get('resumed_answers', 'Not recorded')
    reused = assessment.get('reused_answers', m.get('cache_hits', 0))
    warnings = ''.join(f'<li>{e(w)}</li>' for w in assessment.get('warnings', []))
    return f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{e(title)} · Faultline</title><style>
:root{{font:16px/1.5 system-ui,sans-serif;color:#dce8ef;background:#0e171c;color-scheme:dark}}
body{{max-width:1120px;margin:0 auto;padding:38px 24px}}h1{{font-size:clamp(28px,5vw,46px);line-height:1.1;margin:14px 0}}h2{{font-size:20px}}p{{color:#adbec9}}.brand{{letter-spacing:.15em;color:#76ecc0;font-size:13px}}.badge{{color:#ffd48c}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:30px 0}}.card{{padding:18px;background:#17262e;border:1px solid #30444e;border-radius:12px}}.card small{{display:block;color:#adbec9}}.card strong{{display:block;font-size:24px;margin-top:8px}}input[type=radio]{{position:absolute;opacity:0}}label{{display:inline-block;padding:10px 16px;cursor:pointer;border:1px solid #45616c;border-radius:8px;margin:0 6px 8px 0}}input:checked+label{{background:#76ecc0;color:#112c23;border-color:#76ecc0}}input:focus-visible+label{{outline:3px solid white;outline-offset:3px}}.pane{{display:none}}{css}
.decision{{font-size:22px;color:#dce8ef}}.decision strong{{font-size:38px;color:#76ecc0}}.decision span{{color:#adbec9}}.bar{{height:10px;background:#2b3e48;border-radius:10px;overflow:hidden}}.bar i{{display:block;height:100%;background:#76ecc0}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;margin:12px 0}}th,td{{text-align:left;padding:12px 8px;border-bottom:1px solid #2d414b;font-size:13px;vertical-align:top}}td:first-child{{overflow-wrap:anywhere;min-width:220px}}.run b{{color:#76ecc0}}.omit b{{color:#a9b8c1}}summary{{cursor:pointer}}footer{{border-top:1px solid #30444e;margin-top:30px;padding-top:15px;font-size:13px}}@media(max-width:650px){{.cards{{grid-template-columns:1fr 1fr}}}}@media print{{:root{{color:#111;background:white;color-scheme:light}}body{{max-width:none}}.pane{{display:block!important;break-before:page}}label,input{{display:none}}.card{{background:white}}p,small,.decision,.decision span{{color:#333!important}}.scroll{{overflow:visible}}.run b,.decision strong{{color:#164e3d}}}}
</style><body><div class="brand">FAULTLINE / TEST IMPACT ASSESSMENT</div>
<h1>{e(title)}</h1><p class="badge">{'SYNTHETIC DEMO — all results, costs and times below are invented.' if demo else ('Complete assessment' if data.get('complete') else 'Incomplete assessment — fallbacks apply') + ' · Shadow report, no tests executed.'}</p>
<p>Diff + test source → Jev relevance judgments → an explicit test-selection policy.</p>
<div class="cards">{''.join(f'<div class="card"><small>{e(label)}</small><strong>{e(value)}</strong></div>' for label, value in cards)}</div>
<p>Compare 10%, 25% and 50% relevance. Switching tabs makes no API calls. Required and unresolved tests stay RUN.</p>
{''.join(tabs)}<div class="panes">{''.join(panes)}</div>
<footer><h2>What this costs and measures</h2><p>{m['requests']} HTTP attempts · {tokens} input tokens. {e(pricing)}. Input estimates exclude unpriced output, agent work and search services. Average cost per file spreads this run’s input cost over the inventory; it is not a marginal API price.</p>
<p>Newly accepted answers: {e(fresh)} · recovered from this run: {e(resumed)} · reused from other runs: {e(reused)}. Answers may cover source windows rather than one complete file. A reused answer’s original cost belongs to its earlier run.</p>
<p>Analysis: {e(f'{analysis:.1f}s' if analysis is not None else 'unknown')} · inference: {e(f'{inference:.1f}s' if inference is not None else 'unknown')} (included in analysis). {e(assessment.get('timing_scope', 'Engine-to-report and agent context time were not recorded in this older snapshot.'))} Earlier completed invocations: {assessment.get('prior_invocation_seconds', 0):.1f}s. Abruptly terminated phases may have unrecorded duration. Agent investigation time is unmeasured. Supplied context-collection cost: {money(assessment.get('agent_context_cost_usd'))} (self-reported, separate from Jev).</p>
<p>Relevance = P(plausible + strong + direct), excluding weak relevance. Windowed files use their strongest assessed part. Relevance is not failure probability. Observed regression recall, code coverage and CI time saved are unmeasured; fewer selected files alone does not prove savings or quality.</p>
<ul>{warnings}</ul><p>Self-contained HTML. No JavaScript, external assets or network requests.</p></footer></body></html>'''


def report(path, *, output=None, document=None):
    path = Path(path)
    document = document or checked(path, 'benchmark')
    destination = Path(output).with_suffix('.html') if output else path.with_suffix('.html')
    if destination.resolve() == path.resolve():
        raise FaultlineError('Report output would overwrite frozen evidence')
    data = routing_data(document)
    comparison = compare(document, data)
    result = render(path, document, output=destination, compare_policies=True)
    write_text(destination, page(document['change']['id'], data, comparison,
                                 assessment=document.get('assessment'), inference=document['inference_seconds'],
                                 analysis=document['selection_seconds']))
    return {**result, 'html': str(destination.resolve()), 'new_jev_requests': 0}


def demo_report(output):
    names = ['tests/checkout.test.ts', 'tests/tax.test.ts', 'features/refunds.feature', 'tests/search.test.ts']
    scores = dict(zip(names, [.82, .36, .14, .02]))
    scenarios = []
    for threshold in (.1, .25, .5):
        actions = {name: 'RUN' if score >= threshold else 'OMIT' for name, score in scores.items()}
        count = sum(a == 'RUN' for a in actions.values())
        scenarios.append({'kind': 'relevance', 'label': f'Relevance ≥ {threshold:.0%}', 'approaches': {'jev': {
            'would_run': count, 'would_omit': len(names) - count, 'run_policy': count, 'run_required': 0,
            'run_unresolved': 0, 'full_suites': [], 'actions': actions,
            'reasons': {name: {'reason': f'Mock relevance {score:.0%}'} for name, score in scores.items()}}}})
    data = {'target_count': len(names), 'targets': [{'target': n} for n in names], 'pricing': None,
            'policies': {'jev': {'valid_judgments': 4, 'input_usd_estimate': .02, 'input_tokens': 10000, 'requests': 1}}}
    destination = Path(output).with_suffix('.html')
    write_text(destination, page('Example: change checkout tax rounding', data,
                                {'scenarios': scenarios, 'relevance_probabilities': {'jev': scores}},
                                assessment={'invocation_seconds': 3.2, 'new_answers': 4, 'resumed_answers': 0,
                                            'reused_answers': 0, 'timing_scope': 'Invented demo timings.'},
                                inference=2.1, analysis=2.8, demo=True))
    return {'html': str(destination.resolve()), 'demo': True, 'execution': 'none', 'jev_requests': 0}
