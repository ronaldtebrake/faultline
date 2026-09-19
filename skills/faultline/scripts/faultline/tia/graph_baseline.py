"""Outcome-blind, natural-size CodeGraph baseline and paired Jev comparison."""

POLICY = 'codegraph-only-v1'
REQUIRED = {'whole_check_requires_full_execution', 'changed_or_new_test', 'must_run_rule',
            'description_setup_changed', 'positive_coverage_or_dependency_match'}


def build(suites, graph, unknown_paths):
    """Use only pre-inference facts; never pad the graph set to a hybrid budget."""
    output = []
    graph_gaps = sorted(set(graph['fallbacks'] + (['change_outside_declared_scope'] if unknown_paths else [])))
    for suite in suites:
        fallbacks = sorted(set(suite['fallbacks'] + graph_gaps))
        targets = []
        for unit in suite['units']:
            reasons = sorted(REQUIRED.intersection(suite['reasons'][unit['id']]))
            matched = bool(graph['paths'].get(unit['source']))
            if reasons or suite['fallbacks']:
                state = 'required'
                reasons += suite['fallbacks']
            elif matched:
                state, reasons = 'graph_match', ['positive_code_graph_match']
            elif graph_gaps or unit['source'] in graph['unmapped_tests']:
                state = 'unknown'
                reasons = graph_gaps or ['test_source_without_usable_structural_graph']
            else:
                state, reasons = 'no_graph_match', ['no_graph_impact_found']
            targets.append({'id': unit['id'], 'source': unit['source'], 'state': state,
                            'graph_match': matched, 'reasons': sorted(set(reasons))})
        output.append({'key': suite['key'], 'suite': suite['suite'], 'targets': targets,
                       'prerequisites': suite['prerequisites'], 'fallbacks': fallbacks,
                       'would_run_full_suite': bool(fallbacks) or suite['kind'] == 'check'})
    # A prerequisite must run even when it has no independent graph path.
    pending = {p for s in output if s['would_run_full_suite'] or any(t['state'] != 'no_graph_match' for t in s['targets'])
               for p in s['prerequisites']}
    visited = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        for suite in output:
            if suite['suite'] != name:
                continue
            suite['would_run_full_suite'] = True
            suite['fallbacks'] = sorted(set(suite['fallbacks'] + ['execution_prerequisite']))
            for target in suite['targets']:
                if target['state'] == 'no_graph_match':
                    target['state'] = 'required'
                target['reasons'] = sorted(set(target['reasons'] + ['execution_prerequisite']))
            pending.update(suite['prerequisites'])
    for suite in output:
        suite['would_run'] = sorted(t['id'] for t in suite['targets'] if t['state'] != 'no_graph_match')
        suite['not_suggested'] = sorted(t['id'] for t in suite['targets'] if t['state'] == 'no_graph_match')
    targets = [t for s in output for t in s['targets']]
    return {'policy': POLICY, 'suites': output,
            'counts': {'known_targets': len(targets), 'would_run': sum(len(s['would_run']) for s in output),
                       'not_suggested': sum(len(s['not_suggested']) for s in output),
                       'positive_graph_matches': sum(t['graph_match'] for t in targets),
                       'required': sum(t['state'] == 'required' for t in targets),
                       'unknown': sum(t['state'] == 'unknown' for t in targets),
                       'suites_requiring_full_run': sum(s['would_run_full_suite'] for s in output)},
            'limitations': ['CodeGraph-only means structural evidence plus the same mandatory rules and prerequisites, without Jev.',
                            'No graph match means not suggested by this baseline, not proven irrelevant.',
                            'Graph gaps keep affected targets would-run; incomplete inventory may require a full suite beyond listed targets.',
                            'The baseline uses its own selection size, not the hybrid policy execution budget.']}


def compare(selection):
    if selection.get('analysis_mode') == 'codegraph_only':
        return {'available': False, 'reason': 'jev_disabled'}
    baseline = selection['graph_baseline']
    graph_run = {id for s in baseline['suites'] for id in s['would_run']}
    hybrid_run = {id for s in selection['suites'] for id in s['proposed_selected']}
    hybrid_omit = {id for s in selection['suites'] for id in s['proposed_omitted']}
    graph_matches = {t['id'] for s in baseline['suites'] for t in s['targets'] if t['graph_match']}
    complete = {id for id, row in selection['judgments'].items()
                if id not in selection['semantic_errors'] and row.get('evidence_complete', True)}
    extra = hybrid_run - graph_run
    groups = {'would_run_both': graph_run & hybrid_run,
              'jev_additions': extra & complete, 'unresolved_additions': extra - complete,
              'jev_removals': (graph_run & hybrid_omit) & complete,
              'not_suggested_by_either': hybrid_omit - graph_run,
              'unresolved': {u['id'] for s in selection['suites'] for u in s['units'] if u.get('kind') != 'check'} - complete,
              'graph_matches_scored_irrelevant': set()}
    for suite in selection['suites']:
        for unit in suite['units']:
            id = unit['id']
            if id not in graph_matches & complete:
                continue
            row = selection['judgments'][id]
            probability = row.get('all_parts_irrelevant_probability', row['probabilities']['irrelevant'])
            if probability is not None and probability >= suite['threshold']:
                groups['graph_matches_scored_irrelevant'].add(id)
    groups = {key: sorted(ids) for key, ids in groups.items()}
    return {'available': True, 'counts': {key: len(ids) for key, ids in groups.items()}, **groups,
            'limitations': ['Selection differences describe proposals, not additional regressions caught or measured savings.',
                            'Unfinished Jev assessments are reported separately from Jev additions.',
                            'The current hybrid policy retains positive graph matches even when Jev scores them irrelevant.']}
