"""Executable authoring contract for Project Docs' Archify explainer route."""

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from engine_paths import find_engine, prepare_runtime


ROOT = Path(__file__).resolve().parent.parent
OVERVIEW = ROOT / "skills/project-docs-overview"
EXAMPLE = OVERVIEW / "assets/project-explainer.archify.md"
prepare_runtime()
CLI = find_engine("archify")


class ExplainerRoutingTest(unittest.TestCase):
    def test_overview_routes_to_self_contained_authoring_reference_and_example(self):
        skill = (OVERVIEW / "SKILL.md").read_text()
        self.assertIn("references/explainer.md", skill)
        guide = (OVERVIEW / "references/explainer.md").read_text()
        self.assertIn("finalize explainer", guide)
        self.assertIn("patch explainer", guide)
        self.assertIn("--repo-root", guide)
        self.assertIn("--browser-check", guide)
        self.assertIn("assets/project-explainer.archify.md", guide)
        self.assertTrue(EXAMPLE.is_file())
        self.assertIn("explainer", (ROOT / "skills/project-docs/SKILL.md").read_text())


@unittest.skipUnless(CLI or os.environ.get("ARCHIFY_OFFICIAL_CLI"), "official Archify CLI not installed")
class OfficialExplainerTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(CLI, "explicit ARCHIFY_OFFICIAL_CLI must resolve")
        temporary = tempfile.TemporaryDirectory(prefix="project explainer ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("remote", "add", "origin", "https://github.com/example/project.git")
        (self.repo / "README.md").write_text("# Project\n\nCommitted project introduction.\n")
        self.git("add", "README.md")
        self.git("commit", "-qm", "fixture")
        self.draft = self.root / "candidate.archify.md"
        self.draft.write_bytes(EXAMPLE.read_bytes())
        self.output = self.root / "answer.html"

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def run_cli(self, *args):
        result = subprocess.run([CLI, *map(str, args), "--json"], capture_output=True,
                                text=True, timeout=180, cwd=self.root)
        try:
            receipt = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail(result.stdout + result.stderr)
        return result, receipt

    def finalize(self, *extra):
        return self.run_cli("finalize", "explainer", self.draft, self.output,
                            "--repo-root", self.repo, *extra)

    def test_beginner_installation_example_delivers_and_preserves_source_boundary(self):
        example = OVERVIEW / "assets/beginner-explainer.archify.md"
        self.draft.write_bytes(example.read_bytes())
        for relative in ("install.sh", "scripts/update_project_docs.py"):
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        self.git("add", ".")
        self.git("commit", "-qm", "installation evidence")
        result, receipt = self.finalize()
        self.assertEqual(result.returncode, 0, receipt)
        self.assertTrue(receipt["ok"], receipt)
        self.assertFalse(receipt["browserCheck"]["ran"])
        for gate in ("validate", "deliver", "check"):
            self.assertEqual(receipt["gates"][gate], "pass")
        self.assertIn("diagram-dialog", self.output.read_text())
        self.assertIn(self.git("rev-parse", "HEAD"), self.output.read_text())
        prepared = re.search(
            r'<script[^>]*id="archify-explainer-prepared"[^>]*>(.*?)</script>',
            self.output.read_text(), re.S)
        self.assertIsNotNone(prepared)
        document = json.loads(prepared[1])["document"]
        diagram = next(block["spec"] for panel in document["panels"]
                       for block in panel["blocks"] if block["type"] == "diagram")
        # The two Skill directories have separate entry points and source files.
        self.assertEqual(len(diagram["edges"]), 2)
        self.assertEqual(len({edge["from"] for edge in diagram["edges"]}), 2)
        self.assertEqual(len({edge["to"] for edge in diagram["edges"]}), 2)
        # Link-only sources are not checked for file existence by Archify itself.
        for source in document["sources"]:
            with self.subTest(source=source["id"]):
                content = self.git("show", f'HEAD:{source["path"]}')
                first, last = source["lines"]
                self.assertGreaterEqual(first, 1)
                self.assertGreaterEqual(last, first)
                self.assertLessEqual(last, len(content.splitlines()))
        original_html = self.output.read_bytes()
        # The existing engine rejects unresolved code sources in every mode.
        self.draft.write_text(self.draft.read_text() +
                              "\n@code source=unknown language=bash\n")
        result, receipt = self.finalize()
        self.assertNotEqual(result.returncode, 0, receipt)
        self.assertFalse(receipt["ok"])
        self.assertEqual(self.output.read_bytes(), original_html)

    def test_example_delivers_native_diagram_and_pinned_code_without_browser(self):
        (self.repo / "README.md").write_text("UNCOMMITTED CONTENT MUST NOT REPLACE PINNED SOURCE\n")
        original = self.draft.read_bytes()
        result, receipt = self.finalize()
        self.assertEqual(result.returncode, 0, receipt)
        self.assertTrue(receipt["ok"], receipt)
        self.assertFalse([item for item in receipt.get("diagnostics", [])
                          if item.get("code", "").startswith("explainer/writing-")], receipt)
        for gate in ("validate", "deliver", "check"):
            self.assertEqual(receipt["gates"][gate], "pass")
        self.assertFalse(receipt["browserCheck"]["ran"])
        self.assertEqual(self.draft.read_bytes(), original)
        html = self.output.read_text()
        self.assertIn("Committed project introduction.", html)
        self.assertNotIn("UNCOMMITTED CONTENT", html)
        self.assertIn("archify-explainer-prepared", html)
        self.assertIn("diagram-dialog", html)
        self.assertIn(self.git("rev-parse", "HEAD"), html)
        checked, proof = self.run_cli("check", self.output, "--require-provenance")
        self.assertEqual(checked.returncode, 0, proof)

    def test_four_styles_and_chinese_locale_are_accepted(self):
        original = self.draft.read_text()
        for style in ("clean", "editorial", "product", "swiss"):
            with self.subTest(style=style):
                self.draft.write_text(original.replace("style=clean", f"style={style}"))
                result, receipt = self.run_cli("validate", "explainer", self.draft,
                                               "--repo-root", self.repo)
                self.assertEqual(result.returncode, 0, receipt)

    def test_panel_patch_preserves_conclusion_and_frozen_code(self):
        result, receipt = self.finalize()
        self.assertEqual(result.returncode, 0, receipt)
        replacement = self.root / "replacement.md"
        replacement.write_text("## 下一步做什么？ {#checks}\n\n- [ ] 核对关键业务规则。\n")
        revised = self.root / "revised.html"
        (self.repo / "README.md").unlink()
        result, receipt = self.run_cli("patch", "explainer", self.output, "checks", replacement, revised)
        self.assertEqual(result.returncode, 0, receipt)
        html = revised.read_text()
        self.assertIn("核对关键业务规则", html)
        self.assertIn("Committed project introduction.", html)
        self.assertIn("把源码和需求整理为", html)
        checked, proof = self.run_cli("check", revised, "--require-provenance")
        self.assertEqual(checked.returncode, 0, proof)

    def test_invalid_drafts_do_not_replace_existing_artifact(self):
        result, receipt = self.finalize()
        self.assertEqual(result.returncode, 0, receipt)
        original_html = self.output.read_bytes()
        valid = self.draft.read_text()
        invalid = {
            "duplicate-panel": valid + "\n## 重复章节 {#checks}\n\n重复。\n",
            "missing-code-source": valid.replace("source=readme", "source=unknown"),
            "unsafe-path": valid.replace("path=README.md", "path=../README.md"),
            "missing-source-lines": valid.replace("lines=1:3", "lines=100:103"),
            "missing-chart": valid + '\n## 数据 {#data}\n\n@chart type=bar data=missing.csv x=name y=value\n',
            "raw-html": valid + "\n## 错误 {#invalid}\n\n<script>alert(1)</script>\n",
        }
        for case, text in invalid.items():
            with self.subTest(case=case):
                self.draft.write_text(text)
                result, receipt = self.finalize()
                self.assertNotEqual(result.returncode, 0, receipt)
                self.assertFalse(receipt["ok"])
                self.assertTrue(receipt["diagnostics"])
                self.assertEqual(self.output.read_bytes(), original_html)

    def test_panel_patch_rejects_changed_id_and_preserves_original(self):
        result, receipt = self.finalize()
        self.assertEqual(result.returncode, 0, receipt)
        original_html = self.output.read_bytes()
        replacement = self.root / "wrong-panel.md"
        replacement.write_text("## 不同面板 {#wrong-id}\n\n不应覆盖原面板。\n")
        revised = self.root / "rejected.html"
        result, receipt = self.run_cli("patch", "explainer", self.output, "checks", replacement, revised)
        self.assertNotEqual(result.returncode, 0, receipt)
        self.assertFalse(revised.exists())
        self.assertEqual(self.output.read_bytes(), original_html)

    def test_missing_repository_fails_for_code_excerpt(self):
        result, receipt = self.run_cli("finalize", "explainer", self.draft, self.output)
        self.assertNotEqual(result.returncode, 0, receipt)
        self.assertFalse(self.output.exists())

    def test_business_material_explainer_needs_no_repository_but_code_still_does(self):
        self.draft.write_text('''# 借书为什么要登记？ {#borrowing}

登记借阅人和书名，归还时才能核对是哪一次借阅。

@answer scope="模拟业务材料：借书登记借阅人与书名，归还核对登记；不涉及真实系统或上线状态"
@meta locale=zh-CN style=clean

## 如何借还？ {#flow}

@workflow id=borrowing-flow title="借还过程"
| borrow | 借书登记 | external |
| return | 归还核对 | external |
| borrow > return | 按登记核对 |

## 登记意味着什么？ {#limits}

登记记录借阅关系。丢失赔偿与逾期处理未在材料中约定，仍需业务方确认。
''')
        result, receipt = self.run_cli("finalize", "explainer", self.draft, self.output)
        self.assertEqual(result.returncode, 0, receipt)
        self.assertTrue(receipt["ok"], receipt)
        self.assertFalse(receipt["browserCheck"]["ran"])
        original_html = self.output.read_bytes()
        (self.root / "rules.txt").write_text("Borrowing rules supplied by the user.\n")
        self.draft.write_text(self.draft.read_text() +
                             '\n@source rules title="业务材料" path=rules.txt lines=1:1\n'
                             '\n@code source=rules language=text\n')
        result, receipt = self.run_cli("finalize", "explainer", self.draft, self.output)
        self.assertNotEqual(result.returncode, 0, receipt)
        self.assertFalse(receipt["ok"])
        self.assertEqual(self.output.read_bytes(), original_html)

    def test_explanation_goals_use_different_structures_without_a_repository(self):
        cases = {
            "registration-rule": {"comparison", "callout"},
            "notification-delay": {"diagram", "callout"},
            "repair-change": {"comparison", "steps", "callout"},
        }
        examples = OVERVIEW / "assets/beginner-explainers"
        for name, required in cases.items():
            with self.subTest(case=name):
                material = (examples / f"{name}.input.md").read_bytes()
                (self.root / f"{name}.input.md").write_bytes(material)
                self.draft.write_bytes((examples / f"{name}.archify.md").read_bytes())
                result, receipt = self.run_cli("finalize", "explainer", self.draft, self.output)
                self.assertEqual(result.returncode, 0, receipt)
                self.assertTrue(receipt["ok"], receipt)
                self.assertFalse(receipt["browserCheck"]["ran"])
                prepared = re.search(
                    r'<script[^>]*id="archify-explainer-prepared"[^>]*>(.*?)</script>',
                    self.output.read_text(), re.S)
                self.assertIsNotNone(prepared)
                document = json.loads(prepared[1])["document"]
                blocks = [block for panel in document["panels"] for block in panel["blocks"]]
                self.assertTrue(required <= {block["type"] for block in blocks})
                if name == "registration-rule":
                    rows = next(block["rows"] for block in blocks if block["type"] == "comparison")
                    # One free place confirms the applicant; a full session stays at 3.
                    self.assertEqual([row["label"] for row in rows[:2]], ["2", "3"])
                    self.assertEqual([row["cells"][1]["text"] for row in rows[:2]], ["3", "3"])
                    self.assertEqual(len(rows), 4)  # Includes over-capacity and missing data.
                elif name == "notification-delay":
                    graph = next(block["spec"] for block in blocks if block["type"] == "diagram")
                    self.assertEqual([(edge["from"], edge["to"]) for edge in graph["edges"]],
                                     [("accept", "delivery")])
                else:
                    steps = next(block["items"] for block in blocks if block["type"] == "steps")
                    self.assertEqual([item["id"] for item in steps], ["submit", "save", "query"])
                self.assertEqual((self.root / f"{name}.input.md").read_bytes(), material)

    def test_beginner_and_domain_expert_views_preserve_the_same_rule_results(self):
        examples = OVERVIEW / "assets/beginner-explainers"
        material = (examples / "registration-rule.input.md").read_bytes()
        (self.root / "registration-rule.input.md").write_bytes(material)
        documents = []
        for name in ("registration-rule", "registration-rule-expert"):
            self.draft.write_bytes((examples / f"{name}.archify.md").read_bytes())
            result, receipt = self.run_cli("finalize", "explainer", self.draft, self.output)
            self.assertEqual(result.returncode, 0, receipt)
            self.assertTrue(receipt["ok"], receipt)
            prepared = re.search(
                r'<script[^>]*id="archify-explainer-prepared"[^>]*>(.*?)</script>',
                self.output.read_text(), re.S)
            self.assertIsNotNone(prepared)
            documents.append(json.loads(prepared[1])["document"])
        results = []
        for document in documents:
            comparison = next(block for panel in document["panels"]
                              for block in panel["blocks"] if block["type"] == "comparison")
            results.append([(row["label"], [cell["text"] for cell in row["cells"]])
                            for row in comparison["rows"]])
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(results[0]), 4)  # Normal, full, over-capacity and unknown.
        self.assertNotEqual(documents[0]["meta"]["title"], documents[1]["meta"]["title"])
        self.assertEqual((self.root / "registration-rule.input.md").read_bytes(), material)

    @unittest.skipUnless(os.environ.get("ARCHIFY_EXPLAINER_BROWSER_TEST") == "1",
                         "set ARCHIFY_EXPLAINER_BROWSER_TEST=1 for browser and export acceptance")
    def test_browser_gate_mobile_layout_and_real_image_pdf_exports(self):
        result, receipt = self.finalize("--browser-check")
        self.assertEqual(result.returncode, 0, receipt)
        self.assertTrue(receipt["browserCheck"]["ran"])
        self.assertEqual(receipt["gates"]["browser-check"], "pass")
        result = subprocess.run(["node", str(ROOT / "scripts/fixtures/archify_explainer_browser.mjs"),
                                 CLI, str(self.output), str(self.root)], capture_output=True,
                                text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([item["width"] for item in json.loads(result.stdout)], [1440, 390])
        for name, signature in (("png", b"\x89PNG\r\n\x1a\n"), ("jpg", b"\xff\xd8\xff"),
                                ("webp", b"RIFF"), ("pdf", b"%PDF-")):
            data = (self.root / f"answer.{name}").read_bytes()
            self.assertTrue(data.startswith(signature), name)
            self.assertGreater(len(data), 1000, name)
            if name == "webp":
                self.assertEqual(data[8:12], b"WEBP")

    def test_csv_chart_freezes_data_and_rejects_blank_numeric_cell(self):
        self.draft.write_text(self.draft.read_text() +
                             '\n## 数据说明什么？ {#data}\n\n@chart type=bar data=counts.csv x=name y=count title="数量（示意）"\n')
        data = self.root / "counts.csv"
        data.write_text("name,count\nAPI,3\nDocs,2\n")
        result, receipt = self.finalize()
        self.assertEqual(result.returncode, 0, receipt)
        original_html = self.output.read_bytes()
        data.write_text("name,count\nAPI,\n")
        result, receipt = self.finalize()
        self.assertNotEqual(result.returncode, 0, receipt)
        self.assertEqual(self.output.read_bytes(), original_html)


if __name__ == "__main__":
    unittest.main()
