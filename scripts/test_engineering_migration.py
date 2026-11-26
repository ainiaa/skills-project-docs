"""Ownership, reachability and compatibility contracts for the engineering split."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = 'GUIDE.md' if ROOT.name == '.bundle' else 'SKILL.md'
ENGINEERING = ROOT / 'skills/project-docs-engineering'
EXPECTED = {
    'Engineering': 'add-app add-service adopt api-mock bootstrap changelog code-gen db-design db-migrate deploy design e2e i18n lint perf quality security ship standard test-setup',
    'Product': 'prd ui-design ui-design-pro',
    'Lifecycle': 'feature relate retro status',
    'Converge': 'fix implement loop-next loop-run refactor review task tdd',
    'Overview': 'arch onboard',
    'Host': 'settings',
}


def local_links(path):
    for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
        if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target) or target.startswith('#'):
            continue
        yield (path.parent / target.split('#', 1)[0]).resolve()


class EngineeringMigrationTests(unittest.TestCase):
    def test_relation_commands_are_implemented_in_capability_status(self):
        document = (ROOT / 'docs/pdlc-capability-map.md').read_text()
        status = document.split('## 重复消除与实际缺口', 1)[1]
        for command in ('set', 'query', 'impact', 'orphans', 'validate'):
            self.assertIn('`' + command + '`', status)
        self.assertIn('直接读取原记录', status)
        self.assertNotIn('`rebuild`', status)
        gaps = status.split('保留缺口：', 1)[1]
        self.assertNotIn('六类业务关系', gaps)
        self.assertNotIn('反向索引', gaps)

    def test_review_modes_keep_product_and_engineering_document_review(self):
        entries = json.loads((ROOT / 'docs/pdlc-capability-map.json').read_text())['entries']
        review = next(item for item in entries if item['name'] == 'pdlc-review')
        self.assertEqual({'code': 'Converge', 'product-document': 'Product',
                          'engineering-document': 'Engineering'},
                         {mode['mode']: mode['owner'] for mode in review['modes']})
        for mode in review['modes']:
            self.assertTrue((ROOT / 'docs' / mode['owned_reference']).resolve().is_file())

    def test_all_upstream_entries_have_one_responsible_owner_and_canonical_method(self):
        data = json.loads((ROOT / 'docs/pdlc-capability-map.json').read_text())
        expected = {'pdlc-' + name: owner for owner, names in EXPECTED.items() for name in names.split()}
        self.assertEqual(38, len(expected))
        self.assertEqual(set(expected), {item['name'] for item in data['entries']})
        for item in data['entries']:
            with self.subTest(capability=item['name']):
                self.assertEqual(expected[item['name']], item['owner'])
                self.assertEqual(len(set(item['collaborators'])), len(item['collaborators']))
                self.assertNotIn(item['owner'], item['collaborators'])
                self.assertNotIn('project-docs-lifecycle/references/engineering/', item['owned_reference'])
                method = (ROOT / 'docs' / item['owned_reference']).resolve()
                self.assertTrue(method.is_relative_to(ROOT))
                self.assertTrue(method.is_file(), method)
        self.assertEqual('Product', expected['pdlc-prd'])

    def test_engineering_resources_and_license_resolve_without_installed_providers(self):
        self.assertTrue((ENGINEERING / ENTRY).is_file())
        resources = [ENGINEERING / 'references' / (name + '.md')
                     for name in ('project', 'design', 'quality', 'release')]
        for document in resources:
            self.assertTrue(document.is_file(), document)
            links = list(local_links(document))
            self.assertTrue(links, document)
            for target in links:
                self.assertTrue(target.is_relative_to(ROOT), target)
                self.assertTrue(target.is_file(), target)
        notice = ROOT / 'references/third-party-notices.md'
        self.assertIn('Copyright (c) 2026 LEO', notice.read_text())
        self.assertIn('Permission is hereby granted', notice.read_text())

    def test_old_method_paths_are_redirects_to_one_current_source(self):
        for name in ('project', 'design', 'quality', 'release'):
            legacy = ROOT / 'skills/project-docs-lifecycle/references/engineering' / (name + '.md')
            targets = list(local_links(legacy))
            self.assertIn((ENGINEERING / 'references' / (name + '.md')).resolve(), targets)
            self.assertFalse(re.search(r'^## ', legacy.read_text(), re.M), legacy)
            self.assertTrue(all(target.is_file() for target in targets))

    def test_coordination_and_product_methods_remain_accessible(self):
        for relative in ('skills/project-docs-lifecycle/references/coordination.md',
                         'skills/project-docs-product/references/ui-design.md',
                         'docs/engineering-ownership.md'):
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            for target in local_links(path):
                self.assertTrue(target.is_file(), (relative, target))


if __name__ == '__main__':
    unittest.main()
