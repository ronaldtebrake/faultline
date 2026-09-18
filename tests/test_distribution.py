"""Keep native plugin wrappers aligned with the standalone skill package."""
import json
import re
import unittest
from pathlib import Path

from faultline import __version__

REPO = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_manifests_share_identity_version_and_existing_skill(self):
        for name in ('plugin.json', '.codex-plugin/plugin.json', '.claude-plugin/plugin.json'):
            manifest = json.loads((REPO / name).read_text())
            self.assertEqual('faultline', manifest['name'])
            self.assertEqual(__version__, manifest['version'])
        for name in ('.agents/plugins/marketplace.json', '.claude-plugin/marketplace.json'):
            catalog = json.loads((REPO / name).read_text())
            entry = catalog['plugins'][0]
            source = entry['source']
            path = source['path'] if isinstance(source, dict) else source
            self.assertEqual('faultline', entry['name'])
            self.assertTrue((REPO / path / 'skills/faultline/SKILL.md').is_file())

    def test_skill_markdown_links_stay_inside_installable_bundle(self):
        skill = REPO / 'skills/faultline'
        for page in skill.rglob('*.md'):
            for link in re.findall(r'\]\(([^)]+)\)', page.read_text()):
                if '://' in link or link.startswith('#'):
                    continue
                target = (page.parent / link.split('#')[0]).resolve()
                self.assertTrue(target.is_relative_to(skill.resolve()), (page, link))
                self.assertTrue(target.is_file(), (page, link))
