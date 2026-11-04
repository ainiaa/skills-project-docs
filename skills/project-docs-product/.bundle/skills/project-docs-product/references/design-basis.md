# 产品方法的参考与采用边界

2026-10-27核对具体文件；下列提交用于追溯所读版本，不代表安装、升级或调用这些项目。仅借鉴方法，未复制其脚本或模板全文。日常生成按现有规范工作，不要求联网读取参考项目。

| 实际参考 | 采用与现有落点 | 保留的边界 |
|---|---|---|
| [phuryn/pm-skills：create-prd](https://github.com/phuryn/pm-skills/blob/07b34f64ee828df08953f505b7f747aef85ae7c6/pm-execution/skills/create-prd/SKILL.md) | 问题、用户任务、改前改后与方案形成因果关系；落实到input-and-quality.md的推荐方案判断及读者模板开篇。 | 不强制篇幅、市场分析或固定章节，不编造收益；完整性以能支持本期决定为准。 |
| [product-on-purpose/pm-skills：PRD模板](https://github.com/product-on-purpose/pm-skills/blob/f943d9589bfe9db06fac2641f9740987ff9b3aee/skills/deliver-prd/references/TEMPLATE.md) | 开篇关联问题、方案、目标用户及成功结果；落实到读者模板，边界及未决仍沿用现有章节。 | 不整套套用长模板、AI评测或代理执行章节，不为补栏目发明指标。 |
| [GitHub Spec Kit：规格模板](https://github.com/github/spec-kit/blob/ee94598c3c87ae231027b22fb2be2b5a13e8820f/templates/spec-template.md) | 按重要用户任务组织场景，以前提、操作和可观察结果表达验收；落实到读者模板，具体状态及数值继续按已有走读核实。 | 不强制所有任务都能独立部署，不复制分支、开发计划或代码生成流程。 |
| [OpenSpec：spec-driven schema](https://github.com/Fission-AI/OpenSpec/blob/6d04a1b58dedc95729d34e4f223d9d483aae210a/schemas/spec-driven/schema.yaml) | 业务行为与实现设计分层，修改已有要求保留完整上下文；复用reading-and-change.md的主文/技术补充分工及workflow.md的定点修订、保留走读。 | 已有能力不重复造流程；不强制新增proposal/spec/design/tasks目录或引入其CLI。 |
| [Anthropic：web-artifacts-builder](https://github.com/anthropics/skills/blob/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/web-artifacts-builder/SKILL.md) | 可实际查看和移交的HTML成果；复用prototype.md已有的自包含HTML、共享模拟状态、导航与浏览器验收。入口区分HTML阅读版和可点击原型。 | 原型仅按明确要求；不复制React/组件脚手架，不采用其测试可选策略，不以说明页或截图代替已要求的交互原型。 |

这些项目的方法不能证明本Skill的成品质量。结构检查只核声明和资源；实际效果仍按evaluation.md，以原始输入、真实成品及独立评判核对，不将参考项目的能力归算为本Skill已验证能力。
