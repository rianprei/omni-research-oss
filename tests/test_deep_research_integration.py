import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'deep-research' / 'SKILL.md'
REFS = SKILL.parent / 'references'
EXPECTED_VERSION = '1.3.0'


def declared_versions():
    """Every place this package declares its own version."""
    versions = {}

    versions['plugin.json'] = json.loads(
        (ROOT / 'plugin.json').read_text(encoding='utf-8')
    )['version']

    cloud = (ROOT / 'server' / 'cloud.py').read_text(encoding='utf-8')
    versions['server/cloud.py'] = re.search(
        r"MCPServer\('OmniResearch OSS',\s*version='([^']+)'", cloud
    ).group(1)

    main = (ROOT / 'server' / 'main.py').read_text(encoding='utf-8')
    versions['server/main.py'] = re.search(
        r"'serverInfo':\{'name':'omni-research-oss','version':'([^']+)'\}", main
    ).group(1)

    engine = (ROOT / 'server' / 'engine.py').read_text(encoding='utf-8')
    versions['server/engine.py'] = re.search(
        r"return \{'name':'OmniResearch OSS','version':'([^']+)'", engine
    ).group(1)

    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    versions['README.md'] = re.search(
        r'^# OmniResearch OSS v([0-9.]+)', readme, re.M
    ).group(1)

    return versions


class DeepResearchIntegrationTests(unittest.TestCase):
    def test_portable_skill_metadata(self):
        text = SKILL.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('---\nname: deep-research\ndescription: '))
        self.assertEqual(text.count('\n---\n', 2), 1)
        self.assertIn('Agent', text)
        self.assertIn('single-agent', text)

    def test_refs_are_preserved_verbatim(self):
        import hashlib
        expected = {
            'researcher.md': 'd3ec5a268edb44e88fd2cca48551f65e2094a511b08d226cbd52ce18da1b88dd',
            'report-writer.md': '52057c0808b8ea640a908f6543866ae3d1d3981a05af37fdbc7543250dbff84f',
        }
        for filename, digest in expected.items():
            self.assertEqual(hashlib.sha256((REFS / filename).read_bytes()).hexdigest(), digest)

    def test_user_supplied_upstream_refs_are_excluded(self):
        """The public candidate must not ship files whose redistribution license was never verified."""
        self.assertFalse((REFS / 'supplied-coordinator.md').exists())

    def test_coordinator_wires_roles_and_quality_gates(self):
        text = SKILL.read_text(encoding='utf-8')
        for needed in (
            'references/researcher.md',
            'references/report-writer.md',
            'reports/',
            'research_notes/',
            'BLUF',
            'run_in_background=false',
            'Quality gates',
        ):
            self.assertIn(needed, text)
        omni = (ROOT / 'skills' / 'omni-research' / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('deep-research', omni)

    def test_versions_agree_across_every_declared_location(self):
        versions = declared_versions()
        self.assertGreaterEqual(len(versions), 5)
        for where, value in versions.items():
            self.assertEqual(value, EXPECTED_VERSION, f'{where} declares {value}, expected {EXPECTED_VERSION}')
        self.assertEqual(len(set(versions.values())), 1, f'version drift across files: {versions}')

    def test_skill_manifests_are_valid(self):
        skills = sorted((ROOT / 'skills').glob('*/SKILL.md'))
        self.assertEqual(len(skills), 6)
        for skill in skills:
            text = skill.read_text(encoding='utf-8')
            self.assertTrue(text.startswith('---\nname: '), f'{skill} is missing a name')
            self.assertIn('\ndescription: ', text, f'{skill} is missing a description')
            name = re.search(r'^name:\s*(\S+)', text, re.M).group(1)
            self.assertEqual(name, skill.parent.name, f'{skill} name does not match its directory')

    def test_cloud_exposes_only_public_read_only_tools(self):
        cloud = (ROOT / 'server' / 'cloud.py').read_text(encoding='utf-8')
        for local_only in ('read_document', 'memory_save', 'memory_search'):
            self.assertNotRegex(cloud, rf'def {local_only}\b')
        exposed = set(re.findall(r'^def ([a-z_]+)\(', cloud, re.M)) - {'_bounds'}
        self.assertEqual(
            len(exposed), 12,
            f'cloud should expose 12 public tools, got {len(exposed)}: {sorted(exposed)}',
        )


if __name__ == '__main__':
    unittest.main()
