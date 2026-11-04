"""Isolated upstream installation tests; no network or user skill directories."""

import importlib
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from product_dependencies import REQUIRED


ROOT = Path(__file__).resolve().parents[1]


def isolated_upstreams(root):
    """Exercise real Git fetch/archive using a local pinned repository."""
    source = root / "upstream"
    source.mkdir()
    for name, references in REQUIRED.items():
        directory = source / "skills" / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test fixture\n---\n# Fixture\n")
        for reference in references:
            (directory / reference).write_text("# Format\n")
    (source / "LICENSE").write_text("Fixture license\n")
    (source / "skills/optional-skill").mkdir()
    (source / "skills/optional-skill/SKILL.md").write_text("not requested\n")
    for args in [("init",), ("add", "."), ("-c", "user.name=Jeff.Liu", "-c", "user.email=tests@example.invalid", "commit", "-m", "Fixture")]:
        subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    sources = {name: {"url": str(source), "revision": revision, "path": f"skills/{name}"} for name in REQUIRED}
    manifest = root / "test-sources.json"
    manifest.write_text(json.dumps(sources))
    launcher = root / "isolated-python"
    launcher.write_text(f"#!{sys.executable}\n" +
        "import importlib.util,json,os,sys\nfrom pathlib import Path\n" +
        "if len(sys.argv)>1 and Path(sys.argv[1]).name=='install_product_dependencies.py':\n" +
        " sys.path.insert(0,str(Path(sys.argv[1]).parent))\n" +
        " spec=importlib.util.spec_from_file_location('isolated_installer',sys.argv[1])\n" +
        " module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)\n" +
        f" module.SOURCES=json.loads(Path({str(manifest)!r}).read_text())\n" +
        " sys.exit(module.main(sys.argv[2:]))\n" +
        "os.execv(sys.executable,[sys.executable,*sys.argv[1:]])\n")
    launcher.chmod(0o755)
    return sources, launcher


def populate(directory):
    for name, references in REQUIRED.items():
        skill = directory / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n# Existing user version\n")
        for reference in references:
            (skill / reference).write_text("# Existing format\n")


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class UpstreamInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="product dependency install ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources, _ = isolated_upstreams(self.root)
        self.target = self.root / "codex/skills"
        self.module = importlib.import_module("install_product_dependencies")
        self.environment = patch.dict(os.environ, {"HOME": str(self.root), "CODEX_HOME": str(self.root / "codex"), "CLAUDE_HOME": str(self.root / "claude")})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def sync(self, *targets, check=False):
        return self.module.synchronize(targets or (self.target,), check=check, sources=self.sources)

    def test_missing_dependencies_installed_with_resources_license_and_pinned_source(self):
        report = self.sync()
        self.assertTrue(report["ready"])
        self.assertEqual(set(p.name for p in self.target.iterdir()), set(REQUIRED))
        for name, references in REQUIRED.items():
            for file in ("SKILL.md", "UPSTREAM-LICENSE", *references):
                self.assertTrue((self.target / name / file).is_file())
            origin = json.loads((self.target / name / ".project-docs-source.json").read_text())
            self.assertEqual(origin, self.sources[name])

    def test_existing_versions_reused_offline_without_writes_or_upgrade(self):
        populate(self.target)
        before = snapshot(self.target)
        with patch.object(self.module, "fetch_repository", side_effect=AssertionError("must not fetch")):
            self.assertTrue(self.sync()["ready"])
        self.assertEqual(snapshot(self.target), before)

    def test_partial_missing_and_multiple_hosts_preserve_existing(self):
        populate(self.target)
        shutil.rmtree(self.target / "grilling")
        before = (self.target / "brainstorming/SKILL.md").read_bytes()
        other = self.root / "claude/skills"
        self.assertTrue(self.sync(self.target, other)["ready"])
        self.assertEqual((self.target / "brainstorming/SKILL.md").read_bytes(), before)
        self.assertEqual(set(p.name for p in other.iterdir()), set(REQUIRED))

    def test_hosts_with_symlinked_shared_root_install_once(self):
        shared = self.root / "shared-skills"
        shared.mkdir()
        for home in (self.root / "codex", self.root / "claude"):
            home.mkdir()
            (home / "skills").symlink_to(shared)
        self.assertTrue(self.sync(self.target, self.root / "claude/skills")["ready"])
        self.assertEqual(set(p.name for p in shared.iterdir()), set(REQUIRED))

    def test_shared_root_does_not_leak_codex_private_visibility_to_claude(self):
        shared = self.root / "shared-skills"
        shared.mkdir()
        for home in (self.root / "codex", self.root / "claude"):
            home.mkdir()
            (home / "skills").symlink_to(shared)
        private = self.root / ".agents/skills"
        populate(private)
        before = snapshot(private)
        targets = (self.target, self.root / "claude/skills")
        self.assertFalse(self.sync(*targets, check=True)["ready"])
        with patch.object(self.module, "fetch_repository", side_effect=AssertionError("reuse existing")):
            self.assertTrue(self.sync(*targets)["ready"])
        self.assertTrue(self.sync(*targets, check=True)["ready"])
        self.assertEqual(snapshot(private), before)
        self.assertEqual(set(p.name for p in shared.iterdir()), set(REQUIRED))

    def test_file_broken_link_wrong_name_and_missing_resources_are_not_overwritten(self):
        for kind in ("file", "broken", "wrong-name", "missing-resource"):
            with self.subTest(kind=kind):
                target = self.root / kind
                target.mkdir()
                conflict = target / "domain-modeling"
                if kind == "file": conflict.write_text("keep")
                elif kind == "broken": conflict.symlink_to(self.root / "absent")
                else:
                    conflict.mkdir()
                    (conflict / "SKILL.md").write_text("---\nname: wrong\n---\n" if kind == "wrong-name" else "---\nname: domain-modeling\n---\n")
                before = snapshot(target)
                with self.assertRaises((RuntimeError, ValueError)):
                    self.sync(self.target, target)
                self.assertEqual(snapshot(target), before)
                self.assertFalse(self.target.exists())
                if kind == "broken": self.assertTrue(conflict.is_symlink())

    def test_check_is_readonly_and_reports_missing_then_available(self):
        with patch.object(self.module, "fetch_repository", side_effect=AssertionError("check must not fetch")):
            self.assertFalse(self.sync(check=True)["ready"])
        self.assertFalse(self.target.exists())
        self.sync()
        before = snapshot(self.target)
        self.assertTrue(self.sync(check=True)["ready"])
        self.assertEqual(snapshot(self.target), before)

    def test_readiness_does_not_claim_host_loading_or_model_compatibility(self):
        report = self.sync()
        self.assertEqual(report["hostVisibility"], "not_checked")
        self.assertEqual(report["behaviorCheck"], "not_run")
        self.assertTrue(all(item["versionState"] == "pinned" for item in report["dependencies"]))
        report = self.sync()
        self.assertTrue(all(item["status"] == "reused" for item in report["dependencies"]))

    def test_malformed_plugin_config_stops_without_mutation(self):
        codex = self.root / "codex"
        codex.mkdir()
        (codex / "config.toml").write_text('[plugins]\nmalformed="unexpected"\n')
        with self.assertRaisesRegex(RuntimeError, "plugin"):
            self.sync()
        self.assertFalse(self.target.exists())

    def test_cli_preflight_check_install_and_conflict_have_explicit_results(self):
        arguments = ["--skill-root", str(self.target)]
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(self.module, "SOURCES", self.sources), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(self.module.main([*arguments, "--preflight"]), 0)
            self.assertFalse(self.target.exists())
            self.assertEqual(self.module.main([*arguments, "--check"]), 1)
            self.assertIn('"missing"', output.getvalue())
            self.assertEqual(self.module.main(arguments), 0)
            self.assertEqual(self.module.main([*arguments, "--check"]), 0)
            (self.target / "grilling").unlink()
            (self.target / "grilling").write_text("keep")
            self.assertEqual(self.module.main(arguments), 1)
            self.assertIn('"ready": false', errors.getvalue())
            self.assertEqual((self.target / "grilling").read_text(), "keep")

    def test_shared_codex_skills_and_valid_links_reused_without_copy(self):
        shared = self.root / ".agents/skills"
        populate(shared)
        self.target.mkdir(parents=True)
        (self.target / "grilling").symlink_to(shared / "grilling")
        with patch.object(self.module, "fetch_repository", side_effect=AssertionError("reuse shared")):
            self.assertTrue(self.sync()["ready"])
        self.assertEqual([p.name for p in self.target.iterdir()], ["grilling"])

    def test_different_visible_versions_are_ambiguous_and_never_guessed(self):
        populate(self.target)
        shared = self.root / ".agents/skills"
        populate(shared)
        (shared / "grilling/SKILL.md").write_text("---\nname: grilling\n---\n# Other\n")
        before = snapshot(self.root)
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            self.sync()
        self.assertEqual(snapshot(self.root), before)

    def test_enabled_codex_and_claude_user_plugins_reused(self):
        codex = self.root / "codex"
        plugin = codex / "plugins/cache/official/superpowers/1/skills"
        populate(plugin)
        (codex / "config.toml").write_text('[plugins."superpowers@official"]\nenabled=true\n')
        claude = self.root / "claude"
        other = self.root / "claude-plugin/skills"
        populate(other)
        (claude / "plugins").mkdir(parents=True)
        (claude / "settings.json").write_text(json.dumps({"enabledPlugins": {"product@official": True}}))
        (claude / "plugins/installed_plugins.json").write_text(json.dumps({"plugins": {"product@official": [{"scope": "user", "installPath": str(other.parent)}]}}))
        with patch.object(self.module, "fetch_repository", side_effect=AssertionError("reuse plugins")):
            self.assertTrue(self.sync(self.target, claude / "skills")["ready"])
        self.assertFalse(self.target.exists())
        self.assertFalse((claude / "skills").exists())

    def test_download_failure_leaves_all_hosts_uninstalled(self):
        self.sources["grilling"] = dict(self.sources["grilling"], url=str(self.root / "unreachable"))
        with self.assertRaises(RuntimeError):
            self.sync(self.target, self.root / "other/skills")
        self.assertFalse(self.target.exists())
        self.assertFalse((self.root / "other/skills").exists())

    def test_invalid_downloaded_skill_and_symlink_do_not_publish(self):
        source = Path(self.sources["brainstorming"]["url"])
        (source / "skills/brainstorming/escape").symlink_to("../../../outside")
        subprocess.run(["git", "-C", str(source), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "-c", "user.name=Jeff.Liu", "-c", "user.email=tests@example.invalid", "commit", "-m", "Unsafe fixture"], check=True, capture_output=True)
        revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        for item in self.sources.values(): item["revision"] = revision
        with self.assertRaisesRegex(RuntimeError, "link|regular"):
            self.sync()
        self.assertFalse(self.target.exists())

    def test_target_created_after_preflight_is_preserved(self):
        original = Path.mkdir
        original_link = Path.symlink_to
        def concurrent(path, *args, **kwargs):
            if path == self.target / "grilling":
                original(path)
                (path / "keep.txt").write_text("concurrent user data")
                raise FileExistsError(str(path))
            return original(path, *args, **kwargs)
        def concurrent_link(path, *args, **kwargs):
            if path == self.target / "grilling":
                original(path)
                (path / "keep.txt").write_text("concurrent user data")
            return original_link(path, *args, **kwargs)
        with patch.object(Path, "mkdir", concurrent), patch.object(Path, "symlink_to", concurrent_link), self.assertRaises((RuntimeError, FileExistsError)):
            self.sync()
        self.assertEqual((self.target / "grilling/keep.txt").read_text(), "concurrent user data")
        self.assertFalse((self.target / "brainstorming").exists())

    def test_concurrent_symlink_in_unpublished_target_cannot_overwrite_user_file(self):
        external = self.root / "user-document"
        external.write_text("preserve user content")
        original = Path.mkdir
        def inject(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == self.target / "brainstorming":
                (path / "SKILL.md").symlink_to(external)
            return result
        with patch.object(Path, "mkdir", inject):
            try:
                self.sync()
            except (RuntimeError, OSError):
                pass
        self.assertEqual(external.read_text(), "preserve user content")

    def test_copy_failure_rolls_back_only_new_installations(self):
        populate(self.target)
        shutil.rmtree(self.target / "grilling")
        before = snapshot(self.target)
        with patch.object(shutil, "copytree", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.sync()
        self.assertEqual(snapshot(self.target), before)
        self.assertFalse((self.target / "grilling").exists())

    def test_bad_upstream_resource_does_not_publish_any_dependency(self):
        self.sources["domain-modeling"] = dict(self.sources["domain-modeling"], path="skills/grilling")
        with self.assertRaisesRegex(RuntimeError, "invalid upstream"):
            self.sync()
        self.assertFalse(self.target.exists())

    def test_disabled_plugin_cache_is_not_treated_as_visible(self):
        codex = self.root / "codex"
        cache = codex / "plugins/cache/official/plugin/1/skills"
        populate(cache)
        (codex / "config.toml").write_text('[plugins."plugin@official"]\nenabled=false\n')
        self.assertTrue(self.sync()["ready"])
        self.assertTrue((self.target / "grilling/SKILL.md").is_file())

    def test_multiple_enabled_plugin_versions_are_not_selected_by_directory_order(self):
        codex = self.root / "codex"
        for version in ('1', '2'):
            cache = codex / f"plugins/cache/official/plugin/{version}/skills"
            populate(cache)
            entry = cache / "brainstorming/SKILL.md"
            entry.write_text(entry.read_text() + version)
        (codex / "config.toml").write_text('[plugins."plugin@official"]\nenabled=true\n')
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            self.sync()
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
