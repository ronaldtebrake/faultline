"""Pack whole targets first; subdivide only evidence that cannot fit a request."""
import hashlib
import json

from ..core import digest
from .batch import fits, payload


def segment(raw, start=0, end=None, checksum=None):
    end = len(raw) if end is None else end
    return {'text': raw[start:end].decode('utf-8'), 'start_byte': start, 'end_byte': end,
            'total_bytes': len(raw), 'sha256': checksum or hashlib.sha256(raw).hexdigest()}


def split(part):
    raw = part['text'].encode()
    middle = len(raw) // 2
    while middle and raw[middle] & 0xc0 == 0x80:
        middle -= 1
    if not middle:
        return None
    return ({**part, 'text': raw[:middle].decode(), 'end_byte': part['start_byte'] + middle},
            {**part, 'text': raw[middle:].decode(), 'start_byte': part['start_byte'] + middle})


class SourcePlan:
    def __init__(self, context, profiles, config):
        self.context, self.config = context, config
        self.diff = segment(context['diff'].encode())
        self.groups, self.diff_ranges = {}, set()
        for profile in profiles:
            key = digest({k: v for k, v in profile.items() if k != 'id'})
            group = self.groups.setdefault(key, {'profile': profile, 'aliases': [], 'pairs': [], 'error': None})
            group['aliases'].append(profile['id'])

    def item(self, key, profile, diff, source):
        context = {**self.context, 'diff': diff['text'], 'diff_evidence': {k: v for k, v in diff.items() if k != 'text'}}
        if len(json.dumps(context.get('changed_files', [])).encode()) > self.config['max_state_bytes'] // 8:
            context['changed_files'] = {'count': len(self.context['changed_files']),
                                        'sha256': digest(self.context['changed_files']), 'details': 'see diff fragments'}
        graph = profile['graph_evidence']
        if len(json.dumps(graph).encode()) > self.config['max_state_bytes'] // 8:
            graph = {'structural_match': graph.get('structural_match', False), 'details_omitted': 'graph_context_byte_budget'}
        id = f"{key}:d{diff['start_byte']}-{diff['end_byte']}:t{source['start_byte']}-{source['end_byte']}"
        test = {'id': id, 'source': profile['source'], 'description': profile['description'],
                'source_evidence': source, 'execution_context': profile['execution_context'], 'graph_evidence': graph}
        return context, test

    def pairs(self, key, group):
        profile = group['profile']
        pending = [(self.diff, segment(profile['source_text'].encode()))]
        # Per-target planning guard is independent of the per-run HTTP ceiling.
        # Oversized targets are visible and cannot be proposed for omission.
        leaves, blocked = [], None
        while pending:
            diff, source = pending.pop()
            context, test = self.item(key, profile, diff, source)
            if fits(payload(context, [test], self.config), self.config):
                leaves.append((context, test))
                if len(leaves) + len(pending) > 10000:
                    blocked = 'Target needs more than 10000 evidence judgments; increase payload capacity or reduce its source scope'
                    break
                continue
            source_larger = len(source['text'].encode()) >= len(diff['text'].encode())
            pieces = split(source if source_larger else diff)
            if pieces is None:
                blocked = 'Request metadata exceeds payload limits; target cannot be scored with this configuration'
                break
            if source_larger:
                pending.extend([(diff, pieces[1]), (diff, pieces[0])])
            else:
                pending.extend([(pieces[1], source), (pieces[0], source)])
        if blocked:
            group['error'] = blocked
            return
        for context, test in leaves:
            group['pairs'].append(test['id'])
            meta = context['diff_evidence']
            self.diff_ranges.add((meta['start_byte'], meta['end_byte']))
            yield context, test

    def requests(self):
        def order(item):
            key, group = item
            p = group['profile']
            return (p['source'] not in self.context.get('changed_files', []),
                    not p['graph_evidence'].get('structural_match', False), len(p['source_text'].encode()), p['source'], key)
        def pack(cohort):
            # Finish a bounded cohort across ALL its change windows. Sharing each
            # window avoids repeating the diff once per test; limiting cohort size
            # avoids scattering a small request budget over the entire repository.
            windows = {}
            for key, group in cohort:
                for context, test in self.pairs(key, group):
                    window = windows.setdefault(digest(context), (context, []))
                    window[1].append(test)
            for context, tests in windows.values():
                current = []
                for test in tests:
                    if current and (not fits(payload(context, current + [test], self.config), self.config)
                                    or len(current) >= self.config.get('max_evidence_pairs', 10000)):
                        yield payload(context, current, self.config)
                        current = []
                    current.append(test)
                if current:
                    yield payload(context, current, self.config)
        cohort, size = [], 0
        source_budget = max(1, self.config['max_state_bytes'] - min(len(self.context['diff'].encode()), self.config['max_state_bytes'] // 2) - 2000)
        for key, group in sorted(self.groups.items(), key=order):
            cost = len(group['profile']['source_text'].encode()) + 500
            if cohort and (size + cost > source_budget or len(cohort) >= self.config['max_batch_units']):
                yield from pack(cohort)
                cohort, size = [], 0
            cohort.append((key, group))
            size += cost
        if cohort:
            yield from pack(cohort)
