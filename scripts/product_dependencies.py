"""Inspect explicitly selected upstream skill directories without installing anything."""

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path


REQUIRED = {
    "brainstorming": (),
    "grilling": (),
    "domain-modeling": ("GLOSSARY-FORMAT.md", "ADR-FORMAT.md"),
}


def inspect_skill(directory, name, references):
    directory = directory.resolve()
    entry = directory / "SKILL.md"
    files, errors = {}, []
    for relative in ("SKILL.md", *references):
        path = directory / relative
        try:
            if not path.resolve().is_relative_to(directory):
                raise ValueError("reference escapes skill directory")
            data = path.read_bytes()
            text = data.decode("utf-8")
            if not text.strip():
                raise ValueError("empty file")
            files[relative] = hashlib.sha256(data).hexdigest()
            if relative == "SKILL.md":
                header = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.S)
                if not header or not re.search(rf"(?m)^name:\s*['\"]?{re.escape(name)}['\"]?\s*$", header[1]):
                    raise ValueError("skill name or frontmatter does not match")
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(f"{relative}: {error}")
    return {"path": str(entry), "problems": errors, "files": files,
            "contentFingerprint": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}


def diagnose_skill(roots, name, references):
    candidates = set()
    directory = Path(name)
    try:
        for root in roots:
            root = Path(root).expanduser()
            for directory in (root, root / name, root / "skills" / name):
                if directory.name != name:
                    continue
                try:
                    mode = (directory / "SKILL.md").stat().st_mode
                except (FileNotFoundError, NotADirectoryError):
                    continue
                if stat.S_ISREG(mode):
                    candidates.add(directory.resolve())
        observations = [inspect_skill(path, name, references) for path in sorted(candidates)]
    except (OSError, RuntimeError) as error:
        return {"name": name, "status": "incomplete", "versionState": "unknown", "contentFingerprint": None,
                "candidates": [{"path": str(directory), "problems": [str(error)], "files": {},
                                "contentFingerprint": None}]}
    valid = [item for item in observations if not item["problems"]]
    if not observations:
        status = "missing"
    elif len(valid) != len(observations):
        status = "incomplete"
    elif len({item["contentFingerprint"] for item in valid}) > 1:
        status = "ambiguous"
    else:
        status = "available"
    return {"name": name, "status": status, "versionState": "unknown",
            "contentFingerprint": valid[0]["contentFingerprint"] if status == "available" else None,
            "candidates": observations}


def diagnose(roots, pdlc_roots=()):
    dependencies = [diagnose_skill(roots, name, references) for name, references in REQUIRED.items()]
    pdlc = diagnose_skill(pdlc_roots, "pdlc-prd", ("assets/prd-template.md",))
    pdlc.update(compatibility="handoff_only" if pdlc["status"] == "available" else "unavailable",
                stateWrite="not_attempted")
    return {"ready": all(item["status"] == "available" for item in dependencies),
            "dependencies": dependencies, "pdlc": pdlc,
            "hostVisibility": "not_checked", "behaviorCheck": "not_run"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", action="append", type=Path, required=True,
                        help="explicit skill collection root or individual dependency directory; repeat as needed")
    parser.add_argument("--pdlc-root", action="append", type=Path, default=[],
                        help="optional explicitly selected PDLC directory; never affects product readiness")
    args = parser.parse_args()
    report = diagnose(args.skill_root, args.pdlc_root)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
