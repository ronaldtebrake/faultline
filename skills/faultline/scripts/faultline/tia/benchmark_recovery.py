"""Recover unresolved benchmark judgments before inspecting CI outcomes."""
import copy
import time
from pathlib import Path

from .. import __version__
from ..core import FaultlineError, now, number
from .batch import BatchedJev, identity
from .benchmark import prerequisites
from .benchmark_windows import RecoveryPlan
from .common import checked, save_frozen, seal
from .config import DEFAULT_EVALUATOR
from . import context as context_sources

VERSION = 'reference-source-recovery-v1'


def reroute(document, arm, rows, errors):
    old = document['policies'][arm]
    selected = set(old.get('required', []))
    full = set(old.get('full_suites', []))
    unresolved = set(errors)
    configs = {s['id']: s for s in document['config']['suites']}
    suites = []
    for s in document['inventory']['suites']:
        ids = {u['id'] for u in s['units']}
        threshold = configs[s['suite']]['irrelevant_threshold']
        if s['key'] in full:
            selected.update(ids)
        for id in ids:
            row = rows.get(id)
            if row is None or id in errors or not row.get('evidence_complete', True):
                unresolved.add(id)
                selected.add(id)
            elif row.get('all_parts_irrelevant_probability', row['probabilities']['irrelevant']) < threshold:
                selected.add(id)
        suites.append({'key': s['key'], 'suite': s['suite'], 'reasons': {id: [] for id in ids},
                       'fallbacks': ['frozen_full_suite'] if s['key'] in full else [],
                       'prerequisites': configs[s['suite']]['prerequisites']})
    selected, extra = prerequisites(suites, selected)
    required = set(old.get('required', [])) | {id for s in suites if s['suite'] in extra or s['key'] in full for id in s['reasons']}
    all_ids = {u['id'] for s in document['inventory']['suites'] for u in s['units']}
    result = {**old, 'judgments': rows, 'errors': errors, 'would_run': sorted(selected), 'would_omit': sorted(all_ids - selected),
              'required': sorted(required), 'unresolved': sorted(unresolved), 'complete': not unresolved,
              'full_suites': sorted(full | {s['key'] for s in suites if s['suite'] in extra}),
              'retained': sorted(selected - required - unresolved),
              'ranking': sorted(all_ids, key=lambda id: (-rows.get(id, {}).get('score', 4), id)),
              'decision_groups': {'required': sorted(required), 'unresolved': sorted(unresolved - required),
                                  'retained': sorted(selected - required - unresolved), 'omit': sorted(all_ids - selected)}}
    result.pop('recommended', None)
    return result


def recover(store, path, *, prepare=False, max_requests=None, selection_seconds=None, output=None, evaluator=None):
    started = time.monotonic()
    original = checked(Path(path), 'benchmark')
    if original['contract'].removesuffix('+context-v1') not in ('reference-source-v1', 'reference-adaptive-source-v1', VERSION):
        raise FaultlineError('Recovery requires a source benchmark or an earlier source recovery')
    if set(original['policies']) != {'jev'}:
        raise FaultlineError('This snapshot uses a retired comparison contract; create a new Jev-only benchmark')
    settings = {**DEFAULT_EVALUATOR, **original['evaluator']['settings']}
    if max_requests is not None:
        settings['jev_requests'] = number(max_requests, 'max_requests', allow_zero=True)
    if selection_seconds is not None:
        settings['selection_seconds'] = number(selection_seconds, 'selection_seconds')
    targets = {arm: set(original['policies'][arm]['unresolved']) | set(original['policies'][arm].get('errors', {})) for arm in ('jev',)}
    available = {p['id'] for p in original['inputs']}
    absent = {a: ids - available for a, ids in targets.items()}
    bundle = original.get('context_bundle')
    if bundle:
        context_sources.validate(bundle, original['change'], original['repository'])
    assessment = context_sources.assessment_context(original['change'], bundle)
    boundary_basis = 'Complete-line boundaries from exact frozen source and context'
    plan = RecoveryPlan(assessment, original['inputs'], {a: available for a in targets}, settings)
    plan.restrict_targets({a: ids & available for a, ids in targets.items()})
    engine = evaluator or BatchedJev(store, settings, deadline=time.monotonic() + settings['selection_seconds'])
    counts = {a: {'rows': {}, 'errors': {id: 'Frozen source evidence unavailable' for id in absent[a]},
                  'usage': [], 'requests': 0, 'cache_hits': 0, 'remaining_requests': 0,
                  'validation_retries': 0, 'invalid_answers': []} for a in targets}
    estimates, manifests = {a: 0 for a in targets}, []
    submitted = 0
    # Every attempt shares the same finite budget.
    groups = {a: [g[a] for g in plan.groups if a in g] for a in targets}
    for i in range(max(map(len, groups.values()), default=0)):
        for arm in (('jev',) if i % 2 == 0 else ('jev',)):
            if i >= len(groups[arm]):
                continue
            request = groups[arm][i]
            engine.config = {**settings, 'max_evidence_pairs': max(0, settings['max_evidence_pairs'] - submitted)}
            result = engine.evaluate(assessment, [], dry_run=prepare, prepared=([request], []))
            estimates[arm] += result['uncached_requests']
            target = counts[arm]
            target['rows'].update(result['rows'])
            target['errors'].update(result['errors'])
            target['usage'].extend(result['usage'])
            target['invalid_answers'].extend(result.get('invalid_answers', []))
            for key in ('requests', 'cache_hits', 'remaining_requests', 'validation_retries'):
                target[key] += result.get(key, 0)
            if not prepare:
                submitted += result['requests'] * len(request['questions'])
                if result.get('halted'):
                    engine.budget.limit = engine.budget.used
            manifests.extend({'arm': arm, **entry} for entry in result.get('request_manifest', [{'request_key': identity(request), 'targets': [p['id'] for p in request['state']['tests']]}]))
    preparation = {**plan.summary, 'context': context_sources.summary(bundle), 'uncached_requests': estimates, 'shared_request_ceiling': settings['jev_requests'],
                   'recovery_retry_limit': settings['invalid_response_retries'], 'boundary_basis': boundary_basis,
                   'source_unavailable': {a: sorted(v) for a, v in absent.items()},
                   'assumption': 'Counts exclude bounded retries; all HTTP attempts share the request/time/judgment ceilings.'}
    if prepare:
        return {'complete': not (bundle and bundle['gaps']) and not any(plan.rejected.values()) and not any(absent.values()) and sum(estimates.values()) <= settings['jev_requests'],
                'preparation': preparation, 'parent_benchmark': original['integrity'], 'execution': 'none', 'dry_run': True}
    totals = plan.aggregate(counts)
    document = copy.deepcopy(original)
    document.pop('integrity', None)
    document.update(contract=VERSION + ('+context-v1' if bundle else ''), engine_version=__version__, created_at=now())
    for arm, total in totals.items():
        rows = {**original['policies'][arm]['judgments'], **total['rows']}
        errors = {**original['policies'][arm].get('errors', {}), **total['errors']}
        for id, row in total['rows'].items():
            if row.get('evidence_complete', True) and id not in total['errors']:
                errors.pop(id, None)
        document['policies'][arm] = reroute(document, arm, rows, errors)
        document['policies'][arm].update({k: counts[arm][k] for k in ('requests', 'usage', 'cache_hits', 'remaining_requests', 'validation_retries', 'invalid_answers')})
    document['recovery'] = {'parent_benchmark': original['integrity'], 'parent_path': str(Path(path).resolve()),
                            'prior_usage': original['usage'], 'prior_policy_usage': {a: {k:original['policies'][a][k] for k in ('requests','usage','cache_hits')} for a in targets},
                            'targets': {a: sorted(v) for a, v in targets.items()},
                            'remaining': {a: len(document['policies'][a]['unresolved']) for a in targets}, 'preparation': preparation,
                            'windowed_targets': {a: sorted(id for id, r in document['policies'][a]['judgments'].items() if r.get('score_scope') == 'source-window-recovery-v1') for a in targets}}
    previous_usage = original.get('recovery', {}).get('cumulative_policy_usage', original['policies'])
    document['recovery']['cumulative_policy_usage'] = {
        a: {'requests': previous_usage[a]['requests'] + counts[a]['requests'],
            'usage': previous_usage[a]['usage'] + counts[a]['usage'],
            'cache_hits': previous_usage[a].get('cache_hits', 0) + counts[a]['cache_hits']}
        for a in targets}
    document['recovery']['parent_contract'] = original['contract']
    document['preparation'] = {**original['preparation'], 'packet_plan': preparation,
                               'blockers': ([] if original['inventory']['complete'] else ['Configured inventory contains incomplete or empty suites']) + (['Context collection declared missing evidence; full-suite fallback'] if bundle and bundle['gaps'] else []),
                               'planned_requests': sum(estimates.values()), 'evidence_mode': 'recovery'}
    document['request_manifest'] = manifests
    document['evaluator']['settings'] = settings
    document['evaluator']['packing'] = document['contract']
    document['selection_seconds'] = time.monotonic() - started
    document['inference_seconds'] = document['selection_seconds']
    document['complete'] = not (bundle and bundle['gaps']) and original['inventory']['complete'] and all(p['complete'] for p in document['policies'].values())
    usage = [u for a in targets for u in counts[a]['usage']]
    requests = sum(counts[a]['requests'] for a in targets)
    tokens = sum(u['input_tokens'] for u in usage) if len(usage)==requests and all(u is not None for u in usage) else None
    document['usage'] = {'requests': requests, 'input_tokens': tokens, 'request_ceiling': settings['jev_requests'],
                          'input_usd_estimate': tokens * settings['pricing']['input_usd_per_million']/1000000 if tokens is not None and settings['pricing'] else None,
                          'pricing': settings['pricing']}
    document['limitations'] = [text for text in original['limitations'] if not text.startswith(('Jev receives', 'Whole inputs are used', 'Recovery preserves', 'Windowed recovery'))] + [
        'Recovery preserves accepted parent judgments and re-assesses unresolved inputs. Earlier inference costs are retained separately under recovery.prior_usage.',
        'Windowed recovery covers every source/change range. Cross-window interactions and external setup bodies are not assessed. Maximum part relevance is a routing statistic, not a calibrated whole-change probability.']
    document = seal(document)
    destination = Path(output) if output else store.path / 'benchmarks' / (document['integrity'] + '.json')
    save_frozen(destination, document)
    from .benchmark_report import render
    return {**render(destination, document), 'recovery': document['recovery']}
