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
        documents = [ROOT / "README.md", ROOT / "README.en.md", ROOT / "README.zh-CN.md",
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
        for name in ("README.md", "README.zh-CN.md"):
            content = (ROOT / name).read_text()
            self.assertIn("](docs/media/petclinic-demo.gif)", content)

    def test_language_entrypoints_preserve_legacy_section_links(self):
        english = (ROOT / "README.md").read_text()
        chinese = (ROOT / "README.zh-CN.md").read_text()
        legacy = (ROOT / "README.en.md").read_text()
        self.assertIn("## Quick start", english)
        self.assertIn("[中文](README.zh-CN.md)", english)
        self.assertIn("[English](README.md)", chinese)
        self.assertIn("## 安装与升级", chinese)
        self.assertIn("## 生命周期首个切片", chinese)
        for title, slug in (("Quick start", "quick-start"), ("Choose a task", "choose-a-task"),
                            ("Trust and limits", "trust-and-limits"),
                            ("Try it and share feedback", "try-it-and-share-feedback")):
            self.assertIn("## " + title, legacy)
            self.assertIn("](README.md#" + slug + ")", legacy)
        slugs = ("快速开始|选哪个-skill|按读者与用途交付|eli5-与多场景图解|为什么会有它|"
                 "产品需求与可点击原型|prd-与增量需求|可点击原型与实际验收|结构校验与历史修订|"
                 "上游能力与验证边界|能力与边界|四个渲染引擎分别能画什么|一页说明archify-explainer|"
                 "安装与升级|宿主支持|渲染引擎要另外安装吗|使用-project-docs-api|使用-project-docs-overview|"
                 "使用-project-docs-diagram|引擎如何参与生成|文档|开发与验证|参考与鸣谢|许可与反馈|生命周期首个切片")
        for slug in slugs.split("|"):
            with self.subTest(legacy_section=slug):
                self.assertIn(f'<a id="{slug}"></a>', english)
                self.assertIn("README.zh-CN.md#" + slug, english)


if __name__ == "__main__":
    unittest.main()
