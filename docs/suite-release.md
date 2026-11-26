# Project Docs 发布与可选联动验收

作者：Jeff.Liu

Project Docs 与 Converge 各自维护源码、CI 和版本。只有声明支持某个联动组合时，才同时记录双方候选和兼容验证结果。

## 支持边界

| 组合或状态 | 升级后的处理 |
|---|---|
| Project Docs独立、无Converge | 七入口的文档与方法可独立使用；接管需明确提供方，不强制安装Converge或PDLC |
| Converge独立、无Project Docs | 既有局部工程闭环保持；不补访谈或第二份PRD |
| 当前Product + 当前Converge源码 | 分别预检adopt / revise / iterate；通过仅证明API形状与可加载性，实际接管和语义仍须回归 |
| 当前Product + 旧Converge | 缺必要API时写前拒绝，不靠版本字符串放行；可以继续独立文档交付 |
| 旧schema v1 active/blocked原生项 | 既有合法字段兼容，沿原基线、语义contract和失败预算恢复；不静默换目标、换提供方或rebase |
| 旧准备请求 + 升级后提供方 | 已冻结提供方摘要漂移时拒绝；先保留旧请求和状态，再核对新快照并显式重新准备，不改摘要绕过守卫 |
| 当前版本完成项 | 保存不可变完成档案，再清除非终态项；相同已完成contract的普通重建被拒绝。下一轮显式引用完成指纹、新产品版本及新执行目标 |
| 旧版本已清除、无完成档案的项 | 无法自动补出可验证档案或后继关系；先人工核实原任务及证据，明确新任务身份。不从聊天推造passing receipt |
| 旧PDLC或外部绑定 | 仅显式选择/原绑定恢复，仍验证来源和摘要。升级不迁移其状态、不改第三方源码，不因存在目录而选用它 |

其中“完成后禁止原contract重建”是有意的行为变化，不能描述为所有旧行为完全不变。当前完成档案也不是旧版本已经验证可读取的格式。

固定旧版升级基线为 Converge commit `34eaf71f2bce81c051cb220aaa5e11b27d467a2b`，不是对任意历史版本的承诺。旧源码由Git直接导出到临时目录，生成真实active、blocked和已清除项后交给当前脚本；不手改状态冒充旧版，也不在用户真实任务上试验。六入口链接升级覆盖旧宿主布局，不能据此声称所有历史npm版本均已实装验收。

## 独立发布前核对

1. 保存 Project Docs 候选源码及状态备份。记录候选提交、未提交差异、安装方式和已加载宿主。
2. 从候选重建并检查七个安装快照，按[检查命令](00_standards/test-commands.yml)执行独立覆盖率、安装升级、发布专项和浏览器验证。保存退出码、输出及跳过原因。主 CI 在 push 或 PR 自动执行这些检查，无需选择 Converge。
3. 按[真实任务验收](suite-acceptance.md)分别登记模型、岗位、Java、生产部署和效果状态。保留未验证条件及回退步骤。

安装快照保留运行脚本、随附示例和安装文档冒烟测试。开发回归及出处文件校验从源码仓库执行。构建和 `--check` 会核对清单出处，安装后使用阶段规则计算指纹。

## 可选 Converge 联动

需要验证特定组合时，明确选择兼容的 Converge 源码。使用GitHub Actions 的 `Optional Converge integration` 工作流，输入完整提交 SHA。GitHub Actions 的手动入口在工作流进入默认分支后可用。本地复用以下命令：

```sh
python3 scripts/product_handoff.py --check-provider --converge-root /absolute/converge --capability adopt
python3 scripts/product_handoff.py --check-provider --converge-root /absolute/converge --capability revise
python3 scripts/product_handoff.py --check-provider --converge-root /absolute/converge --capability iterate
PROJECT_DOCS_CONVERGE_TEST_ROOT=/absolute/converge python3 -m pytest \
  scripts/test_product_handoff.py scripts/test_engineering_handoff.py \
  scripts/test_product_evidence.py scripts/test_suite_upgrade.py
```

组合通过要求接管、修订、迭代和旧版升级的用例实际执行且通过。候选须能取得固定的旧版 Git 对象。前置检查或任何用例失败时，保留该组合的失败结果。未选择联动时，报告该组合未验证。

## 无界面浏览器与专项验证

统一入口在[检查命令](00_standards/test-commands.yml)的`browser_doctor`、`browser`和`release_specialties`。CI在Product覆盖率测试前先运行浏览器诊断；发布专项另覆盖安装/更新中断恢复、旧版升级、原生图导出原子性和API日期格式，不把Product/Lifecycle的90%覆盖率扩展为全仓验证。

浏览器复用现有Mermaid所用Puppeteer模块，优先遵循显式模块/可执行文件配置，再读取Mermaid配置和兼容缓存。`--doctor`只解析模块和安全可执行路径，不启动浏览器、不生成交互证据；成功仅表示路径可用，实际旅程通过才证明本次浏览器验证完成。显式配置无效时不静默回退。macOS的`.app`及指向它的别名均在启动前拒绝；使用独立`chrome-headless-shell`，不启用桌面测试开关、不接入用户浏览器资料。

```sh
# 已有安全配置或兼容缓存时先诊断；退出2须按错误修正，不能计为通过。
node scripts/product_browser.mjs --doctor
# 现有Mermaid配置指向桌面Chrome时，只为本轮命令显式指定独立二进制。
PUPPETEER_EXECUTABLE_PATH=/absolute/chrome-headless-shell node scripts/product_browser.mjs --doctor
PUPPETEER_EXECUTABLE_PATH=/absolute/chrome-headless-shell node --test scripts/test_product_browser.mjs
PUPPETEER_EXECUTABLE_PATH=/absolute/chrome-headless-shell python3 -m unittest discover -s scripts -p test_product_bundle.py
```

独立二进制须匹配现有Puppeteer版本，保存在其标准缓存或稳定绝对路径，不依赖临时下载目录。缺Puppeteer时先修复既有Mermaid安装；仅在模块不能从现有CLI解析时设置`PRODUCT_BROWSER_MODULES`为其`node_modules`绝对路径，不另装一套自动化框架。Python浏览器用例执行同一诊断，缺运行环境时skip并保留具体原因；CI的前置诊断非零则失败，不允许以skip代替浏览器验收。

发布专项使用`release_specialties`原命令，首跑保存原始输出。若其中要执行真实Mermaid导出，CLI自身也须使用安全配置：以`MERMAID_OFFICIAL_CLI`指向调用现有CLI且带`--puppeteerConfigFile`的隔离wrapper，配置中明确`executablePath`和`headless: "shell"`；不能只假设环境变量会覆盖CLI已显式传入的桌面路径。Archify官方导出另将`ARCHIFY_CHROME`指向同一独立二进制，PlantUML使用`JAVA_TOOL_OPTIONS=-Djava.awt.headless=true`，不沿用工具自身的桌面自动发现。未安装的官方引擎、桌面导出、平台及外部条件按实际skip/uncovered记录；原子性等模拟故障回归与真实官方导出分别报告。

## 升级顺序与恢复

独立升级先备份该项目，再沿原有宿主和安装方式更新。只在升级已使用的联动组合时准备双方候选并预检三项能力。Project Docs可使用 `bash install.sh --host codex --no-engines` 补齐Engineering链接；既有依赖复用，不要求联网更新第三方。若出现同名非本仓目录冲突，安装应失败并保留原链接，按诊断处理；不得强删。若仍使用不兼容Converge，保持独立文档使用，暂不接管。

通过skills CLI复制安装时，应从同一个已冻结候选更新本次所用入口，避免一部分入口仍带旧bundle；复用现有 `bin/project-docs.js` 的备份/校验/失败恢复，不再写安装器。单入口安装不必安装全部七项，但它自己的bundle必须完整。更新后刷新宿主发现；doctor只证明文件/依赖，不证明宿主已加载或模型遵守Skill。

旧准备请求不因升级而可直接重放。保留旧请求，先检查其输入、业务目标、原生项和新提供方能力；已有原生项按原contract显式接续，需求变更走显式修订，完结后走显式后继。具体命令沿用[接管](../skills/project-docs-product/references/engineering.md)、[在途修订](../skills/project-docs-product/references/revision.md)、[完成后迭代](../skills/project-docs-product/references/iterations.md)，不复制第二套流程。

失败时停止新增写入，保存失败输出和当前源码/状态快照。安装器自身失败恢复先按其原有行为执行。联动状态的回退须用升级前成套源码和状态备份，在确认无新写入后恢复到匹配的组合；不能只回退其中一个仓库并继续使用新冻结请求。若已有新的成功验收、完成档案或后继项，先保留这些新增证据并决定前向修复或人工对账，不能用旧备份覆盖掉新工作。备份完整性未核实或有并发写入时不自动恢复。

## 本轮候选结论

本地修复与回归完成后，具体数量及快照身份写入当轮仓外原始回执和仓内结果报告。真实Java构建、CI/CD、模型行为及真人岗位验收在进入条件满足前仍未验证；本文件不是发布授权或已发布证明。

2026-11-17本地复验（当前未提交工作区，非线上CI）：

| 检查 | 实际结果与边界 |
|---|---|
| Product/Lifecycle覆盖率门禁 | 452通过、3跳过，95.51%；跳过项缺真实模型/成品报告。覆盖率仅限`.coveragerc`规范Python源，不代表全仓；原始日志保留临时fixture源码清理后的coverage警告 |
| 浏览器运行时与交互 | 运行时10通过，实际旅程14通过；独立`chrome-headless-shell`，无浏览器跳过。交付包29项亦通过，已包含在上述Python门禁中，不重复累计 |
| 发布专项统一命令 | 315项中314通过、1跳过；安装/更新恢复、旧版升级、图导出原子性、官方无界面导出和API日期回归通过；draw.io桌面导出未授权，保持未验证 |
| 文档、配置与分发 | 源文档/配置22通过，安装快照文档11通过；七个bundle一致性检查通过 |
| skills CLI安装契约 | 默认检查20通过、7跳过；未开启真实宿主/CLI集成开关，不将静态及隔离模拟检查计为完整实接 |
| Converge能力与线上CI | 当时的本地adopt/revise/iterate预检通过，线上CI未执行；当前以手动工作流的SHA输入选择联动版本 |

首轮专项为补齐外部工具的无界面配置而主动中断，日志保留；上表专项统计来自配置完成后统一命令的整轮复验。源码增量、基线摘要、运行环境和原始输出保存在本轮仓外回执中。真实任务及简单任务对照、模型与岗位验收、Java私有依赖、生产恢复和业务效果仍按[验收缺口](suite-acceptance.md#外部试点的进入条件)保留；这些本地结果不关闭外部缺口。
