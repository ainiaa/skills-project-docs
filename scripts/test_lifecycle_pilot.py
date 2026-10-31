"""Persisted whole-chain simulation with real loopback HTTP execution."""
import hashlib
import json
from pathlib import Path
import tempfile
import shutil
from unittest.mock import patch
import unittest

from run_lifecycle_pilot import EXAMPLE, initial_record, run, serve_checks


class PilotTests(unittest.TestCase):
    def test_persisted_chain_preserves_identity_and_real_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pilot"
            result = run(output)
            self.assertEqual(result["status"], "isolated_release_verified")
            self.assertEqual(result["business_uat"], "simulated")
            self.assertEqual(result["production"], "not_run")
            self.assertEqual(result["record"]["branches"]["effects"], "incomplete")
            self.assertFalse(result["processes_left_running"])
            self.assertTrue((output / "lifecycle-record.json.rev-1.json").is_file())
            record = json.loads((output / "lifecycle-record.json").read_text())
            self.assertEqual(record["subject_ref"], "SIM-REPAIR-001")
            for node in record["artifacts"]:
                self.assertTrue((output / node["source"]).is_file(), node)
                for receipt in node["evidence"]:
                    self.assertTrue((output / receipt["source"]).is_file(), receipt)
            changed = json.loads((output / "scenarios/change-check.json").read_text())
            self.assertTrue(changed["needs_review"])
            manifest = json.loads((output / "manifest.json").read_text())
            for relative, digest in manifest.items():
                self.assertEqual(hashlib.sha256((output / relative).read_bytes()).hexdigest(), digest, relative)
            for name in ("healthy", "outage", "recovered"):
                receipt = json.loads((output / f"release/{name}.json").read_text())
                self.assertTrue(receipt["process_stopped"])
                self.assertEqual(receipt["status"], "passed")
                self.assertTrue(all(item["passed"] for item in receipt["checks"]))
            statuses = [item["status"] for item in json.loads((output / "release/outage.json").read_text())["checks"]]
            self.assertEqual(statuses, [503, 503])

    def test_missing_final_evidence_never_leaves_a_success_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            shutil.copytree(EXAMPLE, source)
            (source / "review.md").unlink()
            output = Path(directory) / "pilot"
            with patch("run_lifecycle_pilot.EXAMPLE", source):
                with self.assertRaises(RuntimeError):
                    run(output)
            self.assertFalse((output / "result.json").exists())
            for name in ("healthy", "outage", "recovered"):
                self.assertTrue(json.loads((output / f"release/{name}.json").read_text())["process_stopped"])

    def test_http_failure_stops_process_and_keeps_failure_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pilot"
            with patch("run_lifecycle_pilot.build_opener") as opener:
                opener.return_value.open.side_effect = OSError("injected request failure")
                with self.assertRaises(OSError):
                    run(output)
            self.assertFalse((output / "result.json").exists())
            receipt = json.loads((output / "release/healthy.json").read_text())
            self.assertTrue(receipt["process_stopped"])
            self.assertEqual(receipt["checks"], [])
            self.assertEqual(receipt["status"], "failed")

    def test_startup_waits_for_complete_port_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "release").mkdir()
            original_read = Path.read_text
            partial_seen = []
            def read(path, *args, **kwargs):
                if path.name == "healthy-port.json" and not partial_seen:
                    partial_seen.append(True)
                    return ""
                return original_read(path, *args, **kwargs)
            build = hashlib.sha256((EXAMPLE / "app.py").read_bytes()).hexdigest()
            with patch.object(Path, "read_text", read):
                serve_checks(EXAMPLE, output, "healthy", build)
            receipt = json.loads((output / "release/healthy.json").read_text())
            self.assertTrue(receipt["process_stopped"])
            self.assertEqual(len(receipt["checks"]), 8)

    def test_pre_prd_phases_reference_their_outputs_and_feed_requirement(self):
        nodes = {node["id"]: node for node in initial_record("fixture-build")["artifacts"]}
        sources = [nodes[key]["source"] for key in ("intake", "investigation", "decision")]
        self.assertEqual(len(set(sources)), 3)
        self.assertNotIn("source/input.md", sources)
        for relative in sources:
            self.assertTrue((EXAMPLE / Path(relative).name).is_file())
        for child, parent in (("investigation", "intake"), ("decision", "investigation"), ("requirement", "decision")):
            self.assertEqual(nodes[child]["depends_on"], [{"id": parent, "version": 1}])

    def test_missing_pre_prd_output_blocks_before_technical_execution(self):
        import run_lifecycle_pilot
        for contents in (None, ""):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "source"
                shutil.copytree(EXAMPLE, source)
                investigation = source / "investigation.md"
                if contents is None:
                    investigation.unlink(missing_ok=True)
                else:
                    investigation.write_text(contents)
                output = Path(directory) / "pilot"
                with patch("run_lifecycle_pilot.EXAMPLE", source), patch("run_lifecycle_pilot.command", wraps=run_lifecycle_pilot.command) as command:
                    with self.assertRaises(RuntimeError):
                        run(output)
                    command.assert_not_called()
                self.assertFalse((output / "result.json").exists())

    def test_unexecuted_or_skipped_business_tests_block_release(self):
        import run_lifecycle_pilot
        for mode in ("zero", "skipped", "expected-failure"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "source"
                shutil.copytree(EXAMPLE, source)
                test = source / "test_app.py"
                if mode == "zero":
                    test.write_text("from app import query\n")
                elif mode == "skipped":
                    test.write_text(test.read_text().replace("class RepairTests(unittest.TestCase):", '@unittest.skip("injected")\nclass RepairTests(unittest.TestCase):'))
                else:
                    test.write_text(test.read_text().replace("    def test_ac01_owner_sees_only_public_fields(self):", '    @unittest.expectedFailure\n    def test_ac01_owner_sees_only_public_fields(self):\n        self.fail("injected")'))
                output = Path(directory) / "pilot"
                with patch("run_lifecycle_pilot.EXAMPLE", source), patch("run_lifecycle_pilot.serve_checks", wraps=run_lifecycle_pilot.serve_checks) as serve:
                    with self.assertRaises(RuntimeError):
                        run(output)
                    serve.assert_not_called()
                self.assertFalse((output / "result.json").exists())
                self.assertFalse((output / "validation/uat-simulated.json").exists())

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sentinel = output / "user-file"
            sentinel.write_text("keep")
            with self.assertRaises(FileExistsError):
                run(output)
            self.assertEqual(sentinel.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
