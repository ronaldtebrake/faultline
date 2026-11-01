"""Cross-checkout cache reuse and authenticated baseline rejection paths."""
import copy
import hashlib
import io
import json
import shutil
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from faultline.core import FaultlineError, Store, write_json
from faultline.tia.common import checked, seal
from faultline.tia.dependency_graph import build
from faultline.tia.dependency_runtime import import_records
from faultline.tia.dependency_shared import pack, restore, correspondence
from faultline.tia.dependency_shared_github import fetch, unpack, ARTIFACT
import test_dependency_graph as fixtures


class SharedBaselineTests(unittest.TestCase):
    setUp = fixtures.DependencyGraphTests.setUp
    git = fixtures.DependencyGraphTests.git
    write = fixtures.DependencyGraphTests.write
    commit = fixtures.DependencyGraphTests.commit
    runtime = fixtures.DependencyGraphTests.runtime

    def baseline(self):
        self.git('remote', 'add', 'origin', 'https://github.com/example/project.git')
        context, path, _ = self.runtime('playwright', 'e2e/profile.spec.ts', ['e2e/pages/checkout.ts'])
        evidence = import_records(self.store, context, [path])
        meta = {'repository': 'example/project', 'repository_id': 1, 'workflow': 'qa.yml', 'run_id': 7,
                'run_attempt': 1, 'event': 'push', 'branch': 'main', 'revision': self.base,
                'collections': [{'job_key': 'browser-1-1', 'runtime': checked(evidence['path'])['integrity']}]}
        output = self.root / '.faultline' / 'baseline.json'
        pack(self.store, output, producer_data=meta, runtime_paths=[Path(evidence['path'])])
        return output

    def test_portable_cache_reuses_unchanged_blobs_and_invalidates_changed_dependencies(self):
        baseline = self.baseline()
        before = checked(baseline)
        # A clean clone has no local parser or snapshot cache.
        destination = self.root / '.faultline' / 'clone'
        self.git('clone', '-q', '--no-hardlinks', str(self.root), str(destination))
        store = Store(destination)
        restored = restore(store, baseline)
        warm = build(store, runtime_paths=restored['runtime_paths'])
        self.assertEqual(0, warm['parsed'])
        self.assertGreater(warm['reused'], 0)
        self.assertEqual(1, warm['graph']['runtime_reuse']['observed'])
        self.assertFalse(restored['omission_authorized'])
        # Edit just one source in the original, then clone the descendant.
        self.write('src/price.ts', 'export const price = () => 17;')
        self.commit()
        next_root = self.root / '.faultline' / 'next'
        self.git('clone', '-q', '--no-hardlinks', str(self.root), str(next_root))
        next_store = Store(next_root)
        reused = restore(next_store, baseline)
        result = build(next_store, runtime_paths=reused['runtime_paths'])
        self.assertEqual(1, result['parsed'])
        self.assertEqual(0, result['graph']['runtime_reuse']['carried'])
        self.assertIn('src/price.ts', result['graph']['runtime_reuse']['invalidated'][0]['changed_inputs'])
        self.assertEqual(before, checked(baseline))

    def test_corrupt_incompatible_foreign_and_nonancestor_baselines_write_no_cache(self):
        baseline = self.baseline()
        value = checked(baseline)
        shutil.rmtree(self.store.path / 'dependency-graph')
        mutations = [lambda v: v.update(engine='old-engine'), lambda v: v.update(repository='another'),
                     lambda v: v.update(config='another'), lambda v: v.update(version=99),
                     lambda v: v['sources'].update({'../outside': next(iter(v['sources'].values()))}),
                     lambda v: v['producer'].update(run_attempt=0),
                     lambda v: v['producer']['collections'].clear(),
                     lambda v: v.update(revision='f' * 40)]
        for change in mutations:
            altered = copy.deepcopy(value)
            change(altered)
            write_json(baseline, seal(altered))
            with self.assertRaises(FaultlineError):
                restore(self.store, baseline)
            self.assertFalse((self.store.path / 'dependency-graph').exists())
        write_json(baseline, {**value, 'integrity': 'bad'})
        with self.assertRaises(FaultlineError):
            restore(self.store, baseline)
        write_json(baseline, value)
        self.git('checkout', '-q', '--orphan', 'unrelated')
        self.write('unrelated.txt', 'different history')
        self.commit()
        with self.assertRaises(FaultlineError):
            restore(self.store, baseline)

    def remote(self, baseline):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('baseline.json', baseline.read_bytes())
        raw = buf.getvalue()
        artifact = {'id': 9, 'name': ARTIFACT, 'expired': False, 'expires_at': '2099-01-01T00:00:00Z',
                    'created_at': '2026-01-01T00:00:00Z',
                    'size_in_bytes': len(raw), 'digest': 'sha256:' + hashlib.sha256(raw).hexdigest(),
                    'workflow_run': {'id': 7, 'repository_id': 1, 'head_repository_id': 1, 'head_sha': self.base}}
        repo = {'id': 1, 'full_name': 'example/project', 'default_branch': 'main'}
        run = {'id': 7, 'workflow_id': 3, 'path': '.github/workflows/qa.yml', 'event': 'push',
               'head_branch': 'main', 'status': 'completed', 'conclusion': 'success', 'repository': repo,
               'head_repository': repo, 'head_sha': self.base, 'run_attempt': 1}
        responses = {'repos/example/project': repo,
                     'repos/example/project/actions/workflows/qa.yml': {'id': 3, 'path': '.github/workflows/qa.yml', 'state': 'active'},
                     'repos/example/project/actions/artifacts?name=' + ARTIFACT + '&per_page=30': {'artifacts': [artifact]},
                     'repos/example/project/actions/runs/7': run, 'repos/example/project/actions/artifacts/9/zip': raw}
        class API:
            def request(self, endpoint, **kwargs):
                return responses[endpoint]
        api = API()
        api.responses = responses
        return api, artifact, run

    def test_newest_valid_artifact_wins_when_listing_and_ids_are_out_of_order(self):
        baseline = self.baseline()
        api, old, _ = self.remote(baseline)
        # Creation time, not a larger ID or position in the page, defines recency.
        newer = {**old, 'id': 2, 'created_at': '2026-01-02T00:00:00Z'}
        listing = api.responses['repos/example/project/actions/artifacts?name=' + ARTIFACT + '&per_page=30']
        listing['artifacts'] = [{**old, 'created_at': 'invalid'}, old, newer]
        api.responses['repos/example/project/actions/artifacts/2/zip'] = api.responses['repos/example/project/actions/artifacts/9/zip']
        args = {'repository': 'example/project', 'workflow': 'qa.yml', 'branch': 'main', 'api': api}
        result = fetch(self.store, self.store.path / 'download.json', **args)
        self.assertTrue(result['restored'])
        self.assertEqual(2, result['artifact_id'])
        # A newer corrupt artifact still falls back to compatible older evidence.
        newer['digest'] = 'sha256:corrupt'
        result = fetch(self.store, self.store.path / 'download.json', **args)
        self.assertTrue(result['restored'])
        self.assertEqual(9, result['artifact_id'])
        self.assertEqual(1, result['rejected_candidates'])

    def test_github_trust_rejects_forks_other_workflows_pr_runs_wrong_attempts_and_expired_artifacts(self):
        baseline = self.baseline()
        api, artifact, run = self.remote(baseline)
        kwargs = {'repository': 'example/project', 'workflow': 'qa.yml', 'branch': 'main', 'api': api}
        target = self.store.path / 'download.json'
        self.assertTrue(fetch(self.store, target, **kwargs)['restored'])
        for obj, field, invalid in [(artifact, 'expired', True), (artifact, 'digest', 'sha256:bad'),
                                    (run, 'workflow_id', 4), (run, 'event', 'pull_request'),
                                    (run, 'head_repository', {'id': 2}), (run, 'head_branch', 'untrusted'),
                                    (run, 'run_attempt', 2), (run, 'status', 'in_progress')]:
            previous = obj[field]
            obj[field] = invalid
            result = fetch(self.store, target, **kwargs)
            self.assertFalse(result['restored'], field)
            self.assertFalse(result['omission_authorized'])
            obj[field] = previous

    def test_bounded_zip_and_json_reject_extra_members_duplicates_and_oversized_data(self):
        baseline = self.baseline()
        value = checked(baseline)
        with patch('faultline.tia.dependency_shared.MAX_BYTES', 10):
            with self.assertRaises(FaultlineError):
                restore(self.store, baseline)
        baseline.write_text('{"version":1,"version":1}')
        with self.assertRaises(FaultlineError):
            restore(self.store, baseline)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as archive:
            archive.writestr('../baseline.json', json.dumps(value))
        raw = buf.getvalue()
        with self.assertRaises(FaultlineError):
            unpack(raw, {'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()})

    def test_missing_fresh_observation_is_unknown_and_not_a_match(self):
        self.baseline()
        paths = list((self.store.path / 'dependency-graph/runtime').glob('*.json'))
        old = build(self.store, runtime_paths=paths)['graph']
        fresh = build(self.store)['graph']
        result = correspondence(old, fresh)
        self.assertEqual(1, result['missing_fresh_observations'])
        self.assertEqual(0, result['matching_observations'])
        self.assertFalse(result['coverage_complete'])


if __name__ == '__main__':
    unittest.main()
