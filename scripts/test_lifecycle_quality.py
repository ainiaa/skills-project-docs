"""Behavioral checks for content review evidence and FR/AC execution trace."""
import copy
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lifecycle_quality import STAGE_CHECKS, check_handoff, check_quality, check_trace, reference

ROOT = Path(__file__).resolve().parents[1]


def scenario(root):
    (root / 'prd.md').write_text('FR-01 Read own records. AC-01 Returns the current state. Errors stay visible.\n')
    (root / 'app.py').write_text('def value():\n    return 3\n')
    (root / 'test_cases.py').write_text('import unittest\nfrom app import value\nclass Tests(unittest.TestCase):\n    def test_ok(self):\n        self.assertEqual(value(), 3)\n')
    quality = {'schema_version': 1, 'project_ref': 'P1', 'subject_ref': 'R1', 'stages': [{
        'stage': 'L3', 'artifact': reference(root, 'prd.md'), 'reviewer': 'model-session-a',
        'reviewer_kind': 'model', 'at': '2026-10-31T10:00:00+08:00',
        'checks': [{'id': identity, 'verdict': 'pass', 'reason': 'Scenario has a specified input and observable result.',
                    'evidence': [reference(root, 'prd.md', 'Returns the current state.')]} for identity in STAGE_CHECKS['L3']],
        'open_decisions': []}]}
    trace = {'schema_version': 1, 'project_ref': 'P1', 'subject_ref': 'R1',
        'build': reference(root, 'app.py'), 'environment': 'isolated', 'scope': 'fixture',
        'requirements': [{'id': 'FR-01', 'version': 1, 'source': reference(root, 'prd.md')}],
        'acceptance': [{'id': 'AC-01', 'version': 1, 'required': True,
                        'requirements': [{'id': 'FR-01', 'version': 1}], 'source': reference(root, 'prd.md')}],
        'tests': [{'id': 'test_cases.Tests.test_ok', 'version': 1, 'source': reference(root, 'test_cases.py'),
                   'covers': [{'id': 'AC-01', 'version': 1}]}]}
    return quality, trace


def handoff(root, quality, trace, execution):
    from test_lifecycle_record import record
    state = record(); state.update(project_ref='P1', subject_ref='R1')
    for item in state['artifacts']:
        item['source'] = 'prd.md'
        item['evidence'][0]['source'] = 'execution.json'
        if item['stage'] == 'L6':
            context = {'build': trace['build']['sha256'], 'environment': trace['environment'], 'scope': trace['scope']}
            item.update(context)
            item['evidence'][0].update(context)
    quality = copy.deepcopy(quality)
    pending = copy.deepcopy(state['artifacts'][-1])
    pending.update(id='uat', stage='L7', status='not_started', source='uat.md', evidence=[],
                   depends_on=[{'id': 'test', 'version': 1}])
    state['artifacts'].append(pending)
    state['branches'][0]['required'].append('uat')
    for stage in ('L0', 'L6'):
        entry = copy.deepcopy(quality['stages'][0]); entry['stage'] = stage
        for criterion, identity in zip(entry['checks'], STAGE_CHECKS[stage]):
            criterion['id'] = identity
        quality['stages'].append(entry)
    for name, data in [('lifecycle-record.json', state), ('quality.json', quality),
                       ('trace.json', trace)]:
        (root / name).write_text(json.dumps(data))
    if not (root / 'execution.json').exists():
        (root / 'execution.json').write_text(json.dumps(execution))
    else:
        assert json.loads((root / 'execution.json').read_text()) == execution
    packet = {'schema_version': 1, 'project_ref': 'P1', 'subject_ref': 'R1', 'record_revision': 1,
              'record': reference(root, 'lifecycle-record.json'), 'prd': reference(root, 'prd.md'),
              'quality': reference(root, 'quality.json'), 'trace': reference(root, 'trace.json'),
              'execution': reference(root, 'execution.json'),
              'next_action': {'stage': 'L7', 'action': 'Verify authorized isolated deployment',
                              'owner': 'next-session', 'expected_result': 'New deployment receipt',
                              'authorized_scope': 'local synthetic data only'},
              'files': [reference(root, path.name) for path in root.iterdir() if path.is_file()]}
    return packet, state, quality


class QualityTraceTests(unittest.TestCase):
    def test_collector_executes_current_sources_despite_matching_timestamp_bytecode(self):
        for filename in ('test_cases.py', 'app.py'):
            with self.subTest(filename=filename):
                root = self.root / Path(filename).stem
                root.mkdir()
                _, trace = scenario(root)
                source = root / filename
                stat = source.stat()
                py_compile.compile(str(source), doraise=True)
                source.write_text(source.read_text().replace('3', '4'))
                os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                trace['build'] = reference(root, 'app.py')
                trace['tests'][0]['source'] = reference(root, 'test_cases.py')
                (root / 'trace.json').write_text(json.dumps(trace))
                before = {p.name: p.read_bytes() for p in (root / '__pycache__').iterdir()}
                process = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/lifecycle_test_runner.py'),
                    '--root', str(root), '--trace', 'trace.json', '--output', str(root / 'execution.json')],
                    capture_output=True, text=True, timeout=20)
                self.assertEqual(process.returncode, 1, process.stderr)
                receipt = json.loads((root / 'execution.json').read_text())
                self.assertEqual(receipt['cases'][0]['status'], 'failed')
                self.assertFalse(check_trace(trace, receipt, root)['ready'])
                self.assertEqual({p.name: p.read_bytes() for p in (root / '__pycache__').iterdir()}, before)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.quality, self.trace = scenario(self.root)

    def execution(self):
        from lifecycle_quality import fingerprint
        from lifecycle_test_runner import runner_identity
        return {'schema_version': 1, 'trace_sha256': fingerprint(self.trace), 'runner_sha256': runner_identity(),
                'build': self.trace['build']['sha256'], 'environment': 'isolated', 'scope': 'fixture',
                'at': '2026-10-31T10:00:00+08:00', 'exit_code': 0,
                'cases': [{'id': 'test_cases.Tests.test_ok', 'status': 'passed',
                           'source': reference(self.root, 'test_cases.py')}], 'source_unchanged': True}

    def test_review_has_cited_answers_and_is_not_business_authorization(self):
        result = check_quality(self.quality, self.root)
        self.assertTrue(result['ready'], result)
        self.assertEqual(result['verification'], 'bound_content_review')
        self.assertFalse(result['business_authorization'])

    def test_file_or_heading_alone_cannot_complete_review(self):
        for mutate in (lambda d: d['stages'][0].update(checks=[]),
                       lambda d: d['stages'][0]['checks'][0].update(reason=' '),
                       lambda d: d['stages'][0]['checks'][0].update(evidence=[]),
                       lambda d: d['stages'][0]['checks'][0]['evidence'][0].update(quote='not in document'),
                       lambda d: d['stages'][0]['checks'].append(copy.deepcopy(d['stages'][0]['checks'][0]))):
            data = copy.deepcopy(self.quality); mutate(data)
            self.assertFalse(check_quality(data, self.root)['ready'])

    def test_multiple_review_targets_in_one_stage_are_distinct_and_all_checked(self):
        (self.root / 'additional.md').write_text('Additional requirement.\n')
        extra = copy.deepcopy(self.quality['stages'][0])
        extra['artifact'] = reference(self.root, 'additional.md')
        for check in extra['checks']:
            check['evidence'] = [reference(self.root, 'additional.md', 'Additional requirement.')]
        self.quality['stages'].append(extra)
        self.assertTrue(check_quality(self.quality, self.root, stages=['L3'])['ready'])
        duplicate = copy.deepcopy(self.quality)
        duplicate['stages'].append(copy.deepcopy(extra))
        self.assertFalse(check_quality(duplicate, self.root)['valid'])
        extra['checks'][0].update(verdict='gap', reason='Additional rule unresolved.')
        result = check_quality(self.quality, self.root, stages=['L3'])
        self.assertTrue(result['valid'], result)
        self.assertFalse(result['ready'])
        self.assertEqual(result['gaps'][0]['artifact'], 'additional.md')
        (self.root / 'additional.md').write_text('Changed after review.\n')
        self.assertFalse(check_quality(self.quality, self.root)['valid'])

    def test_gaps_and_unresolved_decisions_block_only_selected_stages(self):
        item = copy.deepcopy(self.quality['stages'][0]); item['stage'] = 'L2'
        item['checks'] = [{'id': key, 'verdict': 'gap', 'reason': 'No owner decision yet.', 'evidence': []} for key in STAGE_CHECKS['L2']]
        item['open_decisions'] = [{'question': 'Which scope?', 'owner': 'business-owner', 'next_action': 'Confirm scope'}]
        self.quality['stages'].append(item)
        self.assertFalse(check_quality(self.quality, self.root)['ready'])
        self.assertTrue(check_quality(self.quality, self.root, stages=['L3'])['ready'])
        self.assertFalse(check_quality(self.quality, self.root, stages=['L4'])['ready'])

    def test_stale_artifact_or_citation_and_external_paths_are_rejected(self):
        (self.root / 'prd.md').write_text('different bytes')
        self.assertFalse(check_quality(self.quality, self.root)['ready'])
        for relative in ('../outside.md', '/etc/passwd'):
            data = copy.deepcopy(self.quality)
            data['stages'][0]['artifact']['path'] = relative
            self.assertFalse(check_quality(data, self.root)['ready'])

    def test_trace_requires_actual_current_result_for_each_acceptance(self):
        self.assertTrue(check_trace(self.trace, self.execution(), self.root)['ready'])
        self.assertFalse(check_trace(self.trace, None, self.root)['ready'])
        for status in ('skipped', 'failed', 'blocked', 'not_run', 'expected_failure'):
            receipt = self.execution(); receipt['cases'][0]['status'] = status
            self.assertFalse(check_trace(self.trace, receipt, self.root)['ready'])
        receipt = self.execution(); receipt['cases'] = []
        self.assertFalse(check_trace(self.trace, receipt, self.root)['ready'])

    def test_coverage_missing_wrong_versions_and_duplicate_ids_are_rejected(self):
        for mutate in (lambda d: d['tests'][0].update(covers=[]),
                       lambda d: d['tests'][0]['covers'][0].update(version=2),
                       lambda d: d['acceptance'][0]['requirements'][0].update(id='FR-missing'),
                       lambda d: d['acceptance'].append(copy.deepcopy(d['acceptance'][0]))):
            data = copy.deepcopy(self.trace); mutate(data)
            self.assertFalse(check_trace(data, self.execution(), self.root)['ready'])

    def test_all_mapped_tests_must_pass_not_just_one_happy_path(self):
        self.trace['tests'].append(dict(self.trace['tests'][0], id='test_cases.Tests.test_boundary'))
        receipt = self.execution()
        receipt['cases'].append(dict(receipt['cases'][0], id='test_cases.Tests.test_boundary', status='failed'))
        self.assertFalse(check_trace(self.trace, receipt, self.root)['ready'])

    def test_mapping_build_environment_or_sources_cannot_reuse_old_receipt(self):
        receipt = self.execution(); receipt['schema_version'] = True
        self.assertFalse(check_trace(self.trace, receipt, self.root)['ready'])
        for field in ('build', 'environment', 'scope', 'trace_sha256', 'runner_sha256'):
            receipt = self.execution(); receipt[field] = 'different'
            self.assertFalse(check_trace(self.trace, receipt, self.root)['ready'])
        receipt = self.execution(); receipt['source_unchanged'] = False
        self.assertFalse(check_trace(self.trace, receipt, self.root)['ready'])
        (self.root / 'test_cases.py').write_text('changed test')
        self.assertFalse(check_trace(self.trace, self.execution(), self.root)['ready'])

    def test_unittest_collector_records_each_real_case_and_skip(self):
        trace = self.root / 'trace.json'; trace.write_text(json.dumps(self.trace))
        output = self.root / 'execution.json'
        argv = [sys.executable, str(ROOT / 'scripts/lifecycle_test_runner.py'), '--root', str(self.root),
                '--tests', '.', '--trace', 'trace.json', '--output', str(output)]
        result = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(output.read_text())
        self.assertTrue(check_trace(self.trace, receipt, self.root)['ready'])
        self.assertEqual(receipt['cases'][0]['id'], 'test_cases.Tests.test_ok')
        original_receipt = output.read_bytes()
        repeated = subprocess.run(argv, capture_output=True, text=True)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertEqual(output.read_bytes(), original_receipt)
        test = self.root / 'test_cases.py'
        test.write_text(test.read_text().replace('class Tests', '@unittest.skip("fixture skip")\nclass Tests'))
        self.trace['tests'][0]['source'] = reference(self.root, 'test_cases.py')
        trace.write_text(json.dumps(self.trace))
        output = self.root / 'execution-skipped.json'
        argv[-1] = str(output)
        result = subprocess.run(argv, capture_output=True, text=True)
        receipt = json.loads(output.read_text())
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(check_trace(self.trace, receipt, self.root)['ready'])
        self.assertEqual(receipt['cases'][0]['status'], 'skipped')

    def handoff(self):
        return handoff(self.root, self.quality, self.trace, self.execution())

    def test_handoff_binds_identity_revision_and_all_required_sources(self):
        packet, state, quality = self.handoff()
        self.assertTrue(check_handoff(packet, self.root)['ready'])
        missing_review = copy.deepcopy(quality)
        missing_review['stages'] = missing_review['stages'][:1]
        (self.root / 'quality.json').write_text(json.dumps(missing_review))
        incomplete = copy.deepcopy(packet)
        incomplete['quality'] = reference(self.root, 'quality.json')
        incomplete['files'] = [incomplete['quality'] if item['path'] == 'quality.json' else item for item in incomplete['files']]
        self.assertFalse(check_handoff(incomplete, self.root)['ready'])
        (self.root / 'quality.json').write_text(json.dumps(quality))
        stale_state = copy.deepcopy(state)
        stale_state['artifacts'][0]['version'] = 2
        stale_state['artifacts'][0]['evidence'][0]['subject']['version'] = 2
        (self.root / 'lifecycle-record.json').write_text(json.dumps(stale_state))
        stale = copy.deepcopy(packet)
        stale['record'] = reference(self.root, 'lifecycle-record.json')
        stale['files'] = [stale['record'] if item['path'] == 'lifecycle-record.json' else item for item in stale['files']]
        self.assertFalse(check_handoff(stale, self.root)['ready'])
        (self.root / 'lifecycle-record.json').write_text(json.dumps(state))
        for mutate in (lambda d: d.update(subject_ref='other'), lambda d: d.update(record_revision=2),
                       lambda d: d.update(files=[entry for entry in d['files'] if entry['path'] != 'test_cases.py']),
                       lambda d: d['next_action'].update(owner='')):
            bad = copy.deepcopy(packet); mutate(bad)
            self.assertFalse(check_handoff(bad, self.root)['ready'])
        (self.root / 'prd.md').write_text('edited after handoff')
        self.assertFalse(check_handoff(packet, self.root)['ready'])

    def test_handoff_requires_linked_L6_execution_with_matching_context(self):
        from lifecycle_record import check_record
        packet, original, _ = self.handoff()
        for change in ('build', 'environment', 'scope', 'missing_context', 'unlinked', 'not_completed'):
            with self.subTest(change=change):
                state = copy.deepcopy(original)
                node = next(n for n in state['artifacts'] if n['stage'] == 'L6')
                if change in ('build', 'environment', 'scope'):
                    node[change] = 'different'
                    node['evidence'][0][change] = 'different'
                elif change == 'missing_context':
                    node.pop('build'); node['evidence'][0].pop('build')
                elif change == 'unlinked':
                    node['evidence'][0]['source'] = 'prd.md'
                else:
                    node['status'] = 'not_started'
                self.assertTrue(check_record(state)['valid'])
                self.assertFalse(check_record(state)['needs_review'])
                (self.root / 'lifecycle-record.json').write_text(json.dumps(state))
                candidate = copy.deepcopy(packet)
                candidate['record'] = reference(self.root, 'lifecycle-record.json')
                candidate['files'] = [candidate['record'] if e['path'] == 'lifecycle-record.json' else e for e in candidate['files']]
                result = check_handoff(candidate, self.root)
                self.assertFalse(result['ready'], change)
                if change != 'not_completed':
                    self.assertFalse(check_handoff(candidate, self.root, 'transfer')['ready'], change)

    def test_transfer_keeps_pending_effects_without_claiming_stage_completion(self):
        packet, state, quality = self.handoff()
        pending = copy.deepcopy(quality['stages'][0])
        pending['stage'] = 'L10'
        for check, identity in zip(pending['checks'], STAGE_CHECKS['L10']):
            check['id'] = identity
        pending['checks'][1].update(verdict='gap', reason='Real outcome data is not available.')
        pending['open_decisions'] = [{'question': 'Observe real outcomes', 'owner': 'business owner', 'next_action': 'Supply authorized data'}]
        (self.root / 'effects.md').write_text('Fixture: support instructions complete; actual outcome data unavailable.')
        effects = copy.deepcopy(state['artifacts'][-1])
        effects.update(id='effects', stage='L10', status='pending_confirmation', source='effects.md',
                       reason='Outcome data unavailable.', recovery='Observe authorized business data.')
        state['artifacts'].append(effects)
        state['branches'][0]['required'].append('effects')
        quality['stages'].append(pending)
        (self.root / 'quality.json').write_text(json.dumps(quality))
        (self.root / 'lifecycle-record.json').write_text(json.dumps(state))
        packet['quality'] = reference(self.root, 'quality.json')
        packet['record'] = reference(self.root, 'lifecycle-record.json')
        packet['files'] = [reference(self.root, ref['path']) for ref in packet['files']]
        packet['files'].append(reference(self.root, 'effects.md'))
        packet['next_action'].update(stage='L10', action='Observe outcomes when authorized data arrives.')
        (self.root / 'handoff.json').write_text(json.dumps(packet))
        packet['purpose'] = 'transfer'
        self.assertFalse(check_handoff(packet, self.root)['ready'])
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_quality.py'), 'handoff',
            '--root', str(self.root), '--contract', 'handoff.json', '--purpose', 'transfer'], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertTrue(result['ready'])
        self.assertEqual(result['purpose'], 'transfer')
        self.assertFalse(result['quality_ready'])
        self.assertTrue(result['tests_ready'])
        self.assertFalse(result['business_authorization'])
        self.assertTrue(result['gaps'])
        after = json.loads((self.root / 'lifecycle-record.json').read_text())
        self.assertEqual(next(n['status'] for n in after['artifacts'] if n['stage'] == 'L10'), 'pending_confirmation')

    def test_manual_only_transfer_never_claims_automated_test_success(self):
        packet, state, _ = self.handoff()
        node = next(n for n in state['artifacts'] if n['stage'] == 'L6')
        (self.root / 'manual.md').write_text('Fixture only: reviewer executed AC-01 with the declared build and scope. Passed.')
        node['evidence'][0].update(kind='confirmed', source='manual.md', actor='human-fixture')
        (self.root / 'lifecycle-record.json').write_text(json.dumps(state))
        packet['record'] = reference(self.root, 'lifecycle-record.json')
        packet.pop('trace'); packet.pop('execution')
        packet['files'] = [reference(self.root, ref['path']) for ref in packet['files']]
        packet['files'].append(reference(self.root, 'manual.md'))
        result = check_handoff(packet, self.root, 'transfer')
        self.assertTrue(result['ready'], result)
        self.assertIsNone(result['tests_ready'])
        self.assertFalse(result['business_authorization'])
        self.assertFalse(check_handoff(packet, self.root)['ready'])
        packet['trace'] = reference(self.root, 'trace.json')
        self.assertFalse(check_handoff(packet, self.root, 'transfer')['ready'])

    def test_failed_test_can_transfer_for_repair_but_cannot_advance(self):
        packet, state, quality = self.handoff()
        node = next(n for n in state['artifacts'] if n['stage'] == 'L6')
        node.update(status='blocked', reason='Test failed.', recovery='Repair and rerun.')
        node['evidence'][0]['result'] = 'failed'
        receipt = self.execution(); receipt['cases'][0]['status'] = 'failed'; receipt['exit_code'] = 1
        quality['stages'][-1]['checks'][-1].update(verdict='gap', reason='Current test failed.')
        for name, value in [('lifecycle-record.json', state), ('quality.json', quality), ('execution.json', receipt)]:
            (self.root / name).write_text(json.dumps(value))
        for key in ('record', 'quality', 'execution'):
            packet[key] = reference(self.root, packet[key]['path'])
        packet['files'] = [reference(self.root, ref['path']) for ref in packet['files']]
        packet['next_action'].update(stage='L6', action='Repair failed behavior and rerun.')
        result = check_handoff(packet, self.root, 'transfer')
        self.assertTrue(result['ready'], result)
        self.assertFalse(result['tests_ready'])
        self.assertFalse(result['quality_ready'])
        self.assertTrue(result['needs_review'])
        self.assertFalse(check_handoff(packet, self.root)['ready'])
        (self.root / 'prd.md').write_text('Changed after review.')
        self.assertFalse(check_handoff(packet, self.root, 'transfer')['ready'])
        self.assertFalse(check_handoff(packet, self.root, 'publish')['ready'])

    def test_transfer_does_not_hide_misbound_execution_evidence(self):
        packet, original, _ = self.handoff()
        for key in ('build', 'environment', 'scope'):
            with self.subTest(key=key):
                state = copy.deepcopy(original)
                node = next(n for n in state['artifacts'] if n['stage'] == 'L6')
                node['evidence'][0][key] = 'wrong-context'
                (self.root / 'lifecycle-record.json').write_text(json.dumps(state))
                candidate = copy.deepcopy(packet)
                candidate['record'] = reference(self.root, 'lifecycle-record.json')
                candidate['files'] = [reference(self.root, ref['path']) for ref in candidate['files']]
                self.assertFalse(check_handoff(candidate, self.root, 'transfer')['ready'])

    def test_empty_execution_is_not_ready_but_can_transfer_for_repair(self):
        (self.root / 'test_cases.py').write_text('# No tests discovered.\n')
        self.trace['tests'][0]['source'] = reference(self.root, 'test_cases.py')
        (self.root / 'trace.json').write_text(json.dumps(self.trace))
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_test_runner.py'),
            '--root', str(self.root), '--trace', 'trace.json', '--output', str(self.root / 'execution.json')],
            capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        receipt = json.loads((self.root / 'execution.json').read_text())
        self.assertEqual(receipt['cases'], [])
        result = check_trace(self.trace, receipt, self.root)
        self.assertTrue(result['valid'], result)
        self.assertFalse(result['ready'])
        packet, state, quality = handoff(self.root, self.quality, self.trace, receipt)
        node = next(n for n in state['artifacts'] if n['stage'] == 'L6')
        node.update(status='blocked', reason='No tests discovered.', recovery='Fix discovery and rerun.')
        node['evidence'][0]['result'] = 'failed'
        quality['stages'][-1]['checks'][-1].update(verdict='gap', reason='No tests executed.')
        for name, value in [('lifecycle-record.json', state), ('quality.json', quality)]:
            (self.root / name).write_text(json.dumps(value))
        packet['record'] = reference(self.root, 'lifecycle-record.json')
        packet['quality'] = reference(self.root, 'quality.json')
        packet['files'] = [reference(self.root, f['path']) for f in packet['files']]
        packet['next_action'].update(stage='L6', action='Fix test collection and rerun.')
        result = check_handoff(packet, self.root, 'transfer')
        self.assertTrue(result['ready'], result)
        self.assertFalse(result['tests_ready'])
        self.assertTrue(result['gaps'])
        self.assertFalse(check_handoff(packet, self.root)['ready'])
        receipt['exit_code'] = 0
        self.assertFalse(check_trace(self.trace, receipt, self.root)['ready'])

    def test_cross_file_test_implementation_is_not_silently_bound_to_child(self):
        (self.root / 'base_assertions.py').write_text('import unittest\nfrom app import value\nclass Base(unittest.TestCase):\n    def test_ok(self): self.assertEqual(value(), 3)\n')
        modes = {
            'inherited': 'import base_assertions\nclass Tests(base_assertions.Base): pass\n',
            'decorated': 'import unittest\nfrom unittest.mock import patch\nclass Tests(unittest.TestCase):\n    @patch("app.value", return_value=3)\n    def test_ok(self, value): self.assertEqual(value(), 3)\n',
        }
        for mode, code in modes.items():
            with self.subTest(mode=mode):
                (self.root / 'test_cases.py').write_text(code)
                self.trace['tests'][0]['source'] = reference(self.root, 'test_cases.py')
                (self.root / 'trace.json').write_text(json.dumps(self.trace))
                output = self.root / f'{mode}.json'
                process = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_test_runner.py'),
                    '--root', str(self.root), '--trace', 'trace.json', '--output', str(output)], capture_output=True, text=True)
                receipt = json.loads(output.read_text())
                if mode == 'inherited':
                    self.assertNotEqual(process.returncode, 0, 'unbound inherited assertions must not pass the collection gate')
                    self.assertEqual(receipt['cases'][0]['status'], 'passed', 'preserve the real unittest outcome')
                    self.assertTrue(receipt['cases'][0].get('binding_error'))
                    checked = check_trace(self.trace, receipt, self.root)
                    self.assertTrue(checked['valid'], checked)
                    self.assertFalse(checked['ready'])
                    packet, state, quality = handoff(self.root, self.quality, self.trace, receipt)
                    node = next(n for n in state['artifacts'] if n['stage'] == 'L6')
                    node.update(status='blocked', reason='Implementation binding uncovered.', recovery='Use project test evidence.')
                    node['evidence'][0]['result'] = 'blocked'
                    quality['stages'][-1]['checks'][-1].update(verdict='gap', reason='Implementation binding uncovered.')
                    for name, value in [('lifecycle-record.json', state), ('quality.json', quality)]:
                        (self.root / name).write_text(json.dumps(value))
                    packet['record'] = reference(self.root, 'lifecycle-record.json')
                    packet['quality'] = reference(self.root, 'quality.json')
                    packet['files'] = [reference(self.root, ref['path']) for ref in packet['files']]
                    packet['next_action'].update(stage='L6', action='Resolve unbound implementation source.')
                    transferred = check_handoff(packet, self.root, 'transfer')
                    self.assertTrue(transferred['ready'], transferred)
                    self.assertFalse(transferred['tests_ready'])
                    self.assertFalse(check_handoff(packet, self.root)['ready'])
                else:
                    self.assertEqual(process.returncode, 0, process.stderr)
                    self.assertTrue(check_trace(self.trace, receipt, self.root)['ready'])

    def test_source_binding_respects_unmapped_tests_and_optional_skips(self):
        (self.root / 'base_assertions.py').write_text('import unittest\nclass Base(unittest.TestCase):\n    def test_extra(self): self.assertTrue(True)\n')
        for mode in ('unmapped', 'optional_skip'):
            with self.subTest(mode=mode):
                decorator = '@unittest.skip("not in current scope")\n' if mode == 'optional_skip' else ''
                code = 'import unittest\nimport base_assertions\n' + decorator + 'class Extra(base_assertions.Base): pass\nclass Tests(unittest.TestCase):\n    def test_ok(self): self.assertEqual(3, 3)\n'
                (self.root / 'test_cases.py').write_text(code)
                trace = copy.deepcopy(self.trace)
                trace['tests'][0]['source'] = reference(self.root, 'test_cases.py')
                if mode == 'optional_skip':
                    trace['acceptance'].append(dict(trace['acceptance'][0], id='AC-optional', required=False))
                    trace['tests'].append(dict(trace['tests'][0], id='test_cases.Extra.test_extra', covers=[{'id':'AC-optional','version':1}]))
                (self.root / 'trace.json').write_text(json.dumps(trace))
                output = self.root / f'{mode}.json'
                process = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_test_runner.py'),
                    '--root', str(self.root), '--trace', 'trace.json', '--output', str(output)], capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stderr)
                receipt = json.loads(output.read_text())
                self.assertTrue(check_trace(trace, receipt, self.root)['ready'])

    def test_shared_receipt_cannot_hide_a_conflicting_L6_branch(self):
        packet, state, quality = self.handoff()
        node = copy.deepcopy(next(n for n in state['artifacts'] if n['stage'] == 'L6'))
        node['id'] = 'other-test'
        node['evidence'][0]['subject']['id'] = node['id']
        node['build'] = 'other-build'; node['evidence'][0]['build'] = node['build']
        state['artifacts'].append(node)
        (self.root / 'lifecycle-record.json').write_text(json.dumps(state))
        packet['record'] = reference(self.root, 'lifecycle-record.json')
        packet['files'] = [reference(self.root, ref['path']) for ref in packet['files']]
        self.assertFalse(check_handoff(packet, self.root)['ready'])
        # A different execution context is independent when it does not claim this receipt.
        node['evidence'][0]['source'] = 'other-execution.json'
        (self.root / 'other-execution.json').write_text('Fixture: independent test run.')
        (self.root / 'lifecycle-record.json').write_text(json.dumps(state))
        packet['record'] = reference(self.root, 'lifecycle-record.json')
        packet['files'] = [reference(self.root, ref['path']) for ref in packet['files']]
        packet['files'].append(reference(self.root, 'other-execution.json'))
        self.assertTrue(check_handoff(packet, self.root)['ready'])

    def test_collector_blocks_subtest_failure_expected_failure_and_source_mutation(self):
        original_app = (self.root / 'app.py').read_text()
        modes = {
            'subtest': 'import unittest\nclass Tests(unittest.TestCase):\n    def test_ok(self):\n        with self.subTest(value=1):\n            self.assertEqual(1, 2)\n',
            'expected': 'import unittest\nclass Tests(unittest.TestCase):\n    @unittest.expectedFailure\n    def test_ok(self):\n        self.assertEqual(1, 2)\n',
            'error': 'import missing_business_dependency\n',
            'zero': '# no executable test cases\n',
            'failure': 'import unittest\nclass Tests(unittest.TestCase):\n    def test_ok(self):\n        self.assertEqual(1, 2)\n',
            'unexpected': 'import unittest\nclass Tests(unittest.TestCase):\n    @unittest.expectedFailure\n    def test_ok(self):\n        self.assertTrue(True)\n',
            'trace_mutation': 'import unittest\nfrom pathlib import Path\nclass Tests(unittest.TestCase):\n    def test_ok(self):\n        Path(__file__).with_name("trace.json").write_text("{")\n        self.assertTrue(True)\n',
            'mutation': 'import unittest\nfrom pathlib import Path\nclass Tests(unittest.TestCase):\n    def test_ok(self):\n        Path(__file__).with_name("app.py").write_text("changed during test")\n        self.assertTrue(True)\n',
        }
        for mode, content in modes.items():
            with self.subTest(mode=mode):
                (self.root / 'app.py').write_text(original_app)
                (self.root / 'test_cases.py').write_text(content)
                self.trace['tests'][0]['source'] = reference(self.root, 'test_cases.py')
                (self.root / 'trace.json').write_text(json.dumps(self.trace))
                output = self.root / f'{mode}-execution.json'
                process = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_test_runner.py'),
                    '--root', str(self.root), '--tests', '.', '--trace', 'trace.json', '--output', str(output)], capture_output=True, text=True)
                self.assertNotEqual(process.returncode, 0, process.stdout)
                receipt = json.loads(output.read_text())
                self.assertFalse(check_trace(self.trace, receipt, self.root)['ready'])
                if mode in ('mutation', 'trace_mutation'):
                    self.assertFalse(receipt['source_unchanged'])

    def test_optional_skipped_acceptance_does_not_hide_a_mandatory_result(self):
        self.trace['acceptance'].append(dict(self.trace['acceptance'][0], id='AC-optional', required=False))
        self.trace['tests'].append(dict(self.trace['tests'][0], id='optional', covers=[{'id': 'AC-optional', 'version': 1}]))
        receipt = self.execution()
        receipt['cases'].append({'id': 'optional', 'status': 'skipped', 'source': reference(self.root, 'test_cases.py')})
        self.assertTrue(check_trace(self.trace, receipt, self.root)['ready'])
        receipt['cases'].append(copy.deepcopy(receipt['cases'][0]))
        self.assertFalse(check_trace(self.trace, receipt, self.root)['ready'])

    def test_collector_identity_includes_its_shared_validation_code(self):
        receipt = self.execution()
        tool = self.root / 'lifecycle_quality.py'
        tool.write_bytes((ROOT / 'scripts/lifecycle_quality.py').read_bytes())
        (self.root / 'lifecycle_test_runner.py').write_bytes((ROOT / 'scripts/lifecycle_test_runner.py').read_bytes())
        with patch('lifecycle_quality.__file__', str(tool)):
            self.assertTrue(check_trace(self.trace, receipt, self.root)['ready'])
            tool.write_bytes(tool.read_bytes() + b'\n# changed validation code\n')
            self.assertFalse(check_trace(self.trace, receipt, self.root)['ready'])

    def test_in_scope_requirement_cannot_hide_behind_optional_acceptance(self):
        self.trace['requirements'].append(dict(self.trace['requirements'][0], id='FR-optional'))
        self.trace['acceptance'].append(dict(self.trace['acceptance'][0], id='AC-optional', required=False,
            requirements=[{'id': 'FR-optional', 'version': 1}]))
        self.assertFalse(check_trace(self.trace, self.execution(), self.root)['ready'])

    def test_current_trace_cannot_reuse_receipt_after_acceptance_version_change(self):
        receipt = self.execution()
        self.trace['acceptance'][0]['version'] = 2
        self.trace['tests'][0]['covers'][0]['version'] = 2
        self.assertFalse(check_trace(self.trace, receipt, self.root)['ready'])

    def test_cli_reports_real_findings_without_writing_contract(self):
        contract = self.root / 'quality.json'; contract.write_text(json.dumps(self.quality))
        before = contract.read_bytes()
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_quality.py'), 'quality',
                                 '--root', str(self.root), '--contract', 'quality.json'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(json.loads(result.stdout)['ready'])
        self.assertEqual(contract.read_bytes(), before)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/lifecycle_quality.py'), 'quality',
                                 '--root', str(self.root), '--contract', '../missing.json'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_malformed_contracts_return_findings(self):
        for data in (None, [], {}, {'schema_version': 2}, dict(self.trace, tests=[True])):
            self.assertFalse(check_trace(data, None, self.root)['ready'])
        for data in (None, [], {}, dict(self.quality, stages=[True])):
            self.assertFalse(check_quality(data, self.root)['ready'])


if __name__ == '__main__':
    unittest.main()
