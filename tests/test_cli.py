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
    def test_copied_skills_run_without_installation_or_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'skills'
            result = subprocess.run([sys.executable, str(REPO / 'scripts/install_skills.py'), '--target', str(target), '--copy'], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            helper = target / 'rank-tests/scripts/run.py'
            root = Path(temp) / 'project'
            root.mkdir()
            env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'TYPESAFE_API_KEY')}
            init = subprocess.run([sys.executable, '-S', str(helper), '--root', str(root), 'init'], env=env, capture_output=True, text=True)
            self.assertEqual(0, init.returncode, init.stderr)
            self.assertTrue((root / '.faultline/config.json').exists())
            (root / 'test.js').write_text('test("a", () => expect(1).toBe(1))')
            draft = root / '.faultline/draft.jsonl'
            draft.write_text(json.dumps({'id': 'a', 'source': 'test.js', 'description': 'Checks equality'}))
            index = subprocess.run([sys.executable, '-S', str(helper), '--root', str(root), 'index', '--input', str(draft), '--agent', 'test'], env=env, capture_output=True, text=True)
            self.assertEqual(0, index.returncode, index.stderr)
            score = root / 'probs.json'
            score.write_text(json.dumps(dict(zip(('irrelevant', 'weak', 'plausible', 'strong', 'direct'), (0, 0, 0, 0, 1)))))
            scored = subprocess.run([sys.executable, '-S', str(helper), '--root', str(root), 'score', '--input', str(score)], env=env, capture_output=True, text=True)
            self.assertEqual(0, scored.returncode, scored.stderr)
            self.assertEqual(4, json.loads(scored.stdout)['score'])
            collision = subprocess.run([sys.executable, str(REPO / 'scripts/install_skills.py'), '--target', str(target), '--copy'], capture_output=True, text=True)
            self.assertNotEqual(0, collision.returncode)

    def test_malformed_input_returns_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            malformed = root / 'bad.json'
            malformed.write_text('not JSON')
            result = subprocess.run([sys.executable, str(REPO / 'skills/rank-tests/scripts/run.py'), '--root', str(root), 'rank', '--change', str(malformed)], capture_output=True, text=True)
            self.assertEqual(1, result.returncode)
            self.assertNotIn('Traceback', result.stderr)
