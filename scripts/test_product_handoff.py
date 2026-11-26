"""Verify self-owned PRD handoff against the selected native Converge. 作者：Jeff.Liu"""
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ProductHandoffTests(unittest.TestCase):
    def test_standalone_cli_reports_missing_provider_without_creating_state(self):
        command = [sys.executable, str(ROOT / 'scripts/product_handoff.py'),
                   '--prd', str(self.prd), '--converge-root', str(self.upstream),
                   '--project', str(self.project), '--target', 'REQ-001',
                   '--state-root', str(self.state_root)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('selected native Converge is unavailable', json.loads(result.stdout)['error'])
        self.assertFalse(self.state_root.exists())

    def test_prepared_handoff_ignores_provider_test_files_but_rejects_runtime_changes(self):
        from product_handoff import prepare, recheck
        scripts = self.upstream / 'scripts'
        scripts.mkdir()
        (scripts / 'work_item.py').write_text(
            'def resume_or_create(*, state_root, workspace, baseline, target, requirements, acceptance, '
            'decisions, reference_receipt, continuation, exclusive_target=False): pass\n'
            'def work_item_path(root, workspace, baseline, target, requirements, acceptance): pass\n')
        (scripts / 'reference_receipt.py').write_text('def freeze_receipt(references): pass\n')
        (scripts / 'delivery_lease.py').write_text('def lock_record(path): pass\n')
        (self.upstream / 'native.json').write_text('{}')
        manifest = {'id': 'native-v1', 'manifest': str(self.upstream / 'native.json'), 'sources': []}
        binding = {'binding': {'workflow_provider': manifest}}
        (scripts / 'delivery_engine.py').write_text('print(' + repr(json.dumps(binding)) + ')\n')
        args = (self.prd, self.upstream, self.project, 'REQ-001', self.state_root)
        prepared = prepare(*args)
        (scripts / 'test_work_item.py').write_text('# New upstream test.\n')
        self.assertEqual(recheck(prepared), prepared)
        with (scripts / 'work_item.py').open('a') as runtime:
            runtime.write('# Updated runtime.\n')
        with self.assertRaisesRegex(ValueError, 'provider changed'):
            recheck(prepared)

    def test_preflight_requires_shared_adopt_and_bind_imports_for_every_capability(self):
        from product_handoff import provider_capabilities
        scripts = self.upstream / 'scripts'
        scripts.mkdir()
        source = ('def resume_or_create(*, state_root, workspace, baseline, target, requirements, acceptance, '
                  'decisions, reference_receipt, continuation, exclusive_target=False, predecessor_completion=None): pass\n'
                  'def revise_work_item(path, *, workspace, baseline, target, requirements, acceptance, decisions, '
                  'reference_receipt, expected_state_fingerprint, reason): pass\n'
                  'def work_item_path(root, workspace, baseline, target, requirements, acceptance): pass\n'
                  'def read_completion(path): pass\n'
                  'def completion_path(path): pass\n')
        module = scripts / 'work_item.py'
        (scripts / 'reference_receipt.py').write_text('def freeze_receipt(references): pass\n')
        (scripts / 'delivery_lease.py').write_text('def lock_record(path): pass\n')
        module.write_text(source)
        for capability in ('adopt', 'revise', 'iterate'):
            self.assertTrue(provider_capabilities(self.upstream, capability)['ready'])
        for missing, candidate in (
                ('exclusive_target', source.replace('exclusive_target=False, ', '')),
                ('work_item_path', source.replace('def work_item_path(root, workspace, baseline, target, requirements, acceptance): pass\n', ''))):
            with self.subTest(missing=missing):
                module.write_text(candidate)
                for capability in ('adopt', 'revise', 'iterate'):
                    self.assertFalse(provider_capabilities(self.upstream, capability)['ready'], (missing, capability))

    def test_capability_preflight_is_read_only_and_reports_missing_signatures(self):
        from product_handoff import provider_capabilities
        scripts = self.upstream / 'scripts'
        scripts.mkdir()
        (scripts / 'work_item.py').write_text('def resume_or_create(*, state_root, workspace, baseline, target, '
                                            'requirements, acceptance, decisions, reference_receipt, continuation): pass\n'
                                            'def work_item_path(root, workspace, baseline, target, requirements, acceptance): pass\n')
        (scripts / 'reference_receipt.py').write_text('def freeze_receipt(references): pass\n')
        (scripts / 'delivery_lease.py').write_text('def lock_record(path): pass\n')
        report = provider_capabilities(self.upstream, 'adopt')
        self.assertFalse(report['ready'])
        self.assertIn('exclusive_target', ' '.join(report['missing']['adopt']))
        self.assertFalse(self.state_root.exists())
        cli = subprocess.run([sys.executable, str(ROOT / 'scripts/product_handoff.py'), '--check-provider',
                              '--converge-root', str(self.upstream), '--capability', 'iterate'],
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 1, cli.stderr)
        self.assertFalse(json.loads(cli.stdout)['ready'])
        module = scripts / 'work_item.py'
        module.write_text(module.read_text().replace('continuation):', 'continuation, exclusive_target=False):'))
        self.assertTrue(provider_capabilities(self.upstream, 'adopt')['ready'])
        self.assertFalse(provider_capabilities(self.upstream, 'iterate')['ready'])

    def complete_handoff(self, handoff):
        runner = self.provider() / 'scripts/work_item.py'
        command = [sys.executable, str(runner), 'verify', '--state', handoff['native_result']['path'],
                   '--workspace', str(self.project), '--baseline', handoff['baseline'],
                   '--argv-json', json.dumps([sys.executable, '-c', 'pass'])]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        receipt = self.root / 'completion-receipt.json'
        receipt.write_text(json.dumps(json.loads(result.stdout)['receipt']))
        subprocess.run([sys.executable, str(runner), 'complete', '--state', handoff['native_result']['path'],
                        '--workspace', str(self.project), '--baseline', handoff['baseline'],
                        '--receipt', str(receipt)], capture_output=True, text=True, check=True)

    def test_completed_iteration_preserves_business_goal_and_creates_one_new_execution(self):
        from product_handoff import adopt, prepare, prepare_iteration, provider_capabilities
        from product_revision import plan_revision
        previous = adopt(self.request())
        self.complete_handoff(previous)
        old_path = Path(previous['native_result']['path'])
        self.prd.write_text(self.prd.read_text().replace('产品版本：v1', '产品版本：v2')
                            .replace('产品版本 v1', '产品版本 v2'))
        current = prepare(self.prd, self.provider(), self.project, 'REQ-001.iter-2', self.state_root)
        impact = plan_revision(previous['input_snapshot'], current['input_snapshot'])
        prepared = prepare_iteration(previous, current, impact)
        self.assertTrue(provider_capabilities(self.provider(), 'iterate')['ready'])
        result = adopt(prepared)
        self.assertEqual(result['iteration']['business_target'], 'REQ-001')
        self.assertNotEqual(result['native_result']['path'], str(old_path))
        self.assertFalse(old_path.exists())
        self.assertEqual(adopt(prepared)['native_result']['status'], 'resumed')
        self.assertEqual(len(list(old_path.parent.glob('*.json'))), 1)
        self.complete_handoff(result)
        with self.assertRaises((RuntimeError, ValueError)):
            adopt(prepared)
        self.assertEqual(len(list(old_path.parent.glob('*.json'))), 0)

    def test_iteration_rejects_active_predecessor_reused_target_and_same_version(self):
        from product_handoff import adopt, prepare, prepare_iteration
        from product_revision import plan_revision
        previous = adopt(self.request())
        current = prepare(self.prd, self.provider(), self.project, 'REQ-001.iter-2', self.state_root)
        report = plan_revision(previous['input_snapshot'], current['input_snapshot'])
        with self.assertRaises(ValueError):
            prepare_iteration(previous, current, report)
        self.complete_handoff(previous)
        with self.assertRaises(ValueError):
            prepare_iteration(previous, current, report)
        self.prd.write_text(self.prd.read_text().replace('产品版本：v1', '产品版本：v2')
                            .replace('产品版本 v1', '产品版本 v2'))
        reused = self.request()
        with self.assertRaises(ValueError):
            prepare_iteration(previous, reused, plan_revision(previous['input_snapshot'], reused['input_snapshot']))

    def test_business_identity_survives_a_revision_between_completed_iterations(self):
        from product_handoff import adopt, prepare, prepare_iteration, prepare_revision
        from product_revision import plan_revision
        first = adopt(self.request())
        self.complete_handoff(first)
        def next_request(old, version, target):
            self.prd.write_text(self.prd.read_text().replace('产品版本：' + old['product_version'], '产品版本：' + version)
                                .replace('产品版本 ' + old['product_version'], '产品版本 ' + version))
            current = prepare(self.prd, self.provider(), self.project, target, self.state_root)
            return current, plan_revision(old['input_snapshot'], current['input_snapshot'])
        current, impact = next_request(first, 'v2', 'REQ-001.iter-2')
        second = adopt(prepare_iteration(first, current, impact))
        current, impact = next_request(second, 'v2.1', second['target'])
        revised = adopt(prepare_revision(second, current, impact))
        self.complete_handoff(revised)
        current, impact = next_request(revised, 'v3', 'REQ-001.iter-3')
        third = prepare_iteration(revised, current, impact)
        self.assertEqual(third['iteration']['business_target'], 'REQ-001')

    def test_revision_preflight_rejects_unsupported_api_before_lifecycle_write(self):
        from product_handoff import prepare_revision, adopt
        previous, current, report = self.revision_fixture(lifecycle=True)
        with patch('product_handoff.provider_capabilities', return_value={
                'ready': False, 'missing': {'revise': ['revise_work_item']}}), \
                patch('product_handoff.apply_impact') as apply, self.assertRaisesRegex(ValueError, 'revise'):
            adopt(prepare_revision(previous, current, report))
        apply.assert_not_called()

    def test_saved_iteration_cli_replays_once_and_partial_failure_keeps_conservative_impact(self):
        from product_handoff import adopt, prepare, prepare_iteration
        from product_revision import plan_revision
        from test_lifecycle_record import record
        previous = adopt(self.request())
        self.complete_handoff(previous)
        previous_file = self.root / 'adopted-v1.json'
        previous_file.write_text(json.dumps(previous))
        self.prd.write_text(self.prd.read_text().replace('产品版本：v1', '产品版本：v2')
                            .replace('产品版本 v1', '产品版本 v2').replace('正常展示', '展示合计'))
        current = prepare(self.prd, self.provider(), self.project, 'REQ-001.iter-2', self.state_root)
        record_path = self.root / 'lifecycle.json'
        record_path.write_text(json.dumps(record()))
        report = plan_revision(previous['input_snapshot'], current['input_snapshot'], record_path=record_path,
                               bindings={'FR-001': ['requirement']})
        prepared = prepare_iteration(previous, current, report)
        with patch('product_handoff.BIND', "raise RuntimeError('simulated native interruption')"), self.assertRaises(RuntimeError):
            adopt(prepared)
        candidate = record_path.read_bytes()
        self.assertEqual(json.loads(candidate)['revision'], 2)
        impact_file = self.root / 'impact.json'
        impact_file.write_text(json.dumps(report))
        inspect = subprocess.run([sys.executable, str(ROOT / 'scripts/product_handoff.py'),
            '--prd', str(self.prd), '--project', str(self.project), '--converge-root', str(self.provider()),
            '--state-root', str(self.state_root), '--target', 'REQ-001.iter-2',
            '--previous-iteration', str(previous_file), '--impact-report', str(impact_file)],
            capture_output=True, text=True)
        self.assertEqual(inspect.returncode, 0, inspect.stdout + inspect.stderr)
        inspected = json.loads(inspect.stdout)
        request_file = self.root / 'prepared-iteration.json'
        request_file.write_text(json.dumps(inspected))
        command = [sys.executable, str(ROOT / 'scripts/product_handoff.py'), '--prepared', str(request_file),
                   '--adopt', '--expected-contract', inspected['contract_fingerprint']]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)['native_result']['status'], 'resumed')
        self.assertEqual(record_path.read_bytes(), candidate)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='product handoff ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.upstream = self.root / 'upstream'
        self.upstream.mkdir()
        self.state_root = self.root / 'state'
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                        '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null',
                        'commit', '--allow-empty', '-qm', 'baseline'], cwd=self.project, check=True)
        self.prd = self.root / 'prd.md'
        self.prd.write_text('''# Example

> 产品版本：v1
> 状态：已确认

## 来源
### SRC-001 用户决定
用户已明确仅展示当前状态。

## 范围
### FR-001 查看状态
状态：已确认
依据：SRC-001
原型：否
确认记录：业务负责人，2026-11-14，产品版本 v1，范围 FR-001 与 AC-001，来源 SRC-001。
#### AC-001 正常展示
给定有效记录，打开详情时显示当前状态。
''')

    def provider(self):
        root = os.environ.get('PROJECT_DOCS_CONVERGE_TEST_ROOT')
        if not root:
            self.skipTest('native integration requires PROJECT_DOCS_CONVERGE_TEST_ROOT')
        return Path(root)

    def request(self):
        from product_handoff import prepare
        return prepare(self.prd, self.provider(), self.project, 'REQ-001', self.state_root)

    def call(self, *options):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/product_handoff.py'),
            '--prd', str(self.prd), '--converge-root', str(self.provider()),
            '--project', str(self.project), '--target', 'REQ-001',
            '--state-root', str(self.state_root), *options], capture_output=True, text=True, timeout=30)

    def test_inspection_binds_prd_and_native_provider_without_writes(self):
        result = self.request()
        self.assertEqual(result['product_version'], 'v1')
        self.assertEqual(result['prd_sha256'], hashlib.sha256(self.prd.read_bytes()).hexdigest())
        self.assertEqual(result['requirements'], ['FR-001'])
        self.assertEqual(result['acceptance'], ['AC-001'])
        self.assertEqual(result['provider'], 'native-v1')
        self.assertFalse(result['implementation_started'])
        self.assertFalse(self.state_root.exists())
        self.assertFalse((self.project / 'docs/.pdlc-state').exists())

    def test_cli_defaults_to_inspection_and_explicit_adopt_is_idempotent(self):
        before = self.prd.read_bytes()
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)['adopted'])
        prepared = json.loads(result.stdout)
        result = self.call('--adopt', '--expected-contract', prepared['contract_fingerprint'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        first = json.loads(result.stdout)
        self.assertTrue(first['adopted'])
        state = Path(first['native_result']['path'])
        frozen = state.read_bytes()
        result = self.call('--adopt', '--expected-contract', prepared['contract_fingerprint'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['native_result']['status'], 'resumed')
        self.assertEqual(state.read_bytes(), frozen)
        record = json.loads(frozen)
        self.assertEqual(record['reference_receipt']['references'][0]['content_fingerprint'],
                         hashlib.sha256(before).hexdigest())
        self.assertEqual(self.prd.read_bytes(), before)
        self.assertFalse((self.project / 'docs').exists())

    def test_changed_prd_or_prepared_command_is_rejected_before_execution(self):
        from product_handoff import adopt
        request = self.request()
        request['target'] = 'OTHER'
        with self.assertRaises(ValueError):
            adopt(request)
        request = self.request()
        self.prd.write_text(self.prd.read_text() + '\nChanged rule\n')
        with self.assertRaises(ValueError):
            adopt(request)
        self.assertFalse(self.state_root.exists())

    def test_existing_native_work_item_cannot_silently_change_input_version(self):
        from product_handoff import adopt
        first = adopt(self.request())
        state = Path(first['native_result']['path'])
        before = state.read_bytes()
        self.prd.write_text(self.prd.read_text() + '\nNew interpretation\n')
        with self.assertRaises((ValueError, RuntimeError)):
            adopt(self.request())
        self.assertEqual(state.read_bytes(), before)

    def test_unavailable_provider_draft_and_invalid_target_are_rejected(self):
        from product_handoff import prepare
        with self.assertRaises(ValueError):
            prepare(self.prd, self.upstream, self.project, 'REQ-001', self.state_root)
        for content, target in [(self.prd.read_text(), '../escape'), ('# No contract', 'REQ-001'),
                                (self.prd.read_text().replace('已确认', '草稿'), 'REQ-001')]:
            self.prd.write_text(content)
            with self.assertRaises(ValueError):
                prepare(self.prd, self.upstream, self.project, target, self.state_root)
        self.assertFalse(self.state_root.exists())

    def test_missing_project_and_non_git_project_are_rejected(self):
        from product_handoff import prepare
        for project in (self.root / 'missing', self.upstream):
            with self.assertRaises(ValueError):
                prepare(self.prd, self.upstream, project, 'REQ-001', self.state_root)

    def test_native_errors_or_false_success_are_not_adoption(self):
        from product_handoff import adopt
        request = self.request()
        for output in ('not-json', '{}', 'null', '[]', '{"status":"created","path":"missing","work_item":{}}'):
            with patch('product_handoff.subprocess.run', return_value=subprocess.CompletedProcess([], 0, output, '')):
                # Revalidation stays real; only the native write invocation is replaced.
                with patch('product_handoff.prepare', return_value=request):
                    with self.assertRaises((ValueError, RuntimeError)):
                        adopt(request)
        with patch('product_handoff.prepare', return_value=request), patch('product_handoff.subprocess.run',
                return_value=subprocess.CompletedProcess([], 2, '', 'failure')):
            with self.assertRaises(RuntimeError):
                adopt(request)

    def test_changed_project_baseline_is_rejected(self):
        from product_handoff import adopt
        request = self.request()
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                        '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null',
                        'commit', '--allow-empty', '-qm', 'new baseline'], cwd=self.project, check=True)
        with self.assertRaises(ValueError):
            adopt(request)
        self.assertFalse(self.state_root.exists())

    def test_requirement_set_change_keeps_existing_work_item(self):
        from product_handoff import adopt
        first = adopt(self.request())
        state = Path(first['native_result']['path'])
        before = state.read_bytes()
        self.prd.write_text(self.prd.read_text() + '\n#### AC-002 边界\n无记录时展示空状态。\n')
        with self.assertRaises(RuntimeError):
            adopt(self.request())
        self.assertEqual(state.read_bytes(), before)
        self.assertEqual(len(list(state.parent.glob('*.json'))), 1)

    def test_blocked_work_item_and_verifier_progress_are_preserved(self):
        from product_handoff import adopt
        request = self.request()
        first = adopt(request)
        state = Path(first['native_result']['path'])
        record = json.loads(state.read_text())
        record.update(status='blocked', revision=3)
        state.write_text(json.dumps(record))
        before = state.read_bytes()
        self.assertEqual(adopt(request)['native_result']['status'], 'resumed')
        self.assertEqual(state.read_bytes(), before)

    def test_change_between_preparation_and_native_write_is_rejected(self):
        from product_handoff import adopt
        request = self.request()
        run = subprocess.run
        def changed(*args, **kwargs):
            self.prd.write_text(self.prd.read_text() + '\nChanged during invocation\n')
            return run(*args, **kwargs)
        with patch('product_handoff.prepare', return_value=request), patch('product_handoff.subprocess.run', side_effect=changed):
            with self.assertRaises((ValueError, RuntimeError)):
                adopt(request)
        self.assertEqual(list(self.state_root.rglob('*.json')), [])

    def test_provider_changed_before_subprocess_does_not_execute_or_write(self):
        from product_handoff import prepare, adopt
        provider = self.root / 'provider copy'
        source = self.provider()
        for name in ('scripts', 'providers', 'references'):
            shutil.copytree(source / name, provider / name,
                            ignore=shutil.ignore_patterns('__pycache__', '.bundle'))
        request = prepare(self.prd, provider, self.project, 'REQ-001', self.state_root)
        run = subprocess.run
        marker = self.root / 'provider-executed'
        def changed(*args, **kwargs):
            module = provider / 'scripts/work_item.py'
            module.write_text(module.read_text() + '\nPath(' + repr(str(marker)) + ').write_text("executed")\n')
            return run(*args, **kwargs)
        with patch('product_handoff.prepare', return_value=request), patch('product_handoff.subprocess.run', side_effect=changed):
            with self.assertRaises((ValueError, RuntimeError)):
                adopt(request)
        self.assertFalse(marker.exists())
        self.assertEqual(list(self.state_root.rglob('*.json')), [])

    def test_null_reference_in_apparently_successful_native_result_is_rejected(self):
        from product_handoff import adopt
        request = self.request()
        first = adopt(request)
        native = first['native_result']
        state = Path(native['path'])
        native['work_item']['reference_receipt'] = None
        state.write_text(json.dumps(native['work_item']))
        with patch('product_handoff.prepare', return_value=request), patch('product_handoff.subprocess.run',
                return_value=subprocess.CompletedProcess([], 0, json.dumps(native), '')):
            with self.assertRaises(ValueError):
                adopt(request)

    def test_state_root_cannot_be_in_tested_source(self):
        from product_handoff import prepare
        with self.assertRaises(ValueError):
            prepare(self.prd, self.provider(), self.project, 'REQ-001', self.project / 'runtime-state')
        self.assertFalse((self.project / 'runtime-state').exists())

    def test_actual_git_metadata_is_a_valid_state_root(self):
        from product_handoff import prepare, adopt
        metadata = subprocess.check_output(['git', '-C', str(self.project), 'rev-parse', '--absolute-git-dir'], text=True).strip()
        request = prepare(self.prd, self.provider(), self.project, 'REQ-001', Path(metadata) / 'continuation')
        first = adopt(request)
        self.assertTrue(first['adopted'])
        self.assertEqual(adopt(request)['native_result']['status'], 'resumed')

    def test_existing_native_subset_cannot_be_duplicated_as_a_full_scope_item(self):
        from product_handoff import adopt
        self.prd.write_text(self.prd.read_text() + '\n#### AC-002 无记录\n无记录时展示空状态。\n')
        request = self.request()
        code = """import json,sys
sys.path.insert(0,sys.argv[1])
from reference_receipt import freeze_receipt
from work_item import resume_or_create
r=json.load(sys.stdin)
ref=freeze_receipt([{'reference':r['prd'],'status':'read','content_fingerprint':r['prd_sha256']}])
result=resume_or_create(state_root=r['state_root'],workspace=r['project'],baseline=r['baseline'],target=r['target'],requirements=r['requirements'],acceptance=r['acceptance'][:1],decisions=['PRD version: '+r['product_version']],reference_receipt=ref,continuation=True)
print(json.dumps(result))
"""
        native = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(self.provider() / 'scripts')],
                                input=json.dumps(request), capture_output=True, text=True)
        self.assertEqual(native.returncode, 0, native.stderr)
        state = Path(json.loads(native.stdout)['path'])
        before = state.read_bytes()
        with self.assertRaises(RuntimeError):
            adopt(request)
        self.assertEqual(state.read_bytes(), before)
        self.assertEqual(len(list(state.parent.glob('*.json'))), 1)

    def test_attachment_bytes_are_native_references_and_cannot_drift(self):
        from product_handoff import adopt
        extra = self.root / 'rules.txt';extra.write_text('附加规则')
        self.prd.write_text(self.prd.read_text().replace('用户已明确仅展示当前状态。', '[规则](rules.txt)'))
        request = self.request()
        self.assertIn('input_snapshot', request)
        result = adopt(request)
        state = Path(result['native_result']['path'])
        refs = json.loads(state.read_text())['reference_receipt']['references']
        self.assertEqual({ref['reference'] for ref in refs}, {str(self.prd), str(extra)})
        before = state.read_bytes();extra.write_text('新规则')
        with self.assertRaises(ValueError):
            adopt(request)
        self.assertEqual(state.read_bytes(), before)

    def revision_fixture(self, *, lifecycle=True):
        from product_handoff import adopt, prepare
        from product_revision import plan_revision
        previous=adopt(self.request())
        self.prd.write_text(self.prd.read_text().replace('产品版本：v1','产品版本：v2').replace('产品版本 v1','产品版本 v2')
                            .replace('显示当前状态。','显示状态和更新时间。')+'\n#### AC-002 无记录\n没有记录时显示空状态。\n')
        current=prepare(self.prd,self.provider(),self.project,'REQ-001',self.state_root)
        record_path=None;bindings=None
        if lifecycle:
            from test_lifecycle_record import record
            record_path=self.root/'lifecycle.json';record_path.write_text(json.dumps(record()))
            bindings={'FR-001':['requirement']}
        report=plan_revision(previous['input_snapshot'],current['input_snapshot'],record_path=record_path,bindings=bindings)
        return previous,current,report

    def test_explicit_revision_updates_the_existing_item_and_lifecycle_once(self):
        from product_handoff import adopt,prepare_revision
        previous,current,report=self.revision_fixture()
        prepared=prepare_revision(previous,current,report)
        path=Path(previous['native_result']['path']);before=path.read_bytes()
        self.assertEqual(path.read_bytes(),before)
        result=adopt(prepared)
        self.assertEqual(result['native_result']['path'],str(path))
        self.assertEqual(result['native_result']['status'],'revised')
        self.assertEqual(result['native_result']['work_item']['acceptance'],['AC-001','AC-002'])
        self.assertEqual(result['impact_result']['status'],'applied')
        state=path.read_bytes();record=Path(report['record_path']).read_bytes()
        self.assertEqual(adopt(prepared)['native_result']['status'],'resumed')
        self.assertEqual(path.read_bytes(),state)
        self.assertEqual(Path(report['record_path']).read_bytes(),record)
        self.assertEqual(len(list(path.parent.glob('*.json'))),1)

    def test_explicit_handoff_revision_preserves_supported_legacy_native_state(self):
        from product_handoff import adopt,prepare_revision
        previous,current,report=self.revision_fixture(lifecycle=False)
        path=Path(previous['native_result']['path']);legacy=json.loads(path.read_text())
        legacy.pop('verifier_successes');legacy.pop('alignment_scope_fingerprint');path.write_text(json.dumps(legacy))
        request=prepare_revision(previous,current,report);result=adopt(request)
        self.assertEqual(result['native_result']['path'],str(path))
        self.assertEqual(result['native_result']['status'],'revised')
        self.assertEqual(json.loads(Path(result['native_result']['history']).read_text())['previous'],legacy)
        self.assertEqual(adopt(request)['native_result']['status'],'resumed')

    def test_legacy_prepared_request_has_actionable_error_and_never_writes(self):
        from product_handoff import adopt
        request=self.request();request.pop('input_snapshot')
        with self.assertRaisesRegex(ValueError,'legacy|prepare again'):
            adopt(request)
        self.assertFalse(self.state_root.exists())

    def test_failed_native_revision_leaves_conservative_impact_and_same_request_can_resume(self):
        from product_handoff import adopt,prepare_revision
        previous,current,report=self.revision_fixture();prepared=prepare_revision(previous,current,report)
        path=Path(previous['native_result']['path']);before=path.read_bytes()
        with patch('product_handoff.prepare',return_value=current), \
                patch('product_handoff.provider_capabilities', return_value={'ready': True}), \
                patch('product_handoff.subprocess.run',
                return_value=subprocess.CompletedProcess([],1,'','simulated interruption')):
            with self.assertRaises(RuntimeError):adopt(prepared)
        self.assertEqual(path.read_bytes(),before)
        record=json.loads(Path(report['record_path']).read_text())
        self.assertEqual(record['revision'],2)
        self.assertEqual(next(n for n in record['artifacts'] if n['id']=='test')['status'],'pending_confirmation')
        self.assertEqual(adopt(prepared)['native_result']['status'],'revised')
        self.assertEqual(json.loads(Path(report['record_path']).read_text())['revision'],2)

    def test_lifecycle_conflict_never_starts_native_revision(self):
        from product_handoff import adopt,prepare_revision
        previous,current,report=self.revision_fixture();prepared=prepare_revision(previous,current,report)
        path=Path(previous['native_result']['path']);before=path.read_bytes()
        record=json.loads(Path(report['record_path']).read_text());record['revision']=2
        Path(report['record_path']).write_text(json.dumps(record))
        with patch('product_handoff.prepare',return_value=current), \
                patch('product_handoff.provider_capabilities', return_value={'ready': True}), \
                patch('product_handoff.subprocess.run') as run:
            with self.assertRaises(ValueError):adopt(prepared)
            run.assert_not_called()
        self.assertEqual(path.read_bytes(),before)

    def test_revision_requires_new_version_matching_inputs_and_original_target(self):
        from product_handoff import prepare_revision
        previous,current,report=self.revision_fixture(lifecycle=False)
        self.assertEqual(prepare_revision(previous,current,report)['revision']['path'],previous['native_result']['path'])
        for key,value in (('target','REQ-OTHER'),('baseline','b'*40),('project',str(self.root))):
            with self.subTest(key=key),self.assertRaises(ValueError):
                prepare_revision(previous,{**current,key:value},report)
        with self.assertRaises(ValueError):prepare_revision(previous,current,{**report,'affected_requirements':[]})
        self.prd.write_text(self.prd.read_text().replace('产品版本：v2','产品版本：v1').replace('产品版本 v2','产品版本 v1'))
        from product_handoff import prepare
        from product_revision import plan_revision
        same_version=prepare(self.prd,self.provider(),self.project,'REQ-001',self.state_root)
        report=plan_revision(previous['input_snapshot'],same_version['input_snapshot'])
        with self.assertRaises(ValueError):prepare_revision(previous,same_version,report)

    def test_cas_conflict_after_preparation_preserves_actual_state(self):
        from product_handoff import adopt,prepare_revision
        previous,current,report=self.revision_fixture(lifecycle=False)
        request=prepare_revision(previous,current,report);path=Path(previous['native_result']['path'])
        actual=json.loads(path.read_text());actual['revision']+=1;path.write_text(json.dumps(actual));before=path.read_bytes()
        with self.assertRaises(RuntimeError):adopt(request)
        self.assertEqual(path.read_bytes(),before)

    def test_cli_saved_revision_request_recovers_without_repreparing_old_state(self):
        previous,current,report=self.revision_fixture(lifecycle=False)
        previous_file=self.root/'previous.json';report_file=self.root/'impact.json'
        previous_file.write_text(json.dumps(previous));report_file.write_text(json.dumps(report))
        prepared=self.call('--previous-handoff',str(previous_file),'--impact-report',str(report_file))
        self.assertEqual(prepared.returncode,0,prepared.stderr+prepared.stdout)
        value=json.loads(prepared.stdout);request_file=self.root/'request.json';request_file.write_text(prepared.stdout)
        command=[sys.executable,str(ROOT/'scripts/product_handoff.py'),'--prepared',str(request_file),'--adopt',
                 '--expected-contract',value['contract_fingerprint']]
        first=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(first.returncode,0,first.stderr+first.stdout)
        second=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(second.returncode,0,second.stderr+second.stdout)
        self.assertEqual(json.loads(second.stdout)['native_result']['status'],'resumed')

    def test_old_prepared_adoption_cannot_create_a_duplicate_after_explicit_revision(self):
        from product_handoff import adopt,prepare_revision
        previous,current,report=self.revision_fixture(lifecycle=False)
        result=adopt(prepare_revision(previous,current,report));path=Path(result['native_result']['path'])
        self.prd.write_text(previous['input_snapshot']['documents'][str(self.prd)])
        with self.assertRaises((ValueError,RuntimeError)):
            adopt(self.request())
        self.assertEqual(len(list(path.parent.glob('*.json'))),1)

    def test_real_revision_red_green_evidence_and_completion_share_one_item(self):
        from product_handoff import adopt,prepare,prepare_revision
        from product_revision import plan_revision
        from provider_test_evidence import check
        code=self.project/'app.py';tests=self.project/'test_cases.py'
        code.write_text('def total(values):\n return sum(values)\n')
        tests.write_text('import unittest\nfrom app import total\nclass Case(unittest.TestCase):\n'
                         ' def test_normal(self): self.assertEqual(total([1,2]),3)\n'
                         ' def test_empty(self): self.assertEqual(total([]),0)\n'
                         ' def test_invalid(self):\n  with self.assertRaises(TypeError): total(None)\n')
        self.prd.write_text(self.prd.read_text().replace('仅展示当前状态','提供合计功能').replace('查看状态','计算合计')
                            .replace('正常展示','正常、空集合和非法输入').replace('给定有效记录，打开详情时显示当前状态。','给定整数集合返回合计，空集合返回0，非可迭代输入拒绝。'))
        extra=self.root/'rules.txt';extra.write_text('整数集合合计。')
        self.prd.write_text(self.prd.read_text()+'\n[输入规则](rules.txt)\n')
        previous=adopt(self.request());state=Path(previous['native_result']['path'])
        runner=self.provider()/'scripts/work_item.py'
        def verify(selector='test_cases.Case'):
            command=[sys.executable,str(runner),'verify','--state',str(state),'--workspace',str(self.project),
                     '--baseline',previous['baseline'],'--argv-json',json.dumps([sys.executable,'-m','unittest',selector])]
            result=subprocess.run(command,capture_output=True,text=True,timeout=30)
            return result.returncode,json.loads(result.stdout)
        def mapping(handoff,receipts):
            return {'prd':{'path':str(self.prd),'version':handoff['product_version'],'sha256':handoff['prd_sha256']},
                    'inputs':handoff['input_snapshot'],'acceptance':receipts}
        status,old=verify();self.assertEqual(status,0,old)
        old_file=self.root/'old-test.json';old_file.write_text(json.dumps(old['receipt']))
        old_map=mapping(previous,{'AC-001':[{'receipt':str(old_file),'selector':'test_cases.Case'}]})
        self.assertTrue(check(self.prd,old_map,self.provider(),self.project,previous['baseline'])['ready'])
        self.prd.write_text(self.prd.read_text().replace('产品版本：v1','产品版本：v2').replace('产品版本 v1','产品版本 v2')
                            +'\n#### AC-002 负数拒绝\n给定包含负数的集合，返回明确参数错误。\n')
        extra.write_text('整数集合合计；负数参数必须拒绝。')
        tests.write_text(tests.read_text()+' def test_negative(self):\n  with self.assertRaises(ValueError): total([-1])\n')
        current=prepare(self.prd,self.provider(),self.project,'REQ-001',self.state_root)
        from test_lifecycle_record import record
        record_path=self.root/'lifecycle.json';record_path.write_text(json.dumps(record()))
        impact=plan_revision(previous['input_snapshot'],current['input_snapshot'],record_path=record_path,bindings={'FR-001':['requirement']})
        prepared=prepare_revision(previous,current,impact);result=adopt(prepared)
        self.assertEqual(result['native_result']['path'],str(state))
        self.assertEqual(adopt(prepared)['native_result']['status'],'resumed')
        self.assertFalse(check(self.prd,old_map,self.provider(),self.project,previous['baseline'])['ready'])
        status,red=verify();self.assertEqual(status,2,red);self.assertEqual(red['receipt']['test_check']['failed'],1)
        status,blocked=verify();self.assertEqual(blocked['reason'],'identical_verifier_failure');self.assertEqual(status,2)
        code.write_text('def total(values):\n if any(value<0 for value in values): raise ValueError("negative")\n return sum(values)\n')
        status,green=verify();self.assertEqual(status,0,green)
        status,negative=verify('test_cases.Case.test_negative');self.assertEqual(status,0,negative)
        green_file=self.root/'green.json';green_file.write_text(json.dumps(green['receipt']))
        negative_file=self.root/'negative.json';negative_file.write_text(json.dumps(negative['receipt']))
        links=mapping(current,{'AC-001':[{'receipt':str(green_file),'selector':'test_cases.Case'}],
                               'AC-002':[{'receipt':str(negative_file),'selector':'test_cases.Case.test_negative'}]})
        self.assertTrue(check(self.prd,links,self.provider(),self.project,previous['baseline'])['ready'])
        complete=subprocess.run([sys.executable,str(runner),'complete','--state',str(state),'--workspace',str(self.project),
            '--baseline',previous['baseline'],'--receipt',str(green_file)],capture_output=True,text=True,timeout=30)
        self.assertEqual(complete.returncode,0,complete.stderr+complete.stdout)
        self.assertFalse(state.exists());self.assertTrue(Path(result['native_result']['history']).exists())
        with self.assertRaises(RuntimeError):adopt(prepared)
        self.assertFalse(state.exists())

    def test_split_tracking_is_explicit_and_cli_freezes_both_documents(self):
        content=self.prd.read_text();trace=self.root/'trace.md'
        trace.write_text('## 验收追踪\n> 追踪版本：v1\n## 来源'+content.split('## 来源',1)[1])
        self.prd.write_text(content.split('## 来源',1)[0]+'[追踪](trace.md)\n')
        prepared=self.call('--tracking',str(trace))
        self.assertEqual(prepared.returncode,0,prepared.stderr+prepared.stdout)
        request=json.loads(prepared.stdout)
        result=self.call('--tracking',str(trace),'--adopt','--expected-contract',request['contract_fingerprint'])
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        refs=json.loads(result.stdout)['native_result']['work_item']['reference_receipt']['references']
        self.assertEqual({ref['reference'] for ref in refs},{str(self.prd),str(trace)})

    def test_cli_remote_snapshot_paths_resolve_from_mapping_file_and_reject_mixed_inputs(self):
        self.prd.write_text(self.prd.read_text().replace('用户已明确仅展示当前状态。','[访谈](https://example.invalid/interview)'))
        sources=self.root/'sources';sources.mkdir();fact=sources/'interview.txt';fact.write_text('已提供的访谈快照')
        mapping=sources/'attachments.json';mapping.write_text(json.dumps({'https://example.invalid/interview':'interview.txt'}))
        result=self.call('--attachments',str(mapping))
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        value=json.loads(result.stdout)
        self.assertIn(str(fact),{item['path'] for item in value['input_snapshot']['files']})
        prepared=self.root/'prepared.json';prepared.write_text(result.stdout)
        mixed=self.call('--prepared',str(prepared))
        self.assertEqual(mixed.returncode,1);self.assertIn('combined',json.loads(mixed.stdout)['error'])
        mapping.write_text('[]')
        bad=self.call('--attachments',str(mapping))
        self.assertEqual(bad.returncode,1);self.assertFalse(json.loads(bad.stdout)['adopted'])

    def test_attachment_change_after_prepare_before_native_write_is_rejected(self):
        from product_handoff import adopt
        extra=self.root/'fact.txt';extra.write_text('fact')
        self.prd.write_text(self.prd.read_text()+'\n[资料](fact.txt)\n')
        request=self.request();run=subprocess.run
        def changed(*args,**kwargs):
            extra.write_text('changed')
            return run(*args,**kwargs)
        with patch('product_handoff.prepare',return_value=request),patch('product_handoff.subprocess.run',side_effect=changed):
            with self.assertRaises((ValueError,RuntimeError)):
                adopt(request)
        self.assertEqual(list(self.state_root.rglob('*.json')),[])

    def test_same_bytes_symlink_change_before_native_write_is_rejected_without_item(self):
        from product_handoff import adopt
        request=self.request();run=subprocess.run;replacement=self.root/'same-bytes.md'
        def changed(*args,**kwargs):
            self.prd.rename(replacement);self.prd.symlink_to(replacement)
            return run(*args,**kwargs)
        with patch('product_handoff.prepare',return_value=request),patch('product_handoff.subprocess.run',side_effect=changed):
            with self.assertRaises((ValueError,RuntimeError)):adopt(request)
        self.assertEqual(list(self.state_root.rglob('*.json')),[])

    def test_cli_requires_prepared_contract_and_rejects_changes_between_calls(self):
        prepared = json.loads(self.call().stdout)
        result = self.call('--adopt')
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.state_root.exists())
        result = self.call('--adopt', '--target', 'OTHER', '--expected-contract', prepared['contract_fingerprint'])
        self.assertEqual(result.returncode, 1)
        self.prd.write_text(self.prd.read_text() + '\nChanged after inspection\n')
        result = self.call('--adopt', '--expected-contract', prepared['contract_fingerprint'])
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['adopted'])
        self.assertFalse(self.state_root.exists())

    def test_native_writer_between_handoff_check_and_create_cannot_duplicate_target(self):
        from product_handoff import prepare, adopt
        provider = self.root / 'racing provider'
        for name in ('scripts', 'providers', 'references'):
            shutil.copytree(self.provider() / name, provider / name,
                            ignore=shutil.ignore_patterns('__pycache__', '.bundle'))
        module = provider / 'scripts/work_item.py'
        module.write_text(module.read_text() + '\n_native_resume = resume_or_create\n'
            'def resume_or_create(**arguments):\n'
            '    competing = dict(arguments)\n'
            '    competing.pop("exclusive_target", None)\n'
            '    competing.update(requirements=["FR-OTHER"], acceptance=["AC-OTHER"])\n'
            '    _native_resume(**competing)\n'
            '    return _native_resume(**arguments)\n')
        request = prepare(self.prd, provider, self.project, 'REQ-001', self.state_root)
        with self.assertRaises((ValueError, RuntimeError)):
            adopt(request)
        records = list(self.state_root.rglob('*.json'))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())['requirements'], ['FR-OTHER'])

    def test_cli_failure_is_structured(self):
        result = self.call('--target', '../escape', '--adopt')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)['adopted'])


if __name__ == '__main__':
    unittest.main()
