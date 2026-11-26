"""Acceptance tests for official native diagram sources outside typed IR v2."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("render_native_diagram.py")
ARCHIFY_CLI = os.environ.get("ARCHIFY_OFFICIAL_CLI") or shutil.which("archify")
ARCHIFY_EXAMPLES = Path(ARCHIFY_CLI).resolve().parent.parent / "examples" if ARCHIFY_CLI else None


class NativeDiagramTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "out"

    def tearDown(self):
        self.temp.cleanup()

    def render(self, engine, source, *extra):
        return subprocess.run([sys.executable, str(SCRIPT), "--engine", engine,
                               "--input", str(source), "--output", str(self.output), *extra],
                              capture_output=True, text=True)

    def source_backed(self, *, engine="mermaid", diagram_type="class", artifact_quote="class Asset",
                      quote="class Asset", provenance="EXTRACTED", path="Asset.java", line=1):
        source_root = self.root / "source"
        source_root.mkdir(exist_ok=True)
        (source_root / "Asset.java").write_text("class Asset {}\n", encoding="utf-8")
        source = self.root / "classes.mmd"
        source.write_text("classDiagram\n  class Asset\n", encoding="utf-8")
        manifest = self.root / "evidence.json"
        manifest.write_text(json.dumps({"version": 1, "engine": engine,
                                        "diagramType": diagram_type,
                                        "claims": [{"statement": "Asset exists",
                                                    "artifactQuote": artifact_quote,
                                                    "provenance": provenance,
                                                    "evidence": [{"path": path, "line": line,
                                                                  "quote": quote}]}]}), encoding="utf-8")
        return source, source_root, manifest

    def test_source_repo_requires_evidence_manifest(self):
        source, source_root, _ = self.source_backed()
        result = self.render("mermaid", source, "--source-repo", str(source_root))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--evidence", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_evidence_manifest_requires_source_repo(self):
        source, _, manifest = self.source_backed()
        result = self.render("mermaid", source, "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--source-repo", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_source_claim_without_matching_code_quote(self):
        source, source_root, manifest = self.source_backed(quote="class Missing")
        result = self.render("mermaid", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("quote does not occur", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_source_claim_without_matching_diagram_text(self):
        source, source_root, manifest = self.source_backed(artifact_quote="class Missing")
        result = self.render("mermaid", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("artifactQuote", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_v2_manifest_rejects_unclaimed_native_statement(self):
        source, source_root, manifest = self.source_backed()
        source.write_text("classDiagram\n  class Asset\n  class Ledger\n", encoding="utf-8")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["version"] = 2
        payload["claims"][0]["artifactRef"] = "line:2"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        result = self.render("mermaid", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("line:3", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_v2_manifest_rejects_nonliteral_extracted_statement(self):
        source, source_root, manifest = self.source_backed()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["version"] = 2
        payload["claims"][0]["artifactRef"] = "line:2"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        result = self.render("mermaid", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EXTRACTED statement", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_v2_manifest_accepts_complete_literal_claims(self):
        source, source_root, manifest = self.source_backed()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["version"] = 2
        payload["claims"][0]["artifactRef"] = "line:2"
        payload["claims"][0]["statement"] = "class Asset"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        from render_native_diagram import _validate_source_manifest
        _, problems = _validate_source_manifest(manifest, source_root.resolve(), source,
                                               "mermaid", None)
        self.assertEqual(problems, [])

    def test_v2_manifest_inventories_local_plantuml_includes(self):
        from render_native_diagram import _validate_source_manifest
        source, source_root, manifest = self.source_backed()
        source = self.root / "view.puml"
        source.write_text("@startuml\n!include links.puml\nclass Asset\n@enduml\n", encoding="utf-8")
        (self.root / "links.puml").write_text("Asset --> Ledger\n", encoding="utf-8")
        payload = {"version": 2, "engine": "plantuml", "diagramType": "class",
                   "claims": [{"statement": "class Asset", "artifactRef": "line:3",
                               "artifactQuote": "class Asset", "provenance": "EXTRACTED",
                               "evidence": [{"path": "Asset.java", "line": 1,
                                             "quote": "class Asset"}]}]}
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        _, problems = _validate_source_manifest(manifest, source_root.resolve(), source,
                                               "plantuml", None)
        self.assertTrue(any("include:links.puml:line:1" in problem for problem in problems), problems)
        payload["claims"].append({"statement": "Asset links to Ledger",
                                  "artifactRef": "include:links.puml:line:1",
                                  "artifactQuote": "Asset --> Ledger", "provenance": "INFERRED",
                                  "evidence": [{"path": "Asset.java", "line": 1,
                                                "quote": "class Asset"}]})
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        _, problems = _validate_source_manifest(manifest, source_root.resolve(), source,
                                               "plantuml", None)
        self.assertEqual(problems, [])

    def test_plantuml_external_include_prevents_complete_claim_coverage(self):
        from render_native_diagram import _untracked_includes
        source = self.root / "view.puml"
        source.write_text("@startuml\n!include <C4/C4_Container>\nclass Asset\n@enduml\n",
                          encoding="utf-8")
        self.assertEqual(_untracked_includes(source), ["line:2"])

    def test_plantuml_block_include_inventories_only_selected_block(self):
        from render_native_diagram import _plantuml_refs
        source = self.root / "view.puml"
        source.write_text("@startuml\n!include blocks.puml!0\n@enduml\n", encoding="utf-8")
        (self.root / "blocks.puml").write_text(
            "@startuml\nclass Asset\n@enduml\n@startuml\nclass Unselected\n@enduml\n",
            encoding="utf-8")
        refs, untracked, included = _plantuml_refs(source)
        self.assertEqual(refs, {"include:blocks.puml:line:2": "class Asset"})
        self.assertEqual(untracked, [])
        self.assertEqual(included, [(self.root / "blocks.puml").resolve()])

    @unittest.skipUnless(os.environ.get("PLANTUML_OFFICIAL_CLI") or shutil.which("plantuml"),
                         "official PlantUML CLI is unavailable")
    def test_official_plantuml_selected_block_is_packaged(self):
        _, source_root, manifest = self.source_backed()
        source = self.root / "view.puml"
        source.write_text("@startuml\n!include blocks.puml!ASSET\n@enduml\n", encoding="utf-8")
        (self.root / "blocks.puml").write_text(
            "@startuml(id=ASSET)\nclass Asset\n@enduml\n"
            "@startuml(id=OTHER)\nclass Unselected\n@enduml\n", encoding="utf-8")
        manifest.write_text(json.dumps({"version": 2, "engine": "plantuml", "diagramType": "class",
                                        "claims": [{"statement": "class Asset",
                                                    "artifactRef": "include:blocks.puml:line:2",
                                                    "artifactQuote": "class Asset",
                                                    "provenance": "EXTRACTED",
                                                    "evidence": [{"path": "Asset.java", "line": 1,
                                                                  "quote": "class Asset"}]}]}), encoding="utf-8")
        result = self.render("plantuml", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["claimCoverage"], "complete")
        self.assertTrue((self.output / "blocks.puml").is_file())

    @unittest.skipUnless(os.environ.get("PLANTUML_OFFICIAL_CLI") or shutil.which("plantuml"),
                         "official PlantUML CLI is unavailable")
    def test_plantuml_includesub_is_packaged_and_claimed(self):
        _, source_root, manifest = self.source_backed()
        source = self.root / "view.puml"
        source.write_text("@startuml\n!includesub part.puml!BASIC\n@enduml\n", encoding="utf-8")
        (self.root / "part.puml").write_text(
            "@startuml\n!startsub BASIC\nclass Asset\n!endsub\n@enduml\n", encoding="utf-8")
        manifest.write_text(json.dumps({"version": 2, "engine": "plantuml", "diagramType": "class",
                                        "claims": [{"statement": "Asset view",
                                                    "artifactRef": "line:2",
                                                    "artifactQuote": "!includesub part.puml!BASIC",
                                                    "provenance": "INFERRED",
                                                    "evidence": [{"path": "Asset.java", "line": 1,
                                                                  "quote": "class Asset"}]}]}), encoding="utf-8")
        incomplete = self.render("plantuml", source, "--source-repo", str(source_root),
                                 "--evidence", str(manifest))
        self.assertNotEqual(incomplete.returncode, 0)
        self.assertIn("include:part.puml:line:3", incomplete.stdout + incomplete.stderr)
        manifest.write_text(json.dumps({"version": 2, "engine": "plantuml", "diagramType": "class",
                                        "claims": [{"statement": "class Asset",
                                                    "artifactRef": "include:part.puml:line:3",
                                                    "artifactQuote": "class Asset",
                                                    "provenance": "EXTRACTED",
                                                    "evidence": [{"path": "Asset.java", "line": 1,
                                                                  "quote": "class Asset"}]}]}), encoding="utf-8")
        result = self.render("plantuml", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["claimCoverage"], "complete")
        self.assertTrue((self.output / "part.puml").is_file())

    @unittest.skipUnless(os.environ.get("PLANTUML_OFFICIAL_CLI") or shutil.which("plantuml"),
                         "official PlantUML CLI is unavailable")
    def test_official_plantuml_local_include_is_packaged(self):
        _, source_root, manifest = self.source_backed()
        source = self.root / "view.puml"
        source.write_text("@startuml\n!include links.puml\nclass Asset\n@enduml\n", encoding="utf-8")
        (self.root / "links.puml").write_text("Asset --> Ledger\n", encoding="utf-8")
        manifest.write_text(json.dumps({"version": 2, "engine": "plantuml", "diagramType": "class",
                                        "claims": [
                                            {"statement": "class Asset", "artifactRef": "line:3",
                                             "artifactQuote": "class Asset", "provenance": "EXTRACTED",
                                             "evidence": [{"path": "Asset.java", "line": 1,
                                                           "quote": "class Asset"}]},
                                            {"statement": "Asset links to Ledger",
                                             "artifactRef": "include:links.puml:line:1",
                                             "artifactQuote": "Asset --> Ledger", "provenance": "INFERRED",
                                             "evidence": [{"path": "Asset.java", "line": 1,
                                                           "quote": "class Asset"}]}]}), encoding="utf-8")
        result = self.render("plantuml", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["claimCoverage"], "complete")
        self.assertTrue((self.output / "links.puml").is_file())

    @unittest.skipUnless(os.environ.get("PLANTUML_OFFICIAL_CLI") or shutil.which("plantuml"),
                         "official PlantUML CLI is unavailable")
    def test_plantuml_bundle_rerenders_after_moving_without_sender_files(self):
        for absolute in (True, False):
            with self.subTest(absolute=absolute):
                sender = self.root / f"sender-{absolute}"
                parts = sender / "parts"
                parts.mkdir(parents=True)
                source = sender / "flow.puml"
                library = parts / "blocks.puml"
                nested = sender / "detail.puml"
                nested.write_text("class Dependency\n", encoding="utf-8")
                library.write_text(
                    f"@startuml\n  !include {nested}\n@enduml\n"
                    "@startuml\nclass OtherBlock\n@enduml\n", encoding="utf-8")
                if absolute:
                    include = str(library)
                else:
                    (sender / "alias.puml").symlink_to(library)
                    include = "alias.puml"
                original = f"@startuml\n  !include {include}!0\nclass Main\nMain --> Dependency\n@enduml\n"
                source.write_text(original, encoding="utf-8")
                self.output = self.root / f"published-{absolute}"
                first = self.render("plantuml", source, "--export", "svg")
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                self.assertEqual(source.read_text(), original)
                moved = self.output.rename(self.root / f"received-{absolute}")
                sender.rename(self.root / f"archived-{absolute}")
                self.output = self.root / f"rerendered-{absolute}"
                second = self.render("plantuml", moved / "diagram.puml", "--export", "svg")
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertIn("!include parts/blocks.puml!0", (moved / "diagram.puml").read_text())
                self.assertIn("!include ../detail.puml", (moved / "parts/blocks.puml").read_text())
                svg = (self.output / "diagram.plantuml.svg").read_text()
                self.assertIn("Dependency", svg)
                self.assertNotIn("OtherBlock", svg)

    @unittest.skipUnless(os.environ.get("PLANTUML_OFFICIAL_CLI") or shutil.which("plantuml"),
                         "official PlantUML CLI is unavailable")
    def test_plantuml_reexport_removes_only_unedited_owned_includes(self):
        source = self.root / 'flow.puml'
        (self.root / 'links.puml').write_text('Asset --> Ledger\n')
        (self.root / 'notes.puml').write_text('class Notes\n')
        source.write_text('@startuml\n!include links.puml\n!include notes.puml\nclass Asset\n@enduml\n')
        first = self.render('plantuml', source, '--export', 'svg')
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        (self.output / 'notes.puml').write_text("' User notes.\n")
        (self.output / 'manual.puml').write_text("' Unrelated file.\n")
        source.write_text('@startuml\nclass Asset\n@enduml\n')
        second = self.render('plantuml', source, '--export', 'svg')
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertFalse((self.output / 'links.puml').exists())
        self.assertEqual((self.output / 'notes.puml').read_text(), "' User notes.\n")
        self.assertEqual((self.output / 'manual.puml').read_text(), "' Unrelated file.\n")

    @unittest.skipUnless(os.environ.get("PLANTUML_OFFICIAL_CLI") or shutil.which("plantuml"),
                         "official PlantUML CLI is unavailable")
    def test_official_plantuml_library_include_reports_partial_coverage(self):
        _, source_root, manifest = self.source_backed()
        source = self.root / "view.puml"
        source.write_text('@startuml\n!include <C4/C4_Container>\n'
                          'Container(asset, "Asset", "Java", "Stores data")\n@enduml\n',
                          encoding="utf-8")
        manifest.write_text(json.dumps({"version": 2, "engine": "plantuml", "diagramType": "c4-container",
                                        "claims": [{"statement": "Asset container", "artifactRef": "line:3",
                                                    "artifactQuote": "Container(asset", "provenance": "INFERRED",
                                                    "evidence": [{"path": "Asset.java", "line": 1,
                                                                  "quote": "class Asset"}]}]}), encoding="utf-8")
        result = self.render("plantuml", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["claimCoverage"], "partial")
        self.assertEqual(receipt["untrackedIncludes"], ["line:2"])

    def test_v2_manifest_covers_drawio_cells_and_archify_items(self):
        from render_native_diagram import _validate_source_manifest
        source, source_root, manifest = self.source_backed()
        source = self.root / "view.drawio"
        source.write_text('<mxfile><diagram><mxGraphModel><root>'
                          '<mxCell id="0"/><mxCell id="1" parent="0"/>'
                          '<mxCell id="a" value="Asset" vertex="1" parent="1"/>'
                          '<mxCell id="b" value="Ledger" vertex="1" parent="1"/>'
                          '<mxCell id="ab" edge="1" source="a" target="b" parent="1"/>'
                          '</root></mxGraphModel></diagram></mxfile>', encoding="utf-8")
        payload = {"version": 2, "engine": "drawio", "diagramType": "architecture",
                   "claims": [{"statement": "Asset", "artifactRef": "cell:a",
                               "artifactQuote": 'id="a"', "provenance": "INFERRED",
                               "evidence": [{"path": "Asset.java", "line": 1,
                                             "quote": "class Asset"}]}]}
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        _, problems = _validate_source_manifest(manifest, source_root.resolve(), source,
                                               "drawio", None)
        self.assertTrue(any("cell:b" in problem and "cell:ab" in problem
                            for problem in problems), problems)

        source = self.root / "view.archify.json"
        source.write_text(json.dumps({"diagram_type": "architecture",
                                      "components": [{"id": "asset", "label": "Asset"},
                                                     {"id": "ledger", "label": "Ledger"}],
                                      "boundaries": [],
                                      "connections": [{"from": "asset", "to": "ledger"}]}),
                          encoding="utf-8")
        payload["engine"] = "archify"
        payload["claims"][0]["artifactRef"] = "/components/0"
        payload["claims"][0]["artifactQuote"] = '"Asset"'
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        _, problems = _validate_source_manifest(manifest, source_root.resolve(), source,
                                               "archify", "architecture")
        self.assertTrue(any("/components/1" in problem and "/connections/0" in problem
                            for problem in problems), problems)

    def test_rejects_wrong_engine_or_provenance_in_evidence_manifest(self):
        for options, expected in (({"engine": "plantuml"}, "engine"),
                                  ({"provenance": "GUESSED"}, "provenance")):
            with self.subTest(options=options):
                source, source_root, manifest = self.source_backed(**options)
                result = self.render("mermaid", source, "--source-repo", str(source_root),
                                     "--evidence", str(manifest))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout + result.stderr)
                self.assertFalse(self.output.exists())

    def test_rejects_source_evidence_outside_repository(self):
        source, source_root, manifest = self.source_backed(path="../outside.java")
        (self.root / "outside.java").write_text("class Asset {}\n", encoding="utf-8")
        result = self.render("mermaid", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside source root", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_archify_manifest_type_mismatch_before_writing(self):
        source, source_root, manifest = self.source_backed(engine="archify", diagram_type="sequence",
                                                           artifact_quote='"diagram_type": "workflow"')
        source = self.root / "workflow.json"
        source.write_text('{"diagram_type": "workflow", "schema_version": 1}', encoding="utf-8")
        result = self.render("archify", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("diagramType must be workflow", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc"),
                         "official Mermaid CLI unavailable")
    def test_source_backed_native_diagram_checks_claim_anchors_and_exports(self):
        source, source_root, manifest = self.source_backed()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["version"] = 2
        payload["claims"][0]["artifactRef"] = "line:2"
        payload["claims"][0]["statement"] = "class Asset"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        executable = os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc")
        result = self.render("mermaid", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest), "--engine-cli", executable,
                             "--export", "png")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["sourceEvidence"], "anchors_validated")
        self.assertEqual(receipt["claimCoverage"], "complete")
        self.assertEqual(receipt["claimSemantics"], "not_proven")
        self.assertEqual(receipt["claimCount"], 1)
        self.assertEqual(receipt["declaredDiagramType"], "class")
        self.assertIn(str((self.output / "diagram.evidence.json").resolve()), receipt["artifacts"])
        self.assertTrue((self.output / "diagram.mermaid.png").is_file())

    @unittest.skipUnless(os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc"),
                         "official Mermaid CLI unavailable")
    def test_run_without_manifest_removes_stale_evidence_copy(self):
        source, source_root, manifest = self.source_backed()
        executable = os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc")
        first = self.render("mermaid", source, "--source-repo", str(source_root),
                            "--evidence", str(manifest), "--engine-cli", executable)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertTrue((self.output / "diagram.evidence.json").is_file())
        second = self.render("mermaid", source, "--engine-cli", executable)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertFalse((self.output / "diagram.evidence.json").exists())

    def test_rejects_wrong_native_extension_before_writing(self):
        source = self.root / "diagram.txt"
        source.write_text("classDiagram\nA <|-- B\n", encoding="utf-8")
        result = self.render("mermaid", source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".mmd", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_unknown_archify_type_before_writing(self):
        source = self.root / "unknown.json"
        source.write_text('{"diagram_type":"unknown","schema_version":1}', encoding="utf-8")
        result = self.render("archify", source, "--engine-cli", str(self.root / "missing-archify"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported Archify diagram_type", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_archify_quality_flag_for_other_engines(self):
        source = self.root / "diagram.mmd"
        source.write_text("flowchart LR\nA-->B\n", encoding="utf-8")
        result = self.render("mermaid", source, "--quality", "showcase")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Archify", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc"),
                         "official Mermaid CLI unavailable")
    def test_official_mermaid_class_diagram_native_export(self):
        source = self.root / "classes.mmd"
        source.write_text("classDiagram\n  class Asset\n  class Event\n  Asset --> Event : creates\n",
                          encoding="utf-8")
        executable = os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc")
        result = self.render("mermaid", source, "--engine-cli", executable, "--export", "png")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["officialCheck"], "pass")
        self.assertEqual(receipt["sourceEvidence"], "not_checked")
        self.assertIn(str((self.output / "diagram.mermaid.png").resolve()), receipt["artifacts"])
        self.assertTrue((self.output / "diagram.mmd").read_text().startswith("classDiagram"))

    @unittest.skipUnless(os.environ.get("PLANTUML_OFFICIAL_CLI") or shutil.which("plantuml"),
                         "official PlantUML CLI unavailable")
    def test_official_plantuml_activity_diagram_native_validation(self):
        source = self.root / "activity.puml"
        source.write_text("@startuml\nstart\n:Receive request;\nstop\n@enduml\n", encoding="utf-8")
        executable = os.environ.get("PLANTUML_OFFICIAL_CLI") or shutil.which("plantuml")
        result = self.render("plantuml", source, "--engine-cli", executable)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["officialCheck"], "pass")
        self.assertTrue((self.output / "diagram.puml").is_file())

    @unittest.skipUnless(os.environ.get("PLANTUML_OFFICIAL_CLI") or shutil.which("plantuml"),
                         "official PlantUML CLI unavailable")
    def test_official_plantuml_class_diagram_exports_with_graphviz(self):
        source = self.root / "classes.puml"
        source.write_text("@startuml\nclass Order\nclass Item\nOrder --> Item\n@enduml\n")
        executable = os.environ.get("PLANTUML_OFFICIAL_CLI") or shutil.which("plantuml")
        result = self.render("plantuml", source, "--engine-cli", executable, "--export", "svg")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("<svg", (self.output / "diagram.plantuml.svg").read_text())

    @unittest.skipUnless(os.environ.get("PROJECT_DOCS_DESKTOP_TESTS") == "1" and (os.environ.get("DRAWIO_OFFICIAL_CLI") or shutil.which("drawio")),
                         "desktop acceptance requires PROJECT_DOCS_DESKTOP_TESTS=1 and draw.io")
    def test_official_drawio_freeform_diagram_native_export(self):
        source = self.root / "freeform.drawio"
        source.write_text('<mxfile><diagram id="one" name="One"><mxGraphModel><root>'
                          '<mxCell id="0"/><mxCell id="1" parent="0"/>'
                          '<mxCell id="n" value="Node" vertex="1" parent="1">'
                          '<mxGeometry x="40" y="40" width="140" height="60" as="geometry"/>'
                          '</mxCell></root></mxGraphModel></diagram></mxfile>', encoding="utf-8")
        executable = os.environ.get("DRAWIO_OFFICIAL_CLI") or shutil.which("drawio")
        result = self.render("drawio", source, "--engine-cli", executable, "--export", "png")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.output / "diagram.drawio.png").is_file())

    @unittest.skipUnless(ARCHIFY_EXAMPLES and ARCHIFY_EXAMPLES.is_dir(),
                         "official Archify CLI/examples unavailable")
    def test_official_archify_accepts_all_five_native_modes(self):
        examples = {"architecture": "web-app.architecture.json",
                    "workflow": "incident-response.workflow.json",
                    "sequence": "cache-miss-request.sequence.json",
                    "dataflow": "event-stream.dataflow.json",
                    "lifecycle": "agent-run.lifecycle.json"}
        executable = ARCHIFY_CLI
        for kind, filename in examples.items():
            with self.subTest(kind=kind):
                self.output = self.root / kind
                result = self.render("archify", ARCHIFY_EXAMPLES / filename,
                                     "--engine-cli", executable,
                                     *(["--export", "png"] if kind == "architecture" else []))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                receipt = json.loads(result.stdout)
                self.assertEqual(receipt["diagramType"], kind)
                self.assertEqual(receipt["officialCheck"], "pass")
                self.assertTrue((self.output / "diagram.archify.html").is_file())
                if kind == "architecture":
                    self.assertTrue((self.output / "diagram.archify.png").is_file())

    @unittest.skipUnless(os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc"),
                         "official Mermaid CLI unavailable")
    def test_invalid_native_source_keeps_previous_export_unclaimed(self):
        source = self.root / "broken.mmd"
        source.write_text("this is not Mermaid syntax\n", encoding="utf-8")
        self.output.mkdir()
        stale = self.output / "diagram.mermaid.png"
        stale.write_bytes(b"old")
        executable = os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc")
        result = self.render("mermaid", source, "--engine-cli", executable, "--export", "png")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(stale.read_bytes(), b"old")
        self.assertEqual(json.loads(result.stdout)["artifacts"], [])


class NativeDeliveryTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'out'
        self.output.mkdir()
        self.old = {'diagram.mmd': b'flowchart LR\n Old --> Good\n',
                    'diagram.mermaid.svg': b'old SVG', 'diagram.mermaid.png': b'old PNG',
                    'diagram.evidence.json': b'{"old": true}', 'notes.txt': b'keep me'}
        for name, data in self.old.items():
            (self.output / name).write_bytes(data)
        self.source = self.root / 'new.mmd'
        self.source.write_text('flowchart LR\n New --> Good\n')
        self.cli = self.root / 'renderer'
        self.cli.write_text('#!' + sys.executable + '\n' +
            "import pathlib,sys\n" +
            "source=pathlib.Path(sys.argv[sys.argv.index('-i')+1])\n" +
            "target=pathlib.Path(sys.argv[sys.argv.index('-o')+1])\n" +
            "if 'FAIL' in source.read_text() or target.suffix=='.png': sys.exit(2)\n" +
            "target.write_text('<svg xmlns=\"http://www.w3.org/2000/svg\"/>')\n")
        self.cli.chmod(0o755)

    def run_cli(self, *exports):
        argv = [sys.executable, str(SCRIPT), '--engine', 'mermaid', '--input', str(self.source),
                '--output', str(self.output), '--engine-cli', str(self.cli)]
        for fmt in exports:
            argv += ['--export', fmt]
        result = subprocess.run(argv, text=True, capture_output=True)
        return result, json.loads(result.stdout)

    def assert_old_bundle(self):
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, self.old)

    def test_engine_failure_preserves_previous_bundle(self):
        self.source.write_text('FAIL')
        result, report = self.run_cli('svg')
        self.assertEqual(result.returncode, 1)
        self.assertFalse(report['valid'])
        self.assertEqual(report['artifacts'], [])
        self.assert_old_bundle()

    def test_late_export_failure_preserves_previous_bundle(self):
        result, report = self.run_cli('svg', 'png')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report['exportCheck'], 'fail')
        self.assertEqual(report['artifacts'], [])
        self.assert_old_bundle()

    def test_first_failed_delivery_does_not_publish_partial_directory(self):
        shutil.rmtree(self.output)
        self.source.write_text('FAIL')
        result, report = self.run_cli('svg')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report['artifacts'], [])
        self.assertFalse(self.output.exists())

    def test_success_replaces_only_managed_artifacts_and_returns_final_paths(self):
        result, report = self.run_cli('svg')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.output / 'diagram.mmd').read_text(), self.source.read_text())
        self.assertFalse((self.output / 'diagram.evidence.json').exists())
        self.assertFalse((self.output / 'diagram.mermaid.png').exists())
        self.assertEqual((self.output / 'notes.txt').read_bytes(), b'keep me')
        self.assertEqual(set(report['artifacts']),
                         {str(self.output / 'diagram.mmd'), str(self.output / 'diagram.mermaid.svg')})
        self.assertTrue(all(Path(path).is_file() for path in report['artifacts']))

    def test_publication_failure_restores_previous_bundle(self):
        import contextlib
        import io
        from unittest.mock import patch
        import render_native_diagram as renderer
        replace = Path.replace
        def fail_publish(path, target):
            if path.parent.name == 'bundle' and Path(target).name == 'diagram.mermaid.svg':
                raise OSError('simulated publish failure')
            return replace(path, target)
        stdout = io.StringIO()
        with patch.object(Path, 'replace', fail_publish), contextlib.redirect_stdout(stdout):
            code = renderer.main(['--engine', 'mermaid', '--input', str(self.source),
                                  '--output', str(self.output), '--engine-cli', str(self.cli), '--export', 'svg'])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(stdout.getvalue())['valid'])
        self.assert_old_bundle()

    def test_publication_preserves_files_added_or_edited_during_rendering(self):
        self.cli.write_text(self.cli.read_text() +
                            f'\npathlib.Path({str(self.output / "notes.txt")!r}).write_text("edited")\n'
                            f'pathlib.Path({str(self.output / "new.txt")!r}).write_text("new")\n')
        result, report = self.run_cli('svg')
        self.assertEqual(result.returncode, 0, result.stderr or report)
        self.assertEqual((self.output / 'notes.txt').read_text(), 'edited')
        self.assertEqual((self.output / 'new.txt').read_text(), 'new')

    def test_plantuml_rejects_includes_overlapping_delivery_paths_before_rendering(self):
        import contextlib
        import io
        from unittest.mock import patch
        import render_native_diagram as renderer

        for name in ('diagram.puml', 'Diagram.PUML', 'diagram.puml/local.puml',
                     'diagram.plantuml.svg', 'diagram.evidence.json', '.native-includes.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir=self.root) as directory:
                source = Path(directory) / 'main.puml'
                dependency = source.parent / name
                dependency.parent.mkdir(parents=True, exist_ok=True)
                dependency.write_text('class Dependency\n')
                source.write_text(f'@startuml\n!include {name}\nclass Main\n@enduml\n')
                stdout = io.StringIO()
                with patch.object(renderer, '_check_diagram', return_value=None) as render, \
                     contextlib.redirect_stdout(stdout):
                    code = renderer.main(['--engine', 'plantuml', '--input', str(source),
                                          '--output', str(self.output), '--engine-cli', str(self.cli)])
                render.assert_not_called()
                self.assertEqual(code, 1)
                report = json.loads(stdout.getvalue())
                self.assertEqual(report['officialCheck'], 'not_run')
                self.assertIn(name, str(report['problems']))
                self.assert_old_bundle()

    def test_other_engine_keeps_plantuml_source_and_its_includes(self):
        import contextlib
        import io
        from unittest.mock import patch
        import render_native_diagram as renderer

        source = self.root / 'source.puml'
        source.write_text('@startuml\n!include links.puml\nclass Asset\n@enduml\n')
        (self.root / 'links.puml').write_text('Asset --> Ledger\n')
        with patch.object(renderer, 'find_engine', return_value=str(self.cli)), \
             patch.object(renderer, '_check_diagram', return_value=None), contextlib.redirect_stdout(io.StringIO()):
            for engine, native in (('plantuml', source), ('mermaid', self.source)):
                self.assertEqual(renderer.main(['--engine', engine, '--input', str(native),
                                                '--output', str(self.output)]), 0)
        self.assertIn('!include links.puml', (self.output / 'diagram.puml').read_text())
        self.assertTrue((self.output / 'links.puml').is_file())

    def test_publication_detects_outside_edits_and_preserves_their_bytes(self):
        import contextlib
        import io
        from unittest.mock import patch
        import render_native_diagram as renderer

        def edit_live_directory():
            (self.output / 'notes.txt').write_text('Concurrent edit')
            (self.output / 'new-note.txt').write_text('Concurrent addition')

        replace = Path.replace
        def edit_during_staging(path, target):
            result = replace(path, target)
            if path.parent.name == 'bundle' and Path(target).name == 'diagram.mermaid.svg':
                edit_live_directory()
            return result

        exchange = renderer._exchange_directories
        def edit_at_exchange(staged, destination):
            edit_live_directory()
            exchange(staged, destination)

        command = ['--engine', 'mermaid', '--input', str(self.source), '--output', str(self.output),
                   '--engine-cli', str(self.cli), '--export', 'svg']
        for during_staging, intervention in (
                (True, patch.object(Path, 'replace', edit_during_staging)),
                (False, patch.object(renderer, '_exchange_directories', edit_at_exchange))):
            with self.subTest(during_staging=during_staging):
                report = io.StringIO()
                with intervention, contextlib.redirect_stdout(report):
                    self.assertEqual(renderer.main(command), 1, report.getvalue())
                failure = json.loads(report.getvalue())
                self.assertEqual(failure['publicationCheck'], 'fail')
                if during_staging:
                    preserved = self.output
                    self.assertEqual((self.output / 'diagram.mmd').read_bytes(), self.old['diagram.mmd'])
                else:
                    preserved = Path(failure['recoveryBackup'])
                    self.assertEqual((self.output / 'diagram.mmd').read_bytes(), self.source.read_bytes())
                self.assertEqual((preserved / 'notes.txt').read_text(), 'Concurrent edit')
                self.assertEqual((preserved / 'new-note.txt').read_text(), 'Concurrent addition')
                if during_staging:
                    (self.output / 'notes.txt').write_bytes(self.old['notes.txt'])
                    (self.output / 'new-note.txt').unlink()

    def test_competing_publication_cannot_mix_source_and_svg(self):
        import contextlib
        import io
        import threading
        from unittest.mock import patch
        import render_native_diagram as renderer
        second = self.root / 'second.mmd'
        second.write_text('flowchart LR\n Second --> Good\n')
        self.cli.write_text(self.cli.read_text().replace(
            '/>\')', '><text>\'+source.read_text().split()[2]+\'</text></svg>\')'))
        pause, resume = threading.Event(), threading.Event()
        replace = Path.replace
        errors = []
        results = {}

        def interleave(path, target):
            if threading.current_thread().name == 'first-publisher' and (
                    path.parent.name == 'bundle' and Path(target).name == 'diagram.mmd'):
                pause.set()
                if not resume.wait(10):
                    raise OSError('fixture publication timed out')
            return replace(path, target)

        def publish(source, key):
            try:
                results[key] = renderer.main(['--engine', 'mermaid', '--input', str(source),
                    '--output', str(self.output), '--engine-cli', str(self.cli), '--export', 'svg'])
            except Exception as error:
                errors.append(error)

        with patch.object(Path, 'replace', interleave), contextlib.redirect_stdout(io.StringIO()):
            first = threading.Thread(name='first-publisher', target=publish, args=(self.source, 'first'))
            first.start()
            try:
                self.assertTrue(pause.wait(10), errors)
                publish(second, 'second')
            finally:
                resume.set()
                first.join(10)
        self.assertFalse(errors)
        self.assertEqual(results, {'first': 0, 'second': 1})
        self.assertEqual((self.output / 'diagram.mmd').read_text(), self.source.read_text())
        self.assertIn('<text>New</text>', (self.output / 'diagram.mermaid.svg').read_text())
        with contextlib.redirect_stdout(io.StringIO()):
            publish(second, 'retry')
        self.assertEqual(results['retry'], 0)
        self.assertIn('<text>Second</text>', (self.output / 'diagram.mermaid.svg').read_text())

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX process termination')
    def test_reader_and_terminated_writer_see_complete_old_generation_before_switch(self):
        barrier = self.root / 'staged'
        launcher = self.root / 'publisher.py'
        launcher.write_text(
            'import sys, time\nfrom pathlib import Path\n'
            f'sys.path.insert(0, {str(SCRIPT.resolve().parent)!r})\n'
            'from render_native_diagram import main\n'
            'replace = Path.replace\n'
            'def pause_after_svg(path, target):\n'
            '    result = replace(path, target)\n'
            '    if path.parent.name == "bundle" and Path(target).name == "diagram.mermaid.svg":\n'
            f'        Path({str(barrier)!r}).touch()\n'
            '        time.sleep(30)\n'
            '    return result\n'
            'Path.replace = pause_after_svg\n'
            'raise SystemExit(main(sys.argv[1:]))\n')
        with subprocess.Popen([sys.executable, '-B', str(launcher), '--engine', 'mermaid',
                               '--input', str(self.source), '--output', str(self.output),
                               '--engine-cli', str(self.cli), '--export', 'svg'],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
            import time
            try:
                deadline = time.monotonic() + 10
                while not barrier.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(barrier.exists(), 'publisher never reached the SVG staging barrier')
                visible = {path.name: path.read_bytes() for path in self.output.iterdir()}
            finally:
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=10)
        self.assertEqual(visible, self.old)
        self.assert_old_bundle()
        result, report = self.run_cli('svg')
        self.assertEqual(result.returncode, 0, result.stderr or report)
        self.assertEqual((self.output / 'diagram.mmd').read_bytes(), self.source.read_bytes())

    def test_timeout_preserves_previous_bundle(self):
        import contextlib
        import io
        from unittest.mock import patch
        import render_native_diagram as renderer
        stdout = io.StringIO()
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('renderer', 120)), \
                contextlib.redirect_stdout(stdout):
            code = renderer.main(['--engine', 'mermaid', '--input', str(self.source),
                                  '--output', str(self.output), '--engine-cli', str(self.cli)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())['artifacts'], [])
        self.assert_old_bundle()

    def test_archify_delivery_and_export_failures_preserve_previous_bundle(self):
        import contextlib
        import io
        from unittest.mock import patch
        import render_native_diagram as renderer
        source = self.root / 'workflow.json'
        source.write_text('{"diagram_type":"workflow"}')
        def deliver(argv, **kwargs):
            Path(argv[4]).write_text('<html>new</html>')
            return subprocess.CompletedProcess(argv, 0, '{"ok":true,"command":"deliver"}', '')
        for result, exports in ((subprocess.CompletedProcess([], 2, '{}', 'failed'), []), (deliver, ['--export', 'png'])):
            stdout = io.StringIO()
            kwargs = {'side_effect': result} if callable(result) else {'return_value': result}
            with self.subTest(exports=exports), patch('subprocess.run', **kwargs), \
                    patch.object(renderer, '_archify_export', return_value=([], 'export failed')), \
                    contextlib.redirect_stdout(stdout):
                code = renderer.main(['--engine', 'archify', '--input', str(source),
                                      '--output', str(self.output), '--engine-cli', str(self.cli), *exports])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(stdout.getvalue())['artifacts'], [])
            self.assert_old_bundle()

    def test_input_inside_output_and_unrelated_symlink_survive_success(self):
        self.source = self.output / 'diagram.mmd'
        (self.output / 'notes-link').symlink_to('notes.txt')
        result, report = self.run_cli('svg')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(report['valid'])
        self.assertEqual(self.source.read_bytes(), self.old['diagram.mmd'])
        self.assertTrue((self.output / 'notes-link').is_symlink())
        self.assertEqual((self.output / 'notes-link').read_bytes(), b'keep me')


if __name__ == "__main__":
    unittest.main()
