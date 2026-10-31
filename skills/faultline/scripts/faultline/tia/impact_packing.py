"""Lossless batching: verify every test/change association after packing."""
import collections
import copy
import json

from ..core import FaultlineError, digest

MAX_PAIR_BYTES = 96000
MAX_REQUEST_BYTES = 170000
MAX_QUESTIONS = 50


def size(value):
    return len(json.dumps(value, ensure_ascii=False).encode())


def payload(model, state, questions):
    return {'model': model, 'state': state,
            'questions': {f'q{i}': question for i, question in enumerate(questions)}}


def pack(model, state, questions):
    bins = []
    for question in sorted(questions, key=lambda q: (-size(q), digest(q))):
        if size(state) + size(question) > MAX_PAIR_BYTES:
            raise FaultlineError('Packed evidence exceeds the state/question limit')
        options = []
        for i, batch in enumerate(bins):
            length = size(payload(model, state, batch + [question]))
            if len(batch) < MAX_QUESTIONS and length <= MAX_REQUEST_BYTES:
                options.append((MAX_REQUEST_BYTES - length, i))
        if options:
            bins[min(options)[1]].append(question)
        else:
            bins.append([question])
    requests = [payload(model, state, batch) for batch in bins]
    if any(size(r) > MAX_REQUEST_BYTES for r in requests):
        raise FaultlineError('Packed request exceeds the byte limit')
    return requests


def pairs(requests):
    """Canonical evidence multiset, reversing the shared-test representation."""
    result = collections.Counter()
    for request in requests:
        for question in request['questions'].values():
            if 'test' in request['state']:
                instructions = question['instructions']
                test = copy.deepcopy(request['state']['test'])
                test['id'] = instructions['test_identity']['id']
                if 'change_range' in instructions['test_identity']:
                    test['source_evidence']['change_range'] = instructions['test_identity']['change_range']
                restored = {**question, 'instructions': {k: v for k, v in instructions.items()
                            if k not in ('change', 'test_identity', 'bindings')}}
                restored['instructions']['test'] = test
                state = {'change': instructions['change']}
            else:
                restored, state = question, request['state']
            result[(request['model'], digest(state), digest(restored))] += 1
    return result


def mixed(requests):
    if not requests:
        return []
    if len({r['model'] for r in requests}) != 1:
        raise FaultlineError('Cannot batch different model contracts')
    model = requests[0]['model']
    groups = {}
    for request in requests:
        for question in request['questions'].values():
            test = copy.deepcopy(question['instructions']['test'])
            identity = {'id': test.pop('id')}
            if 'change_range' in test['source_evidence']:
                identity['change_range'] = test['source_evidence'].pop('change_range')
            reversed_question = {**question, 'instructions': {k: v for k, v in question['instructions'].items() if k != 'test'}}
            reversed_question['instructions'].update(change=request['state']['change'], test_identity=identity,
                                                     bindings={'test': 'state.test', 'change': 'instructions.change'})
            group = groups.setdefault(digest(test), {'test': test, 'pairs': [], 'cost': 0})
            group['pairs'].append((request, question, reversed_question))
            group['cost'] += size(request['state']) / len(request['questions']) + size(question) + 60 / len(request['questions'])
    reverse, chosen = [], set()
    for key, group in groups.items():
        try:
            packed = pack(model, {'test': group['test']}, [item[2] for item in group['pairs']])
        except FaultlineError:
            # Binding metadata may make reversal larger; retain the original form.
            continue
        if len(group['pairs']) > 1 and sum(map(size, packed)) < .95 * group['cost']:
            reverse.extend(packed)
            chosen.add(key)
    remaining = {}
    for key, group in groups.items():
        if key not in chosen:
            for request, question, _ in group['pairs']:
                remaining.setdefault(digest(request['state']), {'state': request['state'], 'questions': []})['questions'].append(question)
    result = reverse + [request for group in remaining.values() for request in pack(model, group['state'], group['questions'])]
    if pairs(result) != pairs(requests):
        raise FaultlineError('Batching changed evidence associations; no requests may be sent')
    return result
