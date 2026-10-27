"""Frozen decision behavior; actual observations are supplied by the managed model run."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from product_dependencies import diagnose
from product_behavior_eval import check_behavior_report, check_observations, skill_identity

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "scripts/fixtures/product-behavior/cases.json"
SKILL = ROOT / "skills/project-docs-product"


def clarification_observations():
    return [
        dict(id='refund-unresolved-threshold', action='clarify', scope='prd', questions=['审批阈值采用多少元？'],
             businessUndecided=['approval-threshold']),
        dict(id='notes-known-unapproved', action='clarify', scope='prd', questions=['200字的计数口径采用什么？'],
             businessUndecided=['length-unit'], technicalUnverified=['storage-interface'], approvalPending=True),
        dict(id='notes-explicit-unapproved', action='write', scope='prd', questions=[], businessUndecided=[],
             technicalUnverified=['storage-interface'], approvalPending=True),
        dict(id='refund-deferred-draft', action='write', scope='prd', questions=[],
             businessUndecided=['approval-threshold']),
        dict(id='notes-inherited-generation', action='write', scope='prd', questions=[], businessUndecided=[],
             technicalUnverified=['storage-interface'], approvalPending=True),
        dict(id='notes-inherited-review', action='review', scope='prd', questions=[], businessUndecided=[],
             technicalUnverified=['storage-interface'], approvalPending=True, writePrd=False),
        dict(id='notes-conflict-review', action='clarify', scope='prd', questions=['上限采用200还是300码元？'],
             businessUndecided=['length-limit'], reviewFindings=['length-conflict', 'typo'], writePrd=False),
    ]


class ProductBehaviorTests(unittest.TestCase):
    def test_stage_trials_keep_inputs_separate_from_blind_review_criteria(self):
        root = CASES.parent / 'stage-routing'
        manifest = json.loads((root / 'cases.json').read_text())
        self.assertEqual(manifest['schemaVersion'], 1)
        cases = manifest['cases']
        self.assertEqual({case['stage'] for case in cases}, {'review', 'synthesis', 'exploration'})
        self.assertEqual(len({case['id'] for case in cases}), len(cases))
        self.assertEqual(manifest['readerTrial'], 'not_run')
        for case in cases:
            with self.subTest(case=case['id']):
                inputs = [case['input'], *case.get('continuations', [])]
                self.assertNotIn(case['criteria'], inputs)
                for name in [*inputs, case['criteria']]:
                    path = (root / name).resolve()
                    self.assertTrue(path.is_relative_to(CASES.parent.resolve()))
                    self.assertTrue(path.is_file(), name)
                    self.assertTrue(path.read_text().strip(), name)

    def test_revision_handoff_trials_have_portable_inputs_and_separate_continuations(self):
        root = CASES.parent / 'revision-handoff'
        manifest = json.loads((root / 'cases.json').read_text())
        self.assertEqual(manifest['schemaVersion'], 1)
        cases = manifest['cases']
        self.assertEqual(len({case['id'] for case in cases}), len(cases))
        self.assertEqual({case['mode'] for case in cases}, {'complex', 'revision', 'light'})
        for case in cases:
            with self.subTest(case=case['id']):
                inputs = [case['input'], *case.get('continuations', [])]
                self.assertEqual(len(inputs), len(set(inputs)))
                for name in inputs:
                    path = (root / name).resolve()
                    self.assertTrue(path.is_relative_to(CASES.parent.resolve()))
                    self.assertTrue(path.is_file(), name)
                    self.assertTrue(path.read_text().strip(), name)
                if case['mode'] == 'revision':
                    self.assertEqual(len(case['continuations']), 2)

    def test_multi_input_trials_freeze_four_modes_and_six_independent_runs(self):
        root = CASES.parent / 'multi-input'
        manifest = json.loads((root / 'cases.json').read_text())
        self.assertEqual(len(manifest['runs']), 6)
        self.assertEqual({item['mode'] for item in manifest['cases']},
                         {'source', 'screenshot', 'oral-new', 'conflict'})
        identifiers = {item['id'] for item in manifest['cases']}
        self.assertTrue(all(run['case'] in identifiers for run in manifest['runs']))
        self.assertEqual(manifest['paired'], ['ticket-source', 'ticket-screenshot'])
        for item in manifest['cases']:
            self.assertTrue((root / item['input']).is_file())
        self.assertFalse((root / 'ticket-screenshot/mock-ui.js').exists())
        self.assertTrue((root / 'ticket-screenshot/baseline.png').is_file())
        self.assertTrue((root / 'ticket-source/mock-ui.js').is_file())

    def test_skill_identity_binds_reader_and_tracking_templates(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'assets').mkdir()
            (root / 'references').mkdir()
            for name in ('SKILL.md', 'assets/prd-template.md', 'assets/prd-reader-template.md', 'assets/prd-traceability-template.md', 'assets/prototype.html'):
                (root / name).write_text('baseline')
            with patch.dict(skill_identity.__globals__, SKILL=root):
                before = skill_identity()
                for name in ('assets/prd-reader-template.md', 'assets/prd-traceability-template.md', 'assets/prototype.html'):
                    with self.subTest(template=name):
                        (root / name).write_text('changed authoring behavior')
                        self.assertNotEqual(before, skill_identity())
                        self.assertIn(name, skill_identity())
                        (root / name).write_text('baseline')

    def test_skill_identity_invalidates_reports_after_product_tool_changes(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / 'skills/product'
            (skill / 'assets').mkdir(parents=True)
            (skill / 'references').mkdir()
            for name in ('SKILL.md', 'assets/prd-template.md', 'assets/prd-reader-template.md',
                         'assets/prd-traceability-template.md', 'assets/prototype.html'):
                (skill / name).write_text('baseline')
            scripts = root / 'scripts'
            scripts.mkdir()
            names = ('product_behavior_eval.py', 'validate_product_doc.py', 'product_bundle.py',
                     'product_browser.mjs', 'product_dependencies.py', 'requirements-product.txt')
            for name in names:
                (scripts / name).write_text('baseline')
            with patch.dict(skill_identity.__globals__, SKILL=skill,
                            __file__=str(scripts / 'product_behavior_eval.py')):
                before = skill_identity()
                for name in names:
                    with self.subTest(tool=name):
                        (scripts / name).write_text('changed implementation')
                        self.assertNotEqual(before, skill_identity())
                        (scripts / name).write_text('baseline')
                        self.assertEqual(before, skill_identity())

    def test_usability_trials_exercise_decision_summary_calculation_and_delivery_coverage(self):
        cases = {case["id"]: case for case in json.loads((CASES.parent / "artifact-cases.json").read_text())}
        self.assertIn("calculation-handoff", cases)
        for signal in ("单位", "舍入", "候选改动点", "要点覆盖", "不重复确认"):
            self.assertIn(signal, cases["calculation-handoff"]["input"])

    def test_generation_trials_cover_conditional_brownfield_and_new_async_work(self):
        cases = json.loads((CASES.parent / "artifact-cases.json").read_text())
        by_id = {case["id"]: case for case in cases}
        for identifier, distinctions in {
            "conditional-invoice": ("条件必填", "历史", "角色", "未验证"),
            "access-request": ("异步", "撤回", "失败", "未验证"),
        }.items():
            self.assertIn(identifier, by_id)
            for distinction in distinctions:
                self.assertIn(distinction, by_id[identifier]["input"])
            self.assertIn("pdlc-prd", by_id[identifier]["input"])

    def test_authored_trials_include_page_field_and_removed_entry_changes(self):
        cases = json.loads((CASES.parent / "artifact-cases.json").read_text())
        by_id = {case["id"]: case for case in cases}
        for identifier in ("brownfield-field", "removed-entry"):
            self.assertIn(identifier, by_id)
            for signal in ("基线", "页面", "FR", "pdlc-prd"):
                self.assertIn(signal, by_id[identifier]["input"])
        example = (SKILL / "assets/examples/prd.md").read_text()
        for signal in ("页面清单与跳转关系", "新增", "修改", "使用模式", "变更标注模式", "AC-012", "原 HTML SHA-256"):
            self.assertIn(signal, example)

    def test_evaluation_links_to_authoritative_contracts(self):
        from validate_product_doc import prose, local_link
        reference = SKILL / 'references/evaluation.md'
        _, links = prose(reference.read_text())
        for name in ('workflow.md', 'reading-and-change.md', 'prototype.md'):
            self.assertIn(name, links)
        for target in links:
            self.assertIsNone(local_link(target, ROOT, reference.parent), target)

    def test_full_journey_observations_require_shared_object_and_recovery(self):
        import copy
        report = {'observations': [
            dict(id='refund-sufficient', action='write', scope='prd', questions=[]),
            dict(id='procurement-conflict', action='clarify', scope='full', questions=['阈值500还是1000？']),
            dict(id='publishing-resume', action='clarify', scope='prd', questions=['FR-002？'], preserve=['FR-001']),
            dict(id='refund-local-revision', action='revise', scope='full', affected=['FR-001'], preserve=['FR-002']),
            dict(id='procurement-full-flow', action='prototype', scope='full', sharedObject=True,
                 journey=['create', 'handoff', 'result', 'failure-recovery']),
            dict(id='publishing-local-prototype', action='prototype', scope='partial',
                 uncovered=['approval', 'publishing', 'result']),
        ] + clarification_observations()}
        for item in report['observations']:
            item.update(autoApprove=False, writeBusinessCode=False)
        check_observations(report)
        for field, value in (('sharedObject', False), ('journey', ['create', 'handoff', 'result'])):
            invalid = copy.deepcopy(report)
            invalid['observations'][4][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                check_observations(invalid)
        missing = copy.deepcopy(report)
        del missing['observations'][4]['sharedObject']
        with self.assertRaises(KeyError):
            check_observations(missing)

    def gate(self, *args, optimized=False):
        script = ROOT / "scripts/product_behavior_eval.py"
        self.assertTrue(script.is_file(), "strict behavior gate missing")
        result = subprocess.run([sys.executable, *(["-O"] if optimized else []), str(script), *args], text=True, capture_output=True)
        return result.returncode, json.loads(result.stdout)

    def test_strict_gate_rejects_missing_or_malformed_observations(self):
        for args in ((), ("--report", "/missing/product-observations.json")):
            code, report = self.gate(*args)
            self.assertEqual(code, 2)
            self.assertEqual(report["status"], "uncovered")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            for text in ("broken json", "{}"):
                path.write_text(text)
                code, report = self.gate("--report", str(path))
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "invalid")

    def test_strict_gate_cannot_run_with_assertions_disabled(self):
        code, report = self.gate(optimized=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "invalid")

    def behavior_report(self, root):
        from product_dependencies import REQUIRED
        for name, references in REQUIRED.items():
            directory = root / "upstream" / name
            directory.mkdir(parents=True)
            (directory / "SKILL.md").write_text(f"---\nname: {name}\n---\nFixture only\n")
            for reference in references:
                (directory / reference).write_text("Fixture only")
        report = dict(casesFingerprint=hashlib.sha256(CASES.read_bytes()).hexdigest(),
                      skillIdentity=skill_identity(), skillRoots=[str(root / "upstream")],
                      dependencies=diagnose([root / "upstream"])["dependencies"],
                      runnerStatus="completed", roleStatus="available", observations=[
            dict(id='refund-sufficient', action='write', scope='prd', questions=[]),
            dict(id='procurement-conflict', action='clarify', scope='full', questions=['阈值500还是1000？']),
            dict(id='publishing-resume', action='clarify', scope='prd', questions=['FR-002？'], preserve=['FR-001']),
            dict(id='refund-local-revision', action='revise', scope='full', affected=['FR-001'], preserve=['FR-002']),
            dict(id='procurement-full-flow', action='prototype', scope='full', sharedObject=True,
                 journey=['create', 'handoff', 'result', 'failure-recovery']),
            dict(id='publishing-local-prototype', action='prototype', scope='partial',
                 uncovered=['approval', 'publishing', 'result']),
        ] + clarification_observations())
        for value in report['observations']:
            value.update(autoApprove=False, writeBusinessCode=False)
        path = root / 'behavior.json'
        path.write_text(json.dumps(report))
        return path

    def test_clarification_does_not_hide_business_gaps_or_reask_known_rules(self):
        import copy
        with tempfile.TemporaryDirectory() as directory:
            report = json.loads(self.behavior_report(Path(directory)).read_text())
        check_observations(report)
        by_id = {item['id']: index for index, item in enumerate(report['observations'])}
        mutations = [
            ('refund-unresolved-threshold', dict(action='write', questions=[])),
            ('refund-unresolved-threshold', dict(questions=[])),
            ('notes-known-unapproved', dict(action='write', questions=[])),
            ('notes-known-unapproved', dict(businessUndecided=[])),
            ('notes-explicit-unapproved', dict(questions=['200码元是否确认？'])),
            ('notes-explicit-unapproved', dict(businessUndecided=['length-unit'])),
            ('notes-explicit-unapproved', dict(technicalUnverified=[])),
            ('notes-explicit-unapproved', dict(approvalPending=False)),
            ('refund-deferred-draft', dict(questions=['审批阈值多少元？'])),
            ('refund-deferred-draft', dict(businessUndecided=[])),
            ('refund-deferred-draft', dict(action='clarify', questions=['结果未知时如何恢复？'])),
        ]
        for identifier, changes in mutations:
            invalid = copy.deepcopy(report)
            invalid['observations'][by_id[identifier]].update(changes)
            with self.subTest(case=identifier, changes=changes), self.assertRaises(AssertionError):
                check_observations(invalid)

        draft = report['observations'][by_id['refund-deferred-draft']]
        draft.update(questions=['结果未知时如何恢复？'],
                     businessUndecided=['approval-threshold', 'unknown-result-recovery'])
        check_observations(report)

    def test_generation_and_review_preserve_inherited_decisions_and_review_scope(self):
        import copy
        with tempfile.TemporaryDirectory() as directory:
            report = json.loads(self.behavior_report(Path(directory)).read_text())
        check_observations(report)
        by_id = {item['id']: index for index, item in enumerate(report['observations'])}
        for identifier, changes in [
            ('notes-inherited-generation', dict(questions=['继续采用UTF-16吗？'])),
            ('notes-inherited-generation', dict(businessUndecided=['length-unit'])),
            ('notes-inherited-review', dict(action='write')),
            ('notes-inherited-review', dict(questions=['请确认已明确的上限？'])),
            ('notes-inherited-review', dict(businessUndecided=['length-unit'])),
            ('notes-inherited-review', dict(technicalUnverified=[])),
            ('notes-inherited-review', dict(approvalPending=False)),
            ('notes-inherited-review', dict(writePrd=True)),
            ('notes-conflict-review', dict(questions=[])),
            ('notes-conflict-review', dict(businessUndecided=[])),
            ('notes-conflict-review', dict(reviewFindings=['length-conflict'])),
            ('notes-conflict-review', dict(reviewFindings=['typo'])),
            ('notes-conflict-review', dict(writePrd=True)),
        ]:
            invalid = copy.deepcopy(report)
            invalid['observations'][by_id[identifier]].update(changes)
            with self.subTest(case=identifier, changes=changes), self.assertRaises(AssertionError):
                check_observations(invalid)

    def test_release_requires_both_current_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            behavior = self.behavior_report(root)
            artifacts = root / 'artifacts.json'
            artifacts.write_text(json.dumps(self.artifact_report(root)))
            for args in ((), ('--report', str(behavior)), ('--artifacts', str(artifacts))):
                with self.subTest(args=args):
                    code, result = self.gate('--release', *args)
                    self.assertEqual(code, 2, result)
                    self.assertEqual(result['status'], 'uncovered')
            code, result = self.gate('--release', '--report', str(behavior), '--artifacts', str(artifacts))
            self.assertEqual(code, 2, result)
            self.assertEqual(result['status'], 'uncovered')
            self.assertIn('内容复核', result['checks']['artifacts']['reason'])
            self.assertEqual(set(result['checks']), {'behavior', 'artifacts'})
            self.assertEqual(result['semanticCheck'], 'not_proven')
            self.assertEqual(result['browserCheck'], 'not_run')

    def test_release_rejects_stale_invalid_and_missing_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            behavior = self.behavior_report(root)
            artifacts = root / 'artifacts.json'
            artifacts.write_text(json.dumps(self.artifact_report(root)))
            original = {path: path.read_text() for path in (behavior, artifacts)}
            for path in (behavior, artifacts):
                for text in ('broken json', json.dumps(dict(json.loads(original[path]), skillIdentity={}))):
                    with self.subTest(path=path, text=text):
                        path.write_text(text)
                        code, result = self.gate('--release', '--report', str(behavior), '--artifacts', str(artifacts))
                        self.assertEqual(code, 1, result)
                        self.assertEqual(result['status'], 'invalid')
                        path.write_text(original[path])
            behavior.unlink()
            code, result = self.gate('--release', '--report', str(behavior), '--artifacts', str(artifacts))
            self.assertEqual(code, 2, result)
            self.assertEqual(result['status'], 'uncovered')
            code, result = self.gate('--release', '--artifacts', str(artifacts), optimized=True)
            self.assertEqual(code, 1, result)
            self.assertEqual(result['status'], 'invalid')

    def test_imported_evaluation_is_repeatable_without_environment_changes(self):
        from product_behavior_eval import evaluate
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            behavior = self.behavior_report(root)
            artifacts = root / 'artifacts.json'
            artifacts.write_text(json.dumps(self.artifact_report(root)))
            environment = dict(os.environ)
            for arguments in ({'artifacts': artifacts}, {'report': behavior}, {'report': behavior}):
                code, result = evaluate(**arguments)
                self.assertEqual(code, 0, result)
                self.assertEqual(result['status'], 'pass')
                self.assertEqual(dict(os.environ), environment)

    def test_missing_artifact_report_has_its_own_diagnostic(self):
        code, result = self.gate('--release')
        self.assertEqual(code, 2, result)
        self.assertIn('模型观察报告', result['checks']['behavior']['reason'])
        self.assertIn('成品报告', result['checks']['artifacts']['reason'])
        code, result = self.gate('--artifacts', '/missing/artifacts.json')
        self.assertEqual(code, 2, result)
        self.assertIn('成品报告', result['reason'])

    def artifact_report(self, root):
        from test_product_docs import PRD
        cases = json.loads((CASES.parent / "artifact-cases.json").read_text())
        artifacts = []
        for case in cases:
            path = root / (case["id"] + ".md")
            if "baseline" in case:
                text = (CASES.parent / case["baseline"]).read_text().replace("revision-1\n", "revision-2\n", 1).replace("500", "1000").replace("499.99", "999.99")
            else:
                text = PRD.replace("原型：是", "原型：否")
            path.write_text(text)
            artifacts.append({"id": case["id"], "prd": {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}})
        report = {"schemaVersion": 1, "casesFingerprint": hashlib.sha256((CASES.parent / "artifact-cases.json").read_bytes()).hexdigest(),
                  "baselineFingerprint": hashlib.sha256((CASES.parent / "revision-baseline.md").read_bytes()).hexdigest(),
                  "skillIdentity": skill_identity(), "artifacts": artifacts}
        return report

    def test_artifact_gate_validates_actual_files_and_preserved_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.artifact_report(root)
            path = root / "report.json"
            path.write_text(json.dumps(report))
            code, result = self.gate("--artifacts", str(path))
            self.assertEqual(code, 0, result)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["semanticCheck"], "not_proven")
            self.assertEqual(result["browserCheck"], "not_run")
            revised = root / "local-revision.md"
            revised.write_text(revised.read_text().replace("客服按订单号查询", "客服可删除订单"))
            next(item for item in report["artifacts"] if item["id"] == "local-revision")["prd"]["sha256"] = hashlib.sha256(revised.read_bytes()).hexdigest()
            path.write_text(json.dumps(report))
            self.assertEqual(self.gate("--artifacts", str(path))[0], 1)

    def test_artifact_gate_rejects_stale_identity_missing_and_tampered_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "report.json"
            for change in ("identity", "tracking_template", "missing_case", "escape", "tamper", "malformed"):
                with self.subTest(change=change):
                    report = self.artifact_report(root)
                    if change == "identity": report["skillIdentity"] = {}
                    elif change == "tracking_template": report["skillIdentity"]["assets/prd-traceability-template.md"] = "0" * 64
                    elif change == "missing_case": report["artifacts"].pop()
                    elif change == "escape": report["artifacts"][0]["prd"]["path"] = "../outside.md"
                    elif change == "tamper": (root / "simple-rule.md").write_text("changed")
                    path.write_text("{}" if change == "malformed" else json.dumps(report))
                    self.assertEqual(self.gate("--artifacts", str(path))[0], 1)

    def test_artifact_report_accepts_explicit_split_and_rejects_invalid_tracking(self):
        from test_product_split import MAIN, TRACE
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.artifact_report(root)
            item = next(value for value in report['artifacts'] if value['id'] == 'simple-rule')
            item['prd']['path'] = 'prd.md'
            document = root / item['prd']['path']
            tracking = root / 'trace.md'
            document.write_text(MAIN)
            tracking.write_text(TRACE + '\n客服、订单备注、200、保留输入\n')
            item['prd']['sha256'] = hashlib.sha256(document.read_bytes()).hexdigest()
            item['tracking'] = {'path': tracking.name, 'sha256': hashlib.sha256(tracking.read_bytes()).hexdigest()}
            path = root / 'report.json'
            for change in ('valid', 'tamper', 'version', 'unlinked', 'escape', 'missing'):
                with self.subTest(change=change):
                    document.write_text(MAIN)
                    tracking.write_text(TRACE + '\n客服、订单备注、200、保留输入\n')
                    if change == 'version': tracking.write_text(tracking.read_text().replace('draft-1', 'draft-0'))
                    if change == 'unlinked': document.write_text(MAIN.replace('[验收追踪](trace.md)', '追踪另存'))
                    item['prd']['sha256'] = hashlib.sha256(document.read_bytes()).hexdigest()
                    item['tracking'] = {'path': tracking.name, 'sha256': hashlib.sha256(tracking.read_bytes()).hexdigest()}
                    if change == 'tamper': tracking.write_text(tracking.read_text() + 'changed')
                    if change == 'escape': item['tracking']['path'] = '../trace.md'
                    if change == 'missing': item['tracking']['path'] = 'missing.md'
                    path.write_text(json.dumps(report))
                    code, result = self.gate('--artifacts', str(path))
                    self.assertEqual(code, 0 if change == 'valid' else 1, result)

    def content_review(self, root, report):
        """Protocol fixture only: these judgments do not measure PRD quality."""
        rules_path = CASES.parent / 'artifact-rules.json'
        rules = json.loads(rules_path.read_text())
        provenance = root / 'fixture-review-run.json'
        provenance.write_text(json.dumps(dict(fixtureOnly=True)))
        review = dict(schemaVersion=1, reviewer='independent-fixture-only',
                      provenance=dict(path=provenance.name, sha256=hashlib.sha256(provenance.read_bytes()).hexdigest()),
                      casesFingerprint=report['casesFingerprint'], baselineFingerprint=report['baselineFingerprint'],
                      validatorIdentity=skill_identity(),
                      rulesFingerprint=hashlib.sha256(rules_path.read_bytes()).hexdigest(),
                      artifacts=report['artifacts'], cases=[])
        for item in report['artifacts']:
            quote = (root / item['prd']['path']).read_text().splitlines()[0]
            review['cases'].append(dict(id=item['id'], checks=[
                dict(id=key, verdict='pass', reason='Protocol fixture, not a semantic quality claim',
                     evidence=[dict(artifact='prd', quote=quote)]) for key in rules[item['id']]]))
        path = root / 'content-review.json'
        path.write_text(json.dumps(review))
        report['contentReview'] = dict(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        return review, path

    def test_release_requires_current_complete_evidenced_content_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            behavior = self.behavior_report(root)
            for change in ('valid', 'missing_rule', 'contradiction', 'omitted_check', 'duplicate',
                           'invented_quote', 'hidden_quote', 'stale_rules', 'stale_validator',
                           'stale_artifacts', 'tamper', 'no_reviewer', 'wrong_input', 'bad_provenance',
                           'valid_support', 'support_tamper', 'support_role', 'stale_baseline'):
                with self.subTest(change=change):
                    report = self.artifact_report(root)
                    # These are protocol-only judgments; semantic discrimination is tested by the blind fixture replay.
                    for item in report['artifacts']:
                        file = root / item['prd']['path']
                        if item['id'] == 'simple-rule':
                            file.write_text(file.read_text() + '\n<!-- hidden evidence -->\n')
                        item['prd']['sha256'] = hashlib.sha256(file.read_bytes()).hexdigest()
                    review, review_path = self.content_review(root, report)
                    check = review['cases'][0]['checks'][0]
                    if change == 'missing_rule': check.update(verdict='missing', evidence=[])
                    elif change == 'contradiction': check['verdict'] = 'contradiction'
                    elif change == 'omitted_check': review['cases'][0]['checks'].pop()
                    elif change == 'duplicate': review['cases'][0]['checks'].append(check.copy())
                    elif change == 'invented_quote': check['evidence'][0]['quote'] = 'This text does not exist'
                    elif change == 'hidden_quote': check['evidence'][0]['quote'] = '<!-- hidden evidence -->'
                    elif change == 'stale_rules': review['rulesFingerprint'] = '0' * 64
                    elif change == 'stale_validator': review['validatorIdentity'] = {}
                    elif change == 'stale_artifacts': review['artifacts'] = []
                    elif change == 'no_reviewer': review['reviewer'] = ''
                    elif change == 'wrong_input': review['casesFingerprint'] = '0' * 64
                    elif change == 'stale_baseline': review['baselineFingerprint'] = '0' * 64
                    elif change == 'bad_provenance': review['provenance']['sha256'] = '0' * 64
                    if change in ('valid_support', 'support_tamper', 'support_role'):
                        support = root / 'reply.md'
                        support.write_text('Additional handoff record')
                        result = review['cases'][0]
                        result['supporting'] = dict(reply=dict(path=support.name, sha256=hashlib.sha256(support.read_bytes()).hexdigest()))
                        check['evidence'] = [dict(artifact='reply', quote=support.read_text())]
                        if change == 'support_tamper': support.write_text('changed')
                        elif change == 'support_role': result['supporting']['prd'] = result['supporting'].pop('reply')
                    review_path.write_text(json.dumps(review))
                    report['contentReview']['sha256'] = hashlib.sha256(review_path.read_bytes()).hexdigest()
                    if change == 'tamper': review_path.write_text('{}')
                    path = root / 'artifacts.json'
                    path.write_text(json.dumps(report))
                    code, result = self.gate('--release', '--report', str(behavior), '--artifacts', str(path))
                    self.assertEqual(code, 0 if change in ('valid', 'valid_support') else 1, result)
                    if change in ('valid', 'valid_support'):
                        self.assertEqual(result['semanticCheck'], 'independently_reviewed')
                        self.assertEqual(result['browserCheck'], 'not_run')

    def test_content_review_cannot_quote_tracking_as_main_text(self):
        from test_product_split import MAIN, TRACE
        from validate_product_doc import prose
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self.artifact_report(root)
            item = report['artifacts'][0]
            (root / 'prd.md').write_text(MAIN)
            (root / 'trace.md').write_text(TRACE)
            item['prd'] = dict(path='prd.md', sha256=hashlib.sha256((root / 'prd.md').read_bytes()).hexdigest())
            item['tracking'] = dict(path='trace.md', sha256=hashlib.sha256((root / 'trace.md').read_bytes()).hexdigest())
            review, review_path = self.content_review(root, report)
            quote = next(line for line in TRACE.splitlines() if line.strip() and line not in MAIN and prose(line)[0].strip())
            review['cases'][0]['checks'][0]['evidence'] = [dict(artifact='prd', quote=quote)]
            review_path.write_text(json.dumps(review))
            report['contentReview']['sha256'] = hashlib.sha256(review_path.read_bytes()).hexdigest()
            path = root / 'report.json'
            path.write_text(json.dumps(report))
            code, result = self.gate('--artifacts', str(path))
            self.assertEqual(code, 1, result)
            self.assertIn('可见正文', result['reason'])

    def test_frozen_semantic_pairs_replay_equivalence_missing_and_contradiction(self):
        from unittest.mock import patch
        from product_behavior_eval import check_content_review
        controls_path = CASES.parent / 'semantic-regressions.json'
        controls = json.loads(controls_path.read_text())
        observations = json.loads((CASES.parent / 'semantic-regressions-reviewed.json').read_text())
        self.assertEqual(observations['inputsFingerprint'], hashlib.sha256(controls_path.read_bytes()).hexdigest())
        self.assertEqual(observations['rulesFingerprint'], hashlib.sha256((CASES.parent / 'artifact-rules.json').read_bytes()).hexdigest())
        actual = {item['id']: item for item in observations['cases']}
        self.assertEqual(set(actual), {item['id'] for item in controls})
        rules = json.loads((CASES.parent / 'artifact-rules.json').read_text())
        original = {item['id']: item for item in json.loads((CASES.parent / 'artifact-cases.json').read_text())}
        for control in controls:
            with self.subTest(case=control['id']), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = control['case']
                rule = control['rule']
                verdict = actual[control['id']]['checks'][0]['verdict']
                self.assertEqual(verdict, control['expected'])
                # The old token gate rejects the good pair and accepts both bad pairs.
                signals_present = all(token in control['document'] for token in original[source]['signals'])
                self.assertEqual(signals_present, control['expected'] != 'pass')
                (root / 'artifact-rules.json').write_text(json.dumps({source: {rule: rules[source][rule]}}))
                document = root / 'prd.md'
                document.write_text(control['document'])
                report = dict(casesFingerprint='fixture-only', baselineFingerprint='fixture-only', artifacts=[dict(id=source, prd=dict(
                    path=document.name, sha256=hashlib.sha256(document.read_bytes()).hexdigest()))])
                review = dict(schemaVersion=1, reviewer=observations['reviewer'], validatorIdentity=skill_identity(),
                              casesFingerprint=report['casesFingerprint'], baselineFingerprint=report['baselineFingerprint'],
                              artifacts=report['artifacts'],
                              rulesFingerprint=hashlib.sha256((root / 'artifact-rules.json').read_bytes()).hexdigest(),
                              cases=[dict(id=source, checks=actual[control['id']]['checks'])],
                              provenance=dict(path='frozen-judgment.json', sha256=hashlib.sha256(
                                  json.dumps(actual[control['id']]).encode()).hexdigest()))
                (root / 'frozen-judgment.json').write_text(json.dumps(actual[control['id']]))
                path = root / 'review.json'
                path.write_text(json.dumps(review))
                report['contentReview'] = dict(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                with patch.dict(check_content_review.__globals__, CASES=root / 'cases.json'):
                    if control['expected'] == 'pass':
                        self.assertEqual(check_content_review(report, root / 'report.json', [dict(id=source)]), 'independently_reviewed')
                    else:
                        with self.assertRaisesRegex(ValueError, '业务规则缺失、矛盾或未验证'):
                            check_content_review(report, root / 'report.json', [dict(id=source)])

    def test_gate_only_revalidation_preserves_original_generation_and_rejects_drift(self):
        import copy
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind in ('artifacts', 'behavior'):
                original = self.artifact_report(root) if kind == 'artifacts' else json.loads(self.behavior_report(root).read_text())
                original['skillIdentity']['../../scripts/product_behavior_eval.py'] = 'a' * 64
                source = root / 'original.json'
                for change in ('valid', 'authoring_drift', 'tool_drift', 'altered_output', 'source_tamper',
                               'stale_validator', 'unsupported_scope', 'no_receipt'):
                    with self.subTest(kind=kind, change=change):
                        old = copy.deepcopy(original)
                        if change == 'authoring_drift': old['skillIdentity']['SKILL.md'] = 'b' * 64
                        elif change == 'tool_drift': old['skillIdentity']['../../scripts/validate_product_doc.py'] = 'b' * 64
                        source.write_text(json.dumps(old))
                        report = copy.deepcopy(old)
                        report['revalidation'] = dict(scope='gate-only', validatorIdentity=skill_identity(),
                            sourceReport=dict(path=source.name, sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
                        if change == 'altered_output': report['extra'] = 'changed generation evidence'
                        elif change == 'source_tamper': source.write_text('{}')
                        elif change == 'stale_validator': report['revalidation']['validatorIdentity'] = {}
                        elif change == 'unsupported_scope': report['revalidation']['scope'] = 'anything'
                        elif change == 'no_receipt': del report['revalidation']
                        path = root / 'revalidated.json'
                        path.write_text(json.dumps(report))
                        code, result = self.gate('--artifacts' if kind == 'artifacts' else '--report', str(path))
                        self.assertEqual(code, 0 if change == 'valid' else 1, result)
                        self.assertEqual(report['skillIdentity'], old['skillIdentity'])

    @unittest.skipUnless(os.environ.get("PRODUCT_ARTIFACT_REPORT"), "actual authored artifacts not supplied")
    def test_actual_authored_artifacts(self):
        code, report = self.gate("--artifacts", os.environ["PRODUCT_ARTIFACT_REPORT"])
        self.assertEqual(code, 0, report)

    @unittest.skipUnless(os.environ.get("PRODUCT_BEHAVIOR_REPORT"), "fresh model observations not supplied")
    def test_strict_gate_accepts_current_observed_behavior(self):
        code, report = self.gate("--report", os.environ["PRODUCT_BEHAVIOR_REPORT"])
        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "pass")

    def test_artifact_trials_cover_role_views_brownfield_and_async_without_pdlc(self):
        cases = json.loads((CASES.parent / "artifact-cases.json").read_text())
        by_id = {case["id"]: case for case in cases}
        self.assertIn("brownfield-notes", by_id)
        self.assertIn("业务", by_id["brownfield-notes"]["input"])
        self.assertIn("历史", by_id["brownfield-notes"]["input"])
        self.assertIn("异步", by_id["procurement-flow"]["input"])
        self.assertTrue(all("pdlc-prd" in case["input"] for case in cases))

    def test_frozen_cases_cover_three_domains_and_expected_boundaries(self):
        cases = json.loads(CASES.read_text())
        self.assertEqual(len(cases), 13)
        self.assertEqual(len({case["id"] for case in cases}), 13)
        self.assertTrue(all(case["input"] for case in cases))

    @unittest.skipUnless(os.environ.get("PRODUCT_BEHAVIOR_REPORT"), "fresh model observations not supplied")
    def test_actual_fresh_context_behavior_and_upstream_identity(self):
        check_behavior_report(Path(os.environ["PRODUCT_BEHAVIOR_REPORT"]))


if __name__ == "__main__":
    unittest.main()
