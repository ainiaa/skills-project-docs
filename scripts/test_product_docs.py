"""Product authoring resources and observable document validation behavior."""

import re
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT / "skills/project-docs-product"

PRD = """# 退款审批示例
> 产品版本：draft-1
> 状态：草稿

## 来源与决策
### SRC-001 测试设定
这是模拟示例设定，不是实际业务决定。

## 需求
### FR-001 申请退款
状态：待确认
依据：SRC-001
原型：是
申请后显示审批状态。
#### AC-001 正常申请
提交有效输入，显示申请已提交。
#### AC-002 边界输入
输入恰好等于阈值，进入审批。
#### AC-003 非法输入
负数不能提交，并展示错误。

## 未决事项
无。
"""
HTML = """<!doctype html><html lang="zh-CN"><head>
<meta name="product-version" content="draft-1"></head><body>
<main data-requirement="FR-001">
<button data-scenario="AC-001">正常</button>
<button data-scenario="AC-002">边界</button>
<button data-scenario="AC-003">非法</button></main></body></html>"""


class ProductWorkflowTests(unittest.TestCase):
    def test_product_ci_discovers_all_product_python_suites(self):
        workflow = (ROOT / '.github/workflows/product-acceptance.yml').read_text()
        command = 'python3 -m pytest scripts/test_product*.py --cov --cov-fail-under=90'
        self.assertIn(command, workflow)
        self.assertLess(workflow.index('run: python3 scripts/install_renderers.py --engine mermaid'),
                        workflow.index(command))
        self.assertLess(workflow.index('python3 -m pip install pytest=='), workflow.index(command))

    def test_product_job_env_uses_contexts_available_before_runner_assignment(self):
        workflow = (ROOT / '.github/workflows/product-acceptance.yml').read_text()
        environment = workflow.split('    env:', 1)[1].split('    steps:', 1)[0]
        self.assertNotRegex(environment, r'\$\{\{\s*runner\.')

    def test_full_renderer_ci_installs_product_parser_before_discovery(self):
        workflow = (ROOT / '.github/workflows/archify-acceptance.yml').read_text()
        job = workflow.split('\n  diagram-renderers:\n', 1)[1]
        self.assertIn('python3 -m pip install -r scripts/requirements-product.txt', job)
        self.assertLess(job.index('python3 -m pip install -r scripts/requirements-product.txt'),
                        job.index("python3 -m unittest discover -s scripts -p 'test_*.py'"))

    def test_product_ci_renderer_path_matches_published_installer_entry(self):
        from unittest.mock import patch
        from install_renderers import RendererInstaller
        from engine_paths import find_engine
        workflow = (ROOT / '.github/workflows/product-acceptance.yml').read_text()
        with tempfile.TemporaryDirectory() as directory:
            def configured(name):
                value = re.search(rf'(?m)^    +{name}: (.+)$', workflow)[1]
                return value.replace('${{ github.workspace }}', directory).replace('${{ runner.temp }}', directory)
            runtime = Path(directory) / 'mock-mmdc'
            runtime.write_text('#!/bin/sh\nexit 0\n')
            runtime.chmod(0o755)
            home = configured('UNDERSTAND_RENDERER_HOME')
            published = RendererInstaller(home)._publish_link('mmdc', runtime)
            with patch.dict('os.environ', UNDERSTAND_RENDERER_HOME=home,
                            MERMAID_OFFICIAL_CLI=configured('MERMAID_OFFICIAL_CLI')):
                self.assertEqual(find_engine('mermaid'), str(published))

    def test_lightweight_authoring_has_one_contract_and_skippable_template_sections(self):
        guide = (PRODUCT / 'references/reading-and-change.md').read_text()
        self.assertIn('## 轻量需求与拆分选择', guide)
        template = (PRODUCT / 'assets/prd-reader-template.md').read_text()
        self.assertIn('reading-and-change.md#轻量需求与拆分选择', template)

    def test_input_modes_and_product_quality_are_shared_without_requiring_source(self):
        entry = (PRODUCT / 'SKILL.md').read_text()
        self.assertIn('input-and-quality.md', entry)
        guide = (PRODUCT / 'references/input-and-quality.md').read_text()
        for signal in ('截图', '口述', '新产品', '无源码', '完整', '冲突', '错误',
                       '退出', '恢复', '确定失败', '永久缺失', '需求讨论', '业务评审', '技术设计'):
            self.assertIn(signal, guide)
        brownfield = (PRODUCT / 'references/brownfield-delivery.md').read_text()
        self.assertIn('input-and-quality.md', brownfield)
        self.assertIn('页面线框不能用流程节点代替', brownfield)
        self.assertIn('静态HTML', brownfield)
        template = (PRODUCT / 'assets/prd-reader-template.md').read_text()
        self.assertIn('交付结论', template)
        self.assertIn('业务证据', template)

    def test_reader_and_tracking_templates_form_a_valid_split_delivery(self):
        def clean(path):
            return re.sub(r'<!--.*?-->', '', path.read_text(), flags=re.S)
        content = clean(PRODUCT / 'assets/prd-reader-template.md')
        self.assertNotRegex(content, r'(?m)^#{3,4} (?:FR|AC|SRC)-')
        content += '\n[需求与验收追踪](prd-traceability.md)。\n'
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / 'prd.md'
            tracking = Path(directory) / 'prd-traceability.md'
            document.write_text(content)
            tracking.write_text(clean(PRODUCT / 'assets/prd-traceability-template.md'))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_product_doc.py'),
                                     '--file', str(document), '--tracking', str(tracking)],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reader_template_forms_a_valid_single_file_delivery(self):
        content = re.sub(r'<!--.*?-->', '',
                         (PRODUCT / 'assets/prd-reader-template.md').read_text(), flags=re.S)
        content += '\n## 来源与决策\n' + PRD.replace('原型：是', '原型：否').split('## 来源与决策', 1)[1]
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / 'prd.md'
            document.write_text(content)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_product_doc.py'),
                                     '--file', str(document)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_brownfield_prd_requires_baseline_lifecycle_and_combined_scenarios(self):
        skill = (PRODUCT / 'SKILL.md').read_text()
        self.assertIn('brownfield-delivery.md', skill)
        guide = (PRODUCT / 'references/brownfield-delivery.md').read_text()
        for signal in ('实际页面', '增量', '源对象', '结果对象', '准备', '固定', '保存',
                       '首次推送', '冲销', '主数据变化', '新旧切换', '恢复', '责任',
                       '显示尺寸', '评审动作', '推荐', '阻塞'):
            self.assertIn(signal, guide)
        template = (PRODUCT / 'assets/prd-reader-template.md').read_text()
        for signal in ('业务证据', '字段生命周期', '责任角色', '阻塞范围'):
            self.assertIn(signal, template)

    def test_default_prd_is_reader_facing_with_required_visuals_for_ui_and_branching_work(self):
        skill = (PRODUCT / 'SKILL.md').read_text()
        self.assertIn('prd-reader-template.md', skill)
        template = PRODUCT / 'assets/prd-reader-template.md'
        self.assertTrue(template.is_file())
        content = template.read_text()
        main = content.split('<details>', 1)[0]
        self.assertNotRegex(main, r'(?m)^#{2,4} (?:FR|AC|SRC|Q)[-0-9]')
        for signal in ('页面与交互', '业务流程', '字段', '验收场景'):
            self.assertIn(signal, main)
        guide = (PRODUCT / 'references/reading-and-change.md').read_text()
        for signal in ('不等于不画交互图', '有页面变化', '跨系统或多分支', '折叠追踪附录', '实际查看'):
            self.assertIn(signal, guide)

    def test_brownfield_authoring_reads_annotations_and_keeps_business_reading_first(self):
        skill = (PRODUCT / 'SKILL.md').read_text()
        workflow = (PRODUCT / 'references/workflow.md').read_text()
        guide = (PRODUCT / 'references/reading-and-change.md').read_text()
        for signal in ('评论', '回复', '读取完整性'):
            self.assertIn(signal, skill + workflow)
        for signal in ('原编号', '不补零', '证据附录', '已明确规则', '--source-root'):
            self.assertIn(signal, guide)
        self.assertIn('技术待核实', workflow)

    def test_prd_review_routes_to_its_contract_instead_of_authoring_defaults(self):
        skill = (PRODUCT / 'SKILL.md').read_text()
        guide = (PRODUCT / 'references/reading-and-change.md').read_text()
        self.assertIn('references/workflow.md#prd评审', skill)
        self.assertIn('workflow.md#prd评审', guide)
        workflow = (PRODUCT / 'references/workflow.md').read_text()
        self.assertIn('## PRD评审', workflow)

    def test_delivery_reply_prioritizes_decisions_and_links_detailed_evidence(self):
        guide = (PRODUCT / "references/reading-and-change.md").read_text()
        section = guide.split("## 正文与交付回复", 1)[1].split("\n## ", 1)[0]
        for signal in ("改了什么", "需要决定什么", "下一步", "完整命令", "证据链接", "简单整理或小修订"):
            self.assertIn(signal, section)

    def test_delivery_summary_reports_current_evidence_and_expired_results_separately(self):
        guide = (PRODUCT / "references/reading-and-change.md").read_text()
        self.assertIn("## 交付验收汇总", guide)
        section = guide.split("## 交付验收汇总", 1)[1].split("\n## ", 1)[0]
        for signal in ("产品版本", "文档修订", "结构", "浏览器", "模型", "人工确认", "证据", "失效", "未验证"):
            self.assertIn(signal, section)

    def test_engineering_and_numeric_review_keep_evidence_separate_from_design(self):
        guide = (PRODUCT / "references/reading-and-change.md").read_text()
        for heading, signals in (
            ("## 研发速览（按需）", ("候选改动点", "接口", "定义处", "技术方案", "待核实")),
            ("## 计算与修改联动核对", ("输入", "单位", "舍入", "边界", "派生", "FR/AC", "稳定编号")),
        ):
            self.assertIn(heading, guide)
            section = guide.split(heading, 1)[1].split("\n## ", 1)[0]
            for signal in signals:
                self.assertIn(signal, section)
        template = (PRODUCT / "assets/prd-template.md").read_text()
        self.assertIn("候选改动点", template)
        example = (PRODUCT / "assets/examples/prd.md").read_text()
        self.assertIn("### 计算核对", example)
        self.assertIn("499.99 × 100 = 49999", example)

    def test_authoring_contract_keeps_decisions_conditional_and_delivery_points_visible(self):
        guide = (PRODUCT / "references/reading-and-change.md").read_text()
        self.assertIn("## 正文与交付回复", guide)
        section = guide.split("## 正文与交付回复", 1)[1].split("\n## ", 1)[0]
        for signal in ("决策摘要", "资料充分", "不重复确认", "独立证据文件", "用户要点", "FR/AC",
                       "未覆盖", "不复制规则", "对话不可完整恢复"):
            self.assertIn(signal, section)
        skill = (PRODUCT / "SKILL.md").read_text()
        self.assertIn("要点覆盖", skill)
        template = (PRODUCT / "assets/prd-template.md").read_text()
        self.assertIn("正文只写产品规格", template)
        self.assertNotIn("要点覆盖表", template, "the conversational index is not a second PRD table")

    def decision_rows(self, content, heading):
        from markdown_it import MarkdownIt
        self.assertIn(heading, content)
        section = content.split(heading, 1)[1].split("\n## ", 1)[0]
        rows, cells = [], None
        for token in MarkdownIt("commonmark").enable("table").parse(section):
            if token.type == "tr_open":
                cells = []
            elif token.type == "inline" and cells is not None:
                cells.append(token.content)
            elif token.type == "tr_close":
                rows.append(cells)
                cells = None
        self.assertGreaterEqual(len(rows), 4)
        return rows

    def test_reader_tables_answer_three_roles_and_link_to_detailed_rules(self):
        for name in ("assets/prd-template.md", "assets/examples/prd.md"):
            with self.subTest(name=name):
                text = (PRODUCT / name).read_text()
                rows = self.decision_rows(text, "### 角色阅读区")
                for role in ("业务人员", "研发人员", "测试人员"):
                    row = next((row for row in rows[1:] if row[0] == role), None)
                    self.assertIsNotNone(row, role)
                    self.assertEqual(len(row), 4)
                    self.assertTrue(all(cell.strip() for cell in row))
                if "examples" in name:
                    business = next(row for row in rows if row[0] == "业务人员")
                    self.assertNotIn("UTF-16", " ".join(business[1:3]))
                    self.assertTrue(any("新增" in cell for cell in business))
                    self.assertRegex(business[-1], r"\[[^\]]+\]\(#[^)]+\)")
                    self.assertIn("![核心退款流程]", text)

    def test_handoff_tables_expose_conclusions_blockers_and_next_owners(self):
        for name in ("assets/prd-template.md", "assets/examples/prd.md"):
            with self.subTest(name=name):
                text = (PRODUCT / name).read_text()
                rows = self.decision_rows(text, "### 交接结论")
                for purpose in ("业务评审", "技术设计", "测试准备"):
                    row = next((row for row in rows[1:] if row[0] == purpose), None)
                    self.assertIsNotNone(row, purpose)
                    self.assertEqual(len(row), 4)
                    self.assertTrue(all(cell.strip() for cell in row))
                if "examples" in name:
                    section = text.split("### 交接结论", 1)[1]
                    self.assertIn("flow-2-doc-3", section)
                    for boundary in ("真实人员试读：未验证", "生产影响核查：未验证", "生产联调：未验证"):
                        self.assertIn(boundary, section)

    def test_incremental_prototypes_keep_traceable_baselines_and_one_business_model(self):
        guide = (PRODUCT / "references/prototype.md").read_text()
        for rule in ("使用模式", "变更标注模式", "新增", "修改", "删除", "保持不变", "待确认",
                     "基线", "口述", "历史缺字段", "导出", "两套", "data-page", "data-change-note"):
            self.assertIn(rule, guide)
        template = (PRODUCT / "assets/prd-template.md").read_text()
        self.assertIn("页面与字段变更", template)
        self.assertIn("修改前", template)

    def test_page_inventory_and_reader_decisions_are_explicit_without_forcing_more_files(self):
        guide = (PRODUCT / "references/reading-and-change.md").read_text()
        for rule in ("必须能作出的判断", "页面清单", "入口", "去向", "HTML 文件数量", "数据条件"):
            self.assertIn(rule, guide)
        template = (PRODUCT / "assets/prd-template.md").read_text()
        self.assertIn("页面清单与跳转关系", template)
        prototype = (PRODUCT / "references/prototype.md").read_text()
        self.assertIn("不能用状态按钮替代", prototype)

    def test_role_views_keep_a_single_authoritative_prd_and_conditional_detail(self):
        template = (PRODUCT / "assets/prd-template.md").read_text()
        self.assertIn("业务摘要与阅读导航", template)
        reference = PRODUCT / "references/reading-and-change.md"
        self.assertTrue(reference.is_file(), "role reading contract is missing")
        guide = reference.read_text()
        for rule in ("业务人员", "研发人员", "测试人员", "同一份正式 PRD", "FR/AC", "简单需求", "版本", "关键规则"):
            self.assertIn(rule, guide)
        skill = (PRODUCT / "SKILL.md").read_text()
        self.assertIn("references/reading-and-change.md", skill)
        self.assertLessEqual(len(skill.splitlines()), 35, "keep the entrypoint a small router")

    def test_brownfield_contract_distinguishes_unknown_impact_from_verified_none(self):
        guide = (PRODUCT / "references/reading-and-change.md").read_text()
        for rule in ("现状依据", "变更前后", "历史数据", "进行中", "待核实", "已核实无影响", "回归", "源码"):
            self.assertIn(rule, guide)
        template = (PRODUCT / "assets/prd-template.md").read_text()
        self.assertIn("现状、变更与历史影响", template)
        example = (PRODUCT / "assets/examples/prd.md").read_text()
        for signal in ("业务摘要与阅读导航", "变更前后", "进行中", "FR-006", "回归"):
            self.assertIn(signal, example)

    def test_example_links_editable_swimlane_and_business_sequence(self):
        example = PRODUCT / "assets/examples"
        document = (example / "prd.md").read_text()
        for name in ("refund-swimlane", "refund-sequence"):
            source = example / (name + ".puml")
            rendered = example / (name + ".svg")
            self.assertTrue(source.is_file(), name)
            self.assertTrue(rendered.is_file(), name)
            self.assertIn(name + ".puml", document)
            self.assertIn(name + ".svg", document)
            self.assertIn("flow-2", source.read_text())
            self.assertIn("<svg", rendered.read_text())
        self.assertIn("AC-011", (example / "refund-swimlane.puml").read_text())
        self.assertIn("AC-012", document.split("## 图表索引与一致性", 1)[1].split("## 非功能", 1)[0])

    def test_prd_only_and_resume_never_expand_delivery_scope(self):
        guide = (PRODUCT / "references/reading-and-change.md").read_text()
        self.assertIn("交付范围按授权，详见workflow.md", guide)
        workflow = (PRODUCT / "references/workflow.md").read_text()
        for signal in ("仅写PRD", "暂停", "恢复只核实变化", "完整原型已授权", "不因先写PRD或局部修订缩减", "不因未来可能需要而追加"):
            self.assertIn(signal, workflow)

    def test_refund_prd_exposes_existing_text_boundaries_to_development_and_qa(self):
        text = (PRODUCT / "assets/examples/prd.md").read_text()
        create = text.split("### FR-002 ", 1)[1].split("### FR-003 ", 1)[0]
        approve = text.split("### FR-003 ", 1)[1].split("### FR-004 ", 1)[0]
        for signal in ("40", "200", "41", "201", "UTF-16", "首尾空白"):
            self.assertIn(signal, create)
        for signal in ("200", "201", "首尾空白", "计数"):
            self.assertIn(signal, approve)

    def test_adaptive_content_covers_product_dimensions_without_fixed_counts(self):
        template = (PRODUCT / "assets/prd-template.md").read_text()
        for dimension in ("目标用户", "优先级", "非功能", "依赖", "用例", "里程碑"):
            self.assertIn(dimension, template)
        guide = (PRODUCT / "references/workflow.md").read_text()
        for rule in ("八个维度", "不要求凑满", "不适用", "单一规则真源"):
            self.assertIn(rule, guide)
        example = (PRODUCT / "assets/examples/prd.md").read_text()
        self.assertIn("优先级", example)
        self.assertIn("非功能", example)
        self.assertEqual(set(re.findall(r"^### (FR-\d{3}) ", example, re.M)),
                         {f"FR-{i:03}" for i in range(1, 7)})

    def test_product_request_has_a_dedicated_route_and_portable_resources(self):
        router = (ROOT / "skills/project-docs/SKILL.md").read_text()
        self.assertIn("../project-docs-product/SKILL.md", router)
        self.assertTrue((PRODUCT / "SKILL.md").is_file(), "missing product authoring capability")
        skill = (PRODUCT / "SKILL.md").read_text()
        self.assertIn("name: project-docs-product", skill)
        self.assertIn("$project-docs-product", (PRODUCT / "agents/openai.yaml").read_text())
        for source in [PRODUCT / "SKILL.md", *sorted((PRODUCT / "references").glob("*.md"))]:
            with self.subTest(source=source.relative_to(PRODUCT)):
                for match in re.finditer(r"\]\(([^)#]+)(?:#[^)]*)?\)", source.read_text()):
                    target = match[1]
                    if not target.startswith("https://"):
                        self.assertTrue((source.parent / target).resolve().is_file(), target)

    def test_handoff_keeps_one_question_owner_and_explicit_confirmation(self):
        self.assertTrue((PRODUCT / "references/workflow.md").is_file())
        guide = (PRODUCT / "references/workflow.md").read_text()
        for rule in ("brainstorming", "grilling", "domain-modeling", "未回复不是同意",
                     "草稿", "暂停", "FR/AC原编号", "确认绑定真实记录", "按需", "版本"):
            self.assertIn(rule, guide)
        for name in ("prd-template.md", "prototype.html"):
            self.assertTrue((PRODUCT / "assets" / name).is_file(), name)

    def test_pressure_cases_cover_product_decisions_and_change_propagation(self):
        cases = PRODUCT / "references/evaluation.md"
        self.assertTrue(cases.is_file())
        text = cases.read_text()
        for case in ("资料充分", "口径冲突", "未回复", "暂停恢复", "局部修改", "无代码"):
            self.assertIn(case, text)

    def test_complete_prototypes_require_journey_coverage_and_shared_state(self):
        self.assertIn("maxlength", (PRODUCT / "references/prototype.md").read_text())
        guide = (PRODUCT / "references/prototype.md").read_text()
        for requirement in ("完整用户任务", "局部交互验证", "流程覆盖表", "共享模拟数据", "角色交接", "结束结果", "未覆盖"):
            self.assertIn(requirement, guide)
        template = (PRODUCT / "assets/prd-template.md").read_text()
        self.assertIn("流程覆盖表", template)
        example = (PRODUCT / "assets/examples/prd.md").read_text()
        for requirement in ("申请列表", "角色交接", "执行失败", "重试", "操作记录", "流程覆盖表"):
            self.assertIn(requirement, example)


class ProductReviewTests(unittest.TestCase):
    def review(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prd.md"
            if content is not None:
                path.write_text(content)
                (path.parent / "prototype.html").write_text(HTML)
                for asset in (PRODUCT / "assets/examples").iterdir():
                    if asset.suffix in {".puml", ".svg"} or asset.name == "refund-baseline.md":
                        (path.parent / asset.name).write_bytes(asset.read_bytes())
            result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_product_doc.py"),
                                     "--file", str(path), "--review"], capture_output=True, text=True)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_review_observes_dimensions_without_claiming_semantics_or_confirmation(self):
        code, report = self.review((PRODUCT / "assets/examples/prd.md").read_text())
        self.assertEqual(code, 0, report)
        review = report["review"]
        self.assertEqual(len(review["dimensions"]), 8)
        self.assertTrue(all(row["status"] == "mentioned" for row in review["dimensions"]))
        self.assertEqual(review["semanticReview"], "required")
        self.assertEqual(review["humanConfirmation"], "not_proven")
        self.assertEqual(review["workflow"], "not_connected")
        self.assertEqual(report["browserCheck"], "not_run")

    def test_review_missing_dimensions_are_advisory_and_code_cannot_supply_evidence(self):
        code, report = self.review(PRD + "\n```md\n## 目标用户与非功能约束\n角色和性能\n```\n")
        self.assertEqual(code, 0, report)
        rows = {row["dimension"]: row for row in report["review"]["dimensions"]}
        self.assertEqual(rows["目标用户与场景"]["status"], "not_observed")
        self.assertEqual(rows["非功能与依赖"]["status"], "not_observed")

    def test_role_handoff_prompts_never_autocertify_sparse_or_complete_documents(self):
        for content in (PRD, (PRODUCT / "assets/examples/prd.md").read_text()):
            code, report = self.review(content)
            self.assertEqual(code, 0, report)
            handoff = report["review"]["handoffReview"]
            self.assertEqual(handoff["status"], "not_run")
            self.assertEqual(set(handoff["questions"]), {"business", "engineering", "qa"})
            for role, questions in handoff["questions"].items():
                self.assertTrue(questions, role)
                self.assertTrue(all(isinstance(question, str) and question for question in questions))
            self.assertEqual(report["semanticCheck"], "not_proven")
            self.assertEqual(report["review"]["humanConfirmation"], "not_proven")
        guide = (PRODUCT / "references/reading-and-change.md").read_text()
        for signal in ("分角色交接评审", "阻塞", "技术设计"):
            self.assertIn(signal, guide)
        workflow = (PRODUCT / "references/workflow.md").read_text()
        for signal in ("草稿", "真实记录", "模型不能授予批准"):
            self.assertIn(signal, workflow)

    def test_review_does_not_hide_invalid_or_missing_document(self):
        for content in (None, "# 没有需求的文档"):
            with self.subTest(content=content):
                code, report = self.review(content)
                self.assertEqual(code, 1)
                self.assertIsNone(report["review"])
                self.assertTrue(report["problems"])


class ProductValidationTests(unittest.TestCase):
    def test_shared_change_region_checks_each_scenario_usage_against_its_actual_owner(self):
        prd = PRD + '''
### FR-002 补充展示
状态：草稿
依据：SRC-001
原型：是
展示同一对象。
#### AC-004 展示结果
显示正确内容。
'''
        change = '<section data-page="detail" data-requirement="FR-001 FR-002" data-change="modified" data-change-note="共享字段调整" data-scenario="AC-001 AC-004">共享字段</section>'
        html = HTML.replace('</body>', change + '</body>')
        self.assertTrue(self.validate(prd=prd, html=html)['valid'])
        # A correct occurrence must not hide a second occurrence under the wrong FR.
        for bad in ('<div data-requirement="FR-002" data-scenario="AC-001">错误归属</div>',
                    '<div data-requirement="FR-001" data-scenario="AC-004">错误归属</div>'):
            with self.subTest(markup=bad):
                self.assertFalse(self.validate(prd=prd, html=html.replace('</body>', bad + '</body>'))['valid'])

    def test_htm_business_pages_are_not_an_unchecked_resource_extension(self):
        for name in ('detail.htm', 'detail.HTM'):
            first = HTML.replace('</main>', f'<a href="{name}">详情</a></main>')
            page = self.directory / name
            page.write_text(HTML)
            self.assertTrue(self.validate(html=first)['valid'])
            for bad in (HTML.replace('draft-1', 'old'), HTML.replace('FR-001', 'FR-999'),
                        HTML + '<img src="missing.png">',
                        HTML + '<div data-change="unknown">无效标注</div>'):
                page.write_text(bad)
                with self.subTest(page=name, content=bad):
                    self.assertFalse(self.validate(html=first)['valid'])

    def test_optional_change_metadata_accepts_valid_context_and_rejects_missing_or_invalid_links(self):
        markup = '<section data-page="create" data-requirement="FR-001"><div data-change="added" data-change-note="新增备注，历史不回填" data-scenario="AC-001">新增备注</div></section>'
        self.assertTrue(self.validate(html=HTML.replace('</body>', markup + '</body>'))['valid'])
        invalid = [markup.replace('data-page="create"', ''), markup.replace('data-change="added"', 'data-change="unknown"'),
                   markup.replace('data-change-note="新增备注，历史不回填"', ''), markup.replace('data-scenario="AC-001"', ''),
                   markup.replace('data-requirement="FR-001"', ''), markup.replace('AC-001', 'AC-999'),
                   markup + '<aside data-page="create"></aside>', markup.replace('data-page="create"', 'data-page="bad page"'),
                   markup.replace('data-change-note="新增备注，历史不回填"', 'data-change-note')]
        for value in invalid:
            with self.subTest(markup=value):
                self.assertFalse(self.validate(html=HTML.replace('</body>', value + '</body>'))['valid'])

    def test_linked_html_pages_aggregate_coverage_and_validate_each_version_and_resources(self):
        first = HTML.replace('<main data-requirement="FR-001">', '<main data-page="list" data-requirement="FR-001">')
        first = first.replace('<button data-scenario="AC-002">边界</button>', '').replace('<button data-scenario="AC-003">非法</button>', '')
        first = first.replace('</main>', '<a href="pages/detail.html">详情</a></main>')
        folder = self.directory / 'pages'; folder.mkdir()
        second = '<meta name="product-version" content="draft-1"><section data-page="detail" data-requirement="FR-001"><button data-scenario="AC-002 AC-003">边界与异常</button><a href="../prototype.html">返回</a></section>'
        path = folder / 'detail.html'; path.write_text(second)
        self.assertTrue(self.validate(html=first)['valid'])
        for invalid in [second.replace('draft-1', 'old'), second.replace('data-page="detail"', 'data-page="list"'),
                        second.replace('FR-001', 'FR-999'), second.replace('AC-002 AC-003', 'AC-002'),
                        second + '<img src="missing.png">', second + '<img src="../../outside.png">']:
            path.write_text(invalid)
            with self.subTest(html=invalid):
                self.assertFalse(self.validate(html=first)['valid'])

    def test_prd_html_resources_match_markdown_containment_and_opaque_contexts(self):
        (self.directory / "shot.png").write_bytes(b"local screenshot fixture")
        (self.directory / "good.css").write_text('body {background: url(shot.png)}')
        (self.directory / "bad.css").write_text('body {background: url(../outside.png)}')
        valid = ('<img src="shot.png">', '<div>\n<img src="shot.png">\n</div>',
                 '<span style="background:url(shot.png)">图片</span>', '<link rel="stylesheet" href="good.css">',
                 '`<img src="missing.png">`', '<!-- <img src="missing.png"> -->',
                 '```html\n<img src="missing.png">\n```')
        invalid = ('<img src="missing.png">', '<div>\n<img src="../outside.png">\n</div>',
                   '<a href="../outside.md">附件</a>', '<object data="../outside.svg"></object>',
                   '<img srcset="shot.png 1x, missing.png 2x">', '<img src="javascript:alert(1)">',
                   '<span style="background:url(../outside.png)">图片</span>',
                   '<link rel="stylesheet" href="bad.css">')
        for markup, expected in [(value, True) for value in valid] + [(value, False) for value in invalid]:
            with self.subTest(markup=markup):
                self.assertEqual(self.validate(PRD + "\n\n" + markup, prototype=False)["valid"], expected)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="product documents ")
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)

    def validate(self, prd=PRD, html=HTML, prototype=True, baselines=(), source_roots=()):
        script = ROOT / "scripts/validate_product_doc.py"
        self.assertTrue(script.is_file(), "product document validation is not implemented")
        document = self.directory / "prd.md"
        document.write_text(prd)
        args = [sys.executable, str(script), "--file", str(document)]
        if prototype:
            page = self.directory / "prototype.html"
            page.write_text(html)
            args += ["--prototype", str(page)]
        for index, baseline in enumerate(baselines):
            previous = self.directory / f"baseline-{index}.md"
            previous.write_text(baseline)
            args += ["--baseline", str(previous)]
        for source in source_roots:
            args += ['--source-root', str(source)]
        result = subprocess.run(args, text=True, capture_output=True)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["valid"], result.returncode == 0)
        self.assertEqual(value["semanticCheck"], "not_proven")
        return value

    def test_existing_short_identifiers_work_without_renumbering_and_keep_confirmation_checks(self):
        legacy = PRD.replace('FR-001', 'FR-01').replace('SRC-001', 'SRC-1')
        legacy = legacy.replace('AC-001', 'AC-01').replace('AC-002', 'AC-02').replace('AC-003', 'AC-03')
        self.assertTrue(self.validate(legacy, prototype=False)['valid'])
        confirmed = legacy.replace('状态：待确认', '状态：已确认\n确认记录：业务接受 draft-1。')
        confirmed = confirmed.replace('> 状态：草稿', '> 状态：已确认')
        self.assertTrue(self.validate(confirmed, prototype=False)['valid'])
        self.assertFalse(self.validate(confirmed + '\n### Q1 待决定\n关联FR-01，需业务决定。', prototype=False)['valid'])
        changed = confirmed.replace('> 产品版本：draft-1', '> 产品版本：draft-2').replace('显示申请已提交', '显示申请已拒绝')
        self.assertFalse(self.validate(changed, prototype=False, baselines=[confirmed])['valid'])
        mixed = HTML.replace('FR-001', 'FR-01').replace('AC-001', 'AC-01').replace('AC-002', 'AC-02').replace('AC-003', 'AC-03')
        self.assertTrue(self.validate(legacy, html=mixed)['valid'])
        self.assertFalse(self.validate(legacy.replace('AC-02', 'AC-01'), prototype=False)['valid'])

    def test_source_root_allows_existing_evidence_links_but_not_untrusted_paths_or_prototype_assets(self):
        source = self.directory / 'source'; source.mkdir()
        delivery = self.directory / 'delivery'; delivery.mkdir()
        self.directory = delivery
        (source / 'ClaimRecord.java').write_text('class ClaimRecord {}')
        linked = PRD + '\n[字段依据](../source/ClaimRecord.java)\n'
        self.assertFalse(self.validate(linked, prototype=False)['valid'])
        self.assertTrue(self.validate(linked, prototype=False, source_roots=[source])['valid'])
        outside = self.directory.parent / 'secret.txt'; outside.write_text('not authorized')
        for target in ('../missing.java', '../source/missing.java', '../../escape.md', '%2e%2e/secret.txt', str(outside), 'javascript:alert(1)'):
            with self.subTest(target=target):
                self.assertFalse(self.validate(PRD + f'\n[依据](<{target}>)\n', prototype=False, source_roots=[source])['valid'])
        (source / 'escape.java').symlink_to(outside)
        self.assertFalse(self.validate(PRD + '\n[依据](../source/escape.java)\n', prototype=False, source_roots=[source])['valid'])
        self.assertFalse(self.validate(PRD, html=HTML + '<script src="../source/ClaimRecord.java"></script>', source_roots=[source])['valid'])
        self.assertFalse(self.validate(PRD, prototype=False, source_roots=[source/'ClaimRecord.java'])['valid'])

    def test_external_css_source_is_evidence_not_a_prototype_stylesheet(self):
        source = self.directory / 'source'; source.mkdir()
        delivery = self.directory / 'delivery'; delivery.mkdir()
        self.directory = delivery
        (source / 'screen.css').write_text('body { background: url(icon.svg); }')
        (source / 'icon.svg').write_text('<svg/>')
        document = PRD + '\n[现有样式依据](../source/screen.css)\n'
        self.assertTrue(self.validate(document, prototype=False, source_roots=[source])['valid'])
        # A stylesheet shipped as prototype input still requires contained resources.
        (delivery / 'screen.css').write_text('body { background: url(../source/icon.svg); }')
        self.assertFalse(self.validate(PRD + '\n[原型样式](screen.css)\n', prototype=False, source_roots=[source])['valid'])

    def test_checked_in_complete_example_passes_the_actual_structural_gate(self):
        example = PRODUCT / "assets/examples"
        result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_product_doc.py"), "--file", str(example / "prd.md"), "--prototype", str(example / "prototype.html")], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_valid_draft_has_complete_requirement_and_scenario_links(self):
        report = self.validate()
        self.assertTrue(report["valid"], report)
        self.assertTrue(report["prototypeChecked"])

    def test_prd_only_has_no_implicit_browser_or_prototype_claim(self):
        report = self.validate(prototype=False)
        self.assertTrue(report["valid"], report)
        self.assertFalse(report["prototypeChecked"])

    def test_document_rejects_missing_duplicate_and_unresolved_contracts(self):
        cases = {
            "version": PRD.replace("> 产品版本：draft-1", ""),
            "status": PRD.replace("> 状态：草稿", "> 状态：完成"),
            "title": PRD.replace("# 退款审批示例", ""),
            "duplicate": PRD.replace("## 未决事项", "### FR-001 重复需求\n## 未决事项"),
            "source": PRD.replace("依据：SRC-001", "依据：SRC-999"),
            "empty source": PRD.replace("这是模拟示例设定，不是实际业务决定。", ""),
            "scenario": PRD.replace("AC-002", "AC-001"),
            "missing acceptance": PRD[:PRD.index("#### AC-001")],
            "empty acceptance": PRD.replace("提交有效输入，显示申请已提交。", ""),
            "confirmation": PRD.replace("> 状态：草稿", "> 状态：已确认"),
            "question": PRD.replace("> 状态：草稿", "> 状态：已确认").replace("状态：待确认", "状态：已确认\n确认记录：用户在评审会议明确接受 draft-1。").replace("无。", "### Q-001 阈值尚未决\n关联 FR-001，需业务负责人决定。"),
            "assumed confirmation": PRD.replace("状态：待确认", "状态：已确认\n确认记录：建议采用默认值。"),
            "prototype flag": PRD.replace("原型：是", "原型：随意"),
            "placeholder": PRD + "\n<!-- TEMPLATE: 未替换 -->\n",
            "fenced declarations": "# 示例\n> 产品版本：draft-1\n> 状态：草稿\n```markdown\n" + PRD + "\n```",
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                self.assertFalse(self.validate(prd=content)["valid"], name)

    def test_confirmation_requires_record_but_does_not_prove_approval(self):
        confirmed = PRD.replace("> 状态：草稿", "> 状态：已确认").replace("状态：待确认", "状态：已确认\n确认记录：用户在评审会议明确接受 draft-1。")
        self.assertTrue(self.validate(prd=confirmed)["valid"])
        self.assertFalse(self.validate(prd=confirmed.replace("确认记录：用户在评审会议明确接受 draft-1。", ""))["valid"])
        self.assertFalse(self.validate(prd=confirmed.replace("接受 draft-1", "接受 draft-0"))["valid"])
        self.assertFalse(self.validate(prd=confirmed.replace("接受 draft-1", "接受 draft-10"))["valid"])

    def test_acceptance_heading_scope_ends_at_unrelated_peer_or_parent(self):
        for heading in ("# 附录", "## 附录", "### 评审备注", "### FR-999", "#### FR-002 非法需求"):
            with self.subTest(heading=heading):
                content = PRD.replace("#### AC-001 正常申请", heading + "\n说明。\n#### AC-001 正常申请")
                self.assertFalse(self.validate(prd=content, prototype=False)["valid"])
        self.assertTrue(self.validate(prd=PRD.replace("#### AC-002", "##### 辅助说明\n补充上下文。\n#### AC-002"))["valid"])

    def test_baseline_carries_unchanged_approval_without_rewriting_record(self):
        old = PRD.replace("状态：待确认", "状态：已确认\n确认记录：业务负责人接受 draft-1。")
        current = old.replace("> 产品版本：draft-1", "> 产品版本：draft-2")
        report = self.validate(prd=current, prototype=False, baselines=[old])
        self.assertTrue(report["valid"], report)
        third = current.replace("draft-2", "draft-3")
        self.assertTrue(self.validate(prd=third, prototype=False, baselines=[old, current])["valid"])
        self.assertFalse(self.validate(prd=current, prototype=False)["valid"])

    def test_unrelated_requirement_links_do_not_invalidate_unchanged_confirmation(self):
        from validate_product_doc import approval_content
        old = (ROOT / 'scripts/fixtures/product-behavior/revision-baseline.md').read_text()
        current = old.replace('revision-1\n', 'revision-2\n', 1).replace('500', '1000')
        (self.directory / 'input.txt').write_text('FR-001 threshold only')
        for before in ('达到1000元进入待审批，低于阈值进入处理中。',
                       '本样本的审批分流设定，真实产品仍需业务确认。'):
            with self.subTest(owner=before):
                linked = current.replace(before, before + '\n[本次输入](input.txt)')
                report = self.validate(prd=linked, prototype=False, baselines=[old])
                self.assertTrue(report['valid'], report)
                self.assertEqual(approval_content(old)['FR-002'], approval_content(linked)['FR-002'])
        invalid = current.replace('达到1000元进入待审批，低于阈值进入处理中。',
                                  '达到1000元进入待审批，低于阈值进入处理中。\n[输入](missing.txt)')
        self.assertFalse(self.validate(prd=invalid, prototype=False, baselines=[old])['valid'])

    def test_owned_shared_and_ambiguous_references_still_require_confirmation(self):
        old = (ROOT / 'scripts/fixtures/product-behavior/revision-baseline.md').read_text()
        (self.directory / 'input.txt').write_text('unfrozen')
        additions = [
            ('客服按订单号查询；不存在时显示空状态，不创建申请。', '\n[查询依据](input.txt)'),
            ('以下查询确认仅用于回归测试，不是实际业务授权。', '\n[查询依据](input.txt)'),
            ('## 未决事项', '\n[共享依据](input.txt)'),
            ('无其他未决事项；阈值规则保持待确认。', '\n### SRC-003 未绑定来源\n[依据](input.txt)'),
        ]
        for before, addition in additions:
            with self.subTest(scope=before):
                baseline = old.replace(before, before + addition)
                current = baseline.replace('revision-1\n', 'revision-2\n', 1)
                self.assertFalse(self.validate(prd=current, prototype=False, baselines=[baseline])['valid'])
        # A reference-style link resolved by another section must not be mistaken for its property.
        baseline = old.replace('真实产品仍需业务确认。',
                               '真实产品仍需业务确认。\n\n[external]: input.txt\n\n[直接引用](input.txt)')
        baseline = baseline.replace('客服按订单号查询；', '[查询依据][external]\n客服按订单号查询；')
        current = baseline.replace('revision-1\n', 'revision-2\n', 1)
        self.assertFalse(self.validate(prd=current, prototype=False, baselines=[baseline])['valid'])
        # CommonMark deduplicates repeated definitions globally, unlike isolated sections.
        for repeated in ('[external]: input.txt', '[EXTERNAL]: input.txt'):
            with self.subTest(repeated=repeated):
                duplicate = baseline.replace('达到500元进入待审批，低于阈值进入处理中。',
                                             '达到500元进入待审批，低于阈值进入处理中。\n\n'+repeated+'\n')
                current = duplicate.replace('revision-1\n', 'revision-2\n', 1)
                self.assertFalse(self.validate(prd=current, prototype=False, baselines=[duplicate])['valid'])

    def test_inline_heading_markers_cannot_drop_approved_source_rules(self):
        old = PRD.replace("### FR-001 申请退款", "### FR-001 显示 `#### 标题` 文本").replace(
            "状态：待确认", "状态：已确认\n确认记录：业务负责人接受 draft-1。")
        current = old.replace("> 产品版本：draft-1", "> 产品版本：draft-2")
        self.assertTrue(self.validate(prd=current, prototype=False, baselines=[old])["valid"])
        changed = current.replace("这是模拟示例设定，不是实际业务决定。", "退款阈值改为 1000。")
        self.assertFalse(self.validate(prd=changed, prototype=False, baselines=[old])["valid"])

    def test_nested_contract_headings_cannot_own_outside_metadata_or_scenarios(self):
        for heading in ("### FR-001 申请退款", "#### AC-001 正常申请", "### SRC-001 测试设定"):
            for prefix in ("> ", "- ", "1. "):
                with self.subTest(heading=heading, prefix=prefix):
                    content = PRD.replace(heading, prefix + heading + "\n")
                    self.assertFalse(self.validate(prd=content, prototype=False)["valid"])

    def test_baseline_does_not_automatically_confirm_unfrozen_external_material(self):
        old = PRD.replace("状态：待确认", "状态：已确认\n确认记录：业务负责人接受 draft-1。")
        old = old.replace("这是模拟示例设定", "[业务规则](https://example.invalid/rule)：这是模拟示例设定")
        current = old.replace("> 产品版本：draft-1", "> 产品版本：draft-2")
        self.assertFalse(self.validate(prd=current, prototype=False, baselines=[old])["valid"])

    def test_baseline_cannot_hide_changed_code_rule(self):
        old = PRD.replace("状态：待确认", "状态：已确认\n确认记录：业务负责人接受 draft-1。")
        old = old.replace("这是模拟示例设定，不是实际业务决定。", "业务规则如下。\n```text\nthreshold = 500\n```")
        current = old.replace("> 产品版本：draft-1", "> 产品版本：draft-2").replace("threshold = 500", "threshold = 1000")
        self.assertFalse(self.validate(prd=current, prototype=False, baselines=[old])["valid"])

    def test_baseline_detects_inline_visibility_and_same_version_rule_changes(self):
        old = PRD.replace("状态：待确认", "状态：已确认\n确认记录：业务负责人接受 draft-1。")
        for replacement in ("<del>申请后显示审批状态。</del>", "<span hidden>申请后显示审批状态。</span>"):
            current = old.replace("> 产品版本：draft-1", "> 产品版本：draft-2").replace("申请后显示审批状态。", replacement)
            self.assertFalse(self.validate(prd=current, prototype=False, baselines=[old])["valid"])
        changed = old.replace("申请后显示审批状态。", "申请后直接成功。")
        self.assertFalse(self.validate(prd=changed, prototype=False, baselines=[old])["valid"])
        renewed = changed.replace("业务负责人接受 draft-1。", "业务负责人在第二次评审重新确认 draft-1。")
        self.assertTrue(self.validate(prd=renewed, prototype=False, baselines=[old])["valid"])

    def test_baseline_preserves_list_grouping_and_ordered_start(self):
        old = PRD.replace("状态：待确认", "状态：已确认\n确认记录：业务负责人接受 draft-1。")
        for original, changed in (("- 满足以下条件：\n  - 有效订单\n  - 已退货", "- 满足以下条件：\n- 有效订单\n- 已退货"),
                                  ("1. 审批\n2. 执行", "2. 审批\n3. 执行"),
                                  ("**必须**审批。", "必须审批。")):
            baseline = old.replace("申请后显示审批状态。", original)
            current = baseline.replace("> 产品版本：draft-1", "> 产品版本：draft-2").replace(original, changed)
            self.assertFalse(self.validate(prd=current, prototype=False, baselines=[baseline])["valid"])

    def test_baseline_rejects_changed_semantics_rules_shared_context_and_forged_records(self):
        old = PRD.replace("状态：待确认", "状态：已确认\n确认记录：业务负责人接受 draft-1。")
        current = old.replace("> 产品版本：draft-1", "> 产品版本：draft-2")
        for before, after in (("申请后显示审批状态。", "申请后直接成功。"),
                              ("负数不能提交", "负数可以提交"),
                              ("这是模拟示例设定", "这是另外的业务规则"),
                              ("无。", "共享术语发生变化。"),
                              ("业务负责人接受", "系统自动接受")):
            with self.subTest(before=before):
                self.assertFalse(self.validate(prd=current.replace(before, after), prototype=False, baselines=[old])["valid"])
        invalid = old.replace("业务负责人接受", "建议采用默认值")
        self.assertFalse(self.validate(prd=current, prototype=False, baselines=[invalid])["valid"])
        pending = current.replace("状态：已确认", "状态：待确认")
        self.assertTrue(self.validate(prd=pending, prototype=False, baselines=[old])["valid"])

    def test_prototype_rejects_stale_unknown_and_mismatched_claims(self):
        cases = {
            "stale": HTML.replace("draft-1", "draft-2"),
            "unknown requirement": HTML.replace("FR-001", "FR-999"),
            "unknown scenario": HTML.replace("AC-001", "AC-999"),
            "missing scenario": HTML.replace('data-scenario="AC-002"', ""),
            "orphan scenario": HTML.replace('data-requirement="FR-001"', ""),
            "duplicate version": HTML.replace("</head>", '<meta name="product-version" content="draft-1"></head>'),
            "javascript URL": HTML.replace("</main>", '<a href="javascript:alert(1)">跳转</a></main>'),
            "external script": HTML.replace("</head>", '<script src="https://example.invalid/demo.js"></script></head>'),
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                self.assertFalse(self.validate(html=content)["valid"], name)

    def test_local_resources_stay_inside_delivery_directory(self):
        (self.directory / "style.css").write_text("body { color: black; }")
        self.assertTrue(self.validate(html=HTML.replace("</head>", '<link href="style.css" rel="stylesheet"></head>'))["valid"])
        for target in ("missing.png", "../outside.png", "%2e%2e/outside.png", "/tmp/outside.png", "file:///tmp/outside.png"):
            with self.subTest(target=target):
                self.assertFalse(self.validate(html=HTML.replace("</main>", f'<img src="{target}" alt="示例"></main>'))["valid"])
        outside = self.directory.parent / (self.directory.name + "-outside.css")
        outside.write_text("body{}")
        self.addCleanup(outside.unlink)
        (self.directory / "escape.css").symlink_to(outside)
        self.assertFalse(self.validate(html=HTML.replace("</head>", '<link href="escape.css" rel="stylesheet"></head>'))["valid"])

    def test_prd_local_links_are_verified_and_https_sources_allowed(self):
        self.assertFalse(self.validate(prd=PRD + "\n[缺失](missing.md)")["valid"])
        self.assertFalse(self.validate(prd=PRD + "\n[逃逸](../outside.md)")["valid"])
        self.assertTrue(self.validate(prd=PRD + "\n[参考](https://example.invalid/doc)")["valid"])

    def test_missing_document_and_outside_prototype_return_structured_failure(self):
        script = ROOT / "scripts/validate_product_doc.py"
        self.assertTrue(script.is_file())
        result = subprocess.run([sys.executable, str(script), "--file", str(self.directory / "missing.md")], text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["valid"])
        nested = self.directory / "bundle"
        nested.mkdir()
        (nested / "prd.md").write_text(PRD)
        (self.directory / "outside.html").write_text(HTML)
        result = subprocess.run([sys.executable, str(script), "--file", str(nested / "prd.md"), "--prototype", str(self.directory / "outside.html")], text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)

    def test_scenarios_cannot_be_mapped_to_a_different_requirement(self):
        extra = "\n### FR-002 审批\n状态：待确认\n依据：SRC-001\n原型：否\n审批后展示结果。\n#### AC-004 审批通过\n操作后展示结果。\n"
        prd = PRD.replace("## 未决事项", extra + "\n## 未决事项")
        bad = HTML.replace('data-scenario="AC-001"', 'data-scenario="AC-004"')
        self.assertFalse(self.validate(prd=prd, html=bad)["valid"])

    def test_reserved_headings_cannot_bypass_the_requirement_contract(self):
        for heading in ("### FR-00X 非法编号", "## FR-002 错误层级", "##### AC-004 错误层级",
                        "### SRC-ABC 非法来源", "### Q-00X 未决", "### FR-002"):
            with self.subTest(heading=heading):
                self.assertFalse(self.validate(prd=PRD + "\n" + heading + "\n尚未确认。\n")["valid"])

    def test_empty_html_contract_attributes_return_structured_errors(self):
        for attribute in ("data-requirement", "data-scenario", "src", "href", "poster"):
            with self.subTest(attribute=attribute):
                self.assertFalse(self.validate(html=HTML.replace("</main>", f"<div {attribute}></div></main>"))["valid"])

    def test_reference_markdown_links_and_responsive_images_are_checked(self):
        (self.directory / "local.png").write_bytes(b"fixture")
        self.assertTrue(self.validate(prd=PRD + "\n[附件][ref]\n\n[ref]: local.png\n")["valid"])
        self.assertFalse(self.validate(prd=PRD + "\n[附件][ref]\n\n[ref]: ../outside.pdf\n")["valid"])
        self.assertTrue(self.validate(html=HTML.replace("</main>", '<img srcset="local.png 1x, local.png 2x" alt="模拟"></main>'))["valid"])
        for value in ("../outside.png 1x", "local.png 1x, https://example.invalid/image.png 2x"):
            with self.subTest(value=value):
                self.assertFalse(self.validate(html=HTML.replace("</main>", f'<img srcset="{value}" alt="模拟"></main>'))["valid"])

    def test_browser_base_resolution_cannot_escape_a_nested_delivery(self):
        nested = self.directory / "nested"; nested.mkdir()
        (self.directory / "prd.md").write_text(PRD)
        (self.directory / "anchor.html").write_text("anchor")
        (self.directory / "inside.png").write_bytes(b"local pixels")
        page = nested / "prototype.html"
        page.write_text(HTML.replace("</head>", '<base href="../anchor.html"></head>').replace("</main>", '<img src="../inside.png" alt="local"></main>'))
        result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_product_doc.py"), "--file", str(self.directory / "prd.md"), "--prototype", str(page)], text=True, capture_output=True)
        self.assertFalse(json.loads(result.stdout)["valid"], "Browser base URL differs from the parser directory")

    def test_duplicate_attributes_cannot_hide_the_browser_first_value(self):
        (self.directory / "inside.png").write_bytes(b"local pixels")
        for markup in ('<img src="../outside.png" src="inside.png" alt="test">',
                       '<div data-requirement="FR-999" data-requirement="FR-001"></div>',
                       '<img SRC="../outside.png" src="inside.png" alt="test">'):
            with self.subTest(markup=markup):
                self.assertFalse(self.validate(html=HTML.replace("</main>", markup + "</main>"))["valid"])

    def test_inline_and_local_stylesheet_resources_cannot_escape(self):
        (self.directory / "local.png").write_bytes(b"fixture")
        (self.directory / "style.css").write_text('body { background: url("local.png"); }')
        stylesheet = HTML.replace("</head>", '<link href="style.css" rel="stylesheet"></head>')
        self.assertTrue(self.validate(html=stylesheet)["valid"])
        (self.directory / "style.css").write_text('body { background: url("../outside.png"); }')
        self.assertFalse(self.validate(html=stylesheet)["valid"])
        (self.directory / "theme").write_text('body { background: url("../outside.png"); }')
        self.assertFalse(self.validate(html=HTML.replace("</head>", '<link href="theme" rel="stylesheet"></head>'))["valid"])
        for css in ('body{background:url(../outside.png)}', '@import "../outside.css";',
                    r'body{background:u\72l(../outside.png)}'):
            with self.subTest(css=css):
                self.assertFalse(self.validate(html=HTML.replace("</head>", f"<style>{css}</style></head>"))["valid"])
        self.assertFalse(self.validate(html=HTML.replace("</main>", '<div style="background:url(../outside.png)"></div></main>'))["valid"])

    def test_markdown_headings_allow_three_spaces_without_hiding_contracts(self):
        for spaces in ("", " ", "  ", "   "):
            with self.subTest(spaces=len(spaces)):
                indented = "\n".join(spaces + line if line.startswith("#") else line for line in PRD.splitlines())
                self.assertTrue(self.validate(prd=indented)["valid"])
                self.assertFalse(self.validate(prd=PRD + f"\n{spaces}### FR-002 未完整需求\n缺少依据与验收。\n")["valid"])
                self.assertFalse(self.validate(prd=PRD + f"\n{spaces}### FR-00X 非法编号\n未确认。\n")["valid"])
                confirmed = PRD.replace("> 状态：草稿", "> 状态：已确认").replace("状态：待确认", "状态：已确认\n确认记录：用户接受 draft-1。")
                self.assertFalse(self.validate(prd=confirmed + f"\n{spaces}### Q-001 未决事项\n审批口径尚未决定。\n")["valid"])
        self.assertTrue(self.validate(prd=PRD + "\n```markdown\n   ### Q-001 代码示例\n```\n")["valid"])

    def test_nonempty_single_character_titles_are_valid_at_each_heading_indent(self):
        for spaces in ("", " ", "  ", "   "):
            with self.subTest(spaces=len(spaces)):
                self.assertTrue(self.validate(prd=PRD.replace("# 退款审批示例", spaces + "# 退"))["valid"])
        self.assertFalse(self.validate(prd=PRD.replace("# 退款审批示例", "#   "))["valid"])
        self.assertFalse(self.validate(prd=PRD.replace("# 退款审批示例", "# ###"))["valid"])
        self.assertTrue(self.validate(prd=PRD.replace("# 退款审批示例", "# 退 ###"))["valid"])
        for title in ("# `###`", r"# \###"):
            with self.subTest(title=title):
                self.assertTrue(self.validate(prd=PRD.replace("# 退款审批示例", title))["valid"])

    def test_only_markdown_fences_hide_declarations(self):
        confirmed = PRD.replace("> 状态：草稿", "> 状态：已确认").replace(
            "状态：待确认", "状态：已确认\n确认记录：用户接受 draft-1。")
        question = "   ### Q-001 未决事项\n审批口径尚未决定。\n"
        for marker in ("    ```", "\t```", "    ~~~", "```bad`info"):
            with self.subTest(marker=marker):
                self.assertFalse(self.validate(prd=confirmed + "\n" + marker + "\n" + question)["valid"])
        for marker in ("```", "   ~~~~"):
            with self.subTest(marker=marker):
                self.assertTrue(self.validate(prd=confirmed + "\n" + marker + "\n" + question + marker + "\n")["valid"])
        self.assertTrue(self.validate(prd=confirmed + "\n```\n```not-a-closing-fence\n" + question + "```\n")["valid"])
        self.assertFalse(self.validate(prd=confirmed + "\n```html\n<!--\n```\n" + question)["valid"])

    def test_inline_comment_examples_do_not_hide_visible_questions(self):
        confirmed = PRD.replace("> 状态：草稿", "> 状态：已确认").replace(
            "状态：待确认", "状态：已确认\n确认记录：用户接受 draft-1。")
        question = "### Q-001 未决事项\n审批口径尚未决定。\n"
        for ticks in ("`", "``", "```"):
            with self.subTest(ticks=ticks):
                text = f"\n示例：{ticks}<!--{ticks}\n{question}示例：{ticks}-->{ticks}\n"
                self.assertFalse(self.validate(prd=confirmed + text)["valid"])
        self.assertFalse(self.validate(prd=confirmed + "\n\\<!--\n" + question + "-->\n")["valid"])
        self.assertTrue(self.validate(prd=confirmed + "\n<!--\n```\n" + question + "-->\n")["valid"])
        self.assertTrue(self.validate(prd=confirmed + "\n<!--\n" + question)["valid"])

    def test_commonmark_containers_cannot_hide_visible_questions(self):
        confirmed = PRD.replace("> 状态：草稿", "> 状态：已确认").replace(
            "状态：待确认", "状态：已确认\n确认记录：用户接受 draft-1。")
        question = "   ### Q-001 可见未决事项\n审批口径尚未决定。\n"
        for prefix in ("    <!--", "\t<!--", "> <!--", "- <!--", "1. <!--",
                       "- ```\n  <!--\n  ```"):
            with self.subTest(prefix=prefix):
                self.assertFalse(self.validate(prd=confirmed + "\n" + prefix + "\n\n" + question)["valid"])
        self.assertFalse(self.validate(prd=confirmed + "\n> ### Q-001 引用中的未决事项\n> 仍未决定。\n")["valid"])
        for example in ("    ### Q-001 缩进代码示例", "`### Q-001 行内代码示例`",
                        "\\### Q-001 转义文本", "<!--\n### Q-001 注释示例\n-->"):
            with self.subTest(example=example):
                self.assertTrue(self.validate(prd=confirmed + "\n" + example + "\n")["valid"])

    def test_commonmark_resources_follow_parsed_destinations(self):
        (self.directory / "file(name).md").write_text("fixture")
        self.assertTrue(self.validate(prd=PRD + "\n[附件](file(name).md)\n")["valid"])
        for target in ("missing(name).md", "../outside(name).md", "file:///tmp/outside.md", "javascript:alert(1)"):
            with self.subTest(target=target):
                self.assertFalse(self.validate(prd=PRD + f"\n[附件](<{target}>)\n")["valid"])
        self.assertFalse(self.validate(prd=PRD + "\n![截图][image]\n\n[image]: missing(name).png\n")["valid"])
        self.assertFalse(self.validate(prd=PRD + "\n[unused]: ../outside.md\n")["valid"])
        for example in ("`[示例](missing.md)`", "\\[示例](missing.md)",
                        "<!-- [示例](missing.md) -->", "```\n[示例](missing.md)\n```"):
            with self.subTest(example=example):
                self.assertTrue(self.validate(prd=PRD + "\n" + example + "\n")["valid"])

    def test_missing_markdown_dependency_returns_actionable_json(self):
        document = self.directory / "prd.md"
        document.write_text(PRD)
        script = self.directory / "validate_product_doc.py"
        script.write_text((ROOT / "scripts/validate_product_doc.py").read_text())
        result = subprocess.run([sys.executable, "-S", str(script),
                                 "--file", str(document)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        value = json.loads(result.stdout)
        self.assertFalse(value["valid"])
        self.assertIn("requirements-product.txt", " ".join(value["problems"]))
        command = value["problems"][0].split("请执行 ", 1)[1]
        self.assertEqual(shlex.split(command)[-1], str(self.directory / "requirements-product.txt"))
        self.assertEqual(result.stderr, "")

    def test_object_data_resources_are_local_existing_and_inside_the_bundle(self):
        (self.directory / "receipt.pdf").write_bytes(b"fixture")
        self.assertTrue(self.validate(html=HTML.replace("</main>", '<object data="receipt.pdf"></object></main>'))["valid"])
        for attribute in ('data="../outside.pdf"', 'data="%2e%2e/outside.pdf"',
                          'data="missing.pdf"', 'data="https://example.invalid/receipt.pdf"', 'data'):
            with self.subTest(attribute=attribute):
                self.assertFalse(self.validate(html=HTML.replace("</main>", f'<object {attribute}></object></main>'))["valid"])
        outside = self.directory.parent / (self.directory.name + "-outside.pdf")
        outside.write_bytes(b"outside")
        self.addCleanup(outside.unlink)
        (self.directory / "escape.pdf").symlink_to(outside)
        self.assertFalse(self.validate(html=HTML.replace("</main>", '<object data="escape.pdf"></object></main>'))["valid"])


if __name__ == "__main__":
    unittest.main()
