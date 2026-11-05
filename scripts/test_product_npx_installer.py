"""Tests for the standalone npx entry point."""

import json
import os
import shutil
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "bin/project-docs.js"


class ProjectDocsNpxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake = self.bin / "npx"
        fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys, shutil, time
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as f: f.write(" ".join(args) + "\\n")
if os.environ.get("FAIL") == "1": sys.exit(7)
agent = args[args.index("-a") + 1]
root = pathlib.Path.home() if "-g" in args else pathlib.Path.cwd()
target = root / (".agents/skills" if agent == "codex" else ".claude/skills")
names = ["project-docs", "project-docs-api", "project-docs-diagram", "project-docs-lifecycle", "project-docs-overview", "project-docs-product"] if args[args.index("add") + 1].startswith("/") else [args[args.index("--skill") + 1]]
if os.environ.get("WAIT_PROJECT") and names[0] == "project-docs":
    pathlib.Path(os.environ["WAIT_PROJECT"]).write_text("started")
    time.sleep(30)
for name in names:
    skill = target / name
    if name == "brainstorming" and os.environ.get("SYMLINK_SKILL"):
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.symlink_to(os.environ["SYMLINK_SKILL"], target_is_directory=True)
        continue
    if skill.exists() and not skill.is_symlink(): shutil.rmtree(skill)
    if name.startswith("project-docs"):
        source = pathlib.Path(args[args.index("add") + 1]) / "skills" / name
        shutil.copytree(source, skill, ignore=shutil.ignore_patterns("__pycache__"))
        if os.environ.get("CORRUPT_PROJECT") == name:
            (skill / ".bundle/scripts/generate_api_docs.py").unlink()
        if name == "project-docs" and os.environ.get("FAIL_PROJECT_AFTER_FIRST"):
            (skill / "SKILL.md").write_text("partial update")
            lock = pathlib.Path.home() / ".agents/.skill-lock.json" if "-g" in args else pathlib.Path.cwd() / "skills-lock.json"
            lock.parent.mkdir(parents=True, exist_ok=True)
            data = json.loads(lock.read_text()) if lock.exists() else {"version": 1, "skills": {}}
            data["skills"][name] = {"source": "partial"}
            lock.write_text(json.dumps(data))
            if os.environ.get("DELETE_LOCK") == "1": lock.unlink()
            sys.exit(7)
        continue
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("---\\nname: " + name + "\\ndescription: test\\n---\\n" + os.environ.get("VERSION", "one"))
    if name == "domain-modeling" and os.environ.get("INVALID") != "1":
        for ref in ("GLOSSARY-FORMAT.md", "ADR-FORMAT.md"):
            (skill / ref).write_text("reference")
    if name == "domain-modeling" and os.environ.get("INVALID") == "1":
        lock = pathlib.Path.home() / ".agents/.skill-lock.json" if "-g" in args else pathlib.Path.cwd() / "skills-lock.json"
        lock.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(lock.read_text()) if lock.exists() else {"version": 1, "skills": {}}
        data["skills"][name] = {"source": "invalid"}
        lock.write_text(json.dumps(data))
    if name == "brainstorming" and os.environ.get("SYMLINK_MARKER"):
        (skill / ".project-docs-managed.json").symlink_to(os.environ["SYMLINK_MARKER"])
''')
        fake.chmod(0o755)
        self.env = {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "HOME": str(self.root), "CALLS": str(self.root / "calls")}

    def run_cli(self, *args, env=None):
        return subprocess.run(["node", str(CLI), *args], cwd=self.root,
                              env=env or self.env, text=True, capture_output=True, timeout=20)

    def test_package_version_matches_project_version(self):
        package = json.loads((ROOT / "package.json").read_text())
        self.assertEqual(package["version"], (ROOT / "VERSION").read_text().strip())

    def test_default_installs_only_project_skills(self):
        result = self.run_cli("--agent", "codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len((self.root / "calls").read_text().splitlines()), 1)
        self.assertTrue((self.root / ".agents/skills/project-docs/SKILL.md").exists())

    def test_dependencies_are_installed_then_updated(self):
        result = self.run_cli("--with-deps", "--agent", "claude-code", "--global")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("brainstorming", "grilling", "domain-modeling"):
            self.assertIn("one", (self.root / ".claude/skills" / name / "SKILL.md").read_text())
        result = self.run_cli("--with-deps", "--agent", "claude-code", "--global", env={**self.env, "VERSION": "two"})
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("brainstorming", "grilling", "domain-modeling"):
            self.assertIn("two", (self.root / ".claude/skills" / name / "SKILL.md").read_text())

    def test_unmanaged_or_modified_dependency_is_not_overwritten(self):
        target = self.root / ".agents/skills/grilling"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("user content")
        result = self.run_cli("--with-deps", "--agent", "codex")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((target / "SKILL.md").read_text(), "user content")
        self.assertFalse((self.root / "calls").exists())

    def test_unmanaged_project_skill_is_not_overwritten(self):
        target = self.root / ".agents/skills/project-docs-api"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("my own skill")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((target / "SKILL.md").read_text(), "my own skill")
        self.assertFalse((self.root / "calls").exists())

    def test_identical_previous_project_install_can_be_adopted(self):
        target = self.root / ".agents/skills/project-docs-api"
        shutil.copytree(ROOT / "skills/project-docs-api", target, ignore=shutil.ignore_patterns("__pycache__"))
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((target / ".project-docs-managed.json").is_file())

    def test_project_skill_edits_are_not_overwritten(self):
        self.assertEqual(self.run_cli().returncode, 0)
        target = self.root / ".agents/skills/project-docs-api/SKILL.md"
        target.write_text("my edits")
        before = (self.root / "calls").read_text()
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.assertEqual(target.read_text(), "my edits")
        self.assertEqual((self.root / "calls").read_text(), before)

    def test_python_bytecode_cache_does_not_block_update(self):
        self.assertEqual(self.run_cli().returncode, 0)
        cache = self.root / ".agents/skills/project-docs-api/.bundle/scripts/__pycache__"
        cache.mkdir(parents=True)
        (cache / "script.cpython-311.pyc").write_bytes(b"generated")
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_partial_project_update_restores_previous_skills(self):
        self.assertEqual(self.run_cli().returncode, 0)
        lock = self.root / "skills-lock.json"
        original = {"version": 1, "skills": {"project-docs": {"source": "before"}, "other": {"source": "keep"}}}
        lock.write_text(json.dumps(original))
        skills = self.root / ".agents/skills"
        before = (skills / "project-docs/SKILL.md").read_text()
        result = self.run_cli(env={**self.env, "VERSION": "two", "FAIL_PROJECT_AFTER_FIRST": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((skills / "project-docs/SKILL.md").read_text(), before)
        self.assertTrue((skills / "project-docs-product/.project-docs-managed.json").exists())
        self.assertEqual(json.loads(lock.read_text()), original)

    def test_interrupt_restores_previous_skills(self):
        import time
        self.assertEqual(self.run_cli().returncode, 0)
        skills = self.root / ".agents/skills"
        before = (skills / "project-docs/SKILL.md").read_text()
        ready = self.root / "ready"
        process = subprocess.Popen(["node", str(CLI)], cwd=self.root,
                                   env={**self.env, "WAIT_PROJECT": str(ready)},
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        try:
            for _ in range(100):
                if ready.exists(): break
                time.sleep(0.05)
            self.assertTrue(ready.exists())
            os.killpg(process.pid, signal.SIGINT)
            self.assertNotEqual(process.wait(timeout=10), 0)
            self.assertEqual((skills / "project-docs/SKILL.md").read_text(), before)
            self.assertFalse(list(skills.glob(".project-docs-backup-*")))
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

    def test_concurrent_installation_is_rejected_before_changes(self):
        import time
        self.assertEqual(self.run_cli().returncode, 0)
        ready = self.root / "ready"
        process = subprocess.Popen(["node", str(CLI)], cwd=self.root,
                                   env={**self.env, "WAIT_PROJECT": str(ready)},
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        try:
            for _ in range(100):
                if ready.exists(): break
                time.sleep(0.05)
            self.assertTrue(ready.exists())
            calls_before = (self.root / "calls").read_text()
            result = self.run_cli()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((self.root / "calls").read_text(), calls_before)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                process.wait(timeout=10)

    def test_existing_install_lock_is_preserved(self):
        lock = self.root / ".agents/.project-docs-install.lock"
        lock.mkdir(parents=True)
        (lock / "owner").write_text("keep")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((lock / "owner").read_text(), "keep")
        self.assertFalse((self.root / "calls").exists())

    def test_missing_project_resource_causes_failure_and_restore(self):
        self.assertEqual(self.run_cli().returncode, 0)
        target = self.root / ".agents/skills/project-docs-api/.bundle/scripts/generate_api_docs.py"
        before = target.read_bytes()
        result = self.run_cli(env={**self.env, "CORRUPT_PROJECT": "project-docs-api"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), before)

    def test_deleted_install_record_is_restored_after_failure(self):
        self.assertEqual(self.run_cli().returncode, 0)
        lock = self.root / "skills-lock.json"
        original = {"version": 1, "skills": {"project-docs": {"source": "before"}, "other": {"source": "keep"}}}
        lock.write_text(json.dumps(original))
        result = self.run_cli(env={**self.env, "FAIL_PROJECT_AFTER_FIRST": "1", "DELETE_LOCK": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(lock.exists())
        self.assertEqual(json.loads(lock.read_text()), original)

    def test_non_bytecode_in_cache_is_protected(self):
        self.assertEqual(self.run_cli().returncode, 0)
        cache = self.root / ".agents/skills/project-docs-api/.bundle/scripts/__pycache__"
        cache.mkdir(parents=True)
        (cache / "user-data.txt").write_text("keep")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((cache / "user-data.txt").read_text(), "keep")

    def test_global_codex_existing_host_skill_is_not_shadowed(self):
        target = self.root / ".codex/skills/project-docs-api"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("my own skill")
        self.assertNotEqual(self.run_cli("--global").returncode, 0)
        self.assertEqual((target / "SKILL.md").read_text(), "my own skill")
        self.assertFalse((self.root / "calls").exists())

    def test_modified_managed_dependency_is_not_overwritten(self):
        self.assertEqual(self.run_cli("--with-deps").returncode, 0)
        target = self.root / ".agents/skills/grilling/SKILL.md"
        target.write_text("my changes")
        before = (self.root / "calls").read_text()
        self.assertNotEqual(self.run_cli("--with-deps").returncode, 0)
        self.assertEqual(target.read_text(), "my changes")
        self.assertEqual((self.root / "calls").read_text(), before)

    def test_changed_permissions_are_not_overwritten(self):
        self.assertEqual(self.run_cli("--with-deps").returncode, 0)
        target = self.root / ".agents/skills/grilling/SKILL.md"
        target.chmod(0o755)
        self.assertNotEqual(self.run_cli("--with-deps").returncode, 0)
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)

    def test_global_host_dependency_is_not_shadowed_by_project_install(self):
        target = self.root / ".codex/skills/grilling"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("user content")
        work = self.root / "project"
        work.mkdir()
        result = subprocess.run(["node", str(CLI), "--with-deps"], cwd=work,
                                env=self.env, text=True, capture_output=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((target / "SKILL.md").read_text(), "user content")
        self.assertFalse((self.root / "calls").exists())

    def test_invalid_options_and_child_failure_exit_nonzero(self):
        self.assertNotEqual(self.run_cli("--agent", "unknown").returncode, 0)
        self.assertNotEqual(self.run_cli("--bogus").returncode, 0)
        self.assertNotEqual(self.run_cli(env={**self.env, "FAIL": "1"}).returncode, 0)

    def test_incomplete_upstream_is_reported(self):
        result = self.run_cli("--with-deps", env={**self.env, "INVALID": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / ".agents/skills/domain-modeling/.project-docs-managed.json").exists())

    def test_invalid_update_preserves_previous_dependency(self):
        self.assertEqual(self.run_cli("--with-deps").returncode, 0)
        lock = self.root / "skills-lock.json"
        original = {"version": 1, "skills": {"domain-modeling": {"source": "before"}, "other": {"source": "keep"}}}
        lock.write_text(json.dumps(original))
        target = self.root / ".agents/skills/domain-modeling"
        before = (target / "SKILL.md").read_text()
        result = self.run_cli("--with-deps", env={**self.env, "INVALID": "1", "VERSION": "two"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((target / "SKILL.md").read_text(), before)
        self.assertTrue((target / "ADR-FORMAT.md").is_file())
        self.assertTrue((target / ".project-docs-managed.json").is_file())
        self.assertEqual(json.loads(lock.read_text()), original)

    def test_invalid_global_update_restores_global_lock(self):
        self.assertEqual(self.run_cli("--with-deps", "--global").returncode, 0)
        lock = self.root / ".agents/.skill-lock.json"
        lock.parent.mkdir(parents=True, exist_ok=True)
        original = {"version": 1, "skills": {"domain-modeling": {"source": "before"}, "other": {"source": "keep"}}}
        lock.write_text(json.dumps(original))
        result = self.run_cli("--with-deps", "--global", env={**self.env, "INVALID": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(lock.read_text()), original)

    def test_upstream_marker_symlink_is_not_followed(self):
        outside = self.root / "outside"
        outside.write_text("preserve")
        result = self.run_cli("--with-deps", env={**self.env, "SYMLINK_MARKER": str(outside)})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outside.read_text(), "preserve")

    def test_installed_dependency_symlink_is_not_followed(self):
        outside = self.root / "outside-skill"
        outside.mkdir()
        (outside / "SKILL.md").write_text("---\nname: brainstorming\ndescription: test\n---\ntext")
        result = self.run_cli("--with-deps", env={**self.env, "SYMLINK_SKILL": str(outside)})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((outside / ".project-docs-managed.json").exists())


if __name__ == "__main__":
    unittest.main()
