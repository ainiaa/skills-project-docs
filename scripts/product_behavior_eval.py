"""Fail-closed release gate for real model observations; reuse the existing grader."""
import argparse
import io
import json
import os
import sys
import unittest
from pathlib import Path


def check_authored_artifacts(report_path):
    """Check frozen sample contracts, not product semantics or model authorship."""
    from product_bundle import checked_artifact, digest
    from validate_product_doc import approval_content, document_input, prose, validate
    from test_product_behavior_eval import skill_identity
    cases_root = Path(__file__).parent / "fixtures/product-behavior"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("schemaVersion") != 1:
        raise ValueError("不支持的成品评测版本")
    if (report.get("casesFingerprint") != digest(cases_root / "artifact-cases.json")
            or report.get("baselineFingerprint") != digest(cases_root / "revision-baseline.md")
            or report.get("skillIdentity") != skill_identity()):
        raise ValueError("成品输入、基线或 Skill 身份已变化")
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
        visible = parsed[0] if parsed is not None else prose(content)[0]
        if any(signal not in visible for signal in case["signals"]):
            raise ValueError(f"成品缺少冻结输入的可见信号：{case['id']}")
        if baselines:
            old = approval_content(baselines[0].read_text(encoding="utf-8"))
            new = meaning if meaning is not None else approval_content(content)
            for identifier in case["preserve"]:
                if identifier not in new or old[identifier] != new[identifier]:
                    raise ValueError(f"未变需求或确认记录被改写：{identifier}")
            for identifier in case["change"]:
                if identifier not in new or old[identifier] == new[identifier]:
                    raise ValueError(f"指定需求尚未修订：{identifier}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--report", type=Path, help="当前真实模型观察报告；不生成或伪造模型观察")
    inputs.add_argument("--artifacts", type=Path, help="实际成品报告；只检查结构、冻结信号和修订保留")
    args = parser.parse_args()
    status, code, reason = "uncovered", 2, "缺少真实模型观察报告，行为验收未完成"
    if sys.flags.optimize:
        status, code, reason = "invalid", 1, "行为判定不能禁用 Python 断言"
    elif args.artifacts is not None and args.artifacts.is_file():
        try:
            check_authored_artifacts(args.artifacts)
            status, code, reason = "pass", 0, "当前成品结构、冻结信号和修订保留通过；语义与浏览器另验"
        except (OSError, ValueError, KeyError, TypeError) as error:
            status, code, reason = "invalid", 1, str(error)
    elif args.report is not None and args.report.is_file():
        os.environ["PRODUCT_BEHAVIOR_REPORT"] = str(args.report.resolve())
        from test_product_behavior_eval import ProductBehaviorTests
        suite = unittest.TestSuite([ProductBehaviorTests("test_actual_fresh_context_behavior_and_upstream_identity")])
        result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        passed = result.wasSuccessful() and result.testsRun == 1 and not result.skipped
        status, code = ("pass", 0) if passed else ("invalid", 1)
        reason = "当前冻结样本、Skill 与上游身份匹配" if passed else "观察报告或当前 Skill/上游身份未通过判定；运行行为测试查看详情"
    print(json.dumps({"status": status, "reason": reason, "semanticCheck": "not_proven", "browserCheck": "not_run"}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
