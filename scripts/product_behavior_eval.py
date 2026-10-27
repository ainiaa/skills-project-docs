"""Fail-closed release gate for real model observations; reuse the existing grader."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from product_dependencies import diagnose


SKILL = Path(__file__).resolve().parents[1] / "skills/project-docs-product"
CASES = Path(__file__).with_name("fixtures") / "product-behavior/cases.json"


def skill_identity():
    identity = {str(path.relative_to(SKILL)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [SKILL / "SKILL.md", SKILL / "assets/prd-template.md", SKILL / "assets/prd-reader-template.md",
                         SKILL / "assets/prd-traceability-template.md", SKILL / "assets/prototype.html",
                         *sorted((SKILL / "references").glob("*.md"))]}
    for name in ("product_behavior_eval.py", "validate_product_doc.py", "product_bundle.py",
                 "product_browser.mjs", "product_dependencies.py", "requirements-product.txt"):
        path = Path(__file__).resolve().with_name(name)
        identity[f"../../scripts/{name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return identity


def check_observations(report):
    expected = {
        "refund-sufficient": ("write", "prd"),
        "procurement-conflict": ("clarify", "full"),
        "publishing-resume": ("clarify", "prd"),
        "refund-local-revision": ("revise", "full"),
        "procurement-full-flow": ("prototype", "full"),
        "publishing-local-prototype": ("prototype", "partial"),
        "refund-unresolved-threshold": ("clarify", "prd"),
        "notes-known-unapproved": ("clarify", "prd"),
        "notes-explicit-unapproved": ("write", "prd"),
        "refund-deferred-draft": ("write", "prd"),
        "notes-inherited-generation": ("write", "prd"),
        "notes-inherited-review": ("review", "prd"),
        "notes-conflict-review": ("clarify", "prd"),
    }
    values = report["observations"]
    assert len(values) == len(expected) and {value["id"] for value in values} == set(expected), "all frozen samples required"
    for value in values:
        assert (value["action"], value["scope"]) == expected[value["id"]], value
        assert value["autoApprove"] is False and value["writeBusinessCode"] is False, value
        if value["id"] == "refund-sufficient":
            assert value["questions"] == [], value
        if value["id"] == "procurement-conflict":
            assert len(value["questions"]) == 1 and any(word in value["questions"][0] for word in ("500", "1000", "阈值")), value
        if value["id"] == "publishing-resume":
            assert len(value["questions"]) == 1 and "FR-002" in value["questions"][0] and value["preserve"] == ["FR-001"], value
        if value["id"] == "refund-local-revision":
            assert value["affected"] == ["FR-001"] and value["preserve"] == ["FR-002"], value
        if value["id"] == "procurement-full-flow":
            assert value["sharedObject"] is True and set(value["journey"]) == {"create", "handoff", "result", "failure-recovery"}, value
        if value["id"] == "publishing-local-prototype":
            assert set(value["uncovered"]) == {"approval", "publishing", "result"}, value
        if value["id"] == "refund-unresolved-threshold":
            assert len(value["questions"]) == 1 and "阈值" in value["questions"][0], value
            assert value["businessUndecided"] == ["approval-threshold"], value
        if value["id"] == "notes-known-unapproved":
            assert len(value["questions"]) == 1 and "计数" in value["questions"][0], value
            assert value["businessUndecided"] == ["length-unit"], value
            assert value["technicalUnverified"] == ["storage-interface"] and value["approvalPending"] is True, value
        if value["id"] == "notes-explicit-unapproved":
            assert value["questions"] == [] and value["businessUndecided"] == [], value
            assert value["technicalUnverified"] == ["storage-interface"] and value["approvalPending"] is True, value
        if value["id"] == "refund-deferred-draft":
            assert not any("阈值" in question for question in value["questions"]), value
            assert "approval-threshold" in value["businessUndecided"], value
        if value["id"] in ("notes-inherited-generation", "notes-inherited-review"):
            assert value["questions"] == [] and value["businessUndecided"] == [], value
            assert value["technicalUnverified"] == ["storage-interface"] and value["approvalPending"] is True, value
        if value["id"] in ("notes-inherited-review", "notes-conflict-review"):
            assert value["writePrd"] is False, value
        if value["id"] == "notes-conflict-review":
            assert len(value["questions"]) == 1 and all(word in value["questions"][0] for word in ("200", "300")), value
            assert value["businessUndecided"] == ["length-limit"], value
            assert set(value["reviewFindings"]) == {"length-conflict", "typo"}, value


def check_identity(report, report_path):
    """A gate-only replay keeps the producer identity and original report immutable."""
    from product_bundle import checked_artifact
    current = skill_identity()
    receipt = report.get("revalidation")
    if receipt is None:
        if report["skillIdentity"] != current:
            raise ValueError("Skill 身份已变化，须重新生成或提供门禁复验回执")
        return
    if receipt["scope"] != "gate-only" or receipt["validatorIdentity"] != current:
        raise ValueError("门禁复验范围或当前校验身份无效")
    source = checked_artifact(report_path.resolve().parent, receipt["sourceReport"])
    original = json.loads(source.read_text(encoding="utf-8"))
    if original != {key: value for key, value in report.items() if key not in {"revalidation", "contentReview"}}:
        raise ValueError("门禁复验不得改写原生成报告或观察")
    allowed = {"../../scripts/product_behavior_eval.py", "references/evaluation.md"}
    producer = report["skillIdentity"]
    if (set(producer) != set(current)
            or any(producer[key] != value for key, value in current.items() if key not in allowed)):
        raise ValueError("起稿资源或其他工具变化，不能仅复验门禁")


def check_content_review(report, report_path, cases):
    """Validate an independent judgment's coverage and citations, not infer semantics."""
    from product_bundle import checked_artifact, digest
    from validate_product_doc import prose
    if "contentReview" not in report:
        return "not_proven"
    root = report_path.resolve().parent
    review = json.loads(checked_artifact(root, report["contentReview"]).read_text(encoding="utf-8"))
    checked_artifact(root, review["provenance"])
    rules_path = CASES.with_name("artifact-rules.json")
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    if (review["schemaVersion"] != 1 or not isinstance(review["reviewer"], str) or not review["reviewer"].strip()
            or review["validatorIdentity"] != skill_identity()
            or review["casesFingerprint"] != report["casesFingerprint"]
            or review["baselineFingerprint"] != report["baselineFingerprint"]
            or review["rulesFingerprint"] != digest(rules_path)
            or review["artifacts"] != report["artifacts"]):
        raise ValueError("独立内容复核身份、输入、规则或成品已变化")
    findings = review["cases"]
    if (len(findings) != len(cases) or {item["id"] for item in findings} != set(rules)
            or set(rules) != {case["id"] for case in cases}):
        raise ValueError("内容复核必须覆盖全部冻结案例且不可重复")
    for item in report["artifacts"]:
        result = next(value for value in findings if value["id"] == item["id"])
        checks = result["checks"]
        expected = rules[item["id"]]
        if len(checks) != len(expected) or {check["id"] for check in checks} != set(expected):
            raise ValueError(f"内容复核缺少规则或存在重复：{item['id']}")
        document = checked_artifact(root, item["prd"])
        tracking = checked_artifact(root, item["tracking"]) if "tracking" in item else None
        # Read each file separately so a citation cannot move from main text into an attachment.
        texts = {"prd": document.read_text(encoding="utf-8")}
        if tracking is not None:
            texts["tracking"] = tracking.read_text(encoding="utf-8")
        for name, resource in result.get("supporting", {}).items():
            if name not in {"reply", "baseline"}:
                raise ValueError("补充证据只能是交付回复或原始基线，不能替换主文/追踪")
            texts[name] = checked_artifact(root, resource).read_text(encoding="utf-8")
        for check in checks:
            if (check["verdict"] != "pass" or not isinstance(check["reason"], str)
                    or not check["reason"].strip() or not check["evidence"]):
                raise ValueError(f"业务规则缺失、矛盾或未验证：{item['id']}/{check['id']}")
            for evidence in check["evidence"]:
                text = texts[evidence["artifact"]]
                quote = evidence["quote"]
                if (not isinstance(quote, str) or not quote.strip() or quote not in text
                        or not prose(quote)[0].strip() or prose(quote)[0].strip() not in prose(text)[0]):
                    raise ValueError(f"内容复核引用不在可见正文：{item['id']}/{check['id']}")
    return "independently_reviewed"


def check_authored_artifacts(report_path):
    """Check file contracts and, when supplied, an independent content review."""
    from product_bundle import checked_artifact, digest
    from validate_product_doc import approval_content, document_input, validate
    cases_root = Path(__file__).parent / "fixtures/product-behavior"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("schemaVersion") != 1:
        raise ValueError("不支持的成品评测版本")
    if (report.get("casesFingerprint") != digest(cases_root / "artifact-cases.json")
            or report.get("baselineFingerprint") != digest(cases_root / "revision-baseline.md")):
        raise ValueError("成品输入、基线或 Skill 身份已变化")
    check_identity(report, report_path)
    cases = json.loads((cases_root / "artifact-cases.json").read_text(encoding="utf-8"))
    artifacts = report["artifacts"]
    if len(artifacts) != len(cases) or {item["id"] for item in artifacts} != {case["id"] for case in cases}:
        raise ValueError("必须提供全部冻结成品样本，不能缺失或重复")
    for case in cases:
        item = next(item for item in artifacts if item["id"] == case["id"])
        document = checked_artifact(report_path.resolve().parent, item["prd"])
        tracking = checked_artifact(report_path.resolve().parent, item["tracking"]) if "tracking" in item else None
        baselines = [cases_root / case["baseline"]] if "baseline" in case else []
        problems = validate(document, baselines=baselines, tracking=tracking)
        if problems:
            raise ValueError("；".join(problems))
        content, parsed, meaning, _ = document_input(document, tracking)
        if baselines:
            old = approval_content(baselines[0].read_text(encoding="utf-8"))
            new = meaning if meaning is not None else approval_content(content)
            for identifier in case["preserve"]:
                if identifier not in new or old[identifier] != new[identifier]:
                    raise ValueError(f"未变需求或确认记录被改写：{identifier}")
            for identifier in case["change"]:
                if identifier not in new or old[identifier] == new[identifier]:
                    raise ValueError(f"指定需求尚未修订：{identifier}")

    return check_content_review(report, report_path, cases)


def check_behavior_report(report_path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    check_identity(report, report_path)
    if report["casesFingerprint"] != hashlib.sha256(CASES.read_bytes()).hexdigest():
        raise ValueError("行为样本或 Skill 身份已变化")
    roots = report["skillRoots"]
    if not isinstance(roots, list) or not roots or any(not isinstance(root, str) or not root.strip() for root in roots):
        raise ValueError("skillRoots 必须包含有效的上游目录")
    current = diagnose(roots)
    if not current["ready"] or report["dependencies"] != current["dependencies"]:
        raise ValueError("上游依赖未就绪或身份已变化")
    if report["runnerStatus"] != "completed" or report["roleStatus"] != "available":
        raise ValueError("模型观察执行尚未完成")
    check_observations(report)


def evaluate(report=None, artifacts=None):
    missing = "缺少实际成品报告，成品验收未完成" if artifacts is not None else "缺少真实模型观察报告，行为验收未完成"
    status, code, reason = "uncovered", 2, missing
    semantic = "not_proven"
    if sys.flags.optimize:
        status, code, reason = "invalid", 1, "行为判定不能禁用 Python 断言"
    elif artifacts is not None and artifacts.is_file():
        try:
            semantic = check_authored_artifacts(artifacts)
            status, code, reason = "pass", 0, "成品结构、资源及修订保留通过；内容复核单独标示"
        except (OSError, ValueError, KeyError, TypeError) as error:
            status, code, reason = "invalid", 1, str(error)
    elif report is not None and report.is_file():
        try:
            check_behavior_report(report)
            status, code, reason = "pass", 0, "当前冻结样本、Skill 与上游身份匹配"
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as error:
            status, code, reason = "invalid", 1, str(error)
    return code, {"status": status, "reason": reason, "semanticCheck": semantic, "browserCheck": "not_run"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="当前真实模型观察报告；不生成或伪造模型观察")
    parser.add_argument("--artifacts", type=Path, help="实际成品报告；检查结构、修订保留及可选独立内容复核证据")
    parser.add_argument("--release", action="store_true", help="发布检查：行为与实际成品报告须同时通过")
    args = parser.parse_args()
    if args.report and args.artifacts and not args.release:
        parser.error("--report and --artifacts require --release when combined")
    if args.release:
        behavior_code, behavior = evaluate(report=args.report)
        artifact_code, artifacts = evaluate(artifacts=args.artifacts)
        if artifact_code == 0 and artifacts["semanticCheck"] != "independently_reviewed":
            artifact_code = 2
            artifacts.update(status="uncovered", reason="缺少当前逐规则独立内容复核，不能仅凭结构通过发布")
        if artifact_code == 2 and args.artifacts is None:
            artifacts["reason"] = "缺少实际成品报告，成品验收未完成"
        code = 1 if 1 in (behavior_code, artifact_code) else max(behavior_code, artifact_code)
        result = {"status": {0: "pass", 1: "invalid", 2: "uncovered"}[code],
                  "checks": {"behavior": behavior, "artifacts": artifacts},
                  "semanticCheck": artifacts["semanticCheck"], "browserCheck": "not_run"}
    else:
        code, result = evaluate(args.report, args.artifacts)
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
