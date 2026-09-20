import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def test_standalone_skill_runs_without_checkout_or_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'installed/faultline'
            shutil.copytree(REPO / 'skills/faultline', target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            helper = target / 'scripts/run.py'
            root = Path(temp) / 'project'
            root.mkdir()
            env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONDONTWRITEBYTECODE', 'TYPESAFE_API_KEY')}
            init = subprocess.run([sys.executable, '-S', str(helper), '--root', str(root), 'init'], env=env, capture_output=True, text=True)
            self.assertEqual(0, init.returncode, init.stderr)
            self.assertTrue((root / '.faultline/.gitignore').exists())
            self.assertFalse((root / '.faultline/config.json').exists())
            (root / 'test.js').write_text('test("a", () => expect(1).toBe(1))')
            (root / 'faultline.json').write_text(json.dumps({'schema_version': 2, 'suites': [
                {'id': 'unit', 'sources': ['test.js']}]}))
            def git(*args):
                subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
            git('init', '-q')
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fixture')
            prepared = subprocess.run([sys.executable, '-S', str(helper), '--root', str(root),
                'benchmark', '--base', 'HEAD', '--head', 'HEAD', '--prepare'], env=env, capture_output=True, text=True)
            self.assertEqual(0, prepared.returncode, prepared.stderr)
            self.assertEqual('none', json.loads(prepared.stdout)['execution'])
            self.assertFalse(list(target.rglob('__pycache__')))

    def test_malformed_input_returns_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            malformed = root / 'faultline.json'
            malformed.write_text('not JSON')
            result = subprocess.run([sys.executable, str(REPO / 'skills/faultline/scripts/run.py'), '--root', str(root), 'discover'], capture_output=True, text=True)
            self.assertEqual(1, result.returncode)
            self.assertNotIn('Traceback', result.stderr)
