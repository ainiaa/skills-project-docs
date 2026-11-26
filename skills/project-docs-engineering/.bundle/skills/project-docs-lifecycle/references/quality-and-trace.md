# 阶段内容质量、FR/AC追踪与交接检查

作者：Jeff.Liu

这些检查在原有 lifecycle-record v1 之外按需使用，不迁移旧记录、不授予业务批准、不要求单PRD任务补全生命周期。工具使用标准库；当前逐测试结果采集适配 unittest，其他框架尚未适配，不能手写回执冒充实际执行。

## 执行检查点

这是当前阶段的执行步骤。统一入口及Product、Engineering、Lifecycle读取本节后，再使用下表当前阶段的问题及各自专项方法；不新增全生命周期目录，也不要求单PRD任务补建record、quality或trace。

1. **开始当前阶段前**：先确认本次任务、适用阶段、唯一产物及版本、原始输入和仍有效的已决事项；实际读取输入及当前产物，选出下表该阶段的两个问题，并按下节读取详细检查目录、逐项判断适用性及验证映射。阶段可合并，但不能用另一个阶段或另一个文件的通过替代本阶段、本产物的审查。内容还未产生时先记录待核对内容，不预填pass。
2. **交付或标记完成前**：读回实际成品及相关图/测试/报告，逐问题写结论、推导理由、当前产物的正文位置及原文引用，必要时补原始来源。用与任务有关的具体对象、操作顺序、逐步结果和结束后的下一步检验结论。不能用标题出现、文件存在、哈希相同或“已检查”代替内容走读；没有实际内容证据就记gap。不适用要说明原因及依据。PRD按[Product内容走读](https://github.com/ainiaa/skills-project-docs/blob/main/skills/project-docs-product/references/workflow.md#内容走读执行与评审留痕)完成；其他阶段按下表追查实际结果和失败出口。
3. **缺口→处理→复验**：分别保留文档矛盾/遗漏、业务未决、技术待核实和待批准。可按已有授权修复的内容先修，再重读受影响的完整旅程并复验；需业务决定的列问题、Owner、影响范围与恢复条件，不能替其选择答案。只停止依赖缺口的工作，独立部分继续；保留旧失败和旧版本。
4. **修改后或接续时**：核对身份、产物/引用内容及适用版本，检查旧审查是否仍新鲜。变更后实际重做相关问题，不能只更新摘要、版本或评审日期。交付记录当前阶段及实际审查者、输入/产物版本、逐项结论与证据、未覆盖、下一动作和接手人；模型判断、真实执行和有权人员确认分别表达。

单阶段成果可把上述内容放在已有review.md、评审记录或回复中，不新增必填文件。仅评审不改原稿，不为质量检查重建FR/AC或复制第二份PRD。跨阶段准备把本次产物记为completed或输出tested交接时，将实际问题回答写入既有quality契约，并运行下方quality命令选择当前阶段；缺少审查或ready=false时不得宣称该阶段就绪。有未完成内容可显式transfer，保留gap和恢复动作。早期受理/无PRD任务不强套要求PRD的handoff包。

## 详细检查目录、适用性与验证映射

[详细目录](checklist-catalog.json)是本仓当前方法的单一清单基线：每项有稳定ID、所属阶段/总纲问题、实际问题、适用条件、必查标记、验证方法和预期证据。sources以本集合内相对路径、SHA256、原文和来源类型固定；改编方法同时引用已有采用/许可记录。local_method、adapted_method、lineage_record、local_regression分别表示自有方法、改编方法、采用来源记录和本地真实回归，不代表联网重读上游原文或获得外部标准认证。目录不声明穷尽所有行业或项目。

开始当前阶段前先实际读取该阶段目录及对应来源：

```bash
python3 <集合>/scripts/lifecycle_checklist.py --stage L3
```

脚本校验目录结构，显示当前阶段的question/when/evidence_expected和指纹。指纹由该阶段的规则和目录版本生成，规则变更后须重新核对覆盖。维护者从源码仓库执行 `python3 scripts/lifecycle_checklist.py --verify-sources`，核对来源文件、引文和摘要，构建及检查安装快照也执行这项核对。出处更新后由维护者重读并更新目录，历史业务回执保留原样。

按当前任务、PRD、源码和已决事项，逐个详细检查ID记录以下内容；未选的专项也必须明确判断，不能因没看到代码或没运行工具就默认为不适用：

| 字段 | 实际内容与边界 |
|---|---|
| applicability | applicable / not_applicable / undecided；分别为适用、不适用、待判断 |
| reason / evidence | 具体判断理由及当前范围资料的原文引用；not_applicable也须有依据，required=true的必查项不能豁免 |
| verification | 适用项对应目录的review或test方法，记录passed/failed/not_run；review引用当前产物的实际走读位置，test关联已有trace/execution中的真实测试ID |
| owner / next_action | 待判断、失败或未执行时保留责任角色和恢复动作；不把来源记录、测试名或未来计划当本次通过 |

可查事实先查，已决事项不重复问；只有会改变结果的业务选择才提出澄清，技术待核实和待批准分别保留。未知项仅阻断实际依赖的工作，不把清单扩成本期未要求的改造。已显式提供本期自动trace时，L6-AUTOMATED不能标not_applicable；这是声明范围可确定的约束，不从源码关键词猜测专项。机器只核验绑定、判断是否逐项记录及已适配执行结果，不能证明适用性理由或业务推导正确。

跨阶段或需要机器验收时，复用quality v1每条stage/artifact中的可选coverage：`coverage={catalog_sha256,items:[...]}`。catalog_sha256取上述命令指定当前阶段后的fingerprint。按旧算法生成的报告保留为历史，复验时按当前阶段重跑检查并记录新指纹；每个item含id/applicability/reason/evidence，适用项的verification含kind/result/evidence，test还含tests数组。引用仍为已有{path,sha256,quote}，必须绑定当前内容。review不能只引用别的成品；test必须有当前已验证trace和execution，跳过、失败、缺失、身份/来源漂移不能算通过。Java等未适配结果沿原始项目报告做明确内容审查，保留未覆盖范围。

项目特殊规则用PROJECT-前缀ID追加在同一items中，显式指定当前阶段的check、required布尔值、method（review/test）及带原文的source。沿正式来源追加，不伪造目录已有ID；来源变化后旧判断失效。每个项目仍需核对是否有目录外规则，目录条数不能证明业务穷尽。

恢复与适用性变更先核对原始失败及当前范围：不适用或待判断的当前记录不携带verification，不能用切换applicability隐藏残留的失败、错误映射或过期引用。原验证保留在旧版本/旧回执，范围确有变化时给出新的理由和证据，当前记录只表达该次判断。适用测试的failed/not_run也须校验测试ID的非空、唯一及已提供trace中的声明；给出trace/execution时仍校验来源和执行绑定，不能因结果未通过就跳过映射完整性。

工具发现的测试缺口（缺少实际执行或实际映射测试未通过）也必须保留owner/next_action；当前记录未提供时先补真实责任与恢复动作，不修改结果为passed。合法失败可transfer，错误关联须先纠正才可交接。接手先读缺口与旧证据，再按授权修复，重核目录、源文件、trace和映射；实际复测写新回执，旧失败保持不变。新回执重新通过严格检查才能解除依赖阻塞，不能只更新摘要或删除失败来宣称恢复。单份PRD的评审或回复沿相同内容步骤，无需为此增建JSON。

新任务在交付或标记就绪前使用显式严格检查；复用已有合同和评审材料，不改旧失败记录：

```bash
python3 <集合>/scripts/lifecycle_quality.py quality --root <资料目录> --contract quality.json --stage L3 --require-details
# 适用项使用本地自动测试验证时，显式追加 --trace trace.json --execution execution.json
python3 <集合>/scripts/lifecycle_quality.py handoff --root <包目录> --contract handoff.json --require-details
# 带缺口交接需显式 --purpose transfer，仍保留详细检查gaps
```

--require-details由调用者决定，不能靠包内字段关闭。已提供coverage即使未传严格标记也必须校验；混合新旧阶段不能报告全部details_ready。旧v1仍可读，未提供详细数据时details_ready=null，不构成新任务已经完成详细检查。引用不足可保留合法gap后transfer，但不能作为严格tested检查点。目录和辅助检查代码进入测试采集器身份，新版本不能无复验沿用旧工具回执。

### 新任务的受控检查点

新任务机器验收使用同一脚本的 `checkpoint`，固定启用详细检查，并由调用方明确本次阶段和产物；当前结果不能自行改变检查对象：

```bash
python3 <集合>/scripts/lifecycle_quality.py checkpoint --root <资料目录> --contract quality.json --target L3:prd.md --no-project-inputs
# 项目特殊检查使用Product已冻结的输入；expected-inputs取任务准备时保存的fingerprint
python3 <集合>/scripts/lifecycle_quality.py checkpoint --root <资料目录> --contract quality.json --target L3:prd.md --inputs inputs.json --expected-inputs <冻结fingerprint>
```

同一阶段的多个产物重复传 `--target`；目标集合必须与所选阶段的实际审查对象一致。L3目标须对应冻结的正式PRD或其追踪文件。调用方必须明确选择冻结inputs+expected-inputs，或确无正式项目输入时的--no-project-inputs；不能根据待审coverage自动省略输入策略。无项目输入不等于工具认证项目没有其他规则，调用方仍负责原始来源反查；当前产物声明project-checks或coverage出现项目项时拒绝无输入策略。项目索引按Product的[修订约定](../../project-docs-product/references/revision.md)存入唯一主文或追踪的project-checks块，随原输入快照冻结。即使当前coverage删掉整条项目检查，也会按冻结集合报告遗漏。新字段不自动把旧质量报告升级为新任务通过。

Converge托管任务将这条完整命令及本次目标写入已有verification，由现有执行器采集并核对真实回执；只看到quality.ready或一次旧接口成功不足以满足本次检查。Project Docs不新增控制器、工作项库或后台循环。独立文档任务可直接运行并保存证据，不强制安装Converge；没有运行只报告实际内容复核。handoff的transfer仍只证明资料可转交，不能替代本检查点。

### 风险对应的内容复核与旅程

本期目标、依据、保持项和调整/停止条件放在已有调查/PRD/工单；Bug可用复现与预期行为，不强造收益指标。投入决定时、关键规则变化时和效果观察时重核受影响部分，复用有效决定。首次基线由接收者从原始来源反查，不能只核模型自己抽取的清单。

新业务、关键规则或高风险交接，由实际接收者或独立模型上下文推导结果；局部修改沿已有评审和回归，不额外启动全阶段访谈。调用方可在checkpoint命令冻结 `--independent-from <生成者身份>`，要求审查身份不同，并提供source_coverage和counterexample。跨组件/角色任务再冻结 `--walkthrough journey`。实际独立上下文/岗位参与须有宿主或原始交接记录，名称不同仅是字段一致性检查，工具不认证身份、不证明模型推理正确。

证据复用quality每条stage/artifact里的可选 `walkthrough`，数组项沿用检查形状 `{id,verdict,reason,evidence}`；id仅为source_coverage/counterexample/journey，证据仍为当前文件的 `{path,sha256,quote}`。原始来源反查定位诉求与正文/验收；反例给具体对象、顺序和逐步结果；旅程从真实入口到可见结果，再核异常后的接手与恢复。用已有review.md等留痕，不新增必填文件。所需项缺失、无引用、gap或不适用均不能通过；修复后重走相关链路，旧失败保留。机器只验证声明及引用新鲜度，语义仍由独立复核判断。模型审查、实际测试、真人确认和发布授权分别表达。

单独PRD/设计/仅评审不强制新增quality.json：在已有评审记录或回复中用同样的ID、来源、适用性理由、验证证据、结论及缺口表达即可；没有运行严格工具就不声称机器验收已通过。真实岗位批准、模型遵从和外部平台结果继续单独记录。

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

Markdown产物的每个pass或not_applicable检查，必须至少引用当前被审文件的原文；可同时引用来源和评审材料，不能仅引用另一份文件，字节相同的副本也不能替代本产物；按实际文件解析符号链接，别名不能绕过Markdown目标要求，引用同一物理文件的合法别名可以匹配。缺少本产物引用保留为gap（valid=true、ready=false），旧schema v1仍可读取和transfer；补读后留下真实引用再复验。图或二进制等非Markdown产物沿原有可读证据契约，必须按专项方法实际查看或检查，工具不新增解析支持，也不证明其语义。正文引用只能证明评审指向该文件，不能证明审查者真的读全或结论正确；不引入标题/关键词评分器。

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

交接包保存schema_version/project_ref/subject_ref、record_revision、record/prd/quality引用、files快照清单及next_action（stage/action/owner/expected_result/authorized_scope）。文件引用为 `{path,sha256}`；files须包含已完成产物、全部已记录证据、质量引用及实际运行依赖。每份已完成产物的 stage/source 必须对应一条质量审查的 stage/artifact.path，且摘要有效；审查别的PRD或仅在支持引用中提到该文件不能替代明确的审查对象。合并在同一文件、同一阶段的产物可共用审查。原始来源和未决事项按授权保留，历史档案可单独归档。文件摘要、身份、记录revision或已完成产物的审查关联不符在两种用途下都会停止；未审查项可针对实际文件记录明确gap后转交。

trace/execution如提供必须成对。对正式PRD，自动trace可以只覆盖一部分需求和验收。每个ID须存在，AC须绑定到声明的FR，来源须指向实际声明该ID的主文或追踪文件。files须包含全部冻结文件及摘要，包括合并PRD自动发现的附件。旧版无结构PRD继续核对原文中的ID。

严格交接的质量检查和自动追溯使用同一份已核验的正式输入。必查项目项没有覆盖时，tested 校验失败，transfer 保留具体缺口。

采用 test 验证的项目规则，其映射的已通过测试须通过 trace 的 AC 覆盖规则声明的每个 FR。只覆盖其他需求的测试会留下缺失的 FR 清单。

旧版 PRD 和人工转交也核对本地附件。没有正式输入快照时，沿主文和 Markdown 附件的本地引用逐项核对清单和摘要，是否附带自动化回执均适用。资料齐全的草案可以转交，外部网页链接保留为引用。

已确认 PRD 在无自动化回执、无显式冻结快照的严格人工转交中，主文的普通 HTTP(S) Markdown 参考链接可离线保留。SRC 声明中的来源、嵌入资源和项目规则证据依然按本地资料核验。

拆分主文和追踪文件时，使用现有冻结输入，传入 `--inputs <包内快照路径> --expected-inputs <发送方已冻结的原指纹>`。包可复制到新目录，保持包内相对目录结构、文件字节及原快照。接收端按相对路径用包内文件重建核验范围，核对原快照、文件摘要及引用闭包。发送端原路径无需可访问。改动后的包应由发送方重新冻结并传递新指纹。

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
