"""Validate a local coordination view; never authorize external actions.

作者：Jeff.Liu
"""
import argparse
from datetime import datetime, timezone
from glob import escape
from fractions import Fraction
import json
import os
import re
from pathlib import Path
import tempfile

STATES = ("not_started", "in_progress", "blocked", "pending_confirmation", "completed", "not_applicable", "cancelled")
ROUTES = ("development", "guidance", "permission", "configuration", "data")


def _observation_time(value):
    """Exact UTC seconds on an ordinal-day axis, including sub-microsecond precision."""
    parsed = datetime.fromisoformat(value)
    zone = re.search(r'(Z|[+-]\d{2}(?::?\d{2}){0,2}(?:[.,]\d+)?)$', value)
    if zone is None:
        raise ValueError('observation timestamp requires a timezone')
    fraction = Fraction(parsed.microsecond, 1_000_000)
    local_fraction = re.search(r'[.,](\d+)$', value[:zone.start()])
    if local_fraction and len(local_fraction[1]) > 6:
        digits = local_fraction[1]
        fraction += Fraction('0.' + digits) - Fraction(int(digits[:6]), 1_000_000)
    offset = Fraction(0)
    if zone[0] != 'Z':
        clock, *decimals = re.split(r'[.,]', zone[0][1:], maxsplit=1)
        clock = clock.replace(':', '').ljust(6, '0')
        offset = Fraction(int(clock[:2]) * 3600 + int(clock[2:4]) * 60 + int(clock[4:]))
        if decimals:
            offset += Fraction('0.' + decimals[0])
        if zone[0][0] == '-':
            offset = -offset
    return (parsed.toordinal() * 86400 + parsed.hour * 3600 + parsed.minute * 60 + parsed.second
            + fraction - offset)


def check_record(data):
    errors, review = [], {}
    now = datetime.now(timezone.utc)

    def error(message):
        errors.append(message)

    def text_fields(value, names, location):
        if not isinstance(value, dict):
            error(f"{location}: expected object")
            return False
        for name in names:
            if not isinstance(value.get(name), str) or not value[name].strip():
                error(f"{location}.{name}: expected nonempty string")
        return True

    def positive(value):
        return type(value) is int and value > 0

    def timestamp(value, location):
        try:
            parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
            if parsed is None or parsed.utcoffset() is None:
                raise ValueError()
            return parsed
        except ValueError:
            error(f"{location}: expected ISO timestamp with timezone")

    def items(value, location, nonempty=False):
        if not isinstance(value, list) or (nonempty and not value):
            error(f"{location}: expected {'nonempty ' if nonempty else ''}array")
            return []
        return value

    if not text_fields(data, ("project_ref", "subject_ref", "goal", "owner", "updated_at"), "record"):
        data = {}
    if type(data.get("schema_version")) is not int or data.get("schema_version") != 1:
        error("schema_version: supported version is 1")
    if not positive(data.get("revision")):
        error("revision: expected positive integer")
    timestamp(data.get("updated_at"), "updated_at")
    for action in items(data.get("next_actions"), "next_actions"):
        text_fields(action, ("action", "owner", "depends_on", "expected_result"), "next_action")
    for assertion in items(data.get("assertions"), "assertions"):
        if not text_fields(assertion, ("text", "source", "owner", "confirmation"), "assertion"):
            continue
        if assertion.get("classification") not in ("fact", "business_feedback", "hypothesis", "technical_unknown"):
            error("assertion.classification: unknown classification")
        if assertion.get("confirmation") not in ("unconfirmed", "confirmed", "conflicted"):
            error("assertion.confirmation: unknown confirmation")
        if assertion.get("confirmation") == "confirmed":
            text_fields(assertion, ("confirmed_by", "at", "applies_to"), "assertion")
            timestamp(assertion.get("at"), "assertion.at")

    branches, nodes = {}, {}
    for branch in items(data.get("branches"), "branches", True):
        if not text_fields(branch, ("id", "route"), "branch"):
            continue
        identity = branch.get("id")
        if not isinstance(identity, str):
            continue
        if identity in branches:
            error(f"duplicate branch: {identity}")
        branches[identity] = branch
        if branch.get("route") not in ROUTES:
            error(f"{identity}: unknown route")
        for identity_ref in items(branch.get("required"), f"{identity}.required", True):
            if not isinstance(identity_ref, str) or not identity_ref:
                error(f"{identity}: required reference must be a nonempty string")

    for node in items(data.get("artifacts"), "artifacts", True):
        if not text_fields(node, ("id", "kind", "stage", "branch", "owner", "source", "status"), "artifact"):
            continue
        identity = node.get("id")
        if not isinstance(identity, str):
            continue
        if identity in nodes:
            error(f"duplicate artifact: {identity}")
        nodes[identity] = node
        if not positive(node.get("version")):
            error(f"{identity}.version: expected positive integer")
        if node.get("stage") not in tuple(f"L{i}" for i in range(11)):
            error(f"{identity}: unknown stage")
        if node.get("status") not in STATES:
            error(f"{identity}: unknown status")
        if not isinstance(node.get("branch"), str) or node["branch"] not in branches:
            error(f"{identity}: missing branch")
        if node.get("status") in ("blocked", "pending_confirmation"):
            text_fields(node, ("reason", "recovery"), identity)
        if node.get("status") in ("cancelled", "not_applicable"):
            text_fields(node, ("reason",), identity)
        text_fields(node, tuple(key for key in ("build", "environment", "scope") if key in node), identity)
        valid_evidence = False
        for evidence in items(node.get("evidence"), f"{identity}.evidence"):
            if not text_fields(evidence, ("kind", "source", "actor", "at", "result"), f"{identity}.evidence"):
                continue
            timestamp(evidence.get("at"), f"{identity}.evidence.at")
            if evidence.get("kind") not in ("planned", "reported", "executed", "confirmed"):
                error(f"{identity}: unknown evidence kind")
            if evidence.get("result") not in ("passed", "failed", "blocked", "skipped", "unknown"):
                error(f"{identity}: unknown evidence result")
            subject = evidence.get("subject")
            if not isinstance(subject, dict) or not isinstance(subject.get("id"), str) or not positive(subject.get("version")):
                error(f"{identity}: invalid evidence subject")
            if (subject == {"id": identity, "version": node.get("version")}
                    and evidence.get("kind") in ("executed", "confirmed")
                    and evidence.get("result") == "passed"):
                valid_evidence = True
            if subject != {"id": identity, "version": node.get("version")}:
                review.setdefault(identity, []).append("evidence subject/version mismatch")
            for key in ("build", "environment", "scope"):
                if key in evidence:
                    text_fields(evidence, (key,), f"{identity}.evidence")
                if (key in node and evidence.get("kind") in ("executed", "confirmed")
                        and evidence.get(key) != node[key]):
                    review.setdefault(identity, []).append(f"evidence {key} mismatch")
            if "expires_at" in evidence:
                expiry = timestamp(evidence["expires_at"], f"{identity}.evidence.expires_at")
                if expiry is not None and expiry <= now:
                    review.setdefault(identity, []).append("evidence expired")
            # A contradictory/expired receipt cannot be hidden by adding a passing one.
            pending_plan = evidence.get("kind") == "planned" and evidence.get("result") == "unknown"
            if (evidence.get("result") != "passed" and not pending_plan) or evidence.get("validity", "current") != "current":
                review.setdefault(identity, []).append("evidence not current/passed")
        if node.get("status") == "completed" and not valid_evidence:
            review.setdefault(identity, []).append("completion lacks current executed/confirmed evidence")

    dependencies = {}
    for identity, node in nodes.items():
        dependencies[identity] = []
        for ref in items(node.get("depends_on"), f"{identity}.depends_on"):
            if not isinstance(ref, dict) or not isinstance(ref.get("id"), str) or not positive(ref.get("version")):
                error(f"{identity}: invalid dependency reference")
                continue
            target = nodes.get(ref["id"])
            if target is None:
                error(f"{identity}: missing dependency {ref['id']}")
                continue
            dependencies[identity].append(ref["id"])
            if target.get("version") != ref["version"]:
                review.setdefault(identity, []).append(f"dependency version changed: {ref['id']}")
            if node.get("status") == "completed" and target.get("status") != "completed":
                review.setdefault(identity, []).append(f"dependency incomplete: {ref['id']}")
    # Iterative topological walk avoids recursion limits on long handoff chains.
    pending = set(nodes)
    while pending:
        ready = {identity for identity in pending if not pending.intersection(dependencies[identity])}
        if not ready:
            error("dependency cycle")
            break
        for identity in sorted(ready):
            if any(target in review for target in dependencies[identity]):
                review.setdefault(identity, []).append("upstream needs review")
        pending -= ready
    statuses = {}
    for identity, branch in branches.items():
        required = branch.get("required")
        if not isinstance(required, list):
            continue
        selected = []
        for ref in required:
            if not isinstance(ref, str) or ref not in nodes:
                error(f"{identity}: missing required artifact {ref}")
                continue
            if nodes[ref].get("branch") != identity:
                error(f"{identity}: required artifact belongs to another branch: {ref}")
            selected.append(ref)
        # Unlisted unfinished artifacts cannot be hidden to claim branch completion.
        selected = sorted(set(selected) | {key for key, node in nodes.items() if node.get("branch") == identity})
        statuses[identity] = ("needs_review" if any(key in review for key in selected) else
                              "recorded" if selected and all(nodes[key].get("status") == "completed" for key in selected)
                              else "closed" if selected and all(nodes[key].get("status") in ("completed", "cancelled", "not_applicable") for key in selected)
                              else "incomplete")
    return {"valid": not errors, "errors": errors,
            "needs_review": [{"id": key, "reasons": value} for key, value in sorted(review.items())],
            "branches": statuses, "verification": "local_consistency_only"}


def update_record(path, candidate, expected_revision):
    """Single local writer, CAS revision, exclusive lock, immutable previous snapshot."""
    path = Path(path).resolve(strict=True)
    lock = path.with_name(path.name + ".lock")
    # Never remove another writer's lock when exclusive acquisition fails.
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    temporary = None
    try:
        os.close(descriptor)
        current_bytes = path.read_bytes()
        current = json.loads(current_bytes)
        if not check_record(current)["valid"] or not check_record(candidate)["valid"]:
            raise ValueError("invalid current or candidate record")
        if type(expected_revision) is not int or current["revision"] != expected_revision:
            raise ValueError("record revision conflict")
        if candidate["revision"] != expected_revision + 1:
            raise ValueError("candidate revision must increment by one")
        if any(candidate[key] != current[key] for key in ("project_ref", "subject_ref")):
            raise ValueError("project/subject identity cannot change")
        for collection in ("branches", "artifacts"):
            previous_ids = {item["id"] for item in current[collection]}
            candidate_ids = {item["id"] for item in candidate[collection]}
            if not previous_ids <= candidate_ids:
                raise ValueError(f"cannot remove {collection}; retain cancelled/not_applicable records with reasons")
        previous = {node["id"]: node for node in current["artifacts"]}
        predecessors = [current]
        prefix = path.name + '.rev-'
        for snapshot in path.parent.glob(escape(prefix) + '*.json'):
            number = snapshot.name[len(prefix):-5]
            if not number.isdecimal() or not 0 < int(number) < current['revision']:
                continue
            historical = json.loads(snapshot.read_text())
            if (not check_record(historical)['valid'] or historical['revision'] != int(number)
                    or any(historical[key] != current[key] for key in ('project_ref', 'subject_ref'))):
                raise ValueError(f'invalid historical record: {snapshot.name}')
            predecessors.append(historical)
        known_evidence = {}
        for predecessor in predecessors:
            for node in predecessor['artifacts']:
                known_evidence.setdefault(node['id'], []).extend(node['evidence'])
        for node in candidate["artifacts"]:
            old = previous.get(node["id"])
            if old:
                if node['version'] == old['version'] and any(e not in node['evidence'] for e in old['evidence']):
                    raise ValueError(f"same-version evidence cannot be rewritten or removed: {node['id']}")
            for evidence in node['evidence']:
                for prior in known_evidence.get(node['id'], []):
                    if (all(evidence[key] == prior[key] for key in ('kind', 'source', 'actor'))
                            and _observation_time(evidence['at']) == _observation_time(prior['at'])
                            and evidence != prior):
                        raise ValueError(f"existing observation cannot be rewritten or rebound: {node['id']}")
            observations = ("status", "evidence", "owner", "reason", "recovery")
            content = {key: value for key, value in node.items() if key not in observations}
            old_content = {key: value for key, value in (old or {}).items() if key not in observations}
            if old and (node["version"] < old["version"] or
                        (content != old_content and node["version"] == old["version"])):
                raise ValueError(f"changed artifact requires a newer version: {node['id']}")
        history = path.with_name(f"{path.name}.rev-{expected_revision}.json")
        if history.exists():
            if history.read_bytes() != current_bytes:
                raise ValueError("history conflicts with current revision")
        else:
            with os.fdopen(os.open(history, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as output:
                output.write(current_bytes)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(candidate, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--candidate", type=Path, help="replace an existing record under an exclusive local lock")
    args = parser.parse_args()
    try:
        if args.candidate:
            if args.expected_revision is None:
                raise ValueError("--candidate requires --expected-revision")
            update_record(args.record, json.loads(args.candidate.read_text(encoding="utf-8")), args.expected_revision)
        data = json.loads(args.record.read_text(encoding="utf-8"))
        if not args.candidate and args.expected_revision is not None and data.get("revision") != args.expected_revision:
            raise ValueError("record revision conflict")
        result = check_record(data)
        result["updated"] = bool(args.candidate)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["valid"] and not result["needs_review"] else 1
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(json.dumps({"valid": False, "errors": [str(error)], "verification": "local_consistency_only"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
