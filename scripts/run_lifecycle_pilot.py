"""Replay the authored synthetic repair pilot with durable local execution evidence.

This runs the technical rehearsal, not a new model Skill invocation. 作者：Jeff.Liu
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from lifecycle_record import check_record, update_record

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "skills/project-docs-lifecycle/assets/examples/repair-tracker"

# All seven AC cases are mandatory in this frozen example.
BUSINESS_TEST_RUNNER = """import json, sys, unittest
result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('.', pattern='test_app.py'))
summary = {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
           'skipped': len(result.skipped), 'expected_failures': len(result.expectedFailures),
           'unexpected_successes': len(result.unexpectedSuccesses)}
print(json.dumps(summary))
sys.exit(0 if result.wasSuccessful() and result.testsRun >= 7 and not result.skipped and not result.expectedFailures else 1)
"""


def stamp():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def command(argv, cwd, receipt, success=True):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=30,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    write_json(receipt, {"argv": argv, "cwd": str(cwd), "at": stamp(), "exit_code": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
    if (result.returncode == 0) != success:
        raise RuntimeError(f"command failed expectation; inspect {receipt}")
    return result


def serve_checks(package, output, phase, build, unavailable=False):
    port_file = output / f"release/{phase}-port.json"
    log_file = output / f"release/{phase}-server.log"
    argv = [sys.executable, str(package / "app.py"), "--port-file", str(port_file)]
    if unavailable:
        argv.append("--unavailable")
    checks = []
    completed = False
    with log_file.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(argv, cwd=package, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    address = json.loads(port_file.read_text())
                    break
                except (FileNotFoundError, json.JSONDecodeError):
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError(f"server did not start: {log_file}")
                    time.sleep(0.02)
            if address["host"] != "127.0.0.1" or address["build"] != build:
                raise RuntimeError("wrong host or deployed build")
            base = f"http://127.0.0.1:{address['port']}"
            cases = [("health", "/health", None, 503 if unavailable else 200,
                      {"available": not unavailable, "build": build}),
                     ("AC-06" if unavailable else "AC-01", "/repairs/R-100", "alice", 503 if unavailable else 200,
                      {"error": "source_unavailable"} if unavailable else
                      {"id": "R-100", "device": "laptop", "status": "repairing", "next_action": "等待维修完成"})]
            if not unavailable:
                cases.extend([
                    ("AC-02", "/repairs/R-100", None, 401, {"error": "unauthorized"}),
                    ("AC-03", "/repairs/R-100", "bob", 403, {"error": "forbidden"}),
                    ("AC-03-spoof", "/repairs/R-100?owner=alice", "bob", 403, {"error": "forbidden"}),
                    ("AC-04", "/repairs/R-999", "alice", 404, {"error": "not_found"}),
                    ("AC-05", "/repairs/R-10", "alice", 400, {"error": "invalid_id"}),
                    ("AC-07", "/repairs/R-100", "alice", 200,
                     {"id": "R-100", "device": "laptop", "status": "repairing", "next_action": "等待维修完成"}),
                ])
            opener = build_opener(ProxyHandler({}))
            for name, path, actor, expected_status, expected_body in cases:
                headers = {"Authorization": f"Bearer demo-{actor}"} if actor else {}
                request = Request(base + path, headers=headers)
                try:
                    response = opener.open(request, timeout=3)
                except HTTPError as error:
                    response = error
                with response:
                    status, body = response.code, json.loads(response.read())
                checks.append({"case": name, "path": path, "actor": actor, "at": stamp(), "status": status,
                               "body": body, "expected_status": expected_status, "expected_body": expected_body,
                               "passed": status == expected_status and body == expected_body})
                if not checks[-1]["passed"]:
                    raise RuntimeError(f"HTTP acceptance failed: {phase}/{name}")
            completed = True
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            write_json(output / f"release/{phase}.json", {"argv": argv, "at": stamp(), "build": build,
                       "environment": "isolated-loopback", "scope": "synthetic-repair", "checks": checks,
                       "process_stopped": process.poll() is not None, "pid": process.pid,
                       "status": "passed" if completed else "failed"})


def initial_record(build):
    descriptions = [
        ("intake", "L0", "source/problem-intake.md", [], "business-simulation"),
        ("investigation", "L1", "source/investigation.md", ["intake"], "business-simulation"),
        ("decision", "L2", "source/decision.md", ["investigation"], "business-simulation"),
        ("requirement", "L3", "source/prd.md", ["decision"], "isolated-release"),
        ("design", "L4", "source/design.md", ["requirement"], "isolated-release"),
        ("build", "L5", "release/build.json", ["design"], "isolated-release"),
        ("tests", "L6", "validation/unit-green.json", ["build"], "isolated-release"),
        ("uat", "L7", "validation/uat-simulated.json", ["tests"], "business-simulation"),
        ("authorization", "L8", "release/authorization.md", ["tests", "uat"], "isolated-release"),
        ("deployment", "L9", "release/healthy.json", ["authorization"], "isolated-release"),
        ("failure-drill", "L9", "release/outage.json", ["deployment"], "isolated-release"),
        ("recovery", "L9", "release/recovered.json", ["failure-drill", "build"], "isolated-release"),
        ("effects", "L10", "handover.md", ["recovery"], "effects"),
    ]
    nodes = []
    for identity, stage, source, dependencies, branch in descriptions:
        node = {"id": identity, "kind": identity, "stage": stage, "branch": branch, "version": 1,
                "source": source, "owner": "simulation-coordinator", "status": "not_started",
                "depends_on": [{"id": item, "version": 1} for item in dependencies], "evidence": []}
        if identity in ("build", "tests", "authorization", "deployment", "failure-drill", "recovery"):
            node.update(build=build, environment="isolated-loopback", scope="synthetic-repair")
        nodes.append(node)
    return {"schema_version": 1, "revision": 1, "project_ref": "SIM-REPAIR-PROJECT", "subject_ref": "SIM-REPAIR-001",
            "goal": "完成维修查询的模拟业务到真实隔离HTTP发布及恢复", "owner": "simulation-coordinator", "updated_at": stamp(),
            "provenance": {"pre_prd": "supplemented after the original pilot from unchanged simulated input; no new interviews or retrospective approvals"},
            "assertions": [{"text": "业务资料和业务确认均为模拟，不是实际公司批准", "classification": "hypothesis",
                            "source": "source/input.md", "owner": "simulation-coordinator", "confirmation": "unconfirmed"}],
            "branches": [{"id": branch, "route": "development", "required": [n["id"] for n in nodes if n["branch"] == branch]}
                         for branch in ("business-simulation", "isolated-release", "effects")], "artifacts": nodes,
            "next_actions": [{"action": "真实试点另取得身份/数据接入、业务批准与效果观察依据", "owner": "unassigned",
                              "depends_on": "actual-business-environment", "expected_result": "完成真实UAT及效果验证"}]}


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    source.mkdir()
    for path in EXAMPLE.iterdir():
        if path.is_file():
            shutil.copy2(path, source / path.name)
    for folder in ("validation", "release", "scenarios", "provenance"):
        (output / folder).mkdir()
    identity_paths = [ROOT / "skills/project-docs-lifecycle/SKILL.md",
                      *sorted((ROOT / "skills/project-docs-lifecycle/references").glob("*.md")),
                      ROOT / "skills/project-docs-product/SKILL.md", Path(__file__), ROOT / "scripts/lifecycle_record.py"]
    write_json(output / "provenance/skill-identity.json", {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in identity_paths})
    build = hashlib.sha256((source / "app.py").read_bytes()).hexdigest()
    record = initial_record(build)
    for node in record["artifacts"]:
        if node["stage"] in ("L0", "L1", "L2"):
            artifact = output / node["source"]
            if not artifact.is_file() or not artifact.stat().st_size:
                raise RuntimeError(f"missing pre-PRD phase output: {node['source']}")
    write_json(output / "lifecycle-record.json", record)
    baseline = output / "validation/before-implementation"
    baseline.mkdir()
    shutil.copy2(source / "test_app.py", baseline / "test_app.py")
    command([sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_app.py"], baseline,
            output / "validation/red-replay.json", success=False)
    prd = command([sys.executable, str(ROOT / "scripts/validate_product_doc.py"), "--file", str(source / "prd.md")],
                  output, output / "validation/prd-check.json")
    if not json.loads(prd.stdout)["valid"]:
        raise RuntimeError("PRD structure invalid")
    command([sys.executable, "-c", BUSINESS_TEST_RUNNER], source, output / "validation/unit-green.json")
    write_json(output / "validation/uat-simulated.json", {
        "at": stamp(), "actor": "SIMULATED-business-role", "result": "simulated_accepted",
        "basis": "validation/unit-green.json", "criteria": [f"AC-{i:02}" for i in range(1, 8)],
        "build": build, "scope": "synthetic-repair", "real_business_approval": False})
    package = output / "release" / build
    package.mkdir()
    shutil.copy2(source / "app.py", package / "app.py")
    if hashlib.sha256((package / "app.py").read_bytes()).hexdigest() != build:
        raise RuntimeError("deployed bytes differ from tested source")
    write_json(output / "release/build.json", {"build": build, "source": "source/app.py", "package": f"release/{build}/app.py", "at": stamp()})
    (output / "release/authorization.md").write_text("# 隔离授权范围\n\n本轮用户原始请求：“用一个完整的模拟业务案例实际跑一遍这个 Skill，验证从业务痛点到需求、开发、测试和隔离环境上线的全链路，有问题直接修复并补齐测试。”\n\n仅执行本机回环地址上的合成服务。真实业务UAT和发布批准均未取得，不发布生产。\n", encoding="utf-8")
    serve_checks(package, output, "healthy", build)
    serve_checks(package, output, "outage", build, unavailable=True)
    serve_checks(package, output, "recovered", build)
    (output / "handover.md").write_text("# 交接与效果\n\n业务效果待观察，无真实员工或收益数据。真实试点先定义询问次数口径、基线、观察期和负责人。隔离HTTP服务均已停止；保留app.py、test_app.py和完整回执，后续可从同一需求身份接续。真实身份和数据源接入未实现。\n", encoding="utf-8")
    final = copy.deepcopy(record)
    final.update(revision=2, updated_at=stamp())
    for node in final["artifacts"]:
        if node["id"] == "effects":
            node["status"] = "in_progress"
            continue
        simulated = node["id"] in ("intake", "investigation", "decision", "uat")
        receipt_source = {"requirement": "validation/prd-check.json", "design": "source/review.md"}.get(node["id"], node["source"])
        node.update(status="completed", evidence=[{"kind": "confirmed" if simulated else "executed",
                    "source": receipt_source, "actor": "SIMULATED-business-role" if simulated else "current-session-local-runner",
                    "at": stamp(), "result": "passed", "subject": {"id": node["id"], "version": node["version"]},
                    "method": "simulated role replay" if simulated else "see linked authored artifact or actual execution receipt",
                    **{key: node[key] for key in ("build", "environment", "scope") if key in node}}])
    update_record(output / "lifecycle-record.json", final, 1)
    checked = check_record(final)
    if not checked["valid"] or checked["needs_review"]:
        raise RuntimeError(f"invalid lifecycle trace: {checked}")
    changed = copy.deepcopy(final)
    changed["revision"] = 3
    changed["artifacts"][3]["version"] = 2
    scenario = output / "scenarios/changed-record.json"
    write_json(scenario, final)
    update_record(scenario, changed, 2)
    change_check = check_record(changed)
    if "deployment" not in {item["id"] for item in change_check["needs_review"]}:
        raise RuntimeError("requirement change failed to invalidate deployment evidence")
    write_json(output / "scenarios/change-check.json", change_check)
    result = {"status": "isolated_release_verified", "build": build, "record": checked,
              "business_uat": "simulated", "production": "not_run", "processes_left_running": False,
              "model_usage": "deterministic replay of authored inputs; not a new or independent model trial",
              "pre_prd_provenance": "supplemented after the original pilot from unchanged simulated input; no new interviews or retrospective approvals"}
    for node in final["artifacts"]:
        for reference in [node["source"], *(e["source"] for e in node["evidence"])]:
            target = (output / reference).resolve()
            if not target.is_relative_to(output) or not target.is_file():
                raise RuntimeError(f"missing or external evidence: {reference}")
    write_json(output / "manifest.json", {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted(output.rglob("*")) if path.is_file() and "__pycache__" not in path.parts})
    result["manifest_sha256"] = hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest()
    write_json(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new directory; existing paths are never overwritten")
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
