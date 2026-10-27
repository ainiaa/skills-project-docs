"""Install missing required Product skills; reuse existing skills without updating them."""

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path, PurePosixPath

from product_dependencies import REQUIRED, diagnose_skill, inspect_skill


# Reviewed upstream commits; changing these affects missing skills only.
SOURCES = {
    "brainstorming": {"url": "https://github.com/obra/superpowers.git",
                      "revision": "2ce8aa15d05bd57213e6f746f953aafb7ded7a8b", "path": "skills/brainstorming"},
    "grilling": {"url": "https://github.com/mattpocock/skills.git",
                 "revision": "5beb35b040e3de97e54fa9e386d7e42d15c295c2", "path": "skills/productivity/grilling"},
    "domain-modeling": {"url": "https://github.com/mattpocock/skills.git",
                        "revision": "5beb35b040e3de97e54fa9e386d7e42d15c295c2", "path": "skills/engineering/domain-modeling"},
}


def visible_roots(target):
    """Inspect known user-scope roots only, never arbitrary plugin caches."""
    roots = [target]
    home = Path.home()
    codex = Path(os.environ.get("CODEX_HOME", home / ".codex"))
    claude = Path(os.environ.get("CLAUDE_HOME", home / ".claude"))
    if target.absolute() == (codex / "skills").absolute():
        roots.append(home / ".agents/skills")
        config = codex / "config.toml"
        if config.is_file():
            plugins = tomllib.loads(config.read_text()).get("plugins", {})
            if not isinstance(plugins, dict):
                raise RuntimeError(f"invalid plugin configuration: {config}")
            for identity, settings in plugins.items():
                if not isinstance(settings, dict):
                    raise RuntimeError(f"invalid plugin configuration: {identity}")
                name, separator, market = identity.partition("@")
                if separator and settings.get("enabled") is True and re.fullmatch(r"[\w.-]+", name) and re.fullmatch(r"[\w.-]+", market):
                    roots.extend(sorted((codex / "plugins/cache" / market / name).glob("*/skills")))
    if target.absolute() == (claude / "skills").absolute():
        settings = claude / "settings.json"
        registry = claude / "plugins/installed_plugins.json"
        if settings.is_file() and registry.is_file():
            enabled = json.loads(settings.read_text()).get("enabledPlugins", {})
            installed = json.loads(registry.read_text()).get("plugins", {})
            if not isinstance(enabled, dict) or not isinstance(installed, dict):
                raise RuntimeError("invalid Claude plugin configuration")
            for identity, entries in installed.items():
                if enabled.get(identity) is True:
                    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
                        raise RuntimeError(f"invalid Claude plugin registration: {identity}")
                    for entry in entries:
                        if entry.get("scope") == "user" and entry.get("installPath"):
                            roots.append(Path(entry["installPath"]) / "skills")
    return roots


def preflight(targets):
    plan = []
    for target in dict.fromkeys(Path(p).expanduser().absolute() for p in targets):
        ancestor = target
        while not os.path.lexists(ancestor):
            ancestor = ancestor.parent
        if not ancestor.is_dir():
            raise RuntimeError(f"not a usable skill directory: {ancestor}")
        roots = visible_roots(target)
        for name, references in REQUIRED.items():
            # A reserved name without a readable entry is a conflict, not an empty slot.
            for root in roots:
                candidate = root / name
                if os.path.lexists(candidate) and not (candidate / "SKILL.md").is_file():
                    raise RuntimeError(f"incomplete dependency; refusing to replace {candidate}")
            item = diagnose_skill(roots, name, references)
            if item["status"] not in ("available", "missing"):
                raise RuntimeError(f"{name}: {item['status']}; resolve existing entries: {item['candidates']}")
            plan.append({"target": str(target / name), "name": name,
                         "physicalTarget": str(target.resolve() / name),
                         "status": "reused" if item["status"] == "available" else "missing",
                         "versionState": "unknown",
                         "candidates": item["candidates"]})
    # Shared directory aliases do not share each host's private search roots.
    groups = {}
    for item in plan:
        groups.setdefault(item["physicalTarget"], []).append(item)
    for items in groups.values():
        missing = [item for item in items if item["status"] == "missing"]
        candidates = [candidate for item in items if item["status"] == "reused" for candidate in item["candidates"]]
        if missing and candidates:
            if len({candidate["contentFingerprint"] for candidate in candidates}) != 1:
                raise RuntimeError("ambiguous existing dependency for shared skill directory")
            for item in missing:
                item["reuseSource"] = str(Path(candidates[0]["path"]).parent)
    return plan


def git(directory, *args, binary=False):
    result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True,
                            text=not binary, timeout=90,
                            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if result.returncode:
        detail = result.stderr.decode(errors="replace") if binary else result.stderr
        raise RuntimeError(f"upstream Git operation failed: {detail.strip()}")
    return result.stdout if binary else result.stdout.strip()


def fetch_repository(url, revision, destination):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("upstream revision must be a full commit SHA")
    destination.mkdir()
    git(destination, "init", "--quiet")
    git(destination, "fetch", "--quiet", "--depth", "1", "--no-tags", url, revision)
    if git(destination, "rev-parse", "FETCH_HEAD") != revision:
        raise RuntimeError("upstream revision does not match the pinned commit")
    return destination


def stage_skill(repository, specification, name, destination):
    prefix = specification["path"] + "/"
    data = git(repository, "archive", "--format=tar", specification["revision"], specification["path"], "LICENSE", binary=True)
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive:
            if member.name == "LICENSE":
                relative = PurePosixPath("UPSTREAM-LICENSE")
            elif member.name.startswith(prefix):
                relative = PurePosixPath(member.name[len(prefix):])
            else:
                continue
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError("upstream resource escapes skill directory")
            output = destination / relative
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                if member.size > 8 * 1024 * 1024:
                    raise RuntimeError("upstream resource is too large")
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as stream, output.open("xb") as writer:
                    shutil.copyfileobj(stream, writer)
                output.chmod(0o755 if member.mode & 0o111 else 0o644)
            else:
                raise RuntimeError("upstream skill must contain regular files, not links")
    observed = inspect_skill(destination, name, REQUIRED[name])
    if observed["problems"]:
        raise RuntimeError(f"invalid upstream {name}: {observed['problems']}")
    (destination / ".project-docs-source.json").write_text(json.dumps(specification, indent=2) + "\n")


def synchronize(targets, *, check=False, sources=None):
    plan = preflight(targets)
    report = {"ready": all(item["status"] == "reused" for item in plan), "dependencies": plan,
              "hostVisibility": "not_checked", "behaviorCheck": "not_run"}
    if check:
        return report
    sources = SOURCES if sources is None else sources
    missing = [item for item in plan if item["status"] == "missing"]
    if not missing:
        return report
    created, backings, published = [], [], {}
    with tempfile.TemporaryDirectory(prefix="product-upstreams-") as temporary:
        temporary = Path(temporary)
        repositories, staged = {}, {}
        for name in dict.fromkeys(item["name"] for item in missing if "reuseSource" not in item):
            spec = sources[name]
            key = (spec["url"], spec["revision"])
            if key not in repositories:
                repositories[key] = fetch_repository(*key, temporary / f"repo-{len(repositories)}")
            staged[name] = temporary / name
            stage_skill(repositories[key], spec, name, staged[name])
        try:
            for item in missing:
                if item["physicalTarget"] in published:
                    item.update(published[item["physicalTarget"]])
                    continue
                target = Path(item["target"])
                target.parent.mkdir(parents=True, exist_ok=True)
                backing = None
                if "reuseSource" in item:
                    source = Path(item["reuseSource"])
                    result = {"status": "reused", "linkedFrom": str(source)}
                else:
                    store = target.parent.resolve().parent / ".project-docs-upstreams"
                    if os.path.lexists(store) and (store.is_symlink() or not store.is_dir()):
                        raise RuntimeError(f"refusing unsafe upstream storage: {store}")
                    store.mkdir(exist_ok=True)
                    backing = Path(tempfile.mkdtemp(prefix=item["name"] + "-", dir=store))
                    backings.append(backing)
                    source = backing / "skill"
                    shutil.copytree(staged[item["name"]], source)
                    observed = inspect_skill(source, item["name"], REQUIRED[item["name"]])
                    if observed["problems"]:
                        raise RuntimeError(f"invalid staged dependency: {observed['problems']}")
                    result = {"status": "installed", "versionState": "pinned", "source": sources[item["name"]]}
                # Publish only a complete skill. symlink creation never replaces an existing name.
                target.symlink_to(source, target_is_directory=True)
                created.append((target, target.lstat().st_ino, backing))
                item.update(result)
                published[item["physicalTarget"]] = result
        except (OSError, RuntimeError):
            protected = set()
            for target, inode, backing in reversed(created):
                if target.is_symlink() and target.lstat().st_ino == inode:
                    target.unlink()
                elif backing is not None:
                    protected.add(backing)
            for backing in backings:
                if backing not in protected:
                    shutil.rmtree(backing)
            raise
    report["ready"] = True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", action="append", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="diagnose without downloads or writes")
    mode.add_argument("--preflight", action="store_true", help="reject conflicts before any installation; missing entries are allowed")
    args = parser.parse_args(argv)
    try:
        report = synchronize(args.skill_root, check=args.check or args.preflight)
    except (OSError, RuntimeError, ValueError, tarfile.TarError, subprocess.SubprocessError) as error:
        print(json.dumps({"ready": False, "error": str(error)}), file=sys.stderr)
        return 1
    if not args.preflight:
        print("Product required upstream skills: " + json.dumps(report, ensure_ascii=False))
    return 0 if report["ready"] or args.preflight else 1


if __name__ == "__main__":
    raise SystemExit(main())
