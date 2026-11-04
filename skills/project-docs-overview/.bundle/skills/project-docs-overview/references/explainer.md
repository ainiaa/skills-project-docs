# Archify explainer 一页说明

用户要求“一页说明”“交互 HTML”“explainer”“零基础图解成品”或“做成页面便于分享”时使用。默认 Markdown 说明仍按原模板生成；不主动给所有回答附页面，也不更改用户的全局规则。仅要求独立图源或图片时使用 `project-docs-diagram`；图解页面即使只有一张主图也走本流程，按交付物而非图的数量分流。explainer 是文档模式，不是第十一种 typed JSON 图；不传给 `render_native_diagram.py`，不走固定 Markdown 模板校验器。

## 取证与写作

explainer 可面向新手、领域专家或混合读者；先按[读者与用途约定](../../../references/audience.md)选择深度和组织方式。下面的零基础写法仅用于相应知识缺口，不能因为交付 HTML 就默认采用。专家页可先给口径、边界和证据，仍遵循同一页面契约。

有目标代码仓库时遵循 Overview 的源码取证流程。仅有业务材料或解释概念时，以用户材料及实际核对的资料为依据，保留输入或注明来源位置；不创建仓库、不运行源码扫描、不编造 Git 版本或代码引用。材料中的规则与拟议规则分开，未约定的处理标为待确认；无系统证据时只解释概念，不能宣称系统已实现。两种情况都先核对用途、主流程、边界及来源。开头直接回答有什么用，随后每个面板回答一个具体问题。精简不能删除影响结论的异常或限制。将推断、未测数据与未提交代码状态写在范围里；页面检查不能证明业务解释正确。

从 [可执行结构示例](../assets/project-explainer.archify.md) 开始，按目标项目重写事实、流程、源码位置与引用，不能把示例当成已取证事实。保存 `candidate.archify.md`、相邻数据和图源，以及最终 HTML 与官方回执；默认放在目标源码仓库外的独立交付目录。

### 零基础图解

先确定读者已有知识、要理解的问题，以及看完后需要解释或完成什么。业务负责人可能只缺技术背景，开发者可能只缺业务背景；按缺口解释，不把成人当儿童，也不重复讲解已经掌握的内容。信息足够时直接选择，只有读者或目的会改变解释且无法推断时才澄清。

| 解释目标 | 内容怎样组织 | 合适的视觉结构与核对重点 |
| --- | --- | --- |
| 概念：这是什么、与什么不同 | 对象、关系、一个具体例子 | 关系图或概念对照；说清适用与不适用范围 |
| 流程：谁在什么时候做什么 | 触发、交接、结果、异常出口 | 步骤或泳道；核对参与者和分支 |
| 规则：为什么结果不同 | 条件组合、判断顺序、正反例 | 决策表；覆盖临界值、缺失和冲突条件 |
| 机制：为什么这样运作 | 输入、内部动作、输出与限制 | 机制示意；区分解释模型与真实系统实现 |
| 问题：哪里出了问题 | 现象、已知链路、证据、待核假设 | 因果链或时间线；相关性不直接当因果，不臆断根因 |
| 取舍：为什么选这个方案 | 目标、备选、收益、代价、成立条件 | 对照表；说明结论依赖的条件，不替业务方作未授权决定 |
| 变更：对我的工作有什么影响 | 改前、改后、不同角色、保留与变化 | 前后对照和操作步骤；标清拟议、已批准与已生效状态 |
| 培训：我应当如何使用 | 从角色的一项真实任务讲起 | 任务步骤配例子；保留常见误区和异常处理 |
| 客户说明：发生了什么、怎么办 | 具体事件、规则依据、影响、处理办法 | 时间线或实例对照；不承诺未经确认的处理结果 |

围绕主要目标组织页面，必要时组合相邻方式，不机械地填满全部类别。规则表、前后对照也是有效图解，不强制每页有流程图或固定三段结构。配短标签和必要短文，避免同一内容在段落和图中重复；精简不删除影响结论的条件。术语首次出现时就地解释，不把源码、接口清单或术语表放在主阅读路径。

类比可帮助入门，但须说明与真实机制的对应及失效之处；没有合适类比时直接用真实例子。简化保留权限、异常、状态和适用范围，业务事实继续附来源，推测和示意明确标注。无需真实数据时不编造性能、收益或生产成功记录。

按目标参考小型案例：[报名规则](../assets/beginner-explainers/registration-rule.archify.md)使用决策表，[通知延迟](../assets/beginner-explainers/notification-delay.archify.md)区分观察与原因假设，[报修入口变更](../assets/beginner-explainers/repair-change.archify.md)使用前后对照及角色步骤。每个案例旁的 `.input.md` 保留合成材料；随交付保留原材料，不将这些规则套到实际项目。已有的[安装升级图解](../assets/beginner-explainer.archify.md)仍可解释本集合的软链接机制。其他主题按实际证据重写，统一走下方 `finalize explainer`，不增加工具或独立 Skill。

交付前从读者视角核对：能否从图和短文说出“解决什么问题、如何运作、何时不成立”；逐项对照证据，检查类比、箭头和删减是否改变事实。核对目标屏宽下的表头和主图可读性，过密时缩短标签或分组、分步呈现，不把关键解释只留在放大操作后。来源只有链接、没有 `@code` 时，官方检查通过不保证目标文件存在；须回查实际引用版本中的文件及行号。记录实际运行的检查；没有真人试读时不声称已证明新手理解效果。

### Markdown 契约（Archify 3.2.0）

- `# 标题 {#page-id}` 后的第一段是结论；紧跟的平级列表可列最多四条理由。`@answer scope="范围与限制"` 记录适用范围。
- `@meta locale=zh-CN style=clean` 选择语言和初始样式。样式支持 `clean`、`editorial`、`product`、`swiss`，读者也可切换样式和明暗主题。
- `## 这个面板回答什么？ {#stable-id}` 开始一个面板；省略宽度让官方布局自动安排。所有面板、图、步骤和块 ID 在整页内唯一。局部修改保留稳定 ID。
- 支持段落、平级列表、任务清单、Markdown 表格、`**加粗**`、行内代码、安全 HTTP(S) 链接与普通代码围栏。不支持嵌套列表和原始 HTML；路径、占位符及操作符用反引号包裹。指令参数用 `key=value`，带空格值用双引号及 JSON 转义；行数据使用 `| 单元格 |`，单元格中的竖线写为 `\|`。
- 表格单元格可标 `{good:优势}`、`{caution:限制}`、`{bad:问题}`；需要读者操作时用 `- [ ] 具体检查项` 收尾。

### 引用与已提交代码

```text
@source entry title="请求入口" path=src/router.py lines=10:25
@source design title="设计依据" url=https://example.com/design
```

在相应结论旁用 `[](source:entry)` 或 `[入口实现](source:entry)` 引用；`@code source=entry language=python` 嵌入真实代码。`path` 相对目标仓库，行范围必须存在；加 `--repo-root` 后官方工具从 Git 固定提交读取，不能用工作区修改替换已提交字节。默认解析 origin 与 HEAD，也可用 `@meta repo_url=... repo_revision=<完整40位提交>` 明确版本；使用无凭证远程地址。工作区改动只能单独注明，不能宣称已嵌入代码代表未提交状态。非 Git 仓库仍可写说明并注明无法固定版本，但不能伪造 `@code` 成功。

### 原生图与步骤

整页最多四张原生图。按信息形状选择，不把同一内容重复写成段落和图。

```text
@workflow id=request-flow title="处理流程"
| client | 发起请求 | frontend |
| service | 处理业务 | backend | source:entry |
| client > service | 请求 |

@steps id=request-steps
| call | 发起请求 | 提交输入参数。 | request-flow | client |
| handle | 处理业务 | 核对业务规则。 | request-flow | service |
```

节点行 `id | label | type?`，边行 `from > to | label? | variant?`。`@architecture` 同形，适合组件关系；`@workflow` 适合操作流程。类型为 `frontend/backend/database/cloud/security/messagebus/external`。标签短，解释放同面板的步骤中。

其他紧凑图：

| 指令 | 行格式 |
|---|---|
| `@sequence id=... title="..."` | 先 `actor <id> | 标签 | 类型`，再 `from | to | 消息 | variant?`；返回消息用 `return` |
| `@tree id=... title="..."` | `id | 标签 | parent`，根节点 parent 为 `-` |
| `@timeline id=... title="..."` | 可先 `lane <id> | 标签`，再 `id | 带时区ISO时间 | 标题 | lane? | kind?`；紧凑时间线按示意数据处理 |
| `@erd id=... title="..."` | `entity <id> | 标签`；`entity.field | 类型 | pk,fk,uk? | 引用?`；`from > to | many:one | 标签?` |

四种其他图型 `dataflow/lifecycle/class/waterfall` 或需要精确几何时，用 `@diagram <type> id=... source=相邻图源.json title="..."`。先读取 `project-docs-diagram` 的原生图规范及所安装 Archify 对应 schema，再编写官方 typed JSON；紧凑图由官方编译并验证，外部图源也必须通过官方检查。源码来源和节点对应关系仍须逐项核对，不将渲染通过当作源码语义证明。`[组件](node:request-flow.service)` 可打开完整 Viewer；链接的图与节点必须实际存在。

### 图表与其他块

- 同目录 CSV/JSON 数据：`@chart type=bar data=counts.csv x=name y=count title="数量（示意）"`。类型为 `bar/line/pie`；CSV 要有表头，JSON 为对象数组。最多 60 行（饼图 12 行），空数值报错，不能当作零。交付时冻结数据；注明单位与测量／估计／示意范围。
- `mermaid` 围栏仅用于图表：`pie/xychart-beta/quadrantChart/sankey-beta/radar-beta/venn-beta`；流程、时序等使用上面的原生图。带空格或中文标签加引号，多序列命名以显示图例。
- `@callout level=warning title="限制"` 后每行一个管道单元格；`@facts` 后每行 `标签 | 值`。`@image path=images/result.png alt="效果" caption="说明"` 嵌入交付目录内图片；不得使用外部绝对路径。

## 官方交付与验证

先通过本集合 `scripts/engine_paths.py` 的 `find_engine("archify")` 解析实际 CLI：显式 `ARCHIFY_OFFICIAL_CLI`、受管安装、PATH，优先级与其他通道一致。`prepare_runtime()` 可准备受管 Node。检查缺失时按集合安装流程处理；无需另装独立 `archify` Skill，也不联网自动升级。下方 `<archify-cli>` 必须替换为解析出的可执行文件绝对路径，路径有空格时加引号。

```sh
<archify-cli> finalize explainer candidate.archify.md answer.html --repo-root /absolute/repo --json
```

仅基于材料或概念、不嵌入 `@code` 且没有目标仓库时，省略 `--repo-root`：

```sh
<archify-cli> finalize explainer candidate.archify.md answer.html --json
```

嵌入真实代码仍须满足上方固定提交的取证要求；不能用本地存在的材料文件冒充可由 `@code` 读取的已提交源码。

退出码为零且 `ok` 为真才交付。默认包含 validate、原子 deliver 和 check，**不运行浏览器**；保留 `.finalize-summary.json` 及 delivery 回执。非零时检查带行号、组件和修复例子的 diagnostics，修正后重跑，不能交付旧成品冒充本轮成功。`--writing warn|strict|off` 控制写作检查，保留默认 `warn` 并修正可改进的警告，不用 `off` 绕过问题。

要求实际浏览器验收时加 `--browser-check`；若已有同路径浏览器证据，重跑用新的 `--out-dir review-2` 保留旧证据。自动浏览器检查与人工视觉检查分别记录。用户要求审图时，在桌面与手机宽度打开 HTML，检查字、表格、图与步骤联动、来源和 Viewer；实际看过才能声称视觉验收。

已有页面只改单个面板时：

```sh
<archify-cli> patch explainer answer.html checks replacement.md revised.html --json
<archify-cli> check revised.html --require-provenance --json
```

`replacement.md` 必须恰好一个同 ID 的 `##` 面板；其他面板和冻结资源保持原样。修改结论、共享来源或整页结构时回到完整草稿重跑 finalize。patch 不能用来冒充源码已刷新；更新源码版本时重新取证、更新草稿并 finalize。

页面菜单支持长图 PNG/WebP/JPG 与打印 PDF；不承诺 explainer 整页 SVG/WebM，也不调用仅适用图 Viewer 的 `export_archify.mjs`。浏览器若回退为 PNG，按实际 MIME 和文件签名命名并说明，不能改扩展名冒充目标格式；浏览器不支持图片导出时交付 HTML 并报告限制，或按用户要求打印 PDF。宽表和长代码在交互页面可滚动，但长图／打印可能只保留可见范围；导出后单独检查是否截断，优先选择必要的短代码片段，不能把文件存在当作内容完整。

交付时链接 HTML 和可编辑草稿，简述结论、覆盖范围及待确认项。说明采用一页说明结构、未运行固定 Markdown 模板检查；只报告本轮实际完成的检查，不把官方校验等同于完整项目事实审计。
