"""Public entry points must ship the example resources they link to."""
import hashlib
import json
import re
import struct
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


class PublicDocsTests(unittest.TestCase):
    def test_local_links_in_both_languages_and_showcase_resolve(self):
        documents = [ROOT / "README.md", ROOT / "README.en.md",
                     ROOT / "docs/examples/petclinic/README.md",
                     ROOT / "docs/examples/petclinic/developer-guide.md",
                     ROOT / "docs/media/README.md",
                     ROOT / "docs/SHARING.md"]
        for document in documents:
            with self.subTest(document=document.relative_to(ROOT)):
                self.assertTrue(document.is_file(), document)
                content = document.read_text()
                for target in re.findall(r"\]\(([^)]+)\)", content):
                    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith("#"):
                        continue
                    path = unquote(target.split("#", 1)[0])
                    with self.subTest(target=target):
                        self.assertTrue((document.parent / path).exists(), target)

    def test_showcase_preview_is_a_real_png_and_has_editable_sources(self):
        folder = ROOT / "docs/examples/petclinic"
        for name in ("architecture", "owner-flow"):
            with self.subTest(diagram=name):
                self.assertEqual((folder / f"{name}.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
                self.assertTrue((folder / f"{name}.mmd").read_text().strip())
                self.assertTrue((folder / f"{name}.evidence.json").is_file())

    def test_case_verification_matches_the_published_test_results(self):
        folder = ROOT / "docs/examples/petclinic"
        report = json.loads((folder / "verification.json").read_text())
        check = report["checks"]["upstreamControllerTests"]
        results = (folder / check["results"]).read_bytes()
        self.assertEqual(hashlib.sha256(results).hexdigest(), check["resultsSha256"])
        summary = json.loads(results)
        self.assertEqual(summary["sourceCommit"], report["sourceCommit"])
        self.assertEqual(summary["counts"], check["counts"])
        self.assertGreater(summary["counts"]["tests"], 0)
        self.assertEqual(len(summary["tests"]), summary["counts"]["tests"])
        self.assertEqual(len({(test["className"], test["name"]) for test in summary["tests"]}),
                         len(summary["tests"]))
        self.assertTrue(all(test["status"] == "pass" for test in summary["tests"]))
        self.assertEqual(check["exitCode"], 0)
        self.assertEqual(check["status"], "pass")
        for count in ("failures", "errors", "skipped"):
            self.assertEqual(summary["counts"][count], 0)

    def test_demo_gif_matches_its_checked_receipt_and_both_readmes(self):
        folder = ROOT / "docs/media"
        data = (folder / "petclinic-demo.gif").read_bytes()
        receipt = json.loads((folder / "petclinic-demo.json").read_text())
        self.assertEqual(data[:6], b"GIF89a")
        self.assertEqual(struct.unpack("<HH", data[6:10]), (960, 600))
        self.assertLessEqual(len(data), 5 * 1024 * 1024)
        self.assertEqual(len(data), receipt["bytes"])
        self.assertEqual(hashlib.sha256(data).hexdigest(), receipt["sha256"])
        self.assertEqual(receipt["frames"], 6)
        self.assertEqual(receipt["loop"], 0)
        self.assertIn("docs/examples/petclinic/verification.json", receipt["sources"])
        self.assertEqual(set(receipt["sources"]), set(receipt["sourceSha256"]))
        for path, digest in receipt["sourceSha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest, path)
        self.assertGreaterEqual(receipt["durationMs"], 15000)
        self.assertLessEqual(receipt["durationMs"], 25000)
        self.assertEqual(sum(receipt["frameDurationsMs"]), receipt["durationMs"])
        for name in ("README.md", "README.en.md"):
            content = (ROOT / name).read_text()
            self.assertIn("](docs/media/petclinic-demo.gif)", content)


if __name__ == "__main__":
    unittest.main()
