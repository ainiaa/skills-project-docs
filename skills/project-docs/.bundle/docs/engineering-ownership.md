# 产品研发套件：能力归属与交接

作者：Jeff.Liu

Project Docs 与 Converge 独立使用、验证和发布。显式选择联动时，同一任务只使用一个工程控制器。第三方 PDLC 无需安装，完整[38项能力归属](https://github.com/ainiaa/skills-project-docs/blob/main/docs/pdlc-capability-map.md)用于迁移核对，不是每次工作的必读材料。

| 主责 | 入口与能力 | 接收 / 交付 |
|---|---|---|
| Product | `project-docs-product`：发现、研究、投入决定、业务规则、唯一正式 PRD、FR/AC、交互/视觉设计与原型、需求评审和修订 | 原始资料→真实业务决定与同版正式输入；不复制第二份 PRD |
| Engineering | `project-docs-engineering`：接入/初始化/脚手架、规范、技术/API/数据库设计、Mock、迁移、国际化、测试策略/地基、E2E、lint、质量、安全、性能、版本和部署准备 | 需求与源码→工程决定、专项产物及验证依据；实现时沿项目规范或用户选定的执行入口 |
| Lifecycle | `project-docs-lifecycle`：跨阶段身份/版本/证据/依赖、任务状态汇总、业务关系与影响、交接、UAT、发布结果、复盘、效果追踪 | 实际产物与权威系统结果→协调视图、责任人与下一动作；不代签或代部署 |
| Converge | Converge Suite：有限计划、TDD、实现/修复/重构、代码评审、工程证据、工作项状态/恢复与工程终态 | 冻结范围→验证过的工程结果；不重做 Product 流程 |
| 文档与图 | Overview / API / Diagram：源码现状、架构总览、上手、接口资料及可编辑图源 | 工程与产品资料→专业产物；不接管执行 |
| Host | 宿主进度、状态栏、Hook、权限与派发 | 仅使用实际可用能力；不自动移植第三方全局设置 |

## 选择入口与避免重复

- 只写/修订 PRD 或产品原型：Product；已有第三方 PRD 沿原正式主文和身份核对接续，不再运行生成入口。
- 只做数据库、Mock、安全、性能或发布方案：Engineering 按需读取一个方法，方案可独立完成；不先建 Lifecycle 或强制完整 PRD。
- 实现/修复/重构：沿项目规范执行；显式选择 Converge 时由它负责，可读取 Engineering 专项依据。
- 从问题推进到验收、上线和效果：Lifecycle 组织上述能力；当前范围已经明确就从当前阶段接续。
- 只要源码说明、API 文档或图：直接使用 Overview/API/Diagram。

## 输入、证据与恢复

正式需求和冻结工具仍由 Product 维护：[输入接管](../skills/project-docs-product/references/engineering.md)、[修订与恢复](../skills/project-docs-product/references/revision.md)。工程证据接回由 Lifecycle 的[证据接口](../skills/project-docs-lifecycle/references/engineering-evidence.md)负责。六类业务关系工具复用Lifecycle现有记录、版本/CAS与历史；只有depends_on传播影响，不增加工程状态机。业务关系和效果方法见[协调资料](../skills/project-docs-lifecycle/references/coordination.md)。迁移保留工作项身份、历史、CAS、附件摘要或失败预算。

Engineering 不创建独立状态或隐式触发实现；已有 Converge 工作项沿返回路径续接。工程通过、UAT、发布批准、实际部署和效果分别保留事实；一个通过不能代替其他阶段。

## Converge

显式选择 Converge 时，由它负责本次工程执行。`native-v1` 无需安装 Project Docs 或 PDLC。工程计划/任务、TDD、实现、修复、重构、代码评审、重试、恢复与清场均沿现有机制。Product/Engineering/Lifecycle 是输入、专业方法与业务证据层，不是 workflow provider。第三方仅显式或原冻结兼容，不自动扫描、安装或写入其状态。

## 能力与验收边界

七个 Project Docs 入口共享同一维护来源，独立安装包包含本入口和直接协作所需的资料。旧 Lifecycle 工程方法路径保留跳转，不保留第二份正文。方法覆盖不等于通用生成器、迁移执行器、CI/CD 或指标连接器已实现。真实 Java 私有依赖、CI/CD、部署、指标和宿主模型路由仍需实接验收；本次不增加这些通用运行器。

原生完成档案支持[写前兼容预检与显式后继迭代](../skills/project-docs-product/references/iterations.md)，旧任务不复活，下一轮沿同一业务身份建立新执行目标。Engineering资料冻结及演练见[交接示例](https://github.com/ainiaa/skills-project-docs/blob/main/skills/project-docs-engineering/assets/examples/iteration-handoff/README.md)。
