"""Fresh/recovery accounting and installed-skill behavior, with no live API calls."""
import builtins
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from faultline.core import FaultlineError, write_json
from faultline.tia.common import checked
from faultline.tia.evidence import GitSources
from faultline.tia.progress import Progress, RunBudget, run_lock
from faultline.tia.workflow import assess, saved_report, setup
import test_source_pipeline as fixtures
from test_source_pipeline import answer


class WorkflowTests(unittest.TestCase):
    setUp = fixtures.SourcePipelineTests.setUp
    git = fixtures.SourcePipelineTests.git
    commit = fixtures.SourcePipelineTests.commit

    def transport(self, engine):
        outer = self
        class HTTP:
            def request(self, url, payload, **kwargs):
                engine.budget.take()
                outer.calls.append(payload)
                return {'model': payload['model'], 'answers': {q: answer() for q in payload['questions']},
                        'usage': {'input_tokens': 123, 'output_tokens': 7}}, {}
        return HTTP()

    def run_assessment(self, **kwargs):
        self.calls = []
        return assess(self.store, transport_factory=self.transport, **kwargs)

    def test_fresh_default_resumed_run_and_offline_report(self):
        first = self.run_assessment(base=self.base)
        self.assertEqual(1, len(self.calls))
        second = self.run_assessment(base=self.base)
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertEqual(1, len(self.calls))
        again = self.run_assessment(resume=first['run_id'])
        self.assertEqual([], self.calls)
        self.assertEqual(1, again['usage']['requests'])
        self.assertEqual(123, again['usage']['input_tokens'])
        self.assertEqual(2, again['assessment']['resumed_answers'])
        self.assertEqual(0, again['assessment']['reused_answers'])
        self.assertFalse((self.store.path / 'jev-cache.sqlite').exists())
        self.assertTrue(again['assessment']['invocation_seconds'] > 0)
        report = saved_report(self.store, run_id=first['run_id'])
        html = Path(report['html']).read_text()
        for threshold in ('10%', '25%', '50%'):
            self.assertIn(threshold, html)
        self.assertNotIn('<script', html)
        self.assertEqual(0, report['new_jev_requests'])

    def test_opt_in_cache_is_separate_and_fresh_bypasses_it(self):
        self.run_assessment(base=self.base, reuse_cache=True)
        reused = self.run_assessment(base=self.base, reuse_cache=True)
        self.assertEqual([], self.calls)
        self.assertEqual(2, reused['assessment']['reused_answers'])
        fresh = self.run_assessment(base=self.base, fresh=True)
        self.assertEqual(1, len(self.calls))
        self.assertEqual(0, fresh['assessment']['reused_answers'])

    def test_corrupt_optional_cache_is_visible_miss(self):
        (self.store.path / 'jev-cache.sqlite').write_bytes(b'broken')
        result = self.run_assessment(base=self.base, reuse_cache=True)
        self.assertTrue(result['complete'])
        self.assertEqual(1, len(self.calls))
        self.assertTrue(result['assessment']['warnings'])
        self.assertTrue(Path(result['progress']).exists())

    def test_request_ceiling_survives_partial_run_and_can_be_explicitly_increased(self):
        self.raw['evaluator'] = {'max_batch_units': 1}
        write_json(self.root / 'faultline.json', self.raw)
        first = self.run_assessment(base=self.base, max_requests=1)
        self.assertFalse(first['complete'])
        self.assertEqual(1, len(self.calls))
        same = self.run_assessment(resume=first['run_id'])
        self.assertFalse(same['complete'])
        self.assertEqual([], self.calls)
        finish = self.run_assessment(resume=first['run_id'], max_requests=2)
        self.assertTrue(finish['complete'])
        self.assertEqual(1, len(self.calls))
        self.assertEqual(2, finish['usage']['requests'])
        self.assertEqual(246, finish['usage']['input_tokens'])

    def test_prepare_setup_demo_never_call_transport_or_native_runner(self):
        with patch('faultline.tia.runners.invoke', side_effect=AssertionError('No execution')):
            status = setup(self.store)
            self.assertEqual('none', status['execution'])
            result = self.run_assessment(base=self.base, prepare=True)
            self.assertTrue(result['dry_run'])
            self.assertEqual([], self.calls)
            self.assertFalse((self.store.path / 'runs').exists())
            demo = saved_report(self.store, demo=True)
            self.assertIn('SYNTHETIC DEMO', Path(demo['html']).read_text())

    def test_run_integrity_and_configuration_changes_stop_before_spending(self):
        first = self.run_assessment(base=self.base)
        self.raw['suites'][0]['sources'] = ['tests/ATest.php']
        write_json(self.root / 'faultline.json', self.raw)
        with self.assertRaisesRegex(FaultlineError, 'Configuration'):
            self.run_assessment(resume=first['run_id'])
        self.assertEqual([], self.calls)

    def test_html_escapes_untrusted_change_identity(self):
        result = self.run_assessment(base=self.base, identifier='<script>alert(1)</script>')
        html = Path(result['html']).read_text()
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_context_is_frozen_for_resume_and_full_source_survives(self):
        from faultline.tia.context import build
        manifest = self.store.path / 'manifest.json'
        write_json(manifest, {'schema_version': 1, 'evidence': [
            {'kind': 'git_file', 'path': 'src/Service.php', 'revision': 'head'}]})
        context = Path(build(self.store, self.base, self.head, manifest)['output'])
        first = self.run_assessment(base=self.base, context_path=context)
        self.assertIn('class Service', json.dumps(self.calls))
        context.unlink()
        resumed = self.run_assessment(resume=first['run_id'])
        self.assertTrue(resumed['complete'])
        self.assertEqual([], self.calls)
        case = checked(Path(resumed['json']), 'benchmark')
        self.assertIn('class Service', case['context_bundle']['evidence'][0]['text'])

    def test_optional_sqlite_is_not_needed_for_assessment(self):
        original = builtins.__import__
        def no_sqlite(name, *args, **kwargs):
            if name == 'sqlite3' or name.endswith('.cache'):
                raise ImportError('unavailable')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=no_sqlite):
            result = self.run_assessment(base=self.base)
        self.assertTrue(result['complete'])
        self.assertEqual(1, len(self.calls))

    def test_failure_after_send_retains_unknown_charge_on_resume(self):
        def failing(engine):
            class HTTP:
                def request(inner, *args, **kwargs):
                    engine.budget.take()
                    raise FaultlineError('Connection lost after send')
            return HTTP()
        first = assess(self.store, base=self.base, max_requests=2, transport_factory=failing)
        self.assertFalse(first['complete'])
        self.assertIsNone(first['usage']['input_tokens'])
        resumed = self.run_assessment(resume=first['run_id'])
        self.assertTrue(resumed['complete'])
        self.assertEqual(2, resumed['usage']['requests'])
        self.assertIsNone(resumed['usage']['input_tokens'])
        self.assertIsNone(resumed['usage']['input_usd_estimate'])
        self.assertIn('including earlier invocations', Path(resumed['markdown']).read_text())

    def test_prefetch_preserves_binary_utf8_and_newlines_without_process_per_file(self):
        source = GitSources(self.root, self.head)
        paths = list(source.files)
        expected = {p: source.read(p) for p in paths}
        source.cache.clear()
        original = subprocess.run
        with patch('faultline.tia.evidence.subprocess.run', wraps=original) as process:
            source.prefetch(paths)
            self.assertEqual(expected, {p: source.read(p) for p in paths})
            self.assertEqual(1, process.call_count)


class JournalTests(unittest.TestCase):
    def test_attempt_survives_restart_with_unknown_usage_and_partial_tail(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            p = Progress(folder)
            budget = RunBudget(1, p)
            budget.request_key = 'request'
            budget.take()
            with p.path.open('ab') as stream:
                stream.write(b'{"partial":')
            resumed = Progress(folder)
            self.assertEqual([{'request_key': 'request', 'usage': None}], resumed.attempts)
            with self.assertRaises(FaultlineError):
                RunBudget(1, resumed).take()
            with p.path.open('r+b') as stream:
                stream.write(b'x')
            with self.assertRaises(FaultlineError):
                Progress(folder)

    def test_concurrent_resume_fails_and_lock_releases(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            with run_lock(folder):
                with self.assertRaises(FaultlineError):
                    with run_lock(folder):
                        pass
            with run_lock(folder):
                pass

    def test_cache_probe_does_not_count_unused_answers_as_reuse(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            value = {'request_key': 'key', 'question_id': 'q0', 'model': 'jev-1.13.0', 'answer': answer()}
            class Cache:
                def get(self, key, qid):
                    return value
            p = Progress(folder, Cache())
            self.assertEqual(value, p.peek('key', 'q0'))
            self.assertFalse(p.path.exists())
            self.assertEqual(set(), p.reused)
            self.assertEqual(value, p.get('key', 'q0'))
            self.assertEqual({('key', 'q0')}, Progress(folder).reused)

    def test_copied_skill_runs_without_install_or_sqlite(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            bundle = Path(__file__).resolve().parents[1] / 'skills/faultline'
            shutil.copytree(bundle, root / 'skill')
            # -S prevents installed packages from hiding packaging mistakes.
            script = "import builtins,runpy,sys\noriginal=builtins.__import__\ndef guarded(name,*a,**kw):\n if name=='sqlite3': raise ImportError('unavailable')\n return original(name,*a,**kw)\nbuiltins.__import__=guarded\nsys.path.insert(0,sys.argv[1]+'/scripts')\nsys.argv=[sys.argv[1]+'/scripts/run.py','--root',sys.argv[2],'report','--demo','--output','demo.html']\nrunpy.run_path(sys.argv[0],run_name='__main__')"
            result = subprocess.run([sys.executable, '-S', '-c', script, str(root / 'skill'), str(root)],
                                    cwd=root, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((root / 'demo.html').exists())
