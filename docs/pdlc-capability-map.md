# PDLC 全能力盘点与自有承接

作者：Jeff.Liu

## 基线、结论与阅读方式

盘点对象是第三方 [kanfu-panda/pdlc-skills](https://github.com/kanfu-panda/pdlc-skills)，固定提交 `ef05bf20f9dc82fa5b90b9df7f11fb7d63d1d3fb`，共38个Skill，包含内部入口loop-run/settings。版权与完整MIT许可见[第三方声明](../references/third-party-notices.md)。本表描述能力去向，不代表38项真实项目自动化均已验收。

主路径为Project Docs + Converge native-v1；PDLC无需安装，仅作已有项目的可选人工交接来源。Project Docs增加Engineering为第七入口，专业方法由Engineering维护；Product独占PRD与UI产品设计，Lifecycle专注协调。详见[职责归属](engineering-ownership.md)。Converge既有TDD/实现/评审/循环复用，不复制第三方执行引擎。全部入口和资源清单、原始前置信息及摘要见[机器清单](pdlc-capability-map.json)。

“复用/原生复用”表示使用现有自有能力；“方法迁入”表示已提供可执行的模型工作指引，自动化依赖项目现有命令；“原生/宿主替代”表示保留目的并改变机制，不承诺PDLC命令/状态协议兼容。功能方法覆盖、工具集成验证、真实岗位/环境验收分开报告。

## 38项逐项承接

| 第三方入口 | 主责（协作） | 承接方式与唯一资料 | 边界与差异 |
|---|---|---|---|
| `pdlc-add-app` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/project.md) | 识别现有布局后新增应用；真实构建/框架接线随项目验证 |
| `pdlc-add-service` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/project.md) | 沿用现有服务分层与父构建；无固定Java/Go等多栈生成器 |
| `pdlc-adopt` | Engineering（Converge / Overview / API / Diagram） | [已有能力+方法迁入](../skills/project-docs-engineering/references/project.md) | scan只读；init生成实现基线，不能冒充已确认PRD |
| `pdlc-api-mock` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/design.md) | 正常/空/边界/分页/错误样例；使用现有Mock机制，无通用Mock运行器 |
| `pdlc-arch` | Overview（Diagram） | [复用](../skills/project-docs-overview/SKILL.md) | 源代码架构总览和技术图；方案与已实现分开 |
| `pdlc-bootstrap` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/project.md) | 空项目最小方案和骨架；未选型不自动装依赖 |
| `pdlc-changelog` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/release.md) | Git证据→未发布变更；不把草稿设计计作发布 |
| `pdlc-code-gen` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/project.md) | 已有单元内测试先行补模块；无独立多语言模板生成器 |
| `pdlc-db-design` | Engineering（Converge / Overview / API / Diagram） | [方法迁入](../skills/project-docs-engineering/references/design.md) | ER/约束/查询索引/迁移评审；沿项目约定 |
| `pdlc-db-migrate` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/design.md) | generate/diff/status/up/down工作方法；不连库、不虚报已执行，无通用迁移CLI |
| `pdlc-deploy` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/release.md) | 部署手册、冒烟/回退条件；无自动部署执行器 |
| `pdlc-design` | Engineering（Converge / Overview / API / Diagram） | [方法迁入](../skills/project-docs-engineering/references/design.md) | 按FR/AC做方案比较与设计评审；不写PDLC阶段状态 |
| `pdlc-e2e` | Engineering（Converge） | [已有能力+方法迁入](../skills/project-docs-engineering/references/quality.md) | 生成/执行由项目runner完成；非支持格式保留原证据，无通用结果解析器 |
| `pdlc-feature` | Lifecycle（Product / Engineering / Converge） | [原生复用](../skills/project-docs-lifecycle/references/lifecycle.md) | PRD→显式native接管→计划/TDD/实现/评审；发布另依授权 |
| `pdlc-fix` | Converge | [原生复用](engineering-ownership.md) | 复现/红灯/根因修复/回归/文档；不创建PDLC缺陷状态 |
| `pdlc-i18n` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/design.md) | 抽文案/key/locale/回退和占位符测试；翻译需语言审校 |
| `pdlc-implement` | Converge | [原生复用](engineering-ownership.md) | 设计和测试输入→实现→验证/复核；单一工程控制器 |
| `pdlc-lint` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/quality.md) | check/fix/setup沿用现有配置，无新的lint框架 |
| `pdlc-loop-next` | Converge | [原生替代](engineering-ownership.md) | 使用现有next/任务证据决定下一动作；不提供PDLC token协议别名 |
| `pdlc-loop-run` | Converge | [原生替代](engineering-ownership.md) | 有界任务/批次续作；无PDLC外层loop，宿主自动派发须实测 |
| `pdlc-onboard` | Overview | [复用](../skills/project-docs-overview/SKILL.md) | 环境、规范、核心流程、文档索引、已验命令 |
| `pdlc-perf` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/quality.md) | 基线至少3次中位数→逐项改→同环境复测；无测量只分析 |
| `pdlc-prd` | Product | [复用](../skills/project-docs-product/references/workflow.md) | 正式PRD、FR/AC、原型、来源/版本/真实确认，不重写第二份PRD |
| `pdlc-quality` | Engineering（Converge） | [已有能力+方法迁入](../skills/project-docs-engineering/references/quality.md) | 真实检查/阈值/流→test/PRD对账/报告；不代签放行，不复制quality专用CLI |
| `pdlc-refactor` | Converge | [原生复用](engineering-ownership.md) | 行为保持的测试与代码变更；native refactor契约 |
| `pdlc-relate` | Lifecycle（Converge） | [方法与原生工具](../skills/project-docs-lifecycle/references/coordination.md) | 六类关系set/query/impact/orphans/validate；原记录/CAS，不迁移PDLC状态协议 |
| `pdlc-retro` | Lifecycle（Converge） | [方法迁入](../skills/project-docs-lifecycle/references/coordination.md) | 真实交付/质量/耗时/阻断趋势；无数据无统计，不复制PDLC历史读取器 |
| `pdlc-review` | Converge（Product / Engineering） | [原生复用](engineering-ownership.md) | 文档评审与代码评审分流；同会话实现沿原Converge，不开第二控制器 |
| `pdlc-security` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/quality.md) | 先真实依赖/密钥扫描再审权限/注入等；无扫描器则未测量 |
| `pdlc-settings` | Host（Converge） | [宿主替代](engineering-ownership.md) | Claude statusline启停/展示和项目hooks不移植；没有自有等价设置CLI |
| `pdlc-ship` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/release.md) | 测试门、版本、CHANGELOG、发布说明与tag-after-merge策略；提交/tag/推送/CI另依授权 |
| `pdlc-standard` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/project.md) | 规范add/edit/archive/index就地维护，不创建feature历史 |
| `pdlc-status` | Lifecycle（Converge） | [原生复用](../skills/project-docs-lifecycle/references/coordination.md) | 阶段/任务/证据状态视图；不将PDLC已发布状态迁入自有记录 |
| `pdlc-task` | Converge | [原生复用](engineering-ownership.md) | plan/list/start/done/blocked/reopen沿现有计划工单，无重复任务库 |
| `pdlc-tdd` | Converge（Engineering） | [原生复用](engineering-ownership.md) | 真实红灯与绿灯、断言及必要回归；环境失败不算行为红灯 |
| `pdlc-test-setup` | Engineering（Converge） | [方法迁入](../skills/project-docs-engineering/references/quality.md) | 探测/验证/refresh真实命令，保留阈值；不自动接hooks/改CI |
| `pdlc-ui-design` | Product（Engineering） | [已有能力+方法迁入](../skills/project-docs-product/references/ui-design.md) | 页面/交互与正常/加载/空/错误状态，可点击原型按需 |
| `pdlc-ui-design-pro` | Product（Engineering） | [方法迁入](../skills/project-docs-product/references/ui-design.md) | 视觉系统/响应式/无障碍；缺外部设计Skill采用基础流程，不默认安装 |

`pdlc-review`包含多个模式：代码评审由Converge负责，PRD评审由Product负责，技术设计/测试计划评审由Engineering负责；机器清单的`modes`逐项保留，不因入口主责而丢失文档评审。

## 公共工具、模板与分发

| 上游组成 | 自有处理 | 仍需说明的差异 |
|---|---|---|
| pdlc-advance / guard / state-lint及状态历史 | Converge工作项/原生执行契约 + Lifecycle版本/依赖验证 | 不读取/改写第三方状态；无状态批量导入器 |
| pdlc-checks / test-commands / quality模板 | 使用项目真实检查、Converge证据工具及本集合AC关联 | 不复制checks键名或通用runner，非支持格式保留原报告 |
| pdlc-loop / codex-loop-run | Converge有限闭环与Batch | 宿主派发能力以实际支持为准，无PDLC循环别名 |
| pdlc-statusline / hooks模板 | 宿主原生进度与既有护栏 | 不自动修改宿主全局设置；该UI配置无等价移植 |
| PRD/架构/API/DB/UI/测试/部署/质量/发布模板和共享prompts | 保留现有产品模板，专项章节与方法按Product、Engineering、Lifecycle职责改编进唯一引用 | 不复制带示例参数的长模板；不移入PDLC状态/ID/宿主指令 |
| sync_skills / build_codex / build_agent_skills / 安装配置 | 本集合现有installer与七个自包含bundle | 不改安装宿主配置，不把外部包声明为自有代码 |
| 上游tests/evals | 仅作能力与契约参考，自有工具先写独立可执行测试 | 不把上游测试通过等同自有流程行为通过 |

## 重复消除与实际缺口

PRD和UI产品设计归Product；工程专项方法归Engineering；项目概览/API/图使用对应现有能力；计划/TDD/实现/修复/重构/代码评审/循环使用Converge。Lifecycle只保留跨角色交接与证据视图，工程工作项仍是Converge原生状态，避免两套阶段推进和自动循环互相驱动。

当前实际工具切片为：正式PRD/显式追踪/本地附件完整冻结→native工作项的只读准备与显式登记；冻结FR/AC修订差异→声明依赖范围影响与Lifecycle历史保全/失效→同一native工作项显式修订和中断重放；真实工程回执→完整输入绑定的AC覆盖/新鲜度检查。旧成功失效、失败记录保留；不自动rebase、确认业务或启动发布。具体操作见[修订与恢复](../skills/project-docs-product/references/revision.md)。方法文档和分发检查不能证明设计质量或真实项目任务成功。

六类业务关系已支持`set`、`query`、`impact`、`orphans`、`validate`。工具直接读取原记录，写入复用Lifecycle CAS。不兼容旧PDLC状态协议，具体操作见[关系链与协调](../skills/project-docs-lifecycle/references/coordination.md)。

保留缺口：PDLC专有状态栏；非支持测试报告的通用解析器；跨宿主自动托管/恢复；真实Java依赖、CI/CD、部署及指标接入。它们不阻塞自有文档/工程方法使用，按真实项目需要逐项实施和验收，不先建设通用平台。
