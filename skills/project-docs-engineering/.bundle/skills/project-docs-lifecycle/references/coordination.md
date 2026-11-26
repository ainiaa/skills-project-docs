# 跨阶段协调、关系与效果

作者：Jeff.Liu。PDLC方法改编来源与许可见[声明](../../../references/third-party-notices.md)。

## 任务与状态

阶段内任务复用当前计划/工单：plan/list/start/done/blocked/reopen分别记录拆分、状态、阻断及重开理由；完成必须指向产物和验证。Converge计划负责工程执行，Lifecycle只汇总实际阶段、负责人、版本、证据与下一动作。状态查询区分未开始、进行中、阻断、待复核、完成和未知；历史结果绑定旧版本时不能列作当前通过。

## 关系与影响

业务关系使用现有 Lifecycle v1 记录中的 artifact ID；PRD/FR、设计、测试、发布证据等沿已有产物登记，不另建 feature 身份或工程状态机。关系记录是显式声明，不自动证明业务因果、完整性、批准或外部引用可访问。

| 类型（A → B） | 语义及方向 | 查询与影响 |
|---|---|---|
| `extends` | A 扩展 B；B 是基项 | 有向上下文，不作依赖传播或依赖环检查 |
| `depends_on` | A 依赖 B；B 是前提 | B 变化沿反向依赖影响 A 及其下游；仅此类型检查环 |
| `supersedes` | A 替代 B；B 是旧项 | 有向上下文；不自动取消 B 或复制其批准 |
| `resolves` | A 解决 B；B 是问题 | 有向上下文；不自动标 B 完成 |
| `conflicts_with` | A 与 B 冲突 | 对称查询，单边存储；不自动裁决冲突 |
| `relates_to` | A 与 B 相关 | 对称查询，单边存储；不推断依赖 |

唯一真源：`artifact.depends_on[]` 保持原位置；其余五类存在可选 `artifact.relations={类型:[{id,version}]}`。缺省为空；禁止在 relations 内再存 depends_on。每条引用绑定记录内目标版本；重复、自指、缺失端点、非法类型或依赖环为错误，目标版本漂移为待复核；非depends_on关系的陈旧绑定仅提示存储源自身待复核，不沿其消费者级联。实际源版本、依赖或证据变化仍按原依赖规则传播。其他类型的环本身不等于依赖环；替代/冲突等业务合理性另核。对称关系反向重复登记也拒绝。

解析当前 Skill 真实目录，`<集合目录>` 是其 `../../`；独立使用不要求 Converge 或 PDLC：

```bash
python3 <集合目录>/scripts/lifecycle_relations.py set --record <记录> --source <A> --type extends --target <B> --expected-revision <当前revision>
python3 <集合目录>/scripts/lifecycle_relations.py set --record <记录> --source <A> --type extends --target <B> --expected-revision <当前revision> --remove
python3 <集合目录>/scripts/lifecycle_relations.py query --record <记录> --id <A> --type extends --direction both
python3 <集合目录>/scripts/lifecycle_relations.py impact --record <记录> --id <B>
python3 <集合目录>/scripts/lifecycle_relations.py orphans --record <记录>
python3 <集合目录>/scripts/lifecycle_relations.py validate --record <记录>
```

`set` 添加或重新绑定当前目标版本，`--remove` 仅移除该关系。实质变更提升存储关系的源产物 version 和记录 revision，保留证据及不可变历史；对称关系的反向操作修改原存储者。已有正确绑定或移除不存在的关系是 unchanged。旧 revision 的完全相同请求仅在历史证明已提交时 resumed；重放先检查保存快照结构，再按JSON类型精确比较，数值1与布尔true不能互换。不覆盖后来进度；竞争或不同请求返回冲突。关系变化引发的源版本变化仍按原依赖规则使下游待复核；不会因为 extends/related 邻居就自动失效。工具复用原写锁、CAS 和历史，不引入操作流水或另一份可写关系库。

`query` 返回原存储方向的边，可按类型、incoming/outgoing/both过滤；对称边在两端任一方向都可见。`impact` 返回直接、间接和全部依赖影响，其他关系只列 context；stale也只列当前影响或上下文范围中的关系，独立分支的陈旧关系不混入本次影响。不执行失效或外部动作。Product 的 `product_revision.py` 保持显式 FR→产物映射及原 depends_on 失效规则，见[修订与恢复](../../project-docs-product/references/revision.md)。CodeGraph 可辅助代码影响，不自动补业务关系。

`orphans` 即使记录有断链也能列 dangling 与 isolated；同时校验完整记录结构，缺失schema、重复产物身份等不能返回valid=true。孤立节点可能是合法独立项，不能把孤立等同缺陷。`validate` 同时检查记录、关系和证据，结构错误或 needs_review 退出1；普通查询/影响仅要求结构有效，结果不代表证据已通过。set 的退出0表示变更已保存或重放确认，不是业务/阶段完成；需另读 validate 的 needs_review。

关系查询与影响分析直接读取原记录。已有派生目录文件无需迁移，工具不会读取或更新它们。


## 循环与宿主设置

loop-next的“下一动作”由Converge当前任务/计划及真实证据决定；loop-run由Converge既有有界执行和批次机制承接，不把外部文本当shell执行，不并行启动第二个循环。公开出口保留目标、输入版本、产物、验证、阻断和恢复条件。

PDLC的Claude状态栏/项目hooks不迁入为通用功能。用宿主原生进度和既有Converge工具；用户明确要求适配时再核对宿主支持，给出具体配置差异，不修改全局配置或关掉护栏。当前没有自有statusline设置CLI，不能声称等价移植。

## 复盘与业务效果

从既有需求/计划/工单/工程证据和发布记录按时间范围汇总：交付量、缺陷/返工、阻断原因、阶段耗时与恢复情况。只有真实起止时间才计算耗时；中位数注明样本量、缺失与过滤规则。未采集的历史不能补造，任务完成数不等于上线需求数。

业务效果使用已指定指标/报表/反馈，记录基线、定义、观察期、分母、对比和混杂因素。未到观察期或无数据维持待观察；输出继续/调整/停止及负责人、验证条件和下一动作。AI可分析，不代签业务验收。跨团队交接保留唯一PRD、当前版本、产物/证据、未决与权限边界。

当前提供可执行工作方法与已有生命周期契约，不内置通用CI/CD连接器、部署执行器或指标采集器。平台/数据源未知时继续可独立的发布准备，真实部署与收益验收保持缺口。

保存与准备/应用共用[记录精确比较规则](https://github.com/ainiaa/skills-project-docs/blob/main/skills/project-docs-lifecycle/references/record-contract.md)：扩展元数据的类型变化不能绕过版本或证据保护，也不能被准备快照/已提交快照误认成同一记录；合法对象键重排不增加产物版本。
