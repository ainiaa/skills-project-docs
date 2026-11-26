"""Requirement revisions invalidate only declared dependent evidence. 作者：Jeff.Liu"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

import test_product_handoff as fixtures
import test_lifecycle_record as lifecycle_fixtures
from lifecycle_record import check_record, update_record
from product_inputs import freeze_inputs


class ProductRevisionTests(unittest.TestCase):
    def setUp(self):
        fixtures.ProductHandoffTests.setUp(self)
        self.prd.write_text(self.prd.read_text()+'''
### SRC-002 另一来源
名称编辑的既有决定。
### FR-002 编辑名称
状态：已确认
依据：SRC-002
原型：否
确认记录：业务负责人 产品版本 v1
#### AC-002 编辑成功
给定有效名称，保存后显示新名称。
''')
        self.before=freeze_inputs(self.prd)
        data=lifecycle_fixtures.record()
        independent=copy.deepcopy(data['artifacts'][0])
        independent.update(id='other',branch='independent',depends_on=[])
        independent['evidence'][0]['subject']['id']='other'
        data['artifacts'].append(independent)
        data['branches'].append({'id':'independent','route':'configuration','required':['other']})
        self.record_path=self.root/'lifecycle.json'
        self.record_path.write_text(json.dumps(data))
        self.bindings={'FR-001':['requirement'],'FR-002':['other']}

    def changed(self):
        self.prd.write_text(self.prd.read_text().replace('产品版本：v1','产品版本：v2').replace('产品版本 v1','产品版本 v2').replace('显示当前状态。','显示状态和更新时间。'))
        return freeze_inputs(self.prd)

    def plan(self, after=None, record=True):
        from product_revision import plan_revision
        return plan_revision(self.before,after or self.changed(),record_path=self.record_path if record else None,
                             bindings=self.bindings if record else None)

    def test_changed_source_bytes_with_same_rule_do_not_require_a_scope_decision(self):
        from test_product_inputs import ProductInputsTests
        from product_revision import plan_revision
        from lifecycle_quality import reference
        ProductInputsTests.project_index(self)
        before = freeze_inputs(self.prd)
        source = self.root / 'decisions.md'
        old_hash = reference(self.root, source.name)['sha256']
        source.write_text(source.read_text() + '\nUnrelated editorial note.\n')
        new_hash = reference(self.root, source.name)['sha256']
        self.prd.write_text(self.prd.read_text().replace(old_hash, new_hash))
        report = plan_revision(before, freeze_inputs(self.prd))
        self.assertTrue(report['scope_ready'])
        self.assertEqual(report['changes']['project_checks']['unchanged'], ['PROJECT-KEEP-ID'])

    def test_project_scope_changes_require_a_frozen_decision_and_affect_only_owning_requirement(self):
        from test_product_inputs import ProductInputsTests
        from product_revision import plan_revision, apply_impact
        ProductInputsTests.project_index(self)
        before = freeze_inputs(self.prd)
        original = self.prd.read_text()
        self.prd.write_text(original.replace('"required": true', '"required": false'))
        after = freeze_inputs(self.prd)
        report = plan_revision(before, after, record_path=self.record_path, bindings=self.bindings)
        self.assertIn('scope_ready', report, 'project scope changes are not reconciled')
        self.assertFalse(report['scope_ready'])
        self.assertEqual(report['affected_requirements'], ['FR-001'])
        prior = self.record_path.read_bytes()
        with self.assertRaises(ValueError):
            apply_impact(report)
        self.assertEqual(self.record_path.read_bytes(), prior)
        from product_handoff import prepare_revision
        with patch('product_handoff._require_capability'), self.assertRaisesRegex(ValueError, 'scope'):
            prepare_revision({}, {'converge_root': self.root}, report)
        from product_handoff import _validate_iteration
        previous = {key: '' for key in ('path', 'baseline', 'target', 'product_version', 'requirements', 'acceptance')}
        with patch('product_handoff._require_capability'), self.assertRaisesRegex(ValueError, 'scope'):
            _validate_iteration({'converge_root': self.root}, {'previous': previous, 'business_target': 'REQ',
                                                             'completion': {}, 'impact': report})
        # The decision lives in the newly frozen input, not in the mutable report.
        from lifecycle_quality import reference
        source = self.root / 'decisions.md'
        source.write_text('Keep request identifiers.\nBusiness decided this check is optional in v2.\n')
        content = original.replace('"required": true', '"required": false')
        old_source = before['project_checks']['PROJECT-KEEP-ID']['source']['sha256']
        content = content.replace(old_source, reference(self.root, source.name)['sha256'])
        from product_inputs import digest
        self.prd.write_text(content)
        changed_scope = freeze_inputs(self.prd)['project_checks']['PROJECT-KEEP-ID']
        decision = {'id': 'PROJECT-KEEP-ID', 'reason': 'Approved scope reduction.',
                    'before': digest(before['project_checks']['PROJECT-KEEP-ID']), 'after': digest(changed_scope),
                    'source': reference(self.root, source.name, 'Business decided this check is optional in v2.')}
        content = content.replace('"changes": []', '"changes": ' + json.dumps([decision]))
        self.prd.write_text(content)
        approved = plan_revision(before, freeze_inputs(self.prd))
        self.assertTrue(approved['scope_ready'], approved)
        self.assertEqual(approved['changes']['project_checks']['modified'], ['PROJECT-KEEP-ID'])
        # The same decision cannot certify a different later definition.
        self.prd.write_text(content.replace('"method": "review"', '"method": "test"'))
        replay = plan_revision(before, freeze_inputs(self.prd))
        self.assertFalse(replay['scope_ready'], 'an old decision was reused for another scope change')

    def test_project_rule_removal_without_a_decision_is_a_scope_gap(self):
        from test_product_inputs import ProductInputsTests
        from product_revision import plan_revision
        ProductInputsTests.project_index(self)
        before = freeze_inputs(self.prd)
        text = self.prd.read_text()
        start = text.index('```project-checks')
        end = text.index('```', start + 3) + 3
        self.prd.write_text(text[:start] + text[end:])
        report = plan_revision(before, freeze_inputs(self.prd))
        self.assertIn('scope_ready', report, 'removal is not checked')
        self.assertFalse(report['scope_ready'])
        self.assertIn('PROJECT-KEEP-ID', str(report['scope_gaps']))
        from lifecycle_quality import reference
        source = self.root / 'decisions.md'
        source.write_text('Business withdraws the identifier check for v2.\n')
        from product_inputs import digest
        decision = {'id': 'PROJECT-KEEP-ID', 'reason': 'Scope withdrawn by business.',
                    'before': digest(before['project_checks']['PROJECT-KEEP-ID']), 'after': None,
                    'source': reference(self.root, source.name, 'Business withdraws the identifier check for v2.')}
        self.prd.write_text(self.prd.read_text() + '\n```project-checks\n'
                            + json.dumps({'items': [], 'changes': [decision]}) + '\n```\n')
        approved = plan_revision(before, freeze_inputs(self.prd))
        self.assertTrue(approved['scope_ready'])
        self.assertEqual(approved['changes']['project_checks']['removed'], ['PROJECT-KEEP-ID'])

    def test_old_revision_report_without_project_scope_fields_remains_verifiable(self):
        from product_revision import validate_revision
        from product_inputs import digest
        report = self.plan(record=False)
        report.pop('scope_ready', None)
        report.pop('scope_gaps', None)
        report['fingerprint'] = digest({key: value for key, value in report.items() if key != 'fingerprint'})
        self.assertEqual(validate_revision(report), report)

    def test_rule_difference_propagates_to_dependents_and_keeps_independent_branch(self):
        original=self.record_path.read_bytes()
        report=self.plan()
        self.assertEqual(report['changes']['requirements']['modified'],['FR-001'])
        self.assertEqual(report['changes']['requirements']['unchanged'],['FR-002'])
        self.assertEqual(report['affected_acceptance'],['AC-001'])
        self.assertEqual(report['affected_artifacts'],['requirement','test'])
        self.assertEqual(self.record_path.read_bytes(),original)
        candidate=report['record_update']['candidate']
        self.assertEqual(candidate['artifacts'][0],json.loads(original)['artifacts'][0])
        self.assertEqual(candidate['artifacts'][-1],json.loads(original)['artifacts'][-1])
        self.assertEqual(check_record(candidate)['branches']['independent'],'recorded')
        self.assertEqual(check_record(candidate)['branches']['feature'],'needs_review')

    def test_contextual_relations_do_not_expand_product_revision_dependency_impact(self):
        data=json.loads(self.record_path.read_text())
        data['artifacts'][-1]['relations']={kind:[{'id':'requirement','version':1}]
                                          for kind in ('extends','supersedes','resolves','conflicts_with','relates_to')}
        self.record_path.write_text(json.dumps(data))
        report=self.plan()
        self.assertEqual(report['affected_artifacts'],['requirement','test'])
        self.assertEqual(report['record_update']['candidate']['artifacts'][-1],data['artifacts'][-1])

    def test_apply_preserves_history_and_evidence_and_replay_is_read_only(self):
        from product_revision import apply_impact
        before=self.record_path.read_bytes();report=self.plan()
        self.assertEqual(apply_impact(report)['status'],'applied')
        current=self.record_path.read_bytes()
        self.assertEqual(apply_impact(report)['status'],'resumed')
        self.assertEqual(self.record_path.read_bytes(),current)
        self.assertEqual(self.record_path.with_name('lifecycle.json.rev-1.json').read_bytes(),before)
        old=json.loads(before);new=json.loads(current)
        for prior,node in zip(old['artifacts'],new['artifacts']):
            self.assertEqual(node['evidence'],prior['evidence'])
            if node['id'] in report['affected_artifacts']:
                self.assertEqual(node['version'],prior['version']+1)
                self.assertEqual(node['status'],'pending_confirmation')

    def test_replay_after_later_record_progress_does_not_rewind(self):
        from product_revision import apply_impact
        report=self.plan();apply_impact(report)
        current=json.loads(self.record_path.read_text())
        later=copy.deepcopy(current);later.update(revision=3,owner='new-owner')
        update_record(self.record_path,later,2)
        before=self.record_path.read_bytes()
        self.assertEqual(apply_impact(report)['status'],'resumed')
        self.assertEqual(self.record_path.read_bytes(),before)

    def test_old_history_cannot_resume_a_foreign_record_replacing_the_same_path(self):
        from product_revision import apply_impact
        report=self.plan();apply_impact(report)
        candidate=json.loads(self.record_path.read_text());later=copy.deepcopy(candidate);later.update(revision=3,owner='later-owner')
        update_record(self.record_path,later,2)
        for identity in ('project_ref','subject_ref'):
            with self.subTest(identity=identity):
                foreign=copy.deepcopy(later);foreign[identity]='unrelated-identity'
                self.record_path.write_text(json.dumps(foreign));before=self.record_path.read_bytes()
                with self.assertRaisesRegex(ValueError,'identity|changed'):
                    apply_impact(report)
                self.assertEqual(self.record_path.read_bytes(),before)

    def test_saved_report_requires_an_absolute_canonical_record_path(self):
        from product_revision import validate_revision
        from product_inputs import digest
        report=self.plan()
        for path in ('lifecycle.json',str(self.record_path.parent/'subdir/../lifecycle.json')):
            with self.subTest(path=path):
                bad=copy.deepcopy(report);bad['record_path']=path;bad['record_update']['path']=path
                bad['fingerprint']=digest({k:v for k,v in bad.items() if k!='fingerprint'})
                with self.assertRaises(ValueError):validate_revision(bad)

    def test_record_replaced_by_same_bytes_symlink_cannot_redirect_the_writer(self):
        from product_revision import apply_impact
        report=self.plan();target=self.root/'moved-record.json';self.record_path.rename(target)
        self.record_path.symlink_to(target);before=target.read_bytes()
        with self.assertRaises(ValueError):apply_impact(report)
        self.assertEqual(target.read_bytes(),before)

    def test_cli_non_object_snapshot_is_a_structured_error_without_traceback(self):
        before=self.root/'before.json';after=self.root/'after.json';after.write_text(json.dumps(self.before))
        for value in (None,[],42):
            with self.subTest(value=value):
                before.write_text(json.dumps(value))
                result=subprocess.run([sys.executable,str(Path(__file__).with_name('product_revision.py')),
                    '--before',str(before),'--after',str(after)],capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertTrue(result.stdout,result.stderr)
                self.assertFalse(json.loads(result.stdout)['valid'])
                self.assertNotIn('Traceback',result.stderr)

    def test_added_removed_and_modified_acceptance_are_explicit(self):
        self.prd.write_text(self.prd.read_text().replace('AC-002 编辑成功','AC-003 编辑成功')+'\n#### AC-004 非法输入\n非法名称被拒绝。\n')
        report=self.plan(freeze_inputs(self.prd),record=False)
        self.assertEqual(report['changes']['acceptance']['added'],['AC-003','AC-004'])
        self.assertEqual(report['changes']['acceptance']['removed'],['AC-002'])
        self.assertEqual(report['affected_requirements'],['FR-002'])
        self.assertEqual(report['impact_scope'],'requirements_only')
        self.assertIsNone(report['record_update'])

    def test_added_and_removed_requirements_are_kept_in_impact(self):
        self.prd.write_text(self.prd.read_text().replace('FR-002','FR-003').replace('AC-002','AC-003'))
        report=self.plan(freeze_inputs(self.prd),record=False)
        self.assertEqual(report['changes']['requirements']['added'],['FR-003'])
        self.assertEqual(report['changes']['requirements']['removed'],['FR-002'])
        self.assertEqual(report['affected_acceptance'],['AC-002','AC-003'])

    def test_version_and_confirmation_only_change_does_not_invalidate_business_rules(self):
        self.prd.write_text(self.prd.read_text().replace('产品版本：v1','产品版本：v2').replace('产品版本 v1','产品版本 v2'))
        report=self.plan(freeze_inputs(self.prd))
        self.assertEqual(report['affected_requirements'],[])
        self.assertEqual(report['affected_artifacts'],[])
        self.assertIsNone(report['record_update'])

    def test_business_status_and_confirmation_examples_are_never_stripped_as_metadata(self):
        original=self.prd.read_text()
        examples=('接口状态示例：\n```\n状态：active\n```\n',
                  '业务输出要求：\n```md\n#### 输出片段\n状态：active\n```\n',
                  '业务记录示例：\n```\n确认记录：active\n```\n')
        for example in examples:
            with self.subTest(example=example):
                content=original.replace('#### AC-001',example+'#### AC-001')
                self.prd.write_text(content);self.before=freeze_inputs(self.prd)
                self.prd.write_text(content.replace('active','disabled').replace('产品版本：v1','产品版本：v2').replace('产品版本 v1','产品版本 v2'))
                report=self.plan(freeze_inputs(self.prd))
                self.assertEqual(report['affected_requirements'],['FR-001'])
                self.assertEqual(report['affected_artifacts'],['requirement','test'])

    def test_attachment_change_is_assigned_to_its_requirement(self):
        extra=self.root/'fact.txt';extra.write_text('old')
        self.prd.write_text(self.prd.read_text().replace('用户已明确仅展示当前状态。','[资料](fact.txt)'))
        self.before=freeze_inputs(self.prd);extra.write_text('new')
        report=self.plan(freeze_inputs(self.prd))
        self.assertEqual(report['affected_requirements'],['FR-001'])
        self.assertIn(str(extra),report['changes']['files']['modified'])

    def test_incomplete_foreign_and_invalid_dependency_mappings_fail_closed(self):
        from product_revision import plan_revision
        after=self.changed()
        for bindings in ({'FR-001':['requirement']},{**self.bindings,'FR-003':['other']},
                         {**self.bindings,'FR-001':['missing']},{**self.bindings,'FR-001':[]},
                         {**self.bindings,'FR-001':['requirement','requirement']}):
            with self.subTest(bindings=bindings),self.assertRaises(ValueError):
                plan_revision(self.before,after,record_path=self.record_path,bindings=bindings)
        record=json.loads(self.record_path.read_text());record['artifacts'][0]['depends_on']=[{'id':'test','version':1}]
        self.record_path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            self.plan(after)

    def test_stale_record_changed_inputs_and_forged_report_never_write(self):
        from product_revision import apply_impact,validate_revision
        report=self.plan();original=self.record_path.read_bytes()
        forged=copy.deepcopy(report);forged['affected_artifacts']=[]
        with self.assertRaises(ValueError):validate_revision(forged)
        self.prd.write_text(self.prd.read_text()+'\nNew input\n')
        with self.assertRaises(ValueError):apply_impact(report)
        self.assertEqual(self.record_path.read_bytes(),original)
        self.prd.write_text(report['after']['documents'][str(self.prd)])
        record=json.loads(original);record['revision']=2;self.record_path.write_text(json.dumps(record))
        before=self.record_path.read_bytes()
        with self.assertRaises(ValueError):apply_impact(report)
        self.assertEqual(self.record_path.read_bytes(),before)

    def test_failure_after_history_write_can_resume_same_plan(self):
        from product_revision import apply_impact
        report=self.plan();before=self.record_path.read_bytes()
        with patch('lifecycle_record.os.replace',side_effect=OSError('simulated interruption')):
            with self.assertRaises(OSError):apply_impact(report)
        self.assertEqual(self.record_path.read_bytes(),before)
        self.assertTrue(self.record_path.with_name('lifecycle.json.rev-1.json').exists())
        self.assertEqual(apply_impact(report)['status'],'applied')

    @unittest.skipUnless(os.name=='posix','process-exit lock recovery is POSIX-local')
    def test_real_process_exit_after_history_can_replay_without_manual_lock_deletion(self):
        from product_revision import apply_impact
        report=self.plan();before=self.record_path.read_bytes();saved=self.root/'report.json';saved.write_text(json.dumps(report))
        child='''import json,os,sys
sys.path.insert(0,sys.argv[1])
import lifecycle_record
from product_revision import apply_impact
lifecycle_record.os.replace=lambda *args:os._exit(19)
apply_impact(json.load(open(sys.argv[2])))
'''
        result=subprocess.run([sys.executable,'-c',child,str(Path(__file__).parent),str(saved)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,19,result.stderr)
        self.assertEqual(self.record_path.read_bytes(),before)
        self.assertTrue(self.record_path.with_name('lifecycle.json.rev-1.json').exists())
        self.assertEqual(apply_impact(report)['status'],'applied')
        self.assertEqual(apply_impact(report)['status'],'resumed')
        self.assertEqual(self.record_path.with_name('lifecycle.json.rev-1.json').read_bytes(),before)

    def test_live_writer_is_not_reclaimed_and_an_independent_record_can_continue(self):
        from product_revision import apply_impact,plan_revision
        report=self.plan();other=self.root/'other.json';other.write_text(json.dumps(report['record_before']))
        independent=plan_revision(report['before'],report['after'],record_path=other,bindings=self.bindings)
        entered=threading.Event();release=threading.Event();errors=[];replace=os.replace
        def held(source,target):
            if Path(target)==self.record_path:
                entered.set()
                if not release.wait(5):raise RuntimeError('test writer timeout')
            return replace(source,target)
        def first():
            try:apply_impact(report)
            except Exception as error:errors.append(error)
        with patch('lifecycle_record.os.replace',side_effect=held):
            thread=threading.Thread(target=first);thread.start()
            try:
                self.assertTrue(entered.wait(5))
                guard=self.record_path.with_name('lifecycle.json.lock');held_guard=guard.read_bytes()
                with self.assertRaises(FileExistsError):apply_impact(report)
                self.assertEqual(guard.read_bytes(),held_guard)
                self.assertEqual(apply_impact(independent)['status'],'applied')
            finally:release.set();thread.join(timeout=10)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertEqual(apply_impact(report)['status'],'resumed')

    def test_unrecognized_legacy_lock_is_never_deleted_or_adopted(self):
        from product_revision import apply_impact
        report=self.plan();guard=self.record_path.with_name('lifecycle.json.lock');guard.write_bytes(b'')
        before=self.record_path.read_bytes()
        with self.assertRaises(FileExistsError):apply_impact(report)
        self.assertEqual(guard.read_bytes(),b'');self.assertEqual(self.record_path.read_bytes(),before)

    def test_cli_plan_and_explicit_apply_bind_the_same_report(self):
        after=self.changed();before_file=self.root/'before.json';after_file=self.root/'after.json';bindings=self.root/'bindings.json'
        for path,value in ((before_file,self.before),(after_file,after),(bindings,self.bindings)):
            path.write_text(json.dumps(value))
        script=Path(__file__).with_name('product_revision.py')
        result=subprocess.run([sys.executable,str(script),'--before',str(before_file),'--after',str(after_file),
            '--record',str(self.record_path),'--bindings',str(bindings)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        report=json.loads(result.stdout);report_file=self.root/'impact.json';report_file.write_text(json.dumps(report))
        command=[sys.executable,str(script),'--report',str(report_file),'--apply']
        self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
        result=subprocess.run([*command,'--expected-impact',report['fingerprint']],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertEqual(json.loads(result.stdout)['status'],'applied')

    def test_prepared_report_rejects_json_type_changes_even_with_the_old_fingerprint(self):
        from product_revision import validate_revision
        report=self.plan()
        for kind in ('boolean','version'):
            with self.subTest(kind=kind):
                changed=copy.deepcopy(report)
                if kind=='boolean':changed['business_authorization']=0
                else:changed['record_update']['candidate']['artifacts'][1]['version']=2.0
                with self.assertRaises(ValueError):validate_revision(changed)

    def test_same_revision_json_type_drift_cannot_be_overwritten_by_prepared_impact(self):
        from product_revision import apply_impact
        data=json.loads(self.record_path.read_text());data['artifacts'][1]['annotation']=1
        self.record_path.write_text(json.dumps(data));report=self.plan()
        data['artifacts'][1]['annotation']=True;self.record_path.write_text(json.dumps(data));before=self.record_path.read_bytes()
        with self.assertRaises(ValueError):apply_impact(report)
        self.assertEqual(self.record_path.read_bytes(),before)
        self.assertFalse(self.record_path.with_name('lifecycle.json.rev-1.json').exists())

    def test_revision_replay_requires_exact_json_types_in_current_and_historical_records(self):
        from product_revision import apply_impact
        data=json.loads(self.record_path.read_text());data['artifacts'][1]['annotation']=1
        self.record_path.write_text(json.dumps(data));report=self.plan()
        for historical in (False,True):
            with self.subTest(historical=historical):
                self.record_path.write_text(json.dumps(data))
                for path in self.record_path.parent.glob('lifecycle.json.rev-*.json'):path.unlink()
                self.assertEqual(apply_impact(report)['status'],'applied')
                target=self.record_path
                if historical:
                    current=json.loads(self.record_path.read_text());current.update(revision=3,owner='later-owner')
                    update_record(self.record_path,current,2)
                    target=self.record_path.with_name('lifecycle.json.rev-2.json')
                changed=json.loads(target.read_text());changed['artifacts'][1]['annotation']=True
                target.write_text(json.dumps(changed));before=self.record_path.read_bytes()
                with self.assertRaises(ValueError):apply_impact(report)
                self.assertEqual(self.record_path.read_bytes(),before)

    def test_reordered_prepared_and_current_objects_still_replay_without_rewriting(self):
        from product_revision import apply_impact,validate_revision
        report=json.loads(json.dumps(self.plan(),sort_keys=True))
        validate_revision(report)
        self.assertEqual(apply_impact(report)['status'],'applied')
        current=json.loads(self.record_path.read_text());self.record_path.write_text(json.dumps(current,sort_keys=True))
        before=self.record_path.read_bytes()
        self.assertEqual(apply_impact(report)['status'],'resumed')
        self.assertEqual(self.record_path.read_bytes(),before)
