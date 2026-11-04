#!/usr/bin/env python3
"""Build and check self-contained copies for the skills CLI."""

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("project-docs", "project-docs-api", "project-docs-diagram",
         "project-docs-lifecycle", "project-docs-overview", "project-docs-product")


def sources():
    output = subprocess.check_output(["git", "ls-files", "-z", "--", "skills", "scripts",
                                      "references", "docs", "audits", "install.sh", "install-arch.sh", "VERSION",
                                      "README.md", "README.en.md", "README.zh-CN.md", "CHANGELOG.md", "LICENSE"], cwd=ROOT)
    paths = {Path(path) for path in output.decode().split("\0") if path and "/.bundle/" not in path}
    paths.difference_update((Path("scripts/build_npx_bundles.py"), Path("scripts/test_npx_install.py")))
    return sorted(paths)


def snapshot_path(path):
    if len(path.parts) == 3 and path.parts[0] == "skills" and path.parts[1] in NAMES and path.name == "SKILL.md":
        return path.with_name("GUIDE.md")
    return path


def validate_source(path):
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe source path: {path}")
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlink in source path: {current}")


def snapshot_bytes(path):
    data = (ROOT / path).read_bytes()
    if path.suffix == ".md":
        text = data.decode("utf-8")
        if snapshot_path(path) != path:
            text = text.replace("](.bundle/references/", "](../../references/")
            text = text.replace("](.bundle/docs/", "](../../docs/")
            text = re.sub(r"\]\(\.bundle/skills/(project-docs(?:-[a-z0-9-]+)?)/", r"](../\1/", text)
        text = re.sub(r"(project-docs(?:-[a-z0-9-]+)?/)SKILL\.md", r"\1GUIDE.md", text)
        return text.encode("utf-8")
    if path == Path("scripts/product_behavior_eval.py"):
        return data.replace(b'SKILL / "SKILL.md"', b'SKILL / "GUIDE.md"')
    if path == Path("scripts/run_lifecycle_pilot.py"):
        return re.sub(rb'(skills/project-docs(?:-[a-z0-9-]+)?/)SKILL\.md', rb'\1GUIDE.md', data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when a bundle is missing or stale")
    args = parser.parse_args()
    paths = sources()
    for path in paths:
        validate_source(path)
    expected = {snapshot_path(path): path for path in paths}
    if len(expected) != len(paths):
        raise ValueError("snapshot paths collide")
    failed = False
    for name in NAMES:
        bundle = ROOT / "skills" / name / ".bundle"
        if args.check:
            entries = [p for p in bundle.rglob("*") if "__pycache__" not in p.relative_to(bundle).parts] if bundle.is_dir() else []
            links = (["."] if bundle.is_symlink() else []) + [str(p.relative_to(bundle)) for p in entries if p.is_symlink()]
            actual = {p.relative_to(bundle) for p in entries if p.is_file()}
            stale = sorted(str(path) for path in expected.keys() & actual
                           if snapshot_bytes(expected[path]) != (bundle / path).read_bytes()
                           or (ROOT / expected[path]).stat().st_mode & 0o111 != (bundle / path).stat().st_mode & 0o111)
            if actual != expected.keys() or stale or links:
                print(f"{name}: missing={len(expected.keys() - actual)} extra={len(actual - expected.keys())} stale={stale} symlinks={links}")
                failed = True
        else:
            temporary = Path(tempfile.mkdtemp(dir=bundle.parent, prefix=".npx-bundle-"))
            backup = temporary / "previous"
            try:
                staged = temporary / "staged"
                for target_path, path in expected.items():
                    target = staged / target_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(snapshot_bytes(path))
                    shutil.copystat(ROOT / path, target)
                if bundle.exists():
                    bundle.rename(backup)
                try:
                    staged.rename(bundle)
                except BaseException:
                    if backup.exists():
                        backup.rename(bundle)
                    raise
                if backup.exists():
                    shutil.rmtree(backup)
            finally:
                if not backup.exists():
                    shutil.rmtree(temporary)
            print(f"{name}: {len(paths)} files")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
