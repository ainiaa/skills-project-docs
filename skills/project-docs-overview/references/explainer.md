# Archify explainer 一页说明

用户要求“一页说明”“交互 HTML”“explainer”或“做成页面便于分享”时使用。默认 Markdown 说明仍按原模板生成；不主动给所有回答附页面，也不更改用户的全局规则。只有一张图时使用 `project-docs-diagram`。explainer 是文档模式，不是第十一种 typed JSON 图；不传给 `render_native_diagram.py`，不走固定 Markdown 模板校验器。

## 取证与写作

遵循 Overview 的取证流程，先核对用途、功能、主流程、边界及来源。开头直接回答项目有什么用、能交付什么；随后每个面板回答一个具体问题。精简不能删除影响结论的异常或限制。将推断、未测数据与未提交代码状态写在范围里；页面检查不能证明业务解释正确。

从 [可执行结构示例](../assets/project-explainer.archify.md) 开始，按目标项目重写事实、流程、源码位置与引用，不能把示例当成已取证事实。保存 `candidate.archify.md`、相邻数据和图源，以及最终 HTML 与官方回执；默认放在目标源码仓库外的独立交付目录。

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
