"""Freeze an outcome-blind shadow proposal from source targets, CodeGraph, and Jev."""
from __future__ import annotations

import subprocess
import re
import time
from pathlib import Path

from ..core import FaultlineError, digest, now
from . import catalog, graph
from .batch import BATCH_VERSION, BatchedJev
from .common import checked, file_hash, hashes, revision, save_frozen, seal
from .config import load_config, matches, variants
from .mapping import covered_units

POLICY = 'codegraph-jev-shadow-v2'


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


def records(root, inventory):
    return {u['id']: catalog.load_record(root, u) for s in inventory['suites'] for u in s['units']}


def decisions(root, config, inventory, context, description_records, snapshot, graph_evidence):
    changed = context['changed_files']
    suite_configs = {key: suite for suite, _, key in variants(config)}
    bounded = [*config['scope'], 'faultline.json', 'faultline/catalog/**']
    bounded += [p for s in config['suites'] for p in (*s['scope'], *s['sources'], *s['shared_inputs'], *s['description_inputs'])]
    unknown = [p for p in changed if not matches(p, bounded)]
    results, profiles, evidence = [], [], {}
    for native in inventory['suites']:
        suite = suite_configs[native['key']]
        reasons = {u['id']: [] for u in native['units']}
        fallbacks = list(graph_evidence['fallbacks'])
        if not native['complete']:
            fallbacks.append('no_configured_source_targets')
        if snapshot['head'] != context['head'] or not snapshot['clean']:
            fallbacks.append('checkout_does_not_match_clean_tested_revision')
        if unknown:
            fallbacks.append('unbounded_change_scope')
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
            if graph_evidence['paths'].get(u['source']):
                reasons[id].append('positive_code_graph_match')
            if u['source'] in graph_evidence['unmapped_tests']:
                reasons[id].append('test_source_without_usable_graph')
            if u['source'] in changed:
                reasons[id].append('changed_or_new_test')
            if matches(id, suite['must_run']) or matches(u['source'], suite['must_run']):
                reasons[id].append('must_run_rule')
            if any(matches(p, suite['description_inputs']) for p in changed):
                reasons[id].append('description_setup_changed')
            if not catalog.fresh(root, u, description_records[id]):
                reasons[id].append('missing_stale_or_unreviewed_description')
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
        if not fallbacks:
            for u in native['units']:
                if not set(reasons[u['id']]) - {'positive_code_graph_match'}:
                    profiles.append({'id': u['id'], 'source': u['source'], 'description': description_records[u['id']]['description'],
                                     'graph_evidence': {'change_paths': graph_evidence['paths'].get(u['source'], []),
                                                        'test_dependencies': graph_evidence['dependencies'].get(u['source'], [])}})
        results.append({'key': native['key'], 'suite': native['suite'], 'variant': native['variant'],
                        'configured_mode': suite['mode'], 'execution': 'full',
                        'kind': suite['kind'], 'native_complete': native['native_complete'],
                        'prerequisites': suite['prerequisites'], 'threshold': suite['irrelevant_threshold'],
                        'reasons': reasons, 'fallbacks': sorted(set(fallbacks)), 'units': native['units']})
    return results, profiles, evidence, unknown


def select(store, base, head='HEAD', *, identifier=None, output=None, dry_run=False, evaluator=None,
           base_graph=None, head_graph=None, build_graphs=True, native=False):
    started = time.monotonic()
    store.initialize()
    config = load_config(store.root)
    context = change(store.root, base, head, identifier)
    inventory = catalog.source_inventory(store.root, config, native=native)
    snapshot = workspace(store.root)
    descriptions = records(store.root, inventory)
    graph_started = time.monotonic()
    graph_builds = []
    if build_graphs and not dry_run:
        for side, provided in [('base', base_graph), ('head', head_graph)]:
            if provided:
                continue
            try:
                reuse = (base_graph or graph.artifact_path(store, config, context['base'])) if side == 'head' else None
                if reuse and not Path(reuse).exists():
                    reuse = None
                built = graph.build(store, config, context[side], reuse=reuse)
                graph_builds.append({'snapshot': side, 'cache_hit': built['cache_hit'], 'path': built['path']})
            except (FaultlineError, OSError) as exc:
                graph_builds.append({'snapshot': side, 'error': str(exc)})
    graph_evidence = graph.evidence(store, config, context, inventory, base_graph, head_graph)
    graph_seconds = time.monotonic() - graph_started
    suites, profiles, evidence, unknown = decisions(store.root, config, inventory, context, descriptions, snapshot, graph_evidence)
    evaluator = evaluator or BatchedJev(store, config['evaluator'], deadline=time.monotonic() + config['evaluator']['selection_seconds'])
    inference_started = time.monotonic()
    result = evaluator.evaluate(context, profiles, dry_run=dry_run)
    inference_seconds = time.monotonic() - inference_started
    if dry_run:
        return {'dry_run': True, 'change': {k: context[k] for k in ('id', 'base', 'head', 'changed_files')},
                'candidate_units': len(profiles), 'estimate': result, 'unknown_paths': unknown, 'graph': graph_evidence,
                'fallbacks': {s['key']: s['fallbacks'] for s in suites}, 'execution': 'full_shadow'}
    for suite in suites:
        ids = set(suite['reasons'])
        if ids.intersection(result['errors']):
            suite['fallbacks'].append('semantic_evaluation_incomplete')
        selected, omitted = [], []
        for id, reasons in suite['reasons'].items():
            judgment = result['rows'].get(id)
            if suite['fallbacks']:
                reasons.extend(suite['fallbacks'])
            if not reasons and judgment is None:
                reasons.append('missing_semantic_judgment')
            if not reasons and judgment['probabilities']['irrelevant'] >= suite['threshold']:
                reasons.append('irrelevant_probability_meets_proposal_threshold')
                omitted.append(id)
            else:
                if not reasons:
                    reasons.append('semantic_relevance_or_uncertainty')
                selected.append(id)
        suite['proposed_selected'] = sorted(selected)
        suite['proposed_omitted'] = sorted(omitted)
        suite['execution_reasons'] = ['shadow_full_execution', 'runner_validation_required_at_execution']
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
    for suite in suites:
        count = len(suite['proposed_selected'])
        units = suite['units']
        tokens = set(re.findall(r"[a-z][a-z0-9_]+", context['diff'].lower()))
        def lexical(u):
            description = (descriptions[u['id']] or {}).get('description', u['title'])
            return len(tokens & set(re.findall(r"[a-z][a-z0-9_]+", description.lower())))
        suite['baselines'] = {
            'random': [u['id'] for u in sorted(units, key=lambda u: digest([context['base'], context['head'], config['evaluator']['random_seed'], u['id']]))[:count]],
            'path': [u['id'] for u in sorted(units, key=lambda u: (-max((len(set(u['source'].split('/')[:-1]) & set(p.split('/')[:-1])) for p in context['changed_files']), default=0), u['id']))[:count]],
            'lexical': [u['id'] for u in sorted(units, key=lambda u: (-lexical(u), u['id']))[:count]],
            'graph': [u['id'] for u in sorted(units, key=lambda u: (-bool(graph_evidence['paths'].get(u['source'])), u['id']))[:count]],
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
    document = seal({'schema_version': 2, 'kind': 'selection', 'created_at': now(), 'policy': POLICY,
                     'repository': config['repository'], 'change': context, 'workspace': snapshot,
                     'config_hash': config['config_hash'], 'inventory': inventory,
                     'graph': graph_evidence, 'graph_builds': graph_builds,
                     'inventory_hash': inventory_identity(catalog.source_inventory(store.root, config) if native else inventory), 'catalog': descriptions,
                     'catalog_hash': digest(descriptions), 'relationship_evidence': evidence,
                     'evaluator': {'model': config['evaluator']['model'], 'batch_version': BATCH_VERSION},
                     'suites': suites, 'judgments': result['rows'], 'semantic_errors': result['errors'],
                     'usage': {k: result[k] for k in ('batches', 'requests', 'cache_hits', 'uncached_requests', 'usage')},
                     'selection_seconds': time.monotonic() - started, 'graph_seconds': graph_seconds,
                     'inference_seconds': inference_seconds, 'cost': cost, 'unknown_paths': unknown,
                     'complete': True, 'semantic_complete': result['complete'],
                     'limitations': ['Shadow proposals are experimental; all suites execute fully.',
                                     'Static graph paths and Jev relevance are not measured code coverage.',
                                     'Source targets are provisional; executable identities are validated only during execution.',
                                     'CI must authenticate artifact producers; integrity hashes alone do not establish trust. Experimental execution is not enabled.']})
    output = output or store.path / 'selections' / document['integrity'] / 'selection.json'
    save_frozen(output, document)
    return {'path': str(output), 'selection_id': document['integrity'], 'complete': True,
            'semantic_complete': document['semantic_complete'], 'usage': document['usage'],
            'proposed_selected': sum(len(s['proposed_selected']) for s in suites),
            'proposed_omitted': sum(len(s['proposed_omitted']) for s in suites),
            'execution': 'full_shadow', 'targets': 'provisional_source_files',
            'native_validation': 'required_at_execution', 'fallbacks': {s['key']: s['fallbacks'] for s in suites}}
