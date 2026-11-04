"""Contract tests for skills CLI installations in an isolated project."""

import os
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
         "project-docs-lifecycle", "project-docs-overview", "project-docs-product")
SCRIPTS = ("generate_api_docs.py", "generate_architecture.py", "lifecycle_record.py",
           "project_doc_context.py", "validate_product_doc.py")


class NpxInstallTests(unittest.TestCase):
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
    def test_git_install_and_update_refreshes_shared_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "skills").mkdir(parents=True)
            shutil.copytree(ROOT / "skills/project-docs-api", source / "skills/project-docs-api")
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
                run(["npx", "-y", "skills@1.7.6", "add", "fixture-owner/fixture", "--skill", "project-docs-api", "-g", "-a", "codex", "-y"], cwd=root)
                resource = source / "skills/project-docs-api/.bundle/references/audience.md"
                resource.write_text(resource.read_text() + "\nFixture update marker.\n")
                run(["git", "add", "."])
                run([*commit, "update"])
                run(["git", "push", str(remote), "main"])
                update = run(["npx", "-y", "skills@1.7.6", "update", "-g", "project-docs-api", "-y"], cwd=root)
                installed = home / ".agents/skills/project-docs-api/.bundle/references/audience.md"
                self.assertTrue("Fixture update marker." in installed.read_text(),
                                update.stdout + update.stderr + "\n" + str(list(home.rglob("*lock*"))))
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
                 patch.object(build_npx_bundles, "sources", return_value=[Path("runtime")]), \
                 patch.object(sys, "argv", ["build_npx_bundles.py"]), \
                 patch.object(Path, "rename", fail_publish_and_restore):
                with self.assertRaises(OSError):
                    build_npx_bundles.main()
                backups = list(bundle.parent.glob(".npx-bundle-*/previous/previous"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(), "preserve")

    def test_lifecycle_audit_references_are_packaged(self):
        for name in NAMES:
            with self.subTest(skill=name):
                bundle = ROOT / "skills" / name / ".bundle"
                for file in ("README.md", "open-case-20261031.manifest.json", "open-case-20261031.zip"):
                    self.assertEqual((bundle / "audits/lifecycle" / file).read_bytes(),
                                     (ROOT / "audits/lifecycle" / file).read_bytes())

    def test_existing_skill_markdown_links_resolve_in_bundle(self):
        bundle = ROOT / "skills/project-docs/.bundle"
        tracked = set(sources())
        for path in (ROOT / "skills").glob("*/**/*.md"):
            if ".bundle" in path.parts:
                continue
            for link in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                target = urllib.parse.unquote(link.split("#", 1)[0])
                if not target or re.match(r"^[\w+.-]+:", target) or any(c in target for c in "<> {}"):
                    continue
                target = (path.parent / target).resolve()
                if target.is_file() and target.is_relative_to(ROOT) and target.relative_to(ROOT) in tracked:
                    with self.subTest(source=path, target=target):
                        self.assertTrue((bundle / build_npx_bundles.snapshot_path(target.relative_to(ROOT))).is_file())

    def test_bundle_check_rejects_missing_changed_and_extra_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts/runtime.py").write_text("original")
            bundle = root / "skills/demo/.bundle"
            with patch.object(build_npx_bundles, "ROOT", root), \
                 patch.object(build_npx_bundles, "NAMES", ("demo",)), \
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
        for name in NAMES:
            with self.subTest(skill=name):
                bundle = ROOT / "skills" / name / ".bundle"
                self.assertTrue((bundle / "skills" / name / "GUIDE.md").is_file())
                self.assertFalse(list(bundle.rglob("SKILL.md")))
                self.assertFalse((bundle / "scripts/build_npx_bundles.py").exists())
                self.assertFalse((bundle / "scripts/test_npx_install.py").exists())
                self.assertEqual((bundle / "references/audience.md").read_bytes(),
                                 (ROOT / "references/audience.md").read_bytes())
                for script in SCRIPTS:
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

    def test_packaged_identity_and_lifecycle_pilot_use_guides(self):
        scripts = ROOT / "skills/project-docs/.bundle/scripts"
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        identity = subprocess.run([sys.executable, "-c", "from product_behavior_eval import skill_identity; assert 'GUIDE.md' in skill_identity()"],
                                  cwd=scripts, env=env, text=True, capture_output=True, timeout=30)
        self.assertEqual(identity.returncode, 0, identity.stdout + identity.stderr)
        with tempfile.TemporaryDirectory() as directory:
            pilot = subprocess.run([sys.executable, str(scripts / "run_lifecycle_pilot.py"), "--output", str(Path(directory) / "output")],
                                   env=env, text=True, capture_output=True, timeout=90)
            self.assertEqual(pilot.returncode, 0, pilot.stdout + pilot.stderr)

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
                    self.assertTrue((installed / ".bundle/scripts/generate_api_docs.py").is_file())
                    self.assertTrue((installed / ".bundle/skills" / name / "GUIDE.md").is_file())
            listing = subprocess.run(["npx", "-y", "skills@1.7.6", "list", "-g", "-a", "codex", "--json"],
                                     cwd=root, env=env, text=True, capture_output=True, timeout=90)
            self.assertEqual(listing.returncode, 0, listing.stderr)
            self.assertEqual(sorted(item["name"] for item in json.loads(listing.stdout)), sorted(NAMES))

    @unittest.skipUnless(os.environ.get("PROJECT_DOCS_NPX_TEST") == "1", "explicit CLI integration test")
    def test_cli_copy_install_has_working_resources_for_each_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample"
            source.mkdir()
            (source / "app.py").write_text('from fastapi import FastAPI\napp = FastAPI()\n@app.get("/items")\ndef items(): return []\n')
            for name in NAMES:
                result = subprocess.run(["npx", "-y", "skills@1.7.6", "add", str(ROOT),
                                         "--skill", name, "-a", "codex", "--copy", "-y"],
                                        cwd=root, text=True, capture_output=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                entry = root / ".agents/skills" / name / "SKILL.md"
                for link in re.findall(r"\]\(([^)]+)\)", entry.read_text(encoding="utf-8")):
                    target = urllib.parse.unquote(link.split("#", 1)[0])
                    if target and not re.match(r"^[\w+.-]+:", target):
                        self.assertTrue((entry.parent / target).is_file(), f"{name}: {link}")
                bundle = entry.parent / ".bundle"
                self.assertTrue((bundle / "skills" / name / "GUIDE.md").is_file())
                self.assertTrue((bundle / "references/audience.md").is_file())
                for path in sources():
                    installed_path = bundle / build_npx_bundles.snapshot_path(path)
                    self.assertEqual(installed_path.read_bytes(), build_npx_bundles.snapshot_bytes(path), str(path))
                    self.assertEqual(installed_path.stat().st_mode & 0o111,
                                     (ROOT / path).stat().st_mode & 0o111, str(path))
                for script in SCRIPTS:
                    check = subprocess.run(["python3", str(bundle / "scripts" / script), "--help"],
                                           text=True, capture_output=True, timeout=30)
                    self.assertEqual(check.returncode, 0, check.stderr)
                for test in ("test_generate_api_docs.ApiModuleBoundaryTests.test_adapters_and_renderers_import_without_cli_or_each_other",
                             "test_lifecycle_record.RecordTests.test_a_later_execution_in_another_offset_remains_a_new_observation"):
                    check = subprocess.run(["python3", "-m", "unittest", test], cwd=bundle / "scripts",
                                           text=True, capture_output=True, timeout=30)
                    self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
                scripts = bundle / "scripts"
                output = root / f"output-{name}"
                examples = bundle / "skills/project-docs-product/assets/examples/access-request"
                commands = [
                    ["generate_api_docs.py", "--language", "python", "--source", str(source), "--output", str(output), "--no-codegraph"],
                    ["generate_architecture.py", "context", "--source", str(source), "--output", str(root / f"architecture-{name}.json")],
                    ["project_doc_context.py", "--source", str(source), "--focus", "items", "--output", str(root / f"context-{name}.json")],
                    ["lifecycle_record.py", "--record", str(bundle / "skills/project-docs-lifecycle/assets/examples/order-status/lifecycle-record.json")],
                    ["validate_product_doc.py", "--file", str(examples / "prd.md"), "--prototype", str(examples / "prototype.html")],
                ]
                for command in commands:
                    check = subprocess.run(["python3", str(scripts / command[0]), *command[1:]],
                                           text=True, capture_output=True, timeout=30)
                    self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
                self.assertIn("/items", (output / "api-docs.md").read_text())
                self.assertTrue(json.loads((root / f"context-{name}.json").read_text()))


if __name__ == "__main__":
    unittest.main()
