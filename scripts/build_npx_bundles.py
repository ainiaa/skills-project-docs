#!/usr/bin/env python3
"""Build and check self-contained copies for the skills CLI."""

import argparse
import posixpath
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("project-docs", "project-docs-api", "project-docs-diagram",
         "project-docs-lifecycle", "project-docs-overview", "project-docs-product", "project-docs-engineering")
REPO_DOCS = "https://github.com/ainiaa/skills-project-docs/blob/main/"
RUNTIME_DOCS = {
    "ARCHITECTURE_TEMPLATE_RESEARCH.md", "DIAGRAM_STANDARD.md", "RENDERER_CAPABILITY_AUDIT.md",
    "engineering-ownership.md",
}
REPOSITORY_SCRIPTS = {
    "build_npx_bundles.py", "product_behavior_eval.py", "run_lifecycle_pilot.py", "update_project_docs.py",
}
PRODUCT_JOURNEY = Path("skills/project-docs-product/assets/examples/access-request")
PRODUCT_JOURNEY_FILES = {"input.md", "journey.test.mjs", "prd.md", "prototype.html", "review.md"}
REPOSITORY_GUIDES = {
    Path("skills/project-docs-lifecycle/references/validation.md"),
    Path("skills/project-docs-product/references/evaluation.md"),
}


def script_paths(*names):
    return {f"scripts/{name}" for name in names}


COMMON = {"LICENSE", "references/audience.md"}
DISCOVERY = script_paths("discovery.py", "python_runtime.py", "tree_sitter_engine.py", "queries")
DIAGRAM_RUNTIME = DISCOVERY | script_paths(
    "architecture_candidates.py", "architecture_ir.py", "architecture_landscape.py", "architecture_renderers.py",
    "codegraph_context.py", "diagram_profiles.py", "drawio_quality.py", "engine_paths.py", "export_archify.mjs",
    "generate_architecture.py", "install_renderers.py", "lifecycle_record.py", "render_native_diagram.py",
) | {"skills/project-docs-diagram/references"}
DIAGRAM = DIAGRAM_RUNTIME | {
    "docs/ARCHITECTURE_TEMPLATE_RESEARCH.md", "docs/DIAGRAM_STANDARD.md", "docs/RENDERER_CAPABILITY_AUDIT.md",
    "skills/project-docs-diagram/SKILL.md",
}
CHECKPOINT = script_paths(
    "lifecycle_checklist.py", "lifecycle_quality.py", "lifecycle_record.py", "lifecycle_test_runner.py",
    "product_inputs.py", "requirements-product.txt", "validate_product_doc.py",
) | {
    "skills/project-docs-lifecycle/references/checklist-catalog.json",
    "skills/project-docs-lifecycle/references/quality-and-trace.md",
}
HANDOFF = CHECKPOINT | script_paths("product_handoff.py", "product_revision.py", "provider_test_evidence.py") | {
    "skills/project-docs-lifecycle/references/engineering-evidence.md",
    "skills/project-docs-product/references/engineering.md",
    "skills/project-docs-product/references/iterations.md",
    "skills/project-docs-product/references/revision.md",
}
SPECIALISTS = {
    "project-docs-api": DISCOVERY | script_paths(
        "ApiSaviorAstScanner.java", "api_document_ir.py", "api_document_renderers.py", "generate_api_docs.py",
        "java_spring_adapter.py", "python_fastapi_adapter.py",
    ) | {"references/api-document-ir.md", "skills/project-docs-api"},
    "project-docs-diagram": DIAGRAM,
    "project-docs-overview": DIAGRAM | script_paths("project_doc_context.py", "project_doc_impact.py", "validate_project_doc.py") | {
        "docs/engineering-ownership.md", "references/third-party-notices.md", "skills/project-docs-overview",
        "skills/project-docs-product/references/pdlc.md",
    },
    "project-docs-product": HANDOFF | DIAGRAM_RUNTIME | script_paths(
        "install_product_dependencies.py", "product_browser.mjs", "product_bundle.py", "product_dependencies.py",
        "project_doc_context.py",
    ) | {"references/third-party-notices.md", "skills/project-docs-product"},
    "project-docs-engineering": HANDOFF | script_paths("lifecycle_relations.py") | {
        "docs/engineering-ownership.md", "references/third-party-notices.md", "skills/project-docs-engineering",
        "skills/project-docs-lifecycle/references/coordination.md", "skills/project-docs-product/references/ui-design.md",
    },
}
LIFECYCLE_FILES = {"skills/project-docs-lifecycle"}
BUNDLE_CONTENTS = {
    **SPECIALISTS,
    "project-docs-lifecycle": LIFECYCLE_FILES.union(
        SPECIALISTS["project-docs-product"], SPECIALISTS["project-docs-engineering"], SPECIALISTS["project-docs-diagram"],
    ),
    "project-docs": LIFECYCLE_FILES.union({"skills/project-docs"}, *SPECIALISTS.values()),
}


def runtime_source(path):
    parts = path.parts
    if parts[0] == "docs":
        return len(parts) == 2 and path.name in RUNTIME_DOCS
    if parts[0] == "scripts":
        if parts[1:2] == ("queries",):
            return path.suffix == ".scm"
        return len(parts) == 2 and not path.name.startswith("test_") and path.name not in REPOSITORY_SCRIPTS
    if parts[0] == "skills":
        if parts[2:4] == ("assets", "examples"):
            return path.parent == PRODUCT_JOURNEY and path.name in PRODUCT_JOURNEY_FILES
        return (parts[2:3] not in {("agents",), (".bundle",)}
                and path not in REPOSITORY_GUIDES
                and parts[2:4] != ("assets", "beginner-explainers"))
    return parts[0] == "references" or path == Path("LICENSE")


def repository_sources():
    output = subprocess.check_output(["git", "ls-files", "-z", "--", "skills", "scripts",
                                      "references", "docs", "audits", "LICENSE"], cwd=ROOT)
    return {Path(path) for path in output.decode().split("\0") if path and "/.bundle/" not in path}


def sources():
    return sorted(path for path in repository_sources() if runtime_source(path))


def bundle_sources(name, paths):
    declared = {Path(path) for path in COMMON | BUNDLE_CONTENTS[name]}
    return [path for path in paths
            if (path in declared or declared.intersection(path.parents))
            and (path.parent != PRODUCT_JOURNEY or name == "project-docs-product")]


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


def snapshot_link(path, match, repository, selected):
    link, separator, anchor = match.group(1).partition("#")
    published = link.startswith(REPO_DOCS)
    if published:
        target = Path(unquote(link.removeprefix(REPO_DOCS)))
    elif not link or link.startswith("/") or re.match(r"^[\w+.-]+:", link):
        return match.group()
    else:
        target = Path(posixpath.normpath(posixpath.join(path.parent.as_posix(), unquote(link))))
    entry = target.with_name("SKILL.md") if target.name == "GUIDE.md" else target
    if target.name == "GUIDE.md" and snapshot_path(entry) == target:
        target = entry
    suffix = separator + anchor
    if target in selected:
        if published or snapshot_path(target) != target:
            relative = posixpath.relpath(snapshot_path(target), path.parent)
            return f"]({quote(relative)}{suffix})"
    elif not published and target in repository:
        return f"]({REPO_DOCS}{quote(target.as_posix())}{suffix})"
    return match.group()


def snapshot_bytes(path, repository, selected):
    data = (ROOT / path).read_bytes()
    if path.suffix == ".md":
        text = data.decode("utf-8")
        if snapshot_path(path) != path:
            text = text.replace("](.bundle/references/", "](../../references/")
            text = text.replace("](.bundle/docs/", "](../../docs/")
            text = re.sub(r"\]\(\.bundle/skills/(project-docs(?:-[a-z0-9-]+)?)/", r"](../\1/", text)
        text = re.sub(r"\]\(([^)\s]+)\)", lambda match: snapshot_link(path, match, repository, selected), text)
        return text.encode("utf-8")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when a bundle is missing or stale")
    args = parser.parse_args()
    if __package__:
        from .lifecycle_checklist import load_catalog
    else:
        from lifecycle_checklist import load_catalog
    load_catalog(verify_sources=True)
    paths = sources()
    for path in paths:
        validate_source(path)
    repository = repository_sources() if any(path.suffix == ".md" for path in paths) else set()
    failed = False
    for name in NAMES:
        selected = set(bundle_sources(name, paths))
        expected = {snapshot_path(path): path for path in selected}
        if len(expected) != len(selected):
            raise ValueError("snapshot paths collide")
        bundle = ROOT / "skills" / name / ".bundle"
        if args.check:
            entries = [p for p in bundle.rglob("*") if "__pycache__" not in p.relative_to(bundle).parts] if bundle.is_dir() else []
            links = (["."] if bundle.is_symlink() else []) + [str(p.relative_to(bundle)) for p in entries if p.is_symlink()]
            actual = {p.relative_to(bundle) for p in entries if p.is_file()}
            stale = sorted(str(path) for path in expected.keys() & actual
                           if snapshot_bytes(expected[path], repository, selected) != (bundle / path).read_bytes()
                           or (ROOT / expected[path]).stat().st_mode & 0o111 != (bundle / path).stat().st_mode & 0o111)
            if actual != expected.keys() or stale or links:
                print(f"{name}: missing={len(expected.keys() - actual)} extra={len(actual - expected.keys())} stale={stale} symlinks={links}")
                failed = True
        else:
            temporary = Path(tempfile.mkdtemp(dir=bundle.parent, prefix=".npx-bundle-"))
            backup = temporary / "previous"
            try:
                staged = temporary / "staged"
                for target_path, path in sorted(expected.items()):
                    target = staged / target_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(snapshot_bytes(path, repository, selected))
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
            print(f"{name}: {len(selected)} files")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
