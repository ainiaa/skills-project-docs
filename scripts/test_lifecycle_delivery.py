"""Headless synthetic lifecycle replay; business decisions remain simulated."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from lifecycle_record import check_record, update_record

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "skills/project-docs-lifecycle/assets/examples/order-status"


class DeliveryTests(unittest.TestCase):
    def test_trace_build_test_isolated_deploy_failure_and_resume(self):
        with tempfile.TemporaryDirectory(prefix="lifecycle-replay-") as directory:
            work = Path(directory)
            shutil.copytree(EXAMPLE, work / "source")
            source = work / "source"
            tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_status.py"],
                                   cwd=source, capture_output=True, text=True, timeout=30)
            self.assertEqual(tests.returncode, 0, tests.stderr)
            (work / "tests.log").write_text(tests.stdout + tests.stderr)
            build = hashlib.sha256((source / "status.py").read_bytes()).hexdigest()
            release = work / "isolated-release" / build
            release.mkdir(parents=True)
            shutil.copy2(source / "status.py", release / "status.py")
            self.assertEqual(hashlib.sha256((release / "status.py").read_bytes()).hexdigest(), build)
            smoke = subprocess.run([sys.executable, "status.py", "owner", "EX-1"], cwd=release,
                                   capture_output=True, text=True, timeout=10)
            self.assertEqual(smoke.returncode, 0, smoke.stderr)
            self.assertEqual(json.loads(smoke.stdout)["status"], "investigating")
            (work / "smoke.log").write_text(smoke.stdout)
            (work / "build.json").write_text(json.dumps({"build": build, "source": "source/status.py",
                                                        "environment": "isolated-local-process", "result": "passed"}))
            data = json.loads((source / "lifecycle-record.json").read_text())
            self.assertEqual(data["subject_ref"], "FR-EX-1")
            self.assertEqual(len(data["artifacts"]), 11)
            for node in data["artifacts"]:
                node.update(build=build, environment="isolated-local-process", scope="synthetic-EX-1")
                for evidence in node["evidence"]:
                    evidence.update(build=build, environment="isolated-local-process", scope="synthetic-EX-1")
                    if evidence["kind"] == "executed":
                        evidence["source"] = {"code-build": "build.json", "test": "tests.log", "deploy-smoke": "smoke.log"}[node["id"]]
                        evidence["method"] = {"code-build": "SHA-256 of tested status.py", "test": "python -m unittest discover",
                                              "deploy-smoke": "python status.py owner EX-1"}[node["id"]]
                        evidence.update(at=datetime.now(timezone.utc).isoformat(), build=build,
                                        environment="isolated-local-process", scope="synthetic-EX-1")
            # Real technical receipts must resolve to this execution's captured artifacts.
            for node in (data["artifacts"][5], data["artifacts"][6], data["artifacts"][9]):
                receipt_path = work / node["evidence"][0]["source"]
                self.assertTrue(receipt_path.is_file(), receipt_path)
                self.assertTrue(receipt_path.resolve().is_relative_to(work.resolve()))
            result = check_record(data)
            self.assertTrue(result["valid"], result)
            self.assertEqual(result["branches"]["local-demo"], "recorded")
            self.assertEqual(data["validation_scope"]["business_uat"], "simulated")
            # A failed release smoke is a separate failure, never a success claim.
            (release / "status.py").write_text("raise RuntimeError('injected deployment failure')\n")
            failure = subprocess.run([sys.executable, "status.py", "owner", "EX-1"], cwd=release,
                                     capture_output=True, text=True, timeout=10)
            self.assertNotEqual(failure.returncode, 0)
            failed = copy.deepcopy(data)
            failed["artifacts"][9].update(status="blocked", reason="Injected smoke failure",
                                          recovery="Restore prior package and rerun smoke")
            failed["artifacts"][9]["evidence"][0]["result"] = "failed"
            self.assertEqual(check_record(failed)["branches"]["local-demo"], "needs_review")
            # Recovery in an isolated release uses the same verified bytes.
            recovery = work / "recovered-release"
            recovery.mkdir()
            shutil.copy2(source / "status.py", recovery / "status.py")
            self.assertEqual(hashlib.sha256((recovery / "status.py").read_bytes()).hexdigest(), build)
            recovered = subprocess.run([sys.executable, "status.py", "owner", "EX-1"], cwd=recovery,
                                       capture_output=True, text=True, timeout=10)
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertEqual(json.loads(recovered.stdout), json.loads(smoke.stdout))
            path = work / "lifecycle-record.json"
            path.write_text(json.dumps(data))
            changed = copy.deepcopy(data)
            changed["revision"] = 2
            changed["artifacts"][3]["version"] = 2
            update_record(path, changed, 1)
            resumed = json.loads(path.read_text())
            self.assertEqual(resumed["subject_ref"], "FR-EX-1")
            self.assertEqual([n["id"] for n in resumed["artifacts"]], [n["id"] for n in data["artifacts"]])
            review = {entry["id"] for entry in check_record(resumed)["needs_review"]}
            self.assertIn("deploy-smoke", review)
            self.assertNotIn("intake", review)

    def test_shared_release_partial_rollout_and_pending_effect_are_separate(self):
        data = json.loads((EXAMPLE / "branched-record.json").read_text())
        result = check_record(data)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["needs_review"], [])
        self.assertEqual(result["branches"], {"core": "recorded", "pilot": "recorded", "rollout": "incomplete", "effects": "incomplete"})
        nodes = {node["id"]: node for node in data["artifacts"]}
        self.assertEqual({ref["id"] for ref in nodes["code-build"]["depends_on"]}, {"work-query", "work-notify"})
        for deployment in ("deploy-smoke", "deploy-rollout"):
            self.assertIn({"id": "code-build", "version": 1}, nodes[deployment]["depends_on"])
        for requirement in ("requirement", "requirement-notify"):
            self.assertEqual(nodes[requirement]["depends_on"], [{"id": "decision", "version": 1}])
        nodes["code-build"]["version"] = 2
        result = check_record(data)
        reviewed = {entry["id"] for entry in result["needs_review"]}
        self.assertTrue({"deploy-smoke", "deploy-rollout", "handover"} <= reviewed)
        self.assertTrue({"intake", "requirement", "requirement-notify"}.isdisjoint(reviewed))
        self.assertEqual(result["branches"]["rollout"], "needs_review")

    def test_template_starts_incomplete_without_fabricated_evidence(self):
        template = json.loads((ROOT / "skills/project-docs-lifecycle/assets/lifecycle-record.json").read_text())
        result = check_record(template)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["branches"], {"main": "incomplete"})
        self.assertEqual(template["artifacts"][0]["evidence"], [])


if __name__ == "__main__":
    unittest.main()
