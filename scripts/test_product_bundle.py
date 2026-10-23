"""Portable product evidence: references, freshness, and explicit limits."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from test_product_docs import PRD, HTML, ROOT


def artifact(path):
    return {"path": ("evidence/" if path.parent.name == "evidence" else "") + path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class ProductBundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="product bundle ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "evidence").mkdir()
        for name, text in {"prd.md": PRD, "prototype.html": HTML, "journey.test.mjs": "// generated assertions", "evidence/shot.png": "mock pixels"}.items():
            (self.root / name).write_text(text)
        self.files = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest() for name in ("prd.md", "prototype.html", "journey.test.mjs")}
        self.receipt = {"schemaVersion": 1, "tool": "product-browser-v1", "result": "pass",
                        "runnerFingerprint": hashlib.sha256((ROOT / "scripts/product_browser.mjs").read_bytes()).hexdigest(), "exitCode": 0,
                        "tests": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": [],
                        "source": self.files, "test": "journey.test.mjs", "pages": [artifact(self.root / "prototype.html")],
                        "screenshots": [{**artifact(self.root / "evidence/shot.png"), "viewport": {"width": 390, "height": 844}, "role": "approver", "scenario": "AC-001", "page": artifact(self.root / "prototype.html")}]}
        self.bundle = {"schemaVersion": 1, "version": "draft-1", "artifacts": {"prd": artifact(self.root / "prd.md"), "prototype": artifact(self.root / "prototype.html"),
                         "tests": [artifact(self.root / "journey.test.mjs")], "screenshots": [artifact(self.root / "evidence/shot.png")]},
                       "journeys": [{"id": "J1", "requirements": ["FR-001"], "scenarios": ["AC-001", "AC-002", "AC-003"], "test": "journey.test.mjs", "screenshots": ["evidence/shot.png"]}],
                       "browser": "browser.json"}

    def check(self, bundle=None, receipt=None):
        script = ROOT / "scripts/product_bundle.py"
        self.assertTrue(script.is_file(), "bundle checker missing")
        (self.root / "bundle.json").write_text(json.dumps(bundle or self.bundle))
        if (bundle or self.bundle).get("browser") == "browser.json":
            (self.root / "browser.json").write_text(json.dumps(receipt or self.receipt))
        result = subprocess.run([sys.executable, str(script), "--file", str(self.root / "bundle.json")], capture_output=True, text=True)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["valid"], result.returncode == 0)
        self.assertEqual(report["semanticCheck"], "not_proven")
        return report

    def split_bundle(self, prototype=False):
        from test_product_split import MAIN
        (self.root / 'prd.md').write_text(MAIN.replace('# 报名餐食', '# 退款审批示例'))
        tracking = self.root / 'trace.md'
        tracking.write_text('## 需求追踪\n> 追踪版本：draft-1\n\n' + PRD.split('## 来源与决策', 1)[1])
        self.files.update({'prd.md': artifact(self.root / 'prd.md')['sha256'], 'trace.md': artifact(tracking)['sha256']})
        self.receipt['source'] = dict(self.files)
        bundle = copy.deepcopy(self.bundle) if prototype else {'schemaVersion': 1, 'version': 'draft-1', 'artifacts': {}}
        bundle['artifacts'].update(prd=artifact(self.root / 'prd.md'), tracking=artifact(tracking))
        return bundle

    def test_bundle_accepts_split_document_and_maps_prototype_requirements(self):
        for prototype in (False, True):
            with self.subTest(prototype=prototype):
                bundle = self.split_bundle(prototype)
                result = self.check(bundle)
                self.assertTrue(result['valid'], result)

    def test_split_tracking_hash_version_and_link_are_required(self):
        bundle = self.split_bundle()
        original = (self.root / 'trace.md').read_text()
        for change in ('hash', 'version', 'link', 'missing', 'escape'):
            with self.subTest(change=change):
                current = copy.deepcopy(bundle)
                (self.root / 'trace.md').write_text(original)
                if change == 'hash': (self.root / 'trace.md').write_text(original + 'changed')
                if change == 'version':
                    (self.root / 'trace.md').write_text(original.replace('draft-1', 'draft-0'))
                    current['artifacts']['tracking'] = artifact(self.root / 'trace.md')
                if change == 'link':
                    document = self.root / 'prd.md'
                    document.write_text(document.read_text().replace('[验收追踪](trace.md)', '追踪另存'))
                    current['artifacts']['prd'] = artifact(document)
                if change == 'missing': current['artifacts']['tracking']['path'] = 'missing.md'
                if change == 'escape': current['artifacts']['tracking']['path'] = '../trace.md'
                self.assertFalse(self.check(current)['valid'])
                self.split_bundle()

    def test_split_baselines_are_explicit_pairs_and_reject_invalid_groups(self):
        bundle = self.split_bundle()
        old = self.root / 'old'
        old.mkdir()
        for name in ('prd.md', 'trace.md'):
            (old / name).write_bytes((self.root / name).read_bytes())
        pair = [{'path': 'old/' + name, 'sha256': artifact(old / name)['sha256']} for name in ('prd.md', 'trace.md')]
        bundle['artifacts']['baselines'] = [pair]
        self.assertTrue(self.check(bundle)['valid'])
        for invalid in ([], pair[:1], pair * 2, list(reversed(pair))):
            with self.subTest(group=invalid):
                bundle['artifacts']['baselines'] = [invalid]
                self.assertFalse(self.check(bundle)['valid'])

    def test_split_baseline_pair_is_bound_to_browser_inventory(self):
        bundle = self.split_bundle(prototype=True)
        old = self.root / 'old'
        old.mkdir()
        for name in ('prd.md', 'trace.md'):
            (old / name).write_bytes((self.root / name).read_bytes())
            self.files['old/' + name] = artifact(old / name)['sha256']
        self.receipt['source'] = dict(self.files)
        pair = [{'path': 'old/' + name, 'sha256': self.files['old/' + name]} for name in ('prd.md', 'trace.md')]
        bundle['artifacts']['baselines'] = [pair]
        self.assertTrue(self.check(bundle)['valid'])
        (old / 'trace.md').write_text((old / 'trace.md').read_text() + '\n修改历史证据\n')
        pair[1]['sha256'] = artifact(old / 'trace.md')['sha256']
        result = self.check(bundle)
        self.assertFalse(result['valid'])
        self.assertIn('浏览器输入清单已变化', ' '.join(result['problems']))

    def test_missing_historical_resource_is_rejected_even_in_fresh_browser_snapshot(self):
        bundle = self.split_bundle(prototype=True)
        old = self.root / 'old'
        old.mkdir()
        for name in ('prd.md', 'trace.md'):
            (old / name).write_bytes((self.root / name).read_bytes())
        path = old / 'trace.md'
        path.write_text(path.read_text() + '\n[历史资料](../../outside-source.md)\n')
        pair = []
        for name in ('prd.md', 'trace.md'):
            digest = artifact(old / name)['sha256']
            self.files['old/' + name] = digest
            pair.append({'path': 'old/' + name, 'sha256': digest})
        self.receipt['source'] = dict(self.files)
        bundle['artifacts']['baselines'] = [pair]
        result = self.check(bundle)
        self.assertFalse(result['valid'], result)
        self.assertIn('历史基线无效', ' '.join(result['problems']))

    def test_split_tracking_change_invalidates_browser_inventory(self):
        bundle = self.split_bundle(prototype=True)
        self.assertTrue(self.check(bundle)['valid'])
        tracking = self.root / 'trace.md'
        tracking.write_text(tracking.read_text() + '\n新证据\n')
        bundle['artifacts']['tracking'] = artifact(tracking)
        self.assertFalse(self.check(bundle)['valid'])

    def diagram_bundle(self, prototype=False):
        (self.root / "flow.puml").write_text("@startuml\nstart\n:申请退款 FR-001;\nstop\n@enduml")
        (self.root / "flow.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>fixture</text></svg>')
        bundle = copy.deepcopy(self.bundle) if prototype else {
            "schemaVersion": 1, "version": "draft-1", "artifacts": {"prd": artifact(self.root / "prd.md")}}
        bundle["diagrams"] = [{"version": "draft-1", "requirements": ["FR-001"], "scenarios": ["AC-001"],
                               "source": artifact(self.root / "flow.puml"), "exports": [artifact(self.root / "flow.svg")]}]
        for name in ("flow.puml", "flow.svg"):
            self.files[name] = artifact(self.root / name)["sha256"]
        return bundle

    def test_diagram_file_aliases_cannot_bypass_source_and_export_uniqueness(self):
        bundle = self.diagram_bundle()
        (self.root / "alias").mkdir()
        alias_source = copy.deepcopy(bundle["diagrams"][0]["source"])
        alias_source["path"] = "alias/../flow.puml"
        alias_export = copy.deepcopy(bundle["diagrams"][0]["exports"][0])
        alias_export["path"] = "alias/../flow.svg"
        duplicate_source = copy.deepcopy(bundle)
        second = copy.deepcopy(duplicate_source["diagrams"][0]); second["source"] = alias_source
        duplicate_source["diagrams"].append(second)
        duplicate_exports = copy.deepcopy(bundle)
        duplicate_exports["diagrams"][0]["exports"].append(alias_export)
        source_as_export = copy.deepcopy(bundle)
        source_as_export["diagrams"][0]["exports"] = [alias_source]
        for bad in (duplicate_source, duplicate_exports, source_as_export):
            self.assertFalse(self.check(bad)["valid"])
        # A single contained alias is legal; identity comparison must still resolve it.
        bundle["diagrams"][0]["source"] = alias_source
        self.assertTrue(self.check(bundle)["valid"])

    def test_diagram_aliases_bind_to_the_same_canonical_browser_inputs(self):
        bundle = self.diagram_bundle(prototype=True)
        (self.root / "alias").mkdir()
        self.assertTrue(self.check(bundle)["valid"])
        for source_alias, export_alias in ((True, False), (False, True), (True, True)):
            candidate = copy.deepcopy(bundle)
            if source_alias:
                candidate["diagrams"][0]["source"]["path"] = "alias/../flow.puml"
            if export_alias:
                candidate["diagrams"][0]["exports"][0]["path"] = "alias/../flow.svg"
            self.assertTrue(self.check(candidate)["valid"], "Same files and hashes must bind to the same browser snapshot")

    def test_optional_diagrams_work_with_prd_only_and_browser_delivery(self):
        self.assertTrue(self.check(self.diagram_bundle())["valid"])
        self.assertTrue(self.check(self.diagram_bundle(prototype=True))["valid"])
        # No diagrams remains a supported, lightweight delivery.
        self.assertTrue(self.check({"schemaVersion": 1, "version": "draft-1",
                                   "artifacts": {"prd": artifact(self.root / "prd.md")}})["valid"])

    def test_diagram_index_rejects_stale_versions_hashes_and_wrong_fr_ac(self):
        bundle = self.diagram_bundle()
        cases = [{"version": "old"}, {"requirements": ["FR-999"]}, {"requirements": []},
                 {"requirements": "FR-001"}, {"requirements": ["FR-001", "FR-001"]},
                 {"scenarios": ["AC-999"]}, {"scenarios": "AC-001"}, {"scenarios": ["AC-001", "AC-001"]},
                 {"exports": []}, {"exports": "flow.svg"},
                 {"source": {"path": "../outside.puml", "sha256": "0" * 64}},
                 {"source": {"path": "flow.puml", "sha256": "0" * 64}},
                 {"exports": [{"path": "flow.svg", "sha256": "0" * 64}]}]
        for delta in cases:
            with self.subTest(delta=delta):
                bad = copy.deepcopy(bundle); bad["diagrams"][0].update(delta)
                self.assertFalse(self.check(bad)["valid"], delta)
        for value in ({}, "flow.puml", [None], [bundle["diagrams"][0], bundle["diagrams"][0]]):
            bad = copy.deepcopy(bundle); bad["diagrams"] = value
            self.assertFalse(self.check(bad)["valid"], value)
        changed = PRD.replace("原型：是", "原型：否") + "\n### FR-002 查询\n状态：草稿\n依据：SRC-001\n原型：否\n#### AC-004 查询\n看到结果。\n"
        (self.root / "prd.md").write_text(changed)
        bundle["artifacts"]["prd"] = artifact(self.root / "prd.md")
        bundle["diagrams"][0]["scenarios"] = ["AC-004"]
        self.assertFalse(self.check(bundle)["valid"], "An existing AC must belong to a mapped FR")

    @unittest.skipUnless(os.environ.get("PRODUCT_BROWSER_MODULES") or os.environ.get("MERMAID_OFFICIAL_CLI"), "browser runtime is not configured")
    def test_generic_browser_runs_delivery_assertions_and_records_stable_capture(self):
        runner = ROOT / "scripts/product_browser.mjs"
        self.assertTrue(runner.is_file(), "generic browser runner missing")
        module = runner.as_uri()
        test = self.root / "journey.test.mjs"
        test.write_text("import {test} from 'node:test'; import assert from 'node:assert/strict';\n"
                        + f"import {{launchBrowser, openPage, capture}} from {json.dumps(module)};\n"
                        + "test('actual delivered journey', async () => { const browser = await launchBrowser(); try { const page = await openPage(browser, 'prototype.html'); assert.equal(await page.title(), ''); await capture(page, 'mobile.png', {role:'approver',scenario:'AC-001'}); } finally {await browser.close();} });\n")
        result = subprocess.run(["node", str(runner), "--directory", str(self.root), "--test", test.name], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads((self.root / "evidence/browser.json").read_text())
        self.assertEqual(report["result"], "pass")
        self.assertEqual(report["tests"], 1)
        self.assertEqual(report["source"]["prototype.html"], self.files["prototype.html"])
        self.assertEqual(report["screenshots"][0]["scenario"], "AC-001")
        self.assertTrue((self.root / "evidence/mobile.png").is_file())
        delivered = copy.deepcopy(self.bundle)
        screenshot = {**artifact(self.root / "evidence/mobile.png"), "path": "evidence/mobile.png"}
        delivered["artifacts"]["tests"] = [artifact(test)]
        delivered["artifacts"]["screenshots"] = [screenshot]
        delivered["journeys"][0]["screenshots"] = [screenshot["path"]]
        delivered["browser"] = "evidence/browser.json"
        self.assertTrue(self.check(delivered)["valid"])
        original_test = test.read_text()
        (self.root / "old.html").write_text(HTML + "<!-- different old prototype -->")
        test.write_text(original_test.replace("'prototype.html'", "'old.html'"))
        result = subprocess.run(["node", str(runner), "--directory", str(self.root), "--test", test.name], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        delivered["artifacts"]["tests"] = [artifact(test)]
        delivered["artifacts"]["screenshots"] = [{**artifact(self.root / "evidence/mobile.png"), "path": "evidence/mobile.png"}]
        self.assertFalse(self.check(delivered)["valid"], "Opening old.html cannot validate prototype.html")
        race_test = original_test.replace("'prototype.html'", "'old.html'").replace(
            "await capture(page,", "const render = page.screenshot.bind(page); page.screenshot = async options => { await render(options); await page.goto(new URL('prototype.html', page.url()).href); }; await capture(page,")
        test.write_text(race_test)
        result = subprocess.run(["node", str(runner), "--directory", str(self.root), "--test", test.name], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0, "Page navigation during capture must invalidate evidence")
        test.write_text(original_test)
        result = subprocess.run(["node", str(runner), "--directory", str(self.root), "--test", test.name], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        delivered["artifacts"]["tests"] = [artifact(test)]
        delivered["artifacts"]["screenshots"] = [{**artifact(self.root / "evidence/mobile.png"), "path": "evidence/mobile.png"}]
        self.assertTrue(self.check(delivered)["valid"])
        (self.root / "prototype.html").write_text(HTML + "<!-- changed after browser -->")
        delivered["artifacts"]["prototype"] = artifact(self.root / "prototype.html")
        self.assertFalse(self.check(delivered)["valid"])
        for content in ("import {test} from 'node:test'; test('fails', () => {throw Error('business assertion');});", "// no tests", "import {test} from 'node:test'; test('no browser used', () => {});"):
            test.write_text(content)
            result = subprocess.run(["node", str(runner), "--directory", str(self.root), "--test", test.name], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            report = json.loads((self.root / "evidence/browser.json").read_text())
            self.assertEqual(report["result"], "fail")

    @unittest.skipUnless(os.environ.get("PRODUCT_BROWSER_MODULES") or os.environ.get("MERMAID_OFFICIAL_CLI"), "browser runtime is not configured")
    def test_browser_refuses_external_output_and_reports_unavailable_runtime(self):
        runner = ROOT / "scripts/product_browser.mjs"
        evidence = self.root / "evidence"; evidence.mkdir(exist_ok=True)
        outside = self.root.parent / (self.root.name + "-preserve.txt")
        outside.write_text("keep"); self.addCleanup(outside.unlink)
        (evidence / "browser.json").symlink_to(outside)
        args = ["node", str(runner), "--directory", str(self.root), "--test", "journey.test.mjs"]
        result = subprocess.run(args, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outside.read_text(), "keep")
        (evidence / "browser.json").unlink()
        result = subprocess.run(args, text=True, capture_output=True, env={**os.environ, "PUPPETEER_EXECUTABLE_PATH": str(self.root / "missing-chrome")})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(json.loads((evidence / "browser.json").read_text())["result"], "unverified")

    def test_current_linked_delivery_accepts_observed_browser_evidence(self):
        self.assertTrue(self.check()["valid"])

    def test_output_files_cannot_be_prototype_inputs(self):
        for target in ("evidence/rules.js", "bundle.json", "review.md"):
            with self.subTest(target=target):
                (self.root / target).write_text("// business input")
                (self.root / "prototype.html").write_text(HTML + f'<script src="{target}"></script>')
                self.bundle["artifacts"]["prototype"] = artifact(self.root / "prototype.html")
                self.files["prototype.html"] = self.bundle["artifacts"]["prototype"]["sha256"]
                self.receipt["pages"] = [artifact(self.root / "prototype.html")]
                self.receipt["screenshots"][0]["page"] = artifact(self.root / "prototype.html")
                self.assertFalse(self.check()["valid"], "Outputs must never supply untracked behavior")

    @unittest.skipUnless(os.environ.get("PRODUCT_BROWSER_MODULES") or os.environ.get("MERMAID_OFFICIAL_CLI"), "browser runtime is not configured")
    def test_browser_rejects_dynamic_loads_of_excluded_outputs(self):
        runner = ROOT / "scripts/product_browser.mjs"
        (self.root / "evidence/rules.js").write_text("window.threshold = 500")
        (self.root / "prototype.html").write_text(HTML + '<script>const s=document.createElement("script");s.src="evidence/rules.js";document.body.append(s)</script>')
        (self.root / "journey.test.mjs").write_text(
            "import {test} from 'node:test';\n"
            + f"import {{launchBrowser, openPage}} from {json.dumps(runner.as_uri())};\n"
            + "test('dynamic business input', async () => {const b=await launchBrowser();try{await openPage(b)}finally{await b.close()}});\n")
        result = subprocess.run(["node", str(runner), "--directory", str(self.root), "--test", "journey.test.mjs"], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotEqual(json.loads((self.root / "evidence/browser.json").read_text())["result"], "pass")

    def test_changed_or_missing_artifacts_invalidate_old_browser_evidence(self):
        for filename in ("prd.md", "prototype.html", "journey.test.mjs", "evidence/shot.png"):
            with self.subTest(filename=filename):
                path = self.root / filename
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                self.assertFalse(self.check()["valid"])
                path.write_bytes(original)
        (self.root / "evidence/shot.png").unlink()
        self.assertFalse(self.check()["valid"])

    def test_updated_manifest_cannot_hide_stale_browser_inputs(self):
        (self.root / "prototype.html").write_text(HTML + "<!-- changed -->")
        self.bundle["artifacts"]["prototype"] = artifact(self.root / "prototype.html")
        self.assertFalse(self.check()["valid"])

    def test_baseline_approved_prd_can_be_indexed_without_rewriting_confirmation(self):
        old = PRD.replace("状态：待确认", "状态：已确认\n确认记录：业务负责人接受 draft-1。")
        (self.root / "previous.md").write_text(old)
        (self.root / "prd.md").write_text(old.replace("> 产品版本：draft-1", "> 产品版本：draft-2"))
        bundle = {"schemaVersion": 1, "version": "draft-2", "artifacts": {"prd": artifact(self.root / "prd.md"), "baselines": [artifact(self.root / "previous.md")]}}
        self.assertTrue(self.check(bundle)["valid"])

    def test_changed_browser_runner_invalidates_receipt(self):
        self.receipt["runnerFingerprint"] = "0" * 64
        self.assertFalse(self.check()["valid"])

    def test_screenshot_scenario_must_belong_to_the_referencing_journey(self):
        (self.root / "evidence/second.png").write_text("second pixels")
        second = artifact(self.root / "evidence/second.png")
        self.bundle["artifacts"]["screenshots"].append(second)
        self.receipt["screenshots"].append({**second, "viewport": {"width": 1440, "height": 1000}, "role": "approver", "scenario": "AC-002", "page": artifact(self.root / "prototype.html")})
        self.bundle["journeys"] = [
            {"id": "J1", "requirements": ["FR-001"], "scenarios": ["AC-001"], "test": "journey.test.mjs", "screenshots": ["evidence/second.png"]},
            {"id": "J2", "requirements": ["FR-001"], "scenarios": ["AC-002", "AC-003"], "test": "journey.test.mjs", "screenshots": ["evidence/shot.png"]},
        ]
        self.assertFalse(self.check()["valid"])
        self.bundle["journeys"][0]["screenshots"] = ["evidence/shot.png"]
        self.bundle["journeys"][1]["screenshots"] = ["evidence/second.png"]
        self.assertTrue(self.check()["valid"])

    def test_new_inputs_invalidate_old_inventory(self):
        (self.root / "cases").mkdir()
        (self.root / "cases/new-case.json").write_text('{"new":true}')
        self.assertFalse(self.check()["valid"])

    def test_receipt_must_identify_the_declared_prototype_page(self):
        self.receipt["pages"] = [{"path": "old.html", "sha256": "0" * 64}]
        self.assertFalse(self.check()["valid"])

    def test_missing_failed_empty_or_incomplete_browser_evidence_never_passes(self):
        for change in ({"result": "not_run"}, {"exitCode": 1}, {"tests": 0, "passed": 0}, {"errors": ["page error"]}, {"skipped": 1}, {"source": {}}, {"screenshots": []}):
            with self.subTest(change=change):
                self.assertFalse(self.check(receipt={**self.receipt, **change})["valid"])
        self.bundle.pop("browser")
        self.assertFalse(self.check()["valid"])

    def test_foreign_scenarios_versions_and_escaping_paths_are_rejected(self):
        for mutate in (lambda b: b.update(version="old"),
                       lambda b: b["journeys"][0].update(scenarios=["AC-999"]),
                       lambda b: b["journeys"][0].update(requirements=["FR-999"]),
                       lambda b: b["artifacts"]["prd"].update(path="../prd.md"),
                       lambda b: b["artifacts"]["prd"].update(path="https://example.invalid/prd.md"),
                       lambda b: b["journeys"].clear()):
            value = copy.deepcopy(self.bundle); mutate(value)
            self.assertFalse(self.check(value)["valid"])

    def test_prd_only_bundle_needs_no_browser(self):
        bundle = {"schemaVersion": 1, "version": "draft-1", "artifacts": {"prd": artifact(self.root / "prd.md")}}
        report = self.check(bundle)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["browserCheck"], "not_requested")

    def test_malformed_and_symlink_resources_fail_closed(self):
        self.bundle["artifacts"]["tests"] = "wrong"
        self.assertFalse(self.check()["valid"])
        self.bundle["artifacts"]["tests"] = [artifact(self.root / "journey.test.mjs")]
        outside = self.root.parent / (self.root.name + ".png")
        outside.write_text("outside"); self.addCleanup(outside.unlink)
        (self.root / "evidence/shot.png").unlink(); (self.root / "evidence/shot.png").symlink_to(outside)
        self.assertFalse(self.check()["valid"])


if __name__ == "__main__":
    unittest.main()
