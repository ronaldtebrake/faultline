"""Offline graph assessment. Predictions never authorize CI omissions."""
import csv
from html import escape
from pathlib import Path
import re
import time
import uuid

from ..core import FaultlineError, now, read_json, write_json
from .common import checked, save_frozen, seal
from .config import SCHEMA, load_config
from .dependency_graph import build, compare
from .dependency_query import affected
from .selection import change, decisions, workspace
from .source_index import open_index


def markdown(document, *, limit=None):
    """List proposed work, without turning missing paths into omissions."""
    def cell(value):
        return escape(str(value)).replace('|', '&#124;').replace('\n', ' ')
    counts = document['summary']
    lines = ['## Graph prediction (not applied)', '',
             'Full CI runs every normal test. Jev is off. Unresolved tests are not safe omissions.', '',
             f"**Would run: {counts['affected'] + counts['required']} source targets** "
             f"({counts['affected']} graph hits, {counts['required']} mandatory). "
             f"**Unresolved: {counts['unresolved']}.**", '',
             f"Base: `{document['change']['base']}` · Head: `{document['change']['head']}`", '',
             '| Would-run source target | Reason | Dependency path |', '| --- | --- | --- |']
    used = len(('\n'.join(lines) + '\n').encode())
    candidates = [r for r in document['tests'] if r['status'] != 'unresolved']
    for index, row in enumerate(candidates):
        path = ' → '.join(row['paths'][0]['path']) if row['paths'] else 'Mandatory execution rule'
        line = f"| {cell(row['id'])} | {cell(', '.join(row['reasons']))} | {cell(path)} |"
        if limit and used + len(line.encode()) + 1024 > limit:
            lines += ['', f"{len(candidates) - index} more candidates are in the complete HTML/CSV artifact."]
            break
        lines.append(line)
        used += len((line + '\n').encode())
    if not candidates:
        lines += ['| No positive candidates | Keep full CI; dependency coverage is incomplete | |']
    graph = document['graph']
    lines += ['', f"New files: {len(graph.get('added_files', []))}; "
              f"new test targets: {len(graph.get('added_targets', []))}. "
              'The artifact includes every target, unresolved rows and all known paths.', '']
    return '\n'.join(lines)


def report(document, output):
    output = Path(output).with_suffix('')
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(document['tests'], key=lambda r: (r['status'] == 'unresolved', r['id']))
    summary = document['summary']
    heading = f"Graph assessment: {document['change']['id']}"
    note = ('Full CI remains required. Affected paths and mandatory rules identify candidates; '
            'unresolved means no known path, not permission to omit. Jev is off: zero requests and $0 cost.')
    html_rows = ''.join('<tr>' + ''.join(f'<td>{escape(str(value))}</td>' for value in
                       (r['status'], r['id'], ', '.join(r['reasons']), '\n'.join(' → '.join(p['path']) for p in r['paths']))) + '</tr>' for r in rows)
    output.with_suffix('.html').write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        f'<title>{escape(heading)}</title><style>body{{font:16px system-ui;margin:2rem;line-height:1.5}}'
        'table{border-collapse:collapse;width:100%}td,th{padding:.6rem;border:1px solid #ccc;text-align:left;'
        'vertical-align:top;white-space:pre-wrap;overflow-wrap:anywhere}code{overflow-wrap:anywhere}</style>'
        f'<h1>{escape(heading)}</h1><p>{escape(note)}</p><p><strong>Would run (not applied): {summary["affected"] + summary["required"]} source targets.</strong></p><p>{summary["affected"]} affected · '
        f'{summary["required"]} required by rules · {summary["unresolved"]} unresolved</p>'
        f'<p>Base <code>{escape(document["change"]["base"])}</code><br>Head <code>{escape(document["change"]["head"])}</code></p>'
        '<table><thead><tr><th>Status</th><th>Test</th><th>Reasons</th><th>Known paths</th></tr></thead>'
        f'<tbody>{html_rows}</tbody></table></html>', encoding='utf-8')
    with output.with_suffix('.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['status', 'test', 'reasons', 'paths'])
        for row in rows:
            values = [row['status'], row['id'], ', '.join(row['reasons']), '\n'.join(' -> '.join(p['path']) for p in row['paths'])]
            writer.writerow(["'" + v if v.startswith(('=', '+', '-', '@')) else v for v in values])
    output.with_suffix('.md').write_text(markdown(document), encoding='utf-8')
    return {kind: str(output.with_suffix('.' + kind).resolve()) for kind in ('html', 'md', 'csv')} | {
        'new_jev_requests': 0, 'execution': 'none', 'omission_authorized': False, 'ci_policy': 'full_suite'}


def assess(store, *, base=None, head='HEAD', identifier=None, title='', description='',
           runtime_paths=(), prepare=False, resume=None, output=None):
    started = time.monotonic()
    store.initialize()
    if resume:
        if not re.fullmatch(r'[a-f0-9]{32}', resume):
            raise FaultlineError('Invalid graph assessment run ID')
        folder = store.path / 'runs' / resume
        checked(folder / 'run.json', 'graph-run')
        latest = read_json(folder / 'latest.json', {})
        if not re.fullmatch(r'[a-f0-9]{64}\.json', latest.get('benchmark', '')):
            raise FaultlineError('No frozen graph report; run a new assessment')
        path = folder / latest['benchmark']
        document = checked(path, 'graph-assessment')
        return {**document, 'path': str(path), **report(document, folder / 'report')}
    if not base:
        raise FaultlineError('Supply --base with the cumulative PR merge base')
    config = load_config(store.root)
    context = change(store.root, base, head, identifier)
    before = build(store, context['base'], runtime_paths=runtime_paths)
    after = build(store, context['head'], runtime_paths=runtime_paths)
    comparison = compare(before['graph'], after['graph'])
    paths = affected(after['graph'], context['changed_files'], base=before['graph'])['explanations'] if context['changed_files'] else {}
    source, inventory, _ = open_index(store, config, context['head'])
    suites, _, _, unknown = decisions(store.root, config, inventory, context, workspace(store.root), source, include_profiles=False)
    reached = set(comparison['affected'])
    # Propagate existing prerequisite rules without invoking discovery or runners.
    required_suites = {p for s in suites if s['fallbacks'] or unknown or any(s['reasons'].values()) or reached.intersection(s['reasons']) for p in s['prerequisites']}
    while True:
        expanded = required_suites | {p for s in suites if s['suite'] in required_suites for p in s['prerequisites']}
        if expanded == required_suites:
            break
        required_suites = expanded
    rows = []
    for suite in suites:
        for unit in suite['units']:
            key = unit['id']
            reasons = list(suite['reasons'][key]) + suite['fallbacks']
            if unknown:
                reasons.append('change_outside_declared_scope')
            if suite['suite'] in required_suites:
                reasons.append('prerequisite_suite')
            status = 'affected' if key in reached else ('required' if reasons else 'unresolved')
            if key in reached:
                reasons.append('positive_dependency_path_or_new_target')
            rows.append({'id': key, 'source': unit['source'], 'suite': suite['key'], 'status': status,
                         'reasons': sorted(set(reasons)), 'paths': paths.get(key, []), 'warnings': suite['warnings']})
    run_id = uuid.uuid4().hex
    document = seal({'schema_version': SCHEMA, 'kind': 'graph-assessment', 'evaluator': 'graph-v1',
        'run_id': run_id, 'created_at': now(), 'change': {k: context[k] for k in ('id', 'base', 'head', 'changed_files')},
        'title': title, 'description': description, 'tests': rows,
        'summary': {status: sum(r['status'] == status for r in rows) for status in ('affected', 'required', 'unresolved')},
        'graph': comparison, 'unknown_paths': unknown,
        'source_gaps': {p: n['gaps'] for p, n in after['graph']['nodes'].items() if n['gaps']},
        'complete': inventory['complete'], 'coverage_complete': False,
        'preparation': {k: before[k] + after[k] for k in ('parsed', 'reused')},
        'assessment_seconds': time.monotonic() - started, 'jev_requests': 0, 'cost_usd': 0,
        'execution': 'none', 'ci_policy': 'full_suite', 'omission_authorized': False})
    if prepare:
        return {**document, 'dry_run': True}
    folder = store.path / 'runs' / run_id
    save_frozen(folder / 'run.json', {'schema_version': SCHEMA, 'kind': 'graph-run', 'evaluator': 'graph-v1', 'run_id': run_id})
    path = folder / (document['integrity'] + '.json')
    save_frozen(path, document)
    if output:
        save_frozen(output, document)
    write_json(folder / 'latest.json', {'benchmark': path.name})
    return {**document, 'path': str(path.resolve()), **report(document, folder / 'report')}
