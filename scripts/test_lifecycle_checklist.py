"""Detailed checklist provenance, applicability and execution mapping. 作者：Jeff.Liu"""
import copy
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lifecycle_quality import STAGE_CHECKS, check_quality, check_handoff, reference
from test_lifecycle_quality import scenario, handoff

ROOT = Path(__file__).resolve().parents[1]


class DetailedChecklistTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.quality, self.trace = scenario(self.root)

    def catalog(self, stage=None):
        self.assertIsNotNone(importlib.util.find_spec('lifecycle_checklist'), 'detailed checklist loader is missing')
        import lifecycle_checklist
        return lifecycle_checklist.load_catalog(stage)

    def project_scope(self, filename='formal.md'):
        from product_inputs import freeze_inputs
        (self.root / 'scope.md').write_text('Preserve original request identifiers.')
        definition = {'id': 'PROJECT-KEEP-ID', 'stage': 'L3', 'check': 'acceptance',
                      'required': True, 'method': 'review', 'requirements': ['FR-001'],
                      'source': reference(self.root, 'scope.md', 'Preserve original request identifiers.')}
        (self.root / filename).write_text(
            '# Scope\n> 产品版本：v1\n> 状态：已确认\n'
            '```project-checks\n' + json.dumps({'items': [definition], 'changes': []}) + '\n```\n'
            '### SRC-001 Business decision\n[Decision](scope.md)\n'
            '### FR-001 Read state\n状态：已确认\n依据：SRC-001\n原型：否\n'
            '确认记录：Business owner 产品版本 v1\n#### AC-001 Read\nReturns the current state.\n')
        return freeze_inputs(self.root / filename)

    def test_unrelated_catalog_stage_does_not_invalidate_current_stage_or_execution(self):
        import lifecycle_checklist
        from lifecycle_quality import runner_identity
        before = self.catalog('L3')
        runner = runner_identity()
        data = json.loads(lifecycle_checklist.CATALOG.read_text())
        next(item for item in data['items'] if item['stage'] == 'L10')['question'] += ' Edited.'
        path = self.root / 'edited-catalog.json'
        path.write_text(json.dumps(data))
        with patch.object(lifecycle_checklist, 'CATALOG', path):
            self.assertEqual(self.catalog('L3')['fingerprint'], before['fingerprint'])
            self.assertEqual(runner_identity(), runner)
            next(item for item in data['items'] if item['stage'] == 'L3')['question'] += ' Edited.'
            path.write_text(json.dumps(data))
            self.assertNotEqual(self.catalog('L3')['fingerprint'], before['fingerprint'])

    def test_provenance_audit_checks_source_but_does_not_change_stage_fingerprint(self):
        import lifecycle_checklist as module
        data = json.loads(module.CATALOG.read_text())
        item = copy.deepcopy(next(i for i in data['items'] if i['stage'] == 'L3'))
        source = self.root / 'source.md'
        source.write_text('Keep the applicable rule.\n')
        ref = {'path': source.name, 'quote': 'Keep the applicable rule.', 'kind': 'local_method',
               'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        item['sources'] = [ref]
        path = self.root / 'catalog.json'
        def save():
            path.write_text(json.dumps({'schema_version': 1, 'items': [item]}))
        save()
        with patch.object(module, 'ROOT', self.root.resolve()), patch.object(module, 'CATALOG', path):
            before = module.load_catalog('L3')['fingerprint']
            source.write_text(source.read_text() + '\n<!-- Editorial note -->\n')
            self.assertEqual(module.load_catalog('L3')['fingerprint'], before)
            with self.assertRaisesRegex(ValueError, 'stale provenance'):
                module.load_catalog('L3', verify_sources=True)
            ref['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
            save()
            self.assertEqual(module.load_catalog('L3', verify_sources=True)['fingerprint'], before)
            item['required'] = not item['required']
            save()
            self.assertNotEqual(module.load_catalog('L3')['fingerprint'], before)

    def test_frozen_project_scope_detects_missing_downgraded_and_wrong_method_records(self):
        self.assertIn('project_inputs', inspect.signature(check_quality).parameters,
                      'quality has no caller-bound project scope')
        coverage = self.detailed()
        scope = self.project_scope()
        kwargs = {'project_inputs': scope, 'expected_inputs': scope['fingerprint']}
        result = self.strict(**kwargs)
        self.assertFalse(result['ready'])
        self.assertIn('PROJECT-KEEP-ID', str(result['gaps']))
        item = copy.deepcopy(coverage['items'][0])
        item['id'] = 'PROJECT-KEEP-ID'
        coverage['items'].append(item)
        self.assertTrue(self.strict(**kwargs)['ready'])
        for updates in ({'required': False}, {'method': 'test'}, {'check': 'rules_exceptions'}):
            with self.subTest(updates=updates):
                changed = copy.deepcopy(item); item.update(updates)
                self.assertFalse(self.strict(**kwargs)['valid'])
                item.clear(); item.update(changed)
        with self.subTest('scope changed'):
            (self.root / 'scope.md').write_text('Changed decision.')
            self.assertFalse(self.strict(**kwargs)['valid'])

    def test_checkpoint_cli_requires_details_and_exact_caller_targets(self):
        def run(*args):
            (self.root / 'quality.json').write_text(json.dumps(self.quality))
            process = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_quality.py'), 'checkpoint',
                '--root', str(self.root), '--contract', 'quality.json', *args], capture_output=True, text=True)
            return process, json.loads(process.stdout) if process.stdout else {}
        process, result = run('--target', 'L3:prd.md', '--no-project-inputs')
        self.assertTrue(result, process.stderr)
        self.assertEqual(process.returncode, 1)
        self.detailed()
        process, result = run('--target', 'L3:prd.md', '--no-project-inputs')
        self.assertEqual(process.returncode, 0, process.stderr or result)
        self.assertTrue(result['details_ready'])
        for args in ([], ['--target', 'L4:prd.md'], ['--target', 'L3:another.md']):
            process, result = run(*args, '--no-project-inputs')
            self.assertEqual(process.returncode, 1, result)

    def test_checkpoint_cli_cannot_accept_unbound_project_records(self):
        coverage = self.detailed()
        scope = self.project_scope()
        item = copy.deepcopy(coverage['items'][0]); item['id'] = 'PROJECT-KEEP-ID'
        coverage['items'].append(item)
        (self.root / 'quality.json').write_text(json.dumps(self.quality))
        (self.root / 'inputs.json').write_text(json.dumps(scope))
        command = [sys.executable, str(ROOT / 'scripts/lifecycle_quality.py'), 'checkpoint',
                   '--root', str(self.root), '--contract', 'quality.json', '--target', 'L3:prd.md']
        missing = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1)
        process = subprocess.run(command + ['--inputs', 'inputs.json', '--expected-inputs', scope['fingerprint']],
                                 capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stderr or process.stdout)
        self.assertIn('frozen product input', process.stdout)
        entry = self.quality['stages'][0]
        entry['artifact'] = reference(self.root, 'formal.md')
        citation = reference(self.root, 'formal.md', 'Returns the current state.')
        for check in entry['checks']:
            check['evidence'] = [citation]
        for item in coverage['items']:
            item['evidence'] = [citation]
            if item.get('verification'):
                item['verification']['evidence'] = [citation]
        (self.root / 'quality.json').write_text(json.dumps(self.quality))
        command[-1] = 'L3:formal.md'
        process = subprocess.run(command + ['--inputs', 'inputs.json', '--expected-inputs', scope['fingerprint']],
                                 capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr or process.stdout)
        stale = subprocess.run(command + ['--inputs', 'inputs.json', '--expected-inputs', '0' * 64],
                               capture_output=True, text=True)
        self.assertEqual(stale.returncode, 1)

    def test_independent_review_requires_distinct_identity_and_current_walkthrough_evidence(self):
        self.assertIn('independent_from', inspect.signature(check_quality).parameters,
                      'caller cannot require an independent content review')
        self.detailed()
        entry = self.quality['stages'][0]
        result = self.strict(independent_from=entry['reviewer'])
        self.assertFalse(result['ready'])
        self.assertIn('independent', str(result['gaps']))
        self.assertFalse(self.strict(independent_from='producer-session')['ready'])
        (self.root / 'review.md').write_text('Original request retained.\nMixed states preserve partial success.\n')
        entry['walkthrough'] = [
            {'id': 'source_coverage', 'verdict': 'pass', 'reason': 'Checked original request against the artifact.',
             'evidence': [reference(self.root, 'review.md', 'Original request retained.')]},
            {'id': 'counterexample', 'verdict': 'pass', 'reason': 'Walked mixed states step by step.',
             'evidence': [reference(self.root, 'review.md', 'Mixed states preserve partial success.')]}]
        self.assertTrue(self.strict(independent_from='producer-session')['ready'])
        (self.root / 'review.md').write_text('Changed conclusion.')
        self.assertFalse(self.strict(independent_from='producer-session')['valid'])

    def test_required_journey_cannot_be_missing_waived_or_declared_failed(self):
        self.assertIn('walkthrough', inspect.signature(check_quality).parameters)
        self.detailed()
        kwargs = {'walkthrough': ['journey']}
        self.assertFalse(self.strict(**kwargs)['ready'])
        entry = self.quality['stages'][0]
        evidence = [reference(self.root, 'prd.md', 'Returns the current state.')]
        entry['walkthrough'] = [{'id': 'journey', 'verdict': 'pass',
                                 'reason': 'Entry, operation, visible result and recovery were checked.', 'evidence': evidence}]
        self.assertTrue(self.strict(**kwargs)['ready'])
        for verdict in ('gap', 'not_applicable'):
            entry['walkthrough'][0]['verdict'] = verdict
            self.assertFalse(self.strict(**kwargs)['ready'])
        entry['walkthrough'][0]['verdict'] = 'pass'
        entry['walkthrough'].append(copy.deepcopy(entry['walkthrough'][0]))
        self.assertFalse(self.strict(**kwargs)['valid'])

    def test_checkpoint_cli_carries_the_callers_review_policy(self):
        self.detailed()
        (self.root / 'quality.json').write_text(json.dumps(self.quality))
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_quality.py'), 'checkpoint',
            '--root', str(self.root), '--contract', 'quality.json', '--target', 'L3:prd.md',
            '--no-project-inputs', '--independent-from', 'producer-session', '--walkthrough', 'journey'], capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stdout)
        self.assertTrue(process.stdout, process.stderr)
        self.assertIn('source_coverage', process.stdout)
        self.assertIn('journey', process.stdout)

    def test_checkpoint_requires_an_explicit_caller_input_policy(self):
        self.detailed()
        (self.root / 'quality.json').write_text(json.dumps(self.quality))
        command = [sys.executable, str(ROOT / 'scripts/lifecycle_quality.py'), 'checkpoint',
                   '--root', str(self.root), '--contract', 'quality.json', '--target', 'L3:prd.md']
        missing = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1, 'omitting scope policy silently bypassed frozen scope')
        explicit = subprocess.run(command + ['--no-project-inputs'], capture_output=True, text=True)
        self.assertEqual(explicit.returncode, 0, explicit.stdout + explicit.stderr)

    def test_no_project_inputs_policy_rejects_a_project_index_in_the_actual_artifact(self):
        self.detailed()
        content = (self.root / 'prd.md').read_text() + '\n```project-checks\n{"items":[],"changes":[]}\n```\n'
        for suffix in ('.md', '.markdown'):
            with self.subTest(suffix=suffix):
                name = 'prd' + suffix
                (self.root / name).write_text(content)
                entry = self.quality['stages'][0]
                entry['artifact'] = reference(self.root, name)
                evidence = [reference(self.root, name, 'Returns the current state.')]
                for check in entry['checks']:
                    check['evidence'] = evidence
                for item in entry['coverage']['items']:
                    item['evidence'] = evidence
                    if 'verification' in item:
                        item['verification']['evidence'] = evidence
                (self.root / 'quality.json').write_text(json.dumps(self.quality))
                process = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_quality.py'), 'checkpoint',
                    '--root', str(self.root), '--contract', 'quality.json', '--target', 'L3:' + name, '--no-project-inputs'],
                    capture_output=True, text=True)
                self.assertEqual(process.returncode, 1, process.stdout)
                self.assertIn('project-checks', process.stdout)

    def test_new_checkpoint_options_are_not_silently_ignored_by_legacy_modes(self):
        execution = self.collected()
        packet, _, _ = handoff(self.root, self.quality, self.trace, execution)
        (self.root / 'handoff.json').write_text(json.dumps(packet))
        command = [sys.executable, str(ROOT / 'scripts/lifecycle_quality.py'), 'handoff',
                   '--root', str(self.root), '--contract', 'handoff.json']
        for args in (['--target', 'L3:prd.md'], ['--independent-from', 'producer'], ['--walkthrough', 'journey']):
            process = subprocess.run(command + args, capture_output=True, text=True)
            self.assertEqual(process.returncode, 1, 'caller policy was silently ignored: ' + process.stdout)

    def test_walkthrough_policy_rejects_wrong_types_even_when_empty(self):
        self.detailed()
        for value in ({}, '', False, 0):
            self.assertFalse(self.strict(walkthrough=value)['valid'])

    def test_passing_components_do_not_hide_a_broken_complete_journey(self):
        coverage = self.detailed('L6')
        app = self.root / 'app.py'
        app.write_text('def value(): return 3\ndef label(value): return f"State:{value}"\n'
                       'def journey(): return label(value() + 1)\n')
        (self.root / 'test_cases.py').write_text(
            'import unittest\nfrom app import value,label,journey\n'
            'class Units(unittest.TestCase):\n'
            ' def test_value(self): self.assertEqual(value(),3)\n'
            ' def test_label(self): self.assertEqual(label(4),"State:4")\n'
            'class Journey(unittest.TestCase):\n'
            ' def test_result(self): self.assertEqual(journey(),"State:3")\n')
        units = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'test_cases.Units'],
                               cwd=self.root, capture_output=True, text=True)
        self.assertEqual(units.returncode, 0, units.stderr)
        ids = ['test_cases.Units.test_value', 'test_cases.Units.test_label', 'test_cases.Journey.test_result']
        self.trace['tests'] = [{'id': key, 'version': 1, 'source': reference(self.root, 'test_cases.py'),
                               'covers': [{'id': 'AC-01', 'version': 1}]} for key in ids]
        self.trace['build'] = reference(self.root, 'app.py')
        mapped = next(item for item in coverage['items'] if item['id'] == 'L6-AUTOMATED')
        mapped.update(applicability='applicable', owner='fixture-reviewer', next_action='Repair the integration.',
                      verification={'kind': 'test', 'result': 'passed', 'tests': ids, 'evidence': []})
        failed = self.collected(expected_exit=1)
        self.assertEqual(sum(case['status'] == 'passed' for case in failed['cases']), 2)
        self.assertFalse(self.strict(trace=self.trace, execution=failed)['ready'])
        old = (self.root / 'execution.json').read_bytes()
        app.write_text(app.read_text().replace('label(value() + 1)', 'label(value())'))
        self.trace['build'] = reference(self.root, 'app.py')
        passed = self.collected(output='execution-2.json')
        self.assertTrue(self.strict(trace=self.trace, execution=passed)['ready'])
        self.assertEqual((self.root / 'execution.json').read_bytes(), old)

    def strict(self, value=None, **kwargs):
        self.assertIn('require_details', inspect.signature(check_quality).parameters,
                      'quality does not check detailed coverage')
        return check_quality(value or self.quality, self.root, require_details=True, **kwargs)

    def add_coverage(self, entry):
        catalog = self.catalog(entry['stage'])
        evidence = [reference(self.root, 'prd.md', 'Returns the current state.')]
        records = []
        for item in catalog['items']:
            record = {'id': item['id'], 'applicability': 'applicable' if item['required'] else 'not_applicable',
                      'reason': 'This isolated scope reads its own current state.', 'evidence': copy.deepcopy(evidence)}
            if item['required']:
                record['verification'] = {'kind': item['verification'], 'result': 'passed',
                                          'evidence': copy.deepcopy(evidence)}
            records.append(record)
        entry['coverage'] = {'catalog_sha256': catalog['fingerprint'], 'items': records}
        return entry['coverage']

    def detailed(self, stage='L3'):
        entry = self.quality['stages'][0]
        entry['stage'] = stage
        for check, identity in zip(entry['checks'], STAGE_CHECKS[stage]):
            check['id'] = identity
        return self.add_coverage(entry)

    def collected(self, expected_exit=0, output='execution.json'):
        (self.root / 'trace.json').write_text(json.dumps(self.trace))
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_test_runner.py'),
                                 '--root', str(self.root), '--trace', 'trace.json',
                                 '--output', str(self.root / output)], text=True, capture_output=True)
        self.assertEqual(result.returncode, expected_exit, result.stdout + result.stderr)
        return json.loads((self.root / output).read_text())

    def test_catalog_covers_every_stage_question_and_has_frozen_provenance(self):
        catalog = self.catalog()
        self.assertGreater(len(catalog['items']), 22)
        self.assertEqual(len({x['id'] for x in catalog['items']}), len(catalog['items']))
        self.assertEqual({(s, c) for s, checks in STAGE_CHECKS.items() for c in checks},
                         {(x['stage'], x['check']) for x in catalog['items']})
        for item in catalog['items']:
            self.assertTrue(item['question'])
            self.assertTrue(item['when'])
            self.assertTrue(item['evidence_expected'])
            self.assertIn(item['verification'], ('review', 'test'))
            self.assertTrue(item['sources'])
            for source in item['sources']:
                path = ROOT / source['path']
                self.assertEqual(source['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertIn(source['quote'], path.read_text())

    def test_catalog_rejects_stale_escape_duplicate_and_invalid_source_kind(self):
        data = self.catalog()
        import lifecycle_checklist as module
        original = json.loads(module.CATALOG.read_text())
        cases = [lambda d: d['items'][0]['sources'][0].update(sha256='0' * 64),
                 lambda d: d['items'][0]['sources'][0].update(path='../outside.md'),
                 lambda d: d['items'].append(copy.deepcopy(d['items'][0])),
                 lambda d: d['items'][0]['sources'][0].update(kind='certified-standard')]
        for mutate in cases:
            changed = copy.deepcopy(original); mutate(changed)
            path = self.root / 'catalog.json'; path.write_text(json.dumps(changed))
            with patch.object(module, 'CATALOG', path), self.assertRaises(ValueError):
                module.load_catalog(verify_sources=True)

    def test_legacy_review_remains_readable_but_strict_does_not_claim_detail_coverage(self):
        self.assertTrue(check_quality(self.quality, self.root)['ready'])
        result = self.strict()
        self.assertTrue(result['valid'], result)
        self.assertFalse(result['ready'])
        self.assertFalse(result['details_ready'])
        self.assertTrue(result['gaps'])

    def test_complete_applicability_and_current_review_evidence_are_ready(self):
        self.detailed()
        result = self.strict()
        self.assertTrue(result['ready'], result)
        self.assertTrue(result['details_ready'])
        self.assertFalse(result['business_authorization'])

    def test_omitted_conditional_item_is_a_gap_not_silent_not_applicable(self):
        coverage = self.detailed()
        item = next(x for x in coverage['items'] if x['applicability'] == 'not_applicable')
        coverage['items'].remove(item)
        result = self.strict()
        self.assertTrue(result['valid'], result)
        self.assertFalse(result['ready'])
        self.assertIn(item['id'], str(result['gaps']))

    def test_required_item_cannot_be_waived_and_unknown_needs_owner_action(self):
        coverage = self.detailed()
        item = next(x for x in coverage['items'] if x['applicability'] == 'applicable')
        item['applicability'] = 'not_applicable'
        self.assertFalse(self.strict()['ready'])
        item.update(applicability='undecided', owner='product', next_action='Clarify the affected rule.')
        del item['verification']
        result = self.strict()
        self.assertTrue(result['valid'], result)
        self.assertFalse(result['ready'])
        self.assertIn('Clarify', str(result['gaps']))
        del item['owner']
        self.assertFalse(self.strict()['valid'])

    def test_duplicate_unknown_cross_stage_stale_and_wrong_method_are_rejected(self):
        cases = [lambda c: c['items'].append(copy.deepcopy(c['items'][0])),
                 lambda c: c['items'][0].update(id='unknown-item'),
                 lambda c: c.update(catalog_sha256='0' * 64),
                 lambda c: c['items'][0]['verification'].update(kind='test')]
        for mutate in cases:
            self.quality, self.trace = scenario(self.root)
            coverage = self.detailed(); mutate(coverage)
            self.assertFalse(self.strict()['valid'])
        coverage = self.detailed()
        coverage['items'][0]['id'] = self.catalog('L4')['items'][0]['id']
        self.assertFalse(self.strict()['valid'])

    def test_na_and_pass_need_evidence_and_present_details_are_always_validated(self):
        coverage = self.detailed()
        optional = next(x for x in coverage['items'] if x['applicability'] == 'not_applicable')
        optional['evidence'] = []
        self.assertFalse(self.strict()['ready'])
        self.quality, self.trace = scenario(self.root)
        coverage = self.detailed()
        item = next(x for x in coverage['items'] if 'verification' in x)
        (self.root / 'other.md').write_text('Another artifact passed.')
        item['verification']['evidence'] = [reference(self.root, 'other.md', 'Another artifact passed.')]
        self.assertFalse(self.strict()['ready'])
        coverage['catalog_sha256'] = '0' * 64
        self.assertFalse(check_quality(self.quality, self.root)['ready'])

    def test_project_rule_has_its_own_source_and_mapping(self):
        coverage = self.detailed()
        (self.root / 'scope.md').write_text('Project rule: preserve original request identifiers.')
        record = copy.deepcopy(next(x for x in coverage['items'] if 'verification' in x))
        record.update(id='PROJECT-KEEP-ID', check='acceptance', required=True, method='review',
                      source=reference(self.root, 'scope.md', 'preserve original request identifiers.'))
        coverage['items'].append(record)
        self.assertTrue(self.strict()['ready'])
        (self.root / 'scope.md').write_text('Rule revised after review.')
        self.assertFalse(self.strict()['valid'])

    def test_required_project_rule_cannot_be_waived_or_hide_invalid_requirement(self):
        coverage = self.detailed()
        (self.root / 'scope.md').write_text('Project rule: preserve original request identifiers.')
        record = copy.deepcopy(next(x for x in coverage['items'] if 'verification' in x))
        record.update(id='PROJECT-KEEP-ID', check='acceptance', required=True, method='review',
                      source=reference(self.root, 'scope.md', 'preserve original request identifiers.'))
        coverage['items'].append(record)
        record['applicability'] = 'not_applicable'
        self.assertFalse(self.strict()['ready'])
        record.update(applicability='applicable', required='false')
        self.assertFalse(self.strict()['valid'])

    def test_test_verification_needs_current_trace_actual_results_and_declared_tests(self):
        coverage = self.detailed('L6')
        execution = self.collected()
        mapped = next(x for x in self.catalog('L6')['items'] if x['verification'] == 'test')
        record = next(x for x in coverage['items'] if x['id'] == mapped['id'])
        record.update(applicability='applicable', verification={'kind': 'test', 'result': 'passed',
                      'tests': ['test_cases.Tests.test_ok'], 'evidence': []})
        self.assertFalse(self.strict()['ready'])
        result = self.strict(trace=self.trace, execution=execution)
        self.assertTrue(result['ready'], result)
        record['verification']['tests'] = ['missing.Test.test_absent']
        self.assertFalse(self.strict(trace=self.trace, execution=execution)['valid'])
        record['verification']['tests'] = ['test_cases.Tests.test_ok']
        failed = copy.deepcopy(execution); failed['cases'][0]['status'] = 'failed'
        self.assertFalse(self.strict(trace=self.trace, execution=failed)['ready'])
        wrong = copy.deepcopy(self.trace); wrong['subject_ref'] = 'another-subject'
        self.assertFalse(self.strict(trace=wrong, execution=execution)['valid'])

    def test_declared_automated_scope_cannot_be_marked_not_applicable(self):
        coverage = self.detailed('L6')
        execution = self.collected()
        result = self.strict(trace=self.trace, execution=execution)
        self.assertTrue(result['valid'], result)
        self.assertFalse(result['ready'])
        self.assertIn('L6-AUTOMATED', str(result['gaps']))
        item = next(x for x in coverage['items'] if x['id'] == 'L6-AUTOMATED')
        item.update(applicability='applicable', verification={'kind': 'test', 'result': 'passed',
                    'tests': ['test_cases.Tests.test_ok'], 'evidence': []})
        self.assertTrue(self.strict(trace=self.trace, execution=execution)['ready'])
        (self.root / 'quality.json').write_text(json.dumps(self.quality))
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_quality.py'), 'quality',
                                 '--root', str(self.root), '--contract', 'quality.json', '--stage', 'L6',
                                 '--require-details', '--trace', 'trace.json', '--execution', 'execution.json'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['details_ready'])

    def test_strict_handoff_cannot_drop_details_but_transfer_preserves_missing_work(self):
        self.assertIn('require_details', inspect.signature(check_handoff).parameters)
        execution = self.collected()
        packet, state, quality = handoff(self.root, self.quality, self.trace, execution)
        self.assertTrue(check_handoff(packet, self.root)['ready'])
        self.assertFalse(check_handoff(packet, self.root, require_details=True)['ready'])
        transfer = check_handoff(packet, self.root, 'transfer', require_details=True)
        self.assertTrue(transfer['ready'], transfer)
        self.assertFalse(transfer['quality_ready'])
        self.assertTrue(transfer['gaps'])
        for entry in quality['stages']:
            coverage = self.add_coverage(entry)
            if entry['stage'] == 'L6':
                item = next(x for x in coverage['items'] if x['id'] == 'L6-AUTOMATED')
                item.update(applicability='applicable', verification={'kind': 'test', 'result': 'passed',
                            'tests': ['test_cases.Tests.test_ok'], 'evidence': []})
        (self.root / 'quality.json').write_text(json.dumps(quality))
        packet['quality'] = reference(self.root, 'quality.json')
        packet['files'] = [reference(self.root, x['path']) for x in packet['files']]
        self.assertTrue(check_handoff(packet, self.root, require_details=True)['ready'])

    def test_strict_handoff_uses_frozen_project_rules_for_quality_readiness(self):
        scope = self.project_scope('prd.md')
        prd = reference(self.root, 'prd.md')
        stage = self.quality['stages'][0]
        stage['artifact'] = prd
        for check in stage['checks']:
            check['evidence'] = [reference(self.root, 'prd.md', 'Returns the current state.')]
        self.trace['requirements'][0].update(id='FR-001', source=prd)
        self.trace['acceptance'][0].update(id='AC-001', source=prd,
                                          requirements=[{'id': 'FR-001', 'version': 1}])
        self.trace['tests'][0]['covers'] = [{'id': 'AC-001', 'version': 1}]
        execution = self.collected()
        packet, _, quality = handoff(self.root, self.quality, self.trace, execution)
        for entry in quality['stages']:
            coverage = self.add_coverage(entry)
            if entry['stage'] == 'L6':
                item = next(x for x in coverage['items'] if x['id'] == 'L6-AUTOMATED')
                item.update(applicability='applicable', verification={'kind': 'test', 'result': 'passed',
                            'tests': ['test_cases.Tests.test_ok'], 'evidence': []})
        checks = next(entry for entry in quality['stages'] if entry['stage'] == 'L3')['coverage']['items']
        binding = {'project_inputs': scope, 'expected_inputs': scope['fingerprint']}

        for included in (False, True):
            if included:
                project = copy.deepcopy(next(item for item in checks if item['applicability'] == 'applicable'))
                project['id'] = 'PROJECT-KEEP-ID'
                checks.append(project)
            for has_trace in (True, False):
                candidate = copy.deepcopy(packet)
                review = copy.deepcopy(quality)
                if not has_trace:
                    candidate.pop('trace')
                    candidate.pop('execution')
                    test_review = next(entry for entry in review['stages'] if entry['stage'] == 'L6')
                    automated = next(item for item in test_review['coverage']['items'] if item['id'] == 'L6-AUTOMATED')
                    automated.update(applicability='not_applicable', reason='Only manual verification was supplied.')
                    automated.pop('verification')
                (self.root / 'quality.json').write_text(json.dumps(review))
                candidate['quality'] = reference(self.root, 'quality.json')
                candidate['files'] = [reference(self.root, item['path']) for item in candidate['files']]
                for supplied in ({}, binding):
                    for purpose in (('tested', 'transfer') if has_trace else ('transfer',)):
                        with self.subTest(included=included, explicit=bool(supplied), purpose=purpose, has_trace=has_trace):
                            result = check_handoff(candidate, self.root, purpose, require_details=True, **supplied)
                            self.assertEqual(result['ready'], included or purpose == 'transfer', result)
                            self.assertEqual(result['details_ready'], included, result)
                            if not included:
                                self.assertIn('PROJECT-KEEP-ID', str(result['gaps']))

    def test_handoff_project_rule_tests_cover_its_frozen_requirements(self):
        from product_inputs import freeze_inputs

        self.project_scope('prd.md')
        path = self.root / 'prd.md'
        project_rule = {
            'id': 'PROJECT-DETAILS', 'stage': 'L6', 'check': STAGE_CHECKS['L6'][0],
            'required': True, 'method': 'test', 'requirements': ['FR-002'],
            'source': reference(self.root, 'scope.md', 'Preserve original request identifiers.'),
        }
        intro, index, requirements = path.read_text().split('```', 2)
        scope_index = json.loads(index.removeprefix('project-checks\n'))
        scope_index['items'].append(project_rule)
        path.write_text(intro + '```project-checks\n' + json.dumps(scope_index) + '\n```' + requirements +
            '### FR-002 Read details\n状态：已确认\n依据：SRC-001\n原型：否\n'
            '确认记录：Business owner 产品版本 v1\n#### AC-002 Read\nReturns the details.\n')
        scope = freeze_inputs(path)
        prd = reference(self.root, 'prd.md')
        stage = self.quality['stages'][0]
        stage['artifact'] = prd
        for check in stage['checks']:
            check['evidence'] = [reference(self.root, 'prd.md', 'Returns the current state.')]
        cases = self.root / 'test_cases.py'
        cases.write_text(cases.read_text() + '    def test_details(self):\n        self.assertGreater(value(), 0)\n')
        ids = ['test_cases.Tests.test_ok', 'test_cases.Tests.test_details']
        self.trace['requirements'] = [{'id': f'FR-00{i}', 'version': 1, 'source': prd}
                                      for i in (1, 2)]
        self.trace['acceptance'] = [{'id': f'AC-00{i}', 'version': 1, 'required': True, 'source': prd,
                                     'requirements': [{'id': f'FR-00{i}', 'version': 1}]} for i in (1, 2)]
        self.trace['tests'] = [{'id': identity, 'version': 1, 'source': reference(self.root, cases.name),
                                'covers': [{'id': f'AC-00{i}', 'version': 1}]}
                               for i, identity in enumerate(ids, 1)]
        packet, _, quality = handoff(self.root, self.quality, self.trace, self.collected())
        for entry in quality['stages']:
            items = self.add_coverage(entry)['items']
            if entry['stage'] == 'L3':
                items.append(dict(copy.deepcopy(next(item for item in items if 'verification' in item)),
                                  id='PROJECT-KEEP-ID'))
            if entry['stage'] == 'L6':
                automated = next(item for item in items if item['id'] == 'L6-AUTOMATED')
                automated.update(applicability='applicable', verification={
                    'kind': 'test', 'result': 'passed', 'tests': ids, 'evidence': []})
                project = dict(copy.deepcopy(automated), id=project_rule['id'])
                items.append(project)

        for mapped, covered in ((ids[:1], False), (ids[1:], True)):
            with self.subTest(mapped=mapped):
                project['verification']['tests'] = mapped
                (self.root / 'quality.json').write_text(json.dumps(quality))
                packet['quality'] = reference(self.root, 'quality.json')
                packet['files'] = [reference(self.root, item['path']) for item in packet['files']]
                options = {'require_details': True, 'project_inputs': scope, 'expected_inputs': scope['fingerprint']}
                tested = check_handoff(packet, self.root, 'tested', **options)
                transfer = check_handoff(packet, self.root, 'transfer', **options)
                self.assertEqual(tested['ready'], covered, tested)
                self.assertTrue(transfer['ready'], transfer)
                self.assertEqual(transfer['details_ready'], covered, transfer)
                if not covered:
                    self.assertTrue(any(gap.get('item') == project_rule['id'] and gap.get('requirements') == ['FR-002']
                                        for gap in tested['gaps']), tested)

    def test_strict_manual_handoff_allows_web_reading_but_requires_local_evidence(self):
        from product_inputs import freeze_inputs

        self.project_scope('prd.md')
        prd = self.root / 'prd.md'
        original = prd.read_text()
        url = 'https://example.invalid/context'
        background = f'\n[Background reading]({url})\n'
        alias = '\n[Background reading][web]\n\n[web]: ' + url + '\n'
        for label, content, ready in (
                ('inline', original + background, True),
                ('reference style', original + alias, True),
                ('same URL in source', (original + alias).replace('[Decision](scope.md)',
                    '[Decision](scope.md)\n[Source][web]'), False),
                ('embedded image', original + background + f'\n![Evidence]({url})\n', False),
                ('project rule source', (original + background).replace('"path": "scope.md"',
                    f'"path": "{url}"'), False)):
            with self.subTest(label=label):
                prd.write_text(content)
                with self.assertRaisesRegex(ValueError, 'explicit local snapshot'):
                    freeze_inputs(prd)
                stage = self.quality['stages'][0]
                stage['artifact'] = reference(self.root, 'prd.md')
                for check in stage['checks']:
                    check['evidence'] = [reference(self.root, 'prd.md', 'Returns the current state.')]
                packet, _, quality = handoff(self.root, self.quality, self.trace, {})
                packet.pop('trace')
                packet.pop('execution')
                for entry in quality['stages']:
                    items = self.add_coverage(entry)['items']
                    if entry['stage'] == 'L3':
                        items.append(dict(copy.deepcopy(next(item for item in items if 'verification' in item)),
                                          id='PROJECT-KEEP-ID'))
                (self.root / 'quality.json').write_text(json.dumps(quality))
                packet['quality'] = reference(self.root, 'quality.json')
                packet['files'] = [reference(self.root, item['path']) for item in packet['files']]

                result = check_handoff(packet, self.root, 'transfer', require_details=True)
                self.assertEqual(result['ready'], ready, result)
                if ready:
                    self.assertTrue(result['details_ready'], result)
                    without_local_source = dict(packet, files=[item for item in packet['files']
                                                               if item['path'] != 'scope.md'])
                    missing = check_handoff(without_local_source, self.root, 'transfer', require_details=True)
                    self.assertIn('inventory omits', str(missing['errors']))
                else:
                    self.assertIn('explicit local snapshot', str(result['errors']))

    def test_partial_legacy_stage_coverage_never_claims_all_details_ready(self):
        self.detailed()
        other = copy.deepcopy(self.quality['stages'][0]); other['stage'] = 'L4'; del other['coverage']
        for check, identity in zip(other['checks'], STAGE_CHECKS['L4']): check['id'] = identity
        self.quality['stages'].append(other)
        result = check_quality(self.quality, self.root)
        self.assertTrue(result['ready'], result)
        self.assertFalse(result['details_ready'])
        self.assertFalse(self.strict()['ready'])
        self.assertTrue(self.strict(stages=['L3'])['ready'])

    def test_bad_catalog_scalar_values_fail_with_validation_errors(self):
        self.catalog()
        import lifecycle_checklist as module
        data = json.loads(module.CATALOG.read_text())
        for mutate in (lambda d: d['items'][0].update(stage=[]),
                       lambda d: d['items'][0]['sources'][0].update(kind=[])):
            changed = copy.deepcopy(data); mutate(changed)
            path = self.root / 'catalog.json'; path.write_text(json.dumps(changed))
            with patch.object(module, 'CATALOG', path):
                try:
                    module.load_catalog()
                except Exception as error:
                    self.assertIsInstance(error, ValueError)
                else:
                    self.fail('bad catalog scalar was accepted')
        try:
            module.load_catalog([])
        except Exception as error:
            self.assertIsInstance(error, ValueError)
        else:
            self.fail('bad stage scalar was accepted')

    def test_dependency_loss_returns_an_explicit_invalid_result(self):
        self.detailed()
        with patch.dict(sys.modules, {'lifecycle_checklist': None}):
            try:
                result = self.strict()
            except ImportError as error:
                self.fail(f'missing dependency escaped validation: {error}')
        self.assertFalse(result['valid'])
        self.assertFalse(result['ready'])

    def test_catalog_cli_and_stage_scoped_source_validation(self):
        self.catalog()
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_checklist.py'), '--stage', 'L3'],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({i['stage'] for i in json.loads(result.stdout)['items']}, {'L3'})
        import lifecycle_checklist as module
        changed = json.loads(module.CATALOG.read_text())
        next(i for i in changed['items'] if i['stage'] == 'L4')['sources'][0]['sha256'] = '0' * 64
        path = self.root / 'catalog.json'; path.write_text(json.dumps(changed))
        with patch.object(module, 'CATALOG', path):
            self.assertTrue(module.load_catalog('L3')['items'])
            with self.assertRaises(ValueError): module.load_catalog('L4', verify_sources=True)

    def test_failed_or_unexecuted_verification_retains_owner_and_next_action(self):
        coverage = self.detailed()
        item = next(x for x in coverage['items'] if 'verification' in x)
        for status in ('failed', 'not_run'):
            item['verification']['result'] = status
            item.update(owner='current-reviewer', next_action='Repair and recheck the affected rule.')
            result = self.strict()
            self.assertTrue(result['valid'], result)
            self.assertFalse(result['ready'])
            self.assertIn('Repair and recheck', str(result['gaps']))

    def test_strict_cli_flag_is_not_controlled_by_contract_data(self):
        self.assertIn('require_details', inspect.signature(check_quality).parameters)
        self.quality['require_details'] = False
        (self.root / 'quality.json').write_text(json.dumps(self.quality))
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_quality.py'), 'quality',
                                 '--root', str(self.root), '--contract', 'quality.json', '--stage', 'L3',
                                 '--require-details'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)['ready'])

    def test_every_stage_and_each_of_56_items_has_an_explicit_decision(self):
        examined = []
        for stage in STAGE_CHECKS:
            self.quality, self.trace = scenario(self.root)
            coverage = self.detailed(stage)
            self.assertTrue(self.strict()['ready'], stage)
            for item in list(coverage['items']):
                with self.subTest(stage=stage, item=item['id']):
                    coverage['items'].remove(item)
                    result = self.strict()
                    self.assertTrue(result['valid'], result)
                    self.assertFalse(result['ready'], result)
                    self.assertIn(item['id'], str(result['gaps']))
                    coverage['items'].append(item)
                    examined.append(item['id'])
        self.assertEqual(len(examined), 56)
        self.assertEqual(set(examined), {i['id'] for i in self.catalog()['items']})

    def test_inactive_applicability_cannot_hide_a_verification_mapping(self):
        coverage = self.detailed()
        item = next(x for x in coverage['items'] if x['applicability'] == 'not_applicable')
        for choice in ('not_applicable', 'undecided'):
            with self.subTest(choice=choice):
                item.update(applicability=choice, owner='product', next_action='Resolve the scope.')
                item['verification'] = {'kind': 'review', 'result': 'failed',
                                        'evidence': [dict(reference(self.root, 'prd.md'), quote='not present')]}
                self.assertFalse(self.strict()['valid'], 'inactive branch silently hid verification data')

    def test_all_items_validate_applicable_failed_undecided_and_waived_states(self):
        execution = self.collected()
        for stage in STAGE_CHECKS:
            self.quality, self.trace = scenario(self.root)
            coverage = self.detailed(stage)
            for item in coverage['items']:
                with self.subTest(stage=stage, item=item['id']):
                    original = copy.deepcopy(item)
                    definition = next(i for i in self.catalog(stage)['items'] if i['id'] == item['id'])
                    item.update(applicability='applicable', owner='review-owner', next_action='Repair and recheck.')
                    item['verification'] = {'kind': definition['verification'], 'result': 'passed',
                                            'evidence': [reference(self.root, 'prd.md', 'Returns the current state.')]}
                    kwargs = {}
                    if definition['verification'] == 'test':
                        item['verification']['tests'] = ['test_cases.Tests.test_ok']
                        kwargs = {'trace': self.trace, 'execution': execution}
                    self.assertTrue(self.strict(**kwargs)['ready'])
                    item['verification']['result'] = 'failed'
                    result = self.strict(**kwargs)
                    self.assertTrue(result['valid'], result)
                    self.assertFalse(result['ready'])
                    self.assertIn('Repair and recheck.', str(result['gaps']))
                    del item['verification']
                    item['applicability'] = 'undecided'
                    result = self.strict()
                    self.assertTrue(result['valid'], result)
                    self.assertFalse(result['ready'])
                    item['applicability'] = 'not_applicable'
                    result = self.strict()
                    self.assertTrue(result['valid'], result)
                    self.assertEqual(result['ready'], not definition['required'])
                    item.clear(); item.update(original)

    def test_failed_and_unrun_test_mappings_still_validate_ids_and_trace_binding(self):
        coverage = self.detailed('L6')
        execution = self.collected()
        item = next(x for x in coverage['items'] if x['id'] == 'L6-AUTOMATED')
        item.update(applicability='applicable', owner='test-owner', next_action='Fix and rerun the mapped test.')
        for status in ('failed', 'not_run'):
            for ids in (None, [], {}, ['missing.Test.test_absent'], ['test_cases.Tests.test_ok'] * 2):
                with self.subTest(status=status, ids=ids):
                    item['verification'] = {'kind': 'test', 'result': status, 'tests': ids, 'evidence': []}
                    self.assertFalse(self.strict(trace=self.trace, execution=execution)['valid'])
            item['verification']['tests'] = ['test_cases.Tests.test_ok']
            result = self.strict(trace=self.trace, execution=execution)
            self.assertTrue(result['valid'], result)
            self.assertFalse(result['ready'])
            wrong = copy.deepcopy(execution); wrong['trace_sha256'] = '0' * 64
            self.assertFalse(self.strict(trace=self.trace, execution=wrong)['valid'])

    def test_actual_test_gaps_retain_recovery_in_transfer_and_accept_fresh_rerun(self):
        base_quality = copy.deepcopy(self.quality)
        coverage = self.detailed('L6')
        (self.root / 'app.py').write_text('def value():\n    return 2\n')
        self.trace['build'] = reference(self.root, 'app.py')
        failed = self.collected(expected_exit=1)
        self.assertEqual(failed['cases'][0]['status'], 'failed')
        failed_bytes = (self.root / 'execution.json').read_bytes()
        item = next(x for x in coverage['items'] if x['id'] == 'L6-AUTOMATED')
        item.update(applicability='applicable', owner='test-owner', next_action='Rerun the current mapped test.',
                    verification={'kind': 'test', 'result': 'passed',
                                  'tests': ['test_cases.Tests.test_ok'], 'evidence': []})
        for kwargs in ({}, {'trace': self.trace, 'execution': failed}):
            with self.subTest(bound=bool(kwargs)):
                result = self.strict(**kwargs)
                self.assertTrue(result['valid'], result)
                gap = next(g for g in result['gaps'] if g.get('item') == 'L6-AUTOMATED')
                self.assertEqual(gap.get('owner'), item['owner'])
                self.assertEqual(gap.get('next_action'), item['next_action'])
        del item['next_action']
        self.assertFalse(self.strict(trace=self.trace, execution=failed)['valid'])
        item['next_action'] = 'Rerun the current mapped test.'
        packet, state, quality = handoff(self.root, base_quality, self.trace, failed)
        for entry in quality['stages']:
            self.add_coverage(entry)
            if entry['stage'] == 'L6':
                entry['coverage'] = copy.deepcopy(coverage)
        (self.root / 'quality.json').write_text(json.dumps(quality))
        packet['quality'] = reference(self.root, 'quality.json')
        packet['files'] = [reference(self.root, x['path']) for x in packet['files']]
        result = check_handoff(packet, self.root, 'transfer', require_details=True)
        self.assertTrue(result['ready'], result)
        gap = next(g for g in result['gaps'] if isinstance(g, dict) and g.get('item') == 'L6-AUTOMATED')
        self.assertEqual(gap.get('owner'), item['owner'])
        self.assertEqual(gap.get('next_action'), item['next_action'])
        self.assertFalse(check_handoff(packet, self.root, require_details=True)['ready'])
        (self.root / 'app.py').write_text('def value():\n    return 3\n')
        self.trace['build'] = reference(self.root, 'app.py')
        self.assertFalse(self.strict(trace=self.trace, execution=failed)['ready'])
        execution = self.collected(output='execution-2.json')
        self.assertTrue(self.strict(trace=self.trace, execution=execution)['ready'])
        self.assertEqual((self.root / 'execution.json').read_bytes(), failed_bytes)


if __name__ == '__main__':
    unittest.main()
