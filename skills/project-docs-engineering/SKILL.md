---
name: project-docs-engineering
description: Prepare and review engineering solutions for project setup, technical and database design, API mocks, migrations, test strategy, quality, security, performance, and release preparation. Use Product for business requirements and PRDs, Lifecycle for cross-stage coordination, and Converge for authorized implementation and verification.
---

# Project Docs Engineering

Turn established requirements and repository evidence into engineering decisions, designs, validation strategies, and release preparations. Use the methods relevant to the task and hand authorized implementation to the existing engineering controller.

[中文文档 / Chinese documentation](https://github.com/ainiaa/skills-project-docs/blob/main/README.zh-CN.md)

若当前 Skill 目录下存在 `.bundle` 且其 `../../` 不是本集合的 Git 检出，先读取 `.bundle/skills/project-docs-engineering/GUIDE.md` 并以该目录为 Skill 真实目录；共享脚本、资料与其他能力来自同一快照。独立安装通过 `npx skills update project-docs-engineering` 更新，按实际作用域加 `-g` 或 `-p`。

开始当前专项前读取[阶段执行检查点](.bundle/skills/project-docs-lifecycle/references/quality-and-trace.md#执行检查点)：设计及测试策略用L4，代码实施/评审证据接Converge的L5，实际测试/质量结果用L6，发布准备用L8；实际部署及支持/效果分别按授权使用L9/L10。交付前读回方案、代码/测试或真实报告，逐项给结果推导、失败恢复和当前产物引用；未执行项保留缺口，方案不能冒充执行。只核本次实际阶段，不增加第二个工程控制器或全套生命周期资料。 详细检查的来源、适用性和验证映射按该节逐项落实，新任务机器验收使用checkpoint并冻结--target；项目检查绑定冻结输入，必要独立复核/旅程要求随原verification执行，见该节。

## 选择当前工作

| 目标 | 按需读取 | 产物 |
|---|---|---|
| 项目扫描/接入、初始化、服务/应用/模块骨架、工程规范 | [项目工程](references/project.md) | 源码基线、工程方案、构建与接线验证 |
| 技术/API/数据库方案、Mock、迁移、国际化、UI技术实现 | [设计方法](references/design.md) | 技术决定、契约、变更及验证方案 |
| 测试地基、E2E、质量、lint、安全、性能 | [质量方法](references/quality.md) | 真实命令、测试策略、专项报告与未验证项 |
| 版本、变更日志、发布准备、部署手册 | [发布准备](references/release.md) | 可审阅的版本变更、发布与恢复步骤 |

只加载当前专项。不为单项设计补建全生命周期记录，也不要求完整 PRD；已有需求足够时直接使用。业务规则未决时按[Product 指南](https://github.com/ainiaa/skills-project-docs/blob/main/skills/project-docs-product/SKILL.md)交接，优先读取当前快照附带的指南，或使用宿主已安装的 `project-docs-product`。技术待核实由工程取证，不能用技术假设代替业务决定。正式 PRD、FR/AC、业务验收标准及交互/视觉原型归 Product；本 Skill 不再生成第二份 PRD。API 文档、源码架构总览和图源分别复用 API、Overview、Diagram。

## 与执行及交接的边界

用户仅要求方案时交付设计。已授权实现且显式选择 Converge 时读取其实际可用入口，沿同一事项使用 `native-v1`，由其负责计划、TDD、实现/修复/重构、代码评审、验证与终态；本 Skill 提供专项依据，不创建 workflow provider、任务库或执行循环。已有 work item 沿原路径接续，不重登记同范围任务；已有设计只补缺口，不重跑整套前置流程。

方案与文档可独立交付。未选择 Converge 时，已授权代码工作遵循项目规范和 TDD，但不能声称已通过 Converge 托管验收，不自动安装执行器。Converge 也可独立执行局部任务，无需先运行 Engineering、Product 或 Lifecycle。

跨阶段工作按 [Lifecycle 协调资料](.bundle/skills/project-docs-lifecycle/references/coordination.md)交接，携带同一业务身份、输入版本、设计决定、变更文件、真实验证、未决及恢复条件。任务/状态汇总、业务关系、UAT、发布结果、复盘和效果由 Lifecycle 维护；它不反向启动第二个工程流程。发布方案不授予真实部署、提交、tag、推送或外部写入权限。

## 交付

需要完整输入选择及完结后接续时按[Engineering交接示例](assets/examples/iteration-handoff/README.md)组织PRD、设计、测试策略与附件映射；示例只作合成演练，不代替真实确认或测试结果。

沿项目既有位置和规范保存必要产物，说明输入来源/版本、方案与现状的差异、验证方式和未覆盖部分。普通专业方法不依赖第三方 PDLC；不调用 `/pdlc-*` 或写其状态。方法改编的完整 MIT 声明见[第三方声明](.bundle/references/third-party-notices.md)，职责与完整能力归属见[所有权说明](.bundle/docs/engineering-ownership.md)。
