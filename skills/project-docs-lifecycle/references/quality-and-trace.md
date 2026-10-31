# 阶段内容质量、FR/AC追踪与交接检查

作者：Jeff.Liu

这些检查在原有 lifecycle-record v1 之外按需使用，不迁移旧记录、不授予业务批准、不要求单PRD任务补全生命周期。工具使用标准库；当前逐测试结果采集适配 unittest，其他框架尚未适配，不能手写回执冒充实际执行。

## 阶段内容审查

审查者先阅读原始输入和当前阶段产物，逐项回答下面的问题：给出实际判断及理由，并引用来源中的原文。资料不足写 gap，列待决问题、责任人及下一动作；不为通过检查补关键词、编造确认或把假设改成事实。真实规则/批准需要有权人员确认；模型审查单独标记。

| 阶段 | 固定检查ID | 审查者应回答什么 |
|---|---|---|
| L0 | problem_source / scope_impact | 原话、来源和问题是什么？哪些影响有依据，范围与负责人是否明确？ |
| L1 | current_state / causes_evidence | 当前业务实际怎样运行？哪些证据支持或否定候选原因，哪些仍未知？ |
| L2 | options_decision / value_scope | 研发、指导、配置、数据处理或不做分别是否适用，选择依据与决定人是谁？目标、价值依据和边界是什么？ |
| L3 | rules_exceptions / acceptance | 规则、状态、权限及例外能否确定结果？FR/AC是否覆盖原始诉求、正常和异常场景？ |
| L4 | design_dependencies / failure_recovery | 实现方案是否覆盖需求与实际依赖？失败、恢复、数据/外部影响和回退责任是否清楚？ |
| L5 | test_first / change_build | 是否有当前范围的真实红绿证据？代码变更与被测构建能否追溯？ |
| L6 | ac_coverage / execution_results | 每项必需AC是否有对应测试？是否在当前版本/构建/环境实际执行，失败和跳过如何处理？ |
| L7 | business_scenarios / confirmation_scope | 业务场景及结果是否由对应角色核对？确认绑定了哪些内容版本和范围，哪些仍是模拟或待批？ |
| L8 | build_environment / authorization_recovery | 待发布制品、环境和范围与测试是否一致？必要授权、恢复方案及执行责任是否具备？ |
| L9 | deployed_checks / failure_result | 实际部署、健康和业务检查证明什么？失败及恢复结果是否分开记录，是否仍有受影响范围？ |
| L10 | handover_owner / outcome_observation | 接收人能否据资料继续操作和支持？效果指标、数据、观察期和Owner是否落实，未达标后做什么？ |

质量文件形状（实际字段须绑定真实文件，不复制以下示意值当成评审）：

```json
{"schema_version":1,"project_ref":"已有项目","subject_ref":"已有需求","stages":[{"stage":"L3","artifact":{"path":"prd.md","sha256":"实际SHA256"},"reviewer":"实际审查上下文或人员","reviewer_kind":"model","at":"带时区ISO时间","checks":[{"id":"rules_exceptions","verdict":"pass","reason":"具体结论和推导","evidence":[{"path":"prd.md","sha256":"实际SHA256","quote":"该文件中的非空原文"}]},{"id":"acceptance","verdict":"gap","reason":"具体缺口","evidence":[]}],"open_decisions":[{"question":"会改变结果的未决问题","owner":"对应角色","next_action":"如何取得决定"}]}]}
```

每条审查以阶段和 artifact.path 共同标识，绑定被审查文件的当前摘要；同阶段不同文件可分别审查，同一组合不能重复。每条审查完整回答该阶段的两个问题，不能重复或删掉。pass 和 not_applicable 都要有理由及引用；gap 可保留空证据，但使对应产物不就绪。未决问题保留所属产物路径；`--stage` 检查该阶段所有产物，不因另一份产物通过而隐藏缺口。引用文件和原文摘要变化时旧审查失效。工具核对证据、完整性与新鲜度；引用正确仍不能证明审查结论正确，重要事项需独立内容复核或业务确认。

```bash
python3 <集合>/scripts/lifecycle_quality.py quality --root <资料目录> --contract quality.json
# 仅检查已授权范围；不自动补其他阶段
python3 <集合>/scripts/lifecycle_quality.py quality --root <资料目录> --contract quality.json --stage L3
```

## FR/AC到实际测试

`trace.json` 固定本次范围及版本：

```json
{"schema_version":1,"project_ref":"已有项目","subject_ref":"已有需求","build":{"path":"app.py","sha256":"实际SHA256"},"environment":"实际验证环境","scope":"本次范围","requirements":[{"id":"FR-01","version":1,"source":{"path":"prd.md","sha256":"实际SHA256"}}],"acceptance":[{"id":"AC-01","version":1,"required":true,"requirements":[{"id":"FR-01","version":1}],"source":{"path":"prd.md","sha256":"实际SHA256"}}],"tests":[{"id":"test_business.Tests.test_normal","version":1,"source":{"path":"test_business.py","sha256":"实际SHA256"},"covers":[{"id":"AC-01","version":1}]}]}
```

同一AC可以对应多个正常/边界/异常测试，同一测试也可关联多个AC；每项必需AC的所有声明测试均须实际通过，不能以一个正常用例隐藏失败的边界用例。当前范围内每个FR必须有关联的必需AC，不能全设为可选来绕过验证；暂缓的FR不纳入本次声明范围。版本引用不可悬空，ID不可重复。只声明当前范围；不重新编号已有FR/AC。

```bash
python3 <集合>/scripts/lifecycle_test_runner.py --root <资料目录> --tests . --trace trace.json --output <资料目录>/execution-1.json
python3 <集合>/scripts/lifecycle_quality.py trace --root <资料目录> --contract trace.json --execution execution-1.json
```

采集器在独立Python进程中执行真实 unittest，逐个记录测试ID、结果、测试文件摘要，并绑定trace、被测文件、环境/范围和采集器及其共享校验代码身份。输出必须是新文件；复测保留旧回执。零执行、必需测试缺失/跳过/失败/预期失败、映射或文件变化、错误构建/环境、测试中修改源文件均不能通过。未映射的额外测试不能替代必需AC；可选AC的跳过可保留，但真实测试命令失败仍阻断。

零测试回执可以是合法的失败结果：valid=true、ready=false，逐项保留not_run缺口，可按transfer交给下一人排查；不能作为tested检查点。

当前单文件测试源绑定要求测试方法实现与测试类位于同一文件；普通保留__wrapped__的装饰器会先展开再核对。跨文件继承或无法定位的方法记binding_error及未覆盖gap，保留真实测试结果，ready=false；可转交排查但拒绝作为tested检查点，不强迫已有项目改变测试布局；改用该项目的原生报告材料承接。本检查只核对声明的来源，不证明导入助手、数据文件等全部传递依赖均未改变。

检查证明“声明关联的测试是否以当前输入实际执行”，不自动判断断言是否足够。审查者仍须核对AC含义与测试断言，不能用测试数量或名称相似代替语义覆盖。源文件采用整文件摘要，单文件中任一内容变化会要求复核相关绑定；未实现自动的最小语义影响分析。环境/范围是调用方声明的本地上下文，不是远程平台的可信授权。

## 人工验收与已有项目测试

自动trace只声明自动化验证子集；人工AC仍保留在唯一PRD中，不能因采集器不支持而删除、设为可选或声称全部覆盖。L6内容审查分别列出自动化覆盖和人工/未适配部分，并核对完整PRD范围。人工场景保存AC/FR及版本、实际步骤/输入、观察结果、通过/失败/未执行、被测构建、环境和范围、确认人/角色、时间及可查来源；模拟必须标模拟。用现有record的confirmed或executed证据引用实际材料，不另造一套人工测试回执格式。人工测试通过、L7业务验收及L8发布授权分别保留对应角色和依据；模型审查不能代签。

Java等项目继续执行自己的工程命令，保留真实命令日志、CI/JUnit等报告和AC关联材料，由内容审查说明实际结果与局限。当前采集器没有适配这些报告，不填写假的unittest ID、runner摘要或passed回执；tests_ready=null表示没有本采集器可验证的自动结果，不代表测试通过或失败。已有项目门禁仍是权威来源，不增加新框架或替代其运行器。

## 交接包与就绪边界

交接包保存schema_version/project_ref/subject_ref、record_revision、record/prd/quality引用、files快照清单及next_action（stage/action/owner/expected_result/authorized_scope）。文件引用为 `{path,sha256}`；files须包含已完成产物、全部已记录证据、质量引用及实际运行依赖。每份已完成产物的 stage/source 必须对应一条质量审查的 stage/artifact.path，且摘要有效；审查别的PRD或仅在支持引用中提到该文件不能替代明确的审查对象。合并在同一文件、同一阶段的产物可共用审查，不要求机械拆文件。原始来源和未决事项按授权保留；历史档案可单独归档，不机械复制整个工作区。trace/execution如提供必须成对，并包含其所有引用。文件摘要、身份、记录revision或已完成产物的审查关联不符在两种用途下都会停止；未审查项可针对实际文件记录明确gap后转交，不填假pass。

| 用途 | 检查与ready的含义 | 不表示什么 |
|---|---|---|
| tested（默认） | 可作为自动测试已通过的检查点接续；质量就绪、依赖无待复核、自动trace实际通过。回执须由明确L6产物的executed证据引用，L6已完成，其build/environment/scope与trace一致 | 不表示所有后续阶段完成、真实业务批准或可发布 |
| transfer（显式指定） | 包内资料可一致地交给下一人；质量或测试可失败/待观察，needs_review和gaps原样返回。允许没有自动trace的人工资料包 | 不表示阶段完成、测试通过、可以继续依赖失败结果的工作或获得任何外部授权 |

```bash
python3 <集合>/scripts/lifecycle_quality.py handoff --root <包目录> --contract handoff.json
python3 <集合>/scripts/lifecycle_quality.py handoff --root <包目录> --contract handoff.json --purpose transfer
```

purpose由调用方显式选择，不能靠包内字段降级默认检查。两种用途都返回business_authorization=false；quality_ready说明所附内容审查，tests_ready说明当前自动trace（未提供或尚未完成校验则null）。transfer的ready=true只表示可转交；接手方仍按next_action、gaps、needs_review和项目权限判断可以修复或继续哪些独立工作。构建/环境/范围错绑仍拒绝，不用transfer掩盖错误关联。历史工具身份不匹配要重新采集，不能改旧回执的摘要冒充新运行。

gaps 同时保留记录中 blocked/pending_confirmation 的产物ID、阶段/版本、来源、状态、负责人、原因和恢复条件，不能仅因所附质量及自动测试通过而返回空缺口。后续业务验收阻塞不否定已经通过的L6检查点，因此 tested 的 ready 可为true且带后续阶段阻塞；它仍不表示全部阶段完成或可发布。工具不自动改写 next_action 或替负责人决定解除阻塞。

记录中 confirmation=conflicted 的事实/反馈也在gaps保留原陈述、分类、来源和负责人，不以技术测试通过掩盖已声明的来源冲突。未确认不自动等于冲突，工具不推断真实性或其影响阶段；若冲突改变当前规则或验收，由负责人核实，并在对应内容审查中记gap，停止依赖它的定稿、实现或业务放行，独立工作继续。已有L6技术检查点仍按tested边界解释，不代替业务裁决。

L10支持交接完成与效果待观察可同时成立：保留handover检查结果、效果gap、观察负责人/触发条件和下一动作，使用transfer传递，不能宣称效果已达成或重跑已完成部署。更早的受理/无PRD交接仍按生命周期文档契约传现状与缺口，不强造PRD或测试来套这个资料包检查。

校验CLI在导入同目录工具前禁写Python缓存。接手先只读核验，再复制到新工作目录接续，冻结包保持不变；重测写新文件，记录按CAS更新。独立上下文验证不等于桌面聊天自动切换、跨账户权限或自治调度。

`-B` 仅禁止写缓存，不能阻止读取旧字节码。采集器CLI和交接校验CLI在独立进程内使用临时空缓存前缀，读取当前源码并在退出时清理临时目录；原有缓存和用户配置不删除、不改写。它保证本进程的导入检查，不证明子进程、外部运行器或未声明的传递依赖；这些仍按项目实际命令核验。

源码绑定诊断只阻断本次已声明为通过证据的测试；未映射的额外测试和可选跳过项不充当已验证覆盖，也不会因此扩大必需范围。真实测试命令失败仍阻断 tested。
