"""Public entry points must ship the example resources they link to."""
import hashlib
import json
import re
import struct
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
IN_SNAPSHOT = ROOT.name == ".bundle"


class PublicDocsTests(unittest.TestCase):
    def test_skill_catalog_introductions_are_english_with_chinese_docs(self):
        entry_name = "GUIDE.md" if IN_SNAPSHOT else "SKILL.md"
        chinese_readme = "../../README.zh-CN.md" if IN_SNAPSHOT else ".bundle/README.zh-CN.md"
        skills = sorted((ROOT / "skills").glob(f"project-docs*/{entry_name}"))
        self.assertEqual(len(skills), 6)
        for entry in skills:
            with self.subTest(skill=entry.parent.name):
                _, metadata, body = entry.read_text().split("---", 2)
                description = re.search(r"^description: (.+)$", metadata, re.M)
                self.assertIsNotNone(description)
                self.assertNotRegex(description.group(1), r"[\u4e00-\u9fff]")
                heading, introduction, language_link, _ = body.strip().split("\n\n", 3)
                self.assertTrue(heading.startswith("# "))
                self.assertRegex(introduction, r"[A-Za-z]")
                self.assertNotRegex(introduction, r"[\u4e00-\u9fff]")
                self.assertIn(f"]({chinese_readme})", language_link)
                self.assertRegex((entry.parent / chinese_readme).read_text(),
                                 r"[\u4e00-\u9fff]")

    def test_packaged_guides_keep_chinese_documentation_links(self):
        bundles = [ROOT]
        if not IN_SNAPSHOT:
            bundles = sorted((ROOT / "skills").glob("project-docs*/.bundle"))
            self.assertEqual(len(bundles), 6)
        for bundle in bundles:
            guides = sorted((bundle / "skills").glob("project-docs*/GUIDE.md"))
            self.assertEqual(len(guides), 6, bundle)
            for guide in guides:
                with self.subTest(bundle=bundle.parent.name, guide=guide.parent.name):
                    link = re.search(r"\[中文文档 / Chinese documentation\]\(([^)]+)\)",
                                     guide.read_text())
                    self.assertIsNotNone(link)
                    target = (guide.parent / link.group(1)).resolve()
                    self.assertEqual(target, (bundle / "README.zh-CN.md").resolve())
                    self.assertTrue(target.is_file())

    def test_local_links_in_both_languages_and_showcase_resolve(self):
        documents = [ROOT / "README.md", ROOT / "README.en.md", ROOT / "README.zh-CN.md",
                     ROOT / "docs/examples/petclinic/README.md",
                     ROOT / "docs/examples/petclinic/README.en.md",
                     ROOT / "docs/examples/petclinic/developer-guide.en.md",
                     ROOT / "docs/examples/petclinic/developer-guide.md",
                     ROOT / "docs/media/README.md",
                     ROOT / "docs/SHARING.md",
                     ROOT / "docs/launch/README.md",
                     ROOT / "docs/launch/first-post.zh-CN.md",
                     ROOT / "docs/launch/first-post.en.md"]
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

    def test_demo_gifs_match_their_checked_receipts_and_language_readmes(self):
        for name, stem, locale in (("README.md", "petclinic-demo.en", "en"),
                                   ("README.zh-CN.md", "petclinic-demo", "zh-CN")):
            folder = ROOT / "docs/media"
            data = (folder / (stem + ".gif")).read_bytes()
            receipt = json.loads((folder / (stem + ".json")).read_text())
            self.assertEqual(receipt["locale"], locale)
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
            self.assertIn("](docs/media/" + stem + ".gif)", (ROOT / name).read_text())

    def test_english_case_preserves_sources_and_has_no_untranslated_body(self):
        folder = ROOT / "docs/examples/petclinic"
        upstream = r"https://github.com/spring-projects/spring-petclinic/(?:blob|tree)/[^\s)]+"
        for stem in ("README", "developer-guide"):
            chinese = (folder / (stem + ".md")).read_text()
            english = (folder / (stem + ".en.md")).read_text()
            self.assertEqual(set(re.findall(upstream, english)), set(re.findall(upstream, chinese)))
            self.assertNotRegex(english.replace("中文", ""), r"[\u4e00-\u9fff]")
            self.assertIn("](verification.json)", english)
            self.assertIn("](controller-test-results.json)", english)
        self.assertEqual(len(re.findall(r"^## \d+\.", (folder / "developer-guide.en.md").read_text(), re.M)), 9)
        homepage = (ROOT / "README.md").read_text()
        self.assertIn("](docs/examples/petclinic/README.en.md)", homepage)
        self.assertIn("](docs/examples/petclinic/developer-guide.en.md)", homepage)

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
