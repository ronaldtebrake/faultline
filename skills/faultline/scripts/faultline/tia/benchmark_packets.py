"""Explicit bounded comparisons: whole test files against whole diff sections.

No source bytes are sliced to force a fit. This contract measures section-level
relevance and does not claim a calibrated probability for the cumulative change.
"""
import re
import json

from ..core import digest
from .batch import fits


class FilePairPlan:
    def __init__(self, context, profiles, config):
        from .benchmark import ARMS, reference_request
        self.context, self.config = context, config
        self.groups, self.pairs = [], {p['id']: [] for p in profiles}
        self.rejected = {arm: {} for arm in ARMS}
        text = context['diff']
        starts = [m.start() for m in re.finditer(r'^diff --git ', text, re.M)]
        if not starts or starts[0] != 0:
            starts.insert(0, 0)
        self.sections = list(zip(starts, starts[1:] + [len(text)]))
        self.diff_hash = digest(text)
        self.request = reference_request
        self.windows = set()
        cohort = []
        # Finish small, readable targets across all sections before the next
        # cohort, so a finite budget can produce complete target judgments.
        for profile in sorted(profiles, key=lambda p: (len(p['source_text'].encode()), p['id'])):
            allowed = tuple(arm for arm in ARMS if all(self.fits([profile], start, end, (arm,)) for start, end in self.sections))
            for arm in set(ARMS) - set(allowed):
                self.rejected[arm][profile['id']] = 'A whole test, graph context, or complete changed-file section exceeds payload limits; no source was truncated'
            if len(allowed) < len(ARMS):
                if cohort:
                    self.pack(cohort, ARMS)
                    cohort = []
                if allowed:
                    self.pack([profile], allowed)
                continue
            if cohort and not all(self.fits(cohort + [profile], start, end, ARMS) for start, end in self.sections):
                self.pack(cohort, ARMS)
                cohort = []
            cohort.append(profile)
        if cohort:
            self.pack(cohort, ARMS)
        self.summary = {'changed_file_sections': len(self.sections), 'change_windows': len(self.windows),
                        'target_window_pairs': sum(len(pairs) for pairs in self.pairs.values()),
                        'aggregation': 'Maximum observed relevance score; omission requires P(irrelevant) to meet the configured threshold for every planned window.',
                        'setup_evidence': 'Identities only; implementation bodies are not supplied.',
                        'limitation': 'Interactions between separate windows and unprovided setup implementations are not assessed.'}

    def items(self, profiles, start, end):
        whole = self.context['diff']
        context = {**self.context, 'diff': whole[start:end],
                   'diff_evidence': {'whole_diff_hash': self.diff_hash, 'start_char': start, 'end_char': end,
                                     'total_chars': len(whole), 'is_whole': start == 0 and end == len(whole),
                                     'boundary': 'complete_changed_file_sections'}}
        tests = [{**p, 'id': p['id'] + f'#change:{start}:{end}'} for p in profiles]
        return context, tests

    def fits(self, profiles, start, end, arms):
        context, tests = self.items(profiles, start, end)
        for arm in arms:
            request = self.request(context, tests, self.config, arm)
            state_bytes = len(json.dumps(request['state'], ensure_ascii=False).encode())
            question_bytes = max(len(json.dumps(q, ensure_ascii=False).encode()) for q in request['questions'].values())
            # Conservative byte ceilings are local guards, not a tokenizer.
            # Bound shared state plus its largest question as well as total wire size.
            if not fits(request, self.config) or state_bytes + question_bytes > self.config['max_state_bytes']:
                return False
        return True

    def pack(self, profiles, arms):
        start, end = self.sections[0]
        for next_start, next_end in self.sections[1:]:
            if self.fits(profiles, start, next_end, arms):
                end = next_end
            else:
                self.emit(profiles, start, end, arms)
                start, end = next_start, next_end
        self.emit(profiles, start, end, arms)

    def emit(self, profiles, start, end, arms):
        context, tests = self.items(profiles, start, end)
        self.groups.append({arm: self.request(context, tests, self.config, arm) for arm in arms})
        self.windows.add((start, end))
        for p, test in zip(profiles, tests):
            self.pairs[p['id']].append({'id': test['id'], 'start_char': start, 'end_char': end, 'arms': arms})

    def aggregate(self, totals, *, preparing=False):
        result = {}
        for arm, total in totals.items():
            rows, errors = {}, {id: error for id, error in total['errors'].items() if id in self.pairs}
            for id, pairs in self.pairs.items():
                needed = [p for p in pairs if arm in p['arms']]
                found = [{**total['rows'][p['id']], 'change_window': {k: p[k] for k in ('start_char', 'end_char')}}
                         for p in needed if p['id'] in total['rows']]
                failures = sorted({total['errors'][p['id']] for p in needed if p['id'] in total['errors']})
                complete = bool(needed) and len(found) == len(needed) and id not in errors and not failures
                if found:
                    rows[id] = {**max(found, key=lambda row: row['score']), 'parts': found,
                                'evidence_complete': complete, 'evaluated_parts': len(found), 'expected_parts': len(needed),
                                'all_parts_irrelevant_probability': min(r['probabilities']['irrelevant'] for r in found) if complete else None,
                                'score_scope': 'maximum_observed_changed_file_window_relevance'}
                if not complete and id not in errors and (not preparing or failures):
                    errors[id] = '; '.join(failures) or 'Changed-file assessments remain incomplete'
            # Source-read errors may refer to targets with no profile/packet plan.
            errors.update({id: error for id, error in total['errors'].items() if '#change:' not in id})
            result[arm] = {**total, 'rows': rows, 'errors': errors}
        return result
