"""Check external test evidence without inventing native execution receipts. 作者：Jeff.Liu"""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_product_handoff as handoff_fixture


class ProductEvidenceTests(unittest.TestCase):
    def test_provider_evidence_fingerprint_ignores_tests_but_binds_runtime(self):
        from provider_test_evidence import verification_code_fingerprint
        scripts = self.upstream / 'scripts'
        scripts.mkdir()
        runtime = scripts / 'evidence_contract.py'
        runtime.write_text('# Runtime\n')
        before = verification_code_fingerprint(self.upstream)
        (scripts / 'test_evidence_contract.py').write_text('# New test\n')
        self.assertEqual(verification_code_fingerprint(self.upstream), before)
        runtime.write_text('# Changed runtime\n')
        self.assertNotEqual(verification_code_fingerprint(self.upstream), before)

    def setUp(self):
        handoff_fixture.ProductHandoffTests.setUp(self)
        self.receipt = self.root / 'test.observed.json'
        self.receipt.write_text(json.dumps({'source': {'source_fingerprint': 'a' * 64}}))
        self.links = {'AC-001': [{'receipt': str(self.receipt), 'selector': 'tests.Case.test_ok'}]}
        self.binding = {'path': str(self.prd), 'version': 'v1', 'sha256': hashlib.sha256(self.prd.read_bytes()).hexdigest()}

    def bound(self, links):
        return {'prd': dict(self.binding), 'acceptance': links}

    def test_failed_missing_or_skipped_evidence_cannot_cover_acceptance(self):
        from provider_test_evidence import check
        for error in ('failed tests', 'skipped required test', 'stale source'):
            with patch('provider_test_evidence.verify_receipt', side_effect=ValueError(error)):
                result = check(self.prd, self.bound(self.links), self.upstream, self.project, 'HEAD')
            self.assertFalse(result['ready'])
            self.assertIn(error, str(result['gaps']))

    def test_mapping_pass_preserves_business_and_tdd_boundaries(self):
        from provider_test_evidence import check
        with patch('provider_test_evidence.verify_receipt', return_value={'passed': 1}):
            result = check(self.prd, self.bound(self.links), self.upstream, self.project, 'HEAD')
        self.assertTrue(result['ready'], result)
        self.assertFalse(result['business_authorization'])
        self.assertFalse(result['tdd_verified'])
        self.assertEqual(result['coverage'], {'AC-001': ['tests.Case.test_ok']})

    def test_attachment_mapping_requires_full_input_identity_and_cannot_relabel_old_bytes(self):
        from product_inputs import freeze_inputs
        from provider_test_evidence import check
        extra=self.root/'fact.txt';extra.write_text('actual fact')
        self.prd.write_text(self.prd.read_text()+'\n[资料](fact.txt)\n')
        self.binding['sha256']=hashlib.sha256(self.prd.read_bytes()).hexdigest()
        frozen=self.bound(self.links);frozen['inputs']=freeze_inputs(self.prd)
        with patch('provider_test_evidence.verify_receipt',return_value={'passed':1}):
            self.assertFalse(check(self.prd,self.bound(self.links),self.upstream,self.project,'HEAD')['ready'])
            self.assertTrue(check(self.prd,frozen,self.upstream,self.project,'HEAD')['ready'])
            extra.write_text('changed fact')
            self.assertFalse(check(self.prd,frozen,self.upstream,self.project,'HEAD')['ready'])

    def test_attachment_drift_during_evidence_check_prevents_ready(self):
        from product_inputs import freeze_inputs
        from provider_test_evidence import check
        extra=self.root/'fact.txt';extra.write_text('fact')
        self.prd.write_text(self.prd.read_text()+'\n[资料](fact.txt)\n')
        self.binding['sha256']=hashlib.sha256(self.prd.read_bytes()).hexdigest()
        frozen=self.bound(self.links);frozen['inputs']=freeze_inputs(self.prd)
        def changed(*args):
            extra.write_text('changed');return {'passed':1}
        with patch('provider_test_evidence.verify_receipt',side_effect=changed):
            result=check(self.prd,frozen,self.upstream,self.project,'HEAD')
        self.assertFalse(result['ready']);self.assertIn('changed',str(result['gaps']))

    def test_unknown_or_missing_acceptance_and_empty_test_list_are_not_green(self):
        from provider_test_evidence import check
        for mapping in ({}, {'AC-999': self.links['AC-001']}, {'AC-001': []}):
            with self.subTest(mapping=mapping), patch('provider_test_evidence.verify_receipt', return_value={}):
                self.assertFalse(check(self.prd, self.bound(mapping), self.upstream, self.project, 'HEAD')['ready'])

    def test_invalid_documents_entries_and_unavailable_provider_remain_gaps(self):
        from provider_test_evidence import check
        for entry in ({}, {'receipt': str(self.receipt), 'selector': ''},
                      {'receipt': str(self.root / 'missing'), 'selector': 'tests.Case.test_ok'}):
            result = check(self.prd, self.bound({'AC-001': [entry]}), self.upstream, self.project, 'HEAD')
            self.assertFalse(result['ready'])
        self.assertFalse(check(self.prd, self.bound(self.links), self.upstream, self.project, 'HEAD')['ready'])
        self.prd.write_text('# No requirements\n')
        self.assertFalse(check(self.prd, self.bound(self.links), self.upstream, self.project, 'HEAD')['valid'])

    def test_changed_prd_and_duplicate_mapping_cannot_pass(self):
        from provider_test_evidence import check
        with patch('provider_test_evidence.verify_receipt', return_value={}):
            result = check(self.prd, self.bound({'AC-001': self.links['AC-001'] * 2}), self.upstream, self.project, 'HEAD')
        self.assertFalse(result['ready'])
        def changed(*args):
            self.prd.write_text(self.prd.read_text() + '\nChanged\n')
            return {}
        with patch('provider_test_evidence.verify_receipt', side_effect=changed):
            self.assertFalse(check(self.prd, self.bound(self.links), self.upstream, self.project, 'HEAD')['valid'])

    def test_mapping_without_a_frozen_prd_input_is_not_ready(self):
        from provider_test_evidence import check
        with patch('provider_test_evidence.verify_receipt', return_value={'passed': 1}) as verify:
            result = check(self.prd, self.links, self.upstream, self.project, 'HEAD')
        self.assertFalse(result['ready'])
        verify.assert_not_called()

    def test_old_mapping_cannot_be_relabelled_as_a_new_prd_version(self):
        from provider_test_evidence import check
        frozen = self.bound(self.links)
        with patch('provider_test_evidence.verify_receipt', return_value={'passed': 1}):
            self.assertTrue(check(self.prd, frozen, self.upstream, self.project, 'HEAD')['ready'])
            self.prd.write_text(self.prd.read_text().replace('产品版本：v1', '产品版本：v2').replace('产品版本 v1', '产品版本 v2'))
            self.assertFalse(check(self.prd, frozen, self.upstream, self.project, 'HEAD')['ready'])
            frozen['prd'].update(version='v2', sha256=hashlib.sha256(self.prd.read_bytes()).hexdigest())
            self.assertTrue(check(self.prd, frozen, self.upstream, self.project, 'HEAD')['ready'])
            self.prd.write_text(self.prd.read_text() + '\nChanged rule with the same IDs\n')
            self.assertFalse(check(self.prd, frozen, self.upstream, self.project, 'HEAD')['ready'])

    def test_draft_with_current_mapping_is_not_formal_evidence_ready(self):
        from provider_test_evidence import check
        self.prd.write_text(self.prd.read_text().replace('已确认', '草稿'))
        frozen = self.bound(self.links)
        frozen['prd']['sha256'] = hashlib.sha256(self.prd.read_bytes()).hexdigest()
        with patch('provider_test_evidence.verify_receipt', return_value={'passed': 1}) as verify:
            self.assertFalse(check(self.prd, frozen, self.upstream, self.project, 'HEAD')['ready'])
        verify.assert_not_called()

    def test_provider_process_failure_without_stderr_is_reported(self):
        from provider_test_evidence import verify_receipt
        scripts = self.upstream / 'scripts'
        scripts.mkdir()
        for name in ('evidence_contract.py', 'tdd_impact_guard.py'):
            (scripts / name).write_text('# Fixture\n')
        with patch('provider_test_evidence.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', '')):
            with self.assertRaisesRegex(ValueError, 'exit 1'):
                verify_receipt({}, 'tests.Case.test_ok', self.upstream, self.project, 'HEAD')

    def test_mixed_source_receipts_cannot_jointly_cover_acceptance(self):
        from provider_test_evidence import check
        other = self.root / 'other.json'
        other.write_text(json.dumps({'source': {'source_fingerprint': 'b' * 64}}))
        links = {'AC-001': [*self.links['AC-001'], {'receipt': str(other), 'selector': 'tests.Case.test_other'}]}
        with patch('provider_test_evidence.verify_receipt', return_value={'passed': 1}):
            result = check(self.prd, self.bound(links), self.upstream, self.project, 'HEAD')
        self.assertFalse(result['ready'], result)
        self.assertIn('same project source', str(result['gaps']))

    def test_source_is_rechecked_before_ready_and_final_verifier_errors_are_gaps(self):
        from provider_test_evidence import check
        for error in (ValueError('source changed after first verification'),
                      subprocess.TimeoutExpired(['provider'], 30)):
            with self.subTest(error=error), patch('provider_test_evidence.verify_receipt',
                    side_effect=[{'passed': 1}, error]) as verify:
                result = check(self.prd, self.bound(self.links), self.upstream, self.project, 'HEAD')
            self.assertFalse(result['ready'], result)
            self.assertEqual(verify.call_count, 2)
            self.assertTrue(result['gaps'])

    def test_provider_change_during_verification_cannot_report_ready(self):
        from provider_test_evidence import check
        scripts = self.upstream / 'scripts'
        scripts.mkdir()
        for name in ('evidence_contract.py', 'tdd_impact_guard.py'):
            (scripts / name).write_text('# provider A\n')
        def changed(*args, **kwargs):
            (scripts / 'tdd_impact_guard.py').write_text('# provider B\n')
            return subprocess.CompletedProcess([], 0, '{"passed": 1}', '')
        with patch('provider_test_evidence.subprocess.run', side_effect=changed):
            result = check(self.prd, self.bound(self.links), self.upstream, self.project, 'HEAD')
        self.assertFalse(result['ready'], result)
        self.assertIn('provider changed', str(result['gaps']))

    def test_provider_update_between_acceptance_receipts_is_rejected(self):
        from provider_test_evidence import check
        scripts = self.upstream / 'scripts'
        scripts.mkdir()
        for name in ('evidence_contract.py', 'tdd_impact_guard.py'):
            (scripts / name).write_text('# provider A\n')
        second = self.root / 'second.json'
        second.write_bytes(self.receipt.read_bytes())
        links = {'AC-001': [*self.links['AC-001'], {'receipt': str(second), 'selector': 'tests.Case.test_other'}]}
        read = Path.read_text
        def read_then_update(path, *args, **kwargs):
            if path == second:
                (scripts / 'evidence_contract.py').write_text('# provider B\n')
            return read(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read_then_update), patch('provider_test_evidence.subprocess.run',
                return_value=subprocess.CompletedProcess([], 0, '{"passed": 1}', '')) as verify:
            result = check(self.prd, self.bound(links), self.upstream, self.project, 'HEAD')
        self.assertFalse(result['ready'], result)
        self.assertIn('provider changed', str(result['gaps']))
        self.assertEqual(verify.call_count, 1)

    def test_cli_invalid_mapping_returns_structured_failure(self):
        mapping = self.root / 'mapping.json'
        mapping.write_text('{invalid')
        result = subprocess.run([sys.executable, str(Path(__file__).parent / 'provider_test_evidence.py'),
            '--prd', str(self.prd), '--mapping', str(mapping), '--provider-root', str(self.upstream),
            '--workspace', str(self.project), '--baseline', 'HEAD'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['ready'])

    def test_real_converge_receipt_checks_current_source_and_selector(self):
        provider = os.environ.get('PROJECT_DOCS_CONVERGE_TEST_ROOT')
        if not provider:
            self.skipTest('real provider integration requires PROJECT_DOCS_CONVERGE_TEST_ROOT')
        from provider_test_evidence import check
        (self.project / 'test_cases.py').write_text('import unittest\nclass Tests(unittest.TestCase):\n def test_ok(self):\n  self.assertEqual(3, 3)\n')
        for argv in (['git', 'init', '-q'], ['git', 'add', 'test_cases.py'],
                     ['git', '-c', 'user.name=test', '-c', 'user.email=test@example.invalid',
                      '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture']):
            subprocess.run(argv, cwd=self.project, check=True, capture_output=True)
        result = subprocess.run([sys.executable, str(Path(provider) / 'scripts/evidence_contract.py'), 'run',
            '--workspace', str(self.project), '--baseline', 'HEAD', '--', sys.executable, '-m', 'unittest',
            'test_cases.Tests.test_ok'], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.receipt.write_text(result.stdout)
        mapping = {'AC-001': [{'receipt': str(self.receipt), 'selector': 'test_cases.Tests.test_ok'}]}
        self.assertTrue(check(self.prd, self.bound(mapping), Path(provider), self.project, 'HEAD')['ready'])
        mapping_path = self.root / 'mapping.json'
        cli_mapping = self.bound({'AC-001': [{'receipt': self.receipt.name, 'selector': 'test_cases.Tests.test_ok'}]})
        cli_mapping['prd']['path'] = self.prd.name
        mapping_path.write_text(json.dumps(cli_mapping))
        cli = subprocess.run([sys.executable, str(Path(__file__).parent / 'provider_test_evidence.py'),
            '--prd', str(self.prd), '--mapping', str(mapping_path), '--provider-root', provider,
            '--workspace', str(self.project), '--baseline', 'HEAD'], capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertFalse(json.loads(cli.stdout)['tdd_verified'])
        # Schedule a real source change between successful receipt checks.
        from provider_test_evidence import verify_receipt
        source = self.project / 'test_cases.py'
        original = source.read_bytes()
        changed = original + b' def test_other(self):\n  self.assertEqual(4, 4)\n'
        source.write_bytes(changed)
        second = subprocess.run([sys.executable, str(Path(provider) / 'scripts/evidence_contract.py'), 'run',
            '--workspace', str(self.project), '--baseline', 'HEAD', '--', sys.executable, '-m', 'unittest',
            'test_cases.Tests.test_other'], capture_output=True, text=True, timeout=30)
        self.assertEqual(second.returncode, 0, second.stderr)
        other = self.root / 'second.observed.json'
        other.write_text(second.stdout)
        source.write_bytes(original)
        def verify_then_change(*args):
            value = verify_receipt(*args)
            source.write_bytes(changed)
            return value
        mixed = {'AC-001': [*mapping['AC-001'], {'receipt': str(other), 'selector': 'test_cases.Tests.test_other'}]}
        with patch('provider_test_evidence.verify_receipt', side_effect=verify_then_change):
            self.assertFalse(check(self.prd, self.bound(mixed), Path(provider), self.project, 'HEAD')['ready'])
        source.write_bytes(original)
        with patch('provider_test_evidence.verify_receipt', side_effect=verify_then_change):
            self.assertFalse(check(self.prd, self.bound(mapping), Path(provider), self.project, 'HEAD')['ready'])
        source.write_bytes(original)
        mapping['AC-001'][0]['selector'] = 'test_cases.Tests.other'
        self.assertFalse(check(self.prd, self.bound(mapping), Path(provider), self.project, 'HEAD')['ready'])
        mapping['AC-001'][0]['selector'] = 'test_cases.Tests.test_ok'
        (self.project / 'test_cases.py').write_text('# Changed\n')
        self.assertFalse(check(self.prd, self.bound(mapping), Path(provider), self.project, 'HEAD')['ready'])
