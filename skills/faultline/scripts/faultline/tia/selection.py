"""Freeze an outcome-blind shadow proposal from Git source targets and Jev."""
from __future__ import annotations

import subprocess
import re
import time

from ..core import FaultlineError, digest, now, number
from .batch import BATCH_VERSION, BatchedJev
from .common import checked, hashes, revision, save_frozen, seal
from .config import load_config, matches, variants
from .mapping import covered_units
from .. import __version__
from .evidence import test_profile

POLICY = 'jev-source-targets-v1'
REQUIRED = {'whole_check_requires_full_execution', 'changed_or_new_test', 'must_run_rule',
            'description_setup_changed', 'positive_coverage_or_dependency_match'}


def git_output(root, *args):
    p = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if p.returncode:
        raise FaultlineError('Git could not read the change or workspace')
    return p.stdout


def workspace(root):
    diff = git_output(root, 'diff', '--no-ext-diff', '--no-textconv', '--binary', 'HEAD', '--')
    untracked = [p for p in git_output(root, 'ls-files', '--others', '--exclude-standard', '-z').split('\0') if p]
    return {'head': revision(root), 'diff_hash': digest(diff), 'untracked': hashes(root, untracked),
            'clean': not diff and not untracked}


def change(root, base, head, identifier=None):
    base, head = revision(root, base), revision(root, head)
    files = git_output(root, 'diff', '--no-renames', '--name-only', '-z', base, head, '--').split('\0')
    return {'id': identifier or head, 'base': base, 'head': head,
            'changed_files': sorted(p for p in files if p),
            'diff': git_output(root, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--binary', base, head, '--'),
            'title': '', 'description': ''}


def inventory_identity(inventory):
    return digest({key: inventory[key] for key in ('head', 'config_hash', 'suites', 'execution_inputs', 'complete')})


def decisions(root, config, inventory, context, snapshot, source, *, include_profiles=True):
    changed = context['changed_files']
    suite_configs = {key: (suite, variant) for suite, variant, key in variants(config)}
    bounded = [*config['scope'], 'faultline.json']
    bounded += [p for s in config['suites'] for p in (*s['scope'], *s['sources'], *s['shared_inputs'], *s['description_inputs'])]
    unknown = [p for p in changed if not matches(p, bounded)]
    results, profiles, evidence = [], [], {}
    for native in inventory['suites']:
        suite, variant = suite_configs[native['key']]
        reasons = {u['id']: [] for u in native['units']}
        fallbacks = []
        warnings = []
        if not native['complete']:
            fallbacks.append('no_configured_source_targets')
        if snapshot['head'] != context['head'] or not snapshot['clean']:
            warnings.append('git_revision_analyzed_with_local_configuration')
        if unknown:
            warnings.append('change_outside_declared_scope')
        if 'faultline.json' in changed or any(matches(p, suite['shared_inputs']) for p in changed):
            fallbacks.append('suite_configuration_or_shared_setup_changed')
        if any(matches(p, suite['sources']) and p not in {u['source'] for u in native['units']} for p in changed):
            fallbacks.append('changed_test_source_not_in_inventory')
        if any(u.get('requires_full_suite') for u in native['units']):
            fallbacks.append('cross_test_dependencies_require_full_execution')
        for u in native['units']:
            id = u['id']
            if u.get('kind') == 'check':
                reasons[id].append('whole_check_requires_full_execution')
                continue
            if u['source'] in changed:
                reasons[id].append('changed_or_new_test')
            if matches(id, suite['must_run']) or matches(u['source'], suite['must_run']):
                reasons[id].append('must_run_rule')
            if any(matches(p, suite['description_inputs']) for p in changed):
                reasons[id].append('description_setup_changed')
        for path in suite['relationships']:
            try:
                mapping = checked(root / path, 'relationships')
                evidence[path] = mapping['integrity']
                if mapping.get('suite') != suite['id'] or mapping.get('variant') != native['variant']:
                    raise FaultlineError('mapping_suite_or_variant_mismatch')
                if mapping.get('revision') not in (context['base'], context['head']):
                    raise FaultlineError('mapping_revision_outside_change')
                if not isinstance(mapping.get('edges'), list):
                    raise FaultlineError('invalid_mapping_edges')
                matched = covered_units(mapping, native['units'], changed)
                if matched['unmatched']:
                    fallbacks.append('unmatched_positive_mapping_identity')
                for id in matched['required']:
                    reasons[id].append('positive_coverage_or_dependency_match')
            except (FaultlineError, KeyError, TypeError) as exc:
                fallbacks.append('unusable_relationship_evidence')
        # Execution rules never gate semantic scoring.
        for u in native['units'] if include_profiles else []:
            if u.get('kind') == 'check':
                continue
            try:
                profiles.append(test_profile(source, u, suite, variant))
            except FaultlineError as exc:
                reasons[u['id']].append('source_evidence_unavailable')
                evidence[u['id']] = str(exc)
        results.append({'key': native['key'], 'suite': native['suite'], 'variant': native['variant'],
                        'configured_mode': suite['mode'], 'execution': 'none',
                        'kind': suite['kind'], 'native_complete': native['native_complete'],
                        'prerequisites': suite['prerequisites'], 'threshold': suite['irrelevant_threshold'],
                        'reasons': reasons, 'warnings': sorted(set(warnings)), 'fallbacks': sorted(set(fallbacks)), 'units': native['units']})
    return results, profiles, evidence, unknown


def select(store, base, head='HEAD', *, identifier=None, output=None, dry_run=False, evaluator=None,
           native=False, max_requests=None, selection_seconds=None, prepare=False):
    started = time.monotonic()
    store.initialize()
    config = load_config(store.root)
    if max_requests is not None:
        number(max_requests, 'max_requests', allow_zero=True)
        config['evaluator']['jev_requests'] = max_requests
    if selection_seconds is not None:
        number(selection_seconds, 'selection_seconds')
        config['evaluator']['selection_seconds'] = selection_seconds
    context = change(store.root, base, head, identifier)
    if native and (revision(store.root) != context['head'] or not workspace(store.root)['clean']):
        raise FaultlineError('Optional native enrichment requires a clean tested checkout; omit --native for source-only analysis')
    snapshot = workspace(store.root)
    source_started = time.monotonic()
    from .source_index import open_index
    source, raw_inventory, index_provenance = open_index(store, config, context['head'])
    inventory = open_index(store, config, context['head'], native=True)[1] if native else raw_inventory
    source_seconds = time.monotonic() - source_started
    suites, profiles, evidence, unknown = decisions(store.root, config, inventory, context, snapshot, source)
    for suite in suites:
        if unknown:
            suite['fallbacks'].append('change_outside_declared_scope')
    inference_started = time.monotonic()
    evaluator = evaluator or BatchedJev(store, config['evaluator'], deadline=time.monotonic() + config['evaluator']['selection_seconds'])
    evaluate = evaluator.evaluate_source if isinstance(evaluator, BatchedJev) else evaluator.evaluate
    result = evaluate(context, profiles, dry_run=dry_run or prepare)
    inference_seconds = time.monotonic() - inference_started
    if dry_run or prepare:
        return {'dry_run': True, 'change': {k: context[k] for k in ('id', 'base', 'head', 'changed_files')},
                'candidate_units': sum(len(s['units']) for s in suites),
                'analysis_mode': 'jev', 'estimate': result, 'index': index_provenance, 'unknown_paths': unknown,
                'fallbacks': {s['key']: s['fallbacks'] for s in suites}, 'execution': 'none', 'mode': 'shadow'}
    for suite in suites:
        ids = set(suite['reasons'])
        if ids.intersection(result['errors']):
            suite['warnings'].append('semantic_evaluation_incomplete')
        selected, omitted = [], []
        for id, reasons in suite['reasons'].items():
            judgment = result['rows'].get(id)
            if id in result['errors']:
                reasons.append('semantic_evaluation_incomplete')
            if suite['fallbacks']:
                reasons.extend(suite['fallbacks'])
            if not reasons and judgment is None:
                reasons.append('missing_semantic_judgment')
            if not reasons and judgment.get('all_parts_irrelevant_probability', judgment['probabilities']['irrelevant']) >= suite['threshold']:
                reasons.append('irrelevant_probability_meets_proposal_threshold')
                omitted.append(id)
            else:
                if not reasons:
                    reasons.append('semantic_relevance_or_uncertainty')
                selected.append(id)
        suite['proposed_selected'] = sorted(selected)
        suite['proposed_omitted'] = sorted(omitted)
        suite['execution_reasons'] = ['shadow_report_only', 'execution_requires_explicit_opt_in']
        if suite['configured_mode'] == 'experimental':
            suite['execution_reasons'].append('experimental_execution_not_enabled_in_this_engine_version')
    # Proposals also retain prerequisite suites whenever a dependent proposes work.
    required = {p for s in suites if s['proposed_selected'] or s['fallbacks'] for p in s['prerequisites']}
    while required:
        name = required.pop()
        for suite in suites:
            if suite['suite'] != name:
                continue
            if suite['proposed_omitted']:
                for id in suite['proposed_omitted']:
                    suite['reasons'][id].append('execution_prerequisite')
                suite['proposed_selected'] = sorted(suite['reasons'])
                suite['proposed_omitted'] = []
                required.update(suite['prerequisites'])
    # Freeze comparison policies before any outcomes are imported. Each receives
    # the same unit-count budget; lexical/path scores are deterministic baselines.
    source_texts = {p['id']: p['source_text'] for p in profiles}
    for suite in suites:
        count = len(suite['proposed_selected'])
        units = suite['units']
        tokens = set(re.findall(r"[a-z][a-z0-9_]+", context['diff'].lower()))
        def lexical(u):
            description = source_texts.get(u['id'], u['title'])
            return len(tokens & set(re.findall(r"[a-z][a-z0-9_]+", description.lower())))
        suite['baselines'] = {
            'random': [u['id'] for u in sorted(units, key=lambda u: digest([context['base'], context['head'], config['evaluator']['random_seed'], u['id']]))[:count]],
            'path': [u['id'] for u in sorted(units, key=lambda u: (-max((len(set(u['source'].split('/')[:-1]) & set(p.split('/')[:-1])) for p in context['changed_files']), default=0), u['id']))[:count]],
            'lexical': [u['id'] for u in sorted(units, key=lambda u: (-lexical(u), u['id']))[:count]],
            'jev': [u['id'] for u in sorted(units, key=lambda u: (-result['rows'].get(u['id'], {}).get('score', 4), u['id']))[:count]]}
    # Detect source changes during discovery/inference before freezing any decision.
    if workspace(store.root) != snapshot:
        raise FaultlineError('Workspace changed during selection; no selection was frozen')
    billed = result['usage']
    tokens = sum(x['input_tokens'] for x in billed) if len(billed) == result['requests'] and all(x is not None for x in billed) else None
    pricing = config['evaluator']['pricing']
    cost = {'input_tokens': tokens, 'pricing': pricing,
            'input_usd_estimate': tokens * pricing['input_usd_per_million'] / 1000000 if tokens is not None and pricing else None,
            'agent_cost': None}
    target_ids = {u['id'] for suite in suites for u in suite['units'] if u.get('kind') != 'check'}
    scored = target_ids.intersection(result['rows'])
    complete_ids = {id for id in scored if id not in result['errors']}
    semantic = {'targets': len(target_ids), 'scored': len(scored), 'fully_scored': len(complete_ids),
                'unscored': len(target_ids - scored), 'partial': len(scored - complete_ids),
                'status': 'complete' if target_ids and target_ids == complete_ids else ('partial' if scored else 'not_evaluated'),
                'errors': {**{id: evidence[id] for id in target_ids if id in evidence}, **result['errors']}}
    semantic_complete = bool(target_ids) and target_ids == complete_ids
    document = seal({'schema_version': 2, 'kind': 'selection', 'mode': 'shadow', 'execution': 'none', 'created_at': now(), 'engine_version': __version__, 'policy': POLICY,
                     'analysis_mode': 'jev',
                     'repository': config['repository'], 'change': context, 'workspace': snapshot,
                     'source_provenance': {'revision': context['head'], 'configuration': 'local faultline.json', 'configuration_hash': config['config_hash']},
                     'config_hash': config['config_hash'], 'inventory': inventory,
                     'inventory_hash': inventory_identity(raw_inventory), 'index': index_provenance, 'relationship_evidence': evidence,
                     'evaluator': {'model': config['evaluator']['model'], 'batch_version': BATCH_VERSION},
                     'suites': suites, 'judgments': result['rows'], 'semantic_errors': result['errors'],
                     'usage': {k: result[k] for k in ('batches', 'requests', 'cache_hits', 'uncached_requests', 'usage', 'unique_evidence_targets', 'evidence_pairs', 'diff_fragments', 'remaining_requests', 'request_ceiling', 'target_completion_ceiling', 'blocked_targets', 'uncached_payload_bytes', 'pacing_floor_seconds', 'selection_seconds_limit') if k in result},
                     'selection_seconds': time.monotonic() - started, 'source_seconds': source_seconds,
                     'inference_seconds': inference_seconds, 'cost': cost, 'unknown_paths': unknown,
                     'complete': True, 'semantic_complete': semantic_complete, 'semantic': semantic,
                     'limitations': ['Shadow mode is report-only; no tests are executed.',
                                     'Jev relevance is not measured code coverage or a predicted failure probability.',
                                     'Source targets are provisional; executable identities are validated only during execution.',
                                     'CI must authenticate artifact producers; integrity hashes alone do not establish trust. Experimental execution is not enabled.']})
    output = output or store.path / 'selections' / document['integrity'] / 'selection.json'
    save_frozen(output, document)
    # Retain a canonical snapshot even when the caller chooses a custom output.
    save_frozen(store.path / 'selections' / document['integrity'] / 'selection.json', document)
    from .proposals import report_selection
    proposal_report = report_selection(store, document)
    return {'report': proposal_report, 'path': str(output), 'selection_id': document['integrity'], 'complete': True,
            'analysis_mode': document['analysis_mode'],
            'semantic_complete': document['semantic_complete'], 'semantic': semantic, 'index': index_provenance, 'usage': document['usage'],
            'proposed_selected': sum(len(s['proposed_selected']) for s in suites),
            'proposed_omitted': sum(len(s['proposed_omitted']) for s in suites),
            'execution': 'none', 'mode': 'shadow', 'targets': 'provisional_source_files',
            'native_validation': 'required_at_execution', 'fallbacks': {s['key']: s['fallbacks'] for s in suites}}
