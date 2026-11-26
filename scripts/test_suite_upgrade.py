"""Upgrade real legacy native state; no model calls or desktop application. 作者：Jeff.Liu"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

from product_handoff import provider_capabilities

LEGACY_COMMIT = '34eaf71f2bce81c051cb220aaa5e11b27d467a2b'


class SuiteUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        selected = os.environ.get('PROJECT_DOCS_CONVERGE_TEST_ROOT')
        if not selected:
            raise unittest.SkipTest('legacy upgrade requires selected Converge checkout and pinned Git history')
        cls.current = Path(selected).resolve()
        result = subprocess.run(['git', '-C', str(cls.current), 'archive', '--format=tar',
                                 LEGACY_COMMIT, 'scripts', 'VERSION'], capture_output=True)
        if result.returncode:
            raise unittest.SkipTest('pinned legacy Converge Git source is unavailable')
        cls.temporary = tempfile.TemporaryDirectory(prefix='suite legacy provider ')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.legacy = Path(cls.temporary.name)
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
            archive.extractall(cls.legacy, filter='data')
        cls.legacy_digest = hashlib.sha256((cls.legacy / 'scripts/work_item.py').read_bytes()).hexdigest()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='suite upgrade ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.environment = dict(os.environ, HOME=str(self.root), PYTHONDONTWRITEBYTECODE='1')
        self.run_command(['git', 'init', '-q', str(self.project)])
        self.run_command(['git', '-c', 'user.name=Jeff.Liu', '-c', 'user.email=tests@example.invalid',
                          '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null',
                          'commit', '--allow-empty', '-qm', 'baseline'], cwd=self.project)
        self.baseline = self.run_command(['git', 'rev-parse', 'HEAD'], cwd=self.project).stdout.strip()
        self.state_root = self.root / 'native-state'
        result = self.run_command([sys.executable, '-I', '-B', '-c',
            'import sys,json;sys.path.insert(0,sys.argv[1]);from reference_receipt import freeze_receipt;'
            'print(json.dumps(freeze_receipt([])))', str(self.legacy / 'scripts')])
        self.reference = self.root / 'references.json'
        self.reference.write_text(result.stdout)
        self.arguments = ['resume', '--state-root', str(self.state_root), '--workspace', str(self.project),
                          '--baseline', self.baseline, '--target', 'legacy-task', '--requirement', 'FR-001',
                          '--acceptance', 'AC-001', '--reference-receipt', str(self.reference)]

    def run_command(self, argv, *, cwd=None, expected=0):
        result = subprocess.run(argv, cwd=cwd, env=self.environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def native(self, provider, arguments, *, expected=0):
        result = self.run_command([sys.executable, '-B', str(provider / 'scripts/work_item.py'),
                                   *arguments], expected=expected)
        return json.loads(result.stderr if expected == 1 else result.stdout)

    def create_legacy(self):
        result = self.native(self.legacy, self.arguments)
        return Path(result['path'])

    def verify(self, provider, state, argv, *, expected=0):
        return self.native(provider, ['verify', '--state', str(state), '--workspace', str(self.project),
                                     '--baseline', self.baseline, '--argv-json', json.dumps(argv)], expected=expected)

    def test_legacy_active_item_resumes_completes_and_cannot_be_recreated(self):
        state = self.create_legacy()
        original = json.loads(state.read_text())
        result = self.native(self.current, self.arguments)
        self.assertEqual(result['status'], 'resumed')
        self.assertEqual(Path(result['path']), state)
        for key, value in original.items():
            self.assertEqual(result['work_item'][key], value, key)
        passed = self.verify(self.current, state, [sys.executable, '-c', 'pass'])
        receipt = self.root / 'receipt.json'
        receipt.write_text(json.dumps(passed['receipt']))
        self.native(self.current, ['complete', '--state', str(state), '--workspace', str(self.project),
                                  '--baseline', self.baseline, '--receipt', str(receipt)])
        self.assertFalse(state.exists())
        archive = state.parent / 'completed' / state.name
        saved = archive.read_bytes()
        self.assertEqual(json.loads(saved)['work_item']['target'], original['target'])
        rejected = self.native(self.current, self.arguments, expected=1)
        self.assertIn('complete', rejected['message'])
        self.assertFalse(state.exists())
        self.assertEqual(saved, archive.read_bytes())

    def test_legacy_failed_verifier_stays_blocked_for_the_same_source_and_command(self):
        state = self.create_legacy()
        argv = [sys.executable, '-c', 'raise SystemExit(7)']
        failure = self.verify(self.legacy, state, argv, expected=2)
        self.assertEqual(failure['receipt']['exit_code'], 7)
        before = state.read_bytes()
        resumed = self.native(self.current, self.arguments)
        self.assertEqual(resumed['work_item']['status'], 'blocked')
        rejected = self.verify(self.current, state, argv, expected=2)
        self.assertEqual(rejected['status'], 'blocked')
        self.assertEqual(state.read_bytes(), before)

    def test_legacy_completion_without_archive_is_unavailable_and_not_reconstructed(self):
        state = self.create_legacy()
        passed = self.verify(self.legacy, state, [sys.executable, '-c', 'pass'])
        receipt = self.root / 'receipt.json'
        receipt.write_text(json.dumps(passed['receipt']))
        self.native(self.legacy, ['complete', '--state', str(state), '--workspace', str(self.project),
                                 '--baseline', self.baseline, '--receipt', str(receipt)])
        self.assertFalse(state.exists())
        rejected = self.native(self.current, ['completion', '--state', str(state)], expected=1)
        self.assertIn('archive is unavailable', rejected['message'])
        self.assertFalse(state.exists())
        self.assertFalse((state.parent / 'completed' / state.name).exists())

    def test_current_bridge_rejects_old_provider_without_changing_legacy_state(self):
        state = self.create_legacy()
        before = state.read_bytes()
        for capability in ('adopt', 'revise', 'iterate'):
            with self.subTest(capability=capability):
                self.assertFalse(provider_capabilities(self.legacy, capability)['ready'])
                self.assertTrue(provider_capabilities(self.current, capability)['ready'])
        self.assertEqual(state.read_bytes(), before)
        self.assertEqual(hashlib.sha256((self.legacy / 'scripts/work_item.py').read_bytes()).hexdigest(),
                         self.legacy_digest)

    def test_controlled_legacy_success_can_complete_after_upgrade(self):
        state = self.create_legacy()
        passed = self.verify(self.legacy, state, [sys.executable, '-c', 'pass'])
        receipt = self.root / 'legacy-passing-receipt.json'
        receipt.write_text(json.dumps(passed['receipt']))
        self.native(self.current, ['complete', '--state', str(state), '--workspace', str(self.project),
                                  '--baseline', self.baseline, '--receipt', str(receipt)])
        archived = self.native(self.current, ['completion', '--state', str(state)])
        self.assertEqual(archived['receipt'], passed['receipt'])
        self.assertFalse(state.exists())

    def test_matching_legacy_source_and_state_backup_restore_preserves_failure_budget(self):
        state = self.create_legacy()
        failed_argv = [sys.executable, '-c', 'raise SystemExit(9)']
        self.verify(self.legacy, state, failed_argv, expected=2)
        original = state.read_bytes()
        self.verify(self.current, state, [sys.executable, '-c', 'pass'])
        after_upgrade = state.read_bytes()
        self.assertNotEqual(after_upgrade, original)
        retained = self.root / 'retained-post-upgrade-state.json'
        retained.write_bytes(after_upgrade)
        # Isolated manual rollback of the matching source/state pair, before any completion.
        replacement = state.with_suffix('.restore')
        replacement.write_bytes(original)
        replacement.replace(state)
        resumed = self.native(self.legacy, self.arguments)
        self.assertEqual(resumed['work_item']['status'], 'blocked')
        self.assertEqual(state.read_bytes(), original)
        rejected = self.verify(self.legacy, state, failed_argv, expected=2)
        self.assertEqual(rejected['reason'], 'identical_verifier_failure')
        self.assertEqual(retained.read_bytes(), after_upgrade)
        self.assertFalse((state.parent / 'completed' / state.name).exists())


if __name__ == '__main__':
    unittest.main()
