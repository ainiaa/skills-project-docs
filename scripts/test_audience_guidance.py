"""Shared audience guidance stays reachable from direct and linked Skill entries."""

import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STANDARD = ROOT / "references/audience.md"
SKILLS = ("project-docs", "project-docs-product", "project-docs-overview",
          "project-docs-api", "project-docs-diagram", "project-docs-lifecycle")


class AudienceGuidanceTests(unittest.TestCase):
    def test_shared_guidance_is_reachable_through_every_direct_install(self):
        self.assertTrue(STANDARD.is_file())
        with tempfile.TemporaryDirectory() as directory:
            for name in SKILLS:
                with self.subTest(skill=name):
                    installed = Path(directory) / name
                    installed.symlink_to(ROOT / "skills" / name, target_is_directory=True)
                    links = re.findall(r"\]\(([^)]+)\)", (installed / "SKILL.md").read_text())
                    targets = {(installed / link.split("#")[0]).resolve() for link in links
                               if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", link)}
                    self.assertIn(STANDARD.resolve(), targets)

    def test_shared_guidance_examples_are_available(self):
        text = STANDARD.read_text()
        links = re.findall(r"\]\(([^)]+)\)", text)
        self.assertTrue(links)
        for link in links:
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", link) or link.startswith("#"):
                continue
            with self.subTest(resource=link):
                self.assertTrue((STANDARD.parent / link.split("#")[0]).resolve().is_file())


if __name__ == "__main__":
    unittest.main()
