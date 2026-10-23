#!/usr/bin/env python3
"""Validate an optional product artifact index; never grant product approval."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from validate_product_doc import document_contract, document_input, local_link, validate


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_inventory(root, browser_receipt):
    files = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts[0] == "evidence" or relative.as_posix() in {"bundle.json", "review.md", browser_receipt}:
            continue
        if path.is_symlink():
            raise ValueError("浏览器输入不能为符号链接")
        if path.is_file():
            if len(files) >= 4096 or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("交付输入超出快照上限")
            files[relative.as_posix()] = digest(path)
    return files


def file_in(root, relative):
    if not isinstance(relative, str) or not relative or re.search(r"[\\\\?#:]", relative):
        raise ValueError("交付物路径必须是本地相对文件")
    problem = local_link(relative, root, root, allow_https=False)
    if problem:
        raise ValueError(problem)
    return root / relative


def checked_artifact(root, item):
    if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
        raise ValueError("交付物必须包含 path 和 sha256")
    path = file_in(root, item["path"])
    if digest(path) != item["sha256"]:
        raise ValueError(f"交付物已变化：{item['path']}")
    return path


def check(bundle_path):
    root = bundle_path.resolve().parent
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict) or bundle.get("schemaVersion") != 1:
        raise ValueError("不支持的 bundle 版本")
    artifacts = bundle["artifacts"]
    document = checked_artifact(root, artifacts["prd"])
    tracking = checked_artifact(root, artifacts["tracking"]) if "tracking" in artifacts else None
    content, parsed, meaning, resources = document_input(document, tracking)
    _, version, requirements, scenarios, _ = document_contract(
        content, parsed=parsed, meaning=meaning, confirmation_resources=resources)
    baselines = artifacts.get("baselines", [])
    if not isinstance(baselines, list):
        raise ValueError("baselines 必须是从旧到新的快照列表")
    baseline_paths, baseline_artifacts = [], []
    for baseline in baselines:
        group = baseline if isinstance(baseline, list) else [baseline]
        if len(group) not in {1, 2}:
            raise ValueError("每个历史基线须为单文件或显式主文/追踪文件对")
        paths = tuple(checked_artifact(root, item) for item in group)
        baseline_paths.append(paths)
        baseline_artifacts.extend(group)
    if bundle.get("version") != version:
        raise ValueError("bundle 与 PRD 版本不一致")
    diagrams = bundle.get("diagrams", [])
    if not isinstance(diagrams, list):
        raise ValueError("diagrams 必须是可选图清单")
    diagram_inputs, diagram_sources = [], set()
    for diagram in diagrams:
        if not isinstance(diagram, dict) or set(diagram) != {"version", "requirements", "scenarios", "source", "exports"}:
            raise ValueError("图清单须声明版本、FR/AC、图源及导出文件")
        owners, acceptance = diagram["requirements"], diagram["scenarios"]
        if diagram["version"] != version:
            raise ValueError("图与 PRD 版本不一致")
        if not isinstance(owners, list) or not owners or any(not isinstance(owner, str) or owner not in requirements for owner in owners) \
                or len(owners) != len(set(owners)) or not isinstance(acceptance, list) \
                or any(not isinstance(ac, str) or ac not in scenarios or scenarios[ac] not in owners for ac in acceptance) \
                or len(acceptance) != len(set(acceptance)):
            raise ValueError("图的 FR/AC 关联错误")
        source = checked_artifact(root, diagram["source"]).resolve()
        if source in diagram_sources:
            raise ValueError("图源重复声明")
        diagram_sources.add(source)
        exports = diagram["exports"]
        if not isinstance(exports, list) or not exports:
            raise ValueError("图清单缺少导出文件")
        exported = [checked_artifact(root, item).resolve() for item in exports]
        if source in exported or len(exported) != len(set(exported)):
            raise ValueError("图源和导出文件须分别唯一")
        for path, item in zip([source, *exported], [diagram["source"], *exports]):
            diagram_inputs.append({"path": path.relative_to(root).as_posix(), "sha256": item["sha256"]})
    if "prototype" not in artifacts:
        problems = validate(document, baselines=baseline_paths, tracking=tracking)
        if problems:
            raise ValueError("；".join(problems))
        return "not_requested"
    prototype = checked_artifact(root, artifacts["prototype"])
    problems = validate(document, prototype, baseline_paths, tracking=tracking)
    if problems:
        raise ValueError("；".join(problems))
    tests, screenshots = artifacts["tests"], artifacts["screenshots"]
    if not isinstance(tests, list) or not tests or not isinstance(screenshots, list) or not screenshots:
        raise ValueError("原型交付须有当前旅程测试和截图")
    for item in tests + screenshots:
        checked_artifact(root, item)
    test_paths = {item["path"] for item in tests}
    screenshot_paths = {item["path"] for item in screenshots}
    journeys = bundle["journeys"]
    if not isinstance(journeys, list) or not journeys:
        raise ValueError("原型交付缺少旅程映射")
    covered, ids = set(), set()
    for journey in journeys:
        if not isinstance(journey, dict) or not isinstance(journey.get("id"), str) or not journey["id"] or journey["id"] in ids:
            raise ValueError("旅程标识缺少或重复")
        ids.add(journey["id"])
        owners, acceptance = journey["requirements"], journey["scenarios"]
        if not isinstance(owners, list) or not owners or any(owner not in requirements for owner in owners) \
                or not isinstance(acceptance, list) or not acceptance or any(ac not in scenarios or scenarios[ac] not in owners for ac in acceptance):
            raise ValueError("旅程 FR/AC 关联错误")
        if journey["test"] not in test_paths or not isinstance(journey["screenshots"], list) or not journey["screenshots"] \
                or any(shot not in screenshot_paths for shot in journey["screenshots"]):
            raise ValueError("旅程未关联实际测试或截图")
        covered.update(acceptance)
    expected = {ac for ac, owner in scenarios.items() if requirements[owner]["prototype"] == "是"}
    if not expected <= covered:
        raise ValueError("旅程未覆盖原型范围全部 AC")
    receipt = json.loads(file_in(root, bundle["browser"]).read_text(encoding="utf-8"))
    if receipt.get("schemaVersion") != 1 or receipt.get("tool") != "product-browser-v1" \
            or receipt.get("runnerFingerprint") != digest(Path(__file__).with_name("product_browser.mjs")) \
            or receipt.get("result") != "pass" or type(receipt.get("exitCode")) is not int or receipt["exitCode"] != 0 \
            or type(receipt.get("tests")) is not int or receipt["tests"] < 1 or receipt.get("passed") != receipt["tests"] \
            or receipt.get("failed") != 0 or receipt.get("skipped") != 0 or receipt.get("errors") != []:
        raise ValueError("缺少成功的实际浏览器证据")
    if test_paths != {receipt.get("test")}:
        raise ValueError("浏览器证据未运行清单中的测试入口；多个旅程应汇总到一个测试文件")
    source = receipt.get("source")
    if not isinstance(source, dict) or not source:
        raise ValueError("浏览器证据没有输入快照")
    if input_inventory(root, bundle["browser"]) != source:
        raise ValueError("浏览器输入清单已变化，新增、删除或修改输入后须重新运行")
    for item in [artifacts["prd"], artifacts["prototype"],
                 *([artifacts["tracking"]] if tracking is not None else []), *tests, *baseline_artifacts, *diagram_inputs]:
        if source.get(item["path"]) != item["sha256"]:
            raise ValueError("浏览器输入未绑定全部交付物")
    pages = receipt.get("pages")
    if not isinstance(pages, list) or not pages or any(not isinstance(page, dict) or set(page) != {"path", "sha256"}
            or not isinstance(page["path"], str) or source.get(page["path"]) != page["sha256"] for page in pages):
        raise ValueError("浏览器没有记录实际打开的当前页面")
    if artifacts["prototype"] not in pages:
        raise ValueError("声明的原型没有被实际打开")
    shots = receipt.get("screenshots")
    if not isinstance(shots, list):
        raise ValueError("截图证据格式错误")
    for item in screenshots:
        matches = [shot for shot in shots if isinstance(shot, dict) and shot.get("path") == item["path"] and shot.get("sha256") == item["sha256"]]
        if len(matches) != 1:
            raise ValueError("截图未由本次浏览器记录")
        shot = matches[0]
        if shot.get("page") not in pages:
            raise ValueError("截图没有绑定实际打开的页面")
        viewport = shot.get("viewport", {})
        if not isinstance(viewport, dict) or any(type(viewport.get(key)) is not int or viewport[key] <= 0 for key in ("width", "height")) \
                or not isinstance(shot.get("role"), str) or not shot["role"] or shot.get("scenario") not in covered:
            raise ValueError("截图缺少视口、角色或有效场景")
    if not any(shot.get("page") == artifacts["prototype"] for shot in shots):
        raise ValueError("缺少声明原型页面的实际截图")
    for journey in journeys:
        for path in journey["screenshots"]:
            if not any(shot["path"] == path and shot["scenario"] in journey["scenarios"] for shot in shots):
                raise ValueError("截图场景不属于关联旅程")
    return "evidence_checked"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    problems, browser = [], "unverified"
    try:
        browser = check(args.file)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError) as error:
        problems.append(f"交付证据无效：{error}")
    print(json.dumps({"valid": not problems, "problems": problems, "browserCheck": browser,
                      "semanticCheck": "not_proven", "visualCheck": "not_proven", "productApproval": "not_proven"}, ensure_ascii=False))
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
