"""Executable examples for frozen engineering inputs and completed iteration handoff."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from product_inputs import freeze_inputs, require_current_inputs
from product_revision import plan_revision

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'skills/project-docs-engineering/assets/examples/iteration-handoff'


def attachments(folder):
    return {key: str((folder / value).resolve())
            for key, value in json.loads((folder / 'attachments.json').read_text()).items()}


class EngineeringHandoffTests(unittest.TestCase):
    def test_native_receipt_executes_the_strict_checkpoint_and_detects_deleted_project_rule(self):
        provider = os.environ.get('PROJECT_DOCS_CONVERGE_TEST_ROOT')
        if not provider:
            self.skipTest('native integration requires PROJECT_DOCS_CONVERGE_TEST_ROOT')
        import test_product_handoff as fixtures
        from test_product_inputs import ProductInputsTests
        from product_handoff import prepare, adopt
        from lifecycle_quality import STAGE_CHECKS, reference
        from lifecycle_checklist import load_catalog
        fixtures.ProductHandoffTests.setUp(self)
        ProductInputsTests.project_index(self)
        request = adopt(prepare(self.prd, provider, self.project, 'REQ-checkpoint', self.state_root))
        snapshot = request['input_snapshot']
        (self.root / 'inputs.json').write_text(json.dumps(snapshot))
        evidence = [reference(self.root, 'prd.md', '显示当前状态')]
        entry = {'stage': 'L3', 'artifact': reference(self.root, 'prd.md'), 'reviewer': 'fixture-reviewer',
                 'reviewer_kind': 'model', 'at': '2026-11-16T10:00:00+08:00',
                 'checks': [{'id': key, 'verdict': 'pass', 'reason': 'Synthetic source and result walkthrough.',
                             'evidence': evidence} for key in STAGE_CHECKS['L3']]}
        quality = {'schema_version': 1, 'project_ref': 'P1', 'subject_ref': 'REQ-checkpoint', 'stages': [entry]}
        report = self.project / 'quality.json'
        report.write_text(json.dumps(quality))
        command = [sys.executable, str(ROOT / 'scripts/lifecycle_quality.py'), 'checkpoint',
                   '--root', str(self.root), '--contract', 'project/quality.json', '--target', 'L3:prd.md',
                   '--inputs', 'inputs.json', '--expected-inputs', snapshot['fingerprint']]
        def verify():
            result = subprocess.run([sys.executable, str(Path(provider) / 'scripts/work_item.py'), 'verify',
                '--state', request['native_result']['path'], '--workspace', str(self.project),
                '--baseline', request['baseline'], '--argv-json', json.dumps(command)],
                capture_output=True, text=True, timeout=30)
            return result.returncode, json.loads(result.stdout)
        code, failed = verify()
        self.assertEqual(code, 2, failed)
        self.assertEqual(failed['receipt']['exit_code'], 1)
        catalog = load_catalog('L3')
        records = []
        for definition in catalog['items']:
            item = {'id': definition['id'], 'applicability': 'applicable' if definition['required'] else 'not_applicable',
                    'reason': 'Synthetic read-only state scope.', 'evidence': evidence}
            if definition['required']:
                item['verification'] = {'kind': 'review', 'result': 'passed', 'evidence': evidence}
            records.append(item)
        project = {'id': 'PROJECT-KEEP-ID', 'applicability': 'applicable', 'reason': 'Explicit frozen rule.',
                   'evidence': evidence, 'verification': {'kind': 'review', 'result': 'passed', 'evidence': evidence}}
        records.append(project)
        entry['coverage'] = {'catalog_sha256': catalog['fingerprint'], 'items': records}
        report.write_text(json.dumps(quality))
        code, passed = verify()
        self.assertEqual(code, 0, passed)
        self.assertEqual(passed['receipt']['argv'], command)
        self.assertNotEqual(passed['receipt']['source'], failed['receipt']['source'])
        records.remove(project)
        report.write_text(json.dumps(quality))
        code, deleted = verify()
        self.assertEqual(code, 2, deleted)
        self.assertEqual(deleted['receipt']['exit_code'], 1)

    def test_both_versions_freeze_exactly_one_prd_design_and_test_strategy(self):
        snapshots = []
        for name in ('v1', 'v2'):
            folder = EXAMPLE / name
            snapshot = freeze_inputs(folder / 'prd.md', attachments=attachments(folder))
            self.assertEqual(snapshot['product_version'], name)
            self.assertEqual({Path(item['path']).name for item in snapshot['files']},
                             {'prd.md', 'design.md', 'test-strategy.md'})
            self.assertEqual(set(snapshot['requirements']), {'FR-001'})
            snapshots.append(snapshot)
        report = plan_revision(*snapshots)
        self.assertTrue(report['version_changed'])
        self.assertEqual(report['before'], snapshots[0])
        self.assertEqual(report['after'], snapshots[1])

    def test_design_drift_is_rejected_without_a_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory).resolve() / 'v1'
            shutil.copytree(EXAMPLE / 'v1', folder)
            snapshot = freeze_inputs(folder / 'prd.md', attachments=attachments(folder))
            (folder / 'design.md').write_text((folder / 'design.md').read_text() + '\n新增实现约束。\n')
            with self.assertRaises(ValueError):
                require_current_inputs(snapshot)

    def test_copied_example_completes_then_runs_one_new_iteration_with_real_red_green(self):
        provider = os.environ.get('PROJECT_DOCS_CONVERGE_TEST_ROOT')
        if not provider:
            self.skipTest('native integration requires PROJECT_DOCS_CONVERGE_TEST_ROOT')
        from product_handoff import prepare, prepare_iteration, adopt
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            delivery = root / 'delivery'
            shutil.copytree(EXAMPLE, delivery)
            project = root / 'project'
            project.mkdir()
            (project / 'app.py').write_text('def total(values):\n return sum(values)\n')
            tests = project / 'tests'
            tests.mkdir()
            case = tests / 'test_total.py'
            case.write_text('import unittest\nfrom app import total\nclass Total(unittest.TestCase):\n'
                            ' def test_normal(self): self.assertEqual(total([1,2]),3)\n'
                            ' def test_empty(self): self.assertEqual(total([]),0)\n'
                            ' def test_invalid(self):\n  with self.assertRaises(TypeError): total(None)\n')
            subprocess.run(['git', 'init', '-q', str(project)], check=True)
            subprocess.run(['git', 'add', '.'], cwd=project, check=True)
            subprocess.run(['git', '-c', 'user.name=Jeff.Liu', '-c', 'user.email=tests@example.invalid',
                            '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null',
                            'commit', '-qm', 'baseline'], cwd=project, check=True)
            native = Path(provider) / 'scripts/work_item.py'
            def verify(handoff):
                result = subprocess.run([sys.executable, str(native), 'verify', '--state', handoff['native_result']['path'],
                    '--workspace', str(project), '--baseline', handoff['baseline'], '--argv-json',
                    json.dumps([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'])],
                    capture_output=True, text=True, timeout=30)
                return result.returncode, json.loads(result.stdout)
            def complete(handoff, receipt):
                path = root / 'passing-receipt.json'
                path.write_text(json.dumps(receipt))
                result = subprocess.run([sys.executable, str(native), 'complete', '--state', handoff['native_result']['path'],
                    '--workspace', str(project), '--baseline', handoff['baseline'], '--receipt', str(path)],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
            v1 = delivery / 'v1'
            first = adopt(prepare(v1 / 'prd.md', provider, project, 'REQ-total', root / 'state', attachments=attachments(v1)))
            code, green = verify(first)
            self.assertEqual(code, 0, green)
            complete(first, green['receipt'])
            old = Path(first['native_result']['path'])
            archive = old.parent / 'completed' / old.name
            frozen = archive.read_bytes()
            v2 = delivery / 'v2'
            current = prepare(v2 / 'prd.md', provider, project, 'REQ-total.iter-2', root / 'state', attachments=attachments(v2))
            request = prepare_iteration(first, current, plan_revision(first['input_snapshot'], current['input_snapshot']))
            second = adopt(request)
            self.assertEqual(adopt(request)['native_result']['status'], 'resumed')
            case.write_text(case.read_text() + ' def test_negative(self):\n  with self.assertRaises(ValueError): total([-1])\n')
            code, red = verify(second)
            self.assertEqual(code, 2, red)
            self.assertEqual(red['receipt']['test_check']['failed'], 1)
            (project / 'app.py').write_text('def total(values):\n if any(value<0 for value in values): raise ValueError("negative")\n return sum(values)\n')
            code, green = verify(second)
            self.assertEqual(code, 0, green)
            self.assertEqual(green['receipt']['test_check']['passed'], 4)
            complete(second, green['receipt'])
            self.assertEqual(archive.read_bytes(), frozen)
            self.assertEqual(len(list(old.parent.glob('*.json'))), 0)
            self.assertEqual(len(list((old.parent / 'completed').glob('*.json'))), 2)


if __name__ == '__main__':
    unittest.main()
