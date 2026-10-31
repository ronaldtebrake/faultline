"""Small offline Noul report; execution manifests remain independent."""
import csv
import html
from pathlib import Path
from .ci_manifest import from_assessment, fingerprint
from .config import load_config
from ..core import FaultlineError


def report(store, document, output):
    config = load_config(store.root)
    if fingerprint(config) != document['execution_config']:
        raise FaultlineError('Use the assessment configuration to regenerate its report')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    records = {}
    dependency_selected = (document.get('dependency_evidence') or {}).get('selected', {})
    from .dependency_semantics import actions as relationship_actions
    relationship_evidence = document.get('relationship_evidence') or {}
    relationships = relationship_actions(relationship_evidence)
    for suite in document['suites']:
        for unit in suite['units']:
            records[unit['id']] = {'id': unit['id'], 'suite': suite['suite'], 'file': unit['source'],
                                   'impact': document['scores'].get(unit['id']),
                                   'relationship_action': relationships.get(unit['id'], '')}
    summaries = []
    for threshold in (.10, .25, .50):
        manifest, reasons = from_assessment(document, config, threshold)
        selected = 0
        for record in records.values():
            entry = manifest['suites'][record['suite']]
            run = entry['mode'] == 'all' or record['file'] in entry.get('files', [])
            record['run_' + str(int(threshold * 100))] = run
            selected += run
        summaries.append((threshold, selected, len(records) - selected))
    cost = document['usage']
    lines = ['# Jev impact assessment', '', 'Experimental noul-v1; no tests executed.', '',
             f"Revision: `{document['revision']}`", '',
             f"Jev assessed: {len(document['scores'])}/{len(records)}; retained by dependency evidence without scoring: {len(dependency_selected)}. Known input cost: ${cost['known_usd']:.6f}; conservative upper bound: ${cost['upper_usd']:.6f}.",
             '', '| Cutoff | RUN | OMIT |', '| --- | ---: | ---: |']
    lines += [f'| {t:.0%} | {run} | {omit} |' for t, run, omit in summaries]
    if relationship_evidence:
        scope = relationship_evidence['scope']
        relationship_detail = (f"Relationship fallback: {scope.get('fallback') or 'none'}; "
                               f"unowned changed files: {len(scope['uncovered'])}; "
                               f"test evidence fallbacks: {len(relationship_evidence['fallbacks'])}; "
                               f"cache warnings: {len(relationship_evidence['cache_warnings'])}. "
                               'Exact paths and reasons are retained in the assessment JSON.')
        lines += ['', f"Surface relationships: {relationship_evidence['cached_pairs']} reused pairs; {relationship_evidence['fresh_pairs']} fresh pairs. "
                  f"Their separate, frozen retention cutoff is {relationship_evidence['threshold']:.1%}; the impact cutoffs above do not change it.",
                  '', relationship_evidence['limitation'], '', relationship_detail]
    lines += ['', f"Input tokens: {cost['input_tokens']}; unknown-usage attempts: {cost['unknown_attempts']}.",
              f"Source: {document['timing']['source_seconds']:.2f}s; preparation: {document['timing']['planning_seconds']:.2f}s; scoring this invocation: {document['timing']['scoring_seconds']:.2f}s.", '', document['limitation'], '', 'RUN includes execution requirements and suite fallbacks; scores are retained independently.', '',
              '| Test | Impact | 10% | 25% | 50% |', '| --- | ---: | --- | --- | --- |']
    rows = []
    for record in sorted(records.values(), key=lambda r: (-(r['impact'] if r['impact'] is not None else 2), r['id'])):
        score = ('dependency/required execution' if record['id'] in dependency_selected else
                 'surface relationship: ' + relationships[record['id']] if record['id'] in relationships else
                 'unresolved') if record['impact'] is None else f"{record['impact']:.1%}"
        actions = ['RUN' if record['run_' + str(t)] else 'OMIT' for t in (10, 25, 50)]
        lines.append('| ' + record['id'].replace('|', '\\|') + ' | ' + score + ' | ' + ' | '.join(actions) + ' |')
        rows.append('<tr><td>' + html.escape(record['id']) + '</td><td>' + score + '</td>' + ''.join('<td>' + a + '</td>' for a in actions) + '</tr>')
    markdown = output.with_suffix('.md')
    markdown.write_text('\n'.join(lines) + '\n')
    page = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Faultline assessment</title><style>body{max-width:1100px;margin:40px auto;padding:20px;font:16px/1.5 system-ui;color:#18302b}table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left;overflow-wrap:anywhere}td:first-child{max-width:600px}code{overflow-wrap:anywhere}</style><h1>Jev impact assessment</h1>'
    page += '<p>' + html.escape(lines[6]) + '</p><p>Revision: <code>' + document['revision'] + '</code></p>'
    page += '<table><tr><th>Cutoff</th><th>RUN</th><th>OMIT</th></tr>' + ''.join(f'<tr><td>{t:.0%}</td><td>{run}</td><td>{omit}</td></tr>' for t, run, omit in summaries) + '</table>'
    page += '<p>' + html.escape(f"Input tokens: {cost['input_tokens']}; unknown attempts: {cost['unknown_attempts']}; scoring: {document['timing']['scoring_seconds']:.2f}s.") + '</p>'
    page += '<p>' + html.escape(document['limitation']) + '</p><p>RUN includes mandatory execution and fallback rules.</p><table><tr><th>Test</th><th>Impact</th><th>10%</th><th>25%</th><th>50%</th></tr>' + ''.join(rows) + '</table>'
    if relationship_evidence:
        page += '<p>' + html.escape(f"Surface relationships: {relationship_evidence['cached_pairs']} reused pairs; {relationship_evidence['fresh_pairs']} fresh pairs. "
                                  f"Separate retention cutoff: {relationship_evidence['threshold']:.1%}. " + relationship_evidence['limitation']) + '</p>'
        page += '<p>' + html.escape(relationship_detail) + '</p>'
    output.with_suffix('.html').write_text(page)
    with output.with_suffix('.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'suite', 'file', 'impact', 'relationship_action', 'run_10', 'run_25', 'run_50'])
        writer.writeheader()
        writer.writerows(records.values())
    return {'html': str(output.with_suffix('.html')), 'markdown': str(markdown), 'csv': str(output.with_suffix('.csv')), 'new_jev_requests': 0}
