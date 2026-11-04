"""Frozen checkpoint and fresh-process continuation regressions. 作者：Jeff.Liu"""
import copy
import hashlib
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest

from lifecycle_quality import check_handoff, check_trace, reference
import test_lifecycle_quality as fixtures

REPOSITORY = Path(__file__).resolve().parents[1]
EXAMPLE = REPOSITORY / 'skills/project-docs-lifecycle/assets/examples/open-case'


class HandoffTests(unittest.TestCase):
    def test_declared_fact_conflict_is_not_hidden_by_passed_technical_checks(self):
        for confirmation in ('conflicted', 'unconfirmed', 'confirmed'):
            state = json.loads((self.root / 'lifecycle-record.json').read_text())
            assertion = dict(text='Requester and operator disagree on status freshness.',
                             classification='business_feedback', source='prd.md', owner='business-owner',
                             confirmation=confirmation)
            if confirmation == 'confirmed':
                assertion.update(confirmed_by='fixture-operator', at='2026-10-31T10:00:00+08:00', applies_to='R1/v1')
            state['assertions'] = [assertion]
            packet = self.alternate('record', state)
            before = (self.root / packet['record']['path']).read_bytes()
            for purpose in ('tested', 'transfer'):
                with self.subTest(confirmation=confirmation, purpose=purpose):
                    result = check_handoff(packet, self.root, purpose=purpose)
                    self.assertTrue(result['ready'], result)
                    self.assertTrue(result['tests_ready'])
                    self.assertFalse(result['business_authorization'])
                    conflicts = [gap for gap in result['gaps'] if isinstance(gap, dict) and 'assertion' in gap]
                    expected = [{'assertion': assertion['text'], 'confirmation': 'conflicted',
                                 'classification': assertion['classification'], 'source': assertion['source'],
                                 'owner': assertion['owner']}] if confirmation == 'conflicted' else []
                    self.assertEqual(conflicts, expected)
            self.assertEqual((self.root / packet['record']['path']).read_bytes(), before)

    def test_blocked_or_pending_acceptance_is_visible_without_invalidating_L6(self):
        for status in ('blocked', 'pending_confirmation'):
            state = json.loads((self.root / 'lifecycle-record.json').read_text())
            node = next(n for n in state['artifacts'] if n['stage'] == 'L7')
            node.update(status=status, reason='Business owner unavailable', recovery='Arrange acceptance with the owner')
            packet = self.alternate('record', state)
            for purpose in ('tested', 'transfer'):
                with self.subTest(status=status, purpose=purpose):
                    result = check_handoff(packet, self.root, purpose=purpose)
                    self.assertTrue(result['ready'], result)
                    self.assertTrue(result['tests_ready'])
                    self.assertFalse(result['business_authorization'])
                    self.assertIn({'id': node['id'], 'stage': 'L7', 'version': node['version'],
                                   'artifact': node['source'], 'status': status, 'owner': node['owner'],
                                   'reason': node['reason'], 'recovery': node['recovery']}, result['gaps'])
                    self.assertEqual(result['next_action'], packet['next_action'])

    def test_cli_does_not_import_a_stale_record_validator(self):
        validator = self.root / 'validator'
        validator.mkdir()
        for name in ('lifecycle_quality.py', 'lifecycle_test_runner.py', 'lifecycle_record.py'):
            shutil.copy(REPOSITORY / 'scripts' / name, validator / name)
        source = validator / 'lifecycle_record.py'
        actual = source.read_bytes()
        stub = b"def check_record(data): return {'valid': True, 'needs_review': []}\n#"
        source.write_bytes(stub + b' ' * (len(actual) - len(stub)))
        stat = source.stat()
        py_compile.compile(str(source), doraise=True)
        source.write_bytes(actual)
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        state = json.loads((self.root / 'lifecycle-record.json').read_text())
        state['artifacts'][0]['evidence'][0]['result'] = 'failed'
        packet = self.alternate('record', state)
        (self.root / 'handoff.json').write_text(json.dumps(packet))
        before = {p.name: p.read_bytes() for p in (validator / '__pycache__').iterdir()}
        process = subprocess.run([sys.executable, '-B', str(validator / 'lifecycle_quality.py'), 'handoff',
            '--root', str(self.root), '--contract', 'handoff.json'], capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 1, process.stdout)
        self.assertFalse(json.loads(process.stdout)['ready'])
        self.assertEqual({p.name: p.read_bytes() for p in (validator / '__pycache__').iterdir()}, before)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='lifecycle-handoff-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'checkpoint'
        self.root.mkdir()
        quality, trace = fixtures.scenario(self.root)
        (self.root / 'trace.json').write_text(json.dumps(trace))
        process = subprocess.run([sys.executable, str(REPOSITORY / 'scripts/lifecycle_test_runner.py'),
                                  '--root', str(self.root), '--trace', 'trace.json',
                                  '--output', str(self.root / 'execution.json')],
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        receipt = json.loads((self.root / 'execution.json').read_text())
        self.packet, _, _ = fixtures.handoff(self.root, quality, trace, receipt)
        (self.root / 'handoff.json').write_text(json.dumps(self.packet))

    def alternate(self, key, value):
        path = f'alternate-{key}.json'
        (self.root / path).write_text(json.dumps(value))
        packet = copy.deepcopy(self.packet)
        packet[key] = reference(self.root, path)
        packet['files'].append(packet[key])
        return packet

    def test_fresh_isolated_process_resumes_identity_and_preserves_frozen_sources(self):
        self.assertTrue(check_handoff(self.packet, self.root)['ready'])
        before = {item['path']: (self.root / item['path']).read_bytes() for item in self.packet['files']}
        script = '''import hashlib,json,shutil,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from lifecycle_quality import check_handoff
from lifecycle_record import update_record
source=Path(sys.argv[2]); packet=json.loads((source/'handoff.json').read_text())
checked=check_handoff(packet,source)
assert checked['ready'], checked
work=source.parent/'resumed'; shutil.copytree(source,work)
path=work/packet['record']['path']; state=json.loads(path.read_text())
identity=(state['project_ref'],state['subject_ref']); revision=state['revision']
assert packet['next_action']['stage']=='L7'
node=next(item for item in state['artifacts'] if item['stage']=='L7')
node['owner']='fresh-process-simulated-operator'
state['revision']+=1; state['updated_at']=datetime.now(timezone.utc).isoformat()
update_record(path,state,revision)
assert (state['project_ref'],state['subject_ref'])==identity
assert hashlib.sha256((work/packet['prd']['path']).read_bytes()).hexdigest()==packet['prd']['sha256']
assert path.with_name(path.name+f'.rev-{revision}.json').is_file()
print(json.dumps({'identity':identity,'revision':state['revision']}))
'''
        process = subprocess.run([sys.executable, '-I', '-c', script, str(REPOSITORY / 'scripts'), str(self.root)],
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        receipt = json.loads(process.stdout)
        self.assertEqual(receipt['identity'], [self.packet['project_ref'], self.packet['subject_ref']])
        self.assertEqual(receipt['revision'], self.packet['record_revision'] + 1)
        for path, content in before.items():
            self.assertEqual((self.root / path).read_bytes(), content, path)
        self.assertTrue(check_handoff(self.packet, self.root)['ready'])

    def test_cli_handoff_check_does_not_create_import_caches_in_frozen_directory(self):
        validator = self.root / 'validator'
        validator.mkdir()
        for name in ('lifecycle_quality.py', 'lifecycle_test_runner.py', 'lifecycle_record.py'):
            shutil.copy(REPOSITORY / 'scripts' / name, validator / name)
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        process = subprocess.run([sys.executable, '-E', str(validator / 'lifecycle_quality.py'), 'handoff',
                                  '--root', str(self.root), '--contract', 'handoff.json'],
                                 capture_output=True, text=True, timeout=20)
        self.assertIn(process.returncode, (0, 1), process.stderr)
        self.assertIn('ready', json.loads(process.stdout))
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(set(after), set(before), 'read-only validation must not add Python import caches')
        self.assertEqual(after, before)

    def test_actual_case_cannot_hide_a_skipped_test_or_missing_stage_review(self):
        execution = json.loads((self.root / self.packet['execution']['path']).read_text())
        execution['cases'][0]['status'] = 'skipped'
        result = check_handoff(self.alternate('execution', execution), self.root)
        self.assertFalse(result['ready'])
        self.assertIn('test evidence', str(result['errors']))
        quality = json.loads((self.root / self.packet['quality']['path']).read_text())
        quality['stages'] = [entry for entry in quality['stages'] if entry['stage'] != 'L6']
        result = check_handoff(self.alternate('quality', quality), self.root)
        self.assertFalse(result['ready'])
        self.assertIn('omits completed stage reviews', str(result['errors']))

    def test_open_case_acceptance_is_reexecuted_with_current_tools(self):
        root = self.root.parent / 'business-case'
        root.mkdir()
        for name in ('app', 'tests', 'sources'):
            shutil.copytree(EXAMPLE / name, root / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name in ('prd.md', 'prd-traceability.md', 'trace.json'):
            shutil.copy(EXAMPLE / name, root / name)
        process = subprocess.run([sys.executable, str(REPOSITORY / 'scripts/lifecycle_test_runner.py'),
                                  '--root', str(root), '--tests', 'tests', '--trace', 'trace.json',
                                  '--output', str(root / 'execution-current.json')],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        trace = json.loads((root / 'trace.json').read_text())
        receipt = json.loads((root / 'execution-current.json').read_text())
        self.assertTrue(check_trace(trace, receipt, root)['ready'])
        self.assertEqual({case['id'] for case in receipt['cases']}, {case['id'] for case in trace['tests']})
        self.assertTrue(all(case['status'] == 'passed' for case in receipt['cases']))

    def test_other_subject_or_changed_primary_prd_cannot_resume(self):
        packet = copy.deepcopy(self.packet)
        packet['subject_ref'] = 'another-request'
        self.assertFalse(check_handoff(packet, self.root)['ready'])
        path = self.root / self.packet['prd']['path']
        original = path.read_bytes()
        path.write_bytes(original + b'\nChanged after handoff\n')
        self.assertFalse(check_handoff(self.packet, self.root)['ready'])
        self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), self.packet['prd']['sha256'])

    def test_review_of_another_prd_cannot_cover_the_recorded_requirement(self):
        (self.root / 'other-prd.md').write_text('Different business scope.\n')
        quality = json.loads((self.root / 'quality.json').read_text())
        entry = next(e for e in quality['stages'] if e['stage'] == 'L3')
        entry['artifact'] = reference(self.root, 'other-prd.md')
        for check in entry['checks']:
            check['evidence'] = [reference(self.root, 'other-prd.md', 'Different business scope.')]
        packet = self.alternate('quality', quality)
        packet['files'].append(reference(self.root, 'other-prd.md'))
        for purpose in ('tested', 'transfer'):
            with self.subTest(purpose=purpose):
                result = check_handoff(packet, self.root, purpose=purpose)
                self.assertFalse(result['valid'], result)
                self.assertFalse(result['ready'])

    def test_same_stage_artifacts_each_need_an_explicit_review_target(self):
        (self.root / 'additional.md').write_text('Additional current requirement.\n')
        state = json.loads((self.root / 'lifecycle-record.json').read_text())
        extra = copy.deepcopy(next(n for n in state['artifacts'] if n['stage'] == 'L3'))
        extra.update(id='additional', source='additional.md')
        extra['evidence'][0]['subject']['id'] = 'additional'
        state['artifacts'].append(extra)
        state['branches'][0]['required'].append('additional')
        packet = self.alternate('record', state)
        packet['files'].append(reference(self.root, 'additional.md'))
        quality = json.loads((self.root / 'quality.json').read_text())
        primary = next(e for e in quality['stages'] if e['stage'] == 'L3')
        citation = reference(self.root, 'additional.md', 'Additional current requirement.')
        primary['checks'][0]['evidence'].append(citation)
        # A supporting citation is not a declaration that this artifact was reviewed.
        for reviewed in (False, True):
            if reviewed:
                review = copy.deepcopy(primary)
                review['artifact'] = reference(self.root, 'additional.md')
                for check in review['checks']:
                    check['evidence'] = [citation]
                quality['stages'].append(review)
            (self.root / 'quality.json').write_text(json.dumps(quality))
            candidate = copy.deepcopy(packet)
            candidate['quality'] = reference(self.root, 'quality.json')
            candidate['files'] = [candidate['quality'] if e['path'] == 'quality.json' else e for e in packet['files']]
            for purpose in ('tested', 'transfer'):
                with self.subTest(reviewed=reviewed, purpose=purpose):
                    self.assertEqual(check_handoff(candidate, self.root, purpose=purpose)['ready'], reviewed)
        for check in review['checks']:
            check.update(verdict='gap', reason='Additional requirement awaits content review.', evidence=[])
        (self.root / 'quality.json').write_text(json.dumps(quality))
        candidate['quality'] = reference(self.root, 'quality.json')
        candidate['files'] = [candidate['quality'] if e['path'] == 'quality.json' else e for e in packet['files']]
        self.assertFalse(check_handoff(candidate, self.root)['ready'])
        transfer = check_handoff(candidate, self.root, purpose='transfer')
        self.assertTrue(transfer['ready'], transfer)
        self.assertFalse(transfer['quality_ready'])
        self.assertEqual(transfer['gaps'][0]['artifact'], 'additional.md')


if __name__ == '__main__':
    unittest.main()
