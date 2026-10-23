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

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "scripts/fixtures/product-behavior/cases.json"
SKILL = ROOT / "skills/project-docs-product"


def skill_identity():
    return {str(path.relative_to(SKILL)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [SKILL / "SKILL.md", SKILL / "assets/prd-template.md", SKILL / "assets/prd-reader-template.md",
                         SKILL / "assets/prd-traceability-template.md", *sorted((SKILL / "references").glob("*.md"))]}


def check_observations(report):
    expected = {
        "refund-sufficient": ("write", "prd"),
        "procurement-conflict": ("clarify", "full"),
        "publishing-resume": ("clarify", "prd"),
        "refund-local-revision": ("revise", "full"),
        "procurement-full-flow": ("prototype", "full"),
        "publishing-local-prototype": ("prototype", "partial"),
    }
    values = report["observations"]
    assert len(values) == len(expected) and {value["id"] for value in values} == set(expected), "all frozen samples required"
    for value in values:
        assert (value["action"], value["scope"]) == expected[value["id"]], value
        assert value["autoApprove"] is False and value["writeBusinessCode"] is False, value
        if value["id"] == "refund-sufficient":
            assert value["questions"] == [], value
        if value["id"] == "procurement-conflict":
            assert len(value["questions"]) == 1 and any(word in value["questions"][0] for word in ("500", "1000", "阈值")), value
        if value["id"] == "publishing-resume":
            assert len(value["questions"]) == 1 and "FR-002" in value["questions"][0] and value["preserve"] == ["FR-001"], value
        if value["id"] == "refund-local-revision":
            assert value["affected"] == ["FR-001"] and value["preserve"] == ["FR-002"], value
        if value["id"] == "procurement-full-flow":
            assert value["sharedObject"] is True and set(value["journey"]) == {"create", "handoff", "result", "failure-recovery"}, value
        if value["id"] == "publishing-local-prototype":
            assert set(value["uncovered"]) == {"approval", "publishing", "result"}, value


class ProductBehaviorTests(unittest.TestCase):
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
            for name in ('SKILL.md', 'assets/prd-template.md', 'assets/prd-reader-template.md', 'assets/prd-traceability-template.md'):
                (root / name).write_text('baseline')
            with patch.dict(skill_identity.__globals__, SKILL=root):
                before = skill_identity()
                for name in ('assets/prd-reader-template.md', 'assets/prd-traceability-template.md'):
                    with self.subTest(template=name):
                        (root / name).write_text('changed authoring behavior')
                        self.assertNotEqual(before, skill_identity())
                        self.assertIn(name, skill_identity())
                        (root / name).write_text('baseline')

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
        ]}
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

    def artifact_report(self, root):
        from test_product_docs import PRD
        cases = json.loads((CASES.parent / "artifact-cases.json").read_text())
        artifacts = []
        for case in cases:
            path = root / (case["id"] + ".md")
            if "baseline" in case:
                text = (CASES.parent / case["baseline"]).read_text().replace("revision-1\n", "revision-2\n", 1).replace("500", "1000").replace("499.99", "999.99")
            else:
                text = PRD.replace("原型：是", "原型：否") + "\n" + "、".join(case["signals"]) + "\n"
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
            # Frozen signals may occur in either file, including identifiers in tracking.
            document.write_text(MAIN)
            tracking.write_text(TRACE + '\n客服、订单备注、200、保留输入\n')
            item['prd']['sha256'] = hashlib.sha256(document.read_bytes()).hexdigest()
            item['tracking'] = {'path': tracking.name, 'sha256': hashlib.sha256(tracking.read_bytes()).hexdigest()}
            path = root / 'report.json'
            for change in ('valid', 'tamper', 'version', 'missing_signal', 'unlinked', 'escape', 'missing'):
                with self.subTest(change=change):
                    document.write_text(MAIN)
                    tracking.write_text(TRACE + '\n客服、订单备注、200、保留输入\n')
                    if change == 'version': tracking.write_text(tracking.read_text().replace('draft-1', 'draft-0'))
                    if change == 'missing_signal': tracking.write_text(TRACE)
                    if change == 'unlinked': document.write_text(MAIN.replace('[验收追踪](trace.md)', '追踪另存'))
                    item['prd']['sha256'] = hashlib.sha256(document.read_bytes()).hexdigest()
                    item['tracking'] = {'path': tracking.name, 'sha256': hashlib.sha256(tracking.read_bytes()).hexdigest()}
                    if change == 'tamper': tracking.write_text(tracking.read_text() + 'changed')
                    if change == 'escape': item['tracking']['path'] = '../trace.md'
                    if change == 'missing': item['tracking']['path'] = 'missing.md'
                    path.write_text(json.dumps(report))
                    code, result = self.gate('--artifacts', str(path))
                    self.assertEqual(code, 0 if change == 'valid' else 1, result)

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
        self.assertEqual(len(cases), 6)
        self.assertEqual(len({case["id"] for case in cases}), 6)
        self.assertTrue(all(case["input"] for case in cases))

    @unittest.skipUnless(os.environ.get("PRODUCT_BEHAVIOR_REPORT"), "fresh model observations not supplied")
    def test_actual_fresh_context_behavior_and_upstream_identity(self):
        report = json.loads(Path(os.environ["PRODUCT_BEHAVIOR_REPORT"]).read_text())
        self.assertEqual(report["casesFingerprint"], hashlib.sha256(CASES.read_bytes()).hexdigest())
        self.assertEqual(report["skillIdentity"], skill_identity())
        current = diagnose(report["skillRoots"])
        self.assertTrue(current["ready"], current)
        self.assertEqual(report["dependencies"], current["dependencies"])
        self.assertEqual(report["runnerStatus"], "completed")
        self.assertEqual(report["roleStatus"], "available")
        check_observations(report)


if __name__ == "__main__":
    unittest.main()
