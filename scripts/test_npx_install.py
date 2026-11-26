"""Contract tests for skills CLI installations in an isolated project."""

import ast
import os
import hashlib
import json
import contextlib
import http.server
import io
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

if __package__:
    from scripts import build_npx_bundles
else:
    import build_npx_bundles

sources = build_npx_bundles.sources

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("project-docs", "project-docs-api", "project-docs-diagram",
         "project-docs-lifecycle", "project-docs-overview", "project-docs-product", "project-docs-engineering")
ENTRY_SCRIPTS = {
    "project-docs-api": ("generate_api_docs.py",),
    "project-docs-diagram": ("generate_architecture.py", "render_native_diagram.py"),
    "project-docs-lifecycle": ("lifecycle_record.py", "lifecycle_relations.py", "lifecycle_quality.py"),
    "project-docs-overview": ("project_doc_context.py", "validate_project_doc.py"),
    "project-docs-product": ("validate_product_doc.py", "product_bundle.py", "product_handoff.py"),
    "project-docs-engineering": ("lifecycle_checklist.py", "provider_test_evidence.py"),
}


class NpxInstallTests(unittest.TestCase):
    def test_snapshots_exclude_repository_only_material(self):
        excluded = (
            "README.zh-CN.md", "audits", "docs/examples", "docs/media", "docs/launch",
            "docs/pdlc-capability-map.json", "docs/suite-release.md", "scripts/fixtures",
            "scripts/test_public_docs.py", "scripts/product_behavior_eval.py", "scripts/run_lifecycle_pilot.py",
            "skills/project-docs-lifecycle/assets/examples", "skills/project-docs-engineering/assets/examples",
            "skills/project-docs-overview/assets/beginner-explainers",
            "skills/project-docs-product/assets/examples/refund-sequence.svg",
        )
        for name in NAMES:
            bundle = ROOT / "skills" / name / ".bundle"
            for path in excluded:
                with self.subTest(skill=name, path=path):
                    self.assertFalse((bundle / path).exists())

    def test_api_snapshot_contains_only_api_runtime_and_shared_references(self):
        bundle = ROOT / "skills/project-docs-api/.bundle"
        self.assertEqual({path.parent.name for path in (bundle / "skills").glob("*/GUIDE.md")},
                         {"project-docs-api"})
        for path in ("scripts/ApiSaviorAstScanner.java", "scripts/queries/java/tags.scm",
                     "scripts/python_fastapi_adapter.py", "references/api-document-ir.md"):
            self.assertTrue((bundle / path).is_file(), path)
        self.assertFalse((bundle / "scripts/lifecycle_record.py").exists())
        self.assertFalse((bundle / "scripts/generate_architecture.py").exists())
        self.assertFalse((bundle / "scripts/validate_product_doc.py").exists())

    def test_specialist_bundles_keep_collaboration_dependencies_only(self):
        cases = {
            "diagram": (
                ("scripts/render_native_diagram.py", "scripts/export_archify.mjs"),
                ("scripts/project_doc_context.py", "scripts/product_browser.mjs", "skills/project-docs-overview/GUIDE.md"),
            ),
            "overview": (
                ("scripts/validate_project_doc.py", "scripts/render_native_diagram.py", "skills/project-docs-diagram/GUIDE.md"),
                ("scripts/validate_product_doc.py", "scripts/lifecycle_quality.py", "skills/project-docs-engineering/GUIDE.md"),
            ),
            "product": (
                ("scripts/project_doc_context.py", "scripts/render_native_diagram.py", "scripts/product_handoff.py",
                 "skills/project-docs-diagram/references/native-diagrams.md",
                 "skills/project-docs-lifecycle/references/checklist-catalog.json"),
                ("scripts/generate_api_docs.py", "scripts/validate_project_doc.py", "scripts/lifecycle_relations.py",
                 "skills/project-docs-diagram/GUIDE.md", "skills/project-docs-lifecycle/GUIDE.md"),
            ),
            "engineering": (
                ("scripts/lifecycle_quality.py", "scripts/provider_test_evidence.py", "scripts/lifecycle_relations.py",
                 "skills/project-docs-lifecycle/references/coordination.md", "skills/project-docs-product/references/ui-design.md"),
                ("scripts/generate_architecture.py", "scripts/product_browser.mjs", "skills/project-docs-product/GUIDE.md",
                 "skills/project-docs-lifecycle/GUIDE.md"),
            ),
        }
        for name, (required, excluded) in cases.items():
            bundle = ROOT / "skills" / f"project-docs-{name}" / ".bundle"
            for resource in required:
                self.assertTrue((bundle / resource).is_file(), (name, resource))
            for resource in excluded:
                self.assertFalse((bundle / resource).exists(), (name, resource))

    def test_bundled_python_modules_have_no_missing_local_imports(self):
        repository_modules = {path.stem for path in sources() if path.parts[0] == "scripts" and path.suffix == ".py"}
        for name in NAMES:
            scripts = ROOT / "skills" / name / ".bundle/scripts"
            present = {path.stem for path in scripts.glob("*.py")}
            for path in scripts.glob("*.py"):
                for statement in ast.walk(ast.parse(path.read_bytes())):
                    if isinstance(statement, ast.Import):
                        modules = {alias.name.split(".")[0] for alias in statement.names}
                    elif isinstance(statement, ast.ImportFrom) and statement.module:
                        modules = {statement.module.split(".")[0]}
                    else:
                        continue
                    self.assertFalse((modules & repository_modules) - present, (name, path.name, modules))

    def test_diagram_standalone_routes_explainer_to_its_owner(self):
        bundle = ROOT / "skills/project-docs-diagram/.bundle"
        guide_path = "skills/project-docs-diagram/references/native-diagrams.md"
        guide = (bundle / guide_path).read_text()
        self.assertIn("https://github.com/ainiaa/skills-project-docs/blob/main/skills/"
                      "project-docs-overview/references/explainer.md", guide)
        self.assertIn("(diagram-view-ir.md)", guide)
        with_overview = ROOT / "skills/project-docs-overview/.bundle" / guide_path
        self.assertIn("(../../project-docs-overview/references/explainer.md)", with_overview.read_text())

    def test_lifecycle_keeps_stage_routes_and_focused_source_evidence(self):
        bundle = ROOT / "skills/project-docs-lifecycle/.bundle"
        guides = {path.parent.name for path in (bundle / "skills").glob("*/GUIDE.md")}
        self.assertEqual(guides, {"project-docs-lifecycle", "project-docs-engineering",
                                  "project-docs-product", "project-docs-diagram"})
        for resource in ("scripts/project_doc_context.py", "scripts/product_handoff.py",
                         "scripts/lifecycle_quality.py", "scripts/provider_test_evidence.py",
                         "scripts/render_native_diagram.py", "scripts/product_browser.mjs"):
            self.assertTrue((bundle / resource).is_file(), resource)
        for resource in ("scripts/generate_api_docs.py", "scripts/project_doc_impact.py",
                         "scripts/validate_project_doc.py", "skills/project-docs-overview/assets"):
            self.assertFalse((bundle / resource).exists(), resource)

    def test_unified_entry_keeps_all_deliverables_and_only_product_ships_its_example(self):
        router = ROOT / "skills/project-docs/.bundle"
        guides = {path.parent.name for path in (router / "skills").glob("*/GUIDE.md")}
        self.assertEqual(guides, set(NAMES))
        for resource in ("scripts/generate_api_docs.py", "scripts/validate_project_doc.py",
                         "skills/project-docs-overview/assets/project-explainer.archify.md"):
            self.assertTrue((router / resource).is_file(), resource)
        journey = "skills/project-docs-product/assets/examples/access-request/journey.test.mjs"
        for name in ("project-docs", "project-docs-lifecycle"):
            self.assertFalse((ROOT / "skills" / name / ".bundle" / journey).exists(), name)
        self.assertTrue((ROOT / "skills/project-docs-product/.bundle" / journey).is_file())

    def test_snapshot_keeps_lifecycle_schema_and_links_to_source_examples(self):
        bundle = ROOT / "skills/project-docs/.bundle"
        for path in ("assets/lifecycle-record.json", "references/checklist-catalog.json"):
            self.assertTrue((bundle / "skills/project-docs-lifecycle" / path).is_file(), path)
        guide = (bundle / "skills/project-docs-overview/references/explainer.md").read_text()
        self.assertIn("https://github.com/ainiaa/skills-project-docs/blob/main/skills/project-docs-overview/"
                      "assets/beginner-explainers/registration-rule.archify.md", guide)
        self.assertIn("../assets/project-explainer.archify.md", guide)

    def test_each_entry_only_links_to_files_inside_its_own_installation(self):
        for name in NAMES:
            directory = ROOT / 'skills' / name
            for link in re.findall(r'\]\(([^)]+)\)', (directory / 'SKILL.md').read_text()):
                target = urllib.parse.unquote(link.split('#', 1)[0])
                if not target or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target):
                    continue
                resolved = (directory / target).resolve()
                self.assertTrue(resolved.is_relative_to(directory.resolve()), (name, link))
                self.assertTrue(resolved.is_file(), (name, link))

    def test_sources_keep_runtime_validation_and_explicitly_supported_journey(self):
        kept = [Path("scripts/lifecycle_test_runner.py"),
                Path("skills/project-docs-product/assets/examples/access-request/journey.test.mjs")]
        excluded = [Path("scripts/build_npx_bundles.py"), Path("scripts/test_product_npx_installer.py"),
                    Path("scripts/test_lifecycle_quality.py"), Path("scripts/test_product_runtime.mjs"),
                    Path("scripts/test_public_docs.py"), Path("skills/project-docs-lifecycle/assets/examples/test_cases.py"),
                    Path("skills/project-docs-product/assets/examples/access-request/evidence/browser.json")]
        inventory = "\0".join(str(path) for path in kept + excluded).encode() + b"\0"
        with patch.object(build_npx_bundles.subprocess, "check_output", return_value=inventory):
            self.assertEqual(build_npx_bundles.sources(), kept)

    def test_prototype_guide_names_a_journey_shipped_with_the_installed_runner(self):
        bundle = ROOT / "skills/project-docs-product/.bundle"
        text = (bundle / "skills/project-docs-product/references/prototype.md").read_text()
        command = re.search(r"`node (scripts/product_browser\.mjs) --directory (skills/\S+) --test (\S+\.mjs)`", text)
        self.assertIsNotNone(command)
        runner, directory, journey = command.groups()
        self.assertTrue((bundle / runner).is_file())
        self.assertTrue((bundle / directory / journey).is_file())
        self.assertNotIn("node --test scripts/test_product_browser.mjs", text)

    def test_generated_snapshots_are_marked_for_review(self):
        paths = ["skills/project-docs-api/.bundle/scripts/generate_api_docs.py",
                 "skills/project-docs-api/SKILL.md"]
        result = subprocess.run(["git", "check-attr", "linguist-generated", "--", *paths],
                                cwd=ROOT, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines, [f"{paths[0]}: linguist-generated: set",
                                 f"{paths[1]}: linguist-generated: unspecified"])

    @unittest.skipUnless(os.environ.get("PROJECT_DOCS_NPX_TEST") == "1", "explicit CLI integration test")
    def test_documented_migration_removes_only_owned_codex_links(self):
        command = "bash install.sh --uninstall --host codex"
        for filename in ("README.md", "README.zh-CN.md"):
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn(command, text)
            self.assertLess(text.index(command), text.index("npx skills add ainiaa/skills-project-docs"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ".codex/skills"
            target.mkdir(parents=True)
            for name in NAMES:
                (target / name).symlink_to(ROOT / "skills" / name, target_is_directory=True)
            unrelated = target / "unrelated"
            unrelated.mkdir()
            (unrelated / "SKILL.md").write_text("keep")
            env = {**os.environ, "HOME": directory, "CODEX_HOME": str(root / ".codex"),
                   "XDG_CONFIG_HOME": str(root / ".config"), "XDG_STATE_HOME": str(root / ".local/state"),
                   "npm_config_cache": str(Path.home() / ".npm")}
            uninstall = subprocess.run(["bash", str(ROOT / "install.sh"), "--uninstall", "--host", "codex"],
                                       cwd=root, env=env, text=True, capture_output=True, timeout=30)
            self.assertEqual(uninstall.returncode, 0, uninstall.stdout + uninstall.stderr)
            self.assertEqual((unrelated / "SKILL.md").read_text(), "keep")
            self.assertTrue(all(not (target / name).exists() for name in NAMES))
            install = subprocess.run(["npx", "-y", "skills@1.7.6", "add", str(ROOT), "--skill", "*", "-g", "-a", "codex", "-y"],
                                     cwd=root, env=env, text=True, capture_output=True, timeout=90)
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            self.assertTrue(all((root / ".agents/skills" / name / "SKILL.md").is_file() for name in NAMES))
            self.assertEqual((unrelated / "SKILL.md").read_text(), "keep")
            if shutil.which("codex"):
                self.assertEqual(sorted(self.codex_skill_names(root, env)), sorted(NAMES))

    def test_individually_installed_entry_links_resolve(self):
        for name in NAMES:
            with self.subTest(skill=name), tempfile.TemporaryDirectory() as directory:
                installed = Path(directory) / name
                shutil.copytree(ROOT / "skills" / name, installed)
                entry = installed / "SKILL.md"
                for link in re.findall(r"\]\(([^)]+)\)", entry.read_text(encoding="utf-8")):
                    target = urllib.parse.unquote(link.split("#", 1)[0])
                    if not target or re.match(r"^[\w+.-]+:", target):
                        continue
                    with self.subTest(link=link):
                        self.assertTrue((entry.parent / target).is_file(), link)

    def test_router_instructions_match_packaged_guide_links(self):
        for path in (ROOT / "skills/project-docs/SKILL.md", ROOT / "skills/project-docs/.bundle/skills/project-docs/GUIDE.md"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("读取选中能力的 `SKILL.md`", text)
            self.assertIn("读取选中能力的入口说明", text)

    @unittest.skipUnless(os.environ.get("PROJECT_DOCS_NPX_TEST") == "1" and shutil.which("gemini"), "Gemini CLI unavailable")
    def test_gemini_discovers_only_published_entrypoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {**os.environ, "HOME": directory, "GEMINI_CLI_HOME": directory,
                   "XDG_CONFIG_HOME": str(root / ".config"), "XDG_STATE_HOME": str(root / ".local/state"),
                   "XDG_CACHE_HOME": str(root / ".cache"), "XDG_DATA_HOME": str(root / ".local/share"),
                   "npm_config_cache": str(Path.home() / ".npm"), "DO_NOT_TRACK": "1", "NO_COLOR": "1"}
            install = subprocess.run(["npx", "-y", "skills@1.7.6", "add", str(ROOT), "--skill", "*", "-g", "-a", "gemini-cli", "-y"],
                                     cwd=root, env=env, text=True, capture_output=True, timeout=90)
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            listed = subprocess.run(["gemini", "skills", "list"], cwd=root, env=env,
                                    text=True, capture_output=True, timeout=45)
            self.assertEqual(listed.returncode, 0, listed.stdout + listed.stderr)
            names = re.findall(r"(?m)^(project-docs(?:-[a-z-]+)?) \[Enabled\]$", listed.stdout)
            self.assertEqual(sorted(names), sorted(NAMES))
            self.assertNotIn(".bundle/skills/", listed.stdout)

    @unittest.skipUnless(os.environ.get("PROJECT_DOCS_NPX_TEST") == "1" and shutil.which("opencode"), "OpenCode CLI unavailable")
    def test_opencode_uses_only_published_entrypoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {**os.environ, "HOME": directory, "XDG_CONFIG_HOME": str(root / ".config"),
                   "XDG_STATE_HOME": str(root / ".local/state"), "XDG_CACHE_HOME": str(root / ".cache"),
                   "XDG_DATA_HOME": str(root / ".local/share"), "npm_config_cache": str(Path.home() / ".npm"),
                   "DO_NOT_TRACK": "1", "NO_COLOR": "1"}
            install = subprocess.run(["npx", "-y", "skills@1.7.6", "add", str(ROOT), "--skill", "*", "-g", "-a", "opencode", "-y"],
                                     cwd=root, env=env, text=True, capture_output=True, timeout=90)
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            listed = subprocess.run(["opencode", "debug", "skill", "--pure"], cwd=root, env=env,
                                    text=True, capture_output=True, timeout=45)
            self.assertEqual(listed.returncode, 0, listed.stdout + listed.stderr)
            found = [item for item in json.loads(listed.stdout) if item["name"] in NAMES]
            self.assertEqual(sorted(item["name"] for item in found), sorted(NAMES))
            for item in found:
                self.assertNotIn(".bundle", Path(item["location"]).parts, item["location"])

    def test_can_run_directly_from_a_different_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/test_npx_install.py"),
                                     "NpxInstallTests.test_regeneration_preserves_existing_bundle_when_source_is_missing"],
                                    cwd=directory, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(os.environ.get("PROJECT_DOCS_NPX_TEST") == "1" and shutil.which("codex"), "Codex CLI unavailable")
    def test_codex_discovers_each_installed_skill_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skills = root / ".agents/skills"
            skills.mkdir(parents=True)
            (root / ".codex").mkdir()
            for name in NAMES:
                shutil.copytree(ROOT / "skills" / name, skills / name)
            env = {**os.environ, "HOME": str(root), "CODEX_HOME": str(root / ".codex"),
                   "XDG_CONFIG_HOME": str(root / ".config"), "XDG_STATE_HOME": str(root / ".local/state")}
            self.assertEqual(sorted(self.codex_skill_names(root, env)), sorted(NAMES))

    def codex_skill_names(self, root, env):
        process = subprocess.Popen(["codex", "app-server"], cwd=root, env=env, text=True,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1)

        def request(message):
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        def response(identity):
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            try:
                while selector.select(20):
                    line = process.stdout.readline()
                    if not line:
                        self.fail("Codex app-server exited before responding")
                    result = json.loads(line)
                    if result.get("id") == identity:
                        return result
                self.fail("Codex app-server timed out")
            finally:
                selector.close()

        try:
            request({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "npx-test", "version": "1"}}})
            self.assertIn("result", response(1))
            request({"method": "initialized"})
            request({"id": 2, "method": "skills/list", "params": {"cwds": [str(root)], "forceReload": True}})
            found = response(2)["result"]["data"][0]["skills"]
            return [skill["name"] for skill in found if skill["name"] in NAMES]
        finally:
            process.terminate()
            process.wait(timeout=10)
            process.stdin.close()
            process.stdout.close()

    @unittest.skipUnless(os.environ.get("PROJECT_DOCS_NPX_TEST") == "1", "explicit CLI integration test")
    def test_git_update_replaces_both_older_bundle_layouts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "skills").mkdir(parents=True)
            obsolete = {
                "project-docs": ("audits/lifecycle/open-case-20261031.manifest.json",
                                 "skills/project-docs-product/assets/examples/access-request/journey.test.mjs"),
                "project-docs-lifecycle": ("scripts/generate_api_docs.py", "skills/project-docs-overview/GUIDE.md"),
            }
            for name, resources in obsolete.items():
                checkout = ROOT / "skills" / name
                shutil.copytree(checkout, source / "skills" / name, ignore=shutil.ignore_patterns("__pycache__"))
                for resource in resources:
                    self.assertFalse((checkout / ".bundle" / resource).exists())
                    old = source / "skills" / name / ".bundle" / resource
                    old.parent.mkdir(parents=True, exist_ok=True)
                    old.write_text("old layout\n")
            home = root / "home"
            home.mkdir()
            env = {**os.environ, "HOME": str(home), "CODEX_HOME": str(home / ".codex"),
                   "XDG_CONFIG_HOME": str(home / ".config"), "XDG_STATE_HOME": str(home / ".local/state"),
                   "npm_config_cache": str(Path.home() / ".npm"),
                   "GIT_CONFIG_NOSYSTEM": "1", "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}

            def run(argv, cwd=source):
                result = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result

            run(["git", "init", "-q", "-b", "main"])
            run(["git", "add", "."])
            commit = ["git", "-c", "user.name=Jeff.Liu", "-c", "user.email=jeff@example.invalid", "commit", "-qm"]
            run([*commit, "fixture"])
            remote = root / "fixture-owner/fixture.git"
            remote.parent.mkdir()
            run(["git", "clone", "--bare", str(source), str(remote)], cwd=root)

            class GitHandler(http.server.BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def serve_git(self):
                    path, _, query = self.path.partition("?")
                    length = int(self.headers.get("Content-Length", "0"))
                    request_env = {**env, "GIT_PROJECT_ROOT": str(root), "GIT_HTTP_EXPORT_ALL": "1",
                                   "PATH_INFO": path, "QUERY_STRING": query, "REQUEST_METHOD": self.command,
                                   "CONTENT_TYPE": self.headers.get("Content-Type", ""), "CONTENT_LENGTH": str(length)}
                    result = subprocess.run(["git", "http-backend"], input=self.rfile.read(length),
                                            capture_output=True, env=request_env, timeout=30)
                    headers, body = result.stdout.split(b"\r\n\r\n", 1)
                    lines = headers.decode("latin1").split("\r\n")
                    status = next((int(line.split()[1]) for line in lines if line.lower().startswith("status:")), 200)
                    self.send_response(status)
                    for line in lines:
                        key, _, value = line.partition(":")
                        if key.lower() != "status":
                            self.send_header(key, value.strip())
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                do_GET = serve_git
                do_POST = serve_git

            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GitHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                config = root / "gitconfig"
                config.write_text(f'[url "http://127.0.0.1:{server.server_port}/"]\n    insteadOf = https://github.com/\n')
                preload = root / "offline.cjs"
                preload.write_text('const original = globalThis.fetch; globalThis.fetch = (u, o) => String(u).startsWith("https://api.github.com/") ? Promise.resolve(new Response("", {status: 404})) : original(u, o);\n')
                env.update({"GIT_CONFIG_GLOBAL": str(config), "NODE_OPTIONS": f"--require={preload}", "DO_NOT_TRACK": "1"})
                installs = (("project-docs", root, home, "-g"),
                            ("project-docs-lifecycle", root / "workspace", root / "workspace", "-p"))
                (root / "workspace").mkdir()
                npx = ["npx", "-y", "skills@1.7.6"]
                for name, cwd, install_root, scope in installs:
                    run([*npx, "add", "fixture-owner/fixture", "--skill", name,
                         *(["-g"] if scope == "-g" else ["--copy"]), "-a", "codex", "-y"], cwd=cwd)
                    bundle = install_root / ".agents/skills" / name / ".bundle"
                    for path in obsolete[name]:
                        self.assertTrue((bundle / path).is_file(), (name, path))
                        (source / "skills" / name / ".bundle" / path).unlink()
                    self.assertEqual({entry.parent.name for entry in bundle.parent.parent.glob("*/SKILL.md")}, {name})
                run(["git", "add", "."])
                run([*commit, "update"])
                run(["git", "push", str(remote), "main"])
                for name, cwd, install_root, scope in installs:
                    with self.subTest(skill=name, scope=scope):
                        update = run([*npx, "update", scope, name, "-y"], cwd=cwd)
                        bundle = install_root / ".agents/skills" / name / ".bundle"
                        expected = ROOT / "skills" / name / ".bundle"
                        installed = {path.relative_to(bundle): path.read_bytes()
                                     for path in bundle.rglob("*") if path.is_file()}
                        published = {path.relative_to(expected): path.read_bytes() for path in expected.rglob("*")
                                     if path.is_file() and "__pycache__" not in path.parts}
                        self.assertEqual(installed.keys(), published.keys(), update.stdout + update.stderr)
                        for path in installed:
                            self.assertEqual(installed[path], published[path], path)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_regeneration_preserves_existing_bundle_when_source_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "skills/demo/.bundle"
            bundle.mkdir(parents=True)
            sentinel = bundle / "previous"
            sentinel.write_text("preserve")
            with patch.object(build_npx_bundles, "ROOT", root), \
                 patch.object(build_npx_bundles, "NAMES", ("demo",)), \
                 patch.dict(build_npx_bundles.BUNDLE_CONTENTS, {"demo": {"scripts", "runtime", "missing"}}), \
                 patch.object(build_npx_bundles, "sources", return_value=[Path("missing")]), \
                 patch.object(sys, "argv", ["build_npx_bundles.py"]):
                with self.assertRaises(FileNotFoundError):
                    build_npx_bundles.main()
                self.assertEqual(sentinel.read_text(), "preserve")

    def test_snapshot_rejects_paths_outside_checkout(self):
        for path in (Path("../outside"), Path("/outside")):
            with self.subTest(path=path), \
                 patch.object(build_npx_bundles, "sources", return_value=[path]), \
                 patch.object(sys, "argv", ["build_npx_bundles.py", "--check"]):
                with self.assertRaisesRegex(ValueError, "unsafe source path"):
                    build_npx_bundles.main()

    def test_regeneration_rejects_symlinked_sources_without_replacing_bundle(self):
        for symlink_parent in (False, True):
            with self.subTest(symlink_parent=symlink_parent), tempfile.TemporaryDirectory() as directory:
                outer = Path(directory)
                root = outer / "checkout"
                root.mkdir()
                outside = outer / "outside"
                outside.mkdir()
                (outside / "runtime.py").write_text("private data")
                if symlink_parent:
                    (root / "scripts").symlink_to(outside, target_is_directory=True)
                else:
                    (root / "scripts").mkdir()
                    (root / "scripts/runtime.py").symlink_to(outside / "runtime.py")
                bundle = root / "skills/demo/.bundle"
                bundle.mkdir(parents=True)
                sentinel = bundle / "previous"
                sentinel.write_text("preserve")
                with patch.object(build_npx_bundles, "ROOT", root), \
                     patch.object(build_npx_bundles, "NAMES", ("demo",)), \
                     patch.dict(build_npx_bundles.BUNDLE_CONTENTS, {"demo": {"scripts", "runtime", "missing"}}), \
                     patch.object(build_npx_bundles, "sources", return_value=[Path("scripts/runtime.py")]), \
                     patch.object(sys, "argv", ["build_npx_bundles.py"]):
                    with self.assertRaisesRegex(ValueError, "symlink"):
                        build_npx_bundles.main()
                self.assertEqual(sentinel.read_text(), "preserve")

    def test_snapshot_rejects_guide_path_collision(self):
        with patch.object(build_npx_bundles, "sources", return_value=[
                Path("skills/project-docs/SKILL.md"), Path("skills/project-docs/GUIDE.md")]), \
             patch.object(sys, "argv", ["build_npx_bundles.py", "--check"]):
            with self.assertRaisesRegex(ValueError, "collide"):
                build_npx_bundles.main()

    def test_regeneration_restores_previous_bundle_when_publish_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runtime").write_text("new")
            bundle = root / "skills/demo/.bundle"
            bundle.mkdir(parents=True)
            (bundle / "previous").write_text("preserve")
            rename = Path.rename

            def fail_publish(path, target):
                if path.name == "staged":
                    raise OSError("publish failed")
                return rename(path, target)

            with patch.object(build_npx_bundles, "ROOT", root), \
                 patch.object(build_npx_bundles, "NAMES", ("demo",)), \
                 patch.dict(build_npx_bundles.BUNDLE_CONTENTS, {"demo": {"scripts", "runtime", "missing"}}), \
                 patch.object(build_npx_bundles, "sources", return_value=[Path("runtime")]), \
                 patch.object(sys, "argv", ["build_npx_bundles.py"]), \
                 patch.object(Path, "rename", fail_publish):
                with self.assertRaises(OSError):
                    build_npx_bundles.main()
                self.assertEqual((bundle / "previous").read_text(), "preserve")

    def test_regeneration_restores_previous_bundle_when_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runtime").write_text("new")
            bundle = root / "skills/demo/.bundle"
            bundle.mkdir(parents=True)
            (bundle / "previous").write_text("preserve")
            rename = Path.rename

            def interrupt_publish(path, target):
                if path.name == "staged":
                    raise KeyboardInterrupt()
                return rename(path, target)

            with patch.object(build_npx_bundles, "ROOT", root), \
                 patch.object(build_npx_bundles, "NAMES", ("demo",)), \
                 patch.dict(build_npx_bundles.BUNDLE_CONTENTS, {"demo": {"scripts", "runtime", "missing"}}), \
                 patch.object(build_npx_bundles, "sources", return_value=[Path("runtime")]), \
                 patch.object(sys, "argv", ["build_npx_bundles.py"]), \
                 patch.object(Path, "rename", interrupt_publish):
                with self.assertRaises(KeyboardInterrupt):
                    build_npx_bundles.main()
                self.assertEqual((bundle / "previous").read_text(), "preserve")

    def test_regeneration_keeps_backup_if_restore_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runtime").write_text("new")
            bundle = root / "skills/demo/.bundle"
            bundle.mkdir(parents=True)
            (bundle / "previous").write_text("preserve")
            rename = Path.rename

            def fail_publish_and_restore(path, target):
                if path.name in ("staged", "previous"):
                    raise OSError("rename failed")
                return rename(path, target)

            with patch.object(build_npx_bundles, "ROOT", root), \
                 patch.object(build_npx_bundles, "NAMES", ("demo",)), \
                 patch.dict(build_npx_bundles.BUNDLE_CONTENTS, {"demo": {"scripts", "runtime", "missing"}}), \
                 patch.object(build_npx_bundles, "sources", return_value=[Path("runtime")]), \
                 patch.object(sys, "argv", ["build_npx_bundles.py"]), \
                 patch.object(Path, "rename", fail_publish_and_restore):
                with self.assertRaises(OSError):
                    build_npx_bundles.main()
                backups = list(bundle.parent.glob(".npx-bundle-*/previous/previous"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(), "preserve")

    def test_packaged_guides_and_references_have_resolvable_local_links(self):
        for name in NAMES:
            bundle = ROOT / "skills" / name / ".bundle"
            guides = (bundle / "skills").glob("*/GUIDE.md")
            references = (bundle / "skills").glob("*/references/**/*.md")
            for path in [*guides, *references, *(bundle / "docs").glob("*.md"), *(bundle / "references").glob("*.md")]:
                for link in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                    target, _, anchor = link.partition("#")
                    if not target or re.match(r"^[\w+.-]+:", target) or any(c in target for c in "<> {}"):
                        continue
                    with self.subTest(skill=name, source=path.relative_to(bundle), link=link):
                        resolved = (path.parent / urllib.parse.unquote(target)).resolve()
                        self.assertTrue(resolved.is_relative_to(bundle))
                        self.assertTrue(resolved.is_file())
                        if anchor and resolved.suffix == ".md":
                            headings = re.findall(r"^#{1,6} +(.+)$", resolved.read_text(), re.M)
                            slugs = {re.sub(r"[^\w -]", "", heading.lower()).strip().replace(" ", "-")
                                     for heading in headings}
                            self.assertIn(urllib.parse.unquote(anchor), slugs)

    def test_bundle_check_rejects_missing_changed_and_extra_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts/runtime.py").write_text("original")
            bundle = root / "skills/demo/.bundle"
            with patch.object(build_npx_bundles, "ROOT", root), \
                 patch.object(build_npx_bundles, "NAMES", ("demo",)), \
                 patch.dict(build_npx_bundles.BUNDLE_CONTENTS, {"demo": {"scripts", "runtime", "missing"}}), \
                 patch.object(build_npx_bundles, "sources", return_value=[Path("scripts/runtime.py")]), \
                 patch.object(sys, "argv", ["build_npx_bundles.py", "--check"]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(build_npx_bundles.main(), 1)
                (bundle / "scripts").mkdir(parents=True)
                target = bundle / "scripts/runtime.py"
                target.write_text("changed")
                self.assertEqual(build_npx_bundles.main(), 1)
                target.write_text("original")
                self.assertEqual(build_npx_bundles.main(), 0)
                cache = bundle / "scripts/__pycache__"
                cache.mkdir()
                (cache / "runtime.cpython-311.pyc").write_bytes(b"temporary bytecode")
                self.assertEqual(build_npx_bundles.main(), 0)
                target.unlink()
                target.symlink_to(root / "scripts/runtime.py")
                self.assertEqual(build_npx_bundles.main(), 1)
                target.unlink()
                target.write_text("original")
                (bundle / "unexpected").write_text("extra")
                self.assertEqual(build_npx_bundles.main(), 1)

    def test_each_skill_contains_self_contained_shared_resources(self):
        repository = build_npx_bundles.repository_sources()
        eligible = sources()
        for name in NAMES:
            with self.subTest(skill=name):
                bundle = ROOT / "skills" / name / ".bundle"
                self.assertTrue((bundle / "skills" / name / "GUIDE.md").is_file())
                self.assertFalse(list(bundle.rglob("SKILL.md")))
                self.assertFalse((bundle / "scripts/build_npx_bundles.py").exists())
                self.assertFalse((bundle / "scripts/test_npx_install.py").exists())
                selected = set(build_npx_bundles.bundle_sources(name, eligible))
                self.assertEqual((bundle / "references/audience.md").read_bytes(),
                                 build_npx_bundles.snapshot_bytes(Path("references/audience.md"), repository, selected))
                for script in ENTRY_SCRIPTS.get(name, ("generate_api_docs.py", "lifecycle_quality.py")):
                    self.assertEqual((bundle / "scripts" / script).read_bytes(),
                                     (ROOT / "scripts" / script).read_bytes())

    def test_packaged_guides_link_to_other_guides(self):
        bundle = ROOT / "skills/project-docs/.bundle"
        for name in NAMES:
            guide = bundle / "skills" / name / "GUIDE.md"
            for link in re.findall(r"\]\((\.\./project-docs[^)]*)\)", guide.read_text()):
                with self.subTest(skill=name, link=link):
                    self.assertTrue((guide.parent / link.split("#", 1)[0]).is_file())
                    self.assertNotIn("/SKILL.md", link)

    def test_unified_guide_scopes_update_commands_to_the_installation_method(self):
        directory = ROOT / "skills/project-docs/.bundle"
        guide = (directory / "skills/project-docs/GUIDE.md").read_text()
        self.assertIn("## 安装与更新\n", guide)
        instructions = guide.split("## 安装与更新\n", 1)[1].split("\n| 用户需要", 1)[0]
        self.assertRegex(instructions, r"(?m)^- .*`npx skills add`.*`npx skills update")
        self.assertRegex(instructions, r"(?m)^- .*`npx github:ainiaa/skills-project-docs`.*原安装命令")
        self.assertRegex(instructions, r"(?m)^- .*Git 检出.*`bash <真实Skill目录>/\.\./\.\./install.sh --update")

    def test_guide_routes_use_local_copies_when_the_target_is_shipped(self):
        cases = (
            ("project-docs", "project-docs-diagram", "project-docs-overview", True),
            ("project-docs-lifecycle", "project-docs-engineering", "project-docs-product", True),
            ("project-docs", "project-docs-lifecycle", "project-docs-api", True),
            ("project-docs-diagram", "project-docs-diagram", "project-docs-overview", False),
            ("project-docs-lifecycle", "project-docs-lifecycle", "project-docs-api", False),
        )
        for package, origin, target, local in cases:
            with self.subTest(package=package, origin=origin, target=target):
                guide = ROOT / "skills" / package / ".bundle/skills" / origin / "GUIDE.md"
                link = (f"../{target}/GUIDE.md" if local else
                        f"https://github.com/ainiaa/skills-project-docs/blob/main/skills/{target}/SKILL.md")
                self.assertIn(f"]({link})", guide.read_text())

    def test_localized_public_links_keep_encoded_paths_and_heading_fragments(self):
        source = Path("skills/project-docs/SKILL.md")
        target = Path("docs/stage evidence.md")
        link = re.search(r"\]\(([^)]+)\)", f"[证据]({build_npx_bundles.REPO_DOCS}docs/stage%20evidence.md#L4)")
        self.assertEqual(build_npx_bundles.snapshot_link(source, link, {target}, {target}),
                         "](../../docs/stage%20evidence.md#L4)")

    def check_installed_engineering_checkpoint(self, run, root):
        catalog = json.loads(run("lifecycle_checklist.py", "--stage", "L4"))
        design = root / "design.md"
        text = "The item list reads inventory and returns a retryable error when inventory is unavailable."
        design.write_text(f"# Item list design\n\n{text}\n")
        artifact = {"path": design.name, "sha256": hashlib.sha256(design.read_bytes()).hexdigest()}
        evidence = [{**artifact, "quote": text}]
        records = []
        for definition in catalog["items"]:
            record = {"id": definition["id"], "reason": "Read-only item list scope.", "evidence": evidence,
                      "applicability": "applicable" if definition["required"] else "not_applicable"}
            if definition["required"]:
                record["verification"] = {"kind": "review", "result": "passed", "evidence": evidence}
            records.append(record)
        checks = [{"id": identity, "verdict": "pass", "reason": "Source and recovery reviewed.", "evidence": evidence}
                  for identity in ("design_dependencies", "failure_recovery")]
        quality = {"schema_version": 1, "project_ref": "P1", "subject_ref": "REQ-1", "stages": [{
            "stage": "L4", "artifact": artifact, "reviewer": "fixture-reviewer", "reviewer_kind": "model",
            "at": "2026-11-16T10:00:00+08:00", "checks": checks,
            "coverage": {"catalog_sha256": catalog["fingerprint"], "items": records},
        }]}
        (root / "quality.json").write_text(json.dumps(quality))
        result = json.loads(run("lifecycle_quality.py", "checkpoint", "--root", str(root),
                                "--contract", "quality.json", "--target", f"L4:{design.name}", "--no-project-inputs"))
        self.assertTrue(result["details_ready"], result)

    @unittest.skipUnless(os.environ.get("PROJECT_DOCS_NPX_TEST") == "1", "explicit CLI integration test")
    def test_global_default_install_is_isolated_and_has_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {**os.environ, "HOME": str(root), "CODEX_HOME": str(root / ".codex"),
                   "XDG_CONFIG_HOME": str(root / ".config"), "XDG_STATE_HOME": str(root / ".local/state"),
                   "npm_config_cache": str(Path.home() / ".npm")}
            result = subprocess.run(["npx", "-y", "skills@1.7.6", "add", str(ROOT),
                                     "--skill", "*", "-g", "-a", "codex", "-y"],
                                    cwd=root, env=env, text=True, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in NAMES:
                with self.subTest(skill=name):
                    installed = root / ".agents/skills" / name
                    for script in ENTRY_SCRIPTS.get(name, ("generate_api_docs.py", "lifecycle_quality.py")):
                        self.assertTrue((installed / ".bundle/scripts" / script).is_file(), script)
                    self.assertTrue((installed / ".bundle/skills" / name / "GUIDE.md").is_file())
            listing = subprocess.run(["npx", "-y", "skills@1.7.6", "list", "-g", "-a", "codex", "--json"],
                                     cwd=root, env=env, text=True, capture_output=True, timeout=90)
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertEqual(sorted(item["name"] for item in json.loads(listing.stdout)), sorted(NAMES))

    @unittest.skipUnless(os.environ.get("PROJECT_DOCS_NPX_TEST") == "1", "explicit CLI integration test")
    def test_cli_copy_install_has_working_resources_for_each_skill(self):
        for name in NAMES:
            with self.subTest(skill=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "sample"
                source.mkdir()
                (source / "app.py").write_text('from fastapi import FastAPI\napp = FastAPI()\n@app.get("/items")\ndef items(): return []\n')
                env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
                env.update({"DO_NOT_TRACK": "1", "PYTHONDONTWRITEBYTECODE": "1"})
                result = subprocess.run(["npx", "-y", "skills@1.7.6", "add", str(ROOT),
                                         "--skill", name, "-a", "codex", "--copy", "-y"],
                                        cwd=root, env=env, text=True, capture_output=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                installations = root / ".agents/skills"
                self.assertEqual({path.parent.name for path in installations.glob("*/SKILL.md")}, {name})
                entry = installations / name / "SKILL.md"
                for link in re.findall(r"\]\(([^)]+)\)", entry.read_text(encoding="utf-8")):
                    target = urllib.parse.unquote(link.split("#", 1)[0])
                    if target and not re.match(r"^[\w+.-]+:", target):
                        self.assertTrue((entry.parent / target).is_file(), f"{name}: {link}")
                bundle = entry.parent / ".bundle"
                self.assertTrue((bundle / "skills" / name / "GUIDE.md").is_file())
                self.assertTrue((bundle / "references/audience.md").is_file())
                published = ROOT / "skills" / name / ".bundle"
                installed_files = {path.relative_to(bundle) for path in bundle.rglob("*") if path.is_file()}
                published_files = {path.relative_to(published) for path in published.rglob("*") if path.is_file()
                                   and "__pycache__" not in path.parts}
                self.assertEqual(installed_files, published_files)
                for path in installed_files:
                    self.assertEqual((bundle / path).read_bytes(), (published / path).read_bytes(), path)
                    self.assertEqual((bundle / path).stat().st_mode & 0o111, (published / path).stat().st_mode & 0o111, path)

                output = root / "api"
                fixture = ROOT / "skills/project-docs-product/assets/examples/access-request"
                example = root / "product-input"
                example.mkdir()
                for filename in ("input.md", "prd.md", "prototype.html", "review.md"):
                    shutil.copyfile(fixture / filename, example / filename)
                starter = bundle / "skills/project-docs-lifecycle/assets/lifecycle-record.json"
                workflows = {
                    "project-docs-api": [
                        ["generate_api_docs.py", "--language", "python", "--source", str(source), "--output", str(output), "--no-codegraph"],
                    ],
                    "project-docs-diagram": [
                        ["generate_architecture.py", "context", "--source", str(source), "--output", str(root / "architecture.json")],
                    ],
                    "project-docs-overview": [
                        ["project_doc_context.py", "--source", str(source), "--focus", "items", "--output", str(root / "context.json")],
                    ],
                    "project-docs-lifecycle": [["lifecycle_record.py", "--record", str(starter)]],
                    "project-docs-engineering": [["lifecycle_checklist.py", "--stage", "L4"]],
                    "project-docs-product": [
                        ["validate_product_doc.py", "--file", str(example / "prd.md"), "--prototype", str(example / "prototype.html")],
                    ],
                }
                if name == "project-docs":
                    commands = [command for flow in workflows.values() for command in flow]
                elif name == "project-docs-lifecycle":
                    commands = [command for skill, flow in workflows.items() if skill != "project-docs-api" for command in flow]
                    commands += [["lifecycle_relations.py", "validate", "--record", str(starter)],
                                 ["product_handoff.py", "--help"], ["provider_test_evidence.py", "--help"]]
                elif name == "project-docs-product":
                    commands = workflows[name] + workflows["project-docs-overview"] + [["render_native_diagram.py", "--help"]]
                else:
                    commands = workflows[name]
                commands += [[script, "--help"] for script in ENTRY_SCRIPTS.get(name, ())]
                def run(script, *arguments):
                    check = subprocess.run([sys.executable, str(bundle / "scripts" / script), *arguments],
                                           cwd=root, env=env, text=True, capture_output=True, timeout=30)
                    self.assertEqual(check.returncode, 0, f"{script} {arguments}\n{check.stdout}{check.stderr}")
                    return check.stdout

                for command in commands:
                    run(*command)
                if name in {"project-docs", "project-docs-api"}:
                    self.assertIn("/items", (output / "api-docs.md").read_text())
                if name in {"project-docs", "project-docs-lifecycle"}:
                    self.check_installed_engineering_checkpoint(run, root)
                    self.assertIn("app.py", (root / "context.json").read_text())
                if name in {"project-docs", "project-docs-overview"}:
                    template = bundle / "skills/project-docs-overview/assets/project-overview.md"
                    headings = re.findall(r"^## .+$", template.read_text(), re.M)
                    document = root / "overview.md"
                    document.write_text("# Item list\n\n" + "\n\n".join(f"{heading}\n\nReviewed in app.py." for heading in headings))
                    report = json.loads(run("validate_project_doc.py", "--kind", "project", "--file", str(document)))
                    self.assertTrue(report["valid"], report)


if __name__ == "__main__":
    unittest.main()
