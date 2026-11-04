"""Read-only upstream dependency diagnostics, including incomplete and shadowed skills."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {"brainstorming": (), "grilling": (), "domain-modeling": ("GLOSSARY-FORMAT.md", "ADR-FORMAT.md")}


class ProductDependencyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="product upstream ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def populate(self, root):
        for name, references in REQUIRED.items():
            directory = root / name
            directory.mkdir(parents=True)
            (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test skill\n---\n# {name}\n")
            for reference in references:
                (directory / reference).write_text("# Format\n")

    def check(self, *roots, pdlc_roots=()):
        script = ROOT / "scripts/product_dependencies.py"
        self.assertTrue(script.is_file(), "upstream dependency diagnostics are missing")
        args = [sys.executable, str(script)]
        for root in roots:
            args += ["--skill-root", str(root)]
        for root in pdlc_roots:
            args += ["--pdlc-root", str(root)]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["ready"], result.returncode == 0)
        self.assertEqual(report["hostVisibility"], "not_checked")
        self.assertEqual(report["behaviorCheck"], "not_run")
        return report

    def pdlc(self, root):
        directory = root / "pdlc-prd"
        (directory / "assets").mkdir(parents=True)
        (directory / "SKILL.md").write_text("---\nname: pdlc-prd\n---\n# Native stage\n")
        (directory / "assets/prd-template.md").write_text("# Native PRD template\n")
        return directory

    def test_optional_pdlc_missing_does_not_block_independent_product_workflow(self):
        self.populate(self.root)
        report = self.check(self.root, pdlc_roots=(self.root / "missing",))
        self.assertTrue(report["ready"])
        self.assertEqual(report["pdlc"]["status"], "missing")
        self.assertEqual(report["pdlc"]["compatibility"], "unavailable")
        self.assertFalse((self.root / "missing").exists())

    def test_installed_pdlc_reports_identity_without_claiming_native_adoption_or_writing_state(self):
        self.populate(self.root)
        directory = self.pdlc(self.root)
        marker = self.root / "docs/.pdlc-state/F20261021-01.json"
        marker.parent.mkdir(parents=True)
        marker.write_text('{"current_stage":"review"}')
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        report = self.check(self.root, pdlc_roots=(directory,))
        self.assertTrue(report["ready"])
        self.assertEqual(report["pdlc"]["status"], "available")
        self.assertEqual(report["pdlc"]["compatibility"], "handoff_only")
        self.assertEqual(report["pdlc"]["stateWrite"], "not_attempted")
        self.assertRegex(report["pdlc"]["contentFingerprint"], r"^[a-f0-9]{64}$")
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_optional_pdlc_incomplete_and_shadowed_versions_are_not_selected(self):
        self.populate(self.root)
        first, second = self.pdlc(self.root / "first"), self.pdlc(self.root / "second")
        (second / "SKILL.md").write_text((second / "SKILL.md").read_text() + "different\n")
        report = self.check(self.root, pdlc_roots=(first, second))
        self.assertTrue(report["ready"])
        self.assertEqual(report["pdlc"]["status"], "ambiguous")
        (first / "assets/prd-template.md").unlink()
        self.assertEqual(self.check(self.root, pdlc_roots=(first,))["pdlc"]["status"], "incomplete")

    def test_optional_pdlc_discovery_permission_error_keeps_required_readiness(self):
        from product_dependencies import diagnose
        self.populate(self.root)
        directory = self.pdlc(self.root)
        for method, target in (("stat", directory / "SKILL.md"), ("resolve", directory), ("expanduser", directory)):
            original = getattr(Path, method)
            def denied(path, *args, **kwargs):
                if path == target:
                    raise PermissionError(13, "Permission denied", str(path))
                return original(path, *args, **kwargs)
            with self.subTest(method=method), patch.object(Path, method, denied):
                report = diagnose((self.root,), (directory,))
            self.assertTrue(report["ready"])
            self.assertEqual(report["pdlc"]["status"], "incomplete")
            self.assertEqual(report["pdlc"]["compatibility"], "unavailable")
            self.assertIn("Permission denied", str(report["pdlc"]["candidates"]))

    def test_complete_dependencies_report_content_identity_without_latest_claim(self):
        self.populate(self.root)
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        report = self.check(self.root)
        self.assertTrue(report["ready"], report)
        for item in report["dependencies"]:
            self.assertEqual(item["status"], "available")
            self.assertEqual(item["versionState"], "unknown")
            self.assertRegex(item["contentFingerprint"], r"^[a-f0-9]{64}$")
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_missing_roots_and_references_do_not_install_or_claim_ready(self):
        self.assertFalse(self.check(self.root / "missing")["ready"])
        self.assertFalse((self.root / "missing").exists())
        self.populate(self.root)
        (self.root / "domain-modeling/ADR-FORMAT.md").unlink()
        self.assertFalse(self.check(self.root)["ready"])

    def test_empty_malformed_or_wrong_skill_is_rejected(self):
        self.populate(self.root)
        entry = self.root / "grilling/SKILL.md"
        for text in ("", "# unrelated", "---\nname: other\n---\n# Other"):
            with self.subTest(text=text):
                entry.write_text(text)
                self.assertFalse(self.check(self.root)["ready"])

    def test_distinct_shadowed_entries_are_not_guessed(self):
        first, second = self.root / "one", self.root / "two"
        self.populate(first)
        self.populate(second)
        self.assertTrue(self.check(first, second)["ready"])
        entry = second / "grilling/SKILL.md"
        entry.write_text(entry.read_text() + "Different version\n")
        self.assertFalse(self.check(first, second)["ready"])

    def test_symlinked_installation_and_explicit_skill_directories_work(self):
        source, installed = self.root / "source", self.root / "installed"
        self.populate(source)
        installed.mkdir()
        for name in REQUIRED:
            (installed / name).symlink_to(source / name, target_is_directory=True)
        self.assertTrue(self.check(installed)["ready"])
        self.assertTrue(self.check(*(source / name for name in REQUIRED))["ready"])


if __name__ == "__main__":
    unittest.main()
