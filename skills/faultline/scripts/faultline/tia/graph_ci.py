"""Packaged source-baseline CI orchestration; never a test execution policy."""
import json
import os
from pathlib import Path

from ..core import FaultlineError, write_json
from .common import checked, git, revision, save_frozen
from .dependency_graph import build
from .dependency_query import file_names
from .dependency_shared import metrics, pack, producer, NO_EXECUTION
from .dependency_shared_github import fetch
from .graph_assessment import assess, markdown, report


def expectations(value):
    """Optional experiment controls. Routine installations need none."""
    if value is None:
        return {}
    try:
        value = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        raise FaultlineError('Graph expectations must be a JSON object') from None
    allowed = {'restored', 'parsed', 'min_reused', 'affected', 'new_files', 'new_targets', 'paths'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise FaultlineError('Unsupported graph expectation fields')
    if 'restored' in value and type(value['restored']) is not bool:
        raise FaultlineError('Expected restored must be a boolean')
    for key in ('parsed', 'min_reused'):
        if key in value and (type(value[key]) is not int or value[key] < 0):
            raise FaultlineError('Expected parser counts must be nonnegative integers')
    for key in ('affected', 'new_files', 'new_targets'):
        if key in value:
            if not isinstance(value[key], list):
                raise FaultlineError('Expected sources must be arrays of literal paths')
            if value[key]:
                file_names(value[key])
    if 'paths' in value:
        if not isinstance(value['paths'], list):
            raise FaultlineError('Expected paths must be an array of source/input objects')
        for row in value['paths']:
            if not isinstance(row, dict) or set(row) != {'source', 'input'}:
                raise FaultlineError('Expected path needs source and input')
            file_names([row['source'], row['input']])
    return value


def verify(document, restored, built, expected):
    failures = []
    if (document['evaluator'] != 'graph-v1' or document['jev_requests'] != 0 or document['cost_usd'] != 0 or
            document['ci_policy'] != 'full_suite' or document['omission_authorized'] or document['coverage_complete']):
        failures.append('Graph CI must remain offline and require full test execution')
    for key, actual in [('restored', restored['restored']), ('parsed', built['parsed'])]:
        if key in expected and expected[key] != actual:
            failures.append(f'Expected {key}={expected[key]}, observed {actual}')
    if built['reused'] < expected.get('min_reused', 0):
        failures.append('Parser reuse is below the expected minimum')
    positive = {r['source'] for r in document['tests'] if r['status'] == 'affected'}
    new_ids = set(document['graph']['added_targets'])
    new_targets = {r['source'] for r in document['tests'] if r['id'] in new_ids}
    for key, actual in [('affected', positive), ('new_files', set(document['graph']['added_files'])), ('new_targets', new_targets)]:
        for path in expected.get(key, []):
            if path not in actual:
                failures.append(f'Expected {key}: {path}')
    for wanted in expected.get('paths', []):
        if not any(r['source'] == wanted['source'] and any(p['input'] == wanted['input'] for p in r['paths']) for r in document['tests']):
            failures.append(f"Expected dependency path from {wanted['source']} to {wanted['input']}")
    return failures


def run(store, *, base, compare_base=None, trusted_branch=None, workflow=None,
        output=None, publish_baseline=False, expected=None, environ=None):
    env = dict(os.environ if environ is None else environ)
    expected = expectations(expected)
    folder = Path(output or store.path / 'ci-graph').resolve()
    folder.mkdir(parents=True, exist_ok=True)
    # Never mix attempts or silently replace frozen CI evidence.
    if (folder / 'result.json').exists():
        raise FaultlineError('Graph CI output already exists; use a fresh output directory')
    store.initialize()
    head = revision(store.root)
    bases = {'cumulative': git(store.root, 'merge-base', revision(store.root, base), head)}
    if compare_base:
        bases['stacked'] = git(store.root, 'merge-base', revision(store.root, compare_base), head)
    repository = env.get('GITHUB_REPOSITORY', '').lower()
    if not workflow:
        workflow = env.get('GITHUB_WORKFLOW_REF', '').split('/.github/workflows/', 1)[-1].split('@', 1)[0]
    meta = None
    if publish_baseline:
        try:
            meta = producer({'repository': repository, 'repository_id': int(env['GITHUB_REPOSITORY_ID']),
                'workflow': workflow, 'run_id': int(env['GITHUB_RUN_ID']), 'run_attempt': int(env['GITHUB_RUN_ATTEMPT']),
                'revision': env['GITHUB_SHA'], 'event': env['GITHUB_EVENT_NAME'], 'branch': env['GITHUB_REF_NAME'], 'collections': []})
        except (KeyError, ValueError):
            raise FaultlineError('Publishing a baseline requires complete GitHub push provenance') from None
        if meta['revision'] != head:
            raise FaultlineError('GitHub event SHA does not match the checked-out revision')
    restored = {'restored': False, 'reason': 'no_trusted_branch_configured', **NO_EXECUTION}
    if trusted_branch:
        if not repository or not workflow:
            raise FaultlineError('Restoring a CI baseline requires GitHub repository and workflow identity')
        restored = fetch(store, folder / 'downloaded-baseline.json', repository=repository, workflow=workflow, branch=trusted_branch)
    write_json(folder / 'restore.json', restored)
    built = build(store, head, output=folder / 'graph.json')
    build_result = {**metrics(built), **NO_EXECUTION}
    write_json(folder / 'build.json', build_result)
    documents, outputs, failures = {}, {}, []
    for name, diff_base in bases.items():
        result = assess(store, base=diff_base, head=head)
        doc = checked(result['path'], 'graph-assessment')
        save_frozen(folder / (name + '.json'), doc)
        outputs[name] = {**report(doc, folder / name), 'json': str(folder / (name + '.json')), 'summary': doc['summary']}
        documents[name] = doc
        failures += verify(doc, restored, build_result, {})
    failures += verify(documents.get('stacked', documents['cumulative']), restored, build_result, expected)
    bundle = {'schema_version': 1, 'kind': 'graph-ci', 'head': head, 'bases': bases,
        'restore': restored, 'build': build_result, 'reports': outputs,
        'validation': {'passed': not failures, 'failures': sorted(set(failures)), 'expectations': expected},
        'complete': all(d['complete'] for d in documents.values()),
        'ci_policy': 'full_suite', 'coverage_complete': False, **NO_EXECUTION}
    write_json(folder / 'result.json', bundle)
    summary = ['# Faultline — full CI retained', '',
        f"Baseline restored: **{restored['restored']}**. Parsed: **{built['parsed']}**; reused: **{built['reused']}**.",
        'Source facts only; runtime coverage and regression recall are not established.', '']
    for name, doc in documents.items():
        summary += [f'### {name.title()} change', '', markdown(doc, limit=48 * 1024)]
    if failures:
        summary += ['Validation failed. See result.json for the expected and observed values.']
    text = '\n'.join(summary)
    (folder / 'summary.md').write_text(text, encoding='utf-8')
    if env.get('GITHUB_STEP_SUMMARY'):
        with Path(env['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as stream:
            stream.write(text)
    if failures:
        raise FaultlineError('Graph CI validation failed: ' + '; '.join(sorted(set(failures))))
    if meta:
        bundle['baseline'] = pack(store, folder / 'baseline.json', producer_data=meta)
        write_json(folder / 'result.json', bundle)
    return bundle
